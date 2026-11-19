"""Pure original geometry expectations; numerical tolerances retained."""
import math
POLICY = dict(schema='s2-geometry-comparison-policy-r1',
              status='ORIGINAL_NUMERICAL_CRITERIA_RETAINED', region_relative=0.005,
              region_absolute=1e-10, contact_relative=1e-6,
              contact_absolute=1e-10, coordinate_absolute_um=1e-6,
              doping_relative=0.02, doping_absolute_cm3=1e8)

def contact_bounds(g, contact):
    name, d = contact['name'], g['dimension']
    if name in ('source', 'drain'):
        box=contact['physical_box_xy_um']; bounds=[box[0],box[1],[0.,0.]]
    elif name=='body':
        bounds=[g['domain_um']['x'],g['domain_um']['y'],[g['domain_um']['z'][1]]*2]
    else:
        gate=g['gate_void']
        bounds=[[-gate['x_half_width_um'],gate['x_half_width_um']],
                [-gate['y_half_width_um'],gate['y_half_width_um']],
                [gate['top_um'],gate['bottom_um']]]
    return [bounds[0],bounds[2],[0.,0.]] if d==2 else bounds

def measurement_plan(g):
    """Declared expected values only. They never replace raw measurements."""
    rows=[]; probes=[]; material_probes=[]
    def add(id,category,field,kind,entity,op,value,unit,rtol=0.,atol=0.,pos=None):
        row=dict(id=id,category=category,field=field,entity_kind=kind,entity=entity,
                 operation=op,expected=value,unit=unit,relative_tolerance=rtol,
                 absolute_tolerance=atol)
        if pos is not None:row['native_position']=pos
        rows.append(row)
    for region in g['regions']:
        add('region.'+region['name'],'materials','ONE','region',region['name'],
            'integral',region['measure'],g['measure_unit'],POLICY['region_relative'],POLICY['region_absolute'])
    axes='XY' if g['dimension']==2 else 'XYZ'
    domain=[g['domain_um'][x] for x in ('xz' if g['dimension']==2 else 'xyz')]
    for axis,bounds in zip(axes,domain):
        for op,value in zip(('min','max'),bounds):
            add('domain.'+axis+'.'+op,'units',axis,'material','Silicon',op,value,'um',
                atol=POLICY['coordinate_absolute_um'])
    for c in g['contacts']:
        for axis,bounds in zip(axes,contact_bounds(g,c)):
            for op,value in zip(('min','max'),bounds):
                add('contact.'+c['name']+'.'+axis+'.'+op,'contacts',axis,'region',c['name'],op,value,'um',
                    atol=POLICY['coordinate_absolute_um'])
        if c['name']=='gate':
            for p in c['boundary_probes']:
                probes.append(dict(id='gate.'+p['surface'],contact='gate',native_position=p['sde_point_um']))
        else:probes.append(dict(id=c['name'],contact=c['name'],native_position=c['sde_probe_um']))
    dp=g['doping']; donor=dp['donor_species']; acceptor=dp['acceptor_species']
    ys=[0.] if g['dimension']==2 else [-.008,0.,.008]
    # Keep the originally exercised probe coordinates for every controlled SN
    # depth. The 87 nm probe is a common location, not a hard-coded junction;
    # all expected concentrations below use the actual a_sn from the model.
    physical=[(x,y,z) for x in (-.052,.052) for y in ys for z in (.01,.04,.07,.087,.11,.1375,.17)]
    physical += [(x,0.,z) for x in (-.006,0.,.006) for z in (.18,.22)]
    physical += [(.3,0.,.4)]
    for i,(x,y,z) in enumerate(physical):
        weight=(1-math.tanh(x/dp['blend_um']))/2
        expected=dp['peak_cm3']*(weight*math.exp(-(z/dp['a_sn_um'])**2)
                                +(1-weight)*math.exp(-(z/dp['a_bl_um'])**2))
        native=[x,z] if g['dimension']==2 else [x,y,z]
        material_probes.append(dict(id='sample.'+str(i),native_position=[x,z,0.] if g['dimension']==2 else native,
                                    expected_region='R.Silicon',expected_material='Silicon'))
        for species,val in ((donor,expected),(acceptor,dp['acceptor_cm3'])):
            add('sample.'+str(i)+'.'+species,'doping',species,'all','','probe',val,'cm^-3',
                POLICY['doping_relative'],POLICY['doping_absolute_cm3'],native)
    add('silicon.donor.min','doping',donor,'material','Silicon','min',0.,'cm^-3',
        atol=POLICY['doping_absolute_cm3'])
    add('silicon.donor.max','doping',donor,'material','Silicon','max',dp['peak_cm3'],'cm^-3',
        POLICY['doping_relative'],POLICY['doping_absolute_cm3'])
    for op in ('min','max'):
        add('silicon.acceptor.'+op,'doping',acceptor,'material','Silicon',op,dp['acceptor_cm3'],'cm^-3',
            POLICY['doping_relative'],POLICY['doping_absolute_cm3'])
    for region in g['regions']:
        if region['material']=='Silicon':continue
        for species in (donor,acceptor):
            for op in ('min','max'):
                add('outside_si.'+region['name']+'.'+species+'.'+op,'doping',species,'region',region['name'],op,0.,'cm^-3',
                    atol=POLICY['doping_absolute_cm3'])
    return rows,probes,material_probes
