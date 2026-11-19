"""Prepare read-only native field extraction from one collected source run."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import tarfile

ROOT=Path(__file__).resolve().parents[3]
RT=ROOT/'local_runtime/dram-see-v4/transport-probe'
def sha(p):
    digest=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run_id');p.add_argument('script',type=Path);p.add_argument('label');p.add_argument('--family',choices=['gfield','gstep'],default='gfield');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.run_id) or not re.fullmatch(r'[a-z0-9-]+',a.label):raise ValueError('Unsafe run or label')
    script=a.script.resolve()
    if not script.is_relative_to((ROOT/'experiments/dram-see-v4/source-field-audit-r1').resolve()):raise ValueError('Only declared field-audit Tcl source')
    run=ROOT/'local_runtime/runs'/a.run_id;m=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    if m['state']!='COLLECTED' or m.get('ssh_exit_code')!=0 or sha(run/'results.tar')!=m['results_sha256']:raise ValueError('Run is not a verified collected archive')
    remote=m['remote_directory']
    if not remote.endswith('/runs/'+a.run_id):raise ValueError('Remote binding differs')
    hashes={}
    with tarfile.open(run/'results.tar') as tar:
        seen=set()
        for item in tar.getmembers():
            name=item.name.removeprefix('./')
            if name in seen:raise ValueError('Duplicate archive entry')
            seen.add(name)
            if re.fullmatch(a.family+r'_[0-9]+_access_des\.tdr',name):
                if not item.isfile():raise ValueError('Nonregular TDR member')
                hashes[name]=hashlib.sha256(tar.extractfile(item).read()).hexdigest()
    if not hashes or (a.family=='gfield' and len(hashes)!=5):raise ValueError('Missing expected field family')
    folder=RT/'inputs'/a.label;folder.mkdir(parents=True,exist_ok=False)
    (folder/'extract_fields.tcl').write_bytes(script.read_bytes())
    (folder/'tdr-files.txt').write_text(''.join(n+'\n' for n in sorted(hashes)),encoding='utf-8',newline='\n')
    (folder/'tdr-sha256.txt').write_text(''.join(hashes[n]+'  '+n+'\n' for n in sorted(hashes)),encoding='utf-8',newline='\n')
    evidence=dict(schema='dram-see-v4-native-field-postprocess-r1',source_run_id=a.run_id,
                  source_archive_sha256=m['results_sha256'],source_manifest_sha256=sha(run/'manifest.json'),
                  script_sha256=sha(script),tdr_sha256=hashes,new_sdevice_solves=0,threads=1,
                  time_binding='File names are identifiers only. Accepted BE times require separate raw-log/PLT audit.')
    (folder/'source-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    commands=['set -euo pipefail']
    commands+=['cp -- '+shlex.quote(remote+'/'+n)+' '+shlex.quote(n) for n in sorted(hashes)]
    commands+=['sha256sum -c tdr-sha256.txt','set +e',
      '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl > svisual.log 2>&1',
      'v4_field_rc=$?','printf "%s\\n" "$v4_field_rc" > svisual-exit-code.txt','set -e','test "$v4_field_rc" -eq 0',
      "grep -F 'FIELD_AUDIT_COMPLETED mandatory_errors=0' svisual.log",
      "grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt",'sha256sum -c tdr-sha256.txt',
      'test -s field-inventory.csv','test -s field-measurements.csv','echo NATIVE_FIELD_POSTPROCESS_COMPLETED']
    (folder/'task.sh').write_text('\n'.join(commands)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(input=folder.relative_to(ROOT).as_posix(),tdr_count=len(hashes),new_solves=0)))

if __name__=='__main__':main()
