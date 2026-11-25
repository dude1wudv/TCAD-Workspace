"""Prepare LHS responses against the immutable native pools and original queue."""

import argparse
from collections import Counter
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace


WORK = Path.cwd()
EXPERIMENT = WORK / 'experiments/dram-se-r06/development-transport-first-wave-r1'
PRIVATE = WORK / 'local_runtime/server-codex'
BASE = PRIVATE / 'r06-full-supply-lhs-r1'
OUTPUT = PRIVATE / 'r06-lhs-response-supply-r1'
EXISTING = PRIVATE / 'r06-lhs02-response-handoff-r1'
RELEASE = Path('/opt/tcad-autonomy/current')

sys.path[:0] = [str(RELEASE), str(PRIVATE), str(EXPERIMENT)]
import geant4_archive
import month_one_draw as draw
import month_one_response as response
import month_one_supply as supply
import month_one_wave as wave
import r06_gate as gate
import scheduler_supply
import stage_lhs02_responses_r1 as staging


ERRORS = (*scheduler_supply.INVALID, ArithmeticError, tarfile.TarError)


def ref(path):
    return staging.ref(path)


def freeze(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    return staging.freeze_file(path, document)


def snapshot(path, document):
    with TemporaryDirectory(dir=path.parent) as directory:
        staged = Path(directory) / path.name
        staged.write_bytes(wave._json_bytes(document))
        staged.replace(path)


def control(catalog, intents, task, profile, bit, mesh_pin):
    intent = intents[task]
    native_path = WORK / catalog['native_runs'] / intent['run_id'] / 'manifest.json'
    native_ref = ref(native_path)
    native, admission, _, _, _, protocol = response._native(WORK, gate, intents, task, native_ref)
    gate.need(admission['recipe_id'] == 'zero_whr' and admission['profile_id'] == profile
              and protocol['stored_bit'] == bit and protocol['source']['source_epoch_ns'] == 22
              and native['input_sha256']['cell_msh.tdr'] == mesh_pin, 'Original zero-control inputs differ')
    return dict(original_task_id=task, original_manifest=native_ref, directory=intent['project'],
                matched_control_collected=True, input_sha256=native['input_sha256'])


def observations(controls, published, catalog, intents):
    result = {}
    for bit, item in controls.items():
        if published:
            path = PRIVATE / f'r06-lhs02-hold22-b{bit}-zero-observation-20261123.json'
            result[bit] = ref(path)
        else:
            task = item['original_task_id']
            result[bit] = draw._zero(WORK, gate, catalog, {'zero_observations': {}, 'zero_tasks': {bit: task}},
                                     intents, bit)
    return result


@lru_cache(maxsize=1)
def load_adapter(path):
    previous = sys.modules.pop('prepare', None)
    try:
        return runpy.run_path(str(path))
    finally:
        if previous is not None:
            sys.modules['prepare'] = previous


def projection_assets(mesh_audit, geometry, mapping):
    adapter = load_adapter(gate.referenced(WORK, mapping['projection_adapter']))
    reader = adapter['mesh_reader']
    prior = gate.read_reference(WORK, mesh_audit['strict_bound_diagnostic'])
    frozen, helpers = reader.reader(prior['task_id'])
    native, raw = reader.load_archive(prior['run_id'], mesh_audit['mesh_manifest']['sha256'],
                                      prior['results_sha256'], frozen, helpers)
    nodes, original_zero = adapter['mesh_zero'].native_nodal_rows(helpers, raw, prior)
    zero = gate.referenced(WORK, mapping['zero_source']).read_bytes()
    silicon = {row['id']: row for row in geometry['regions'] if row['material'] == 'G4_Si'}
    grid = {}
    for name, row in silicon.items():
        bounds = []
        for faces in zip(row['lo_nm'], row['hi_nm'], strict=True):
            native_faces = tuple(Decimal(face).scaleb(-3) for face in faces)
            ticks = tuple(face.quantize(Decimal('0.000001')) for face in native_faces)
            gate.need(all(abs(value - tick) <= Decimal('1e-15')
                          for value, tick in zip(native_faces, ticks, strict=True)),
                      'Native source grid face is off the original lattice')
            bounds.append(ticks)
        grid[name] = adapter['lattice'].edges_from_bounds(bounds, 2)
    projector = SimpleNamespace(**runpy.run_path(str(gate.referenced(WORK, mapping['projector']))))
    mesh = reader.native_mesh(projector, raw, set(silicon))
    gate.need(native['input_sha256']['cell_msh.tdr'] == geometry['mesh_sha256'] == mapping['mesh_sha256']
              and original_zero == zero and adapter['serialize'](mesh, nodes, zero, [], {'rows': []}) == zero,
              'Particle projection does not share the original native grid and zero source')
    return (adapter, projector, mesh, nodes, grid), zero


def audit_pool(policy, contract, settings, known, intents, pool, preparation, navigation):
    candidate, = pool['pool_request_candidates']
    key = [candidate['crn_group_id'], candidate['radiation_id']]
    task, intent, operation = draw._collected(WORK, gate, contract, settings['operations'], key,
                                               pool['task_id'], known, intents)
    nav = navigation['pools'][pool['task_id']]
    gate.need(nav['status'] == 'passed' and nav['input_sha256'] == pool['input_sha256'] == intent['input_sha256']
              and nav['preparation'] == preparation, 'Collected transport differs from native navigation')
    audit = PRIVATE / 'month-one-natural-r1' / intent['run_id'] / 'ledger'
    if not audit.exists():
        ledger = staging.ledger
        binding = gate.read_reference(WORK, preparation)
        raw = gate.referenced(WORK, preparation).read_bytes()
        original_lookup, original_members = ledger.prepared_pool, ledger.MEMBERS
        ledger.prepared_pool = lambda frozen_task: (raw, binding, pool)
        ledger.MEMBERS = tuple(dict.fromkeys((*original_members, *staging.TABLES)))
        try:
            with geant4_archive.materialized_tar(WORK / settings['operations'] / intent['run_id'],
                                                   config_path=policy['result_gdrive_config']):
                report, events = ledger.audit(intent['run_id'], pool['task_id'], task, intent['project'])
        finally:
            ledger.prepared_pool, ledger.MEMBERS = original_lookup, original_members
        deposition = ledger.encode(events).encode()
        report['event_deposition_sha256'] = response._sha(deposition)
        audit.parent.mkdir(exist_ok=True, parents=True)
        staging.install_directory(audit, {'audit.json': ledger.encode(report).encode(),
                                          'event-deposition.json': deposition})
    report = gate.read(audit / 'audit.json')
    gate.need(report['transport_run_id'] == intent['run_id'] and report['archive_sha256'] == operation['archive_sha256']
              and report['input_sha256'] == intent['input_sha256']
              and report['binding_sha256'] == preparation['sha256'], 'Original transport audit differs')
    return audit, intent


def project_cell(policy, catalog, pool, preparation, audit, intent, cell, context, assets, mapping, zero, transient):
    draw_dir, package, projection = (cell / name for name in ('draw', 'package', 'projection'))
    original_lookup = staging.sampler.prepared_pool
    binding_path = gate.referenced(WORK, preparation)
    binding = gate.read(binding_path)
    staging.sampler.prepared_pool = lambda frozen_task: (binding_path.read_bytes(), binding, pool)
    try:
        if not draw_dir.exists():
            profile = pool['pool_request_candidates'][0]['profile_id']
            selected = staging.sampler.freeze(audit, profile, 'S', WORK / context['path'])
            staging.install_directory(draw_dir, {name: staging.ledger.encode(data).encode()
                                                 for name, data in selected.items()})
        if not package.exists():
            operation = WORK / catalog['operations'] / intent['run_id']
            with geant4_archive.materialized_tar(operation, config_path=policy['result_gdrive_config']):
                staging.install_directory(package, staging.packager.package(audit, draw_dir, 'S'))
        if not projection.exists():
            staging.SCHEMA = 'tcad-r06-lhs-development-draw-nodal-offline-v1'
            staging.project(projection, package, assets, mapping, zero, transient)
    finally:
        staging.sampler.prepared_pool = original_lookup
    return ref(projection / 'manifest.json')


def lhs_source(original, gate_module, projection, source, profile):
    if profile not in {f'LHS0{number}-development' for number in range(1, 7)}:
        return original(gate_module, projection, source, profile)
    gate_module.need(projection['schema'] in ('tcad-r06-lhs-development-draw-nodal-offline-v1',
                                              'tcad-r06-lhs02-development-draw-nodal-offline-v1')
                     and projection['condition']['profile_id'] == source['profile_id'] == profile
                     and projection['mesh'] == source and Decimal(source['pair_creation_energy_eV']) == Decimal('3.6'),
                     'LHS projection differs from the pinned original source mapping')
    return source['mesh_sha256'], source['zero_source']['sha256'], Decimal('3.6')


def approved(policy, contract, profile, entries):
    batch = dict(schema=supply.INTAKE_SCHEMA, manifest_sha256=contract['manifest']['sha256'], entries=entries)
    checked = wave.prepare_entries(policy, gate, entries, profiles=wave.ANCHORS | {profile},
                                   post_p2=True, validate_only=True)
    gate.need(not checked['blocked'] and len(checked['prepared']) == len(entries), str(checked['blocked']))
    name = response._sha(wave._json_bytes(batch))[:20]
    return supply.publish_approval(policy, gate, freeze(OUTPUT / 'approved' / f'{name}.json', batch))


def zero_reuse(contract, intents, case, observation, projection, document, event, cell):
    case_id = case['case_id']
    package = gate.read_reference(WORK, document['package'])
    native_event, = (item for item in package['events'] if item['event_id'] == event['event_id'])
    sample, = (item for item in native_event['responses'] if item['case_id'] == case_id)
    selection, mapping = (gate.read_reference(WORK, package['frozen_draw_files'][name])
                          for name in ('selection.json', 'case-draw-map.json'))
    draw_row, = (row for row in mapping['case_draws'] if row['case_id'] == case_id)
    selected, = (row for row in selection['draws'] if (row['event_id'], row['stored_bit']) ==
                 (draw_row['event_id'], draw_row['stored_bit']))
    native_audit = native_event['native_event_audit']
    context = gate.read_reference(WORK, document['response_context'])
    control = gate.read_reference(WORK, context['electrical'])['controls'][str(case['stored_bit'])]
    source = gate.read_reference(WORK, context['source_mapping'])
    observed = gate.read_reference(WORK, observation)
    operation = gate.read_reference(WORK, package['operation'])
    gate.need(native_audit['passed'] is native_audit['zero_si_ionizing'] is True
              and native_event['positive_silicon_steps'] == 0
              and Decimal(native_event['native_silicon_ionizing_energy_eV']) == selected['deposition_energy_eV'] == 0
              and draw_row['event_id'] == sample['event_id'] == event['event_id']
              and native_event['source_primary_id'] == event['source_primary_id']
              and draw_row['stored_bit'] == sample['stored_bit'] == case['stored_bit']
              and sample['inclusion_probability'] == selected['inclusion_probability']
              and mapping['manifest_sha256'] == contract['manifest']['sha256']
              and mapping['selection_sha256'] == package['selection_sha256'] == selection['selection_sha256']
              and selection['response_context_sha256'] == document['response_context']['sha256']
              and package['condition'] == selection['condition'] ==
              {key: case[key] for key in ('profile_id', 'radiation_id')}
              and package['block'] == mapping['block'] == case['block']
              and operation['collection_verified'] is operation['parallel_slot_released'] is True
              and operation['label'] == package['transport_run_id'] == selection['transport_run_id']
              and operation['archive_sha256'] == package['transport_archive_sha256']
              and control['matched_control_collected'] is True
              and control['original_task_id'] == observed['task_id']
              and control['original_manifest'] == observed['native_manifest']
              and control['input_sha256'] == observed['input_sha256']
              and document['mesh'] == source
              and source['mesh_sha256'] == observed['input_sha256']['cell_msh.tdr']
              and source['zero_source']['sha256'] == observed['input_sha256']['nodal-source.dat'],
              'Zero-deposition event, draw, or exact original control differs')
    receipt = response.deferred_zero_receipt(WORK, gate, contract, intents, projection, document,
                                            observation, {case_id: case})
    candidate = cell / f'{case_id}-zero-reuse-candidate.json'
    if candidate.is_file():
        gate.need(receipt == gate.read(candidate), 'Recomputed zero reuse differs from staged evidence')
    return freeze(OUTPUT / 'verified-zero-reuse' / f'{case_id}.json', receipt)


def qualification_runs(work, gate_module, intents, profile, observed):
    candidates = []
    for task, intent in intents.items():
        binding = intent.get('scientific_admission') or {}
        if binding.get('scope') != 'p0_diagnostic' or binding.get('profile_id') not in (None, profile):
            continue
        obj = binding.get('scientific_object') or {}
        if obj.get('profile_id', binding.get('profile_id')) != profile:
            continue
        admission = gate_module.read_reference(work, binding['admission'])
        if admission.get('recipe_id') != 'zero_whr' or 'diagnostic_plan' not in admission:
            continue
        plan = gate_module.read_reference(work, admission['diagnostic_plan'])
        if not plan.get('zero_case_id'):
            continue
        candidates.append(dict(task=task, run_id=intent['run_id'], bit=plan['stored_bit'],
                               plan=admission['diagnostic_plan'], step_ratio=plan.get('step_ratio_to_original_h'),
                               state=observed.get(task, {}).get('status')))
    return candidates


def update_public_progress(rows):
    program = ['/usr/bin/python3', '-B', '/srv/xjtu-shop-site/status-checker/progress_store.py',
               '--db', '/var/lib/xjtu-shop-status/progress.sqlite3']
    prior = {item['case_id']: item for item in json.loads(subprocess.check_output(
        [*program, 'list'], text=True, encoding='utf-8'))}
    for profile in sorted({row['profile'] for row in rows}):
        group = profile.split('-')[0].lower()
        members = [row for row in rows if row['profile'] == profile]
        linked = sum('projection' in row for row in members)
        transported = sum(row['pool_status'] == 'succeeded' for row in members)
        dispositions = Counter(item['status'] for row in members for item in row['cases'].values())
        case = f'r06-z-{group}-development-b0'
        old = prior.get(case, {})
        note = old.get('note') or '八个辐照条件已登记同态对照和粒子源映射。'
        if not members[0]['qualification']:
            next_step = ('八个辐照条件已登记同态对照和源映射。待本组双态零源数值资格，'
                         '签署后自动接续输运，归档后冻结抽样并准备实际事件源。')
        elif transported < len(members):
            next_step = f'输运已归档 {transported} 组。其余输运归档后自动冻结抽样、准备源并按原判据发布。'
        else:
            next_step = (f'已复核 {linked} 组响应源，{dispositions["queued_or_run"]} 项已入原队列，'
                         f'{dispositions["verified_zero_reuse"]} 项零沉积已核对同态对照。')
        if (old.get('note'), old.get('next_step')) != (note, next_step):
            subprocess.run([*program, 'set', '--case', case, '--issue', old.get('issue', 'none'),
                            '--action', old.get('action', 'monitoring'), '--phase', 'validation', '--note', note,
                            '--next-step', next_step, '--evidence', str(OUTPUT / 'response-status.json')],
                           check=True, capture_output=True)


def prepare(policy, args):
    contract = gate.read_reference(WORK, policy['scientific_gate']['contract'])
    manifest = gate.read_reference(WORK, contract['manifest'])
    manifest_sha = contract['manifest']['sha256']
    recipe = gate.read_reference(WORK, policy['scheduler_supply']['continuous'])
    catalog = recipe['natural_draws']
    state = Path(policy['state_dir'])
    intents = gate.read(state / 'runtime.json')['intents']
    observation = gate.read(state / 'observation.json')
    observed = {row['id']: row for row in observation['runs']}
    _, known = scheduler_supply._queue(gate, Path(policy['queue_file']))
    claimed = response.claimed_cases(WORK, gate, contract, known, intents)
    signed, receipt_blocks = supply._approved_entries(policy, gate, WORK, manifest_sha, known, intents, ())
    signed = {gate.read_reference(WORK, entry['admission']).get('case_id') for entry in signed}
    lhs = recipe['lhs_evidence']
    p2 = gate.read(WORK / lhs['p2_release_path'])
    gate.need(p2['manifest_sha256'] == manifest_sha and p2['p2_authorized'] is True
              and (p2.get('threshold_bracket_observed') is True or p2.get('censoring_accepted') is True),
              'P2 release differs from the frozen plan')
    gate.referenced(WORK, p2['p1_evidence']['decision'])
    navigation = gate.read_reference(WORK, p2['lhs_native_navigation'])
    gate.need(navigation['primaries'] == 0 and len(navigation['pools']) == 48, 'Expected all 48 navigation receipts')
    rows = []
    for profile, p0_path in sorted(lhs['p0_gate_paths'].items()):
        group = profile.split('-')[0].lower()
        prep_ref, = (item for item in recipe['transport']['preparations']
                     if item['path'].endswith(f'/{group}-development-preparation.json'))
        pools = gate.read_reference(WORK, prep_ref)['pools']
        mesh_ref = ref(BASE / f'{group}-geometry-audit.json')
        mesh_audit = gate.read_reference(WORK, mesh_ref)
        gate.need(mesh_audit['status'] == 'passed' and mesh_audit['profile_id'] == profile
                  and all(Decimal(mesh_audit[key]) < Decimal('0.001') for key in
                          ('maximum_interface_offset_nm', 'maximum_ray_path_offset_nm')),
                  'Frozen LHS geometry offsets differ')
        mesh_pin = mesh_audit['native_mesh_sha256']
        directory = OUTPUT / group
        published = group == 'lhs02'
        controls = {str(bit): control(catalog, intents, f'r06-p0-{group}-hold22-readout-b{bit}-r1',
                                      profile, bit, mesh_pin) for bit in (0, 1)}
        template = WORK / controls['1']['directory']
        zero_pin = ref(template / 'nodal-source.dat')
        gate.need(all(item['input_sha256']['nodal-source.dat'] == zero_pin['sha256']
                      for item in controls.values()), 'Original zero controls use different node directories')
        electrical = ref(EXISTING / 'electrical.json') if published else freeze(
            directory / 'electrical.json', {'profile_id': profile, 'controls': controls})
        source_mapping = (gate.read(EXISTING / 'source-context.json') if published else
                          dict(profile_id=profile, mesh_sha256=mesh_pin, zero_source=zero_pin, scale_factor=1,
                               pair_creation_energy_eV='3.6', native_mesh_review=mesh_ref,
                               projection_adapter=ref(staging.ADAPTER), projector=ref(staging.PROJECTOR),
                               lhs_native_navigation=p2['lhs_native_navigation']))
        source_ref = ref(EXISTING / 'source-context.json') if published else freeze(
            directory / 'source-context.json', source_mapping)
        qualification = (WORK / p0_path).is_file()
        science_ref = ref(WORK / p0_path) if qualification else None
        if qualification:
            science = gate.common_gate(WORK, contract, {'p0_gate': science_ref})
            gate.qualified_profile(WORK, science, profile)
        refinements = qualification_runs(WORK, gate, intents, profile, observed)
        assets = None
        prepared_observations = None
        for pool in sorted(pools, key=lambda item: item['task_id']):
            candidate, = pool['pool_request_candidates']
            radiation = candidate['radiation_id']
            task = pool['task_id']
            nav = navigation['pools'][task]
            geometry_pin = ref(WORK / pool['project'] / 'geometry.json')
            gate.need(nav['status'] == 'passed' and nav['geometry_audit'] == mesh_ref
                      and nav['preparation'] == prep_ref and nav['input_sha256'] == pool['input_sha256']
                      and geometry_pin['sha256'] == pool['input_sha256']['geometry.json']
                      and candidate['profile_id'] == profile, 'Response plan differs from frozen pool and navigation')
            cases = {case['case_id']: case for case in manifest['cases'] if case.get('profile_id') == profile
                     and case.get('radiation_id') == radiation and case['block'] in ('S', 'T')}
            status = dict(profile=profile, radiation=radiation, pool_task=task, preparation=prep_ref,
                          native_geometry=geometry_pin, geometry_review=mesh_ref, navigation=p2['lhs_native_navigation'],
                          controls=electrical, source_mapping=source_ref,
                          qualification_path=p0_path, qualification=science_ref,
                          qualification_runs=refinements,
                          pool_status=observed.get(task, {}).get('status', 'not_submitted'),
                          cases={key: {'block': case['block'], 'bit': case['stored_bit'],
                                       'status': 'queued_or_run' if key in claimed else
                                       'approved_waiting_queue' if key in signed else 'pending'}
                                 for key, case in cases.items()})
            rows.append(status)
            if not qualification or status['pool_status'] != 'succeeded':
                status['dependencies'] = ([] if qualification else ['dual_state_numerical_qualification']) + [
                    'verified_transport_collection', 'frozen_draw_and_particle_source_projection']
                continue
            cell = (EXISTING if published else directory) / radiation
            try:
                if prepared_observations is None:
                    prepared_observations = observations(controls, published, catalog, intents)
                if published:
                    context = ref(cell / 'response-context.json')
                    projection = ref(cell / 'projection/manifest.json')
                    audit = PRIVATE / 'month-one-natural-r1' / intents[task]['run_id'] / 'ledger'
                else:
                    cell.mkdir(exist_ok=True, parents=True)
                    context = freeze(cell / 'response-context.json', dict(
                        frozen=True, profile_id=profile, radiation_id=radiation, manifest_sha256=manifest_sha,
                        source_time_ns=22.0, deck_timing_version='r06-hold-window-v1', electrical=electrical,
                        source_mapping=source_ref, timing=science['timing']['evidence'][0], label_contract=science_ref))
                    audit, intent = audit_pool(policy, contract, catalog, known, intents, pool, prep_ref, navigation)
                    if assets is None:
                        geometry = json.loads(gate.referenced(WORK, geometry_pin).read_text(), parse_float=Decimal)
                        assets, zero = projection_assets(mesh_audit, geometry, source_mapping)
                    transient = gate.read(template / 'protocol.json')['transient']
                    projection = project_cell(policy, catalog, pool, prep_ref, audit, intent, cell, context,
                                              assets, source_mapping, zero, transient)
                document = gate.read_reference(WORK, projection)
                gate.need(document['condition'] == {'profile_id': profile, 'radiation_id': radiation}
                          and document['response_context'] == context, 'Response archive belongs to another condition')
                status.update(context=context, projection=projection, transport_audit=ref(audit / 'audit.json'))
                entries = []
                for item in status['cases'].values():
                    if item['block'] == 'T' and item['status'] == 'pending':
                        item['dependency'] = 'frozen threshold reference or accepted same-primary 10x response'
                for event in document['events']:
                    for sample in event['responses']:
                        case_id = sample['case_id']
                        if status['cases'][case_id]['status'] != 'pending':
                            continue
                        case = cases[case_id]
                        try:
                            observation_ref = prepared_observations[str(case['stored_bit'])]
                            if event['source_status'] == 'nodal_candidate':
                                item = dict(case_id=case_id, projection=projection, zero_observation=observation_ref)
                                entries.append(response._stage(WORK, gate, contract, cases, case, item,
                                                               f'{case_id}-supply-r1', intents))
                                status['cases'][case_id]['status'] = 'staged'
                            else:
                                receipt = zero_reuse(contract, intents, case, observation_ref, projection,
                                                     document, event, cell)
                                status['cases'][case_id].update(status='verified_zero_reuse', evidence=receipt)
                        except ERRORS as error:
                            status['cases'][case_id].update(status='blocked', dependency=str(error))
                if entries and args.publish:
                    status['approval'] = approved(policy, contract, profile, entries)
            except ERRORS as error:
                status['error'] = str(error)
    gate.need(len(rows) == 48 and len({(row['profile'], row['radiation']) for row in rows}) == 48,
              'Response register must cover the original 48 conditions')
    report = dict(schema='tcad-r06-lhs-response-supply-v1', manifest_sha256=manifest_sha,
                  observation_utc=observation['utc'], cases=rows, intake_errors=receipt_blocks,
                  counts=Counter(row['pool_status'] for row in rows))
    snapshot(OUTPUT / 'response-status.json', report)
    if args.publish:
        update_public_progress(rows)
    return report['counts']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    original_source = response._natural_source
    response._natural_source = lambda *values: lhs_source(original_source, *values)
    OUTPUT.mkdir(exist_ok=True)
    print(prepare(gate.read(args.policy), args))
