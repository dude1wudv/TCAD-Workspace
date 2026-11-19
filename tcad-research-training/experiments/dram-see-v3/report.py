"""Generate an evidence-linked stage report and course-material draft index."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _module(name):
    path = HERE / (name + '.py')
    spec = importlib.util.spec_from_file_location('_v3_report_' + name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


def _safe(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _relative(path, base):
    import os
    return Path(os.path.relpath(path, base)).as_posix()


def _table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
                     + ['| ' + ' | '.join(_safe(value) for value in row) + ' |' for row in rows])


def parameter_rows():
    return [
        ['gate_length', '0.18/0.25/0.35/0.45', 'um', 'plan.md frozen matrix', 'Exploratory planar access NMOS; not process-node calibration'],
        ['oxide_nominal', '5', 'nm', 'v1 inherited geometry; plan.md', 'Uncalibrated geometry assumption'],
        ['oxide_extension', '4/5/6 at L=0.25', 'nm', 'plan.md controlled +/-20%', 'Same silicon-entry events; new thickness requires own mesh/control/neutral'],
        ['stored_SN_target', '0.1 / 0.9', 'V', 'v2 controlled initialization, v3 plan', 'Ideal clamp; not actual transistor write calibration'],
        ['neutral_SN_target', '0.5', 'V', 'v3 plan and D1 diagnostic context', 'Full matched cell curve; no scalar offset subtraction'],
        ['storage_capacitance', '10', 'fF', 'Inherited v2 uncalibrated circuit', 'Signal and neutral cells identical'],
        ['bitline_capacitance', '100', 'fF', 'Inherited v2 uncalibrated circuit', 'Signal and reference bitlines identical'],
        ['particles_energy', 'alpha/proton, 5', 'MeV', 'v3 frozen event design / validated G4 files', 'Equivalent track in silicon/vacuum; no full oxide transport stack'],
        ['directions', '0/30', 'deg', 'Frozen coordinate and entry contract', '(-sin(theta),cos(theta),0); finite silicon exit'],
        ['readout_thresholds', '2.5/5/10', 'mV', 'Retained v2 thresholds, v3 main5mV', 'Criterion error, critical and numerical uncertainty are distinct'],
        ['source_conversion', '3.6', 'eV/pair', 'Frozen Geant4-to-TCAD conversion', 'LET=Qdep/track, normalization factor1; actual integral audit'],
        ['solver_budget', '86400', 's', 'v3 plan and frozen execution budget', 'Cumulative new solver effort including failure/validation; no kill of normal solve'],
    ]


def native_lines(summary, base):
    native = summary.get('native_evidence', {})
    captured = [row for row in native.get('captures', []) if row.get('state') == 'CAPTURED_PENDING_VISUAL_REVIEW']
    lines = ['原生场图和真实SVisual窗口截图与DATA PLOT分开保存。原始归档、4 ns信号TDR及本地取证文件已核对哈希，只证明来源一致；色标、单位和所选run的视觉审查仍单独待完成。'
             if captured else '尚无已绑定原始归档/TDR的原生导出与真实SVisual窗口截图；保持待完成。']
    for row in captured:
        link = lambda key: _relative(ROOT / row[key], base)
        lines += [f"- `{row['run_id']}` / `{row['ledger_tag']}`；预声明目标：{'是' if row['predeclared_target'] else '否（补充取证）'}；状态：`{row['state']}`。"
                  f" [原生导出]({link('native_export')})；[真实窗口截图]({link('screenshot')})；[取证JSON]({link('evidence_file')})。",
                  f"  条件：L={row['condition']['gate_length_um']} um，bit={row['condition'].get('stored_bit')}，oxide={row['condition'].get('oxide_nm')} nm；"
                  f"场量 `{row['field']}` ({row['field_units']})，坐标 {row['coordinate_units']}。"
                  f"原档 SHA-256：`{row['archive_sha256']}`；TDR SHA-256：`{row['tdr_sha256']}`。范围：{row.get('scope')} "
                  f"视觉审查：{row.get('visual_review_status')}。"]
    pending = native.get('pending_targets', [])
    if pending:
        lines.append('未取得完整取证的预声明目标：' + '、'.join('`' + tag + '`' for tag in pending) + '。')
    return lines


def render(summary, snapshot, figures=None, link_base=None):
    snapshot = Path(snapshot)
    fixture = summary.get('synthetic_fixture', False)
    counts, budget = summary['main_threshold_counts'], summary['budget']
    prefix = '【合成测试专用，非物理结果】\n\n' if fixture else ''
    rows = [[name, counts[name]] for name in ('correct', 'criterion_error', 'critical', 'numerically_uncertain', 'failed', 'missing')]
    stages = [[name, value.get('state', '未登记'), value.get('continuous_passed', '—'), value.get('classification_stable', '—')]
              for name, value in summary['stages'].items()]
    data_link = _relative(snapshot, Path(link_base) if link_base else HERE)
    lines = [prefix + '# DRAM SEE v3 阶段性结果',
             f"快照时间（UTC）：`{summary['generated_utc']}`。本报告来自冻结设计、已结束运行的原始归档及匹配曲线重新审计。运行中输出不参与统计。",
             f"固定主矩阵为 **64 个独立事件、128 个 0/1 配对响应**。当前获得匹配指标的响应为 **{summary['measured_main_responses']}/128**；至少一位有指标的事件为 {summary['events_with_any_measured_response']}/64，两位都有指标的事件为 {summary['events_with_both_measured_responses']}/64。数值复跑、配对位和氧化层变体不增加独立事件数。",
             '## 当前状态与完整分母',
             '以下主阈值为 ±5 mV。已计算的分类仍需结合阶段门槛；`validation_pending` 保存在逐响应 CSV，不能把待完成参考验证写成最终科学有效。',
             _table(['类别', '响应数（计划128）'], rows),
             f"累计已登记的新求解预算：{budget['accounted_solver_s']:.2f} / {budget['planned_budget_s']} s（{budget['accounted_solver_s']/3600:.3f} h）。继承归档计为0；运行中或未结运行的最终耗时尚未结算：{len(budget['running_or_unsettled'])} 项。",
             _table(['阶段', '工程/审计状态', '连续容差通过', '分类稳定'], stages) if stages else '尚无阶段整体通过记录。单个旧基准的复核不代表新版参考验证已经完成。',
             '## 指标、初态与参考',
             '`deltaQ = Cstore × (SNevent − SNcontrol)` 在2.8 ns取样并保留符号；`D=BLsignal−BLneutral`；`M=(2b−1)D(4 ns)`；`deltaM=Mcontrol−Mevent`。单位分别为fC、mV。0.1/0.9 V是理想钳位初态，不是访问管实际写入校准。',
             f"已重新审计 {len(summary['audited_runs'])} 个归档。初态表见 [initial-state.csv]({data_link}/initial-state.csv)。参考采用同条件完整中性单元曲线；物理双支路源隔离和匹配电压需要各自的真实验证记录。",
             '## 按计划分层的计数与区间',
             '每个尺寸×粒子×方向×存储位×阈值计划N=4。failed、missing、critical及数值不确定都进入最佳—最差范围，未隐含视作正确。Wilson双侧95%区间采用冻结分母及未决赋值包络。仅四项全部可判且零误读时，单侧95%上界约52.7%；区间是描述性结果，不保证多重比较同时覆盖。',
             f"全部96层见 [statistics.csv]({data_link}/statistics.csv)，所有128槽位见 [responses.csv]({data_link}/responses.csv)。原始分类与数值不确定后的分类均保留。",
             '## 预测与真实验证',
             ('模型与逐事件预测已在测试提交前冻结；现有真实测试计分见下表。训练、留出和外推仍按事件分组，不用测试结果调参。' if summary.get('prediction_scores') else
              '尚无可报告的真实测试计分。本报告不填充拟合优度、残差或预测成功率；模型/预测冻结及真实测试状态以对应证据为准。'),
    ]
    reference = summary.get('reference_validation', {})
    if reference:
        lines.insert(lines.index('## 按计划分层的计数与区间'), _table(['复核门槛', '原档重算通过/计划', '已结束物理分支', '证据状态'],
            [[name, f"{row['passed_comparisons']}/{row['planned_comparisons']}", row['completed_physical_runs'], row['state']]
             for name, row in reference.items()]))
    scoring = summary.get('prediction_scores')
    if scoring:
        lines.append(_table(['划分', '位', '目标', '模型', '有效/计划', 'MAE', 'RMSE', '最大绝对误差'],
            [[row['split'], row['stored_bit'], row['target'], row['model'], f"{row['valid_n']}/{row['planned_n']}",
              '—' if row['MAE'] is None else f"{row['MAE']:.6g}", '—' if row['RMSE'] is None else f"{row['RMSE']:.6g}",
              '—' if row['max_absolute_error'] is None else f"{row['max_absolute_error']:.6g}"] for row in scoring['scores']]))
        lines.append('误差仅针对表中有效连续观测；缺失/失败数另列CSV。若岭模型未优于训练均值，应按表如实报告，不重新选择测试样本。')
    lines += ['## 数值与氧化层检查',
              f"已保存完整数值比较报告 {len(summary.get('numerical_reports', []))} 份。近边界未复验与确认跨类均按阈值标记数值不确定；连续容差失败独立记录，不能靠放宽阈值或换事件消除。",
              (f"氧化层证据含 {len(summary['oxide'].get('responses', []))} 个新增厚度响应；4/5/6 nm比较固定原硅入口事件，新增独立事件数为0。" if summary.get('oxide') else
               '氧化层敏感性尚无完整结果；4/5/6 nm是预登记假设，不能写成已验证的真实工艺规律。'),
              '## 图件与证据类型',
              '下列PNG/SVG由真实数值生成并标为DATA PLOT。它们不代替Sentaurus Visual原生导出或真实桌面截图；原生软件取证须单独保存来源run ID和哈希，未提供时保持待完成。']
    if figures:
        for row in figures['created']:
            png = next(value['file'] for value in row['files'] if value['file'].endswith('.png'))
            lines.append(f"![{row['name']}]({data_link}/figures/{png})\n\n{row['description']} 来源：[哈希与run索引]({data_link}/figures/{row['sources']})。")
        if figures['skipped']:
            lines.append('未生成图件（没有补造数据）：\n\n' + '\n'.join('- ' + row['plot'] + '：' + row['reason'] for row in figures['skipped']))
    else:
        lines.append('此快照尚未生成DATA PLOT。')
    lines += ['### 原生场图与真实窗口证据', *native_lines(summary, Path(link_base) if link_base else HERE)]
    lines += ['## 课程交付与结论边界',
              f"课程材料草案索引见 [materials/index.md]({data_link}/materials/index.md)，参数来源见 [parameter-sources.csv]({data_link}/materials/parameter-sources.csv)。实际学生分工、教师审核、实验室资源交接、答辩和最终考核均须真实记录；本脚本不把技术运行替代课程验收。",
              '本研究为未校准二维1T1C探索模型。粒子扰动、判据误读和物理持久位翻转不能混称，不外推商业DRAM可靠性或真实辐射截面。',
              f"原始证据及源码哈希见 [sources.json]({data_link}/sources.json)；完整阶段快照见 [summary.json]({data_link}/summary.json)。"]
    if summary['errors']:
        lines += ['## 尚未解决的失败', _table(['响应/依赖', '原因'], summary['errors'].items())]
    return '\n\n'.join(lines) + '\n'


def materials(summary, snapshot):
    folder = Path(snapshot) / 'materials'
    if folder.exists():
        raise ValueError('Materials snapshot already exists')
    folder.mkdir()
    with (folder / 'parameter-sources.csv').open('x', encoding='utf8', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['parameter', 'value', 'unit', 'source', 'scope'])
        writer.writerows(parameter_rows())
    pending = {key: {'state': 'PENDING', 'reason': 'No verified human/course evidence supplied to this generator'} for key in summary['design']['course_pending']}
    index = {'schema': 'dram-see-v3-course-materials-draft', 'synthetic_fixture': summary.get('synthetic_fixture', False),
             'technical_status': 'stage snapshot only', 'human_course_items': pending,
             'native_visual_evidence': summary.get('native_evidence', {'state': 'PENDING', 'captures': []}),
             'bounded_request_demonstration': summary.get('request_demo', {'state': 'PENDING', 'student_demonstration': 'PENDING'}),
             'main_event_denominator': 64, 'paired_responses': 128,
             'materials': ['parameter-sources.csv', '../responses.csv', '../statistics.csv', '../sources.json', '../report.md']}
    (folder / 'index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    fixture = '**合成fixture，非物理实验成果。**\n\n' if summary.get('synthetic_fixture') else ''
    text = fixture + '''# 课程交付材料草案索引

| 材料 | 当前入口 | 状态与边界 |
| --- | --- | --- |
| 可行性说明 | ../../../../plan.md；../report.md | 未校准2D探索模型；资源与预算按真实记录 |
| 设计与进度 | ../summary.json；../responses.csv | 固定64事件/128响应槽位，保留缺失与失败 |
| 参数来源 | parameter-sources.csv | 探索假设和原始来源明确区分；非工艺校准 |
| 自然语言改参演示 | 下方限定接口证据 | 接口验证与学生实际演示分别登记 |
| Geant4-TCAD联合链路 | ../sources.json；../summary.json | 源事件、输入、原始归档、指标可追溯 |
| 数值图件 | ../figures/index.json | DATA PLOT，不是原生软件截图 |
| Sentaurus Visual取证 | 下方原生导出和真实窗口证据 | 来源哈希核验与视觉审查分别登记 |
| 总结报告/答辩素材 | ../report.md | 阶段草稿；不得将计划写成结果 |

实际2–3名学生分工、教师审核、实验室资源交接、答辩与最终考核见index.json的PENDING事项。没有真实证据不得改为完成。
'''
    demo = summary.get('request_demo', {})
    if demo.get('state') == 'VERIFIED_BOUNDED_INTERFACE':
        text += '\n## 限定自然语言接口证据\n\n' + f"{demo['utc']} 的限定模板解析已核对原始验证记录：64事件/128响应相同、五类越界或歧义请求拒绝。"
        text += f" [演示指南]({_relative(ROOT / demo['guide'], folder)})；[原始验证绑定]({_relative(ROOT / demo['evidence_file'], folder)})。实际学生演示仍为PENDING；不宣称通用自然语言建模能力。\n"
    else:
        text += '\n限定自然语言接口证据尚未绑定；实际学生演示仍为PENDING。\n'
    text += '\n## 原生取证索引\n\n' + '\n\n'.join(native_lines(summary, folder)) + '\n'
    (folder / 'index.md').write_text(text, encoding='utf8')


def generate(snapshot=None, publish=False, plots=True):
    summarizer = _module('summarize')
    snapshot = summarizer.write_snapshot(summarizer.collect()) if snapshot is None else Path(snapshot).resolve()
    summary = json.loads((snapshot / 'summary.json').read_text(encoding='utf8'))
    if publish and summary.get('synthetic_fixture'):
        raise ValueError('A synthetic fixture may never publish a project report')
    sources = json.loads((snapshot / 'sources.json').read_text(encoding='utf8'))
    if sources['summary_sha256'] != summarizer.sha(snapshot / 'summary.json'):
        raise ValueError('Snapshot summary hash mismatch')
    if publish:
        summarizer.validate_snapshot_claims(summary)
    figure_index = None
    if plots:
        path = snapshot / 'figures/index.json'
        if path.exists():
            figure_index = json.loads(path.read_text())
            if figure_index['summary_sha256'] != summarizer.sha(snapshot / 'summary.json'):
                raise ValueError('Figure index belongs to a different snapshot')
            for row in figure_index['created']:
                for output in row['files']:
                    if summarizer.sha(path.parent / output['file']) != output['sha256']:
                        raise ValueError('Previously generated figure changed')
        else:
            figure_index = _module('plot_results').plot_snapshot(snapshot)
    if (snapshot / 'report.md').exists():
        raise ValueError('Snapshot report already exists; create a new summary snapshot')
    materials(summary, snapshot)
    text = render(summary, snapshot, figure_index, link_base=snapshot)
    (snapshot / 'report.md').write_text(text, encoding='utf8', newline='\n')
    if publish:
        published = render(summary, snapshot, figure_index, link_base=HERE)
        (snapshot / 'published-report.md').write_text(published, encoding='utf8', newline='\n')
        (HERE / 'report.md').write_text(published, encoding='utf8', newline='\n')
    return {'snapshot': str(snapshot), 'report': str(HERE / 'report.md' if publish else snapshot / 'report.md'),
            'published': publish, 'sha256': summarizer.sha(snapshot / ('published-report.md' if publish else 'report.md'))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args()
    print(json.dumps(generate(args.snapshot, args.publish, not args.no_plots), indent=2))
