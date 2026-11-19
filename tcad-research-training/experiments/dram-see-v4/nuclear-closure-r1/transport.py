"""Frozen natural-event requests on the unchanged original operation adapter."""
import csv
import json
from pathlib import Path
import shlex
import shutil
import common as c

LEGACY = c.HERE.parent/'matched-transport-r1'
BUILD_LABEL = 'nc-r1-transport-build'


def contract():
    value = c.read(c.HERE/'transport-contract.json')
    c.require(value['closure_revision']=='nuclear-closure-r1', 'Wrong transport revision')
    c.require(c.sha(c.GEOMETRY)==value['geometry_sha256'], 'Geometry changed')
    return value


def legacy():
    return c.module(LEGACY/'control.py', '_nc_original_transport_control')


def header(value):
    result = legacy().header(value)
    old = c.sha(LEGACY/'matched-contract.json')
    c.require(result.count(old)==1, 'Expected unique generated contract binding')
    return result.replace(old, c.sha(c.HERE/'transport-contract.json'))


def assert_operation_complete(folder):
    return legacy().assert_operation_complete(Path(folder))


def request(label):
    rows = [r for r in contract()['requests'] if r['label']==label]
    c.require(len(rows)==1, 'Request outside preregistered manifest')
    return rows[0]


def compile_inputs():
    folder = c.OLD_OPS/'inputs'/BUILD_LABEL
    folder.mkdir(parents=True, exist_ok=False)
    for source,name in [(LEGACY/'transport_matched.cc','transport_matched.cc'),
                        (c.HERE/'transport-contract.json','matched-contract.json'),
                        (c.GEOMETRY,'geometry-contract.json')]:
        shutil.copyfile(source,folder/name)
    (folder/'geometry.hh').write_text(header(contract()),encoding='utf-8',newline='\n')
    for name in ('environment.sh','dataset-inventory.json'):
        shutil.copyfile(c.OLD_OPS/'operations/install-data-r2/collected'/name,folder/name)
    shutil.copyfile(c.HERE.parent/'transport-probe/environment-spec.json',folder/'environment-spec.json')
    legacy().hashlist(folder)
    script='''set -euo pipefail
sha256sum -c input-hashes.sha256
source environment.sh
G4ROOT=/home/tcad/research-training/dram-see-v1/software/Geant4-10.7.3-Linux
g++ --version > compiler-version.txt
"$G4ROOT/bin/geant4-config" --version > geant4-version.txt
g++ -O2 $("$G4ROOT/bin/geant4-config" --cflags) transport_matched.cc -o transport_matched $("$G4ROOT/bin/geant4-config" --libs)
ldd transport_matched > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
sha256sum transport_matched transport_matched.cc geometry.hh matched-contract.json geometry-contract.json environment.sh dataset-inventory.json > build-sha256.txt
'''
    (folder/'task.sh').write_text(script,encoding='utf-8',newline='\n')
    return folder


def require_initialization_gate():
    for arm in ('h','e'):
        label='nc-r1-init-'+arm
        record=c.RT/'transport/runs'/label/'record.json'
        audit=c.RT/'transport/audits'/label/'audit.json'
        a=c.read(audit)
        c.require(a['passed'] is True and a['record_sha256']==c.sha(record), 'Initialization not accepted')
        c.require(a['audit_code_sha256']==c.sha(c.HERE/'transport_audit.py'),'Initialization audit revision changed')
        c.require(c.read(record)['request']==request(label),'Initialization identity changed')


def prepare(label,build):
    r=request(label)
    if r['mode']!='init':require_initialization_gate()
    build=Path(build).resolve()
    assert_operation_complete(build)
    c.require(not (c.OLD_OPS/'operations'/label).exists(),'Request already has original operation; reconcile only')
    for name,path in [('transport_matched.cc',LEGACY/'transport_matched.cc'),
                      ('matched-contract.json',c.HERE/'transport-contract.json'),
                      ('geometry-contract.json',c.GEOMETRY)]:
        c.require(c.sha(build/'collected'/name)==c.sha(path),'Build/source mismatch: '+name)
    c.require((build/'collected/geometry.hh').read_text()==header(contract()),'Header differs')
    folder=c.OLD_OPS/'inputs'/label
    folder.mkdir(parents=True,exist_ok=False)
    for name in ('transport_matched','transport_matched.cc','geometry.hh','matched-contract.json',
                 'geometry-contract.json','environment.sh','dataset-inventory.json','environment-spec.json'):
        shutil.copyfile(build/'collected'/name,folder/name)
    c.write(folder/'request.json',r)
    c.write(folder/'package-origin.json',dict(build_operation_path=build.relative_to(c.ROOT).as_posix(),
       build_operation_sha256=c.sha(build/'operation.json'),control_sha256=c.sha(Path(__file__))))
    legacy().hashlist(folder)
    script='\n'.join(['set -euo pipefail','sha256sum -c input-hashes.sha256','source environment.sh',
        'chmod u+x transport_matched',
        "printf '%s  binary\\n' \"$(sha256sum transport_matched | cut -d ' ' -f1)\" > provenance.sha256",
        "printf '%s  environment\\n' \"$(sha256sum environment.sh | cut -d ' ' -f1)\" >> provenance.sha256",
        "printf '%s  dataset_inventory\\n' \"$(sha256sum dataset-inventory.json | cut -d ' ' -f1)\" >> provenance.sha256",
        './transport_matched '+shlex.quote(label),''])
    (folder/'task.sh').write_text(script,encoding='utf-8',newline='\n')
    return folder


def collect(operation_folder):
    opfolder=Path(operation_folder).resolve()
    receipt=c.read(opfolder/'operation.json');label=receipt['label']
    r=request(label)
    c.require(opfolder==(c.OLD_OPS/'operations'/label).resolve(),'Wrong original operation')
    c.require(receipt.get('state') in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'),'Unknown operation state; inspect original directory')
    source=opfolder/'collected'
    c.require(c.read(source/'request.json')==r,'Wrong collected request')
    destination=c.RT/'transport/runs'/label
    if (destination/'record.json').exists():
        old=c.read(destination/'record.json')
        c.require(old['operation_evidence']==c.ref(opfolder/'operation.json'),'Original receipt changed')
        return destination
    # Never overwrite partially copied evidence after an interruption.
    shutil.copytree(source,destination)
    record=dict(schema='dram-see-v4-matched-run-r1',closure_revision='nuclear-closure-r1',run_id=label,
        mode='init' if r['mode']=='init' else 'events',arm=r['arm'],request=r,
        runner_exit_code=receipt['ssh_exit_code'],remote_exit_code=receipt['remote_exit_code'],
        collection_exit_code=receipt['collection_exit_code'],
        runner_exit_definition='Actual synchronous original operation.py SSH wrapper code',
        input_sha256=receipt['input_sha256'],binary_sha256=c.sha(destination/'transport_matched'),
        environment_sha256=c.sha(destination/'environment.sh'),dataset_inventory_sha256=c.sha(destination/'dataset-inventory.json'),
        raw_archive=c.ref(opfolder/'results.tar'),operation_evidence=c.ref(opfolder/'operation.json'),
        provenance_files=dict(binary='transport_matched',binary_witness='provenance.sha256',environment='environment.sh',dataset_inventory='dataset-inventory.json'),
        output_sha256={p.relative_to(destination).as_posix():c.sha(p) for p in sorted(destination.rglob('*')) if p.is_file()})
    c.write(destination/'record.json',record)
    return destination


def audit(label):
    record=c.RT/'transport/runs'/label/'record.json'
    dest=c.RT/'transport/audits'/label
    if (dest/'audit.json').exists():
        result=c.read(dest/'audit.json')
        c.require(result['record_sha256']==c.sha(record) and result['audit_code_sha256']==c.sha(c.HERE/'transport_audit.py'),'Audit binding changed')
        return result
    auditor=c.module(c.HERE/'transport_audit.py','_nc_transport_audit')
    fun=auditor.audit_init if request(label)['mode']=='init' else auditor.audit_events
    return fun(record.parent,dest)


def choose(stage):
    """Selection only after all requests in a stage passed; no response ranking."""
    rows=[r for r in contract()['requests'] if r['closure_stage']==stage]
    reports=[]
    for r in rows:
        a=audit(r['label']);c.require(a['passed'] is True,'Incomplete/failed stage')
        reports.append((r,a))
    for r,a in reports:
        if r['arm']!='H' or r['mode']=='init':continue
        candidates=sorted(a['mechanism_summary']['qualifying_witnesses'],key=lambda w:(w['event_id'],w['parent_track_id'],w['parent_step_id']))
        if not candidates:continue
        run=c.RT/'transport/runs'/r['label']
        eligible={}
        with (run/'steps.csv').open(newline='',encoding='utf-8') as stream:
            for step in csv.DictReader(stream):
                event=int(step['event_id']);track=int(step['track_id'])
                if step['pre_material']!='G4_Si' or float(step['ionizing_MeV'])<=0:continue
                t0=float(step['pre_t_ns']);t1=float(step['post_t_ns'])
                # Original deposit time (not a shifted Gaussian tail) must intersect Geant 0..3 ns.
                if t0<3.0 and t1>=0.0 or t0==t1==3.0:
                    for n,w in enumerate(candidates):
                        if event==w['event_id'] and track in w['descendant_track_ids']:
                            fraction=1.0 if t1==t0 else max(0.0,min(t1,3.0)-max(t0,0.0))/(t1-t0)
                            amount=float(step['ionizing_MeV'])*fraction
                            entry=eligible.setdefault(n,{'energy':0.0,'steps':[]})
                            entry['energy']+=amount
                            if amount>0:entry['steps'].append([event,track,int(step['step_id'])])
        for n,w in enumerate(candidates):
            if eligible.get(n,{}).get('energy',0)>0:
                return dict(schema='nuclear-closure-selected-event-r1',selected_utc=c.utc(),stage=stage,
                    record=c.ref(run/'record.json'),audit=c.ref(c.RT/'transport/audits'/r['label']/'audit.json'),
                    event_id=w['event_id'],request=r,
                    witness={**w,'window_descendant_si_ionizing_MeV':eligible[n]['energy'],'window_descendant_step_ids':eligible[n]['steps']},
                    selection_rule=c.contract()['transport']['selection'])
    return None
