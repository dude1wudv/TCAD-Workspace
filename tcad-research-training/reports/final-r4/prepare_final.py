"""Bind an accepted, immutable r4 delivery snapshot to new final manuscripts.

This program copies evidence and formats tables/text. It never imports a solver,
controller, audit session, prediction fitting routine or historical writer.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding='utf8')


def js(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def tex(value):
    result = str(value)
    for a, b in (('\\', '\\textbackslash{}'), ('&', '\\&'), ('%', '\\%'), ('_', '\\_'), ('#', '\\#')):
        result = result.replace(a, b)
    return result


def f(value, digits=4):
    return ('--' if value is None else f'{value:.{digits}f}')


def table(name, headers, rows, columns=None):
    body = '\\begin{tabular}{' + (columns or ('l' * len(headers))) + '}\n\\toprule\n'
    body += ' & '.join(headers) + '\\\\\n\\midrule\n'
    body += '\n'.join(' & '.join(str(x) for x in row) + '\\\\' for row in rows)
    body += '\n\\bottomrule\n\\end{tabular}\n'
    write(HERE / 'tables' / (name + '.tex'), body)


def figure(name, caption, label, width='.95'):
    return '\n\\begin{figure}[htbp]\n\\centering\n\\includegraphics[width=' + width + '\\textwidth]{' + name + '}\n\\caption{' + caption + '}\n\\label{' + label + '}\n\\end{figure}\n'


def float_table(name, caption, label, small='small'):
    return '\n\\begin{table}[htbp]\n\\centering\\' + small + '\n\\caption{' + caption + '}\n\\label{' + label + '}\n\\input{tables/' + name + '.tex}\n\\end{table}\n'


def bind(snapshot, native_review, plot_review=None):
    snapshot = Path(snapshot).resolve()
    expected = ROOT / 'experiments/dram-see-v3/r50-main/data/delivery-r4'
    if not snapshot.is_relative_to(expected):
        raise ValueError('Only a new accepted real r4 delivery snapshot is permitted')
    manifest = read(snapshot / 'snapshot-manifest.json')
    if manifest.get('synthetic_fixture') is not False or manifest.get('new_solver_calls') != 0:
        raise ValueError('Require real read-only delivery output')
    for name, digest in manifest['files_sha256'].items():
        path = (snapshot / name).resolve()
        if not path.is_relative_to(snapshot) or sha(path) != digest:
            raise ValueError('Snapshot file missing or changed: ' + name)
    summary = read(snapshot / 'summary.json')
    if summary['measured_main_responses'] != 128 or not summary['simulation_evidence_verified']:
        raise ValueError('Complete 128 raw-reviewed main responses required')
    if summary['planned_independent_events'] != 64 or len(summary['aliases']) != 4:
        raise ValueError('Independent sample or alias inventory changed')
    if summary['native_evidence']['state'] != 'VERIFIED':
        raise ValueError('Actual native inspection required')
    target = HERE / 'data/snapshot'
    if target.exists():
        old = read(HERE / 'data/snapshot-binding.json')
        if old['source_manifest_sha256'] != sha(snapshot / 'snapshot-manifest.json'):
            raise ValueError('Refuse to replace already-bound final evidence')
    else:
        shutil.copytree(snapshot, target)
    for name, digest in manifest['files_sha256'].items():
        if sha(target / name) != digest:
            raise ValueError('Local final evidence copy changed: ' + name)
    native_review = Path(native_review).resolve()
    if sha(native_review) != '8678e261287a28c882082918e1cdc214fd232c25788fc8dd48b94fa60d9bab2f':
        raise ValueError('Use the specified root actual native image review')
    shutil.copy2(native_review, HERE / 'data/native-visual-review.json')
    sources = {str(snapshot.relative_to(ROOT) / name): digest for name, digest in manifest['files_sha256'].items()}
    sources[str(snapshot.relative_to(ROOT) / 'snapshot-manifest.json')] = sha(snapshot / 'snapshot-manifest.json')
    sources[str(native_review.relative_to(ROOT))] = sha(native_review)
    if plot_review:
        plot_review = Path(plot_review).resolve()
        shutil.copy2(plot_review, HERE / 'data/data-plot-visual-review.json')
        sources[str(plot_review.relative_to(ROOT))] = sha(plot_review)
    root_review = ROOT / 'local_runtime/dram-see-v3/downstream-r4-completion/20261012T0020Z/delivery-root-acceptance.json'
    if sha(root_review) != 'e306c743baf297251d9de9d31c470c85cb4f1d3f81ccab067d941833b24a2856':
        raise ValueError('Require specified external final snapshot acceptance')
    shutil.copy2(root_review, HERE / 'data/delivery-root-acceptance.json')
    sources[root_review.relative_to(ROOT).as_posix()] = sha(root_review)
    for i, item in enumerate(summary['native_evidence']['targets']):
        # Root observed the source export's clipped unit suffix; present only the
        # unchanged complete owned-window image and keep both original files.
        file = item['files']['own-window.png']
        path = ROOT / file['path']
        if sha(path) != file['sha256']:
            raise ValueError('Root-reviewed native window changed')
        name = 'native-physical-window.png' if 'physical-' in item['ledger_tag'] else 'native-event-window.png'
        shutil.copy2(path, HERE / 'figures' / name)
        sources[file['path']] = file['sha256']
    plots = read(target / 'figure-review-required.json')['figures']
    for item in plots['created']:
        for asset in item['files']:
            if asset['file'].endswith('.png'):
                shutil.copy2(target / 'figures' / asset['file'], HERE / 'figures' / asset['file'])
    model_path = ROOT / 'experiments/dram-see-v3/r50-main/data/predictions/models.json'
    expected_model_sha = summary['source_files_sha256'][model_path.relative_to(ROOT).as_posix()]
    if sha(model_path) != expected_model_sha:
        raise ValueError('Frozen models changed; do not refit')
    shutil.copy2(model_path, HERE / 'data/frozen-models.json')
    sources[model_path.relative_to(ROOT).as_posix()] = expected_model_sha
    js(HERE / 'data/snapshot-binding.json', {'schema': 'dram-see-v3-final-r4-writing-binding',
        'snapshot': str(snapshot), 'source_manifest_sha256': sha(snapshot / 'snapshot-manifest.json'),
        'summary_sha256': sha(snapshot / 'summary.json'), 'native_review_sha256': sha(native_review),
        'plot_review_path': str(plot_review) if plot_review else None,
        'bound_utc': datetime.now(timezone.utc).isoformat(), 'new_solver_calls': 0,
        'source_files_sha256': sources, 'human_course_activities_claimed': False})
    js(HERE / 'sources.json', {'schema': 'dram-see-v3-final-r4-writing-sources',
        'sources': sources, 'historical_reuse': read(HERE / 'qa/reused-history-source-hashes.json'),
        'snapshot_is_complete_simulation_evidence': True, 'human_course_completion': False})
    with (HERE / 'evidence-index.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['path', 'sha256'])
        writer.writeheader()
        writer.writerows({'path': k, 'sha256': v} for k, v in sources.items())
    return summary, read(model_path)


def prepare(s, models):
    d = s['design']; responses = s['responses']; scores = s['final_numerical_prediction_scores']['scores']
    instant = datetime.fromisoformat(s['generated_utc'].replace('Z', '+00:00'))
    date = instant.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + ' UTC'
    write(HERE / 'tables/snapshot.tex', '\\newcommand{\\EvidenceDate}{' + date + '}\n')
    table('progress', ['集合', '独立事件', '配对响应', '已验证', '缺失'], [
        ['训练0.18/0.35 $\\mu$m', 32, 64, 64, 0], ['域内0.25 $\\mu$m', 16, 32, 32, 0],
        ['外推0.45 $\\mu$m', 16, 32, 32, 0]], 'lrrrr')
    names = {'correct': '正确', 'criterion_error': '判据误读', 'critical': '临界', 'numerically_uncertain': '数值不确定', 'failed': '失败', 'missing': '缺失'}
    counts = []
    threshold_counts = {}
    for t in d['thresholds_mV']:
        c = Counter(row['effective_classification'].get(str(t), row['status']) for row in responses)
        threshold_counts[str(t)] = dict(c)
        counts.append([f'{t:g}'] + [c.get(k, 0) for k in names])
    table('thresholds', ['阈值/mV'] + list(names.values()), counts, 'rrrrrrr')
    rows = []
    for length in (.18, .25, .35, .45):
        for particle in ('alpha', 'proton'):
            for bit in (0, 1):
                items = [r for r in responses if r['gate_length_um'] == length and r['particle'] == particle and r['stored_bit'] == bit]
                rows.append([f(length, 2), '$\\alpha$' if particle == 'alpha' else '质子', bit,
                             f(min(r['deltaQ_fC'] for r in items), 3) + '至' + f(max(r['deltaQ_fC'] for r in items), 3),
                             f(min(r['deltaM_mV'] for r in items), 3) + '至' + f(max(r['deltaM_mV'] for r in items), 3),
                             f(min(r['M_mV'] for r in items), 3) + '至' + f(max(r['M_mV'] for r in items), 3)])
    table('response-ranges', ['$L$/\\,$\\mu$m', '粒子', '位', '$\\Delta Q$/fC', '$\\Delta M$/mV', '$M$/mV'], rows, 'lclrrr')
    cv = []
    for key, model in models['models'].items():
        cv.append([model['stored_bit'], '$\\Delta Q$/fC' if model['target'] == 'deltaQ_fC' else '$\\Delta M$/mV',
                   model['selected_alpha'], f(next(r['mean_fold_rmse'] for r in model['cv_alpha_scores'] if r['alpha'] == model['selected_alpha']), 6),
                   f(model['training_mean']['cv_mean_fold_rmse'], 6)])
    table('training-cv', ['位', '目标', '$\\lambda$', '岭回归RMSE', '均值基准RMSE'], cv, 'llrrr')
    for target, name in (('deltaQ_fC', 'prediction-dq'), ('deltaM_mV', 'prediction-dm')):
        rows = [[('留出' if row['split'] == 'holdout' else '外推'), row['stored_bit'],
                 ('岭回归' if row['model'] == 'ridge' else '均值基准'), row['valid_n'], row['missing_n'], row['invalid_or_failed_n'],
                 f(row['MAE'], 6), f(row['RMSE'], 6), f(row['max_absolute_error'], 6)] for row in scores if row['target'] == target]
        table(name, ['集合', '位', '模型', '$n$', '缺失', '无效', 'MAE', 'RMSE', '最大误差'], rows, 'lllrrrrrr')
    oxide_rows = [[('$\\alpha$' if r['event']['particle'] == 'alpha' else '质子'), r['stored_bit'], f(r['oxide_nm'], 0),
                   f(r['differences_from_5nm']['deltaQ_fC'], 5), f(r['differences_from_5nm']['deltaM_V']*1000, 5),
                   f(r['observation']['metrics']['M4_V']*1000, 4)] for r in s['oxide']['responses']]
    table('oxide', ['粒子', '位', '$t_{ox}$/nm', '$\\delta(\\Delta Q)$/fC', '$\\delta(\\Delta M)$/mV', '$M$/mV'], oxide_rows, 'llrrrr')
    boundary_rows = []
    for r in s['numerical_boundary']['comparisons']:
        v = r['variation']; uncertain = ','.join(f'{t*1000:g}' for t in r['numerically_uncertain_thresholds_V']) or '无'
        boundary_rows.append([f"{r['event']['seed']}/b{r['stored_bit']}", '半步长' if v['step'] == .5 else '0.7网格',
                              f(max(abs(x) for x in r['differences_V'].values())*1000, 6), f(abs(r['deltaQ_difference_fC']), 6),
                              '通过' if r['continuous_passed'] else '失败', uncertain])
    table('boundary', ['事件/位', '变体', '最大电压变化/mV', '$|\\delta\\Delta Q|$/fC', '连续门槛', '不确阈值/mV'], boundary_rows, 'llrrll')
    status = Counter(v['classification_refinement_status'] for row in s['numerical_boundary']['main_threshold_status'] for v in row['thresholds'].values())
    status_labels = {'CONFIRMED_STABLE': '细化稳定', 'CROSSING': '分类跨界', 'FAILED_CONTINUOUS': '连续失败',
                     'PENDING_NEAR_BOUNDARY': '近界待确认', 'OUTSIDE_BAND_UNREFINED': '界外未细化'}
    table('numerical-status', ['阈值响应对状态', '数量/384'], [[status_labels[k], status.get(k, 0)] for k in status_labels], 'lr')
    alias_rows = []
    for canonical, actual in s['aliases'].items():
        original = s['ledger_snapshot']['runs'][canonical]
        alias_rows.append([canonical.split('-s')[-1], actual.split('-main-')[1].split('-l')[0], original['state'],
                           'null（未观测）' if original.get('runner_exit_code') is None else original['runner_exit_code']])
    table('failed-aliases', ['原seed/位', '有效重试版本', '原状态', '原runner退出码'], alias_rows, 'llll')
    table('provenance-short', ['证据类别', '本包入口'], [
        ['完整128槽及数值状态', '\\sourcepath{data/snapshot/responses.csv}'],
        ['真实case owner与四alias', '\\sourcepath{data/snapshot/response-sources.json}'],
        ['原FAILED和费用', '\\sourcepath{data/snapshot/ledger-snapshot.json}'],
        ['原r4固定模型评分', '\\sourcepath{data/snapshot/original-r4-prediction-scores.json}'],
        ['最终数值证据评分', '\\sourcepath{data/snapshot/final-numerical-prediction-scores.json}'],
        ['原生PNG真实目视', '\\sourcepath{data/native-visual-review.json}'],
        ['全部来源与哈希', '\\sourcepath{sources.json}']], 'lp{0.62\\textwidth}')
    main = s['main_threshold_counts']
    summary_sentence = f"在5~mV主阈值下，128个响应中{main['correct']}项正确、{main['criterion_error']}项判据误读、{main['critical']}项临界、{main['numerically_uncertain']}项数值不确定，失败和缺失各为{main['failed']}与{main['missing']}项。"
    score_sentence = []
    for split in ('holdout', 'extrapolation'):
        values = [r for r in scores if r['split'] == split and r['model'] == 'ridge']
        dq = [r for r in values if r['target'] == 'deltaQ_fC']; dm = [r for r in values if r['target'] == 'deltaM_mV']
        score_sentence.append(('域内留出' if split == 'holdout' else '尺寸外推') + '的存储0/1岭回归RMSE分别为' + '/'.join(f(r['RMSE'], 6) for r in dq) + '~fC（电荷）和' + '/'.join(f(r['RMSE'], 6) for r in dm) + '~mV（裕量损失）。')
    score_sentence = ''.join(score_sentence)
    base_abstract = '基于未校准二维平面访问管与理想电容组成的1T1C模型，建立受约束自然语言输入、Geant4电离沉积到TCAD等效源传递、匹配中性参考及测试前预测冻结的评估流程。统一50~$\\Omega$预充版本完成四栅长、两粒子、两个方向下64个独立事件和128个0/1配对响应；训练64响应，域内留出与外推各32响应。' + summary_sentence + score_sentence + '14项氧化层case与预定两目标的匹配边界细化通过连续门槛，分类跨界和未选近界状态仍保留数值不确定。工程失败、未知退出码与四项确定性重试全部保全，重试和扩展不增加独立事件数。结论限于固定硅入口、二维等效源、受控准静态初态及所选电磁输运配置；不推断持久位翻转、商业DRAM可靠性或辐射截面。'
    write(HERE / 'sections/course/abstract.tex', base_abstract + '\n')
    write(HERE / 'sections/paper/abstract.tex', base_abstract + '\n')
    same_score = s['original_r4_prediction_scores'] == s['final_numerical_prediction_scores']
    score_compare = '本次原r4评分与最终连续有效性评分逐项一致。' if same_score else '最终数值证据改变了有效可评分集合，原r4评分和最终评分分别保留，差异可从两份完整JSON逐项核对。'
    results = '\\section{全量响应、预测与扩展结果}\n\\label{cr:results}\n\\subsection{封存快照与样本完成度}\n'
    results += '本次证据截止为\\EvidenceDate。完整训练和测试均经原档重审，未读取在途或原FAILED电学输出。四alias仅提供其原逻辑槽，来源含实际run、owner plan、case-freeze与输入/归档SHA。\n'
    results += '快照内部分图件状态保留采集时的PENDING标签，未回写历史快照；后续完整机器、统计和逐图目视验收另见\\sourcepath{data/delivery-root-acceptance.json}及两份visual-review记录。本文将采集时状态与事后验收证书分开引用。\n'
    results += float_table('progress', '完整主矩阵的样本与响应分配；同事件两位不独立翻倍。', 'cr:progress')
    results += '\\subsection{匹配参考与预充修订的历史依据}\n历史D1无粒子诊断中，固定理想参考留下约12.37~mV读出偏移；同一信号状态改用匹配中性参考后，差分从+2.454961~mV变为-9.915036~mV。该诊断说明参考会改变判据解释，不纳入R50主矩阵。原100~$\\Omega$固定事件的3~ns预充误差为-13.297362~$\\mu$V，超过10~$\\mu$V原门槛；独立50~$\\Omega$ probe对应误差为-4.731204~$\\mu$V，随后才建立独立统一主版本。\n'
    results += figure('d1-reference-comparison.pdf', '历史D1参考诊断，仅用于解释方法演进；原始分类不追溯替换。', 'cr:d1', '.85')
    results += figure('r50-precharge.pdf', '历史100~$\\Omega$失败与独立50~$\\Omega$ probe。两者均不作为新的R50主事件。', 'cr:precharge', '.85')
    results += '\\subsection{完整128响应与三阈值统计}\n' + summary_sentence + '\n每个尺寸/粒子/方向/位值分层的预定N保持4，零次明确误读不能推出总体风险为零。表中有效分类已传播近界和细化跨界不确定性，原分类另见完整响应CSV。\n'
    results += float_table('thresholds', '完整128响应在三阈值下的有效状态；失败与缺失不计为正确。', 'cr:thresholds')
    results += float_table('response-ranges', '按栅长、粒子、位值列出的连续响应范围；每行合并两方向共8响应，未额外增加独立样本。', 'cr:ranges', 'footnotesize')
    results += figure('readout-l018.png', '0.18~$\\mu$m的全部事件、同位control与neutral读出曲线；数据来自统一R50快照。', 'cr:readout')
    results += figure('threshold-window-l045.png', '0.45~$\\mu$m外推集合在3.8至4~ns的读出裕量窗口；线条和阈值均来自封存快照。', 'cr:window')
    results += '\\subsection{原冻结模型的独立留出与外推}\n四模型由训练工况LOCO选择，冻结后不再调参。'
    results += float_table('training-cv', '八个物理工况折RMSE的算术平均；仅用于训练阶段模型选择。', 'cr:cv')
    results += score_sentence + score_compare + '\n分类临界或跨界与连续量有效性分别处理；原r4首次评分的原字节副本与最终数值评分均附在证据包。\n'
    results += float_table('prediction-dq', '$\\Delta Q$的固定预测误差，单位fC。每模型/位/集合计划16响应；缺失和无效显式报告。', 'cr:scoreq', 'footnotesize')
    results += float_table('prediction-dm', '$\\Delta M$的固定预测误差，单位mV。测试没有反向参与选模。', 'cr:scorem', 'footnotesize')
    results += figure('prediction-residuals.png', '冻结预测减去实际观测的留出/外推残差；训练均值与岭回归均保留。', 'cr:residuals')
    results += '\\subsection{氧化层敏感性}\n在0.25~$\\mu$m、垂直入射的固定alpha/质子首个事件上，4/6~nm厚度各建立独立0/1对照、中性参考和事件响应，共14个case。5~nm复用对应四个主响应；含原质子bit0的r3有效alias。每个新厚度实际重建网格，事件三文件字节保持一致。\n'
    results += float_table('oxide', '相对于对应5~nm响应的氧化层变化；$\\delta(\\Delta Q)$和$\\delta(\\Delta M)$是新厚度减5~nm。', 'cr:oxide', 'footnotesize')
    results += figure('oxide-sensitivity.png', '4/5/6~nm在固定硅入口事件下的TCAD敏感性；不表示变化材料栈的Geant4输运。', 'cr:oxidefig')
    results += '八个新事件响应相对于5~nm的最大绝对变化为0.112560497~mV（裕量损失）和约0.005783687~fC（电荷），分类保持。这些幅度小于预定验收容差0.5~mV和0.01~fC；容差不是统计误差条或已估计的分辨率。每个氧化层响应未再做独立细化和统计校准，故只报告固定入口事件下幅度较小的受控敏感性，不主张零效应、微小效应已可靠分辨或统计显著性。\n'
    results += '\\subsection{完整矩阵边界细化与原生图}\n边界目标由完整128响应到$\\pm2.5/5/10$~mV的最小距离排序选取，保持原规则和目标。每目标分别使用半步长与0.7网格的匹配control/neutral/event。四项连续比较均通过，但连续通过不代表类别稳定；5~mV跨界及未选近界响应继续保留不确定性。\n'
    results += float_table('boundary', '四个边界比较。最大电压变化包含规定的两侧BL与派生读出量；容差0.5~mV和0.01~fC。', 'cr:boundary', 'footnotesize')
    results += float_table('numerical-status', '128响应乘三阈值的384个状态。界外未细化不冒称全部网格独立。', 'cr:uncertainty')
    results += figure('native-physical-window.png', '真实SVisual owned窗口：0.18~$\\mu$m存储1物理参考，4~ns，Abs(ElectricField-V)，V/cm。完整窗口原字节保留并经主代理逐图目视。', 'cr:nativephysical')
    results += figure('native-event-window.png', '真实SVisual owned窗口：0.18~$\\mu$m、alpha、30°、seed202610311、bit1，4~ns。所示为原窗口，不是数据后处理绘图。', 'cr:nativeevent')
    results += '对应1400×1000原生导出右端图例单位后缀存在裁切，已保留并如实记录；本文只展示同组完整owned窗口。真实窗口证明声明的run/变量/时刻，不证明通过Workbench Run按钮调度。\n\\subsection{失败保全与完整费用}\n'
    results += float_table('failed-aliases', '四个主线原始工程FAILED及其有效alias。null表示原始退出码未观测，不补写为0。', 'cr:failures')
    results += '完整历史账本共有7条FAILED记录；表中四项仅是R50主矩阵对应的确定性重试别名。最终逻辑槽失败为0，不表示历史失败为0，全部7条仍在原账本和快照中保留。\n'
    results += f"唯一全局账本已结算{f(s['budget']['accounted_solver_s'],2)}~s，约{f(s['budget']['accounted_solver_s']/3600,3)}~h；含原版本、probe、失败、重试与扩展。当前授权无上限，未结{len(s['budget']['running_or_unsettled'])}项、费用缺项{len(s['budget']['accounting_gaps'])}项。该累计求解成本不是学生投入时长或AI效率对照。\n\\FloatBarrier\n"
    write(HERE / 'sections/course/05-results.tex', results)
    conclusion = '\\section{结论与后续工作}\n' + summary_sentence + score_sentence + '\n本次完成了限定自然语言映射、真实事件到器件源项传递、匹配参考定义、统一主矩阵、预测前冻结、独立留出/外推评分与受控扩展的一致证据链。原科学门槛、样本分母和全部失败保持不变。边界验证显示连续量稳定与分类稳定需要分别报告，不能以一次连续门槛通过清除全部数值不确定。\n\n下一步器件研究需用具有出处的工艺和电学数据校准结构、实际写入、保持、感放及恢复，扩展能量、位置与统计规模。课程方面已形成可编辑报告、研究稿、PPT与只读演示材料；真实学生贡献、教师审核、试讲、答辩和考核由参与者完成并据实留证。\n'
    write(HERE / 'sections/course/07-conclusion.tex', conclusion)
    # The research paper uses the same generated factual tables while keeping a
    # concise scientific narrative; references to course chapter labels are removed.
    paper_results = results[results.index('\\subsection{完整128响应与三阈值统计}'):]
    paper_results = '\\section{全矩阵响应与敏感性结果}\n' + paper_results
    paper_results = paper_results.replace('cr:', 'paper:')
    write(HERE / 'sections/paper/04-results.tex', paper_results)
    discussion = r'''\section{预测方法与适用性讨论}
分别对存储0/1的$\Delta Q$和$\Delta M$建立四个岭回归器，特征为
\begin{equation}\mathbf x=(Q_{\rm dep},Q_{\rm dep}/L,Q_{\rm dep}\sin\theta).\end{equation}
八个物理工况留一交叉验证中，每组四次重复及配对位保持同组，标准化仅使用该折训练数据。
候选正则化系数为0、0.01、0.1、1、10，最终参数在测试TCAD首次提交前冻结。
模型是给定Geant4沉积与基线后的条件TCAD响应代理，不代替任意粒子输运。

全量测试扩大了已评价的尺寸范围，却没有校准真实工艺或增加能量、位置、材料栈覆盖。
相同简化模型可能具有共同系统误差，这些误差不会因为训练或测试残差小而消失。
已报告误差须与基准和最差误差一起阅读，不能仅择优列出某个位值或粒子。
低维特征关联不能唯一证明微观收集机制。

存储状态由理想钳位和准静态初态建立，未验证真实写入能力；二维1T1C、固定集总电容和
总量等效直径迹不代表真实立体存储器及三维敏感体积。所选电磁option4的质子结果不包含已验证的
核反应次级粒子效应。4/6 nm结果只是固定硅入口事件下TCAD敏感性，不是完整材料栈输运重算。

连续门槛、判据分类和持久位翻转是不同对象。采样时刻的临界与跨界不能自动解释为商业SEU，
每层N=4也不能支持高精度稀有失效概率。数值细化通过的响应和界外未细化的响应均在完整状态表中区分。
确定性工程重试保留原失败及未知退出码，只恢复原逻辑槽。

AI协助脚本、核验和文稿，固定程序执行数值过程。本研究未设置人工操作对照，因此没有AI加速率结论。
学生与教师活动不是本文软件证据的推论，课程实际审核和答辩保留待完成。
'''
    write(HERE / 'sections/paper/05-prediction-discussion.tex', discussion)
    write(HERE / 'sections/paper/06-conclusion.tex', conclusion.replace('\\section{结论与后续工作}', '\\section{结论}'))
    js(HERE / 'data/writing-results.json', {'summary_sentence': summary_sentence, 'score_sentence': score_sentence,
        'threshold_counts': threshold_counts, 'main_threshold_counts': main, 'numerical_status_counts': dict(status),
        'scores_unchanged_after_numerical_review': same_score, 'snapshot_generated_utc': s['generated_utc'],
        'global_solver_s': s['budget']['accounted_solver_s'], 'core_slide_count': 12, 'backup_slide_count': 4})
    for name in ('feasibility.md', 'design-and-steps.md', 'methods-and-ai.md', 'demonstration.md', 'defense-outline.md', 'handoff.md'):
        content = (HERE / 'data/snapshot/materials' / name).read_text(encoding='utf8')
        content = content.replace('../', '../data/snapshot/')
        if name == 'handoff.md':
            content += '\n\n本次完整文稿与PPT位于本包上层目录；代理课程材料索引见[index.md](index.md)。外部最终数据验收见[delivery-root-acceptance.json](../data/delivery-root-acceptance.json)，快照内采集时PENDING标签保留未改。\n'
        write(HERE / 'materials' / name, content)
    js(HERE / 'data/preparation-result.json', {'state': 'COMPLETE_SNAPSHOT_BOUND_TEXT_AND_TABLES_GENERATED',
        'generated_utc': datetime.now(timezone.utc).isoformat(), 'main_responses': 128, 'independent_events': 64,
        'no_fitting_or_solver_calls': True, 'visual_document_review': 'PENDING_AFTER_COMPILATION'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--native-review', required=True, type=Path)
    parser.add_argument('--plot-review', type=Path)
    args = parser.parse_args()
    summary, models = bind(args.snapshot, args.native_review, args.plot_review)
    prepare(summary, models)
    print(json.dumps({'state': 'BOUND_AND_FORMATTED', 'response_count': len(summary['responses']),
                      'snapshot': str(args.snapshot), 'output': str(HERE)}, ensure_ascii=False))
