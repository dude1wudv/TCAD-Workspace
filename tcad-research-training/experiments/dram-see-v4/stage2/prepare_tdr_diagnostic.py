"""Freeze native postprocessing of copied completed A1 TDRs; no SDevice rerun."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import tarfile
import re

ROOT=Path(__file__).resolve().parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/transport-probe'
RUN=ROOT/'local_runtime/runs/20261013T115652Z-v4-source-interface-r2-a1-b1-base-9aee36a9'
SOURCE=ROOT/'experiments/dram-see-v4/source-interface-r2/diagnostics/inspect_tdr.tcl'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(revision='r1',script_name='inspect_tdr.tcl'):
    if not re.fullmatch('r[1-9][0-9]*',revision) or not re.fullmatch('inspect_tdr(?:_r[1-9][0-9]*)?\\.tcl',script_name):
        raise ValueError('Invalid explicit diagnostic revision')
    source=SOURCE.with_name(script_name)
    manifest=json.loads((RUN/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state']!='COLLECTED' or manifest['ssh_exit_code']!=0 or sha(RUN/'results.tar')!=manifest['results_sha256']:
        raise ValueError('Unverified completed archive')
    folder=RUNTIME/('inputs/r2-a1-tdr-diagnostic-'+revision);folder.mkdir(parents=True,exist_ok=False)
    (folder/'inspect_tdr.tcl').write_bytes(source.read_bytes())
    names=[f'gfield_{i}_access_des.tdr' for i in range(5)]
    hashes={}
    with tarfile.open(RUN/'results.tar') as tar:
        members={m.name.removeprefix('./'):m for m in tar.getmembers()}
        for name in names:
            m=members[name]
            if not m.isfile():raise ValueError('TDR not regular file')
            hashes[name]=hashlib.sha256(tar.extractfile(m).read()).hexdigest()
    (folder/'tdr-sha256.txt').write_text(''.join(h+'  '+n+'\n' for n,h in hashes.items()),encoding='utf-8',newline='\n')
    record={'schema':'dram-see-v4-r2-tdr-diagnostic-inputs','source_run_id':RUN.name,
            'source_archive_sha256':sha(RUN/'results.tar'),'source_manifest_sha256':sha(RUN/'manifest.json'),
            'tdr_sha256':hashes,'script_sha256':sha(source),'new_sdevice_solves':0,'threads':1,
            'purpose':'Read archived native source fields; never infer a passed generation gate from circuit voltages'}
    (folder/'source-evidence.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
    remote=manifest['remote_directory']
    if not remote.endswith('/'+RUN.name):raise ValueError('Unexpected remote evidence path')
    commands=['set -euo pipefail']
    commands += ['cp -- '+shlex.quote(remote+'/'+n)+' '+shlex.quote(n) for n in names]
    commands += ['sha256sum -c tdr-sha256.txt','set +e',
        '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script inspect_tdr.tcl > svisual.log 2>&1',
        'v4_visual_rc=$?', 'printf "%s\\n" "$v4_visual_rc" > svisual-exit-code.txt', 'set -e', 'test "$v4_visual_rc" -eq 0',
        "grep -F 'R2_NATIVE_TDR_DIAGNOSTIC_COMPLETED mandatory_errors=0' svisual.log",
        "grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt",'sha256sum -c tdr-sha256.txt',
        'test -s field-inventory.csv','test -s field-measurements.csv','echo R2_POSTPROCESS_ONLY_COMPLETED']
    (folder/'task.sh').write_text('\n'.join(commands)+'\n',encoding='utf-8',newline='\n')
    print(folder.relative_to(ROOT).as_posix())
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--revision',default='r1');parser.add_argument('--script',default='inspect_tdr.tcl')
    args=parser.parse_args();main(args.revision,args.script)
