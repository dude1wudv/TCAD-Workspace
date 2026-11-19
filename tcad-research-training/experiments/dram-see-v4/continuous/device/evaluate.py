"""Read-only comparison of geometry observations; never calls native tools.

Only original-run observations bound to current immutable inputs are evaluated.
Current authorization replaces former budget and release-signature prerequisites.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import dfise_observer
import importlib.util

HERE = Path(__file__).resolve().parent
RAW_FILES = ('material-measurements.csv','contact-measurements.csv','doping-measurements.csv',
             'sde-contact-measurements.csv','sde-contact-probes.csv','geometry-inventory.csv',
             'mesh-identity.csv','geometry-status.json','sde-geometry-status.txt','sde-material-probes.csv','observation-context.json',
             'sde-exit-code.txt','mesh-exit-code.txt','svisual-exit-code.txt',
             'tdx-metadata-exit-code.txt','tdx-converter-exit-code.txt',
             'tdr-region-datasets.csv','tdr-geometry.csv','tdr-topology-identity.csv','tdr-region-status.json',
             'mesh-observed.grd','mesh-observed.dat','tdx-source-before.json','tdx-source-after.json')
FLOAT = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
HDF5_BACKEND='native_hdf5_v16_export'
HDF5_CONTEXT='dram-see-v4-hdf5-geometry-observation-context-r1'
ACTIVE_HDF5_CONTEXT='dram-see-v4-hdf5-geometry-observation-context-r2'
ACTIVE_REPRESENTATION='tdr-hdf5-v16'
HDF5_RAW_FILES=tuple(n for n in RAW_FILES if n not in ('tdx-converter-exit-code.txt','mesh-observed.grd',
    'mesh-observed.dat','tdx-source-before.json','tdx-source-after.json'))+(
    'current-mesh-before.json','current-mesh-after.json','tdr-hash-provider.csv','geometry-hash-provider.csv')

def sibling(name):
    """Closed sibling modules only; no code path supplied by an input or receipt."""
    require(name in ('metadata_continuation','hdf5_observer'),'Unregistered observer implementation')
    spec=importlib.util.spec_from_file_location('geometry_evaluator_'+name,str(HERE/(name+'.py')))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

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
    active_mesh=context.get('schema')==ACTIVE_HDF5_CONTEXT
    hdf5=context.get('schema') in (HDF5_CONTEXT,ACTIVE_HDF5_CONTEXT)
    require(hdf5 or context.get('schema')=='s2-geometry-observation-context-r1','Observation context schema differs')
    if hdf5:
        require(not synthetic and context.get('geometry_observation_backend')==HDF5_BACKEND
            and context.get('inherited_step_indices')==[1,2,3] and context.get('actual_geometry_step_indices')==[5],
            'HDF5 observation scope/origin differs')
    else:
        require(context.get('geometry_observation_backend','native_dfise')=='native_dfise',
                'Legacy same-run context cannot select another observation backend')
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
    exit_keys=('sde_exit_code','mesh_exit_code','tdx_metadata_exit_code','svisual_exit_code') if hdf5 else (
        'sde_exit_code','mesh_exit_code','tdx_metadata_exit_code','tdx_converter_exit_code','svisual_exit_code')
    require(not hdf5 or set(context.get('raw_exit_sha256',{}))=={k.replace('_','-')+'.txt' for k in exit_keys},
            'HDF5 scope cannot declare current converter/prefix exits')
    for key in exit_keys:
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
    metadata=obj(raw/'tdr-region-status.json')
    metadata_mesh_sha=context.get('origin_mesh_sha256') if active_mesh else mesh_sha
    require(metadata.get('schema')=='dram-see-v4-tdr-region-observation-r2' and metadata.get('completed') is True
            and metadata.get('conversion_performed') is False and metadata.get('source_modified') is False
            and metadata.get('original_mesh_sha256')==metadata_mesh_sha,'TDX metadata observation incomplete or changed mesh')
    if hdf5:
        cfg=obj(raw/'project.json')['s2_geometry']
        module=sibling('metadata_continuation');binding=module.verify_folder(raw,cfg)
        require(context.get('metadata_source_binding_sha256')==sha(raw/'metadata-source-binding.json')
            ==cfg.get('metadata_source_binding_sha256') and binding['mesh_sha256']==mesh_sha
            and cfg.get('run_id')==cfg.get('producer_run_id')==context['producer_run_id'],
            'HDF5/current producer source graph differs')
        if active_mesh:
            verify_active_context_identity(context,binding,cfg,mesh_sha)
        else:
            require(binding.get('schema')==module.SCHEMA and 'mesh_representation' not in context,
                    'Original HDF5 context cannot select active representation')
        for phase in ('BEFORE','AFTER'):
            interval=obj(raw/('current-mesh-'+phase.lower()+'.json'))
            require(interval==dict(schema='dram-see-v4-current-mesh-integrity-r1',phase=phase,
                run_id=context['producer_run_id'],path=observations['BEFORE']['path'],sha256=mesh_sha),
                'Actual current mesh identity interval differs')
        return context,mesh_sha
    identities=unique(csv_rows(raw/'tdr-topology-identity.csv',['phase','path','sha256']),'phase')
    require(set(identities)=={'BEFORE','AFTER'},'Missing original TDX metadata before/after hash')
    for phase in ('BEFORE','AFTER'):
        row=identities[phase]
        interval=obj(raw/('tdx-source-'+phase.lower()+'.json'))
        require(row['sha256']==mesh_sha and row['path']==observations['BEFORE']['path']
                and interval.get('schema')=='dram-see-v4-tdx-source-identity-r1' and interval.get('phase')==phase
                and interval.get('run_id')==context['producer_run_id'] and interval.get('sha256')==mesh_sha
                and interval.get('path')==row['path'],'Original TDX source/interval hash or identity differs')
    return context,mesh_sha


def verify_active_context_identity(context,binding,cfg,mesh_sha):
    require(binding.get('schema')=='dram-see-v4-metadata-hdf5-source-binding-r2'
        and context.get('schema')==ACTIVE_HDF5_CONTEXT
        and context.get('mesh_representation')==cfg.get('mesh_representation')==binding.get('mesh_representation')==ACTIVE_REPRESENTATION
        and context.get('origin_mesh_sha256')==cfg.get('origin_mesh_sha256')==binding.get('origin_mesh_sha256')
        and context.get('active_solver_mesh_sha256')==cfg.get('active_solver_mesh_sha256')==binding.get('active_solver_mesh_sha256')
        ==context.get('mesh_sha256')==binding.get('mesh_sha256')==mesh_sha
        and binding['origin_mesh_sha256']!=mesh_sha,'Active context confused original and actual solver mesh identities')

def verify_execution_context(raw,plan_path,plan,context,execution_context_path):
    require(execution_context_path is not None,'Current execution context missing')
    execution=obj(execution_context_path)
    require(execution.get('schema')=='dram-see-v4-continuous-run-context-r1' and
            execution.get('synthetic') is False,'Wrong current execution context')
    for key,value in (('role_id',plan['role_id']),('producer_run_id',context['producer_run_id']),
                      ('run_id',context['producer_run_id'])):
        require(execution.get(key)==value,'Execution identity differs: '+key)
    require(execution.get('input_manifest_sha256')==sha(raw/'input-manifest.json'),
            'Execution input manifest differs')
    manifest=obj(raw/'input-manifest.json')
    require(manifest.get('schema')=='dram-see-v4-continuous-inputs-r1','Wrong input manifest')
    hashes=manifest.get('files_sha256',{})
    implementations=('metadata_continuation.py','mesh_continuation.py','hdf5_observer.py','tdx_hash_sha256.tcl','measure-geometry.tcl') if context.get('schema') in (HDF5_CONTEXT,ACTIVE_HDF5_CONTEXT) else (
        'dfise_observer.py','observe_tdr_topology.tcl')
    for name in ('evaluate.py','measurement-plan.json','geometry-contract.json','task-authorization.json')+implementations:
        require(hashes.get(name)==sha(raw/name),'Evaluator input differs: '+name)
    authority=obj(raw/'task-authorization.json')
    require(execution.get('authorization_sha256')==sha(raw/'task-authorization.json') and
            authority.get('schema')=='dram-see-v4-current-user-authorization-r1' and
            authority.get('source')=='current_user_instruction' and authority.get('synthetic') is False and
            plan['role_id'] in authority.get('role_ids',[]),'Current task authorization differs')

def verify_contact_bounds_coverage(plan):
    """Require actual mesh coordinate coverage after the unsupported CAD bbox path.

The source plan's expected values and tolerances are retained. These checks do
not produce observations; they ensure each needed original-mesh measurement
remains mandatory and names the correct contact region.
"""
    g=plan['expected_geometry']; d=plan['dimension']; policy=plan['comparison_policy']
    measured={m['id']:m for m in plan['measurements'] if m['category']=='contacts'}
    required=set()
    for contact in g['contacts']:
        for axis,limits in zip('XYZ'[:d],bounds(g,contact)[:d]):
            for operation,expected in zip(('min','max'),limits):
                name='contact.'+contact['name']+'.'+axis+'.'+operation
                required.add(name)
                item=measured.get(name,{})
                require(item.get('field')==axis and item.get('entity_kind')=='region'
                        and item.get('entity')==contact['name'] and item.get('operation')==operation
                        and item.get('unit')=='um' and item.get('expected')==expected
                        and item.get('absolute_tolerance')==policy['coordinate_absolute_um']
                        and item.get('relative_tolerance')==0.,'Native mesh contact bounds missing/changed: '+name)
    require(set(measured)==required,'Native mesh contact bound coverage differs')

def verify_region_material_inventory(g,inventory):
    """Interface metadata must name two distinct declared physical regions.

The D3 contract also contains the two STI bodies; they remain physical bodies,
and each observed interface must resolve to a pair in that exact inventory.
"""
    def names(kind):return {r['name'] for r in inventory if r['kind']==kind}
    physical_regions={r['name'] for r in g['regions']}
    interfaces={(r['name'],r['parent']) for r in inventory if r['kind']=='region' and r['parent']=='Interface'}
    if interfaces:
        pairs=set()
        for interface_name,unused in interfaces:
            pair=interface_name.split('+')
            require(len(pair)==2 and len(set(pair))==2 and set(pair)<=physical_regions,
                    'Interface metadata is not between declared physical regions')
            require(frozenset(pair) not in pairs,'Duplicate physical interface metadata')
            pairs.add(frozenset(pair))
    materials={r['material'] for r in g['regions']}|{'Contact'}|({'Interface'} if interfaces else set())
    require(names('material')==materials,'Actual material inventory differs')
    require(names('contact')=={c['name'] for c in g['contacts']},'Actual mesh contacts differ')
    expected={(r['name'],r['material']) for r in g['regions']}|{(c['name'],'Contact') for c in g['contacts']}|interfaces
    require({(r['name'],r['parent']) for r in inventory if r['kind']=='region'}==expected,
            'Actual mesh region/material mapping differs')
    require(all(r['parent']=='Contact' for r in inventory if r['kind']=='contact'),'Contact material mapping differs')

def compare(plan,raw,backend='native_dfise'):
    g=plan['expected_geometry'];policy=plan['comparison_policy'];d=plan['dimension'];details=[]
    require(g.get('dimension')==d and g.get('length_unit')=='um' and
            g.get('measure_unit')==('um^2' if d==2 else 'um^3'),'Geometry dimension/unit contract differs')
    checks=dict(materials=True,contacts=True,doping=True,units=True)
    verify_contact_bounds_coverage(plan)
    require(backend in ('native_dfise',HDF5_BACKEND),'Unknown native geometry backend')
    hdf5=backend==HDF5_BACKEND
    mesh_observations,mesh_audit=(sibling('hdf5_observer') if hdf5 else dfise_observer).observe(plan,raw)
    inventory=csv_rows(raw/'geometry-inventory.csv',['kind','name','parent'])
    require(len({(r['kind'],r['name'],r['parent']) for r in inventory})==len(inventory),'Duplicate geometry inventory')
    def names(kind):return {r['name'] for r in inventory if r['kind']==kind}
    verify_region_material_inventory(g,inventory)
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
            mesh=mesh_observations.get(item['id'])
            value=mesh['value'] if mesh else raw_number(row['raw_value'],d)
            passed=close(value,item['expected'],item['absolute_tolerance'],item['relative_tolerance'])
            if category=='doping':passed=passed and value>=0
            checks[item['category']]=checks[item['category']] and passed
            details.append(dict(id=item['id'],raw_value=row['raw_value'],observed=value,expected=item['expected'],
                                unit=item['unit'],passed=passed,
                                observation_source=mesh['source'] if mesh else 'native_svisual',
                                original_svisual_raw_retained=bool(mesh)))
    contacts=unique(csv_rows(raw/'sde-contact-measurements.csv',
        ['contact','entity_count','measure','unit']),'contact')
    require(set(contacts)=={c['name'] for c in g['contacts']},'Actual CAD contacts differ')
    for c in g['contacts']:
        row=contacts[c['name']]; require(re.fullmatch(r'[1-9]\d*',row['entity_count']) is not None,'Empty/invalid contact entity count')
        count=int(row['entity_count']);count_ok=(count>=(4 if d==2 else 6)) if c['name']=='gate' else count==1
        value=number(row['measure']);expect=c['measure']
        passed=(count_ok and value>0 and row['unit']==c['measure_unit'] and
                close(value,expect,policy['contact_absolute'],policy['contact_relative']))
        checks['contacts']=checks['contacts'] and passed
        details.append(dict(id='cad.contact.'+c['name'],observed=value,expected=expect,unit=c['measure_unit'],passed=passed,
                            bounds_observation=('actual native HDF5 contact vertices; original SVisual rows retained' if hdf5 else
                                'actual DF-ISE Contact element vertex extrema; original SVisual rows retained')))
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
    details.append(dict(id='native.hdf5.topology-and-fields' if hdf5 else 'native.dfise.topology-and-fields',passed=True,audit=mesh_audit))
    return checks,details

def evaluate(plan_path,raw_directory,output_directory,synthetic=False,execution_context_path=None):
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
        if context.get('schema')==ACTIVE_HDF5_CONTEXT:
            report.update({n:context[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')})
        backend=context.get('geometry_observation_backend','native_dfise')
        raw_files=set(HDF5_RAW_FILES if backend==HDF5_BACKEND else RAW_FILES)
        if backend==HDF5_BACKEND:
            module=sibling('metadata_continuation')
            raw_files.update(module.evidence_hashes(module.FolderReader(raw)))
            report['geometry_observation_backend']=backend
        before={name:sha(raw/name) for name in sorted(raw_files)}
        numeric,details=compare(plan,raw,backend)
        report['numeric_checks']=numeric;report['comparisons']=details
        if not synthetic:verify_execution_context(raw,plan_path,plan,context,execution_context_path)
        require(before=={name:sha(raw/name) for name in raw_files} and sha(raw/'cell_msh.tdr')==mesh_sha,
                'Original measurements/mesh changed during comparison')
        report['checks']=numeric;report['evidence_sha256']=before
        report['passed']=all(numeric.values())
        if not report['passed']:report['errors'].append('Declared geometry comparisons failed')
        report['current_context_verified']=not synthetic
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError,OSError,csv.Error) as exc:
        report['errors'].append(str(exc))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'geometry-validation.json').open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True);parser.add_argument('--observations',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--execution-context')
    parser.add_argument('--synthetic-fixture',action='store_true')
    a=parser.parse_args();r=evaluate(a.plan,a.observations,a.output,a.synthetic_fixture,a.execution_context)
    print(json.dumps(dict(passed=r['passed'],synthetic=r['synthetic'],native_qualified=False,errors=r['errors'])))
    return 0 if r['passed'] else 2

if __name__=='__main__':raise SystemExit(main())
