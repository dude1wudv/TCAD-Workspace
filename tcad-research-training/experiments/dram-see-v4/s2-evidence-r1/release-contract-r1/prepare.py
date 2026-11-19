"""Build an inert first-four release-contract review package; no dispatch API."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNTIME = ROOT / 'local_runtime/dram-see-v4/s2-release-contract-r1'
INTEGRATION = ROOT / 'local_runtime/dram-see-v4/s2-runner-integration-r1/20261016T155822Z'
CANDIDATE = INTEGRATION / 'candidate-r2'
EXPECTED = 'e71373cdbfcc3c6e60ac0f976aebd6171f4422f5d9b6136a27253ec32e1c0296'
THREAD = '01a144ee-5a13-76f1-a56b-f26ef88da9f3'
ROLES = ('B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1')
OWNER_LOCK = 'local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/continuation/owner.lock'


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def foundation(authorization):
    require(sha(CANDIDATE / 'candidate-manifest.json') == EXPECTED, 'Wrong integration candidate-r2 manifest')
    authority = read(authorization)
    require(authority.get('source') == 'direct_user_message' and authority.get('verbatim'), 'Direct user evidence absent')
    require(authority.get('role_ids') == list(ROLES) and authority.get('explicit_native_authorization') is True,
            'Current action permission/role scope absent')
    owner = dict(schema='s2-original-owner-binding-r1', scheduler='root', preparation_thread=THREAD,
                 ownership_implementation=ref(ROOT / 'experiments/dram-see-v4/nuclear-closure-r1/supervisor.py'),
                 ownership_function='ownership', owner_lock=OWNER_LOCK,
                 runner=ref(ROOT / 'scripts/tcad.py'),
                 operation=ref(ROOT / 'experiments/dram-see-v4/transport-probe/operation.py'),
                 expected_applied_runner_sha256=read(CANDIDATE / 'candidate.json')['candidate_runner_sha256'],
                 shared_solver_lock='{connection.remote_root}/.solver.lock',
                 connection_binding='scripts/tcad.py::connection; existing local_runtime/connection.json',
                 strict_ssh=True, native_threads=1, native_cores=1,
                 actual_lock_holder=None, live_admission=None, owner_release=None,
                 old_entry=ref(ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/active-entry.json'),
                 old_entry_reactivated=False, old_budget_reused=False,
                 rule='Use the original owner lock; do not call the old nuclear reserve/write path for S2.')
    return authority, owner


def source_ref(name, inventory):
    require(name in inventory, 'Source input absent from accepted inventory: ' + name)
    return dict(path=(CANDIDATE / name).relative_to(ROOT).as_posix(), sha256=inventory[name],
                verification='Accepted candidate-r2 manifest; previous payload verification reused')


def budget_review(stamp, runs):
    budget_id = 'dram-see-v4-s2-first4-' + stamp.lower()
    requests = []
    for index, role in enumerate(ROLES):
        prefix = budget_id + '-' + role.lower()
        requests.append(dict(request_id=prefix + '-execution', role_id=role, run_id=runs[role],
                             category='role_execution', units=dict(sdevice=1, mesh_builds=int(index < 2)),
                             status='REQUEST_NOT_RESERVED', approved=False, reservation_id=None))
        category = 'native_geometry_extractions' if index < 2 else 'native_field_extractions'
        requests.append(dict(request_id=prefix + '-extraction', role_id=role, run_id=runs[role],
                             category=category, units=1, status='REQUEST_NOT_RESERVED',
                             approved=False, reservation_id=None))
    return dict(schema='s2-first-four-budget-review-r1', budget_id=budget_id,
                status='PROPOSED_NOT_APPROVED', approved=False, execution_enabled=False,
                approval_evidence=None, operational_ledger_path=None, operational_ledger_sha256=None,
                approved_calls=0, reservations=0, consumed=0, requests=requests,
                proposed=dict(sdevice=4, mesh_builds=2, native_geometry_extractions=2,
                              native_field_extractions=2, total_svisual=4, cpu_hours_cap=4,
                              retained_new_GiB_cap=8, compile=0, training=0, transport=0),
                sde_accounting='Two SDE constructions are included in the two mesh-building roles; explicit snmesh is invoked once per role.',
                old_ledger=ref(ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/budget.json'),
                old_balance_transfer=0, old_ledger_modified=False,
                original_proposal=ref(ROOT / 'experiments/dram-see-v4/course-plan-r13/budget.proposed.json'),
                integration_allocation=ref(CANDIDATE / 'budget-allocation.proposed.json'),
                accounting='Reserve before launch; failed and unknown reservations count. No automatic retries or correction allocation.')


def role_review(output, role, index, runs, budget, inventory):
    dest = output / 'roles' / role
    dest.mkdir(parents=True)
    prefix = 'roles/' + role + '/'
    original = CANDIDATE / 'roles' / role
    run_id = runs[role]
    producer = run_id if index < 2 else runs['B1-D3']
    release_id = budget['budget_id'] + '-' + role.lower() + '-release'
    project = read(original / 'project.review.json')
    project['s2_geometry'].update(run_id=run_id, producer_run_id=producer)
    d3_path = ROOT / 'local_runtime/runs' / runs['B1-D3']
    if index >= 2:
        project['s2_geometry'].update(source_run_directory=str(d3_path),
                                     acceptance_file=str(output.parent / 'pending-native-evidence/D3-reuse-acceptance.json'))
    write(dest / 'project.review.json', project)
    resource = read(original / 'resource-policy.json')
    resource.update(planned_release_id=release_id, forecast_status='MISSING_REVIEWED_FORECAST',
                    first_role_rule='D2 may use a justified reviewed forecast before its own mesh exists; never invent measured costs.')
    write(dest / 'resource-policy.review.json', resource)
    requests = [r for r in budget['requests'] if r['role_id'] == role]
    write(dest / 'budget-requests.review.json', dict(budget_id=budget['budget_id'], requests=requests,
                                                   budget_review=ref(output / 'budget.review.json'), approved=False))
    known = read(original / 'input-manifest.json')['files_sha256']
    # Bind accepted source payload by its inventory; do not rerun a package hash patrol.
    excluded = {'project.review.json', 'resource-policy.json', 'comparison-policy.proposed.json',
                'geometry-release.proposed.json', 'geometry-budget-reservation.proposed.json',
                'observation-context.required.json', 'reuse-acceptance.required.json',
                'README.txt', 'geometry-integration.review.patch'}
    payload = {name: source_ref(prefix + name, inventory) for name in known if name not in excluded}
    policy = None
    if index < 2:
        policy = read(original / 'comparison-policy.proposed.json')
        write(dest / 'comparison-policy.review.json', policy)
    mutable = {p.name: ref(p) for p in sorted(dest.iterdir()) if p.is_file()}
    inputs = dict(schema='s2-review-input-binding-r1', role_id=role, planned_run_id=run_id,
                  status='EXACT_KNOWN_REVIEW_INPUTS_NOT_EXECUTION_FREEZE', execution_enabled=False,
                  source_manifest=source_ref(prefix + 'input-manifest.json', inventory),
                  source_payload=payload, review_configuration=mutable,
                  authorization=ref(output / 'authorization.json'),
                  execution_input_manifest_sha256=None,
                  pending_payload=['project.json', 'approved resource policy', 'budget reservation receipts',
                                   'approved geometry policy/producer release' if index < 2 else 'accepted D3 original mesh and geometry evidence'])
    write(dest / 'input-review.json', inputs)
    execution = read(original / 'execution-release.proposed.json')
    execution.update(status='NOT_RELEASED', explicit_native_authorization=True, run_id=run_id,
                     planned_release_id=release_id, owner_binding=ref(output / 'owner-binding.json'),
                     budget_id=budget['budget_id'], budget_review_sha256=sha(output / 'budget.review.json'),
                     planned_budget_reservation_id=requests[0]['request_id'], budget_reservation_id=None,
                     budget_ledger_sha256=None, input_manifest_sha256=None,
                     review_input_binding_sha256=sha(dest / 'input-review.json'),
                     expected_runner_sha256=read(output / 'owner-binding.json')['expected_applied_runner_sha256'],
                     authorization_evidence_file='authorization.json',
                     authorization_evidence_sha256=sha(output / 'authorization.json'),
                     authorization_source_path=ref(output / 'authorization.json')['path'])
    if index < 2:
        geometry = read(original / 'geometry-release.proposed.json')
        geometry.update(status='NOT_RELEASED', explicit_native_authorization=True, producer_run_id=run_id,
                        budget_id=budget['budget_id'], planned_budget_reservation_id=requests[1]['request_id'],
                        budget_reservation_id=None, policy_sha256=None, input_manifest_sha256=None,
                        authorization_sha256=sha(output / 'authorization.json'),
                        authorization_review=ref(output / 'authorization.json'),
                        comparison_policy_review=ref(dest / 'comparison-policy.review.json'),
                        input_review=ref(dest / 'input-review.json'))
        write(dest / 'geometry-release.review.json', geometry)
        execution['geometry_release_review'] = ref(dest / 'geometry-release.review.json')
    else:
        execution['d3_producer_run_id'] = producer
        write(dest / 'd3-reuse.review.json', dict(schema='s2-d3-reuse-binding-review-r1', status='PENDING_D3_ACCEPTANCE',
              producer_run_id=producer, source_run_directory=str(d3_path),
              acceptance_file=project['s2_geometry']['acceptance_file'], acceptance_sha256=None,
              source_manifest_sha256=None, source_archive_sha256=None, mesh_sha256=None,
              geometry_validation_sha256=None, final_execution_input_manifest_sha256=None,
              native_remeasurement=False, original_bytes_required=True))
        write(dest / 'field-extraction.review.json', dict(schema='s2-field-extraction-contract-review-r1',
              status='PENDING_A0_ORIGINAL_ARCHIVE_AND_INPUT_FREEZE', execution_enabled=False,
              explicit_native_authorization=True, source_solver_run_id=run_id,
              planned_operation_label='s2-' + output.parent.name.lower() + '-' + role.lower() + '-fields',
              operation=ref(ROOT / 'experiments/dram-see-v4/transport-probe/operation.py'),
              extractor=ref(ROOT / 'experiments/dram-see-v4/s2-inputs-r1/extract_fields.tcl'),
              audit=ref(ROOT / 'experiments/dram-see-v4/s2-inputs-r1/field_audit.py'),
              planned_budget_reservation_id=requests[1]['request_id'], budget_reservation_id=None,
              budget_id=budget['budget_id'], category='native_field_extractions', svisual_calls=1,
              source_solver_manifest_sha256=None, source_solver_archive_sha256=None,
              actual_tdr_inputs=None, task_sh_sha256=None, execution_input_manifest_sha256=None,
              rule='Freeze the full same-run TDR selection and original operation inputs after A0 acceptance; no new operation implementation.'))
    write(dest / 'execution-release.review.json', execution)
    binding = dict(schema='s2-role-release-contract-review-r1', role_id=role, order=index + 1,
                   mode='produce' if index < 2 else 'reuse', planned_run_id=run_id, actual_run_id=None,
                   producer_run_id=producer, previous_role=None if index == 0 else ROLES[index - 1],
                   previous_role_acceptance_sha256=None, planned_release_id=release_id,
                   local_original_run_directory=str(ROOT / 'local_runtime/runs' / run_id),
                   local_run_collision_checked=True, remote_run_collision_checked=False,
                   execution_enabled=False, owner_release_approved=False,
                   source_role_contract=source_ref(prefix + 'role-contract.json', inventory),
                   review_inputs=ref(dest / 'input-review.json'), execution_review=ref(dest / 'execution-release.review.json'),
                   stop_on='unknown/nonzero exit; missing provenance; unchanged geometry/electrical/resource/budget/owner gate failure',
                   recovery='Inspect only the same original run/operation directory; never resubmit an unknown job.')
    write(dest / 'role-contract.review.json', binding)
    return ref(dest / 'role-contract.review.json')


def prepare(output, authorization, stamp, spine=False):
    output = Path(output).resolve()
    require(RUNTIME in output.parents and not output.exists(), 'Use a new isolated contract review directory')
    require(re.fullmatch(r'\d{8}T\d{6}Z', stamp), 'Explicit UTC batch stamp required')
    authority, owner = foundation(authorization)
    output.mkdir(parents=True)
    write(output / 'authorization.json', authority)
    write(output / 'owner-binding.json', owner)
    base = dict(schema='s2-first-four-release-contract-r1', status='OFFLINE_REVIEW_NOT_RELEASED',
                execution_enabled=False, native_calls=0, patches_applied=False,
                source_candidate=ref(CANDIDATE / 'candidate-manifest.json'),
                reused_acceptance=ref(INTEGRATION / 'root-acceptance.json'),
                authorization=ref(output / 'authorization.json'), owner=ref(output / 'owner-binding.json'),
                batch_stamp=stamp, created_utc=datetime.now(timezone.utc).isoformat())
    if spine:
        base.update(status='OFFLINE_SPINE_ONLY', pending='F1 exact review inputs, budget and missing evidence')
        write(output / 'spine-contract.json', base)
        return base
    inventory = read(CANDIDATE / 'candidate-manifest.json')['files_sha256']
    runs = {role: stamp + '-v4-s2-' + role.lower() + '-r1' for role in ROLES}
    for run_id in runs.values():
        require(not (ROOT / 'local_runtime/runs' / run_id).exists(), 'Planned original run directory already exists')
    budget = budget_review(stamp, runs)
    write(output / 'budget.review.json', budget)
    roles = [role_review(output, role, i, runs, budget, inventory) for i, role in enumerate(ROLES)]
    gaps = [
        dict(id='BUDGET', applies_to=list(ROLES), status='UNAPPROVED',
             requirement='Approve exact new S2 limits and establish the distinct operational ledger; planned requests are not reservations.'),
        dict(id='POLICY', applies_to=list(ROLES[:2]), status='UNAPPROVED',
             requirement='Approve unchanged comparison values and issue geometry policies with exact input binding.'),
        dict(id='RESOURCE', applies_to=list(ROLES), status='MISSING_EVIDENCE',
             requirement='Provide justified per-role storage/memory/CPU forecasts and live admission; first D2 does not require its future actual mesh.'),
        dict(id='OWNER_RELEASE', applies_to=list(ROLES), status='NOT_RELEASED',
             requirement='Original owner lock holder must bind a new S2 release; old nuclear entry/reservation writer remains held.'),
        dict(id='PATCH_APPLICATION', applies_to=list(ROLES), status='AUTHORIZED_NOT_APPLIED',
             requirement='Apply one of the alternative tcad patches plus original operation patch at release time and bind actual implementation hashes.'),
        dict(id='EXECUTION_INPUT', applies_to=list(ROLES), status='NOT_FROZEN',
             requirement='Materialize reviewed payload, approved policies and true reservations; freeze project.json + non-cyclic input-manifest before releases.'),
        dict(id='D3_EVIDENCE', applies_to=list(ROLES[2:]), status='PENDING_PRODUCER',
             requirement='Bind accepted D3 original manifest/tar/mesh/context and raw exits to both A0 final input freezes.'),
        dict(id='FIELD_INPUT', applies_to=list(ROLES[2:]), status='PENDING_SOLVER',
             requirement='Bind each accepted A0 archive and full TDR frame selection to its separate original-operation label and extraction reservation.'),
    ]
    write(output / 'missing-evidence.json', dict(schema='s2-release-missing-evidence-r1',
          ready_for_native=False, user_action_permission='GRANTED', items=gaps,
          requires_reasking_same_user_permission=False))
    base.update(role_order=list(ROLES), planned_run_ids=runs, roles=roles,
                budget=ref(output / 'budget.review.json'), missing_evidence=ref(output / 'missing-evidence.json'),
                user_action_permission_granted=True, contract_approved=False, ready_for_native=False,
                old_budget_modified=False, old_active_entry_modified=False,
                reused_checks=['old29', 'geometry15', 'Tcl mocks', 'integration9'],
                native_qualified=False, protected_blockers=['PMI actual BE not updated', 'R12 not compiled/released'],
                excluded_execution=['B2/B3/B4', 'compile/training without their own role/input/budget/release'],
                patch_choices=dict(combined=source_ref('tcad.capture-and-geometry.review.patch', inventory),
                                   incremental=source_ref('tcad.geometry-only.review.patch', inventory),
                                   operation=source_ref('operation.capture-r3.review.patch', inventory),
                                   rule='Choose combined on original runner OR incremental on capture-r3; never both.'),
                handoff_order=['Approve exact budget/unchanged comparison policy; review initial D2 resource forecast.',
                               'Original owner performs fresh process/strict-SSH/shared-lock/resource and run-ID admission.',
                               'Apply authorized candidate patches, freeze exact executable D2 input and issue owner release.',
                               'Execute and accept each role serially; D3 supplies A0 mesh; each A0 supplies its field extraction.'])
    write(output / 'contract.json', base)
    write(output / 'review-manifest.json', dict(schema='s2-release-contract-review-inventory-r1',
          files_sha256={p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--authorization', required=True, type=Path)
    parser.add_argument('--stamp', required=True)
    parser.add_argument('--spine', action='store_true')
    args = parser.parse_args()
    result = prepare(args.output, args.authorization, args.stamp, args.spine)
    print(json.dumps({'status': result['status'], 'execution_enabled': False, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
