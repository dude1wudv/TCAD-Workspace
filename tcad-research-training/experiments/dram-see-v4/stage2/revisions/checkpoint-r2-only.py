"""Derive a coordination checkpoint from immutable operation/launch evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def main():
    path=HERE/'coordination.json'; state=read(path)
    state['updated_utc']=datetime.now(timezone.utc).isoformat()
    rt=ROOT/'local_runtime/dram-see-v4'
    witness=[]
    for p in sorted((rt/'transport-probe/operations').glob('witness-*/operation.json')):
        r=read(p)
        witness.append({k:r.get(k) for k in ('label','state','started_utc','finished_utc','ssh_exit_code','remote_exit_code','collection_exit_code')})
        witness[-1]['path']=p.relative_to(ROOT).as_posix()
    sources=[]
    for p in sorted((rt/'source-interface-r2/launches').glob('*/execution.json')):
        r=read(p)
        sources.append({k:r.get(k) for k in ('label','identity','state','run_id','started_utc','finished_utc','runner_exit_code','runner_pid','launcher_pid','ssh_exit_code')})
        sources[-1]['path']=p.relative_to(ROOT).as_posix()
    state.update(witness_operations=witness,source_invocations=sources,
        active_solver=[{'family':'TCAD',**r} for r in sources if r['state'] in ('PREPARING','RUNNING')]+[
                       {'family':'Geant4',**r} for r in witness if r['state'] in ('PREPARED','RUNNING')],
        nuclear_gates=[p.name for p in (HERE.parent/'mechanism-witness/results').glob('*-gate.json') if read(p).get('passed')],
        ledger_manifests=[p.relative_to(ROOT).as_posix() for p in (rt/'source-ledger').glob('*/source_manifest.json')],
        device_evidence='device-evidence-r2/README.md; Shin original figures verified; Park inaccessible',
        note='Derived coordination view only; operation/launch/raw records are authoritative. Unknown states must be reconciled read-only, never resubmitted automatically.')
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');temp.replace(path)
    print(json.dumps({'witness_operations':len(witness),'tcad_invocations':len(sources),'active':state['active_solver'],'gates':state['nuclear_gates']}))
if __name__=='__main__':main()
