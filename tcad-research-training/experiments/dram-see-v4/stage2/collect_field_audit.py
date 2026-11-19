"""Bind successful native extraction to its immutable solver and operation evidence."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
RT=ROOT/'local_runtime/dram-see-v4/transport-probe'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    digest=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()
def ref(p):return p.relative_to(ROOT).as_posix()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('label');a=parser.parse_args()
    if not re.fullmatch('[a-z0-9-]+',a.label):raise ValueError('Explicit label required')
    opdir=RT/'operations'/a.label;op=read(opdir/'operation.json');data=opdir/'collected';input_dir=RT/'inputs'/a.label
    if op['state']!='COLLECTED_PENDING_AUDIT' or any(op.get(k)!=0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')):
        raise ValueError('Operation outcome not known successful')
    if sha(opdir/'results.tar')!=op['archive_sha256']:raise ValueError('Operation archive hash differs')
    evidence=read(data/'source-evidence.json');run=ROOT/'local_runtime/runs'/evidence['source_run_id'];manifest=read(run/'manifest.json')
    if manifest['state']!='COLLECTED' or manifest.get('ssh_exit_code')!=0:raise ValueError('Original solver outcome invalid')
    if sha(run/'manifest.json')!=evidence['source_manifest_sha256'] or sha(run/'results.tar')!=evidence['source_archive_sha256']:
        raise ValueError('Original solver archive/manifest changed')
    for name,digest in op['input_sha256'].items():
        if sha(input_dir/name)!=digest or sha(data/name)!=digest:raise ValueError('Extraction input changed: '+name)
    names=(data/'tdr-files.txt').read_text().splitlines()
    hashes=evidence['tdr_sha256']
    if sorted(names)!=sorted(hashes) or len(names)!=len(set(names)):raise ValueError('TDR list mismatch')
    post={n:sha(data/n) for n in names}
    if post!=hashes:raise ValueError('Copied TDR bytes changed')
    log=(data/'execution.log').read_text(encoding='utf-8')
    for name in names:
        if log.splitlines().count(name+': OK')!=2:raise ValueError('Both before/after native sha256 checks missing: '+name)
    visual=int((data/'svisual-exit-code.txt').read_text().strip())
    status=(data/'diagnostic-status.txt').read_text().splitlines()
    if visual!=0 or 'mandatory_command_errors=0' not in status or 'files_completed='+str(len(names)) not in status:
        raise ValueError('Native extractor did not complete every requested TDR')
    record=dict(schema='dram-see-v4-native-field-extraction-receipt-r1',created_utc=datetime.now(timezone.utc).isoformat(),
      solver_run_id=run.name,solver_archive_sha256=evidence['source_archive_sha256'],solver_manifest_sha256=evidence['source_manifest_sha256'],
      tdr_files_sha256=hashes,tdr_before_sha256=hashes,tdr_after_sha256=post,
      extractor_sha256=sha(data/'extract_fields.tcl'),operation_record=ref(opdir/'operation.json'),operation_record_sha256=sha(opdir/'operation.json'),
      operation_archive=ref(opdir/'results.tar'),operation_archive_sha256=op['archive_sha256'],
      svisual_exit_code=visual,remote_exit_code=op['remote_exit_code'],runner_exit_code=op['ssh_exit_code'],
      runner_exit_definition='Actual SSH process exit from existing operation.py; not an inferred scientific pass',
      collection_exit_code=op['collection_exit_code'],single_cpu_affinity=(data/'affinity.txt').read_text().strip(),
      native_outputs_sha256={p.name:sha(p) for p in data.iterdir() if p.is_file() and not p.name.endswith('.tdr')},
      new_sdevice_solves=0,physical_source_acceptance=False)
    with (opdir/'field-extraction-record.json').open('x',encoding='utf-8') as f:f.write(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(receipt=ref(opdir/'field-extraction-record.json'),frames=len(names),extraction_complete=True,physical_acceptance=False)))

if __name__=='__main__':main()
