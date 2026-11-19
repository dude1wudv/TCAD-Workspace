"""Offline S2 geometry-measurement candidate. Never launches a native tool."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

FROZEN_MANIFEST = '165473aacaada00f613885ced15b0d645205740cdf5c0c0fcffb50d82c18a8f3'
ROLES = {'B1-D2': 2, 'B1-D3': 3}

POLICY = dict(schema='s2-geometry-comparison-policy-r1', approved=False,
              status='PROPOSED_NOT_RELEASED', region_relative=0.005,
              region_absolute=1e-10, contact_relative=1e-6,
              contact_absolute=1e-10, coordinate_absolute_um=1e-6,
              doping_relative=0.02, doping_absolute_cm3=1e8)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_json(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Expected JSON object: '+str(path))
    return data

def write_json(path, data):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

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

def prepare(package, output):
    package, output = Path(package), Path(output)
    if digest(package/'package-manifest.json') != FROZEN_MANIFEST:
        raise ValueError('Frozen S2 package identity differs')
    manifest = read_json(package/'package-manifest.json')['files_sha256']
    plans = {}
    for role, dimension in ROLES.items():
        rel = 'roles/'+role+'/geometry-contract.json'
        if digest(package/rel) != manifest[rel]:
            raise ValueError('Frozen geometry changed: '+role)
        geometry = read_json(package/rel)
        if geometry.get('schema') != 's2-bcat-analytic-geometry-r1' or geometry.get('dimension') != dimension:
            raise ValueError('Unexpected geometry contract')
        plans[role] = dict(schema='s2-geometry-measurement-plan-r1', role_id=role,
                           dimension=dimension, geometry_contract_sha256=manifest[rel],
                           execution_enabled=False, policy_approved=False,
                           actual_mesh_sha256=None, expected_geometry=geometry,
                           origin='offline_candidate', native_qualified=False)
        plans[role]['comparison_policy']=dict(POLICY)
        plans[role]['measurements'],plans[role]['contact_probes'],plans[role]['material_probes']=measurement_plan(geometry)
    output.mkdir(parents=True, exist_ok=False)
    from native_scripts import render_sde,render_svisual
    for role, plan in plans.items():
        folder=output/role;folder.mkdir()
        write_json(folder/'measurement-plan.json',plan)
        # Full original deck prefix retained, observer only; frozen file is read-only.
        original=package/'roles'/role/'geometry.scm'
        if digest(original)!=manifest['roles/'+role+'/geometry.scm']:
            raise ValueError('Frozen CAD source changed')
        (folder/'geometry-with-measurements.scm').write_bytes(original.read_bytes()+b'\n'+render_sde(plan).encode('utf-8'))
        (folder/'measure-geometry.tcl').write_text(render_svisual(plan),encoding='utf-8',newline='\n')
        write_json(folder/'comparison-policy.proposed.json',POLICY)
    # Ship the exact comparison code as review material, never an execution project.
    (output/'evaluate.py').write_bytes((Path(__file__).parent/'evaluate.py').read_bytes())
    result = dict(schema='s2-geometry-candidate-r1', status='OFFLINE_CANDIDATE_NOT_RELEASED',
                  roles=list(plans), native_calls=0, execution_enabled=False,
                  package_manifest_sha256=FROZEN_MANIFEST,
                  files_sha256={p.relative_to(output).as_posix():digest(p) for p in sorted(output.rglob('*')) if p.is_file()},
                  native_geometry_measurement_calls_proposed=2,approved_native_calls=0,
                  code_sha256={name:digest(Path(__file__).parent/name) for name in ('producer.py','evaluate.py','native_scripts.py')},
                  geometry_report_location='same solver archive before it is sealed',
                  a0_reuse='accepted D3 mesh and geometry evidence; no duplicate mesh or probe job')
    write_json(output/'candidate.json', result)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--package',required=True);p.add_argument('--output',required=True)
    args=parser.parse_args()
    result=prepare(args.package,args.output)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    main()
