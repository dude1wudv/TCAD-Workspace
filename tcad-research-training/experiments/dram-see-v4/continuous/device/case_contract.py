"""Small structured whitelist shared by the preparer and original-runner bridge."""
import re

SCHEMA = 'dram-see-v4-controlled-device-request-r1'
SCHEMA_2D_PROTON_MULTICONDITION_CONTROL = 'dram-see-v4-parameterized-proton-multicondition-control-request-r1'
SCHEMA_2D_PROTON_MULTICONDITION = 'dram-see-v4-parameterized-proton-multicondition-request-r1'
SCHEMA_2D_PROTON_MULTICONDITION_REFINEMENT = 'dram-see-v4-parameterized-proton-multicondition-refinement-request-r1'
SCHEMA_2D_ALPHA_RESTART = 'dram-see-v4-parameterized-alpha-restart-request-r1'
SCHEMA_2D_A0_RESTART = 'dram-see-v4-parameterized-a0-restart-request-r1'
SCHEMA_V2 = 'dram-see-v4-controlled-device-request-r2'
SCHEMA_MESH = 'dram-see-v4-controlled-device-request-r3'
SCHEMA_MESH_REUSE = 'dram-see-v4-controlled-device-request-r4'
SCHEMA_METADATA_REUSE = 'dram-see-v4-controlled-device-request-r5'
SCHEMA_ACTIVE_MESH = 'dram-see-v4-controlled-device-request-r6'
SCHEMA_DC_REUSE = 'dram-see-v4-controlled-device-request-r7'
SCHEMA_2D = 'dram-see-v4-controlled-device-request-r8'
SCHEMA_2D_ALPHA = 'dram-see-v4-controlled-device-request-r9'
SCHEMA_2D_OPERATING = 'dram-see-v4-controlled-device-request-r10'
SCHEMA_2D_OPERATION = 'dram-see-v4-controlled-device-request-r11'
SCHEMA_2D_OPERATING_ALPHA = 'dram-see-v4-controlled-device-request-r12'
SCHEMA_2D_PARAMETERIZED = 'dram-see-v4-controlled-device-request-r13'
SCHEMA_2D_OPERATING_VOLTAGE = 'dram-see-v4-controlled-device-request-r14'
SCHEMA_2D_PARAMETERIZED_ALPHA = 'dram-see-v4-controlled-device-request-r15'
SCHEMA_2D_ALPHA_PARTITION_REFINEMENT = 'dram-see-v4-parameterized-alpha-partition-refinement-request-r1'
SCHEMA_2D_ALPHA_MULTICONDITION = 'dram-see-v4-parameterized-alpha-multicondition-request-r1'
SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL = 'dram-see-v4-parameterized-alpha-multicondition-control-request-r1'
SCHEMA_2D_ALPHA_NATIVE_PARTITION = 'dram-see-v4-parameterized-alpha-native-partition-request-r1'
SCHEMA_2D_ALPHA_PARTITION_CONTROL = 'dram-see-v4-parameterized-alpha-partition-control-request-r1'
SCHEMA_2D_PROTON_REFINEMENT = 'dram-see-v4-parameterized-proton-refinement-request-r1'
SCHEMA_2D_PARAMETERIZED_PROTON_CONTROL = 'dram-see-v4-parameterized-proton-control-request-r1'
SCHEMA_2D_PARAMETERIZED_PROTON = 'dram-see-v4-parameterized-proton-request-r1'
SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL = 'dram-see-v4-parameterized-alpha-control-request-r1'
DC_REUSE_RECIPE = 'native-v16-qualified-geometry-to-dc-r1'
METADATA_RECIPE = 'native-hdf5-v16-r1'
ACTIVE_MESH_RECIPE = 'native-hdf5-v16-active-mesh-r1'
ACTIVE_MESH_REPRESENTATION = 'tdr-hdf5-v16'
METADATA_FIELDS = {'metadata_source_run','tdr_conversion_operation','hdf5_export_operation','continuation_recipe'}
ALPHA_V2 = 'v2-alpha-surface'
GRADIENT_MESH = 'dram-see-v4-gradient-mesh-r1'
GRADIENT_MESH_R2 = 'dram-see-v4-gradient-mesh-r2'
GRADIENT_MESH_R3 = 'dram-see-v4-gradient-mesh-r3'
GRADIENT_MESH_R4 = 'dram-see-v4-gradient-mesh-r4'
GRADIENT_MESH_R5 = 'dram-see-v4-gradient-mesh-r5'
GRADIENT_MESH_R6 = 'dram-see-v4-gradient-mesh-r6'
FIELDS = {'schema', 'kind', 'gate_top_depth_nm', 'sn_junction_depth_nm', 'dimension', 'variant', 'stored_bit',
          'source_case', 'd3_source_run', 'matched_a0_project',
          'source_features_file', 'registered_data_input', 'particle', 'proton_source_bundle'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def size_id(depth):
    require(type(depth) is int and depth in (70, 80, 90), 'Gate top depth must be 70, 80 or 90 nm')
    return 'gate-top-depth-{}nm'.format(depth)


def sn_depth(value=87):
    require(type(value) is int and value in (82,87,92), 'SN junction depth must be 82, 87 or 92 nm')
    return value


def parameter_id(request):
    return size_id(request['gate_top_depth_nm'])+'__sn-junction-depth-{}nm'.format(sn_depth(request.get('sn_junction_depth_nm',87)))


def operating_voltage_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('operating_voltage_dc_2d.py')
    spec=importlib.util.spec_from_file_location('case_operating_voltage_dc_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def operating_alpha_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('operating_alpha_2d.py')
    spec=importlib.util.spec_from_file_location('case_operating_alpha_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def operating_transient_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('operating_transient_2d.py')
    spec=importlib.util.spec_from_file_location('case_operating_transient_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def parameterized_alpha_control_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_control_runtime_2d.py')
    spec=importlib.util.spec_from_file_location('case_parameterized_alpha_control_runtime_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value



def proton_multicondition_control_api():
    from pathlib import Path
    import hashlib
    import importlib.util
    path=Path(__file__).with_name('parameterized_proton_multicondition_controls_2d.py')
    raw=path.read_bytes()
    require(not path.is_symlink() and hashlib.sha256(raw).hexdigest()=='531c43d83c258ba91d16b8383102f56c4d2fddeddd095e5292c698566c8ea4bf',
        'fixed proton multicondition control runtime changed')
    spec=importlib.util.spec_from_file_location('case_proton_multicondition_control_2d',str(path))
    value=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),value.__dict__);return value


def proton_multicondition_api():
    from pathlib import Path
    import importlib.util
    path=Path(__file__).with_name('parameterized_proton_multicondition_2d.py')
    spec=importlib.util.spec_from_file_location('case_proton_multicondition_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

def proton_multicondition_refinement_api():
    from pathlib import Path
    import importlib.util
    path=Path(__file__).with_name('parameterized_proton_multicondition_refinement_2d.py')
    spec=importlib.util.spec_from_file_location('case_proton_multicondition_refinement_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def proton_refinement_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_proton_refinement_2d.py')
    spec=importlib.util.spec_from_file_location('case_proton_refinement_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def parameterized_proton_controls_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_proton_controls_2d.py')
    spec=importlib.util.spec_from_file_location('case_parameterized_proton_controls_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def parameterized_proton_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_proton_2d.py')
    spec=importlib.util.spec_from_file_location('case_parameterized_proton_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def alpha_partition_control_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_partition_controls_2d.py')
    spec=importlib.util.spec_from_file_location('case_alpha_partition_controls_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def alpha_partition_refinement_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_partition_refinement_2d.py')
    spec=importlib.util.spec_from_file_location('case_alpha_partition_refinement_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def alpha_multicondition_api():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_multicondition_2d.py')
    raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!='6e651db56c2c44307f129f9fc9be24b97ee51aec8205ee5bda0ebd16e582c01d':
        raise ValueError('fixed alpha multicondition runtime changed')
    spec=importlib.util.spec_from_file_location('case_alpha_multicondition_2d',str(path))
    value=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),value.__dict__)
    return value



def alpha_multicondition_control_api():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_multicondition_controls_2d.py')
    raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!='7d7a29569ecaf453bfc1c06674bf107b6c01bf7d11ad2200039041163567c2e6':
        raise ValueError('fixed alpha multicondition runtime changed')
    spec=importlib.util.spec_from_file_location('case_alpha_multicondition_2d',str(path))
    value=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),value.__dict__)
    return value


def alpha_native_partition_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_native_partition_2d.py')
    spec=importlib.util.spec_from_file_location('case_alpha_native_partition_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def parameterized_alpha_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_2d.py')
    spec=importlib.util.spec_from_file_location('case_parameterized_alpha_2d',str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def parameterized_operating_api():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_operating_2d.py')
    spec=importlib.util.spec_from_file_location('case_parameterized_operating_2d',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def alpha_restart_api():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_alpha_restart_2d.py')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='c115c00f1e1670b989fe65fe85d81eee9d0bea3807c5ef2581b5ee21e9d5b039':
        raise ValueError('fixed alpha restart runtime changed')
    spec=importlib.util.spec_from_file_location('case_alpha_restart',str(path))
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def a0_restart_api():
    import hashlib
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('parameterized_a0_restart_2d.py')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='825a0229cdfbf07effc32344a0d8f66459babf0069347c469b00969640e00a9d':
        raise ValueError('fixed A0 restart runtime changed')
    spec=importlib.util.spec_from_file_location('case_a0_restart_2d',str(path))
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def validate(request):
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_RESTART:
        return alpha_restart_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PROTON_MULTICONDITION_CONTROL:
        return proton_multicondition_control_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL:
        return alpha_multicondition_control_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_MULTICONDITION:
        return alpha_multicondition_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_A0_RESTART:
        return a0_restart_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_PARTITION_REFINEMENT:
        return alpha_partition_refinement_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_PARTITION_CONTROL:
        return alpha_partition_control_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_ALPHA_NATIVE_PARTITION:
        return alpha_native_partition_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PROTON_MULTICONDITION:
        return proton_multicondition_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PROTON_MULTICONDITION_REFINEMENT:
        return proton_multicondition_refinement_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PROTON_REFINEMENT:
        return proton_refinement_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PARAMETERIZED_PROTON_CONTROL:
        return parameterized_proton_controls_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PARAMETERIZED_PROTON:
        return parameterized_proton_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL:
        return parameterized_alpha_control_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PARAMETERIZED_ALPHA:
        return parameterized_alpha_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_PARAMETERIZED:
        return parameterized_operating_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_OPERATING_VOLTAGE:
        return operating_voltage_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_OPERATING_ALPHA:
        return operating_alpha_api().validate_request(request)
    if isinstance(request,dict) and request.get('schema')==SCHEMA_2D_OPERATION:
        return operating_transient_api().validate_request(request)
    if isinstance(request, dict) and request.get('schema') == SCHEMA_2D_OPERATING:
        expected={'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant',
                  'd2_source_run','effective_width_nm','gate_V','write_BL_V','body_V',
                  'Cstore_fF','Cbl_fF','max_source_step_V','paths'}
        require(set(request)==expected, '2D operating DC needs its exact diagnostic fields')
        require(request['kind']=='operating_dc' and request['variant']=='main'
                and request['paths']=='write0p6_1p12_read1p08_0p8-r1', 'Unknown static operating diagnostic')
        for name,value in (('dimension',2),('gate_top_depth_nm',80),('sn_junction_depth_nm',87),('effective_width_nm',20)):
            require(type(request[name]) is int and request[name]==value, 'Operating DC fixed geometry/width differs: '+name)
        for name,value in (('gate_V',1.8),('write_BL_V',1.2),('body_V',0.),('Cstore_fF',20.),('Cbl_fF',200.),('max_source_step_V',.01)):
            require(type(request[name]) in (int,float) and request[name]==value, 'Operating DC fixed physical/path value differs: '+name)
        require(isinstance(request['d2_source_run'],str) and request['d2_source_run'], 'Original completed D2 source required')
        return dict(request)
    if isinstance(request, dict) and request.get('schema') == SCHEMA_2D_ALPHA:
        expected={'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant',
                  'stored_bit','source_case','d2_source_run','effective_width_nm','particle',
                  'alpha_projection_package','matched_a0_run','source_epoch_s','source_observation_window_s'}
        require(set(request)==expected, '2D alpha request needs its exact closed fields')
        control={k:v for k,v in request.items() if k not in expected-{
            'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant',
            'stored_bit','source_case','d2_source_run','effective_width_nm'}}
        control.update(schema=SCHEMA_2D,source_case='A0')
        validate(control)
        require(request['particle']=='alpha' and request['source_case']=='Aalpha'
                and request['variant']=='main', 'First 2D alpha version only enables main positive alpha')
        for key in ('alpha_projection_package','matched_a0_run'):
            require(isinstance(request[key],str) and request[key], 'Missing explicit 2D alpha input: '+key)
        require(type(request['source_epoch_s']) in (int,float) and request['source_epoch_s']==1.5e-8
                and request['source_observation_window_s']==[1.4998399999999998e-8,1.50016e-8]
                and all(type(v) in (int,float) for v in request['source_observation_window_s']),
                'First 2D alpha retains the explicit original 15ns epoch and mathematical eight-sigma window')
        return dict(request)
    if isinstance(request, dict) and request.get('schema') == SCHEMA_2D:
        expected={'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant',
                  'stored_bit','source_case','d2_source_run','effective_width_nm'}
        require(set(request)==expected, '2D control request needs its exact closed fields')
        require(request['kind']=='transient' and type(request['dimension']) is int and request['dimension']==2
                and request['source_case']=='A0', 'Request r8 only enables source-free 2D A0')
        require(type(request['gate_top_depth_nm']) is int and request['gate_top_depth_nm']==80
                and type(request['sn_junction_depth_nm']) is int and request['sn_junction_depth_nm']==87,
                'First 2D A0 requires the original gate80/SN87 D2; other producers need their own version')
        require(type(request['effective_width_nm']) is int and request['effective_width_nm']==20,
                'First 2D A0 has the explicit original 20 nm effective width')
        require(request['variant'] in ('main','time') and type(request['stored_bit']) is int
                and request['stored_bit'] in (0,1), '2D A0 bit/variant unsupported; no h/2 producer is presumed')
        require(isinstance(request['d2_source_run'],str) and request['d2_source_run'], 'Original completed D2 source required')
        return dict(request)
    require(isinstance(request, dict) and request.get('schema') in (SCHEMA,SCHEMA_V2,SCHEMA_MESH,SCHEMA_MESH_REUSE,SCHEMA_METADATA_REUSE,SCHEMA_ACTIVE_MESH,SCHEMA_DC_REUSE), 'Wrong controlled request schema')
    v2=request['schema']==SCHEMA_V2
    inherited=request['schema']==SCHEMA_MESH_REUSE
    active=request['schema']==SCHEMA_ACTIVE_MESH
    dc_reuse=request['schema']==SCHEMA_DC_REUSE
    metadata=request['schema'] in (SCHEMA_METADATA_REUSE,SCHEMA_ACTIVE_MESH)
    mesh=request['schema'] in (SCHEMA_MESH,SCHEMA_MESH_REUSE,SCHEMA_METADATA_REUSE,SCHEMA_ACTIVE_MESH,SCHEMA_DC_REUSE)
    allowed=FIELDS|({'source_version','source_packet_file'} if v2 else {'mesh_policy'} if mesh else set())|({'mesh_source_run'} if inherited else set())|(METADATA_FIELDS if metadata else set())|({'mesh_representation'} if active or dc_reuse else set())|({'dc_source_run','continuation_recipe'} if dc_reuse else set())
    require(set(request) <= allowed, 'Unknown or executable request fields are forbidden')
    request=dict(request)
    request.setdefault('sn_junction_depth_nm',87)
    if inherited:
        require(isinstance(request.get('mesh_source_run'),str) and request['mesh_source_run'],
                'Request r4 needs the original failed D3 directory with an observed successful mesh prefix')
    if dc_reuse:
        require(request.get('continuation_recipe')==DC_REUSE_RECIPE and request.get('mesh_representation')==ACTIVE_MESH_REPRESENTATION
                and isinstance(request.get('dc_source_run'),str) and request['dc_source_run'],
                'Request r7 needs the explicit original passed-v16 geometry source and fixed DC-only recipe')
    if metadata:
        require(request.get('continuation_recipe')==(ACTIVE_MESH_RECIPE if active else METADATA_RECIPE),
                'Metadata request needs its fixed native HDF5 provenance recipe')
        if active:
            require(request.get('mesh_representation')==ACTIVE_MESH_REPRESENTATION,'Request r6 needs the explicit fixed active representation')
        for name in METADATA_FIELDS-{'continuation_recipe'}:
            require(isinstance(request.get(name),str) and request[name],'Request r5 needs original source '+name)
    if mesh:
        require(request.get('kind')=='dc' and request.get('dimension')==3
                and request.get('mesh_policy') in (GRADIENT_MESH,GRADIENT_MESH_R2,GRADIENT_MESH_R3,GRADIENT_MESH_R4,GRADIENT_MESH_R5,GRADIENT_MESH_R6),
                'Request r3 requires the explicit registered 3D gradient mesh policy')
        if request['mesh_policy']==GRADIENT_MESH_R5:
            require(request['sn_junction_depth_nm']==87,
                    'Mesh r5 supports only analyzed SN87; SN82/92 require their own partition evidence')
        if request['mesh_policy']==GRADIENT_MESH_R6:
            require(request['sn_junction_depth_nm']==87,
                    'Mesh r6 supports only analyzed SN87; SN82/92 require their own partition evidence')
    if v2:
        require(request.get('kind')=='transient' and request.get('particle')=='alpha'
                and request.get('source_version')==ALPHA_V2,'Request r2 only adds the explicit registered alpha v2 transient')
        require(request.get('source_case') in ('A0','Aalpha'),'Alpha v2 supports amplitude1 and its inactive A0 context; H/Z/split are unsupported')
        require(isinstance(request.get('source_packet_file'),str) and request['source_packet_file'],'Alpha v2 needs its original source packet')
        if request['source_case']!='A0':
            require(request.get('source_features_file',request['source_packet_file'])==request['source_packet_file'],
                    'Alpha v2 packet and prospective source summary must be the same original file')
            request.setdefault('source_features_file',request['source_packet_file'])
    require(request.get('kind') in ('dc', 'transient'), 'Only dc or transient is supported')
    size_id(request.get('gate_top_depth_nm'))
    sn_depth(request['sn_junction_depth_nm'])
    require(type(request.get('dimension')) is int and request['dimension'] in (2, 3), 'Dimension must be 2 or 3')
    variant = request.get('variant')
    require(variant in ('main', 'mesh', 'time'), 'Unknown numerical variant')
    if request['kind'] == 'dc':
        require(set(request) == ({'schema', 'kind', 'gate_top_depth_nm', 'sn_junction_depth_nm', 'dimension', 'variant'}
                                |({'mesh_policy'} if mesh else set())|({'mesh_source_run'} if inherited else set())
                                |(METADATA_FIELDS if metadata else set())|({'mesh_representation'} if active or dc_reuse else set())
                                |({'dc_source_run','continuation_recipe'} if dc_reuse else set())), 'DC request has unrelated source fields')
        require(variant in ('main', 'mesh') and (request['dimension'] == 3 or variant == 'main'), 'Only 3D has h/2 producer roles')
    else:
        require(request['dimension'] == 3,'Transient controls require an actual 3D producer')
        require(type(request.get('stored_bit')) is int and request['stored_bit'] in (0, 1), 'Stored bit must be 0 or 1')
        particle=request.get('particle','alpha')
        require(particle in ('alpha','proton'),'Only alpha or proton is in scope')
        if particle=='proton':
            require(request['gate_top_depth_nm']==80 and request['sn_junction_depth_nm']==87,
                    'Current proton v1 source/control requires gate 80 nm and SN 87 nm; a new source version is required')
            require(request.get('source_case') in ('A0','SIGNAL','STRUCTURAL_ZERO'),'Unknown proton source role')
            require(isinstance(request.get('proton_source_bundle'),str) and request['proton_source_bundle'],
                    'Proton transient requires an original complete-event source bundle, including its control')
        else:
            require(request.get('source_case') in ('A0','Aalpha','Z','H','split'),'Unknown alpha source case')
            if request['source_case']!='A0' and not v2:
                require(request['gate_top_depth_nm']==80 and request['sn_junction_depth_nm']==87,
                        'Current alpha v1 source requires gate 80 nm and SN 87 nm; a new source version is required')
            require('proton_source_bundle' not in request,'Alpha cannot borrow a proton source bundle')
            require(request['source_case'] in ('A0', 'Aalpha') or variant == 'main', 'Z/H/split use the main variant')
        require(isinstance(request.get('d3_source_run'), str) and request['d3_source_run'], 'Actual collected D3 source is required')
        if request['source_case'] == 'A0':
            require('matched_a0_project' not in request, 'A0 is its own baseline, not a matched signal')
            require(not {'source_features_file', 'registered_data_input'} & set(request),
                    'The current A0 baseline has no active source-feature or signal data binding')
        else:
            require(isinstance(request.get('matched_a0_project'), str) and request['matched_a0_project'],
                    'Signal requires a concrete frozen matched A0 input project')
            for key in ('source_features_file', 'registered_data_input'):
                if key in request:
                    require(isinstance(request[key], str) and request[key], 'Invalid prospective input path: ' + key)
    return dict(request)


def role_id(request):
    r = validate(request)
    if r['schema']==SCHEMA_2D_PROTON_MULTICONDITION_CONTROL:
        return proton_multicondition_control_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL:
        return alpha_multicondition_control_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_MULTICONDITION:
        return alpha_multicondition_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_RESTART:
        return alpha_restart_api().role_id(r)
    if r['schema']==SCHEMA_2D_A0_RESTART:
        return a0_restart_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_PARTITION_REFINEMENT:
        return alpha_partition_refinement_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_PARTITION_CONTROL:
        return alpha_partition_control_api().role_id(r)
    if r['schema']==SCHEMA_2D_ALPHA_NATIVE_PARTITION:
        return alpha_native_partition_api().role_id(r)
    if r['schema']==SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL:
        return parameterized_alpha_control_api().role_id(r)
    if r['schema']==SCHEMA_2D_PROTON_MULTICONDITION:
        return proton_multicondition_api().role_id(r)
    if r['schema']==SCHEMA_2D_PROTON_MULTICONDITION_REFINEMENT:
        return proton_multicondition_refinement_api().role_id(r)
    if r['schema']==SCHEMA_2D_PROTON_REFINEMENT:
        return proton_refinement_api().role_id(r)
    if r['schema']==SCHEMA_2D_PARAMETERIZED_PROTON_CONTROL:
        return parameterized_proton_controls_api().role_id(r)
    if r['schema']==SCHEMA_2D_PARAMETERIZED_PROTON:
        return parameterized_proton_api().role_id(r)
    if r['schema']==SCHEMA_2D_PARAMETERIZED_ALPHA:
        return parameterized_alpha_api().role_id(r)
    if r['schema']==SCHEMA_2D_PARAMETERIZED:
        return parameterized_operating_api().role_id(r)
    if r['schema']==SCHEMA_2D_OPERATING_VOLTAGE:
        return operating_voltage_api().role_id(r)
    if r['schema']==SCHEMA_2D_OPERATING_ALPHA:
        return operating_alpha_api().role_id(r)
    if r['schema']==SCHEMA_2D_OPERATION:
        return operating_transient_api().role_id(r)
    if r['schema']==SCHEMA_2D_OPERATING:
        return 'B2D-OPERATING-DC-main'
    if r['schema']==SCHEMA_2D_ALPHA:
        return 'B2D-Aalpha-main-b'+str(r['stored_bit'])
    if r['schema']==SCHEMA_2D:
        return 'B2D-A0-'+r['variant']+'-b'+str(r['stored_bit'])
    if r['kind'] == 'dc':
        return 'B1-D{}'.format(r['dimension'])
    if r.get('source_version')==ALPHA_V2:
        return ('B1-A0-alpha-v2-' if r['source_case']=='A0' else 'B2-A2-')+r['variant']+'-b'+str(r['stored_bit'])
    if r.get('particle')=='proton':
        prefix={'A0':'B1-A0-proton','SIGNAL':'B3-P','STRUCTURAL_ZERO':'B3-PZERO'}[r['source_case']]
        return prefix+'-'+r['variant']+'-b'+str(r['stored_bit'])
    prefix = 'B1-A0-' + r['variant'] if r['source_case'] == 'A0' else (
        'B2-A-' + r['variant'] if r['source_case'] == 'Aalpha' else 'B2-' + r['source_case'].upper())
    return prefix + '-b' + str(r['stored_bit'])


def is_role(role):
    return isinstance(role, str) and (role in ('B1-D2', 'B1-D3', 'B2D-OPERATING-DC-main', 'B2D-OPERATING-VOLTAGE-DC-main') or
        role == 'B2D-Aalpha-restored-suffix-r1-main-b1' or
        re.fullmatch(r'B2D-A0-restored-suffix-r1-main-b[01]', role) is not None or
        re.fullmatch(r'B2D-Aalpha-native-partition-refinement-r1-(h2|dt2)-b[01]', role) is not None or
        re.fullmatch(r'B2D-(?:Z|H|split)-proton-multicondition-control-r1-main-(?:g70-p50-a(?:0|30)|g70-p100-a0|g80-p50-a0|g80-p100-a(?:0|30))-b[01]-e(?:0|[1-9][0-9]*)', role) is not None or
        re.fullmatch(r'B2D-Aproton-multicondition-r1-main-(?:g70-p50-a(?:0|30)|g70-p100-a0|g80-p50-a0|g80-p100-a(?:0|30))-b[01]-e(?:0|[1-9][0-9]*)', role) is not None or
        re.fullmatch(r'B2D-Aproton-multicondition-refinement-r1-(h2|dt2)-(?:g70-p50-a(?:0|30)|g70-p100-a0|g80-p50-a0|g80-p100-a(?:0|30))-b[01]-e(?:0|[1-9][0-9]*)', role) is not None or
        re.fullmatch(r'B2D-Aproton-refinement-r1-(h2|dt2)-b[01]-e[0-3]', role) is not None or
        re.fullmatch(r'B2D-(Z|H|split)-proton-control-r1-main-b[01]-e[0-3]', role) is not None or
        re.fullmatch(r'B2D-Aproton-parameterized-r1-main-b[01]-e[0-3]', role) is not None or
        re.fullmatch(r'B2D-(Z|H|split)-parameterized-control-r1-main-b[01]', role) is not None or
        re.fullmatch(r'B2D-Aalpha-operating-r1-main-b[01]', role) is not None or
        re.fullmatch(r'B2D-(Z|H|split)-multicondition-control-r1-(main|h2|dt2)-b[01]', role) is not None or re.fullmatch(r'B2D-(Z|H|split)-native-partition-control-r1-main-b[01]', role) is not None or re.fullmatch(r'B2D-Aalpha-multicondition-r1-(main|h2|dt2)-b[01]', role) is not None or re.fullmatch(r'B2D-Aalpha-native-partition-r1-main-b[01]', role) is not None or re.fullmatch(r'B2D-Aalpha-parameterized-r1-(main|h2|dt2)-b[01]', role) is not None or
        re.fullmatch(r'B2D-A0-parameterized-r1-(main|h2|dt2)-b[01]', role) is not None or
        re.fullmatch(r'B2D-A0-operating-r1-main-b[01]', role) is not None or
        re.fullmatch(r'B2D-Aalpha-main-b[01]', role) is not None or
        re.fullmatch(r'B2D-A0-(main|time)-b[01]', role) is not None or
        re.fullmatch(r'B1-A0-(?:proton-|alpha-v2-)?(main|mesh|time)-b[01]|B2-(A|A2)-(main|mesh|time)-b[01]|B2-(Z|H|SPLIT)-b[01]|B3-(P|PZERO)-(main|mesh|time)-b[01]', role) is not None)


def parse_depth_change(text):
    """A deterministic natural-language patch; never evaluates code or launches."""
    require(isinstance(text, str), 'Natural-language request must be text')
    match = re.fullmatch(r'\s*(?:请)?(?:将|把)?\s*栅顶深度\s*(?:改为|设置为|设为|=)\s*(70|80|90)\s*(?:nm|纳米)\s*[。.]?\s*', text)
    if match is not None:return {'gate_top_depth_nm': int(match.group(1))}
    match=re.fullmatch(r'\s*(?:请)?(?:将|把)?\s*SN\s*结深\s*(?:改为|设置为|设为|=)\s*(82|87|92)\s*(?:nm|纳米)\s*[。.]?\s*',text)
    require(match is not None, 'Only one explicit gate-top depth 70/80/90 nm or SN junction depth 82/87/92 nm is recognized')
    return {'sn_junction_depth_nm':int(match.group(1))}
