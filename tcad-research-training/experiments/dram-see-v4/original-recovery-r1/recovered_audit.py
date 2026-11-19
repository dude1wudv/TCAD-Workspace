"""Explicit recovered-A1 scientific composition using unchanged frozen numerics."""
import argparse
import csv
import io
import json
from pathlib import Path
import re

import recovery_proof as proof
import fields_bridge as bridge

ROOT = proof.ROOT
HERE = Path(__file__).resolve().parent
V4 = ROOT / 'experiments/dram-see-v4'
r5 = bridge.module(V4 / 'source-interface-r5/audit_interface.py', '_recovered_r5_numerics')
field = bridge.field
old, T = r5.old, r5.T
require, accepted, builder = r5.require, r5.accepted, r5.builder
canonical_matching, matched_control = r5.canonical_matching, r5.matched_control
compare, comparison_curves, write = r5.compare, r5.comparison_curves, r5.write
sha, read = old.sha_file, bridge.read
FIELD_SCHEMA = 'source-field-audit-r2-recovered-r1'
SINGLE_SCHEMA = 'dram-see-v4-original-recovery-source-audit-r1'
FIELD_CHECKS = {'recovered_engineering_evidence', 'frozen_field_dependencies', 'full_raw_curves',
                'native_extraction_provenance', 'actual_BE_frame_bijection', 'frozen_r5_measurement_contract',
                'native_full_field_gates', 'terminal_voltage_current_conservation', 'safe_archive_read'}
SINGLE_CHECKS = {'recovered_engineering_evidence', 'frozen_r5_inputs', 'full_finite_raw_curves',
                 'native_total_and_timing', 'voltage_current_conservation', 'native_all_frame_source', 'archive_stability'}
PINNED = {
    'source-probe/audit_probe.py': 'd79c0c0989a15e074e39d6ec721b39b5430ded7d4b8f8b6c6f3de122f9fba1c1',
    'source-interface-r5/audit_interface.py': 'ad99cc46364649e246c228fae7d3ad44c1feb1c6163022da18571346d8d6dd42',
    'source-field-audit-r2/audit_fields.py': '5269653bccfabf0a30bd1d839d357fa5df9f5f738edd49df40b93c472d6d0272',
    'source-field-audit-r2/field_contract.json': '8fb5d56e958b6b861d7af360a30cb315fcb7c6a262af32d6a75b92ca81c9115f',
    'source-field-audit-r2/extract_fields.tcl': bridge.EXTRACTOR_SHA256,
}


def dependencies():
    for path, digest in PINNED.items():
        require(sha(V4 / path) == digest, 'Frozen scientific dependency changed: ' + path)
    require(field.T == T and field.CONVERSION == r5.CONVERSION, 'Frozen numerical tolerances/conversion differ')
    require(field.C['frozen_reference_contract_sha256'] == sha(field.r3.b.CONTRACT) and
            field.C['audit_tolerances'] == field.r3.T, 'Frozen field reference contract changed')
    for name, digest in field.C['frozen_library_sha256'].items():
        require(sha(ROOT / name) == digest, 'Frozen field library changed: ' + name)
    return {str((V4 / p).relative_to(ROOT)).replace('\\', '/'): digest for p, digest in PINNED.items()}


def _report(schema):
    out = r5.report(schema)
    out.update(audit_code_sha256=sha(Path(__file__)), recovery_adapter_sha256=sha(Path(__file__)),
               original_execution_contract_passed=False, recovered_engineering_evidence_passed=False)
    return out


def _bind(out, run):
    require(Path(run).resolve() == proof.RUN_FOLDER.resolve(), 'Only the exact original run may use recovery science')
    out['frozen_dependency_sha256'] = dependencies()
    manifest = proof.bind_report(out, run)
    require(out.get('original_execution_contract_passed') is False and
            out.get('recovered_engineering_evidence_passed') is True, 'Recovery proof did not establish its explicit contract')
    return manifest


def _finish(out, expected, success):
    out['passed'] = not out['errors'] and set(out['checks']) == set(expected) and all(
        v.get('passed') is True for v in out['checks'].values())
    out['status'] = success if out['passed'] else 'FAILED_OR_INCOMPLETE'
    return out


def _stable(run, out):
    require(sha(Path(run) / 'manifest.json') == out['manifest_sha256'] and
            sha(Path(run) / 'results.tar') == out['archive_sha256'], 'Original evidence changed during scientific audit')
    require(dependencies() == out['frozen_dependency_sha256'], 'Scientific dependencies changed during audit')
    reference = out['recovery_reference']
    require(sha(ROOT / reference['path']) == reference['sha256'], 'Recovery contract changed during audit')
    return True


def _field_physics(archive, project, curves, out):
    p, spec, source_proof = r5.check_contract(archive, project, out)
    c = old.json_load(archive.read('source-contract.json'))
    require(p['schema'] == 'dram-see-v4-source-interface-r5' and p['case_id'] == 'A1' and
            p['stored_bit'] == 1 and p['variant'] == 'time', 'Recovered scientific identity differs')
    require(c['audit_tolerances'] == field.T and c['rois_um'] == field.C['rois_um'], 'Field thresholds/ROIs differ')
    require(c['additional_roi_gate_cases'] == field.C['local_source_roi_cases'] and
            c['additional_rois'] == field.C['local_source_rois'] and
            c['legacy_roi_names'] == field.C['legacy_rois'], 'Field ROI gate scope differs')
    out['source_parameters'] = p
    out['cadence'] = field.r3.r2.cadence(curves, p)
    return p, spec, source_proof


def _extraction(extraction, archive, solver_report, out):
    operation = Path(extraction).resolve()
    if operation.name == 'collected':
        operation = operation.parent
    require(operation == (bridge.TRANSPORT / 'operations' / bridge.FIELD_LABEL).resolve(), 'Recovery extraction operation differs')
    record = read(operation / 'field-extraction-record.json')
    bridge.validate_recovery_binding(record, solver_report)
    return field.extraction_evidence(operation, archive, solver_report, out)


def _mapping(archive, curves, files):
    actual = {n for n in archive.members if re.fullmatch(r'gstep(?:_[A-Za-z0-9]+)+\.tdr', n)}
    require(len(files) == bridge.EXPECTED_FRAMES and actual == set(files), 'All original 405 gstep frames are required exactly once')
    index, boundary = field.index_frames(archive.read('transient_des.log').decode(errors='replace'),
                                         curves['device'], files, True)
    require(len(index) == bridge.EXPECTED_FRAMES - 1 and len(boundary) == 1,
            'Recovered original accepted/boundary frame counts differ')
    return index, boundary


def _frame_csv(frames):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(frames[0]))
    writer.writeheader(); writer.writerows(frames)
    return buffer.getvalue().encode('utf-8')


def _output(path, kind):
    dest = Path(path).resolve()
    allowed = [proof.STATE / 'scientific-audits',
               ROOT / 'local_runtime/dram-see-v4/source-field-audit-r2/audit-dev'] if kind == 'field' else [
               ROOT / 'local_runtime/dram-see-v4/source-interface-r5/audits']
    require(any(dest.is_relative_to(base.resolve()) and dest != base.resolve() for base in allowed),
            'Output must be a new allowed v4 scientific-audit child')
    require(not dest.exists(), 'Audit output exists; preserve it and review before another revision')
    return dest


def field_audit(run, extraction, output=None):
    run = Path(run).resolve()
    dest = _output(output, 'field') if output is not None else None
    out = _report(FIELD_SCHEMA)
    out.update(mode='full', field_measurements_passed=False, audit_sha256=sha(Path(__file__)),
               field_contract_sha256=sha(V4 / 'source-field-audit-r2/field_contract.json'))
    checks = old.Checks(out)
    manifest = checks.call('recovered_engineering_evidence', lambda: _bind(out, run))
    frames = []
    if manifest is not None:
        checks.call('frozen_field_dependencies', dependencies)
        def inspect():
            nonlocal frames
            with old.Archive(run / 'results.tar') as archive:
                curves = checks.call('full_raw_curves', lambda: old._curves(archive, out))
                extracted = checks.call('native_extraction_provenance', lambda: _extraction(extraction, archive, out, out))
                if curves is None or extracted is None:
                    return False
                files, values = extracted
                mapped = checks.call('actual_BE_frame_bijection', lambda: _mapping(archive, curves, files))
                if mapped is not None:
                    index, boundary = mapped
                    out.update(accepted_intervals=index, boundary_frames_not_integrated=boundary)
                    frames = field.summarize_snapshots(index, values)
                    out['frame_count'] = len(frames)
                    physical = checks.call('frozen_r5_measurement_contract', lambda: _field_physics(archive, None, curves, out))
                    if physical is not None:
                        p, spec, source_proof = physical
                        checks.call('native_full_field_gates', lambda: field.full_metrics(index, values, curves['device'], spec, source_proof, out))
                        checks.call('terminal_voltage_current_conservation', lambda: old._response(p, curves, out))
            return _stable(run, out)
        checks.call('safe_archive_read', inspect)
    _finish(out, FIELD_CHECKS, 'RECOVERED_NATIVE_FULL_FIELD_GATES_PASSED_CONTROL_STILL_REQUIRED')
    out['field_measurements_passed'] = out['passed']
    frame_bytes = _frame_csv(frames) if frames else None
    if frame_bytes:
        out.update(frames_csv_sha256=old.sha_bytes(frame_bytes), frames_csv_schema='source-field-audit-r2-native-11roi-frames',
                   frames_csv_path=str(dest / 'frames.csv') if dest else None)
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=False)
        if frame_bytes:
            with (dest / 'frames.csv').open('xb') as stream:
                stream.write(frame_bytes)
        bridge.save_new(dest / 'audit.json', out)
    return out


def bind_recovered_field_rows(path, out, curves, archive):
    path = Path(path).resolve()
    raw = path.read_bytes(); f = old.json_load(raw)
    accepted(f)
    require(f.get('schema') == FIELD_SCHEMA and f.get('mode') == 'full' and
            f.get('field_measurements_passed') is True and set(f['checks']) == FIELD_CHECKS, 'Complete recovered field audit required')
    require(f.get('audit_code_sha256') == f.get('recovery_adapter_sha256') == sha(Path(__file__)), 'Recovery field auditor changed')
    require(f.get('frozen_dependency_sha256') == dependencies() == out['frozen_dependency_sha256'], 'Frozen field dependencies differ')
    require(f.get('field_contract_sha256') == sha(V4 / 'source-field-audit-r2/field_contract.json'), 'Field contract changed')
    require(f.get('original_execution_contract_passed') is False and f.get('recovered_engineering_evidence_passed') is True,
            'Recovered report changed original execution facts')
    for key in ('run_id', 'archive_sha256', 'manifest_sha256', 'mesh_sha256', 'recovery_reference', 'engineering_evidence'):
        require(f.get(key) == out[key], 'Recovered field report belongs to another source: ' + key)
    require(not f.get('field_gate_failures'), 'Native spatial/temporal gates failed')
    receipt = f['extraction_record']
    operation = (ROOT / receipt['operation_record']).resolve().parent
    scratch = {}
    files, values = _extraction(operation, archive, out, scratch)
    require(scratch['extraction_record'] == receipt and scratch['extraction_record_sha256'] == f['extraction_record_sha256'],
            'Published extraction receipt differs')
    index, boundary = _mapping(archive, curves, files)
    require(index == f['accepted_intervals'] and boundary == f['boundary_frames_not_integrated'] and
            len(index) == f['frame_count'], 'Published accepted/boundary intervals differ')
    frame_path = Path(f['frames_csv_path']).resolve()
    require(frame_path == path.parent / 'frames.csv' and sha(frame_path) == f['frames_csv_sha256'], 'Published frame CSV changed')
    require(frame_path.read_bytes() == _frame_csv(field.summarize_snapshots(index, values)), 'Frame CSV does not reproduce native observations')
    require(scratch['field_measurements_sha256'] == f['field_measurements_sha256'] == receipt['native_outputs_sha256']['field-measurements.csv'],
            'Published native measurements differ')
    # Retain the real window-start boundary for comparison, never integrate it twice.
    rows = []
    for interval in sorted(boundary + index, key=lambda row: row['end_s']):
        row = {'time': interval['end_s'], 'start_s': interval['start_s'], 'source_file': interval['source_file']}
        for roi in field.C['rois_um']:
            row[roi] = values[interval['source_file']][('G', roi)] * r5.CONVERSION
        rows.append(row)
    require(sha(path) == old.sha_bytes(raw), 'Recovered field report changed during binding')
    out['native_field_audit'] = dict(path=str(path), sha256=old.sha_bytes(raw), report=f,
        field_measurements_sha256=f['field_measurements_sha256'],
        native_curves_from='Unchanged frozen parsers over original TDR measurements and accepted PLT intervals; explicit recovery provenance')
    return rows


def load(run, project=None, field_audit=None):
    run = Path(run).resolve()
    if run.name != proof.RUN_ID:
        return r5.load(run, project, field_audit)
    out = _report(SINGLE_SCHEMA); out['run_path'] = str(run)
    bundle = {'summary': out}; checks = old.Checks(out)
    manifest = checks.call('recovered_engineering_evidence', lambda: _bind(out, run))
    if manifest is None:
        return bundle
    def inspect():
        with old.Archive(run / 'results.tar') as archive:
            physical = checks.call('frozen_r5_inputs', lambda: r5.check_contract(archive, project, out))
            curves = checks.call('full_finite_raw_curves', lambda: old._curves(archive, out))
            if curves is not None:
                bundle['curves'] = curves
            if physical is not None:
                p, spec, source_proof = physical
                require([p['case_id'], p['stored_bit'], p['variant']] == ['A1', 1, 'time'], 'Recovered source identity differs')
                bundle.update(parameters=p, source=spec, proof=source_proof)
                if curves is not None:
                    checks.call('native_total_and_timing', lambda: r5.source_curve(curves, p, spec, source_proof, out))
                    checks.call('voltage_current_conservation', lambda: old._response(p, curves, out))
                    def bind():
                        require(field_audit is not None, 'Native full-frame recovered field audit required')
                        bundle['native_curves'] = bind_recovered_field_rows(field_audit, out, curves, archive)
                        return True
                    checks.call('native_all_frame_source', bind)
        return _stable(run, out)
    checks.call('archive_stability', inspect)
    _finish(out, SINGLE_CHECKS, 'RECOVERED_R5_INDIVIDUAL_PASSED_CONTROL_AND_COMPARISONS_REQUIRED')
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('fields'); p.add_argument('run', type=Path); p.add_argument('--extraction', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('single'); p.add_argument('run', type=Path); p.add_argument('--project', type=Path, required=True)
    p.add_argument('--field', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'fields':
        result = field_audit(args.run, args.extraction, args.output)
    else:
        _output(args.output, 'single')
        bundle = load(args.run, args.project, args.field)
        write(args.output, bundle); result = bundle['summary']
    print(json.dumps({k: result.get(k) for k in ('schema', 'passed', 'status', 'errors')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
