"""Static cleanup revision accepting the original or frozen recovery-r1 gate origin.

Original interface-completion-r1/cleanup_plan.py SHA-256:
56354a08900f6361fd7bcc408f534eb17041876d66f68f26a659c88faa49575d.
Only gate acceptance-source validation differs. All other evidence, archive,
path, whitelist and generated remote deletion protections remain unchanged.

CLI: cleanup_plan.py prepare OPERATION_LABEL ROLE_ID NEW_OUTPUT
API: prepare(operation_label, role_id, output) -> metadata
Only writes a new child of runtime/interface-completion-r1/cleanup-dev. No SSH,
subprocess, unlink, rmtree, installation or automatic retry exists in this module.
Local archives, collected copies and original solver directories are retained.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import tarfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
HERE=ROOT/'experiments/dram-see-v4/interface-completion-r1'
RT=ROOT/'local_runtime/dram-see-v4'
STATE=RT/'interface-completion-r1'
OUTPUT=STATE/'cleanup-dev'
OPERATIONS=RT/'transport-probe/operations'
CAMPAIGN=HERE/'campaign.json'
TDR=re.compile(r'gstep_[0-9]+_access_des\.tdr')
LABEL=re.compile(r'r5-[a-z0-9]+(?:-[a-z0-9]+)*')


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def read(path):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'Duplicate JSON key');out[k]=v
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,
                      parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def local_path(value):
    require(isinstance(value,str) and value and '\\' not in value and ':' not in value,'Unsafe local evidence reference')
    rel=PurePosixPath(value)
    require(not rel.is_absolute() and '..' not in rel.parts,'Evidence outside repository')
    p=ROOT.joinpath(*rel.parts)
    require(p.resolve().is_relative_to(ROOT.resolve()) and p.is_file(),'Missing/outside local evidence')
    for part in (p,*p.parents):
        if part==ROOT.parent:break
        require(not part.is_symlink() and not (hasattr(part,'is_junction') and part.is_junction()),'Linked local evidence forbidden')
    return p


def ref(path):return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def reference(path):return {'path':ref(path),'sha256':sha(path)}


def passed(report,context,require_checks=False):
    require(report.get('passed') is True and not report.get('errors'),context+' did not pass')
    if require_checks:require(isinstance(report.get('checks'),dict) and report['checks'],context+' has no actual checks')
    require(all(v.get('passed') is True for v in report.get('checks',{}).values()),context+' contains failed/unknown checks')


def gate_record(role):
    path=STATE/'gates'/(role+'.json')
    require(path.is_file(),'Final role gate missing: '+role)
    gate=read(path)
    require(gate.get('schema')=='dram-see-v4-completion-role-gate-r1' and gate.get('role_id')==role,'Wrong final role gate')
    passed(gate,'Final role gate')
    require(gate.get('campaign_sha256')==sha(CAMPAIGN),'Role gate campaign changed')
    acceptance_sha=gate.get('acceptance_code_sha256')
    if acceptance_sha=='bc0a76ff03dc0cc6eee9229dc615b23509c4ef6117ec204abfd79eace9a96a1a':
        require(sha(HERE/'acceptance.py')==acceptance_sha,'Original final acceptance code changed')
    elif acceptance_sha=='29314dd3de9c8ef56d027a9325719ba2ad85a89094e0272433d46ef914cd058e':
        recovery=HERE.parent/'original-recovery-r1'
        require(sha(recovery/'acceptance.py')==acceptance_sha,'Recovered final acceptance code changed')
        spec=importlib.util.spec_from_file_location('_cleanup_frozen_r1_proof',recovery/'recovery_proof.py')
        proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
        proof.check_release()
        release=read(recovery/'release.json')
        require(release.get('passed') is True and
                release.get('files_sha256',{}).get(ref(recovery/'acceptance.py'))==acceptance_sha,
                'Recovered final acceptance is not bound by its frozen release')
    else:
        raise ValueError('Final acceptance code is outside the explicit frozen allowlist')
    require(isinstance(gate.get('evidence'),list) and gate['evidence'],'Final role gate has no evidence')
    for item in gate['evidence']:
        file=local_path(item['path']);require(sha(file)==item['sha256'],'Gate evidence hash differs: '+item['path'])
        if item.get('requires_pass'):passed(read(file),'Gate evidence')
    return path,gate


def operation_success(op,receipt):
    require(op.get('state')=='COLLECTED_PENDING_AUDIT','Operation not successfully collected')
    for key in ('ssh_exit_code','remote_exit_code','collection_exit_code'):
        require(type(op.get(key)) is int and op[key]==0,'Unknown/nonzero operation exit: '+key)
    for key in ('svisual_exit_code','remote_exit_code','runner_exit_code','collection_exit_code'):
        require(type(receipt.get(key)) is int and receipt[key]==0,'Unknown/nonzero receipt exit: '+key)
    require(op['ssh_exit_code']==receipt['runner_exit_code'] and op['remote_exit_code']==receipt['remote_exit_code']
            and op['collection_exit_code']==receipt['collection_exit_code'],'Operation/receipt exits differ')


class Archive:
    def __init__(self,path):
        self.tar=tarfile.open(path,'r:*');self.members={}
        try:
            for member in self.tar.getmembers():
                name=member.name
                while name.startswith('./'):name=name[2:]
                p=PurePosixPath(name)
                require(not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,'Unsafe archive namespace')
                require(member.isfile() or member.isdir(),'Archive links/special entries forbidden')
                if member.isdir():continue
                require(p.as_posix() not in self.members,'Duplicate archive member')
                self.members[p.as_posix()]=member
        except Exception:self.tar.close();raise
    def digest(self,name):
        require(name in self.members,'Missing archive member: '+name);digest=hashlib.sha256()
        with self.tar.extractfile(self.members[name]) as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        return digest.hexdigest()
    def read(self,name):
        require(name in self.members and self.members[name].size<=128*1024*1024,'Missing/oversized textual member')
        return self.tar.extractfile(self.members[name]).read()
    def __enter__(self):return self
    def __exit__(self,*args):self.tar.close()


def remote_paths(remote_root,label,run_id):
    require(LABEL.fullmatch(label),'Only a new r5 operation label is allowed')
    require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-v4-source-interface-r5-[A-Za-z0-9_-]+',run_id),'Only a real r5 source run is allowed')
    require(isinstance(remote_root,str) and re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',remote_root),'Unsafe configured remote root')
    require(not any(v in ('.','..') for v in PurePosixPath(remote_root).parts),'Unnormalized remote root')
    target=remote_root+'/dram-see-v4/transport-probe/operations/'+label
    source=remote_root+'/runs/'+run_id
    return target,source


def render_script(plan):
    """Return inert shell text. This function and its callers never execute it."""
    require(re.fullmatch(r'[0-9a-f]{24}',plan['plan_id']),'Unsafe cleanup plan identity')
    require(plan['files'] and all(TDR.fullmatch(r['name']) and re.fullmatch('[0-9a-f]{64}',r['sha256']) and type(r['bytes']) is int and r['bytes']>0 for r in plan['files']),'Unsafe cleanup allowlist')
    require(len({r['name'] for r in plan['files']})==len(plan['files']),'Duplicate cleanup allowlist')
    target,source=remote_paths(plan['remote_root'],plan['operation_label'],plan['source_run_id'])
    require(target==plan['remote_target'] and source==plan['remote_source'],'Remote scope mismatch')
    lines='\n'.join(r['name']+'\t'+r['sha256']+'\t'+str(r['bytes']) for r in plan['files'])
    shell=r'''#!/bin/bash
set -euo pipefail
umask 077
rootdir=__ROOT__
target=__TARGET__
source_dir=__SOURCE__
plan_id=__PLANID__
fail() { printf 'CLEANUP_REFUSED %s\n' "$*" >&2; exit 70; }
no_links() {
    local path="$1" cursor=/ component
    local -a components
    [[ "$path" == /* ]] || fail 'nonabsolute path'
    IFS=/ read -r -a components <<< "$path"
    for component in "${components[@]}"; do
        [[ -z "$component" ]] && continue
        [[ "$component" != . && "$component" != .. ]] || fail 'path traversal'
        cursor="${cursor%/}/$component"
        [[ ! -L "$cursor" ]] || fail "symlink $cursor"
    done
    [[ "$(realpath -e -- "$path")" == "$path" ]] || fail "noncanonical path $path"
}
no_links "$rootdir"
no_links "$target"
no_links "$source_dir"
[[ -d "$target" && -d "$source_dir" && "$target" != "$source_dir" ]] || fail 'scope not directories'
[[ "$target" == "$rootdir/dram-see-v4/transport-probe/operations/"r5-* ]] || fail 'target outside r5 operation namespace'
[[ "$source_dir" == "$rootdir/runs/"* ]] || fail 'original source directory mismatch'
[[ "$(pwd -P)" != "$target" && "$(pwd -P)" != "$target/"* ]] || fail 'run cleanup from outside the target'
lock="$rootdir/.solver.lock"
[[ ! -L "$lock" ]] || fail 'linked shared lock'
if [[ -e /proc/$$/fd/9 && "$(readlink -f /proc/$$/fd/9)" == "$lock" ]]; then
    flock -n 9 || fail 'shared inherited lock busy'
else
    exec 9>"$lock"
    flock -n 9 || fail 'shared lock busy'
fi
check_processes() {
    local proc cwd uid myuid
    myuid=$(id -u)
    for proc in /proc/[0-9]*; do
        [[ -d "$proc" ]] || continue
        uid=$(awk '/^Uid:/{print $2}' "$proc/status" 2>/dev/null) || { [[ ! -d "$proc" ]] && continue; fail "cannot inspect $proc"; }
        if cwd=$(readlink "$proc/cwd" 2>/dev/null); then
            [[ "$cwd" != "$target" && "$cwd" != "$target/"* ]] || fail "active process cwd $proc $cwd"
        elif [[ "$uid" == "$myuid" && -e "$proc/exe" ]]; then
            [[ ! -d "$proc" ]] || fail "same-owner cwd unreadable $proc"
        fi
    done
}
check_processes
evidence="$target/cleanup-$plan_id"
[[ ! -e "$evidence" && ! -L "$evidence" ]] || fail 'plan already claimed; no automatic retry'
mkdir -- "$evidence"
printf 'name\tsha256\tbytes\tremoved\tsource_sha256\n' > "$evidence/actions.tsv"
printf 'name\tduplicate_sha256\tsource_sha256\tbytes\n' > "$evidence/verified-before.tsv"
printf '%s\n' __FILES__ > "$evidence/allowlist.tsv"
check_file() {
    local path="$1" expected="$2" expected_bytes="$3" got
    no_links "$path"
    [[ -f "$path" && ! -L "$path" ]] || fail "nonregular file $path"
    [[ "$(stat -c %h -- "$path")" == 1 ]] || fail "hard-linked file $path"
    [[ "$(stat -c %s -- "$path")" == "$expected_bytes" ]] || fail "size changed $path"
    got=$(sha256sum -- "$path"); got=${got%% *}
    [[ "$got" == "$expected" ]] || fail "hash changed $path"
}
on_exit() {
    local rc=$? name expected bytes got hash_rc
    trap - EXIT
    set +e
    df -B1 -P -- "$target" > "$evidence/disk-after.txt" || { [[ $rc != 0 ]] || rc=90; }
    printf 'name\texpected_sha256\tactual_sha256\tunchanged\n' > "$evidence/source-after.tsv"
    while IFS=$'\t' read -r name expected bytes; do
        got=$(sha256sum -- "$source_dir/$name" 2>/dev/null); hash_rc=$?; got=${got%% *}
        if [[ $hash_rc == 0 && "$got" == "$expected" && -f "$source_dir/$name" && ! -L "$source_dir/$name" ]]; then
            printf '%s\t%s\t%s\t1\n' "$name" "$expected" "$got" >> "$evidence/source-after.tsv"
        else
            printf '%s\t%s\t%s\t0\n' "$name" "$expected" "$got" >> "$evidence/source-after.tsv"
            [[ $rc != 0 ]] || rc=91
        fi
    done < "$evidence/allowlist.tsv"
    printf '%s\n' "$rc" > "$evidence/exit-code.txt"
    printf 'plan_id=%s\nexit_code=%s\nautomatic_retry=false\n' "$plan_id" "$rc" > "$evidence/status.txt"
    if [[ $rc == 0 ]]; then printf 'R5_DUPLICATE_TDR_CLEANUP_COMPLETED plan_id=%s\n' "$plan_id"; else printf 'R5_DUPLICATE_TDR_CLEANUP_FAILED plan_id=%s exit=%s\n' "$plan_id" "$rc" >&2; fi
    exit "$rc"
}
trap on_exit EXIT
df -B1 -P -- "$target" > "$evidence/disk-before.txt"
# Validate EVERY registered duplicate and retained original before the FIRST rm.
while IFS=$'\t' read -r name expected bytes; do
    [[ "$name" =~ ^gstep_[0-9]+_access_des\.tdr$ ]] || fail 'unexpected file name'
    check_file "$target/$name" "$expected" "$bytes"
    check_file "$source_dir/$name" "$expected" "$bytes"
    printf '%s\t%s\t%s\t%s\n' "$name" "$expected" "$expected" "$bytes" >> "$evidence/verified-before.tsv"
done < "$evidence/allowlist.tsv"
check_processes
while IFS=$'\t' read -r name expected bytes; do
    check_file "$target/$name" "$expected" "$bytes"
    check_file "$source_dir/$name" "$expected" "$bytes"
    printf '%s\t%s\t%s\t0\t%s\n' "$name" "$expected" "$bytes" "$expected" >> "$evidence/actions.tsv"
    rm -- "$target/$name"
    [[ ! -e "$target/$name" && ! -L "$target/$name" ]] || fail "removal not confirmed $name"
    check_file "$source_dir/$name" "$expected" "$bytes"
    printf '%s\t%s\t%s\t1\t%s\n' "$name" "$expected" "$bytes" "$expected" >> "$evidence/actions.tsv"
done < "$evidence/allowlist.tsv"
'''
    for key,value in {'__ROOT__':plan['remote_root'],'__TARGET__':target,'__SOURCE__':source,'__PLANID__':plan['plan_id'],'__FILES__':lines}.items():
        shell=shell.replace(key,shlex.quote(value))
    return shell.encode()


def prepare(operation_label,role_id,output):
    require(LABEL.fullmatch(operation_label) is not None,'Only new r5-* operation labels may be cleaned')
    require(re.fullmatch(r'a[0-9]+(?:s[24])?-b[01]-(?:main|time|fine)',role_id),'Unsafe role ID')
    campaign=read(CAMPAIGN);requests={r['role_id']:r for r in campaign['roles']}
    require(role_id in requests and requests[role_id]['case_id']!='A0','Only a current registered nonzero-source role is eligible')
    gate_path,gate=gate_record(role_id)
    registry_path=STATE/'evidence-registry.json';registry=read(registry_path)
    require(registry['schema']=='dram-see-v4-completion-evidence-registry-r1','Unknown evidence registry')
    row=registry['runs'][role_id];wanted=requests[role_id]
    require(row['role']==[wanted['case_id'],wanted['stored_bit'],wanted['variant']],'Registry role differs')
    run_manifest=local_path(row['run']+'/manifest.json');run=run_manifest.parent;manifest=read(run_manifest)
    require(run.name==manifest['run_id']==gate['run_id'] and '-v4-source-interface-r5-' in run.name,'Gate is not tied to this r5 source run')
    require(manifest['state']=='COLLECTED' and type(manifest.get('ssh_exit_code')) is int and manifest['ssh_exit_code']==0,'Source solver outcome unknown/failed')
    source_tar=run/'results.tar';require(sha(source_tar)==manifest['results_sha256'],'Source results archive hash differs')
    audit_path=local_path(row['audit']);require(sha(audit_path)==row['audit_sha256'],'Final source audit hash differs')
    audit=read(audit_path);passed(audit,'Final source audit',True)
    require(audit['audit_code_sha256']==sha(HERE.parent/'source-interface-r5/audit_interface.py')
            and audit['contract_sha256']==sha(HERE.parent/'source-interface-r5/source_contract.json'),'Final source audit implementation changed')
    require(audit['run_id']==run.name and audit['archive_sha256']==manifest['results_sha256'] and audit['manifest_sha256']==sha(run_manifest),'Final source audit identifies different raw evidence')
    require(any(e['path']==ref(audit_path) and e['sha256']==sha(audit_path) for e in gate['evidence']),'Final gate does not bind the registered source audit')
    field_path=local_path(row['field_audit']);require(sha(field_path)==row['field_audit_sha256'],'Registered field audit hash differs')
    field=read(field_path);passed(field,'Native full field audit',True)
    require(audit['native_field_audit']['sha256']==sha(field_path) and Path(audit['native_field_audit']['path']).resolve()==field_path,'Final source audit binds another field report')
    require(field['schema']=='source-field-audit-r2' and field['mode']=='full' and field['field_measurements_passed'] is True and not field.get('field_gate_failures'),'Sparse/failed field audit cannot authorize cleanup')
    require(field['run_id']==run.name and field['archive_sha256']==manifest['results_sha256'] and field['manifest_sha256']==sha(run_manifest),'Field audit identifies different source evidence')
    field_dir=HERE.parent/'source-field-audit-r2'
    require(field['audit_sha256']==sha(field_dir/'audit_fields.py') and field['field_contract_sha256']==sha(field_dir/'field_contract.json'),'Field code/contract changed')
    require(field['audit_tolerances']==read(field_dir/'field_contract.json')['audit_tolerances'],'Field gates changed')
    require(Path(field['frames_csv_path']).resolve()==field_path.parent/'frames.csv' and sha(field_path.parent/'frames.csv')==field['frames_csv_sha256'],'Published full native frame CSV changed')
    opdir=OPERATIONS/operation_label;data=opdir/'collected'
    op_path=opdir/'operation.json';receipt_path=opdir/'field-extraction-record.json'
    op,receipt=read(op_path),read(receipt_path);operation_success(op,receipt)
    require(receipt['schema']=='dram-see-v4-native-field-extraction-receipt-r1','Unknown extraction receipt')
    require(field['extraction_record']==receipt and field['extraction_record_sha256']==sha(receipt_path),'Field audit does not bind this operation receipt')
    require(Path(field['extraction_directory']).resolve()==data.resolve(),'Field extraction directory differs')
    require(local_path(receipt['operation_record'])==op_path and sha(op_path)==receipt['operation_record_sha256'],'Operation identity/hash differs')
    operation_tar=local_path(receipt['operation_archive'])
    require(operation_tar==opdir/'results.tar' and sha(operation_tar)==op['archive_sha256']==receipt['operation_archive_sha256'],'Complete local operation archive differs')
    require(receipt['solver_run_id']==run.name and receipt['solver_archive_sha256']==manifest['results_sha256'] and receipt['solver_manifest_sha256']==sha(run_manifest),'Receipt source binding differs')
    evidence=read(data/'source-evidence.json');hashes=receipt['tdr_files_sha256'];names=(data/'tdr-files.txt').read_text().splitlines()
    require(names and len(names)==len(set(names)) and all(TDR.fullmatch(n) for n in names),'Only complete registered gstep digit TDRs may be deleted')
    require(set(names)==set(hashes)==set(evidence['tdr_sha256'])==set(receipt['tdr_before_sha256'])==set(receipt['tdr_after_sha256']),'TDR inventories differ')
    require(evidence['source_run_id']==run.name and evidence['source_archive_sha256']==manifest['results_sha256'] and evidence['source_manifest_sha256']==sha(run_manifest),'Source evidence binding differs')
    require(field['field_measurements_sha256']==receipt['native_outputs_sha256']['field-measurements.csv'],'Field raw measurement binding differs')
    files=[]
    with Archive(source_tar) as source,Archive(operation_tar) as operation:
        require({n for n in source.members if TDR.fullmatch(n)}==set(names),'Not every source gstep is registered')
        require({n for n in operation.members if TDR.fullmatch(n)}==set(names),'Operation gstep inventory differs')
        require({n for n in operation.members if n.endswith('.tdr')}==set(names),'Unregistered TDR exists in the operation archive')
        require(source.read('exit-code.txt').strip()==b'0' and operation.read('exit-code.txt').strip()==b'0' and operation.read('svisual-exit-code.txt').strip()==b'0','Archived raw execution exit differs')
        for name,digest in manifest['input_sha256'].items():require(source.digest(name)==digest,'Frozen solver input hash differs')
        for name,digest in receipt['native_outputs_sha256'].items():
            require(re.fullmatch(r'[A-Za-z0-9_.-]+',name) and sha(local_path(ref(data/name)))==digest==operation.digest(name),'Native output evidence hash differs')
        for name,digest in op['input_sha256'].items():require(operation.digest(name)==digest,'Operation input hash differs')
        for name in names:
            digest=hashes[name];p=local_path(ref(data/name));size=source.members[name].size
            require(re.fullmatch('[0-9a-f]{64}',digest) and digest==evidence['tdr_sha256'][name]==receipt['tdr_before_sha256'][name]==receipt['tdr_after_sha256'][name]
                    ==source.digest(name)==operation.digest(name)==sha(p),'Registered TDR bytes/hash differ: '+name)
            require(size==operation.members[name].size==p.stat().st_size and size>0,'TDR byte length differs')
            files.append({'name':name,'sha256':digest,'bytes':size})
    launch_refs=[]
    for e in gate['evidence']:
        if not e['path'].endswith('/execution.json'):continue
        launch=read(local_path(e['path']))
        if launch.get('run_id')==run.name:
            require(launch.get('role_id')==role_id and launch.get('campaign_sha256')==sha(CAMPAIGN),'Source launch role/campaign differs')
            require(launch.get('state')=='RUNNER_EXITED' and type(launch.get('runner_exit_code')) is int and launch['runner_exit_code']==0
                    and type(launch.get('ssh_exit_code')) is int and launch['ssh_exit_code']==0
                    and launch.get('runner_manifest_state')=='COLLECTED' and launch.get('manifest_input_matches_project') is True,'Source launcher outcome unknown/failed')
            launch_refs.append(e)
    require(len(launch_refs)==1,'Final role gate must bind one exact successful source launch')
    remote_root=read(ROOT/'local_runtime/connection.json')['remote_root'].rstrip('/')
    target,remote_source=remote_paths(remote_root,operation_label,run.name)
    require(op['remote_directory']==target and manifest['remote_directory']==remote_source,'Remote original/duplicate directory binding differs')
    plan={'schema':'dram-see-v4-remote-duplicate-tdr-cleanup-plan-r1','state':'PREPARED_NOT_EXECUTED','role_id':role_id,
          'operation_label':operation_label,'source_run_id':run.name,'remote_root':remote_root,'remote_target':target,'remote_source':remote_source,
          'files':sorted(files,key=lambda v:v['name']),'file_count':len(files),'registered_duplicate_bytes':sum(v['bytes'] for v in files),
          'evidence':[reference(p) for p in (CAMPAIGN,registry_path,gate_path,audit_path,field_path,field_path.parent/'frames.csv',receipt_path,op_path,operation_tar,run_manifest,source_tar)],
          'gate_evidence':gate['evidence'],'source_launch':launch_refs[0],'cleanup_code_sha256':sha(Path(__file__)),
          'created_utc':datetime.now(timezone.utc).isoformat(),'automatic_retry':False,'cleanup_executed':False,
          'retained':['all local evidence and archives','local collected TDR copies','entire original source run directory'],
          'process_check_scope':'All readable process cwd plus fail-closed unreadable live same-owner cwd; foreign-user inaccessible cwd cannot be inspected without elevated privileges.'}
    plan['plan_id']=hashlib.sha256(encoded(plan)).hexdigest()[:24]
    script=render_script(plan);plan['script_sha256']=hashlib.sha256(script).hexdigest()
    dest=Path(output).resolve();require(dest.is_relative_to(OUTPUT.resolve()) and dest!=OUTPUT.resolve() and not dest.exists(),'Use a new cleanup-dev child output')
    for p in (dest.parent,*dest.parent.parents):
        if p==ROOT.parent:break
        require(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()),'Linked output parent forbidden')
    dest.mkdir(parents=True,exist_ok=False)
    with (dest/'plan.json').open('xb') as f:f.write(encoded(plan))
    with (dest/'remote-cleanup.sh').open('xb') as f:f.write(script)
    return {**plan,'output':str(dest),'plan_file_sha256':sha(dest/'plan.json')}


def self_test(output):
    """Offline refusal and script-text tests only; no successful scientific fixture."""
    from unittest.mock import patch
    checks=[]
    def rejection(name,fn):
        try:fn()
        except (ValueError,FileNotFoundError,KeyError):checks.append(name);return
        raise AssertionError('Expected refusal: '+name)
    rejection('old_operation_label',lambda:prepare('r4-any','a4-b1-main',OUTPUT/'never-created'))
    rejection('unsafe_operation_label',lambda:prepare('r5-a/../x','a4-b1-main',OUTPUT/'never-created'))
    rejection('failed_operation',lambda:operation_success({'state':'FAILED_COLLECTED'},{}))
    rejection('unknown_operation_exit',lambda:operation_success({'state':'COLLECTED_PENDING_AUDIT','ssh_exit_code':None},{}))
    OUTPUT.mkdir(parents=True,exist_ok=True)
    absent=OUTPUT/'missing-final-gate-fixture-never-created'
    require(not absent.exists(),'Refusal-only fixture path unexpectedly exists')
    with patch.dict(globals(),STATE=absent):
        rejection('missing_final_role_gate',lambda:prepare('r5-test-only','a4-b1-main',absent/'must-not-exist'))
        require(not absent.exists(),'Refusal wrote a cleanup artifact')
    rejection('original_runs_not_a_target',lambda:remote_paths('/home/test/research','r5-valid','old-r4-run'))
    # Inert text-only fixture. It contains no passed scientific report and is never executed.
    template={'remote_root':'/home/test/research','operation_label':'r5-inert-script-test','source_run_id':'20261013T000000Z-v4-source-interface-r5-a4-b1-main-test',
              'plan_id':'0'*24,'files':[{'name':'gstep_0000_access_des.tdr','sha256':'0'*64,'bytes':1}]}
    template['remote_target'],template['remote_source']=remote_paths(template['remote_root'],template['operation_label'],template['source_run_id'])
    script=render_script(template).decode()
    require(script.count('    rm -- "$target/$name"')==1 and 'rm -r' not in script and 'rm -- "$source_dir' not in script,'Deletion scope regression')
    require(script.index('# Validate EVERY')<script.index('    rm --') and 'check_processes\nwhile' in script,'Prevalidation ordering regression')
    require('flock -n 9' in script and 'realpath -e' in script and 'source-after.tsv' in script and 'disk-before.txt' in script and 'disk-after.txt' in script,'Safety evidence missing')
    checks.append('inert_script_scope_and_evidence')
    bad={**template,'files':[{'name':'../runs/gstep_0_access_des.tdr','sha256':'0'*64,'bytes':1}]}
    rejection('tdr_path_traversal',lambda:render_script(bad))
    rejection('gfield_not_deletable',lambda:render_script({**template,'files':[{'name':'gfield_0_access_des.tdr','sha256':'0'*64,'bytes':1}]}))
    result={'status':'OFFLINE_REFUSAL_AND_TEXT_CHECKS_PASSED','checks':checks,'successful_scientific_prepare_tested':False,
            'shell_executed':False,'ssh_used':False,'files_deleted':False,'cleanup_code_sha256':sha(Path(__file__))}
    dest=Path(output).resolve();require(dest.is_relative_to(OUTPUT.resolve()) and dest!=OUTPUT.resolve() and not dest.exists(),'New cleanup-dev test log required')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('xb') as f:f.write(encoded(result))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('prepare');a.add_argument('operation_label');a.add_argument('role_id');a.add_argument('output',type=Path)
    t=s.add_parser('self-test');t.add_argument('output',type=Path)
    args=p.parse_args();result=prepare(args.operation_label,args.role_id,args.output) if args.command=='prepare' else self_test(args.output)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
