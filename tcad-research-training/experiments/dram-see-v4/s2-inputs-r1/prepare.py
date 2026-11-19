"""Offline S2 review-package preparation. No solver or network entry point."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

import decks
import geometry
import alpha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE.parent / "course-plan-r13"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def inventory(folder, exclude=()):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.relative_to(folder).as_posix() not in exclude}


def prepare(output, private_physics):
    output = Path(output).resolve()
    runtime = (ROOT/'local_runtime/dram-see-v4/s2-inputs-r1').resolve()
    if runtime not in output.parents:
        raise ValueError('Private material cards must remain inside the ignored S2 local_runtime directory')
    original = PLAN/'model-contract.proposed.json'
    model = json.loads(original.read_text(encoding='utf-8'))
    decks.validate_model(model)
    geometry.validate_geometry(model)
    # Fail rather than overwrite any earlier preparation, including failed ones.
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(original, output/'model.proposed.json')
    shutil.copyfile(PLAN/'budget.proposed.json', output/'budget.proposed.json')
    alpha_result = alpha.prepare_audit(model, output/'alpha-audit')
    role_manifests = {}
    for role in decks.SCOPE_ROLES:
        folder = output/'roles'/role
        folder.mkdir(parents=True)
        dimension = 2 if role == 'B1-D2' else 3
        is_dc = role in ('B1-D2', 'B1-D3')
        bit = None if is_dc else int(role[-1])
        desc = geometry.describe_geometry(model, dimension=dimension)
        write_json(folder/'geometry-contract.json', desc)
        shutil.copyfile(original, folder/'model.proposed.json')
        decks.prepare_physics(private_physics, folder)
        if is_dc:
            (folder/'geometry.scm').write_text(geometry.render_sde(model, dimension), encoding='utf-8', newline='\n')
            device = decks.render_dc(model, dimension)
        else:
            device = decks.render_transient(model, bit)
            write_json(folder/'mesh-import.required.json', {
                'schema': 's2-mesh-import-required-r1', 'resolved': False,
                'producer_role': 'B1-D3', 'required_file': 'cell_msh.tdr',
                'required_log': 'cell_msh.log', 'actual_mesh_sha256': None,
                'producer_input_manifest_sha256': role_manifests['B1-D3'],
                'rule': 'Import only completed accepted D3 mesh/log from original archive. Verify SHA and same geometry/physics. Never rebuild or use an old geometry mesh.'})
            write_json(folder/'source-spec.json', alpha.source_spec('A0', bit, 'main'))
            for name in ('field-contract.json', 'extract_fields.tcl', 'windows.tcldata',
                         'source-contract.json', 'alpha-reference.json', 'alpha-profile.csv'):
                shutil.copyfile(output/'alpha-audit'/name, folder/name)
        (folder/'device.cmd').write_text(device, encoding='utf-8', newline='\n')
        shutil.copyfile(HERE/'mesh_resource_guard.py', folder/'mesh_resource_guard.py')
        shutil.copyfile(HERE/'metrics.py', folder/'metrics.py')
        write_json(folder/'project.review.json', decks.project_review(role))
        write_json(folder/'resource-policy.json', {
            'schema': 's2-resource-policy-r1', 'role': role, 'approved': False,
            'execution_enabled': False, 'release_id': None,
            'forecast_remote_peak_bytes': None, 'forecast_peak_memory_bytes': None,
            'forecast_evidence_sha256': None, 'scheduler_preflight_sha256': None,
            'imported_mesh_sha256': None, 'native_threads': 1, 'native_cores': 1,
            'existing_floors_GiB': {'local_free':20, 'remote_free':8, 'remote_memory':4, 'combined_retained_cap':160},
            'reason': 'No actual mesh/node/field-size observation yet. Review is not a resource or execution release.'})
        write_json(folder/'role-contract.json', {
            'schema': 's2-role-contract-r1', 'role': role, 'dimension':dimension,
            'stored_bit':bit, 'case':'DC' if is_dc else 'A0', 'execution_enabled':False,
            'parent_model_file_sha256':digest(original), 'native_syntax_verified':False,
            'contact_mapping':{'source':'SN', 'drain':'BL', 'gate':'WL', 'body':'0'},
            'area_factor':.02 if dimension == 2 else 1,
            'source_configured':False, 'literature_calibrated':False,
            'transient_segments':[] if is_dc else decks.transient_segments(model),
            'stop_conditions':['unknown/failed exit or missing provenance', 'contact/doping/material/unit mismatch',
                               'unconverged or incomplete curves', 'resource/budget/lock/owner failure',
                               'write/hold/precharge/read/KCL gate failure'],
            'acceptance_spec_sha256':digest(PLAN/'refine-logs/EXPERIMENT_PLAN.md'),
            'native_gate_status':'NOT_RUN', 'G1_status':'NOT_QUALIFIED',
            'native_field_extractions_proposed':0 if is_dc else 1})
        write_json(folder/'native-evidence.required.json', {
            'schema':'s2-native-evidence-requirements-r1', 'actual_native_evidence_present':False,
            'not_a_receipt':True, 'existing_runner':'scripts/tcad.py',
            'future_release_must_supply_before_dispatch':[
                'explicit budget/release tied to exact inputs and unique scheduler',
                'fresh local/remote storage forecast and original owner/shared lock check',
                'read-only evidence collector compatible with original runner output; no replacement runner'],
            'future_actual_artifacts':[
                'original inputs.tar/results.tar and manifest with actual exits and hashes',
                'per-tool exit, single CPU affinity, shared lock raw evidence, installed version',
                'actual geometry/contact/doping/mesh validation manifest'],
            'field_audit_for_3d_A0_only':None if is_dc else {
                'parser':'field_audit.py::audit_native',
                'source_receipt_schema':'s2-native-source-receipt-r1',
                'extractor_receipt_schema':'s2-native-field-receipt-r1',
                'publication_status':'NOT_RELEASED; protocol only, no generated native receipt',
                'full_archive_integration':'Not yet exercised; must be checked with actual future archive'}})
        (folder/'README.txt').write_text(
            role+' — OFFLINE REVIEW INPUT ONLY\n'
            'No project.json or native execution release is supplied. Do not rename and launch.\n'
            'Use the existing sole scheduler, strict SSH, shared lock, one core and one thread only after a new approved release.\n'
            +('SDE/snmesh and DC syntax/topology remain native-unverified.\n' if is_dc else
              'This A0 package intentionally has no mesh. Bind accepted D3 mesh/log and re-freeze a new execution package.\n'
              'Do not regenerate the mesh or borrow an old event/mesh. Extraction requires a separately budgeted release.\n')
            +'Any failed/unknown role is charged and preserved; inspect original directory, never resubmit automatically.\n',
            encoding='utf-8', newline='\n')
        write_json(folder/'input-manifest.json', {'schema':'s2-role-inputs-r1', 'role':role,
                   'status':'REVIEW_ONLY_NOT_RELEASED', 'execution_enabled':False,
                   'files_sha256':inventory(folder)})
        role_manifests[role] = digest(folder/'input-manifest.json')
    code = [p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py', '.tcl', '.md')]
    write_json(output/'preparation.json', {
        'schema':'s2-offline-review-package-r1', 'status':'PREPARED_FOR_REVIEW',
        'execution_enabled':False, 'native_calls':0, 'native_authorized':0,
        'model_sha256':digest(original), 'role_order':list(decks.SCOPE_ROLES),
        'role_manifest_sha256':role_manifests, 'alpha_offline_result':alpha_result,
        'code_sha256':{p.name:digest(p) for p in sorted(code)},
        'budget_proposal_sha256':digest(PLAN/'budget.proposed.json'),
        'pending':['independent input review', 'explicit new execution budget and release',
                   'fresh storage forecast and owner/shared-lock preflight',
                   'native CAD/mesh/doping/DC checks', 'D3 mesh import into both A0 packages',
                   'native function/KCL gates and later h2/dt2 qualification']})
    write_json(output/'package-manifest.json', {'schema':'s2-package-inventory-r1', 'files_sha256':inventory(output)})
    return verify(output)


def verify(output):
    output = Path(output)
    manifest = json.loads((output/'package-manifest.json').read_text(encoding='utf-8'))
    actual = inventory(output, ('package-manifest.json',))
    if actual != manifest['files_sha256']:
        raise ValueError('Review package is missing/changed or contains unexpected files')
    prep = json.loads((output/'preparation.json').read_text(encoding='utf-8'))
    if prep['execution_enabled'] is not False or prep['native_calls'] != 0 or prep['native_authorized'] != 0:
        raise ValueError('Offline preparation status changed')
    if prep['role_order'] != list(decks.SCOPE_ROLES):
        raise ValueError('First-four role set/order changed')
    for role in decks.SCOPE_ROLES:
        folder = output/'roles'/role
        if (folder/'project.json').exists() or list(folder.glob('*.tdr')):
            raise ValueError('Unexpected launch entry or fabricated native mesh')
        if digest(folder/'input-manifest.json') != prep['role_manifest_sha256'][role]:
            raise ValueError('Role identity mismatch')
        rm = json.loads((folder/'input-manifest.json').read_text(encoding='utf-8'))
        if inventory(folder, ('input-manifest.json',)) != rm['files_sha256']:
            raise ValueError('Role files mismatch')
        device = (folder/'device.cmd').read_text(encoding='utf-8')
        if 'HeavyIon(' in device or 'PMI' in device:
            raise ValueError('Particle source appeared in a no-particle role')
        if role.startswith('B1-A0') and (folder/'geometry.scm').exists():
            raise ValueError('A0 must reuse the exact D3 mesh')
    return {'status':'OFFLINE_PACKAGE_INTEGRITY_PASS', 'native_qualified':False,
            'native_calls':0, 'roles':list(decks.SCOPE_ROLES),
            'package_manifest_sha256':digest(output/'package-manifest.json'), 'file_count':len(actual)}


def skeleton(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = PLAN / "model-contract.proposed.json"
    model = json.loads(original.read_text(encoding="utf-8"))
    assert model["execution_enabled"] is False
    (output / "model.proposed.json").write_bytes(original.read_bytes())
    record = {"schema": "s2-offline-skeleton-r1", "status": "INPUT_SKELETON_ONLY",
              "execution_enabled": False, "native_calls": 0,
              "parent_model_sha256": digest(original),
              "roles": ["B1-D2", "B1-D3", "B1-A0-main-b0", "B1-A0-main-b1"]}
    (output / "skeleton.json").write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["skeleton", "prepare", "verify"])
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--private-physics", type=Path)
    args = p.parse_args()
    if args.action == 'prepare':
        if args.private_physics is None:
            p.error('--private-physics is required for prepare')
        result = prepare(args.output, args.private_physics)
    elif args.action == 'verify':
        result = verify(args.output)
    else:
        result = skeleton(args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
