"""Read-only comparison of geometry observations; never calls native tools.

Native observation collection, its execution release and budget are separate.
Only a cooperating operator's released, original-run evidence can be evaluated.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
RAW_FILES = ('material-measurements.csv','contact-measurements.csv','doping-measurements.csv',
             'sde-contact-measurements.csv','sde-contact-probes.csv','geometry-inventory.csv',
             'mesh-identity.csv','geometry-status.json','sde-geometry-status.txt','sde-material-probes.csv','observation-context.json',
             'sde-exit-code.txt','mesh-exit-code.txt','svisual-exit-code.txt')
FLOAT = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'

def require(ok, message):
    if not ok:raise ValueError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def obj(path):
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    require(isinstance(value,dict),'Expected JSON object: '+Path(path).name)
    return value

def number(value):
    require(not isinstance(value,bool),'Boolean is not a measurement')
    result=float(value)
    require(math.isfinite(result),'Nonfinite measurement')
    return result

def raw_number(raw,dimension):
    # SVisual extrema can return value {x y [z]}; retain raw in the audit.
    match=re.fullmatch(r'\s*('+FLOAT+r')(?:\s+\{([^{}]+)\})?\s*',raw)
    require(match is not None,'Malformed/multiple native numeric values: '+raw[:120])
    if match.group(2) is not None:
        coords=match.group(2).split()
        require(len(coords) in (dimension,3),'Unexpected extrema coordinates')
        for v in coords:number(v)
    return number(match.group(1))

def csv_rows(path,columns):
    with Path(path).open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f)
        require(reader.fieldnames==columns,'CSV columns differ: '+Path(path).name)
        rows=list(reader)
    require(rows,'Empty measurement CSV: '+Path(path).name)
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows),
            'Incomplete/extra CSV values: '+Path(path).name)
    return rows

def unique(rows,key):
    result={}
    for row in rows:
        require(row[key] not in result,'Duplicate observation: '+row[key])
        result[row[key]]=row
    return result

def close(actual,expected,absolute,relative):
    return abs(actual-expected)<=max(absolute,relative*abs(expected))

def bounds(g,c):
    if c['name'] in ('source','drain'):
        xy=c['physical_box_xy_um']; b=[xy[0],xy[1],[0.,0.]]
    elif c['name']=='body':b=[g['domain_um']['x'],g['domain_um']['y'],[g['domain_um']['z'][1]]*2]
    else:
        v=g['gate_void'];b=[[-v['x_half_width_um'],v['x_half_width_um']],
                             [-v['y_half_width_um'],v['y_half_width_um']],[v['top_um'],v['bottom_um']]]
    return [b[0],b[2],[0.,0.]] if g['dimension']==2 else b

def verify_context(plan_path,plan,raw,synthetic):
    context=obj(raw/'observation-context.json')
    require(context.get('schema')=='s2-geometry-observation-context-r1','Observation context schema differs')
    require(context.get('synthetic') is synthetic and context.get('origin')==
            ('synthetic_fixture' if synthetic else 'native_pipeline'),'Observation origin mismatch')
    if synthetic:
        require('UNIT_FIXTURE_NOT_NATIVE' in str(raw) and
                (raw/'SYNTHETIC_NOT_NATIVE').is_file(),'Synthetic isolation marker missing')
    else:
        require('UNIT_FIXTURE_NOT_NATIVE' not in str(raw) and
                not (raw/'SYNTHETIC_NOT_NATIVE').exists(),'Synthetic cannot qualify as native')
    for key,value in (('plan_sha256',sha(plan_path)),('geometry_contract_sha256',plan['geometry_contract_sha256']),
                      ('role_id',plan['role_id']),('dimension',plan['dimension'])):
        require(context.get(key)==value,'Context binding differs: '+key)
    for filename,key in (('geometry-with-measurements.scm','sde_deck_sha256'),
                         ('measure-geometry.tcl','svisual_script_sha256')):
        require(context.get(key)==sha(plan_path.parent/filename),'Producer script differs: '+filename)
    require(isinstance(context.get('producer_run_id'),str) and context['producer_run_id'],
            'Original producer run missing')
    mesh_sha=sha(raw/'cell_msh.tdr')
    require(context.get('mesh_sha256')==mesh_sha,'Context mesh binding differs')
    for key in ('sde_exit_code','mesh_exit_code','svisual_exit_code'):
        require(type(context.get(key)) is int and context[key]==0,'Unknown/nonzero raw '+key)
        filename=key.replace('_','-')+'.txt'
        raw_exit=(raw/filename).read_text(encoding='utf-8')
        require(re.fullmatch(r'0\s*',raw_exit) is not None and
                context.get('raw_exit_sha256',{}).get(filename)==sha(raw/filename),
                'Missing/changed/nonzero observed exit: '+filename)
    observations=unique(csv_rows(raw/'mesh-identity.csv',['phase','path','sha256','run_id','command_status']),'phase')
    require(set(observations)=={'BEFORE','AFTER'},'Missing mesh before/after observation')
    for row in observations.values():
        require(row['command_status']=='OK' and row['sha256']==mesh_sha and
                row['run_id']==context['producer_run_id'],'Mesh observation differs')
        require(row['path'].startswith('/') and Path(row['path']).name=='cell_msh.tdr','Original mesh path differs')
    require(observations['BEFORE']['path']==observations['AFTER']['path'],'Mesh path changed')
    require((raw/'sde-geometry-status.txt').read_text(encoding='utf-8').strip()==
            'S2_SDE_GEOMETRY_OBSERVATION_COMPLETED','SDE contact observation incomplete')
    status=obj(raw/'geometry-status.json')
    require(status.get('schema')=='s2-geometry-observation-status-r1' and status.get('completed') is True and
            type(status.get('mandatory_errors')) is int and status['mandatory_errors']==0 and
            status.get('dimension')==plan['dimension'] and status.get('plan_role')==plan['role_id'] and
            status.get('reference_mode')=='original_mesh','SVisual observation incomplete')
    return context,mesh_sha

def verify_release(raw,plan_path,plan,context,release_path):
    require(release_path is not None,'No native geometry producer release/authorization')
    release=obj(release_path)
    require(release.get('schema')=='s2-geometry-producer-release-r1' and release.get('status')=='RELEASED' and
            release.get('execution_enabled') is True and release.get('explicit_native_authorization') is True and
            release.get('synthetic') is False,'Native geometry release not approved')
    for key,value in (('plan_sha256',sha(plan_path)),('evaluator_sha256',sha(HERE/'evaluate.py')),
                      ('role_id',plan['role_id']),('producer_run_id',context['producer_run_id'])):
        require(release.get(key)==value,'Native release binding differs: '+key)
    require(release.get('budget_id') and release.get('budget_reservation_id'),'Geometry cost reservation missing')
    policy=obj(raw/'geometry-policy.released.json')
    require(release.get('policy_sha256')==sha(raw/'geometry-policy.released.json'),'Released policy hash differs')
    require(policy.get('approved') is True and policy.get('status')=='RELEASED','Geometry policy is unapproved')
    for k,v in plan['comparison_policy'].items():
        if k not in ('approved','status'):require(policy.get(k)==v,'Released policy changes proposed comparison: '+k)
    authority=obj(raw/'geometry-authorization.json')
    require(release.get('authorization_sha256')==sha(raw/'geometry-authorization.json') and
            authority.get('explicit_native_authorization') is True and authority.get('synthetic') is False and
            plan['role_id'] in authority.get('role_ids',[]),'Native geometry authority scope differs')

def compare(plan,raw):
    g=plan['expected_geometry'];policy=plan['comparison_policy'];d=plan['dimension'];details=[]
    require(g.get('dimension')==d and g.get('length_unit')=='um' and
            g.get('measure_unit')==('um^2' if d==2 else 'um^3'),'Geometry dimension/unit contract differs')
    checks=dict(materials=True,contacts=True,doping=True,units=True)
    inventory=csv_rows(raw/'geometry-inventory.csv',['kind','name','parent'])
    require(len({(r['kind'],r['name'],r['parent']) for r in inventory})==len(inventory),'Duplicate geometry inventory')
    def names(kind):return {r['name'] for r in inventory if r['kind']==kind}
    require(names('material')=={'Silicon','SiO2','Contact'},'Actual material inventory differs')
    require(names('contact')=={c['name'] for c in g['contacts']},'Actual mesh contacts differ')
    expected_regions={(r['name'],r['material']) for r in g['regions']}|{(c['name'],'Contact') for c in g['contacts']}
    require({(r['name'],r['parent']) for r in inventory if r['kind']=='region'}==expected_regions,
            'Actual mesh region/material mapping differs')
    require(all(r['parent']=='Contact' for r in inventory if r['kind']=='contact'),'Contact material mapping differs')
    fields=set('XY' if d==2 else 'XYZ')|{g['doping']['donor_species'],g['doping']['acceptor_species']}
    require(fields<=names('field'),'Missing native coordinate/doping fields')
    by_category={k:[] for k in ('materials','contacts','doping')}
    for item in plan['measurements']:by_category['materials' if item['category']=='units' else item['category']].append(item)
    for category,wanted in by_category.items():
        file={'materials':'material','contacts':'contact','doping':'doping'}[category]+'-measurements.csv'
        actual=unique(csv_rows(raw/file,['id','raw_value','command_status']),'id')
        require(set(actual)=={m['id'] for m in wanted},'Missing/unexpected measurement rows: '+category)
        for item in wanted:
            row=actual[item['id']];require(row['command_status']=='OK','Native measurement command failed: '+item['id'])
            value=raw_number(row['raw_value'],d)
            passed=close(value,item['expected'],item['absolute_tolerance'],item['relative_tolerance'])
            if category=='doping':passed=passed and value>=0
            checks[item['category']]=checks[item['category']] and passed
            details.append(dict(id=item['id'],raw_value=row['raw_value'],observed=value,expected=item['expected'],
                                unit=item['unit'],passed=passed))
    contacts=unique(csv_rows(raw/'sde-contact-measurements.csv',
        ['contact','entity_count','measure','unit','min_x','min_y','min_z','max_x','max_y','max_z']),'contact')
    require(set(contacts)=={c['name'] for c in g['contacts']},'Actual CAD contacts differ')
    for c in g['contacts']:
        row=contacts[c['name']]; require(re.fullmatch(r'[1-9]\d*',row['entity_count']) is not None,'Empty/invalid contact entity count')
        count=int(row['entity_count']);count_ok=(count>=(4 if d==2 else 6)) if c['name']=='gate' else count==1
        value=number(row['measure']);expect=c['measure']
        passed=(count_ok and value>0 and row['unit']==c['measure_unit'] and
                close(value,expect,policy['contact_absolute'],policy['contact_relative']))
        for axis,b in zip('xyz',bounds(g,c)):
            for prefix,expected in zip(('min_','max_'),b):
                passed=passed and close(number(row[prefix+axis]),expected,policy['coordinate_absolute_um'],0.)
        checks['contacts']=checks['contacts'] and passed
        details.append(dict(id='cad.contact.'+c['name'],observed=value,expected=expect,unit=c['measure_unit'],passed=passed))
    probe=unique(csv_rows(raw/'sde-contact-probes.csv',['id','contact','matched_count','attached']),'id')
    require(set(probe)=={p['id'] for p in plan['contact_probes']},'Contact surface probe coverage differs')
    for p in plan['contact_probes']:
        row=probe[p['id']]
        passed=row['contact']==p['contact'] and row['matched_count']=='1' and row['attached']=='1'
        checks['contacts']=checks['contacts'] and passed
        details.append(dict(id='cad.probe.'+p['id'],passed=passed))
    material=unique(csv_rows(raw/'sde-material-probes.csv',['id','matched_count','region','material']),'id')
    require(set(material)=={p['id'] for p in plan['material_probes']},'Material sample coverage differs')
    for p in plan['material_probes']:
        row=material[p['id']]
        passed=row['matched_count']=='1' and row['region']==p['expected_region'] and row['material']==p['expected_material']
        checks['materials']=checks['materials'] and passed
        checks['doping']=checks['doping'] and passed
        details.append(dict(id='cad.material.'+p['id'],passed=passed))
    return checks,details

def evaluate(plan_path,raw_directory,output_directory,synthetic=False,release_path=None):
    plan_path,raw,out=map(Path,(plan_path,raw_directory,output_directory))
    require(not out.exists(),'Output already exists; preserve prior report')
    report=dict(schema='s2-native-geometry-validation-r1',origin='synthetic_fixture' if synthetic else 'unverified',
                synthetic=synthetic,passed=False,native_qualified=False,is_tcad_result=False,
                checks=dict(materials=False,contacts=False,doping=False,units=False),
                mesh_sha256=None,evidence_sha256={},native_calls=0,errors=[],comparisons=[],
                boundary='Geometry observations only; finite samples are not full topology/doping proof or G1/G2.')
    try:
        plan=obj(plan_path)
        require(plan.get('schema')=='s2-geometry-measurement-plan-r1' and
                plan.get('dimension') in (2,3),'Unexpected measurement plan')
        context,mesh_sha=verify_context(plan_path,plan,raw,synthetic)
        report.update(origin=context['origin'],mesh_sha256=mesh_sha,producer_run_id=context['producer_run_id'],role_id=plan['role_id'],
                      geometry_contract_sha256=plan['geometry_contract_sha256'],plan_sha256=sha(plan_path))
        before={name:sha(raw/name) for name in RAW_FILES}
        numeric,details=compare(plan,raw)
        report['numeric_checks']=numeric;report['comparisons']=details
        if not synthetic:verify_release(raw,plan_path,plan,context,release_path)
        require(before=={name:sha(raw/name) for name in RAW_FILES} and sha(raw/'cell_msh.tdr')==mesh_sha,
                'Original measurements/mesh changed during comparison')
        report['checks']=numeric;report['evidence_sha256']=before
        report['passed']=all(numeric.values())
        if not report['passed']:report['errors'].append('Declared geometry comparisons failed')
        report['policy_authorized_for_native']=not synthetic
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError,OSError,csv.Error) as exc:
        report['errors'].append(str(exc))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'geometry-validation.json').open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True);parser.add_argument('--observations',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--release')
    parser.add_argument('--synthetic-fixture',action='store_true')
    a=parser.parse_args();r=evaluate(a.plan,a.observations,a.output,a.synthetic_fixture,a.release)
    print(json.dumps(dict(passed=r['passed'],synthetic=r['synthetic'],native_qualified=False,errors=r['errors'])))
    return 0 if r['passed'] else 2

if __name__=='__main__':raise SystemExit(main())
