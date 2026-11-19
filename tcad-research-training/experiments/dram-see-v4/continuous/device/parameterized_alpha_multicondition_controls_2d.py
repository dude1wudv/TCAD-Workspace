"""Versioned linear-amplitude and disjoint-table controls of multicondition alpha.

Python 3.6 stdlib guest closure. Host preparation replays the unchanged f8
parent mathematics and actual same-condition r13 A0 originals. No launcher or qualification shortcut.
"""
import hashlib
import importlib.util
import json
import math
from decimal import Decimal, localcontext
from pathlib import Path
import re
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BRANCH = 'dram-see-v4-parameterized-alpha-multicondition-controls-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-alpha-multicondition-control-request-r1'
BINDING_SCHEMA = 'dram-see-v4-alpha-multicondition-control-binding-r1'
RUNTIME_SCHEMA = 'dram-see-v4-alpha-multicondition-control-runtime-r1'
SPEC_SCHEMA = 'dram-see-v4-alpha-multicondition-control-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-alpha-multicondition-control-role-r1'
REPRESENTATION_SCHEMA = 'dram-see-v4-alpha-multicondition-control-native-representation-r1'
MAIN_SHA = '6e651db56c2c44307f129f9fc9be24b97ee51aec8205ee5bda0ebd16e582c01d'
CONTROL_PROJECTION_SCHEMA = 'dram-see-v4-multicondition-alpha-control-projection-r1'
CONTROL_PROJECTION_REQUEST_SCHEMA = 'dram-see-v4-multicondition-alpha-control-projection-request-r1'
CONTROL_MANIFEST_SCHEMA = 'dram-see-v4-multicondition-alpha-control-projection-manifest-r1'
PREFIX = 'alpha-control-projection/'
A0_PREFIX = 'matched-a0-bindings/'
REPRESENTATION_FILE = 'native-control-representation.json'
BINDING_FILE = 'parameterized-alpha-multicondition-control-binding.json'
RUNTIME_BINDING_FILE = 'parameterized-alpha-multicondition-control-runtime-binding.json'
CASES = {'zero': ('Z', 0.), 'half': ('H', .5), 'split': ('split', 1.)}
FROZEN_RESULT_KEYS = {
    'binding', 'report', 'source_cfg', 'dimensional_contract', 'operation_timing',
    'operating_binding', 'source_spec', 'role_contract', 'numerical_relation',
    'projection', 'control_binding', 'control_runtime_binding', 'matched_a0',
    'source_time_contract', 'native_representation'}
LOGICAL_VIEW_MAPPING = {'parent_source_only':'alpha-control-projection/base-projection/',
    'roles_or_cfg_or_original_archives_aliased':False,'actual_native_control_verified_separately':True}


def require(ok, message):
    if not ok:
        raise ValueError('Alpha partition controls: '+message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def obj(raw):
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'JSON object required')
    return value


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def fixed(name,expected):
    path=HERE/name
    require(path.is_file() and not path.is_symlink(),'fixed local implementation missing/linked: '+name)
    raw=path.read_bytes();require(sha(raw)==expected,'fixed local implementation changed: '+name)
    spec=importlib.util.spec_from_file_location('_alpha_multicondition_controls_'+name.replace('.','_'),str(path))
    value=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),value.__dict__)
    return value


def main_api():
    return fixed('parameterized_alpha_multicondition_2d.py', MAIN_SHA)






def validate_request(request):
    require(isinstance(request,dict) and set(request)=={'schema','control','reference_alpha_request'},
            'exact independent multicondition-control request required')
    require(request['schema']==REQUEST_SCHEMA and request['control'] in CASES,'explicit new control schema/case required')
    reference=main_api().validate_request(request['reference_alpha_request'])
    result=obj(encoded(request));result['reference_alpha_request']=reference
    return result



def role_id(request):
    r=validate_request(request);reference=r['reference_alpha_request']
    return 'B2D-'+CASES[r['control']][0]+'-multicondition-control-r1-'+reference['variant']+'-b'+str(reference['stored_bit'])



class BytesReader:
    def __init__(self, files):
        self.files = files

    def read(self, name):
        return self.files[name]

    def digest(self, name):
        return sha(self.read(name))

    def size(self, name):
        return len(self.read(name))




def native_representation(base_include,base_parameters,control):
    """Exact original LET scaling and subdivision; no new source integration."""
    require(control in CASES,'unknown control')
    R=main_api();main=R.render_native(base_include,base_parameters)
    amp=CASES[control][1]
    found=list(R.ARRAY.finditer(base_include))
    tokens={m.group(1).decode():m.group(2).split() for m in found}
    position=list(R.POSITION.finditer(base_include))[0]
    header=b'HeavyIon("'+R.NATIVE_NAME.encode()+b'")'
    pieces=[];declarations=[];coverage=[];parent_cuts=[]
    with localcontext() as context:
        context.prec=100
        values={k:[R._decimal_token(v) for v in rows] for k,rows in tokens.items()}
        lengths=values['Length'];parent_let=values['LET_f'];amplitude=Decimal(str(amp))
        # Decimal multiplication preserves the original serialized table's exact
        # line integral. 0/.5/1 also have the same binary64 amplitude relation.
        control_let=[v*amplitude for v in parent_let]
        require(all(float(c)==amp*float(p) for c,p in zip(control_let,parent_let)),
                'serialized control LET/binary64 amplitude differs')
        origin=[R._decimal_token(v) for v in position.group(1,2)]
        direction=[R._decimal_token(v) for v in position.group(3,4)]
        for parent_index,part in enumerate(main['contract']['pieces']):
            first,last=part['original_node_indices_inclusive'];parent_cuts.append([first,last])
            middle=first+(last-first)//2
            require(control!='split' or first<middle<last,'cannot split parent interval without inventing a node')
            cuts=[(first,middle),(middle,last)] if control=='split' else [(first,last)]
            for first,last in cuts:
                index=len(pieces);start=lengths[first]
                local_name=R.NATIVE_NAME if index==0 else R.NATIVE_NAME+'_control_part'+str(index)
                include=base_include
                for match in reversed(found):
                    key=match.group(1).decode()
                    if key=='Length':entries=[R._decimal_bytes(v-start) for v in lengths[first:last+1]]
                    elif key=='LET_f':entries=([v for v in tokens[key][first:last+1]] if amp==1.
                        else [R._decimal_bytes(v) for v in control_let[first:last+1]])
                    else:entries=tokens[key][first:last+1]
                    include=include[:match.start(2)]+b' '.join(entries)+include[match.end(2):]
                include=include.replace(header,b'HeavyIon("'+local_name.encode()+b'")',1)
                new_origin=[origin[i]+direction[i]*start for i in range(2)]
                replacement=b' StartPoint=('+b','.join(R._decimal_bytes(v) for v in new_origin)+b') Direction=('
                replacement+=position.group(3)+b','+position.group(4)+b')\n'
                include=include.replace(position.group(0),replacement,1)
                par=base_parameters.replace(header,b'HeavyIon("'+local_name.encode()+b'")',1)
                indices=list(range(first,last));coverage.extend(indices)
                q=sum((lengths[i+1]-lengths[i])*(control_let[i]+control_let[i+1])/2 for i in indices)
                declarations.append(dict(index=index,parent_piece_index=parent_index,name=local_name,
                    original_node_indices_inclusive=[first,last],original_interval_indices=indices,
                    original_s_interval_um=[str(start),str(lengths[last])],native_node_count=last-first+1,
                    native_local_s_tokens=[R._decimal_bytes(v-start).decode() for v in lengths[first:last+1]],
                    original_LET_tokens=[v.decode() for v in tokens['LET_f'][first:last+1]],
                    control_LET_tokens=[v.decode() for v in list(R.ARRAY.finditer(include))[1].group(2).split()],
                    original_width_tokens=[v.decode() for v in tokens['Wt_hi'][first:last+1]],
                    native_StartPoint_tokens=[R._decimal_bytes(v).decode() for v in new_origin],
                    original_Direction_tokens=[v.decode() for v in position.group(3,4)],
                    exact_decimal_line_integral_pC=str(q),
                    expected_finite_interval='0 <= local_s < length; each original interpolation interval owned once',
                    actual_native_endpoint_or_junction_verified=False))
                pieces.append((include,par,q))
        parent_q=sum((b-a)*(la+lb)/2 for a,b,la,lb in zip(lengths,lengths[1:],parent_let,parent_let[1:]))
        control_q=sum(p[2] for p in pieces)
        require(coverage==list(range(len(lengths)-1)) and control_q==amplitude*parent_q,
                'complete original interval denominator or amplitude charge differs')
    include=b''.join(p[0] for p in pieces);parameters=b''.join(p[1] for p in pieces)
    contract=dict(schema=REPRESENTATION_SCHEMA,control=control,amplitude=amp,
        reference_main_runtime_sha256=MAIN_SHA,control_transform_implementation_sha256=file_sha(__file__),
        parent_include_sha256=sha(base_include),parent_parameter_sha256=sha(base_parameters),
        reference_main_native_include_sha256=sha(main['heavyion_physics_inc']),
        reference_main_native_parameter_sha256=sha(main['source_par']),
        reference_main_native_representation_sha256=sha(encoded(main['contract'])),
        active_include_sha256=sha(include),active_parameter_sha256=sha(parameters),
        parent_node_count=len(lengths),parent_interval_count=len(lengths)-1,
        reference_main_piece_count=len(main['contract']['pieces']),piece_count=len(pieces),pieces=declarations,
        original_parent_piece_node_ranges=parent_cuts,all_original_nodes_preserved=True,
        all_original_interpolation_intervals_retained=True,omitted_original_node_indices=[],omitted_original_interval_indices=[],
        parent_line_integral_pC=str(parent_q),control_line_integral_pC=str(control_q),
        exact_decimal_amplitude_partition_delta_pC='0',split_has_distinct_native_partition=control=='split',
        split_rule='Bisect every actual parent native piece at its middle original node; no new or removed nodes',
        source_amplitude_binary64_relation_verified=True,
        source_epoch_literal=re.findall(rb'\bTime=([^\s]+)',base_include)[0].decode(),
        units=dict(Length='um',LET_f='pC/um',Wt_hi='um',Time='s'),
        gaussian_or_time_or_energy_renormalized=False,original_reference_energy_unscaled=True,
        control_is_not_a_new_physical_event=True,control_is_not_an_independent_training_condition=True,
        original_half_device_response_linearity_required=False,
        native_table_count_limit_claimed=False,native_endpoint_field_qualification=False,
        native_source_qualified=False,scientific_evidence_verified=False,training_admitted=False)
    return dict(heavyion_physics_inc=include,source_par=parameters,contract=contract)



def _runtime_bytes():
    result=main_api()._runtime_bytes()
    result['parameterized_alpha_multicondition_controls_2d.py']=Path(__file__).read_bytes()
    return result



def _snapshots():
    result={}
    for name,(relative,expected) in _snapshot_map().items():
        raw=(HERE/relative).read_bytes();require(sha(raw)==expected,'fixed mathematical dependency differs: '+name)
        result[name]=raw
    return result



def projection(reader,timing,reference,control):
    R=main_api();base_verified=R.projection(ParentProjectionView(reader),timing,reference)
    base_verified['reference_view_only_not_actual_native_main']=True
    base={n:reader.read(PREFIX+'base-projection/'+n) for n in R.PROJECTION_FILES}
    derived=derive_control(base,control)
    for name,raw in derived['files'].items():
        require(reader.read(PREFIX+name)==raw,'complete control transform replay differs: '+name)
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):
        require(reader.read(name)==derived['files'][name],'actual root control source differs: '+name)
    require(obj(reader.read(REPRESENTATION_FILE))==derived['native']['contract'],'actual native control representation differs')
    result={k:derived[k] for k in ('contract','ledger','manifest','energy_source_provenance')}
    result.update(base_projection=base_verified,native_expression_replayed=True,
        guest_mathematical_replay=False,guest_scope='Complete fixed parent identities and exact linear/interval transform; host replays f8',
        actual_root_identity_never_aliased=True)
    return result,derived['native']['contract']




def input_status(request):
    r=validate_request(request);result=main_api().input_status(r['reference_alpha_request'])
    return dict(result,control=r['control'],control_role_id=role_id(r),
        control_is_not_a_new_physical_event=True,control_is_not_an_independent_training_condition=True,
        new_physical_events=0,project=None,native_source_qualified=False,training_admitted=False)


def scaled_source_row(row,amplitude):
    """Scale charge-weighted source moments, never the parent's energy history."""
    result=obj(encoded(row))
    for key,value in row.items():
        is_source=any(key.endswith(s) for s in ('_fC','_fC_um','_fC_um2','_fC_ps','_fC_ps2'))
        if is_source and key!='offline_charge_gate_fC':
            require(type(value) in (int,float) and math.isfinite(value),'nonfinite original charge/moment '+key)
            result[key]=amplitude*value
    if 'declared_axial_all_transverse_all_time_fC' in result:
        result['offline_charge_gate_fC']=max(1e-6,.001*abs(result['declared_axial_all_transverse_all_time_fC']))
    return result


def derive_control(base,control):
    """Pure deterministic transform of the entire frozen parent source package.

    The caller must verify/replay f8; guest validates its complete hash closure.
    Linear amplitude and interval additivity do not claim native seam values.
    """
    R=main_api();require(set(base)==set(R.PROJECTION_FILES),'all 14 original parent files required')
    parent_contract=obj(base['source-contract.json']);parent_ledger=obj(base['projection-ledger.json'])
    parent_energy=obj(base['energy-source-provenance.json']);amp=CASES[control][1]
    require(parent_ledger['actual_clock'] is None and parent_ledger['tail_renormalization'] is False,
            'parent must remain pre-TCAD finite-domain source')
    native=native_representation(base['heavyion.physics.inc'],base['source.par'],control)
    coarse=scaled_source_row(parent_ledger['coarse'],amp);fine=scaled_source_row(parent_ledger['refined'],amp)
    energy=dict(schema='dram-see-v4-multicondition-control-reference-energy-r1',
        original_parent_energy=parent_ledger['energy'],original_parent_provenance=parent_energy,
        reference_energy_unscaled=True,reference_incident_energy_MeV=parent_ledger['energy']['entry_energy_MeV'],
        reference_remaining_energy_MeV=parent_ledger['energy']['exit_energy_MeV'],
        configured_source_amplitude=amp,amplitude_is_not_incident_energy_scaling=True,
        configured_source_account=dict(
            analytic_electronic_line_charge_fC=amp*parent_ledger['energy']['electronic_line_charge_fC'],
            tabulated_electronic_line_charge_fC=amp*parent_ledger['energy']['tabulated_line_charge_fC'],
            analytic_vs_LUT_charge_difference_fC=amp*parent_ledger['energy']['lut_charge_error_fC'],
            declared_axial_all_transverse_all_time_fC=fine['declared_axial_all_transverse_all_time_fC'],
            configured_charge_and_moments_are_in_control_ledger=True),
        incident_energy_counted_once=True,restarted_at_incident_energy_per_segment=False,
        nuclear_energy_converted_to_charge=False,new_physical_events=0)
    ledger=dict(schema='dram-see-v4-multicondition-control-charge-ledger-r1',
        coarse=coarse,refined=fine,energy=energy,original_parent_ledger=parent_ledger,
        charge_partition_order=parent_ledger['charge_partition_order'],
        configured_source_amplitude=amp,parent_scaled_reference=fine,
        refinement_absolute_differences={k:abs(coarse[k]-v) for k,v in fine.items() if type(v) in (int,float)},
        control_transform='Linear charge-weighted amplitude; split is exact disjoint original-interval subdivision',
        integration_recomputed=False,host_parent_mathematics_must_be_replayed=True,
        tail_renormalization=False,discarded_source_records=0,original_all_time_line_source_retained=True,
        actual_clock=None,is_native_measurement=False,native_zero_split_charge_limit_fC=1e-4,
        native_zero_split_voltage_limit_V=1e-5,native_zero_split_checks_executed=False,native_source_qualified=False)
    control_request=dict(schema=CONTROL_PROJECTION_REQUEST_SCHEMA,control=control,source_case=CASES[control][0],
        amplitude=amp,base_request=parent_contract['request'])
    contract=dict(schema=CONTROL_PROJECTION_SCHEMA,particle='alpha',dimension=2,request=control_request,
        configured_amplitude=amp,base_request=parent_contract['request'],
        base_source_contract_sha256=sha(base['source-contract.json']),
        base_projection_manifest_sha256=sha(base['input-output-manifest.json']),
        base_projection_implementation_sha256=R.PROJECTION_SHA,control_transform_sha256=file_sha(__file__),
        base_mapping=parent_contract['mapping'],time_shift_s=0,additional_normalization=False,
        source_amplitude_does_not_change_incident_energy=True,new_physical_events=0,new_training_conditions=0,
        exact_native_representation_sha256=sha(encoded(native['contract'])),
        native_endpoint_and_seam_field_verification='PENDING; integral identity does not prove native endpoint samples',
        native_source_qualified=False,native_qualified=False,is_tcad_result=False,training_admitted=False,pmi_r12_fixed=False)
    for name in ('response','path','input_sha256','mesh_sha256','physics_manifest_sha256','source_window_s','full_simulation_window_s'):
        contract[name]=parent_contract[name]
    packet={'base-projection/'+n:raw for n,raw in base.items()}
    packet.update({'control-request.json':encoded(control_request),'projection-ledger.json':encoded(ledger),
        'energy-source-provenance.json':encoded(energy),'native-control-representation.json':encoded(native['contract']),
        'heavyion.physics.inc':native['heavyion_physics_inc'],'source.par':native['source_par']})
    contract['derived_files_sha256']={n:sha(raw) for n,raw in packet.items() if not n.startswith('base-projection/')}
    packet['source-contract.json']=encoded(contract)
    manifest=dict(schema=CONTROL_MANIFEST_SCHEMA,implementation_sha256=file_sha(__file__),
        base_projection_sha256=R.PROJECTION_SHA,
        files={n:dict(sha256=sha(raw),size_bytes=len(raw)) for n,raw in packet.items()},
        is_native_result=False,native_source_qualified=False,training_admitted=False)
    packet['input-output-manifest.json']=encoded(manifest)
    return dict(files=packet,contract=contract,ledger=ledger,manifest=manifest,
        energy_source_provenance=energy,native=native)


class ParentProjectionView:
    """Only source-data view; no aliases of roles, cfg, runtime or archives."""
    def __init__(self,reader):
        self.reader=reader
        R=main_api()
        self.native=R.render_native(reader.read(PREFIX+'base-projection/heavyion.physics.inc'),
                                   reader.read(PREFIX+'base-projection/source.par'))

    def read(self,name):
        R=main_api()
        if name.startswith(R.PROJECTION_PREFIX):
            return self.reader.read(PREFIX+'base-projection/'+name[len(R.PROJECTION_PREFIX):])
        if name=='source-contract.json':return self.reader.read(PREFIX+'base-projection/'+name)
        if name=='heavyion.physics.inc':return self.native['heavyion_physics_inc']
        if name=='source.par':return self.native['source_par']
        if name==R.NATIVE_REPRESENTATION_FILE:return encoded(self.native['contract'])
        return self.reader.read(name)

    def digest(self,name):return sha(self.read(name))
    def size(self,name):return len(self.read(name))


def _snapshot_map():
    R=main_api()
    result={'alpha-projection-implementation.py':('parameterized_alpha_projection_2d.py',R.PROJECTION_SHA),
        'alpha-projection-core.py':('alpha_projection_2d.py',R.CORE_PROJECTION_SHA),
        'alpha-projection-reference.py':('../proton/source_reference.py',R.REFERENCE_SHA)}
    result.update({'alpha-projection-dependency-'+k+'.py':v for k,v in R.DEPENDENCIES.items()})
    return result


def replay_control(read):
    """Host-only original f8 re-computation, followed by exact new transform."""
    R=main_api();P=R.module('parameterized_alpha_projection_2d.py',R.PROJECTION_SHA)
    request=validate_request(obj(read('controlled-request.json')));reference=request['reference_alpha_request']
    timing=obj(read('operation-timing.json'))
    class Read:
        def read(self,name):return read(name)
        def digest(self,name):return sha(read(name))
        def size(self,name):return len(read(name))
    logical,native=projection(Read(),timing,reference,request['control'])
    base={n:read(PREFIX+'base-projection/'+n) for n in R.PROJECTION_FILES}
    inputs={n:base[n] for n in P.INPUT_NAMES}
    source_request=obj(base['projection-request.json'])
    expected,contract,ledger=P.derive(inputs,source_request)
    require(contract==logical['base_projection']['contract'] and ledger==logical['base_projection']['ledger'],
            'host f8 source mathematics differs from frozen parent')
    for name,raw in expected.items():require(base[name]==raw,'host full parent source differs: '+name)
    logical['host_parent_mathematical_replay']=True
    return logical,P._context(inputs,source_request),None


def actual_match(reference,R):
    """Same actual r13 baseline/native/clock/triple checks; no old control API."""
    source=Path(reference['matched_a0_run']).resolve();D=R.dimensional()
    require(source.is_dir() and not source.is_symlink() and 'fixture' not in str(source).lower()
            and not (source/'SYNTHETIC_NOT_NATIVE').exists(),'actual original matching A0 directory required')
    require(all((source/n).is_file() for n in ('manifest.json','results.tar','inputs.tar')),'PENDING_MATCHED_A0_ORIGINALS')
    host=R.baseline_api().reduce_archive(source)
    require(host.get('native_engineering_chain_verified') is True and host.get('complete_clock_evidence_verified') is True
            and host.get('candidate_functional_pass') is True,'actual r13 A0 native/clock/five checks not passed')
    raw=(source/'manifest.json').read_bytes();manifest=obj(raw)
    require(manifest.get('state')=='COLLECTED' and manifest.get('run_id')==source.name,'actual matching A0 not fully collected')
    originals={A0_PREFIX+n:dict(path=str(source/n),sha256=file_sha(source/n),size_bytes=(source/n).stat().st_size)
               for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
        and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'original A0 outer hashes differ')
    with tarfile.open(str(source/'results.tar'),'r:*') as a,tarfile.open(str(source/'inputs.tar'),'r:*') as i:
        reader=D.ArchiveReader(a);match=R.verify_matched_a0(reader,manifest,D.ArchiveReader(i),reference)
        source_bytes={n:reader.read(n) for n in ('cell_msh.tdr','d2-source-binding.json')}
    require(host['candidate_metrics']==match['metrics'],'host and original reader metrics differ')
    matched=R.matched_identity(match,manifest,sha(raw),originals[A0_PREFIX+'results.tar']['sha256'])
    R.request_matches(reference,match['verified']['operation_timing'],matched,match['cfg'])
    return host,match,matched,originals,source_bytes



def _declarations(reader, cfg, request, match, matched, originals):
    control = request['control']
    reference = request['reference_alpha_request']
    case, amp = CASES[control]
    bound = dict(schema=BINDING_SCHEMA, source_branch=BRANCH, run_id=cfg['run_id'],
        role_id=role_id(request), control=control, source_case=case, amplitude=amp,
        implementation_sha256=file_sha(__file__), reference_main_runtime_sha256=MAIN_SHA,
        design_condition=main_api().design_condition(reference),
        control_transform_sha256=file_sha(__file__), parent_math_sha256=main_api().PROJECTION_SHA,
        logical_control_manifest_sha256=reader.digest(PREFIX+'input-output-manifest.json'),
        logical_source_contract_sha256=reader.digest('source-contract.json'),
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        active_include_sha256=reader.digest('heavyion.physics.inc'), active_parameter_sha256=reader.digest('source.par'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),
        mesh_sha256=reader.digest('cell_msh.tdr'), physics_manifest_sha256=reader.digest('physics-manifest.json'),
        dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        matched_a0=matched, matched_a0_original_files=originals,
        logical_guest_view_mapping=LOGICAL_VIEW_MAPPING,
        actual_root_identity_never_aliased=True, source_free_deck_byte_identical=True,
        half_response_linearity_required=False, native_source_qualified=False, training_admitted=False)
    bound_sha = sha(encoded(bound))
    spec = dict(schema=SPEC_SCHEMA, source_branch=BRANCH, particle='alpha', role='SIGNAL',
        source_case=case, control=control, amplitude=amp, stored_bit=reference['stored_bit'],
        numerical_variant=reference['variant'], dimension=2, gate_top_depth_nm=reference['gate_top_depth_nm'], sn_junction_depth_nm=87,
        effective_width_nm=20, energy_MeV=reference['energy_MeV'], theta_deg=reference['theta_deg'], phi_deg=180,
        design_condition=main_api().design_condition(reference),new_physical_events=0,new_training_conditions=0,
        source_configured=True, input_structural_zero=control == 'zero',
        structural_zero_is_not_measured_G_zero=True, control_binding_sha256=bound_sha,
        source_contract_sha256=reader.digest('source-contract.json'),
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),
        physics_manifest_sha256=reader.digest('physics-manifest.json'),
        dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        reference_main_runtime_sha256=MAIN_SHA, source_native_relative_tolerance=.05,
        zero_split_response_charge_limit_fC=1e-4, zero_split_response_voltage_limit_V=1e-5,
        half_response_linearity_required=False, source_field_comparison_required=True,
        configured_amplitude_is_not_incident_energy_scaling=True,
        native_source_qualified=False, scientific_evidence_verified=False, training_admitted=False)
    role = dict(schema=ROLE_SCHEMA, role=role_id(request), source_branch=BRANCH,
        source_case=case, stored_bit=reference['stored_bit'], matched_A0_role=match['role'],
        numerical_variant=reference['variant'],design_condition=main_api().design_condition(reference),
        source_spec_sha256=sha(encoded(spec)), control_binding_sha256=bound_sha,
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        source_configured=True, native_syntax_verified=False, native_source_qualified=False)
    return bound, spec, role


def runtime_binding(reader, cfg):
    return dict(schema=RUNTIME_SCHEMA, source_branch=BRANCH, run_id=cfg['run_id'], role_id=cfg['role_id'],
        implementation_sha256=file_sha(__file__),
        runtime_sha256={n:sha(v) for n,v in _runtime_bytes().items()},
        files_sha256={n:reader.digest(n) for n in (
            'controlled-request.json', BINDING_FILE, REPRESENTATION_FILE, 'source-spec.json',
            'role-contract.json', 'device.cmd', 'heavyion.physics.inc', 'source.par',
            'source-contract.json', 'source-time-contract.json')},
        guest_mathematical_integrals_replayed=False, guest_native_representation_replayed=True,
        guest_uses_closed_local_runtime=True, native_source_qualified=False, training_admitted=False)


def verify_frozen(reader, cfg):
    R = main_api()
    P, D, A = R.parameterized(), R.dimensional(), R.alpha()
    require(cfg.get('source_branch') == BRANCH and cfg.get('dimension_branch') == P.DIMENSION_BRANCH
            and cfg.get('mode') == 'reuse' and 'parameterized_operating_branch' not in cfg,
            'explicit new partition-control root required')
    request = validate_request(obj(reader.read('controlled-request.json')))
    reference = request['reference_alpha_request']
    require(cfg.get('role_id') == role_id(request) and cfg.get('stored_bit') == reference['stored_bit']
            and cfg.get('alpha_design_condition')==R.design_condition(reference),
            'actual new control role/bit differs')
    for name, raw in _runtime_bytes().items():
        require(reader.digest(name) == sha(raw), 'closed runtime changed: '+name)
    result, _, _ = P._verify_sources(reader, cfg)
    bound = obj(reader.read(BINDING_FILE))
    require(bound.get('schema') == BINDING_SCHEMA and reader.digest(BINDING_FILE)
            == cfg.get('parameterized_alpha_multicondition_control_binding_sha256'), 'new control binding differs')
    originals = bound.get('matched_a0_original_files', {})
    require(set(originals) == {A0_PREFIX+n for n in ('manifest.json', 'results.tar', 'inputs.tar')},
            'all three original matched A0 files required')
    for name, row in originals.items():
        require(row == dict(sha256=reader.digest(name), size_bytes=reader.size(name)),
                'actual matching A0 original changed: '+name)
    manifest = obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256') == reader.digest(A0_PREFIX+'results.tar')
            and manifest.get('inputs_archive_sha256') == reader.digest(A0_PREFIX+'inputs.tar'),
            'outer original A0 archive hashes differ')
    with reader.stream(A0_PREFIX+'results.tar') as a, reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a, mode='r:*') as ar, tarfile.open(fileobj=i, mode='r:*') as ir:
            prior = D.ArchiveReader(ar)
            match = R.verify_matched_a0(prior, manifest, D.ArchiveReader(ir), reference)
            matched = R.matched_identity(match, manifest, reader.digest(A0_PREFIX+'manifest.json'),
                                         reader.digest(A0_PREFIX+'results.tar'))
            for name, raw in match['shared'].items():
                require(reader.read(name) == raw, 'control/A0 physical input differs: '+name)
            require(reader.digest('cell_msh.tdr') == prior.digest('cell_msh.tdr') == cfg['mesh_sha256']
                    and reader.read('d2-source-binding.json') == prior.read('d2-source-binding.json'),
                    'actual control/A0 mesh or source differs')
            timing = match['verified']['operation_timing']
            R.request_matches(reference, timing, matched, cfg)
            logical, native = projection(reader, timing, reference, request['control'])
            time = R.source_time_contract(match['device'], logical['base_projection']['contract'], timing, reference)
            include = reader.read('heavyion.physics.inc')
            require(reader.read('device.cmd') == A.render_signal(match['device'], include)
                    and A.source_free_deck(reader.read('device.cmd'), include) == match['device'],
                    'source-free deck differs from actual same-bit A0')
            require(obj(reader.read('source-time-contract.json')) == time, 'source/native physical time changed')
    require(reader.read('run-parameters.par') == reader.read('physics.par')+b'\n'+reader.read('source.par')
            and obj(reader.read('parameter-binding.json')) == A.parameter_binding(reader),
            'actual base/source parameter binding differs')
    expected, spec, role = _declarations(reader, cfg, request, match, matched, originals)
    require(bound == expected and obj(reader.read('source-spec.json')) == spec
            and obj(reader.read('role-contract.json')) == role, 'new root source/role declarations differ')
    runtime = runtime_binding(reader, cfg)
    require(obj(reader.read(RUNTIME_BINDING_FILE)) == runtime and reader.digest(RUNTIME_BINDING_FILE)
            == cfg.get('parameterized_alpha_multicondition_control_runtime_sha256'), 'new runtime binding differs')
    require(reader.read('heavyion.plot.inc') == A.PLOT.rstrip()+b'\n'
            and reader.read('heavyion.currentplot.inc') == A.CURRENT, 'original source diagnostics differ')
    result.update(operation_timing=timing, operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'], source_spec=spec, role_contract=role,
        projection=logical, control_binding=bound, control_runtime_binding=runtime,
        matched_a0=matched, source_time_contract=time, native_representation=native)
    require(set(result) == FROZEN_RESULT_KEYS, 'new 15-key result differs')
    return result


def candidate_payload(request):
    request=validate_request(request);reference=request['reference_alpha_request'];R=main_api()
    R.require_supported_interfaces(reference)
    host,match,matched,originals,source_bytes=actual_match(reference,R)
    P=R.module('parameterized_alpha_projection_2d.py',R.PROJECTION_SHA)
    package=Path(reference['alpha_projection_package']).resolve();verified=P.verify(package)
    base={n:(package/n).read_bytes() for n in R.PROJECTION_FILES}
    require(obj(base['input-output-manifest.json'])==verified['manifest']
        and all(dict(sha256=sha(base[n]),size_bytes=len(base[n]))==row for n,row in verified['manifest']['files'].items()),
        'parent changed after host f8 replay')
    timing=match['verified']['operation_timing'];R.source_request(verified['contract']['request'],timing,reference)
    for name in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(match['shared'][name]==base[name],'actual control/A0 geometry/material/width differs: '+name)
    require(verified['contract']['mesh_sha256']==sha(source_bytes['cell_msh.tdr'])
        and verified['contract']['physics_manifest_sha256']==sha(match['shared']['physics-manifest.json']),
        'actual control parent mesh/physics differs')
    derived=derive_control(base,request['control']);native=derived['native']
    files=dict(match['shared']);files.update(source_bytes)
    files.update({PREFIX+n:raw for n,raw in derived['files'].items()})
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):files[name]=derived['files'][name]
    files[REPRESENTATION_FILE]=encoded(native['contract']);A=R.alpha()
    files['device.cmd']=A.render_signal(match['device'],files['heavyion.physics.inc'])
    require(A.source_free_deck(files['device.cmd'],files['heavyion.physics.inc'])==match['device'],
            'source-free candidate differs from same-condition A0')
    files['run-parameters.par']=files['physics.par']+b'\n'+files['source.par']
    files['heavyion.plot.inc']=A.PLOT.rstrip()+b'\n';files['heavyion.currentplot.inc']=A.CURRENT
    files['source-time-contract.json']=encoded(R.source_time_contract(match['device'],verified['contract'],timing,reference))
    files['parameter-binding.json']=encoded(A.parameter_binding(BytesReader(files)))
    files['controlled-request.json']=encoded(request);files.update(_runtime_bytes());files.update(_snapshots())
    checked,native_check=projection(BytesReader(files),timing,reference,request['control'])
    require(checked['contract']==derived['contract'] and native_check==native['contract'],'host/frozen control transform differs')
    return dict(files=files,imports=originals,request=request,match=match,host_a0_report=host,
        matched_a0=matched,projection=checked,native_representation=native['contract'],
        status='CANDIDATE_BYTES_ONLY_NO_PROJECT_NO_NATIVE_CONTROL_RESULT',
        native_source_qualified=False,training_admitted=False)



def _add_declarations(files, cfg, request, match, matched, originals):
    reader = BytesReader(files)
    bound, spec, role = _declarations(reader, cfg, request, match, matched, originals)
    files[BINDING_FILE] = encoded(bound)
    cfg['parameterized_alpha_multicondition_control_binding_sha256'] = sha(files[BINDING_FILE])
    files['source-spec.json'] = encoded(spec)
    files['role-contract.json'] = encoded(role)
    files[RUNTIME_BINDING_FILE] = encoded(runtime_binding(reader, cfg))
    cfg['parameterized_alpha_multicondition_control_runtime_sha256'] = sha(files[RUNTIME_BINDING_FILE])


def admit(project, spec, runner_sha, bridge):
    R = main_api()
    D, O = R.dimensional(), R.operation()
    project = Path(project)
    cfg = spec['s2_geometry']
    require('fixture' not in str(project.resolve()).lower() and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'fixture cannot be admitted')
    request = validate_request(obj((project/'controlled-request.json').read_bytes()))
    reference = request['reference_alpha_request']
    require(cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False
            and cfg.get('execution_enabled') is True and spec.get('execution_enabled') is True
            and spec.get('role') == cfg.get('role_id') == role_id(request)
            and O.plain_name(cfg.get('run_id'))
            and cfg['run_id'] not in (cfg['producer_run_id'], O.source_name(reference['matched_a0_run']))
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))],
            'original-runner actual role, identity or serial-step contract differs')
    bridge.geometry_context(project, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(project)
    d2 = obj((project/'d2-source-binding.json').read_bytes())
    mathematical = obj((project/PREFIX/'input-output-manifest.json').read_bytes())
    required = set(D.SHARED_INPUTS)|set(_runtime_bytes())|set(R.SHARED)|set(d2['original_files'])
    required |= set(_snapshot_map())|{PREFIX+n for n in mathematical['files']}
    required |= {A0_PREFIX+n for n in ('manifest.json', 'results.tar', 'inputs.tar')}
    required |= {
        'project.json', 'controlled-request.json', 'case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py',
        'task-authorization.json', 'resource-policy.json', 'device.cmd', 'cell_msh.tdr', 'cell_msh.log',
        'd2-source-binding.json', 'source-contract.json', 'source.par', 'heavyion.physics.inc', 'heavyion.plot.inc',
        'heavyion.currentplot.inc', 'run-parameters.par', 'parameter-binding.json', 'source-time-contract.json',
        BINDING_FILE, RUNTIME_BINDING_FILE, REPRESENTATION_FILE, 'source-spec.json', 'role-contract.json',
        PREFIX+'input-output-manifest.json'}
    require(required <= set(hashes), 'mandatory actual source, runtime or original proof missing')
    for name, h in hashes.items():
        require(D.file_sha(bridge.geometry_path(project, name)) == h, 'frozen input changed: '+name)
    manifest = obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id') == cfg['run_id'] and manifest.get('role_id') == cfg['role_id'],
            'input manifest native identity differs')
    verified = verify_frozen(D.FolderReader(project), cfg)
    require(verified['operation_timing']['origin'] == 'prescribed_input', 'UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes()) == dict(
        schema='dram-see-v4-actual-resource-policy-r1', role=cfg['role_id'],
        observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None),
        'actual resource observation only; no quota or approval')
    return cfg


def prepare(request, run_id, runner=None, output=None):
    """Prepare one real control input; never submit or create an operation."""
    request = validate_request(request)
    status=input_status(request)
    if status['status']!='INPUT_FILES_PRESENT_REPLAY_REQUIRED':return status
    R = main_api()
    P, D, O = R.parameterized(), R.dimensional(), R.operation()
    C, bridge = R.module('case_contract.py'), R.module('geometry_bridge.py')
    require(getattr(C, 'SCHEMA_2D_ALPHA_MULTICONDITION_CONTROL', None) == REQUEST_SCHEMA
            and hasattr(bridge, 'geometry_alpha_multicondition_control_module'),
            'PENDING_DISPATCH: explicit new control route not integrated; no project created')
    require(O.plain_name(run_id) and 'fixture' not in run_id.lower(), 'new nonfixture run ID required')
    runner = Path(runner or ROOT/'scripts/tcad.py').resolve()
    require(runner == (ROOT/'scripts/tcad.py').resolve() and runner.is_file(), 'original runner required')
    allowed = (ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-multicondition-controls-r1').resolve()
    target = Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'fixture' not in str(target).lower(),
            'new allowed input directory required')
    request = obj(encoded(request))
    reference = request['reference_alpha_request']
    for name in ('d2_source_run', 'base_d2_source_run', 'matched_a0_run', 'alpha_projection_package'):
        reference[name] = str(Path(reference[name]).resolve())
    require(run_id not in (O.source_name(reference['d2_source_run']), O.source_name(reference['matched_a0_run'])),
            'new signal identity must differ from all real producers')
    payload = candidate_payload(request)
    files, originals = dict(payload['files']), payload['imports']
    match, matched = payload['match'], payload['matched_a0']
    role = role_id(request)
    cfg = dict(match['cfg'])
    cfg.pop('parameterized_operating_branch')
    cfg.pop('parameterized_operating_binding_sha256')
    cfg.update(role_id=role, run_id=run_id, source_branch=BRANCH,alpha_design_condition=R.design_condition(reference),
               source_run_directory=reference['d2_source_run'],
               base_source_run_directory=reference['base_d2_source_run'], execution_enabled=True, synthetic=False)
    R.request_matches(reference, match['verified']['operation_timing'], matched, cfg)
    bundle = P.source_bundle(target, cfg)
    require(bundle['mesh_sha256'] == match['cfg']['mesh_sha256']
            and bundle['d2_source_binding_sha256'] == match['cfg']['d2_source_binding_sha256'],
            'actual signal/A0 source pair differs')
    files.update(bundle['generated_files'])
    original_identity = {n:{k:v for k,v in row.items() if k != 'path'} for n,row in originals.items()}
    _add_declarations(files, cfg, request, match, matched, original_identity)
    spec = dict(schema='dram-see-v4-continuous-project-r1', name='v4-2d-'+role.lower(), role=role,
        execution_enabled=True, runner='original scripts/tcad.py', native_threads=1, native_cores=1,
        s2_geometry=cfg, steps=[dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))])
    files.update({
        'project.json':encoded(spec),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
            observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction', synthetic=False, role_ids=[role],
            instruction='已授权冻结设计参数下真实同条件同variant同bit D2/A0匹配的α控制输入；原父能量账与控制幅值账分开，zero/half按原节点缩放，split逐父段原节点二分，原runner/owner/共享锁串行单核单线程。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-alpha-multicondition-control-input-provenance-r1',
            run_id=run_id, role=role, matched_a0=matched, reference_main_runtime_sha256=MAIN_SHA,
            control_transform_sha256=file_sha(__file__),
            logical_control_manifest_sha256=sha(files[PREFIX+'input-output-manifest.json']),
            native_representation_sha256=sha(files[REPRESENTATION_FILE]),
            host_original_A0_chain_and_metrics_replayed=True, host_control_mathematics_replayed=True,
            new_time_or_gate_selected_by_generator=False, actual_root_identity_never_aliased=True,
            logical_guest_view_mapping=LOGICAL_VIEW_MAPPING, native_run_completed=False,
            source_free_deck_byte_identical=True, half_device_response_linearity_required=False,
            independent_split_control_qualified=False, native_source_qualified=False, training_admitted=False)),
    })
    for name in ('geometry_bridge.py', 'case_contract.py', 'mesh_resource_guard.py'):
        files[name] = (HERE/name).read_bytes()
    files['generator-prepare_case.py'] = (HERE/'prepare_case.py').read_bytes()
    hashes = {n:sha(v) for n,v in files.items()}
    for name, h in bundle['exports'].items():
        require(name not in hashes or hashes[name] == h, 'actual D2 export collision: '+name)
        hashes[name] = h
    for name, row in originals.items():
        require(name not in hashes, 'actual A0 original import collision: '+name)
        hashes[name] = row['sha256']
    files['input-manifest.json'] = encoded(dict(schema='dram-see-v4-continuous-inputs-r1',
        run_id=run_id, role_id=role, files_sha256=hashes))
    runner_sha = D.file_sha(runner)
    files['execution-context.json'] = encoded(dict(schema='dram-see-v4-continuous-run-context-r1',
        run_id=run_id, role_id=role, producer_run_id=cfg['producer_run_id'], synthetic=False,
        expected_runner_sha256=runner_sha, input_manifest_sha256=sha(files['input-manifest.json']),
        authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        bridge.geometry_write(target/name, raw)
    for name, row in originals.items():
        require(file_sha(row['path']) == row['sha256'], 'original matched A0 changed while preparing')
        destination = target/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Path(row['path']).open('rb') as inp, destination.open('xb') as out:
            for block in iter(lambda: inp.read(1048576), b''):
                out.write(block)
        require(file_sha(destination) == row['sha256'], 'original A0 copy differs')
    bridge.geometry_stage_reuse(target, cfg)
    bridge.geometry_admit(target, spec, runner_sha)
    return dict(project=str(target), run_id=run_id, role_id=role, matched_a0=matched,
        operation_timing_sha256=cfg['operation_timing_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']),
        control_binding_sha256=cfg['parameterized_alpha_multicondition_control_binding_sha256'],
        control_runtime_sha256=cfg['parameterized_alpha_multicondition_control_runtime_sha256'],
        native_representation_sha256=sha(files[REPRESENTATION_FILE]), native_submissions=0,
        independent_split_control_qualified=False, native_source_qualified=False, training_admitted=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(encoded(prepare(obj(args.request.read_bytes()), args.run_id, output=args.output)).decode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
