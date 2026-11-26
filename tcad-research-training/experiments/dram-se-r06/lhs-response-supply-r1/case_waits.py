"""Project the original r0.6 ledger and supply receipts into a private JSON file."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


RELEASE = Path('/opt/tcad-autonomy/current')
LHS_STATUS = 'local_runtime/server-codex/r06-lhs-response-supply-r1/response-status.json'
D1_G0_ZERO_B1 = 'r06-p0-d1-g0-hold22-exact-deck-zero-b1-r1'
HOLDOUT_HANDOFF = 'local_runtime/server-codex/r06-full-supply-holdout-r1/handoff.json'
HOLDOUT_BOUNDS = 'experiments/dram-se-r06/p0-holdout-geometry-r1/mesh-proposals/h1-h2-native-bounds-review.json'
H0_WHR = 'local_runtime/server-codex/holdout-h0-whr'
INPUT_ERRORS = (OSError, ValueError, KeyError, TypeError)
PUBLIC_WAIT = {
    'p2_release': '等待 P1 证据审阅和 P2 放行。',
    'dual_state_qualification': '等待该结构两种存储状态的数值资格验收。',
    'zero_receipt': '等待对应存储状态的匹配零源验收记录。',
    'transport_preparation': '等待该工况的输运输入冻结。',
    'transport_collection': '等待该工况的输运完成并核验收集。',
    'draw_and_source': '等待冻结入选事件并生成对应的粒子源。',
    'matched_zero': '等待同结构、同存储状态的匹配零源。',
    'threshold_reference': '等待真实参考事件、匹配零源和初次阈值试探决定。',
    'threshold_feedback': '等待同工况初次阈值试探的配对读出验收。',
    'threshold_decision': '等待根据已验收读出确定下一次试探倍率或记录停止决定。',
    'threshold_branch_hold': '等待确认阈值试探的下一分支及未使用计划位。',
    'response_review': '等待输入核验和原调度器准入。',
    'queue_publication': '等待已审阅输入进入原调度队列。',
    'dispatch': '等待原调度器分配运行资源。',
    'run_observation': '等待原运行的状态回读。',
    'execution': '等待原运行完成。',
    'collection': '等待核验并收集原运行结果。',
    'case_acceptance': '等待原运行结果的科学验收。',
    'repair_review': '等待复核已有运行并决定修复或结案。',
    'evidence_review': '等待核对该项证据和原任务身份。',
    'al_acquisition': '等待开发数据快照、候选模型和分批选点决定冻结。',
    'holdout_freeze': '等待开发模型和评估规则冻结后解封。',
    'holdout_inputs': '等待按冻结规则准备留出评估输入。',
}


def optional(gate, path):
    return gate.read(path) if path.is_file() else {}


def phase_evidence(work, gate, recipe, manifest_sha, warnings):
    lhs = recipe.get('lhs_evidence', {})
    p2_ref = recipe.get('p2_release')
    p2_name = lhs.get('p2_release_path')
    p1 = {}
    try:
        p2 = (gate.read_reference(work, p2_ref) if p2_ref
              else optional(gate, gate.path_at(work, p2_name)) if p2_name else {})
        if p2:
            gate.need(p2.get('manifest_sha256') == manifest_sha
                      and p2.get('p2_authorized') is True, 'P2 release differs from this plan')
            if lhs:
                gate.need(p2.get('threshold_bracket_observed') is True
                          or p2.get('censoring_accepted') is True, 'P2 has no accepted P1 decision')
            decision = p2.get('p1_evidence', {}).get('decision')
            if decision or lhs:
                p1 = gate.read_reference(work, decision)
    except INPUT_ERRORS as error:
        warnings['p2_release'] = str(error)
        p2 = {}
    try:
        status = optional(gate, work / LHS_STATUS)
        if status:
            gate.need(status.get('schema') == 'tcad-r06-lhs-response-supply-v1'
                      and status.get('manifest_sha256') == manifest_sha, 'LHS report differs from this plan')
    except INPUT_ERRORS as error:
        warnings['lhs_response_status'] = str(error)
        status = {}
    return p2, p1, status


def reuse_binding(work, gate, case, reference, manifest_sha, lhs_producer=False):
    receipt = gate.read_reference(work, reference)
    case_id = case['case_id']
    labels = [item['label'] for item in receipt['cases'] if item['label']['case_id'] == case_id]
    gate.need(receipt['manifest_sha256'] == manifest_sha and receipt['block'] == case['block']
              and receipt['condition'] == {key: case[key] for key in ('profile_id', 'radiation_id')}
              and len(labels) == 1 and labels[0]['stored_bit'] == case['stored_bit'],
              'zero-reuse receipt belongs to another case')
    if lhs_producer:
        native = gate.read_reference(work, receipt['native_zero'])
        gate.need(receipt['schema'] == 'tcad-r06-deferred-zero-reuse-v1'
                  and receipt['formal_statistics_eligible'] is receipt['training_eligible'] is False
                  and labels[0]['accepted'] is True and labels[0]['y'] == 0
                  and labels[0]['acceptance_evidence_sha256'] == receipt['native_zero']['sha256']
                  and native['run_id'] == receipt['zero_run_id']
                  and native['results_sha256'] == receipt['zero_result_sha256']
                  and native['profile_id'] == case['profile_id'] and native['stored_bit'] == case['stored_bit'],
                  'LHS zero-reuse receipt differs from the recorded original zero run')
    return {'run_id': receipt['zero_run_id'], 'evidence': reference,
            'source': 'lhs_response_supply' if lhs_producer else 'month_one'}


def recorded_result(work, gate, case, results, manifest_sha, attempts):
    is_zero = case['block'] == 'Z'
    name = 'z-baseline-reuse' if is_zero else 'case-acceptance'
    path = results / name / (case['case_id'] + '.json')
    record = optional(gate, path)
    if not record:
        return None
    coordinates = ('block', 'profile_id', 'radiation_id', 'stored_bit')
    matches_case = (record.get('case_id') == case['case_id']
                    and all(record[key] == case[key] for key in coordinates
                            if key in record and (case['block'] != 'AL' or case[key] is not None)))
    if record.get('schema') == 'tcad-r06-zero-source-reuse-acceptance-v1' and not is_zero:
        gate.need(matches_case and record.get('plan_sha256') == manifest_sha
                  and record.get('event_run_id') is None and record.get('status') == 'accepted',
                  'recorded zero reuse differs from the frozen case')
        reference, = (ref for ref in record['evidence'] if ref.get('kind') == 'zero_source_reuse')
        return {'zero_reuse_reference': reference}
    plan_key = 'plan_sha256' if is_zero else 'manifest_sha256'
    # Older acceptance records can be joined through the already indexed original run.
    plan_matches = (record.get(plan_key) == manifest_sha if plan_key in record else
                    not is_zero and any(item.get('run_id') == record.get('run_id') for item in attempts))
    gate.need(record.get('schema') == ('tcad-r06-z-baseline-reuse-v1' if is_zero
                                      else 'tcad-r06-case-acceptance-v1')
              and matches_case and record.get('run_id') and plan_matches,
              'recorded acceptance identity differs from the frozen case')
    if record.get('status') != ('validated' if is_zero else 'accepted'):
        return None
    return {**{key: record[key] for key in ('run_id', 'status', 'readout_error', 'scale_factor')
               if key in record}, 'path': path.relative_to(work).as_posix()}


def finish(row, status, code=None, *, public_zh=None, **detail):
    row.update(status=status, wait={'code': code, **detail} if code else None,
               public_wait_zh=(public_zh or PUBLIC_WAIT[code]) if code else None)
    return row


def bound_attempts(row, observed, scheduler):
    attempts = row['attempts']
    active = [item for item in attempts if item.get('observed_status') in
              ('running', 'submitted', 'starting', 'collecting', 'queued', 'pending')]
    queued = [item for item in attempts if not item.get('run_id')]
    if active:
        item = active[-1]
        code = 'collection' if item['observed_status'] == 'collecting' else 'execution'
        return finish(row, 'run_bound', code, task_id=item['task_id'], run_id=item['run_id'])
    if queued:
        item = queued[-1]
        task = item['task_id']
        return finish(row, 'queued', 'dispatch', task_id=task, reason=item.get('observed_reason'),
                      detail=item.get('detail'), admission_block=scheduler.get('admission_blocks', {}).get(task))
    successful = [item for item in attempts if item.get('observed_status') == 'succeeded']
    if successful:
        item = successful[-1]
        return finish(row, 'run_bound', 'case_acceptance', task_id=item['task_id'], run_id=item['run_id'])
    item = attempts[-1]
    return finish(row, 'run_bound', 'repair_review' if item.get('observed_status') else 'run_observation',
                  task_id=item['task_id'], run_id=item['run_id'],
                  observed_status=item.get('observed_status'), detail=observed.get(item['task_id'], {}).get('detail'))


def run_identity(evidence, task):
    run_id = evidence['intents'].get(task, {}).get('run_id')
    run = evidence['observed'].get(task, {})
    if not run_id or run.get('run_id') != run_id:
        run = {}
    return run_id, run


def isolated_zero_wait(row, case, evidence):
    profile, bit = case['profile_id'], case['stored_bit']
    group = profile.split('-')[0]
    if group == 'H0':
        task = f'r06-p0-h0-zero-whr-b{bit}-r1'
        run_id, run = run_identity(evidence, task)
        evidence_paths = evidence['h0_reviews'].get(bit, {})
        if 'function_review' in evidence_paths:
            step = '等待隔离基线数值资格签署'
        elif run.get('collected'):
            step = '等待隔离复核零源写入、保持、读出及数值收敛'
        else:
            step = '等待隔离零源运行收集'
        return finish(row, 'waiting', 'isolated_zero_baseline',
                      public_zh=f'{group} b{bit} {step}。', task_id=task, run_id=run_id,
                      observed_status=run.get('status'), collected=run.get('collected'), **evidence_paths)
    review = evidence['holdout_geometry'].get(profile, {})
    draft = evidence['holdout_drafts'].get(case['case_id'], {})
    blocked = review.get('stage_zero_permitted_by_this_review') is False
    step = '等待原几何超差复核与隔离零源准入' if blocked else '等待隔离零源几何与输入准入'
    return finish(row, 'waiting', 'isolated_zero_geometry',
                  public_zh=f'{group} b{bit} {step}。', handoff=HOLDOUT_HANDOFF,
                  bounds_review=evidence['holdout_bounds'], geometry_parent=review.get('geometry_parent'),
                  bounds_failed=review.get('bounds_failed'), bounds_checked=review.get('bounds_checked'),
                  mesh_run_id=review.get('run_id'), task_candidate=draft.get('task_candidate'),
                  hold_reason=draft.get('hold_reason'))


def isolated_zero_evidence(work, gate, manifest_sha, intents, warnings):
    bounds = HOLDOUT_BOUNDS
    drafts = {}
    try:
        handoff = optional(gate, work / HOLDOUT_HANDOFF)
        if handoff:
            gate.need(handoff['schema'] == 'tcad-r06-isolated-holdout-zero-drafts-v1'
                      and handoff['manifest']['sha256'] == manifest_sha
                      and handoff['development_use'] is False, 'isolated holdout draft belongs to another plan')
            reference = handoff['original_bounds_review']
            review = gate.read_reference(work, reference)
            bounds = reference['path']
            drafts = {draft['case_id']: draft for draft in handoff['held_drafts']}
        else:
            review = optional(gate, work / bounds)
    except PermissionError:
        # The service can read the original bounds review when the handoff directory is root-only.
        review = optional(gate, work / bounds)
    except INPUT_ERRORS as error:
        warnings['holdout_geometry'] = str(error)
        review = {}
    geometry = {result['profile_id']: result for result in review.get('results', [])}
    h0 = defaultdict(dict)
    for bit in (0, 1):
        task = f'r06-p0-h0-zero-whr-b{bit}-r1'
        run_id = intents.get(task, {}).get('run_id')
        for suffix in ('private-observation', 'function-review'):
            name = f'{H0_WHR}/{task}-{suffix}.json'
            try:
                review = optional(gate, work / name)
                if review:
                    gate.need(run_id and review['run_id'] == run_id and review['stored_bit'] == bit
                              and review['development_use'] is False, 'H0 review identity differs')
                    if suffix == 'function-review':
                        gate.need(all(review.get(key) is True for key in (
                            'write_direction_at_end_and_release', 'hold_direction_all_native_circuit_rows',
                            'read_clock_and_direction_at_31_9_ns', 'exact_zero_source_verified_by_frozen_reader')),
                            'H0 function review has an unresolved check')
                    h0[bit][suffix.replace('-', '_')] = name
            except INPUT_ERRORS as error:
                warnings[f'{task}-{suffix}'] = str(error)
    return {'holdout_bounds': bounds, 'holdout_geometry': geometry, 'holdout_drafts': drafts, 'h0_reviews': h0}


def asymmetry_wait(row, case, evidence, zero_case):
    profile, rad, shape, scale = (case[key] for key in
                                 ('profile_id', 'radiation_id', 'source_shape_id', 'scale_factor'))
    prior = evidence['threshold_cases'][profile, rad, shape, 1, scale]
    accepted = evidence['records'].get(prior, {})
    control = evidence['asymmetry_controls'].get((profile, rad), {})
    zero_task = control.get('zero_tasks', {}).get('0')
    zero_run, observed = run_identity(evidence, zero_task)
    prefix = f"{profile.split('-')[0]}/{rad} b0 ×{scale:g}"
    message = (f'{prefix} 等待核验同一套输入的 b0 零源。' if accepted else
               f'{prefix} 等待同工况 b1 ×{scale:g} 正式验收及同一套输入的 b0 零源核验。')
    return finish(row, 'waiting', 'matched_zero' if accepted else 'threshold_feedback', public_zh=message,
                  prior_case_id=prior, prior_scale=scale, prior_run_id=accepted.get('run_id'),
                  prior_acceptance=accepted.get('path'), baseline_case_id=zero_case, zero_task_id=zero_task,
                  zero_run_id=zero_run, zero_observed_status=observed.get('status'),
                  baseline_case_run_id=evidence['records'].get(zero_case, {}).get('run_id'),
                  zero_observation=control.get('zero_observations', {}).get('0'), requires_exact_deck_zero=True)


def case_wait(row, case, evidence):
    cid, block, profile, bit, rad = (case[key] for key in
                                    ('case_id', 'block', 'profile_id', 'stored_bit', 'radiation_id'))
    lhs, item = evidence['lhs_cases'].get(cid, (evidence['lhs_profiles'].get(profile, {}), {}))
    coordinate = (profile, rad)
    zero_case = evidence['zeros'].get((profile, bit))
    approval = evidence['approved'].get(cid)
    if block == 'Z' and case.get('holdout') == 'profile':
        return isolated_zero_wait(row, case, evidence)
    if block in ('HR', 'HP'):
        if cid not in evidence['later']:
            return finish(row, 'sealed', 'holdout_freeze', required_schema='tcad-r06-training-freeze-v1',
                          required=['model', 'preprocessing', 'split', 'calibration', 'acquisition'])
        if approval:
            return finish(row, 'waiting', 'queue_publication', admission=approval)
        return finish(row, 'waiting', 'holdout_inputs', baseline_case_id=zero_case,
                      radiation_id=rad, selection_mechanism=case['selection_mechanism'],
                      staged_admission=evidence['later'][cid])
    if block == 'AL':
        if not evidence['p2']:
            return finish(row, 'waiting', 'p2_release')
        if approval and cid in evidence['later']:
            return finish(row, 'waiting', 'queue_publication', admission=approval)
        if cid in evidence['later']:
            return finish(row, 'waiting', 'response_review', staged_admission=evidence['later'][cid])
        return finish(row, 'await_acquisition', 'al_acquisition', batch_id=cid.split('-')[2],
                      required=['development_snapshot', 'candidate_model', 'selection_rule',
                                'selected_event', 'response_input'])
    if profile in evidence['qualification_paths']:
        if block != 'Z' and not evidence['p2']:
            return finish(row, 'waiting', 'p2_release')
        if profile not in evidence['qualified']:
            return finish(row, 'waiting', 'dual_state_qualification',
                          public_zh=f"等待 {profile.split('-')[0]} 的 b0、b1 数值资格验收。",
                          evidence_path=evidence['qualification_paths'][profile],
                          qualification_runs=lhs.get('qualification_runs', []), stored_bit=bit)
    if block == 'Z':
        return finish(row, 'waiting', 'zero_receipt', stored_bit=bit,
                      functional_evidence=evidence['z_functional'].get(cid))
    if approval:
        return finish(row, 'waiting', 'queue_publication', admission=approval)
    if item.get('status') == 'approved_waiting_queue':
        return finish(row, 'waiting', 'queue_publication')
    if item.get('status') == 'staged':
        return finish(row, 'waiting', 'response_review')
    if item.get('status') == 'blocked':
        return finish(row, 'waiting', 'response_review', detail=item.get('dependency'))
    if case.get('bracket_role') == 'b0_asymmetry_probe':
        return asymmetry_wait(row, case, evidence, zero_case)
    cell = evidence['cells'].get(coordinate, {})
    pool_task = lhs.get('pool_task') if cid in evidence['lhs_cases'] else None
    pool_tasks = sorted(evidence['pools'].get(coordinate, set())
                        | {item['task_id'] for item in row['related_transport_intents']}
                        | ({pool_task} if pool_task else set()))
    pool_runs = [{**{'task_id': task}, **{key: evidence['observed'].get(task, {}).get(key)
                                        for key in ('run_id', 'status')}} for task in pool_tasks]
    pool_done = any(run['status'] == 'succeeded' for run in pool_runs)
    if not pool_done and pool_task and not evidence['observed'].get(pool_task):
        pool_done = lhs.get('pool_status') == 'succeeded'
    if block == 'T' and case['scale_factor'] != 10:
        key = (profile, rad, case['source_shape_id'], bit)
        scale = case['scale_factor']
        first = evidence['threshold_cases'].get((*key, 10))
        high = evidence['threshold_cases'].get((*key, 30))
        group = f"{profile.split('-')[0]}/{rad} b{bit}"
        if scale == 3 and bit == 1 and coordinate in evidence['d2_censored']:
            return finish(row, 'decision_pending', 'threshold_branch_hold',
                          public_zh=f'{group} ×30 仍未翻转，保留 ×3 分支，等待独立的新试探决定。',
                          branch_state='retained_right_censored', prior_case_id=high,
                          proposed_scale=scale, **evidence['d2_censored'][coordinate])
        if key[:2] == ('D1-short-channel', 'G0') and bit == 1:
            run_id, zero = run_identity(evidence, D1_G0_ZERO_B1)
            collected = zero.get('status') == 'succeeded' and zero.get('collected') is True
            message = (f'{group} ×{scale:g} 等待用已收集的零源复核配对并确定试探分支。' if collected else
                       f'{group} ×{scale:g} 等待同一套输入的零源运行完成并核验。')
            return finish(row, 'decision_pending' if collected else 'waiting',
                          'threshold_decision' if collected else 'matched_zero', public_zh=message,
                          task_id=D1_G0_ZERO_B1, run_id=run_id, observed_status=zero.get('status'),
                          prior_case_id=first, prior_run_id=evidence['records'].get(first, {}).get('run_id'),
                          proposed_scale=scale)
        if profile == 'LHS02-development' and scale == 3:
            high_attempts = evidence['indexed'].get(high, {}).get('attempts', [])
            if high_attempts and high not in evidence['records']:
                probe = next((attempt for attempt in reversed(high_attempts)
                              if attempt.get('observed_status') == 'running'), high_attempts[-1])
                return finish(row, 'waiting', 'threshold_feedback',
                              public_zh=f'{group} ×3 等待同工况 ×30 的配对读出验收和分支决定。',
                              prior_case_id=high, prior_scale=30, proposed_scale=scale,
                              prior_task_id=probe['task_id'], prior_run_id=probe.get('run_id'),
                              prior_status=probe.get('observed_status'), requires_branch_decision=True)
            if high in evidence['records']:
                first = high
        feedback = evidence['records'].get(first)
        if not feedback:
            return finish(row, 'waiting', 'threshold_feedback', prior_case_id=first,
                          public_zh=f'等待 {group} ×10 试探的配对读出验收。',
                          baseline_case_id=zero_case, proposed_scale=case['scale_factor'])
        configured = cid in evidence['threshold_recipes']
        holds_high = case['scale_factor'] == 30 and feedback.get('readout_error') == 1
        code = ('threshold_branch_hold' if holds_high else
                'response_review' if configured else 'threshold_decision')
        return finish(row, 'waiting' if configured and not holds_high else 'decision_pending',
                      code, prior_case_id=first, readout_error=feedback.get('readout_error'),
                      prior_run_id=feedback['run_id'], proposed_scale=case['scale_factor'],
                      same_primary_and_state=True)
    if not pool_done and (block != 'T' or profile in evidence['qualification_paths']):
        return finish(row, 'waiting', 'transport_collection' if pool_tasks else 'transport_preparation',
                      pool_runs=pool_runs, crn_group_id=case['crn_group_id'], radiation_id=rad,
                      detail=lhs.get('error') or next((evidence['blockers'][task] for task in pool_tasks
                                                     if task in evidence['blockers']), None))
    if block == 'T':
        return finish(row, 'waiting', 'threshold_reference', baseline_case_id=zero_case,
                      source_shape_id=case['source_shape_id'], radiation_id=rad,
                      proposed_scale=case['scale_factor'], pool_runs=pool_runs, detail=item.get('dependency'))
    if lhs.get('projection') and cid in evidence['lhs_cases']:
        return finish(row, 'waiting', 'response_review', projection=lhs['projection'],
                      detail=item.get('dependency') or lhs.get('error'))
    draw = cell.get('frozen_draws', {}).get(block)
    zero_task = cell.get('zero_tasks', {}).get(str(bit))
    if draw and zero_task and evidence['observed'].get(zero_task, {}).get('status') != 'succeeded':
        return finish(row, 'waiting', 'matched_zero', baseline_case_id=zero_case, task_id=zero_task,
                      stored_bit=bit, frozen_draw=draw)
    return finish(row, 'waiting', 'draw_and_source', pool_runs=pool_runs, frozen_draw=draw,
                  baseline_case_id=zero_case, detail=lhs.get('error') if cid in evidence['lhs_cases'] else None)


def build(policy, index, gate, approved_reader=None):
    work = Path(policy['workspace']).resolve()
    state = Path(policy['state_dir'])
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    manifest_sha = contract['manifest']['sha256']
    manifest = gate.read_reference(work, contract['manifest'])
    cases = {case['case_id']: case for case in manifest['cases']}
    indexed = {row['case_id']: row for row in index['cases']}
    gate.need(index['manifest_sha256'] == manifest_sha and cases.keys() == indexed.keys()
              and len(cases) == len(manifest['cases']) == len(index['cases']) == manifest['budget']['total_cases'],
              'month-one index does not cover the frozen plan exactly once')
    warnings = dict(index.get('zero_reuse_blocks', {}))
    recipe_ref = policy.get('scheduler_supply', {}).get('continuous')
    recipe = gate.read_reference(work, recipe_ref) if recipe_ref else {}
    gate.need(not recipe or recipe['manifest_sha256'] == manifest_sha, 'continuous recipe differs from this plan')
    p2, p1, lhs = phase_evidence(work, gate, recipe, manifest_sha, warnings)
    d2_censored = {}
    for summary in p1.get('d2', []):
        if summary.get('max_observed_scale') == 30 and summary.get('observed_errors') == 0:
            try:
                reference = summary['feedback']
                gate.referenced(work, reference)
                high, = (row for row in summary['rows'] if row['scale'] == 30 and row['readout_error'] == 0)
                d2_censored[summary['profile_id'], summary['radiation_id']] = {
                    'p1_decision': p2['p1_evidence']['decision'], 'feedback_receipt': reference,
                    'prior_run_id': high['run_id'], 'prior_scale': 30,
                }
            except INPUT_ERRORS as error:
                warnings[f"D2/{summary.get('radiation_id')}"] = str(error)
    observation = optional(gate, state / 'observation.json')
    observed = {run['id']: run for run in observation.get('runs', [])}
    scheduler = observation.get('scheduler', {}) if index.get('observation_fresh') else {}
    intents = optional(gate, state / 'runtime.json').get('intents', {})
    tasks = {task['id']: task for task in gate.read(policy['queue_file'])['tasks']}
    admissions = gate.path_at(work, contract['production_admissions_dir'])
    results = admissions.parent / 'results'
    records, reuse = {}, {}
    lhs_cases = {cid: (cell, item) for cell in lhs.get('cases', []) for cid, item in cell['cases'].items()}
    for cid, case in cases.items():
        try:
            record = recorded_result(work, gate, case, results, manifest_sha, indexed[cid]['attempts'])
            recorded_reuse = (record or {}).get('zero_reuse_reference')
            if record and not recorded_reuse:
                records[cid] = record
        except INPUT_ERRORS as error:
            warnings[cid] = str(error)
            recorded_reuse = None
        try:
            reference = indexed[cid].get('zero_reuse_receipt')
            item = lhs_cases.get(cid, ({}, {}))[1]
            lhs_reference = recorded_reuse or item.get('evidence')
            if reference or recorded_reuse or item.get('status') == 'verified_zero_reuse':
                reuse[cid] = reuse_binding(work, gate, case, reference or lhs_reference, manifest_sha,
                                           lhs_producer=not reference)
        except INPUT_ERRORS as error:
            warnings[cid] = str(error)
    transport = recipe.get('transport', {})
    pools = defaultdict(set)
    for reference in transport.get('preparations', []):
        try:
            for pool in gate.read_reference(work, reference)['pools']:
                for request in pool['pool_request_candidates']:
                    pools[request['profile_id'], request['radiation_id']].add(pool['task_id'])
        except INPUT_ERRORS as error:
            warnings[reference['path']] = str(error)
    qualification_paths = recipe.get('lhs_evidence', {}).get('p0_gate_paths', {})
    qualified = set()
    for profile, name in qualification_paths.items():
        try:
            path = gate.path_at(work, name)
            if path.is_file():
                document = gate.common_gate(work, contract, {'p0_gate': {'path': name, 'sha256': gate.sha(path)}})
                gate.qualified_profile(work, document, profile)
                qualified.add(profile)
        except INPUT_ERRORS as error:
            warnings[profile] = str(error)
    catalog = {}
    p2_path = recipe.get('lhs_evidence', {}).get('p2_release_path')
    if p2 and p2_path:
        try:
            catalog = optional(gate, gate.path_at(work, p2_path).with_name('response-catalog.json'))
            gate.need(not catalog or (catalog['schema'] == 'tcad-r06-response-catalog-v1'
                                      and catalog['manifest_sha256'] == manifest_sha),
                      'response catalog differs from this plan')
        except INPUT_ERRORS as error:
            warnings['response_catalog'] = str(error)
            catalog = {}
    later, approved = {}, {}
    approved_entries = []
    if approved_reader:
        approved_entries, intake_errors = approved_reader(policy, gate, work, manifest_sha, tasks, intents, ())
        warnings.update(intake_errors)
    later_entries = [*recipe.get('later_entries', []), *catalog.get('later_entries', [])]
    entries = [(entry, False) for entry in later_entries] + [(entry, True) for entry in approved_entries]
    for entry, is_approved in entries:
        try:
            ref = entry['admission']
            admission = gate.read_reference(work, ref)
            cid = admission.get('case_id')
            gate.need(admission['manifest_sha256'] == manifest_sha, 'staged admission differs from this plan')
            if cid in cases:
                if admission.get('scope') == 'holdout_evaluation':
                    gate.training_freeze(work, admission)
                    later[cid] = ref
                elif cases[cid]['block'] == 'AL' and admission.get('acquisition'):
                    acquisition = gate.read_reference(work, admission['acquisition'])
                    gate.need(acquisition.get('schema') == 'tcad-r06-al-acquisition-v1'
                              and acquisition.get('case_id') == cid and acquisition.get('holdout_used') is False,
                              'staged acquisition differs from the frozen case')
                    later[cid] = ref
                if is_approved:
                    approved[cid] = ref
        except INPUT_ERRORS as error:
            warnings[f'later_entry_{len(warnings)}'] = str(error)
    evidence = {
        'p2': p2, 'lhs_cases': lhs_cases, 'qualified': qualified, 'qualification_paths': qualification_paths,
        'lhs_profiles': {row['profile']: row for row in lhs.get('cases', [])},
        'pools': pools, 'observed': observed, 'records': records, 'later': later, 'approved': approved,
        'd2_censored': d2_censored, 'indexed': indexed, 'intents': intents,
        'blockers': scheduler.get('replenishment', {}).get('blocked', {}),
        'cells': {(cell['profile_id'], cell['radiation_id']): cell
                  for cell in recipe.get('natural_draws', {}).get('cells', [])},
        'zeros': {(c['profile_id'], c['stored_bit']): cid for cid, c in cases.items() if c['block'] == 'Z'},
        'z_functional': {cid: f'{results.relative_to(work).as_posix()}/z-functional-evidence/{cid}.json'
                         for cid, c in cases.items() if c['block'] == 'Z'
                         and (results / 'z-functional-evidence' / (cid + '.json')).is_file()},
        'threshold_cases': {(c['profile_id'], c['radiation_id'], c['source_shape_id'], c['stored_bit'],
                             c['scale_factor']): cid for cid, c in cases.items() if c['block'] == 'T'},
        'threshold_recipes': {entry['case_id'] for source in (recipe, catalog) for entry in source.get('responses', [])},
    }
    evidence.update(isolated_zero_evidence(work, gate, manifest_sha, intents, warnings))
    asymmetry_controls = defaultdict(lambda: {'zero_tasks': {}, 'zero_observations': {}})
    for cell in recipe.get('natural_draws', {}).get('cells', []):
        control = asymmetry_controls[cell['profile_id'], cell['radiation_id']]
        for name in ('zero_tasks', 'zero_observations'):
            control[name].update(cell.get(name, {}))
    evidence['asymmetry_controls'] = asymmetry_controls
    rows = []
    for cid, case in cases.items():
        original = indexed[cid]
        attempts = []
        for attempt in original['attempts']:
            task = attempt['task_id']
            intent = intents.get(task, {})
            binding = intent.get('scientific_admission') or {}
            obj = binding.get('scientific_object') or {}
            if not attempt.get('run_id'):
                obj = optional(gate, admissions / (task + '.json'))
            attempts.append(dict(attempt, repair_of=attempt.get('repair_of') or tasks.get(task, {}).get('repair_of'),
                                 depends_on=tasks.get(task, {}).get('depends_on', []),
                                 actual_scale_factor=obj.get('scale_factor')))
        row = {key: case[key] for key in ('case_id', 'block', 'profile_id', 'radiation_id', 'stored_bit', 'holdout')}
        row['planned_scale_factor'] = case['scale_factor']
        if case['block'] == 'AL' and attempts:
            row.update({key: obj[key] for key in ('profile_id', 'radiation_id') if key in obj})
        row.update(index_state=original['state'], attempts=attempts,
                   related_transport_intents=original['related_transport_intents'],
                   acceptance=records.get(cid), zero_reuse=reuse.get(cid))
        if cid in records:
            row = finish(row, 'zero_baseline_reused' if case['block'] == 'Z' else 'acceptance_recorded')
        elif cid in reuse:
            row = finish(row, 'zero_source_reused')
        elif original['state'] in ('evidence_record_to_verify', 'evidence_identity_conflict'):
            row = finish(row, 'waiting', 'evidence_review', detail=warnings.get(cid))
        elif attempts:
            row = bound_attempts(row, observed, scheduler)
        else:
            row = case_wait(row, case, evidence)
        rows.append(row)
    return {
        'schema': 'tcad-r06-case-waits-v1', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'manifest_sha256': manifest_sha, 'observation_utc': index.get('observation_utc'),
        'observation_fresh': index.get('observation_fresh', False),
        'lhs_response_observation_utc': lhs.get('observation_utc'), 'plan_cases': len(rows),
        'counts': dict(Counter(row['status'] for row in rows)), 'cases': rows, 'warnings': warnings,
    }


def write_private(output, document):
    staged = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as stream:
            staged = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(staged, output)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RELEASE))
    import month_one
    from month_one_supply import _approved_entries
    import r06_gate as gate

    policy = gate.read(args.policy)
    write_private(args.output, build(policy, month_one.project(policy, gate), gate, _approved_entries))


if __name__ == '__main__':
    main()
