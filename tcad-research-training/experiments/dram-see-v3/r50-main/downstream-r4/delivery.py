"""Read-only, complete r4 delivery snapshots; never refit, dispatch or mutate ledger.

Shared provenance validates the real r1/r2/r3/r4 owners. Reporting receives a
separate in-memory logical view; the original ledger and failures are retained.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MAIN = HERE.parent
BASE = MAIN.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
DEV = LOCAL / 'downstream-r4-delivery-development'
OUTPUT = MAIN / 'data/delivery-r4'
FIRST = LOCAL / 'physical-revisions/r50-main-r1/plan.json'
EXTENSION = LOCAL / 'physical-revisions/r50-main-extensions-r4/plan.json'
AUTHORIZATION = LOCAL / 'unlimited-authorization-20261011T0346Z.json'
SCHEMA = 'dram-see-v3-r50-main-downstream-r4'
REVISION = 'r50-main-r1'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
ALIASES = {
    'v3-r50-main-l035-alpha-a30-s202610394-b1': 'v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1',
    'v3-r50-main-l025-alpha-a30-s202610353-b0': 'v3-r50-main-retry-r3-l025-alpha-a30-s202610353-b0',
    'v3-r50-main-l025-proton-a0-s202610361-b0': 'v3-r50-main-retry-r3-l025-proton-a0-s202610361-b0',
    'v3-r50-main-l025-proton-a30-s202610371-b1': 'v3-r50-main-retry-r4-l025-proton-a30-s202610371-b1',
}
NATIVE_TAGS = ('v3-r50-main-physical-l018-b1', 'v3-r50-main-l018-alpha-a30-s202610311-b1')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, message):
    require(actual == expected, message)


def repo(path):
    path = Path(path)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    require(path.is_relative_to(ROOT), 'Path escapes repository')
    return path


def rel(path):
    return repo(path).relative_to(ROOT).as_posix()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location('_r4_delivery_' + name, path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def write_json(path, value):
    with Path(path).open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def expected_sources():
    """Explicit transitive inventories, with no circular delivery/shared hash."""
    files = {}
    for path in (MAIN / 'delivery-source-manifest.json', MAIN / 'demo-source-manifest.json',
                 HERE / 'source-manifest.json'):
        body = json.loads(path.read_bytes())
        for name, digest in body['files_sha256'].items():
            require(name not in files or files[name] == digest, 'Conflicting source manifests: ' + name)
            files[name] = digest
        files[rel(path)] = sha(path)
    for name in ('delivery.py', 'test_delivery.py', 'delivery-implementation.md'):
        files[rel(HERE / name)] = sha(HERE / name)
    return dict(sorted(files.items()))


def sources():
    path = HERE / 'delivery-source-manifest.json'
    value = json.loads(path.read_bytes())
    same(value.get('schema'), SCHEMA + '-delivery-sources', 'Wrong delivery source manifest')
    same(value.get('design_sha256'), DESIGN_SHA, 'Wrong delivery design binding')
    same(value.get('physical_revision'), REVISION, 'Wrong delivery physical revision')
    same(value.get('files_sha256'), expected_sources(), 'Delivery dependency inventory changed')
    for name, digest in value['files_sha256'].items():
        same(sha(repo(name)), digest, 'Delivery dependency changed: ' + name)
    return {**value['files_sha256'], rel(path): sha(path)}


def logical_slots(design, ledger, proof):
    """A detached reporting view, never a replacement global ledger."""
    same(proof['aliases'], ALIASES, 'The fixed four aliases differ')
    canonical = ['v3-r50-main-' + e['label'] + '-b' + str(b) for e in design['events'] for b in (0, 1)]
    require(len(canonical) == len(set(canonical)) == 128, 'Require exactly 128 main slots')
    same(set(proof['baseline']), set(canonical), 'Complete 128 baseline required')
    same(set(proof['response_sources']), set(canonical), 'Complete 128 owner sources required')
    logical, run_ids = {}, set()
    for identifier in canonical:
        source = proof['response_sources'][identifier]
        actual = ALIASES.get(identifier, identifier)
        same(source['response_id'], identifier, 'Canonical source identity differs')
        same(source['actual_ledger_tag'], actual, 'Actual source alias differs')
        row = ledger['runs'].get(actual, {})
        require(row.get('state') == 'VERIFIED' and row.get('runner_exit_code') == 0,
                'A logical slot requires an actually completed, audited run: ' + identifier)
        same(row.get('run_id'), source['run_id'], 'Logical run owner differs')
        require(source['run_id'] not in run_ids, 'One actual run cannot fill two logical slots')
        run_ids.add(source['run_id'])
        for source_key, ledger_key in (('input_sha256', 'input_sha256'), ('archive_sha256', 'audit_archive_sha256'),
                                       ('case_freeze', 'execution_freeze')):
            same(source[source_key], row.get(ledger_key), 'Logical provenance differs: ' + source_key)
        require(source.get('owner_plan'), 'Actual case owner is required')
        signal = proof['baseline'][identifier]['metrics']['sources']['signal']
        same(signal['run_id'], source['run_id'], 'Baseline signal run differs from actual owner')
        same(signal['archive_sha256'], source['archive_sha256'], 'Baseline signal archive differs from actual owner')
        if actual != identifier:
            require(ledger['runs'].get(identifier, {}).get('state') == 'FAILED', 'Original failed alias attempt lost')
        logical[identifier] = copy.deepcopy(row)
    return {'runs': logical}


def unlimited_budget(ledger, authorization, authorization_sha256, report):
    same(authorization.get('schema'), 'dram-see-v3-unlimited-continuation-authorization', 'Wrong unlimited authorization')
    require('solver_budget_s' in authorization and authorization['solver_budget_s'] is None
            and 'expires_utc' in authorization and authorization['expires_utc'] is None,
            'Current unlimited, unexpired authorization is required')
    # The original pure sum detects duplicate run IDs and missing/invalid costs.
    value = report.global_budget(ledger)
    value.update(planned_budget_s=None, global_budget_s=None, deadline_utc=None,
                 budget_policy='UNLIMITED_BY_EXPLICIT_AUTHORIZATION', authorization=rel(AUTHORIZATION),
                 authorization_sha256=authorization_sha256,
                 policy='All unique original/failed/retry/validation/extension ledger charges retained; no new charge or reset')
    return value


def verify_boundary_table(design, proof, boundary, comparisons, interface):
    """Use the registered full-population uncertainty function without file writes."""
    audit = module(MAIN / 'audit.py', 'audit_predicate')
    scope = {'R': SimpleNamespace(design=lambda: design, A=audit,
                                  event_tag=interface.R.event_tag),
             'read': lambda path: {'comparisons': comparisons}, 'HERE': MAIN}
    expected = module(MAIN / 'delivery.py', 'pure_boundary').pure(
        MAIN / 'extensions.py', ('numerical_uncertainty',), scope)['numerical_uncertainty'](
            {'baseline': proof['baseline']}, boundary['comparisons'])
    same(boundary.get('main_threshold_status'), expected, 'Full 128 x three-threshold table differs')
    same(len(expected), 128, 'Boundary table denominator changed')
    return expected


def validate_extension_review(review, proof):
    """Fail closed if the shared raw re-audit is incomplete or merely a status."""
    require(review.get('state') == 'VERIFIED', 'Complete extension re-audit required')
    plan = review['plan']
    same(plan['selection'], proof['selection'], 'Extension full-population ranking changed')
    same(plan['baseline'], proof['baseline'], 'Extension frozen 128 baseline changed')
    cases = review['cases']
    same({r['tag'] for r in cases}, {c['tag'] for c in plan['planned_cases']}, 'Extension case inventory differs')
    same(len(cases), len(plan['planned_cases']), 'Duplicate extension case')
    require(all(r.get('raw_reviewed') is True and r.get('state') == 'VERIFIED' for r in cases),
            'Every extension case requires completed raw review')
    require(len([r for r in cases if r['stage'] == 'oxide']) == 14, 'Require exactly 14 oxide cases')
    oxide, boundary = review['oxide'], review['boundary']
    require(oxide.get('state') == 'VERIFIED' and oxide.get('new_response_count') == 8
            and len(oxide.get('baseline_5nm', [])) == 4 and len(oxide.get('responses', [])) == 8,
            'Complete oxide comparison required')
    require(boundary.get('state') == 'VERIFIED' and boundary.get('continuous_passed') is True
            and len(boundary.get('comparisons', [])) == 4, 'Four completed continuous boundary comparisons required')
    same(boundary['selection'], proof['selection'], 'Boundary report selection differs')
    require(oxide.get('new_independent_events') == boundary.get('new_independent_events') == 0,
            'Extensions cannot increase independent N')
    return review


def require_native_review(native):
    same(native.get('state'), 'VERIFIED', 'Native PNG actual visual inspection is required')
    rows = native.get('targets', [])
    same({row.get('ledger_tag') for row in rows}, set(NATIVE_TAGS), 'Both registered native targets required')
    same(len(rows), 2, 'Duplicate native target')
    require(all(row.get('state') == 'CAPTURED_VISUALLY_REVIEWED' for row in rows),
            'Machine PNG checks do not establish actual image inspection')


def mapping_evidence(evidence):
    folder = MAIN / 'data/demo/20261010T1842Z-mapping'
    value = evidence.read_json(folder / 'manifest.json')
    same(value.get('state'), 'SOFTWARE_MAPPING_VERIFIED', 'Existing mapping acceptance missing')
    for name, digest in value['files_sha256'].items():
        require(Path(name).name == name, 'Mapping file path escapes evidence')
        same(evidence.bind(folder / name), digest, 'Mapping evidence changed')
    acceptance = evidence.read_json(folder / 'acceptance.json')
    require(acceptance.get('software_mapping_accepted') is True and acceptance.get('actual_student_demo') is False,
            'Mapping software evidence must not claim student activity')
    source = evidence.read_json(MAIN / 'demo-source-manifest.json')
    same(evidence.bind(MAIN / 'demo-source-manifest.json'), acceptance['manifest_sha256'], 'Accepted mapping source manifest changed')
    same(evidence.bind(MAIN / 'demo.py'), acceptance['source_sha256'], 'Accepted mapping implementation changed')
    for name, digest in source['files_sha256'].items():
        same(evidence.bind(repo(name)), digest, 'Mapping source dependency changed')
    audit = evidence.read_json(folder / 'audit.json')
    require(audit.get('events_exactly_equal_frozen_design') is True and audit.get('events') == 64
            and audit.get('responses') == 128 and audit.get('design_sha256') == DESIGN_SHA,
            'Mapping acceptance does not represent the same fixed matrix')
    return {'state': 'SOFTWARE_MAPPING_VERIFIED', 'manifest': rel(folder / 'manifest.json'),
            'manifest_sha256': evidence.bind(folder / 'manifest.json'), 'actual_student_demo': False}


def collect(extension_plan=EXTENSION, visual_review=None):
    """Require all real science/native prerequisites before returning a snapshot.

    No snapshot directory is created on incomplete science or missing eye review.
    The returned snapshot still awaits DATA PLOT and document/PPT visual review.
    """
    source_hashes = sources()
    extension_plan = repo(extension_plan)
    same(extension_plan, EXTENSION, 'Only the accepted r4 extension plan is supported')
    require(visual_review is not None, 'Explicit root native PNG eye-review file required')
    shared = module(HERE / 'provenance.py', 'provenance')
    extension_module = module(HERE / 'extensions.py', 'extensions')
    old = module(MAIN / 'delivery.py', 'native_interface')
    b = module(MAIN / 'reporting.py', 'reporting')
    session = shared.Session(extension_plan=extension_plan)
    chain = session.validate_chain()
    proof = session.prerequisites()
    session.check_prediction()  # Hash + fixed coefficients only; never model fitting.
    ev = b.Evidence()
    for name, digest in proof['files'].items():
        same(ev.bind(repo(name)), digest, 'Prerequisite source changed: ' + name)
    ledger_path = LOCAL / 'ledger.json'
    ledger = ev.read_json(ledger_path)
    same(ledger, session.ledger, 'Global ledger changed during source review')
    design = b.design_checked(MAIN / 'design.json')
    ev.bind(MAIN / 'design.json')
    logical = logical_slots(design, ledger, proof)
    interface = old.interfaces(design)
    review = old.Review(design, ledger, interface, ev)
    # Only the two native targets and original reference/numerical gates retain
    # r1 ownership. Never call old main(), prediction(), tests() or collect().
    review.plan(FIRST, 'first', interface.first)
    stages, note = b.stage_proofs(FIRST.parent / 'stage-index.json', ev)
    gates = b.reference_checks(design, review.reader, stages, ev, review.errors)
    prereg, gates['numerical_preregistered'] = b.numerical_checks(design, review.reader, stages, ev, review.errors)
    require(all(gates.get(name, {}).get('state') == 'VERIFIED'
                for name in ('references', 'pilot', 'numerical_preregistered')) and not review.errors,
            'Original raw reference/pilot/numerical gates incomplete')
    ext = validate_extension_review(extension_module.review(session, extension_plan), proof)
    for name, digest in ext['files'].items():
        same(ev.bind(repo(name)), digest, 'Extension evidence changed: ' + name)
    verify_boundary_table(design, proof, ext['boundary'], prereg, interface)
    native = review.native(MAIN / 'figures/native', repo(visual_review), NATIVE_TAGS)
    require_native_review(native)
    measured = {tag: obs['metrics'] for tag, obs in proof['baseline'].items()}
    # Load only accepted actual archives using the shared owner-compatible audit.
    # RawReader remains restricted to original r1 reference/native evidence.
    bundles = dict(review.reader.bundles)
    def load_actual(tag):
        value = session.bundle(tag)
        require(value is not None, 'Accepted actual response archive missing')
        bundles[tag] = value
        return value
    def load_member(member):
        matches = [tag for tag, row in ledger['runs'].items() if row.get('run_id') == member.get('run_id')]
        require(len(matches) == 1, 'Ambiguous matching archive owner')
        value = load_actual(matches[0])
        same(value['summary']['archive_sha256'], member['archive_sha256'], 'Matching archive hash differs')
    for canonical, source in proof['response_sources'].items():
        load_actual(source['actual_ledger_tag'])
        for member in proof['baseline'][canonical]['metrics']['sources'].values():
            load_member(member)
    for case in ext['cases']:
        load_actual(case['tag'])
    require(not review.reader.errors, 'A completed raw source failed reporting audit')
    predictions = ev.read_json(MAIN / 'data/predictions/predictions.json')
    prediction_freeze = ev.read_json(MAIN / 'data/predictions/freeze.json')
    original_scores = interface.P.score_predictions(predictions, proof['observed_tests'], design)
    same(original_scores, proof['original_prediction_scores'], 'Original r4 scores changed')
    authorization = ev.read_json(AUTHORIZATION)
    budget = unlimited_budget(ledger, authorization, ev.bind(AUTHORIZATION), b)
    require(not budget['running_or_unsettled'] and not budget['accounting_gaps'], 'Final collection needs all real costs settled')
    gates.update(train={'state': 'VERIFIED', 'training_plan_sha256': proof['training_plan_sha256'],
                        'training_audit_sha256': proof['training_audit_sha256'], 'responses': 64},
                 prediction_freeze={'state': 'VERIFIED', 'sha256': proof['prediction_freeze_sha256'],
                                    'prediction_plan_sha256': proof['prediction_plan_sha256']},
                 test={'state': 'VERIFIED', 'test_plan_sha256': proof['test_plan_sha256'],
                       'test_result_sha256': proof['test_result_sha256'], 'responses': 64},
                 oxide={'state': ext['oxide']['state']}, numerical_boundary={'state': ext['boundary']['state'],
                        'classification_stable': ext['boundary']['classification_stable']},
                 native={'state': 'VERIFIED'})
    comparisons = prereg + ext['boundary']['comparisons']
    curves = {v['summary']['run_id']: b.display_curve(v) for v in bundles.values()
              if v['parameters']['reference_mode'] == 'offline'}
    audits = {v['summary']['run_id']: v['summary'] for v in bundles.values()}
    summary = b.assemble(design, logical, measured, audits, curves, comparisons, gates,
                         budget, {}, ev.hashes)
    for row in summary['responses']:
        source = proof['response_sources'][row['response_id']]
        row.update(actual_ledger_tag=source['actual_ledger_tag'], owner_plan=source['owner_plan'],
                   case_freeze=source['case_freeze'], input_sha256=source['input_sha256'],
                   archive_sha256=source['archive_sha256'],
                   original_attempt=copy.deepcopy(ledger['runs'][row['response_id']])
                       if row['response_id'] in ALIASES else None)
        row['numerical']['boundary_followup'] = 'VERIFIED'
    summary.update(schema=SCHEMA + '-delivery-snapshot', source_code_sha256=source_hashes,
                   stage_index_note=note, provenance_chain=chain, provenance_prerequisites=proof,
                   numerical_comparisons=comparisons, oxide=ext['oxide'], numerical_boundary=ext['boundary'],
                   extension_cases=ext['cases'], native_evidence=native, aliases=dict(ALIASES),
                   ledger_snapshot=ledger, ledger_snapshot_sha256=ev.bind(ledger_path),
                   original_failures={'failure_log': copy.deepcopy(ledger.get('failures', [])),
                       'failed_rows': {tag: copy.deepcopy(row) for tag, row in ledger['runs'].items()
                                       if row.get('state') in b.FAILURES},
                       'alias_originals': copy.deepcopy(proof['original_failures'])},
                   raw_submission_index=copy.deepcopy(proof['raw_submission_index']),
                   prediction_freeze=prediction_freeze, original_r4_prediction_scores=original_scores,
                   original_r4_score_path=rel(LOCAL / 'physical-revisions/r50-main-restart-r4/prediction-scores.json'),
                   model_review_scope='Immutable artifacts and fixed coefficient prediction only; no fitting or freeze regeneration',
                   simulation_evidence_verified=True,
                   report_state='SCIENCE_AND_NATIVE_REVIEWED_PENDING_FINAL_DOCUMENT_AND_DATA_PLOT_REVIEW',
                   agent_materials_state='PENDING_SNAPSHOT_GENERATION',
                   course_state='PENDING_REAL_STUDENT_TEACHER_DEFENSE_ASSESSMENT',
                   data_plot_visual_review='PENDING_ROOT_ACTUAL_IMAGE_INSPECTION',
                   software_mapping=mapping_evidence(ev))
    # Preserve original r4 score bytes and compute a separately named final view.
    final_scores = old.effective_scores(summary, {'predictions': predictions}, interface)
    summary['prediction_scores'] = final_scores
    summary['final_numerical_prediction_scores'] = final_scores
    for name in ('docs/course-project-syllabus.md', 'reports/outline.md'):
        ev.bind(ROOT / name)
    summary['source_files_sha256'] = dict(ev.hashes)
    session.stable()
    ev.stable()
    same(source_hashes, sources(), 'Delivery sources advanced during collection')
    return summary


def materials(summary, output):
    """Reusable course prose with actual evidence and explicit human boundaries."""
    folder = output / 'materials'
    folder.mkdir()
    synthetic = '**SYNTHETIC SOFTWARE FIXTURE — 非物理结果。**\n\n' if summary['synthetic_fixture'] else ''
    docs = {
        'feasibility.md': '# 可行性与适用范围\n\n' + synthetic +
            '本研究复用Windows控制、单VM许可证和串行单线程工具链，研究未校准二维1T1C在固定硅入口事件下的条件响应。'
            '64独立事件、128配对位槽保持冻结；0/1、确定性工程重试、氧化层和数值细化均不增加独立N。'
            '本R50主支路两侧导通预充电阻为50 Ω；历史100 Ω、probe及所有失败独立保留。\n\n'
            '当前用户已取消求解预算上限和截止时间；全部原始、失败、重试及验证成本继续由唯一账本累计。'
            '原计划资源限制属于历史证据，不能重新作为当前上限。实际费用、未知退出码及保全记录见../summary.json。'
            '本模型不代表商业DRAM工艺校准、辐射截面或真实写入成功。\n',
        'design-and-steps.md': '# 设计方案、步骤与进度\n\n' + synthetic +
            '科学设计与全部来源见../sources.json，当前128槽见../responses.csv，四alias及实际case owner见../response-sources.json。'
            '原训练32事件64响应冻结四个bit/target模型；测试32事件64响应（域内留出32、外推32）先预测后提交，禁止重新拟合。\n\n'
            '实施顺序：参考与初态/预充审计→pilot与源隔离→预登记完整匹配细化→64训练响应→模型及64预测冻结→'
            '64测试响应→14氧化层case→全128中固定排序的两个边界目标及匹配细化→两个原生目标四张PNG逐图核验→交付。\n\n'
            '本快照的实际阶段门槛见../stage-verification.json。数据图、最终文稿/PPT尚须单独目视验收；'
            '课程真实学生分工、教师方案审核、试讲、答辩与考核未由代理执行。\n',
        'methods-and-ai.md': '# 物理方法、模型与AI使用披露\n\n' + synthetic +
            '三份原Geant4事件证据锁定alpha/proton、5 MeV、0/30度及seed；电离沉积按3.6 eV/pair换算电荷，源归一因子固定1。'
            '源积分、KCL、BE及四端守恒、4 ns终点和原始退出码均按原阈值验收。\n\n'
            'ΔQ=Cstore(SN事件−SN匹配对照)，取2.8 ns；D=BL信号−同条件BL中性，M=(2b−1)D，'
            'ΔM=M对照−M事件，取4 ns并保存3.8–4 ns窗口。2.5/5/10 mV三阈值全部报告；闭区间为critical。'
            '每层计划N=4；失败、缺失、临界与数值不确定不能隐含算正确，Wilson上下包络保留未知。\n\n'
            '固定模型原r4评分与最终数值证据评分分别保留。氧化层4/6 nm重建网格及匹配对照、中性，5 nm复用主响应；'
            '这是固定硅入口事件的TCAD敏感性，并未执行变化材料栈的完整Geant4输运。\n\n'
            'AI参与代码、证据核验、统计呈现和课程材料草拟；固定脚本执行数值过程。未进行人工对照效率实验，'
            '不宣称AI加速倍数。具体模型/会话版本由主代理据真实配置披露；本材料不虚构学生阅读、判断或批准。\n',
        'demonstration.md': '# 只读可复现演示脚本（学生现场执行待发生）\n\n' + synthetic +
            '使用已冻结归档演示并明示“预先运行”，本脚本不启动求解。\n\n'
            '1. 核验../snapshot-manifest.json及../sources.json，展示设计、64事件/128槽和四alias。\n'
            '2. 复用R50映射软件验收索引../summary.json的software_mapping；合法文本预览、指定event/bit定位与模糊请求拒绝均有原软件证据。'
            '原映射快照的24小时语法字段属于历史记录，不决定当前无限预算；这不代表学生现场操作已完成。\n'
            '3. 从../response-sources.json定位任一真实run的owner plan、case-freeze、input和archive SHA；原FAILED及未知退出码保持原值。\n'
            '4. 展示同条件control/neutral/event三联、ΔQ、D、M、ΔM、三阈值分类及数值不确定性。\n'
            '5. 对照原预测冻结时间和实际测试提交索引，解释域内/外推及两种基准的残差；对照原r4和最终数值评分。\n'
            '6. 区分DATA PLOT、真实SVisual原生导出和owned窗口截图；按实际目视记录核run、4 ns、场变量、单位与隐私。\n',
        'defense-outline.md': '# 答辩材料提纲（不是答辩完成记录）\n\n' + synthetic +
            '建议10–12页核心内容：题目与真实人员；目标和限制；器件/电路；Geant4→TCAD接口；数值审计；'
            '自然语言映射；冻结矩阵和预测；真实响应/失败；域内与外推；氧化层/边界；结论与局限；可复现证据。'
            '必要时追加原档索引、公式、失败保全及课程披露备份页。此文件不是已生成的PPT。\n\n'
            '准备解释：中性参考的作用；临界与数值不确定的区别；模型未见测试响应的证据；重试/细化不增加独立N；'
            '为何判据误读不等于持久位翻转，二维理想初态为何不能外推商业可靠性。\n\n'
            '真实2–3人分工、教师方案审核、资源交接、组内试讲、正式答辩与教师考核仍待真实证据。'
            '课程评分权重导师20%、报告20%、答辩演示60%；不预测分数。\n',
        'handoff.md': '# 证据与可复现资料交接\n\n' + synthetic +
            '入口../report.md；完整128槽../responses.csv；三阈值分层../statistics.csv；四alias来源../response-sources.json；'
            '原账本../ledger-snapshot.json；全部历史失败../original-failures.json；费用及阶段../summary.json和../stage-verification.json。'
            '原r4评分../original-r4-prediction-scores.json，最终数值评分../final-numerical-prediction-scores.json，不能覆盖前者。\n\n'
            '复核顺序：输出SHA→固定源码/科学设计→实际case owner→原档/真实退出码→匹配指标→冻结/提交时间→'
            '全128排序及敏感性→PNG真实目视→新文稿/PPT逐页验收。完整归档保留在受忽略local_runtime，密钥、许可证和商业手册不复制。'
            '新增快照必须使用独占目录。旧reports/final是19/64历史写作包；最终文稿/PPT由主代理另写reports/final-r4并验收。\n',
    }
    for name, body in docs.items():
        (folder / name).write_text(body, encoding='utf8')
    index = {'schema': SCHEMA + '-agent-materials', 'state': 'AGENT_AUTHORED_MATERIALS_GENERATED',
             'technical_evidence_state': summary['report_state'], 'course_complete': False,
             'human_items': summary['course_pending'], 'files': list(docs),
             'actual_student_demo': False, 'actual_teacher_review': False, 'actual_defense': False,
             'data_plot_review': 'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION',
             'final_documents_and_ppt': 'PENDING_ROOT_ARTIFACT_CREATION_AND_VISUAL_REVIEW'}
    write_json(folder / 'index.json', index)
    (folder / 'index.md').write_text('# 代理课程材料索引\n\n' + synthetic +
        '\n'.join('- [' + n + '](' + n + ')' for n in docs) +
        '\n\n已生成代理材料；实际学生操作、教师审核、试讲、答辩和考核保持待发生。\n', encoding='utf8')
    return index


def render(summary, figures):
    synthetic = '**SYNTHETIC SOFTWARE FIXTURE — 非物理结果。**\n\n' if summary['synthetic_fixture'] else ''
    budget = summary['budget']
    lines = [synthetic + '# DRAM SEE v3 r4 证据快照',
             f"UTC `{summary['generated_utc']}`；状态 `{summary['report_state']}`。",
             '64独立事件、128配对位槽；训练64响应与测试64响应。四alias仅恢复原逻辑槽，全部原失败和未知退出码保留。',
             '这是未校准二维1T1C的条件模拟。受控理想初态不等于实际写入；判据误读不等于持久位翻转；不能推出商业DRAM可靠性或辐射截面。',
             '| 5 mV有效分类 | 数量/128 |\n| --- | --- |\n' +
             '\n'.join(f'| {k} | {v} |' for k, v in summary['main_threshold_counts'].items()),
             '2.5/5/10 mV三阈值、每层N=4及未知包络见[分层统计](statistics.csv)。分类跨界、连续失败及未选近界不确定性均保留。',
             f"预算无上限；唯一原账本累计已登记 {budget['accounted_solver_s']:.2f} s，"
             f"未结 {len(budget['running_or_unsettled'])} 项、费用缺项 {len(budget['accounting_gaps'])} 项。包含历史/失败/重试/验证成本。",
             '[原r4固定模型评分](original-r4-prediction-scores.json)与[最终数值证据评分](final-numerical-prediction-scores.json)分别保存，未重新训练或修改预测。',
             '[来源](sources.json) · [128槽](responses.csv) · [四alias和真实owner](response-sources.json) · '
             '[阶段](stage-verification.json) · [原失败](original-failures.json) · [课程材料](materials/index.md)',
             '真实原生PNG机器来源与逐图目视已作为collect门槛；以下新生成DATA PLOT还需主代理逐图核验。最终文稿/PPT需另行生成与逐页验收。']
    for item in figures['created']:
        png = next(x['file'] for x in item['files'] if x['file'].endswith('.png'))
        lines += [f"![{item['name']}](figures/{png})", item['description'] + '；PENDING_ROOT_ACTUAL_IMAGE_INSPECTION。']
    lines += ['学生/教师活动不由程序代填；本快照与代理材料不表示课程全部通过。']
    return '\n\n'.join(lines) + '\n'


def write_snapshot(summary, output, plots=True):
    output = repo(output)
    synthetic = summary.get('synthetic_fixture') is True
    allowed = DEV if synthetic else OUTPUT
    require(output.is_relative_to(allowed) and output != allowed and not output.exists(),
            'Require a new exclusive snapshot in the permitted r4 output directory')
    if not synthetic:
        require(summary.get('simulation_evidence_verified') is True, 'Final snapshot requires complete science evidence')
        require_native_review(summary['native_evidence'])
        same(summary['source_code_sha256'], sources(), 'Source changed before snapshot')
        for name, digest in summary['source_files_sha256'].items():
            same(sha(repo(name)), digest, 'Input advanced before snapshot: ' + name)
    b = module(MAIN / 'reporting.py', 'output')
    plotter = module(BASE / 'plot_results.py', 'plots') if plots else None
    output.mkdir(parents=True)
    summary = copy.deepcopy(summary)
    summary['agent_materials_state'] = 'AGENT_AUTHORED_MATERIALS_GENERATED'
    summary['rendering_environment'] = {'python': sys.version, 'matplotlib': plotter.matplotlib.__version__ if plotter else None}
    write_json(output / 'summary.json', summary)
    b.csv_write(output / 'responses.csv', summary['responses'])
    b.csv_write(output / 'statistics.csv', summary['statistics']['strata'])
    b.csv_write(output / 'extension-cases.csv', summary['extension_cases'], ('tag', 'run_id', 'state', 'raw_reviewed', 'reused', 'role', 'stage', 'new_independent_event'))
    for name, value in {
        'stage-verification.json': summary['stages'], 'ledger-snapshot.json': summary['ledger_snapshot'],
        'original-failures.json': summary['original_failures'], 'raw-submission-index.json': summary['raw_submission_index'],
        'response-sources.json': summary['provenance_prerequisites']['response_sources'],
        'final-numerical-prediction-scores.json': summary['final_numerical_prediction_scores'],
    }.items():
        write_json(output / name, value)
    if synthetic:
        write_json(output / 'original-r4-prediction-scores.json', summary['original_r4_prediction_scores'])
    else:
        original_score = repo(summary['original_r4_score_path'])
        same(sha(original_score), summary['source_files_sha256'][rel(original_score)], 'Original r4 score advanced')
        with (output / 'original-r4-prediction-scores.json').open('xb') as stream:
            stream.write(original_score.read_bytes())
    b.csv_write(output / 'prediction-scores.csv', summary['prediction_scores']['scores'])
    b.csv_write(output / 'prediction-residuals.csv', summary['prediction_scores']['stratified_residuals'])
    write_json(output / 'sources.json', {'summary_sha256': sha(output / 'summary.json'),
        'source_files_sha256': summary['source_files_sha256'], 'source_code_sha256': summary['source_code_sha256'],
        'audited_run_archives': {rid: a['archive_sha256'] for rid, a in summary['audited_runs'].items()}})
    figures = plotter.plot_snapshot(output) if plotter else {'created': [], 'skipped': [{'plot': 'all', 'reason': 'Explicit --no-plots'}]}
    write_json(output / 'figure-review-required.json', {'schema': SCHEMA + '-figure-review-required',
        'state': 'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION', 'kind': 'DATA PLOT', 'figures': figures,
        'native_separate': summary['native_evidence']})
    materials(summary, output)
    (output / 'report.md').write_text(render(summary, figures), encoding='utf8')
    if not synthetic:
        same(summary['source_code_sha256'], sources(), 'Sources advanced during snapshot writing')
        for name, digest in summary['source_files_sha256'].items():
            same(sha(repo(name)), digest, 'Evidence advanced during snapshot writing: ' + name)
    files = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    write_json(output / 'snapshot-manifest.json', {'schema': SCHEMA + '-delivery-output', 'physical_revision': REVISION,
        'synthetic_fixture': synthetic, 'files_sha256': files, 'course_complete': False,
        'new_solver_calls': 0, 'new_ledger_charges': 0, 'data_plot_review': 'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION',
        'final_documents_and_ppt': 'PENDING_ROOT_ARTIFACT_CREATION_AND_VISUAL_REVIEW'})
    return {'snapshot': str(output), 'state': summary['report_state'], 'new_solver_calls': 0,
            'new_ledger_charges': 0, 'course_complete': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extension-plan', type=Path, default=EXTENSION)
    parser.add_argument('--visual-review', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args()
    summary = collect(args.extension_plan, args.visual_review)
    print(json.dumps(write_snapshot(summary, args.snapshot, not args.no_plots), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
