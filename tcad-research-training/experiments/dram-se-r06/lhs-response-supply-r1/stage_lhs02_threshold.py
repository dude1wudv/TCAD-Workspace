"""Stage initial x10 T responses from the original collected LHS pools.

Run on the research server with the active autonomy release and the existing
server-codex helpers on PYTHONPATH. The default context is the signed LHS02
handoff. For another profile with the same lattice projection recipe, supply
its frozen contexts, both collected zero observations and a separate output.
Review the printed batch reference before using month_one_supply.py intake.
"""

import argparse
from decimal import Decimal, localcontext
import os
from pathlib import Path
import sys
import tarfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

import geant4_archive as archive
import month_one_response as response
import month_one_wave as wave
import r06_gate as gate
import scheduler_supply as supply
from stage_lhs02_responses_r1 import (
    ADAPTER, PROFILE, PROJECTOR, ROOT, WORK,
    freeze_file, install_directory, project_source, projection_assets, ref,
)

import freeze_development_draw_continuous as ledger
import select_threshold_reference as selector


BASE = WORK / 'local_runtime/server-codex'
POLICY = Path('/etc/tcad-autonomy/policy.json')
SCHEMA = 'tcad-r06-lhs-initial-threshold-source-v1'
SELECTOR_SHA = 'fa5d71ba658d54f758365d02d47f9b1c0f593c9613df78fedcea87c7ac2bf3cf'


def read(reference):
    return gate.read_reference(WORK, reference)


def verify_controls(context, case, contract, intents, observation_refs):
    science = gate.common_gate(WORK, contract, {'p0_gate': context['label_contract']})
    profile = case['profile_id']
    gate.qualified_profile(WORK, science, profile)
    electrical = read(context['electrical'])
    gate.need(electrical['profile_id'] == profile, 'Electrical control profile differs')
    for bit, observation_ref in enumerate(observation_refs):
        observation = read(observation_ref)
        task = observation['task_id']
        control = electrical['controls'][str(bit)]
        native = response._native(WORK, gate, intents, task, observation['native_manifest'])
        gate.need(control['matched_control_collected'] is True and control['original_task_id'] == task
                  and control['original_manifest'] == observation['native_manifest']
                  and control['directory'] == intents[task]['project']
                  and control['input_sha256'] == native[0]['input_sha256'],
                  'Signed electrical control differs from original collection')
        response._zero_evidence(gate, native, observation, dict(case, stored_bit=bit), science)
    return electrical['controls']


def threshold_input(work, gate_module, intents, cases, case, recipe):
    """Read this producer's initial T evidence for the existing _stage serializer."""
    proof, zero_ref = recipe['initial_projection'], recipe['zero_observation']
    projection = gate_module.read_reference(work, proof)
    context_ref = projection['response_context']
    context = gate_module.read_reference(work, context_ref)
    observation = gate_module.read_reference(work, zero_ref)
    task = observation['task_id']
    zero = response._native(work, gate_module, intents, task, observation['native_manifest'])
    hashes = zero[0]['input_sha256']
    control = response._frozen_control(work, gate_module, context['electrical'], observation,
                                       case['profile_id'])
    gate_module.need(projection['schema'] == SCHEMA and projection['case_id'] == case['case_id']
                     and case['block'] == 'T' and case['stored_bit'] == observation['stored_bit'] == 1
                     and case['scale_factor'] == projection['scale_factor'] == 10
                     and response._same_frozen_control(control, hashes, case['profile_id'])
                     and projection['mesh']['sha256'] == hashes['cell_msh.tdr']
                     and projection['zero_source']['sha256'] == hashes['nodal-source.dat'],
                     'Initial threshold source and same-state control differ')
    source = {'path': Path(proof['path']).with_name('nodal-source.dat').as_posix(),
              'sha256': projection['files_sha256']['nodal-source.dat']}
    raw = gate_module.referenced(work, source).read_bytes()
    evidence = [proof, zero_ref, source, context_ref, *projection['selection_evidence'].values(),
                *projection['controls']]
    return (zero, observation, evidence, context['label_contract'], context_ref, {},
            projection['event_id'], projection['source_primary_id'], raw, Decimal(1),
            Decimal(projection['expected_scaled_pairs']), [task])


def project(case, audit, event_id, context, controls, policy, scratch, assets_by_mapping):
    mapping = read(context['source_mapping'])
    profile = case['profile_id']
    zero_ref = mapping['zero_source']
    mesh_sha = mapping['mesh_sha256']
    gate.need(mapping['profile_id'] == profile and mapping['scale_factor'] == 1
              and Decimal(mapping['pair_creation_energy_eV']) == Decimal('3.6')
              and mapping['projection_adapter'] == ref(ADAPTER) and mapping['projector'] == ref(PROJECTOR)
              and all((row['input_sha256']['cell_msh.tdr'], row['input_sha256']['nodal-source.dat'])
                      == (mesh_sha, zero_ref['sha256']) for row in controls.values()),
              'Frozen lattice mapping differs from the original dual-state controls')
    zero = gate.referenced(WORK, zero_ref).read_bytes()
    template = gate.path_at(WORK, controls['1']['directory'])
    protocol = gate.read(template / 'protocol.json')
    transient = protocol['transient']
    mapping_sha = context['source_mapping']['sha256']
    if mapping_sha not in assets_by_mapping:
        transfer, = [row for row in read(mapping['lattice_replay'])['results'] if row['profile_id'] == profile]
        gate.need(transfer['extent_review'] == mapping['native_mesh_review'], 'Frozen native mesh review differs')
        prior = read(mapping['native_mesh_review'])
        assets_by_mapping[mapping_sha] = projection_assets(mesh_sha, template, zero, prior, transfer)
    adapter, projector, mesh, nodes, grid = assets_by_mapping[mapping_sha]
    operation = gate.referenced(WORK, audit['operation'])
    original_tar = operation.with_name('results.tar')
    if not original_tar.is_file():
        receipt = archive._identity(operation)
        gate.need(receipt['archive_sha256'] == audit['archive_sha256']
                  and receipt['primary_ledger_sha256'] == audit['event_deposition_sha256'],
                  'Cold archive receipt differs from audited transport')
        original_tar = archive._stage_archive(scratch, receipt, policy['result_gdrive_config'], 20 * 1024**3)
    tables, originals, native, energy = adapter['native_event'](original_tar, audit, event_id)
    gate.need(native['zero_si_ionizing'] is False and energy > 0, 'Selected native event has no silicon ionization')
    end, step = Decimal(transient['source_window_endpoints_s'][-1]), Decimal(transient['source_max_step_s'])
    voxel, expected_base, lineage = adapter['source_rows'](tables, energy, grid, end, step)
    gate.need(len(lineage) == sum(row['pre_material'] == 'G4_Si' and Decimal(row['ionizing_MeV']) > 0
                                  for row in tables['steps.csv']), 'Projection omitted a positive native step')
    voxel_path = scratch / 'voxel-source.dat'
    voxel_path.write_bytes(voxel)
    base, report, checks = project_source(projector, mesh, nodes, zero, end, voxel_path,
                                          expected_base, len(voxel.splitlines()) - 2)
    with localcontext() as precision:
        precision.prec = 60
        expected = energy * Decimal(10) / Decimal('3.6')
        scaled, rows, allocations, pairs = response._nodal(gate, base, zero, protocol, Decimal(10), expected)
        response._nodal(gate, scaled, zero, protocol, Decimal(1), expected)
    payload = dict(originals, **{'voxel-source-x1.dat': voxel, 'nodal-source.dat': scaled,
                                 'projection-x1.json': wave._json_bytes(report),
                                 'step-lineage.json': wave._json_bytes(lineage)})
    proof = dict(expected_scaled_pairs=str(expected), reintegrated_pairs=pairs, rows=rows, allocations=allocations,
                 native_event_audit=native, native_unscaled_silicon_ionizing_energy_eV=str(energy),
                 projection_checks=checks, mesh=ref(template / 'cell_msh.tdr'), zero_source=zero_ref)
    return payload, proof, energy


def stage_cell(case, args, policy, contract, cases, settings, release_ref, intents, observation_refs, assets_by_mapping):
    profile, radiation = case['profile_id'], case['radiation_id']
    navigation_ref = read(release_ref)['lhs_native_navigation']
    navigation = read(navigation_ref)
    preparation_ref, = [pin for pin in settings['transport']['preparations']
                        if Path(pin['path']).name == f'{profile.lower()}-preparation.json']
    prep_path = gate.referenced(WORK, preparation_ref)
    prep_raw = prep_path.read_bytes()
    preparation = read(preparation_ref)
    pool, = [pool for pool in preparation['pools'] if any(
        row['profile_id'] == profile and row['radiation_id'] == radiation for row in pool['pool_request_candidates'])]
    task = pool['task_id']
    intent = intents[task]
    ledger_dir = args.ledger_root / intent['run_id'] / 'ledger'
    audit, audit_sha, events = ledger.read_ledger(ledger_dir)
    with patch.object(ledger, 'prepared_pool', return_value=(prep_raw, preparation, pool)):
        candidate = ledger.verify_pool(audit, contract['manifest']['sha256'], profile)
    nav = navigation['pools'][task]
    gate.need(candidate['radiation_id'] == radiation and candidate['crn_group_id'] == case['crn_group_id']
              and audit['transport_run_id'] == intent['run_id'] and audit['executed_task_id'] == task
              and audit['executed_project'] == intent['project'] == pool['project']
              and audit['lhs_native_navigation'] == navigation_ref and nav['status'] == 'passed'
              and nav['profile_id'] == profile and nav['input_sha256'] == audit['input_sha256'] == intent['input_sha256']
              and intent['scientific_admission']['scope'] == 'transport_pool'
              and intent['scientific_admission']['pool'] == [case['crn_group_id'], radiation],
              'Original LHS transport identity, admission or navigation differs')
    selected, rank, count = selector.select_positive_reference(events)
    event_id = selected['event_id']
    context_ref = ref(args.context_dir / radiation / 'response-context.json')
    context = read(context_ref)
    gate.need(context['frozen'] is True and context['manifest_sha256'] == contract['manifest']['sha256']
              and all(context[key] == case[key] for key in ('profile_id', 'radiation_id', 'source_time_ns',
                                                           'deck_timing_version')),
              'Frozen response context differs from the initial threshold case')
    controls = verify_controls(context, case, contract, intents, observation_refs)
    target = args.output_dir / radiation
    with TemporaryDirectory(dir=args.output_dir, prefix=f'.{radiation}-') as scratch:
        payload, proof, energy = project(case, audit, event_id, context, controls, policy, Path(scratch), assets_by_mapping)
    gate.need(float(energy) == selected['deposition_energy_eV'], 'Selected energy differs from the native event')
    primary = f"{audit['native_request_id']}:{audit['seed']}:{event_id}"
    scale_source = dict(source_primary_id=primary, expected_scaled_pairs=proof['expected_scaled_pairs'])
    payload['source.json'] = wave._json_bytes(scale_source)
    source_ref = wave._reference(WORK, target / 'source.json', payload['source.json'])
    evidence = dict(design=contract['manifest'], p2_release=release_ref, preparation=preparation_ref,
                    selector=ref(Path(selector.__file__)), operation=audit['operation'], navigation=navigation_ref,
                    audit={'path': (ledger_dir / 'audit.json').relative_to(WORK).as_posix(), 'sha256': audit_sha},
                    depositions={'path': (ledger_dir / 'event-deposition.json').relative_to(WORK).as_posix(),
                                 'sha256': audit['event_deposition_sha256']})
    document = dict(proof, schema=SCHEMA, case_id=case['case_id'], profile_id=profile, radiation_id=radiation,
                    scale_factor=10, source_shape_id=case['source_shape_id'], source=source_ref,
                    event_id=event_id, source_primary_id=primary, positive_rank=rank, positive_count=count,
                    rule='lower-median-positive-silicon-ionizing-energy-v1',
                    transport_run_id=audit['transport_run_id'], transport_archive_sha256=audit['archive_sha256'],
                    response_context=context_ref, controls=observation_refs, selection_evidence=evidence,
                    files_sha256={name: response._sha(raw) for name, raw in payload.items()},
                    statistics_eligible=False, training_eligible=False)
    payload['manifest.json'] = wave._json_bytes(document)
    install_directory(target, payload)
    gate.need(gate.input_hashes(target) == {name: response._sha(raw) for name, raw in payload.items()},
              'Existing threshold projection differs')
    recipe = dict(initial_projection=ref(target / 'manifest.json'), zero_observation=observation_refs[1])
    # The installed initial-T reader is hard-coded to LHS04/G0. Adapt only
    # this offline process. The real admission and intake validators run as-is.
    with patch.object(response, '_threshold', threshold_input), patch.object(
            response, 'OUTPUT', args.output_dir.relative_to(WORK).as_posix()):
        entry = response._stage(WORK, gate, contract, cases, case, recipe, f"{case['case_id']}-supply-r1", intents)
    print('STAGED', case['case_id'], audit['transport_run_id'], event_id, f'{rank}/{count}', flush=True)
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('radiations', nargs='*', metavar='G0/C1')
    parser.add_argument('--profile', default=PROFILE)
    parser.add_argument('--context-dir', type=Path, default=BASE / 'r06-lhs02-response-handoff-r1')
    parser.add_argument('--zero-b0', type=Path, default=BASE / 'r06-lhs02-hold22-b0-zero-observation-20261123.json')
    parser.add_argument('--zero-b1', type=Path, default=BASE / 'r06-lhs02-hold22-b1-zero-observation-20261123.json')
    parser.add_argument('--ledger-root', type=Path, default=ROOT)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.context_dir = args.context_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.ledger_root = args.ledger_root.resolve()
    radiations = list(dict.fromkeys(args.radiations or selector.SHAPES))
    if not set(radiations) <= selector.SHAPES.keys():
        parser.error('Initial threshold pools must be G0 or C1')
    os.umask(0o077)
    gate.need(args.output_dir.parent == BASE and args.output_dir != args.context_dir,
              'Choose a separate candidate directory directly under local_runtime/server-codex')
    gate.need(ref(Path(selector.__file__))['sha256'] == SELECTOR_SHA,
              'Frozen lower-median-positive selector SHA differs')
    policy = gate.read(POLICY)
    contract = read(policy['scientific_gate']['contract'])
    manifest = read(contract['manifest'])
    cases = {row['case_id']: row for row in manifest['cases']}
    settings = read(policy['scheduler_supply']['continuous'])
    lhs = settings['lhs_evidence']
    release_ref = settings.get('p2_release') or ref(gate.path_at(WORK, lhs['p2_release_path']))
    release = read(release_ref)
    decision = read(release['p1_evidence']['decision'])
    gate.need(release['schema'] == 'tcad-r06-p2-release-v1' and release['p2_authorized'] is True
              and release['manifest_sha256'] == decision['manifest_sha256'] == contract['manifest']['sha256']
              and decision['initial_lhs_probe_scale'] == 10 and args.profile in lhs['p0_gate_paths'],
              'Missing P2 authorization, frozen initial x10 decision or profile qualification')
    state = Path(policy['state_dir'])
    intents = gate.read(state / 'runtime.json')['intents']
    _, known = supply._queue(gate, Path(policy['queue_file']))
    claimed = response.claimed_cases(WORK, gate, contract, known, intents)
    observation_refs = [ref(path.resolve()) for path in (args.zero_b0, args.zero_b1)]
    args.output_dir.mkdir(exist_ok=True)
    entries, failures, assets_by_mapping = [], [], {}
    for radiation in radiations:
        try:
            case = selector.initial_case(manifest, args.profile, radiation)
            gate.need(case['scale_factor'] == 10, 'Initial case is outside the frozen x10 scope')
            task_id = f"{case['case_id']}-supply-r1"
            if case['case_id'] in claimed or task_id in known or task_id in intents:
                print('ALREADY_CLAIMED', case['case_id'], flush=True)
                continue
            entries.append(stage_cell(case, args, policy, contract, cases, settings, release_ref,
                                      intents, observation_refs, assets_by_mapping))
        except (*response.RECIPE_ERRORS, tarfile.TarError) as error:
            failures.append(radiation)
            print('HOLD', radiation, str(error), file=sys.stderr, flush=True)
    if entries:
        profiles = wave.ANCHORS | {args.profile}
        check = wave.prepare_entries(policy, gate, entries, profiles=profiles, post_p2=True, validate_only=True)
        if check['blocked']:
            print('HOLD', check['blocked'], file=sys.stderr, flush=True)
        prepared = set(check['prepared'])
        entries = [entry for entry in entries if supply.read_proposal(WORK, gate, entry['proposal'])['id'] in prepared]
        if entries:
            batch = dict(schema='tcad-r06-approved-supply-v1', manifest_sha256=contract['manifest']['sha256'],
                         entries=entries)
            path = args.output_dir / ('approved-' + '-'.join(sorted(prepared)) + '.json')
            receipt = freeze_file(path, batch)
            print('BATCH', receipt['path'], receipt['sha256'], len(entries), flush=True)
        failures.extend(check['blocked'])
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
