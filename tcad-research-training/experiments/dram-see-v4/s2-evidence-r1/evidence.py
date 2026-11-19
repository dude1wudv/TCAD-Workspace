"""Read-only evidence adapter. No subprocess, network, extraction or launch API."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import importlib.util

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), value.__dict__)
    return value


BASE_PATH = HERE.parent/'s2-inputs-r1/field_audit.py'
B = module(BASE_PATH, '_s2_frozen_field_audit_for_evidence')
Archive, require = B.Archive, B.require


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def skeleton(folder, kind):
    folder = Path(folder)
    name = 'manifest.json' if kind == 'solver' else 'operation.json'
    record = json.loads((folder/name).read_text(encoding='utf-8'))
    return dict(schema='s2-evidence-spine-smoke-r1', is_tcad_result=False,
                native_qualified=False, native_calls=0, status='SPINE_ONLY',
                record_file=str(folder/name), record_sha256=sha(folder/name),
                kind=kind, recorded_state=record.get('state'),
                recorded_ssh_exit=record.get('ssh_exit_code'))


def fact(value=None, kind='unavailable', source=None, digest=None, rule=None):
    return {'value':value, 'evidence_kind':kind, 'source':source, 'sha256':digest, 'rule':rule}


def object_json(raw, label):
    value=json.loads(raw)
    require(isinstance(value,dict),label+' must be a JSON object')
    return value


def mapping(value,label):
    require(isinstance(value,dict),label+' must be a mapping')
    return value


def affinity(text):
    """Parse format only; caller must label native process versus parent wrapper."""
    if re.fullmatch(r'\s*[0-9]+\s*', text):
        return {'cpu':int(text.strip()), 'threads':None, 'format':'integer_cpu', 'name':None}
    cpus = re.findall(r'^Cpus_allowed_list:\s*([^\r\n]+)', text, re.M)
    threads = re.findall(r'^Threads:\s*([0-9]+)\s*$', text, re.M)
    names = re.findall(r'^Name:\s*([^\r\n]+)', text, re.M)
    require(len(cpus)==1 and re.fullmatch(r'[0-9]+', cpus[0].strip()), 'Missing/ambiguous/multicore CPU mask')
    require(len(threads)==1 and int(threads[0])==1, 'Missing/ambiguous/non-single process thread observation')
    require(len(names)<=1, 'Ambiguous native process name')
    return {'cpu':int(cpus[0]), 'threads':1, 'format':'proc_status', 'name':names[0].strip() if names else None}


def _exit(raw, label):
    require(re.fullmatch(rb'[0-9]+\s*', raw) is not None, 'Noninteger raw exit: '+label)
    value = int(raw)
    require(0 <= value <= 255, 'Raw exit outside shell range: '+label)
    return value


def _member_fact(archive, name, parser):
    if name not in archive.members:
        return fact(rule='Required original member was not recorded: '+name)
    return fact(parser(archive.read(name)), 'observed', name, archive.digest(name))


def _process_identity(archive, prefix, tool, record):
    name=prefix+'-process-observation.json'
    status_name=prefix+'-process-status.txt'
    if name not in archive.members or status_name not in archive.members:
        return fact(rule='Required exact native process observation/status binding was not recorded')
    observation=object_json(archive.read(name),'native process observation')
    require(observation.get('schema')=='native-process-observation-r1', 'Unknown native process observation schema')
    require(observation.get('origin')==record.get('origin') and observation.get('synthetic') is record.get('synthetic'),
            'Process observation origin mismatch')
    require(observation.get('status')=='OBSERVED' and observation.get('requested_tool')==tool,
            'Native process was not uniquely observed')
    require(observation.get('status_file')==status_name and observation.get('status_sha256')==archive.digest(status_name),
            'Native raw status identity/hash mismatch')
    pairs=[line.split(':',1) for line in archive.read(status_name).decode().splitlines() if ':' in line]
    require(len({p[0] for p in pairs})==len(pairs), 'Duplicate native status fields')
    fields={key:value.strip() for key,value in pairs}
    require(fields.get('Name')==tool, 'Native process name is not the exact tool')
    for key in ('native_pid','native_start_ticks','root_child_pid','wrapper_pid'):
        require(type(observation.get(key)) is int and observation[key]>0, 'Invalid native identity '+key)
    installation=observation.get('installation_root')
    executable=observation.get('native_executable')
    for value in (installation,executable):
        require(isinstance(value,str) and value.startswith('/') and value!='/' and
                posixpath.normpath(value)==value and not value.startswith('//'), 'Invalid native executable path')
    require(PurePosixPath(executable).name==tool and executable.startswith(installation+'/'),
            'Native executable does not bind the exact installed tool')
    chain=observation.get('parent_chain')
    require(isinstance(chain,list) and 1<=len(chain)<=128, 'Missing native parent chain')
    for node in chain:
        mapping(node,'native parent chain node')
        require(all(type(node.get(k)) is int and node[k]>0 for k in ('pid','ppid','start_ticks')),
                'Invalid native parent chain identity')
    require(len({n['pid'] for n in chain})==len(chain),'Repeated PID in native parent chain')
    require(chain[0]['pid']==observation['root_child_pid'] and chain[0]['ppid']==observation['wrapper_pid'],
            'Native root child is not bound to wrapper')
    require(all(chain[i]['ppid']==chain[i-1]['pid'] for i in range(1,len(chain))), 'Broken native parent chain')
    last=chain[-1]
    require(last['pid']==observation['native_pid'] and last['start_ticks']==observation['native_start_ticks']
            and last.get('name')==tool, 'Native leaf identity mismatch')
    require(fields.get('Pid')==str(last['pid']) and fields.get('PPid')==str(last['ppid']),
            'Raw native PID/PPid differs from observation')
    return fact(observation,'observed',name,archive.digest(name),
                'Exact original snapshot binding only; not whole-run thread/CPU proof')


def _process_admission(archive, prefix, tool, record, identity, affinity_fact):
    name=prefix+'-process-admission.json'
    exit_name=prefix+'-process-admission-exit-code.txt'
    if name not in archive.members or exit_name not in archive.members:
        return fact(rule='Required separate original process-admission record/exit was not recorded')
    admission=object_json(archive.read(name),'native process admission')
    require(admission.get('schema')=='native-process-admission-r1' and admission.get('origin')==record.get('origin')
            and admission.get('synthetic') is record.get('synthetic'), 'Process admission schema/origin mismatch')
    if identity['evidence_kind']!='observed' or affinity_fact['evidence_kind']!='observed':
        return fact(source=name,digest=archive.digest(name),
                    rule='Process admission cannot replace missing original identity/affinity')
    require(admission.get('status')=='PASSED' and admission.get('errors')==[]
            and admission.get('requested_tool')==tool and admission.get('actual_native_exit_is_separate') is True,
            'Original native process admission failed or changed')
    require(admission.get('requested_cpu')==str(affinity_fact['value']['cpu']), 'Process admission CPU differs')
    require(_exit(archive.read(exit_name),exit_name)==0, 'Nonzero original process admission exit')
    return fact(dict(admission,raw_exit_file=exit_name,raw_exit_sha256=archive.digest(exit_name)),
                'observed',name,archive.digest(name),'Independent capture admission; native tool rc is separate')


def inspect(folder, kind):
    """Hash immutable original archives, report observations and unresolved gaps.

    Existing archives without an explicit origin remain unqualified historical
    format evidence. This function never creates receipts or fills unknown rc=0.
    """
    require(kind in ('solver','extraction'), 'Unknown operation kind')
    folder = Path(folder).resolve()
    manifest_name = 'manifest.json' if kind=='solver' else 'operation.json'
    path = folder/manifest_name
    require(not path.is_symlink(), 'Manifest symlink refused')
    original_hash = sha(path)
    record = object_json(path.read_text(encoding='utf-8'),'original manifest')
    archive_hash = sha(folder/'results.tar')
    require(record.get('results_sha256', record.get('archive_sha256'))==archive_hash, 'Manifest/archive hash mismatch')
    require(record.get('state') in ('COLLECTED','COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'), 'Incomplete original operation')
    tool = 'sdevice' if kind=='solver' else 'svisual'
    if kind=='solver':
        steps=record.get('steps')
        require(isinstance(steps,list) and all(isinstance(s,dict) for s in steps),'Original solver steps must be a list of objects')
        positions=[i for i,s in enumerate(steps,1) if s.get('tool')=='sdevice']
        require(len(positions)==1,'S2 evidence adapter requires exactly one SDevice step')
        tool_prefix='step-{:03d}-sdevice'.format(positions[0])
    else:
        tool_prefix='svisual'
    facts, notes = {}, []
    for key in ('ssh_exit_code','collection_exit_code'):
        value = record.get(key)
        if value is not None:
            require(type(value) is int and 0 <= value <= 255, 'Invalid recorded '+key)
            facts[key] = fact(value,'observed',manifest_name,original_hash)
        else:
            facts[key] = fact(rule='No independently persisted original '+key)
    with Archive(folder/'results.tar') as archive:
        frozen = record.get('input_sha256')
        require(isinstance(frozen,dict) and frozen, 'No original input inventory')
        for name, digest in frozen.items():
            require(B.OLD.old.safe_name(name)==name and re.fullmatch(r'[a-f0-9]{64}',digest or ''), 'Unsafe input name/hash')
            require(archive.digest(name)==digest, 'Archived input changed: '+name)
        with Archive(folder/'inputs.tar') as inputs:
            require(set(inputs.members)==set(frozen), 'Frozen input archive inventory mismatch')
            require(all(inputs.digest(n)==h for n,h in frozen.items()), 'Frozen input bytes mismatch')
        facts['remote_exit_code'] = _member_fact(archive,'exit-code.txt',lambda r:_exit(r,'exit-code.txt'))
        if record.get('remote_exit_code') is not None:
            require(type(record['remote_exit_code']) is int and record['remote_exit_code']==facts['remote_exit_code']['value'], 'Remote exit record disagrees with raw exit')
        facts['tool_exit_code'] = _member_fact(archive,tool_prefix+'-exit-code.txt',lambda r:_exit(r,tool))
        process_name = tool_prefix+'-process-status.txt'
        facts['tool_affinity'] = _member_fact(archive,process_name,lambda r:affinity(r.decode()))
        if facts['tool_affinity']['evidence_kind']=='observed':
            observed = facts['tool_affinity']['value']
            require(observed['name']==tool, 'CPU record is not the exact expected native process')
            require(observed['threads']==1, 'Native process thread observation is incomplete')
        facts['tool_process_identity']=_process_identity(archive,tool_prefix,tool,record)
        if kind=='solver':
            facts['tool_process_admission']=_process_admission(archive,tool_prefix,tool,record,
                                                             facts['tool_process_identity'],facts['tool_affinity'])
        facts['wrapper_affinity'] = _member_fact(archive,'affinity.txt',lambda r:affinity(r.decode()))
        lock_name='shared-lock-evidence.txt'
        if lock_name in archive.members:
            rows=archive.read(lock_name).decode().splitlines()
            pairs=[line.split('=',1) for line in rows if line]
            require(all(len(p)==2 for p in pairs) and len({p[0] for p in pairs})==len(pairs),'Malformed lock observation')
            lock=dict(pairs)
            require(lock.get('status')=='ACQUIRED' and lock.get('fd')=='9' and re.fullmatch(r'[0-9]+',lock.get('pid','')),'Invalid observed shared lock')
            require(lock.get('lock_path','').endswith('/.solver.lock') and lock.get('acquired_utc'), 'Incomplete shared-lock observation')
            facts['shared_lock'] = fact(lock,'observed',lock_name,archive.digest(lock_name))
        else:
            facts['shared_lock'] = fact(rule='No original lock observation; script control flow is only inferential evidence')
        log_name='transient_des.log' if kind=='solver' else 'svisual.log'
        if log_name not in archive.members and kind=='solver':
            log_name='dc_des.log'
        if log_name in archive.members:
            log=archive.read(log_name).decode()
            versions=set(re.findall(r'\bVersion\s+(W-[0-9]{4}\.[0-9]{2})\b',log))
            require(len(versions)==1,'Missing/ambiguous installed native version')
            facts['tool_version']=fact(next(iter(versions)),'observed',log_name,archive.digest(log_name))
            if kind=='solver':
                assembly=re.findall(r'Number of assembly threads:\s*([0-9]+)',log,re.I)
                linear=re.findall(r'Number of solver threads:\s*([0-9]+)',log,re.I)
                require(assembly and linear and set(assembly+linear)=={'1'}, 'Native numerical threading not single/complete')
            else:
                native_threads=re.findall(r'Multithreading will use\s+([0-9]+) threads',log)
                require(native_threads and set(native_threads)=={'1'},'Native SVisual threading not single/complete')
            facts['native_compute_threads']=fact(1,'observed',log_name,archive.digest(log_name))
        else:
            facts['tool_version']=fact(rule='Native log missing')
            facts['native_compute_threads']=fact(rule='Native threading observation missing')
        if 'run.sh' in archive.members:
            script=archive.read('run.sh').decode()
            if 'flock -n 9' in script and facts['remote_exit_code']['value']==0:
                notes.append(fact('control_flow_reached_completion','inferred','run.sh',archive.digest('run.sh'), 'Does not replace observed lock or per-tool exit'))
        if record.get('collection_exit_code') is None and record.get('state')=='COLLECTED':
            notes.append(fact('collection_success_from_state_transition','inferred',manifest_name,original_hash,'No raw collection exit code is invented'))
    require(sha(path)==original_hash and sha(folder/'results.tar')==archive_hash, 'Original evidence changed while reading')
    required=('ssh_exit_code','remote_exit_code','collection_exit_code','tool_exit_code','tool_affinity',
              'tool_process_identity','shared_lock','tool_version','native_compute_threads')
    if kind=='solver':
        required+=('tool_process_admission',)
    missing=[k for k in required if facts[k]['evidence_kind']!='observed']
    return dict(schema='s2-readonly-evidence-report-r1',kind=kind,origin=record.get('origin','historical_archive_unqualified'),
                synthetic=record.get('synthetic'), folder=str(folder),identity=record.get('run_id',record.get('label')),
                manifest_name=manifest_name,manifest_sha256=original_hash,archive_sha256=archive_hash,
                producer_sha256=record.get('runner_sha256',record.get('adapter_sha256')),
                input_sha256=frozen,remote_directory=record.get('remote_directory'),facts=facts,inferences=notes,
                observation_gaps=missing,all_required_observations_present=not missing,
                is_tcad_result=False,native_qualified=False,native_calls=0,
                scientific_acceptance=False,receipt_created=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--kind', required=True, choices=['solver', 'extraction'])
    args = p.parse_args()
    print(json.dumps(inspect(args.folder, args.kind), indent=2))


if __name__ == '__main__':
    main()
