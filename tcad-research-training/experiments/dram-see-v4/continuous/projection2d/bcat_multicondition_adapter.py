"""Versioned host replay of original BCAT batches and unchanged 20 nm mathematics.

No native tool is launched. Legacy v1 packages retain the complete 139164 replay;
v2 requires the original per-geometry build, original operation and all raw rows.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/proton-multicondition-runtime-r1'
VERSION = 'dram-see-v4-bcat-multicondition-2d-r1'
MANIFEST_SCHEMA = VERSION + '-batch'
BINDING_SCHEMA = VERSION + '-binding'
SOURCE_SCHEMA = VERSION + '-source-inputs'
SOURCE_MANIFEST_SCHEMA = VERSION + '-source-manifest'
DEVELOPMENT = {
    'proton-T01': (70, 50, 0), 'proton-T02': (70, 100, 0),
    'proton-T03': (80, 50, 0), 'proton-T04': (80, 100, 0),
    'proton-T05': (70, 50, 30), 'proton-T06': (80, 100, 30)}
DEPS = {
    'native': ('projection2d/bcat_native_adapter.py', '139164c45e0673e13f80cf5821320fce1313a4f3a71e4f760b4344f94179c6dd'),
    'source': ('projection2d/prepare_pmi_candidate.py', 'a9446fe3e8fa04f634b82e965eb1a0dbad819b5598f373121f877c02019efcfe'),
    'transport_v2': ('proton/transport_prepare_v2.py', 'fac600ae7ad11a258db2d1bbd312411511ea46987c1269e476bcd840263ecf61'),
    'geometry_v2': ('proton/proton_geometry_v2.py', '09aa8966d9320e0fa1981a516e5a78a2d228a0a74ca9199534efffe472f9c394'),
    'common_v2': ('proton/proton_common_v2.py', '6e0fe5c77a0efcc1b4d8dfb93216f8126c2bc577ffee80cf124d64e4f8fa90c4'),
}
MODULES = {}


def require(ok, message):
    if not ok:
        raise ValueError('BCAT multicondition: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf8')


def read(path):
    return json.loads(Path(path).read_bytes(),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + value)))


def ref(path):
    path = Path(path).resolve()
    require(path.is_file() and not path.is_symlink() and ROOT in path.parents, 'original workspace file required')
    return dict(path=str(path), sha256=sha(path.read_bytes()))


def fixed(name):
    relative, expected = DEPS[name]
    path = HERE.parent / relative
    raw = path.read_bytes()
    require(not path.is_symlink() and sha(raw) == expected, 'fixed dependency changed: ' + relative)
    if name not in MODULES:
        spec = importlib.util.spec_from_file_location('_bcat_multicondition_' + name, path)
        module = importlib.util.module_from_spec(spec)
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        MODULES[name] = module
    return MODULES[name]


def dependencies():
    for name in DEPS:
        fixed(name)
    return {name: ref(HERE.parent / relative) for name, (relative, _) in DEPS.items()}


def condition_identity(condition_id, gate, energy, angle):
    require(condition_id in DEVELOPMENT and (gate, energy, angle) == DEVELOPMENT[condition_id],
        'condition is outside this versioned six-train-condition provider; no final-stage provider is implied')
    return dict(condition_id=condition_id, particle='proton', gate_top_depth_nm=gate,
        sn_junction_depth_nm=87, energy_MeV=energy, angle_deg=angle, phi_deg=180, effective_width_nm=20)


def validate_v2_metadata(request, metadata, geometry, model, semantic, B, T):
    """New format boundary; never relabel a v1/S2 request or replace its validator."""
    N = fixed('native')
    require(request.get('schema') == 'continuous-proton-transport-request-v2'
        and request.get('version_id') == 'v2-proton-bcat', 'actual v2 request required')
    require(geometry.get('schema') == 'continuous-bcat-proton-geometry-v2'
        and geometry.get('version_id') == 'v2-proton-bcat'
        and geometry.get('device_parameters') == semantic, 'exact v2 compiled geometry semantics required')
    cid = request['condition_id']
    condition_identity(cid, model['geometry']['gate_top_depth_nm'], request['energy_MeV'], request['theta_deg'])
    require(semantic['gate_top_depth_nm'] == request['gate_top_depth_nm']
        and semantic['sn_junction_depth_nm'] == request['sn_junction_depth_nm'] == 87
        and semantic['active_width_nm'] == 20, 'compiled model is not the requested geometry/width')
    row = T.condition(cid, request['seed'], development=True)
    require(request['matrix_row'] == row and request['original_split'] == row['split'] == 'train'
        and request['final_holdout'] is False, 'original request matrix identity differs')
    require(metadata['schema'] == 'v4-matched-transport-r1' and metadata['units'] == N.UNITS,
        'actual native units/schema differ')
    require(metadata['geometry'] == geometry and metadata['geometry_id'] == model['model_id'],
        'original embedded native geometry differs')
    require(request['mode'] == metadata['mode'] == 'normal'
        and request['arm'] == metadata['arm'] == 'H' and metadata['primary_particle'] == 'proton',
        'complete proton H transport required')
    for key, native in (('seed', 'seed'), ('event_count', 'events_requested'),
            ('energy_MeV', 'energy_MeV'), ('theta_deg', 'angle_deg'), ('label', 'request_label')):
        require(request[key] == metadata[native], 'actual request/native mismatch: ' + key)
    require(type(request['event_count']) is int and request['event_count'] > 0
        and type(request['seed']) is int and request['seed'] > 0, 'actual positive request count/seed required')
    require(request['phi_deg'] == 180 and request['target_um'] == [-.052, 0., 0.],
        'original incidence point/azimuth differs')
    require(metadata['requested_threads'] == 1 and metadata['multithreaded_run_manager'] is False
        and metadata['run_manager'] == 'G4RunManager' and metadata['geant4_version_number'] == 1073,
        'original single-thread Geant4 identity differs')
    require(metadata['user_track_killing'] is False and metadata['standard_neutron_time_limit_ns'] == 10000
        and metadata['step_limiter_charged_only'] is True and metadata['output_precision_digits'] == 17,
        'original tracking/export policy differs')
    require(metadata['production_cut_um'] == geometry['production_cut_um']
        and metadata['max_step_um'] == geometry['max_step_um'], 'actual cut/step differs')
    return row, B.native_beam(request, metadata)


def audit_v2(operation, epoch_s, build):
    require(type(epoch_s) in (int, float) and math.isfinite(epoch_s) and epoch_s >= 0,
        'explicit nonnegative epoch in seconds required')
    N, T = fixed('native'), fixed('transport_v2')
    fixed('geometry_v2')
    fixed('common_v2')
    with N.A.v1().proton_modules() as (P, _, B):
        build, build_receipt, semantic = T.audit_build(build)
        outputs = tuple(set(T.RUN_INPUTS + B.EVENT_OUTPUTS + ('request.json', 'input-manifest.json', 'task.sh')))
        operation, receipt = P.complete_operation(operation, outputs)
        require(receipt['schema'] == 'dram-see-v4-transport-operation-v2', 'original operation-v2 required')
        folder, compiled = operation / 'collected', build / 'collected'
        request, metadata, geometry, model, status = [
            read(folder / name) for name in ('request.json', 'metadata.json', 'geometry-contract.json', 'model-input.json', 'status.json')]
        row, beam = validate_v2_metadata(request, metadata, geometry, model, semantic, B, T)
        require(request == T.request_payload(build, operation.name, row, request['seed'], request['event_count'], semantic),
            'actual v2 request differs from its original native build and frozen matrix')
        require(request['source_operation_sha256'] == P.sha(build / 'operation.json'),
            'original run does not bind its actual build')
        for name in T.RUN_INPUTS:
            require((folder / name).read_bytes() == (compiled / name).read_bytes(),
                'actual run changed its per-geometry compiled input: ' + name)
        require(geometry['model_sha256'] == P.sha(folder / 'model-input.json')
            and metadata['geometry_sha256'] == metadata['contract_sha256'] == P.sha(folder / 'geometry-contract.json'),
            'actual model/geometry hash differs')
        manifest = read(folder / 'input-manifest.json')
        require(manifest['schema'] == 'continuous-proton-inputs-v2'
            and manifest['version_id'] == 'v2-proton-bcat'
            and manifest['kind'] == 'geant4_multi_condition_development_transport_candidate',
            'actual original multi-condition run manifest differs')
        require(set(manifest['files']) == set(T.RUN_INPUTS) | {'request.json', 'task.sh'},
            'complete submitted v2 file set differs')
        for name, digest in manifest['files'].items():
            require(P.sha(folder / name) == digest, 'actual submitted input changed: ' + name)
        require((folder / 'transport-exit-code.txt').read_bytes().strip() == b'0', 'actual transport did not exit0')
        columns = N.export_headers(compiled / 'transport_bcat.cc')
        tables = {name: N.exact_csv(folder / name, columns[name]) for name in N.RAW_TABLES}
        probes = [line.split() for line in (folder / 'geometry-probes.tsv').read_text().splitlines()]
        require(len(tables['geometry-probes-native.csv']) == len(probes) > 0 and all(
            native['passed'] == '1' and native['native_material'] == native['expected_material'] == probe[3]
            and [float(native[a + '_um']) for a in 'xyz'] == list(map(float, probe[:3]))
            for native, probe in zip(tables['geometry-probes-native.csv'], probes)),
            'actual native material probes differ')
        built = tables['geometry-built.csv']
        require(len(built) == len(N.VOLUMES) and {r['volume'] for r in built} == set(N.VOLUMES)
            and all(r['material'] == N.VOLUMES[r['volume']] and r['overlap_check_passed'] == '1' for r in built),
            'actual native volume/overlap evidence differs')
        for item in built:
            if item['volume'] != 'World':
                require(abs(float(item['density_g_cm3']) - geometry['material_densities_g_cm3'][item['material']]) <= 1e-9
                    and abs(float(item['charged_max_step_um']) - geometry['max_step_um']) <= 1e-15,
                    'actual native density/step differs')
        events, grouped = N.validate_population(tables, status, request['event_count'], B)
        binding = dict(schema=BINDING_SCHEMA, adapter_stage='six_train_conditions_only',
            operation=N.A.ref(operation / 'operation.json'), archive=N.A.ref(operation / 'results.tar'),
            build_operation=N.A.ref(build / 'operation.json'), build_archive=N.A.ref(build / 'results.tar'),
            binary=N.A.ref(folder / 'transport_bcat'), compiled_exporter=N.A.ref(folder / 'transport_bcat.cc'),
            request=N.A.ref(folder / 'request.json'), geometry=N.A.ref(folder / 'geometry-contract.json'),
            model=N.A.ref(folder / 'model-input.json'),
            raw_files={name: N.A.ref(folder / name) for name in
                (*N.RAW_TABLES, 'metadata.json', 'status.json', 'materials.csv', 'cuts.csv')},
            raw_columns={name: columns[name] for name in N.RAW_TABLES}, actual_exported_units=metadata['units'],
            coordinate_transform=geometry['coordinate_transform'], condition=row, seed=request['seed'], native_beam=beam,
            original_request_event_count=request['event_count'], original_request_event_ids=list(range(request['event_count'])),
            all_event_summaries=events, no_event_filter=True, epoch_s=epoch_s,
            original_exits={k: receipt[k] for k in
                ('ssh_exit_code', 'remote_exit_code', 'operation_task_exit_code', 'collection_exit_code')},
            adapter_implementation=ref(__file__), dependencies=dependencies(),
            native_source_qualified=False, pmi_r12_fixed=False)
    sources = []
    for event in events:
        event_id = int(event['event_id'])
        selected = grouped[event_id]
        context = dict(scope='BCAT_MULTICONDITION_COMPLETE_REQUEST_PENDING_NATIVE_SOURCE',
            registered_r14_source=False, original_geometry=geometry,
            original_batch_binding_sha256=N.A.sha(N.A.encoded(binding)),
            original_request_denominator=binding['original_request_event_ids'],
            unprojected_original_event_ids=[], unprojected_reason='All original primary events retained',
            original_files=binding['raw_files'], selection='All originally requested primaries without event/charge/response filtering')
        sources.append(N.A.reconstruct(event, selected['tracks.csv'], selected['steps.csv'],
            selected['birth-links.csv'], metadata, epoch_s, [0, 1, 2], context))
    require([s['event_id'] for s in sources] == binding['original_request_event_ids'], 'lost original primary event')
    return dict(binding=binding, sources=sources)


def batch_payload(result, replay_request):
    N = fixed('native')
    files = {'native-batch-binding.json': N.A.encoded(result['binding']),
        'replay-request.json': N.A.encoded(replay_request)}
    files.update({'event-{}-g3-source.json'.format(source['event_id']): N.A.encoded(source) for source in result['sources']})
    files['adapter-manifest.json'] = encoded(dict(schema=MANIFEST_SCHEMA, implementation=ref(__file__),
        files={name: sha(raw) for name, raw in files.items()}, event_ids=result['binding']['original_request_event_ids'],
        native_source_qualified=False, pmi_r12_fixed=False))
    return files


def verify(package):
    package = Path(package).resolve()
    manifest = read(package / 'adapter-manifest.json')
    N = fixed('native')
    if manifest.get('schema') == 'dram-see-v4-bcat-native-adapter-package-r1':
        result = N.verify(package)
        condition = result['binding']['condition']
        condition_identity(condition['condition_id'], int(float(condition['gate_top_depth_nm'])),
            float(condition['energy_MeV']), float(condition['angle_deg']))
        return result
    require(manifest.get('schema') == MANIFEST_SCHEMA and manifest['implementation'] == ref(__file__),
        'unregistered multicondition batch implementation')
    request = read(package / 'replay-request.json')
    require(set(request) == {'operation', 'epoch_s', 'build'}, 'exact original replay request required')
    result = audit_v2(request['operation'], request['epoch_s'], request['build'])
    expected = batch_payload(result, request)
    require({p.name for p in package.iterdir()} == set(expected)
        and all((package / name).read_bytes() == raw for name, raw in expected.items()),
        'new batch differs from complete original v2 recomputation')
    return result


def source_payload(replay, model, geometry, dimensional, window, legacy=False):
    M = fixed('source')
    bound, sources = replay['binding'], replay['sources']
    actual_geometry = read(bound['geometry']['path'])
    response, relation = M.P.bcat_response(model, geometry, dimensional, actual_geometry)
    files, index = {}, []
    for source in sources:
        event_id = source['event_id']
        prefix = 'event-{}/'.format(event_id)
        ledger = M.K.integrate(source['terms'], response, window, bound['native_beam']['surface_position_um'], source['epoch_s'])
        late = ledger['raw_deposition_outside_window_uids']
        files[prefix + 'projection-sources3d.dat'] = M.source_table(source['terms'])
        files[prefix + 'projection-context.dat'] = M.context_bytes(window)
        files[prefix + 'input-only-projection-reference.json'] = M.A.encoded(ledger)
        files[prefix + 'full-original-event-source.json'] = M.A.encoded(source)
        index.append(dict(event_id=event_id, seed=source['seed'], source_rows=len(source['terms']), late_uids=late,
            readiness='RAW_LATE_SOURCE_REQUIRES_MATCHING_TIMING_EXTENSION' if late else
                'CANDIDATE_INPUT_ONLY_APD_AND_NATIVE_QUALIFICATION_UNRESOLVED',
            source_present=bool(source['terms']), all_original_steps_retained=source['all_selected_event_steps_retained']))
    source_index = dict(schema='dram-see-v4-projection-native-source-input-candidate-r1' if legacy else SOURCE_SCHEMA,
        batch_binding=bound, response_bindings=relation, complete_window_s=list(window), events=index,
        omitted_event_ids=[], reference_kernel=M.A.ref(M.HERE / 'kernel.py'),
        source_adapter=M.A.ref(M.HERE / 'bcat_native_adapter.py') if legacy else ref(__file__),
        coordinate_map='native X=physical x, native Y=physical z, native Z=0; all physical y remains in original source rows',
        native_physics_fragment=None, APD_basis=None, native_source_qualified=False, pmi_r12_fixed=False)
    files['all-event-source-inputs.json'] = M.A.encoded(source_index)
    manifest = dict(schema='dram-see-v4-projection-candidate-inputs-r1' if legacy else SOURCE_MANIFEST_SCHEMA,
        kind='all-original-BCAT-events-native-source-input-candidate-not-activated',
        files={name: M.A.sha(raw) for name, raw in sorted(files.items())},
        preparer=M.A.ref(M.__file__) if legacy else ref(__file__),
        compiled=False, solver_dispatched=False, native_source_qualified=False, pmi_r12_fixed=False)
    files['candidate-input-manifest.json'] = M.A.encoded(manifest)
    files['input-hashes.sha256'] = ''.join(sha(raw) + '  ' + name + '\n'
        for name, raw in sorted(files.items())).encode('ascii')
    return files


def verify_source_package(batch, source_package, model, geometry, dimensional, window):
    replay = verify(batch)
    folder = Path(source_package).resolve()
    manifest = read(folder / 'candidate-input-manifest.json')
    legacy = manifest.get('schema') == 'dram-see-v4-projection-candidate-inputs-r1'
    require(legacy or manifest.get('schema') == SOURCE_MANIFEST_SCHEMA, 'unregistered source package schema')
    require(not legacy or replay['binding']['schema'] == 'dram-see-v4-bcat-native-complete-batch-binding-r1',
        'legacy source package cannot relabel a v2 native batch')
    expected = source_payload(replay, model, geometry, dimensional, window, legacy)
    require({p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()} == set(expected)
        and all(not (folder / name).is_symlink() and (folder / name).read_bytes() == raw for name, raw in expected.items()),
        'complete source package differs from original fixed mathematical replay')
    ids = replay['binding']['original_request_event_ids']
    names = ['adapter-manifest.json', 'native-batch-binding.json', 'replay-request.json'] + [
        'event-{}-g3-source.json'.format(e) for e in ids]
    return dict(replay=replay, source_files=expected,
        batch_files={name: (Path(batch) / name).read_bytes() for name in names})


def write_payload(output, files):
    path = Path(output).resolve()
    require(EVIDENCE.resolve() in path.parents and not path.exists(), 'new evidence-only output directory required')
    require(all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in files),
        'unsafe input-only member')
    path.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        item = path / name
        item.parent.mkdir(parents=True, exist_ok=True)
        with item.open('xb') as stream:
            stream.write(raw)
    return path


def build_package(operation, epoch_s, output, build):
    replay_request = dict(operation=str(Path(operation).resolve()), epoch_s=epoch_s, build=str(Path(build).resolve()))
    result = audit_v2(operation, epoch_s, build)
    return write_payload(output, batch_payload(result, replay_request))


def prepare_source_inputs(batch, model, geometry, dimensional, window, output):
    return write_payload(output, source_payload(verify(batch), model, geometry, dimensional, window))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('batch')
    for name in ('operation', 'build', 'output'):
        command.add_argument('--' + name, type=Path, required=True)
    command.add_argument('--epoch-s', type=float, required=True)
    command = sub.add_parser('source-inputs')
    for name in ('batch', 'model', 'geometry', 'dimensional', 'output'):
        command.add_argument('--' + name, type=Path, required=True)
    command.add_argument('--window', type=float, nargs=2, required=True)
    sub.add_parser('verify').add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'batch':
        result = str(build_package(args.operation, args.epoch_s, args.output, args.build))
    elif args.command == 'source-inputs':
        result = str(prepare_source_inputs(args.batch, args.model, args.geometry, args.dimensional, args.window, args.output))
    else:
        value = verify(args.package)
        result = dict(original_event_ids=value['binding']['original_request_event_ids'], native_source_qualified=False)
    print(json.dumps(result))
