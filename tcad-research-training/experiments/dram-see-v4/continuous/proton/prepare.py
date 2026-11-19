"""Prepare immutable inputs for the existing operation.py; never dispatch.

Current continuous authorization replaces old budgets and release signatures.
Actual input identity, original operation exits and solver evidence stay required.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shlex
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNTIME = ROOT / 'local_runtime/dram-see-v4/continuous/proton'
OLD = ROOT / 'experiments/dram-see-v4/nuclear-closure-r1'
OPS = ROOT / 'local_runtime/dram-see-v4/transport-probe/operations'
DEFAULT_MODEL = ROOT / 'experiments/dram-see-v4/course-plan-r13/model-contract.proposed.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Upstream source anchor changed: '+old[:80])
    return text.replace(old, new)


def write_package(output, files, kind):
    output = Path(output).resolve()
    if not output.is_relative_to(RUNTIME.resolve()):
        raise ValueError('Prepared inputs must stay inside continuous/proton runtime')
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema='continuous-proton-inputs-v1', kind=kind,
                    preparer_sha256=sha(__file__), solver_dispatched=False,
                    compiled=False, native_qualified=False,
                    files={name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())})
    files = dict(files, **{'input-manifest.json': encoded(manifest)})
    files['input-hashes.sha256'] = ''.join(
        hashlib.sha256(raw).hexdigest()+'  '+name+'\n'
        for name, raw in sorted(files.items()) if name != 'task.sh').encode()
    for name, raw in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return output


def geometry_package(model_path, max_step_um=.002, cut_um=.001):
    if not all(math.isfinite(x) and x > 0 for x in (max_step_um, cut_um)):
        raise ValueError('Positive finite physical step and production cut required')
    model_path = Path(model_path)
    model = json.loads(model_path.read_text(encoding='utf-8'))
    geom = module(ROOT/'experiments/dram-see-v4/s2-inputs-r1/geometry.py', '_continuous_bcat_geometry')
    p = geom._parameters(model)
    if not (p['gate_top'] <= p['center_z']-p['metal_radius'] and
            p['sti_depth'] >= p['center_z']+p['radius']):
        raise ValueError('Boolean geometry assumptions no longer hold')
    description = geom.describe_geometry(model, 3)
    description['size_id'] = 'gate-top-'+format(p['gate_top']*1000, '.15g')+'nm'
    contract = dict(schema='continuous-bcat-proton-geometry-v1', geometry=description,
        model_source=str(model_path.resolve()), model_sha256=sha(model_path),
        geometry_code_sha256=sha(ROOT/'experiments/dram-see-v4/s2-inputs-r1/geometry.py'),
        coordinate_transform='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um',
        gate_transport_material='G4_Galactic',
        gate_limitation='Ideal electrical gate boundary has no declared transport metal; no gate-metal scattering claim',
        material_densities_g_cm3={'G4_Si': 2.33, 'G4_SILICON_DIOXIDE': 2.2},
        max_step_um=max_step_um, production_cut_um=cut_um,
        numerical_status='candidate; native geometry, range-cut and step sensitivity unverified',
        parent_transport_sha256=sha(OLD/'transport_material_r2.cc'))
    digest = hashlib.sha256(encoded(contract)).hexdigest()
    arr = lambda values: '{{'+','.join(format(float(x), '.17g') for x in values)+'}}'
    raw_json = json.dumps(contract, ensure_ascii=True, separators=(',', ':'))
    header = ['#pragma once', '#include <array>', '#include <string>', '#include <vector>', 'namespace frozen {',
        'struct Request { std::array<double,3> surface,position,direction; bool hits=true; };',
        'struct Solid { const char* id; const char* material; double density; };',
        'const Solid solids[]={{"R.Silicon","G4_Si",2.33},{"R.Trench","G4_SILICON_DIOXIDE",2.2},{"R.STI.minus","G4_SILICON_DIOXIDE",2.2},{"R.STI.plus","G4_SILICON_DIOXIDE",2.2}};',
        'const char* geometry_id="'+model['model_id']+'";',
        'const char* geometry_sha256="'+digest+'";', 'const char* contract_sha256="'+digest+'";',
        'const char* geometry_json=R"BCAT('+raw_json+')BCAT";']
    for name, values in [('domain_lo', [p['domain'][a][0] for a in 'xyz']),
                         ('domain_hi', [p['domain'][a][1] for a in 'xyz']),
                         ('world_half_um', [max(abs(v) for v in p['domain'][a])+10 for a in 'xyz'])]:
        header.append('const std::array<double,3> '+name+'='+arr(values)+';')
    for name, value in dict(outer_radius=p['radius'], metal_radius=p['metal_radius'],
        outer_half_y=p['outer_y_half'], metal_half_y=p['metal_y_half'], active_half_y=p['active_half'],
        centre_z=p['center_z'], gate_top=p['gate_top'], sti_depth=p['sti_depth'],
        max_step_um=max_step_um, cut_um=cut_um).items():
        header.append('const double '+name+'='+format(value, '.17g')+';')
    header.append('}')
    # Deterministic off-boundary probes: independent Python mask vs native CSG.
    axes = [sorted(set([p['domain'][a][0]+fraction*(p['domain'][a][1]-p['domain'][a][0])
                       for fraction in (.173,.827)]+extra)) for a,extra in zip('xyz',
        [[-.052, -.011, -.007, -.001, .001, .007, .011, .052],
         [-.055, -.013, -.009, .001, .009, .013, .055],
         [.001, .079, .081, .139, .143, .149, .151, .153, .199, .201]])]
    probes=[]
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:
                material=geom.material_at(model,x,y,z)
                native={'Silicon':'G4_Si','SiO2':'G4_SILICON_DIOXIDE','GateVoid':'G4_Galactic','Outside':'G4_Galactic'}[material]
                probes.append(' '.join(format(v,'.17g') for v in (x,y,z))+' '+native+'\n')
    return contract, ('\n'.join(header)+'\n').encode(), ''.join(probes).encode()


CONFIG = r'''Config parse(int argc, char** argv) {
  if(argc!=11) throw std::runtime_error("Usage: transport_bcat label mode arm seed events energy_MeV theta_deg target_x_um target_y_um phi_deg");
  Config c; static frozen::Request request;
  c.label=argv[1]; c.mode=argv[2]; c.arm=argv[3];
  c.seed=std::stoi(argv[4]);c.events=std::stoi(argv[5]);c.energy=std::stod(argv[6]);c.angle=std::stod(argv[7]);
  const double tx=std::stod(argv[8]),ty=std::stod(argv[9]),phi=std::stod(argv[10])*deg;
  if((c.mode!="init" && c.mode!="normal") || (c.arm!="H" && c.arm!="E") || c.seed<=0 ||
     c.events<0 || (c.mode=="init")!=(c.events==0) || !std::isfinite(c.energy) || c.energy<=0 ||
     !std::isfinite(c.angle) || c.angle<0 || c.angle>=90 || !std::isfinite(tx) || !std::isfinite(ty) || !std::isfinite(phi))
    throw std::runtime_error("Invalid explicit continuous request");
  request.surface={{tx,ty,0}};
  request.direction={{std::sin(c.angle*deg)*std::cos(phi),std::sin(c.angle*deg)*std::sin(phi),std::cos(c.angle*deg)}};
  const double distance=1./request.direction[2];
  for(int i=0;i<3;++i) {
    request.position[i]=request.surface[i]-distance*request.direction[i];
    if(std::abs(request.position[i])>=frozen::world_half_um[i]) throw std::runtime_error("Beam starts outside world");
  }
  c.request=&request;return c;
}
'''


def transport_source():
    source=(OLD/'transport_material_r2.cc').read_text(encoding='utf-8')
    source=replace_once(source,'#include "G4Box.hh"','#include "G4Box.hh"\n#include "G4Tubs.hh"\n#include "G4DisplacedSolid.hh"\n#include "G4UnionSolid.hh"\n#include "G4SubtractionSolid.hh"\n#include "G4RotationMatrix.hh"')
    source=replace_once(source,'G4ThreeVector direction() const { return {0.,1.,0.}; }',
        'G4ThreeVector direction() const { const auto& v=request->direction; return {v[0],v[1],v[2]}; }')
    start=source.index('Config parse('); end=source.index('std::map<std::string,std::string> declared_volumes()',start)
    source=source[:start]+CONFIG+source[end:]
    start=source.index('class Geometry :'); end=source.index('class Electromagnetic :',start)
    source=source[:start]+(HERE/'bcat_geometry.inc').read_text(encoding='utf-8')+'\n'+source[end:]
    source=replace_once(source,'p->SetDefaultCutValue(.01*um);','p->SetDefaultCutValue(frozen::cut_um*um);')
    source=replace_once(source,'GetProductionCut(j)/um-.01','GetProductionCut(j)/um-frozen::cut_um')
    source=replace_once(source,'Actual range cut differs from explicit 0.01 um policy','Actual range cut differs from explicit continuous geometry policy')
    source=replace_once(source,'{"production_cut_um","0.01"},{"max_step_um","0.02"}',
        '{"production_cut_um",number(frozen::cut_um)},{"max_step_um",number(frozen::max_step_um)}')
    return source.encode()


def transport_build(output, model=DEFAULT_MODEL, max_step_um=.002, cut_um=.001):
    contract, header, probes=geometry_package(model,max_step_um,cut_um)
    files={'transport_bcat.cc':transport_source(),'geometry.hh':header,
           'geometry-contract.json':encoded(contract),'geometry-probes.tsv':probes,
           'model-input.json':Path(model).read_bytes()}
    for name in ('environment.sh','dataset-inventory.json'):
        files[name]=(OPS/'install-data-r2/collected'/name).read_bytes()
    files['task.sh']=b'''set -euo pipefail
sha256sum -c input-hashes.sha256 > verified-inputs.txt
source environment.sh
G4ROOT=/home/tcad/research-training/dram-see-v1/software/Geant4-10.7.3-Linux
g++ --version > compiler-version.txt
"$G4ROOT/bin/geant4-config" --version > geant4-version.txt
set +e
g++ -O2 $("$G4ROOT/bin/geant4-config" --cflags) transport_bcat.cc -o transport_bcat $("$G4ROOT/bin/geant4-config" --libs) > compile.stdout.txt 2> compile.stderr.txt
rc=$?
set -e
printf '%s\\n' "$rc" > compile-exit-code.txt
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
ldd transport_bcat > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
sha256sum transport_bcat transport_bcat.cc geometry.hh geometry-contract.json > build-sha256.txt
'''
    return write_package(output,files,'geant4_compile_only')


def complete_operation(operation, required_outputs=()):
    operation=Path(operation).resolve()
    receipt=json.loads((operation/'operation.json').read_text(encoding='utf-8'))
    current=receipt.get('schema')=='dram-see-v4-transport-operation-v2'
    if current:
        if (receipt.get('state')!='COLLECTED_PENDING_AUDIT' or receipt.get('collection_verified') is not True
                or receipt.get('origin')!='native_pipeline' or receipt.get('synthetic') is not False
                or receipt.get('label')!=operation.name):
            raise ValueError('Current operation lacks verified original completion/identity')
        exit_keys=('remote_exit_code','operation_task_exit_code','collection_exit_code')
    else:
        if receipt.get('schema')!='dram-see-v4-transport-operation-v1':
            raise ValueError('Unknown native operation schema')
        exit_keys=('ssh_exit_code','remote_exit_code','collection_exit_code')
    if not all(type(receipt.get(k)) is int and receipt[k]==0 for k in exit_keys):
        raise ValueError('Native operation lacks actual successful exits')
    if receipt.get('archive_sha256')!=sha(operation/'results.tar'):
        raise ValueError('Original native archive identity mismatch')
    for name,digest in receipt['input_sha256'].items():
        if sha(operation/'collected'/name)!=digest:
            raise ValueError('Archived native input changed: '+name)
    raw_exits=('exit-code.txt','operation-task-exit-code.txt') if current else ()
    wanted=set(required_outputs)|set(raw_exits)
    with tarfile.open(operation/'results.tar') as archive:
        for member in archive:
            name=member.name.removeprefix('./')
            if name not in wanted:continue
            if not member.isfile():raise ValueError('Expected regular native output: '+name)
            data=archive.extractfile(member)
            digest=hashlib.sha256()
            for chunk in iter(lambda:data.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=sha(operation/'collected'/name):
                raise ValueError('Collected native output differs from original archive: '+name)
            if name in raw_exits and (operation/'collected'/name).read_bytes().strip()!=b'0':
                raise ValueError('Original native task/wrapper exit is not zero: '+name)
            wanted.remove(name)
    if wanted:raise ValueError('Native outputs absent from original archive: '+str(sorted(wanted)))
    return operation,receipt


def transport_run(output, operation, label, arm='H', seed=2026101701, events=1,
                  energy=5., theta=0., target_x=-.052, target_y=0., phi=180.):
    operation,receipt=complete_operation(operation,('transport_bcat','compile-exit-code.txt','build-sha256.txt'))
    if not re.fullmatch('[a-z0-9][a-z0-9-]*',label) or arm not in ('H','E'):
        raise ValueError('Invalid request identity')
    if type(seed) is not int or seed<=0 or type(events) is not int or events<0:
        raise ValueError('Invalid seed/event count')
    if not all(math.isfinite(x) for x in (energy,theta,target_x,target_y,phi)) or energy<=0 or not 0<=theta<90:
        raise ValueError('Invalid proton beam')
    collected=operation/'collected'
    if int((collected/'compile-exit-code.txt').read_text())!=0:
        raise ValueError('Transport compiler did not succeed')
    request=dict(label=label,mode='init' if events==0 else 'normal',arm=arm,seed=seed,event_count=events,
                 energy_MeV=energy,theta_deg=theta,phi_deg=phi,target_um=[target_x,target_y,0],
                 source_operation_sha256=sha(operation/'operation.json'))
    names=('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json','geometry-probes.tsv',
           'model-input.json','environment.sh','dataset-inventory.json','build-sha256.txt')
    files={name:(collected/name).read_bytes() for name in names}
    files['request.json']=encoded(request)
    args=[label,request['mode'],arm,str(seed),str(events),*[format(v,'.17g') for v in (energy,theta,target_x,target_y,phi)]]
    files['task.sh']=('set -euo pipefail\nsha256sum -c input-hashes.sha256 > verified-inputs.txt\n'
        'sha256sum -c build-sha256.txt > verified-build.txt\nsource environment.sh\nchmod u+x transport_bcat\n'
        'set +e\n./transport_bcat '+' '.join(shlex.quote(x) for x in args)+' > transport.stdout.txt 2> transport.stderr.txt\n'
        'rc=$?\nset -e\nprintf \'%s\\n\' "$rc" > transport-exit-code.txt\nexit "$rc"\n').encode()
    return write_package(output,files,'geant4_native_transport')


def r12_build(output):
    old=OLD/'source-update-r12'
    files={name:(old/name).read_bytes() for name in ('pmi_nuclear_qy_r12.C','source_kernel_r12.hpp','candidate_math_r12.hpp','test_context_r12.C')}
    spec=json.loads((OLD/'pmi-recovery-r2.json').read_text(encoding='utf-8'))
    vector_ref=spec['original']['vectors']; vector_path=ROOT/vector_ref['path']
    if sha(vector_path)!=vector_ref['sha256']: raise ValueError('Original arithmetic vector identity changed')
    vectors=json.loads(vector_path.read_text(encoding='utf-8'))
    files['native-oracle-vectors.json']=vector_path.read_bytes()
    # Reuse the already reviewed compile/link/test commands, not its old release/budget coordinator.
    legacy=(old/'build_candidate_r12.py').read_text(encoding='utf-8')
    script=legacy.split("script = r'''",1)[1].split("'''",1)[0]
    script=script.replace('sha256sum -c expected-sha256.txt > verified-input-runtime-hashes.txt',
                          'sha256sum -c input-hashes.sha256 > verified-input-runtime-hashes.txt\nsha256sum -c expected-runtime.sha256 >> verified-input-runtime-hashes.txt')
    expected=dict(spec['runtime_hashes'])
    for line in (OPS/'nc-r1-pmi-build/collected/native-tool-header-sha256.txt').read_text().splitlines():
        digest,path=line.split(None,1);expected[path.strip()]=digest
    files['expected-runtime.sha256']=''.join(digest+'  '+path+'\n' for path,digest in sorted(expected.items())).encode()
    for row in vectors['vectors']:
        name=row['name']
        if not re.fullmatch('[a-z_]+',name):raise ValueError('Unsafe oracle identity')
        path=ROOT/row['native']['path']
        if sha(path)!=row['native']['sha256']:raise ValueError('Original source table changed')
        files['probes/'+name+'.dat']=path.read_bytes()
        values=row['xyz_um']+row['window_s']
        if not all(math.isfinite(x) for x in values):raise ValueError('Nonfinite oracle')
        script+='printf '+shlex.quote(name+',')+' >> native-oracle.csv\n'
        script+=' '.join(['./source_probe','probes/'+name+'.dat']+[format(x,'.17g') for x in values])+' >> native-oracle.csv\n'
    script+='sha256sum pmi_nuclear_qy_r12.so.linux64 source_probe context_test > native-build-sha256.txt\n'
    files['task.sh']=script.encode()
    files['candidate-boundary.json']=encoded(dict(source='R12 byte-identical candidate',compiled=False,qualified=False,
        unresolved=['APD basis with documented quantity/units/tags','actual BE callbacks and retry intervals','native OpticalGeneration vs user fields','carrier-only source equivalence'],
        execution_path='existing transport-probe/operation.py, controlled only by main owner'))
    return write_package(output,files,'pmi_r12_compile_only')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('transport-build');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',type=Path,default=DEFAULT_MODEL);p.add_argument('--max-step-um',type=float,default=.002);p.add_argument('--cut-um',type=float,default=.001)
    p=sub.add_parser('r12-build');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('transport-run');p.add_argument('--output',type=Path,required=True);p.add_argument('--operation',type=Path,required=True);p.add_argument('--label',required=True)
    p.add_argument('--arm',choices=['H','E'],default='H');p.add_argument('--seed',type=int,required=True);p.add_argument('--events',type=int,required=True)
    for name,default in [('energy',5.),('theta',0.),('target-x',-.052),('target-y',0.),('phi',180.)]:p.add_argument('--'+name,type=float,default=default)
    args=vars(parser.parse_args());command=args.pop('command').replace('-','_')
    print(globals()[command](**args))


if __name__=='__main__':main()
