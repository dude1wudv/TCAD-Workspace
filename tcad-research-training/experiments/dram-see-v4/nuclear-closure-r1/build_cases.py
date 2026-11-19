"""Generate immutable 3D PMI cases; never invoke a solver or remote operation.

Geometry/doping/circuit derive from the explicitly hashed prior 3D representative
cell. This revision freezes a selected-event mesh and native nested time points.
The generated Python 3.6 mesh guard only reads native mesh/resource facts.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

HERE, ROOT, RT = c.HERE, c.ROOT, c.RT
QUAL_BOX = [[-.09, -.09, -.09], [.09, .09, .09]]
DEVICE_BOX = [[0., 0., -.5], [.85, 1.2, .5]]
OLD_SOURCE = HERE.parent / 'source-interface-3d-r1/source_contract.json'
OLD_DECK = ROOT / 'local_runtime/dram-see-v4/source-interface-r5/inputs/v4-source-interface-r5-a0-b1-main/device.cmd'
DEPENDENCIES = {
    'experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json': '3fb882383484e35445192b23169981d0061b650b06c64f132d1fb4ba63fd755d',
    'local_runtime/dram-see-v4/source-interface-r5/inputs/v4-source-interface-r5-a0-b1-main/device.cmd': 'da11dfc2b3cc092dd414a1d35d27c092f64154a1f15e01fcc9149df83479ebca',
}
FS = 1e-15
EPS_TIME = 1e-18


def kernel():
    import source_kernel
    return source_kernel


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else c.encoded(value)).hexdigest()


def number(value):
    c.require(type(value) in (int, float) and math.isfinite(value), 'Nonfinite numeric input')
    return format(value, '.17g')


def dependencies():
    for path, sha in DEPENDENCIES.items():
        c.require(c.sha(ROOT/path) == sha, 'Frozen device dependency changed: '+path)
    c.require(c.contract()['geometry']['sha256'] == c.sha(c.GEOMETRY), 'Shared geometry differs')
    return dict(DEPENDENCIES)


def source(steps, role):
    return kernel().canonical_source(dict(schema='nuclear-closure-source-r1',
        geometry_sha256=c.sha(c.GEOMETRY), steps=steps,
        provenance=dict(synthetic=True, role=role)))


def step(uid, r0, r1, charge, time=1e-9, role='artificial'):
    return dict(uid=uid, r0_um=list(r0), r1_um=list(r1), t0_s=time, t1_s=time,
                charge_fC=charge, w_um=.03, sigma_s=2e-12,
                kind='point' if list(r0)==list(r1) else 'segment',
                provenance=dict(synthetic=True, role=role))


def artificial_source(role):
    line0, line1 = [.425,.3,.05], [.55,.85,.15]
    if role in ('qualification-zero',) or role.startswith('a0-'):
        steps=[]
    elif role=='qualification-point':
        steps=[step('qualification-point', [0,0,0], [0,0,0], .01, role=role)]
    elif role=='artificial-line':
        steps=[step('artificial-line', line0, line1, 1., role=role)]
    elif role=='artificial-point':
        steps=[step('artificial-point', [.425,.6,-.12], [.425,.6,-.12], 1., role=role)]
    elif role in ('artificial-mixed','artificial-segmented'):
        steps=[step('mixed-point', [.02,.6,-.12], [.02,.6,-.12], .5, 1.01e-9, role='mixed')]
        if role=='artificial-mixed':
            steps.append(step('mixed-line', line0, line1, .5, role='mixed'))
        else:
            middle=[(a+b)/2 for a,b in zip(line0,line1)]
            steps += [step('mixed-line-a',line0,middle,.25,role='segmented'),
                      step('mixed-line-b',middle,line1,.25,role='segmented')]
    else:
        raise ValueError('Unknown artificial/zero role: '+role)
    return source(steps,role)


def merged_windows(sources):
    """Outward integer-fs cover of eight-sigma windows; no source renormalization."""
    spans=[]
    for value in sources:
        for item in kernel().canonical_source(value)['steps']:
            if item['charge_fC']<=0: continue
            lo=math.floor((min(item['t0_s'],item['t1_s'])-8*item['sigma_s'])/FS)
            hi=math.ceil((max(item['t0_s'],item['t1_s'])+8*item['sigma_s'])/FS)
            lo,hi=max(0,lo),min(4000000,hi)
            if hi>lo: spans.append([lo,hi])
    merged=[]
    for lo,hi in sorted(spans):
        if merged and lo<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],hi)
        else: merged.append([lo,hi])
    return [[lo*FS,hi*FS] for lo,hi in merged]


def freeze_mesh(event_source):
    dependencies()
    event=kernel().canonical_source(event_source)
    c.require(event['steps'], 'Select a nonempty real event before the common mesh')
    c.require(event.get('provenance',{}).get('synthetic') is not True, 'Common event cannot be an artificial fixture')
    models=[event]+[artificial_source(x) for x in ('artificial-line','artificial-point','artificial-mixed','artificial-segmented')]
    positive=[s for m in models for s in m['steps'] if s['charge_fC']>0]
    low=[max(DEVICE_BOX[0][i],min(min(s['r0_um'][i],s['r1_um'][i])-4*s['w_um'] for s in positive)) for i in range(3)]
    high=[min(DEVICE_BOX[1][i],max(max(s['r0_um'][i],s['r1_um'][i])+4*s['w_um'] for s in positive)) for i in range(3)]
    c.require(all(a<b for a,b in zip(low,high)), 'Selected source support misses silicon')
    old=c.read(OLD_SOURCE)
    windows=copy.deepcopy([w for w in old['mesh']['windows'] if w['name'] in ('All','Surface','OxideInterface')])
    windows.append(dict(name='AllRegisteredSources',min_um=low,max_um=high,
                        max_size_um=[.01,.01,.01],min_size_um=[.005,.005,.005]))
    active=merged_windows(models)
    c.require(active, 'No first-readout active source window')
    return dict(schema='nuclear-closure-common-mesh-r1', geometry=c.ref(c.GEOMETRY),
                event_source_sha256=digest(event), event_source=event,
                artificial_source_sha256={r:digest(artificial_source(r)) for r in
                    ('artificial-line','artificial-point','artificial-mixed','artificial-segmented')},
                windows=windows, mesh_scales=c.contract()['numerical']['mesh_scales'],
                source_windows_s=active, source_support_margin_w=4,
                source_window_sigma=8, source_support_policy='Mesh refinement envelope only; Gaussian tails are not removed',
                clipping='No spatial or temporal renormalization', frozen_dependencies=dependencies(),
                old_mesh_contract_sha256=c.sha(OLD_SOURCE))


def qualified_mesh():
    point=artificial_source('qualification-point')
    return dict(schema='nuclear-closure-qualification-mesh-r1',geometry=c.ref(c.GEOMETRY),
                windows=[dict(name='All',min_um=QUAL_BOX[0],max_um=QUAL_BOX[1],
                              max_size_um=[.012]*3,min_size_um=[.006]*3)],
                mesh_scales={'m0':1.}, source_windows_s=merged_windows([point]))


def role_identity(role):
    c.require(role in c.contract()['primary_roles'], 'Role outside the frozen 14 primary cases')
    if role.startswith('qualification-'):return 'm0','t0',True
    if role.startswith('artificial-'):return 'm0','t0',False
    match=re.fullmatch(r'(?:a0|event)-(m[01])-(t[01])',role)
    c.require(match is not None,'Invalid matrix identity')
    return match[1],match[2],False


def time_blocks(mesh, time_key):
    scale=c.contract()['numerical']['time_scales'][time_key]
    windows=[[round(a/FS),round(b/FS)] for a,b in mesh['source_windows_s']]
    edges=sorted({0,600000,950000,1050000,2800000,3000000,4000000} | {x for w in windows for x in w})
    blocks=[]
    for index,(lo,hi) in enumerate(zip(edges,edges[1:])):
        active=any(lo>=a and hi<=b for a,b in windows)
        base=500 if active or 950000<=lo<1050000 else 1000 if 2800000<=lo<3000000 else 5000 if lo>=3000000 else 10000
        delta=int(base*scale)
        c.require(delta>0 and float(delta)==base*scale, 'Time grid is not integer fs')
        points=[x*FS for x in range(lo+delta,hi,delta)]
        blocks.append(dict(index=index,initial_s=lo*FS,final_s=hi*FS,max_step_s=delta*FS,
                           turning_points_s=points,active_source=active))
    return blocks


def pos(value):return '(position '+' '.join(number(x) for x in value)+')'


def render_geometry(mesh, mesh_key, qualification):
    dependencies();g=c.read(c.GEOMETRY);scale=mesh['mesh_scales'][mesh_key]
    lines=['; Independent nuclear-closure-r1 geometry; no solver invoked by builder.','(sde:clear)','(sdegeo:set-default-boolean "ABA")']
    if qualification:
        lines.append('(sdegeo:create-cuboid '+pos(QUAL_BOX[0])+' '+pos(QUAL_BOX[1])+' "Silicon" "R.Si")')
        contacts=[('source',[0,-.09,0]),('drain',[0,.09,0])]
    else:
        for s in g['solids']:lines.append('(sdegeo:create-cuboid '+pos(s['min_um'])+' '+pos(s['max_um'])+' "'+s['sde_material']+'" "'+s['id']+'")')
        contacts=[(p['name'],p['face_probe_um']) for p in g['contacts']]
    for name,probe in contacts:
        lines += ['(sdegeo:define-contact-set "'+name+'" 4 (color:rgb 1 0 0) "##")',
                  '(define face-'+name+' (find-face-id '+pos(probe)+'))',
                  '(if (not (= (length face-'+name+') 1)) (sde:error "Expected unique '+name+' face"))',
                  '(sdegeo:set-contact face-'+name+' "'+name+'")']
    body=g['doping']['body']
    lines += ['(sdedr:define-constant-profile "P.Body" "'+body['species']+'" '+number(body['value_cm3'])+')',
              '(sdedr:define-constant-profile-region "P.Body.Place" "P.Body" "R.Si")']
    if not qualification:
        implant=g['doping']['source_drain']
        for b in implant['baselines']:
            x0,y,z0=b['min_um'];x1,_,z1=b['max_um']
            points=([x0,y,z0],[x0,y,z1],[x1,y,z1],[x1,y,z0],[x0,y,z0])
            lines.append('(sdedr:define-refeval-window "'+b['id']+'" "Polygon" (list '+' '.join(pos(p) for p in points)+'))')
        lines.append('(sdedr:define-gaussian-profile "N.SD" "'+implant['species']+'" "PeakPos" '+number(implant['peak_position_um'])+' "PeakVal" '+number(implant['peak_value_cm3'])+' "ValueAtDepth" '+number(implant['value_at_depth_cm3'])+' "Depth" '+number(implant['depth_um'])+' "Gauss" "Factor" '+number(implant['lateral_gauss_factor'])+')')
        for b in implant['baselines']:lines.append('(sdedr:define-analytical-profile-placement "'+b['id'].split('.')[0]+'.Place" "N.SD" "'+b['id']+'" "Positive" "NoReplace" "Eval")')
    for w in mesh['windows']:
        name=w['name'];sizes=[v*scale for v in w['max_size_um']+w['min_size_um']]
        lines += ['(sdedr:define-refeval-window "'+name+'" "Cuboid" '+pos(w['min_um'])+' '+pos(w['max_um'])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '+' '.join(map(number,sizes))+')',
                  '(sdedr:define-refinement-placement "'+name+'.Place" "Mesh.'+name+'" "'+name+'")']
    lines += ['(sdedr:define-refinement-function "Mesh.All" "DopingConcentration" "MaxTransDiff" 1)',
              '(sde:build-mesh "snmesh" "" "cell")',
              '(define resource-guard-status (system:command "/usr/bin/python3 mesh_resource_guard.py"))',
              '(if (not (equal? resource-guard-status 0)) (sde:error "Native mesh resource gate blocked SDevice"))']
    return ('\n'.join(lines)+'\n').encode()


def render_deck(blocks, qualification):
    electrodes='{Name="source" Voltage=0} {Name="drain" Voltage=0}'
    if not qualification:electrodes+=' {Name="gate" Voltage=0 WorkFunction=4.6} {Name="body" Voltage=0}'
    head='''Device Cell {
 File { Grid="cell_msh.tdr" Current="device.plt" Plot="device.tdr" Parameter="source.par" }
 Electrode { '''+electrodes+''' }
 Physics { AreaFactor=1 Temperature=300 Fermi EffectiveIntrinsicDensity(OldSlotboom)
 Mobility(DopingDep HighFieldSaturation Enormal) Recombination(SRH(DopingDep) Auger pmi_nuclear_source) }
}
File { Output="transient" PMIPath="." }
Plot { eDensity hDensity Potential ElectricField/Vector Doping TotalCurrent/Vector eCurrent/Vector hCurrent/Vector Temperature PMIRecombination PMIUserField0 PMIUserField1 PMIUserField2 PMIUserField3 }
CurrentPlot {
 PMIRecombination(Integrate(Semiconductor) Integrate(Name="R_Total" Semiconductor Coordinates))
 PMIUserField0(Integrate(Name="G_Check" Semiconductor))
 eDensity(Integrate(Name="Electrons" Semiconductor))
 hDensity(Integrate(Name="Holes" Semiconductor))
}
Math { CoordinateSystem { AsIs } CurrentPlot(IntegrationUnit=um Digits=12)
 RelErrControl Digits=5 ErrRef(electron)=1e7 ErrRef(hole)=1e7 Iterations=30 Notdamped=100
 Transient=BE Method=Blocked SubMethod=ParDiSo ExitOnFailure }
'''
    if qualification:
        system='''System {
 Cell access ("source"=qs "drain"=qd)
 Vsource_pset vs (qs 0) {dc=0}
 Vsource_pset vd (qd 0) {dc=0}
 Plot "circuit.plt" (time() v(qs) v(qd) i(access,qs) i(access,qd))
}
'''
    else:
        original=OLD_DECK.read_text(encoding='utf-8');system=original[original.index('System {'):original.index('Solve {')]
    lines=[head+system,'Solve {',' Coupled(Iterations=100) {Poisson}',
           ' Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}',
           ' Plot(FilePrefix="initial")']
    for b in blocks:
        lo,hi=b['initial_s'],b['final_s']
        if not qualification:
            if abs(lo-.6e-9)<1e-21:lines.append(' Unset(sn)')
            if abs(lo-2.8e-9)<1e-21:lines.append(' Unset(bl)')
            if abs(lo-3e-9)<1e-21:lines += [' Set(rpre."resistance"=1e20)',' Unset(ref)']
        options='InitialTime='+number(lo)+' FinalTime='+number(hi)+' InitialStep='+number(min(1e-13,b['max_step_s']/5))+' MinStep=1e-18 MaxStep='+number(b['max_step_s'])+' Increment=1.3'
        if b['turning_points_s']:
            options+=' TurningPoints( (Condition (Time( '+' ; '.join(map(number,b['turning_points_s']))+' )) Value='+number(b['max_step_s'])+') )'
        lines += [' Transient('+options+') {',' Coupled {Poisson Electron Hole Contact Circuit}']
        if b['active_source']:
            # Exclude the repeated initial state; every newly accepted step is
            # retained. 1e-21 is below the declared minimum native step (1e-18).
            lines.append(' Plot(FilePrefix="gstep_b'+format(b['index'],'03d')+'" Time=(Range=('+number(lo+1e-21)+' '+number(hi)+')) NoOverwrite)')
        if abs(hi-4e-9)<1e-21:lines.append(' Plot(FilePrefix="final" Time=(4e-9))')
        lines.append(' }')
    lines.append('}')
    return ('\n'.join(lines)+'\n').encode()


# Self-contained generated runtime helper: no imports from a changing host tree.
GUARD = r'''"""Native post-mesh resource gate; Python 3.6; no solver/mesh edits."""
import hashlib,json,math,re,shutil,sys
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def inspect():
 m=json.loads(Path('input-manifest.json').read_text());p=json.loads(Path('parameters.json').read_text())
 if m['schema']!='nuclear-closure-inputs-r1':raise ValueError('Wrong input schema')
 for name,value in m['files_sha256'].items():
  if sha(name)!=value:raise ValueError('Frozen input changed: '+name)
 text=Path('cell_msh.log').read_text(errors='replace')
 v=re.findall(r'^\s*Optimizing elements\.\.\.done\.\s*\(([0-9]+) vertices\)\s*$',text,re.M)
 if len(v)!=1 or int(v[0])<=0:raise ValueError('Unknown/ambiguous native mesh vertex count')
 mem=re.findall(r'^MemAvailable:\s+([0-9]+) kB\s*$',Path('/proc/meminfo').read_text(),re.M)
 if len(mem)!=1:raise ValueError('Unknown native available memory')
 policy=p['resource_guard'];vertices=int(v[0]);free=shutil.disk_usage('.').free
 raw=math.ceil(policy['reference_mean_frame_bytes']*vertices/policy['reference_mesh_vertices']*policy['frame_allowance']*policy['format_margin'])
 peak=raw*policy['copy_allowance']+policy['extra_bytes']
 checks={'disk':free>=peak+policy['free_disk_floor_bytes'],'memory_start_floor':int(mem[0])*1024>=policy['available_memory_floor_bytes'],'conditional_campaign_ceiling':peak<=policy['campaign_storage_ceiling_bytes']}
 return dict(schema='nuclear-closure-native-mesh-resource-r1',passed=all(checks.values()),checks=checks,native_mesh_vertices=vertices,mesh_sha256=sha('cell_msh.tdr'),mesh_log_sha256=sha('cell_msh.log'),input_manifest_sha256=sha('input-manifest.json'),free_disk_bytes=free,available_memory_bytes=int(mem[0])*1024,conditional_raw_frame_bytes=raw,conditional_peak_additional_bytes=peak,policy=policy,peak_memory_estimate_bytes=None,resource_upper_bound_proven=False,solver_started_by_guard=False)
def main():
 if any(Path(x).exists() for x in ('mesh-resource-report.json','mesh-resource-passed.json')):return 2
 try:r=inspect()
 except Exception as e:r=dict(schema='nuclear-closure-native-mesh-resource-r1',passed=False,error=type(e).__name__+': '+str(e))
 raw=(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
 with Path('mesh-resource-report.json').open('xb') as f:f.write(raw)
 if r['passed']:
  with Path('mesh-resource-passed.json').open('xb') as f:f.write(raw)
  print('NUCLEAR_CLOSURE_MESH_RESOURCE_PASSED');return 0
 print('NUCLEAR_CLOSURE_MESH_RESOURCE_BLOCKED');return 2
if __name__=='__main__':sys.exit(main())
'''


def resource_policy(blocks):
    old=c.read(OLD_SOURCE)['resource_guard'];policy=copy.deepcopy(old)
    expected=sum(len(b['turning_points_s'])+1 for b in blocks if b['active_source'])
    policy.update(frame_allowance=4*expected+16,copy_allowance=2,
        campaign_storage_ceiling_bytes=c.contract()['budgets']['storage_GiB']*2**30,
        semantics='Actual native vertices, measured legacy bytes/vertex, four times planned accepted checkpoints plus sixteen frames. Conditional screen, not a hard frame/peak-memory bound; no automatic coarsening or frame removal.')
    return policy


def code_hashes():
    return {p.relative_to(ROOT).as_posix():c.sha(p) for p in
            (Path(__file__),HERE/'common.py',HERE/'source_kernel.py',HERE/'contract.json',OLD_SOURCE)}


def _files(role, name, event, mesh, binary_name, binary):
    m,t,qualification=role_identity(role)
    spec=event if role.startswith('event-') else artificial_source(role)
    spec=kernel().canonical_source(spec)
    blocks=time_blocks(mesh,t);geometry=render_geometry(mesh,m,qualification)
    common=dict(dimension=3,stored_bit=1,qualification=qualification,mesh_key=m,time_key=t,
                geometry_contract_sha256=c.sha(c.GEOMETRY),geometry_sha256=digest(geometry),
                common_mesh_manifest_sha256=digest(mesh),source_windows_s=mesh['source_windows_s'],
                time_blocks=blocks,area_factor=1.,pmi_binary_sha256=digest(binary),
                circuit_scope='two grounded opposing silicon contacts' if qualification else 'frozen representative bit1 cell',
                device_window_s=[0.,4e-9])
    p=dict(schema='nuclear-closure-device-r1',role=role,**common,
           source_sha256=digest(spec),source_count=len(spec['steps']),
           source_charge_fC=math.fsum(s['charge_fC'] for s in spec['steps']),
           matching_contract=common,matching_contract_sha256=digest(common),
           control_role='qualification-zero' if qualification else 'a0-'+m+'-'+t,
           resource_guard=resource_policy(blocks),source_code_sha256=code_hashes())
    project=dict(name='v4-nuclear-closure-r1-'+role,steps=[dict(tool='sde',args=['-e','-l','geometry.scm'],outputs=['cell_msh.tdr','mesh-resource-passed.json']),
                dict(tool='sdevice',args=['device.cmd'],outputs=['circuit.plt','access_device.plt','initial_access_des.tdr','final_access_des.tdr','transient_des.log'])])
    files={'geometry.scm':geometry,'device.cmd':render_deck(blocks,qualification),
           'source.par':b'pmi_nuclear_source { }\n','sources.dat':kernel().native_bytes(spec),
           'source-spec.json':c.encoded(spec),'source-contract.json':(HERE/'contract.json').read_bytes(),
           'geometry-contract.json':c.GEOMETRY.read_bytes(),'mesh-manifest.json':c.encoded(mesh),
           'parameters.json':c.encoded(p),'project.json':c.encoded(project),
           'mesh_resource_guard.py':GUARD.encode(),binary_name:binary}
    manifest=dict(schema='nuclear-closure-inputs-r1',role=role,source_code_sha256=code_hashes(),
        frozen_dependencies=dependencies(),files_sha256={k:digest(v) for k,v in files.items()},
        mesh_key=m,time_key=t,pmi_binary_name=binary_name,pmi_binary_sha256=digest(binary),
        matching_contract_sha256=p['matching_contract_sha256'],solver_started=False)
    return files,manifest


def destination_path(destination):
    value=Path(destination).resolve()
    c.require(any(value.is_relative_to((RT/x).resolve()) and value!=(RT/x).resolve() for x in ('inputs','device-dev')),
              'Input destination must be a new nuclear-closure inputs/device-dev child')
    for parent in (value,*value.parents):
        if parent==RT.parent:break
        c.require(not parent.is_symlink() and not (hasattr(parent,'is_junction') and parent.is_junction()),'Linked input path forbidden')
    return value


def build(role, destination, event_source, pmi_binary_path, mesh_manifest_path=None):
    _,_,qualification=role_identity(role);dependencies()
    out=destination_path(destination);c.require(not out.exists(),'Existing case input is immutable')
    binary_path=Path(pmi_binary_path).resolve()
    c.require(binary_path.is_file() and not binary_path.is_symlink() and re.fullmatch(r'pmi_nuclear_source\.so\.[A-Za-z0-9_-]+',binary_path.name), 'Expected the verified PMI model shared library')
    binary=binary_path.read_bytes();c.require(binary.startswith(b'\x7fELF'),'PMI library is not an ELF binary')
    if qualification:mesh=qualified_mesh();event=None
    else:
        c.require(mesh_manifest_path is not None,'Freeze the selected-event common mesh before device inputs')
        event=kernel().canonical_source(event_source);mesh=c.read(mesh_manifest_path)
        c.require(mesh==freeze_mesh(event),'Common mesh does not reproduce from selected event and artificial sources')
    files,manifest=_files(role,out.name,event,mesh,binary_path.name,binary)
    out.mkdir(parents=True,exist_ok=False)
    for name,raw in {**files,'input-manifest.json':c.encoded(manifest)}.items():
        with (out/name).open('xb') as stream:stream.write(raw)
    check_project(out)
    return manifest


def check_project(project):
    folder=destination_path(project);manifest=c.read(folder/'input-manifest.json')
    role=manifest['role'];_,_,qualification=role_identity(role)
    mesh=c.read(folder/'mesh-manifest.json');event=None if qualification else mesh['event_source']
    c.require(mesh==(qualified_mesh() if qualification else freeze_mesh(event)),'Frozen mesh changed')
    name=manifest['pmi_binary_name']
    c.require(re.fullmatch(r'pmi_nuclear_source\.so\.[A-Za-z0-9_-]+',name),'Unsafe PMI library basename')
    files,expected=_files(role,folder.name,event,mesh,name,(folder/name).read_bytes())
    c.require(expected==manifest,'Input manifest/source implementation changed')
    c.require({p.name for p in folder.iterdir()}==set(files)|{'input-manifest.json'},'Case input inventory changed')
    for name,raw in files.items():
        path=folder/name;c.require(path.is_file() and not path.is_symlink() and path.read_bytes()==raw,'Case input bytes changed: '+name)
    return dict(passed=True,role=role,manifest=c.ref(folder/'input-manifest.json'),
                matching_contract_sha256=manifest['matching_contract_sha256'],solver_started=False)


def check_control(a0, signal):
    for path in (a0,signal):check_project(path)
    p0,p1=(c.read(Path(path)/'parameters.json') for path in (a0,signal))
    c.require(p0['role']==p1['control_role'],'Wrong matched A0 role')
    c.require(p0['matching_contract']==p1['matching_contract'],'A0/signal geometry, source windows, checkpoints, binary, circuit or numerical settings differ')
    c.require((Path(a0)/'geometry.scm').read_bytes()==(Path(signal)/'geometry.scm').read_bytes(),'A0/signal mesh definition differs')
    c.require((Path(a0)/'device.cmd').read_bytes()==(Path(signal)/'device.cmd').read_bytes(),'A0/signal device deck differs')
    return dict(passed=True,control_role=p0['role'],signal_role=p1['role'],matching_contract_sha256=p0['matching_contract_sha256'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    q=sub.add_parser('check');q.add_argument('project',type=Path)
    b=sub.add_parser('build');b.add_argument('role');b.add_argument('destination',type=Path);b.add_argument('--event',type=Path);b.add_argument('--pmi',type=Path,required=True);b.add_argument('--mesh',type=Path)
    a=parser.parse_args()
    value=check_project(a.project) if a.command=='check' else build(a.role,a.destination,c.read(a.event) if a.event else None,a.pmi,a.mesh)
    print(json.dumps(value,indent=2,ensure_ascii=False))
