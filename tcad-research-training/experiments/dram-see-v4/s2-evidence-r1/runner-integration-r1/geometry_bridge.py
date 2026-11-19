"""Data-only bridge for the original runner; no process or network launcher.

This source may be embedded before scripts/tcad.py's main function.  All added
names are prefixed to avoid changing the original runner's globals. Python 3.6.
"""
import argparse as GEOMETRY_argparse
import hashlib as GEOMETRY_hashlib
import importlib.util as GEOMETRY_importlib
import json as GEOMETRY_json
import math as GEOMETRY_math
import re as GEOMETRY_re
import sys as GEOMETRY_sys
import tarfile as GEOMETRY_tarfile
from pathlib import Path as GEOMETRY_Path, PurePosixPath as GEOMETRY_PurePosixPath


GEOMETRY_EXITS = {
    'step-001-sde-exit-code.txt': 'sde-exit-code.txt',
    'step-002-snmesh-exit-code.txt': 'mesh-exit-code.txt',
    'step-003-svisual-exit-code.txt': 'svisual-exit-code.txt',
}
GEOMETRY_CHECKS = ('materials', 'contacts', 'doping', 'units')
GEOMETRY_RAW_REQUIRED = (
    'material-measurements.csv', 'contact-measurements.csv', 'doping-measurements.csv',
    'sde-contact-measurements.csv', 'sde-contact-probes.csv', 'sde-material-probes.csv',
    'geometry-inventory.csv', 'mesh-identity.csv', 'geometry-status.json',
    'sde-geometry-status.txt', 'observation-context.json',
    'sde-exit-code.txt', 'mesh-exit-code.txt', 'svisual-exit-code.txt',
)
GEOMETRY_PRODUCE_INPUTS = {
    'project.json', 'geometry_bridge.py', 'evaluate.py', 'measurement-plan.json',
    'geometry-with-measurements.scm', 'measure-geometry.tcl', 'geometry-contract.json',
    'mesh_resource_guard.py', 'resource-policy.json', 'device.cmd',
    'geometry-policy.released.json', 'geometry-authorization.json',
    'geometry-budget-reservation.json',
}
GEOMETRY_STEPS = (
    ('sde', ['-e', '-l', 'geometry-with-measurements.scm']),
    ('snmesh', ['--threads', '1', '--max_threads', '1', 'cell']),
    ('svisual', ['--threads', '1', '--max_threads', '1', '-b', '-tcl', '-script', 'measure-geometry.tcl']),
    ('sdevice', ['device.cmd']),
)


def geometry_require(ok, message):
    if not ok:
        raise ValueError(message)


def geometry_digest(path):
    path = GEOMETRY_Path(path)
    geometry_require(path.is_file() and not path.is_symlink(), 'Missing or linked file: ' + str(path))
    with path.open('rb') as stream:
        return geometry_stream_digest(stream)


def geometry_stream_digest(stream):
    value = GEOMETRY_hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''):
        value.update(block)
    return value.hexdigest()


def geometry_hash_value(value, label):
    geometry_require(isinstance(value, str) and GEOMETRY_re.fullmatch(r'[a-f0-9]{64}', value) is not None,
                     'Invalid SHA-256: ' + label)
    return value


def geometry_new_budget_id(value):
    geometry_require(isinstance(value, str) and 's2' in GEOMETRY_re.split(r'[^a-z0-9]+', value.lower())
                     and 'nuclear' not in value.lower(), 'Reservation must belong to a distinct new S2 ledger')
    return value


def geometry_json(path):
    path = GEOMETRY_Path(path)
    geometry_require(path.is_file() and not path.is_symlink(), 'Missing or linked JSON: ' + str(path))
    return geometry_json_bytes(path.read_bytes(), str(path))


def geometry_json_bytes(raw, label):
    value = GEOMETRY_json.loads(raw.decode('utf-8'))
    geometry_require(isinstance(value, dict), 'Expected JSON object: ' + label)
    return value


def geometry_relative(name):
    geometry_require(isinstance(name, str), 'Evidence filename must be a string')
    parts = name.split('/')
    geometry_require((len(parts) == 1 or (len(parts) == 2 and parts[0] == 'geometry-producer-bindings'))
                     and all(GEOMETRY_re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part) for part in parts),
                     'Unsafe evidence filename: ' + name)
    return name


def geometry_path(folder, name):
    name = geometry_relative(name)
    folder = GEOMETRY_Path(folder)
    path = folder.joinpath(*name.split('/'))
    geometry_require(not path.is_symlink() and not path.parent.is_symlink(), 'Linked evidence path: ' + name)
    return path


def geometry_write(path, raw):
    path = GEOMETRY_Path(path)
    geometry_require(not path.is_symlink() and not path.parent.is_symlink(), 'Refusing linked output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def geometry_write_json(path, value):
    geometry_write(path, (GEOMETRY_json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def geometry_exit_value(raw, label):
    geometry_require(GEOMETRY_re.fullmatch(rb'[0-9]+\s*', raw) is not None, 'Unknown original exit: ' + label)
    value = int(raw)
    geometry_require(0 <= value <= 255, 'Out-of-range original exit: ' + label)
    return value


def geometry_record_exit(folder, source_name, canonical_name):
    """Copy one explicit raw exit without normalization, including nonzero exits."""
    geometry_require(GEOMETRY_EXITS.get(source_name) == canonical_name, 'Unapproved original exit mapping')
    source = geometry_path(folder, source_name)
    geometry_digest(source)
    raw = source.read_bytes()
    value = geometry_exit_value(raw, source_name)
    geometry_write(geometry_path(folder, canonical_name), raw)
    return value


def geometry_exit_sources(folder, complete=True):
    result = {}
    for source, canonical in GEOMETRY_EXITS.items():
        if not complete and canonical == 'svisual-exit-code.txt':
            continue
        source_path, canonical_path = geometry_path(folder, source), geometry_path(folder, canonical)
        source_sha, canonical_sha = geometry_digest(source_path), geometry_digest(canonical_path)
        geometry_require(source_sha == canonical_sha and source_path.read_bytes() == canonical_path.read_bytes(),
                         'Canonical exit differs from original step: ' + canonical)
        value = geometry_exit_value(source_path.read_bytes(), source)
        geometry_require(value == 0, 'Original native exit is nonzero: ' + source)
        result[canonical] = dict(source=source, source_sha256=source_sha,
                                 canonical_sha256=canonical_sha, observed_exit_code=value)
    return result


def geometry_authority(project, name, digest, role):
    path = geometry_path(project, name)
    geometry_require(geometry_digest(path) == geometry_hash_value(digest, name), 'Authority hash differs')
    authority = geometry_json(path)
    geometry_require(authority.get('synthetic') is False and authority.get('explicit_native_authorization') is True,
                     'Native authorization is absent')
    roles = authority.get('role_ids')
    geometry_require(isinstance(roles, list) and all(isinstance(x, str) for x in roles)
                     and len(roles) == len(set(roles)) and role in roles, 'Authorization role differs')
    return authority


def geometry_input_hashes(project):
    manifest = geometry_json(geometry_path(project, 'input-manifest.json'))
    hashes = manifest.get('files_sha256')
    geometry_require(isinstance(hashes, dict) and hashes, 'Input manifest has no payload hashes')
    geometry_require(not {'input-manifest.json', 'execution-release.json', 'geometry-release.json'} & set(hashes),
                     'Release/input manifest contains a cyclic hash dependency')
    for name, digest in hashes.items():
        geometry_relative(name)
        geometry_hash_value(digest, name)
    return hashes


def geometry_resource_precheck(project, role):
    """Mirror the original guard's approval/forecast prerequisites, not live data."""
    policy = geometry_json(geometry_path(project, 'resource-policy.json'))
    geometry_require(policy.get('schema') == 's2-resource-policy-r1' and policy.get('approved') is True
                     and policy.get('execution_enabled') is True and policy.get('release_id')
                     and policy.get('role') == role, 'Resource policy is not released for this role')
    for key in ('forecast_remote_peak_bytes', 'forecast_peak_memory_bytes'):
        value = policy.get(key)
        geometry_require(type(value) in (int, float) and GEOMETRY_math.isfinite(value) and value > 0,
                         'Unpriced resource forecast: ' + key)
    for key in ('forecast_evidence_sha256', 'scheduler_preflight_sha256'):
        geometry_hash_value(policy.get(key), key)


def geometry_tar_members(archive):
    members = {}
    for member in archive.getmembers():
        name = member.name
        while name.startswith('./'):
            name = name[2:]
        if name in ('', '.') and member.isdir():
            continue
        path = GEOMETRY_PurePosixPath(name)
        geometry_require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name,
                         'Unsafe source archive member')
        normalized = path.as_posix()
        geometry_require(normalized not in members and (member.isfile() or member.isdir()),
                         'Duplicate or nonregular source archive member: ' + normalized)
        members[normalized] = member
    return members


def geometry_tar_bytes(archive, members, name):
    geometry_require(name in members and members[name].isfile(), 'Source archive is missing ' + name)
    with archive.extractfile(members[name]) as stream:
        return stream.read()


def geometry_source_bundle(project, cfg, execution, synthetic_fixture=False):
    """Verify an already accepted D3 source; return only immutable copy metadata."""
    geometry_require(type(synthetic_fixture) is bool, 'Synthetic fixture mode must be explicit Boolean')
    project = GEOMETRY_Path(project)
    source_value, acceptance_value = cfg.get('source_run_directory'), cfg.get('acceptance_file')
    geometry_require(isinstance(source_value, str) and isinstance(acceptance_value, str), 'D3 source/acceptance is absent')
    source, acceptance_path = GEOMETRY_Path(source_value), GEOMETRY_Path(acceptance_value)
    geometry_require(source.is_absolute() and acceptance_path.is_absolute() and source.is_dir() and not source.is_symlink(),
                     'D3 source/acceptance must use explicit original absolute paths')
    if synthetic_fixture:
        for folder in (project, source):
            marker = folder / 'SYNTHETIC_NOT_NATIVE'
            geometry_require('UNIT_FIXTURE_NOT_NATIVE' in str(folder.resolve()) and marker.is_file()
                             and not marker.is_symlink(), 'Synthetic reuse fixture is not isolated')
        geometry_require(geometry_json(project / 'project.json').get('s2_geometry') == cfg
                         and cfg.get('schema') == 's2-runner-geometry-integration-r1'
                         and cfg.get('mode') == 'reuse' and cfg.get('synthetic') is True
                         and cfg.get('execution_enabled') is False
                         and cfg.get('role_id') in ('B1-A0-main-b0', 'B1-A0-main-b1')
                         and execution.get('synthetic') is True and execution.get('execution_enabled') is False,
                         'Synthetic reuse must explicitly disable execution')
    else:
        for folder in (project, source):
            geometry_require('UNIT_FIXTURE_NOT_NATIVE' not in str(folder.resolve())
                             and not (folder / 'SYNTHETIC_NOT_NATIVE').exists(), 'Synthetic reuse cannot enter native mode')
        geometry_require(source.name == cfg['producer_run_id'], 'D3 original directory identity differs')
    expected_origin = 'synthetic_fixture' if synthetic_fixture else 'native_pipeline'
    acceptance_sha = geometry_digest(acceptance_path)
    geometry_require(execution.get('d3_acceptance_sha256') == acceptance_sha, 'A0 release does not bind D3 acceptance')
    acceptance = geometry_json(acceptance_path)
    geometry_require(acceptance.get('schema') == 's2-d3-geometry-reuse-acceptance-r1'
                     and acceptance.get('status') == 'ACCEPTED' and acceptance.get('synthetic') is synthetic_fixture
                     and (not synthetic_fixture or acceptance.get('origin') == expected_origin),
                     'D3 reuse acceptance origin differs')
    manifest_path, archive_path = source / 'manifest.json', source / 'results.tar'
    manifest_sha, archive_sha = geometry_digest(manifest_path), geometry_digest(archive_path)
    manifest = geometry_json(manifest_path)
    producer = cfg['producer_run_id']
    geometry_require(manifest.get('state') == 'COLLECTED' and manifest.get('origin') == expected_origin
                     and manifest.get('synthetic') is synthetic_fixture and manifest.get('run_id') == producer,
                     'D3 source manifest origin/completion differs')
    for key in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code'):
        geometry_require(type(manifest.get(key)) is int and manifest[key] == 0, 'D3 source exit is unknown/nonzero: ' + key)
    tool_exits = manifest.get('tool_exit_codes')
    geometry_require(isinstance(tool_exits, dict) and tool_exits
                     and all(type(v) is int and v == 0 for v in tool_exits.values()), 'D3 native step exits are incomplete')
    geometry_require(manifest.get('results_sha256') == archive_sha, 'D3 archive differs from its original manifest')
    if 'archive_sha256' in manifest:
        geometry_require(manifest['archive_sha256'] == archive_sha, 'Conflicting D3 archive hashes')
    for key, value in (('source_run_id', producer), ('source_manifest_sha256', manifest_sha), ('source_archive_sha256', archive_sha)):
        geometry_require(acceptance.get(key) == value, 'D3 acceptance binding differs: ' + key)
    geometry_require(execution.get('d3_source_manifest_sha256') == manifest_sha
                     and execution.get('d3_source_archive_sha256') == archive_sha
                     and execution.get('d3_producer_run_id') == producer, 'A0 release source binding differs')
    with GEOMETRY_tarfile.open(str(archive_path), 'r:*') as archive:
        members = geometry_tar_members(archive)
        if synthetic_fixture:
            source_spec = geometry_json_bytes(geometry_tar_bytes(archive, members, 'project.json'), 'D3 fixture project')
            source_cfg = source_spec.get('s2_geometry')
            geometry_require(isinstance(source_cfg, dict)
                             and source_cfg.get('schema') == 's2-runner-geometry-integration-r1'
                             and source_cfg.get('mode') == 'produce' and source_cfg.get('synthetic') is True
                             and source_cfg.get('execution_enabled') is False and source_cfg.get('role_id') == 'B1-D3'
                             and source_cfg.get('run_id') == producer and source_cfg.get('producer_run_id') == producer,
                             'D3 synthetic source cfg must explicitly disable execution')
        report_raw = geometry_tar_bytes(archive, members, 'geometry-validation.json')
        report = geometry_json_bytes(report_raw, 'D3 geometry report')
        report_sha = GEOMETRY_hashlib.sha256(report_raw).hexdigest()
        geometry_require(report.get('schema') == 's2-native-geometry-validation-r1'
                         and report.get('origin') == expected_origin and report.get('synthetic') is synthetic_fixture
                         and (not synthetic_fixture or report.get('native_qualified') is False)
                         and report.get('passed') is True and report.get('role_id') == 'B1-D3'
                         and report.get('producer_run_id') == producer
                         and all(report.get('checks', {}).get(k) is True for k in GEOMETRY_CHECKS),
                         'D3 geometry report origin/checks differ')
        hashes = report.get('evidence_sha256')
        geometry_require(isinstance(hashes, dict) and set(GEOMETRY_RAW_REQUIRED) <= set(hashes), 'D3 raw geometry evidence is incomplete')
        geometry_require('geometry-validation.json' not in hashes, 'D3 report has a cyclic evidence dependency')
        producer_binding = 'input-manifest.json' if synthetic_fixture else 'execution-release.json'
        geometry_require('geometry-producer-bindings/' + producer_binding in hashes
                         and 'geometry-exit-sources.json' in hashes, 'D3 report lacks producer/exit binding evidence')
        exports = dict(hashes)
        exports['geometry-validation.json'] = report_sha
        for name in ('cell_msh.tdr', 'cell_msh.log'):
            geometry_require(name in members and members[name].isfile(), 'D3 source is missing ' + name)
            with archive.extractfile(members[name]) as stream:
                exports[name] = geometry_stream_digest(stream)
        reserved = {'project.json', 'input-manifest.json', 'execution-release.json', 'geometry-release.json',
                    'geometry-authorization.json', 'geometry-policy.released.json', 'geometry-budget-reservation.json'}
        for name, digest in exports.items():
            geometry_relative(name)
            geometry_require(name not in reserved, 'D3 root authority would overwrite current-role input')
            geometry_hash_value(digest, name)
            geometry_require(name in members and members[name].isfile() and members[name].size > 0, 'Empty/missing D3 evidence: ' + name)
            with archive.extractfile(members[name]) as stream:
                geometry_require(geometry_stream_digest(stream) == digest, 'D3 evidence hash differs: ' + name)
        context = geometry_json_bytes(geometry_tar_bytes(archive, members, 'observation-context.json'), 'D3 context')
        mesh_sha = exports['cell_msh.tdr']
        geometry_require(context.get('schema') == 's2-geometry-observation-context-r1'
                         and context.get('origin') == expected_origin and context.get('synthetic') is synthetic_fixture
                         and context.get('producer_run_id') == producer and context.get('role_id') == 'B1-D3'
                         and context.get('mesh_sha256') == mesh_sha == report.get('mesh_sha256')
                         and context.get('dimension') == 3, 'D3 mesh/context/producer identity differs')
        for name in GEOMETRY_EXITS.values():
            geometry_require(geometry_exit_value(geometry_tar_bytes(archive, members, name), name) == 0
                             and context.get('raw_exit_sha256', {}).get(name) == exports[name], 'D3 original exit/context differs')
        geometry_require(geometry_exit_value(geometry_tar_bytes(archive, members, 'exit-code.txt'), 'D3 wrapper') == 0,
                         'D3 wrapper exit is nonzero')
        geometry_require(acceptance.get('mesh_sha256') == execution.get('d3_mesh_sha256') == mesh_sha
                         and acceptance.get('geometry_validation_sha256') == report_sha, 'D3 acceptance mesh/report binding differs')
    return dict(archive=archive_path, archive_sha256=archive_sha, exports=exports)


def geometry_admit(project, spec, runner_sha256):
    """Reject review candidates before connection/native work; return the original cfg."""
    if 's2_geometry' not in spec:
        return None
    project = GEOMETRY_Path(project)
    geometry_require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve())
                     and not (project / 'SYNTHETIC_NOT_NATIVE').exists(), 'Synthetic fixtures cannot enter native admission')
    cfg = spec['s2_geometry']
    geometry_require(isinstance(cfg, dict) and cfg.get('schema') == 's2-runner-geometry-integration-r1', 'Unknown geometry integration contract')
    geometry_require(cfg.get('execution_enabled') is True and cfg.get('mode') in ('produce', 'reuse'), 'Geometry integration is not released')
    mode, role, run_id, producer = cfg['mode'], cfg.get('role_id'), cfg.get('run_id'), cfg.get('producer_run_id')
    geometry_require(spec.get('execution_enabled') is True and spec.get('role') == role
                     and type(spec.get('native_threads')) is int and spec['native_threads'] == 1
                     and type(spec.get('native_cores')) is int and spec['native_cores'] == 1,
                     'Project is not released for this role and single core/thread')
    geometry_require(isinstance(run_id, str) and GEOMETRY_re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id), 'Exact published run ID is absent')
    geometry_require(isinstance(producer, str) and producer, 'Original producer run ID is absent')
    geometry_require(role in (('B1-D2', 'B1-D3') if mode == 'produce' else ('B1-A0-main-b0', 'B1-A0-main-b1')), 'Role/mode differs')
    geometry_require(mode != 'produce' or producer == run_id, 'Produce role must own its geometry run')
    geometry_require(geometry_json(geometry_path(project, 'project.json')) == spec, 'Project spec differs from frozen project.json')
    execution = geometry_json(geometry_path(project, 'execution-release.json'))
    geometry_require(execution.get('schema') == 's2-execution-release-r1' and execution.get('status') == 'RELEASED'
                     and execution.get('execution_enabled') is True and execution.get('explicit_native_authorization') is True
                     and execution.get('synthetic') is False, 'Native execution release is absent')
    geometry_require(execution.get('scheduler') == 'root' and type(execution.get('threads')) is int and execution['threads'] == 1
                     and type(execution.get('cpu_count')) is int and execution['cpu_count'] == 1, 'Root/single-thread/single-core release differs')
    geometry_require(execution.get('role_id') == role and execution.get('run_id') == run_id, 'Execution role/run identity differs')
    geometry_require(execution.get('expected_runner_sha256') == geometry_hash_value(runner_sha256, 'runner'), 'Original runner version is not released')
    geometry_require(execution.get('input_manifest_sha256') == geometry_digest(project / 'input-manifest.json')
                     and execution.get('geometry_bridge_sha256') == geometry_digest(project / 'geometry_bridge.py'), 'Input/helper release binding differs')
    geometry_new_budget_id(execution.get('budget_id'))
    geometry_require(execution.get('budget_reservation_id'), 'Execution budget binding is absent')
    geometry_hash_value(execution.get('budget_ledger_sha256'), 'execution budget ledger')
    authority_name = geometry_relative(execution.get('authorization_evidence_file'))
    geometry_authority(project, authority_name, execution.get('authorization_evidence_sha256'), role)
    geometry_resource_precheck(project, role)
    hashes = geometry_input_hashes(project)
    required = {'project.json', 'geometry_bridge.py', 'mesh_resource_guard.py', 'resource-policy.json', 'device.cmd', authority_name}
    imports = {}
    if mode == 'produce':
        required |= GEOMETRY_PRODUCE_INPUTS
        geometry_require([(s.get('tool'), s.get('args')) for s in spec.get('steps', [])] == list(GEOMETRY_STEPS), 'Produce native step sequence differs')
        release = geometry_json(project / 'geometry-release.json')
        geometry_require(execution.get('geometry_release_sha256') == geometry_digest(project / 'geometry-release.json'), 'Execution release does not bind geometry release')
        geometry_require(release.get('schema') == 's2-geometry-producer-release-r1' and release.get('status') == 'RELEASED'
                         and release.get('execution_enabled') is True and release.get('explicit_native_authorization') is True
                         and release.get('synthetic') is False and release.get('role_id') == role
                         and release.get('producer_run_id') == producer, 'Geometry producer is not released')
        for key, name in (('input_manifest_sha256', 'input-manifest.json'), ('plan_sha256', 'measurement-plan.json'),
                          ('evaluator_sha256', 'evaluate.py'), ('policy_sha256', 'geometry-policy.released.json'),
                          ('authorization_sha256', 'geometry-authorization.json'), ('budget_reservation_sha256', 'geometry-budget-reservation.json')):
            geometry_require(release.get(key) == geometry_digest(project / name), 'Geometry release binding differs: ' + key)
        plan, policy = geometry_json(project / 'measurement-plan.json'), geometry_json(project / 'geometry-policy.released.json')
        geometry_require(plan.get('schema') == 's2-geometry-measurement-plan-r1' and plan.get('role_id') == role
                         and plan.get('dimension') == (2 if role == 'B1-D2' else 3)
                         and isinstance(plan.get('comparison_policy'), dict) and plan['comparison_policy'], 'Plan role/dimension/policy differs')
        geometry_require(plan.get('geometry_contract_sha256') == geometry_digest(project / 'geometry-contract.json'), 'Plan geometry contract differs')
        geometry_require(policy.get('approved') is True and policy.get('status') == 'RELEASED', 'Geometry comparison policy is not released')
        for key, value in plan.get('comparison_policy', {}).items():
            if key not in ('approved', 'status'):
                geometry_require(policy.get(key) == value, 'Released geometry policy changes comparison: ' + key)
        geometry_authority(project, 'geometry-authorization.json', release.get('authorization_sha256'), role)
        budget = geometry_json(project / 'geometry-budget-reservation.json')
        budget_id = geometry_new_budget_id(budget.get('budget_id'))
        geometry_require(budget.get('schema') == 's2-geometry-budget-reservation-r1' and budget.get('status') == 'RESERVED'
                         and budget.get('synthetic') is False and budget.get('category') == 'native_geometry_extractions'
                         and type(budget.get('units')) is int and budget['units'] == 1
                         and budget.get('role_id') == role and budget.get('run_id') == run_id
                         and budget_id == release.get('budget_id') == execution.get('budget_id')
                         and budget.get('budget_ledger_sha256') == execution.get('budget_ledger_sha256')
                         and isinstance(budget.get('budget_reservation_id'), str) and budget['budget_reservation_id']
                         and budget['budget_reservation_id'] == release.get('budget_reservation_id')
                         and budget['budget_reservation_id'] != execution.get('budget_reservation_id'), 'Geometry reservation scope differs')
    else:
        geometry_require([(s.get('tool'), s.get('args')) for s in spec.get('steps', [])] == [('sdevice', ['device.cmd'])], 'Reuse role must not build/measure geometry')
        imports = geometry_source_bundle(project, cfg, execution, synthetic_fixture=False)['exports']
        required |= set(imports)
    geometry_require(required <= set(hashes), 'Mandatory execution payload is absent from input manifest')
    for name, digest in hashes.items():
        path = geometry_path(project, name)
        if not path.exists() and name in imports:
            geometry_require(imports[name] == digest, 'Deferred D3 import hash differs: ' + name)
            continue
        geometry_require(geometry_digest(path) == digest, 'Execution input changed: ' + name)
        if name in imports:
            geometry_require(imports[name] == digest, 'D3 import/current input conflict: ' + name)
    return cfg


def geometry_stage_reuse(project, cfg, synthetic_fixture=False):
    """Copy accepted D3 bytes before A0 input freeze; never measure or alter D3."""
    project = GEOMETRY_Path(project)
    geometry_require(cfg.get('mode') == 'reuse', 'Only A0 reuse can stage D3 evidence')
    bundle = geometry_source_bundle(project, cfg, geometry_json(project / 'execution-release.json'),
                                    synthetic_fixture=synthetic_fixture)
    hashes = geometry_input_hashes(project)
    for name, digest in bundle['exports'].items():
        geometry_require(hashes.get(name) == digest, 'D3 import not frozen in current input manifest: ' + name)
        target = geometry_path(project, name)
        if target.exists():
            geometry_require(geometry_digest(target) == digest, 'Existing D3 import conflicts: ' + name)
    with GEOMETRY_tarfile.open(str(bundle['archive']), 'r:*') as archive:
        members = geometry_tar_members(archive)
        for name, digest in sorted(bundle['exports'].items()):
            target = geometry_path(project, name)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(members[name]) as source, target.open('xb') as destination:
                for block in iter(lambda: source.read(1048576), b''):
                    destination.write(block)
            geometry_require(geometry_digest(target) == digest, 'Imported D3 bytes differ: ' + name)
    geometry_require(geometry_digest(bundle['archive']) == bundle['archive_sha256'], 'D3 archive changed during import')
    for name, digest in hashes.items():
        geometry_require(geometry_digest(geometry_path(project, name)) == digest, 'Incomplete/changed input after D3 import: ' + name)
    return cfg


def geometry_runtime(folder, run_id):
    folder = GEOMETRY_Path(folder)
    geometry_require(folder.resolve().name == run_id, 'Original runtime directory does not match released run ID')
    spec = geometry_json(folder / 'project.json')
    execution = geometry_json(folder / 'execution-release.json')
    cfg = geometry_admit(folder, spec, execution.get('expected_runner_sha256'))
    geometry_require(cfg and cfg['mode'] == 'produce' and cfg['run_id'] == run_id, 'Runtime geometry identity differs')
    return cfg


def geometry_fixture_runtime(folder, run_id):
    """Internal software-test gate; it cannot approve native work or reuse."""
    folder = GEOMETRY_Path(folder)
    marker = folder / 'SYNTHETIC_NOT_NATIVE'
    geometry_require('UNIT_FIXTURE_NOT_NATIVE' in str(folder.resolve()) and marker.is_file() and not marker.is_symlink(),
                     'Synthetic bridge fixture is not isolated')
    spec = geometry_json(folder / 'project.json')
    cfg = spec.get('s2_geometry')
    geometry_require(isinstance(cfg, dict) and cfg.get('schema') == 's2-runner-geometry-integration-r1'
                     and cfg.get('mode') == 'produce' and cfg.get('synthetic') is True
                     and cfg.get('execution_enabled') is False and cfg.get('run_id') == run_id
                     and cfg.get('producer_run_id') == run_id and cfg.get('role_id') in ('B1-D2', 'B1-D3'),
                     'Synthetic fixture must explicitly disable execution')
    hashes = geometry_input_hashes(folder)
    required = {'project.json', 'geometry_bridge.py', 'evaluate.py', 'measurement-plan.json',
                'geometry-with-measurements.scm', 'measure-geometry.tcl', 'geometry-contract.json'}
    geometry_require(required <= set(hashes), 'Synthetic fixture payload is not frozen')
    for name, digest in hashes.items():
        geometry_require(geometry_digest(geometry_path(folder, name)) == digest, 'Synthetic fixture input changed: ' + name)
    for name in ('execution-release.json', 'geometry-release.json'):
        path = folder / name
        if path.exists():
            release = geometry_json(path)
            geometry_require(release.get('execution_enabled') is False and release.get('synthetic') is True,
                             'Synthetic fixture must not fabricate a native release')
    return cfg


def geometry_tcl_word(value):
    value = str(value)
    for old, new in (('\\', '\\\\'), ('"', '\\"'), ('$', '\\$'), ('[', '\\['), (']', '\\]'), ('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t')):
        value = value.replace(old, new)
    return '"' + value + '"'


def geometry_prepare(folder, run_id):
    folder = GEOMETRY_Path(folder)
    geometry_runtime(folder, run_id)
    geometry_exit_sources(folder, complete=False)
    mesh = geometry_path(folder, 'cell_msh.tdr')
    descriptor = ' '.join(geometry_tcl_word(v) for v in (str(mesh.resolve()), geometry_digest(mesh), run_id)) + '\n'
    geometry_write(folder / 'mesh-input.tcldata', descriptor.encode('utf-8'))
    return 0


def geometry_finalize(folder, run_id, synthetic_fixture=False):
    """Preserve the original evaluator result and add provenance, never thresholds."""
    folder = GEOMETRY_Path(folder)
    try:
        geometry_require(type(synthetic_fixture) is bool, 'Synthetic fixture mode must be explicit Boolean')
        cfg = geometry_fixture_runtime(folder, run_id) if synthetic_fixture else geometry_runtime(folder, run_id)
        geometry_require(not (folder / 'geometry-validation.json').exists()
                         and not (folder / 'geometry-evaluation').exists(), 'Prior geometry evaluation must be preserved')
        sources = geometry_exit_sources(folder)
        plan = geometry_json(folder / 'measurement-plan.json')
        context = dict(schema='s2-geometry-observation-context-r1', synthetic=synthetic_fixture,
                       origin='synthetic_fixture' if synthetic_fixture else 'native_pipeline',
                       role_id=cfg['role_id'], dimension=plan['dimension'], producer_run_id=run_id,
                       plan_sha256=geometry_digest(folder / 'measurement-plan.json'),
                       geometry_contract_sha256=plan['geometry_contract_sha256'],
                       sde_deck_sha256=geometry_digest(folder / 'geometry-with-measurements.scm'),
                       svisual_script_sha256=geometry_digest(folder / 'measure-geometry.tcl'),
                       mesh_sha256=geometry_digest(folder / 'cell_msh.tdr'),
                       raw_exit_sha256={name: row['canonical_sha256'] for name, row in sources.items()})
        for name, row in sources.items():
            context[name.replace('-exit-code.txt', '_exit_code')] = row['observed_exit_code']
        geometry_write_json(folder / 'observation-context.json', context)
        geometry_write_json(folder / 'geometry-exit-sources.json', dict(schema='s2-geometry-exit-sources-r1', sources=sources))
        module_spec = GEOMETRY_importlib.spec_from_file_location('geometry_original_evaluator', str(folder / 'evaluate.py'))
        evaluator = GEOMETRY_importlib.module_from_spec(module_spec)
        module_spec.loader.exec_module(evaluator)
        report = evaluator.evaluate(folder / 'measurement-plan.json', folder, folder / 'geometry-evaluation',
                                    synthetic=synthetic_fixture,
                                    release_path=None if synthetic_fixture else folder / 'geometry-release.json')
        if synthetic_fixture:
            binding_names = {'input-manifest.json'}
        else:
            execution = geometry_json(folder / 'execution-release.json')
            binding_names = {'execution-release.json', 'geometry-release.json', 'input-manifest.json',
                             'geometry-policy.released.json', 'geometry-authorization.json', 'geometry-budget-reservation.json',
                             execution['authorization_evidence_file']}
        bindings = {}
        for name in sorted(binding_names):
            geometry_require('/' not in geometry_relative(name), 'Producer authority must use a simple root filename')
            destination = 'geometry-producer-bindings/' + name
            geometry_write(geometry_path(folder, destination), geometry_path(folder, name).read_bytes())
            bindings[destination] = geometry_digest(geometry_path(folder, destination))
        additions = dict(bindings)
        additions['geometry-exit-sources.json'] = geometry_digest(folder / 'geometry-exit-sources.json')
        for row in sources.values():
            additions[row['source']] = row['source_sha256']
        geometry_require(not set(additions) & set(report['evidence_sha256']), 'Producer binding name conflicts with evaluator evidence')
        report['evidence_sha256'].update(additions)
        report['original_exit_sources'] = sources
        report['producer_release_bindings_sha256'] = bindings
        report['integration_schema'] = 's2-runner-geometry-integration-r1'
        geometry_require(report.get('synthetic') is synthetic_fixture and report.get('native_qualified') is False
                         and report.get('origin') == ('synthetic_fixture' if synthetic_fixture else 'native_pipeline'),
                         'Evaluator origin/qualification differs from bridge mode')
        geometry_write_json(folder / 'geometry-validation.json', report)
        return 0 if report.get('passed') is True else 2
    except (ValueError, KeyError, TypeError, OSError, GEOMETRY_tarfile.TarError) as exc:
        print('Geometry integration stopped: ' + str(exc), file=GEOMETRY_sys.stderr)
        return 2


def geometry_main():
    parser = GEOMETRY_argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    item = sub.add_parser('record-exit')
    item.add_argument('--folder', required=True)
    item.add_argument('--source', required=True)
    item.add_argument('--canonical', required=True)
    for command in ('prepare', 'finalize'):
        item = sub.add_parser(command)
        item.add_argument('--folder', required=True)
        item.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'record-exit':
            geometry_record_exit(args.folder, args.source, args.canonical)
            return 0  # Successful byte capture is not a successful native exit.
        if args.command == 'prepare':
            return geometry_prepare(args.folder, args.run_id)
        if args.command == 'finalize':
            return geometry_finalize(args.folder, args.run_id)
        parser.error('choose record-exit, prepare, or finalize')
    except (ValueError, KeyError, TypeError, OSError, GEOMETRY_tarfile.TarError) as exc:
        print('Geometry integration stopped: ' + str(exc), file=GEOMETRY_sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(geometry_main())
