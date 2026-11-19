"""Generate an unapplied original-runner review package; never dispatch tools."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import runner_patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PACKAGE = ROOT / 'local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/packages-r2'
GEOMETRY = ROOT / 'local_runtime/dram-see-v4/s2-geometry-r1/20261016T135638Z/candidate-r1'
CAPTURE = ROOT / 'local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/capture/r3'
ROLES = ('B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def budget_proposal():
    old = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/budget.json'
    course = ROOT / 'experiments/dram-see-v4/course-plan-r13/budget.proposed.json'
    proposal = read(course)
    assert proposal['B1_first_slice']['native_field_extractions'] == 2
    return dict(schema='s2-geometry-integration-cost-allocation-r1', status='PROPOSAL_NOT_AUTHORIZATION',
        execution_enabled=False, approved=False, approved_native_calls=0, reservations=0, consumed=0,
        ledger_scope='distinct future S2 ledger; no transfer of nuclear-closure balance',
        budget_id=None, existing_ledger=str(old.relative_to(ROOT)), existing_ledger_sha256=sha(old),
        original_course_proposal_sha256=sha(course), old_counts=read(old),
        allocation=[dict(role_id=role, category='native_geometry_extractions' if i < 2 else 'native_field_extractions',
                         tool='svisual', units=1, approved=False, reservation_id=None)
                    for i, role in enumerate(ROLES)],
        first_slice_proposed=dict(native_geometry_extractions=2, native_field_extractions=2,
            total_svisual_invocations=4, mesh_builds=2, sdevice=4,
            dispatch_cpu_hours_cap=proposal['B1_first_slice']['dispatch_cpu_hours_cap_proposed'],
            retained_new_GiB_cap=proposal['B1_first_slice']['retained_new_GiB_cap_proposed'],
            geometry_cpu_seconds=None, geometry_retained_bytes=None),
        accounting='Reserve before each launch, including failed/unknown. No automatic retry or implicit correction units.',
        limits='Geometry cost is inside the unchanged proposed 4 CPU hours / 8 GiB envelope; unpriced means unreleased.',
        exclusions=['no old postprocess balance use', 'no B2/B3/B4 authorization', 'no training budget change'])


def copy_new(source, destination):
    with Path(source).open('rb') as src, Path(destination).open('xb') as dst:
        shutil.copyfileobj(src, dst)


def text_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(value)


def role_candidate(role, output, geometry_inventory):
    source = PACKAGE / 'roles' / role
    destination = output / 'roles' / role
    destination.mkdir(parents=True, exist_ok=False)
    frozen = read(PACKAGE / 'package-manifest.json')['files_sha256']
    if sha(source / 'input-manifest.json') != frozen['roles/' + role + '/input-manifest.json']:
        raise ValueError('Frozen role manifest changed: ' + role)
    old_manifest = read(source / 'input-manifest.json')
    # Copy the needed role payload once into this new review artifact. Old
    # package-wide verification/acceptance is reused, not rerun as a patrol.
    for filename in old_manifest['files_sha256']:
        if filename != 'project.review.json':
            copy_new(source / filename, destination / filename)
            if sha(destination / filename) != old_manifest['files_sha256'][filename]:
                raise ValueError('Copied input differs from frozen role manifest: ' + role + '/' + filename)
    project = read(source / 'project.review.json')
    cfg = dict(schema='s2-runner-geometry-integration-r1', mode='produce' if role in ROLES[:2] else 'reuse',
               role_id=role, run_id=None, producer_run_id=None, execution_enabled=False)
    project['s2_geometry'] = cfg
    project['runner'] = 'original scripts/tcad.py with separately reviewed UNAPPLIED capture+geometry patch'
    project['execution_enabled'] = False
    copy_new(HERE / 'geometry_bridge.py', destination / 'geometry_bridge.py')
    if cfg['mode'] == 'produce':
        for filename in ('measurement-plan.json', 'measure-geometry.tcl', 'comparison-policy.proposed.json'):
            src = GEOMETRY / role / filename
            if sha(src) != geometry_inventory[role + '/' + filename]:
                raise ValueError('Geometry input changed: ' + filename)
            copy_new(src, destination / filename)
        src = GEOMETRY / role / 'geometry-with-measurements.scm'
        if sha(src) != geometry_inventory[role + '/geometry-with-measurements.scm']:
            raise ValueError('Frozen geometry source changed')
        original = src.read_text(encoding='utf-8')
        build = '(sde:build-mesh "snmesh" "" "cell")'
        separated = runner_patch.replace_once(original, build,
            '; Integration candidate: original runner invokes this mesh exactly once.\n'
            '(sdeio:save-tdr-bnd (get-body-list) "cell_bnd.tdr")\n'
            '(sdedr:write-cmd-file "cell.cmd")')
        guard = ('; Same-stage guard supplied by package integration; no second mesh or solver invocation.\n'
                 '(define resource-guard-status (system:command "/usr/bin/python3 mesh_resource_guard.py"))\n'
                 '(if (not (equal? resource-guard-status 0)) (sde:error "Mesh resource guard blocked SDevice; see mesh-resource-report.json"))')
        separated = runner_patch.replace_once(separated, guard,
            '; Original mesh_resource_guard.py runs after the explicit mesh step, before observation and SDevice.')
        text_new(destination / 'geometry-with-measurements.scm', separated)
        text_new(destination / 'geometry-integration.review.patch', runner_patch.patch(original, separated,
            role + '/geometry-producer-r1/geometry-with-measurements.scm', role + '/geometry-with-measurements.scm'))
        copy_new(GEOMETRY / 'evaluate.py', destination / 'evaluate.py')
        project['steps'] = [
            dict(tool='sde', args=['-e', '-l', 'geometry-with-measurements.scm'],
                 outputs=['cell_bnd.tdr', 'cell.cmd', 'sde-contact-measurements.csv',
                          'sde-contact-probes.csv', 'sde-material-probes.csv', 'sde-geometry-status.txt']),
            dict(tool='snmesh', args=['--threads', '1', '--max_threads', '1', 'cell'],
                 outputs=['cell_msh.tdr', 'cell_msh.log']),
            dict(tool='svisual', args=['--threads', '1', '--max_threads', '1', '-b', '-tcl', '-script', 'measure-geometry.tcl'],
                 outputs=['geometry-status.json', 'geometry-inventory.csv', 'mesh-identity.csv',
                          'material-measurements.csv', 'contact-measurements.csv', 'doping-measurements.csv']),
            project['steps'][-1]]
        write(destination / 'geometry-budget-reservation.proposed.json', dict(
            schema='s2-geometry-budget-reservation-r1', status='NOT_RESERVED', synthetic=False,
            budget_id=None, budget_reservation_id=None, budget_ledger_sha256=None, role_id=role, run_id=None,
            category='native_geometry_extractions', units=1, approved=False))
        write(destination / 'geometry-release.proposed.json', dict(schema='s2-geometry-producer-release-r1',
            status='NOT_RELEASED', execution_enabled=False, explicit_native_authorization=False, synthetic=False,
            role_id=role, producer_run_id=None, plan_sha256=sha(destination / 'measurement-plan.json'),
            evaluator_sha256=sha(destination / 'evaluate.py'), budget_id=None, budget_reservation_id=None,
            policy_sha256=None, authorization_sha256=None, input_manifest_sha256=None, budget_reservation_sha256=None))
        write(destination / 'observation-context.required.json', dict(schema='s2-geometry-observation-context-r1',
            status='REQUIRED_FUTURE_OBSERVATION_NOT_CONTEXT', role_id=role, dimension=2 if role == 'B1-D2' else 3,
            producer_run_id=None, mesh_sha256=None, sde_exit_code=None, mesh_exit_code=None, svisual_exit_code=None,
            raw_exit_sources={'sde-exit-code.txt':'step-001-sde-exit-code.txt',
                              'mesh-exit-code.txt':'step-002-snmesh-exit-code.txt',
                              'svisual-exit-code.txt':'step-003-svisual-exit-code.txt'}))
    else:
        cfg.update(source_run_directory=None, acceptance_file=None)
        write(destination / 'reuse-acceptance.required.json', dict(schema='s2-d3-geometry-reuse-acceptance-r1',
            status='NOT_ACCEPTED', source_run_id=None, source_manifest_sha256=None,
            source_archive_sha256=None, mesh_sha256=None, geometry_validation_sha256=None,
            boundary='Future accepted D3 original archive only; no invented acceptance or remeasurement'))
    write(destination / 'project.review.json', project)
    manifest = dict(schema='s2-role-inputs-r1', role=role, status='INTEGRATION_REVIEW_ONLY_NOT_RELEASED',
                    execution_enabled=False, frozen_source_input_manifest_sha256=sha(source / 'input-manifest.json'),
                    files_sha256={p.name: sha(p) for p in sorted(destination.iterdir()) if p.is_file()})
    write(destination / 'input-manifest.json', manifest)
    write(destination / 'execution-release.proposed.json', dict(schema='s2-execution-release-r1',
        status='NOT_RELEASED', execution_enabled=False, explicit_native_authorization=False, synthetic=False,
        role_id=role, run_id=None, scheduler='root', threads=1, cpu_count=1, budget_id=None,
        budget_reservation_id=None, budget_ledger_sha256=None, expected_runner_sha256=None,
        geometry_bridge_sha256=sha(destination / 'geometry_bridge.py'),
        input_manifest_sha256=sha(destination / 'input-manifest.json'), geometry_release_sha256=None,
        d3_producer_run_id=None, d3_mesh_sha256=None, d3_acceptance_sha256=None,
        d3_source_manifest_sha256=None, d3_source_archive_sha256=None))
    return dict(role_id=role, mode=cfg['mode'], project_review_sha256=sha(destination / 'project.review.json'),
                input_manifest_sha256=sha(destination / 'input-manifest.json'), native_calls=0)


def prepare(output, spine=False):
    output = Path(output).resolve()
    runtime = (ROOT / 'local_runtime/dram-see-v4/s2-runner-integration-r1').resolve()
    if runtime not in output.parents:
        raise ValueError('Review output must remain in isolated integration runtime')
    if sha(PACKAGE / 'package-manifest.json') != '165473aacaada00f613885ced15b0d645205740cdf5c0c0fcffb50d82c18a8f3':
        raise ValueError('Frozen S2 package manifest changed')
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'budget-allocation.proposed.json', budget_proposal())
    if spine:
        write(output / 'spine-candidate.json', dict(schema='s2-runner-integration-spine-r1',
            status='OFFLINE_SPINE_ONLY', execution_enabled=False, native_calls=0,
            geometry_candidate_sha256=sha(GEOMETRY / 'candidate.json'),
            capture_report_sha256=sha(CAPTURE / 'capture-patch-report.json'),
            pending='F1 original-runner patch and observation bridge'))
        return dict(output=str(output), status='OFFLINE_SPINE_ONLY', native_calls=0)
    frozen_geometry = read(GEOMETRY / 'candidate.json')
    if sha(GEOMETRY / 'candidate.json') != 'fec305990fc65b6fe3835dc2086ecb55b1a359645b5927f6f7aa48f59b5d5ec0':
        raise ValueError('Frozen geometry candidate changed')
    if sha(GEOMETRY / 'evaluate.py') != frozen_geometry['files_sha256']['evaluate.py']:
        raise ValueError('Frozen evaluator changed')
    original, capture_source, candidate, preserved = runner_patch.compose(ROOT, CAPTURE)
    text_new(output / 'tcad.geometry-only.review.patch', runner_patch.patch(capture_source, candidate,
        'a/scripts/tcad.py (capture-r3)', 'b/scripts/tcad.py (geometry integration review)'))
    text_new(output / 'tcad.capture-and-geometry.review.patch', runner_patch.patch(original, candidate,
        'a/scripts/tcad.py', 'b/scripts/tcad.py'))
    # .review extension deliberately is not an installed second runner.
    text_new(output / 'tcad.py.review', candidate)
    copy_new(CAPTURE / 'operation.review.patch', output / 'operation.capture-r3.review.patch')
    roles = [role_candidate(role, output, frozen_geometry['files_sha256']) for role in ROLES]
    write(output / 'candidate.json', dict(schema='s2-runner-geometry-integration-candidate-r1',
        status='UNAPPLIED_OFFLINE_REVIEW_ONLY', execution_enabled=False, native_calls=0,
        patches_applied=False, original_runner_modified=False, budget_modified=False,
        approved_native_calls=0, reservations=0, roles=roles, original_runner_sha256=sha(ROOT / 'scripts/tcad.py'),
        capture_report_sha256=sha(CAPTURE / 'capture-patch-report.json'),
        geometry_candidate_sha256=sha(GEOMETRY / 'candidate.json'),
        generator_sha256={name: sha(HERE / name) for name in ('prepare.py', 'runner_patch.py', 'geometry_bridge.py')},
        candidate_runner_sha256=sha(output / 'tcad.py.review'), preserved_function_asts=preserved,
        required_future_release=['original owner/scheduler and capture patches', 'exact execution inputs and run IDs',
                                 'separate S2 ledger and two geometry reservations', 'approved comparison/resource policies',
                                 'explicit native authority and live strict SSH/shared-lock/single-core admission'],
        no_claims=['native syntax/runtime', 'scientific qualification', 'PMI repair', 'R12 release']))
    write(output / 'candidate-manifest.json', dict(schema='s2-runner-integration-review-inventory-r1',
        files_sha256={p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(output=str(output), status='UNAPPLIED_OFFLINE_REVIEW_ONLY', native_calls=0,
                candidate_manifest_sha256=sha(output / 'candidate-manifest.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--spine', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.spine), ensure_ascii=False))


if __name__ == '__main__':
    main()
