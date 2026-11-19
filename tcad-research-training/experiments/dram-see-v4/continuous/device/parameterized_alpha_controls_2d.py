"""Candidate-only source controls on an actually verified matching r13 A0.

No project/operation/runner is created or executed. The original fixed r13
reducer and r15 matched-A0 reader are reused without relabelling original data.
The nested r15 request describes the unchanged full-alpha reference, not the
new control role. New control source/deck bytes have their own binding.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BRANCH='dram-see-v4-parameterized-alpha-controls-2d-r1'
REQUEST_SCHEMA='dram-see-v4-parameterized-alpha-control-request-r1'
ALPHA_SHA='395879dae534e5ab1832740e056519457d1dbb217e7a69180078ea026148ebef'
PROJECTION_SHA='a2593ddcf1cf6e776d69cafb4c174d82885f81b221dcf6c9577fe5577d3e90dc'
CANDIDATE_SCHEMA='dram-see-v4-parameterized-alpha-control-candidate-r1'
BINDING_SCHEMA='dram-see-v4-parameterized-alpha-control-binding-r1'
SOURCE_SCHEMA='dram-see-v4-parameterized-alpha-control-source-spec-r1'
PREFIX='alpha-control-projection/'
A0_PREFIX='matched-a0-bindings/'
CASES={'zero':('Z',0.),'half':('H',.5),'split':('split',1.)}

class CandidateRefused(ValueError):
    def __init__(self,message,evidence=None):
        ValueError.__init__(self,'Alpha control candidate: '+message)
        self.evidence=evidence

def require(ok,message,evidence=None):
    if not ok:raise CandidateRefused(message,evidence)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):return json.loads(raw.decode('utf-8'))
def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()
def fixed(name,expected):
    path=HERE/name;raw=path.read_bytes();require(sha(raw)==expected and not path.is_symlink(),'fixed local module changed: '+name)
    spec=importlib.util.spec_from_file_location('_parameterized_alpha_controls_'+name.replace('.','_'),path)
    module=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),module.__dict__);return module
def alpha():return fixed('parameterized_alpha_2d.py',ALPHA_SHA)
def projection():return fixed('parameterized_alpha_control_projection_2d.py',PROJECTION_SHA)

def validate_request(request):
    require(isinstance(request,dict) and set(request)=={'schema','control','control_projection_package','reference_alpha_request'}
        and request['schema']==REQUEST_SCHEMA and request['control'] in CASES,'exact independent control request required')
    require(isinstance(request['control_projection_package'],str) and request['control_projection_package'].strip(),'explicit control package required')
    reference=alpha().validate_request(request['reference_alpha_request'])
    require(reference['gate_top_depth_nm']==80 and reference['energy_MeV']==5 and reference['theta_deg']==0
        and reference['variant']=='main','controls currently use g80 E5 normal main only; no final or refinement relabelling')
    value=obj(encoded(request));value['reference_alpha_request']=reference
    return value

def role_id(request):
    r=validate_request(request);return 'B2D-'+CASES[r['control']][0]+'-parameterized-control-r1-main-b'+str(r['reference_alpha_request']['stored_bit'])

def _actual_match(reference,R):
    source=Path(reference['matched_a0_run']).resolve();D=R.dimensional()
    require(source.is_dir() and 'fixture' not in str(source).lower() and not (source/'SYNTHETIC_NOT_NATIVE').exists(),
        'actual original matching A0 directory required')
    missing=[n for n in ('manifest.json','results.tar','inputs.tar') if not (source/n).is_file()]
    require(not missing,'PENDING_MATCHED_A0_ORIGINALS',dict(source=str(source),missing_original_files=missing,
        native_source_qualified=False,training_admitted=False))
    host=R.baseline_api().reduce_archive(source)
    require(host.get('native_engineering_chain_verified') is True and host.get('complete_clock_evidence_verified') is True
        and host.get('candidate_functional_pass') is True,'actual r13 A0 original native/clock/five checks not passed',host)
    raw=(source/'manifest.json').read_bytes();manifest=obj(raw)
    require(manifest.get('state')=='COLLECTED' and manifest.get('run_id')==source.name,'original matched A0 is not fully collected')
    originals={A0_PREFIX+n:dict(path=str(source/n),sha256=file_sha(source/n),size_bytes=(source/n).stat().st_size)
        for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
        and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'original A0 outer hashes differ')
    with tarfile.open(str(source/'results.tar'),'r:*') as a,tarfile.open(str(source/'inputs.tar'),'r:*') as i:
        reader=D.ArchiveReader(a);match=R.verify_matched_a0(reader,manifest,D.ArchiveReader(i),reference)
        source_bytes={n:reader.read(n) for n in ('cell_msh.tdr','d2-source-binding.json')}
    require(host['candidate_metrics']==match['metrics'],'host and original reader replay differ')
    matched=R.matched_identity(match,manifest,sha(raw),originals[A0_PREFIX+'results.tar']['sha256'])
    R.request_matches(reference,match['verified']['operation_timing'],matched,match['cfg'])
    return host,match,matched,originals,source_bytes

class BytesReader:
    def __init__(self,files):self.files=files
    def read(self,name):return self.files[name]
    def digest(self,name):return sha(self.read(name))
    def size(self,name):return len(self.read(name))

def candidate_payload(request):
    """Return native input candidate bytes/imports only after real A0 proof.

    No formal project, run ID, admission, dispatch or native receipt is created.
    CandidateRefused.evidence retains full rejected baseline diagnostics.
    """
    r=validate_request(request);reference=r['reference_alpha_request'];R=alpha();P=projection();A=R.alpha()
    host,match,matched,originals,source_bytes=_actual_match(reference,R)
    package=Path(r['control_projection_package']).resolve();verified=P.verify(package);contract=verified['contract']
    require(contract['request']['control']==r['control'],'control package/request differ')
    parent=package/'base-projection'
    original_parent=Path(reference['alpha_projection_package']).resolve()
    for n in P.BASE_FILES:
        require((parent/n).read_bytes()==(original_parent/n).read_bytes(),'control/full-alpha original source bytes differ: '+n)
    base_contract=obj((parent/'source-contract.json').read_bytes());timing=match['verified']['operation_timing']
    R.source_request(base_contract['request'],timing,reference)
    for n in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(match['shared'][n]==(parent/n).read_bytes(),'control/A0 model/material/width differs: '+n)
    require(contract['mesh_sha256']==sha(source_bytes['cell_msh.tdr'])
        and contract['physics_manifest_sha256']==sha(match['shared']['physics-manifest.json']),
        'actual selected A0 mesh/physics differs from source reference')
    packet={n:(package/n).read_bytes() for n in verified['manifest']['files']}
    packet['input-output-manifest.json']=(package/'input-output-manifest.json').read_bytes()
    require(all(sha(packet[n])==v['sha256'] and len(packet[n])==v['size_bytes'] for n,v in verified['manifest']['files'].items()),
        'control changed after mathematical replay')
    files=dict(match['shared']);files.update(source_bytes);files.update({PREFIX+n:raw for n,raw in packet.items()})
    for n in ('heavyion.physics.inc','source.par','source-contract.json'):files[n]=packet[n]
    files['device.cmd']=A.render_signal(match['device'],files['heavyion.physics.inc'])
    require(A.source_free_deck(files['device.cmd'],files['heavyion.physics.inc'])==match['device'],
        'source-free candidate must equal original matching A0 deck bytes')
    files['run-parameters.par']=files['physics.par']+b'\n'+files['source.par']
    files['heavyion.plot.inc']=A.PLOT.rstrip()+b'\n';files['heavyion.currentplot.inc']=A.CURRENT
    files['source-time-contract.json']=encoded(R.source_time_contract(match['device'],base_contract,timing,reference))
    files['parameter-binding.json']=encoded(A.parameter_binding(BytesReader(files)))
    files['source-control-request.json']=encoded(r)
    case,amplitude=CASES[r['control']];role=role_id(r)
    bound=dict(schema=BINDING_SCHEMA,source_branch=BRANCH,control=r['control'],source_case=case,amplitude=amplitude,
        source_contract_sha256=sha(files['source-contract.json']),control_projection_manifest_sha256=sha(packet['input-output-manifest.json']),
        base_alpha_source_contract_sha256=contract['base_source_contract_sha256'],
        matched_a0=matched,matched_a0_original_files={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()},
        operation_timing_sha256=sha(files['operation-timing.json']),source_time_contract_sha256=sha(files['source-time-contract.json']),
        mesh_sha256=sha(files['cell_msh.tdr']),physics_manifest_sha256=sha(files['physics-manifest.json']),
        dimensional_contract_sha256=sha(files['dimensional-contract.json']),
        implementation_sha256=file_sha(__file__),projection_implementation_sha256=PROJECTION_SHA,
        parent_alpha_verifier_sha256=ALPHA_SHA,baseline_verifier_sha256=R.BASELINE_SHA,
        host_matched_A0_original_chain_replayed=True,source_free_deck_byte_identical=True,
        host_control_mathematics_replayed=True,native_control_run_completed=False,
        native_source_qualified=False,training_admitted=False,additional_normalization=False)
    files['parameterized-alpha-control-binding.json']=encoded(bound)
    binding_sha=sha(files['parameterized-alpha-control-binding.json'])
    spec=dict(schema=SOURCE_SCHEMA,particle='alpha',role='SIGNAL',source_case=case,control=r['control'],
        stored_bit=reference['stored_bit'],numerical_variant='main',dimension=2,gate_top_depth_nm=80,
        sn_junction_depth_nm=87,effective_width_nm=20,energy_MeV=5,theta_deg=0,phi_deg=180,amplitude=amplitude,
        source_configured=True,input_structural_zero=amplitude==0,structural_zero_is_not_measured_G_zero=True,
        energy_definition='Reference Si-entry E5 trajectory retained; amplitude changes configured G, not incident energy',
        source_contract_sha256=sha(files['source-contract.json']),source_time_contract_sha256=sha(files['source-time-contract.json']),
        operation_timing_sha256=sha(files['operation-timing.json']),physics_manifest_sha256=sha(files['physics-manifest.json']),
        dimensional_contract_sha256=sha(files['dimensional-contract.json']),control_binding_sha256=binding_sha,
        expected_comparison='same-bit r13 A0' if case=='Z' else 'same-bit unsplit full alpha from identical parent source',
        half_response_linearity_assumed=False,source_field_comparison_required=True,
        source_native_relative_tolerance=.05,zero_split_response_charge_limit_fC=1e-4,zero_split_response_voltage_limit_V=1e-5,
        zero_split_limits_are_not_checks_executed=True,native_source_qualified=False,training_admitted=False)
    files['source-spec.json']=encoded(spec)
    files['role-contract.json']=encoded(dict(schema='dram-see-v4-parameterized-alpha-control-role-r1',role=role,
        source_case=case,stored_bit=reference['stored_bit'],source_branch=BRANCH,
        matched_A0_role=match['role'],source_spec_sha256=sha(files['source-spec.json']),control_binding_sha256=binding_sha,
        source_configured=True,native_syntax_verified=False,native_source_qualified=False))
    files['matched-a0-host-audit.json']=encoded(host)
    for name,row in originals.items():require(file_sha(row['path'])==row['sha256'],'original A0 changed during read-only candidate build: '+name)
    manifest=dict(schema=CANDIDATE_SCHEMA,source_branch=BRANCH,role=role,implementation_sha256=file_sha(__file__),
        files={n:dict(sha256=sha(raw),size_bytes=len(raw)) for n,raw in files.items()},imports=originals,
        matched_a0=matched,requires_same_original_runner_freeze=True,not_an_executable_project=True,
        no_run_id_assigned=True,global_dispatch_modified=False,native_calls=0,native_source_qualified=False,training_admitted=False)
    return dict(files=files,imports=originals,manifest=manifest,source_spec=spec,binding=bound,
        integration=dict(branch=BRANCH,role=role,source_case=case,
            existing_r15_and_field_adapters_accept_this_version=False,
            required_next='Register a new version in original dispatch and add control-aware field/response comparison; preserve r15'))

def verify_candidate(reader,request):
    """Host replay of candidate data; no archived Python executes."""
    expected=candidate_payload(request)
    for name,raw in expected['files'].items():require(reader.read(name)==raw,'candidate bytes differ: '+name)
    for name,row in expected['imports'].items():
        require(reader.digest(name)==row['sha256'] and reader.size(name)==row['size_bytes'],'candidate original A0 import differs: '+name)
    return expected['manifest']

def inspect_request(request):
    """JSON-safe status including actual rejected A0 diagnostics; no file writes."""
    try:
        result=candidate_payload(request)
        return dict(status='CANDIDATE_BYTES_ONLY',manifest=result['manifest'],source_spec=result['source_spec'],
            integration=result['integration'],native_source_qualified=False,training_admitted=False)
    except (CandidateRefused,OSError,ValueError,KeyError,TypeError,tarfile.TarError) as error:
        return dict(status='REFUSED_CANDIDATE',error=dict(type=type(error).__name__,message=str(error)),
            actual_rejection_evidence=getattr(error,'evidence',None),native_calls=0,
            native_source_qualified=False,training_admitted=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    require(not args.output.exists(),'new diagnostic output required; no overwrite')
    require(ROOT/'local_runtime' in args.output.resolve().parents,'diagnostic output must remain in project runtime')
    result=inspect_request(obj(args.request.read_bytes()));args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as stream:stream.write(encoded(result))
    print(encoded(dict(status=result['status'],error=result.get('error'),native_source_qualified=False)).decode())
    raise SystemExit(0 if result['status']=='CANDIDATE_BYTES_ONLY' else 2)
