"""Pure text composition on the reviewed capture/r3 original-runner candidate."""
import ast
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Frozen runner anchor missing or ambiguous: ' + old[:100])
    return text.replace(old, new, 1)


def compose(root, capture):
    root, capture = Path(root), Path(capture)
    record = json.loads((capture / 'capture-patch-report.json').read_text(encoding='utf-8'))
    entry = next(x for x in record['entries'] if x['source_path'] == 'scripts/tcad.py')
    original = (root / entry['source_path']).read_bytes()
    if hashlib.sha256(original).hexdigest() != entry['source_sha256']:
        raise ValueError('Original runner changed since capture/r3')
    module_path = HERE.parent / 'capture_patch.py'
    if hashlib.sha256(module_path.read_bytes()).hexdigest() != record['generator_sha256']:
        raise ValueError('Frozen capture generator changed')
    module_spec = importlib.util.spec_from_file_location('capture_review_composition', module_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    base = module._tcad_candidate(original.decode('utf-8').replace('\r\n', '\n'))
    if hashlib.sha256(base.encode()).hexdigest() != entry['candidate_sha256']:
        raise ValueError('Composed capture candidate differs from r3')
    bridge = (HERE / 'geometry_bridge.py').read_text(encoding='utf-8')
    embedded = bridge.split("if __name__ == '__main__':", 1)[0]
    if embedded == bridge:
        raise ValueError('Bridge main guard is missing')
    candidate = replace_once(base, 'def run_project(cfg, ssh, project):\n',
        embedded + '\n\ndef run_project(cfg, ssh, project):\n')
    anchor = "    spec = json.loads((project / 'project.json').read_text(encoding='utf-8'))\n"
    candidate = replace_once(candidate, anchor, anchor +
        "    geometry_cfg = geometry_admit(project, spec, file_hash(Path(__file__))) if 's2_geometry' in spec else None\n"
        "    if geometry_cfg and geometry_cfg['mode'] == 'reuse':\n"
        "        geometry_stage_reuse(project, geometry_cfg)\n")
    candidate = replace_once(candidate, "    allowed = {'sde', 'snmesh', 'sdevice'}\n",
        "    allowed = {'sde', 'snmesh', 'sdevice'} | ({'svisual'} if geometry_cfg else set())\n")
    anchor = "    run_id = stamp + '-' + spec['name'] + '-' + uuid.uuid4().hex[:8]\n"
    candidate = replace_once(candidate, anchor, anchor +
        "    if geometry_cfg:\n        run_id = geometry_cfg['run_id']\n")
    anchor = "    for index, step in enumerate(steps, 1):\n"
    candidate = replace_once(candidate, anchor,
        "    if geometry_cfg and geometry_cfg['mode'] == 'reuse':\n"
        "        runner += ['taskset -c \"$cpu\" /usr/bin/python3 mesh_resource_guard.py']\n" + anchor)
    old = ("        runner += ['echo ' + shlex.quote('STEP ' + str(index) + ': ' + shlex.join(args)),\n"
           "                   'capture_native_step ' + shlex.join([capture_key, step['tool'], capture_installation])\n"
           "                   + ' ' + shlex.join(args)]\n")
    new = ("        capture_command = 'capture_native_step ' + shlex.join([capture_key, step['tool'], capture_installation]) + ' ' + shlex.join(args)\n"
           "        runner += ['echo ' + shlex.quote('STEP ' + str(index) + ': ' + shlex.join(args))]\n"
           "        if geometry_cfg and geometry_cfg['mode'] == 'produce' and step['tool'] in ('sde', 'snmesh', 'svisual'):\n"
           "            canonical = {'sde': 'sde-exit-code.txt', 'snmesh': 'mesh-exit-code.txt', 'svisual': 'svisual-exit-code.txt'}[step['tool']]\n"
           "            runner += ['if ' + capture_command + '; then geometry_step_rc=0; else geometry_step_rc=$?; fi',\n"
           "                       'if taskset -c \"$cpu\" /usr/bin/python3 geometry_bridge.py record-exit ' + shlex.join(['--folder', '.', '--source', capture_key + '-exit-code.txt', '--canonical', canonical]) + '; then geometry_alias_rc=0; else geometry_alias_rc=$?; fi',\n"
           "                       'if [ \"$geometry_step_rc\" -ne 0 ]; then exit \"$geometry_step_rc\"; fi',\n"
           "                       'if [ \"$geometry_alias_rc\" -ne 0 ]; then exit \"$geometry_alias_rc\"; fi']\n"
           "        else:\n            runner += [capture_command]\n")
    candidate = replace_once(candidate, old, new)
    anchor = "        runner += ['test -s ' + shlex.quote(out) for out in step['outputs']]\n"
    candidate = replace_once(candidate, anchor, anchor +
        "        if geometry_cfg and geometry_cfg['mode'] == 'produce':\n"
        "            if step['tool'] == 'snmesh':\n"
        "                runner += ['taskset -c \"$cpu\" /usr/bin/python3 mesh_resource_guard.py',\n"
        "                           'taskset -c \"$cpu\" /usr/bin/python3 geometry_bridge.py prepare --folder . --run-id ' + shlex.quote(run_id)]\n"
        "            elif step['tool'] == 'svisual':\n"
        "                runner += ['taskset -c \"$cpu\" /usr/bin/python3 geometry_bridge.py finalize --folder . --run-id ' + shlex.quote(run_id)]\n")
    anchor = "    cfg, ssh, ip = connection()\n"
    candidate = replace_once(candidate, anchor,
        "    if args.command == 'run':\n"
        "        geometry_project = args.project.resolve()\n"
        "        geometry_spec = json.loads((geometry_project / 'project.json').read_text(encoding='utf-8'))\n"
        "        if 's2_geometry' in geometry_spec:\n"
        "            geometry_admit(geometry_project, geometry_spec, file_hash(Path(__file__)))\n" + anchor)
    ast.parse(candidate)
    base_tree, final_tree = ast.parse(base), ast.parse(candidate)
    preserved = {}
    for name in ('execute', 'connection', 'remote', 'doctor', 'native_capture_shell_lines', 'capture_archive_exit_codes'):
        def body(tree):
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), include_attributes=False)
        preserved[name] = body(base_tree) == body(final_tree)
    if not all(preserved.values()):
        raise ValueError('Existing SSH/capture helpers changed')
    return original.decode('utf-8').replace('\r\n', '\n'), base, candidate, preserved


def patch(before, after, before_name, after_name):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                     fromfile=before_name, tofile=after_name))
