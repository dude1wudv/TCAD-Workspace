"""Stage approved r0.6 native transport pools from frozen preparation snapshots."""

from datetime import datetime
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from month_one_wave import ANCHORS, _install, _json_bytes, _reference


INPUT_ROOT = 'local_runtime/cloud-benchmark/geant4-preparation/inputs'
DRAFT_ROOT = 'local_runtime/server-codex/month-one-transport'
NATIVE_SCHEMA = 'dram-se-r06-native-transport-request-v1'
POOL_SCHEMA = 'tcad-r06-transport-request-v1'
ENGINE_SHA = 'c622d52da1899eae1689329ea4556f57e2536a0dc62da33a3423118eb4177df6'
LHS_FINE_NAVIGATION_ENGINE_SHA = '86b2ac4ea716b6b878e172b34eeaccc597962c0abaa953d6361922612dd5232f'
INPUT_FILES = {'transport_l08.cc', 'task.sh', 'geometry.json', 'geometry.hh', 'request.json',
               'input-hashes.sha256'}
INVALID = (OSError, ValueError, KeyError, TypeError, AttributeError)


def _claimed_pools(work, gate, contract, profiles, known, intents):
    claimed = set()
    for intent in intents.values():
        scientific = intent.get('scientific_admission') or {}
        pool = scientific.get('pool') or (scientific.get('scientific_object') or {}).get('pool')
        if isinstance(pool, (list, tuple)) and len(pool) == 2:
            claimed.add(tuple(pool))

    for task_id, record in sorted((known | intents).items()):
        task = known.get(task_id, {}) | record
        if task.get('backend') != 'geant4':
            continue
        admission = gate.path_at(work, f'{contract["production_admissions_dir"]}/{task_id}.json')
        if admission.is_file():
            document = gate.read(admission)
            if document.get('scope') == 'transport_pool':
                profile = profiles[document['profile_id']]
                claimed.add((profile['crn_group_id'], document['radiation_id']))
        if not task.get('project'):
            continue
        path = gate.path_at(work, task['project'] + '/request.json')
        if path.is_file():
            native = gate.read(path)
            if native.get('schema') == NATIVE_SCHEMA:
                claimed.add((native['crn_group_id'], native['radiation_id']))
    return claimed


def _catalog(work, gate, contract, refs):
    gate.need(isinstance(refs, list) and refs, 'expected frozen transport preparations')
    manifest_sha = contract['manifest']['sha256']
    candidates = []
    for reference in refs:
        receipt = gate.read_reference(work, reference)
        gate.need(receipt.get('manifest_sha256') == manifest_sha
                  and receipt.get('artifact_role') == 'offline_input_preparation'
                  and receipt.get('scope') == 'development', 'transport preparation differs from the plan')
        preflight_ref = receipt['preflight']
        preflight = gate.read_reference(work, preflight_ref)
        gate.need(preflight.get('source_manifest') == contract['manifest'], 'transport preflight manifest differs')
        priority = receipt.get('priority', 1)
        allowed = {(row['crn_group_id'], row['radiation_id'], frozenset(row['profile_ids']))
                   for row in preflight['transport_pools'] if row['priority'] == priority}
        rows = receipt['pools']
        gate.need(priority in (1, 2) and isinstance(rows, list) and 0 < len(rows) <= 24,
                  'invalid transport preparation batch')
        candidates.extend((priority, row, reference, preflight_ref, allowed) for row in rows)
    return sorted(candidates, key=lambda candidate: candidate[0])


def _profile_request(work, gate, contract, requests, settings, p0_refs, qualifications):
    for request in requests:
        profile_id = request['profile_id']
        if profile_id not in settings.get('profiles', ANCHORS) or profile_id not in p0_refs:
            continue
        p0_ref = p0_refs[profile_id]
        if profile_id not in qualifications:
            try:
                qualified = gate.common_gate(work, contract, {'p0_gate': p0_ref})
                gate.qualified_profile(work, qualified, profile_id)
                qualifications[profile_id] = None
            except INVALID as exc:
                qualifications[profile_id] = str(exc)
        if qualifications[profile_id] is None:
            return request, p0_ref
    reasons = ', '.join(qualifications[request['profile_id']] for request in requests
                        if qualifications.get(request['profile_id']))
    raise ValueError(reasons or 'no enabled profile with a pinned P0 qualification')


def _verify_inputs(work, gate, row, radiation, request, manifest_sha, profile_ids):
    project = gate.path_at(work, row['project'])
    native_ref = request['native_request']
    pins = row['input_sha256']
    profile_id = request['profile_id']
    exact_lhs = profile_ids == {profile_id} and re.fullmatch(r'LHS0[1-6]-development', profile_id)
    engine_sha = LHS_FINE_NAVIGATION_ENGINE_SHA if exact_lhs else ENGINE_SHA
    gate.need(set(pins) == INPUT_FILES and pins['transport_l08.cc'] == engine_sha
              and pins == gate.input_hashes(project), 'original native project missing or changed')
    gate.need(native_ref == {'path': row['project'] + '/request.json', 'sha256': pins['request.json']},
              'native request belongs to another project')
    native = gate.read_reference(work, native_ref)
    gate.need(native.get('schema') == NATIVE_SCHEMA and native.get('id') == row['task_id']
              and native.get('manifest_sha256') == manifest_sha
              and set(native['profile_ids']) == profile_ids and native.get('particle') == 'proton'
              and (native.get('incident_energy_MeV'), native.get('theta_deg'), native.get('phi_deg'))
              == (radiation['energy_MeV'], radiation['theta_deg'], radiation['phi_deg'])
              and all(native.get(field) == request[field] for field in ('seed', 'crn_group_id', 'radiation_id'))
              and native.get('geometry_sha256') == pins['geometry.json']
              and native.get('event_count') == request['primary_count'] == 100000
              and type(request['seed']) is int
              and native['source_plane']['area_cm2'] == request['source_area_cm2'] > 0
              and all(native.get(field) is request.get(field) is True for field in
                      ('uniform_source_area_sampling', 'retain_zero_deposition_primaries')),
              'native request differs from the frozen development pool')
    header = (project / 'geometry.hh').read_bytes()
    gate.need(f'contract_sha256="{pins["request.json"]}";'.encode() in header,
              'compiled request SHA differs from the frozen request')
    runner = (project / 'task.sh').read_bytes()
    gate.need(b'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\n' in runner
              and f'./transport_l08 {row["task_id"]} >'.encode() in runner,
              'original single-thread runner binding differs')


def _navigation_evidence(gate, catalog, row, profile_id):
    if 'lhs_navigation' not in catalog or not re.fullmatch(r'LHS0[1-6]-development', profile_id):
        return []
    navigation = catalog['lhs_navigation']
    gate.need(navigation is not None, 'missing native navigation evidence')
    evidence = navigation['report'].get(row['task_id'])
    gate.need(evidence is not None, 'missing native navigation evidence for this pool')
    gate.need(evidence.get('status') == 'passed' and evidence.get('profile_id') == profile_id
              and evidence.get('input_sha256') == row['input_sha256'],
              'native navigation evidence differs from the frozen pool')
    return [navigation['reference']]


def _draft(work, gate, contract, task, row, request, evidence, p0_ref, created_at):
    root = gate.path_at(work, DRAFT_ROOT + '/' + task['id'])
    request_raw = _json_bytes(request)
    request_ref = _reference(work, root / 'pool-request.json', request_raw)
    admission = dict(schema='tcad-r06-production-admission-v1', plan_id=contract['plan_id'],
                     revision=contract['revision'], owner=contract['owner'], backend='geant4',
                     scope='transport_pool', task_id=task['id'], project=task['project'],
                     created_at=created_at, profile_id=request['profile_id'], radiation_id=request['radiation_id'],
                     pool_request=request_ref, input_sha256=row['input_sha256'],
                     manifest_sha256=contract['manifest']['sha256'], p0_gate=p0_ref)
    admission_raw = _json_bytes(admission)
    official = gate.path_at(work, f'{contract["production_admissions_dir"]}/{task["id"]}.json')
    gate.need(not official.exists() or (official.is_file() and official.read_bytes() == admission_raw),
              'official admission conflicts with the frozen transport draft')
    artifacts = {'pool-request': request_raw,
                 'proposal': _json_bytes({'schema': 'tcad-work-items-v1', 'tasks': [task]}),
                 'admission': admission_raw}
    result = {'evidence': [*evidence, p0_ref, request_ref, request['native_request']]}
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.draft-', dir=root) as folder:
        for name, raw in artifacts.items():
            filename = name + '.json'
            staged = Path(folder) / filename
            target = gate.path_at(work, (root / filename).relative_to(work).as_posix())
            staged.write_bytes(raw)
            _install(gate, staged, target)
            if name != 'pool-request':
                result[name] = _reference(work, target, raw)
    return result


def prepare(work, gate, contract, manifest, known, intents, settings, limit):
    """Use settings['transport'] with preparations, p0_gates by profile, and a fixed created_at."""
    if limit <= 0:
        return [], {}
    entries, blocked = [], {}
    try:
        catalog = settings['transport']
        created_at = catalog['created_at']
        gate.need(datetime.fromisoformat(created_at.replace('Z', '+00:00')).utcoffset() is not None,
                  'transport catalog requires a timezone-aware creation time')
        gate.referenced(work, contract['authority'])
        profiles = {row['id']: row for row in manifest['profiles']}
        radiations = {row['id']: row for row in manifest['radiations']}
        pools = {(row['crn_group_id'], row['radiation_id']) for row in manifest['cases']
                 if row['block'] != 'AL' and row.get('radiation_id') is not None}
        candidates = _catalog(work, gate, contract, catalog['preparations'])
        claimed = _claimed_pools(work, gate, contract, profiles, known, intents)
        projects = {row['project'] for row in (*known.values(), *intents.values()) if row.get('project')}
    except INVALID as exc:
        return [], {'transport': str(exc)[:200]}

    qualifications = {}
    for _, row, receipt, preflight, allowed in candidates:
        if len(entries) >= limit:
            break
        key = row.get('task_id', 'transport')
        try:
            requests = row['pool_request_candidates']
            pool, = {(request['crn_group_id'], request['radiation_id']) for request in requests}
            if pool in claimed or key in known or key in intents or row['project'] in projects:
                continue
            if key in settings.get('skip_task_ids', ()):
                continue
            gate.need(re.fullmatch(r'r06-(?!p0-)[a-z0-9-]{1,92}', key)
                      and row['project'] == f'{INPUT_ROOT}/{key}', 'invalid transport task or project identity')
            profile_ids = frozenset(request['profile_id'] for request in requests)
            radiation = radiations[pool[1]]
            gate.need(len(profile_ids) == len(requests) and (pool[0], pool[1], profile_ids) in allowed
                      and pool in pools and (radiation['role'], radiation['particle']) == ('development', 'proton')
                      and all(profiles[profile_id]['partition'] == 'development'
                              and profiles[profile_id]['crn_group_id'] == pool[0] for profile_id in profile_ids),
                      'pool outside the authorized development preflight')
            request, p0_ref = _profile_request(work, gate, contract, requests, settings,
                                               catalog['p0_gates'], qualifications)
            gate.need(request.get('schema') == POOL_SCHEMA, 'transport pool request schema differs')
            navigation = _navigation_evidence(gate, catalog, row, request['profile_id'])
            _verify_inputs(work, gate, row, radiation, request, contract['manifest']['sha256'], profile_ids)
            task = dict(id=key, backend='geant4', project=row['project'], depends_on=[], requires=[])
            entries.append(_draft(work, gate, contract, task, row, request, [receipt, preflight, *navigation],
                                  p0_ref, created_at))
            claimed.add(pool)
        except INVALID as exc:
            blocked[str(key)] = str(exc)[:200]
    return entries, blocked
