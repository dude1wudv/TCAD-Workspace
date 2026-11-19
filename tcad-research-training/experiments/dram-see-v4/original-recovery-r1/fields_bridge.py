"""Prepare/receipt bridge for one recovered original run; never execute SSH."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shlex

import recovery_proof as proof

ROOT = proof.ROOT
V4 = ROOT / 'experiments/dram-see-v4'
TRANSPORT = ROOT / 'local_runtime/dram-see-v4/transport-probe'
FIELD_LABEL = proof.LABEL + '-fields'
EXPECTED_FRAMES = 405
EXTRACTOR_SHA256 = 'e7b05794444fa0a0406efced528360a75e04325441d994b098e836ffd6df386e'
OPERATION_SHA256 = '55d4b650b047be490a1aeb6b5c6d97c833e9bcab3c7ccbfc17ce7ee53c930d1b'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


field = module(V4 / 'source-field-audit-r2/audit_fields.py', '_recovery_native_fields')
old = field.old
require, sha, read = old.require, old.sha_file, lambda p: old.json_load(Path(p).read_bytes())


def reference(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT.resolve()) and path.is_file() and not path.is_symlink(), 'Invalid evidence path')
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}


def save_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def check_label(label):
    require(label == FIELD_LABEL, 'Only the original recovered field-operation label is allowed')


def original_frames(archive):
    files = sorted(n for n in archive.members if re.fullmatch(r'gstep_[0-9]+_access_des\.tdr', n))
    all_gstep = {n for n in archive.members if re.fullmatch(r'gstep(?:_[A-Za-z0-9]+)+\.tdr', n)}
    require(len(files) == EXPECTED_FRAMES and set(files) == all_gstep, 'Original 405-frame inventory differs')
    require(all(archive.members[n].size > 0 for n in files), 'Empty original field frame')
    return {n: archive.digest(n) for n in files}


def render_task(remote, hashes):
    require(remote.endswith('/runs/' + proof.RUN_ID), 'Original remote run binding differs')
    commands = ['set -euo pipefail']
    commands += ['cp -- ' + shlex.quote(remote + '/' + n) + ' ' + shlex.quote(n) for n in sorted(hashes)]
    commands += ['sha256sum -c tdr-sha256.txt', 'set +e',
        '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl > svisual.log 2>&1',
        'v4_field_rc=$?', 'printf "%s\\n" "$v4_field_rc" > svisual-exit-code.txt',
        'set -e', 'test "$v4_field_rc" -eq 0',
        "grep -F 'FIELD_AUDIT_COMPLETED mandatory_errors=0' svisual.log",
        "grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt", 'sha256sum -c tdr-sha256.txt',
        'test -s field-inventory.csv', 'test -s field-measurements.csv',
        'echo NATIVE_FIELD_POSTPROCESS_COMPLETED']
    return ('\n'.join(commands) + '\n').encode('utf-8')


def validate_recovery_binding(record, recovered):
    require({'original_runner_exit_code', 'original_ssh_exit_code', 'original_engineering_marker_present',
             'original_execution_contract_passed', 'recovered_engineering_evidence_passed',
             'recovery_reference', 'bridge_sha256'} <= set(record), 'Recovery evidence fields are incomplete')
    require(record.get('solver_run_id', record.get('source_run_id')) == recovered['run_id'] == proof.RUN_ID,
            'Recovered extraction run identity differs')
    require(record.get('recovery_reference') == recovered['recovery_reference'], 'Recovery proof reference differs')
    require(record.get('original_execution_contract_passed') is False and
            record.get('recovered_engineering_evidence_passed') is True, 'Recovery evidence semantics differ')
    require(record.get('original_runner_exit_code') is None and record.get('original_ssh_exit_code') is None
            and record.get('original_engineering_marker_present') is False, 'Original unknown/missing evidence was relabeled')
    require(record.get('bridge_sha256') == sha(Path(__file__)), 'Recovery field bridge changed')


def recovery_metadata(recovered):
    return dict(recovery_reference=recovered['recovery_reference'],
                original_execution_contract_passed=False, recovered_engineering_evidence_passed=True,
                original_runner_exit_code=None, original_ssh_exit_code=None,
                original_engineering_marker_present=False, bridge_sha256=sha(Path(__file__)))


def prepare(run_id, label):
    require(run_id == proof.RUN_ID, 'Only the original run may be recovered')
    check_label(label)
    recovered = proof.verify(proof.RUN_FOLDER)
    script = V4 / 'source-field-audit-r2/extract_fields.tcl'
    require(sha(script) == EXTRACTOR_SHA256, 'Frozen native extractor changed')
    require(sha(V4 / 'transport-probe/operation.py') == OPERATION_SHA256, 'Frozen operation adapter changed')
    folder = TRANSPORT / 'inputs' / label
    require(not folder.exists() and not (TRANSPORT / 'operations' / label).exists(),
            'Original field preparation/operation exists; reconcile it, never resubmit')
    with old.Archive(proof.RUN_FOLDER / 'results.tar') as archive:
        hashes = original_frames(archive)
    evidence = dict(schema='dram-see-v4-native-field-postprocess-recovered-r1', source_run_id=run_id,
                    source_archive_sha256=recovered['archive_sha256'], source_manifest_sha256=recovered['manifest_sha256'],
                    original_manifest_state=recovered['original_manifest']['state'], script_sha256=sha(script),
                    tdr_sha256=hashes, new_sdevice_solves=0, threads=1,
                    time_binding='Accepted BE intervals remain bound to original logs and PLT; names are identifiers.',
                    **recovery_metadata(recovered))
    task = render_task(recovered['original_manifest']['remote_directory'], hashes)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'extract_fields.tcl').write_bytes(script.read_bytes())
    (folder / 'tdr-files.txt').write_bytes(''.join(n + '\n' for n in hashes).encode())
    (folder / 'tdr-sha256.txt').write_bytes(''.join(hashes[n] + '  ' + n + '\n' for n in hashes).encode())
    save_new(folder / 'source-evidence.json', evidence)
    (folder / 'task.sh').write_bytes(task)
    require(sha(proof.RUN_FOLDER / 'manifest.json') == recovered['manifest_sha256'] and
            sha(proof.RUN_FOLDER / 'results.tar') == recovered['archive_sha256'], 'Original evidence changed during preparation')
    return dict(input=folder.relative_to(ROOT).as_posix(), tdr_count=len(hashes), new_solves=0,
                recovery_reference=recovered['recovery_reference'], solver_started=False)


def collect(label):
    check_label(label)
    recovered = proof.verify(proof.RUN_FOLDER)
    operation = TRANSPORT / 'operations' / label
    inputs = TRANSPORT / 'inputs' / label
    data = operation / 'collected'
    receipt_path = operation / 'field-extraction-record.json'
    require(not receipt_path.exists(), 'Extraction receipt exists; verify/reuse it, do not replace')
    op = read(operation / 'operation.json')
    require(op.get('label') == label and op.get('adapter_sha256') == OPERATION_SHA256, 'Operation identity/adapter differs')
    require(op.get('state') == 'COLLECTED_PENDING_AUDIT' and
            all(type(op.get(k)) is int and op[k] == 0 for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')),
            'Native extraction outcome unknown or failed')
    require(sha(operation / 'results.tar') == op['archive_sha256'], 'Operation archive hash differs')
    require((data / 'exit-code.txt').read_bytes().strip() == b'0', 'Raw extraction remote exit differs')
    evidence = read(data / 'source-evidence.json')
    validate_recovery_binding(evidence, recovered)
    require(evidence.get('schema') == 'dram-see-v4-native-field-postprocess-recovered-r1' and
            evidence.get('source_manifest_sha256') == recovered['manifest_sha256'] and
            evidence.get('source_archive_sha256') == recovered['archive_sha256'], 'Source manifest/archive binding differs')
    require(evidence.get('original_manifest_state') == recovered['original_manifest']['state'] and
            evidence.get('script_sha256') == EXTRACTOR_SHA256 and evidence.get('new_sdevice_solves') == 0 and
            evidence.get('threads') == 1, 'Prepared recovery metadata differs')
    expected_inputs = {'extract_fields.tcl', 'tdr-files.txt', 'tdr-sha256.txt', 'source-evidence.json', 'task.sh'}
    require(set(op['input_sha256']) == expected_inputs, 'Operation input inventory differs')
    for name, digest in op['input_sha256'].items():
        require(sha(inputs / name) == digest == sha(data / name), 'Extraction input changed: ' + name)
    with old.Archive(proof.RUN_FOLDER / 'results.tar') as archive:
        hashes = original_frames(archive)
    require(evidence['tdr_sha256'] == hashes, 'Prepared original frame hashes differ')
    names = (data / 'tdr-files.txt').read_text().splitlines()
    require(names == sorted(hashes) and len(names) == EXPECTED_FRAMES, 'TDR list differs')
    require((data / 'tdr-sha256.txt').read_bytes() == ''.join(hashes[n] + '  ' + n + '\n' for n in names).encode(),
            'Expected remote checksum list differs')
    require((data / 'task.sh').read_bytes() == render_task(recovered['original_manifest']['remote_directory'], hashes),
            'Extraction task differs from the reviewed serial task')
    field.checked_extractor(EXTRACTOR_SHA256, data / 'extract_fields.tcl')
    post = {n: sha(data / n) for n in names}
    require(post == hashes, 'Copied original TDR bytes changed')
    lines = (data / 'execution.log').read_text(encoding='utf-8').splitlines()
    require('V4_OPERATION_COMPLETED' in lines and 'NATIVE_FIELD_POSTPROCESS_COMPLETED' in lines,
            'New extraction completion marker missing')
    require(all(lines.count(n + ': OK') == 2 for n in names), 'Both native before/after hashes are required')
    require((data / 'svisual-exit-code.txt').read_bytes().strip() == b'0', 'Native SVisual did not exit zero')
    status = {}
    for line in (data / 'diagnostic-status.txt').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            require(key not in status, 'Duplicate native status field')
            status[key] = value
    require(status.get('schema') == 'source-field-audit-r2-extraction' and
            status.get('mandatory_command_errors') == '0' and
            status.get('files_requested') == status.get('files_completed') == str(len(names)), 'Native extraction incomplete')
    require(status.get('memory_release') == 'plot_then_dataset_per_frame' and
            status.get('cleanup_success') == 'exact_deleted_object_name', 'Native memory cleanup semantics differ')
    require('FIELD_AUDIT_COMPLETED mandatory_errors=0' in (data / 'svisual.log').read_text(errors='replace').splitlines(),
            'Native SVisual completion sentinel missing')
    measurements = (data / 'field-measurements.csv').read_text()
    field.parse_measurements(measurements, names)
    field.check_cleanup(measurements, names, 'exact_deleted_object_name', (data / 'field-inventory.csv').read_text())
    native_hashes = {p.name: sha(p) for p in data.iterdir() if p.is_file() and not p.name.endswith('.tdr')}
    require({'field-measurements.csv', 'field-inventory.csv', 'tdr-state-metadata.csv', 'diagnostic-status.txt',
             'svisual.log', 'svisual-exit-code.txt'} <= set(native_hashes), 'Missing native evidence')
    with old.Archive(operation / 'results.tar') as archive:
        for name, digest in dict(native_hashes, **hashes).items():
            require(archive.digest(name) == digest, 'Collected bytes differ from operation archive: ' + name)
    record = dict(schema='dram-see-v4-native-field-extraction-receipt-r1', created_utc=datetime.now(timezone.utc).isoformat(),
        solver_run_id=proof.RUN_ID, solver_archive_sha256=recovered['archive_sha256'],
        solver_manifest_sha256=recovered['manifest_sha256'], tdr_files_sha256=hashes, tdr_before_sha256=hashes,
        tdr_after_sha256=post, extractor_sha256=EXTRACTOR_SHA256,
        operation_record=(operation / 'operation.json').relative_to(ROOT).as_posix(), operation_record_sha256=sha(operation / 'operation.json'),
        operation_archive=(operation / 'results.tar').relative_to(ROOT).as_posix(), operation_archive_sha256=op['archive_sha256'],
        svisual_exit_code=0, remote_exit_code=op['remote_exit_code'], runner_exit_code=op['ssh_exit_code'],
        runner_exit_definition='Actual new field-extraction SSH exit; original TCAD runner/SSH remain unknown.',
        collection_exit_code=op['collection_exit_code'], single_cpu_affinity=(data / 'affinity.txt').read_text().strip(),
        native_outputs_sha256=native_hashes, new_sdevice_solves=0, physical_source_acceptance=False,
        **recovery_metadata(recovered))
    require(sha(proof.RUN_FOLDER / 'manifest.json') == recovered['manifest_sha256'] and
            sha(proof.RUN_FOLDER / 'results.tar') == recovered['archive_sha256'] and
            sha(operation / 'results.tar') == op['archive_sha256'], 'Evidence changed during receipt validation')
    require(read(operation / 'operation.json') == op, 'Operation record changed during receipt validation')
    save_new(receipt_path, record)
    return dict(receipt=receipt_path.relative_to(ROOT).as_posix(), frames=len(names), extraction_complete=True,
                physical_acceptance=False, new_sdevice_solves=0, recovery_reference=recovered['recovery_reference'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('run_id'); p.add_argument('label')
    p = sub.add_parser('collect'); p.add_argument('label')
    args = parser.parse_args()
    value = prepare(args.run_id, args.label) if args.command == 'prepare' else collect(args.label)
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
