"""Build only frozen A0/A1 bit1 mesh observers. No solver, SSH or scheduler."""
import argparse
import difflib
import importlib.util
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CONTRACT=HERE/'source_contract.json'
OUTPUT_ROOT=ROOT/'local_runtime/dram-see-v4/source-interface-r4'
R2=ROOT/'experiments/dram-see-v4/source-interface-r2'
R3=ROOT/'experiments/dram-see-v4/source-interface-r3'
R2_INPUTS=ROOT/'local_runtime/dram-see-v4/source-interface-r2/inputs'
DYNAMIC_PLOT='Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)'


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
    return m


r2=module(R2/'build_interface.py','_r4_frozen_r2')
r3=module(R3/'build_interface.py','_r4_frozen_r3')
read_json,encoded,number,sha=r2.read_json,r2.encoded,r2.number,r2.sha


def contract():
    c=read_json(CONTRACT)
    if c.get('schema')!='dram-see-v4-source-interface-r4-contract' or c.get('revision')!=4:
        raise ValueError('Wrong r4 contract')
    for parent,stem in [(R2,'r2'),(R3,'r3')]:
        names=[('build_interface.py','builder'),('source_contract.json','contract')]
        names += [('audit_interface.py','auditor')] if stem=='r2' else [('oracle.py','oracle')]
        for name,label in names:
            if sha((parent/name).read_bytes())!=c['frozen_references'][stem+'_'+label+'_sha256']:
                raise ValueError('Frozen dependency changed: '+str(parent/name))
    if c['audit_tolerances']!=r3.contract()['audit_tolerances']:
        raise ValueError('Numerical gates cannot change in r4')
    if c['candidate_roles']!=[['A0',1,'mesh'],['A1',1,'mesh']] or c['global_budget']['maximum_tcad_attempts']!=19:
        raise ValueError('Only the two preplanned mesh diagnostics share global 19')
    if c['measurement']['dynamic_plot_command']!=DYNAMIC_PLOT or c['measurement']['window_can_pass_acceptance'] is not False:
        raise ValueError('Unexpected output/measurement route')
    return c


def check_role(case,bit=1,variant='mesh'):
    if type(bit) is not int or [case,bit,variant] not in contract()['candidate_roles']:
        raise ValueError('Only A0/A1 bit1 mesh candidates are authorized')


def source_spec(case):
    check_role(case)
    return r2.make_spec(case)


def current_plot(case):
    check_role(case)
    # A0 integrals remain requested, but zero generation has no defined centroid.
    return r3.current_plot().replace(' Coordinates','') if case=='A0' else r3.current_plot()


def render_deck(case):
    deck=r2.render_deck(source_spec(case),1,'mesh')
    start=deck.index('CurrentPlot { HeavyIonGeneration(');end=deck.index('\nMath {',start)
    deck=deck[:start]+current_plot(case)+deck[end:]
    anchor='Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="gfield_0"'
    if deck.count(anchor)!=1:
        raise ValueError('Injection output anchor changed')
    return deck.replace(anchor,'Coupled {Poisson Electron Hole Contact Circuit}\n '+DYNAMIC_PLOT+'\n Plot(FilePrefix="gfield_0"',1)


def strip_r4_observers(deck,case):
    """Reconstruct the exact r2 mesh deck, never merely remove physical lines."""
    expected=current_plot(case)
    original=r2.render_deck(source_spec(case),1,'mesh')
    start=original.index('CurrentPlot { HeavyIonGeneration(');end=original.index('\nMath {',start)
    if deck.count(expected)!=1 or deck.count(DYNAMIC_PLOT)!=1:
        raise ValueError('Observer block missing/duplicated')
    deck=deck.replace(expected,original[start:end],1)
    injected='Coupled {Poisson Electron Hole Contact Circuit}\n '+DYNAMIC_PLOT+'\n Plot(FilePrefix="gfield_0"'
    if deck.count(injected)!=1:raise ValueError('Dynamic plot outside the intended injection block')
    return deck.replace(injected,'Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="gfield_0"',1)


def code_hashes():
    paths=[Path(__file__),CONTRACT,R2/'build_interface.py',R2/'source_contract.json',R2/'audit_interface.py',
           R3/'build_interface.py',R3/'source_contract.json',R3/'oracle.py',
           R3/'diagnostics/tdr-fallback-design.md',ROOT/'scripts/tcad.py',
           ROOT/'experiments/dram-see-v3/r50-main/build_case.py',ROOT/'experiments/dram-see-v1/build_case.py',
           ROOT/'local_runtime/dram-see-v1/heavyion-reference.txt']
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}


def references(case,reference):
    check_role(case)
    reference=Path(reference).resolve()
    wanted=(R2_INPUTS/('v4-source-interface-r2-'+case.lower()+'-b1-mesh')).resolve()
    if reference!=wanted:raise ValueError('Require the explicitly authorized corresponding new r2 mesh reference')
    r2.check_project(reference)
    base=R2_INPUTS/('v4-source-interface-r2-'+case.lower()+'-b1-base')
    r2.check_project(base)
    p=read_json(reference/'parameters.json');old=read_json(base/'parameters.json')
    if [p['case_id'],p['stored_bit'],p['variant']]!=[case,1,'mesh']:
        raise ValueError('Physical reference case/bit/variant differs')
    differences={k:{'base':old['matching_contract'].get(k),'mesh':v} for k,v in p['matching_contract'].items()
                 if old['matching_contract'].get(k)!=v}
    if set(differences)!={'geometry_sha256','mesh_scale','variant'}:
        raise ValueError('Mesh variant changed additional circuit/source/time parameters')
    if p['mesh_scale']!=.5 or p['pulse_max_step_s']!=5e-13:
        raise ValueError('Frozen mesh/time setting differs')
    for name in ['device.cmd','heavyion.par','source-spec.json']:
        if (reference/name).read_bytes()!=(base/name).read_bytes():
            raise ValueError('Mesh reference altered source/circuit/deck: '+name)
    return reference,base,p,old,differences


def physical_diff(case,reference):
    ref,base,p,old,differences=references(case,reference)
    geometry_diff=''.join(difflib.unified_diff((base/'geometry.scm').read_text().splitlines(True),
        (ref/'geometry.scm').read_text().splitlines(True),fromfile='r2-base/geometry.scm',tofile='r2-mesh/geometry.scm'))
    return {'schema':'dram-see-v4-source-interface-r4-physical-diff','case_id':case,
        'base_project':base.relative_to(ROOT).as_posix(),'mesh_reference_project':ref.relative_to(ROOT).as_posix(),
        'base_manifest_sha256':sha((base/'input-manifest.json').read_bytes()),
        'mesh_manifest_sha256':sha((ref/'input-manifest.json').read_bytes()),'physical_parameter_differences':differences,
        'mesh_geometry_diff':geometry_diff,'source_and_r2_device_deck_byte_identical_to_base':True,
        'r4_observer_changes':['retain r3 diagnostic integrals; omit A0 undefined Coordinates',DYNAMIC_PLOT],
        'observer_stripped_deck_equals_r2_mesh':strip_r4_observers(render_deck(case),case)==(ref/'device.cmd').read_text(),
        'new_forced_time_points':False,'existing_five_gfield_time_points_retained':True,
        'promotes_prior_failed_base_to_pass':False,'changes_main_mesh_for_other_cases':False,'solver_started':False}


def build(output,case,reference_project):
    check_role(case)
    reference,base,p,old,differences=references(case,reference_project)
    out=Path(output).resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out==OUTPUT_ROOT.resolve() or out.exists():
        raise ValueError('Use a new child directory under r4 runtime; never overwrite')
    if not re.fullmatch('v4-source-interface-r4-'+case.lower()+r'-b1-mesh(?:-[a-z0-9_-]+)?',out.name):
        raise ValueError('Output name must bind r4, case, bit1 and mesh')
    proof=r3.offline_proof(source_spec(case));proof['schema']='dram-see-v4-source-interface-r4-offline'
    p.update(schema='dram-see-v4-source-interface-r4',measurement_revision=4,
             source_contract_sha256=sha(CONTRACT.read_bytes()),source_code_sha256=code_hashes(),
             r2_reference_project=reference.relative_to(ROOT).as_posix(),
             r2_reference_manifest_sha256=sha((reference/'input-manifest.json').read_bytes()))
    project=read_json(reference/'project.json');project['name']=out.name
    files={name:(reference/name).read_bytes() for name in ['geometry.scm','heavyion.par','source-spec.json']}
    files.update({'device.cmd':render_deck(case).encode(),'parameters.json':encoded(p),'project.json':encoded(project),
        'source-contract.json':CONTRACT.read_bytes(),'offline-source-check.json':encoded(proof),
        'physical-diff.json':encoded(physical_diff(case,reference)),
        'r2-reference-device.cmd':(reference/'device.cmd').read_bytes(),
        'r2-reference-parameters.json':(reference/'parameters.json').read_bytes(),
        'r2-reference-input-manifest.json':(reference/'input-manifest.json').read_bytes()})
    manifest={'schema':'dram-see-v4-source-interface-r4-inputs','case_id':case,'stored_bit':1,'variant':'mesh',
        'files_sha256':{name:sha(data) for name,data in files.items()},'source_code_sha256':code_hashes(),'solver_started':False,
        'budget':'One shared global 19 attempts, 3 already used at r4 freeze; root alone schedules/counts attempts',
        'dynamic_outputs':'Original full-project tar retains dynamic gstep files; fixed outputs are not all-frame completeness evidence'}
    out.mkdir(parents=True)
    for name,data in {**files,'input-manifest.json':encoded(manifest)}.items():
        with (out/name).open('xb') as stream:stream.write(data)
    return check_project(out)


def check_project(project):
    contract();folder=Path(project).resolve()
    if not folder.is_relative_to(OUTPUT_ROOT.resolve()) or folder==OUTPUT_ROOT.resolve():raise ValueError('Not an r4 candidate')
    m=read_json(folder/'input-manifest.json');p=read_json(folder/'parameters.json')
    case=p['case_id'];check_role(case,p['stored_bit'],p['variant'])
    if {x.name for x in folder.iterdir()}!=set(m['files_sha256'])|{'input-manifest.json'}:raise ValueError('Input file inventory differs')
    for name,digest in m['files_sha256'].items():
        if '/' in name or '\\' in name or (folder/name).is_symlink() or sha((folder/name).read_bytes())!=digest:
            raise ValueError('Input file/hash differs: '+name)
    if m['source_code_sha256']!=code_hashes() or p['source_code_sha256']!=code_hashes():raise ValueError('Frozen source dependencies changed')
    ref,base,old,base_p,differences=references(case,ROOT/p['r2_reference_project'])
    if p['matching_contract_sha256']!=old['matching_contract_sha256'] or p['matching_contract']!=old['matching_contract']:
        raise ValueError('Physical matching contract changed from r2 mesh')
    if any(p[k]!=v for k,v in p['matching_contract'].items()):raise ValueError('Physical parameters conflict')
    for name in ['geometry.scm','heavyion.par','source-spec.json']:
        if (folder/name).read_bytes()!=(ref/name).read_bytes():raise ValueError('Physical source/device changed: '+name)
    deck=(folder/'device.cmd').read_text()
    if deck!=render_deck(case) or strip_r4_observers(deck,case)!=(ref/'device.cmd').read_text():raise ValueError('Observer/physical deck differs')
    for original,saved in [('device.cmd','r2-reference-device.cmd'),('parameters.json','r2-reference-parameters.json'),('input-manifest.json','r2-reference-input-manifest.json')]:
        if (folder/saved).read_bytes()!=(ref/original).read_bytes():raise ValueError('Reference evidence changed')
    if (folder/'source-contract.json').read_bytes()!=CONTRACT.read_bytes() or p['source_contract_sha256']!=sha(CONTRACT.read_bytes()):raise ValueError('Contract changed')
    if p['r2_reference_manifest_sha256']!=sha((ref/'input-manifest.json').read_bytes()):raise ValueError('Reference hash differs')
    if read_json(folder/'physical-diff.json')!=physical_diff(case,ref):raise ValueError('Physical difference evidence differs')
    project_data=read_json(folder/'project.json');expected=read_json(ref/'project.json');expected['name']=folder.name
    if project_data!=expected:raise ValueError('Fixed project output/runner steps changed')
    return {'status':'OFFLINE_INPUT_CHECK_PASSED','solver_started':False,'project':str(folder),'case_id':case,'stored_bit':1,'variant':'mesh',
        'measurement_revision':4,'matching_contract_sha256':p['matching_contract_sha256'],'manifest_sha256':sha((folder/'input-manifest.json').read_bytes()),
        'global_budget_limit':19,'prior_attempts_at_revision_freeze':3,'new_budget_created':False,
        'dynamic_frames_require_separate_native_audit':True,'prior_failures_promoted':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('output',type=Path);b.add_argument('--case',required=True,choices=['A0','A1']);b.add_argument('--reference-project',required=True,type=Path)
    k=sub.add_parser('check');k.add_argument('project',type=Path)
    sub.add_parser('plan');args=p.parse_args()
    if args.command=='build':result=build(args.output,args.case,args.reference_project)
    elif args.command=='check':result=check_project(args.project)
    else:result={'candidate_roles':contract()['candidate_roles'],'global_budget':contract()['global_budget'],'solver_started':False}
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
