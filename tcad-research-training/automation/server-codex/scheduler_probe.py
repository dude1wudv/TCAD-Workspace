"""One bounded, read-only SSH sample of original jobs, leases and telemetry."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time


REMOTE_PROBE = r'''
import hashlib,json,os,sys,time
from pathlib import Path
request=json.loads(sys.argv[1]); root=Path(request['root'])
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
processes={}
for path in Path('/proc').iterdir():
    if not path.name.isdigit():continue
    try:
        raw=(path/'stat').read_text();stat=raw.rsplit(')',1)[1].split()
        try:cwd=os.readlink(str(path/'cwd'))
        except OSError:cwd=None
        processes[int(path.name)]={'state':stat[0],'ppid':int(stat[1]),'pgrp':int(stat[2]),'ticks':int(stat[19]),'rss_kib':int(stat[21])*os.sysconf('SC_PAGE_SIZE')//1024,
                                   'name':raw.split('(',1)[1].rsplit(')',1)[0],'cwd':cwd}
    except (OSError,ValueError,IndexError):pass

def tail(path):
    if not path.is_file():return None
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-4096));return stream.read(4096).decode('utf-8','replace')

def observe(record):
    folder=Path(record['remote_directory'])
    value={'directory':str(folder),'alive':False,'remote_exit_code':None,'status':'START_UNCONFIRMED'}
    if not folder.is_dir():value['status']='NOT_FOUND';return value
    identity_file=folder/'process-identity.json'
    if not identity_file.is_file():return value
    identity=json.loads(identity_file.read_text());value['identity']=identity
    script=record.get('script_sha256')
    run_id=record.get('run_id',record.get('label'))
    if identity.get('cwd')!=str(folder) or identity.get('run_id')!=run_id or identity.get('script_sha256')!=script:
        raise ValueError('original identity mismatch')
    if hashlib.sha256((folder/'run.sh').read_bytes()).hexdigest()!=script:raise ValueError('original script mismatch')
    pinned=record.get('process_identity')
    if pinned and any(pinned.get(k)!=identity.get(k) for k in ('pid','start_ticks','boot_id','cwd','run_id','script_sha256')):raise ValueError('pinned process identity mismatch')
    pid=identity['pid'];proc=processes.get(pid)
    same=bool(proc and proc['ticks']==identity['start_ticks'] and identity['boot_id']==boot)
    if same:
        path=Path('/proc')/str(pid)
        if os.readlink(str(path/'cwd'))!=str(folder) or b'run.sh' not in (path/'cmdline').read_bytes():raise ValueError('live process identity mismatch')
        value['alive']=proc['state']!='Z'
    # Include descendants and any independently reparented process in this exact cwd.
    descendants={pid} if same else set()
    changed=True
    while changed:
        added={p for p,s in processes.items() if s['ppid'] in descendants}-descendants
        changed=bool(added);descendants.update(added)
    for child,stat in processes.items():
        if child==pid or stat['state']=='Z':continue
        try:
            if stat.get('cwd')==str(folder):descendants.add(child)
        except OSError:pass
    alive=[p for p in descendants if processes[p]['state']!='Z']
    value['rss_kib']=sum(processes[p]['rss_kib'] for p in alive)
    value['descendants_alive']=bool([p for p in alive if p!=pid])
    exit_file=folder/'exit-code.txt'
    if exit_file.is_file():
        raw=exit_file.read_text().strip()
        if not raw.isdigit() or not 0<=int(raw)<=255:raise ValueError('invalid original exit code')
        value['remote_exit_code']=int(raw)
    if value['alive']:value['status']='RUNNING'
    elif value['descendants_alive']:value['status']='DESCENDANTS_ALIVE'
    elif value['remote_exit_code'] is not None:value['status']='FINISHED'
    else:value['status']='LOST_WITHOUT_EXIT'
    value['log_tail']=tail(folder/'execution.log')
    value['transient_log_tail']=tail(folder/'transient_des.log')
    termination=folder/'termination-record.json'
    if termination.is_file():
        proof=checked_termination(folder,identity);value['termination_record']=proof
        if proof and not value['alive'] and not value['descendants_alive']:
            value['status']='FINISHED'
    return value

runs={}
for key,record in request['records'].items():
    try:runs[key]=observe(record)
    except (OSError,ValueError,TypeError,KeyError) as exc:runs[key]={'status':'UNKNOWN','alive':None,'error':str(exc)[:400]}
mem={}
for line in Path('/proc/meminfo').read_text().splitlines():
    key,_,value=line.partition(':')
    if key in ('MemAvailable','MemTotal'):mem[key]=int(value.split()[0])/1048576
paths=set([str(root)]+[r['remote_directory'] for r in request['records'].values()])
free={}
for path in paths:
    parent=Path(path)
    while not parent.exists() and parent!=parent.parent:parent=parent.parent
    v=os.statvfs(str(parent));free[path]=v.f_bavail*v.f_frsize/1073741824
names={value['name'] for value in processes.values()}
solver_names=('sdevice','sde','snmesh','svisual_exec','tdx','dram_transport','transport','cc1','cmi')
solvers=[{'pid':pid,'name':value['name'],'cwd':value['cwd'],'start_ticks':value['ticks']}
         for pid,value in processes.items() if value['name'].startswith(solver_names) and value['state']!='Z']
leases=[]
store=root/'.solver-slots';lease_paths=list(store.glob('slot-*.json'));slot_locks=list(store.glob('slot-*.lock'))
if len(lease_paths)>64 or len(slot_locks)>64:raise ValueError('Unbounded or out-of-range original slot store')
for path in lease_paths+slot_locks:
    suffix='.json' if path.suffix=='.json' else '.lock';number=path.name[5:-len(suffix)]
    if not number.isdigit() or not 0<=int(number)<64 or path.is_symlink():raise ValueError('Unknown original slot file: '+path.name)
for path in lease_paths:
    try:
        if path.stat().st_size>65536:raise ValueError('Oversized original lease')
        lease=json.loads(path.read_text())
        if not isinstance(lease,dict):raise ValueError('Original lease is not an object')
        leases.append(lease)
    except (ValueError,OSError) as exc:leases.append({'slot':path.name,'error':str(exc)[:200]})
lock_files={}
for path in [root/'.solver.lock',store/'allocation.lock']+slot_locks:
    if path.exists():
        stat=path.stat();lock_files[(os.major(stat.st_dev),os.minor(stat.st_dev),stat.st_ino)]=str(path)
locks=[]
for line in Path('/proc/locks').read_text().splitlines():
    parts=line.split()
    if 'FLOCK' not in parts or '->' in parts:continue
    i=parts.index('FLOCK');device=parts[i+4].split(':');key=(int(device[0],16),int(device[1],16),int(device[2]))
    if key in lock_files:locks.append(dict(path=lock_files[key],mode=parts[i+2],pid=int(parts[i+3])))
capacity=root/'.solver-slots'/'capacity.json'
if capacity.is_file() and capacity.stat().st_size>65536:raise ValueError('Oversized pool configuration')
result={'ok':True,'observed_at':time.time(),'boot_id':boot,'runs':runs,'leases':leases,
'locks':locks,'locks_verified':True,'pool_configuration':json.loads(capacity.read_text()) if capacity.is_file() else None,
'processes_with_solver_names':solvers,
'telemetry':{'mem_available_gib':mem.get('MemAvailable'),'mem_total_gib':mem.get('MemTotal'),
'remote_disk_free_gib':min(free.values()),'remote_disk_paths':free,
'license_daemons_alive':all(name in names for name in ('lmgrd','snpslmd')),'license_feature_available':None}}
print(json.dumps(result))
'''


class BatchRemoteProbe:
    def __init__(self, policy, read_only=False):
        self.policy = policy
        self.read_only = read_only
        self.failures = 0
        self.next_at = 0
        self.last_success = None

    def probe(self, records, profiles):
        now = time.time()
        if now < self.next_at:
            return {"ok": False, "observed_at": self.last_success, "runs": {},
                    "error": {"kind": "endpoint_backoff", "retry_at": self.next_at}}
        cfg = profiles["tcad"]["cfg"]
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", cfg["ssh_target"])
                or not re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)+", cfg["runtime_entry"])):
            raise ValueError("Invalid original endpoint")
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-o", "UpdateHostKeys=no"]
        if not self.read_only:
            mux = Path(self.policy["state_dir"]) / "ssh-mux"
            mux.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":mux.chmod(0o700)
            key = hashlib.sha256((cfg["ssh_target"] + cfg["runtime_entry"]).encode()).hexdigest()[:16]
            argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=120s", "-o", "ControlPath=" + str(mux / key)]
        if self.read_only:argv += ['-o','ControlMaster=no','-o','ControlPath=none']
        selected={key:{name:record[name] for name in ('run_id','label','remote_directory','script_sha256','process_identity') if name in record} for key,record in records.items()}
        for record in selected.values():
            if isinstance(record.get('process_identity'),dict):record['process_identity']={key:value for key,value in record['process_identity'].items() if key in ('pid','start_ticks','boot_id','cwd','run_id','script_sha256')}
        payload=json.dumps({'root':cfg['remote_root'],'records':selected},separators=(',',':'))
        if len(payload.encode('utf-8'))>64000:return {'ok':False,'runs':{},'error':{'kind':'probe_input_too_large'}}
        checker=''
        if records:
            import importlib.util
            source=Path(self.policy['workspace'])/'scripts/runner_termination.py'
            spec=importlib.util.spec_from_file_location('_original_termination_probe',source)
            helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
            checker=helper.TERMINATION_CHECK_CODE

        script = "/usr/bin/python3 - " + shlex.quote(payload) + " <<'SCHEDULER_PROBE'\n" + checker + REMOTE_PROBE + "\nSCHEDULER_PROBE\n"
        script = "exec " + shlex.quote(cfg["runtime_entry"]) + " /bin/bash -lc " + shlex.quote(script)
        argv += [cfg["ssh_target"], "bash -lc " + shlex.quote(script)]
        excluded = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "TCAD_MAGPIE_API_KEY"}
        environment = {k: v for k, v in os.environ.items() if k.upper() not in excluded}
        try:
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=float(self.policy.get("probe_timeout_seconds", 15)),
                                    env=environment, check=False, stdin=subprocess.DEVNULL)
            if result.returncode:
                raise ConnectionError((result.stderr or "SSH failed")[-600:])
            if len(result.stdout) > 2097152:raise ValueError("Unbounded probe response")
            sample = json.loads(result.stdout)
            if sample.get("ok") is not True or not isinstance(sample.get("runs"), dict):raise ValueError("Invalid probe response")
            sample["telemetry"]["host_disk_free_gib"] = shutil.disk_usage(self.policy["state_dir"]).free / 1073741824
            backing = self.policy.get("resources", {}).get("backing_disk_path")
            sample["telemetry"]["backing_disk_free_gib"] = shutil.disk_usage(backing).free / 1073741824 if backing else None
            observed=sample.get('observed_at')
            if type(observed) not in (int,float) or not -5<=time.time()-observed<=30:raise ValueError('Remote probe time is stale or clock differs')
            sample["remote_observed_at"]=observed;sample["observed_at"]=time.time()
            self.last_success = sample["observed_at"]
            self.failures, self.next_at = 0, 0
            return sample
        except (subprocess.TimeoutExpired, OSError, ValueError, TypeError, KeyError, ConnectionError) as exc:
            self.failures += 1
            self.next_at = now + (5, 15, 45, 120, 300)[min(self.failures - 1, 4)]
            return {"ok": False, "observed_at": self.last_success, "runs": {},
                    "error": {"kind": "TRANSIENT_NETWORK", "detail": str(exc)[:600], "retry_at": self.next_at}}
