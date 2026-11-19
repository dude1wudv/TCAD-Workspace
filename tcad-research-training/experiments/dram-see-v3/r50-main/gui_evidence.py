"""Explicit R50-main native 4 ns field export and real owned SVisual window capture.

No solver dispatch, automatic sample selection, resume, or window closing.
Existing/partial evidence directories always require read-only reconciliation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import time
import zlib

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
CAPTURE = BASE.parent / 'dram-see-v2/capture_guest_window.py'
CAPTURE_SHA = '4fbdf4bd625bb3a9faf1ed0c73cf7b9cf9fbfb213d1f4814529ea8ac8ae7d280'
MEMBER = 'final_access_des.tdr'
VISUAL = '/usr/synopsys/sentaurus/W-2024.09/bin/svisual'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), result.__dict__)
    return result


common = _module('_r50_gui_common', BASE / 'common.py')
audit = _module('_r50_gui_audit', HERE / 'audit.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def dependencies():
    manifest = HERE / 'gui-source-manifest.json'
    frozen = json.loads(manifest.read_text(encoding='utf8'))
    if frozen.get('schema') != 'dram-see-v3-r50-main-gui-sources':
        raise ValueError('Wrong GUI source manifest')
    current = {name: sha(ROOT / name) for name in frozen['files_sha256']}
    if current != frozen['files_sha256']:
        raise ValueError('GUI source bytes changed; review a new version before capture')
    return {**current, manifest.relative_to(ROOT).as_posix(): sha(manifest)}


def check_selected_case(tag, row):
    """Bind the two preregistered objects to their accepted first-segment inputs."""
    if tag not in ('v3-r50-main-physical-l018-b1', 'v3-r50-main-l018-alpha-a30-s202610311-b1'):
        raise ValueError('Native evidence is restricted to the two fixed R50-main targets')
    if (row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0
            or row.get('physical_revision') != 'r50-main-r1' or row.get('physical_revision_probe_only') is not False):
        raise ValueError('Need verified original R50-main role and zero runner exit')
    plan_path = LOCAL / 'physical-revisions/r50-main-r1/plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf8'))
    marker = json.loads(plan_path.with_name('plan-sha256.json').read_text(encoding='utf8'))
    if (marker.get('sha256') != sha(plan_path) or plan.get('schema') != 'dram-see-v3-r50-main-execution-plan'
            or plan.get('design_sha256') != sha(HERE / 'design.json')):
        raise ValueError('R50-main execution/design evidence differs')
    for name, digest in plan['source_sha256'].items():
        if sha(ROOT / name) != digest or sha(plan_path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('R50-main frozen source differs')
    cases = [case for case in plan['planned_cases'] if case['tag'] == tag]
    frozen = plan_path.parent / 'case-freezes' / (tag + '.json')
    execution = json.loads(frozen.read_text(encoding='utf8'))
    if (len(cases) != 1 or execution.get('case') != cases[0]
            or execution.get('main_plan_sha256') != sha(plan_path)
            or execution.get('main_plan') != plan_path.relative_to(ROOT).as_posix()
            or execution.get('source_sha256') != plan['source_sha256']
            or execution.get('inputs') != {tag: row.get('input_sha256')}
            or row.get('execution_freeze') != frozen.relative_to(ROOT).as_posix()
            or row.get('execution_freeze_sha256') != sha(frozen)):
        raise ValueError('Native target case is not bound to the frozen main execution')
    return {'plan_sha256': sha(plan_path), 'case_freeze_sha256': sha(frozen), 'design_sha256': sha(HERE / 'design.json')}


def remote(ssh, operation_root, label, script, payload=None, timeout=30):
    folder = operation_root / label
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'command.sh').write_text(script, encoding='utf8', newline='\n')
    record = {'label': label, 'started_utc': now(), 'timeout_s': timeout,
              'script_sha256': hashlib.sha256(script.encode()).hexdigest(),
              'stdin_sha256': hashlib.sha256(payload).hexdigest() if payload is not None else None}
    try:
        result = subprocess.run(ssh + ['bash -lc ' + shlex.quote(script)], input=payload,
                                capture_output=True, timeout=timeout)
        (folder / 'stdout.bin').write_bytes(result.stdout)
        (folder / 'stderr.txt').write_bytes(result.stderr)
        record['exit_code'] = result.returncode
        return result, record
    except subprocess.TimeoutExpired as exc:
        (folder / 'stdout.bin').write_bytes(exc.stdout or b'')
        (folder / 'stderr.txt').write_bytes(exc.stderr or b'')
        record['error'] = 'TimeoutExpired; inspect actual remote state, do not relaunch automatically'
        raise
    except Exception as exc:
        record['error'] = repr(exc)
        raise
    finally:
        record['finished_utc'] = now()
        common.write_json(folder / 'operation.json', record, exclusive=True)


def render_tcl(source, target, rid, tdr_hash):
    if any(character in source + target for character in '{}\r\n'):
        raise ValueError('Remote paths are unsafe in a literal Tcl path')
    marker = 'V3_R50_MAIN_NATIVE_FIELD_EXPORT_COMPLETED ' + rid + ' ' + tdr_hash
    script = '''set data [load_file {SOURCE/final_access_des.tdr}]
set plot [create_plot -dataset $data]
set_plot_prop -plot $plot -title {v3 R50-main actual 4 ns signal E-field (not a readout curve) | RID | V/cm, coordinates um}
foreach f [list_fields -plot $plot -show] {set_field_prop -plot $plot -geom $data $f -hide -hide_bands}
set_field_prop -plot $plot -geom $data Abs(ElectricField-V) -show -show_bands -scale log -levels 41
zoom_plot -plot $plot -reset
export_view {TARGET/final-field-native.png} -plots $plot -resolution 1400x1000 -format PNG -overwrite
set proof [open {TARGET/native-proof.txt} w]
puts $proof [list_fields -dataset $data]
puts $proof {MARKER}
close $proof
'''.replace('SOURCE', source).replace('TARGET', target).replace('RID', rid).replace('MARKER', marker)
    return script, marker


def parse_process(content, expected_pid, target):
    lines = content.decode('utf8').splitlines()
    if len(lines) != 3 or lines[0] != target:
        raise ValueError('Owned Visual cwd or process evidence differs')
    stat, command = lines[1:]
    if not stat.startswith(str(expected_pid) + ' (') or ') ' not in stat:
        raise ValueError('Owned process ID differs')
    values = stat.rsplit(') ', 1)[1].split()
    if len(values) < 20 or not values[19].isdigit() or 'svisual' not in command or 'view.tcl' not in command:
        raise ValueError('Missing Visual startup identity')
    return {'pid': expected_pid, 'cwd': lines[0], 'start_ticks': int(values[19]), 'command_line': command}


def process_script(pid, target):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Unsafe process ID')
    proc = '/proc/' + str(pid)
    return ('set -eu\ncwd=$(readlink ' + shlex.quote(proc + '/cwd') + ')\n'
            'test "$cwd" = ' + shlex.quote(target) + '\nprintf "%s\\n" "$cwd"\n'
            'cat ' + shlex.quote(proc + '/stat') + '\ntr "\\000" " " < ' + shlex.quote(proc + '/cmdline') + '\nprintf "\\n"\n')


def _png(data, name):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Invalid PNG output: ' + name)
    width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if width <= 0 or height <= 0:
        raise ValueError('Invalid PNG dimensions: ' + name)
    offset, kinds = 8, []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('Truncated PNG chunk: ' + name)
        size = int.from_bytes(data[offset:offset + 4], 'big')
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('Truncated PNG chunk content: ' + name)
        kind = data[offset + 4:offset + 8]
        crc = int.from_bytes(data[end - 4:end], 'big')
        if zlib.crc32(data[offset + 4:end - 4]) & 0xffffffff != crc:
            raise ValueError('PNG CRC mismatch: ' + name)
        kinds.append(kind)
        if kind == b'IEND' and (size != 0 or end != len(data)):
            raise ValueError('PNG end marker differs: ' + name)
        offset = end
    if kinds[0] != b'IHDR' or kinds[-1] != b'IEND' or b'IDAT' not in kinds:
        raise ValueError('Incomplete PNG image: ' + name)
    return {'width': width, 'height': height}


def main(rid):
    if not isinstance(rid, str) or not re.fullmatch(r'\d{8}T\d{6}Z-v3-[a-z0-9_-]+-[0-9a-f]{8}', rid):
        raise ValueError('Explicit real v3 run ID required')
    with common.controller_lock():
        return _owned_session(rid)


def _owned_session(rid):
    local = HERE / 'figures/native' / rid
    operation_root = LOCAL / 'r50-gui-operations' / rid
    if local.exists() or operation_root.exists():
        raise ValueError('Native evidence or partial operation already exists; inspect, never relaunch automatically')
    ledger = json.loads((LOCAL / 'ledger.json').read_text(encoding='utf8'))
    if any(row.get('state') == 'RUNNING' for row in ledger.get('runs', {}).values()):
        raise ValueError('A v3 run remains active/unsettled; wait before Visual capture')
    rows = [(tag, row) for tag, row in ledger['runs'].items() if row.get('run_id') == rid]
    if len(rows) != 1 or rows[0][1].get('state') != 'VERIFIED' or rows[0][1].get('inherited'):
        raise ValueError('Need one explicitly selected VERIFIED v3 ledger run')
    tag = rows[0][0]
    accepted_source = check_selected_case(tag, rows[0][1])
    summary = audit.audit(rid, export=False)
    if (summary.get('input_sha256') != rows[0][1].get('input_sha256')
            or summary.get('archive_sha256') != rows[0][1].get('audit_archive_sha256')
            or summary.get('parameters') != rows[0][1].get('parameters')):
        raise ValueError('Audited native source differs from the original verified ledger inputs/archive')
    if (summary.get('parameters', {}).get('schema') != 'dram-see-v3-r50-main'
            or summary['parameters'].get('physical_revision') != 'r50-main-r1'
            or summary['parameters'].get('physical_revision_probe_only') is not False
            or abs(summary.get('final_time_s', 0) - 4e-9) > 1e-18):
        raise ValueError('Need audited v3 result through 4 ns')
    with tarfile.open(ROOT / 'local_runtime/runs' / rid / 'results.tar') as archive:
        tdr_hash = hashlib.sha256(audit.read(archive, MEMBER)).hexdigest()
    if summary.get('tdr_sha256', {}).get(MEMBER) != tdr_hash:
        raise ValueError('Audit/archive final TDR hash differs')
    dependency_hashes = dependencies()
    helper = CAPTURE.read_bytes()
    if hashlib.sha256(helper).hexdigest() != CAPTURE_SHA:
        raise ValueError('Verified capture helper changed; do not use a different implementation silently')
    # The mandatory existing preflight records its own v3/preflight evidence.
    common.preflight('gui-' + rid)
    local.mkdir(parents=True, exist_ok=False)
    operation_root.mkdir(parents=True, exist_ok=False)
    request = {'schema': 'dram-see-v3-r50-main-gui-request', 'run_id': rid, 'ledger_tag': tag,
               'archive_sha256': summary['archive_sha256'], 'tdr_sha256': tdr_hash,
               'depended_source_files_sha256': dependency_hashes,
               'state': 'RESERVED_NOT_YET_LAUNCHED', 'utc': now()}
    common.write_json(operation_root / 'request.json', request, exclusive=True)
    try:
        cfg, ssh, _ = common.tcad.connection()
        source = cfg['remote_root'].rstrip('/') + '/runs/' + rid
        target_parent = cfg['remote_root'].rstrip('/') + '/dram-see-v3/r50-main-gui'
        target = target_parent + '/' + rid
        tcl, marker = render_tcl(source, target, rid, tdr_hash)

        def checked(label, script, payload=None, timeout=30):
            result, record = remote(ssh, operation_root, label, script, payload, timeout)
            if result.returncode:
                raise RuntimeError(label + ' failed; preserve v3 logs and inspect, no automatic relaunch')
            return result, record

        def source_check(label):
            result, _ = checked(label, 'sha256sum ' + shlex.quote(source + '/' + MEMBER))
            if result.stdout.decode().split()[0] != tdr_hash:
                raise ValueError('Remote loaded TDR differs from the audited archive')

        source_check('source-hash-before')
        checked('existing-visual-inventory', "ps -eo pid,ppid,stat,etime,comm,args | awk '$5 ~ /^(svisual|svisual_exec|Xorg|Xvnc)$/ {print}'")
        (local / 'view.tcl').write_text(tcl, encoding='utf8', newline='\n')
        checked('upload-view', 'set -eu\numask 077\nmkdir -p ' + shlex.quote(target_parent) + '\nmkdir ' + shlex.quote(target)
                + '\ncat > ' + shlex.quote(target + '/view.tcl') + '\n', tcl.encode())
        checked('upload-capture-helper', 'cat > ' + shlex.quote(target + '/capture.py'), helper)
        launch = ('set -eu\nexport DISPLAY=:0\nexport XAUTHORITY="$HOME/.Xauthority"\ncd ' + shlex.quote(target)
                  + '\nnohup ' + shlex.quote(VISUAL) + ' -tcl -script view.tcl > visual.log 2>&1 < /dev/null &\n'
                  'echo $! > own-pid.txt\n')
        _, launch_record = checked('launch', launch)
        result, _ = checked('owned-pid', 'cat ' + shlex.quote(target + '/own-pid.txt'))
        if not result.stdout.strip().isdigit():
            raise ValueError('No numeric owned launch PID; do not relaunch')
        pid = int(result.stdout.strip())
        (local / 'own-pid.txt').write_bytes(result.stdout)
        result, _ = checked('owned-process-before', process_script(pid, target))
        before = parse_process(result.stdout, pid, target)
        for index in range(12):
            result, _ = remote(ssh, operation_root, f'ready-{index:02d}', 'test -f ' + shlex.quote(target + '/native-proof.txt'), timeout=20)
            if result.returncode == 0:
                break
            if result.returncode != 1:
                raise RuntimeError('GUI readiness connection failed; do not relaunch')
            time.sleep(2)
        else:
            raise RuntimeError('Native export not yet complete; inspect existing owned GUI without relaunch')
        result, _ = checked('owned-process-pre-capture', process_script(pid, target))
        current = parse_process(result.stdout, pid, target)
        if current['start_ticks'] != before['start_ticks']:
            raise ValueError('Owned launch PID was reused')
        capture = ('set -eu\nexport DISPLAY=:0\nexport XAUTHORITY="$HOME/.Xauthority"\ncd ' + shlex.quote(target)
                   + '\n/usr/bin/python capture.py ' + str(pid) + ' own-window.png\n')
        result, capture_record = checked('capture', capture)
        capture_stdout = result.stdout.decode(errors='strict')
        matches = re.findall(r'OWNED_WINDOW_CAPTURE pid=(\d+) window=(0x[0-9a-fA-F]+)L? width=(\d+) height=(\d+)', capture_stdout)
        if len(matches) != 1:
            raise ValueError('Missing unique owned-window capture confirmation')
        actual_pid, window_id, width, height = matches[0]
        result, _ = checked('captured-process-after', process_script(int(actual_pid), target))
        captured = parse_process(result.stdout, int(actual_pid), target)
        result, _ = checked('owned-process-after', process_script(pid, target))
        after = parse_process(result.stdout, pid, target)
        if after['start_ticks'] != before['start_ticks']:
            raise ValueError('Owned PID changed across capture')
        for name in ('final-field-native.png', 'own-window.png', 'native-proof.txt', 'visual.log'):
            result, _ = checked('fetch-' + name, 'cat ' + shlex.quote(target + '/' + name))
            (local / name).write_bytes(result.stdout)
        proof = (local / 'native-proof.txt').read_text(encoding='utf8')
        if marker not in proof.splitlines() or 'Abs(ElectricField-V)' not in proof.split():
            raise ValueError('Native proof lacks the selected run/TDR identity or field')
        dimensions = {name: _png((local / name).read_bytes(), name) for name in ('final-field-native.png', 'own-window.png')}
        if dimensions['final-field-native.png'] != {'width': 1400, 'height': 1000}:
            raise ValueError('Native export resolution differs')
        if dimensions['own-window.png'] != {'width': int(width), 'height': int(height)}:
            raise ValueError('Screenshot dimensions differ from captured-window report')
        source_check('source-hash-after')
        if dependencies() != dependency_hashes or sha(CAPTURE) != CAPTURE_SHA:
            raise ValueError('GUI/audit/capture implementation changed during evidence capture')
        evidence = {'schema': 'dram-see-v3-r50-main-native-field-evidence', 'run_id': rid, 'ledger_tag': tag,
                    'accepted_case_source': accepted_source, 'physical_revision': 'r50-main-r1',
                    'archive_sha256': summary['archive_sha256'], 'tdr_member': MEMBER, 'tdr_sha256': tdr_hash,
                    'remote_source_sha256_before_load': tdr_hash, 'remote_source_sha256_after_capture': tdr_hash,
                    'native_loaded_file': source + '/' + MEMBER, 'condition': summary['parameters'],
                    'depended_source_files_sha256': dependency_hashes, 'capture_helper_sha256': CAPTURE_SHA,
                    'launch_operation': launch_record, 'capture_operation': capture_record,
                    'operation_directory': operation_root.relative_to(ROOT).as_posix(),
                    'owned_launch_identity_before': before, 'owned_launch_identity_after': after,
                    'captured_process_identity': captured, 'window_id': window_id, 'capture_stdout': capture_stdout,
                    'image_dimensions': dimensions, 'field': 'Abs(ElectricField-V)', 'field_units': 'V/cm', 'coordinate_units': 'um',
                    'visual_version_lines': re.findall(r'[^\r\n]*Version [^\r\n]+', (local / 'visual.log').read_text(errors='replace')),
                    'screenshot_kind': 'real newly owned SVisual X11 window pixels; unmodified',
                    'export_kind': 'native SVisual export from audited final signal TDR',
                    'scope': 'Actual 4 ns signal electric-field map; NOT a transient readout curve or Workbench Run-button evidence; no solver launched',
                    'window_behavior': 'Only newly owned window raised; it may temporarily cover existing windows. No window closed; new GUI remains open.',
                    'visual_review_status': 'pending human/agent image inspection of actual colorbar, units and selected run',
                    'files_sha256': {path.name: sha(path) for path in sorted(local.iterdir()) if path.is_file()}}
        common.write_json(local / 'evidence.json', evidence, exclusive=True)
        common.write_json(operation_root / 'completion.json', {'state': 'CAPTURED_PENDING_VISUAL_REVIEW', 'utc': now(),
                          'evidence': (local / 'evidence.json').relative_to(ROOT).as_posix(), 'evidence_sha256': sha(local / 'evidence.json')}, exclusive=True)
        return evidence
    except Exception as exc:
        common.write_json(operation_root / 'failure.json', {'utc': now(), 'state': 'REQUIRES_READ_ONLY_RECONCILIATION',
                          'error': repr(exc), 'automatic_relaunch': False}, exclusive=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    print(json.dumps(main(parser.parse_args().run_id), indent=2))
