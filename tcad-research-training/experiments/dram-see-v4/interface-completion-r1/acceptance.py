"""Root-owned, read-only scientific acceptance and append-only evidence gates."""
import argparse
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import re

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATE = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1'
R5 = ROOT / 'local_runtime/dram-see-v4/source-interface-r5'
REGISTRY = STATE / 'evidence-registry.json'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def utc(): return datetime.now(timezone.utc).isoformat()
def rel(p): return Path(p).resolve().relative_to(ROOT).as_posix()
def module(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(Path(p).read_bytes(), str(p), 'exec'), obj.__dict__)
    return obj
def api(): return module(HERE.parent / 'source-interface-r5/audit_interface.py', '_completion_acceptance')
def save_new(p, data):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
def reference(p, passed=False):
    return dict(path=rel(p), sha256=sha(p), requires_pass=passed)
def update_registry(registry):
    if REGISTRY.exists():
        history = STATE / 'registry-history'
        history.mkdir(exist_ok=True)
        snapshot = history / (sha(REGISTRY) + '.json')
        if not snapshot.exists(): snapshot.write_bytes(REGISTRY.read_bytes())
    temporary = REGISTRY.with_suffix('.tmp')
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(REGISTRY)

def load_registered(a, registry, role):
    row = registry['runs'][role]
    a.require(sha(ROOT / row['audit']) == row['audit_sha256'], 'Registered audit changed')
    if row.get('field_audit'):
        a.require(sha(ROOT / row['field_audit']) == row['field_audit_sha256'], 'Registered field audit changed')
    value = a.load(ROOT / row['run'], ROOT / row['project'], ROOT / row['field_audit'] if row.get('field_audit') else None)
    a.accepted(value['summary'])
    a.require([value['parameters']['case_id'], value['parameters']['stored_bit'], a.canonical_matching(value)['variant']] == row['role'], 'Registry role differs')
    a.require(value['summary'] == read(ROOT / row['audit']), 'Registered audit no longer reproduces')
    return value

def registration(bundle, run, project, audit, field=None):
    a = api(); p = bundle['parameters']
    row = dict(run=rel(run), project=rel(project), audit=rel(audit), audit_sha256=sha(audit),
               role=[p['case_id'], p['stored_bit'], a.canonical_matching(bundle)['variant']])
    if field: row.update(field_audit=rel(field), field_audit_sha256=sha(field))
    return row

def gate(role, evidence, extra=None):
    record = dict(schema='dram-see-v4-completion-role-gate-r1', role_id=role, passed=True,
                  created_utc=utc(), campaign_sha256=sha(HERE / 'campaign.json'), evidence=evidence,
                  scientific_calibration_passed=False, three_dimensional_coupling_passed=False,
                  upset_labels_generated=False, acceptance_code_sha256=sha(Path(__file__)))
    if extra: record.update(extra)
    save_new(STATE / 'gates' / (role + '.json'), record)
    return record

def validate_invocation(execution, request, label):
    """Re-entry must retain the same physical inputs and still-valid dependency proof."""
    tool = module(HERE / 'control.py', '_acceptance_dependency_control')
    require = api().require
    require(execution['label'] == label and execution['role_id'] == request['role_id'], 'Invocation label/role differs')
    require(execution['identity'] == [request['case_id'], request['stored_bit'], request['variant']], 'Invocation identity differs')
    require(execution['campaign_sha256'] == sha(HERE / 'campaign.json'), 'Invocation campaign differs')
    project = (ROOT / execution['project']).resolve()
    require(project == (ROOT / request['project']).resolve(), 'Invocation project differs')
    proof = api().builder().check_project(project)
    require(proof == execution['offline_input_check'], 'Invocation frozen input proof differs')
    inputs = {p.relative_to(project).as_posix(): sha(p) for p in sorted(project.rglob('*')) if p.is_file()}
    require(inputs == execution['source_input_sha256'], 'Invocation source bytes differ')
    dependencies = [tool.check_gate(role) for role in request['requires']]
    require(dependencies == execution['dependency_gates'], 'Invocation dependency gate changed or differs')
    return dependencies

def reuse(label):
    a = api(); b = a.builder(); registry = {'schema': 'dram-see-v4-completion-evidence-registry-r1', 'runs': {}}
    a.require(re.fullmatch(r'[a-z0-9-]+', label), 'Unsafe reuse label')
    a.require(not REGISTRY.exists(), 'Reuse registry already exists; do not rerun or replace')
    bundles = {}; evidence = []
    for row in b.contract()['reuse_roles']:
        run = ROOT / 'local_runtime/runs' / row['run_id']
        project = ROOT / row['project_path']
        value = a.load(run, project)
        out = R5 / 'reuse' / label / row['case_id'].lower()
        a.write(out, value)
        a.accepted(value['summary'])
        role = row['case_id'].lower() + '-b1-main'
        registry['runs'][role] = registration(value, run, project, out / 'audit.json', ROOT / row['field_audit_path'] if row.get('field_audit_path') else None)
        bundles[role] = value; evidence.append(reference(out / 'audit.json', True))
    matching = a.matched_control(bundles['a1-b1-main'], bundles['a0-b1-main'])
    match_path = R5 / 'reuse' / label / 'matching.json'; save_new(match_path, matching)
    evidence.append(reference(match_path, True))
    for name in ('build_interface.py', 'source_contract.json', 'audit_interface.py', 'reuse_bridge.py'):
        evidence.append(reference(HERE.parent / 'source-interface-r5' / name))
    update_registry(registry)
    gate('reuse-main-b1', evidence, {'canonical_variant': 'main', 'original_variant': 'mesh', 'new_solver_calls': 0})
    return dict(passed=True, registered_roles=list(registry['runs']), new_solver_calls=0)

def accept(role, label, field=None):
    a = api(); c = read(HERE / 'campaign.json')
    a.require(re.fullmatch(r'r5-[a-z0-9-]+', label), 'Unsafe invocation label')
    request = next(r for r in c['roles'] if r['role_id'] == role)
    a.require(not (STATE / 'gates' / (role + '.json')).exists(), 'Role already accepted; duplicate acceptance refused')
    launch = R5 / 'launches' / label / 'execution.json'; execution = read(launch)
    validate_invocation(execution, request, label)
    a.require(execution['role_id'] == role and execution['campaign_sha256'] == sha(HERE / 'campaign.json'), 'Invocation role/campaign differs')
    a.require(execution['state'] == 'RUNNER_EXITED' and execution['runner_exit_code'] == execution['ssh_exit_code'] == 0
              and execution['runner_manifest_state'] == 'COLLECTED' and execution['manifest_input_matches_project'] is True, 'Solver outcome unknown/failed')
    run = ROOT / 'local_runtime/runs' / execution['run_id']; project = ROOT / execution['project']
    a.require(project.resolve() == (ROOT / request['project']).resolve(), 'Actual project differs from campaign role')
    value = a.load(run, project, field); out = R5 / 'audits' / label; a.write(out, value)
    outcome = dict(schema='dram-see-v4-completion-outcome-r1', label=label, role_id=role, passed=False,
                   created_utc=utc(), campaign_sha256=sha(HERE / 'campaign.json'), evidence=[reference(out / 'audit.json')], errors=[])
    try:
        a.accepted(value['summary'])
        registry = read(REGISTRY); p = value['parameters']; cache = {role: value}
        a.require([p['case_id'], p['stored_bit'], p['variant']] == [request['case_id'], request['stored_bit'], request['variant']],
                  'Actual archived identity differs from campaign role')
        if p['case_id'] == 'A0':
            a.require(value['summary']['radiation'].get('generated_fC') == 0
                      and value['summary']['radiation'].get('source_free') is True,
                      'New A0 needs structural zero and an observed native zero curve')
        def get(key):
            if key not in cache: cache[key] = load_registered(a, registry, key)
            return cache[key]
        if p['case_id'] != 'A0':
            control_id = f'a0-b{p["stored_bit"]}-{p["variant"]}'
            control = get(control_id)
            matching = a.matched_control(value, control)
            outcome['evidence'].append(reference(ROOT / registry['runs'][control_id]['audit'], True))
            match_path = out / 'matching-control.json'; save_new(match_path, matching)
            outcome['evidence'].append(reference(match_path, True))
            # Preserve matched-control response curves also for roles without a pair test.
            rows = a.comparison_curves(value, value, control, control)
            a.write(R5 / 'responses' / label, {'summary': dict(schema='dram-see-v4-r5-control-relative-comparison', passed=True,
                    role_id=role, matching=matching, response_only=True, comparison_performed=False), 'curves': rows})
            if request['comparison_mode']:
                mode = request['comparison_mode']
                reference_role = ('a5' if p['case_id'] == 'A7' else 'a1') + f'-b{p["stored_bit"]}-main'
                if mode == 'refinement': reference_role = p['case_id'].lower() + f'-b{p["stored_bit"]}-main'
                baseline = get(reference_role)
                baseline_control = get(f'a0-b{p["stored_bit"]}-main')
                comparison_out = R5 / 'comparisons' / label
                result = a.compare(baseline, value, baseline_control, control, mode, comparison_out)
                outcome['evidence'].append(reference(comparison_out / 'comparison.json', True))
                a.accepted(result)
        registry['runs'][role] = registration(value, run, project, out / 'audit.json', field)
        update_registry(registry)
        gate(role, outcome['evidence'] + [reference(launch)], {'run_id': run.name, 'comparison_mode': request['comparison_mode']})
        outcome['passed'] = True
    except (ValueError, KeyError, TypeError, OSError) as exc:
        outcome['passed'] = False
        outcome['errors'].append(str(exc))
    save_new(STATE / 'outcomes' / (label + '.json'), outcome)
    return {k: outcome[k] for k in ('passed', 'role_id', 'errors')}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('reuse'); r.add_argument('label')
    p = sub.add_parser('accept'); p.add_argument('role'); p.add_argument('label'); p.add_argument('--field', type=Path)
    args = parser.parse_args()
    result = reuse(args.label) if args.command == 'reuse' else accept(args.role, args.label, args.field)
    print(json.dumps(result, ensure_ascii=False)); return 0 if result['passed'] else 1

if __name__ == '__main__': raise SystemExit(main())
