"""Read-only remote readiness and conservative local/remote peak-space check."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
RT=ROOT/'local_runtime/dram-see-v4'
GiB=2**30
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def local_new_bytes():
    roots=list((ROOT/'local_runtime/runs').glob('*-v4-source-interface-r5-*'))
    roots+=list((RT/'transport-probe/operations').glob('r5-*'))
    roots += [RT/'source-interface-r5',RT/'source-field-audit-r2',RT/'interface-completion-r1']
    return sum(p.stat().st_size for base in roots if base.exists() for p in base.rglob('*') if p.is_file() and not p.is_symlink())

def forecast(profile,c):
    estimate=c['default_resource_forecast'][profile+'_raw_GiB']*GiB
    evidence=[]
    for p in (RT/'source-interface-r5/launches').glob('*/execution.json'):
        d=read(p)
        if d.get('identity',[None,None,None])[2]!=profile or d.get('runner_manifest_state')!='COLLECTED':continue
        run=ROOT/'local_runtime/runs'/d['run_id'];archive=run/'results.tar'
        if archive.is_file():
            estimate=max(estimate,archive.stat().st_size*1.2)
            evidence.append(dict(run_id=run.name,archive_bytes=archive.stat().st_size))
    return estimate,evidence

def assess(free_local,used_local,free_remote,raw,c,active):
    remote_peak=raw*c['default_resource_forecast']['remote_peak_multiplier']
    local_peak=raw*c['default_resource_forecast']['local_peak_multiplier']
    budget=c['local_reserve_GiB']*GiB;floor=c['remote_minimum_free_after_peak_GiB']*GiB
    checks=dict(no_active_solver_or_v4_postprocessor=not active,
                remote_peak_leaves_eight_GiB=free_remote-remote_peak>=floor,
                local_campaign_within_eighty_GiB=used_local+local_peak<=budget,
                local_space_available=free_local>=max(local_peak,budget-used_local))
    return dict(passed=all(checks.values()),checks=checks,forecast_raw_bytes=raw,
                forecast_remote_peak_bytes=remote_peak,forecast_local_peak_bytes=local_peak,
                local_free_bytes=free_local,local_campaign_bytes=used_local,remote_free_bytes=free_remote,
                active_processes=active)

def check(profile,label):
    c=read(HERE/'campaign.json')
    if profile not in c['profiles'] or not re.fullmatch(r'r5-[a-z0-9-]+',label):raise ValueError('Unknown resource request')
    folder=RT/'interface-completion-r1/resources'/label;folder.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('_resource_runner',ROOT/'scripts/tcad.py');runner=importlib.util.module_from_spec(spec)
    exec(compile((ROOT/'scripts/tcad.py').read_bytes(),str(ROOT/'scripts/tcad.py'),'exec'),runner.__dict__)
    cfg,ssh,_=runner.connection()
    script=r'''set -eu
rootdir=__ROOT__
date -u +%Y-%m-%dT%H:%M:%SZ
printf 'AVAILABLE_KIB '
df -Pk "$rootdir" | awk 'NR==2 {print $4}'
for procpath in /proc/[0-9]*; do
  app=$(cat "$procpath/comm" 2>/dev/null || true)
  location=$(readlink "$procpath/cwd" 2>/dev/null || true)
  case "$app" in
    sdevice*|snmesh*|sde|transport*) printf 'ACTIVE %s %s %s\n' "${procpath##*/}" "$app" "$location" ;;
    svisual*) case "$location" in "$rootdir/dram-see-v4/"*) printf 'ACTIVE %s %s %s\n' "${procpath##*/}" "$app" "$location" ;; esac ;;
  esac
done
if flock -n "$rootdir/.solver.lock" true; then printf 'LOCK_FREE\n'; else printf 'LOCK_BUSY\n'; fi
printf 'RESOURCE_SCAN_COMPLETE\n'
'''.replace('__ROOT__',shlex.quote(cfg['remote_root'].rstrip('/')))
    (folder/'read-only.sh').write_text(script,encoding='utf-8',newline='\n')
    result=subprocess.run(ssh+['bash -lc '+shlex.quote(script)],capture_output=True,timeout=45)
    (folder/'stdout.txt').write_bytes(result.stdout);(folder/'stderr.txt').write_bytes(result.stderr)
    text=result.stdout.decode(errors='replace');match=re.search(r'^AVAILABLE_KIB (\d+)$',text,re.MULTILINE)
    record=dict(schema='dram-see-v4-completion-resource-check-r1',created_utc=datetime.now(timezone.utc).isoformat(),
                profile=profile,label=label,ssh_exit_code=result.returncode,read_only=True,solver_started=False,
                campaign_sha256=sha(HERE/'campaign.json'),passed=False)
    if result.returncode==0 and match and 'RESOURCE_SCAN_COMPLETE' in text and 'LOCK_FREE' in text:
        raw,evidence=forecast(profile,c)
        record.update(assess(shutil.disk_usage(ROOT).free,local_new_bytes(),int(match[1])*1024,raw,c,
                             [line for line in text.splitlines() if line.startswith('ACTIVE ')]))
        record['prior_same_profile_archive_sizes']=evidence
    else:record['error']='Remote readiness incomplete, shared lock busy, or SSH failure'
    p=folder/'record.json';p.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return dict(**record,path=p.relative_to(ROOT).as_posix(),sha256=sha(p))
