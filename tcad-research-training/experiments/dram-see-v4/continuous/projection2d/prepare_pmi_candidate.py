"""Prepare new 2D R12-ABI candidate inputs/oracles; never compile or dispatch."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path
import shlex

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_r14_bcat_candidate_adapter',HERE/'bcat_native_adapter.py')
N=importlib.util.module_from_spec(spec);exec(compile((HERE/'bcat_native_adapter.py').read_bytes(),str(HERE/'bcat_native_adapter.py'),'exec'),N.__dict__)
A=N.A;P=N.frozen('project.py');K=N.frozen('kernel.py');require=A.require
ROOT=N.ROOT
R12_BUILD=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-r12-build-20261017t050852z'
SOURCE_NAMES=('pmi_projection_qy_r1.C','projection_pmi_math_r1.hpp','test_projection_context_r1.C')


def source_table(terms):
    rows=sorted(term['p0_um']+term['p1_um']+[term['t0_s'],term['t1_s'],term['charge_fC'],term['width_um'],term['sigma_s']] for term in terms)
    return ('NUCLEAR_CLOSURE_SOURCE_V1 '+str(len(rows))+'\n'+''.join(' '.join(format(v,'.17g') for v in row)+'\n' for row in rows)).encode()


def context_bytes(window):
    require(len(window)==2 and all(math.isfinite(v) for v in window) and 0<=window[0]<window[1],'Explicit complete timing window required')
    return ('DRAM_SEE_V4_2D_SOURCE_CONTEXT_R1 0.02 '+' '.join(format(v,'.17g') for v in window)+'\n').encode()


def oracle_average(terms,x,z,lo,hi,context):
    """Independent time integral of the already frozen pointwise G2 function."""
    require(hi>lo,'Positive arithmetic interval required')
    mask=K.ResponseMask(dict(kind='arithmetic_rectangle',bounds_xz_um=[-2.,-1.,2.,2.],outer_trench=None),K.ABS_TOL/4,K.REL_TOL/4)
    require(mask.contains(x,z),'Oracle point outside its explicitly declared arithmetic rectangle')
    if not terms:return 0.
    points={0.,1.}
    for term in terms:
        for u in K.breakpoints(term,mask,(lo,hi),(x,z)):
            center=term['t0_s']+u*(term['t1_s']-term['t0_s'])
            for multiple in (-8,-4,-2,0,2,4,8):
                v=(center+multiple*term['sigma_s']-lo)/(hi-lo)
                if 0<v<1:points.add(v)
    for edge in context:
        v=(edge-lo)/(hi-lo)
        if 0<v<1:points.add(v)
    points=sorted(points)
    fn=lambda u:[K.generation2d(terms,mask,x,z,lo+u*(hi-lo),context)]
    return math.fsum(K.R.integrate_vector(fn,a,b,1e-11/len(points),1e-9)[0] for a,b in zip(points,points[1:]))


def oracle_vectors():
    epoch=15e-9;context=[0.,50e-9]
    def term(p0,p1,t0,t1,q=1.):return dict(uid='ARITHMETIC_FIXTURE_NOT_NATIVE',p0_um=p0,p1_um=p1,t0_s=t0,t1_s=t1,charge_fC=q,width_um=.03,sigma_s=2e-12)
    point=term([-.052,0.,.4],[-.052,0.,.4],epoch,epoch)
    diagonal=term([-.12,-.05,.3],[-.02,.06,.5],epoch-10e-12,epoch+20e-12,.8)
    transverse=term([-.052,-.08,.4],[-.052,.07,.4],epoch-30e-12,epoch+50e-12,.3)
    delayed=term([-.052,0.,.4],[-.052,0.,.4],epoch-1e-9,epoch+1e-9,.4)
    cases=[('zero',[],[-.052,.4],[epoch-2e-12,epoch+2e-12]),
        ('point',[point],[-.052,.4],[epoch-2e-12,epoch+2e-12]),
        ('dy_dt',[diagonal],[-.06,.42],[epoch+4e-12,epoch+6e-12]),
        ('only_y_and_time',[transverse],[-.04,.41],[epoch-10e-12,epoch+10e-12]),
        ('zero_chord_delayed',[delayed],[-.04,.41],[epoch+30e-12,epoch+35e-12]),
        ('overlap',[diagonal,point],[-.06,.42],[epoch-2e-12,epoch+6e-12])]
    vectors=[]
    for name,terms,point2,window in cases:
        value=oracle_average(terms,*point2,*window,context)
        vectors.append(dict(name=name,terms=terms,physical_xz_um=point2,arithmetic_interval_s=window,
            context_window_s=context,expected_G2_cm_minus3_s_minus1=value,origin='SYNTHETIC_MATH_VECTOR_NOT_NATIVE',
            independent_reference='Time quadrature of frozen kernel.generation2d, not candidate C++ output',native_clock=False))
    return vectors


VERIFY_SCRIPT='''import csv,json,math
from pathlib import Path
reference=json.loads(Path('projection-oracle-vectors.json').read_text())
actual=list(csv.DictReader(Path('candidate-oracle.csv').open()))
expected={v['name']:v for v in reference['vectors']}
assert len(actual)==len(expected) and {r['name'] for r in actual}==set(expected)
checks=[]
for row in actual:
    value=float(row['actual']);want=expected[row['name']]['expected_G2_cm_minus3_s_minus1']
    gate=1e-12+2e-8*abs(want)
    passed=math.isfinite(value) and value>=0 and abs(value-want)<=gate
    checks.append(dict(name=row['name'],actual=value,expected=want,gate=gate,passed=passed))
Path('candidate-oracle-comparison.json').write_text(json.dumps(dict(checks=checks,compiled_math_only=True,native_source_qualified=False,pmi_r12_fixed=False),indent=2))
assert all(v['passed'] for v in checks)
'''


def write_new(output,payload,kind):
    output=Path(output).resolve();require(output.is_relative_to(N.RUNTIME.resolve()) and not output.exists(),'Candidate output must be new in projection evidence directory')
    manifest=dict(schema='dram-see-v4-projection-candidate-inputs-r1',kind=kind,
        files={name:A.sha(raw) for name,raw in sorted(payload.items())},preparer=A.ref(__file__),
        compiled=False,solver_dispatched=False,native_source_qualified=False,pmi_r12_fixed=False)
    payload=dict(payload,**{'candidate-input-manifest.json':A.encoded(manifest)})
    payload['input-hashes.sha256']=''.join(A.sha(raw)+'  '+name+'\n' for name,raw in sorted(payload.items()) if name!='task.sh').encode()
    output.mkdir(parents=True)
    for name,raw in payload.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    return manifest


def prepare_compile(output):
    F=A.v1()
    with F.proton_modules() as (original,_,__):
        build,receipt=original.complete_operation(R12_BUILD,('pmi_nuclear_qy_r12.C','source_kernel_r12.hpp','candidate_math_r12.hpp',
            'task.sh','expected-runtime.sha256','cmi-exit-code.txt','pmi_nuclear_qy_r12.so.linux64','native-build-sha256.txt'))
    require((build/'collected/cmi-exit-code.txt').read_bytes().strip()==b'0','Original R12 ABI build did not succeed')
    vectors=oracle_vectors();files={name:(HERE/name).read_bytes() for name in SOURCE_NAMES}
    files['source_kernel_r12.hpp']=(build/'collected/source_kernel_r12.hpp').read_bytes()
    files['expected-runtime.sha256']=(build/'collected/expected-runtime.sha256').read_bytes()
    files['projection-oracle-vectors.json']=A.encoded(dict(schema='dram-see-v4-projection-arithmetic-oracles-r1',vectors=vectors,
        frozen_kernel=A.ref(HERE/'kernel.py'),native_callback_context=False))
    files['verify_candidate_oracle.py']=VERIFY_SCRIPT.encode()
    original_task=(build/'collected/task.sh').read_text()
    prefix=original_task.split('set +e',1)[0]
    task=prefix+'''set +e
"$CMI" -O -v pmi_projection_qy_r1.C > cmi.stdout.txt 2> cmi.stderr.txt
rc=$?
set -e
printf '%s\\n' "$rc" > cmi-exit-code.txt
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
test -s pmi_projection_qy_r1.so.linux64
nm -D pmi_projection_qy_r1.so.linux64 > exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]new_PMI_OpticalQuantumYield$' exported-symbols.txt
ldd pmi_projection_qy_r1.so.linux64 > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
grep -F "libstdc++.so.6 => $SDK/lib/libstdc++.so.6" linked-libraries.txt
grep -F "libgcc_s.so.1 => $SDK/lib/libgcc_s.so.1" linked-libraries.txt
g++ -O2 -std=c++14 -DPROJECTION_STANDALONE pmi_projection_qy_r1.C -o projection_probe
g++ -O2 -std=c++14 test_projection_context_r1.C -o projection_context_test
set +e
./projection_context_test > context-result.json 2> context.stderr.txt
rc=$?
set -e
printf '%s\\n' "$rc" > context-exit-code.txt
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
printf 'name,actual\\n' > candidate-oracle.csv
'''
    for vector in vectors:
        name=vector['name'];files['probes/'+name+'.dat']=source_table(vector['terms'])
        files['probes/'+name+'.context']=context_bytes(vector['context_window_s'])
        task+='printf '+shlex.quote(name+',')+' >> candidate-oracle.csv\n'
        values=vector['physical_xz_um']+vector['arithmetic_interval_s']
        task+=' '.join(['./projection_probe','probes/'+name+'.dat','probes/'+name+'.context']+[format(x,'.17g') for x in values])+' >> candidate-oracle.csv\n'
    task+='python3 verify_candidate_oracle.py\nsha256sum pmi_projection_qy_r1.so.linux64 projection_probe projection_context_test > native-build-sha256.txt\n'
    files['task.sh']=task.encode()
    files['candidate-boundary.json']=A.encoded(dict(schema='dram-see-v4-projection-pmi-candidate-boundary-r1',
        original_abi_build=A.ref(build/'operation.json'),original_abi_archive=A.ref(build/'results.tar'),
        original_header=A.ref(build/'collected/source_kernel_r12.hpp'),decision_record=A.ref(HERE/'BCAT-NATIVE-CANDIDATE-DECISIONS.md'),
        raw_API_clock_only=True,source_basis_cm_minus3_s_minus1=1e35,
        actual_APD_basis_status='UNRESOLVED_NO_APD_FILE_GENERATED',physics_deck_fragment=None,
        unresolved=['Actual APD quantity/units/tags and Nref field','Actual BE callbacks including retries','OpticalGeneration equals projected G2',
                    'Electron and hole equations both receive source','Native 2D coordinates/area/width field verification'],
        compiled=False,native_source_qualified=False,pmi_r12_fixed=False))
    return write_new(output,files,'compile-and-standalone-arithmetic-only-no-native-TCAD')


def prepare_source_inputs(batch,model,geometry,dimensional,window,output):
    """Preserve every true BCAT event; no source activation/APD file is supplied."""
    audited=N.verify(batch);binding=audited['binding'];sources=audited['sources']
    actual_geometry=A.read_json(binding['geometry']['path'])
    response,response_binding=P.bcat_response(model,geometry,dimensional,actual_geometry)
    files={};index=[]
    for source in sources:
        eid=source['event_id'];name=f'event-{eid}/'
        ledger=K.integrate(source['terms'],response,window,binding['native_beam']['surface_position_um'],source['epoch_s'])
        late=ledger['raw_deposition_outside_window_uids']
        files[name+'projection-sources3d.dat']=source_table(source['terms'])
        files[name+'projection-context.dat']=context_bytes(window)
        files[name+'input-only-projection-reference.json']=A.encoded(ledger)
        files[name+'full-original-event-source.json']=A.encoded(source)
        index.append(dict(event_id=eid,seed=source['seed'],source_rows=len(source['terms']),late_uids=late,
            readiness='RAW_LATE_SOURCE_REQUIRES_MATCHING_TIMING_EXTENSION' if late else 'CANDIDATE_INPUT_ONLY_APD_AND_NATIVE_QUALIFICATION_UNRESOLVED',
            source_present=bool(source['terms']),all_original_steps_retained=source['all_selected_event_steps_retained']))
    files['all-event-source-inputs.json']=A.encoded(dict(schema='dram-see-v4-projection-native-source-input-candidate-r1',
        batch_binding=binding,response_bindings=response_binding,complete_window_s=list(window),events=index,
        omitted_event_ids=[],reference_kernel=A.ref(HERE/'kernel.py'),source_adapter=A.ref(HERE/'bcat_native_adapter.py'),
        coordinate_map='native X=physical x, native Y=physical z, native Z=0; all physical y remains in original source rows',
        native_physics_fragment=None,APD_basis=None,native_source_qualified=False,pmi_r12_fixed=False))
    return write_new(output,files,'all-original-BCAT-events-native-source-input-candidate-not-activated')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    q=sub.add_parser('compile-inputs');q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('source-inputs');q.add_argument('--batch',type=Path,required=True);q.add_argument('--model',type=Path,required=True)
    q.add_argument('--geometry',type=Path,required=True);q.add_argument('--dimensional',type=Path,required=True)
    q.add_argument('--window',type=float,nargs=2,required=True);q.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=prepare_compile(args.output) if args.command=='compile-inputs' else prepare_source_inputs(args.batch,args.model,args.geometry,args.dimensional,args.window,args.output)
    print(A.encoded(result).decode())
