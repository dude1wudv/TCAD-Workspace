"""New multi-condition input packages for the original operation, no dispatch."""
from __future__ import annotations
import argparse
import importlib.util
import math
from pathlib import Path
import re
import shlex

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_proton_transport_geometry_v2',HERE/'proton_geometry_v2.py')
G=importlib.util.module_from_spec(spec);exec(compile((HERE/'proton_geometry_v2.py').read_bytes(),str(HERE/'proton_geometry_v2.py'),'exec'),G.__dict__)
F=G.F;require=F.require
BUILD_INPUTS=('transport_bcat.cc','geometry.hh','geometry-contract.json','device-geometry-contract.json',
              'geometry-probes.tsv','model-input.json','environment.sh','dataset-inventory.json','input-manifest.json','task.sh')
BUILD_OUTPUTS=('transport_bcat','compile-exit-code.txt','build-sha256.txt','compiler-version.txt','geant4-version.txt','linked-libraries.txt')
RUN_INPUTS=('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json','device-geometry-contract.json',
            'geometry-probes.tsv','model-input.json','environment.sh','dataset-inventory.json','build-sha256.txt')


def condition(condition_id,seed,*,development=False):
    F.stable();found=[row for row in F.B.conditions() if row['condition_id']==condition_id]
    require(len(found)==1,'Unknown original proton condition')
    row=found[0];gate=float(row['gate_top_depth_nm'])
    require(gate in (70.,80.,90.) and row['size_id']=={70.:'S1',80.:'S2',90.:'S3'}[gate],
            'Original condition gate/size identity differs')
    require(type(seed) is int and seed in [int(value) for value in row['proposed_seeds'].split('|')],
            'Seed must belong to the original condition; no condition or stream relabeling')
    require(float(row['energy_MeV']) in (50.,100.,150.) and float(row['angle_deg']) in (0.,30.)
            and float(row['azimuth_deg'])==180. and float(row['source_time_ns'])==15.
            and [float(row['start_'+axis+'_nm']) for axis in 'xyz']==[-52.,0.,0.],
            'Original proton beam axes/origin changed')
    if development:require(row['split']=='train','Final holdout is unavailable to development input preparation')
    return row


def prepare_build(model_path,geometry_path,output,max_step_um=.002,cut_um=.001):
    model_path=Path(model_path).resolve();geometry_path=Path(geometry_path).resolve()
    model_raw=model_path.read_bytes();geometry_raw=geometry_path.read_bytes()
    contract,header,probes=G.construct(model_raw,geometry_raw,str(model_path),str(geometry_path),max_step_um,cut_um)
    files=F.original_build_payload()
    files.update({'model-input.json':model_raw,'device-geometry-contract.json':geometry_raw,
                  'geometry-contract.json':F.encoded(contract),'geometry.hh':header,'geometry-probes.tsv':probes})
    return F.write_package(output,files,'geant4_multi_condition_compile_candidate',
                           [__file__,G.__file__,F.__file__,HERE/'PROTON-V2-ASSUMPTIONS.md'])


def audit_build(build):
    build,receipt=F.P.complete_operation(build,BUILD_INPUTS+BUILD_OUTPUTS)
    folder=build/'collected';semantic=G.validate_files(folder)
    require((folder/'compile-exit-code.txt').read_bytes().strip()==b'0','Original multi-condition compiler failed')
    require((folder/'geant4-version.txt').read_bytes().strip()==b'10.7.3','Compiled Geant4 version differs')
    require('not found' not in (folder/'linked-libraries.txt').read_text(),'Original compiled library missing')
    manifest=F.read(folder/'input-manifest.json')
    require(manifest['schema']=='continuous-proton-inputs-v2' and manifest['version_id']=='v2-proton-bcat'
            and manifest['kind']=='geant4_multi_condition_compile_candidate','Unknown compiled input package')
    for name,digest in manifest['files'].items():
        require(F.sha((folder/name).read_bytes())==digest,'Original compiled input manifest differs: '+name)
    binary_hashes={name.strip():digest for digest,name in
                   (line.split(None,1) for line in (folder/'build-sha256.txt').read_text().splitlines())}
    for name in ('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json'):
        require(binary_hashes.get(name)==F.sha((folder/name).read_bytes()),'Native compiled identity differs: '+name)
    return build,receipt,semantic


def request_payload(build,label,row,seed,events,semantic):
    require(re.fullmatch('[a-z0-9][a-z0-9-]*',label) is not None,'Invalid native input label')
    require(type(events) is int and events>=0,'Explicit nonnegative physical event count required')
    require(float(row['gate_top_depth_nm'])==semantic['gate_top_depth_nm'],'Requested condition is not the compiled D3 gate')
    return dict(schema='continuous-proton-transport-request-v2',version_id='v2-proton-bcat',label=label,
        mode='init' if events==0 else 'normal',arm='H',seed=seed,event_count=events,
        energy_MeV=float(row['energy_MeV']),theta_deg=float(row['angle_deg']),phi_deg=180.,target_um=[-.052,0.,0.],
        source_operation_sha256=F.P.sha(Path(build)/'operation.json'),condition_id=row['condition_id'],original_split=row['split'],
        gate_top_depth_nm=semantic['gate_top_depth_nm'],sn_junction_depth_nm=semantic['sn_junction_depth_nm'],
        matrix=F.ref(F.MATRIX),matrix_row=row,sn_axis_data_design_registered=False,
        related_stream_policy='Same condition/seed/event across SN uses a common random stream; do not count as independent primaries',
        final_holdout=row['split']!='train',final_holdout_policy='never_for_tuning')


def prepare_run(output,build,label,condition_id,seed,events,initialization_only=False):
    row=condition(condition_id,seed,development=True)
    require(type(events) is int and events>0,'Positive explicit event count required; this is a data definition, not a quota')
    build,receipt,semantic=audit_build(build);folder=build/'collected'
    request=request_payload(build,label,row,seed,0 if initialization_only else events,semantic)
    files={name:(folder/name).read_bytes() for name in RUN_INPUTS};files['request.json']=F.encoded(request)
    args=[label,request['mode'],'H',str(seed),str(request['event_count']),
          *[format(value,'.17g') for value in (request['energy_MeV'],request['theta_deg'],-.052,0.,180.)]]
    files['task.sh']=('set -euo pipefail\nsha256sum -c input-hashes.sha256 > verified-inputs.txt\n'
        'sha256sum -c build-sha256.txt > verified-build.txt\nsource environment.sh\nchmod u+x transport_bcat\n'
        'set +e\n./transport_bcat '+' '.join(shlex.quote(value) for value in args)+' > transport.stdout.txt 2> transport.stderr.txt\n'
        'rc=$?\nset -e\nprintf \'%s\\n\' "$rc" > transport-exit-code.txt\nexit "$rc"\n').encode()
    return F.write_package(output,files,'geant4_multi_condition_development_transport_candidate',[__file__,G.__file__,F.__file__])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('build');q.add_argument('--model-path',type=Path,required=True);q.add_argument('--geometry-path',type=Path,required=True)
    q.add_argument('--output',type=Path,required=True);q.add_argument('--max-step-um',type=float,default=.002);q.add_argument('--cut-um',type=float,default=.001)
    q=sub.add_parser('run');q.add_argument('--output',type=Path,required=True);q.add_argument('--build',type=Path,required=True)
    q.add_argument('--label',required=True);q.add_argument('--condition-id',required=True);q.add_argument('--seed',type=int,required=True)
    q.add_argument('--events',type=int,required=True);q.add_argument('--initialization-only',action='store_true')
    args=vars(p.parse_args());command=args.pop('command');print(globals()['prepare_'+command](**args))
