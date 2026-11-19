"""Current DRAM SEE v4 data bridge; no process, network or solver launcher.

The original runner retains scheduling and locks. Current user authorization is
bound to an exact run and immutable inputs; there are no budget/release gates.
Python 3.6 compatible for the existing guest.
"""
import argparse as GEOMETRY_argparse
import csv as GEOMETRY_csv
import hashlib as GEOMETRY_hashlib
import importlib.util as GEOMETRY_importlib
import json as GEOMETRY_json
import math as GEOMETRY_math
import re as GEOMETRY_re
import sys as GEOMETRY_sys
import tarfile as GEOMETRY_tarfile
from pathlib import Path as GEOMETRY_Path, PurePosixPath as GEOMETRY_PurePosixPath
from types import SimpleNamespace as GEOMETRY_Namespace

GEOMETRY_SCHEMA = 'dram-see-v4-continuous-geometry-r2'
GEOMETRY_HDF5_BACKEND = 'native_hdf5_v16_export'
GEOMETRY_HDF5_CONTEXT = 'dram-see-v4-hdf5-geometry-observation-context-r1'
GEOMETRY_ACTIVE_CONTEXT = 'dram-see-v4-hdf5-geometry-observation-context-r2'
GEOMETRY_ACTIVE_REPRESENTATION = 'tdr-hdf5-v16'
GEOMETRY_EXITS = {
    'step-001-sde-exit-code.txt': 'sde-exit-code.txt',
    'step-002-snmesh-exit-code.txt': 'mesh-exit-code.txt',
    'step-003-tdx-exit-code.txt': 'tdx-metadata-exit-code.txt',
    'step-004-tdx-exit-code.txt': 'tdx-converter-exit-code.txt',
    'step-005-svisual-exit-code.txt': 'svisual-exit-code.txt',
}
GEOMETRY_CHECKS = ('materials', 'contacts', 'doping', 'units')
GEOMETRY_PROTON_PAYLOAD = ('sources.dat','heavyion.physics.inc','source.par','source-contract.json','fragments.json',
                          'heavyion.plot.inc','heavyion.currentplot.inc')
GEOMETRY_PROTON_ALIASES = {'geometry-contract.json':'transport-geometry-contract.json',
                          'model-input.json':'transport-model-input.json','request.json':'transport-request.json'}
GEOMETRY_ALPHA_V2_INPUTS = ('model.proposed.json','geometry-contract.json','source-request.json','alpha-astar-silicon.csv',
    'source-origins.json','alpha-profile.csv','heavyion.physics.inc','source.par','source-contract.json')
GEOMETRY_MESH_POLICY_FILES = ('mesh-policy.json','mesh-policy-definition.json','mesh-policy-assumptions.md')
GEOMETRY_RAW_REQUIRED = (
    'material-measurements.csv', 'contact-measurements.csv', 'doping-measurements.csv',
    'sde-contact-measurements.csv', 'sde-contact-probes.csv', 'sde-material-probes.csv',
    'geometry-inventory.csv', 'mesh-identity.csv', 'geometry-status.json',
    'sde-geometry-status.txt', 'observation-context.json',
    'sde-exit-code.txt', 'mesh-exit-code.txt', 'svisual-exit-code.txt',
    'tdx-metadata-exit-code.txt', 'tdx-converter-exit-code.txt',
    'tdr-region-datasets.csv', 'tdr-geometry.csv', 'tdr-topology-identity.csv', 'tdr-region-status.json',
    'mesh-observed.grd', 'mesh-observed.dat', 'tdx-source-before.json', 'tdx-source-after.json',
)
GEOMETRY_HDF5_RAW_REQUIRED = tuple(n for n in GEOMETRY_RAW_REQUIRED if n not in (
    'tdx-converter-exit-code.txt','mesh-observed.grd','mesh-observed.dat','tdx-source-before.json','tdx-source-after.json')) + (
    'current-mesh-before.json','current-mesh-after.json','tdr-hash-provider.csv','geometry-hash-provider.csv')
GEOMETRY_STEPS = (
    ('sde', ['-e', '-l', 'geometry-with-measurements.scm']),
    ('snmesh', ['--threads', '1', '--max_threads', '1', 'cell']),
    ('tdx', ['-tcl', 'observe_tdr_topology.tcl', 'cell_msh.tdr']),
    ('tdx', ['-dd', '-M', '0', '-S', '0', 'cell_msh.tdr', 'mesh-observed']),
    ('svisual', ['--threads', '1', '--max_threads', '1', '-b', '-tcl', '-script', 'measure-geometry.tcl']),
    ('sdevice', ['device.cmd']),
)


def geometry_require(ok, message):
    if not ok:
        raise ValueError(message)


def geometry_stream_digest(stream):
    value = GEOMETRY_hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''):
        value.update(block)
    return value.hexdigest()


def geometry_digest(path):
    path = GEOMETRY_Path(path)
    geometry_require(path.is_file() and not path.is_symlink(), 'Missing or linked file: ' + str(path))
    with path.open('rb') as stream:
        return geometry_stream_digest(stream)


def geometry_hash_value(value, label):
    geometry_require(isinstance(value, str) and GEOMETRY_re.fullmatch(r'[a-f0-9]{64}', value) is not None,
                     'Invalid SHA-256: ' + label)
    return value


def geometry_json_bytes(raw, label):
    value = GEOMETRY_json.loads(raw.decode('utf-8'))
    geometry_require(isinstance(value, dict), 'Expected JSON object: ' + label)
    return value


def geometry_json(path):
    path = GEOMETRY_Path(path)
    geometry_digest(path)
    return geometry_json_bytes(path.read_bytes(), str(path))


GEOMETRY_PROTON_CONTROL_PATHS = ('proton-control-inputs/control-input-index.json', 'proton-control-inputs/half/event-0/control-contract.json', 'proton-control-inputs/half/event-0/input-only-linear-reference.json', 'proton-control-inputs/half/event-0/parent-child-map.json', 'proton-control-inputs/half/event-0/projection-context.dat', 'proton-control-inputs/half/event-0/projection-sources3d.dat', 'proton-control-inputs/half/event-0/source-terms.json', 'proton-control-inputs/half/event-1/control-contract.json', 'proton-control-inputs/half/event-1/input-only-linear-reference.json', 'proton-control-inputs/half/event-1/parent-child-map.json', 'proton-control-inputs/half/event-1/projection-context.dat', 'proton-control-inputs/half/event-1/projection-sources3d.dat', 'proton-control-inputs/half/event-1/source-terms.json', 'proton-control-inputs/half/event-2/control-contract.json', 'proton-control-inputs/half/event-2/input-only-linear-reference.json', 'proton-control-inputs/half/event-2/parent-child-map.json', 'proton-control-inputs/half/event-2/projection-context.dat', 'proton-control-inputs/half/event-2/projection-sources3d.dat', 'proton-control-inputs/half/event-2/source-terms.json', 'proton-control-inputs/half/event-3/control-contract.json', 'proton-control-inputs/half/event-3/input-only-linear-reference.json', 'proton-control-inputs/half/event-3/parent-child-map.json', 'proton-control-inputs/half/event-3/projection-context.dat', 'proton-control-inputs/half/event-3/projection-sources3d.dat', 'proton-control-inputs/half/event-3/source-terms.json', 'proton-control-inputs/parent-bindings.json', 'proton-control-inputs/parents/batch/adapter-manifest.json', 'proton-control-inputs/parents/batch/event-0-g3-source.json', 'proton-control-inputs/parents/batch/event-1-g3-source.json', 'proton-control-inputs/parents/batch/event-2-g3-source.json', 'proton-control-inputs/parents/batch/event-3-g3-source.json', 'proton-control-inputs/parents/batch/native-batch-binding.json', 'proton-control-inputs/parents/batch/replay-request.json', 'proton-control-inputs/parents/operation-timing.json', 'proton-control-inputs/parents/source-inputs/all-event-source-inputs.json', 'proton-control-inputs/parents/source-inputs/candidate-input-manifest.json', 'proton-control-inputs/parents/source-inputs/event-0/full-original-event-source.json', 'proton-control-inputs/parents/source-inputs/event-0/input-only-projection-reference.json', 'proton-control-inputs/parents/source-inputs/event-0/projection-context.dat', 'proton-control-inputs/parents/source-inputs/event-0/projection-sources3d.dat', 'proton-control-inputs/parents/source-inputs/event-1/full-original-event-source.json', 'proton-control-inputs/parents/source-inputs/event-1/input-only-projection-reference.json', 'proton-control-inputs/parents/source-inputs/event-1/projection-context.dat', 'proton-control-inputs/parents/source-inputs/event-1/projection-sources3d.dat', 'proton-control-inputs/parents/source-inputs/event-2/full-original-event-source.json', 'proton-control-inputs/parents/source-inputs/event-2/input-only-projection-reference.json', 'proton-control-inputs/parents/source-inputs/event-2/projection-context.dat', 'proton-control-inputs/parents/source-inputs/event-2/projection-sources3d.dat', 'proton-control-inputs/parents/source-inputs/event-3/full-original-event-source.json', 'proton-control-inputs/parents/source-inputs/event-3/input-only-projection-reference.json', 'proton-control-inputs/parents/source-inputs/event-3/projection-context.dat', 'proton-control-inputs/parents/source-inputs/event-3/projection-sources3d.dat', 'proton-control-inputs/parents/source-inputs/input-hashes.sha256', 'proton-control-inputs/proton-control-input-manifest.json', 'proton-control-inputs/split/event-0/control-contract.json', 'proton-control-inputs/split/event-0/input-only-linear-reference.json', 'proton-control-inputs/split/event-0/parent-child-map.json', 'proton-control-inputs/split/event-0/projection-context.dat', 'proton-control-inputs/split/event-0/projection-sources3d.dat', 'proton-control-inputs/split/event-0/source-terms.json', 'proton-control-inputs/split/event-1/control-contract.json', 'proton-control-inputs/split/event-1/input-only-linear-reference.json', 'proton-control-inputs/split/event-1/parent-child-map.json', 'proton-control-inputs/split/event-1/projection-context.dat', 'proton-control-inputs/split/event-1/projection-sources3d.dat', 'proton-control-inputs/split/event-1/source-terms.json', 'proton-control-inputs/split/event-2/control-contract.json', 'proton-control-inputs/split/event-2/input-only-linear-reference.json', 'proton-control-inputs/split/event-2/parent-child-map.json', 'proton-control-inputs/split/event-2/projection-context.dat', 'proton-control-inputs/split/event-2/projection-sources3d.dat', 'proton-control-inputs/split/event-2/source-terms.json', 'proton-control-inputs/split/event-3/control-contract.json', 'proton-control-inputs/split/event-3/input-only-linear-reference.json', 'proton-control-inputs/split/event-3/parent-child-map.json', 'proton-control-inputs/split/event-3/projection-context.dat', 'proton-control-inputs/split/event-3/projection-sources3d.dat', 'proton-control-inputs/split/event-3/source-terms.json', 'proton-control-inputs/zero/event-0/control-contract.json', 'proton-control-inputs/zero/event-0/input-only-linear-reference.json', 'proton-control-inputs/zero/event-0/parent-child-map.json', 'proton-control-inputs/zero/event-0/projection-context.dat', 'proton-control-inputs/zero/event-0/projection-sources3d.dat', 'proton-control-inputs/zero/event-0/source-terms.json', 'proton-control-inputs/zero/event-1/control-contract.json', 'proton-control-inputs/zero/event-1/input-only-linear-reference.json', 'proton-control-inputs/zero/event-1/parent-child-map.json', 'proton-control-inputs/zero/event-1/projection-context.dat', 'proton-control-inputs/zero/event-1/projection-sources3d.dat', 'proton-control-inputs/zero/event-1/source-terms.json', 'proton-control-inputs/zero/event-2/control-contract.json', 'proton-control-inputs/zero/event-2/input-only-linear-reference.json', 'proton-control-inputs/zero/event-2/parent-child-map.json', 'proton-control-inputs/zero/event-2/projection-context.dat', 'proton-control-inputs/zero/event-2/projection-sources3d.dat', 'proton-control-inputs/zero/event-2/source-terms.json', 'proton-control-inputs/zero/event-3/control-contract.json', 'proton-control-inputs/zero/event-3/input-only-linear-reference.json', 'proton-control-inputs/zero/event-3/parent-child-map.json', 'proton-control-inputs/zero/event-3/projection-context.dat', 'proton-control-inputs/zero/event-3/projection-sources3d.dat', 'proton-control-inputs/zero/event-3/source-terms.json')


GEOMETRY_ALPHA_RESTART_PATHS = (
    'reference-alpha-bindings/manifest.json',
    'reference-alpha-bindings/results.tar',
    'reference-alpha-bindings/inputs.tar',
)


GEOMETRY_A0_RESTART_PATHS = (
    'reference-a0-bindings/manifest.json',
    'reference-a0-bindings/results.tar',
    'reference-a0-bindings/inputs.tar',
    'restart-state/source_window_0000_access_des.tdr',
    'restart-state/source_window_0000_circuit_des.sav',
)


def geometry_relative(name):
    geometry_require(isinstance(name, str), 'Evidence filename must be a string')
    parts = name.split('/')
    geometry_require(((len(parts)==2 and parts[0]=='proton-multicondition-controls' and
                        parts[1] in ('proton-control-input-manifest.json','parent-bindings.json','control-input-index.json')) or
                     (len(parts)==3 and parts[0]=='proton-multicondition-controls' and
                        parts[1]=='parents' and parts[2]=='operation-timing.json') or
                     (len(parts)==4 and parts[0]=='proton-multicondition-controls' and
                        parts[1] in ('zero','half','split') and
                        GEOMETRY_re.fullmatch(r'event-(?:0|[1-9][0-9]*)',parts[2]) is not None and
                        parts[3] in ('projection-sources3d.dat','projection-context.dat','source-terms.json',
                                     'parent-child-map.json','input-only-linear-reference.json','control-contract.json')) or
                     (len(parts)==2 and parts[0]=='proton-multicondition-batch' and
                        (parts[1] in ('adapter-manifest.json','native-batch-binding.json','replay-request.json') or
                         GEOMETRY_re.fullmatch(r'event-(?:0|[1-9][0-9]*)-g3-source\.json',parts[1]) is not None)) or
                     (len(parts)==2 and parts[0]=='proton-multicondition-source' and
                        parts[1] in ('all-event-source-inputs.json','candidate-input-manifest.json','input-hashes.sha256')) or
                     (len(parts)==3 and parts[0]=='proton-multicondition-source' and
                        GEOMETRY_re.fullmatch(r'event-(?:0|[1-9][0-9]*)',parts[1]) is not None and
                        parts[2] in ('projection-sources3d.dat','projection-context.dat',
                                     'input-only-projection-reference.json','full-original-event-source.json')) or
                     name in GEOMETRY_ALPHA_RESTART_PATHS or name in GEOMETRY_A0_RESTART_PATHS or name in GEOMETRY_PROTON_CONTROL_PATHS or name in ('proton-reference-inputs/model.proposed.json', 'proton-reference-inputs/geometry-contract.json', 'proton-reference-inputs/dimensional-contract.json', 'proton-multicondition-reference-inputs/model.proposed.json', 'proton-multicondition-reference-inputs/geometry-contract.json', 'proton-multicondition-reference-inputs/dimensional-contract.json') or len(parts) == 1 or (len(parts) == 2 and parts[0] in ('geometry-producer-bindings','mesh-source-bindings',
                     'metadata-source-bindings','tdr-conversion-bindings','hdf5-export-bindings','hdf5-export',
                     'dc-source-bindings','dc-completed-bindings','d2-producer-bindings','d2-base-bindings','d2-refinement-base',
                     'alpha-projection','matched-a0-bindings','operation-template','operation-selection',
                     'proton-transport-bindings','proton-build-bindings','proton-pmi-bindings','proton-batch',
                     'proton-source-inputs','proton-activation','proton-implementations')) or
                     (len(parts)==2 and parts[0]=='alpha-control-projection' and parts[1] in (
                         'native-control-representation.json','control-request.json','energy-source-provenance.json','fragment-000-profile.csv','fragment-001-profile.csv','heavyion.physics.inc','input-output-manifest.json','projection-ledger.json','segments.json','source-contract.json','source.par')) or
                     (len(parts)==3 and ((parts[0]=='proton-source-inputs' and parts[1] in ('event-0','event-1','event-2','event-3')) or
                     (parts[0]=='proton-activation' and parts[1]=='original') or
                     (parts[0]=='alpha-control-projection' and parts[1]=='base-projection' and parts[2] in (
                         'alpha-astar-silicon.csv','alpha-profile-2d-native.csv','alpha-profile-3d-reference.csv','dimensional-contract.json','energy-source-provenance.json','geometry-contract.json','heavyion.physics.inc','input-origins.json','input-output-manifest.json','model.proposed.json','projection-ledger.json','projection-request.json','source-contract.json','source.par')))))
                     and all(GEOMETRY_re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part) for part in parts),
                     'Unsafe evidence filename: ' + name)
    return name


def geometry_path(folder, name):
    path = GEOMETRY_Path(folder).joinpath(*geometry_relative(name).split('/'))
    geometry_require(not path.is_symlink() and all(not GEOMETRY_Path(folder).joinpath(*name.split('/')[:i]).is_symlink()
                     for i in range(1,len(name.split('/')))), 'Linked evidence path: ' + name)
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
    """Preserve the actual original exit bytes, including a failure."""
    geometry_require(GEOMETRY_EXITS.get(source_name) == canonical_name, 'Unexpected original exit mapping')
    source = geometry_path(folder, source_name)
    geometry_digest(source)
    raw = source.read_bytes()
    value = geometry_exit_value(raw, source_name)
    geometry_write(geometry_path(folder, canonical_name), raw)
    return value


def geometry_exit_sources(folder, complete=True):
    result = {}
    inherited = (GEOMETRY_Path(folder)/'mesh-source-binding.json').exists()
    binding = geometry_json(GEOMETRY_Path(folder)/'mesh-source-binding.json') if inherited else None
    metadata = geometry_json(GEOMETRY_Path(folder)/'metadata-source-binding.json') if (GEOMETRY_Path(folder)/'metadata-source-binding.json').exists() else None
    for source, canonical in GEOMETRY_EXITS.items():
        if metadata and canonical=='tdx-converter-exit-code.txt':
            continue  # Original r10 converter137 remains solely in its original namespace.
        if not complete and canonical not in ('sde-exit-code.txt', 'mesh-exit-code.txt'):
            continue
        inherited_prefix = inherited and canonical in ('sde-exit-code.txt','mesh-exit-code.txt')
        if inherited_prefix:
            geometry_require(not geometry_path(folder,source).exists(), 'Inherited step cannot have a current raw exit')
            source = 'mesh-source-bindings/'+source
        inherited_metadata=metadata and canonical=='tdx-metadata-exit-code.txt'
        if inherited_metadata:
            geometry_require(not geometry_path(folder,source).exists(),'Inherited metadata cannot have a current raw exit')
            source='metadata-source-bindings/'+source
        source_path, canonical_path = geometry_path(folder, source), geometry_path(folder, canonical)
        source_sha, canonical_sha = geometry_digest(source_path), geometry_digest(canonical_path)
        geometry_require(source_sha == canonical_sha and source_path.read_bytes() == canonical_path.read_bytes(),
                         'Canonical exit differs from original step: ' + canonical)
        value = geometry_exit_value(source_path.read_bytes(), source)
        geometry_require(value == 0, 'Original native exit is nonzero: ' + source)
        result[canonical] = dict(source=source, source_sha256=source_sha,
                                 canonical_sha256=canonical_sha, observed_exit_code=value)
        if inherited_prefix:
            result[canonical].update(source_kind='inherited_original_native_prefix',
                source_run_id=binding['source_run_id'],source_archive_sha256=binding['source_archive_sha256'],
                source_manifest_sha256=binding['source_manifest_sha256'])
        if inherited_metadata:
            node=metadata['nodes']['metadata']
            result[canonical].update(source_kind='inherited_original_native_metadata',source_run_id=node['id'],
                source_archive_sha256=node['archive_sha256'],source_manifest_sha256=node['receipt_sha256'])
    return result


def geometry_mesh_module():
    """Only this fixed sibling implementation is executable, never an archive path."""
    path = GEOMETRY_Path(__file__).with_name('mesh_continuation.py')
    module_spec = GEOMETRY_importlib.spec_from_file_location('geometry_mesh_continuation',str(path))
    module = GEOMETRY_importlib.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def geometry_stage_mesh_reuse(project, cfg):
    geometry_require(cfg.get('mode') == 'produce_from_mesh', 'Wrong mesh-prefix staging mode')
    return geometry_mesh_module().stage(project,cfg)


def geometry_metadata_module():
    path=GEOMETRY_Path(__file__).with_name('metadata_continuation.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_metadata_continuation',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_stage_metadata_reuse(project,cfg):
    geometry_require(cfg.get('mode')=='produce_from_metadata','Wrong metadata staging mode')
    return geometry_metadata_module().stage(project,cfg)


def geometry_dc_module():
    path=GEOMETRY_Path(__file__).with_name('dc_continuation.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_dc_continuation',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_stage_dc_reuse(project,cfg):
    geometry_require(cfg.get('mode')=='produce_from_geometry','Wrong DC-only staging mode')
    return geometry_dc_module().stage(project,cfg)


def geometry_2d_module():
    path=GEOMETRY_Path(__file__).with_name('two_dimensional.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_two_dimensional',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_alpha_2d_module():
    path=GEOMETRY_Path(__file__).with_name('alpha_native_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_native_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_operating_voltage_module():
    path=GEOMETRY_Path(__file__).with_name('operating_voltage_dc_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_operating_voltage_dc_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_operating_2d_module():
    path=GEOMETRY_Path(__file__).with_name('operating_dc_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_operating_dc_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_operating_alpha_module():
    path=GEOMETRY_Path(__file__).with_name('operating_alpha_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_operating_alpha_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_operating_transient_module():
    path=GEOMETRY_Path(__file__).with_name('operating_transient_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_operating_transient_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_parameterized_alpha_control_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_control_runtime_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_alpha_control_runtime_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value



def geometry_proton_multicondition_controls_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_multicondition_controls_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='531c43d83c258ba91d16b8383102f56c4d2fddeddd095e5292c698566c8ea4bf',
        'fixed proton multicondition control runtime changed')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_proton_multicondition_controls_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);exec(compile(raw,str(path),'exec'),value.__dict__);return value


def geometry_proton_multicondition_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_multicondition_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_proton_multicondition_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value

def geometry_proton_multicondition_refinement_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_multicondition_refinement_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_proton_multicondition_refinement_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_proton_refinement_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_refinement_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_proton_refinement_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module);return module


def geometry_parameterized_proton_controls_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_controls_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_proton_controls_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module);return module


def geometry_parameterized_proton_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_proton_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_proton_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_alpha_partition_control_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_partition_controls_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_partition_controls_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_alpha_partition_refinement_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_partition_refinement_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_partition_refinement_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_alpha_multicondition_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_multicondition_2d.py')
    raw=path.read_bytes()
    if path.is_symlink() or GEOMETRY_hashlib.sha256(raw).hexdigest()!='6e651db56c2c44307f129f9fc9be24b97ee51aec8205ee5bda0ebd16e582c01d':
        raise ValueError('fixed alpha multicondition runtime changed')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_multicondition_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),value.__dict__)
    return value



def geometry_alpha_multicondition_control_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_multicondition_controls_2d.py')
    raw=path.read_bytes()
    if path.is_symlink() or GEOMETRY_hashlib.sha256(raw).hexdigest()!='7d7a29569ecaf453bfc1c06674bf107b6c01bf7d11ad2200039041163567c2e6':
        raise ValueError('fixed alpha multicondition runtime changed')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_multicondition_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),value.__dict__)
    return value


def geometry_alpha_native_partition_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_native_partition_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_alpha_native_partition_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_parameterized_alpha_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_alpha_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_alpha_2d',str(path))
    value=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def geometry_parameterized_operating_module():
    path=GEOMETRY_Path(__file__).with_name('parameterized_operating_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_parameterized_operating_2d',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def geometry_validate_hash_provider(raw):
    rows = list(GEOMETRY_csv.DictReader(raw.decode('utf-8').splitlines()))
    expected = dict(schema='dram-see-v4-tdx-sha256-provider-r1',
        source_path='/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/tcllib1.16/sha1/sha256.tcl',
        source_sha256='107ef278e9752467718d0cfaf7dac868f31b7c91ff80fbc4700a07eac939dee1',
        source_bytes='24595',package_name='sha256',package_version='1.0.3',backend='tcl',safe_interpreter='1',
        unsafe_commands_visible='',package_unknown_empty='1',known_vectors_verified='empty abc',chunk_bytes='65536',
        maximum_supported_file_bytes='536870911',algorithm_representation_limit_not_resource_quota='1')
    geometry_require(len(rows)==1 and set(rows[0])==set(expected)|{'tcl_patchlevel'}
                     and all(rows[0][k]==v for k,v in expected.items())
                     and GEOMETRY_re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',rows[0]['tcl_patchlevel']) is not None,
                     'TDX in-process hash provider evidence differs')
    return rows[0]


def geometry_input_hashes(project):
    manifest = geometry_json(geometry_path(project, 'input-manifest.json'))
    geometry_require(manifest.get('schema') == 'dram-see-v4-continuous-inputs-r1', 'Wrong input manifest')
    hashes = manifest.get('files_sha256')
    geometry_require(isinstance(hashes, dict) and hashes, 'Input manifest has no payload hashes')
    geometry_require(not {'input-manifest.json', 'execution-context.json'} & set(hashes), 'Cyclic input manifest')
    for name, digest in hashes.items():
        geometry_relative(name)
        geometry_hash_value(digest, name)
    return hashes


def geometry_context(project, cfg, runner_sha256):
    context = geometry_json(geometry_path(project, 'execution-context.json'))
    geometry_require(context.get('schema') == 'dram-see-v4-continuous-run-context-r1'
                     and context.get('synthetic') is False, 'Current native execution context absent')
    for key in ('run_id', 'role_id', 'producer_run_id'):
        geometry_require(context.get(key) == cfg.get(key), 'Current context identity differs: ' + key)
    geometry_require(context.get('expected_runner_sha256') == geometry_hash_value(runner_sha256, 'runner'),
                     'Original runner version differs')
    geometry_require(context.get('input_manifest_sha256') == geometry_digest(project / 'input-manifest.json'),
                     'Current input manifest differs')
    authority = geometry_json(project / 'task-authorization.json')
    geometry_require(context.get('authorization_sha256') == geometry_digest(project / 'task-authorization.json')
                     and authority.get('schema') == 'dram-see-v4-current-user-authorization-r1'
                     and authority.get('synthetic') is False
                     and authority.get('source') == 'current_user_instruction'
                     and cfg['role_id'] in authority.get('role_ids', [])
                     and isinstance(authority.get('instruction'), str) and authority['instruction'].strip(),
                     'Current user authorization binding differs')
    return context


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


def geometry_validate_mesh_policy_payload(files, cfg, require_sde=False):
    """Validate the original frozen policy; never regenerate an old producer's mesh."""
    description=geometry_json_bytes(files['geometry-contract.json'],'mesh physical geometry')
    present=set(GEOMETRY_MESH_POLICY_FILES)&set(files)
    if not present:
        geometry_require('policy' not in description['mesh'] and 'mesh_policy_id' not in cfg
                         and 'mesh_policy_sha256' not in cfg,'Declared mesh policy is missing its original files')
        return None
    geometry_require(present==set(GEOMETRY_MESH_POLICY_FILES),'Original mesh policy is incomplete')
    policy=geometry_json_bytes(files['mesh-policy.json'],'mesh policy')
    definition=geometry_json_bytes(files['mesh-policy-definition.json'],'mesh definition')
    digest=lambda raw:GEOMETRY_hashlib.sha256(raw).hexdigest()
    identity=description['mesh'].get('policy',{})
    geometry_require(policy.get('schema')=='dram-see-v4-instantiated-mesh-policy-r1'
                     and policy.get('policy_id')==definition.get('policy_id')==identity.get('policy_id')
                     ==cfg.get('mesh_policy_id') in ('dram-see-v4-gradient-mesh-r1','dram-see-v4-gradient-mesh-r2','dram-see-v4-gradient-mesh-r3','dram-see-v4-gradient-mesh-r4','dram-see-v4-gradient-mesh-r5','dram-see-v4-gradient-mesh-r6')
                     and policy.get('dimension')==description['dimension']==3 and policy.get('length_unit')=='um'
                     and policy.get('scale')==description['mesh']['scale'] in (1,.5)
                     and policy.get('numerical_variant')==('mesh' if policy['scale']==.5 else 'main'),
                     'Original mesh policy/version/dimension differs')
    physical={key:value for key,value in description.items() if key!='mesh'}
    physical_raw=GEOMETRY_json.dumps(physical,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    geometry_require(policy.get('model_sha256')==digest(files['model.proposed.json'])
                     and policy.get('physical_geometry_sha256')==digest(physical_raw)
                     and policy.get('definition_sha256')==digest(files['mesh-policy-definition.json'])
                     and policy.get('assumptions_sha256')==digest(files['mesh-policy-assumptions.md'])
                     and identity.get('contract_file')=='mesh-policy.json'
                     and identity.get('contract_sha256')==cfg.get('mesh_policy_sha256')==digest(files['mesh-policy.json']),
                     'Mesh policy original model/geometry/definition bytes differ')
    geometry_require(description['mesh']['windows']==policy.get('volume_refinements')
                     and description['mesh'].get('interface_refinements')==policy.get('interface_refinements')
                     and 'interface' not in description['mesh']
                     and policy.get('physical_parameters_changed') is False
                     and policy.get('measurement_criteria_changed') is False
                     and policy.get('native_accuracy_qualified') is False
                     and policy.get('source_charge_or_response_convergence_qualified') is False,
                     'Actual mesh placements or qualification declaration differ')
    if policy['policy_id']=='dram-see-v4-gradient-mesh-r5':
        geometry_validate_r5_partitions(files,description,policy,definition)
    if policy['policy_id']=='dram-see-v4-gradient-mesh-r6':
        geometry_validate_r6_partitions(files,description,policy,definition)
    if policy['policy_id'] in ('dram-see-v4-gradient-mesh-r3','dram-see-v4-gradient-mesh-r4','dram-see-v4-gradient-mesh-r5','dram-see-v4-gradient-mesh-r6'):
        native=policy.get('delaunizer',{})
        geometry_require(native==definition.get('delaunizer')==description['mesh'].get('delaunizer')
                         and native.get('explicit_parameters')=={'maxPoints':2147483647}
                         and native.get('finite_integer_not_unlimited') is True
                         and native.get('not_project_resource_budget') is True
                         and native.get('not_accuracy_acceptance') is True
                         and native.get('scales_with_h2') is False,
                         'Original finite Delaunizer parameter contract differs')
    if require_sde:
        text=files['geometry-with-measurements.scm'].decode('utf-8')
        start='; BEGIN EXPLICIT MESH POLICY '+policy['policy_id']
        end='; END EXPLICIT MESH POLICY '+policy['policy_id']+'\n'
        geometry_require(text.count(start)==1 and text.count(end)==1,'Actual mesh block is absent or duplicated')
        block=start+text.split(start,1)[1].split(end,1)[0]+end
        geometry_require(digest(block.encode('utf-8'))==policy.get('sde_mesh_block_sha256'),
                         'Actual SDE mesh block differs from the original declared policy')
        if policy['policy_id'] in ('dram-see-v4-gradient-mesh-r3','dram-see-v4-gradient-mesh-r4','dram-see-v4-gradient-mesh-r5','dram-see-v4-gradient-mesh-r6'):
            command='(sdesnmesh:delaunizer "maxPoints" 2147483647)'
            geometry_require(block.count(command)==1 and text.count('(sdesnmesh:delaunizer')==1
                             and text.index(command)<text.index('(sdedr:write-cmd-file'),
                             'Delaunizer setting must precede original mesh command output')
    return policy


def geometry_validate_r5_partitions(files,description,policy,definition):
    """Check only the new r5 declaration; old producer semantics are unchanged."""
    digest=lambda raw:GEOMETRY_hashlib.sha256(raw).hexdigest()
    source=definition.get('doping_partition_source',{})
    table_raw=source.get('raw_utf8','').encode('utf-8')
    expected_sha='04b2a4d3782456dcbaeb82537aae1473642c71078f47bb06079ce877dab776dc'
    geometry_require(digest(table_raw)==source.get('sha256')==expected_sha,
                     'r5 original mathematical partition table differs')
    table=geometry_json_bytes(table_raw,'r5 original doping partitions')
    model=geometry_json_bytes(files['model.proposed.json'],'r5 model')
    doping=model['doping']
    geometry_require(model['geometry']['gate_top_depth_nm'] in (70,80,90)
                     and doping.get('sn_junction_depth_nm')==87 and doping.get('bl_junction_depth_nm')==137.5
                     and doping.get('peak_donor')==1.45e20 and doping.get('uniform_acceptor')==1e17
                     and description['doping']['blend_um']==.005,
                     'r5 requires the original analyzed SN87 doping condition')
    evidence=policy.get('doping_partition_evidence',{})
    geometry_require(evidence.get('source_sha256')==expected_sha
                     and evidence.get('applicability')==table['applicability']
                     and evidence.get('candidate_ids')==[row['id'] for row in table['placements']]
                     and evidence.get('actual_cell_spans_verified') is False
                     and evidence.get('native_accuracy_qualified') is False,
                     'r5 mathematical evidence cannot be relabeled as actual mesh qualification')
    windows={w['name']:w for w in policy['volume_refinements']}
    geometry_require(len(windows)==len(policy['volume_refinements'])
                     and not set(table['replace_exact_windows'])&set(windows),
                     'r5 old full-depth doping placements remain or names are duplicated')
    geometry_require(all(w.get('sde_min_um')==w['physical_min_um'] and w.get('sde_max_um')==w['physical_max_um']
                         for w in windows.values()),'r5 native and physical mesh window coordinates differ')
    expected_names=set()
    for row in table['placements']:
        name=row['id'] if row['id'].startswith('Blend') else 'ActiveDoping'+row['id']
        expected_names.add(name)
        w=windows.get(name,{})
        geometry_require(w.get('physical_min_um')==[v/1000. for v in row['lo_nm']]
                         and w.get('physical_max_um')==[v/1000. for v in row['hi_nm']]
                         and w.get('max_size_um')==[v/1000.*policy['scale'] for v in row['max_step_nm']]
                         and w.get('min_size_um')==[v/1000.*policy['scale']*.5 for v in row['max_step_nm']]
                         and w.get('materials')==['Silicon'] and w.get('replaces_window')==row['replaces']
                         and w.get('doping_candidate_id')==row['id'],
                         'r5 doping rectangle differs from its original mathematical candidate: '+name)
    geometry_require({name for name in windows if name.startswith(('ActiveDoping','Blend'))}==expected_names,
                     'r5 additional full-depth doping constraints are not declared')
    straight=definition.get('straight_geometry_partition',{})
    geometry_require(straight==policy.get('straight_geometry_partition')
                     and straight.get('gate_side_straight_max_xyz_um')==[.001,.005,.005]
                     and straight.get('trench_sti_edge_straight_max_xyz_um')==[.001,.001,.005]
                     and straight.get('top_surface_halo_to_side_oxide_ratio')==.5
                     and straight.get('native_accuracy_qualified') is False,
                     'r5 straight geometric partition differs')
    oxide=description['nominal_oxide_um']['side']
    z0=description['outer_trench']['top_um'];zc=description['outer_trench']['round_center_z_um']
    gt=description['gate_void']['top_um']
    bounds=(z0,z0+oxide*.5,gt-oxide*2,gt+oxide*.5,zc-oxide,zc+oxide*.25)
    segments=('Surface','StraightUpper','GateTop','StraightLower','CurveTransition')
    padding=oxide*.25;corner=oxide*.5
    tx=description['outer_trench']['x_half_width_um'];gx=description['gate_void']['x_half_width_um']
    ex=tx+padding;ey=description['outer_trench']['y_half_width_um']+padding
    inner_y=[description['sti']['y_intervals_um'][0][1],description['sti']['y_intervals_um'][1][0]]
    xy_boxes={'GateSideNormalX':[([-ex,-ey],[-gx+padding,ey]),([gx-padding,-ey],[ex,ey])],
              'TrenchSTISideCorners':[([x-corner,y-corner],[x+corner,y+corner]) for x in (-tx,tx) for y in inner_y]}
    for family,count,old_max,new_max in (('GateSideNormalX',2,[.001,.005,.001],[.001,.005,.005]),
                                         ('TrenchSTISideCorners',4,[.001,.001,.001],[.001,.001,.005])):
        expected={family+str(i)+segment for i in range(1,count+1) for segment in segments}
        geometry_require({name for name in windows if name.startswith(family)}==expected,
                         'r5 original full-height side/edge placement remains or partition is incomplete')
        for i in range(1,count+1):
            for j,segment in enumerate(segments):
                w=windows[family+str(i)+segment]
                maximum=new_max if j in (1,3) else old_max
                geometry_require(w['physical_min_um'][:2]==xy_boxes[family][i-1][0]
                                 and w['physical_max_um'][:2]==xy_boxes[family][i-1][1]
                                 and w['physical_min_um'][2]==bounds[j] and w['physical_max_um'][2]==bounds[j+1]
                                 and w['max_size_um']==[v*policy['scale'] for v in maximum]
                                 and w['min_size_um']==[v*policy['scale']*.5 for v in maximum]
                                 and w.get('directional_segment')==segment and w.get('directional_family')==family,
                                 'r5 straight/corner band differs from actual geometry')


def geometry_validate_r6_partitions(files,description,policy,definition):
    """Validate r6 only; inherited declarations do not confer native qualification."""
    digest=lambda raw:GEOMETRY_hashlib.sha256(raw).hexdigest()
    expected_sha='3e6a7e34522a3be0c000874c92f1d7dda87ab174b8686193100245a135449cf1'
    source=definition.get('doping_partition_source',{})
    table_raw=source.get('raw_utf8','').encode('utf-8')
    geometry_require(digest(table_raw)==source.get('sha256')==expected_sha,
                     'r6 original 99-placement mathematical table differs')
    table=geometry_json_bytes(table_raw,'r6 original doping partitions')
    counts={'NEW_HESSIAN_BOUNDED_COARSENING':75,'INHERITED_ACTUAL_R5_NO_NEW_CERTIFICATION':23,
            'EXACT_EFFECTIVE_Y_FACTORING_WITH_BLEND':1}
    geometry_require(len(table['placements'])==99 and len(table['replace_only_r5_doping_window_names'])==13
                     and {key:sum(row['evidence_class']==key for row in table['placements']) for key in counts}==counts,
                     'r6 original bounded/inherited/support counts differ')
    model=geometry_json_bytes(files['model.proposed.json'],'r6 model')
    doping=model['doping']
    geometry_require(model['geometry']['gate_top_depth_nm'] in (70,80,90)
                     and model['geometry']['units']=='nm' and doping['units']=='cm^-3'
                     and doping.get('sn_junction_depth_nm')==87 and doping.get('bl_junction_depth_nm')==137.5
                     and doping.get('peak_donor')==1.45e20 and doping.get('uniform_acceptor')==1e17
                     and description['doping']['blend_um']==.005,
                     'r6 requires the original analyzed SN87 doping condition')
    evidence=policy.get('doping_partition_evidence',{})
    geometry_require(evidence.get('source_sha256')==expected_sha
                     and evidence.get('applicability')==table['applicability']
                     and evidence.get('baseline_policy_ref')==table['baseline_policy_ref']
                     and evidence.get('candidate_ids')==[row['id'] for row in table['placements']]
                     and evidence.get('evidence_counts')==counts
                     and all(evidence.get(key) is False for key in ('full_domain_certified','actual_cell_spans_verified','native_accuracy_qualified')),
                     'r6 partial mathematical evidence cannot become full-domain or native qualification')
    windows={w['name']:w for w in policy['volume_refinements']}
    geometry_require(len(windows)==len(policy['volume_refinements'])
                     and not set(table['replace_only_r5_doping_window_names'])&set(windows),
                     'r6 old thirteen doping placements remain or names are duplicated')
    geometry_require(all(w.get('sde_min_um')==w['physical_min_um'] and w.get('sde_max_um')==w['physical_max_um']
                         for w in windows.values()),'r6 native and physical mesh coordinates differ')
    expected_names={row['id'] for row in table['placements']}
    geometry_require({name for name,w in windows.items() if 'doping_candidate_id' in w
                      or name.startswith(('ActiveDoping','Blend','Doping')) or name=='CoreYSupport'}==expected_names,
                     'r6 undeclared doping placement or old fine constraint remains')
    for row in table['placements']:
        w=windows.get(row['id'],{})
        geometry_require(w.get('physical_min_um')==[float(v) for v in row['lo_um_decimal']]
                         and w.get('physical_max_um')==[float(v) for v in row['hi_um_decimal']]
                         and w.get('max_size_um')==[float(v)*policy['scale'] for v in row['max_step_um_decimal']]
                         and w.get('min_size_um')==[float(v)*policy['scale'] for v in row['minimum_step_um_decimal']]
                         and w.get('materials')==['Silicon'] and not w.get('regions')
                         and w.get('doping_candidate_id')==row['id']
                         and w.get('doping_evidence_class')==row['evidence_class']
                         and w.get('doping_original_r5_window_names')==row.get('original_r5_window_names',[])
                         and w.get('doping_new_mathematical_certification')==(row['evidence_class']=='NEW_HESSIAN_BOUNDED_COARSENING')
                         and w.get('doping_maximum_bound_over_original_tolerance')==row.get('maximum_bound_over_original_tolerance'),
                         'r6 doping rectangle/evidence differs: '+row['id'])
    active=description['mesh'].get('active_doping_refinement',{})
    geometry_require(active.get('schema')=='dram-see-v4-partitioned-active-doping-r2'
                     and active.get('window_names')==[w['name'] for w in policy['volume_refinements']
                         if 'doping_candidate_id' in w or w['name'].startswith('Contact')]
                     and active.get('probe_locations_changed') is False,
                     'r6 measured doping partition identity differs')

    source=definition.get('source_spacing_source',{})
    source_raw=source.get('raw_utf8','').encode('utf-8')
    analysis_raw=source.get('analysis_raw_utf8','').encode('utf-8')
    source_sha='0131e202d37c48d8e70569052d11222506570ed19a3e00518156eb7f1ff04bfa'
    analysis_sha='39b116b621ebf6dcfab6ec38e887a82b561c7b3e6756fe870f7525ecbbcf78e4'
    geometry_require(digest(source_raw)==source.get('sha256')==source_sha
                     and digest(analysis_raw)==source.get('analysis_ref',{}).get('sha256')==analysis_sha,
                     'r6 original source-spacing certificate differs')
    candidate=geometry_json_bytes(source_raw,'r6 source candidate')
    analysis=geometry_json_bytes(analysis_raw,'r6 source analysis')
    source_evidence=policy.get('source_spacing_evidence',{})
    scope=candidate['scope']
    matches=(model['geometry']['gate_top_depth_nm']==scope['gate_top_depth_nm']
             and doping['sn_junction_depth_nm']==scope['sn_junction_depth_nm'])
    geometry_require(source_evidence.get('candidate_sha256')==source_sha
                     and source_evidence.get('analysis_sha256')==analysis_sha
                     and source_evidence.get('scope')==scope
                     and source_evidence.get('conditional_certificate')==analysis['rational_upper_bound_certificate']
                     and source_evidence.get('certificate_conditions')==analysis['P1_certificate_conditions']
                     and source_evidence.get('conditional_certificate_scope_matches_input')==matches
                     and all(source_evidence.get(key) is False for key in ('actual_cell_spans_verified',
                         'ROI_centroid_moments_qualified','native_accuracy_qualified','source_values_changed')),
                     'r6 source scope/conditional evidence cannot become native qualification')
    geometry_require(model['alpha']['first_energy_MeV']==5 and model['alpha']['angle_deg_from_positive_z']==0
                     and model['alpha']['radial_Gaussian_w_nm']==50,
                     'r6 source column is only the original normal 5MeV alpha candidate')
    for row in candidate['changes_only']:
        w=windows.get(row['name'],{})
        geometry_require(w.get('physical_min_um')==row['physical_min_um']
                         and w.get('physical_max_um')==row['physical_max_um']
                         and w.get('max_size_um')==[v*policy['scale'] for v in row['candidate_max_size_um']]
                         and w.get('min_size_um')==[v*policy['scale'] for v in row['candidate_min_size_um']]
                         and w.get('materials')==row['materials'],
                         'r6 approved source core geometry/steps differ: '+row['name'])

    # Reuse only the already checked r5 geometric-band validator. This local
    # validation projection is never emitted as an input, policy or native result.
    # Restore its exact thirteen mathematical rows while retaining all actual
    # r6 geometric windows, so its existing geometry checks operate unchanged.
    original_source=definition.get('inherited_r5_doping_partition_source',{})
    original_raw=original_source.get('raw_utf8','').encode('utf-8')
    geometry_require(digest(original_raw)==original_source.get('sha256')==
                     '04b2a4d3782456dcbaeb82537aae1473642c71078f47bb06079ce877dab776dc',
                     'r6 inherited r5 geometric validation source differs')
    original=geometry_json_bytes(original_raw,'r5 fixed partition source')
    projected=GEOMETRY_json.loads(GEOMETRY_json.dumps(policy))
    projected['volume_refinements']=[w for w in projected['volume_refinements'] if w['name'] not in expected_names]
    for row in original['placements']:
        name=row['id'] if row['id'].startswith('Blend') else 'ActiveDoping'+row['id']
        low=[v/1000. for v in row['lo_nm']];high=[v/1000. for v in row['hi_nm']]
        projected['volume_refinements'].append(dict(name=name,physical_min_um=low,physical_max_um=high,
            sde_min_um=low,sde_max_um=high,max_size_um=[v/1000.*policy['scale'] for v in row['max_step_nm']],
            min_size_um=[v/1000.*policy['scale']*.5 for v in row['max_step_nm']],materials=['Silicon'],
            doping_candidate_id=row['id'],replaces_window=row['replaces']))
    projected['doping_partition_evidence']=dict(source_sha256=digest(original_raw),applicability=original['applicability'],
        candidate_ids=[row['id'] for row in original['placements']],actual_cell_spans_verified=False,native_accuracy_qualified=False)
    projected_definition=dict(definition,doping_partition_source=original_source)
    geometry_validate_r5_partitions(files,description,projected,projected_definition)


def geometry_compare_dc_a0_inputs(project, producer_inputs):
    """Retain shared physics/mesh identity, not false DC/mixed solver equality."""
    for name, raw in producer_inputs.items():
        # The original DC numerical file is still verified in its complete
        # frozen inputs.tar. A0 separately renders/binds its mixed=True contract.
        if name == 'numerical-method.json':
            continue
        current = GEOMETRY_Path(project) / name
        if current.exists():
            geometry_require(geometry_digest(current) == GEOMETRY_hashlib.sha256(raw).hexdigest(),
                             'A0 input differs from completed DC: ' + name)


def geometry_source_bundle(project, cfg, execution=None, synthetic_fixture=False):
    """Verify D3's completed original archive; no human sign-off is required."""
    geometry_require(synthetic_fixture is False, 'Synthetic data cannot supply a native A0 mesh')
    if cfg.get('dimension_branch')=='dram-see-v4-parameterized-d2-source-r1':
        return geometry_parameterized_operating_module().source_bundle(project,cfg,execution)
    if cfg.get('dimension_branch')=='dram-see-v4-2d-control-r1':
        return geometry_2d_module().source_bundle(project,cfg,None,execution)
    source_value = cfg.get('source_run_directory')
    geometry_require(isinstance(source_value, str) and source_value, 'D3 source directory is absent')
    source = GEOMETRY_Path(source_value)
    producer = cfg.get('producer_run_id')
    geometry_require(source.is_absolute() and source.is_dir() and not source.is_symlink()
                     and source.name == producer, 'D3 original directory identity differs')
    for folder in (GEOMETRY_Path(project), source):
        geometry_require('UNIT_FIXTURE_NOT_NATIVE' not in str(folder.resolve())
                         and not (folder / 'SYNTHETIC_NOT_NATIVE').exists(), 'Synthetic cannot supply native geometry')
    manifest_path, archive_path = source / 'manifest.json', source / 'results.tar'
    manifest_sha, archive_sha = geometry_digest(manifest_path), geometry_digest(archive_path)
    manifest = geometry_json(manifest_path)
    geometry_require(manifest.get('schema') == 'tcad-native-run-r2'
                     and manifest.get('collection_verified') is True
                     and manifest.get('state') == 'COLLECTED' and manifest.get('origin') == 'native_pipeline'
                     and manifest.get('synthetic') is False and manifest.get('run_id') == producer,
                     'D3 source origin/completion differs')
    # An interrupted transport is retained as such. Successful recovery is a
    # property of the original job and completed collection, not a forged SSH 0.
    for key in ('remote_exit_code', 'collection_exit_code'):
        geometry_require(type(manifest.get(key)) is int and manifest[key] == 0, 'D3 source exit unknown/nonzero: ' + key)
    geometry_require(type(manifest.get('ssh_exit_code')) is int, 'D3 original SSH exit is missing')
    exits = manifest.get('tool_exit_codes')
    full_steps = {'step-001-sde','step-002-snmesh','step-003-tdx','step-004-tdx','step-005-svisual','step-006-sdevice'}
    tail_steps = full_steps-{'step-001-sde','step-002-snmesh'}
    metadata_tail_steps={'step-005-svisual','step-006-sdevice'}
    geometry_require(isinstance(exits, dict)
                     and set(exits) in (full_steps,tail_steps,metadata_tail_steps,{'step-006-sdevice'})
                     and all(type(v) is int and v == 0 for v in exits.values()), 'D3 tool exits incomplete')
    geometry_require(manifest.get('results_sha256') == archive_sha, 'D3 archive differs from original manifest')
    for key, actual in (('source_manifest_sha256', manifest_sha), ('source_archive_sha256', archive_sha)):
        if cfg.get(key) is not None:
            geometry_require(cfg[key] == actual, 'D3 source binding differs: ' + key)
    with GEOMETRY_tarfile.open(str(archive_path), 'r:*') as archive:
        members = geometry_tar_members(archive)
        source_spec = geometry_json_bytes(geometry_tar_bytes(archive, members, 'project.json'), 'D3 project')
        source_cfg = source_spec.get('s2_geometry', {})
        if source_cfg.get('mode')=='produce_from_geometry':
            geometry_require(source_cfg.get('schema')==GEOMETRY_SCHEMA and source_cfg.get('synthetic') is False
                and source_cfg.get('role_id')=='B1-D3' and source_cfg.get('run_id')==source_cfg.get('producer_run_id')==producer,
                'DC-only archived producer identity differs')
            dc=geometry_dc_module()
            result=dc.completed_bundle(source,manifest_path.read_bytes(),archive,members,source_cfg)
            geometry_compare_dc_a0_inputs(project,result['producer_inputs'])
            geometry_validate_mesh_policy_payload(result['producer_inputs'],source_cfg)
            for name in ('mesh_policy_id','mesh_policy_sha256'):
                if name in cfg:geometry_require(cfg[name]==source_cfg.get(name),'A0 DC mesh policy differs: '+name)
            for name in ('mesh_sha256','geometry_validation_sha256','mesh_representation','origin_mesh_sha256',
                         'active_solver_mesh_sha256','dc_completed_binding_sha256')+dc.SELECTOR_CFG_FIELDS:
                if execution is not None or name in cfg:
                    geometry_require(cfg.get(name)==result.get(name),'A0 completed DC/geometry selector differs: '+name)
            return result
        composite = source_cfg.get('mode') == 'produce_from_mesh'
        metadata = source_cfg.get('mode') == 'produce_from_metadata'
        active_mesh=metadata and source_cfg.get('mesh_representation')==GEOMETRY_ACTIVE_REPRESENTATION
        geometry_require(source_cfg.get('schema') == GEOMETRY_SCHEMA and source_cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata')
                         and source_cfg.get('synthetic') is False and source_cfg.get('role_id') == 'B1-D3'
                         and source_cfg.get('run_id') == producer and source_cfg.get('producer_run_id') == producer,
                         'D3 archived project identity differs')
        geometry_require(set(exits) == (metadata_tail_steps if metadata else tail_steps if composite else full_steps),
                         'D3 actual exit set differs from producer mode')
        if composite or metadata:
            get = lambda name: geometry_tar_bytes(archive,members,name)
            index = geometry_json_bytes(get('_collection-members.json'),'Composite collection index')
            geometry_require(set(index) == {n for n,v in members.items() if v.isfile()}-{'_collection-members.json'},
                             'Composite complete collection index membership differs')
            for name,row in index.items():
                geometry_require(members[name].size == row.get('size'),'Composite collection size differs: '+name)
                with archive.extractfile(members[name]) as stream:
                    geometry_require(geometry_stream_digest(stream) == row.get('sha256'),'Composite collection bytes differ: '+name)
            if metadata:
                metadata_module=geometry_metadata_module();metadata_reader=metadata_module.ArchiveReader(archive,members)
                geometry_require(geometry_digest(source/'inputs.tar')==manifest.get('inputs_archive_sha256'),
                                 'Completed metadata producer input archive differs')
                with (source/'inputs.tar').open('rb') as stream:
                    source_binding=metadata_module.validate_completed(metadata_reader,manifest,source_cfg,stream)
                for node in source_binding['nodes'].values():
                    original_folder=GEOMETRY_Path(node['directory'])
                    geometry_require(geometry_digest(original_folder/'results.tar')==node['archive_sha256']
                        and geometry_digest(original_folder/'inputs.tar')==node['inputs_archive_sha256'],
                        'Original metadata/operation archive changed')
                ancestor=geometry_json_bytes(get('mesh-source-binding.json'),'Original mesh ancestor')
                original_folder=GEOMETRY_Path(ancestor['source_run_directory'])
                geometry_require(geometry_digest(original_folder/'results.tar')==ancestor['source_archive_sha256']
                    and geometry_digest(original_folder/'inputs.tar')==ancestor['source_inputs_archive_sha256'],
                    'Original mesh prefix archive changed')
            else:
                mesh_module = geometry_mesh_module()
                geometry_require(not {'step-001-sde-exit-code.txt','step-002-snmesh-exit-code.txt'} & set(members),
                                 'Composite producer must not claim current prefix exits')
                source_binding = mesh_module.validate_completed(get,lambda name:index[name]['sha256'],manifest,source_cfg,
                                                                 (source/'inputs.tar').read_bytes())
                original = mesh_module.source_package(GEOMETRY_Path(source_binding['source_run_directory']),
                    geometry_json_bytes(get('controlled-request.json'),'Composite request'),
                    frozen_manifest=get('mesh-source-bindings/manifest.json'))
                geometry_require(original['binding'] == source_binding,'Composite inherited original archive changed')
        report_raw = geometry_tar_bytes(archive, members, 'geometry-validation.json')
        report = geometry_json_bytes(report_raw, 'D3 geometry report')
        report_sha = GEOMETRY_hashlib.sha256(report_raw).hexdigest()
        geometry_require(report.get('schema') == 's2-native-geometry-validation-r1'
                         and report.get('origin') == 'native_pipeline' and report.get('synthetic') is False
                         and report.get('passed') is True and report.get('role_id') == 'B1-D3'
                         and report.get('producer_run_id') == producer
                         and all(report.get('checks', {}).get(k) is True for k in GEOMETRY_CHECKS),
                         'D3 geometry report origin/checks differ')
        hashes = report.get('evidence_sha256')
        geometry_require(isinstance(hashes, dict) and set(GEOMETRY_HDF5_RAW_REQUIRED if metadata else GEOMETRY_RAW_REQUIRED) <= set(hashes), 'D3 raw evidence incomplete')
        geometry_require('geometry-producer-bindings/execution-context.json' in hashes
                         and 'geometry-producer-bindings/input-manifest.json' in hashes
                         and 'geometry-exit-sources.json' in hashes, 'D3 producer/exit binding missing')
        for name in ('execution-context.json', 'input-manifest.json', 'task-authorization.json'):
            geometry_require(geometry_tar_bytes(archive, members, name)
                             == geometry_tar_bytes(archive, members, 'geometry-producer-bindings/' + name),
                             'D3 original input/context differs from its evidence copy: ' + name)
        source_context = geometry_json_bytes(geometry_tar_bytes(archive, members, 'execution-context.json'), 'D3 execution context')
        geometry_require(source_context.get('run_id') == producer and source_context.get('role_id') == 'B1-D3'
                         and source_context.get('input_manifest_sha256')
                         == GEOMETRY_hashlib.sha256(geometry_tar_bytes(archive, members, 'input-manifest.json')).hexdigest(),
                         'D3 original execution context/input identity differs')
        source_inputs = geometry_json_bytes(geometry_tar_bytes(archive, members, 'input-manifest.json'), 'D3 input manifest')
        if 'tdx_hash_sha256.tcl' in source_inputs.get('files_sha256',{}):
            geometry_require('tdr-hash-provider.csv' in hashes,'D3 new metadata hash provider evidence absent')
            geometry_validate_hash_provider(geometry_tar_bytes(archive,members,'tdr-hash-provider.csv'))
        if composite:
            required_inherited = set(source_binding['proofs_sha256'])|{'mesh-source-binding.json'}
            geometry_require(required_inherited <= set(hashes)
                             and report.get('mesh_source_binding_sha256') == source_cfg['mesh_source_binding_sha256']
                             and report.get('inherited_step_indices') == [1,2]
                             and report.get('actual_geometry_step_indices') == [3,4,5],
                             'Composite geometry report lacks inherited/current separation')
            for source_name,canonical in list(GEOMETRY_EXITS.items())[:2]:
                inherited_name = 'mesh-source-bindings/'+source_name
                recorded = report.get('original_exit_sources',{}).get(canonical,{})
                geometry_require(recorded.get('source') == inherited_name
                    and recorded.get('source_kind') == 'inherited_original_native_prefix'
                    and recorded.get('source_run_id') == source_binding['source_run_id']
                    and recorded.get('source_archive_sha256') == source_binding['source_archive_sha256']
                    and recorded.get('source_manifest_sha256') == source_binding['source_manifest_sha256']
                    and get(canonical) == get(inherited_name), 'Composite prefix exit provenance differs')
        if metadata:
            graph_hashes=metadata_module.evidence_hashes(metadata_reader,source_binding)
            geometry_require(set(graph_hashes)<=set(hashes)
                and all(hashes[n]==v for n,v in graph_hashes.items())
                and report.get('metadata_source_binding_sha256')==source_cfg['metadata_source_binding_sha256']
                and report.get('geometry_observation_backend')==GEOMETRY_HDF5_BACKEND
                and report.get('inherited_step_indices')==[1,2,3]
                and report.get('actual_geometry_step_indices')==[5], 'HDF5 producer report lost source-owner separation')
            if active_mesh:
                geometry_require(report.get('mesh_representation')==GEOMETRY_ACTIVE_REPRESENTATION
                    and report.get('origin_mesh_sha256')==source_binding['origin_mesh_sha256']==source_cfg['origin_mesh_sha256']
                    and report.get('active_solver_mesh_sha256')==source_binding['active_solver_mesh_sha256']==source_cfg['active_solver_mesh_sha256']
                    and report.get('mesh_sha256')==source_binding['active_solver_mesh_sha256'],
                    'Active solver report confused origin and actual mesh')
            geometry_validate_hash_provider(get('geometry-hash-provider.csv'))
            for step,tool,canonical in ((1,'sde','sde-exit-code.txt'),(2,'snmesh','mesh-exit-code.txt'),(3,'tdx','tdx-metadata-exit-code.txt')):
                name=('mesh-source-bindings/' if step<3 else 'metadata-source-bindings/')+'step-{:03d}-{}-exit-code.txt'.format(step,tool)
                recorded=report.get('original_exit_sources',{}).get(canonical,{})
                expected_owner=(dict(source_kind='inherited_original_native_prefix',source_run_id=ancestor['source_run_id'],
                    source_archive_sha256=ancestor['source_archive_sha256'],source_manifest_sha256=ancestor['source_manifest_sha256']) if step<3 else
                    dict(source_kind='inherited_original_native_metadata',source_run_id=source_binding['nodes']['metadata']['id'],
                    source_archive_sha256=source_binding['nodes']['metadata']['archive_sha256'],source_manifest_sha256=source_binding['nodes']['metadata']['receipt_sha256']))
                geometry_require(recorded.get('source')==name and all(recorded.get(k)==v for k,v in expected_owner.items())
                    and recorded.get('observed_exit_code')==0 and recorded.get('source_sha256')==hashes[name]
                    and recorded.get('canonical_sha256')==hashes[canonical] and get(name)==get(canonical),
                    'HDF5 inherited original native exit identity differs')
        physics_hashes = {}
        producer_inputs = {}
        for name in ('physics-manifest.json', 'physics.par', 'Silicon.par', 'Oxide.par'):
            original = geometry_tar_bytes(archive, members, name)
            actual = GEOMETRY_hashlib.sha256(original).hexdigest()
            geometry_require(source_inputs.get('files_sha256', {}).get(name) == actual,
                             'D3 original physics input differs: ' + name)
            physics_hashes[name] = actual
            producer_inputs[name] = original
            current = GEOMETRY_Path(project) / name
            if current.exists():
                geometry_require(geometry_digest(current) == actual,
                                 'A0 physics differs from its D3 baseline: ' + name)
        for name in ('geometry-contract.json', 'model.proposed.json', 'numerical-method.json'):
            if name == 'numerical-method.json' and name not in source_inputs.get('files_sha256', {}):
                continue
            original = geometry_tar_bytes(archive, members, name)
            geometry_require(source_inputs.get('files_sha256', {}).get(name)
                             == GEOMETRY_hashlib.sha256(original).hexdigest(), 'D3 original input differs: ' + name)
            producer_inputs[name] = original
        policy_names=set(GEOMETRY_MESH_POLICY_FILES)&set(source_inputs.get('files_sha256',{}))
        geometry_require(not policy_names or policy_names==set(GEOMETRY_MESH_POLICY_FILES),
                         'D3 original mesh policy files are incomplete')
        for name in sorted(policy_names):
            original=geometry_tar_bytes(archive,members,name)
            geometry_require(source_inputs['files_sha256'][name]==GEOMETRY_hashlib.sha256(original).hexdigest(),
                             'D3 original mesh policy input differs: '+name)
            producer_inputs[name]=original
        policy_payload=dict(producer_inputs)
        if policy_names:
            original=geometry_tar_bytes(archive,members,'geometry-with-measurements.scm')
            geometry_require(source_inputs['files_sha256'].get('geometry-with-measurements.scm')==GEOMETRY_hashlib.sha256(original).hexdigest(),
                             'Original mesh-policy SDE differs')
            policy_payload['geometry-with-measurements.scm']=original
        geometry_validate_mesh_policy_payload(policy_payload,source_cfg,require_sde=bool(policy_names))
        for name in ('mesh_policy_id','mesh_policy_sha256'):
            if name in cfg:
                geometry_require(cfg[name]==source_cfg.get(name),'A0 original mesh policy differs: '+name)
        exports = dict(hashes)
        exports['geometry-validation.json'] = report_sha
        for name in ('cell_msh.tdr', 'cell_msh.log'):
            geometry_require(name in members and members[name].isfile(), 'D3 source is missing ' + name)
            with archive.extractfile(members[name]) as stream:
                exports[name] = geometry_stream_digest(stream)
        for name, expected in exports.items():
            geometry_relative(name)
            geometry_require(name not in ('project.json', 'input-manifest.json', 'execution-context.json', 'task-authorization.json'),
                             'D3 root context conflicts with A0 inputs')
            geometry_hash_value(expected, name)
            empty_original=metadata and name in source_binding['imports'] and source_binding['imports'][name]['size_bytes']==0
            geometry_require(name in members and members[name].isfile() and (members[name].size > 0 or empty_original), 'Empty/missing D3 evidence: ' + name)
            with archive.extractfile(members[name]) as stream:
                geometry_require(geometry_stream_digest(stream) == expected, 'D3 evidence changed: ' + name)
        observation = geometry_json_bytes(geometry_tar_bytes(archive, members, 'observation-context.json'), 'D3 observation')
        mesh_sha = exports['cell_msh.tdr']
        geometry_require(observation.get('schema') == (GEOMETRY_ACTIVE_CONTEXT if active_mesh else GEOMETRY_HDF5_CONTEXT if metadata else 's2-geometry-observation-context-r1')
                         and observation.get('origin') == 'native_pipeline' and observation.get('synthetic') is False
                         and observation.get('producer_run_id') == producer and observation.get('role_id') == 'B1-D3'
                         and observation.get('mesh_sha256') == mesh_sha == report.get('mesh_sha256')
                         and observation.get('dimension') == 3, 'D3 mesh/producer identity differs')
        if metadata:
            geometry_require(observation.get('geometry_observation_backend')==GEOMETRY_HDF5_BACKEND
                and observation.get('metadata_source_binding_sha256')==source_cfg['metadata_source_binding_sha256']
                and observation.get('inherited_step_indices')==[1,2,3] and observation.get('actual_geometry_step_indices')==[5],
                'HDF5 observation graph context differs')
            if active_mesh:
                geometry_require(observation.get('mesh_representation')==GEOMETRY_ACTIVE_REPRESENTATION
                    and observation.get('origin_mesh_sha256')==source_binding['origin_mesh_sha256']
                    and observation.get('active_solver_mesh_sha256')==mesh_sha==source_binding['active_solver_mesh_sha256'],
                    'Current observation origin/active mesh identity differs')
                for name in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256'):
                    if execution is not None or name in cfg:
                        geometry_require(cfg.get(name)==source_cfg[name],'A0 actual/origin mesh representation differs: '+name)
        for name in (n for n in GEOMETRY_EXITS.values() if not metadata or n!='tdx-converter-exit-code.txt'):
            geometry_require(geometry_exit_value(geometry_tar_bytes(archive, members, name), name) == 0
                             and observation.get('raw_exit_sha256', {}).get(name) == exports[name], 'D3 raw exit differs')
        geometry_require(geometry_exit_value(geometry_tar_bytes(archive, members, 'exit-code.txt'), 'D3 wrapper') == 0,
                         'D3 wrapper exit is nonzero')
        if cfg.get('mesh_sha256') is not None:
            geometry_require(cfg['mesh_sha256'] == mesh_sha, 'Different D3 mesh')
        current_geometry = GEOMETRY_Path(project) / 'geometry-contract.json'
        if current_geometry.exists():
            geometry_require(geometry_digest(current_geometry) == observation.get('geometry_contract_sha256'),
                             'A0 geometry contract differs from its original D3 mesh')
    result=dict(archive=archive_path, archive_sha256=archive_sha, manifest_sha256=manifest_sha,
                geometry_validation_sha256=report_sha, mesh_sha256=mesh_sha, physics_sha256=physics_hashes,
                producer_inputs=producer_inputs, producer_cfg=source_cfg, exports=exports)
    if active_mesh:
        result.update({n:source_cfg[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
    return result


def geometry_validate_current_case(project, cfg, hashes, model, device):
    """Validate the controlled role and the parameter file actually used by SDevice."""
    request = geometry_json(project / 'controlled-request.json')
    geometry_require('case_contract.py' in hashes, 'Controlled request validator is not frozen')
    geometry_require(geometry_digest(project / 'case_contract.py') == hashes['case_contract.py'],
                     'Controlled request validator changed')
    module_spec = GEOMETRY_importlib.spec_from_file_location('geometry_case_contract', str(project / 'case_contract.py'))
    case = GEOMETRY_importlib.module_from_spec(module_spec)
    module_spec.loader.exec_module(case)
    request = case.validate(request)
    geometry_require(case.role_id(request) == cfg['role_id']
                     and cfg.get('size_id') == case.size_id(request['gate_top_depth_nm'])
                     and cfg.get('numerical_variant') == request['variant']
                     and model.get('geometry', {}).get('gate_top_depth_nm') == request['gate_top_depth_nm']
                     and model.get('doping',{}).get('sn_junction_depth_nm')==request.get('sn_junction_depth_nm',87)
                     ==cfg.get('sn_junction_depth_nm',87),
                     'Controlled role, gate/SN depth or numerical variant differs')
    if 'parameter_id' in cfg:
        geometry_require(cfg['parameter_id']==case.parameter_id(request) and 'controlled-parameters.json' in hashes,
                         'Controlled parameter identity differs')
        geometry_validate_parameter_contract(project,cfg,request,model)
    if request['kind'] == 'dc':
        geometry_require(GEOMETRY_re.findall(r'\bParameter\s*=\s*"([^"]+)"', device) == ['physics.par'],
                         'DC must use its original physics parameter file')
        if request.get('schema')=='dram-see-v4-controlled-device-request-r13':
            module=geometry_parameterized_operating_module()
            module.verify_d2_inputs(module.d2_api().FolderReader(project),cfg)
        return
    binding = geometry_json(project / 'parameter-binding.json')
    geometry_require(binding.get('schema') == 'dram-see-v4-active-parameters-r1'
                     and binding.get('base_file') == 'physics.par'
                     and binding.get('base_sha256') == geometry_digest(project / 'physics.par'),
                     'Base physics parameter binding differs')
    proton = request.get('particle') == 'proton'
    alpha_v2 = request.get('source_version') == 'v2-alpha-surface'
    if request['source_case'] == 'A0' or (proton and request['source_case'] == 'STRUCTURAL_ZERO'):
        expected_file, expected = 'physics.par', (project / 'physics.par').read_bytes()
        geometry_require(binding.get('source_file') is None and binding.get('aggregation') == 'base_only'
                         and GEOMETRY_re.search(r'\bHeavyIon\s*\(', device) is None,
                         'A0/structural zero must have structural source absence')
    else:
        prefix = '' if proton or request['source_case'] == 'Aalpha' else request['source_case'] + '.'
        source_name = prefix + 'source.par'
        source = geometry_path(project, source_name).read_bytes()
        physics_name = prefix + 'heavyion.physics.inc'
        physical = geometry_path(project, physics_name).read_text(encoding='utf-8')
        geometry_require(binding.get('source_file') == source_name
                         and binding.get('source_sha256') == geometry_digest(project / source_name)
                         and binding.get('source_physics_file') == physics_name
                         and binding.get('source_physics_sha256') == geometry_digest(project / physics_name)
                         and binding.get('aggregation') == 'base_bytes + LF + source_bytes'
                         and physical in device, 'Configured source or active parameter relationship differs')
        # Source parameter cards may contain only the declared HeavyIon blocks.
        p = [('a_1',0.),('a_2',0.),('a_3',0.),('a_4',0.),('k_hi',1.),('c_1',0.),
             ('c_2',1.),('c_3',0.),('c_4',1.),('s_hi',2e-12 if proton else .2e-12)]
        if proton:
            fragments=GEOMETRY_json.loads((project/'fragments.json').read_text(encoding='utf-8'))
            names=[f['name'] for f in fragments]
            geometry_require(names==['G4Deposit'+str(i) for i in range(len(names))] and names,
                             'Proton fragment identity or positive source differs')
        elif alpha_v2:
            names=['AlphaASTARv2']
        else:
            names=['S2ASTAR5MeV_'+str(i) for i in range(2 if request['source_case']=='split' else 1)]
        indent=' ' if proton or alpha_v2 else '  '
        expected_source = ''.join('HeavyIon("'+name+'") {\n' +
            ''.join(indent+key+' = '+format(value, '.17g')+'\n' for key, value in p)+'}\n' for name in names)
        geometry_require(source == expected_source.encode('utf-8'), 'Source parameters include an undeclared override')
        expected_file = 'run-parameters.par'
        expected = (project / 'physics.par').read_bytes() + b'\n' + source
    geometry_require(binding.get('active_file') == expected_file
                     and binding.get('active_sha256') == GEOMETRY_hashlib.sha256(expected).hexdigest()
                     and geometry_path(project, expected_file).read_bytes() == expected
                     and GEOMETRY_re.findall(r'\bParameter\s*=\s*"([^"]+)"', device) == [expected_file],
                     'SDevice active parameter file is not the bound base/source aggregate')


def geometry_validate_parameter_contract(project,cfg,request,model):
    contract=geometry_json(project/'controlled-parameters.json')
    description=geometry_json(project/'geometry-contract.json');dp=description['doping']
    depth=request.get('sn_junction_depth_nm',87)
    width=(depth/1000.)/GEOMETRY_math.sqrt(GEOMETRY_math.log(model['doping']['peak_donor']/model['doping']['uniform_acceptor']))
    geometry_require(contract.get('schema')=='dram-see-v4-controlled-device-parameters-r1'
                     and cfg.get('controlled_parameters_sha256')==geometry_digest(project/'controlled-parameters.json')
                     and contract.get('parameter_id')==cfg['parameter_id']
                     and contract.get('gate_top_depth_nm')==request['gate_top_depth_nm']
                     and contract.get('sn_junction_depth_nm')==depth
                     and contract.get('units')==dict(gate_top_depth='nm',sn_junction_depth='nm',native_length='um',concentration='cm^-3')
                     and model['geometry']['units']=='nm' and model['doping']['units']=='cm^-3'
                     and contract.get('native_sn_junction_depth_um')==depth/1000.
                     and contract.get('native_gaussian_width_um')==dp['a_sn_um']==width
                     and contract.get('native_general_initialization')==dp['initialization'],
                     'Controlled SN parameter is not the actual Gaussian/units definition')
    names={'model.proposed.json','geometry-contract.json'}
    if cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry'):names|={'measurement-plan.json','geometry-with-measurements.scm'}
    if 'mesh_policy_id' in cfg:names|=set(GEOMETRY_MESH_POLICY_FILES)
    geometry_require(set(contract.get('bound_files_sha256',{}))==names
                     and all(contract['bound_files_sha256'][name]==geometry_digest(project/name) for name in names),
                     'Controlled parameter source/measurement bytes differ')
    if cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry'):
        geometry_require(dp['initialization'] in (project/'geometry-with-measurements.scm').read_text(encoding='utf-8'),
                         'Actual SDE initializer differs from the requested SN profile')
        plan=geometry_json(project/'measurement-plan.json')
        geometry_require(plan.get('expected_geometry')==description
                         and plan.get('geometry_contract_sha256')==geometry_digest(project/'geometry-contract.json'),
                         'Actual SN measurement contract differs')
    else:
        producer=contract.get('actual_D3_binding',{})
        for name in ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256'):
            geometry_require(producer.get(name)==cfg.get(name),'Controlled A0/D3 identity differs: '+name)
        geometry_require(producer.get('model_sha256')==geometry_digest(project/'model.proposed.json')
                         and producer.get('geometry_contract_sha256')==geometry_digest(project/'geometry-contract.json'),
                         'Controlled A0 geometry/model do not belong to actual D3')


def geometry_validate_controlled_a0(project,cfg,request):
    spec=geometry_json(project/'source-spec.json');source=geometry_json(project/'source-contract.json')
    geometry_require(request.get('source_case')=='A0' and request.get('particle','alpha')=='alpha'
                     and spec.get('schema')=='continuous-particle-source-spec-v1' and spec.get('particle')=='alpha'
                     and spec.get('role')=='CONTROL' and spec.get('stored_bit')==request['stored_bit']
                     and spec.get('numerical_variant')==request['variant']
                     and spec.get('physics_manifest_sha256')==geometry_digest(project/'physics-manifest.json')
                     and source.get('schema')=='dram-see-v4-controlled-a0-source-contract-r1'
                     and source.get('source_configured') is False and source.get('structural_source_absence') is True
                     and source.get('source_oracle') is None and source.get('source_waveform') is None
                     and source.get('parameter_id')==cfg['parameter_id']
                     and source.get('model_sha256')==geometry_digest(project/'model.proposed.json')
                     and source.get('geometry_contract_sha256')==geometry_digest(project/'geometry-contract.json'),
                     'Controlled A0 source absence or selected model differs')
    producer=source.get('producer_binding',{})
    for name in ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256'):
        geometry_require(producer.get(name)==cfg.get(name),'Controlled A0 source/D3 identity differs: '+name)


def geometry_validate_prospective_binding(project, model):
    """Check frozen byte relationships; data admission independently recomputes the source again."""
    request=geometry_json(project/'controlled-request.json')
    proton=request.get('particle')=='proton'
    alpha_v2=request.get('source_version')=='v2-alpha-surface'
    geometry_require(request.get('source_case') in (('SIGNAL','STRUCTURAL_ZERO') if proton else ('Aalpha','Z','H','split')),
                     'Unsupported prospective source')
    binding=geometry_json(project/'source-feature-binding.json')
    packet=geometry_json(project/'source-features.json')
    contract=geometry_json(project/'source-feature-contract.json')
    registered=geometry_json(project/'data-input.json')
    geometry_require(binding.get('schema') in ('dram-see-v4-prospective-source-binding-r1','dram-see-v4-prospective-source-binding-r2')
                     and registered.get('schema')=='dram-see-v4-registered-data-input-v2',
                     'Prospective binding or registered data schema differs')
    packet_sha=geometry_digest(project/'source-features.json')
    contract_sha=geometry_digest(project/'source-feature-contract.json')
    geometry_require(binding.get('source_features_original_ref',{}).get('sha256')==packet_sha
                     and registered.get('source_features_sha256')==packet_sha
                     and registered.get('source_features_ref')==binding.get('registered_source_features_ref')
                     and registered.get('source_features_ref',{}).get('sha256')==packet_sha
                     and packet.get('feature_contract_sha256')==contract_sha
                     and packet.get('feature_contract')==contract
                     and registered.get('source_feature_contract_sha256')==contract_sha
                     and binding.get('feature_contract_sha256')==contract_sha,
                     'Prospective feature/contract bytes differ from registered originals')
    geometry_require(binding.get('registered_data_original_ref',{}).get('sha256')==geometry_digest(project/'data-input.json'),
                     'Registered data input bytes changed')
    if alpha_v2:
        names=set(GEOMETRY_ALPHA_V2_INPUTS);aliases={name:name for name in names}
    elif proton:
        names=set(GEOMETRY_PROTON_PAYLOAD)|{'source-bundle.json','geometry-contract.json','request.json','model-input.json'}
        aliases={name:GEOMETRY_PROTON_ALIASES.get(name,name) for name in names}
    else:
        prefix='' if request['source_case']=='Aalpha' else request['source_case']+'.'
        names={'model.proposed.json','geometry-contract.json','alpha-profile.csv',prefix+'heavyion.physics.inc',prefix+'source.par'}
        aliases={name:name for name in names}
    expected={name:geometry_digest(project/aliases[name]) for name in names}
    geometry_require(set(packet.get('inputs',{}))==names and binding.get('pure_source_inputs_sha256')==expected
                     and all(packet['inputs'][name].get('sha256')==digest for name,digest in expected.items()),
                     'Prospective source summary is not bound to the current pure source/geometry inputs')
    geometry_require(binding.get('input_file_aliases',aliases)==aliases,'Prospective input aliases differ')
    values=packet.get('source_features')
    geometry_require(isinstance(values,dict) and len(values)==13
                     and all(type(v) in (int,float) and GEOMETRY_math.isfinite(v) for v in values.values())
                     and registered.get('source_features')==values==binding.get('source_features'),
                     'Registered thirteen source quantities differ')
    identity=binding.get('registered_identity',{})
    geometry_require(type(registered.get('stored_bit')) is int and registered['stored_bit']==request['stored_bit']
                     and registered.get('gate_top_depth_nm')==model['geometry']['gate_top_depth_nm']
                     and registered.get('sn_junction_depth_nm')==model['doping']['sn_junction_depth_nm']
                     and registered.get('physics_manifest_sha256')==geometry_digest(project/'physics-manifest.json')
                     and all(registered.get(name)==value for name,value in identity.items()),
                     'Registered device/bit/physical identity differs')
    purpose=registered.get('purpose','dataset')
    geometry_require(purpose in ('dataset','qualification','diagnostic')
                     and purpose==binding.get('registration_purpose'),'Registered input purpose differs')
    origin_keys=('plan_sha256','design_sha256') if purpose=='dataset' else ('registration_request_sha256',)
    for name in origin_keys+('circuit_contract_sha256',):
        geometry_hash_value(registered.get(name),name)
    if purpose!='dataset':
        geometry_require(registered.get('source_case')==request['source_case']
                         and registered.get('numerical_variant')==request['variant'],
                         'Registered qualification source or numerical variant differs')
    else:
        geometry_require(request.get('variant','main')=='main' and registered.get('numerical_variant','main')=='main',
                         'Numerical refinement cannot enter formal training as a main row')
    verifier_name='source_features_v2.py' if alpha_v2 else 'source_features.py'
    for original,snapshot in ((verifier_name,'source-feature-verifier-snapshot.py'),
                              ('source_inputs.py','registered-input-verifier-snapshot.py')):
        geometry_require(binding.get('verification_code_sha256',{}).get(original)==geometry_digest(project/snapshot),
                         'Prospective verification implementation snapshot differs')
    if binding['schema']=='dram-see-v4-prospective-source-binding-r2':
        version=binding.get('source_feature_version',{})
        geometry_validate_source_version(project,version,dict(verifier='source-feature-verifier-snapshot.py',
            dispatcher='source-feature-dispatcher-snapshot.py',registry='source-feature-registry-snapshot.json',
            dependency_manifest='source-feature-dependencies-snapshot.json'))
        geometry_require(binding.get('verification_code_sha256',{}).get('source_feature_versions.py')==version['dispatcher']['sha256']
                         and packet.get('implementations',{}).get(verifier_name)==version['verifier'],
                         'Dispatcher and original registered verifier identities differ')
    source=geometry_json(project/('device-source-binding.json' if proton or alpha_v2 else 'source-contract.json'))
    geometry_require(source.get('prospective_source_binding_sha256')==geometry_digest(project/'source-feature-binding.json')
                     and source.get('prospective_source_features_sha256')==packet_sha,
                     'Source contract lacks prospective feature binding')
    if proton or alpha_v2:
        spec=geometry_json(project/'source-spec.json')
        geometry_require(spec.get('data_input_sha256')==geometry_digest(project/'data-input.json')
                         and spec.get('source_features_sha256')==packet_sha
                         and registered.get('particle')==packet.get('particle')==request.get('particle'),
                         'Current spec/data/source identity differs')
        if alpha_v2:
            geometry_require((project/'source-packet.json').read_bytes()==(project/'source-features.json').read_bytes(),
                             'Alpha v2 source and prospective packets differ')


def geometry_validate_source_version(project, version, snapshots):
    """Frozen identity evidence only; the preparer uses the fixed upstream dispatcher."""
    geometry_require(version.get('version_id') in ('v1-s2','v2-alpha-surface'),'Unsupported source verifier version')
    for name,snapshot in snapshots.items():
        geometry_require(version.get(name,{}).get('sha256')==geometry_digest(project/snapshot),
                         'Fixed source '+name+' snapshot differs')
    registry=geometry_json(project/snapshots['registry'])
    entries=[entry for entry in registry.get('versions',[]) if entry.get('version_id')==version['version_id']]
    geometry_require(len(entries)==1 and entries[0].get('verifier_sha256')==version['verifier']['sha256']
                     and entries[0].get('dependency_snapshot',{}).get('sha256')==version['dependency_manifest']['sha256'],
                     'Fixed registry does not bind original verifier/dependencies')


def geometry_validate_alpha_v2_binding(project,cfg,request,model,device):
    """New transient branch only; no producer or native-qualification inference."""
    packet=geometry_json(project/'source-packet.json');source=geometry_json(project/'source-contract.json')
    record=geometry_json(project/'device-source-binding.json');spec=geometry_json(project/'source-spec.json')
    window=geometry_json(project/'source-time-contract.json');role=geometry_json(project/'role-contract.json')
    active=request['source_case']=='Aalpha';packet_sha=geometry_digest(project/'source-packet.json')
    geometry_require(request.get('schema')=='dram-see-v4-controlled-device-request-r2'
                     and request.get('source_case') in ('A0','Aalpha') and request.get('particle')=='alpha'
                     and packet.get('schema')=='continuous-particle-source-features-v2'
                     and packet.get('version_id')==record.get('source_version')==spec.get('source_version')=='v2-alpha-surface'
                     and packet.get('particle')=='alpha' and source.get('schema')=='continuous-alpha-source-contract-v2'
                     and source==packet.get('source_definition') and source.get('source_amplitude')==1.
                     and record.get('source_active') is active
                     and record.get('original_packet_ref',{}).get('sha256')==packet_sha,
                     'Alpha v2 source/version/active context differs')
    expected={name:geometry_digest(project/name) for name in GEOMETRY_ALPHA_V2_INPUTS}
    geometry_require(set(packet.get('inputs',{}))==set(expected) and record.get('original_source_inputs_sha256')==expected
                     and all(packet['inputs'][name].get('sha256')==value for name,value in expected.items()),
                     'Alpha v2 original source or actual D3 bytes differ')
    for name in ('alpha-profile.csv','heavyion.physics.inc','source.par'):
        geometry_require(source.get('source_files_sha256',{}).get(name)==expected[name],'Alpha v2 native source bytes differ')
    geometry_require(spec.get('schema')=='continuous-particle-source-spec-v1' and spec.get('particle')=='alpha'
                     and spec.get('role')==('SIGNAL' if active else 'CONTROL')
                     and spec.get('stored_bit')==request['stored_bit']==role.get('stored_bit')
                     and spec.get('numerical_variant')==request['variant']==role.get('numerical_variant')
                     and spec.get('physics_manifest_sha256')==geometry_digest(project/'physics-manifest.json')
                     and spec.get('source_contract_sha256')==expected['source-contract.json']
                     and spec.get('source_packet_sha256')==role.get('source_packet_sha256')==packet_sha
                     and role.get('source_configured') is active,'Alpha v2 actual role or physical inputs differ')
    producer=record.get('actual_D3_binding',{})
    for name in ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256'):
        geometry_require(producer.get(name)==cfg.get(name),'Alpha v2 actual D3 identity differs: '+name)
    geometry_require(producer.get('model_sha256')==expected['model.proposed.json']
                     and producer.get('geometry_contract_sha256')==expected['geometry-contract.json'],
                     'Alpha v2 does not bind the actual D3 model/geometry')
    for name in ('physics.par','physics-manifest.json','Silicon.par','Oxide.par'):
        actual=geometry_digest(project/name)
        geometry_require(producer.get('physics_sha256',{}).get(name)==record.get('actual_physics_sha256',{}).get(name)==actual,
                         'Alpha v2 actual D3 physics differs: '+name)
    source_request=geometry_json(project/'source-request.json');conditions=packet.get('source_conditions',{})
    geometry_require(conditions.get('gate_top_depth_nm')==model['geometry']['gate_top_depth_nm']
                     and conditions.get('sn_junction_depth_nm')==model['doping']['sn_junction_depth_nm']
                     and conditions.get('energy_MeV')==source_request.get('energy_MeV') in (3,5,7)
                     and conditions.get('angle_deg')==source_request.get('theta_deg') in (0,30)
                     and record.get('original_data_design_notice')==packet.get('data_design'),
                     'Authoritative alpha v2 condition or original holdout notice differs')
    geometry_validate_source_version(project,record.get('source_feature_version',{}),dict(verifier='alpha-v2-verifier.py',
        dispatcher='alpha-v2-dispatcher.py',registry='alpha-v2-registry.json',dependency_manifest='alpha-v2-dependencies.json'))
    geometry_require(window.get('source_contract_sha256')==expected['source-contract.json']
                     and window.get('observation_window_s')==source['required_source_window_s']
                     and window.get('path')==source['path'] and window.get('required_field_checks')==source['required_native_checks']
                     and window.get('native_endpoint_semantics_verified') is False and window.get('native_source_qualified') is False
                     and role.get('source_time_contract_sha256')==geometry_digest(project/'source-time-contract.json'),
                     'Alpha v2 observation contract or qualification boundary differs')
    observed=GEOMETRY_re.findall(r'Plot\(FilePrefix="source_window" Time=\(Range=\(([^ ]+) ([^)]+)\)\)',device)
    geometry_require([[float(a),float(b)] for a,b in observed]==[source['required_source_window_s']],
                     'Alpha v2 actual source/control window differs from the original exact endpoints')


def geometry_validate_proton_binding(project, cfg, model, device):
    request=geometry_json(project/'controlled-request.json')
    record=geometry_json(project/'device-source-binding.json')
    bundle=geometry_json(project/'source-bundle.json')
    source=geometry_json(project/'source-contract.json')
    spec=geometry_json(project/'source-spec.json')
    role=geometry_json(project/'role-contract.json')
    manifest=geometry_json(project/'proton-source-input-manifest.json')
    geometry_require(record.get('schema')=='dram-see-v4-original-proton-source-binding-r1'
                     and record.get('source_manifest_sha256')==geometry_digest(project/'proton-source-input-manifest.json')
                     and manifest.get('schema')=='continuous-proton-inputs-v1'
                     and manifest.get('kind')=='complete_native_proton_event_source_bundle',
                     'Original proton source manifest differs')
    expected_role='CONTROL' if request['source_case']=='A0' else request['source_case']
    geometry_require(spec.get('schema')=='continuous-particle-source-spec-v1' and spec.get('particle')=='proton'
                     and spec.get('role')==expected_role and spec.get('stored_bit')==request['stored_bit']
                     and role.get('stored_bit')==request['stored_bit']
                     and spec.get('numerical_variant')==request['variant']==role.get('numerical_variant')
                     and role.get('case')==request['source_case'] and role.get('source_configured')==(expected_role=='SIGNAL')
                     and spec.get('physics_manifest_sha256')==geometry_digest(project/'physics-manifest.json')
                     and spec.get('source_contract_sha256')==geometry_digest(project/'source-contract.json'),
                     'Proton role, physical model or numerical identity differs')
    original=record.get('original_source_sha256',{})
    for name,expected in original.items():
        geometry_require(geometry_digest(geometry_path(project,name))==expected,'Original proton source bytes changed: '+name)
    for name,expected in manifest.get('files',{}).items():
        actual_name=GEOMETRY_PROTON_ALIASES.get(name,name)
        geometry_require(original.get(actual_name)==expected==geometry_digest(geometry_path(project,actual_name)),
                         'Original source package member differs: '+name)
    for name,expected in bundle.get('source_payload_sha256',{}).items():
        geometry_require(geometry_digest(geometry_path(project,name))==expected,'Original event payload differs: '+name)
    event=bundle.get('binding',{})
    geometry_require(event==record.get('original_event_binding')==geometry_json(project/'event-binding.json')
                     and event.get('schema')=='continuous-proton-native-event-binding-v1' and event.get('particle')=='proton'
                     and bundle.get('schema')=='continuous-proton-source-bundle-v1'
                     and source.get('schema')=='continuous-proton-heavyion-candidate-v1'
                     and set(GEOMETRY_PROTON_PAYLOAD)|{'source-reference-pre-clock.json'} <= set(bundle.get('source_payload_sha256',{}))
                     and bundle.get('source_contract_sha256')==geometry_digest(project/'source-contract.json')
                     and source.get('event_id')==event.get('transport_event_id')
                     and source.get('epoch_s')==event.get('source_time_s'), 'Original complete event identity differs')
    geometry_require(type(event.get('original_ssh_exit_code')) is int
                     and all(type(event.get(name)) is int and event[name]==0 for name in
                         ('original_task_exit_code','original_remote_exit_code','original_collection_exit_code')),
                     'Original proton event has unknown/nonzero task or collection exit')
    for key,name in (('geometry_contract','transport-geometry-contract.json'),('model_input','transport-model-input.json'),
                     ('request','transport-request.json')):
        geometry_require(event.get(key,{}).get('sha256')==geometry_digest(project/name),'Transport alias identity differs: '+name)
    producer=record.get('actual_D3_binding',{})
    for key in ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256'):
        geometry_require(producer.get(key)==cfg.get(key),'Proton actual D3 binding differs: '+key)
    for key,name in (('geometry_contract_sha256','geometry-contract.json'),('model_sha256','model.proposed.json')):
        geometry_require(producer.get(key)==geometry_digest(project/name),'Actual device input differs: '+name)
    for name in ('physics.par','physics-manifest.json','Silicon.par','Oxide.par'):
        geometry_require(producer.get('physics_sha256',{}).get(name)==geometry_digest(project/name),'Actual D3 physics differs: '+name)
    transport=geometry_json(project/'transport-geometry-contract.json')
    transport_model=geometry_json(project/'transport-model-input.json')
    actual=geometry_json(project/'geometry-contract.json')
    ignored={'schema','status','native_qualified','size_id','legacy_size_label','mesh'}
    geometry_require(transport.get('schema')=='continuous-bcat-proton-geometry-v1'
                     and transport.get('coordinate_transform')=='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um'
                     and transport.get('gate_transport_material')=='G4_Galactic'
                     and {k:v for k,v in transport['geometry'].items() if k not in ignored}=={k:v for k,v in actual.items() if k not in ignored}
                     and transport_model['geometry']==model['geometry'] and transport_model['doping']==model['doping'],
                     'Transport/device physical geometry, doping or coordinate definition differs')
    geometry_validate_source_version(project,record.get('source_feature_version',{}),dict(verifier='proton-source-verifier.py',
        dispatcher='proton-source-dispatcher.py',registry='proton-source-registry.json',dependency_manifest='proton-source-dependencies.json'))
    window=geometry_json(project/'source-time-contract.json')
    geometry_require(source.get('kernel')==dict(width_um=.03,temporal_sigma_s=2e-12,source='original isotropic Gaussian line-convolution')
                     and source.get('eV_per_pair')==3.6 and window.get('late_deposits_clipped') is False
                     and role.get('source_time_contract_sha256')==geometry_digest(project/'source-time-contract.json')
                     and role.get('source_bundle_sha256')==geometry_digest(project/'source-bundle.json'),
                     'Proton kernel, observation or role binding differs')
    fragments=GEOMETRY_json.loads((project/'fragments.json').read_text(encoding='utf-8'))
    geometry_require(type(source.get('fragment_count')) is int and source['fragment_count']==len(fragments),
                     'Proton complete fragment count differs')
    if fragments:
        bounds=source.get('source_time_bounds_s');required=source.get('required_source_window_s')
        geometry_require(isinstance(bounds,list) and len(bounds)==2
                         and required==[bounds[0]-16e-12,bounds[1]+16e-12]
                         and 8.1e-9<required[0]<required[1]<19.9e-9
                         and window.get('source_present') is True and expected_role!='STRUCTURAL_ZERO',
                         'Complete proton envelope/positive role differs')
    else:
        required=[source['epoch_s'],19.9e-9]
        geometry_require(expected_role!='SIGNAL' and source.get('required_source_window_s') is None
                         and source.get('source_time_bounds_s') is None and window.get('source_present') is False
                         and (project/'sources.dat').read_bytes()==b'NUCLEAR_CLOSURE_SOURCE_V1 0\n'
                         and not (project/'heavyion.physics.inc').read_bytes().strip()
                         and not (project/'source.par').read_bytes().strip(), 'Structural-zero source is not absent')
        if expected_role=='STRUCTURAL_ZERO':
            geometry_require(geometry_json(project/'data-input.json').get('zero_source_comparison_window_s')==required,
                             'Registered structural-zero comparison interval differs')
    geometry_require(window.get('observation_window_s')==required,'Actual observation interval differs from complete source')
    observed=GEOMETRY_re.findall(r'Plot\(FilePrefix="source_window" Time=\(Range=\(([^ ]+) ([^)]+)\)\)',device)
    geometry_require([[float(a),float(b)] for a,b in observed]==[required],
                     'Actual device does not observe the full original source/comparison interval')


def geometry_alpha_restart_module():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_restart_2d.py')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='c115c00f1e1670b989fe65fe85d81eee9d0bea3807c5ef2581b5ee21e9d5b039':
        raise ValueError('fixed alpha restart runtime changed')
    spec=importlib.util.spec_from_file_location('geometry_alpha_restart',str(path))
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_a0_restart_module():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_a0_restart_2d.py')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='825a0229cdfbf07effc32344a0d8f66459babf0069347c469b00969640e00a9d':
        raise ValueError('fixed A0 restart runtime changed')
    spec=importlib.util.spec_from_file_location('geometry_a0_restart_2d',str(path))
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_operating_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='ea81cbfedef56c2e2ba90be02b31247a4e0e5733ba54d9fcd56850e0fcc654df',
                     'fixed source-segment-frame A0 runtime changed')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_operating',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_alpha_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_alpha_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='5b1eb3c3a3e5389aa9b702ffb199e66210408d9db46589fa8251de9c956095aa',
                     'fixed source-segment-frame particle runtime changed: source_segment_frames_alpha_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_alpha_module',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_alpha_control_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_alpha_controls_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='af3b34b5fadb24356eca270d63d948a08f43cdad60914c49b29732d64d34144a',
                     'fixed source-segment-frame particle runtime changed: source_segment_frames_alpha_controls_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_alpha_control_module',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_proton_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_proton_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='6e2f0b65afb8c95d0bbd51d7c6f98ed10d1294511f008e3baa26bc429c5895bb',
                     'fixed source-segment-frame particle runtime changed: source_segment_frames_proton_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_proton_module',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_proton_refinement_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_proton_refinement_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='0e76c6e1efda1953b362af93d7de71b131c86eb82844db1f93a7c393bee88c2d',
                     'fixed source-segment-frame particle runtime changed: source_segment_frames_proton_refinement_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_proton_refinement_module',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_source_segment_frames_proton_controls_module():
    path=GEOMETRY_Path(__file__).with_name('source_segment_frames_proton_controls_2d.py')
    raw=path.read_bytes()
    geometry_require(not path.is_symlink() and GEOMETRY_hashlib.sha256(raw).hexdigest()=='5dd27cd2d640917b0605bcda372d8d1923ab6854bcddac98f38948818a524b65',
                     'fixed source-segment-frame particle runtime changed: source_segment_frames_proton_controls_2d.py')
    spec=GEOMETRY_importlib.spec_from_file_location('geometry_source_segment_frames_proton_controls_module',str(path))
    module=GEOMETRY_importlib.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def geometry_admit(project, spec, runner_sha256):
    project = GEOMETRY_Path(project)
    cfg = spec.get('s2_geometry')
    if cfg is None:
        return None
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-source-segment-frames-alpha-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_alpha_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-source-segment-frames-alpha-controls-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_alpha_control_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-source-segment-frames-proton-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_proton_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-source-segment-frames-proton-refinement-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_proton_refinement_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-source-segment-frames-proton-control-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_proton_controls_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_segment_frames_branch')=='dram-see-v4-source-segment-frames-operating-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_source_segment_frames_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('alpha_restart_branch')=='dram-see-v4-parameterized-alpha-restored-suffix-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_restart_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('a0_restart_branch')=='dram-see-v4-parameterized-a0-restored-suffix-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_a0_restart_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('operating_voltage_branch')=='dram-see-v4-operating-voltage-dc-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_operating_voltage_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-controls-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_parameterized_alpha_control_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-multicondition-control-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_proton_multicondition_controls_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-multicondition-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_proton_multicondition_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-multicondition-refinement-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_proton_multicondition_refinement_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-refinement-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_proton_refinement_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-control-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_parameterized_proton_controls_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-proton-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_parameterized_proton_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-partition-controls-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_partition_control_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-partition-refinement-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_partition_refinement_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-multicondition-controls-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_multicondition_control_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-multicondition-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_multicondition_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-native-partition-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_native_partition_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-parameterized-alpha-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_parameterized_alpha_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('parameterized_operating_branch')=='dram-see-v4-parameterized-operating-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_parameterized_operating_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-operating-alpha-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_operating_alpha_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('operating_transient_branch')=='dram-see-v4-operating-transient-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_operating_transient_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('operating_branch')=='dram-see-v4-operating-dc-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_operating_2d_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('source_branch')=='dram-see-v4-alpha-native-2d-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_alpha_2d_module().admit(project,spec,runner_sha256,api)
    if isinstance(cfg,dict) and cfg.get('dimension_branch')=='dram-see-v4-2d-control-r1':
        api=GEOMETRY_Namespace(GEOMETRY_SCHEMA=GEOMETRY_SCHEMA,geometry_context=geometry_context,
                              geometry_input_hashes=geometry_input_hashes,geometry_path=geometry_path)
        return geometry_2d_module().admit(project,spec,runner_sha256,api)
    geometry_require(isinstance(cfg, dict) and cfg.get('schema') == GEOMETRY_SCHEMA, 'Wrong current geometry context')
    geometry_require(cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
                     and spec.get('execution_enabled') is True, 'Not a native execution project')
    geometry_require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve())
                     and not (project / 'SYNTHETIC_NOT_NATIVE').exists(), 'Synthetic cannot be submitted as native')
    role = cfg.get('role_id')
    geometry_require(isinstance(role, str) and (role in ('B1-D2', 'B1-D3') or
                     GEOMETRY_re.fullmatch(r'B1-A0-(?:proton-|alpha-v2-)?(main|mesh|time)-b[01]|B2-(A|A2)-(main|mesh|time)-b[01]|B2-(Z|H|SPLIT)-b[01]|B3-(P|PZERO)-(main|mesh|time)-b[01]', role))
                     and spec.get('role') == role and spec.get('native_threads') == 1 and spec.get('native_cores') == 1,
                     'Role/single-core/single-thread differs')
    run_id = cfg.get('run_id')
    geometry_require(isinstance(run_id, str) and GEOMETRY_re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id), 'Invalid run ID')
    execution = geometry_context(project, cfg, runner_sha256)
    hashes = geometry_input_hashes(project)
    required = {'project.json', 'geometry_bridge.py', 'mesh_resource_guard.py', 'resource-policy.json',
                'device.cmd', 'task-authorization.json', 'geometry-contract.json', 'physics.par', 'physics-manifest.json',
                'model.proposed.json', 'Silicon.par', 'Oxide.par'}
    physics = geometry_json(project / 'physics-manifest.json')
    model = geometry_json(project / 'model.proposed.json')
    mesh_inputs={name:geometry_path(project,name).read_bytes() for name in
                 ('model.proposed.json','geometry-contract.json')+tuple(n for n in GEOMETRY_MESH_POLICY_FILES if n in hashes)}
    if any(name in hashes for name in GEOMETRY_MESH_POLICY_FILES):
        required|=set(GEOMETRY_MESH_POLICY_FILES)
        if cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry'):
            mesh_inputs['geometry-with-measurements.scm']=geometry_path(project,'geometry-with-measurements.scm').read_bytes()
    selected_mesh=geometry_validate_mesh_policy_payload(mesh_inputs,cfg,
        require_sde=bool(set(GEOMETRY_MESH_POLICY_FILES)&set(hashes)) and cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry'))
    geometry_require(physics.get('schema') == 'dram-see-v4-physics-card-r2'
                     and physics.get('assumption_id') == model.get('physics_assumption_id')
                     == 'dram-see-v4-physics-local-hurkx-r1'
                     and physics.get('btbt_model') == 'Hurkx' and physics.get('btbt_density_correction') == 'None'
                     and physics.get('btbt_postprocessing') is False
                     and physics.get('btbt_explicit_overrides')
                     == model.get('materials_and_physics', {}).get('selected_btbt', {}).get('parameters'),
                     'Current BTBT model/assumption binding differs')
    device = geometry_path(project, 'device.cmd').read_text(encoding='utf-8')
    geometry_require(device.count('Band2Band(Model=Hurkx DensityCorrection=None)') == 1
                     and 'Band2Band(Model=NonlocalPath)' not in device,
                     'Device selector differs from explicit current local BTBT branch')
    for name in ('Silicon.par', 'Oxide.par'):
        geometry_require(physics.get('default_cards_sha256', {}).get(name) == geometry_digest(project / name),
                         'Installed material card changed: ' + name)
    if 'controlled-request.json' in hashes:
        required |= {'controlled-request.json', 'case_contract.py', 'numerical-method.json'}
        request=geometry_json(project/'controlled-request.json')
        if cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry'):
            geometry_require(request.get('mesh_policy')==(selected_mesh['policy_id'] if selected_mesh else None),
                             'Producer request did not explicitly select its original mesh policy')
        proton=request.get('particle')=='proton'
        alpha_v2=request.get('source_version')=='v2-alpha-surface'
        if cfg.get('mode') == 'reuse':
            required |= {'source-spec.json','source-contract.json','parameter-binding.json'}
            if alpha_v2:
                required|=set(GEOMETRY_ALPHA_V2_INPUTS)|{'source-packet.json','source-time-contract.json','device-source-binding.json',
                    'alpha-v2-feature-contract.json','alpha-v2-verifier.py','alpha-v2-dispatcher.py','alpha-v2-registry.json',
                    'alpha-v2-dependencies.json','heavyion.plot.inc','heavyion.currentplot.inc','role-contract.json'}
                geometry_validate_alpha_v2_binding(project,cfg,request,model,device)
            elif proton:
                required |= set(GEOMETRY_PROTON_PAYLOAD)|set(GEOMETRY_PROTON_ALIASES.values())|{
                    'role-contract.json','source-bundle.json','event-binding.json','source-reference-pre-clock.json',
                    'device-source-binding.json','source-time-contract.json','proton-source-input-manifest.json',
                    'proton-source-verifier.py','proton-source-dispatcher.py','proton-source-registry.json','proton-source-dependencies.json'}
                geometry_validate_proton_binding(project,cfg,model,device)
            elif request.get('source_case')=='A0' and geometry_json(project/'source-spec.json').get('schema')=='continuous-particle-source-spec-v1':
                required|={'controlled-parameters.json'}
                geometry_validate_controlled_a0(project,cfg,request)
            else:
                required |= {'field-contract.json','alpha-reference.json','alpha-profile.csv'}
        geometry_validate_current_case(project, cfg, hashes, model, device)
        if cfg.get('mode')=='reuse' and not role.startswith('B1-A0'):
            required|={'source-features.json','source-feature-contract.json','source-feature-binding.json',
                       'data-input.json','source-feature-verifier-snapshot.py','registered-input-verifier-snapshot.py'}
            if geometry_json(project/'source-feature-binding.json').get('schema')=='dram-see-v4-prospective-source-binding-r2':
                required|={'source-feature-dispatcher-snapshot.py','source-feature-registry-snapshot.json',
                           'source-feature-dependencies-snapshot.json'}
            geometry_validate_prospective_binding(project,model)
    else:
        geometry_require(role in ('B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1'),
                         'New role requires the structured controlled request')
    policy = geometry_json(project / 'resource-policy.json')
    geometry_require(policy.get('schema') == 'dram-see-v4-actual-resource-policy-r1' and policy.get('role') == role,
                     'Current resource observation policy differs')
    imports = {}
    if role in ('B1-D2', 'B1-D3'):
        inherited = cfg.get('mode') == 'produce_from_mesh'
        metadata = cfg.get('mode') == 'produce_from_metadata'
        dc_reuse=cfg.get('mode')=='produce_from_geometry'
        geometry_require(cfg.get('mode') in ('produce','produce_from_mesh','produce_from_metadata','produce_from_geometry') and cfg.get('producer_run_id') == run_id
                         and (not (inherited or metadata or dc_reuse) or role == 'B1-D3'), 'Producer identity differs')
        geometry_require([(s.get('tool'), s.get('args')) for s in spec.get('steps', [])] == list(GEOMETRY_STEPS[5:] if dc_reuse else GEOMETRY_STEPS[4:] if metadata else GEOMETRY_STEPS[2:] if inherited else GEOMETRY_STEPS),
                         'Producer must preserve the original serial step order')
        required |= {'dfise_observer.py','measurement-plan.json','geometry-with-measurements.scm'}
        if not dc_reuse:required|={'evaluate.py','observe_tdr_topology.tcl','measure-geometry.tcl'}
        plan = geometry_json(project / 'measurement-plan.json')
        geometry_require(plan.get('schema') == 's2-geometry-measurement-plan-r1' and plan.get('role_id') == role
                         and plan.get('dimension') == (2 if role == 'B1-D2' else 3)
                         and plan.get('geometry_contract_sha256') == geometry_digest(project / 'geometry-contract.json'),
                         'Measurement plan/geometry identity differs')
        if inherited:
            required |= {'mesh_continuation.py','mesh-source-binding.json','tdx_hash_sha256.tcl'}
            binding = geometry_mesh_module().verify_folder(project,cfg,allow_deferred=True)
            imports = {name:row['sha256'] for name,row in binding['imports'].items()}
            required |= set(imports)|set(binding['proofs_sha256'])
            geometry_require('tdr-hash-provider.csv' in spec['steps'][0].get('outputs',[]),
                             'Continuation must retain its actual TDX hash-provider output')
        if metadata:
            required|={'metadata_continuation.py','mesh_continuation.py','metadata-source-binding.json',
                       'mesh-source-binding.json','hdf5_observer.py','tdx_hash_sha256.tcl'}
            module=geometry_metadata_module()
            binding=module.verify_folder(project,cfg)
            imports=module.evidence_hashes(module.FolderReader(project),binding)
            required|=set(imports)
            geometry_require('geometry-hash-provider.csv' in spec['steps'][0].get('outputs',[]),
                             'Metadata continuation must retain actual SVisual hash-provider output')
        if dc_reuse:
            module=geometry_dc_module();binding,selector=module.verify_folder(project,cfg)
            imports=module.evidence_hashes(module.metadata_module().FolderReader(project),binding)
            required|=set(module.RUNTIME_FILES)|set(imports)
            geometry_require(spec['steps'][0].get('outputs')==list(module.SDE_OUTPUTS),
                             'DC-only continuation must preserve its actual device outputs')
        if not dc_reuse and 'tdx_hash_sha256.tcl' in geometry_path(project,'observe_tdr_topology.tcl').read_text(encoding='utf-8'):
            required.add('tdx_hash_sha256.tcl')
    else:
        geometry_require(cfg.get('mode') == 'reuse' and cfg.get('producer_run_id') != run_id, 'Transient requires original D3 identity')
        geometry_require([(s.get('tool'), s.get('args')) for s in spec.get('steps', [])] == [('sdevice', ['device.cmd'])],
                         'Transient must not rebuild its D3 mesh')
        source_bundle=geometry_source_bundle(project,cfg,execution)
        imports=source_bundle['exports']
        if 'dc_completed_binding_sha256' in source_bundle:
            module=geometry_dc_module();required|=set(module.RUNTIME_FILES)
            for name,raw in source_bundle['runtime_files'].items():
                geometry_require(geometry_path(project,name).read_bytes()==raw,'Frozen completed DC verifier differs: '+name)
        required |= set(imports)
    geometry_require(required <= set(hashes), 'Mandatory input absent from manifest')
    for name, expected in hashes.items():
        path = geometry_path(project, name)
        if not path.exists() and name in imports:
            geometry_require(imports[name] == expected, 'Deferred D3 import differs: ' + name)
        else:
            geometry_require(geometry_digest(path) == expected, 'Frozen input changed: ' + name)
            if name in imports:
                geometry_require(imports[name] == expected, 'D3 import/current input conflict: ' + name)
    return cfg


def geometry_stage_reuse(project, cfg, synthetic_fixture=False):
    project = GEOMETRY_Path(project)
    geometry_require(cfg.get('mode') == 'reuse', 'Only a transient role may stage D3 geometry')
    bundle = geometry_source_bundle(project, cfg, synthetic_fixture=synthetic_fixture)
    hashes = geometry_input_hashes(project)
    with GEOMETRY_tarfile.open(str(bundle['archive']), 'r:*') as archive:
        members = geometry_tar_members(archive)
        for name, expected in sorted(bundle['exports'].items()):
            geometry_require(hashes.get(name) == expected, 'D3 import absent from frozen input: ' + name)
            target = geometry_path(project, name)
            if target.exists():
                geometry_require(geometry_digest(target) == expected, 'Existing D3 input conflicts: ' + name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if name in bundle.get('generated_files',{}):
                geometry_write(target,bundle['generated_files'][name])
                geometry_require(geometry_digest(target)==expected,'Generated DC proof bytes differ: '+name)
                continue
            external=bundle.get('external_files',{}).get(name)
            if external:
                geometry_require(geometry_digest(external['path'])==expected==external['sha256'],'Original DC proof changed: '+name)
                source=GEOMETRY_Path(external['path']).open('rb')
            else:
                source=archive.extractfile(members[bundle.get('export_members',{}).get(name,name)])
            with source, target.open('xb') as destination:
                for block in iter(lambda: source.read(1048576), b''):
                    destination.write(block)
            geometry_require(geometry_digest(target) == expected, 'Imported D3 bytes differ: ' + name)
    geometry_require(geometry_digest(bundle['archive']) == bundle['archive_sha256'], 'D3 archive changed during import')
    return cfg


def geometry_runtime(folder, run_id):
    folder = GEOMETRY_Path(folder)
    geometry_require(folder.resolve().name == run_id, 'Original runtime directory does not match run ID')
    execution = geometry_json(folder / 'execution-context.json')
    cfg = geometry_admit(folder, geometry_json(folder / 'project.json'), execution.get('expected_runner_sha256'))
    geometry_require(cfg and cfg['mode'] in ('produce','produce_from_mesh','produce_from_metadata') and cfg['run_id'] == run_id, 'Runtime producer differs')
    return cfg


def geometry_tcl_word(value):
    value = str(value)
    for old, new in (('\\', '\\\\'), ('"', '\\"'), ('$', '\\$'), ('[', '\\['), (']', '\\]'), ('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t')):
        value = value.replace(old, new)
    return '"' + value + '"'


def geometry_prepare(folder, run_id):
    folder = GEOMETRY_Path(folder)
    cfg=geometry_runtime(folder, run_id)
    geometry_exit_sources(folder, complete=False)
    mesh = geometry_path(folder, 'cell_msh.tdr')
    geometry_require(mesh.stat().st_size > 0, 'Empty native mesh')
    descriptor = ' '.join(geometry_tcl_word(v) for v in (str(mesh.resolve()), geometry_digest(mesh), run_id)) + '\n'
    geometry_write(folder / 'mesh-input.tcldata', descriptor.encode('utf-8'))
    metadata=cfg['mode']=='produce_from_metadata'
    geometry_write_json(folder / ('current-mesh-before.json' if metadata else 'tdx-source-before.json'), dict(
        schema='dram-see-v4-current-mesh-integrity-r1' if metadata else 'dram-see-v4-tdx-source-identity-r1',
        phase='BEFORE', run_id=run_id, path=str(mesh.resolve()), sha256=geometry_digest(mesh)))
    return 0


def geometry_finalize(folder, run_id, synthetic_fixture=False):
    folder = GEOMETRY_Path(folder)
    try:
        geometry_require(synthetic_fixture is False, 'Native bridge cannot finalize synthetic observations')
        cfg = geometry_runtime(folder, run_id)
        geometry_require(not (folder / 'geometry-validation.json').exists()
                         and not (folder / 'geometry-evaluation').exists(), 'Prior geometry evaluation must be preserved')
        sources = geometry_exit_sources(folder)
        mesh = geometry_path(folder, 'cell_msh.tdr')
        metadata=cfg['mode']=='produce_from_metadata'
        active_mesh=metadata and cfg.get('mesh_representation')==GEOMETRY_ACTIVE_REPRESENTATION
        geometry_write_json(folder / ('current-mesh-after.json' if metadata else 'tdx-source-after.json'), dict(
            schema='dram-see-v4-current-mesh-integrity-r1' if metadata else 'dram-see-v4-tdx-source-identity-r1',
            phase='AFTER', run_id=run_id, path=str(mesh.resolve()), sha256=geometry_digest(mesh)))
        plan = geometry_json(folder / 'measurement-plan.json')
        context = dict(schema=GEOMETRY_ACTIVE_CONTEXT if active_mesh else GEOMETRY_HDF5_CONTEXT if metadata else 's2-geometry-observation-context-r1', synthetic=False, origin='native_pipeline',
                       role_id=cfg['role_id'], dimension=plan['dimension'], producer_run_id=run_id,
                       plan_sha256=geometry_digest(folder / 'measurement-plan.json'),
                       geometry_contract_sha256=plan['geometry_contract_sha256'],
                       sde_deck_sha256=geometry_digest(folder / 'geometry-with-measurements.scm'),
                       svisual_script_sha256=geometry_digest(folder / 'measure-geometry.tcl'),
                       mesh_sha256=geometry_digest(folder / 'cell_msh.tdr'),
                       raw_exit_sha256={name: row['canonical_sha256'] for name, row in sources.items()})
        if metadata:
            context.update(geometry_observation_backend=GEOMETRY_HDF5_BACKEND,
                metadata_source_binding_sha256=cfg['metadata_source_binding_sha256'],
                inherited_step_indices=[1,2,3],actual_geometry_step_indices=[5])
            if active_mesh:
                context.update({n:cfg[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
        for name, row in sources.items():
            context[name.replace('-exit-code.txt', '_exit_code').replace('-', '_')] = row['observed_exit_code']
        geometry_write_json(folder / 'observation-context.json', context)
        geometry_write_json(folder / 'geometry-exit-sources.json', dict(schema='s2-geometry-exit-sources-r1', sources=sources))
        module_spec = GEOMETRY_importlib.spec_from_file_location('geometry_current_evaluator', str(folder / 'evaluate.py'))
        evaluator = GEOMETRY_importlib.module_from_spec(module_spec)
        module_spec.loader.exec_module(evaluator)
        report = evaluator.evaluate(folder / 'measurement-plan.json', folder, folder / 'geometry-evaluation',
                                    synthetic=False, execution_context_path=folder / 'execution-context.json')
        bindings = {}
        for name in ('execution-context.json', 'input-manifest.json', 'task-authorization.json'):
            destination = 'geometry-producer-bindings/' + name
            geometry_write(geometry_path(folder, destination), geometry_path(folder, name).read_bytes())
            bindings[destination] = geometry_digest(geometry_path(folder, destination))
        additions = dict(bindings)
        additions['geometry-exit-sources.json'] = geometry_digest(folder / 'geometry-exit-sources.json')
        for row in sources.values():
            additions[row['source']] = row['source_sha256']
        if 'tdx_hash_sha256.tcl' in geometry_input_hashes(folder):
            geometry_validate_hash_provider((folder/'tdr-hash-provider.csv').read_bytes())
            additions['tdr-hash-provider.csv'] = geometry_digest(folder/'tdr-hash-provider.csv')
        if metadata:
            module=geometry_metadata_module();source_binding=module.verify_folder(folder,cfg)
            additions.update(module.evidence_hashes(module.FolderReader(folder),source_binding))
            geometry_validate_hash_provider((folder/'geometry-hash-provider.csv').read_bytes())
            additions['geometry-hash-provider.csv']=geometry_digest(folder/'geometry-hash-provider.csv')
            report.update(metadata_source_binding_sha256=cfg['metadata_source_binding_sha256'],
                geometry_observation_backend=GEOMETRY_HDF5_BACKEND,inherited_step_indices=[1,2,3],actual_geometry_step_indices=[5])
            if active_mesh:
                report.update({n:cfg[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
        if cfg['mode'] == 'produce_from_mesh':
            source_binding = geometry_mesh_module().verify_folder(folder,cfg)
            additions['mesh-source-binding.json'] = geometry_digest(folder/'mesh-source-binding.json')
            additions.update(source_binding['proofs_sha256'])
            report['mesh_source_binding_sha256'] = additions['mesh-source-binding.json']
            report['inherited_step_indices'] = [1,2]
            report['actual_geometry_step_indices'] = [3,4,5]
        if metadata:
            geometry_require(all(report['evidence_sha256'][n]==additions[n] for n in set(additions)&set(report['evidence_sha256'])),
                             'Producer binding bytes conflict with native HDF5 evidence')
        else:
            geometry_require(not set(additions) & set(report['evidence_sha256']), 'Producer bindings conflict with evidence')
        report['evidence_sha256'].update(additions)
        report['original_exit_sources'] = sources
        report['producer_context_bindings_sha256'] = bindings
        report['integration_schema'] = GEOMETRY_SCHEMA
        geometry_require(report.get('synthetic') is False and report.get('native_qualified') is False
                         and report.get('origin') == 'native_pipeline', 'Evaluator origin/qualification differs')
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
            return 0
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
