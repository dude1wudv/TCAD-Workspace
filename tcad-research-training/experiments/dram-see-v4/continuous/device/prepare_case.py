"""Prepare one controlled case, never a batch, scheduler, native result or receipt.

Private installed cards stay below continuous/device in ignored local_runtime.
Only the gate-top-depth family and the original numerical/source controls are
accepted. A transient requires the complete original native D3 archive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import alpha_source
import alpha_v2_inputs
import case_contract
import decks
import dc_continuation
import doping_patch
import geometry
import geometry_bridge as bridge
import measurements
import mesh_continuation
import metadata_continuation
import mesh_patch
import mesh_policy_registry as mesh_policy
import native_scripts
import numerics_patch
import observer_patch
import physics_patch
import prospective
import proton_inputs
import prepare as first
import visual_patch
import two_dimensional

HERE, ROOT, CANDIDATE, OUTPUT = first.HERE, first.ROOT, first.CANDIDATE, first.OUTPUT
PHYSICS_FILES = ('physics.par', 'physics-manifest.json', 'Silicon.par', 'Oxide.par')
SNAPSHOT_FILES = ('prepare_case.py', 'prepare.py', 'case_contract.py', 'geometry.py', 'decks.py',
    'alpha_source.py', 'measurements.py', 'native_scripts.py', 'observer_patch.py',
    'doping_patch.py', 'mesh_patch.py', 'visual_patch.py', 'physics_patch.py', 'numerics_patch.py', 'prospective.py','proton_inputs.py','alpha_v2_inputs.py',
    'mesh_policy.py','mesh_policy_v2.py','mesh_policy_v3.py','mesh_policy_v4.py','mesh_policy_v5.py','mesh_policy_v6.py','mesh_policy_registry.py',
    'mesh_continuation.py','metadata_continuation.py','dc_continuation.py')


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def baseline_model(depth, sn_junction_depth_nm=87):
    model = first.obj(CANDIDATE / 'roles/B1-D3/model.proposed.json')
    case_contract.size_id(depth)
    model['geometry']['gate_top_depth_nm'] = depth
    model['doping']['sn_junction_depth_nm'] = case_contract.sn_depth(sn_junction_depth_nm)
    report = geometry.validate_geometry(model)
    case_contract.require(report['passed'], 'Invalid declared geometry: ' + '; '.join(report['errors']))
    return model


def require_model_parameters(request, model):
    """An A0/request cannot silently inherit a different producer's doping."""
    case_contract.require(model['geometry']['gate_top_depth_nm']==request['gate_top_depth_nm'], 'D3 gate depth differs')
    case_contract.require(model['doping']['sn_junction_depth_nm']==request.get('sn_junction_depth_nm',87),
                          'D3 SN junction depth differs')


def parameter_contract(request, model, files, d3_binding=None):
    require_model_parameters(request,model)
    description=json.loads(files['geometry-contract.json'])
    names=('model.proposed.json','geometry-contract.json')+ (('measurement-plan.json','geometry-with-measurements.scm') if 'measurement-plan.json' in files else ())
    names += tuple(name for name in mesh_policy.FILES if name in files)
    return dict(schema='dram-see-v4-controlled-device-parameters-r1',parameter_id=case_contract.parameter_id(request),
        gate_top_depth_nm=request['gate_top_depth_nm'],sn_junction_depth_nm=request.get('sn_junction_depth_nm',87),
        units=dict(gate_top_depth='nm',sn_junction_depth='nm',native_length='um',concentration='cm^-3'),
        native_sn_junction_depth_um=model['doping']['sn_junction_depth_nm']/1000.,
        native_gaussian_width_um=description['doping']['a_sn_um'],
        native_general_initialization=description['doping']['initialization'],
        bound_files_sha256={name:digest(files[name]) for name in names},
        actual_D3_binding=d3_binding,measurement_policy='Original probe coordinates and numerical tolerances retained; expected doping recomputed from selected model',
        native_parameter_validation_completed=False)


def current_physics(model, device):
    source = CANDIDATE / 'roles/B1-D3'
    result = physics_patch.apply(device, (source/'physics.par').read_text(encoding='utf-8'),
                                 first.obj(source/'physics-manifest.json'), model)
    files = {'physics.par': result['parameters'].encode('utf-8'),
             'physics-manifest.json': raw_json(result['manifest']),
             'model.proposed.json': raw_json(result['model'])}
    for name in ('Silicon.par', 'Oxide.par'):
        files[name] = (source/name).read_bytes()
    return result['model'], result['device'], files


def producer_payload(request):
    """Pure payload construction; declaration/fixtures never imply native geometry."""
    request = case_contract.validate(request)
    case_contract.require(request['kind'] == 'dc', 'Producer is a DC role')
    dimension, variant = request['dimension'], request['variant']
    model = baseline_model(request['gate_top_depth_nm'],request['sn_junction_depth_nm'])
    model, device, files = current_physics(model, decks.render_dc(model, dimension))
    device = numerics_patch.apply(device, dimension)
    scale = .5 if variant == 'mesh' else 1
    description = geometry.describe_geometry(model, dimension, scale)
    description['mesh']['active_doping_refinement'] = mesh_patch.specification(dimension, scale)
    description['mesh']['numerical_variant'] = variant
    selected_mesh = None
    if request.get('mesh_policy'):
        selected_mesh, policy_files = mesh_policy.build(request['mesh_policy'],files['model.proposed.json'],description,scale)
        files.update(policy_files)
        description = mesh_policy.describe(description,selected_mesh,files['mesh-policy.json'])
    files['geometry-contract.json'] = raw_json(description)
    plan = dict(schema='s2-geometry-measurement-plan-r1', role_id=case_contract.role_id(request),
        dimension=dimension, geometry_contract_sha256=digest(files['geometry-contract.json']),
        execution_enabled=True, actual_mesh_sha256=None, expected_geometry=description,
        origin='declared_expectation_not_measurement', native_qualified=False,
        comparison_policy=dict(measurements.POLICY))
    plan['measurements'], plan['contact_probes'], plan['material_probes'] = measurements.measurement_plan(description)
    text = geometry.render_sde(model, dimension, scale) + '\n' + native_scripts.render_sde(plan)
    text = observer_patch.apply(text, dimension)
    text = doping_patch.apply(text, dimension)
    text = mesh_patch.apply(text, dimension, scale)
    if selected_mesh:
        text = mesh_policy.apply(text,selected_mesh)
    files.update({'measurement-plan.json': raw_json(plan),
        'geometry-with-measurements.scm': text.encode('utf-8'),
        'measure-geometry.tcl': visual_patch.apply(native_scripts.render_svisual(plan)).encode('utf-8'),
        'device.cmd': device.encode('utf-8'),
        'numerical-method.json': raw_json(numerics_patch.contract(dimension))})
    files['controlled-parameters.json']=raw_json(parameter_contract(request,model,files))
    return files, model


def control_payload(model, request, producer_binding, producer_inputs):
    """Source-free A0 for controlled parameters; does not borrow an S2 source oracle."""
    case_contract.require(request['source_case']=='A0' and request.get('particle','alpha')=='alpha',
                          'Only source-free device controls use this contract')
    require_model_parameters(request,model)
    spec=dict(schema='continuous-particle-source-spec-v1',particle='alpha',role='CONTROL',
        stored_bit=request['stored_bit'],numerical_variant=request['variant'],
        physics_manifest_sha256=digest(producer_inputs['physics-manifest.json']))
    contract=dict(schema='dram-see-v4-controlled-a0-source-contract-r1',source_configured=False,
        structural_source_absence=True,source_field_absence='structural absence, never measured zero',
        parameter_id=case_contract.parameter_id(request),producer_binding=producer_binding,
        model_sha256=digest(producer_inputs['model.proposed.json']),
        geometry_contract_sha256=digest(producer_inputs['geometry-contract.json']),
        native_source_qualified=False,native_A0_functionality_qualified=False,
        source_oracle=None,source_waveform=None,physical_parameter_fitting=False,
        observation_window_s=[[s['start_s'],s['end_s']] for s in decks.transient_segments(model) if s['source_window']][0])
    return {'source-spec.json':raw_json(spec),'source-contract.json':raw_json(contract)},''


def source_payload(model, request, producer_binding):
    """Reuse the already checked S2 reference; generate only the exact requested source."""
    alpha_source.validate_model(model)
    case, bit, variant = request['source_case'], request['stored_bit'], request['variant']
    original = CANDIDATE/'roles/B1-A0-main-b0'
    # The retained independent reference uses this exact Si mask and 5 MeV table.
    prior_model = first.obj(original/'model.proposed.json')
    for key in ('geometry', 'doping', 'circuit', 'alpha', 'numerics'):
        case_contract.require(model[key] == prior_model[key], 'S2 reference cannot be stretched to a different ' + key)
    files = {name: (original/name).read_bytes() for name in
             ('alpha-reference.json', 'alpha-profile.csv', 'windows.tcldata', 'extract_fields.tcl')}
    case_contract.require(digest(files['alpha-profile.csv']) == first.sha(alpha_source.PROFILE), 'Actual ASTAR source table differs')
    spec = alpha_source.source_spec(case, bit, variant)
    field = first.obj(original/'field-contract.json')
    field.update(status='CURRENT_OBSERVATION_CONTRACT_NOT_NATIVE_QUALIFICATION', execution_enabled=True)
    source = first.obj(original/'source-contract.json')
    for name in ('native_calls', 'alpha_roles_added_to_first_four'):
        source.pop(name, None)
    source.update(status='CURRENT_DECLARED_SOURCE_NOT_NATIVE_QUALIFICATION', execution_enabled=True,
        native_qualified=False, model_snapshot=model,
        model_sha256=digest(json.dumps(model, sort_keys=True, separators=(',', ':')).encode('utf-8')),
        geometry=model['geometry'], alpha=model['alpha'], current_spec=spec,
        size_id=case_contract.size_id(request['gate_top_depth_nm']),
        producer_binding=producer_binding,
        independent_reference_reused=dict(path=str((original/'alpha-reference.json').relative_to(ROOT)).replace('\\','/'),
            sha256=digest(files['alpha-reference.json']),
            reason='Same S2 geometry, Si mask, table, temporal kernel and numerical expectations; original checked reference retained'),
        physical_parameter_fitting=False, source_renormalization=False,
        current_generator_snapshots={name: first.sha(HERE/name) for name in SNAPSHOT_FILES})
    physical, parameters = alpha_source.render_source(alpha_source.load_profile(), case)
    if case != 'A0':
        prefix = '' if case == 'Aalpha' else case+'.'
        files[prefix+'heavyion.physics.inc'] = physical.encode('utf-8')
        files[prefix+'source.par'] = parameters.encode('utf-8')
        files['heavyion.plot.inc'] = b'HeavyIonGeneration HeavyIonChargeDensity\n'
        files['heavyion.currentplot.inc'] = b'CurrentPlot {\n HeavyIonGeneration( Integrate(Semiconductor) )\n}\n'
    files.update({'source-spec.json': raw_json(spec), 'source-contract.json': raw_json(source),
                  'field-contract.json': raw_json(field)})
    return files, physical if case != 'A0' else ''


def transient_payload(model, request, producer_binding, producer_inputs):
    """Exact base physics + LF + source parameters, with SDevice's active filename bound."""
    request = case_contract.validate(request)
    case_contract.require(request['kind'] == 'transient', 'Transient request required')
    files = {name: producer_inputs[name] for name in PHYSICS_FILES + ('model.proposed.json', 'geometry-contract.json')}
    files.update(mesh_policy.inherit(producer_inputs))
    case_contract.require(json.loads(files['model.proposed.json'].decode('utf-8')) == model, 'Producer model bytes differ')
    case_contract.require(model.get('physics_assumption_id') == physics_patch.ASSUMPTION_ID, 'Unexpected current physical branch')
    require_model_parameters(request,model)
    if request['source_case']=='A0' and (request['gate_top_depth_nm'],request['sn_junction_depth_nm'])!=(80,87):
        source_files,physical=control_payload(model,request,producer_binding,producer_inputs)
    else:
        source_files, physical = source_payload(model, request, producer_binding)
    files.update(source_files)
    case = request['source_case']
    device = decks.render_transient(model, request['stored_bit'], source_block=physical,
        source_plot='' if case == 'A0' else 'HeavyIonGeneration HeavyIonChargeDensity',
        time_scale=.5 if request['variant'] == 'time' else 1)
    case_contract.require(device.count(physics_patch.SELECTOR_OLD) == 1, 'Unexpected transient physics selector')
    device = device.replace(physics_patch.SELECTOR_OLD, physics_patch.SELECTOR_NEW)
    device = numerics_patch.apply(device, 3, mixed=True)
    binding = dict(schema='dram-see-v4-active-parameters-r1', base_file='physics.par',
        base_sha256=digest(files['physics.par']), source_file=None, source_sha256=None,
        source_physics_file=None, source_physics_sha256=None,
        active_file='physics.par', active_sha256=digest(files['physics.par']), aggregation='base_only')
    if case != 'A0':
        prefix = '' if case == 'Aalpha' else case+'.'
        source_name, physical_name = prefix+'source.par', prefix+'heavyion.physics.inc'
        files['run-parameters.par'] = files['physics.par'] + b'\n' + files[source_name]
        case_contract.require(device.count('Parameter="physics.par"') == 1, 'Unexpected active parameter selector')
        device = device.replace('Parameter="physics.par"', 'Parameter="run-parameters.par"')
        case_contract.require(device.count('Math {') == 1, 'Unexpected global Math section')
        device = device.replace('Math {', files['heavyion.currentplot.inc'].decode('utf-8')+'Math {', 1)
        binding.update(source_file=source_name, source_sha256=digest(files[source_name]),
            source_physics_file=physical_name, source_physics_sha256=digest(files[physical_name]),
            active_file='run-parameters.par', active_sha256=digest(files['run-parameters.par']),
            aggregation='base_bytes + LF + source_bytes')
    files['device.cmd'] = device.encode('utf-8')
    files['parameter-binding.json'] = raw_json(binding)
    files['numerical-method.json'] = raw_json(numerics_patch.contract(3, mixed=True))
    files['controlled-parameters.json']=raw_json(parameter_contract(request,model,files,producer_binding))
    return files


def producer_binding(bundle, cfg):
    result = dict(producer_run_id=cfg['producer_run_id'], source_manifest_sha256=bundle['manifest_sha256'],
        source_archive_sha256=bundle['archive_sha256'], mesh_sha256=bundle['mesh_sha256'],
        geometry_validation_sha256=bundle['geometry_validation_sha256'],
        geometry_contract_sha256=digest(bundle['producer_inputs']['geometry-contract.json']),
        model_sha256=digest(bundle['producer_inputs']['model.proposed.json']), physics_sha256=bundle['physics_sha256'])
    if 'mesh-policy.json' in bundle['producer_inputs']:
        result.update(mesh_policy_id=json.loads(bundle['producer_inputs']['mesh-policy.json'])['policy_id'],
                      mesh_policy_sha256=digest(bundle['producer_inputs']['mesh-policy.json']))
    if 'mesh_representation' in bundle:
        result.update({n:bundle[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
    for name in dc_continuation.SELECTOR_CFG_FIELDS+('dc_completed_binding_sha256',):
        if name in bundle:result[name]=bundle[name]
    return result


def source_free_deck(files, source_case):
    """Remove only exact declared additions to compare all remaining A0 bytes."""
    actual = files['device.cmd'].decode('utf-8')
    if 'device-source-binding.json' in files:
        if json.loads(files['device-source-binding.json']).get('source_version')==case_contract.ALPHA_V2:
            return alpha_v2_inputs.source_free_deck(files)
        return proton_inputs.source_free_deck(files)
    if source_case == 'A0':
        return actual
    prefix = '' if source_case == 'Aalpha' else source_case+'.'
    actual = actual.replace(files[prefix+'heavyion.physics.inc'].decode('utf-8'), '')
    actual = actual.replace(files['heavyion.currentplot.inc'].decode('utf-8'), '')
    actual = actual.replace(' HeavyIonGeneration HeavyIonChargeDensity', ' ')
    return actual.replace('Parameter="run-parameters.par"', 'Parameter="physics.par"')


def matched_baseline(path, request, cfg, files, runner_sha):
    path = Path(path).resolve()
    case_contract.require(path.is_dir() and not path.is_symlink(), 'Matched A0 project does not exist')
    spec = first.obj(path/'project.json')
    bridge.geometry_admit(path, spec, runner_sha)
    source = first.obj(path/'source-spec.json')
    if source.get('schema')=='continuous-particle-source-spec-v1':
        case_contract.require(source.get('particle')==request.get('particle','alpha'),'Matched A0 particle context differs')
        case_contract.require(source.get('role')=='CONTROL' and source.get('stored_bit')==request['stored_bit']
            and source.get('numerical_variant')==request['variant'], 'Matched A0 bit/variant/source absence differs')
        if request.get('particle')=='proton':
            for name in ('source-time-contract.json','source-bundle.json'):
                case_contract.require((path/name).read_bytes()==files[name],'Proton control belongs to another event/window: '+name)
        if request.get('source_version')==case_contract.ALPHA_V2:
            case_contract.require(source.get('source_version')==case_contract.ALPHA_V2,'Alpha v2 requires the explicit v2 matched control')
            for name in ('source-time-contract.json','source-packet.json'):
                case_contract.require((path/name).read_bytes()==files[name],'Alpha v2 control belongs to another source/window: '+name)
    else:
        expected = alpha_source.source_spec('A0', request['stored_bit'], request['variant'])
        case_contract.require(source == expected, 'Matched A0 bit/variant/source absence differs')
    prior = spec['s2_geometry']
    for key in ('producer_run_id', 'source_archive_sha256', 'mesh_sha256', 'geometry_validation_sha256'):
        case_contract.require(prior.get(key) == cfg[key], 'Matched A0 D3 identity differs: ' + key)
    case_contract.require(prior.get('sn_junction_depth_nm',87)==request.get('sn_junction_depth_nm',87),
                          'Matched A0 SN junction depth differs')
    for name in PHYSICS_FILES + ('geometry-contract.json', 'model.proposed.json', 'numerical-method.json'):
        case_contract.require((path/name).read_bytes() == files[name], 'Matched A0 differs: ' + name)
    for name in mesh_policy.FILES:
        case_contract.require((path/name).exists()==(name in files), 'Matched A0 mesh-policy presence differs: '+name)
        if name in files:
            case_contract.require((path/name).read_bytes()==files[name], 'Matched A0 mesh policy differs: '+name)
    # Compare the real complete control deck, after removing only declared source additions.
    actual = source_free_deck(files, request['source_case'])
    case_contract.require(actual == (path/'device.cmd').read_text(encoding='utf-8'),
                          'Signal and matched A0 waveform/numerical/physics decks differ outside declared source additions')
    return dict(project=str(path), input_manifest_sha256=first.sha(path/'input-manifest.json'),
        device_sha256=first.sha(path/'device.cmd'), run_id=prior['run_id'], stored_bit=request['stored_bit'],
        numerical_variant=request['variant'], producer_run_id=prior['producer_run_id'],
        input_identity_only=True, native_functionality_qualified=False,
        qualification='Requires actual original A0 results and unchanged functional/KCL checks; frozen input is not success')


def prepare_2d(request, run_id, runner=None, output=None):
    """One real-source 2D A0 input; old 3D contracts and source oracles stay separate."""
    request=case_contract.validate(request)
    case_contract.require(request['schema']==case_contract.SCHEMA_2D, 'Explicit 2D request required')
    case_contract.require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',run_id), 'Unsafe run ID')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve()
    case_contract.require(runner==(ROOT/'scripts/tcad.py').resolve() and runner.is_file(), 'Use original scripts/tcad.py')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    case_contract.require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),
                          '2D preparation needs a new allowed nonfixture directory')
    request['d2_source_run']=str(Path(request['d2_source_run']).resolve())
    role=case_contract.role_id(request);runner_sha=first.sha(runner)
    cfg=dict(schema=bridge.GEOMETRY_SCHEMA,mode='reuse',dimension_branch=two_dimensional.BRANCH,
        role_id=role,run_id=run_id,producer_run_id=Path(request['d2_source_run']).name,
        execution_enabled=True,synthetic=False,source_run_directory=request['d2_source_run'],
        source_dimension=2,effective_width_nm=20,area_factor=.02,size_id=case_contract.size_id(80),
        sn_junction_depth_nm=87,numerical_variant=request['variant'],parameter_id=case_contract.parameter_id(request))
    bundle=bridge.geometry_source_bundle(target,cfg)
    cfg.update(source_manifest_sha256=bundle['manifest_sha256'],source_archive_sha256=bundle['archive_sha256'],
        mesh_sha256=bundle['mesh_sha256'],geometry_validation_sha256=bundle['geometry_validation_sha256'],
        d2_source_binding_sha256=bundle['d2_source_binding_sha256'])
    files=dict(bundle['producer_inputs']);files.update(bundle['generated_files'])
    model=json.loads(files['model.proposed.json'])
    require_model_parameters(request,model)
    device=decks.render_transient(model,request['stored_bit'],time_scale=.5 if request['variant']=='time' else 1,
                                  dimension=2,effective_width_nm=20)
    case_contract.require(device.count(physics_patch.SELECTOR_OLD)==1, 'Unexpected 2D physics selector')
    device=device.replace(physics_patch.SELECTOR_OLD,physics_patch.SELECTOR_NEW)
    device=numerics_patch.apply(device,2,mixed=True)
    files['device.cmd']=device.encode('utf-8')
    files['numerical-method.json']=raw_json(numerics_patch.contract(2,mixed=True))
    width=two_dimensional.dimensional_contract(bundle['d2_binding'])
    files['dimensional-contract.json']=raw_json(width)
    cfg['dimensional_contract_sha256']=digest(files['dimensional-contract.json'])
    initialization=dict(schema='dram-see-v4-common-neutral-initialization-r1',dimension=2,
        source_model_sha256=digest(files['model.proposed.json']),common_sn_V=.6,initial_wl_V=-.5,
        target_bit_dependent_sn=False,load_written_state=False,clamp_during_transient=False,
        sequence=['System Set(sn=0.6)','Coupled Poisson','Coupled Poisson Electron Hole Contact Circuit',
                  'initial plot','Unset(sn)','actual write/hold/read Transient'],
        scope='Neutral common initialization only; target bit is written through the access device and driver',
        authority='Current root clarification for the user-authorized 2D transition; original shared0.6V initialization retained')
    files['initialization-contract.json']=raw_json(initialization)
    files['parameter-binding.json']=raw_json(dict(schema='dram-see-v4-active-parameters-r1',base_file='physics.par',
        base_sha256=digest(files['physics.par']),source_file=None,source_sha256=None,source_physics_file=None,
        source_physics_sha256=None,active_file='physics.par',active_sha256=digest(files['physics.par']),aggregation='base_only'))
    files['source-spec.json']=raw_json(dict(schema='dram-see-v4-2d-control-source-spec-r1',role='CONTROL',
        source_case='A0',dimension=2,stored_bit=request['stored_bit'],numerical_variant=request['variant'],
        source_configured=False,physics_manifest_sha256=digest(files['physics-manifest.json']),
        dimensional_contract_sha256=cfg['dimensional_contract_sha256']))
    files['source-contract.json']=raw_json(dict(schema='dram-see-v4-2d-structural-control-r1',source_configured=False,
        dimension=2,structural_source_absence=True,source_field_absence='structural absence, never measured zero',
        producer_binding=dict(producer_role_id='B1-D2',producer_run_id=cfg['producer_run_id'],source_dimension=2,
            source_manifest_sha256=cfg['source_manifest_sha256'],source_archive_sha256=cfg['source_archive_sha256'],
            mesh_sha256=cfg['mesh_sha256'],geometry_validation_sha256=cfg['geometry_validation_sha256'],
            d2_source_binding_sha256=cfg['d2_source_binding_sha256']),
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],native_source_qualified=False,
        native_A0_functionality_qualified=False,particle_oracle=None))
    files['controlled-parameters.json']=raw_json(dict(schema='dram-see-v4-2d-control-parameters-r1',dimension=2,
        parameter_id=cfg['parameter_id'],gate_top_depth_nm=80,sn_junction_depth_nm=87,effective_width_nm=20,
        actual_D2_binding_sha256=cfg['d2_source_binding_sha256'],
        bound_files_sha256={n:digest(files[n]) for n in ('geometry-contract.json','model.proposed.json','dimensional-contract.json')}))
    template=CANDIDATE/'roles'/('B1-A0-main-b'+str(request['stored_bit']))
    role_contract=first.obj(template/'role-contract.json')
    role_contract.update(schema='dram-see-v4-2d-control-role-r1',role=role,dimension=2,case='A0',
        stored_bit=request['stored_bit'],numerical_variant=request['variant'],execution_enabled=True,
        area_factor=.02,effective_width_nm=20,source_configured=False,source_dimension=2,
        parent_model_file_sha256=digest(files['model.proposed.json']),
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],
        initialization_contract_sha256=digest(files['initialization-contract.json']),
        transient_segments=decks.transient_segments(model,.5 if request['variant']=='time' else 1),
        native_syntax_verified=False,native_A0_functionality_qualified=False)
    role_contract['stop_conditions']=[s.replace('resource/budget/lock/owner failure','actual resource/lock/owner failure')
                                      for s in role_contract['stop_conditions']]
    files['role-contract.json']=raw_json(role_contract)
    files['metrics.py']=(template/'metrics.py').read_bytes()
    files['functional-criteria.json']=raw_json(dict(schema='dram-see-v4-2d-functional-criteria-r1',
        inherited_metrics_sha256=digest(files['metrics.py']),write_time_s=6e-9,write0_max_V=.12,write1_min_V=1.08,
        hold_window_s=[8.1e-9,19.9e-9],hold_drift_max_V=.005,precharge_time_s=8.1e-9,precharge_target_V=.6,
        precharge_error_max_V=.001,read_window_s=[21.9e-9,22e-9],signed_read_margin_min_V=.020,
        kcl_absolute_fC=1e-4,kcl_relative=.01,Cstore_fF=20,Cbl_fF=200,thresholds_changed=False))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(two_dimensional.A0_OUTPUTS))])
    files.update({'project.json':raw_json(spec),'controlled-request.json':raw_json(request),
        'resource-policy.json':raw_json(dict(schema='dram-see-v4-actual-resource-policy-r1',role=role,
            observation_only=True,imported_mesh_sha256=bundle['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':raw_json(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction',synthetic=False,role_ids=[role],
            instruction='用户已将DRAM SEE v4主线迁移为二维：复用真实D2-r8，先运行两bit实际写读，原runner/owner/共享锁及单核单线程不变；不强置目标bit初态、不设置项目资源额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=first.sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py')+two_dimensional.RUNTIME_FILES:
        files[name]=(HERE/name).read_bytes()
    for name in ('prepare_case.py','decks.py','numerics_patch.py','physics_patch.py'):
        files['generator-'+name]=(HERE/name).read_bytes()
    files['provenance.json']=raw_json(dict(schema='dram-see-v4-2d-control-input-provenance-r1',run_id=run_id,role=role,
        source_dimension=2,source_role='B1-D2',source_run_id=cfg['producer_run_id'],
        source_manifest_sha256=cfg['source_manifest_sha256'],source_archive_sha256=cfg['source_archive_sha256'],
        original_D3_qualification_claimed=False,physics_four_files_unchanged=True,mesh_unchanged=True,
        area_factor=.02,effective_width_nm=20,explicit_capacitance_rescale=False,
        neutral_common_initialization=True,target_bit_preset=False,thresholds_changed=False,
        timing_changed=False,native_run_completed=False,native_qualified=False,
        data_admission='Requires original current-run PLT/BE/circuit/KCL and declared numerical controls; input construction is not functionality'))
    hashes={n:digest(v) for n,v in files.items()}
    for n,h in bundle['exports'].items():
        case_contract.require(n not in hashes or hashes[n]==h,'2D frozen proof collision: '+n)
        hashes[n]=h
    files['input-manifest.json']=raw_json(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    files['execution-context.json']=raw_json(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,
        producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=digest(files['input-manifest.json']),authorization_sha256=digest(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for n,raw in files.items():bridge.geometry_write(target/n,raw)
    bridge.geometry_stage_reuse(target,cfg)
    bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),role_id=role,run_id=run_id,input_manifest_sha256=digest(files['input-manifest.json']),
        expected_runner_sha256=runner_sha,source_dimension=2,source_run_id=cfg['producer_run_id'],mesh_sha256=cfg['mesh_sha256'],
        d2_source_binding_sha256=cfg['d2_source_binding_sha256'],dimensional_contract_sha256=cfg['dimensional_contract_sha256'],
        native_run_completed=False,native_qualified=False)


def prepare(request, run_id, runner=None, output=None):
    request = case_contract.validate(request)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL:
        import parameterized_alpha_multicondition_controls_2d
        return parameterized_alpha_multicondition_controls_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_MULTICONDITION:
        import parameterized_alpha_multicondition_2d
        return parameterized_alpha_multicondition_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_RESTART:
        import parameterized_alpha_restart_2d
        return parameterized_alpha_restart_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_A0_RESTART:
        import parameterized_a0_restart_2d
        return parameterized_a0_restart_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_PARTITION_CONTROL:
        import parameterized_alpha_partition_controls_2d
        return parameterized_alpha_partition_controls_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_PARTITION_REFINEMENT:
        import parameterized_alpha_partition_refinement_2d
        return parameterized_alpha_partition_refinement_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA_NATIVE_PARTITION:
        import parameterized_alpha_native_partition_2d
        return parameterized_alpha_native_partition_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL:
        import parameterized_alpha_control_runtime_2d
        return parameterized_alpha_control_runtime_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PROTON_MULTICONDITION_CONTROL:
        import parameterized_proton_multicondition_controls_2d
        return parameterized_proton_multicondition_controls_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PROTON_MULTICONDITION:
        import parameterized_proton_multicondition_2d
        return parameterized_proton_multicondition_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PROTON_MULTICONDITION_REFINEMENT:
        import parameterized_proton_multicondition_refinement_2d
        return parameterized_proton_multicondition_refinement_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PROTON_REFINEMENT:
        import parameterized_proton_refinement_2d
        return parameterized_proton_refinement_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED_PROTON_CONTROL:
        import parameterized_proton_controls_2d
        return parameterized_proton_controls_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED_PROTON:
        import parameterized_proton_2d
        return parameterized_proton_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED_ALPHA:
        import parameterized_alpha_2d
        return parameterized_alpha_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED and request['kind']=='transient':
        import parameterized_operating_2d
        return parameterized_operating_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_OPERATING_VOLTAGE:
        import operating_voltage_dc_2d
        return operating_voltage_dc_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_OPERATING_ALPHA:
        import operating_alpha_2d
        return operating_alpha_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_OPERATION:
        import operating_transient_2d
        return operating_transient_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_OPERATING:
        import operating_dc_2d
        return operating_dc_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D_ALPHA:
        import alpha_native_2d
        return alpha_native_2d.prepare(request,run_id,runner,output)
    if request['schema']==case_contract.SCHEMA_2D:
        return prepare_2d(request,run_id,runner,output)
    inherited = request['schema'] == case_contract.SCHEMA_MESH_REUSE
    metadata = request['schema'] in (case_contract.SCHEMA_METADATA_REUSE,case_contract.SCHEMA_ACTIVE_MESH)
    active_mesh = request['schema'] == case_contract.SCHEMA_ACTIVE_MESH
    dc_reuse = request['schema'] == case_contract.SCHEMA_DC_REUSE
    if dc_reuse:
        request['dc_source_run']=str(Path(request['dc_source_run']).resolve())
    if inherited:
        request['mesh_source_run'] = str(Path(request['mesh_source_run']).resolve())
    if metadata:
        for name in case_contract.METADATA_FIELDS-{'continuation_recipe'}:
            request[name]=str(Path(request[name]).resolve())
    case_contract.require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id), 'Unsafe run ID')
    runner = Path(runner or ROOT/'scripts/tcad.py').resolve()
    case_contract.require(runner == (ROOT/'scripts/tcad.py').resolve() and runner.is_file(), 'Use original scripts/tcad.py')
    runner_sha = first.sha(runner)
    target = Path(output or OUTPUT/run_id).resolve()
    allowed = (ROOT/'local_runtime/dram-see-v4/continuous/device').resolve()
    case_contract.require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),
                          'Native preparation needs a new allowed nonfixture directory')
    role, reuse = case_contract.role_id(request), request['kind'] == 'transient'
    cfg = dict(schema=bridge.GEOMETRY_SCHEMA, mode='reuse' if reuse else 'produce_from_geometry' if dc_reuse else 'produce_from_metadata' if metadata else 'produce_from_mesh' if inherited else 'produce', role_id=role,
        run_id=run_id, producer_run_id=Path(request['d3_source_run']).name if reuse else run_id,
        execution_enabled=True, synthetic=False, size_id=case_contract.size_id(request['gate_top_depth_nm']),
        numerical_variant=request['variant'],sn_junction_depth_nm=request['sn_junction_depth_nm'],
        parameter_id=case_contract.parameter_id(request))
    bundle, mesh_bundle, metadata_bundle, dc_bundle, baseline, prospective_binding = None, None, None, None, None, None
    if reuse:
        if request['source_case'] != 'A0':
            for name in ('source_features_file','registered_data_input'):
                case_contract.require(isinstance(request.get(name),str) and request[name],
                                      'New signal freezing requires pre-TCAD '+name)
        cfg['source_run_directory'] = str(Path(request['d3_source_run']).resolve())
        bundle = bridge.geometry_source_bundle(target, cfg)
        cfg.update(source_manifest_sha256=bundle['manifest_sha256'], source_archive_sha256=bundle['archive_sha256'],
                   mesh_sha256=bundle['mesh_sha256'], geometry_validation_sha256=bundle['geometry_validation_sha256'])
        if 'mesh_representation' in bundle:
            cfg.update({n:bundle[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
        for name in dc_continuation.SELECTOR_CFG_FIELDS+('dc_completed_binding_sha256',):
            if name in bundle:cfg[name]=bundle[name]
        model = json.loads(bundle['producer_inputs']['model.proposed.json'].decode('utf-8'))
        require_model_parameters(request,model)
        case_contract.require(bundle['producer_cfg'].get('numerical_variant', 'main')
                              == ('mesh' if request['variant'] == 'mesh' else 'main'), 'D3 mesh variant differs')
        numerical = json.loads(bundle['producer_inputs'].get('numerical-method.json', b'{}').decode('utf-8'))
        case_contract.require(numerical.get('branch_id') == numerics_patch.PATCH_ID and numerical.get('method') == 'ILS(set=1)',
                              'Current transient branch requires its declared ILS D3 producer')
        binding = producer_binding(bundle, cfg)
        proton=request.get('particle')=='proton'
        alpha_v2=request.get('source_version')==case_contract.ALPHA_V2
        if alpha_v2:
            source_files,source,source_record=alpha_v2_inputs.load_original(request['source_packet_file'],bundle['producer_inputs'])
            source_record['actual_D3_binding']=binding
            files=alpha_v2_inputs.render_payload(model,request,bundle['producer_inputs'],source_files,source,source_record)
            files['controlled-parameters.json']=raw_json(parameter_contract(request,model,files,binding))
        elif proton:
            source_files,source,source_bundle,source_record=proton_inputs.load_original(
                str(Path(request['proton_source_bundle']).resolve()),
                json.loads(bundle['producer_inputs']['geometry-contract.json'].decode()),model)
            source_record['actual_D3_binding']=binding
            files=proton_inputs.render_payload(model,request,bundle['producer_inputs'],source_files,source,source_record)
            files['controlled-parameters.json']=raw_json(parameter_contract(request,model,files,binding))
        else:
            files = transient_payload(model, request, binding, bundle['producer_inputs'])
        files.update(mesh_policy.inherit(bundle['producer_inputs']))
        files.update(bundle.get('runtime_files',{}))
        if 'mesh-policy.json' in files:
            files['controlled-parameters.json']=raw_json(parameter_contract(request,model,files,binding))
        if request['source_case'] != 'A0':
            baseline = matched_baseline(request['matched_a0_project'], request, cfg, files, runner_sha)
            binding_file='device-source-binding.json' if proton or alpha_v2 else 'source-contract.json'
            contract = json.loads(files[binding_file].decode('utf-8'))
            contract['matched_A0_input'] = baseline
            extra,prospective_binding=prospective.bind(files,request,model)
            case_contract.require(not set(extra)&set(files),'Prospective binding would overwrite an existing input')
            files.update(extra)
            contract['prospective_source_binding_sha256']=digest(files['source-feature-binding.json'])
            contract['prospective_source_features_sha256']=digest(files['source-features.json'])
            files[binding_file] = raw_json(contract)
            if proton or alpha_v2:
                registered=json.loads(files['data-input.json'])
                if proton and request['source_case']=='STRUCTURAL_ZERO':
                    case_contract.require(registered.get('zero_source_comparison_window_s')==json.loads(files['source-time-contract.json'])['observation_window_s'],
                                          'Registered structural-zero comparison window differs from actual control')
                source_spec=json.loads(files['source-spec.json'])
                source_spec.update(data_input_sha256=digest(files['data-input.json']),source_features_sha256=digest(files['source-features.json']))
                files['source-spec.json']=raw_json(source_spec)
    elif dc_reuse:
        dc_bundle=dc_continuation.source_package(request['dc_source_run'],request)
        files=dict(dc_bundle['files']);model=json.loads(files['model.proposed.json'])
        require_model_parameters(request,model)
        cfg.update({n:dc_bundle['source_cfg'][n] for n in dc_continuation.CFG_SOURCE_FIELDS})
        selector=dc_bundle['selector']
        cfg.update(dc_source_binding_sha256=digest(files['dc-source-binding.json']),
            geometry_selector_file=dc_continuation.SELECTOR_FILE,
            geometry_selector_sha256=digest(files[dc_continuation.SELECTOR_FILE]),
            geometry_report_file=selector['report_file'],geometry_producer_run_id=selector['producer_run_id'],
            geometry_validation_sha256=selector['report_sha256'])
    elif metadata:
        metadata_bundle=metadata_continuation.source_package(request)
        files=dict(metadata_bundle['files']);model=json.loads(files['model.proposed.json'])
        require_model_parameters(request,model)
        cfg.update(metadata_source_binding_sha256=digest(files['metadata-source-binding.json']),
                   geometry_observation_backend=metadata_continuation.BACKEND)
        if active_mesh:
            cfg.update(mesh_representation=metadata_continuation.ACTIVE_REPRESENTATION,
                origin_mesh_sha256=metadata_bundle['binding']['origin_mesh_sha256'],
                active_solver_mesh_sha256=metadata_bundle['binding']['active_solver_mesh_sha256'])
        original_visual=visual_patch.apply(native_scripts.render_svisual(json.loads(files['measurement-plan.json'])))
        case_contract.require(original_visual.encode('utf-8')==files['measure-geometry.tcl'],
                              'Original native measurements changed before explicit hash-provider patch')
        files['measure-geometry.tcl']=visual_patch.apply_in_process_identity(original_visual).encode('utf-8')
    elif inherited:
        mesh_bundle = mesh_continuation.source_package(Path(request['mesh_source_run']),request)
        files = dict(mesh_bundle['files'])
        model = json.loads(files['model.proposed.json'])
        require_model_parameters(request,model)
        cfg['mesh_source_binding_sha256'] = digest(files['mesh-source-binding.json'])
    elif request['schema']==case_contract.SCHEMA_2D_PARAMETERIZED:
        import parameterized_operating_2d
        files, model = parameterized_operating_2d.producer_payload(request)
    else:
        files, model = producer_payload(request)
    if 'mesh-policy.json' in files:
        cfg.update(mesh_policy_id=json.loads(files['mesh-policy.json'])['policy_id'],
                   mesh_policy_sha256=digest(files['mesh-policy.json']))
    cfg['controlled_parameters_sha256']=digest(files['controlled-parameters.json'])
    template = CANDIDATE/'roles'/('B1-A0-main-b'+str(request['stored_bit']) if reuse else role)
    spec = first.obj(template/'project.review.json')
    spec.update(name='v4-continuous-'+role.lower()+'-'+cfg['parameter_id'], schema='dram-see-v4-continuous-project-r1',
        execution_enabled=True, runner='original scripts/tcad.py', role=role, s2_geometry=cfg)
    spec.pop('release_required', None)
    if not reuse:
        spec['steps'][2:2] = [dict(tool='tdx', args=['-tcl','observe_tdr_topology.tcl','cell_msh.tdr'],
            outputs=['tdr-region-datasets.csv','tdr-geometry.csv','tdr-topology-identity.csv','tdr-region-status.json']),
            dict(tool='tdx', args=['-dd','-M','0','-S','0','cell_msh.tdr','mesh-observed'], outputs=['mesh-observed.grd','mesh-observed.dat'])]
        spec['steps'][2]['outputs'].append('tdr-hash-provider.csv')
        if dc_reuse:
            spec['steps']=spec['steps'][5:]
        elif inherited:
            spec['steps'] = spec['steps'][2:]
        elif metadata:
            spec['steps']=spec['steps'][4:]
            spec['steps'][0]['outputs'].append('geometry-hash-provider.csv')
    contract = first.obj(template/'role-contract.json')
    contract.update(schema='dram-see-v4-continuous-role-contract-r1', role=role, execution_enabled=True,
        size_id=cfg['size_id'], legacy_size_label={70:'S1',80:'S2',90:'S3'}[request['gate_top_depth_nm']],
        gate_top_depth_nm=request['gate_top_depth_nm'],sn_junction_depth_nm=request['sn_junction_depth_nm'],
        parameter_id=cfg['parameter_id'],active_width_nm=model['geometry']['active_width_nm'],
        numerical_variant=request['variant'], case=request['source_case'] if reuse else 'DC',
        source_configured=reuse and request['source_case'] not in ('A0','STRUCTURAL_ZERO'),
        parent_model_file_sha256=digest(files['model.proposed.json']),
        evaluation_partition='final_holdout_excluded_from_tuning' if request['gate_top_depth_nm'] == 90 else 'unassigned_pending_explicit_design_registration',
        final_holdout_policy='All original final conditions, including interpolation groups, remain protected by data registration; changing SN or seed cannot relabel them as training',
        transient_segments=decks.transient_segments(model, .5 if request['variant'] == 'time' else 1) if reuse else [])
    if request.get('particle')=='proton' or request.get('source_version')==case_contract.ALPHA_V2:
        window=json.loads(files['source-time-contract.json'])
        contract.update(particle=request.get('particle'),source_time_contract_sha256=digest(files['source-time-contract.json']),
            transient_segments=decks.transient_segments(model,.5 if request['variant']=='time' else 1,
                window['observation_window_s'],window['main_max_step_s']),
            metrics_entrypoint='experiments/dram-see-v4/continuous/data/pipeline.py',
            native_source_qualified=False,pmi_r12_fixed=False)
        if request.get('particle')=='proton':contract['source_bundle_sha256']=digest(files['source-bundle.json'])
        else:
            contract.update(source_version=case_contract.ALPHA_V2,source_packet_sha256=digest(files['source-packet.json']),
                native_endpoint_semantics_verified=False,source_data_admission='Requires separate native v2 field/clock/reference qualification')
    elif reuse and json.loads(files['source-spec.json']).get('schema')=='continuous-particle-source-spec-v1':
        contract.update(metrics_entrypoint='experiments/dram-see-v4/continuous/data/pipeline.py',
            source_oracle=None,native_source_qualified=False)
    contract['stop_conditions'] = [v.replace('resource/budget/lock/owner failure','actual resource/lock/owner failure') for v in contract['stop_conditions']]
    if 'mesh-policy.json' in files:
        contract.update(mesh_policy_id=cfg['mesh_policy_id'],mesh_policy_sha256=cfg['mesh_policy_sha256'],
                        mesh_accuracy_qualified=False)
    files.update({'project.json':raw_json(spec), 'role-contract.json':raw_json(contract),
        'controlled-request.json':raw_json(request),
        'resource-policy.json':raw_json(dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
            observation_only=True, imported_mesh_sha256=(bundle or mesh_bundle or metadata_bundle or dc_bundle or {}).get('mesh_sha256'), resource_limits=None)),
        'task-authorization.json':raw_json(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction', synthetic=False, role_ids=[role], instruction=first.USER_INSTRUCTION,
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=first.sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py') + (() if reuse or dc_reuse else
                 ('evaluate.py','dfise_observer.py','observe_tdr_topology.tcl','tdx_hash_sha256.tcl')) + (('mesh_continuation.py',) if inherited else ()) + (('mesh_continuation.py','metadata_continuation.py','hdf5_observer.py') if metadata else ()) + (dc_continuation.RUNTIME_FILES if dc_reuse else ()):
        if inherited and name in mesh_continuation.IDENTICAL_INPUTS:
            continue
        if metadata and name in metadata_bundle['binding']['identical_scientific_inputs_sha256']:
            continue
        files[name] = (HERE/name).read_bytes()
    if request.get('particle')!='proton' and json.loads(files.get('source-spec.json',b'{}')).get('schema')!='continuous-particle-source-spec-v1':
        files['metrics.py'] = (template/'metrics.py').read_bytes()
    for name in SNAPSHOT_FILES:
        files['generator-'+name] = (HERE/name).read_bytes()
    provenance = dict(schema='dram-see-v4-controlled-input-provenance-r1', role=role, run_id=run_id,
        request=request, generator_sha256=first.sha(HERE/'prepare_case.py'),
        prior_candidate=str(CANDIDATE.relative_to(ROOT)).replace('\\','/'),
        original_checked_reference_reused=reuse,
        native_repairs_preserved=[observer_patch.PATCH_ID,doping_patch.PATCH_ID,mesh_patch.PATCH_ID,visual_patch.PATCH_ID,
                                 'native-hdf5-v16-contact-and-region-observation-r1' if metadata or dc_reuse else 'native-dfise-contact-and-region-observation-r1',physics_patch.PATCH_ID,numerics_patch.PATCH_ID],
        numerical_tail_floor_max_cm3=doping_patch.MAX_ADDED_DONOR_CM3,
        changes_comparison_thresholds=False, native_run_completed=False, native_qualified=False,
        actual_D3_binding=producer_binding(bundle,cfg) if bundle else None,
        actual_mesh_prefix_binding_sha256=cfg.get('mesh_source_binding_sha256'),
        actual_metadata_source_binding_sha256=cfg.get('metadata_source_binding_sha256'),
        geometry_observation_backend=cfg.get('geometry_observation_backend','native_dfise'),
        matched_A0_input=baseline, actual_A0_qualification=None,
        prospective_source_binding=prospective_binding,
        no_native_scheduler_or_launcher=True)
    if metadata:
        provenance.update(current_run_changes_mesh=False,actual_step_indices=[5,6],inherited_step_indices=[1,2,3],
            original_failed_converter_preserved=metadata_bundle['binding']['failed_step004'],
            metadata_source_graph=metadata_bundle['binding']['nodes'])
        if active_mesh:
            provenance.update(current_run_changes_mesh=False,current_run_changes_mesh_representation=True,
                mesh_representation=metadata_continuation.ACTIVE_REPRESENTATION,
                origin_mesh_sha256=cfg['origin_mesh_sha256'],active_solver_mesh_sha256=cfg['active_solver_mesh_sha256'],
                memory_benefit='Unproven reader-memory hypothesis; smaller file bytes are not a RAM result')
    if dc_reuse:
        provenance.update(actual_step_indices=[6],inherited_step_indices=[1,2,3,5],
            actual_dc_source_binding_sha256=cfg['dc_source_binding_sha256'],
            geometry_selector_file=cfg['geometry_selector_file'],geometry_selector_sha256=cfg['geometry_selector_sha256'],
            geometry_producer_run_id=cfg['geometry_producer_run_id'],geometry_report_file=cfg['geometry_report_file'],
            original_failed_dc_preserved=dict(owner=dc_bundle['binding']['source_run_id'],exit_code=137),
            current_run_changes_mesh=False,current_run_changes_physics_or_numerics=False)
    if 'mesh-policy.json' in files:
        provenance.update(mesh_policy_id=cfg['mesh_policy_id'],mesh_policy_sha256=cfg['mesh_policy_sha256'],
            mesh_policy_origin='exact original successful D3' if reuse else 'exact original successful mesh prefix; failed D3 sources preserved' if inherited or metadata or dc_reuse else 'explicit request-r3 numerical candidate',
            mesh_discretization_changed=True,mesh_accuracy_qualified=False,
            physical_model_and_device_deck_unchanged_by_mesh_policy=True)
    if dc_reuse:provenance['mesh_discretization_changed']=False
    files['provenance.json'] = raw_json(provenance)
    hashes = {name:digest(raw) for name,raw in files.items()}
    if bundle:
        case_contract.require(not set(hashes) & set(bundle['exports']), 'D3 export collides with case payload')
        hashes.update(bundle['exports'])
    if mesh_bundle:
        for name,row in mesh_bundle['imports'].items():
            case_contract.require(name not in hashes or hashes[name] == row['sha256'], 'Mesh-prefix input collision: '+name)
            hashes[name] = row['sha256']
    if metadata_bundle:
        for name,row in metadata_bundle['imports'].items():
            case_contract.require(name not in hashes or hashes[name]==row['sha256'],'Metadata input collision: '+name)
            hashes[name]=row['sha256']
    if dc_bundle:
        inherited_hashes={n:r['sha256'] for n,r in dc_bundle['imports'].items()}
        inherited_hashes.update(dc_bundle['binding']['proofs_sha256'])
        for name,value in inherited_hashes.items():
            case_contract.require(name not in hashes or hashes[name]==value,'DC checkpoint input collision: '+name)
            hashes[name]=value
    files['input-manifest.json'] = raw_json(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    files['execution-context.json'] = raw_json(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,
        role_id=role,producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=digest(files['input-manifest.json']),authorization_sha256=digest(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():
        bridge.geometry_write(target/name,raw)
    if metadata_bundle:
        # Full frozen originals are required at admission. No runtime Windows-path dependency.
        bridge.geometry_stage_metadata_reuse(target,cfg)
    if dc_bundle:
        bridge.geometry_stage_dc_reuse(target,cfg)
    bridge.geometry_admit(target,spec,runner_sha)
    if bundle:
        bridge.geometry_stage_reuse(target,cfg)
    if mesh_bundle:
        bridge.geometry_stage_mesh_reuse(target,cfg)
    return dict(project=str(target),role_id=role,run_id=run_id,
        input_manifest_sha256=digest(files['input-manifest.json']),expected_runner_sha256=runner_sha,
        native_run_completed=False,native_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--runner')
    parser.add_argument('--output')
    parser.add_argument('--depth-change-text')
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    try:
        request=first.obj(args.request)
        if args.depth_change_text:
            request.update(case_contract.parse_depth_change(args.depth_change_text))
        request=case_contract.validate(request)
        if args.preview:
            physical_request=request['reference_alpha_request'] if request['schema'] in (case_contract.SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL,case_contract.SCHEMA_2D_ALPHA_PARTITION_CONTROL,case_contract.SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL) else request
            result=dict(request=request,role_id=case_contract.role_id(request),size_id=case_contract.size_id(physical_request['gate_top_depth_nm']),
                parameter_id=case_contract.parameter_id(physical_request),
                evaluation_partition='final_holdout_excluded_from_tuning' if physical_request['gate_top_depth_nm']==90 else 'unassigned_pending_explicit_design_registration',
                native_run_completed=False,preview_only=True)
        else:
            result=prepare(request,args.run_id,args.runner,args.output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
