"""Explicit 3D numerical mesh policy; never changes the physical model or launches."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

POLICY_ID = 'dram-see-v4-gradient-mesh-r1'
HERE = Path(__file__).resolve().parent
DEFINITION = HERE / 'mesh-policy-gradient-r1.json'
ASSUMPTIONS = HERE / 'MESH-GRADIENT-R1-ASSUMPTIONS.md'
FILES = ('mesh-policy.json', 'mesh-policy-definition.json', 'mesh-policy-assumptions.md')
BEGIN = '; BEGIN EXPLICIT MESH POLICY ' + POLICY_ID
END = '; END EXPLICIT MESH POLICY ' + POLICY_ID


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def physical_digest(description):
    physical = {key:value for key,value in description.items() if key != 'mesh'}
    return digest(json.dumps(physical, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def number(value):
    return format(value, '.15g')


def position(values):
    return '(position ' + ' '.join(number(v) for v in values) + ')'


def render_block(policy):
    """Only SDE forms already present in the actual D3r3 input are used."""
    lines = [BEGIN, '; New numerical assumption; native accuracy remains unqualified.']
    for window in policy['volume_refinements']:
        name = window['name']
        lines += ['(sdedr:define-refeval-window "Window.'+name+'" "Cuboid" '
                  +position(window['physical_min_um'])+' '+position(window['physical_max_um'])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '
                  +' '.join(number(v) for v in window['max_size_um']+window['min_size_um'])+')']
        placement = '"Window.'+name+'"'
        if window['materials']:
            placement = '(list "window" '+placement+' "material" "'+window['materials'][0]+'")'
        lines.append('(sdedr:define-refinement-placement "Place.'+name+'" "Mesh.'+name+'" '+placement+')')
    for interface in policy['interface_refinements']:
        name = interface['name']
        if interface['window_name'] != 'All':
            lines.append('(sdedr:define-refeval-window "Window.'+interface['window_name']+'" "Cuboid" '
                         +position(interface['physical_min_um'])+' '+position(interface['physical_max_um'])+')')
        lines += ['(sdedr:define-refinement-size "Mesh.'+name+'" '
                  +' '.join(number(v) for v in interface['max_size_um']+interface['min_size_um'])+')',
                  '(sdedr:define-refinement-function "Mesh.'+name+'" "MaxLenInt" "Silicon" "SiO2" '
                  +number(interface['first_step_um'])+' '+number(interface['factor'])+' "DoubleSide")',
                  '(sdedr:define-refinement-placement "Place.'+name+'" "Mesh.'+name+'" "Window.'+interface['window_name']+'")']
    return '\n'.join(lines+[END])+'\n'


def build(model_raw, description, scale):
    require(description['dimension'] == 3 and scale in (1, .5), 'Gradient policy supports only 3D main/h2')
    definition_raw, assumptions_raw = DEFINITION.read_bytes(), ASSUMPTIONS.read_bytes()
    definition = json.loads(definition_raw)
    require(definition['policy_id'] == POLICY_ID and definition['dimension'] == 3, 'Unknown fixed mesh definition')
    original = {v['name']:v for v in description['mesh']['windows']}
    require(set(original) == {'All','Junction','GateOxide','AlphaTrack'}, 'Legacy mesh input differs')
    domain = description['domain_um']
    require(domain['z'] == [0.,1.], 'Gradient track partitions require the original 1um depth')
    windows = [deepcopy(original[name]) for name in ('All','Junction','GateOxide')]

    def add(name, low, high, maximum, materials=None):
        require(all(domain[axis][0] <= lo < hi <= domain[axis][1]
                    for axis,lo,hi in zip('xyz',low,high)), 'Gradient window outside physical domain: '+name)
        windows.append(dict(name=name, physical_min_um=list(low), physical_max_um=list(high),
            sde_min_um=list(low), sde_max_um=list(high), max_size_um=[v*scale for v in maximum],
            min_size_um=[v*scale*.5 for v in maximum], materials=materials or []))

    track = original['AlphaTrack']
    bounds = definition['source_depth_boundaries_um']
    for i,name in enumerate(('AlphaTrackNear','AlphaTrackBulk','AlphaTrackEnd')):
        low,high = list(track['physical_min_um']),list(track['physical_max_um'])
        low[2],high[2] = bounds[i:i+2]
        add(name,low,high,definition['source_max_xyz_um'][i],['Silicon'])
    low,high = deepcopy(definition['active_bounds_um'])
    half = definition['blend_half_width_um']
    add('ActiveDopingCore',[-half,low[1],low[2]],[half,high[1],high[2]],definition['active_core_max_um'],['Silicon'])
    add('ActiveDopingLeft',low,[-half,high[1],high[2]],definition['active_outer_max_um'],['Silicon'])
    add('ActiveDopingRight',[half,low[1],low[2]],high,definition['active_outer_max_um'],['Silicon'])
    halo = definition['contact_halo_um']
    for contact in description['contacts']:
        if contact['name'] not in ('source','drain'):
            continue
        x,y = contact['physical_box_xy_um']
        add('Contact'+contact['name'].title(),[x[0]-halo[0],y[0]-halo[1],0.],
            [x[1]+halo[0],y[1]+halo[1],halo[2]],definition['contact_max_um'],['Silicon'])
    interfaces = []
    for name,window,first,box in (
        ('InterfacesRemote','All',definition['interface_remote_first_um'],[original['All']['physical_min_um'],original['All']['physical_max_um']]),
        ('InterfacesActive','InterfaceActive',definition['interface_local_first_um'],definition['active_bounds_um'])):
        interfaces.append(dict(name=name, window_name=window, physical_min_um=box[0],physical_max_um=box[1],
            materials=['Silicon','SiO2'], first_step_um=first*scale, factor=definition['interface_factor'],DoubleSide=True,
            max_size_um=original['All']['max_size_um'],min_size_um=[first*scale*.5]*3))
    policy = dict(schema='dram-see-v4-instantiated-mesh-policy-r1', policy_id=POLICY_ID,dimension=3,
        length_unit='um',scale=scale,numerical_variant='mesh' if scale==.5 else 'main',
        model_sha256=digest(model_raw),physical_geometry_sha256=physical_digest(description),
        definition_sha256=digest(definition_raw),assumptions_sha256=digest(assumptions_raw),
        generator_sha256=digest(Path(__file__).read_bytes()),legacy_mesh_contract=deepcopy(description['mesh']),
        volume_refinements=windows,interface_refinements=interfaces,
        model_numerics='Original S2 baseline values retained; this explicit contract specifies the changed 3D placements',
        physical_parameters_changed=False,measurement_criteria_changed=False,native_accuracy_qualified=False,
        source_charge_or_response_convergence_qualified=False,resource_limits=None)
    policy['sde_mesh_block_sha256'] = digest(render_block(policy).encode('utf-8'))
    return policy, {'mesh-policy.json':encoded(policy),'mesh-policy-definition.json':definition_raw,
                    'mesh-policy-assumptions.md':assumptions_raw}


def describe(description, policy, raw):
    require(description['dimension']==3 and policy['physical_geometry_sha256']==physical_digest(description),
            'Mesh policy physical geometry differs')
    result = deepcopy(description)
    mesh = result['mesh']
    mesh.pop('interface')
    mesh['windows'] = deepcopy(policy['volume_refinements'])
    mesh['interface_refinements'] = deepcopy(policy['interface_refinements'])
    mesh['active_doping_refinement'] = dict(schema='dram-see-v4-partitioned-active-doping-r1',
        window_names=[v['name'] for v in policy['volume_refinements'] if v['name'].startswith(('ActiveDoping','Contact'))],
        source='mesh-policy.json',probe_locations_changed=False)
    mesh['policy'] = dict(policy_id=POLICY_ID,contract_file='mesh-policy.json',contract_sha256=digest(raw))
    return result


def apply(text, policy):
    start = '(sdedr:define-refeval-window "Window.All"'
    end = '; Uncontacted external boundaries retain natural insulating conditions.'
    require(text.count(start)==1 and text.count(end)==1 and BEGIN not in text,
            'Legacy mesh replacement anchors differ')
    before,tail = text.split(start,1)
    original,after = tail.split(end,1)
    require('"Mesh.Interfaces" "MaxLenInt" "Silicon" "SiO2"' in original
            and '"Window.ActiveDoping"' in original,'Expected legacy interface and active mesh are absent')
    return before+render_block(policy)+end+after


def inherit(producer_inputs):
    present = set(FILES)&set(producer_inputs)
    if not present:
        require('policy' not in json.loads(producer_inputs['geometry-contract.json'])['mesh'],
                'Producer declares a mesh policy without its original contract')
        return {}
    require(present==set(FILES), 'Producer mesh policy files are incomplete')
    result = {name:producer_inputs[name] for name in FILES}
    policy = json.loads(result['mesh-policy.json'])
    geometry = json.loads(producer_inputs['geometry-contract.json'])
    require(policy['policy_id']==POLICY_ID and policy['model_sha256']==digest(producer_inputs['model.proposed.json'])
            and policy['physical_geometry_sha256']==physical_digest(geometry), 'Producer mesh policy/model/geometry differs')
    require(policy['definition_sha256']==digest(result['mesh-policy-definition.json'])
            and policy['assumptions_sha256']==digest(result['mesh-policy-assumptions.md'])
            and geometry['mesh']['policy']['contract_sha256']==digest(result['mesh-policy.json']),
            'Producer mesh policy original bytes differ')
    return result
