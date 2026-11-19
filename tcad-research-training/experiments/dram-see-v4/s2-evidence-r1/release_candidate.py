"""Prepare a finite, NOT AUTHORIZED four-role release candidate. Never dispatch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import evidence as E

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ROLES=('B1-D2','B1-D3','B1-A0-main-b0','B1-A0-main-b1')
MODEL_SHA='a89d30d0429defaa6dd491869470e168a6574125af1b8f27cb7689e4f8241481'
PACKAGE_SHA='165473aacaada00f613885ced15b0d645205740cdf5c0c0fcffb50d82c18a8f3'


def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')


def prepare(package, capture, output):
    package,capture,output=map(lambda p:Path(p).resolve(),(package,capture,output))
    runtime=(ROOT/'local_runtime/dram-see-v4/s2-evidence-r1').resolve()
    E.require(runtime in output.parents,'Candidate must remain in the isolated ignored evidence runtime')
    E.require(E.sha(package/'package-manifest.json')==PACKAGE_SHA,'Wrong frozen four-role package')
    inventory=json.loads((package/'package-manifest.json').read_text())['files_sha256']
    E.require(all(E.sha(package/n)==h for n,h in inventory.items()),'Frozen four-role inputs changed')
    proposal=ROOT/'experiments/dram-see-v4/course-plan-r13/budget.proposed.json'
    budget=json.loads(proposal.read_text())
    E.require(budget['B1_first_slice']['role_ids']==list(ROLES) and budget['all_native_and_training_authorized']==0,
              'First slice or authorization changed; requires another contract')
    E.require(E.sha(package/'model.proposed.json')==MODEL_SHA,'Frozen S2 model differs')
    patches=sorted(capture.glob('*.patch'))
    E.require(len(patches)==2,'Both unapplied runner and operation capture patches are required')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(proposal,output/'budget.proposed.json')
    capture_copy=output/'capture-candidate'; capture_copy.mkdir()
    for p in sorted(capture.iterdir()):
        if p.is_file() and p.suffix in ('.patch','.json','.md'):
            shutil.copyfile(p,capture_copy/p.name)
    roles={}
    for order,role in enumerate(ROLES):
        source=package/'roles'/role
        data=json.loads((source/'input-manifest.json').read_text())
        E.require(data['role']==role and data['execution_enabled'] is False,'Role manifest changed')
        E.require(not (source/'project.json').exists(),'Review inputs contain an executable project')
        d=dict(schema='s2-unapproved-role-release-candidate-r1',role_id=role,order=order+1,
               status='CANDIDATE_NOT_RELEASED',approved=False,execution_enabled=False,
               explicit_native_authorization=False,native_launch_reservations=0,
               input_directory=str(source),input_manifest_sha256=E.sha(source/'input-manifest.json'),
               frozen_review_input_sha256=data['files_sha256'],source_case='DC' if order<2 else 'A0',
               stored_bit=None if order<2 else order-2,numerical_variant='main',
               dependency_role=None if order==0 else ROLES[order-1],
               mesh_producer_role=role if order<2 else 'B1-D3',actual_mesh_sha256=None,
               d3_producer_run_id=None,actual_run_id=None,actual_resource_observations=None,
               execution_release_id=None,budget_reservation_id=None,human_authorization=None,
               review_project_file=str(source/'project.review.json'),project_json_created=False,
               threads=1,cpu_count=1,shared_lock_required=True,
               next_dispatch_requires=['previous dependent role accepted', 'exact new execution-input freeze',
                    'explicit native authorization and distinct budget reservation',
                    'capture patch reviewed, separately applied and implementation fingerprint rechecked',
                    'fresh ownership/process/shared-lock/strict-SSH preflight',
                    'conditional resource forecast and actual resource admission',
                    'native geometry/material/contact/doping evidence producer agreed'],
               stop_conditions=['unknown or nonzero original exit', 'missing required direct observation',
                    'hash/bit/mesh/source/material/contact/doping mismatch', 'unconverged/incomplete output',
                    'any unchanged G1/G2 gate fails', 'budget/resource/owner/shared-lock failure'],
               on_unknown='Inspect the same original directory only; no automatic resubmission')
        path=output/(role+'.review.json'); write(path,d); roles[role]=E.sha(path)
    resource=dict(schema='s2-unmeasured-resource-plan-r1',approved=False,
        source='unchanged r13 first-slice proposal; actual node/runtime/peak-memory/frame-size measurements absent',
        proposal=dict(sdevice=4,mesh_builds=2,native_field_extractions=2,cpu_hours_cap=4,new_retained_GiB_cap=8),
        retained_gates_GiB=dict(local_free=20,remote_free=8,remote_available_memory=4,combined_project_retained_cap=160),
        known=dict(domain_um=[2,.5,1],mesh_max_edge_nm=[1,5,40],source_window_ps=3.2,source_max_step_ps=.04,
                   nominal_minimum_window_intervals=80),
        unknown=dict(actual_mesh_vertices=None,solver_grid_points=None,peak_memory_bytes=None,tdr_bytes_per_frame=None,
                     actual_accepted_frames=None,archive_bytes=None,wall_seconds=None,cpu_seconds=None),
        forecast_ready=False,
        rules=['80 is a minimum nominal interval count, never an upper bound or 410-frame reuse.',
               'No fixed mesh-node or solver cost is invented from nominal mesh sizes.',
               'Measure D2/D3 on future separately authorized roles; no extra probe run is added.',
               'After actual D3 mesh/field sizes, freeze the next role storage forecast before release.',
               'At caps stop new dispatch and preserve/inspect healthy or unknown work; never auto-kill/retry.'])
    write(output/'resource-plan.unmeasured.json',resource)
    code={p.name:E.sha(p) for p in HERE.glob('*.py')}
    candidate=dict(schema='s2-four-role-unapproved-release-candidate-r1',created_utc=datetime.now(timezone.utc).isoformat(),
        status='OFFLINE_CANDIDATE_NOT_AUTHORIZATION',approved=False,execution_enabled=False,native_calls=0,
        authorization_received=False,original_runner_modified=False,old_budget_modified=False,
        frozen_package_manifest_sha256=PACKAGE_SHA,model_sha256=MODEL_SHA,budget_proposal_sha256=E.sha(proposal),
        role_order=list(ROLES),role_candidate_sha256=roles,interface_code_sha256=code,
        capture_patch_sha256={p.name:E.sha(p) for p in patches},
        pending_native_facts=['direct native-process affinity/threads and original exits',
                             'real geometry/doping/contact evidence and D3 mesh identity',
                             'DC/write/hold/read/source field/KCL/convergence outcomes'],
        no_claims=['native syntax', 'real archive happy path', 'new-model source qualification', 'G1/G2 pass',
                   'physical calibration', 'PMI repair', 'commercial LPDDR5/6 reproduction'])
    write(output/'candidate.json',candidate)
    files={p.relative_to(output).as_posix():E.sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    write(output/'candidate-manifest.json',{'schema':'s2-unapproved-candidate-inventory-r1','files_sha256':files})
    return {'status':candidate['status'],'candidate_manifest_sha256':E.sha(output/'candidate-manifest.json'),
            'file_count':len(files),'roles':list(ROLES),'execution_enabled':False,'native_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('package','capture','output'): p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args(); print(json.dumps(prepare(args.package,args.capture,args.output)))


if __name__=='__main__': main()
