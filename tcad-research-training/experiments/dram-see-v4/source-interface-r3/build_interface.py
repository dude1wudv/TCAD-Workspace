"""Immutable A1-only measurement revision; no runner and no budget reset."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CONTRACT=HERE/'source_contract.json'
OUTPUT_ROOT=ROOT/'local_runtime/dram-see-v4/source-interface-r3'
R2=ROOT/'experiments/dram-see-v4/source-interface-r2'


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
    return m


r2=module(R2/'build_interface.py','_r3_frozen_r2_builder')
oracle=module(HERE/'oracle.py','_r3_build_oracle')
read_json,encoded,number,sha=r2.read_json,r2.encoded,r2.number,r2.sha


def contract():
    c=read_json(CONTRACT)
    if c['schema']!='dram-see-v4-source-interface-r3-contract' or c['revision']!=3:
        raise ValueError('Wrong r3 contract')
    ref=c['frozen_references']
    for file,key in [('build_interface.py','r2_builder_sha256'),('source_contract.json','r2_contract_sha256'),('audit_interface.py','r2_auditor_sha256')]:
        if sha((R2/file).read_bytes())!=ref[key]:
            raise ValueError('Frozen r2 dependency changed: '+file)
    return c


def source_spec():
    return r2.make_spec('A1')  # Same artificial physical event, new measurement attempt.


def offline_proof(spec):
    proof=r2.offline_check(spec)
    # Reuse only the frozen spatial quadrature; its old time expression is not r3 evidence.
    proof.pop('time_window_outside_fraction_upper_bound')
    proof.update(schema='dram-see-v4-source-interface-r3-offline',
                 time_kernel='UG p813 Eq810 sigma=s_hi; offline output is not measured data',
                 temporal_mass_0_to_4ns_by_source={t['source_name']:oracle.mass(0.,4e-9,t['time_s'],t['s_hi_s']) for t in spec['tracks']})
    return proof


def current_plot():
    c=contract()
    lines=['CurrentPlot {',' HeavyIonGeneration(',
           '  Integrate(Semiconductor)',
           '  Integrate(Name="G_Plain" Semiconductor Coordinates)',
           '  Integrate(Name="G_2DTotal" Semiconductor Window[(0 0) (0.85 1.2)])']
    for roi,(x0,y0,x1,y1) in c['rois_um'].items():
        coords=' Coordinates' if roi=='Total' else ''
        lines.append('  Integrate(Name="G_'+roi+'" Semiconductor Window[('+number(x0)+' '+number(y0)+' -0.5) ('+number(x1)+' '+number(y1)+' 0.5)]'+coords+')')
    lines+=[' )',' Temperature(','  Integrate(Name="Area_Plain" Semiconductor)',
            '  Integrate(Name="Area_2DTotal" Semiconductor Window[(0 0) (0.85 1.2)])']
    for roi,(x0,y0,x1,y1) in c['rois_um'].items():
        lines.append('  Integrate(Name="Area_'+roi+'" Semiconductor Window[('+number(x0)+' '+number(y0)+' -0.5) ('+number(x1)+' '+number(y1)+' 0.5)])')
    return '\n'.join(lines+[' )','}'])


def render_deck():
    deck=r2.render_deck(source_spec(),1,'base')
    start=deck.index('CurrentPlot { HeavyIonGeneration(')
    end=deck.index('\nMath {',start)
    return deck[:start]+current_plot()+deck[end:]


def code_hashes():
    paths=[Path(__file__),CONTRACT,HERE/'oracle.py',R2/'build_interface.py',R2/'source_contract.json',
           R2/'audit_interface.py',ROOT/'scripts/tcad.py',ROOT/'experiments/dram-see-v3/r50-main/build_case.py']
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}


def build(output,reference_project):
    contract()
    reference=Path(reference_project).resolve()
    r2.check_project(reference)
    p=read_json(reference/'parameters.json')
    if [p['case_id'],p['stored_bit'],p['variant']]!=['A1',1,'base']:
        raise ValueError('Reference must be frozen r2 A1 bit1 base, not a claimed passed source audit')
    out=Path(output).resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out==OUTPUT_ROOT.resolve() or out.exists():
        raise ValueError('Use a new child project under source-interface-r3 runtime')
    if not re.fullmatch(r'v4-source-interface-r3-a1-b1-base(?:-[a-z0-9_-]+)?',out.name):
        raise ValueError('Only an explicit r3 A1 candidate may be built')
    copied=['geometry.scm','heavyion.par','source-spec.json']
    files={name:(reference/name).read_bytes() for name in copied}
    proof=offline_proof(source_spec())
    p.update(schema='dram-see-v4-source-interface-r3',measurement_revision=3,
             source_contract_sha256=sha(CONTRACT.read_bytes()),source_code_sha256=code_hashes(),
             r2_reference_project=reference.relative_to(ROOT).as_posix(),
             r2_reference_manifest_sha256=sha((reference/'input-manifest.json').read_bytes()))
    project=read_json(reference/'project.json');project['name']=out.name
    files.update({'device.cmd':render_deck().encode(),'parameters.json':encoded(p),'project.json':encoded(project),
                  'source-contract.json':CONTRACT.read_bytes(),'offline-source-check.json':encoded(proof),
                  'r2-reference-device.cmd':(reference/'device.cmd').read_bytes(),
                  'r2-reference-parameters.json':(reference/'parameters.json').read_bytes(),
                  'r2-reference-input-manifest.json':(reference/'input-manifest.json').read_bytes()})
    m={'schema':'dram-see-v4-source-interface-r3-inputs','case_id':'A1','stored_bit':1,'variant':'base',
       'files_sha256':{name:sha(raw) for name,raw in files.items()},'source_code_sha256':code_hashes(),'solver_started':False,
       'budget':'Shared global 19 attempts with r2; root scheduler alone enforces remaining budget'}
    out.mkdir(parents=True)
    for name,raw in {**files,'input-manifest.json':encoded(m)}.items():
        with (out/name).open('xb') as stream:stream.write(raw)
    return check_project(out)


def check_project(project):
    contract();folder=Path(project).resolve()
    if not folder.is_relative_to(OUTPUT_ROOT.resolve()) or folder==OUTPUT_ROOT.resolve():
        raise ValueError('Not an r3 candidate directory')
    m=read_json(folder/'input-manifest.json');p=read_json(folder/'parameters.json')
    if {x.name for x in folder.iterdir()}!=set(m['files_sha256'])|{'input-manifest.json'}:
        raise ValueError('Input inventory differs')
    for name,digest in m['files_sha256'].items():
        if '/' in name or '\\' in name or (folder/name).is_symlink() or sha((folder/name).read_bytes())!=digest:
            raise ValueError('Input file/hash differs: '+name)
    if m['source_code_sha256']!=code_hashes() or p['source_code_sha256']!=code_hashes():
        raise ValueError('Source dependencies changed')
    if (folder/'source-contract.json').read_bytes()!=CONTRACT.read_bytes() or (folder/'device.cmd').read_text()!=render_deck():
        raise ValueError('Frozen observer/deck differs')
    ref=ROOT/p['r2_reference_project'];r2.check_project(ref)
    old=read_json(ref/'parameters.json')
    if p['matching_contract_sha256']!=old['matching_contract_sha256'] or encoded(p['matching_contract'])!=encoded(old['matching_contract']):
        raise ValueError('Physical matching contract must be exactly unchanged')
    if any(p[k]!=v for k,v in p['matching_contract'].items()):
        raise ValueError('Physical parameters conflict')
    for name in ['geometry.scm','heavyion.par','source-spec.json']:
        if (folder/name).read_bytes()!=(ref/name).read_bytes():raise ValueError('Physical source/device changed: '+name)
    for original,saved in [('device.cmd','r2-reference-device.cmd'),('parameters.json','r2-reference-parameters.json'),('input-manifest.json','r2-reference-input-manifest.json')]:
        if (folder/saved).read_bytes()!=(ref/original).read_bytes():raise ValueError('Reference evidence differs')
    if p['source_contract_sha256']!=sha(CONTRACT.read_bytes()) or p['r2_reference_manifest_sha256']!=sha((ref/'input-manifest.json').read_bytes()):
        raise ValueError('Reference/source hash differs')
    return {'status':'OFFLINE_INPUT_CHECK_PASSED','solver_started':False,'project':str(folder),'case_id':'A1','stored_bit':1,'variant':'base',
            'measurement_revision':3,'matching_contract_sha256':p['matching_contract_sha256'],'manifest_sha256':sha((folder/'input-manifest.json').read_bytes()),
            'global_budget_limit':19,'new_budget_created':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('output',type=Path);b.add_argument('--reference-project',type=Path,required=True)
    k=s.add_parser('check');k.add_argument('project',type=Path)
    args=p.parse_args();result=build(args.output,args.reference_project) if args.command=='build' else check_project(args.project)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
