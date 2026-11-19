"""Build explicitly synthetic, isolated archives for S2 parser tests only.

No subprocess/network/native-tool API. No native-source-receipt or extraction
receipt is generated. Public native qualification must reject every fixture.
"""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
S2 = ROOT/'experiments/dram-see-v4/s2-inputs-r1'
ISOLATION = 'UNIT_FIXTURE_NOT_NATIVE'
ORIGIN = 'synthetic_fixture'
LOCK = '/UNIT_FIXTURE_NOT_NATIVE/.solver.lock'
STAMP = '2026-10-16T00:00:00Z'


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def _tagged(value):
    return dict(value, origin=ORIGIN, synthetic=True)


def _write_new(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def _archive(path, contents):
    """No extraction; deterministic plain files without links/special members."""
    with Path(path).open('xb') as stream, tarfile.open(fileobj=stream, mode='w') as archive:
        for name, raw in sorted(contents.items()):
            if Path(name).name != name or name in ('.', '..'):
                raise ValueError('Fixture archive members must be simple basenames')
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o600, 0
            archive.addfile(info, io.BytesIO(raw))


def _csv(columns, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def _lock_evidence():
    return ('origin=synthetic_fixture\nsynthetic=true\nstatus=ACQUIRED\nfd=9\n'
            'lock_path='+LOCK+'\npid=123\nacquired_utc='+STAMP+'\n').encode()


def _process_evidence(tool, prefix):
    """Internally linked synthetic process bytes; never reads /proc or launches."""
    if (tool, prefix) not in (('sdevice', 'step-001-sdevice'), ('svisual', 'svisual')):
        raise ValueError('Only the two registered synthetic tool observations are supported')
    wrapper_pid = 123
    root_child_pid, native_pid = (124, 125) if tool == 'sdevice' else (224, 225)
    root_start_ticks, native_start_ticks = (1000, 1001) if tool == 'sdevice' else (2000, 2001)
    installation_root = '/UNIT_FIXTURE_NOT_NATIVE/installation/W-2024.09'
    status_file = prefix+'-process-status.txt'
    raw_status = (f'Fixture: SYNTHETIC_NOT_NATIVE\nName:\t{tool}\nPid:\t{native_pid}\n'
                  f'PPid:\t{root_child_pid}\nThreads:\t1\nCpus_allowed_list:\t0\n').encode()
    observation = _tagged({
        'schema':'native-process-observation-r1', 'status':'OBSERVED', 'requested_tool':tool,
        'root_child_pid':root_child_pid, 'wrapper_pid':wrapper_pid,
        'installation_root':installation_root, 'native_pid':native_pid,
        'native_executable':installation_root+'/bin/'+tool, 'native_start_ticks':native_start_ticks,
        'parent_chain':[
            {'pid':root_child_pid, 'ppid':wrapper_pid, 'start_ticks':root_start_ticks, 'name':'bash'},
            {'pid':native_pid, 'ppid':root_child_pid, 'start_ticks':native_start_ticks, 'name':tool},
        ],
        'status_file':status_file, 'status_sha256':_digest(raw_status),
    })
    result = {status_file:raw_status, prefix+'-process-observation.json':_json(observation)}
    if tool == 'sdevice':
        admission = _tagged({
            'schema':'native-process-admission-r1', 'status':'PASSED', 'errors':[],
            'requested_tool':tool, 'requested_cpu':'0', 'actual_native_exit_is_separate':True,
        })
        result[prefix+'-process-admission.json'] = _json(admission)
        result[prefix+'-process-admission-exit-code.txt'] = b'0\n'
    return result


def _time_fields(a, reference, spec):
    """83 times, 82 intervals and 81 window files, never native measurements."""
    lo, hi = a.WINDOW
    times = [0., lo]+[lo+(hi-lo)*i/80 for i in range(1, 81)]+[25e-9]
    scopes = ['SILICON_NO_WINDOW']+list(a.ROIS)
    generation = 'IntegrSemiconductor HeavyIonGeneration'
    rows = [{'time': 0., generation: 0.}]
    log = ['SYNTHETIC_NOT_NATIVE UNIT TEST LOG', 'Version W-2024.09',
           'Number of assembly threads: 1 (command line threads)',
           'Number of solver threads: 1 (command line threads)']
    frames, data, payloads = [], {}, {}
    present = spec['case'] != 'A0'
    for i, (left, right) in enumerate(zip(times, times[1:]), 1):
        log += [f'Computing BE-step from {left:.17e} s to {right:.17e} s (Stepsize: {right-left:.17e} s)',
                'Error smaller than 1']
        rate = reference['domain_charge_fC']*spec['amplitude']*a.step_average(left, right, a.T0, a.SIGMA)
        rows.append({'time': right, generation: rate/a.CONVERSION})
        if i > 81:
            continue
        name = f'source_window_{i-1:04d}_access_des.tdr'
        frames.append(name)
        log.append(f"Writing plot '{name}' (TDR format) ... done.")
        payloads[name] = (f'SYNTHETIC_NOT_NATIVE\nS2 unit fixture {name}\n'
                          f'bit={spec["stored_bit"]} case={spec["case"]}\n'
                          f'interval={left:.17e},{right:.17e}\n').encode()
        values = {}
        for scope in scopes:
            roi = 'Total' if scope == 'SILICON_NO_WINDOW' else scope
            expected = reference['rois'][roi]
            values['ONE', scope] = expected['volume_um3']
            if present:
                q = expected['q_fC']*spec['amplitude']*a.step_average(left, right, a.T0, a.SIGMA)/a.CONVERSION
                values['G', scope] = q
                for axis, center in zip('XYZ', expected['centroid_um']):
                    values[axis+'G', scope] = q*center
        for axis, j in zip('XYZ', range(3)):
            values[axis, '-min'], values[axis, '-max'] = a.DOMAIN[j], a.DOMAIN[j+3]
        data[name] = values
    log.append('Sentaurus Device simulation finished (SYNTHETIC_NOT_NATIVE unit fixture).')
    return rows, frames, data, payloads, ('\n'.join(log)+'\n').encode()


def _plt(rows):
    names = ['time', 'IntegrSemiconductor HeavyIonGeneration']
    return ('DF-ISE text\n# SYNTHETIC_NOT_NATIVE\nInfo {\n datasets = [ '
            +' '.join('"'+n+'"' for n in names)+' ]\n}\nData {\n'
            +'\n'.join(' '.join(format(row[n], '.17g') for n in names) for row in rows)+'\n}\n').encode()


def _field_outputs(a, frames, data, payloads, directory):
    fields = a.field_contract()['native_fields']
    measurement, inventory, metadata = [], [], []
    for i, name in enumerate(frames):
        dataset, plot = f'UNIT_fixture_data_{i:04d}', f'UNIT_fixture_plot_{i:04d}'
        inventory += [[name, dataset, 'plot', plot], [name, dataset, 'geometry', dataset],
                      [name, dataset, 'fixture_origin', 'SYNTHETIC_NOT_NATIVE']]
        present = ('G', 'SILICON_NO_WINDOW') in data[name]
        for native in ['X', 'Y', 'Z', 'DopingConcentration']+(['HeavyIonGeneration'] if present else []):
            inventory.append([name, dataset, 'field', native])
        inventory.append([name, dataset, 'material', 'Silicon'])
        inventory.append([name, dataset, 'in_memory_field', fields['ONE']])
        if present:
            for role in ('XG', 'YG', 'ZG'):
                inventory.append([name, dataset, 'in_memory_field', fields[role]])
        for (role, scope), value in data[name].items():
            if scope in ('-min', '-max'):
                measurement.append([name, role, role, 'SILICON_NO_WINDOW', scope, format(value, '.17g'), 'OK'])
            else:
                measurement.append([name, role, fields[role], scope, 'integral', format(value, '.17g'), 'OK'])
        measurement += [[name, '', plot, '', 'remove_plots', plot, 'OK'],
                        [name, '', dataset, '', 'remove_datasets', dataset, 'OK']]
        metadata += [[name, 'state_names', 'state_0', 'OK'], [name, 'current_state', '', 'OK'],
                     [name, 'current_state_index', '1', 'OK'],
                     [name, 'generation_evidence', 'observed_native_field' if present else 'structural_zero_not_measured_zero', 'OK']]
    phases = [('GROUP_BEFORE', name) for name in frames]
    phases += [(phase, name) for name in frames for phase in ('FRAME_BEFORE', 'FRAME_AFTER')]
    phases += [('GROUP_AFTER', name) for name in frames]
    dirs = ['/']+['/'.join(directory.split('/')[:i]) for i in range(2, len(directory.split('/'))+1)]
    chain = '|'.join(path+f'=1:{i+1}:{stat.S_IFDIR | 0o700}:directory' for i, path in enumerate(dirs))
    references = []
    for phase, name in phases:
        references.append([phase, name, directory+'/'+name, _digest(payloads[name]), '1', str(1000+frames.index(name)),
                           str(len(payloads[name])), '1600000000', '1600000000', str(stat.S_IFREG | 0o600), chain, 'OK'])
    return {
        'field-measurements.csv': _csv(['source_file','field','native_field','scope','operation','raw_value','command_status'], measurement),
        'field-inventory.csv': _csv(['source_file','dataset','object_type','native_name'], inventory),
        'tdr-state-metadata.csv': _csv(['source_file','property','raw_value','command_status'], metadata),
        'source-reference-checks.csv': _csv(['phase','source_file','source_path','sha256','device','inode','bytes','mtime','ctime','mode','directory_identity','command_status'], references),
        'diagnostic-status.txt': ('schema=s2-native-field-extraction-r1\norigin=synthetic_fixture\nsynthetic=true\n'
                                  'dimension=3\nintegration=volume_um3\nreference_mode=referenced_original_tdr_not_copied\n'
                                  'memory_release=plot_then_dataset_per_frame\ncleanup_success=exact_deleted_object_name\n'
                                  f'files_requested={len(frames)}\nfiles_completed={len(frames)}\nmandatory_command_errors=0\n').encode(),
    }


def _package_model(package, a):
    model_path = S2.parent/'course-plan-r13/model-contract.proposed.json'
    model = json.loads(model_path.read_text(encoding='utf-8'))
    a.prepare_audit(model, package)
    _write_new(package/'model.proposed.json', model_path.read_bytes())
    geometry = _module(S2/'geometry.py', '_s2_fixture_geometry')
    description = geometry.describe_geometry(model, dimension=3)
    _write_new(package/'geometry-contract.json', _json(description))
    _write_new(package/'fixture-package.json', _json(_tagged({'schema':'s2-fixture-package-r1',
                 'native_qualified':False, 'purpose':'archive parser unit test only; not a native input release'})))
    return model, json.loads((package/'alpha-reference.json').read_text(encoding='utf-8'))


def _materialize(folder, inputs, outputs, record_name, record):
    """Original-shaped local files, all inside the explicitly synthetic root."""
    folder.mkdir(exist_ok=False)
    result = dict(inputs)
    if set(result) & set(outputs):
        raise ValueError('Fixture output would overwrite a frozen input')
    result.update(outputs)
    _archive(folder/'inputs.tar', inputs)
    _archive(folder/'results.tar', result)
    _write_new(folder/'run.sh', result['run.sh'])
    for name, raw in result.items():
        _write_new(folder/'collected'/name, raw)
    record = _tagged(dict(record, input_sha256={name:_digest(raw) for name,raw in inputs.items()},
                          ssh_exit_code=0, remote_exit_code=0, collection_exit_code=0))
    archive_hash = _digest((folder/'results.tar').read_bytes())
    record['results_sha256' if record_name=='manifest.json' else 'archive_sha256'] = archive_hash
    record['wrapper_sha256'] = _digest(result['run.sh'])
    _write_new(folder/record_name, _json(record))
    return record, archive_hash


def build_fixture(root: Path, bit=0, case='Aalpha') -> dict:
    """Build a new complete synthetic archive family; return three Path objects.

    The public native audit must reject the returned family. Only the dedicated
    audit_fixture path may evaluate parser/numerical behavior.
    """
    root = Path(root).resolve()
    if ISOLATION not in root.name or root.exists() or any(p.lower()=='runs' for p in root.parts):
        raise ValueError('Use a new explicitly named UNIT_FIXTURE_NOT_NATIVE root outside all real runs directories')
    a = _module(S2/'alpha.py', '_s2_fixture_alpha')
    spec = a.source_spec(case, bit, 'main')
    root.mkdir(parents=True, exist_ok=False)
    marker = _tagged({'schema':'s2-unit-fixture-manifest-r1','is_tcad_result':False,'native_qualified':False,
                      'native_calls':0,'purpose':'synthetic complete-archive parsing only',
                      'created_by':'tests/fixtures.py','stored_bit':bit,'source_case':case})
    _write_new(root/'fixture-manifest.json', _json(marker))
    package = root/'package'
    model, reference = _package_model(package, a)
    rows, frames, values, payloads, native_log = _time_fields(a, reference, spec)
    solver = root/f'solver-UNIT_FIXTURE_NOT_NATIVE-b{bit}-{case}'
    extraction = root/f'extraction-UNIT_FIXTURE_NOT_NATIVE-b{bit}-{case}'
    remote = '/UNIT_FIXTURE_NOT_NATIVE/runs/'+solver.name
    role = f'UNIT_FIXTURE_NOT_NATIVE-S2-{case}-main-b{bit}'
    prefix = '' if case=='Aalpha' else case+'.'
    activated = [] if case=='A0' else [prefix+'heavyion.physics.inc', prefix+'source.par']
    source_names = ['source-contract.json','field-contract.json','alpha-reference.json','alpha-profile.csv',
                    'model.proposed.json','geometry-contract.json']+activated
    inputs = {name:(package/name).read_bytes() for name in source_names}
    inputs['source-spec.json'] = _json(spec)
    mesh = b'SYNTHETIC_NOT_NATIVE\nS2 synthetic mesh bytes; not a TDR file.\n'
    inputs['cell_msh.tdr'] = mesh
    authority = _tagged({'schema':'s2-unit-only-authority-r1','explicit_native_authorization':True,
                         'role_ids':[role], 'statement':'SYNTHETIC UNIT FIXTURE ONLY; never real user authorization'})
    inputs['authorization-evidence.json'] = _json(authority)
    inputs['budget-ledger.synthetic.json'] = _json(_tagged({'budget_id':'UNIT_FIXTURE_NOT_NATIVE_BUDGET',
                                                          'statement':'No real budget or reservation exists'}))
    runner_digest = _digest((ROOT/'scripts/tcad.py').read_bytes())
    operation_digest = _digest((ROOT/'experiments/dram-see-v4/transport-probe/operation.py').read_bytes())
    release = _tagged({'schema':'s2-execution-release-r1','status':'RELEASED','execution_enabled':True,
                       'explicit_native_authorization':True,'scheduler':'root','threads':1,'cpu_count':1,
                       'role_id':role,'stored_bit':bit,'source_case':case,'numerical_variant':'main',
                       'activated_source_include_files':activated,'shared_lock_path':LOCK,
                       'budget_id':'UNIT_FIXTURE_NOT_NATIVE_BUDGET','budget_reservation_id':'UNIT_FIXTURE_NOT_NATIVE_RESERVATION',
                       'budget_ledger_sha256':_digest(inputs['budget-ledger.synthetic.json']),
                       'authorization_evidence_file':'authorization-evidence.json',
                       'authorization_evidence_sha256':_digest(inputs['authorization-evidence.json']),
                       'interface_sha256':{name:_digest((HERE.parent/name).read_bytes()) for name in ('evidence.py','audit.py')},
                       'expected_runner_sha256':runner_digest,'expected_operation_sha256':operation_digest})
    if case=='A0':
        release.update(d3_mesh_sha256=_digest(mesh), d3_producer_run_id='UNIT_FIXTURE_NOT_NATIVE_D3_PRODUCER')
    inputs['execution-release.json'] = _json(release)
    active = '' if not activated else ' #include "'+activated[0]+'"\n'
    inputs['device.cmd'] = ('* SYNTHETIC_NOT_NATIVE: parser fixture, never execute.\n'
                             'File { Grid="cell_msh.tdr" Parameter="physics.par" }\n'
                             'Physics {\n'+active+'}\n').encode()
    inputs['physics.par'] = ('* SYNTHETIC_NOT_NATIVE: no physical native card.\n'+
                            ('' if not activated else '#include "'+activated[1]+'"\n')).encode()
    steps = [{'tool':'sdevice','args':['device.cmd'],'outputs':['access_device.plt','transient_des.log']+frames}]
    inputs['project.json'] = _json(_tagged({'name':f'unit-fixture-not-native-s2-b{bit}-{case.lower()}','steps':steps,
                                           'warning':'SYNTHETIC ONLY; no actual native execution authority'}))
    geometry_evidence = {
        'material-measurements.csv':_csv(['origin','synthetic','material','volume_um3'],[[ORIGIN,'true','Silicon',reference['expected_silicon_volume_um3']]]),
        'contact-measurements.csv':_csv(['origin','synthetic','contact','count'],[[ORIGIN,'true',name,1] for name in ['source','drain','gate','body']]),
        'doping-measurements.csv':_csv(['origin','synthetic','x_um','y_um','z_um','donor_cm3','acceptor_cm3'],[[ORIGIN,'true',-.052,0.,.01,1e20,1e17]]),
    }
    geometry_report = _tagged({'schema':'s2-native-geometry-validation-r1','mesh_sha256':_digest(mesh),
                               'checks':{'materials':True,'contacts':True,'doping':True,'units':True},
                               'evidence_sha256':{name:_digest(raw) for name,raw in geometry_evidence.items()},
                               'warning':'Synthetic parser tokens; never actual native geometry qualification'})
    solver_script = (f'#!/bin/bash\n# SYNTHETIC_NOT_NATIVE; fixture text, never executed.\nset -euo pipefail\n'
                      f'exec 9>{LOCK}\nflock -n 9\n'
                      'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1\n'
                      'taskset -c 0 sdevice --threads 1 --exit-on-failure device.cmd\n'
                      'echo ENGINEERING_RUN_COMPLETED\n').encode()
    outputs = dict(payloads)
    outputs.update(geometry_evidence)
    outputs.update(_process_evidence('sdevice', 'step-001-sdevice'))
    outputs.update({'geometry-validation.json':_json(geometry_report),'run.sh':solver_script,
                    'access_device.plt':_plt(rows),'transient_des.log':native_log,
                    'execution.log':b'SYNTHETIC_NOT_NATIVE\nSTEP 1: sdevice --threads 1 --exit-on-failure device.cmd\nENGINEERING_RUN_COMPLETED\n',
                    'exit-code.txt':b'0\n','step-001-sdevice-exit-code.txt':b'0\n',
                    'shared-lock-evidence.txt':_lock_evidence()})
    sm, solver_archive_hash = _materialize(solver, inputs, outputs, 'manifest.json',
                   {'run_id':solver.name,'state':'COLLECTED','steps':steps,'remote_directory':remote,
                    'runner_sha256':runner_digest,
                    'interpretation':'SYNTHETIC fixture only; no subprocess was executed'})
    extract_inputs = {name:(package/name).read_bytes() for name in ['extract_fields.tcl','field-contract.json','windows.tcldata']}
    extract_inputs.update({'source-spec.json':_json(spec),'source-case.txt':(case+'\n').encode(),
                           'source-directory.txt':(remote+'\n').encode(),
                           'tdr-files.txt':(''.join(name+'\n' for name in frames)).encode(),
                           'tdr-sha256.txt':(''.join(_digest(payloads[name])+'  '+name+'\n' for name in frames)).encode()})
    source_evidence = _tagged({'schema':'s2-synthetic-source-reference-r1','source_run_id':solver.name,
                               'source_archive_sha256':solver_archive_hash,'source_manifest_sha256':_digest((solver/'manifest.json').read_bytes()),
                               'source_remote_directory':remote,'tdr_sha256':{n:_digest(payloads[n]) for n in frames},
                               'tdr_bytes':{n:len(payloads[n]) for n in frames},'tdr_payload_copied':False,
                               'reference_mode':'referenced_original_tdr_not_copied'})
    extract_inputs['source-evidence.json'] = _json(source_evidence)
    extract_inputs['source-provenance.json'] = _json(_tagged({'source_run_id':solver.name,'only_unit_fixture':True}))
    extract_inputs['task.sh'] = (b'# SYNTHETIC_NOT_NATIVE; never executed\nset -euo pipefail\n'
                                 b'svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl\n'
                                 b'echo NATIVE_FIELD_POSTPROCESS_COMPLETED\n')
    extract_outputs = _field_outputs(a, frames, values, payloads, remote)
    extract_outputs.update(_process_evidence('svisual', 'svisual'))
    extract_script = (f'#!/bin/bash\n# SYNTHETIC_NOT_NATIVE; never executed.\nset -euo pipefail\n'
                       f'exec 9>{LOCK}\nflock -n 9\ntaskset -pc 0 $$\nbash task.sh\necho V4_OPERATION_COMPLETED\n').encode()
    extract_outputs.update({'run.sh':extract_script,'exit-code.txt':b'0\n','svisual-exit-code.txt':b'0\n',
                            'affinity.txt':b'Threads:\t1\nCpus_allowed_list:\t0\n',
                            'shared-lock-evidence.txt':_lock_evidence(),
                            'svisual.log':b'SYNTHETIC_NOT_NATIVE\nVersion W-2024.09\nMultithreading will use 1 threads\nFIELD_AUDIT_COMPLETED mandatory_errors=0\n',
                            'execution.log':b'SYNTHETIC_NOT_NATIVE\nNATIVE_FIELD_POSTPROCESS_COMPLETED\nV4_OPERATION_COMPLETED\n'})
    _materialize(extraction, extract_inputs, extract_outputs, 'operation.json',
                  {'label':extraction.name,'state':'COLLECTED_PENDING_AUDIT',
                   'adapter_sha256':operation_digest,
                   'remote_directory':'/UNIT_FIXTURE_NOT_NATIVE/operations/'+extraction.name,
                   'interpretation':'SYNTHETIC fixture only; no SVisual command was executed'})
    _write_new(root/'fixture-inventory.json', _json(_tagged({'schema':'s2-synthetic-fixture-inventory-r1',
                 'time_points':len(rows),'accepted_BE_intervals':len(rows)-1,'source_window_frames':len(frames),
                 'source_window_integrated_intervals':80,'stored_bit':bit,'source_case':case,
                 'solver':solver.name,'extraction':extraction.name,'package':package.name,
                 'native_qualified':False,'is_tcad_result':False,'native_calls':0,
                 'sha256':{str(path.relative_to(root)).replace('\\','/'):_digest(path.read_bytes())
                           for path in sorted(root.rglob('*')) if path.is_file()}})))
    return {'solver':solver,'extraction':extraction,'package':package}
