"""Prepare and summarize a gated A0 fine native five-frame cost probe, never run it."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RT = ROOT / 'local_runtime/dram-see-v4/transport-probe'
STATE = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1'
SCRIPT = HERE / 'cost_probe.tcl'
CAMPAIGN = HERE / 'campaign.json'
GATE = STATE / 'gates/a0-b1-fine.json'
FILES = ['gfield_' + str(i) + '_access_des.tdr' for i in range(5)]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def read(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'Duplicate JSON key')
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def sha(path):
    with Path(path).open('rb') as stream:
        return stream_sha(stream)


def stream_sha(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def ref(path):
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def bound(path):
    p = (ROOT / path).resolve()
    require(p.is_relative_to(ROOT.resolve()) and p.is_file() and not p.is_symlink(), 'Unsafe or missing evidence file')
    return p


def members(archive):
    indexed = {}
    for item in archive:
        name = item.name.removeprefix('./')
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and name not in indexed, 'Unsafe or duplicate archive member')
        require(item.isfile() or item.isdir(), 'Unsupported archive link/member')
        indexed[name] = item
    return indexed


def bytes_member(archive, index, name, maximum=32 * 1024 * 1024):
    item = index.get(name)
    require(item is not None and item.isfile() and item.size <= maximum, 'Missing/oversized evidence member: ' + name)
    return archive.extractfile(item).read()


def log_metrics(text):
    """Only the observed exact SDevice grid-point label; never SDE vertices."""
    lines = text.splitlines()
    node_rows = [(i + 1, line, int(m.group(1))) for i, line in enumerate(lines)
                 if (m := re.fullmatch(r'\s*Number of grid points is (\d+)\.\s*', line))]
    values = {row[2] for row in node_rows}
    wall_rows = [(i + 1, line, float(m.group(1))) for i, line in enumerate(lines)
                 if (m := re.fullmatch(r'\s*wallclock:\s*([0-9]+(?:\.[0-9]+)?)\s+s(?:\s+\(.*\))?\s*', line))]
    wall_values = {row[2] for row in wall_rows}
    return {'mesh_node_count': next(iter(values)) if len(values) == 1 and next(iter(values)) > 0 else None,
            'mesh_node_definition': 'SDevice Number of grid points; not SDE intermediate/final vertices or a TDR-size estimate',
            'mesh_node_log_evidence': [{'line_number': n, 'text': line, 'value': value} for n, line, value in node_rows],
            'solver_wallclock_s': next(iter(wall_values)) if len(wall_values) == 1 else None,
            'solver_wallclock_log_evidence': [{'line_number': n, 'text': line, 'value': value} for n, line, value in wall_rows]}


def verify_run(run_id):
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', run_id), 'Unsafe run ID')
    run = ROOT / 'local_runtime/runs' / run_id
    manifest = read(run / 'manifest.json')
    require(manifest.get('run_id') == run_id and manifest.get('state') == 'COLLECTED' and manifest.get('ssh_exit_code') == 0, 'Run is not successfully collected')
    require(sha(run / 'results.tar') == manifest.get('results_sha256'), 'Original archive hash mismatch')
    gate = read(GATE)
    require(gate.get('schema') == 'dram-see-v4-completion-role-gate-r1' and gate.get('role_id') == 'a0-b1-fine'
            and gate.get('passed') is True and gate.get('run_id') == run_id
            and gate.get('campaign_sha256') == sha(CAMPAIGN), 'A0 fine final gate missing or invalid')
    audits = []
    require(isinstance(gate.get('evidence'), list) and gate['evidence'], 'Gate lacks evidence')
    for evidence in gate['evidence']:
        path = bound(evidence['path'])
        require(sha(path) == evidence['sha256'], 'Gate evidence hash changed')
        # requires_pass is a gate-reference policy, not a source-audit type tag.
        # acceptance.reference() defaults it to false even for a passed audit.
        data = read(path) if path.suffix.lower() == '.json' or evidence.get('requires_pass') else None
        if evidence.get('requires_pass'):
            require(isinstance(data, dict) and data.get('passed') is True, 'Gate references failed evidence')
        if (isinstance(data, dict) and data.get('schema') == 'dram-see-v4-source-interface-r5-audit'
                and data.get('run_id') == run_id and data.get('archive_sha256') == manifest['results_sha256']):
            audits.append((path, data))
    require(len(audits) == 1, 'Require one gate-linked passing source audit for this exact run/archive')
    audit_path, audit = audits[0]
    require(audit.get('schema') == 'dram-see-v4-source-interface-r5-audit' and audit.get('passed') is True
            and audit.get('errors') == [], 'Wrong, failed or incomplete source audit')
    checks = audit.get('checks')
    require(isinstance(checks, dict) and bool(checks)
            and all(isinstance(item, dict) and item.get('passed') is True for item in checks.values()), 'Source audit checks incomplete')
    with tarfile.open(run / 'results.tar', 'r:') as tar:
        index = members(tar)
        raw = bytes_member(tar, index, 'parameters.json')
        require(hashlib.sha256(raw).hexdigest() == manifest['input_sha256']['parameters.json'], 'Original parameter hash mismatch')
        parameters = json.loads(raw)
        require([parameters.get('schema'), parameters.get('case_id'), parameters.get('stored_bit'), parameters.get('variant'),
                 parameters.get('mesh_scale'), parameters.get('pulse_max_step_s'), parameters.get('source_count'), parameters.get('source_charge_fC')]
                == ['dram-see-v4-source-interface-r5', 'A0', 1, 'fine', .25, 5e-13, 0, 0.], 'Not the approved A0 bit1 fine source-free run')
        require(audit.get('parameters') == parameters, 'Audited parameters differ from raw archive')
        require(parameters.get('source_contract_sha256') == sha(ROOT / 'experiments/dram-see-v4/source-interface-r5/source_contract.json'), 'Frozen r5 contract differs')
        names = sorted(n for n in index if re.fullmatch(r'gfield_[0-9]+_access_des\.tdr', n))
        require(names == FILES, 'Require exactly the original five gfield frames')
        hashes, sizes = {}, {}
        for name in FILES:
            require(index[name].isfile(), 'Nonregular frame')
            hashes[name] = stream_sha(tar.extractfile(index[name]))
            sizes[name] = index[name].size
        log = bytes_member(tar, index, 'transient_des.log').decode('utf-8', errors='strict')
        metrics = log_metrics(log)
        if metrics['solver_wallclock_s'] is not None and audit.get('solver_wallclock_s') is not None:
            require(metrics['solver_wallclock_s'] == audit['solver_wallclock_s'], 'Raw/audited solver wallclock differs')
        dynamic = sum(bool(re.fullmatch(r'gstep_[0-9]+_access_des\.tdr', n)) and x.isfile() for n, x in index.items())
    remote = manifest.get('remote_directory')
    require(isinstance(remote, str) and remote.endswith('/runs/' + run_id) and '\n' not in remote, 'Remote original run binding differs')
    return {'schema': 'dram-see-v4-fine-cost-source-r1', 'source_run_id': run_id,
            'source_manifest_sha256': sha(run / 'manifest.json'), 'source_archive_sha256': manifest['results_sha256'],
            'source_archive_bytes': (run / 'results.tar').stat().st_size,
            'gate_path': ref(GATE), 'gate_sha256': sha(GATE), 'source_audit_path': ref(audit_path), 'source_audit_sha256': sha(audit_path),
            'campaign_sha256': sha(CAMPAIGN), 'parameters_sha256': manifest['input_sha256']['parameters.json'],
            'tdr_sha256': hashes, 'tdr_bytes': sizes, 'gstep_frame_count_metadata_only': dynamic,
            'log_member': 'transient_des.log', 'log_sha256': hashlib.sha256(log.encode()).hexdigest(),
            **metrics, 'new_sdevice_solves': 0, 'source_field_acceptance': False,
            'fields_unknown': None, 'load_only_is_full_roi_cost': False}, remote


def prepare(run_id, label):
    require(isinstance(label, str) and re.fullmatch(r'r5-[a-z0-9-]+-cost', label), 'Use a new r5-*-cost label')
    folder = RT / 'inputs' / label
    require(not folder.exists(), 'Refuse existing cost input directory')
    evidence, remote = verify_run(run_id)
    evidence.update(probe_script_sha256=sha(SCRIPT), preparer_sha256=sha(Path(__file__)), label=label,
                    native_api_basis='source-field-audit-r2/extract_fields.tcl: load_file/create_plot/list_fields/remove_plots/remove_datasets',
                    timing='Tcl clock milliseconds per load/query/release; no ROI integration')
    commands = ['set -euo pipefail']
    commands += ['cp -- ' + shlex.quote(remote + '/' + name) + ' ' + shlex.quote(name) for name in FILES]
    commands += ['sha256sum -c tdr-sha256.txt', 'set +e',
        '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script cost_probe.tcl > svisual.log 2>&1',
        'v4_cost_rc=$?', 'printf "%s\\n" "$v4_cost_rc" > svisual-exit-code.txt', 'set -e',
        'test "$v4_cost_rc" -eq 0', "grep -Fx 'COST_PROBE_COMPLETED mandatory_errors=0' svisual.log",
        "grep -Fx 'files_completed=5' cost-status.txt", "grep -Fx 'mandatory_command_errors=0' cost-status.txt",
        'sha256sum -c tdr-sha256.txt', 'test -s cost-timing.csv', 'test -s cost-field-inventory.csv',
        'echo FINE_COST_POSTPROCESS_COMPLETED']
    files = {'cost_probe.tcl': SCRIPT.read_bytes(), 'source-evidence.json': encoded(evidence),
             'tdr-files.txt': ''.join(n + '\n' for n in FILES).encode(),
             'tdr-sha256.txt': ''.join(evidence['tdr_sha256'][n] + '  ' + n + '\n' for n in FILES).encode(),
             'task.sh': ('\n'.join(commands) + '\n').encode()}
    folder.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        with (folder / name).open('xb') as stream:
            stream.write(raw)
    return {'input': ref(folder), 'label': label, 'source_run_id': run_id, 'tdr_count': 5,
            'files_sha256': {n: hashlib.sha256(raw).hexdigest() for n, raw in files.items()}, 'new_solves': 0,
            'run_command': 'python -B experiments/dram-see-v4/transport-probe/operation.py ' + label + ' ' + ref(folder),
            'source_field_acceptance': False}


def timing_rows(raw):
    rows = list(csv.DictReader(io.StringIO(raw)))
    require(len(rows) == 5 and [r.get('source_file') for r in rows] == FILES, 'Timing must cover all five frames exactly once in order')
    output = []
    for row in rows:
        require(row.get('status') == 'OK', 'A native frame operation failed')
        values = {}
        for key in ('load_ms', 'query_ms', 'release_ms', 'total_ms'):
            require(re.fullmatch(r'\d+', row.get(key, '')), 'Invalid native millisecond timing')
            values[key] = int(row[key])
        require(sum(values[k] for k in ('load_ms', 'query_ms', 'release_ms')) == values['total_ms'], 'Timing phases do not sum')
        output.append({'source_file': row['source_file'], **values})
    return output


def summarize(operation_path, output):
    operation = Path(operation_path).resolve()
    require(operation.parent == (RT / 'operations').resolve() and re.fullmatch(r'r5-[a-z0-9-]+-cost', operation.name), 'Unexpected cost operation path')
    out = Path(output).resolve()
    require(out.parent == (STATE / 'cost-probes').resolve() and not out.exists(), 'Use a new direct child of campaign cost-probes')
    op = read(operation / 'operation.json')
    require(op.get('label') == operation.name and op.get('state') == 'COLLECTED_PENDING_AUDIT'
            and all(op.get(k) == 0 for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')), 'Operation is not known complete and successful')
    require(op.get('adapter_sha256') == sha(ROOT / 'experiments/dram-see-v4/transport-probe/operation.py'), 'Original operation adapter differs')
    require(sha(operation / 'results.tar') == op.get('archive_sha256'), 'Cost operation archive changed')
    source = RT / 'inputs' / operation.name
    data = operation / 'collected'
    require(op.get('wrapper_sha256') == sha(operation / 'run.sh') == sha(data / 'run.sh'), 'Original single-CPU/lock wrapper differs')
    evidence = read(data / 'source-evidence.json')
    require(evidence.get('label') == operation.name and evidence.get('probe_script_sha256') == sha(SCRIPT)
            and evidence.get('preparer_sha256') == sha(Path(__file__)), 'Cost implementation or operation binding changed')
    current, _ = verify_run(evidence['source_run_id'])
    require(all(evidence.get(k) == v for k, v in current.items()), 'Original fine source/gate evidence changed')
    expected_inputs = {'cost_probe.tcl', 'source-evidence.json', 'tdr-files.txt', 'tdr-sha256.txt', 'task.sh'}
    require(set(op.get('input_sha256', {})) == expected_inputs, 'Unexpected cost input inventory')
    for name, digest in op['input_sha256'].items():
        require(sha(source / name) == digest and sha(data / name) == digest, 'Native cost input bytes changed')
    require((data / 'svisual-exit-code.txt').read_text().strip() == '0', 'Actual SVisual exit is not zero')
    status = (data / 'cost-status.txt').read_text().splitlines()
    required = ['schema=fine-a0-load-cost-r1', 'files_requested=5', 'files_completed=5', 'mandatory_command_errors=0',
                'clock_unit=milliseconds', 'cleanup_success=exact_deleted_object_name', 'source_field_acceptance=false', 'roi_integrals_executed=0']
    require(status == required, 'Cost native status differs')
    require((data / 'svisual.log').read_text().splitlines().count('COST_PROBE_COMPLETED mandatory_errors=0') == 1, 'Native completion sentinel missing or repeated')
    execution = (data / 'execution.log').read_text().splitlines()
    require(execution.count('FINE_COST_POSTPROCESS_COMPLETED') == 1 and execution.count('V4_OPERATION_COMPLETED') == 1, 'Original adapter completion markers missing')
    for name in FILES:
        require(execution.count(name + ': OK') == 2 and sha(data / name) == evidence['tdr_sha256'][name], 'Both before/after frame hashes must match')
    affinity = (data / 'affinity.txt').read_text()
    require(re.search(r'^Threads:\s*1\s*$', affinity, re.MULTILINE) and re.search(r'^Cpus_allowed_list:\s*\d+\s*$', affinity, re.MULTILINE), 'Single-thread/single-CPU affinity evidence missing')
    native_files = ['source-evidence.json', 'cost_probe.tcl', 'cost-timing.csv', 'cost-field-inventory.csv', 'cost-status.txt',
                    'svisual.log', 'svisual-exit-code.txt', 'execution.log', 'affinity.txt', 'run.sh'] + FILES
    with tarfile.open(operation / 'results.tar', 'r:') as tar:
        index = members(tar)
        for name in native_files:
            require(name in index and index[name].isfile() and stream_sha(tar.extractfile(index[name])) == sha(data / name), 'Collected native output differs from operation archive: ' + name)
    timings = timing_rows((data / 'cost-timing.csv').read_text())
    inventory = list(csv.DictReader(io.StringIO((data / 'cost-field-inventory.csv').read_text())))
    fields = {name: [] for name in FILES}
    for row in inventory:
        require(row.get('source_file') in fields and row.get('dataset') and row.get('native_field'), 'Malformed native inventory')
        fields[row['source_file']].append(row['native_field'])
    require(all(names and len(names) == len(set(names)) for names in fields.values()), 'Missing/duplicate native field inventory')
    sums = {k: sum(r[k] for r in timings) for k in ('load_ms', 'query_ms', 'release_ms', 'total_ms')}
    elapsed = None
    if op.get('started_utc') and op.get('finished_utc'):
        elapsed = (datetime.fromisoformat(op['finished_utc']) - datetime.fromisoformat(op['started_utc'])).total_seconds()
        require(elapsed >= 0, 'Negative operation elapsed time')
    result = {'schema': 'dram-see-v4-fine-a0-cost-probe-r1', 'passed': True, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'source_run_id': evidence['source_run_id'], 'source_archive_sha256': evidence['source_archive_sha256'],
              'source_archive_bytes': evidence['source_archive_bytes'], 'source_gate_sha256': evidence['gate_sha256'],
              'mesh_node_count': evidence['mesh_node_count'], 'mesh_node_definition': evidence['mesh_node_definition'],
              'mesh_node_log_evidence': evidence['mesh_node_log_evidence'], 'solver_wallclock_s': evidence['solver_wallclock_s'],
              'solver_wallclock_log_evidence': evidence['solver_wallclock_log_evidence'],
              'frames': timings, 'tdr_bytes': evidence['tdr_bytes'], 'five_frame_bytes': sum(evidence['tdr_bytes'].values()),
              'native_timing_totals_ms': sums, 'native_load_inventory_release_seconds_per_frame': sums['total_ms'] / 5000.,
              'operation_elapsed_s': elapsed, 'operation_elapsed_definition': 'Includes upload/copy/native execution/collection; separate from Tcl phase timing',
              'native_fields_by_frame': fields, 'fields_unknown': None, 'source_field_acceptance': False, 'new_sdevice_solves': 0,
              'full_11roi_extraction_measured_s': None, 'full_11roi_extraction_estimate_s': None,
              'limits': ['Only five native frame load/inventory/release timings measured; no ROI integral or source-field acceptance.',
                         'These load-only observations cannot be presented as full 11-ROI extraction speed.',
                         'Missing exact node/log timing evidence remains null; no size-derived node count.',
                         'Source-free A0 solve cost does not establish nonlinear A1/A5 runtime.']}
    receipt = {'schema': 'dram-see-v4-fine-cost-native-receipt-r1', 'passed': True, 'source_run_id': evidence['source_run_id'],
               'operation_path': ref(operation), 'operation_record_sha256': sha(operation / 'operation.json'),
               'operation_archive_sha256': op['archive_sha256'], 'source_evidence_sha256': sha(data / 'source-evidence.json'),
               'source_archive_sha256': evidence['source_archive_sha256'], 'source_manifest_sha256': evidence['source_manifest_sha256'],
               'tdr_before_sha256': evidence['tdr_sha256'], 'tdr_after_sha256': {n: sha(data / n) for n in FILES},
               'native_outputs_sha256': {n: sha(data / n) for n in native_files if n not in FILES},
               'ssh_exit_code': 0, 'remote_exit_code': 0, 'collection_exit_code': 0, 'svisual_exit_code': 0,
               'single_cpu_affinity': affinity.strip(), 'new_sdevice_solves': 0, 'source_field_acceptance': False,
               'cost_report_sha256': hashlib.sha256(encoded(result)).hexdigest()}
    out.mkdir(parents=True, exist_ok=False)
    for name, value in [('cost.json', result), ('cost-probe-receipt.json', receipt)]:
        with (out / name).open('xb') as stream:
            stream.write(encoded(value))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('run_id'); p.add_argument('label')
    s = sub.add_parser('summarize'); s.add_argument('operation_path', type=Path); s.add_argument('output', type=Path)
    a = parser.parse_args()
    result = prepare(a.run_id, a.label) if a.command == 'prepare' else summarize(a.operation_path, a.output)
    print(json.dumps(result, indent=2, allow_nan=False))
