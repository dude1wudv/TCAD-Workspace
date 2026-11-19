"""Explicit SN87 bounded-coarsening mesh r6; old policies are byte-preserved."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

POLICY_ID = 'dram-see-v4-gradient-mesh-r6'
HERE = Path(__file__).resolve().parent
DEFINITION = HERE / 'mesh-policy-gradient-r6.json'
ASSUMPTIONS = HERE / 'MESH-GRADIENT-R6-ASSUMPTIONS.md'
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


def source_core_geometry(model_raw, original_track, domain, definition):
    """Bind to the original source center/width and validate its full 4w window."""
    alpha=json.loads(model_raw)['alpha']
    require(alpha['angle_deg_from_positive_z']==0, 'r4 column is a normal-alpha mesh candidate')
    width=alpha['radial_Gaussian_w_nm']/1000.
    center=[value/1000. for value in alpha['position_nm'][:2]]
    outer_multiple=definition['source_outer_half_width_multiple']
    core_multiple=definition['source_core_half_width_multiple']
    require(width>0 and (outer_multiple,core_multiple)==(4,2),'Unknown explicit r4 transverse partition')
    for axis,index in (('x',0),('y',1)):
        expected_low=max(domain[axis][0],center[index]-outer_multiple*width)
        expected_high=min(domain[axis][1],center[index]+outer_multiple*width)
        require(original_track['physical_min_um'][index]==expected_low
                and original_track['physical_max_um'][index]==expected_high,
                'Original 4w source window does not match the declared source center/width')
    low=[max(domain[axis][0],center[i]-core_multiple*width) for i,axis in enumerate('xy')]
    high=[min(domain[axis][1],center[i]+core_multiple*width) for i,axis in enumerate('xy')]
    require(all(a<b for a,b in zip(low,high)), 'Source core does not intersect the actual domain')
    return dict(schema='dram-see-v4-nested-source-column-r1',length_unit='um',
        source_center_xy_um=center,radial_width_um=width,core_min_xy_um=low,core_max_xy_um=high,
        outer_half_width_multiple=outer_multiple,core_half_width_multiple=core_multiple,
        source_values_unchanged=True,source_domain_unchanged=True,source_tail_renormalized=False,
        scope=definition['source_partition_scope'],native_coverage_qualified=False)


def render_block(policy):
    """SDE region intersections p572 and Delaunizer parameters p791 (W-2024.09)."""
    require(policy['delaunizer']['explicit_parameters']=={'maxPoints':2147483647},
            'r4 requires its finite positive native algorithm parameter')
    lines = [BEGIN, '; New numerical assumption; native accuracy remains unqualified.']
    for window in policy['volume_refinements']:
        name = window['name']
        lines += ['(sdedr:define-refeval-window "Window.'+name+'" "Cuboid" '
                  +position(window['physical_min_um'])+' '+position(window['physical_max_um'])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '
                  +' '.join(number(v) for v in window['max_size_um']+window['min_size_um'])+')']
        if window.get('regions'):
            require(not window['materials'], 'Region placements cannot silently mix material semantics')
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



DOPING_TABLE_SHA256 = '3e6a7e34522a3be0c000874c92f1d7dda87ab174b8686193100245a135449cf1'
SOURCE_CANDIDATE_SHA256 = '0131e202d37c48d8e70569052d11222506570ed19a3e00518156eb7f1ff04bfa'
SOURCE_ANALYSIS_SHA256 = '39b116b621ebf6dcfab6ec38e887a82b561c7b3e6756fe870f7525ecbbcf78e4'
EVIDENCE_COUNTS = {'NEW_HESSIAN_BOUNDED_COARSENING':75,
    'INHERITED_ACTUAL_R5_NO_NEW_CERTIFICATION':23,'EXACT_EFFECTIVE_Y_FACTORING_WITH_BLEND':1}


def doping_partitions(model_raw, description, definition):
    """Fixed original mathematical table; no runtime lookup or physical retuning."""
    source = definition['doping_partition_source']
    raw = source['raw_utf8'].encode('utf-8')
    require(digest(raw) == source['sha256'] == DOPING_TABLE_SHA256,
            'r6 original doping partition evidence differs')
    table = json.loads(raw.decode('utf-8'))
    model = json.loads(model_raw)
    doping, measured = model['doping'], description['doping']
    require(model['geometry']['units'] == 'nm' and doping['units'] == 'cm^-3'
            and model['geometry']['gate_top_depth_nm'] in (70,80,90)
            and doping['sn_junction_depth_nm'] == 87
            and doping['bl_junction_depth_nm'] == 137.5
            and doping['peak_donor'] == 1.45e20 and doping['uniform_acceptor'] == 1e17,
            'r6 supports only the analyzed SN87/BL137.5/unchanged doping condition')
    ratio = doping['peak_donor']/doping['uniform_acceptor']
    require(measured['peak_cm3'] == doping['peak_donor']
            and measured['acceptor_cm3'] == doping['uniform_acceptor']
            and measured['blend_um'] == .005 and measured['material_restriction'] == 'Silicon'
            and measured['a_sn_um'] == (87/1000.)/math.sqrt(math.log(ratio))
            and measured['a_bl_um'] == (137.5/1000.)/math.sqrt(math.log(ratio)),
            'r6 physical doping descriptor differs from the analyzed model')
    require(table['schema']=='dram-see-v4-bounded-coarsening-only-candidate-r3'
            and len(table['placements'])==99 and len(table['replace_only_r5_doping_window_names'])==13
            and table['all_placements_material']=='Silicon'
            and table['baseline_policy_ref']['sha256']=='5679c4ad22e1354baad49e6f962fa4a9a1cf2ecdefebe5b4ba633826312765c8'
            and all(table[key] is False for key in ('full_domain_certified','native_accuracy_qualified','actual_cell_spans_verified')),
            'r6 requires the original complete 99-placement partial-evidence table')
    counts={key:sum(row['evidence_class']==key for row in table['placements']) for key in EVIDENCE_COUNTS}
    require(counts==EVIDENCE_COUNTS,'r6 bounded/inherited/support evidence classes differ')
    for row in table['placements']:
        for field in ('lo','hi'):
            require([float(v) for v in row[field+'_um_decimal']]==[v/1000. for v in row[field+'_nm']],
                    'r6 original nm/um coordinates differ')
        require([float(v) for v in row['max_step_um_decimal']]==[v/1000. for v in row['max_step_nm']]
                and [float(v) for v in row['minimum_step_um_decimal']]==[float(v)*.5 for v in row['max_step_um_decimal']],
                'r6 original step units or half-minimum relation differs')
    return table


def doping_window_name(row):
    return row['id']


def source_spacing_evidence(model_raw, definition):
    source=definition['source_spacing_source']
    raw=source['raw_utf8'].encode('utf-8')
    analysis_raw=source['analysis_raw_utf8'].encode('utf-8')
    require(digest(raw)==source['sha256']==SOURCE_CANDIDATE_SHA256
            and digest(analysis_raw)==source['analysis_ref']['sha256']==SOURCE_ANALYSIS_SHA256,
            'r6 original source-spacing evidence differs')
    candidate=json.loads(raw);analysis=json.loads(analysis_raw)
    require(candidate['native_qualified'] is False and candidate['source_width_or_tail_adjusted'] is False
            and candidate['thresholds_changed'] is False,
            'r6 mathematical source evidence is not native qualification')
    require(definition['source_core_max_xyz_um']==[r['candidate_max_size_um'] for r in candidate['changes_only']],
            'r6 three core transverse sizes differ from the exact source candidate')
    model=json.loads(model_raw)
    scope=candidate['scope']
    require(model['alpha']['first_energy_MeV']==5 and model['alpha']['angle_deg_from_positive_z']==0
            and model['alpha']['radial_Gaussian_w_nm']==50,
            'r6 source column only prepares the original 5MeV normal alpha numerical candidate')
    return dict(candidate_sha256=SOURCE_CANDIDATE_SHA256,analysis_sha256=SOURCE_ANALYSIS_SHA256,
        scope=scope,conditional_certificate=analysis['rational_upper_bound_certificate'],
        certificate_conditions=analysis['P1_certificate_conditions'],
        conditional_certificate_scope_matches_input=(model['geometry']['gate_top_depth_nm']==scope['gate_top_depth_nm']
            and model['doping']['sn_junction_depth_nm']==scope['sn_junction_depth_nm']),
        actual_cell_spans_verified=False,ROI_centroid_moments_qualified=False,
        native_accuracy_qualified=False,source_values_changed=False)


def build(model_raw, description, scale):
    require(description['dimension'] == 3 and scale in (1, .5), 'Gradient policy supports only 3D main/h2')
    definition_raw, assumptions_raw = DEFINITION.read_bytes(), ASSUMPTIONS.read_bytes()
    definition = json.loads(definition_raw)
    require(definition['policy_id'] == POLICY_ID and definition['dimension'] == 3, 'Unknown fixed mesh definition')
    doping_table = doping_partitions(model_raw, description, definition)
    spacing_evidence = source_spacing_evidence(model_raw, definition)
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
    source_partition=source_core_geometry(model_raw,track,domain,definition)
    bounds = definition['source_depth_boundaries_um']
    for i,name in enumerate(('AlphaTrackNear','AlphaTrackBulk','AlphaTrackEnd')):
        low,high = list(track['physical_min_um']),list(track['physical_max_um'])
        low[2],high[2] = bounds[i:i+2]
        add(name,low,high,definition['source_max_xyz_um'][i],['Silicon'])
        core_low=source_partition['core_min_xy_um']+[low[2]]
        core_high=source_partition['core_max_xy_um']+[high[2]]
        add(name+'Core',core_low,core_high,definition['source_core_max_xyz_um'][i],['Silicon'])
    for row in doping_table['placements']:
        add(doping_window_name(row),[float(v) for v in row['lo_um_decimal']],
            [float(v) for v in row['hi_um_decimal']],[float(v) for v in row['max_step_um_decimal']],['Silicon'])
        windows[-1]['doping_candidate_id'] = row['id']
        windows[-1]['doping_evidence_class'] = row['evidence_class']
        windows[-1]['doping_original_r5_window_names'] = row.get('original_r5_window_names',[])
        windows[-1]['doping_new_mathematical_certification'] = row['evidence_class']=='NEW_HESSIAN_BOUNDED_COARSENING'
        if 'maximum_bound_over_original_tolerance' in row:
            windows[-1]['doping_maximum_bound_over_original_tolerance'] = row['maximum_bound_over_original_tolerance']
    halo = definition['contact_halo_um']
    for contact in description['contacts']:
        if contact['name'] not in ('source','drain'):
            continue
        x,y = contact['physical_box_xy_um']
        add('Contact'+contact['name'].title(),[x[0]-halo[0],y[0]-halo[1],0.],
            [x[1]+halo[0],y[1]+halo[1],halo[2]],definition['contact_max_um'],['Silicon'])

    # The complete r5 five-band geometric partition remains unchanged.
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
    surface_end = zmin+oxide*definition['straight_geometry_partition']['top_surface_halo_to_side_oxide_ratio']
    require(zmin < surface_end < top_start < top_end < curve_start < side_end,
            'r6 physical straight/endpoint bands overlap or leave their original bounds')
    side_bands = (('Surface',zmin,surface_end,False),
                  ('StraightUpper',surface_end,top_start,True),
                  ('GateTop',top_start,top_end,False),
                  ('StraightLower',top_end,curve_start,True),
                  ('CurveTransition',curve_start,side_end,False))

    def family(name, boxes, regions=None):
        for index,(minimum,maximum) in enumerate(boxes):
            unique = name if len(boxes)==1 else name+str(index+1)
            add(unique,minimum,maximum,limits[name],regions=regions,family=name)

    def straight_family(name, boxes, coarse_maximum):
        for index,(minimum,maximum) in enumerate(boxes):
            for segment,lo,hi,straight in side_bands:
                low,high=list(minimum),list(maximum)
                low[2],high[2]=lo,hi
                add(name+str(index+1)+segment,low,high,
                    coarse_maximum if straight else limits[name],family=name)
                windows[-1]['directional_segment'] = segment

    family('GateEnvelope',[(env_low,env_high)])
    straight_family('GateSideNormalX',[([-ex,-ey,zmin],[-gx+padding,ey,side_end]),
                             ([gx-padding,-ey,zmin],[ex,ey,side_end])],
                    definition['straight_geometry_partition']['gate_side_straight_max_xyz_um'])
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
    straight_family('TrenchSTISideCorners',[([x-corner,y-corner,zmin],[x+corner,y+corner,side_end])
                                  for x in (-tx,tx) for y in inner_faces],
                    definition['straight_geometry_partition']['trench_sti_edge_straight_max_xyz_um'])
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
        source_transverse_partition=source_partition,
        source_spacing_evidence=spacing_evidence,
        doping_partition_evidence=dict(source_sha256=DOPING_TABLE_SHA256,
            applicability=deepcopy(doping_table['applicability']),
            candidate_ids=[row['id'] for row in doping_table['placements']],
            baseline_policy_ref=deepcopy(doping_table['baseline_policy_ref']),
            evidence_counts=deepcopy(EVIDENCE_COUNTS),full_domain_certified=False,
            actual_cell_spans_verified=False,native_accuracy_qualified=False),
        straight_geometry_partition=deepcopy(definition['straight_geometry_partition']),
        previous_native_delaunizer_serialization=deepcopy(definition['previous_native_delaunizer_serialization']),
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
    mesh['active_doping_refinement'] = dict(schema='dram-see-v4-partitioned-active-doping-r2',
        window_names=[v['name'] for v in policy['volume_refinements'] if 'doping_candidate_id' in v or v['name'].startswith('Contact')],
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
