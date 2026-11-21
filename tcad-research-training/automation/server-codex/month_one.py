"""Private read-only index of the frozen r0.6 cases. Never schedules or accepts a case."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def project(policy, gate, case_id=None, now=None):
    work = Path(policy['workspace'])
    state = Path(policy['state_dir'])
    settings = policy['scientific_gate']
    contract = gate.read_reference(work, settings['contract'])
    gate.envelope(contract, 'tcad-r06-scientific-gate-contract-v1')
    manifest = gate.read_reference(work, contract['manifest'])
    cases = {c['case_id']: c for c in manifest['cases']}
    if case_id is not None and case_id not in cases:
        raise ValueError('Unknown frozen case ID')
    admissions = gate.path_at(work, contract['production_admissions_dir'])
    queue = {t['id']: t for t in gate.read(policy['queue_file'])['tasks']}
    ledger = state / 'runtime.json'
    intents = gate.read(ledger)['intents'] if ledger.is_file() else {}
    obs_file = state / 'observation.json'
    obs = gate.read(obs_file) if obs_file.exists() else {}
    pending = {t['id']: t for t in obs.get('pending_tasks', [])}
    runs = {r['id']: r for r in obs.get('runs', [])}
    deferred = set(settings.get('deferred_task_ids', []))
    grouped = defaultdict(list)
    pools = defaultdict(list)
    # For submitted tasks use the intent's frozen binding, not the current proposal.
    for key, intent in intents.items():
        admission = intent.get('scientific_admission') or {}
        pool = admission.get('pool')
        if admission.get('scope') == 'transport_pool' and isinstance(pool, list) and len(pool) == 2:
            pools[tuple(pool)].append({'task_id': key, 'run_id': intent['run_id'],
                                       'request_sha256': (admission.get('scientific_object') or {}).get('pool_request_sha256')})
        cid = admission.get('case_id')
        if cid in cases:
            run = runs.get(key, {})
            same = run.get('run_id') == intent['run_id']
            grouped[cid].append({'task_id': key, 'run_id': intent['run_id'],
                                 'repair_of': intent.get('repair_of'),
                                 'observed_status': run.get('status') if same else None})
    for key, task in queue.items():
        if key in intents or key in deferred or task['backend'] != 'tcad' or key.startswith('r06-p0-'):
            continue
        file = gate.path_at(work, contract['production_admissions_dir'] + '/' + key + '.json')
        if not file.is_file():
            continue
        doc = gate.read(file)
        if (doc.get('task_id') != key or doc.get('project') != task['project'] or
                doc.get('manifest_sha256') != contract['manifest']['sha256']):
            continue  # Not a binding to this task and frozen plan.
        cid = doc.get('case_id')
        if cid in cases:
            wait = pending.get(key, {})
            grouped[cid].append({'task_id': key, 'run_id': None,
                                 'observed_reason': wait.get('reason'), 'detail': wait.get('detail')})
    rows = []
    for cid, c in cases.items():
        if case_id and case_id != cid:
            continue
        attempts = grouped[cid]
        kind = 'z-baseline-reuse' if c['block'] == 'Z' else 'case-acceptance'
        record_path = gate.path_at(work, (admissions.parent / 'results' / kind / (cid + '.json')).relative_to(work.resolve()).as_posix())
        recorded = gate.read(record_path) if record_path.exists() else None
        if recorded is not None:
            status = 'evidence_record_to_verify' if recorded.get('case_id') == cid else 'evidence_identity_conflict'
        elif any(t['run_id'] for t in attempts):
            status = 'claimed'
        elif attempts:
            status = 'proposed'
        elif c.get('holdout') is not None or c['block'] in ('HR', 'HP'):
            status = 'holdout_not_claimed'
        elif c['block'] == 'AL':
            status = 'await_acquisition'
        else:
            status = 'not_bound'
        rows.append({'case_id': cid, 'block': c['block'], 'profile_id': c.get('profile_id'),
                     'state': status, 'attempts': attempts,
                     'related_transport_intents': pools.get((c.get('crn_group_id'), c.get('radiation_id')), [])})
    stamp = obs.get('utc')
    age = None
    if stamp:
        dt = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if dt.tzinfo is not None:
            age = ((now or datetime.now(timezone.utc)) - dt).total_seconds()
    fresh = age is not None and 0 <= age <= max(30, policy.get('poll_interval_seconds', 5) * 3)
    return {'schema': 'tcad-r06-month-one-index-v1', 'manifest_sha256': contract['manifest']['sha256'],
            'plan_cases': len(cases), 'observation_utc': stamp, 'observation_fresh': fresh,
            'pause_marker_present': (state / 'pause.json').exists(),
            'pending_reasons_at_observation': dict(Counter(
                'legacy_deferred' if key in deferred else x['reason'] for key, x in pending.items())),
            'case_states': dict(Counter(r['state'] for r in rows)), 'cases': rows,
            'semantics': 'Private preparation index, not a submission decision, live solver count or scientific acceptance'}
