"""One serial, fail-closed continuation of the frozen v3 stages; no solver implementation.

This controller can wait for an explicitly identified existing reference controller
to exit. It never attaches to, kills, or retries a solver. Stage commands retain
the existing run.py locks, preflight, evidence audits and cumulative budget.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, LOCAL, now, sha, write_json, preflight, check_preservation


def ledger():
    return json.loads((LOCAL / 'ledger.json').read_text(encoding='utf8'))


def processes():
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' } | Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    return [rows] if isinstance(rows, dict) else rows


def identity(row):
    return {'pid': row['ProcessId'], 'created': row['CreationDate'],
            'command_sha256': hashlib.sha256((row.get('CommandLine') or '').encode()).hexdigest()}


@contextmanager
def continuation_lock():
    import msvcrt
    with (LOCAL / 'continuation.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0'); stream.flush()
        stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def commands():
    """Fixed order; child programs implement all scientific gates and input freezes."""
    py = sys.executable
    design=json.loads((HERE/'stats-design.json').read_text(encoding='utf8'))
    fixed=design['numerical']['preregistered']
    event=next(e for e in design['events'] if (e['gate_length_um'],e['particle'],e['angle_deg'],e['replicate']) ==
               (fixed['length_um'],fixed['particle'],fixed['angle_deg'],fixed['replicate']))
    field_tag='v3-'+event['label']+'-b'+str(fixed['stored_bit'])
    def command(script, *args):
        return [py, '-B', str(HERE / script), *args]
    return [
        ('reference-report', command('report.py', '--publish')),
        ('pilot', command('run.py', 'pilot', '--label', 'pilot-r1')),
        ('preregistered-numerics', command('numerical.py', 'preregistered', '--label', 'r1')),
        ('pilot-report', command('report.py', '--publish')),
        ('training', command('run.py', 'train', '--label', 'train-r1')),
        ('test-transport-only', command('run.py', 'transport-test')),
        ('model-and-prediction-freeze', command('prediction.py', 'freeze')),
        ('training-report', command('report.py', '--publish')),
        ('holdout-and-extrapolation', command('run.py', 'test', '--label', 'test-r1')),
        ('oxide', command('oxide.py', '--label', 'r1')),
        ('boundary-numerics', command('numerical.py', 'boundary', '--label', 'r1')),
        ('native-physical-reference', command('gui_evidence.py', '@run:v3-physical-l018-b1')),
        ('native-preregistered-event', command('gui_evidence.py', '@run:'+field_tag)),
        ('final-report', command('report.py', '--publish')),
    ]


def freeze(path, predecessor_pids):
    if path.exists():
        raise ValueError('Continuation evidence exists; inspect before any further dispatch')
    if len(set(predecessor_pids)) != len(predecessor_pids):
        raise ValueError('Duplicate predecessor PID')
    live = {p['ProcessId']: p for p in processes()}
    previous = []
    for pid in predecessor_pids:
        row = live.get(pid)
        if not row or not re.search(r'dram-see-v3[\\/]run\.py references --label reference-r3', row.get('CommandLine') or ''):
            raise ValueError('Predecessor is not the explicitly expected current reference controller')
        previous.append(identity(row))
    paths = set(HERE.glob('*.py'))
    paths.update([HERE / 'stats-design.json', ROOT / 'scripts/tcad.py'])
    sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}
    path.mkdir(parents=True)
    for name, digest in sources.items():
        target = path / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write((ROOT / name).read_bytes())
        if sha(target) != digest:
            raise ValueError('Source changed during continuation freeze')
    manifest = {'schema': 'dram-see-v3-serial-continuation', 'created_utc': now(),
                'source_sha256': sources, 'predecessors': previous, 'commands': commands(),
                'policy': 'Await exact predecessor exit and verified references; stop at first failed stage; no solver retry or termination',
                'scope': 'Existing v3 stage controllers and 86400 second cumulative budget; human course review remains pending'}
    write_json(path / 'plan.json', manifest, exclusive=True)
    (path / 'plan.sha256').write_text(sha(path / 'plan.json') + '\n', encoding='ascii')
    return manifest


def check_frozen(path, plan):
    if (path / 'plan.sha256').read_text().strip() != sha(path / 'plan.json'):
        raise ValueError('Continuation plan changed')
    for name, digest in plan['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('Continuation source changed: ' + name)


def status(path, state, **extra):
    data = {'utc': now(), 'state': state, 'controller_pid': os.getpid(),
            'plan': (path / 'plan.json').relative_to(ROOT).as_posix(), **extra}
    write_json(path / 'status.json', data)
    write_json(LOCAL / 'continuation-state.json', data)
    progress_document(data)
    print(json.dumps(data, ensure_ascii=False), flush=True)
    return data


def progress_document(controller):
    """Publish actual ledger counts; raw audit completion never implies all gates passed."""
    data=ledger()
    design=json.loads((HERE/'stats-design.json').read_text(encoding='utf8'))
    wanted=['v3-'+e['label']+'-b'+str(b) for e in design['events'] for b in (0,1)]
    states=[data['runs'].get(tag,{}).get('state','UNSUBMITTED') for tag in wanted]
    charged=sum(r.get('charged_solver_s',r.get('elapsed_s',0)) for r in data['runs'].values()
                if not r.get('inherited') and r.get('state')!='RUNNING')
    lines=['# v3 实际运行状态',
           'UTC：`'+controller['utc']+'`。本页由串行控制器从实际ledger生成；不是计划完成声明。',
           '- 控制器状态：`'+controller['state']+'`；阶段：`'+controller.get('stage','waiting for reference controller')+'`。',
           '- 主矩阵固定64事件、128响应；原档审计VERIFIED：'+str(states.count('VERIFIED'))+'；RUNNING：'+str(states.count('RUNNING'))+'；FAILED：'+str(states.count('FAILED'))+'；未提交：'+str(states.count('UNSUBMITTED'))+'；其他待核状态：'+str(sum(s not in ('VERIFIED','RUNNING','FAILED','UNSUBMITTED') for s in states))+'。',
           '- 累计已结算新求解：'+format(charged,'.2f')+' / 86400 s。运行中耗时尚未结算；失败与验证耗时计入预算。',
           '- 原始审计VERIFIED与阶段科学门槛分别登记；临界和数值不确定见逐响应报告。']
    table=['| 阶段 | 实际登记状态 | 连续数值检查 |', '| --- | --- | --- |']
    for name,row in data.get('stages',{}).items():
        table.append('| '+name+' | '+row.get('state','UNKNOWN')+' | '+str(row.get('continuous_passed','—'))+' |')
    lines.append('\n'.join(table))
    if controller.get('reason'):
        lines.append('停止原因：`'+controller['reason']+'`。原运行保留，后续提交停止，未自动重试或终止求解。')
    lines+=['[冻结方案](plan.md) · [实际日志](journal.md) · [操作与恢复](workflow.md) · [阶段报告](report.md)',
            '机器状态：`local_runtime/dram-see-v3/continuation-state.json`、`ledger.json`；原始证据：`local_runtime/runs/<run-id>/`。',
            '实际学生分工、教师审核、实验室交接、答辩与最终考核仍须真实记录。']
    target=HERE/'status.md';temporary=target.with_suffix('.md.tmp')
    temporary.write_text('\n\n'.join(lines)+'\n',encoding='utf8');temporary.replace(target)


def wait_predecessors(path, plan):
    waiting=status(path, 'WAITING_FOR_REFERENCE_CONTROLLER', predecessors=plan['predecessors'])
    while plan['predecessors']:
        live = {p['ProcessId']: p for p in processes()}
        remaining = []
        for old in plan['predecessors']:
            current = live.get(old['pid'])
            if current:
                if identity(current) != old:
                    raise ValueError('Predecessor PID identity changed; read-only reconciliation required')
                remaining.append(old)
        if not remaining:
            break
        progress_document({**waiting,'utc':now()})
        time.sleep(20)
    data = ledger()
    if data['stages'].get('references', {}).get('state') != 'VERIFIED':
        raise ValueError('Original reference controller ended without passing reference gate')
    if any(r.get('state') == 'RUNNING' for r in data['runs'].values()):
        raise ValueError('Unsettled original run; never infer solver termination from local process exit')
    preflight('continuation-handoff')


def invoke(path, label, command):
    command=list(command)
    for index,value in enumerate(command):
        if value.startswith('@run:'):
            item=ledger()['runs'].get(value[5:],{})
            if item.get('state')!='VERIFIED' or not item.get('run_id'):
                raise ValueError('Predeclared native evidence run is not verified')
            command[index]=item['run_id']
    log = path / label
    log.mkdir()
    env = os.environ.copy()
    env['PYTHONPYCACHEPREFIX'] = str(path / 'unused-bytecode-cache')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    with (log / 'stdout.log').open('xb') as out, (log / 'stderr.log').open('xb') as err:
        child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, env=env)
        running=status(path, 'RUNNING_STAGE', stage=label, child_pid=child.pid, command=command)
        while True:
            try:
                code = child.wait(timeout=20)
                break
            except subprocess.TimeoutExpired:
                progress_document({**running,'utc':now()})
    write_json(log / 'exit.json', {'finished_utc': now(), 'exit_code': code, 'command': command}, exclusive=True)
    return code


def main(label, predecessor_pids):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', label):
        raise ValueError('Unsafe continuation label')
    LOCAL.mkdir(parents=True, exist_ok=True)
    path = LOCAL / 'continuations' / label
    with continuation_lock():
        plan = freeze(path, predecessor_pids)
        current_stage = 'reference-handoff'
        try:
            wait_predecessors(path, plan)
            check_preservation()
            for current_stage, command in plan['commands']:
                check_frozen(path, plan)
                code = invoke(path, current_stage, command)
                if code:
                    raise RuntimeError('Stage failed with exit ' + str(code) + ': ' + current_stage)
                with (HERE / 'journal.md').open('a', encoding='utf8') as stream:
                    stream.write('\n## ' + now() + ' — 串行阶段命令完成\n\n`' + current_stage + '` 退出0；阶段输出及日志：`' + (path / current_stage).relative_to(ROOT).as_posix() + '`。科学完成范围以该阶段ledger与原始审计为准。\n')
            check_preservation()
            status(path, 'SIMULATION_STAGES_FINISHED', stage=current_stage,
                   remaining=['review final numerical and prediction evidence and native images', 'final course delivery integration; human items remain pending'])
        except Exception as exc:
            (path / 'failure.txt').write_text(traceback.format_exc(), encoding='utf8')
            status(path, 'STOPPED_REQUIRES_RECONCILIATION', stage=current_stage, reason=repr(exc),
                   policy='No retries, no termination; preserve completed/failed/missing slots')
            with (HERE / 'journal.md').open('a', encoding='utf8') as stream:
                stream.write('\n## ' + now() + ' — 串行阶段停止\n\n阶段 `' + current_stage + '` 未通过：`' + repr(exc) + '`。保留原运行，未自动重试或终止远端；依据continuation-state、原manifest和远端状态恢复。\n')
            return 1
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--predecessor', type=int, action='append', default=[])
    args = parser.parse_args()
    raise SystemExit(main(args.label, args.predecessor))
