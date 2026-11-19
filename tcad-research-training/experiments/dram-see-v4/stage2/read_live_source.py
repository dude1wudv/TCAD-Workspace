"""Read progress for an existing exact run, without acquiring or altering its lock."""
import argparse
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_id');p.add_argument('label');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.run_id) or not re.fullmatch(r'[a-z0-9-]+',a.label):
        raise ValueError('Explicit safe run ID and unique label required')
    manifest=json.loads((ROOT/'local_runtime/runs'/a.run_id/'manifest.json').read_text(encoding='utf-8'))
    remote=manifest['remote_directory']
    spec=importlib.util.spec_from_file_location('_existing_runner',ROOT/'scripts/tcad.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    cfg,ssh,_=runner.connection()
    if remote!=cfg['remote_root'].rstrip('/')+'/runs/'+a.run_id:raise ValueError('Remote path binding failed')
    output=ROOT/'local_runtime/dram-see-v4/stage2-live'/a.label;output.mkdir(parents=True,exist_ok=False)
    script=r'''set -eu
target=__TARGET__
date -u +%Y-%m-%dT%H:%M:%SZ
sed -n '/^MemTotal:/p; /^MemAvailable:/p' /proc/meminfo
for proc in /proc/[0-9]*; do
  location=$(readlink "$proc/cwd" 2>/dev/null || true)
  if [ "$location" = "$target" ]; then
    printf 'PID %s ' "${proc##*/}"
    cat "$proc/comm" 2>/dev/null || true
    sed -n '/^Threads:/p; /^Cpus_allowed_list:/p' "$proc/status" 2>/dev/null || true
  fi
done
if [ -f "$target/transient_des.log" ]; then
  grep '^Computing BE-step' "$target/transient_des.log" | tail -n 1
  tail -n 16 "$target/transient_des.log"
fi
find "$target" -maxdepth 1 -type f -name 'gstep*tdr' -printf '%s\n' | awk '{bytes+=$1; count+=1} END {printf "GSTEP_FILES %d BYTES %.0f\n",count,bytes}'
if [ -f "$target/exit-code.txt" ]; then cat "$target/exit-code.txt"; fi
'''.replace('__TARGET__',shlex.quote(remote))
    (output/'read-only.sh').write_text(script,encoding='utf-8',newline='\n')
    result=subprocess.run(ssh+['bash -lc '+shlex.quote(script)],capture_output=True,timeout=45)
    (output/'stdout.txt').write_bytes(result.stdout);(output/'stderr.txt').write_bytes(result.stderr)
    (output/'record.json').write_text(json.dumps(dict(run_id=a.run_id,local_state=manifest['state'],ssh_exit_code=result.returncode,
          utc=datetime.now(timezone.utc).isoformat(),read_only=True,solver_started=False),indent=2)+'\n',encoding='utf-8')
    print(result.stdout.decode(errors='replace'));return result.returncode

if __name__=='__main__':raise SystemExit(main())
