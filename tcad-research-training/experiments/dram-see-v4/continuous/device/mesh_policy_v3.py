"""Explicit directional mesh r3; original r1/r2 algorithms remain byte-preserved."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

POLICY_ID = 'dram-see-v4-gradient-mesh-r3'
HERE = Path(__file__).resolve().parent
DEFINITION = HERE / 'mesh-policy-gradient-r3.json'
ASSUMPTIONS = HERE / 'MESH-GRADIENT-R3-ASSUMPTIONS.md'
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
    """SDE region intersections p572 and Delaunizer parameters p791 (W-2024.09)."""
    require(policy['delaunizer']['explicit_parameters']=={'maxPoints':2147483647},
            'r3 requires its finite positive native algorithm parameter')
    lines = [BEGIN, '; New numerical assumption; native accuracy remains unqualified.']
    for window in policy['volume_refinements']:
        name = window['name']
        lines += ['(sdedr:define-refeval-window "Window.'+name+'" "Cuboid" '
                  +position(window['physical_min_um'])+' '+position(window['physical_max_um'])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '
                  +' '.join(number(v) for v in window['max_size_um']+window['min_size_um'])+')']
        if window.get('regions'):
            require(not window['materials'], 'r3 region placements cannot silently mix material semantics')
            for region in window['regions']:
                require(region in ('R.Silicon','R.STI.minus','R.STI.plus'), 'Unknown STI adjacent region')
                placement = '(list "window" "Window.'+name+'" "region" "'+region+'")'
                lines.append('(sdedr:define-refinement-placement "Place.'+name+'.'+region+'" "Mesh.'+name+'" '+placement+')')
        else:
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
    lines += ['; Finite native quality-refinement bound; not a project budget or accuracy claim.',
              '(sdesnmesh:delaunizer "maxPoints" 2147483647)']
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
    windows = [deepcopy(original[name]) for name in ('All','Junction')]
    windows[1]['max_size_um'] = [v*scale for v in definition['junction_max_xyz_um']]
    windows[1]['min_size_um'] = [v*scale*.5 for v in definition['junction_max_xyz_um']]

    def add(name, low, high, maximum, materials=None, regions=None, family=None):
        require(all(domain[axis][0] <= lo < hi <= domain[axis][1]
                    for axis,lo,hi in zip('xyz',low,high)), 'Gradient window outside physical domain: '+name)
        windows.append(dict(name=name, physical_min_um=list(low), physical_max_um=list(high),
            sde_min_um=list(low), sde_max_um=list(high), max_size_um=[v*scale for v in maximum],
            min_size_um=[v*scale*.5 for v in maximum], materials=materials or []))
        if regions:
            windows[-1]['regions'] = list(regions)
        if family:
            windows[-1]['directional_family'] = family

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
    add('BlendFullWidth',[-half,domain['y'][0],low[2]],[half,domain['y'][1],high[2]],
        definition['blend_full_y_max_xyz_um'],['Silicon'])
    halo = definition['contact_halo_um']
    for contact in description['contacts']:
        if contact['name'] not in ('source','drain'):
            continue
        x,y = contact['physical_box_xy_um']
        add('Contact'+contact['name'].title(),[x[0]-halo[0],y[0]-halo[1],0.],
            [x[1]+halo[0],y[1]+halo[1],halo[2]],definition['contact_max_um'],['Silicon'])

    # Only new r3 windows below: physical coordinates come from the original CSG.
    directional = definition['geometry_derived_directional_windows']
    limits = directional['maximum_xyz_um']
    trench,gate,sti = description['outer_trench'],description['gate_void'],description['sti']
    oxide = description['nominal_oxide_um']['side']
    require(oxide>0 and sti['included'] and len(sti['y_intervals_um'])==2,
            'r3 requires the original finite-width trench/STI geometry')
    region_names = {r['name'] for r in description['regions']}
    adjacent = directional['sti_adjacent_regions']
    require(set(adjacent)=={'R.Silicon','R.STI.minus','R.STI.plus'}
            and set(adjacent)<=region_names and directional['excluded_sti_region']=='R.Trench',
            'r3 STI adjacency must match actual physical regions')
    padding = oxide*directional['padding_to_side_oxide_ratio']
    corner = oxide*directional['corner_half_width_to_side_oxide_ratio']
    core = oxide*directional['sti_core_half_width_to_side_oxide_ratio']
    transition = oxide*directional['sti_transition_half_width_to_side_oxide_ratio']
    bottom_y_halo = oxide*directional['sti_bottom_transition_y_halo_to_side_oxide_ratio']
    top_pre = oxide*directional['gate_top_pre_halo_to_side_oxide_ratio']
    top_post = oxide*directional['gate_top_post_halo_to_side_oxide_ratio']
    gx,gy = gate['x_half_width_um'],gate['y_half_width_um']
    tx = trench['x_half_width_um']
    env_low,env_high = original['GateOxide']['physical_min_um'],original['GateOxide']['physical_max_um']
    ex,ey,zmax = env_high
    zmin = env_low[2]
    require(env_low[:2]==[-ex,-ey] and zmin==trench['top_um'], 'Unexpected physical gate envelope')
    side_end = trench['round_center_z_um']+padding
    curve_start = trench['round_center_z_um']-oxide
    top_start,top_end = gate['top_um']-top_pre,gate['top_um']+top_post

    def family(name, boxes, regions=None):
        for index,(minimum,maximum) in enumerate(boxes):
            unique = name if len(boxes)==1 else name+str(index+1)
            add(unique,minimum,maximum,limits[name],regions=regions,family=name)

    family('GateEnvelope',[(env_low,env_high)])
    family('GateSideNormalX',[([-ex,-ey,zmin],[-gx+padding,ey,side_end]),
                             ([gx-padding,-ey,zmin],[ex,ey,side_end])])
    family('GateBottomCurveXZ',[([-ex,-ey,curve_start],[ex,ey,zmax])])
    family('GateTopNormalZ',[([-gx-padding,-gy-padding,top_start],[gx+padding,gy+padding,top_end])])
    family('GateEndNormalY',[([-ex,-ey,top_start],[ex,-gy+padding,zmax]),
                            ([-ex,gy-padding,top_start],[ex,ey,zmax])])
    xlow,xhigh = definition['active_bounds_um'][0][0],definition['active_bounds_um'][1][0]
    side_faces = sorted({value for interval in sti['y_intervals_um'] for value in interval})
    for name,width in (('STISideNormalYCore',core),('STISideNormalYTransition',transition)):
        family(name,[([xlow,y-width,sti['z_um'][0]],[xhigh,y+width,sti['z_um'][1]+width])
                     for y in side_faces],adjacent)
    for name,ywidth,zwidth in (('STIBottomNormalZCore',core,core),
                              ('STIBottomNormalZTransition',bottom_y_halo,transition)):
        family(name,[([xlow,ylo-ywidth,sti['z_um'][1]-zwidth],
                      [xhigh,yhi+ywidth,sti['z_um'][1]+zwidth]) for ylo,yhi in sti['y_intervals_um']],adjacent)
    inner_faces = [sti['y_intervals_um'][0][1],sti['y_intervals_um'][1][0]]
    require(inner_faces[0]<0<inner_faces[1], 'STI must bound the original central active strip')
    family('TrenchSTISideCorners',[([x-corner,y-corner,zmin],[x+corner,y+corner,side_end])
                                  for x in (-tx,tx) for y in inner_faces])
    family('TrenchSTICurvedCorners',[([-ex,y-corner,curve_start],[ex,y+corner,zmax]) for y in inner_faces])
    interfaces = []
    for name,window,first,box in (
        ('InterfacesRemote','All',definition['interface_remote_first_um'],[original['All']['physical_min_um'],original['All']['physical_max_um']]),):
        interfaces.append(dict(name=name, window_name=window, physical_min_um=box[0],physical_max_um=box[1],
            materials=['Silicon','SiO2'], first_step_um=first*scale, factor=definition['interface_factor'],DoubleSide=True,
            max_size_um=original['All']['max_size_um'],min_size_um=[first*scale*.5]*3))
    policy = dict(schema='dram-see-v4-instantiated-mesh-policy-r1', policy_id=POLICY_ID,dimension=3,
        length_unit='um',scale=scale,numerical_variant='mesh' if scale==.5 else 'main',
        model_sha256=digest(model_raw),physical_geometry_sha256=physical_digest(description),
        definition_sha256=digest(definition_raw),assumptions_sha256=digest(assumptions_raw),
        generator_sha256=digest(Path(__file__).read_bytes()),legacy_mesh_contract=deepcopy(description['mesh']),
        volume_refinements=windows,interface_refinements=interfaces,
        delaunizer=deepcopy(definition['delaunizer']),
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
    mesh['delaunizer'] = deepcopy(policy['delaunizer'])
    mesh['active_doping_refinement'] = dict(schema='dram-see-v4-partitioned-active-doping-r1',
        window_names=[v['name'] for v in policy['volume_refinements'] if v['name'].startswith(('ActiveDoping','Contact','Blend'))],
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
