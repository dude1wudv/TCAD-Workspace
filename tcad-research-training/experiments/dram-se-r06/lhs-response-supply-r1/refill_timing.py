"""Measure the last required collection to a bound r0.6 threshold launch.

Run once per timer tick with --policy and --output. The output is private.
The status checker may copy the public_summary object after checking freshness.
"""

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = 'tcad-r06-refill-timing-v1'
PUBLIC_SCHEMA = 'tcad-r06-refill-timing-public-v1'
SCOPE = 'lhs02-threshold-x10-to-x30'
FOLLOWUP_SCOPE = 'r06-threshold-followup'
PRODUCTION = 'development_production'
LEGACY_CASE = re.compile(r'r06-t-lhs02-development-shape-[ab]-x30-b1')
MAX_SAMPLES = 64
ANCHOR_PROVENANCE = 'tcad-r06-anchor-asymmetry-event-v1'
IDENTITY_FIELDS = ('schema', 'run_id', 'pid', 'start_ticks', 'boot_id', 'cwd', 'script_sha256')
COORDINATES = ('profile_id', 'radiation_id', 'source_shape_id', 'source_time_ns', 'deck_timing_version', 'crn_group_id')
UTC = timezone.utc
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
WRAPPER_DATE = re.compile(
    r'[A-Za-z]{3} ([A-Za-z]{3}) +([0-9]{1,2}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) UTC ([0-9]{4})'
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    require(isinstance(document, dict), f'expected a JSON object at {path.name}')
    return document


def workspace_path(workspace, path):
    candidate = (workspace / Path(path)).resolve()
    require(candidate.is_relative_to(workspace), 'evidence path is outside the workspace')
    return candidate


def reference(workspace, pin):
    path = workspace_path(workspace, pin['path'])
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pin['sha256'], f'evidence hash differs at {path.name}')
    return path, json.loads(raw.decode('utf-8-sig'))


def native_manifest(workspace, intent, admission, pin=None):
    _, connection = reference(workspace, intent['connection'])
    run_id = intent['run_id']
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]*', run_id), 'invalid run ID')
    path = workspace_path(workspace, Path(connection['local_state_root']) / 'runs' / run_id / 'manifest.json')
    if pin is None:
        raw = path.read_bytes()
        manifest = json.loads(raw.decode('utf-8-sig'))
        pin = {'path': path.relative_to(workspace).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()}
    else:
        referenced_path, manifest = reference(workspace, pin)
        require(referenced_path == path, 'predecessor reference is not the original runner manifest')
    require(manifest['schema'] == 'tcad-native-run-r2' and manifest['run_id'] == run_id
            and manifest['origin'] == 'native_pipeline' and manifest['synthetic'] is False
            and Path(manifest['project_directory']) == workspace_path(workspace, intent['project'])
            and manifest['input_sha256'] == admission['input_sha256'] == intent['input_sha256'],
            'manifest identity or frozen inputs differ')
    return pin, manifest


def bound_admission(workspace, task_id, intent, manifest_sha, scope):
    binding = intent['scientific_admission']
    _, admission = reference(workspace, binding['admission'])
    require(binding['scope'] == admission['scope'] == scope
            and binding['manifest_sha256'] == manifest_sha
            and intent['backend'] == admission['backend'] == 'tcad'
            and admission['task_id'] == task_id and admission['project'] == intent['project'],
            'formal admission differs from the runner binding')
    return binding['admission'], admission


def threshold_admission(workspace, task_id, intent, manifest_sha, cases):
    pin, admission = bound_admission(workspace, task_id, intent, manifest_sha, PRODUCTION)
    case = cases[admission['case_id']]
    require(admission['schema'] == 'tcad-r06-production-admission-v1'
            and intent['scientific_admission']['case_id'] == admission['case_id']
            and admission['manifest_sha256'] == manifest_sha and admission['block'] == case['block'] == 'T'
            and all(admission[key] == case[key] for key in (
                'profile_id', 'radiation_id', 'stored_bit', 'scale_factor'
            )), 'formal threshold admission differs from the frozen case')
    return pin, admission, case


def timestamp(value):
    require(isinstance(value, str), 'timestamp is missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() is not None, 'timestamp has no time zone')
    return result.astimezone(UTC)


def utc_text(value, timespec='seconds'):
    return value.isoformat(timespec=timespec).replace('+00:00', 'Z')


def observed_launch(manifest, now):
    # The runner sets started_utc before upload. Its wrapper prints `date -u`
    # after recording ACTIVE and setting affinity, immediately before the tools.
    observation = manifest['last_observation']
    identity = manifest['process_identity']
    require(observation['run_id'] == identity['run_id'] == manifest['run_id']
            and observation['status'] in ('RUNNING', 'FINISHED', 'LOST_WITHOUT_EXIT')
            and identity['schema'] == 'tcad-process-identity-r1'
            and identity['cwd'] == manifest['remote_directory']
            and identity['script_sha256'] == manifest['script_sha256']
            and all(type(identity[key]) is int and identity[key] > 0 for key in ('pid', 'start_ticks')),
            'no verified launch identity')
    log_tail = observation.get('log_tail')
    require(isinstance(log_tail, str), 'original launch log is unavailable')
    lines = log_tail.splitlines()
    require(len(lines) >= 4 and lines[0].startswith('{'), 'original ACTIVE launch marker is unavailable')
    active = json.loads(lines[0])
    require(active['state'] == 'ACTIVE' and active['script_sha256'] == manifest['script_sha256']
            and all(identity[key] == active['identity'][key] == observation['identity'][key]
                    for key in IDENTITY_FIELDS), 'ACTIVE launch marker identity differs')
    pid = identity['pid']
    date_index = 1
    if lines[1].startswith(f"pid {pid}'s current affinity list: "):
        require(lines[2].startswith(f"pid {pid}'s new affinity list: "), 'launch affinity record is incomplete')
        date_index = 3
    match = WRAPPER_DATE.fullmatch(lines[date_index])
    require(match is not None, 'original UTC launch timestamp is unavailable')
    month, day, hour, minute, second, year = match.groups()
    launched = datetime(int(year), MONTHS.index(month) + 1, int(day), int(hour), int(minute), int(second), tzinfo=UTC)
    observed = timestamp(observation['observed_utc'])
    require(timestamp(manifest['started_utc']) < launched + timedelta(seconds=1)
            and launched <= observed <= now, 'launch timestamps are out of order')
    return launched


def collected_record(workspace, intent, admission, pin=None):
    manifest_pin, archive = native_manifest(workspace, intent, admission, pin)
    require(archive['state'] == 'COLLECTED' and archive['collection_verified'] is True
            and archive['parallel_slot_released'] is True
            and archive['remote_exit_code'] == archive['collection_exit_code'] == 0
            and re.fullmatch(r'[0-9a-f]{64}', archive['results_sha256']), 'original archive is not verified')
    collected = timestamp(archive['collected_utc'])
    require(timestamp(archive['started_utc']) <= collected, 'archive timestamps are out of order')
    return archive, {
        'task_id': admission['task_id'], 'run_id': archive['run_id'],
        'case_id': admission.get('case_id'), 'collected_at': utc_text(collected, 'auto'),
        'manifest': manifest_pin,
        'results_sha256': archive['results_sha256'],
    }


def required_zero(workspace, intents, admission, manifest_sha, observation_pin=None):
    task_id = admission['matched_zero_task_id']
    intent = intents[task_id]
    pin, zero = bound_admission(workspace, task_id, intent, manifest_sha, 'p0_diagnostic')
    protocol_pin = {'path': (Path(intent['project']) / 'protocol.json').as_posix(),
                    'sha256': intent['input_sha256']['protocol.json']}
    _, protocol = reference(workspace, protocol_pin)
    source = protocol['source']
    require(zero['schema'] == 'tcad-r06-p0-admission-v1' and zero['recipe_id'] == 'zero_whr'
            and zero['profile_id'] == protocol['profile_id'] == admission['profile_id']
            and type(protocol['stored_bit']) is int and protocol['stored_bit'] == admission['stored_bit']
            and source.get('event_id') is None,
            'zero control does not match the required profile and stored bit')
    if observation_pin is None:
        require(source['required_source_rows'] == source['required_allocations'] == 0, 'zero input is not empty')
        _, row = collected_record(workspace, intent, zero)
        return dict(row, admission=pin, protocol=protocol_pin)
    _, observation = reference(workspace, observation_pin)
    archive, row = collected_record(workspace, intent, zero, observation['native_manifest'])
    table = observation['source']['table']
    require(observation['schema'] == 'tcad-r06-hold22-zero-observation-v1'
            and observation['task_id'] == task_id and observation['profile_id'] == zero['profile_id']
            and observation['stored_bit'] == protocol['stored_bit']
            and observation['manifest_sha256'] == row['manifest']['sha256']
            and all(observation[key] == archive[key] for key in ('run_id', 'input_sha256', 'results_sha256'))
            and table['rows'] == table['allocations'] == 0
            and table['source_sha256'] == archive['input_sha256']['nodal-source.dat'],
            'native zero observation differs from the required zero archive')
    return dict(row, admission=pin, protocol=protocol_pin, zero_observation=observation_pin)


def frozen_dependencies(workspace, proposal, intent, admission_pin):
    # Runtime hashes the normalized task and ignores other proposal metadata.
    task = {key: proposal[key] for key in ('id', 'backend', 'project')}
    task['project'] = workspace_path(workspace, task['project']).relative_to(workspace).as_posix()
    task.update({key: proposal.get(key, default) for key, default in (
        ('depends_on', []), ('requires', []), ('repair_of', None), ('repair_reason', ''), ('adopt_run_id', None)
    )})
    for key in ('wave_admission_sha256', 'supply_input_digest', 'priority'):
        if key in proposal:
            task[key] = proposal[key]
    raw = json.dumps(task, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    require(hashlib.sha256(raw).hexdigest() == intent['task_digest']
            and task.get('wave_admission_sha256', admission_pin['sha256']) == admission_pin['sha256'],
            'proposal dependencies differ from the submitted task')
    deps = task['depends_on']
    require(isinstance(deps, list) and len(deps) == len(set(deps)), 'invalid proposal dependencies')
    return set(deps)


def acceptance_references(source_pin, source, proof, successor):
    keys = {'prior_acceptance', 'source_acceptance'} & source.keys()
    if keys:
        require(source['case_id'] == successor['case_id']
                and source['source_primary_id'] == proof['source_primary_id'],
                'decision does not bind the successor case and primary')
        refs = []
        for key in sorted(keys):
            value = source[key]
            for pin in value if isinstance(value, list) else [value]:
                if pin not in refs:
                    refs.append(pin)
        require(refs, 'decision has no prior acceptances')
        return refs, None
    if source.get('schema') == 'tcad-r06-threshold-followup-decision-v1':
        require(source['next_case'] == successor['case_id'] and source['next_scale'] == successor['scale_factor']
                and source['same_primary'] == proof['source_primary_id'],
                'legacy decision does not bind the successor case and primary')
        return [source['acceptance']], None
    if proof.get('schema') == 'tcad-r06-month-one-response-v1' and source.get('schema') == 'tcad-r06-production-admission-v1':
        # This producer pins the prior admission, manifest, acceptance and pair in order.
        prior_pin, archive_pin, acceptance_pin, pair_pin = proof['evidence'][:4]
        require(source_pin == prior_pin, 'provenance does not bind the prior admission')
        return [acceptance_pin], (prior_pin, archive_pin, pair_pin)
    return [], None


def accepted_predecessor(workspace, intents, by_run, case, successor, primary, pin, legacy, manifest_sha, cases):
    _, accepted = reference(workspace, pin)
    task_id = by_run[accepted['run_id']]
    intent = intents[task_id]
    admission_pin, prior, prior_case = threshold_admission(workspace, task_id, intent, manifest_sha, cases)
    _, prior_proof = reference(workspace, prior['event_provenance'])
    require(accepted['schema'] == 'tcad-r06-case-acceptance-v1' and accepted['status'] == 'accepted'
            and accepted['block'] == 'T' and accepted['manifest_sha256'] == manifest_sha
            and type(accepted['readout_error']) is int and accepted['readout_error'] in (0, 1)
            and accepted['case_id'] == prior['case_id']
            and all(accepted[key] == prior[key] for key in (
                'profile_id', 'radiation_id', 'stored_bit', 'event_id', 'scale_factor'
            ))
            and all(prior_case[key] == case[key] for key in COORDINATES)
            and all(accepted[key] == prior_case[key] for key in ('source_time_ns', 'deck_timing_version'))
            and prior['event_id'] == successor['event_id'] == prior_proof['event_id']
            and prior_proof['case_id'] == prior['case_id'] and prior_proof['source_primary_id'] == primary,
            'prior acceptance does not prove the required threshold event')
    archive, row = collected_record(workspace, intent, prior, legacy[1] if legacy else None)
    require(all(accepted[key] == archive[key] for key in ('run_id', 'input_sha256', 'results_sha256')),
            'prior acceptance differs from the verified archive')
    zero_task = prior['matched_zero_task_id']
    _, zero = bound_admission(workspace, zero_task, intents[zero_task], manifest_sha, 'p0_diagnostic')
    zero_archive, _ = collected_record(workspace, intents[zero_task], zero)
    require(accepted['matched_zero_run_id'] == zero_archive['run_id']
            and accepted['matched_zero_results_sha256'] == zero_archive['results_sha256']
            and (prior['stored_bit'] != successor['stored_bit'] or zero_task == successor['matched_zero_task_id']),
            'prior acceptance differs from the original matched zero')
    row.update(admission=admission_pin, acceptance=pin)
    if legacy:
        prior_pin, archive_pin, pair_pin = legacy
        _, pair = reference(workspace, pair_pin)
        require(prior_pin == admission_pin
                and pair['schema'] == 'tcad-r06-development-pair-observation-v1' and pair['width'] == 1
                and pair['case_id'] == prior['case_id'] and pair['event']['task_id'] == task_id
                and pair['event']['manifest_sha256'] == archive_pin['sha256']
                and all(pair['event'][key] == archive[key] for key in ('run_id', 'input_sha256', 'results_sha256')),
                'legacy paired readout differs from the accepted archive')
        row['paired_readout'] = pair_pin
    return row


def anchor_collections(workspace, intents, by_run, case, successor, proof, plan_pin, cases):
    manifest_sha = plan_pin['sha256']
    pin = proof['source_acceptance']
    _, accepted = reference(workspace, pin)
    task_id = by_run[accepted['run_id']]
    intent = intents[task_id]
    admission_pin, prior, prior_case = threshold_admission(workspace, task_id, intent, manifest_sha, cases)
    _, prior_proof = reference(workspace, prior['event_provenance'])
    require(case['stored_bit'] == proof['stored_bit'] == 0 and prior_case['stored_bit'] == 1
            and prior_case['scale_factor'] == case['scale_factor'] == proof['scale_factor']
            and all(prior_case[key] == case[key] for key in COORDINATES)
            and proof['source_shape_id'] == case['source_shape_id']
            and proof['source_run_id'] == intent['run_id']
            and proof['matched_zero_task_id'] == successor['matched_zero_task_id']
            and prior_proof['case_id'] == prior['case_id']
            and prior_proof['source_primary_id'] == proof['source_primary_id']
            and prior['event_id'] == successor['event_id']
            and accepted['case_id'] == prior['case_id']
            and accepted['schema'] == 'tcad-r06-case-acceptance-v1' and accepted['status'] == 'accepted'
            and accepted['block'] == 'T' and accepted.get('manifest_sha256', manifest_sha) == manifest_sha
            and type(accepted['readout_error']) is int and accepted['readout_error'] in (0, 1),
            'b0 anchor does not bind an accepted same-scale b1 case and primary')
    expected = {key: prior[key] for key in ('profile_id', 'radiation_id', 'stored_bit', 'event_id', 'scale_factor')}
    expected.update({key: prior_case[key] for key in ('source_time_ns', 'deck_timing_version')})
    require(all(accepted.get(key, value) == value for key, value in expected.items()),
            'legacy acceptance conflicts with the bound b1 case')

    zero_run_id = accepted['matched_zero_run_id']
    zero_task = by_run[zero_run_id]
    require(prior.get('matched_zero_task_id', zero_task) == zero_task
            and prior.get('matched_zero_run_id', zero_run_id) == zero_run_id
            and (prior.get('matched_zero_task_id') == zero_task or prior.get('matched_zero_run_id') == zero_run_id),
            'original b1 admission does not bind its accepted zero')
    zero_intent = intents[zero_task]
    _, zero = bound_admission(workspace, zero_task, zero_intent, manifest_sha, 'p0_diagnostic')
    archive, event_row = collected_record(workspace, intent, prior)
    zero_archive, zero_row = collected_record(workspace, zero_intent, zero)
    require(all(accepted[key] == archive[key] for key in ('run_id', 'input_sha256', 'results_sha256'))
            and accepted['matched_zero_results_sha256'] == zero_archive['results_sha256']
            and proof['source_table_sha256'] == archive['input_sha256']['nodal-source.dat']
            == successor['input_sha256']['nodal-source.dat'], 'b0 source table or original result binding differs')

    # Even when a legacy acceptance omits fields, both documents pin a same-plan review.
    independent_pins = [item for item in proof['evidence'] if Path(item['path']).name == task_id + '-independent.json']
    require(len(independent_pins) == 1, 'b0 anchor lacks a unique independent b1 review')
    independent_pin = independent_pins[0]
    independent_path, independent = reference(workspace, independent_pin)
    require(any(item['sha256'] == independent_pin['sha256'] and workspace_path(workspace, item['path']) == independent_path
                for item in accepted['evidence'])
            and independent['schema'] == 'tcad-r06-write1-native-independent-read-v1'
            and independent['manifest'] == plan_pin and independent['case_id'] == prior['case_id'],
            'b0 anchor lacks independent evidence for this plan and b1 case')
    pair_pin = independent['original_observation']
    _, pair = reference(workspace, pair_pin)
    require(pair['schema'] == 'tcad-r06-development-pair-observation-v1' and pair['case_id'] == prior['case_id'],
            'independent evidence refers to a different b1 pair')
    for member, record, row in (('event', archive, event_row), ('zero', zero_archive, zero_row)):
        reconstruction = independent['reconstructed'][member]
        observation = pair[member]
        require(reconstruction['run_id'] == record['run_id'] and reconstruction['archive_sha256'] == record['results_sha256']
                and observation['task_id'] == row['task_id'] and observation['manifest_sha256'] == row['manifest']['sha256']
                and all(observation[key] == record[key] for key in ('run_id', 'input_sha256', 'results_sha256')),
                'independent b1 review differs from the original archives')

    zero_pins = [item for item in proof['evidence'] if Path(item['path']).name == 'zero-observation.json']
    require(len(zero_pins) == 1, 'b0 anchor lacks a unique native zero observation')
    event_row.update(admission=admission_pin, acceptance=pin, independent_same_plan=independent_pin, paired_readout=pair_pin)
    return [event_row, required_zero(workspace, intents, successor, manifest_sha, zero_pins[0])]


def measure(workspace, intents, by_run, task_id, proposal, plan_pin, cases, now):
    manifest_sha = plan_pin['sha256']
    intent = intents[task_id]
    admission_pin, successor, case = threshold_admission(workspace, task_id, intent, manifest_sha, cases)
    proof_pin = successor['event_provenance']
    proof_path, proof = reference(workspace, proof_pin)
    anchor = proof.get('schema') == ANCHOR_PROVENANCE
    source_pin = proof_pin if anchor else proof.get('source')
    if not anchor:
        if not isinstance(source_pin, dict) or not {'path', 'sha256'} <= source_pin.keys():
            return None
        _, source = reference(workspace, source_pin)
        acceptance_pins, legacy = acceptance_references(source_pin, source, proof, successor)
        if not acceptance_pins:
            return None
    require(proof_path == workspace_path(workspace, Path(intent['project']) / 'provenance.json')
            and proof_pin['sha256'] == successor['input_sha256']['provenance.json']
            and proof['case_id'] == successor['case_id'] and proof['event_id'] == successor['event_id']
            and all(proof[key] == case[key] for key in ('source_time_ns', 'deck_timing_version'))
            and isinstance(proof['source_primary_id'], str) and bool(proof['source_primary_id']),
            'successor provenance does not bind the frozen input and primary')
    deps = frozen_dependencies(workspace, proposal, intent, admission_pin)
    if anchor:
        required = anchor_collections(workspace, intents, by_run, case, successor, proof, plan_pin, cases)
    else:
        required = [accepted_predecessor(workspace, intents, by_run, case, successor, proof['source_primary_id'],
                                         pin, legacy, manifest_sha, cases) for pin in acceptance_pins]
        required.append(required_zero(workspace, intents, successor, manifest_sha))
    required_tasks = {row['task_id'] for row in required}
    require(len(required_tasks) == len(required) and required_tasks == deps and task_id not in required_tasks,
            'proposal dependencies do not match the required acceptances and original zero')
    latest = max(required, key=lambda row: timestamp(row['collected_at']))
    collected = timestamp(latest['collected_at'])
    launch_pin, manifest = native_manifest(workspace, intent, successor)
    launched = observed_launch(manifest, now)
    require(collected <= launched, 'collection and launch timestamps are out of order')
    return {
        'task_id': task_id, 'case_id': case['case_id'], 'run_id': manifest['run_id'],
        'prerequisite_case_id': latest['case_id'], 'prerequisite_run_id': latest['run_id'],
        'collected_at': utc_text(collected, 'auto'), 'started_at': utc_text(launched),
        'seconds': int((launched - collected + timedelta(milliseconds=500)).total_seconds()),
        'evidence': {'successor_admission': admission_pin, 'successor_provenance': proof_pin,
                     'source': source_pin, 'task_digest': intent['task_digest'], 'required_collections': required,
                     'successor_manifest': launch_pin,
                     'launch_identity': {key: manifest['process_identity'][key] for key in IDENTITY_FIELDS},
                     'launch_observed_at': manifest['last_observation']['observed_utc'],
                     'launch_field': 'last_observation.log_tail (ACTIVE wrapper UTC date)'},
    }


def summary(scope, samples):
    latest = samples[-1] if samples else {}
    return {'schema': PUBLIC_SCHEMA, 'scope': scope, 'sample_count': len(samples),
            'latest_seconds': latest.get('seconds'), 'latest_started_at': latest.get('started_at')}


def retained_samples(previous, manifest_sha, intents, by_run, now):
    if previous is None:
        return {}
    require(previous['schema'] == SCHEMA, 'refusing to replace an unrelated file')
    previous_plan = previous.get('manifest_sha256')
    if previous_plan is not None and previous_plan != manifest_sha:
        return {}
    retained = {}
    for row in previous['samples'][-MAX_SAMPLES:]:
        run_id = row['run_id']
        if previous_plan is None:
            # The first version stored only the two legacy cases and no plan hash.
            task_id = by_run.get(run_id)
            if task_id is None or not LEGACY_CASE.fullmatch(row['case_id']):
                continue
            binding = intents[task_id]['scientific_admission']
            if (binding['case_id'] != row['case_id'] or binding['manifest_sha256'] != manifest_sha
                    or binding['admission'] != row['evidence']['successor_admission']):
                continue
            row = dict(row, task_id=task_id)
        collected, launched = timestamp(row['collected_at']), timestamp(row['started_at'])
        require(collected <= launched <= now and type(row['seconds']) is int
                and row['seconds'] == int((launched - collected + timedelta(milliseconds=500)).total_seconds()),
                'retained sample timestamps or duration differ')
        retained[run_id] = row
    return retained


def build_snapshot(policy_path, now=None, previous=None):
    now = now or datetime.now(UTC)
    policy = read(policy_path)
    require(policy['schema'] == 'tcad-server-codex-v2', 'unsupported runtime policy')
    workspace = Path(policy['workspace']).resolve()
    _, contract = reference(workspace, policy['scientific_gate']['contract'])
    manifest_sha = contract['manifest']['sha256']
    plan_pin = contract['manifest']
    _, plan = reference(workspace, plan_pin)
    cases = {row['case_id']: row for row in plan['cases'] if row['block'] == 'T'}
    runtime = read(Path(policy['state_dir']) / 'runtime.json')
    require(runtime['schema'] == 'tcad-autonomy-intents-v1', 'unsupported runtime ledger')
    intents = runtime['intents']
    by_run = {}
    for task_id, intent in intents.items():
        run_id = intent['run_id']
        require(run_id not in by_run, 'duplicate original run ID in runtime ledger')
        by_run[run_id] = task_id
    retained = retained_samples(previous, manifest_sha, intents, by_run, now)
    queue = read(workspace_path(workspace, policy['queue_file']))
    require(queue['schema'] == 'tcad-work-items-v1', 'unsupported proposal queue')
    proposals = {row['id']: row for row in queue['tasks']}
    require(len(proposals) == len(queue['tasks']), 'duplicate proposal task ID')
    skipped = []
    for task_id, intent in sorted(intents.items()):
        binding = intent.get('scientific_admission') or {}
        if (binding.get('scope') != PRODUCTION or binding.get('case_id') not in cases
                or intent['run_id'] in retained):
            continue
        try:
            row = measure(workspace, intents, by_run, task_id, proposals.get(task_id, {}), plan_pin, cases, now)
            if row is not None:
                retained[row['run_id']] = row
        except (OSError, KeyError, TypeError, ValueError) as error:
            skipped.append({'task_id': task_id, 'reason': str(error)[:300]})
    ordered = sorted(retained.values(), key=lambda row: (row['started_at'], row['case_id'], row['run_id']))
    legacy = [row for row in ordered if LEGACY_CASE.fullmatch(row['case_id'])][-MAX_SAMPLES:]
    other = [row for row in ordered if not LEGACY_CASE.fullmatch(row['case_id'])]
    slots = MAX_SAMPLES - len(legacy)
    selected = {row['run_id'] for row in legacy + (other[-slots:] if slots else [])}
    samples = [row for row in ordered if row['run_id'] in selected]
    return {
        'schema': SCHEMA, 'manifest_sha256': manifest_sha, 'generated_at': utc_text(now),
        'samples': samples, 'skipped': skipped[:MAX_SAMPLES],
        'public_summary': summary(SCOPE, legacy),
        'threshold_followup_summary': summary(FOLLOWUP_SCOPE, samples),
    }


def write_snapshot(output, snapshot):
    require(not output.is_symlink(), 'output must be a regular private snapshot path')
    if output.exists():
        require(read(output).get('schema') == SCHEMA, 'refusing to replace an unrelated file')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(snapshot, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.close()
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.output.is_symlink(), 'output must be a regular private snapshot path')
        previous = read(args.output) if args.output.exists() else None
        write_snapshot(args.output, build_snapshot(args.policy, previous=previous))
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f'refill timing: {error}\n')


if __name__ == '__main__':
    main()
