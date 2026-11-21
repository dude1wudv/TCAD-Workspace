"""Audited cancellation helpers shared by the original TCAD and Geant4 CLIs.

Cancellation never releases a lease or edits a historical wrapper/exit file.
"""
import hashlib
import json
import time
import uuid


CANCEL_CODE = r'''
import hashlib,json,os,signal,sys,time
from pathlib import Path
request=json.loads(sys.argv[1]);record=request['record'];folder=Path(record['remote_directory'])
identity=json.loads((folder/'process-identity.json').read_text())
expected=record.get('process_identity') or record.get('last_observation',{}).get('identity')
script=record['script_sha256'];run_id=record.get('run_id',record.get('label'))
keys=('pid','start_ticks','boot_id','cwd','run_id','script_sha256')
if identity.get('cwd')!=str(folder) or identity.get('run_id')!=run_id or identity.get('script_sha256')!=script:
    raise ValueError('Original cancellation identity mismatch')
if expected and any(expected.get(k)!=identity.get(k) for k in keys):raise ValueError('Pinned cancellation identity mismatch')
if hashlib.sha256((folder/'run.sh').read_bytes()).hexdigest()!=script:raise ValueError('Original script changed')
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
if boot!=identity['boot_id']:raise ValueError('Original boot changed; use interrupted reconciliation')
policy=record.get('parallel_policy')
def lease_check():
    if policy:
        lease=json.loads((Path(policy['pool_root'])/'.solver-slots'/('slot-%d.json'%policy['slot'])).read_text())
        if lease.get('policy')!=policy or lease.get('script_sha256')!=script or lease.get('state')!='ACTIVE':
            raise ValueError('Original active cancellation lease differs')
        if lease.get('identity')!=identity:raise ValueError('Original cancellation lease identity differs')

def process(pid):
    try:
        path=Path('/proc')/str(pid);stat=(path/'stat').read_text().rsplit(')',1)[1].split()
        return {'pid':pid,'start_ticks':int(stat[19]),'ppid':int(stat[1]),'pgrp':int(stat[2]),
                'session':int(stat[3]),'state':stat[0],'cwd':os.readlink(str(path/'cwd'))}
    except (OSError,ValueError,IndexError):return None

def same(original):
    current=process(original['pid'])
    if not current:return None
    if current['start_ticks']!=original['start_ticks']:raise ValueError('PID reused; no signal sent')
    if current['state']=='Z':return None
    if current['cwd']!=str(folder):raise ValueError('Original process cwd changed')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=boot:raise ValueError('Boot changed during cancellation')
    return current

def exited_code():
    path=folder/'exit-code.txt'
    if not path.exists():return None
    raw=path.read_text().strip()
    if not raw.isdigit() or not 0<=int(raw)<=255:raise ValueError('Invalid raw exit during cancellation')
    return int(raw)

def all_processes():
    return [p for p in (process(int(path.name)) for path in Path('/proc').iterdir() if path.name.isdigit()) if p and p['state']!='Z']

def descendants(pid):
    candidates=all_processes();found={pid};changed=True
    while changed:
        added={p['pid'] for p in candidates if p['ppid'] in found}-found
        changed=bool(added);found.update(added)
    return [p for p in candidates if p['pid'] in found and p['pid']!=pid]

def write_once(path,value):
    raw=json.dumps(value,sort_keys=True).encode()
    try:
        with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    except FileExistsError:
        return json.loads(path.read_text())
    return value

lease_check()
request_path=folder/'termination-request.json'
request_value={k:v for k,v in request.items() if k!='record'}
request_value.update(schema='tcad-termination-request-r1',run_id=run_id,process_identity=identity)
request_value=write_once(request_path,request_value)
if request_value.get('process_identity')!=identity:raise ValueError('Previous cancellation request identity differs')
request_sha=hashlib.sha256(request_path.read_bytes()).hexdigest()
record_path=folder/'termination-record.json'
if record_path.is_file():
    old=json.loads(record_path.read_text())
    if old.get('request_sha256')!=request_sha:raise ValueError('Previous cancellation record differs')
    print(json.dumps(old));raise SystemExit(0)
wrapper=same(identity)
events_file=folder/'termination-events.jsonl'
signals=[json.loads(line) for line in events_file.read_text().splitlines()] if events_file.is_file() else []
if any(event.get('request_sha256')!=request_sha for event in signals):raise ValueError('Cancellation event request differs')
targets=[];mode='none'
if wrapper:
    group=identity.get('process_group')
    if group==identity['pid'] and identity.get('session_id')==identity['pid'] and wrapper['pgrp']==group and wrapper['session']==group:
        mode='independent_group'
        targets=[p for p in all_processes() if p['pgrp']==group]
        family={p['pid'] for p in descendants(identity['pid'])}|{identity['pid']}
        if any(p['pid'] not in family or p['cwd']!=str(folder) for p in targets):raise ValueError('Unrelated process in cancellation group')
    else:
        # Historical wrappers are never group-signalled. Only original, captured
        # native identities still proved to descend from the original wrapper.
        mode='verified_original_native'
        family={p['pid']:p for p in descendants(identity['pid'])}
        for tool in record.get('tool_evidence',{}).values():
            name=tool.get('process_observation_file')
            if not name or Path(name).name!=name:continue
            path=folder/name
            if not path.is_file():continue
            observation=json.loads(path.read_text())
            if observation.get('status')!='OBSERVED' or observation.get('wrapper_pid')!=identity['pid']:continue
            candidates=[{'pid':observation.get('native_pid'),'start_ticks':observation.get('native_start_ticks')}]
            candidates += [item['identity'] for item in observation.get('native_process_family',[])]
            for candidate in candidates:
                pid=candidate.get('pid');current=family.get(pid)
                if current and current['start_ticks']==candidate.get('start_ticks') and current['cwd']==str(folder):
                    executable=os.readlink('/proc/%d/exe'%pid)
                    installation=observation.get('installation_root','')
                    expected_name='svisual_exec' if tool['tool']=='svisual' else tool['tool']
                    if not installation or not executable.startswith(installation.rstrip('/')+'/') or Path(executable).name!=expected_name:
                        raise ValueError('Captured native executable changed')
                    targets.append(current)
        targets=list({p['pid']:p for p in targets}.values())
        if not targets:raise ValueError('Legacy wrapper has no verifiable independent group or original native target; manual review required')
    parents={p['pid']:p['ppid'] for p in all_processes()}
    def depth(target):
        seen=set();pid=target['pid']
        while pid in parents and pid not in seen and pid!=identity['pid']:
            seen.add(pid);pid=parents[pid]
        return len(seen)
    targets.sort(key=depth,reverse=True)
    event_path=folder/'termination-events.jsonl'
    def send(sig):
        lease_check()
        if not same(identity):return
        for target in targets:
            if not same(target):continue
            # Recheck ancestry just before every signal, including escalation.
            if target['pid']!=identity['pid'] and target['pid'] not in {p['pid'] for p in descendants(identity['pid'])}:
                raise ValueError('Original descendant relationship changed')
            try:os.kill(target['pid'],sig)
            except ProcessLookupError:continue
            event={'pid':target['pid'],'start_ticks':target['start_ticks'],'signal':sig,'sent_at':time.time(),'mode':mode,'request_sha256':request_sha}
            signals.append(event)
            with event_path.open('a') as output:output.write(json.dumps(event,sort_keys=True)+'\n');output.flush();os.fsync(output.fileno())
    send(signal.SIGTERM)
    deadline=time.monotonic()+request['grace_seconds']
    while time.monotonic()<deadline and any(same(p) for p in targets):time.sleep(.1)
    if any(same(p) for p in targets):send(signal.SIGKILL)
    deadline=time.monotonic()+max(5,request['grace_seconds'])
    while time.monotonic()<deadline and same(identity):time.sleep(.1)
remaining=[p for p in all_processes() if p['cwd']==str(folder) and p['pid']!=os.getpid()]
quiescent=not remaining and not same(identity)
raw_exit=exited_code()
# Natural success wins a cancellation race; a request alone never means killed.
signalled_exit=raw_exit is None or raw_exit in {128+event['signal'] for event in signals}
outcome='TERMINATED_BY_OPERATOR' if signals and quiescent and signalled_exit else 'NATURAL_COMPLETION' if quiescent and raw_exit is not None else 'TERMINATION_UNCONFIRMED'
value={'schema':'tcad-termination-record-r1','run_id':run_id,'process_identity':identity,
       'request_sha256':request_sha,'signals':signals,'targets':targets,'mode':mode,
       'quiescent':quiescent,'raw_exit_code':raw_exit,'execution_outcome':outcome,
       'derived_exit_code':(128+signals[-1]['signal']) if outcome=='TERMINATED_BY_OPERATOR' and raw_exit is None else None,
       'finished_at':time.time(),'remaining_processes':remaining}
if quiescent:write_once(record_path,value)
print(json.dumps(value))
'''


TERMINATION_CHECK_CODE = r'''
def checked_termination(folder, identity):
    import hashlib,json,os
    from pathlib import Path
    path=folder/'termination-record.json'
    if not path.is_file():return None
    if path.is_symlink() or (folder/'termination-request.json').is_symlink():raise ValueError('Unsafe termination receipt')
    original=json.loads((folder/'process-identity.json').read_text())
    if any(original.get(key)!=identity.get(key) for key in ('pid','start_ticks','boot_id','cwd','run_id','script_sha256')):raise ValueError('Original termination identity differs')
    identity=original
    proof=json.loads(path.read_text());request_raw=(folder/'termination-request.json').read_bytes();request=json.loads(request_raw)
    if (proof.get('schema')!='tcad-termination-record-r1' or proof.get('process_identity')!=identity
            or request.get('process_identity')!=identity or proof.get('run_id')!=identity['run_id']
            or proof.get('request_sha256')!=hashlib.sha256(request_raw).hexdigest() or proof.get('quiescent') is not True):
        raise ValueError('Original termination identity or request differs')
    raw=(folder/'exit-code.txt').read_text().strip() if (folder/'exit-code.txt').is_file() else None
    if raw is not None and (not raw.isdigit() or not 0<=int(raw)<=255):raise ValueError('Invalid original raw termination exit')
    if proof.get('raw_exit_code')!=(int(raw) if raw is not None else None):raise ValueError('Original termination raw exit differs')
    if proof.get('execution_outcome')=='TERMINATED_BY_OPERATOR':
        events=[json.loads(line) for line in (folder/'termination-events.jsonl').read_text().splitlines()]
        if not proof.get('signals') or events!=proof['signals'] or raw=='0':raise ValueError('Cancellation lacks actual signal evidence')
        if any(event.get('request_sha256')!=proof['request_sha256'] or event.get('signal') not in (2,15,9)
               or type(event.get('pid')) is not int or type(event.get('start_ticks')) is not int for event in events):
            raise ValueError('Invalid cancellation signal identity')
        if raw is not None and int(raw) not in {128+event['signal'] for event in events}:raise ValueError('Raw exit does not prove signal termination')
        if raw is None and proof.get('derived_exit_code')!=128+events[-1]['signal']:raise ValueError('Derived signal exit differs')
    elif proof.get('execution_outcome')!='NATURAL_COMPLETION':raise ValueError('Unconfirmed cancellation cannot be archived as terminal')
    ancestors={os.getpid()};pid=os.getppid()
    while pid>1 and pid not in ancestors:
        ancestors.add(pid)
        try:pid=int((Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):break
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) in ancestors:continue
        try:
            state=(process/'stat').read_text().rsplit(')',1)[1].split()[0]
            if state!='Z' and os.readlink(str(process/'cwd'))==str(folder):raise ValueError('Original task process still alive during termination collection')
        except (FileNotFoundError,ProcessLookupError,PermissionError):pass
    return proof
'''


def cancel(module, cfg, ssh, folder, record, reason, grace_seconds=15, requested_by="operator"):
    if not isinstance(reason, str) or not reason.strip():raise ValueError("Cancellation reason is required")
    if type(grace_seconds) not in (int, float) or not 0 <= grace_seconds <= 300:raise ValueError("grace-seconds must be between 0 and 300")
    if record.get("parallel_policy"):
        module.parallel_query(cfg, ssh, record, "verify")
    request = {"request_id": uuid.uuid4().hex, "requested_at": time.time(), "reason": reason,
               "requested_by": requested_by, "grace_seconds": grace_seconds, "record": record}
    # Save the request before any remote signal can be attempted.
    local = folder / ("termination-request-" + request["request_id"] + ".json")
    with local.open("x", encoding="utf-8") as stream:json.dump({k:v for k,v in request.items() if k!='record'},stream,indent=2)
    result = module.remote_python(ssh, CANCEL_CODE, [json.dumps(request)], timeout=2 * grace_seconds + 45)
    if result.get("schema") != "tcad-termination-record-r1" or result.get("run_id") != record.get("run_id", record.get("label")):
        raise ValueError("Original cancellation response differs")
    output = folder / ("termination-observation-" + request["request_id"] + ".json")
    with output.open("x", encoding="utf-8") as stream:json.dump(result,stream,indent=2)
    return result


def verify_archive(archive, record):
    """Return proven cancellation evidence from the already hash-verified archive."""
    names = set(archive.getnames())
    if 'termination-record.json' not in names:return None
    proof = json.load(archive.extractfile('termination-record.json'))
    if proof.get('schema') != 'tcad-termination-record-r1':raise ValueError('Invalid termination receipt')
    identity=json.load(archive.extractfile('process-identity.json'));pinned=record.get('process_identity')
    if not pinned or any(identity.get(key)!=pinned.get(key) for key in ('pid','start_ticks','boot_id','cwd','run_id','script_sha256')):
        raise ValueError('Archived original termination identity differs')
    request_raw = archive.extractfile('termination-request.json').read()
    request = json.loads(request_raw)
    if (proof.get('process_identity') != identity or request.get('process_identity') != identity
            or proof.get('run_id') != record.get('run_id', record.get('label'))
            or proof.get('request_sha256') != hashlib.sha256(request_raw).hexdigest()):
        raise ValueError('Original termination archive identity differs')
    raw = archive.extractfile('exit-code.txt').read().decode().strip() if 'exit-code.txt' in names else None
    if raw is not None and (not raw.isdigit() or not 0 <= int(raw) <= 255):raise ValueError('Invalid archived raw exit')
    if proof.get('raw_exit_code') != (int(raw) if raw is not None else None):raise ValueError('Archived termination raw exit differs')
    if proof.get('quiescent') is not True:raise ValueError('Archived termination is not quiescent')
    if proof.get('execution_outcome') == 'TERMINATED_BY_OPERATOR':
        if proof.get('quiescent') is not True or not proof.get('signals') or proof.get('raw_exit_code') == 0:
            raise ValueError('Cancellation request is not proven termination')
        events = [json.loads(line) for line in archive.extractfile('termination-events.jsonl').read().decode().splitlines()]
        if events != proof['signals']:raise ValueError('Archived termination signal log differs')
        if any(event.get('signal') not in (2,15,9) or type(event.get('start_ticks')) is not int
               or event.get('request_sha256') != proof['request_sha256'] for event in events):
            raise ValueError('Invalid termination signals')
        if raw is not None and int(raw) not in {128+event['signal'] for event in events}:raise ValueError('Archived raw exit does not prove signal termination')
        if raw is None and proof.get('derived_exit_code') != 128 + events[-1]['signal']:
            raise ValueError('Invalid derived exit provenance')
    elif proof.get('execution_outcome') != 'NATURAL_COMPLETION':
        raise ValueError('Unconfirmed cancellation cannot be a terminal archive')
    return proof
