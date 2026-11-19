"""Read-only local campaign accounting; writes only a new timestamped report pair.

No SSH, solver, cleanup, archive extraction, runner import or secret access.
Archive headers supply sizes and frame inventory, never mesh node counts.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RT = ROOT / 'local_runtime/dram-see-v4'
CAMPAIGN = HERE / 'campaign.json'
STATE = RT / 'interface-completion-r1'
OUTPUT_ROOT = STATE / 'budget'
STAMP_PATTERN = r'\d{8}T\d{6}\.\d{6}Z-[a-f0-9]{8}'


def _ref(path):
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _load(path, sources, warnings):
    """Read only specifically selected JSON records, and record their snapshot hash."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Symlink or path outside repository')
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('JSON record exceeds 64 MiB read limit')
        raw = path.read_bytes()
        value = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if not isinstance(value, dict):
            raise ValueError('Expected JSON object')
        sources[_ref(path)] = {'sha256': _sha(raw), 'bytes': len(raw)}
        return value
    except (OSError, ValueError, UnicodeError) as exc:
        warnings.append({'path': _ref(path), 'error': str(exc)})
        return None


def _elapsed(start, finish):
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    try:
        a = datetime.fromisoformat(start.replace('Z', '+00:00'))
        b = datetime.fromisoformat(finish.replace('Z', '+00:00'))
        if a.tzinfo is None or b.tzinfo is None:
            return None
        seconds = (b - a).total_seconds()
        return seconds if seconds >= 0 and math.isfinite(seconds) else None
    except (ValueError, TypeError):
        return None


def _number(value, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    if integer and (int(value) != value or value <= 0):
        return None
    return int(value) if integer else float(value)


def _execution_status(record, manifest=None):
    codes = [record.get(k) for k in ('runner_exit_code', 'ssh_exit_code')]
    if any(type(x) is int and x != 0 for x in codes):
        return 'FAILED'
    if record.get('state') == 'RUNNER_EXITED' and codes == [0, 0] and record.get('runner_manifest_state') == 'COLLECTED':
        if manifest and manifest.get('state') == 'COLLECTED' and manifest.get('ssh_exit_code') == 0:
            return 'COMPLETED'
        return 'UNRESOLVED'
    if record.get('state') in ('PREPARING', 'PREPARED', 'RUNNING'):
        return 'RUNNING_OR_UNRESOLVED'
    return 'UNRESOLVED'


def _tar_metadata(path, warnings):
    result = {'path': _ref(path), 'archive_bytes': None, 'metadata_read': False,
              'regular_member_count': None, 'regular_member_bytes': None,
              'gfield_frame_count': None, 'gstep_frame_count': None, 'gstep_bytes': None,
              'mesh_tdr_bytes': None, 'mesh_node_count': None,
              'content_hash_verified_by_reporter': False}
    if not path.is_file():
        return result
    before = path.stat()
    result['archive_bytes'] = before.st_size
    try:
        seen, count, size, fixed, dynamic, dynamic_bytes = set(), 0, 0, 0, 0, 0
        mesh_bytes = None
        # The original runner emits an uncompressed tar. Seeking headers avoids
        # reading/decompressing TDR payloads or making any extracted copy.
        with tarfile.open(path, mode='r:') as archive:
            for member in archive:
                name = member.name.removeprefix('./')
                pure = PurePosixPath(name)
                if pure.is_absolute() or '..' in pure.parts or name in seen:
                    raise ValueError('Unsafe or duplicate archive member metadata')
                seen.add(name)
                if not member.isfile():
                    continue
                count += 1
                size += member.size
                if re.fullmatch(r'gfield_[0-9]+_access_des\.tdr', name):
                    fixed += 1
                if re.fullmatch(r'gstep_[0-9]+_access_des\.tdr', name):
                    dynamic += 1
                    dynamic_bytes += member.size
                if name == 'cell_msh.tdr':
                    mesh_bytes = member.size
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Archive changed during metadata scan')
        result.update(metadata_read=True, regular_member_count=count, regular_member_bytes=size,
                      gfield_frame_count=fixed, gstep_frame_count=dynamic, gstep_bytes=dynamic_bytes,
                      mesh_tdr_bytes=mesh_bytes)
    except (OSError, ValueError, tarfile.TarError) as exc:
        warnings.append({'path': _ref(path), 'error': str(exc)})
    return result


def _audit_index(sources, warnings):
    by_run = {}
    for directory in sorted(RT.glob('source-interface-*/audits')):
        for path in sorted(directory.rglob('audit.json')):
            data = _load(path, sources, warnings)
            if data and isinstance(data.get('run_id'), str):
                by_run.setdefault(data['run_id'], []).append((path, data))
    return by_run


def _agreed_measurement(audits, keys, integer=False):
    measurements = []
    for path, data in audits:
        for key in keys:
            value = _number(data.get(key), integer)
            if value is not None:
                measurements.append((value, _ref(path), key))
    values = {item[0] for item in measurements}
    return (next(iter(values)) if len(values) == 1 else None,
            [{'path': path, 'field': field, 'value': value} for value, path, field in measurements])


def _scientific_status(audits):
    flags = {data['passed'] for _, data in audits if type(data.get('passed')) is bool}
    if flags == {True}:
        return 'REPORTED_PASSED'
    if flags == {False}:
        return 'REPORTED_FAILED'
    if flags:
        return 'MIXED_RECORDS_REVIEW_REQUIRED'
    return 'NOT_YET_AUDITED'


def _launch_row(path, record, historical, campaign_sha, audits, sources, warnings):
    run_id = record.get('run_id')
    safe_id = isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', run_id)
    run = ROOT / 'local_runtime/runs' / run_id if safe_id else None
    manifest = _load(run / 'manifest.json', sources, warnings) if run else None
    evidence = audits.get(run_id, [])
    wall, wall_evidence = _agreed_measurement(evidence, ['solver_wallclock_s'])
    nodes, node_evidence = _agreed_measurement(evidence, ['mesh_node_count', 'mesh_nodes', 'number_of_mesh_nodes'], True)
    category = 'historical' if historical else record.get('budget_category')
    registered = historical or (record.get('campaign_sha256') == campaign_sha and category in ('primary', 'reserve'))
    row = {'label': record.get('label', path.parent.name), 'execution_path': _ref(path),
           'run_id': run_id if safe_id else None, 'identity': record.get('identity'),
           'role_id': record.get('role_id'), 'budget_category': category if registered else 'unregistered',
           'registered': registered, 'interface_revision': record.get('interface_revision'),
           'execution_status': _execution_status(record, manifest), 'runner_state': record.get('state'),
           'runner_exit_code': record.get('runner_exit_code'), 'ssh_exit_code': record.get('ssh_exit_code'),
           'manifest_state': manifest.get('state') if manifest else None,
           'started_utc': record.get('started_utc'), 'finished_utc': record.get('finished_utc'),
           'launch_elapsed_s': _elapsed(record.get('started_utc'), record.get('finished_utc')),
           'solver_wallclock_s': wall, 'solver_wallclock_evidence': wall_evidence,
           'mesh_node_count': nodes, 'mesh_node_evidence': node_evidence,
           'scientific_status': _scientific_status(evidence),
           'audit_records': [{'path': _ref(p), 'passed': d.get('passed')} for p, d in evidence],
           'archive': _tar_metadata(run / 'results.tar', warnings) if run else None,
           'recorded_archive_sha256': manifest.get('results_sha256') if manifest else None}
    outcome = _load(STATE / 'outcomes' / (path.parent.name + '.json'), sources, warnings)
    row['reported_campaign_outcome'] = {'passed': outcome.get('passed'), 'path': _ref(STATE / 'outcomes' / (path.parent.name + '.json'))} if outcome else None
    return row


def _operations(sources, warnings):
    rows = []
    for path in sorted((RT / 'transport-probe/operations').glob('r5-*/operation.json')):
        data = _load(path, sources, warnings)
        if data is None:
            rows.append({'operation_path': _ref(path), 'status': 'UNREADABLE', 'elapsed_s': None})
            continue
        receipt_path = path.parent / 'field-extraction-record.json'
        receipt = _load(receipt_path, sources, warnings)
        evidence = _load(path.parent / 'collected/source-evidence.json', sources, warnings)
        if evidence is None:
            evidence = _load(RT / 'transport-probe/inputs' / path.parent.name / 'source-evidence.json', sources, warnings)
        codes = {k: data.get(k) for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')}
        success = data.get('state') == 'COLLECTED_PENDING_AUDIT' and all(v == 0 for v in codes.values())
        failed = any(type(v) is int and v != 0 for v in codes.values())
        status = 'COMPLETED' if success else 'FAILED' if failed else 'RUNNING_OR_UNRESOLVED'
        frame_hashes = receipt.get('tdr_files_sha256') if receipt else None
        planned = evidence.get('tdr_sha256') if evidence else None
        rows.append({'label': data.get('label', path.parent.name), 'operation_path': _ref(path),
                     'status': status, 'state': data.get('state'), 'exit_codes': codes,
                     'started_utc': data.get('started_utc'), 'finished_utc': data.get('finished_utc'),
                     'elapsed_s': _elapsed(data.get('started_utc'), data.get('finished_utc')),
                     'elapsed_definition': 'Operation start to collection end; includes transfer/archive overhead, not pure native SVisual time',
                     'native_svisual_wallclock_s': None,
                     'source_run_id': receipt.get('solver_run_id') if receipt else evidence.get('source_run_id') if evidence else None,
                     'requested_frame_count': len(planned) if isinstance(planned, dict) else None,
                     'completed_receipt_frame_count': len(frame_hashes) if isinstance(frame_hashes, dict) and success else None,
                     'receipt_path': _ref(receipt_path) if receipt else None,
                     'receipt_present': receipt is not None,
                     'physical_acceptance': 'Separate field/source audit required; extraction completion is not acceptance',
                     'archive': _tar_metadata(path.parent / 'results.tar', warnings),
                     'recorded_archive_sha256': data.get('archive_sha256')})
    return rows


def _raw_r5_runs(launches, sources, warnings):
    """Also inventory a running raw folder before its launcher records run_id."""
    linked = {r['run_id']: r for r in launches if r.get('run_id')}
    rows = []
    for folder in sorted((ROOT / 'local_runtime/runs').glob('*-v4-source-interface-r5-*')):
        if not folder.is_dir() or folder.is_symlink():
            continue
        manifest = _load(folder / 'manifest.json', sources, warnings)
        row = linked.get(folder.name)
        rows.append({'run_id': folder.name, 'manifest_path': _ref(folder / 'manifest.json'),
                     'manifest_state': manifest.get('state') if manifest else None,
                     'manifest_ssh_exit_code': manifest.get('ssh_exit_code') if manifest else None,
                     'execution_path': row['execution_path'] if row else None,
                     'association': 'EXPLICIT_RUN_ID' if row else 'NOT_YET_BOUND_IN_EXECUTION_RECORD',
                     'archive': row['archive'] if row else _tar_metadata(folder / 'results.tar', warnings),
                     'budget_rule': 'Raw folders are inventoried separately and do not create extra counted calls'})
    return rows


def _disk_usage(warnings):
    roots = [RT / 'source-interface-r5', RT / 'source-field-audit-r2', STATE]
    roots += list((ROOT / 'local_runtime/runs').glob('*-v4-source-interface-r5-*'))
    roots += list((RT / 'transport-probe/operations').glob('r5-*'))
    roots += list((RT / 'transport-probe/inputs').glob('r5-*'))
    seen, total, count, inventory = set(), 0, 0, []
    for base in sorted(roots):
        size, files = 0, 0
        if not base.is_dir() or base.is_symlink():
            continue
        for directory, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [n for n in dirs if not (Path(directory) / n).is_symlink()]
            for name in names:
                path = Path(directory) / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    size += path.stat().st_size
                    files += 1
                except OSError as exc:
                    warnings.append({'path': _ref(path), 'error': str(exc)})
        inventory.append({'path': _ref(base), 'file_count': files, 'logical_file_bytes': size})
        count += files
        total += size
    return {'local_logical_file_bytes': total, 'local_allocated_disk_bytes': None,
            'file_count': count, 'roots': inventory, 'local_volume_free_bytes': shutil.disk_usage(ROOT).free,
            'definition': 'Snapshot sum of actual regular-file st_size, unique resolved paths. Includes all separate copies and prior reports; excludes symlinks. Physical cluster/compression allocation is not measured.',
            'snapshot_before_this_report_write': True}


def _sum_known(rows, field):
    values = [row[field] for row in rows if _number(row.get(field)) is not None]
    return {'known_seconds': math.fsum(values), 'measured_rows': len(values), 'missing_rows': len(rows) - len(values)}


def _archive_totals(rows):
    values = [(r.get('archive') or {}).get('archive_bytes') for r in rows]
    known = [v for v in values if type(v) is int and v >= 0]
    return {'known_archive_bytes': sum(known), 'archive_files_present': len(known),
            'missing_archives': len(values) - len(known)}


def _fine_update(launches, operations):
    candidates = [r for r in launches if r.get('identity') == ['A0', 1, 'fine'] and r['budget_category'] != 'historical']
    result = {'status': 'AWAITING_COMPLETED_FINE_A0', 'measurements': None,
              'fine_remaining_solver_estimate_s': None, 'fine_remaining_postprocess_estimate_s': None,
              'fine_total_schedule_estimate_s': None,
              'limitation': 'No fine cost promise. A0 is a source-free control; its solver cost does not determine nonlinear A1/A5 cost. Node count and sample extraction may remain unavailable.'}
    complete = [r for r in candidates if r['execution_status'] == 'COMPLETED']
    if not complete:
        return result
    # Preserve all attempts elsewhere, choosing the earliest completed raw run
    # only as the deterministic calibration observation, not a successful seed.
    run = sorted(complete, key=lambda r: (r.get('started_utc') or '', r['label']))[0]
    samples = [r for r in operations if r.get('source_run_id') == run['run_id'] and r['status'] == 'COMPLETED'
               and isinstance(r.get('completed_receipt_frame_count'), int) and 0 < r['completed_receipt_frame_count'] <= 10]
    sample = sorted(samples, key=lambda r: (r.get('finished_utc') or '', r['label']))[0] if samples else None
    archive = run.get('archive') or {}
    count = sample['completed_receipt_frame_count'] if sample else None
    per_frame = sample['elapsed_s'] / count if sample and sample['elapsed_s'] is not None else None
    frames = archive.get('gstep_frame_count')
    measurements = {'run_id': run['run_id'], 'mesh_node_count': run['mesh_node_count'],
                    'solver_wallclock_s': run['solver_wallclock_s'], 'launch_elapsed_s': run['launch_elapsed_s'],
                    'archive_bytes': archive.get('archive_bytes'), 'gstep_frame_count': frames,
                    'scientific_status': run['scientific_status'],
                    'sample_operation_label': sample['label'] if sample else None,
                    'sample_frames': count, 'sample_operation_elapsed_s': sample['elapsed_s'] if sample else None,
                    'sample_operation_seconds_per_frame': per_frame,
                    'one_full_frame_set_linear_operation_estimate_s': frames * per_frame if per_frame is not None and frames else None,
                    'extrapolation_definition': 'A descriptive linear extrapolation including fixed transfer/archive overhead; not native SVisual scaling validation or an execution-time guarantee'}
    ready = all(measurements.get(k) is not None for k in ('mesh_node_count', 'solver_wallclock_s', 'archive_bytes', 'sample_operation_seconds_per_frame'))
    result.update(status='OBSERVATIONS_READY_FOR_ROOT_SCHEDULING_REVIEW' if ready else 'PARTIAL_FINE_A0_MEASUREMENTS', measurements=measurements)
    return result


def _markdown(report):
    b = report['budget']
    lines = ['# 二维接口调用与资源预算快照', '', '生成时间：' + report['created_utc'], '',
             f"累计记录 {b['global_attempts_consumed']}/{b['maximum_global_attempts']}；历史 {b['historical_records_found']}/5，本轮 {b['new_attempts_consumed']}/21（primary {b['primary_attempts_consumed']}/17，reserve {b['reserve_attempts_consumed']}/4）。",
             '', '执行记录一经创建即计一次；本报告不恢复、重试、提交或清理任何作业。', '',
             '| 调用 | 分类 | 执行状态 | 已存审计状态 | 求解器墙钟 s | 启动至归档 s | 动态帧 | 节点数 |',
             '|---|---|---|---|---:|---:|---:|---:|']
    def value(v):
        return 'null' if v is None else f'{v:.3f}' if isinstance(v, float) else str(v)
    for row in report['launches']:
        archive = row.get('archive') or {}
        lines.append('| ' + ' | '.join(value(v) for v in (row['label'], row['budget_category'], row['execution_status'], row['scientific_status'], row['solver_wallclock_s'], row['launch_elapsed_s'], archive.get('gstep_frame_count'), row['mesh_node_count'])) + ' |')
    timing = report['wallclock']
    lines += ['', f"已知求解器墙钟合计 {timing['solver']['known_seconds']:.3f} s，缺失 {timing['solver']['missing_rows']} 项。",
              f"本轮后处理操作耗时合计 {timing['postprocessing']['known_seconds']:.3f} s，缺失 {timing['postprocessing']['missing_rows']} 项；包含传输和归档，不能视为纯 SVisual 时间。",
              '', f"本轮本地文件实测逻辑字节：{report['storage']['local_logical_file_bytes']}；物理盘簇占用未测。统计包含已保留副本，不是清理建议。",
              '', '细网格 A0 更新状态：' + report['fine_a0_schedule_update']['status'] + '。缺失量保留 null，未承诺 fine A1/A5 成本。',
              '', 'tar 仅扫描成员元信息，未读取 TDR 内容、未解压、未重新计算归档内容哈希。帧文件数不等于通过完整性审计；节点数不能由文件大小推算。',
              '', '执行完成、后处理完成和已存科学审计状态分别呈现；本报告没有重新执行科学验收。']
    if report['warnings']:
        lines += ['', '读取限制或异常：'] + ['- ' + json.dumps(w, ensure_ascii=False) for w in report['warnings']]
    return '\n'.join(lines) + '\n'


def generate(output=None):
    """Return a snapshot and write budget.json/md to one fresh timestamped folder."""
    sources, warnings = {}, []
    c = _load(CAMPAIGN, sources, warnings)
    if not c or c.get('schema') != 'dram-see-v4-interface-completion-campaign-r1':
        raise ValueError('Frozen campaign missing or invalid')
    campaign_sha = sources[_ref(CAMPAIGN)]['sha256']
    historical = {item['path']: item['sha256'] for item in c['historical_records']}
    audits = _audit_index(sources, warnings)
    launches, unreadable = [], []
    paths = sorted(RT.glob('source-interface-*/launches/*/execution.json'))
    for path in paths:
        data = _load(path, sources, warnings)
        if data is None:
            unreadable.append(_ref(path))
            continue
        is_old = _ref(path) in historical
        if is_old and sources[_ref(path)]['sha256'] != historical[_ref(path)]:
            warnings.append({'path': _ref(path), 'error': 'Frozen historical execution hash changed'})
        launches.append(_launch_row(path, data, is_old, campaign_sha, audits, sources, warnings))
    found = {_ref(p) for p in paths}
    missing = sorted(set(historical) - found)
    if missing:
        warnings.append({'error': 'Historical launch records missing; frozen calls remain conservatively counted', 'paths': missing})
    new_paths = found - set(historical)
    primary = sum(r['budget_category'] == 'primary' for r in launches)
    reserve = sum(r['budget_category'] == 'reserve' for r in launches)
    global_used = len(found | set(historical))
    unregistered = sum(r['budget_category'] == 'unregistered' for r in launches)
    unknown_categories = unregistered + len(set(unreadable) - set(historical))
    attempted_roles = {r['role_id'] for r in launches if r['budget_category'] == 'primary' and r.get('role_id')}
    budget = {'historical_records_found': len(found & set(historical)),
              'historical_attempts_at_freeze': c['historical_attempts_at_freeze'],
              'global_attempts_consumed': global_used, 'maximum_global_attempts': c['maximum_global_attempts'],
              'global_attempts_remaining': max(0, c['maximum_global_attempts'] - global_used),
              'new_attempts_consumed': len(new_paths), 'maximum_new_attempts': c['maximum_new_attempts'],
              'new_attempts_remaining': max(0, c['maximum_new_attempts'] - len(new_paths)),
              'primary_attempts_consumed': primary, 'primary_role_limit': c['primary_roles'],
              'reserve_attempts_consumed': reserve, 'reserve_attempt_limit': c['reserve_attempts'],
              'reserve_attempts_remaining': max(0, c['reserve_attempts'] - reserve) if not unknown_categories else None,
              'unregistered_new_attempts': unregistered,
              'unclassified_new_attempts': unknown_categories,
              'primary_roles_not_attempted': [r['role_id'] for r in c['roles'] if r['role_id'] not in attempted_roles],
              'unreadable_execution_records': unreadable, 'missing_historical_records': missing,
              'counting_rule': 'Every execution record counts once, including failed/unknown; missing frozen historical calls remain consumed; operations never increase TCAD count'}
    ops = _operations(sources, warnings)
    raw_r5 = _raw_r5_runs(launches, sources, warnings)
    stamp = datetime.now(timezone.utc)
    directory = Path(output).resolve() if output is not None else OUTPUT_ROOT / (stamp.strftime('%Y%m%dT%H%M%S.%fZ-') + uuid.uuid4().hex[:8])
    if directory.parent.resolve() != OUTPUT_ROOT.resolve() or not re.fullmatch(STAMP_PATTERN, directory.name) or directory.exists():
        raise ValueError('Report output must be a new timestamped direct child of the campaign budget directory')
    report = {'schema': 'dram-see-v4-interface-completion-budget-r1', 'created_utc': stamp.isoformat(),
              'read_only_inputs': True, 'new_solver_invocations': 0, 'campaign_sha256': campaign_sha,
              'reporter_sha256': _sha(Path(__file__).read_bytes()), 'output_directory': _ref(directory),
              'budget': budget, 'launches': launches, 'r5_raw_run_inventory': raw_r5, 'postprocessing_operations': ops,
              'execution_status_counts': dict(Counter(r['execution_status'] for r in launches)),
              'scientific_status_counts': dict(Counter(r['scientific_status'] for r in launches)),
              'wallclock': {'solver': _sum_known(launches, 'solver_wallclock_s'),
                            'launch_including_overheads': _sum_known(launches, 'launch_elapsed_s'),
                            'new_round_solver': _sum_known([r for r in launches if r['budget_category'] != 'historical'], 'solver_wallclock_s'),
                            'postprocessing': _sum_known(ops, 'elapsed_s')},
              'storage': {**_disk_usage(warnings),
                          'historical_solver_archives': _archive_totals([r for r in launches if r['budget_category'] == 'historical']),
                          'new_r5_solver_archives': _archive_totals(raw_r5),
                          'new_round_postprocessing_archives': _archive_totals(ops)},
              'fine_a0_schedule_update': _fine_update(launches, ops),
              'sources': sources, 'warnings': warnings,
              'limits': ['Local snapshot only; no remote/process inspection.',
                         'Saved audit outcomes are reported, not revalidated or promoted.',
                         'Tar metadata inventory is not archive-content hash validation or accepted-frame validation.',
                         'Disk usage is logical file bytes, not allocated cluster space.',
                         'No fine runtime or completion-date promise; unavailable measurements remain null.']}
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / 'budget.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    with (directory / 'budget.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(_markdown(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = generate(args.output)
    print(json.dumps({k: result[k] for k in ('output_directory', 'budget', 'fine_a0_schedule_update')}, ensure_ascii=False, indent=2))
