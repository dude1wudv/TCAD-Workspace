"""Local-only audit of frozen Geant4 10.7.3 transport probe evidence.

Never runs SSH, executables, solvers, compilation, installation or training.
No energy <= primary kinetic-energy shortcut for nuclear events.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TOLERANCES = {'energy_abs_MeV': 1e-12, 'energy_relative': 1e-9,
              'time_abs_ns': 1e-9, 'position_abs_um': 1e-9, 'direction_norm_abs': 1e-10}
LIMITS = [
    'Arithmetic and provenance validation, not Geant4 physics calibration or statistical convergence.',
    'No full rest-mass/nuclear-excitation/escaped-energy balance is claimed.',
    'All primary events, zero silicon deposition, all tracked descendants and all recorded steps remain in denominator.',
    'QGSP_BIC standard neutron tracking cut at 10000 ns is retained and counted; delayed histories beyond it are outside scope.',
    'No TCAD source mapping, joint injection, DRAM response or particle event-rate estimate.',
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def local_file(folder, name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'Evidence filename must be a relative POSIX path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts, 'Evidence path traversal')
    path = (folder / name).resolve()
    require(path.is_relative_to(folder) and path.is_file(), 'Missing or escaped evidence file: ' + name)
    return path


def integer(value, label):
    require(isinstance(value, str) and re.fullmatch(r'-?\d+', value) is not None,
            'Invalid integer ' + label + ': ' + repr(value))
    return int(value)


def number(value, label):
    v = float(value)
    require(math.isfinite(v), 'Nonfinite value: ' + label)
    return v


def boolean(value, label):
    v = integer(value, label)
    require(v in (0, 1), 'Invalid boolean: ' + label)
    return v


def close(a, b, absolute=None, relative=None):
    absolute = TOLERANCES['energy_abs_MeV'] if absolute is None else absolute
    relative = TOLERANCES['energy_relative'] if relative is None else relative
    return abs(a - b) <= absolute + relative * max(abs(a), abs(b))


def csv_rows(folder, name, required=()):
    text = local_file(folder, name).read_text(encoding='utf-8-sig')
    reader = csv.DictReader(io.StringIO(text), strict=True)
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), 'Missing/duplicate CSV headers: ' + name)
    require(set(required) <= set(reader.fieldnames), 'Missing columns in ' + name + ': ' + str(set(required) - set(reader.fieldnames)))
    rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
            'Truncated or extra CSV cells: ' + name)
    return rows


class Checks:
    def __init__(self, report):
        self.report = report

    def run(self, name, fn):
        try:
            result = fn()
            self.report['checks'][name] = {'passed': True}
            return result
        except (OSError, ValueError, KeyError, TypeError, IndexError, csv.Error, tarfile.TarError) as exc:
            self.report['checks'][name] = {'passed': False, 'error': str(exc)}
            self.report['errors'].append({'check': name, 'error': str(exc)})
            return None


def _receipt(folder, report):
    record = read_json(folder / 'record.json')
    report['record_sha256'] = sha(folder / 'record.json')
    report['run_id'] = record.get('run_id')
    require(record.get('schema') == 'dram-see-v4-transport-run-v1', 'Unknown run receipt schema')
    report['exit_codes'] = {key: record.get(key) for key in
                            ('runner_exit_code', 'remote_exit_code', 'collection_exit_code')}
    report['runner_exit_code_scope'] = record.get('runner_exit_code_scope',
        'SSH process exit; not an additional independent solver subprocess exit')
    for key, value in report['exit_codes'].items():
        require(type(value) is int and value == 0, 'Unknown/nonzero actual exit code: ' + key)
    exit_text = local_file(folder, 'exit-code.txt').read_text().strip()
    require(re.fullmatch(r'-?\d+', exit_text) is not None and int(exit_text) == record['remote_exit_code'],
            'Remote exit-code.txt is missing, unknown, or conflicts with receipt')
    maps = {}
    for group in ('input_sha256', 'output_sha256'):
        mapping = record.get(group)
        require(isinstance(mapping, dict) and mapping, 'Missing evidence hash map: ' + group)
        for name, digest in mapping.items():
            require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Malformed SHA256: ' + name)
            require(sha(local_file(folder, name)) == digest, 'Evidence hash mismatch: ' + name)
        maps.update(mapping)
    required = {'task.sh', 'run.sh', 'exit-code.txt', 'execution.log', 'affinity.txt',
                'metadata.json', 'status.json', 'constructors.csv', 'processes.csv', 'hadronic-models.csv',
                'materials.csv', 'cuts.csv', 'events.csv', 'tracks.csv', 'steps.csv'}
    require(required <= set(maps), 'Required raw evidence is not hash-bound: ' + str(required - set(maps)))
    archive = record.get('raw_archive')
    require(isinstance(archive, dict) and isinstance(archive.get('path'), str), 'Missing original archive reference')
    path = Path(archive['path'])
    if not path.is_absolute():
        path = ROOT / path
    require(sha(path) == archive.get('sha256'), 'Original results archive hash mismatch')
    archived = {}
    with tarfile.open(path, 'r:*') as tf:
        for member in tf:
            name = member.name
            while name.startswith('./'):
                name = name[2:]
            pure = PurePosixPath(name)
            require(not pure.is_absolute() and '..' not in pure.parts and '\\' not in name and ':' not in name,
                    'Unsafe original archive path')
            require(member.isfile() or member.isdir(), 'Original archive contains a link/special member')
            if member.isdir():
                continue
            name = pure.as_posix()
            require(name not in archived, 'Duplicate original archive member')
            h = hashlib.sha256()
            with tf.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):
                    h.update(chunk)
            archived[name] = h.hexdigest()
    require(archived == record['output_sha256'], 'Exported files differ from complete original archive inventory')
    require(all(archived.get(name)==digest for name,digest in record['input_sha256'].items()), 'Original inputs changed within result archive')
    report['raw_archive'] = archive
    operation = record.get('operation_evidence')
    require(isinstance(operation, dict) and isinstance(operation.get('path'), str), 'Missing original operation receipt')
    op_path = Path(operation['path'])
    if not op_path.is_absolute():
        op_path = ROOT / op_path
    require(sha(op_path) == operation.get('sha256'), 'Original operation receipt hash mismatch')
    op = read_json(op_path)
    require(op.get('schema') == 'dram-see-v4-transport-operation-v1', 'Unknown original operation schema')
    for exported, original in [('runner_exit_code','ssh_exit_code'),('remote_exit_code','remote_exit_code'),('collection_exit_code','collection_exit_code')]:
        require(type(op.get(original)) is int and op[original] == record[exported], 'Exported exit code differs from original operation')
    require(op.get('archive_sha256') == archive['sha256'], 'Original operation archive reference differs')
    require(op.get('input_sha256') == record['input_sha256'], 'Original operation input inventory differs')
    report['input_sha256'], report['output_sha256'] = record['input_sha256'], record['output_sha256']
    request = record.get('request')
    require(isinstance(request, dict), 'Missing frozen request')
    request_files = [name for name in record['input_sha256'] if Path(name).name == 'request.json']
    require(len(request_files) == 1 and read_json(local_file(folder, request_files[0])) == request,
            'Receipt request is not bound to an identical frozen request.json')
    contract = read_json(HERE / 'probe-contract.json')
    require(contract.get('csv_arithmetic_tolerances') == TOLERANCES, 'Frozen arithmetic tolerances differ')
    require(request in contract.get('requests', []), 'Request is absent from predeclared probe contract')
    require(request.get('geometry_sha256') == contract.get('geometry_sha256'), 'Requested geometry hash differs')
    report['probe_contract_sha256'] = sha(HERE / 'probe-contract.json')
    report['request'] = request
    return record


def _provenance(folder, record, report):
    files = record.get('provenance_files')
    require(isinstance(files, dict), 'Missing provenance_files binding')
    hashes = {**record['input_sha256'], **record['output_sha256']}
    for kind, field in [('environment', 'environment_sha256'), ('dataset_inventory', 'dataset_inventory_sha256')]:
        name = files.get(kind)
        require(name in hashes and sha(local_file(folder, name)) == record.get(field), 'Missing/incorrect actual ' + kind + ' hash')
    binary = files.get('binary')
    if binary:
        require(binary in hashes and sha(local_file(folder, binary)) == record.get('binary_sha256'), 'Local binary hash differs')
        report['binary_evidence'] = 'actual_local_binary_hash'
    else:
        witness = files.get('binary_witness')
        require(witness in hashes, 'Remote binary hash witness is not hash-bound')
        lines = local_file(folder, witness).read_text().splitlines()
        hits = [line for line in lines if re.fullmatch(r'[0-9a-f]{64}\s+\*?binary', line)]
        require(len(hits) == 1 and hits[0].split()[0] == record.get('binary_sha256'), 'Remote binary witness missing/mismatched')
        report['binary_evidence'] = 'original_remote_sha256_witness; executable not rehashed locally'
    require(re.fullmatch('[0-9a-f]{64}', record.get('binary_sha256', '')), 'Invalid executable SHA256')
    report['binary_sha256'] = record['binary_sha256']
    report['environment_sha256'] = record['environment_sha256']
    report['dataset_inventory_sha256'] = record['dataset_inventory_sha256']
    source_names = [name for name in record['input_sha256'] if name.endswith(('.cc', '.cpp'))]
    require(source_names, 'Compiled source snapshot missing from frozen inputs')
    report['source_sha256'] = {name: hashes[name] for name in source_names}
    inventory = read_json(local_file(folder, files['dataset_inventory']))
    require(inventory.get('schema') == 'dram-see-v4-dataset-inventory-v1', 'Unknown data inventory schema')
    entries = inventory.get('datasets')
    require(isinstance(entries,list) and len({e.get('env') for e in entries})==len(entries), 'Missing/duplicate dataset environment entries')
    dataset_map = {e['env']:e for e in entries}
    required_data = {'G4LEDATA':'G4EMLOW7.13','G4ENSDFSTATEDATA':'G4ENSDFSTATE2.3'}
    if record['request']['arm']=='H':
        required_data.update(G4LEVELGAMMADATA='PhotonEvaporation5.7',G4PARTICLEXSDATA='G4PARTICLEXS3.1.1')
    environment = local_file(folder,files['environment']).read_text()
    for env, basename in required_data.items():
        require(env in dataset_map, 'Required dataset missing from inventory: '+env)
        entry = dataset_map[env]
        require(PurePosixPath(entry.get('path','')).name==basename and type(entry.get('file_count')) is int and entry['file_count']>0
                and type(entry.get('bytes')) is int and entry['bytes']>0
                and re.fullmatch('[0-9a-f]{64}',entry.get('content_manifest_sha256','')), 'Invalid dataset inventory: '+env)
        require(re.search(r'^export\s+'+env+r'=[\"\']?'+re.escape(entry['path'])+r'[\"\']?\s*$',environment,re.MULTILINE),
                'Environment and recorded dataset path differ: '+env)
    report['data_binding'] = {'required_for_arm':required_data,'inventory':entries,
                             'scope':'Original recorded content-manifest hashes, not a new read of remote dataset bytes.'}
    return True


def _serial(folder, metadata, report):
    require(metadata.get('run_manager') == 'G4RunManager' and metadata.get('multithreaded_run_manager') is False
            and type(metadata.get('requested_threads')) is int and metadata['requested_threads'] == 1,
            'Actual Geant4 metadata does not describe the serial run manager')
    affinity = local_file(folder, 'affinity.txt').read_text()
    matches = re.findall(r'^Cpus_allowed_list:\s*(\S+)\s*$', affinity, re.MULTILINE)
    threads = re.findall(r'^Threads:\s*(\d+)\s*$', affinity, re.MULTILINE)
    require(matches and threads, 'Missing raw /proc thread/affinity evidence')
    for value in matches:
        require(re.fullmatch(r'\d+(?:-\d+)?', value), 'Affinity has more than one CPU')
        parts = value.split('-')
        require(len(parts) == 1 or parts[0] == parts[1], 'Affinity spans multiple CPUs')
    require(all(int(value) == 1 for value in threads), 'Observed process has multiple threads')
    task = local_file(folder, 'run.sh').read_text()
    require('taskset' in task and 'flock' in task, 'Missing serial affinity/shared-lock wrapper evidence')
    report['serial_evidence'] = {'run_manager': metadata['run_manager'], 'requested_threads': 1,
                                 'observed_threads': [int(x) for x in threads], 'observed_cpu_lists': matches}
    return True


def _metadata(folder, record, expected_mode, report):
    m, status = read_json(folder / 'metadata.json'), read_json(folder / 'status.json')
    report['metadata'], report['status_record'] = m, status
    require(m.get('schema') == 'v4-transport-probe-r1' and status.get('schema') == 'v4-transport-probe-status-r1',
            'Unknown metadata/status schema')
    require(m.get('geant4_version_number') == 1073 and isinstance(m.get('geant4_version'), str), 'Not actual Geant4 10.7.3')
    mode = 'init' if expected_mode == 'init' else 'thin'
    require(m.get('mode') == mode and record.get('mode') == expected_mode, 'Receipt/metadata mode differs from audit entry point')
    request = record['request']
    for key in ('mode', 'arm', 'energy_MeV', 'angle_deg', 'seed', 'miss'):
        require(m.get(key) == request.get(key), 'Metadata/request mismatch: ' + key)
    require(m.get('arm') in ('H', 'E') and m.get('energy_MeV') in (1, 5, 20, 100) and m.get('angle_deg') in (0, 30),
            'Outside frozen particle conditions')
    require(type(m.get('seed')) is int and m['seed'] > 0 and type(m.get('miss')) is bool, 'Invalid seed/miss configuration')
    count = request.get('event_count', request.get('events'))
    require(type(count) is int and count == m.get('events_requested') == status.get('events_requested'), 'Requested event count differs')
    require(count == (0 if expected_mode == 'init' else 2), 'Outside initial zero/two-event probe budget')
    require(status.get('initialized') is True and status.get('state') == 'COMPLETED'
            and status.get('error') is None, 'Initialization/run not successfully completed')
    require(status.get('beam_on_called') is True and status.get('zero_event_beam_on_called') is True
            and status.get('physics_tables_built') is True
            and status.get('nonzero_event_beam_on_called') is (mode != 'init')
            and m.get('initialization_method') == 'Initialize_then_BeamOn_0', 'Physics-table/zero-primary initialization evidence differs')
    require(status.get('events_completed') == count, 'Actual primary-event denominator differs')
    log = local_file(folder,'execution.log').read_text(encoding='utf-8',errors='replace')
    marker = (f"TRANSPORT_PROBE_COMPLETED mode={mode} arm={m['arm']} events={count} "
              f"tracks={status['tracks_completed']} steps={status['steps_recorded']}")
    require(marker in log.splitlines() and 'V4_OPERATION_COMPLETED' in log.splitlines(), 'Missing actual transport/wrapper completion markers')
    require(m.get('user_track_killing') is False, 'Unexpected user track filtering/killing')
    require(m.get('standard_neutron_time_limit_ns') == (10000 if m['arm'] == 'H' else None), 'Reference neutron tracking-cut contract differs')
    require(m.get('production_cut_um') == .01 and m.get('max_step_um') == .02 and m.get('max_step_region') == 'Si'
            and m.get('step_limiter_charged_only') is True, 'Frozen cut/step configuration differs')
    require(m.get('primary_particle') == 'proton' and m.get('rng_engine'), 'Missing primary particle/RNG identity')
    require(m.get('world_half_extent_um') == 10, 'World geometry differs')
    bounds = m.get('silicon_bounds_um')
    require(isinstance(bounds, dict) and set(bounds) == {'x', 'y', 'z'}, 'Missing silicon geometry')
    require(all(isinstance(v, list) and len(v) == 2 and v[0] < v[1] for v in bounds.values()), 'Invalid geometry bounds')
    require(bounds == {'x':[0,.85],'y':[0,1.2],'z':[-.5,.5]}, 'Silicon dimensions differ from frozen geometry')
    units = m.get('units')
    require(units == {'length':'um','time':'ns','energy':'MeV','charge':'eplus','direction':'unit_vector'}, 'Output units differ')
    report['geometry'] = {'silicon_bounds_um': bounds, 'world_half_extent_um': 10,
                          'beam_position_um': m.get('beam_position_um'), 'beam_direction': m.get('beam_direction'),
                          'surface_position_um': m.get('surface_position_um')}
    for key in ('beam_position_um', 'beam_direction', 'surface_position_um'):
        require(isinstance(m.get(key), list) and len(m[key]) == 3 and all(math.isfinite(float(x)) for x in m[key]), 'Invalid beam geometry: ' + key)
    require(abs(sum(float(x)**2 for x in m['beam_direction']) - 1) <= TOLERANCES['direction_norm_abs'], 'Beam direction not normalized')
    theta=math.radians(m['angle_deg'])
    expected_direction=[-math.sin(theta),math.cos(theta),0]
    expected_surface=[-5 if m['miss'] else .7,0,0]
    expected_position=[expected_surface[0]+.001*math.tan(theta),-.001,0]
    for key,expected in [('beam_direction',expected_direction),('surface_position_um',expected_surface),('beam_position_um',expected_position)]:
        require(all(close(float(x),y,TOLERANCES['position_abs_um'],0) for x,y in zip(m[key],expected)), 'Actual beam differs from frozen geometry: '+key)
    return m, status


def _inventory(folder, metadata, report):
    constructors = csv_rows(folder, 'constructors.csv', ['phase', 'index', 'name', 'physics_type'])
    processes = csv_rows(folder, 'processes.csv', ['phase', 'particle', 'pdg', 'process_index', 'process', 'process_type', 'process_subtype', 'hadronic_model_count'])
    models = csv_rows(folder, 'hadronic-models.csv', ['phase', 'particle', 'pdg', 'process', 'model_index', 'model', 'min_energy_MeV', 'max_energy_MeV'])
    phases = ['post_zero_event_init'] + (['post_events'] if metadata['mode'] == 'thin' else [])
    require(metadata.get('inventory_phases') == phases, 'Missing/extra inventory phases')
    require({r['phase'] for r in constructors} == set(phases) and {r['phase'] for r in processes} == set(phases), 'Actual inventory phases differ')
    for phase in phases:
        cc = [r for r in constructors if r['phase'] == phase]
        require(len({r['index'] for r in cc}) == len(cc), 'Duplicate constructor index')
        em = [r for r in cc if integer(r['physics_type'], 'physics_type') == 2]
        require(len(em) == 1 and em[0]['name'] == 'G4EmStandard_opt4', 'EM option4 not unique or actual name differs')
        pp = [r for r in processes if r['phase'] == phase]
        require(len({(r['particle'], r['process_index']) for r in pp}) == len(pp), 'Duplicate process index per particle')
        for r in pp:
            for key in ('pdg', 'process_index', 'process_type', 'process_subtype', 'hadronic_model_count'):
                integer(r[key], key)
            linked = [x for x in models if x['phase'] == phase and x['particle'] == r['particle'] and x['process'] == r['process']]
            require(len(linked) == int(r['hadronic_model_count']), 'Hadronic model count differs for ' + r['particle'] + '/' + r['process'])
        proton = [r for r in pp if r['particle'] == 'proton']
        counts = Counter(r['process'] for r in proton)
        require(counts['hIoni'] == 1, 'Proton hIoni missing or duplicated')
        if metadata['arm'] == 'H':
            require(counts['hadElastic'] == 1 and counts['protonInelastic'] == 1, 'H proton hadronic processes missing/duplicated')
            require(all(int(r['process_type'])==4 and int(r['hadronic_model_count'])>0
                        for r in proton if r['process'] in ('hadElastic','protonInelastic')),
                    'Required proton hadronic process has wrong type or no registered model')
        else:
            require(all(int(r['process_type']) != 4 for r in pp) and not models,
                    'E arm contains hadronic process/model')
    for row in models:
        lo, hi = number(row['min_energy_MeV'], 'model_min'), number(row['max_energy_MeV'], 'model_max')
        require(0 <= lo <= hi, 'Invalid model energy interval')
        require(any(p['phase']==row['phase'] and p['particle']==row['particle'] and p['process']==row['process'] for p in processes),
                'Model has no registered parent process')
    cuts = csv_rows(folder, 'cuts.csv', ['phase', 'couple_index', 'material', 'particle', 'range_cut_um', 'energy_cut_MeV', 'energy_cut_available'])
    unavailable = 0
    require(cuts, 'No production cut table was produced')
    for row in cuts:
        require(row['phase'] in phases, 'Unexpected cut phase')
        require(number(row['range_cut_um'], 'range cut') >= 0, 'Negative production range cut')
        available = boolean(row['energy_cut_available'], 'energy_cut_available')
        if available:
            require(number(row['energy_cut_MeV'], 'energy cut') > 0, 'Nonpositive production energy cut')
        else:
            require(row['energy_cut_MeV'] == '', 'Unavailable cut has a fabricated numeric value')
            unavailable += 1
    require(unavailable == 0, 'Zero-event initialization did not build all production energy-cut tables')
    for phase in phases:
        for material in ('G4_Si','G4_Galactic'):
            rows=[r for r in cuts if r['phase']==phase and r['material']==material]
            require({r['particle'] for r in rows} == {'gamma','e-','e+','proton'}, 'Material cut table incomplete')
            require(all(close(number(r['range_cut_um'],'range_cut'),.01,1e-12,0) for r in rows), 'Actual production range cut differs')
    materials = csv_rows(folder, 'materials.csv', ['phase', 'material', 'density_g_cm3', 'temperature_K', 'pressure_Pa', 'state', 'number_elements'])
    require(materials, 'No actual material inventory')
    for row in materials:
        require(row['phase'] in phases, 'Unexpected material phase')
        for key in ('density_g_cm3', 'temperature_K', 'pressure_Pa'):
            require(number(row[key], key) >= 0, 'Negative material property')
    report['physics_inventory'] = {'constructors': constructors, 'proton_processes': [r for r in processes if r['particle'] == 'proton'],
                                  'hadronic_models': models, 'energy_cut_unavailable_rows': unavailable,
                                  'cut_scope': 'Initialize plus BeamOn(0) builds tables without primary events; unavailable energy tables fail.',
                                  'model_range_scope': 'Reported global model limits, not material-specific coverage.'}
    return True


EVENT_INT = {'event_id','primary_count','track_count','step_count','si_step_count','world_step_count','hadronic_step_count',
             'primary_hadronic_step_count','primary_first_hadronic_step','neutron_tracking_cut_steps','neutron_tracking_cut_tracks'}
TRACK_INT = {'event_id','track_id','parent_id','pdg','Z','A','creator_type','creator_subtype','step_count','end_track_status'}
STEP_INT = {'event_id','track_id','parent_id','step_id','pdg','post_process_type','post_process_subtype'}
EVENT_BOOL = {'zero_si_ionizing','event_complete'}
TRACK_BOOL = {'ended_by_neutron_tracking_cut'}
STEP_BOOL = {'primary_hadronic_seen_before','primary_hadronic_seen_after','neutron_tracking_cut_step'}
EVENT_FLOAT = {field+'_'+region+'_MeV' for field in ('edep','niel','ionizing') for region in ('all','si','world')} | {
    'primary_first_hadronic_t_ns','si_ionizing_primary_before_hadronic_MeV',
    'si_ionizing_primary_at_or_after_hadronic_MeV','si_ionizing_nonprimary_MeV'}
TRACK_FLOAT = {prefix+value for prefix in ('birth_','end_') for value in ('ke_MeV','x_um','y_um','z_um','dx','dy','dz','t_ns')} | {
    'charge_e','mass_MeV','track_length_um'} | {field+'_'+region+'_MeV' for field in ('edep','niel','ionizing') for region in ('all','si')}
STEP_FLOAT = {prefix+value for prefix in ('pre_','post_') for value in ('x_um','y_um','z_um','dx','dy','dz','ke_MeV','t_ns')} | {
    'step_um','edep_MeV','niel_MeV','ionizing_MeV'}


def numeric_rows(folder, filename, integers, booleans, strings, floats):
    rows = csv_rows(folder, filename, integers | booleans | strings | floats)
    converted = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if key in integers:
                item[key] = integer(value, key)
            elif key in booleans:
                item[key] = boolean(value, key)
            elif key in strings:
                require(value != '', 'Missing text field: ' + key)
                item[key] = value
            else:
                item[key] = number(value, key)
        converted.append(item)
    return converted


def _energy(value, label):
    require(math.isfinite(value) and value >= 0, 'Negative/nonfinite deposited energy: ' + label)


def _check_energy_triplet(row, total, niel, ion):
    for key in (total, niel, ion):
        _energy(row[key], key)
    require(row[niel] <= row[total] + TOLERANCES['energy_abs_MeV'] and
            close(row[total] - row[niel], row[ion]), 'NIEL/ionizing decomposition differs')


def _vector_equal(a, ap, b, bp, suffixes, tolerance):
    return all(close(a[ap + suffix], b[bp + suffix], tolerance, 0) for suffix in suffixes)


def _direction(row,prefix):
    norm=math.fsum(row[prefix+k]**2 for k in ('dx','dy','dz'))
    allowed_zero=row[prefix+'ke_MeV']==0 and norm==0
    require(allowed_zero or abs(norm-1)<=TOLERANCES['direction_norm_abs'], 'Recorded direction is not a unit vector')


def _events(folder, metadata, status, report):
    events = numeric_rows(folder, 'events.csv', EVENT_INT, EVENT_BOOL, {'primary_first_hadronic_process'}, EVENT_FLOAT)
    tracks = numeric_rows(folder, 'tracks.csv', TRACK_INT, TRACK_BOOL,
                          {'particle','creator_process','birth_volume','birth_material','end_volume','end_material'}, TRACK_FLOAT)
    steps = numeric_rows(folder, 'steps.csv', STEP_INT, STEP_BOOL,
                         {'particle','pre_volume','pre_material','post_volume','post_material','post_process'}, STEP_FLOAT)
    n = metadata['events_requested']
    require([r['event_id'] for r in events] == list(range(n)), 'Event IDs must be consecutive 0..N-1 including zero deposition')
    require(status['tracks_completed'] == len(tracks) and status['steps_recorded'] == len(steps), 'Status/count mismatch')
    bytrack, byeventtracks, byeventsteps, tracksteps = {}, defaultdict(list), defaultdict(list), defaultdict(list)
    seen_primary_hadronic = defaultdict(int)
    species, creators, interactions = Counter(), Counter(), Counter()
    for track in tracks:
        key = (track['event_id'], track['track_id'])
        require(track['event_id'] in range(n) and track['track_id'] > 0 and key not in bytrack, 'Invalid/duplicate track identity')
        require(track['parent_id'] >= 0 and track['parent_id'] != track['track_id'], 'Invalid track parent')
        for quantity in ('birth_ke_MeV', 'end_ke_MeV', 'mass_MeV', 'track_length_um'):
            _energy(track[quantity], quantity)
        require(0 <= track['birth_t_ns'] <= track['end_t_ns'] + TOLERANCES['time_abs_ns'], 'Track time reversed')
        for prefix in ('birth_','end_'):
            _direction(track,prefix)
            material={'Si':'G4_Si','World':'G4_Galactic','OUTSIDE':'NONE'}.get(track[prefix+'volume'])
            require(material is not None and track[prefix+'material']==material, 'Track volume/material differ')
        for region in ('all','si'):
            _check_energy_triplet(track, 'edep_' + region + '_MeV', 'niel_' + region + '_MeV', 'ionizing_' + region + '_MeV')
        bytrack[key] = track
        byeventtracks[track['event_id']].append(track)
        species[track['particle']] += 1
        if track['creator_type'] == 4:
            creators[track['creator_process']] += 1
    for step in steps:
        key = (step['event_id'], step['track_id'])
        require(key in bytrack, 'Step without a recorded track')
        track = bytrack[key]
        require(step['parent_id'] == track['parent_id'] and step['particle'] == track['particle'] and step['pdg'] == track['pdg'], 'Step/track identity mismatch')
        _check_energy_triplet(step, 'edep_MeV', 'niel_MeV', 'ionizing_MeV')
        for keynum in ('pre_ke_MeV','post_ke_MeV','step_um'):
            _energy(step[keynum], keynum)
        require(0 <= step['pre_t_ns'] <= step['post_t_ns'] + TOLERANCES['time_abs_ns'], 'Step time reversed')
        require(step['pre_volume'] in ('Si','World') and step['post_volume'] in ('Si','World','OUTSIDE'), 'Unexpected transport volume')
        for prefix in ('pre_','post_'):
            _direction(step,prefix)
            require(step[prefix+'material']=={'Si':'G4_Si','World':'G4_Galactic','OUTSIDE':'NONE'}[step[prefix+'volume']], 'Step volume/material differ')
        before = seen_primary_hadronic[step['event_id']]
        require(step['primary_hadronic_seen_before'] == before, 'Incorrect primary hadronic-before flag')
        if step['track_id'] == 1 and step['post_process_type'] == 4:
            seen_primary_hadronic[step['event_id']] = 1
        require(step['primary_hadronic_seen_after'] == seen_primary_hadronic[step['event_id']], 'Incorrect primary hadronic-after flag')
        if step['post_process_type'] == 4:
            interactions[step['post_process']] += 1
        if step['neutron_tracking_cut_step']:
            require(step['particle'] == 'neutron' and 'neutron' in step['post_process'].lower(), 'Tracking-cut flag on wrong particle/process')
        tracksteps[(step['event_id'], step['track_id'])].append(step)
        byeventsteps[step['event_id']].append(step)
    lineage = []
    for key, track in bytrack.items():
        group = tracksteps[key]
        require([s['step_id'] for s in group] == list(range(1, track['step_count'] + 1)), 'Missing/duplicate/out-of-order per-track steps')
        if track['parent_id'] == 0:
            require(track['track_id'] == 1 and track['particle'] == 'proton', 'Unexpected primary track')
            require(track['creator_process']=='none' and track['creator_type']==-1 and track['creator_subtype']==-1, 'Primary creator fields differ')
            require(track['pdg']==2212 and close(track['birth_ke_MeV'],metadata['energy_MeV'])
                    and close(track['birth_t_ns'],0,TOLERANCES['time_abs_ns'],0), 'Primary energy/time differs from frozen request')
            require(all(close(track['birth_'+axis+'_um'],metadata['beam_position_um'][i],TOLERANCES['position_abs_um'],0)
                        for i,axis in enumerate(('x','y','z'))), 'Primary birth position differs from request')
            require(all(close(track['birth_d'+axis],metadata['beam_direction'][i],TOLERANCES['direction_norm_abs'],0)
                        for i,axis in enumerate(('x','y','z'))), 'Primary birth direction differs from request')
        else:
            require(track['creator_process']!='none' and track['creator_type']>=0 and track['creator_subtype']>=0, 'Secondary lacks creator-process identity')
            require((key[0], track['parent_id']) in bytrack, 'Missing parent track')
            parent = bytrack[(key[0], track['parent_id'])]
            require(parent['birth_t_ns'] <= track['birth_t_ns'] + TOLERANCES['time_abs_ns'] <= parent['end_t_ns'] + 2*TOLERANCES['time_abs_ns'],
                    'Child birth outside parent lifetime')
        ancestor, visited, nuclear = track, set(), False
        while True:
            require(ancestor['track_id'] not in visited, 'Parent cycle')
            visited.add(ancestor['track_id'])
            nuclear = nuclear or ancestor['creator_type'] == 4
            if ancestor['parent_id'] == 0:
                break
            ancestor = bytrack[(key[0], ancestor['parent_id'])]
        lineage.append({'event_id': key[0], 'track_id': key[1], 'creator_lineage_has_hadronic': nuclear,
                        'meaning': 'At least one creator process in the parent chain has Geant4 process type 4; not every post-interaction primary step.'})
        for region, chosen in [('all', group), ('si', [s for s in group if s['pre_volume'] == 'Si'])]:
            for field, source in [('edep','edep_MeV'),('niel','niel_MeV'),('ionizing','ionizing_MeV')]:
                require(close(track[field + '_' + region + '_MeV'], math.fsum(s[source] for s in chosen)), 'Track/step energy sum mismatch')
        require(close(track['track_length_um'], math.fsum(s['step_um'] for s in group), TOLERANCES['position_abs_um'], 1e-9), 'Track/step length mismatch')
        require(track['ended_by_neutron_tracking_cut'] == int(any(s['neutron_tracking_cut_step'] for s in group)), 'Track neutron-cut flag mismatch')
        if group:
            first, last = group[0], group[-1]
            require(_vector_equal(first, 'pre_', track, 'birth_', ('x_um','y_um','z_um'), TOLERANCES['position_abs_um']), 'Track birth/first-step position mismatch')
            require(_vector_equal(last, 'post_', track, 'end_', ('x_um','y_um','z_um'), TOLERANCES['position_abs_um']), 'Track end/last-step position mismatch')
            require(close(first['pre_ke_MeV'], track['birth_ke_MeV']) and close(last['post_ke_MeV'], track['end_ke_MeV']), 'Track endpoint kinetic energy mismatch')
            require(close(first['pre_t_ns'], track['birth_t_ns'], TOLERANCES['time_abs_ns'], 0)
                    and close(last['post_t_ns'], track['end_t_ns'], TOLERANCES['time_abs_ns'], 0), 'Track endpoint time mismatch')
            for left, right in zip(group, group[1:]):
                require(_vector_equal(left, 'post_', right, 'pre_', ('x_um','y_um','z_um'), TOLERANCES['position_abs_um']), 'Step position chain broken')
                require(close(left['post_t_ns'], right['pre_t_ns'], TOLERANCES['time_abs_ns'], 0)
                        and close(left['post_ke_MeV'], right['pre_ke_MeV']), 'Step time/kinetic-energy chain broken')
    for event in events:
        eid, ts, ss = event['event_id'], byeventtracks[event['event_id']], byeventsteps[event['event_id']]
        require(event['primary_count'] == 1 and len([t for t in ts if t['parent_id'] == 0]) == 1, 'Wrong primary-event denominator')
        require(event['track_count'] == len(ts) and event['step_count'] == len(ss) and event['event_complete'] == 1, 'Incomplete event/row counts')
        for region, selected in [('all',ss),('si',[s for s in ss if s['pre_volume']=='Si']),('world',[s for s in ss if s['pre_volume']=='World'])]:
            _check_energy_triplet(event, 'edep_' + region + '_MeV', 'niel_' + region + '_MeV', 'ionizing_' + region + '_MeV')
            if region != 'all':
                require(event[region + '_step_count'] == len(selected), 'Material step count differs')
            for field in ('edep','niel','ionizing'):
                require(close(event[field + '_' + region + '_MeV'], math.fsum(s[field + '_MeV'] for s in selected)), 'Event/step energy sum mismatch: ' + region)
        primary = [s for s in ss if s['track_id']==1]
        ph = [s for s in primary if s['post_process_type']==4]
        require(event['hadronic_step_count'] == sum(s['post_process_type']==4 for s in ss)
                and event['primary_hadronic_step_count']==len(ph), 'Hadronic interaction count mismatch')
        require(event['primary_first_hadronic_step'] == (ph[0]['step_id'] if ph else 0)
                and event['primary_first_hadronic_process'] == (ph[0]['post_process'] if ph else 'none'), 'Primary first nuclear interaction differs')
        require(close(event['primary_first_hadronic_t_ns'], ph[0]['post_t_ns'] if ph else -1, TOLERANCES['time_abs_ns'],0), 'Primary first hadronic time differs')
        for field, selected in [
            ('si_ionizing_primary_before_hadronic_MeV',[s for s in primary if s['pre_volume']=='Si' and not s['primary_hadronic_seen_after']]),
            ('si_ionizing_primary_at_or_after_hadronic_MeV',[s for s in primary if s['pre_volume']=='Si' and s['primary_hadronic_seen_after']]),
            ('si_ionizing_nonprimary_MeV',[s for s in ss if s['pre_volume']=='Si' and s['track_id']!=1])]:
            require(close(event[field],math.fsum(s['ionizing_MeV'] for s in selected)), 'Primary/secondary Si decomposition differs')
        require(event['zero_si_ionizing'] == int(event['ionizing_si_MeV']==0), 'Zero-deposition event flag differs')
        require(event['neutron_tracking_cut_steps']==sum(s['neutron_tracking_cut_step'] for s in ss)
                and event['neutron_tracking_cut_tracks']==sum(t['ended_by_neutron_tracking_cut'] for t in ts), 'Neutron tracking-cut counts differ')
        if metadata['miss']:
            require(event['si_step_count']==0 and event['ionizing_si_MeV']==0, 'Explicit miss test unexpectedly entered/deposited in silicon')
    if metadata['arm']=='E':
        require(not interactions and not creators, 'EM-only event records contain hadronic processes')
    report['event_summary'] = {
        'primary_event_denominator': n, 'tracks':len(tracks),'steps':len(steps),
        'zero_si_events':sum(e['zero_si_ionizing'] for e in events),
        'events_with_hadronic_steps':sum(e['hadronic_step_count']>0 for e in events),
        'track_species_counts':dict(species), 'hadronic_creator_track_counts':dict(creators),
        'hadronic_interaction_step_counts':dict(interactions),
        'si_ionizing_MeV':math.fsum(e['ionizing_si_MeV'] for e in events),
        'escaped_track_count':sum(t['end_volume']=='OUTSIDE' for t in tracks),
        'escaped_kinetic_energy_MeV':math.fsum(t['end_ke_MeV'] for t in tracks if t['end_volume']=='OUTSIDE'),
        'neutron_tracking_cut_steps':sum(e['neutron_tracking_cut_steps'] for e in events),
        'neutron_tracking_cut_tracks':sum(e['neutron_tracking_cut_tracks'] for e in events),
        'scope':'Descriptive counts for fixed probes; no event-probability or full nuclear mass-energy closure estimate.'}
    report['derived_track_lineage'] = lineage
    return True


def _write(output, report):
    if output is None:
        return
    dest = Path(output).resolve()
    allowed = (ROOT/'local_runtime/dram-see-v4/transport-probe', HERE/'results')
    require(any(dest.is_relative_to(base) and dest!=base for base in allowed), 'Output must be a v4 transport audit subdirectory')
    dest.mkdir(parents=True,exist_ok=True)
    (dest/'audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def _audit(run_dir, mode, output):
    folder=Path(run_dir).resolve()
    report={'schema':'dram-see-v4-transport-audit-v1','mode':mode,'run_dir':str(folder),
            'passed':False,'status':'FAILED_OR_INCOMPLETE','checks':{},'errors':[],
            'audit_code_sha256':sha(Path(__file__)),'tolerances':dict(TOLERANCES),'limits':list(LIMITS),
            'physics_calibrated':False,'full_mass_energy_conservation_verified':False}
    c=Checks(report)
    record=c.run('real_exits_and_frozen_hashes',lambda:_receipt(folder,report))
    if record is not None:
        c.run('binary_source_environment_data_provenance',lambda:_provenance(folder,record,report))
        pair=c.run('initialized_mode_request_and_geometry',lambda:_metadata(folder,record,mode,report))
        if pair is not None:
            metadata,status=pair
            c.run('serial_affinity',lambda:_serial(folder,metadata,report))
            c.run('actual_physics_inventory',lambda:_inventory(folder,metadata,report))
            c.run('primary_events_tracks_steps_and_zero_events',lambda:_events(folder,metadata,status,report))
        c.run('receipt_stable',lambda:require(sha(folder/'record.json')==report['record_sha256'],'Receipt changed during audit') or True)
    report['passed']=not report['errors'] and len(report['checks'])==7
    if report['passed']:
        report['status']='INITIALIZATION_EVIDENCE_PASSED' if mode=='init' else 'TRANSPORT_RECORD_PROBE_PASSED'
    _write(output,report)
    return report


def audit_init(run_dir,output=None):
    return _audit(run_dir,'init',output)


def audit_events(run_dir,output=None):
    return _audit(run_dir,'events',output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('init','events'))
    parser.add_argument('run_dir',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=_audit(args.run_dir,args.mode,args.output)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
