"""Versioned complete-event proton controls for six development conditions.

No root role aliases. Host replays original BCAT/source mathematics; Python3.6
guest replays original evidence and exact linear source representation only.
Control amplitudes do not change mother G4 energy or independent event count.
"""
import copy
from decimal import Decimal,localcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
MAIN_SHA = '6e2f0b65afb8c95d0bbd51d7c6f98ed10d1294511f008e3baa26bc429c5895bb'
CONTROL_SHA="adc3dc95488cfc476512ffd46b7008d3b7ae1d3b24f84c5e5af5b484b6061063"
BRANCH='dram-see-v4-source-segment-frames-proton-control-2d-r1'
REQUEST_SCHEMA='dram-see-v4-source-segment-frames-proton-control-request-r1'
BINDING_SCHEMA='dram-see-v4-source-segment-frames-proton-control-binding-r1'
SPEC_SCHEMA='dram-see-v4-source-segment-frames-proton-control-source-spec-r1'
ROLE_SCHEMA='dram-see-v4-source-segment-frames-proton-control-role-r1'
TIME_SCHEMA='dram-see-v4-source-segment-frames-proton-control-native-time-r1'
SOURCE_CONTRACT_SCHEMA='dram-see-v4-source-segment-frames-proton-control-source-contract-r1'
SCHEMA='dram-see-v4-proton-multicondition-source-math-controls-r1'
CONTROL_MANIFEST='proton-control-input-manifest.json'
CONTROL_PREFIX='proton-multicondition-controls/'
CONTROL_CASES={'Z':'zero','H':'half','split':'split'}
CONTROLS=('zero','half','split')
CONTROL_FILES=('projection-sources3d.dat','projection-context.dat','source-terms.json',
    'parent-child-map.json','input-only-linear-reference.json','control-contract.json')
_MODULES={}
def require(ok,message):
    if not ok:raise ValueError('Multicondition proton controls: '+message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'JSON object required');return value
def number(value):return type(value) in (int,float) and math.isfinite(value)
def module(name,expected=None,family='device'):
    path=HERE/name if family=='device' else HERE.parent/family/name
    require(path.is_file() and not path.is_symlink(),'missing fixed local source: '+name)
    raw=path.read_bytes();require(expected is None or sha(raw)==expected,'fixed source changed: '+name)
    key=(str(path),sha(raw))
    if key not in _MODULES:
        spec=importlib.util.spec_from_file_location('_multi_proton_control_'+name.replace('.','_'),str(path))
        value=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),value.__dict__);_MODULES[key]=value
    return _MODULES[key]
M=module('source_segment_frames_proton_2d.py',MAIN_SHA)
a0_api=M.a0_api
baseline_api=M.baseline_api
protocol_api=M.protocol_api
matched_a0_identity=M.matched_a0_identity
SHARED=M.SHARED
A0_BINDING_FILE=M.A0_BINDING_FILE
shared=M.shared
native_api=M.M.native_api
source_api=M.M.source_api
host_api=M.host_api
activation_api=M.activation_api
table_bytes=M.table_bytes
context_bytes=M.context_bytes
event_coverage=M.event_coverage
render_signal=M.render_signal
source_free_deck=M.source_free_deck
frozen_operation=M.frozen_operation
_operation_originals=M._operation_originals
_prefixed_files=M._prefixed_files
frozen_activation=M.frozen_activation
CompositeReader=M.CompositeReader
event_ids=M.event_ids
DEVELOPMENT=M.DEVELOPMENT
REQUEST_FIELDS=M.REQUEST_FIELDS
FROZEN_RESULT_KEYS=(M.FROZEN_RESULT_KEYS-{'proton_binding'})|{'proton_control_binding'}
RUNTIME_FILES=M.RUNTIME_FILES+('source_segment_frames_proton_controls_2d.py',)
ALPHA_SHA,ACTIVATION_SHA=M.ALPHA_SHA,M.ACTIVATION_SHA
NATIVE_SHA,SOURCE_PREPARER_SHA=M.NATIVE_SHA,M.SOURCE_PREPARER_SHA
MULTI_NATIVE_SHA=M.MULTI_NATIVE_SHA
PMI_CPP_SHA,PMI_MATH_SHA,PMI_HEADER_SHA=M.PMI_CPP_SHA,M.PMI_MATH_SHA,M.PMI_HEADER_SHA
SIGMA,WIDTH_UM,SUPPORT_SIGMA=M.SIGMA,M.WIDTH_UM,M.SUPPORT_SIGMA
A0_PREFIX,TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX=M.A0_PREFIX,M.TRANSPORT_PREFIX,M.BUILD_PREFIX,M.PMI_PREFIX
BATCH_PREFIX,SOURCE_PREFIX=M.BATCH_PREFIX,M.SOURCE_PREFIX
ACTIVATION_PREFIX,FRAGMENTS,LIBRARY=M.ACTIVATION_PREFIX,M.FRAGMENTS,M.LIBRARY
SOURCE_FILES,CURRENT_DIAGNOSTIC=M.SOURCE_FILES,M.CURRENT_DIAGNOSTIC
HOST_SOURCES=dict(M.HOST_SOURCES)
HOST_SOURCES['prepare_proton_controls.py']=('projection2d',CONTROL_SHA)
NUMERIC_KEYS=('original_positive_Si_charge_fC','outside_y_strip_fC','inside_strip_outside_xz_box_fC',
    'inside_strip_box_non_silicon_fC','response_silicon_outside_time_window_fC','accepted_fC',
    'accepted_Mx_relative_fC_um','accepted_Mz_relative_fC_um','accepted_Mt_relative_fC_ps',
    'accepted_Mx_absolute_fC_um','accepted_Mz_absolute_fC_um','charge_partition_residual_fC')
FIVE_DESTINATIONS=NUMERIC_KEYS[1:6]
HEADER_SHA=PMI_HEADER_SHA


ENTRYPOINT_FILE='prepare_source_segment_frames_case.py'
ENTRYPOINT_SHA = 'a7e7d5defbb92a01ccf35cfafbb13caf6cf03c070f3462ca530e98c77b957058'
GENERATION_FILE='input-generation-binding.json'
GENERATION_SCHEMA='dram-see-v4-source-segment-frames-proton-input-generation-r1'

def entrypoint_bytes():
    path=HERE/ENTRYPOINT_FILE;raw=path.read_bytes()
    require(not path.is_symlink() and sha(raw)==ENTRYPOINT_SHA,'fixed new input entry changed')
    return raw

def generation_record(request,input_entry=None):
    """Record the actual caller route; None is direct runtime API, not a CLI claim."""
    runtime_path=Path(__file__).resolve();runtime_raw=runtime_path.read_bytes()
    if input_entry is None:
        entry_path=runtime_path;entry_raw=runtime_raw;mode='direct_runtime_API'
    else:
        supplied=Path(input_entry)
        require(not supplied.is_symlink() and supplied.resolve()==(HERE/ENTRYPOINT_FILE).resolve(),
            'input_entry must be the exact fixed local unified entry')
        entry_path=supplied.resolve();entry_raw=entrypoint_bytes();mode='unified_source_segment_frames_entry'
    return dict(schema=GENERATION_SCHEMA,entry_mode=mode,
        entry_kind='direct_runtime_API' if input_entry is None else 'unified_prepare',invocation_entry_path=str(entry_path),
        entry_file=entry_path.name,entry_sha256=sha(entry_raw),renderer_file=runtime_path.name,
        renderer_sha256=sha(runtime_raw),route=BRANCH,source_branch=BRANCH,request_schema=REQUEST_SCHEMA,
        controlled_request_sha256=sha(encoded(request)),
        fixed_unified_entry_snapshot=dict(file=ENTRYPOINT_FILE,sha256=ENTRYPOINT_SHA),
        legacy_generator_prepare_case_snapshot_is_active_entry=False,
        native_scheduler='original scripts/tcad.py',input_generation_does_not_schedule_native=True)

def verify_generation(reader,cfg,request):
    """Hash original input bytes only; never execute any archived entry code."""
    raw=reader.read(GENERATION_FILE);value=obj(raw)
    require(cfg.get('input_generation_binding_sha256')==sha(raw),'actual input generation binding differs')
    require(value.get('schema')==GENERATION_SCHEMA and value.get('route')==BRANCH and value.get('source_branch')==BRANCH
        and value.get('request_schema')==REQUEST_SCHEMA
        and value.get('controlled_request_sha256')==reader.digest('controlled-request.json')==sha(encoded(request)),
        'actual input generator route/request differs')
    mode=value.get('entry_mode');runtime_file=Path(__file__).name
    require(mode in ('direct_runtime_API','unified_source_segment_frames_entry'),'unknown entry mode')
    require(value.get('entry_kind')==('direct_runtime_API' if mode=='direct_runtime_API' else 'unified_prepare'),'entry kind/mode differ')
    selected=runtime_file if mode=='direct_runtime_API' else ENTRYPOINT_FILE
    require(value.get('entry_file')==selected and value.get('entry_sha256')==reader.digest(selected)
        and value.get('renderer_file')==runtime_file and value.get('renderer_sha256')==reader.digest(runtime_file),
        'actual entry/renderer bytes differ')
    require(reader.digest(ENTRYPOINT_FILE)==ENTRYPOINT_SHA and value.get('fixed_unified_entry_snapshot')==dict(file=ENTRYPOINT_FILE,sha256=ENTRYPOINT_SHA),
        'fixed unified entry snapshot differs')
    require(isinstance(value.get('invocation_entry_path'),str) and value['invocation_entry_path'].replace('\\','/').rsplit('/',1)[-1]==selected,
        'actual invocation filename differs')
    expected=generation_record(request,None)
    for name in ('entry_mode','entry_kind','invocation_entry_path','entry_file','entry_sha256'):
        expected[name]=value[name]
    require(value==expected,'unknown or changed input-generation statement')
    return value

def prepare_contract(input_entry):
    if input_entry is None:return None
    # Validate before the known local entry is executed. No callback is accepted.
    generation_record({},input_entry)
    entry=module(ENTRYPOINT_FILE,ENTRYPOINT_SHA)
    return entry.contract_api()


def _parent_shape(request):
    value=copy.deepcopy(request);value.update(schema=M.REQUEST_SCHEMA,source_case='Aproton');return value
def validate_request(request):
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS and request.get('schema')==REQUEST_SCHEMA,
        'exact versioned multicondition control request required')
    case=request.get('source_case');require(case in CONTROL_CASES,'explicit Z/H/split required')
    r=M.validate_request(_parent_shape(request));r.update(schema=REQUEST_SCHEMA,source_case=case);return r
def parent_request(request):return M.validate_request(_parent_shape(validate_request(request)))
def role_id(request):
    r=validate_request(request)
    return 'B2D-{}-proton-source-segment-frames-control-r1-main-g{}-p{}-a{}-b{}-e{}'.format(
        r['source_case'],r['gate_top_depth_nm'],r['energy_MeV'],r['theta_deg'],r['stored_bit'],r['event_id'])
def dependency_status(request):
    r=validate_request(request);value=M.dependency_status(parent_request(r))
    value.update(schema=BRANCH+'-dependency-status',source_case=r['source_case'],
        control_package_is_derived_from_actual_parent=True,independent_new_physical_events=0);return value
def _runtime_bytes():
    result=M._runtime_bytes()
    require(sha(result['source_segment_frames_proton_2d.py'])==MAIN_SHA,'original main runtime changed')
    result['source_segment_frames_proton_controls_2d.py']=Path(__file__).read_bytes()
    require(set(result)==set(RUNTIME_FILES),'closed guest runtime differs');return result
def verify_matched_a0(reader,manifest,inputs,request):
    return M.verify_matched_a0(reader,manifest,inputs,parent_request(request))
def request_matches(request,match,identity):
    return M.request_matches(parent_request(request),match,identity)
def source_time_contract(device,timing,request,sources):
    value=M.source_time_contract(device,timing,parent_request(request),sources)
    value.update(schema=TIME_SCHEMA,configured_source_case=request['source_case'],
        original_parent_support_preserved=True);return value
def validate_control_term(term):
    values=term['p0_um']+term['p1_um']+[term[k] for k in ('t0_s','t1_s','charge_fC','width_um','sigma_s')]
    require(len(term['p0_um'])==len(term['p1_um'])==3 and all(number(v) for v in values)
        and term['t1_s']>=term['t0_s']>=0 and term['charge_fC']>0
        and term['width_um']==WIDTH_UM and term['sigma_s']==SIGMA,
        'actual parent/child Gaussian parameters differ or are invalid')

def flags():
    return dict(is_native_result=False, native_source_qualified=False,
                pmi_r12_fixed=False, scientific_evidence_verified=False, training_admitted=False)


def exact_decimal(rational):
    # Binary64 values and division by two have only powers of two in their
    # denominators. This precision retains even a subnormal's exact decimal.
    with localcontext() as context:
        context.prec = 1100
        return str(Decimal(rational.numerator) / Decimal(rational.denominator))


def table_vector(term):
    return term["p0_um"] + term["p1_um"] + [
        term["t0_s"], term["t1_s"], term["charge_fC"], term["width_um"], term["sigma_s"]]


def control_event(control, source, parent_ledger, context_raw, timing, request, timing_sha):
    """Exact source-charge construction; reference integrals follow linearity."""
    require(control in CONTROLS, "unknown control")
    r=validate_request(request);parent_count=len(source["terms"]);ids=event_ids(r)
    amplitude = {"zero": 0., "half": .5, "split": 1.}[control]
    copies = {"zero": 0, "half": 1, "split": 2}[control]
    terms, mapping, child_rows, contributions = [], [], [], []
    by_uid = {row["uid"]: row for row in parent_ledger["rows"]}
    for parent in source["terms"]:
        child_uids = []
        exact_sum = Fraction(0)
        for index in range(copies):
            child = copy.deepcopy(parent)
            child["uid"] = parent["uid"] + "::" + control + ":" + str(index)
            child["charge_fC"] = parent["charge_fC"] / 2
            require(child["charge_fC"] > 0 and child["charge_fC"] * 2 == parent["charge_fC"],
                    "half charge not exactly representable; do not clip/drop source")
            validate_control_term(child)
            child.update(parent_uid=parent["uid"], representation_copy_index=index,
                control_weight=dict(numerator=1, denominator=2), new_physical_step=False)
            terms.append(child)
            child_uids.append(child["uid"])
            exact_sum += Fraction.from_float(child["charge_fC"])
            parent_row = by_uid[parent["uid"]]
            child_rows.append(dict(
                {k: parent_row[k] / 2 for k in NUMERIC_KEYS},
                uid=child["uid"], parent_uid=parent["uid"],
                raw_deposition_outside_window=parent_row["raw_deposition_outside_window"],
                zero_length_preserved=parent_row["zero_length_preserved"],
                derived_by_fixed_kernel_linearity=True))
        expected = Fraction.from_float(parent["charge_fC"]) * Fraction.from_float(amplitude)
        require(exact_sum == expected, "parent-child source charge relation differs")
        mapping.append(dict(parent_uid=parent["uid"], original_identity=parent["identity"],
            original_positive_Si_charge_fC=parent["charge_fC"], child_uids=child_uids,
            source_weight_sum=amplitude,
            exact_child_charge_sum_fC_binary64_decimal=exact_decimal(exact_sum),
            exact_scaled_parent_charge_fC_binary64_decimal=exact_decimal(expected),
            original_kernel_retained_in_parent_file=True,
            zero_parent_mapping_retained_without_illegal_zero_charge_row=control == "zero"))
        parent_row = by_uid[parent["uid"]]
        contributions.append(dict(parent_uid=parent["uid"], child_uids=child_uids,
            **{k: parent_row[k] * amplitude for k in NUMERIC_KEYS}))
    canonical = sorted(terms, key=table_vector)
    positions = {term["uid"]: index + 2 for index, term in enumerate(canonical)}
    for row in mapping:
        row["child_table_lines_including_header"] = [positions[uid] for uid in row["child_uids"]]
    table = table_bytes(terms)
    require(int(table.splitlines()[0].split()[1]) == parent_count * copies,
            "canonical table count differs")
    if control == "zero":
        require(table == b"NUCLEAR_CLOSURE_SOURCE_V1 0\n", "zero must use existing legal empty-table format")
    totals = {key: math.fsum(row[key] for row in child_rows) for key in NUMERIC_KEYS}
    scaled = {key: parent_ledger["totals"][key] * amplitude for key in NUMERIC_KEYS}
    deltas = {key: totals[key] - scaled[key] for key in NUMERIC_KEYS}
    exact_totals = {key: exact_decimal(Fraction.from_float(parent_ledger["totals"][key]) *
                                     Fraction.from_float(amplitude)) for key in NUMERIC_KEYS}
    q = totals["accepted_fC"]
    ledger = dict(schema=SCHEMA + "-linear-reference", control=control, amplitude=amplitude,
        event_id=source["event_id"], original_event_count=len(ids), parent_positive_kernel_count=parent_count,
        represented_kernel_count=len(terms), rows=child_rows, all_parent_contributions=contributions,
        totals=totals, five_charge_destination_keys=list(FIVE_DESTINATIONS),
        complete_physical_time_window_s=timing["simulation_window_s"],
        native_observation_window_s=timing["native_observation_window_s"],
        mathematical_ledger_window="Original index.complete_window_s; not relabelled as the actual observation integral",
        original_parent_totals=parent_ledger["totals"], scaled_parent_totals=scaled,
        exact_scaled_parent_totals_from_binary64_decimal=exact_totals,
        binary64_total_deltas_from_scaled_parent=deltas,
        all_binary64_total_deltas_zero=all(v == 0 for v in deltas.values()),
        original_parent_offline_charge_gate_fC=parent_ledger["offline_charge_gate_fC"],
        parent_quadrature_residual_retained=True, new_quadrature_performed=False,
        error_propagation="Existing parent quadrature errors scale linearly; duplicates do not create independent accuracy evidence",
        centroids=dict(physical_x_um=totals["accepted_Mx_absolute_fC_um"] / q if q else None,
            physical_z_um=totals["accepted_Mz_absolute_fC_um"] / q if q else None,
            time_s=timing["source_epoch_s"] + totals["accepted_Mt_relative_fC_ps"] / q * 1e-12 if q else None),
        actual_clock=None, **flags())
    contract = dict(schema=SCHEMA + "-event-contract", control=control, event_id=source["event_id"],
        seed=source["seed"], particle="proton", energy_MeV=source["energy_MeV"], angle_deg=source["angle_deg"], condition_id=r["condition_id"],
        amplitude=amplitude, source_explicitly_configured=True,
        source_terms_present=bool(terms), parent_kernel_count=parent_count, represented_source_count=len(terms),
        independent_physical_event=False, secondary_or_hadronic_process_inferred=False,
        source_terms_are_mathematical_representation_not_raw_G4_steps=True,
        original_physical_identity_per_copy_unchanged=True, half_device_response_linearity_required=False,
        all_original_step_records_retained=True, original_step_count=len(source["step_records"]),
        original_raw_ns_kept=True, epoch_addition_count=1, epoch_s=timing["source_epoch_s"],
        complete_physical_time_window_s=timing["simulation_window_s"],
        native_observation_window_s=timing["native_observation_window_s"],
        operation_timing_sha256=timing_sha, context_sha256=sha(context_raw),
        units=dict(position="um", table_time="s", original_G4_time="ns", source_charge="fC",
                   width="um", sigma="s", generation2d="cm^-3 s^-1", effective_width="20 nm"),
        parser_compatibility=dict(source_header="NUCLEAR_CLOSURE_SOURCE_V1",
            columns=11, charge_positive_for_nonempty_rows=True, zero_count_supported=True,
            equal_canonical_rows_supported=True, parser_sha256=HEADER_SHA,
            basis="Fixed original C++ load source; actual loading of these controls not executed"),
        mathematics=dict(
            generation_relation={"zero": "G_control=0", "half": "G_control=G_parent/2",
                                 "split": "G_control=sum_j(G_j/2+G_j/2)=G_parent"}[control],
            unchanged=["positions", "all physical y", "time endpoints", "width", "sigma",
                       "Si mask", "complete context", "native observation contract", "original energy ledger"],
            source_equations=["kernel.step_integrals multiplies vector by q after q-independent quadrature",
                              "kernel.generation2d and projection_r14::average_step are linear in charge",
                              "projection_r14::average sums every input term; eta=G/reference_rate"],
            existing_reference_rate_cm_minus3_s_minus1=1e35,
            no_source_renormalization=True, native_roundoff_not_claimed_identical=True),
        original_parent_event_sha256=sha(encoded(source)),original_parent_energy_unscaled=True,
        configured_source_amplitude_is_not_incident_energy_scaling=True,formal_project_created=False,
        **flags())
    return {
        "projection-sources3d.dat": table,
        "projection-context.dat": context_raw,
        "source-terms.json": encoded(dict(schema=SCHEMA + "-represented-terms", terms=canonical, **flags())),
        "parent-child-map.json": encoded(dict(schema=SCHEMA + "-UID-map", event_id=source["event_id"],
            original_positive_parent_UIDs=[p["uid"] for p in source["terms"]],
            mapping=mapping, original_raw_step_count=len(source["step_records"]), **flags())),
        "input-only-linear-reference.json": encoded(ledger),
        "control-contract.json": encoded(contract),
    }



def control_package_files(request):
    ids=event_ids(validate_request(request))
    return {CONTROL_MANIFEST,'parent-bindings.json','control-input-index.json','parents/operation-timing.json'}|{
        c+'/event-'+str(i)+'/'+n for c in CONTROLS for i in ids for n in CONTROL_FILES}

def derive_controls(sources,ledgers,index,timing_raw,request,parent_identities):
    """Exact existing source-weight algebra, never another source quadrature."""
    r=validate_request(request);ids=event_ids(r);timing=obj(timing_raw)
    require([s['event_id'] for s in sources]==ids and len(ledgers)==len(ids)
        and [v['event_id'] for v in index['events']]==ids and index['omitted_event_ids']==[],
        'all original events and source ledgers required')
    require(index['complete_window_s']==r['simulation_window_s']==timing['simulation_window_s']
        and timing['source_epoch_s']==r['source_epoch_s'],'complete mathematical ledger/time differs')
    require(index['batch_binding']['original_request_event_ids']==ids
        and index['batch_binding']['seed']==r['transport_seed'],'original seed/request denominator differs')
    require(sha(timing_raw)==r['operation_timing_sha256'],'actual selected timing bytes differ')
    packet={'parents/operation-timing.json':timing_raw};entries=[]
    steps=0;empty=0
    for source,ledger in zip(sources,ledgers):
        require(source['seed']==r['transport_seed'] and source['energy_MeV']==r['energy_MeV']
            and source['angle_deg']==r['theta_deg'] and source['epoch_s']==r['source_epoch_s']
            and source['all_selected_event_steps_retained'] is True
            and source['context']['original_request_denominator']==ids,'actual parent identity differs')
        records={row['uid']:row for row in source['step_records']}
        terms={term['uid']:term for term in source['terms']}
        rows={row['uid']:row for row in ledger['rows']}
        require(len(records)==len(source['step_records']) and len(terms)==len(source['terms'])
            and len(rows)==len(ledger['rows']) and set(rows)==set(terms)<=set(records),
            'complete original raw-step/positive-kernel/reference UID denominator differs')
        for term in source['terms']:
            validate_control_term(term)
            require(term['identity']==records[term['uid']]['identity']
                and rows[term['uid']]['original_positive_Si_charge_fC']==term['charge_fC'],
                'source mother identity/charge mapping differs')
        for key in NUMERIC_KEYS:
            require(math.fsum(row[key] for row in ledger['rows'])==ledger['totals'][key],
                'original per-kernel totals differ: '+key)
        steps+=len(records)
        empty+=sum(row['original_native_step']['local_ionizing_MeV_per_um']=='' for row in records.values())
        for control in CONTROLS:
            prefix=control+'/event-'+str(source['event_id'])+'/'
            files=control_event(control,source,ledger,context_bytes(r['simulation_window_s']),timing,r,sha(timing_raw))
            packet.update({prefix+n:raw for n,raw in files.items()})
            entries.append(dict(control=control,original_event_id=source['event_id'],prefix=prefix,
                original_parent_kernels=len(source['terms']),
                represented_kernels=obj(files['control-contract.json'])['represented_source_count']))
    parent=dict(schema=SCHEMA+'-parents',original_event_ids=ids,original_event_count=len(ids),
        batch_binding=index['batch_binding'],source_index_sha256=sha(encoded(index)),
        original_parent_files=parent_identities,operation_timing_sha256=sha(timing_raw),
        original_math_window_s=index['complete_window_s'],actual_observation_window_s=timing['native_observation_window_s'],
        raw_G4_energy_unchanged=True,new_independent_events=0)
    packet['parent-bindings.json']=encoded(parent)
    packet['control-input-index.json']=encoded(dict(schema=SCHEMA+'-index',
        condition_id=r['condition_id'],seed=r['transport_seed'],original_request_event_ids=ids,
        original_event_denominator=len(ids),original_step_denominator=steps,
        original_empty_LET_denominator=empty,entries=entries,no_event_filter=True,
        three_representations_do_not_multiply_physical_event_count=True))
    manifest=dict(schema=SCHEMA+'-manifest',implementation_sha256=sha(Path(__file__).read_bytes()),
        original_control_algebra_sha256=CONTROL_SHA,main_runtime_sha256=MAIN_SHA,host_adapter_sha256=MULTI_NATIVE_SHA,
        files={n:dict(sha256=sha(raw),size_bytes=len(raw)) for n,raw in packet.items()},**flags())
    packet[CONTROL_MANIFEST]=encoded(manifest)
    require(set(packet)==control_package_files(r),'derived control inventory differs')
    return packet

def _parent_file_identities(batch_files,source_files):
    return {prefix+n:dict(sha256=sha(raw),size_bytes=len(raw))
        for prefix,group in ((BATCH_PREFIX,batch_files),(SOURCE_PREFIX,source_files)) for n,raw in group.items()}

def _source_package_host(batch,source_folder,match,request):
    r=validate_request(request)
    result=M._source_package_host(batch,source_folder,match,parent_request(r))
    source_files=result['source_files'];index=obj(source_files['all-event-source-inputs.json'])
    ledgers=[obj(source_files['event-'+str(i)+'/input-only-projection-reference.json']) for i in event_ids(r)]
    packet=derive_controls(result['replay']['sources'],ledgers,index,match['shared']['operation-timing.json'],r,
        _parent_file_identities(result['batch_files'],source_files))
    prefix=CONTROL_CASES[r['source_case']]+'/event-'+str(r['event_id'])+'/'
    result.update(control_files=packet,selected_files={n:packet[prefix+n] for n in CONTROL_FILES})
    return result

class ParentSourceView:
    """Two mathematical data names only; never rewrites root role or request."""
    def __init__(self,reader,request):self.reader=reader;self.prefix=SOURCE_PREFIX+'event-'+str(request['event_id'])+'/'
    def read(self,name):
        return self.reader.read(self.prefix+name if name in ('projection-sources3d.dat','projection-context.dat') else name)
    def digest(self,name):
        return sha(self.read(name)) if name in ('projection-sources3d.dat','projection-context.dat') else self.reader.digest(name)
    def size(self,name):
        return len(self.read(name)) if name in ('projection-sources3d.dat','projection-context.dat') else self.reader.size(name)
    def stream(self,name):return self.reader.stream(name)
    def exists(self,name):return self.reader.exists(name)

def frozen_sources(reader,request,match,operations):
    r=validate_request(request);ids=event_ids(r)
    parent,_=M.frozen_sources(ParentSourceView(reader,r),parent_request(r),match,operations)
    batch_names={'adapter-manifest.json','native-batch-binding.json','replay-request.json'}|{
        'event-'+str(i)+'-g3-source.json' for i in ids}
    source_names={'candidate-input-manifest.json','input-hashes.sha256','all-event-source-inputs.json'}|{
        'event-'+str(i)+'/'+n for i in ids for n in SOURCE_FILES}
    batches={n:reader.read(BATCH_PREFIX+n) for n in batch_names}
    sources={n:reader.read(SOURCE_PREFIX+n) for n in source_names}
    ledgers=[obj(sources['event-'+str(i)+'/input-only-projection-reference.json']) for i in ids]
    packet=derive_controls(parent['sources'],ledgers,parent['index'],reader.read('operation-timing.json'),r,
        _parent_file_identities(batches,sources))
    for name,raw in packet.items():require(reader.read(CONTROL_PREFIX+name)==raw,'actual control linear replay differs: '+name)
    prefix=CONTROL_CASES[r['source_case']]+'/event-'+str(r['event_id'])+'/'
    for name in ('projection-sources3d.dat','projection-context.dat'):
        require(reader.read(name)==packet[prefix+name],'active control table differs from exact child relation')
    selected={n:packet[prefix+n] for n in CONTROL_FILES}
    control=dict(manifest=obj(packet[CONTROL_MANIFEST]),index=obj(packet['control-input-index.json']),
        parent_binding=obj(packet['parent-bindings.json']),selected_contract=obj(selected['control-contract.json']),
        selected_uid_map=obj(selected['parent-child-map.json']),selected_ledger=obj(selected['input-only-linear-reference.json']),
        selected_terms=obj(selected['source-terms.json']),selected_prefix=prefix,
        guest_control_linear_relation_replayed=True,guest_original_source_quadrature_replayed=False)
    result=dict(parent,selected_parent_ledger=parent['selected_ledger'],
        selected_ledger=control['selected_ledger'],control=control)
    return result,source_time_contract(match['device'],match['verified']['operation_timing'],r,parent['sources'])

def source_contract(request, projected, operations, timing):
    r=request;selected=projected['sources'][r['event_id']]
    return dict(schema=SOURCE_CONTRACT_SCHEMA,particle='proton',dimension=2,
        gate_top_depth_nm=r['gate_top_depth_nm'],sn_junction_depth_nm=87,
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],source_family='weighted-control-of-complete-native-BCAT-event',event_id=r['event_id'],
        seed=r['transport_seed'],original_request_event_ids=event_ids(r),original_request_event_count=r["original_event_count"],
        condition_id=r["condition_id"],energy_MeV=r["energy_MeV"],theta_deg=r["theta_deg"],phi_deg=180,energy_definition='original G4 gun kinetic energy; retain original TOF and all deposited-energy accounts',
        full_simulation_window_s=r['simulation_window_s'],source_epoch_s=r['source_epoch_s'],
        native_observation_window_s=r['native_observation_window_s'],charge_window_s=r['charge_window_s'],
        temporal_sigma_s=SIGMA,spatial_width_um=WIDTH_UM,effective_width_nm=20,
        source_context_window_s=r['simulation_window_s'],required_source_window_s=timing['all_event_time_inventory'][r['event_id']]['required_8sigma_observation_s'],
        selected_source_rows=projected['control']['selected_contract']['represented_source_count'],
        configured_zero=(r['source_case']=='Z'),original_parent_is_structural_zero=not selected['terms'],
        control_package_manifest_sha256=sha(encoded(projected["control"]["manifest"])),
        control_contract=projected['control']['selected_contract'],
        original_five_destination_ledger=projected['selected_parent_ledger'],
        controlled_linear_ledger=projected['selected_ledger'],
        independent_physical_event_count=r["original_event_count"],half_device_linearity_required=False,
        original_positive_Si_charge_fC=selected['original_positive_Si_charge_fC'],
        complete_batch_binding_sha256=sha(encoded(projected['binding'])),
        actual_transport_operation_sha256=operations['transport']['receipt_sha256'],
        actual_transport_archive_sha256=operations['transport']['archive_sha256'],
        actual_PMI_build_operation_sha256=operations['pmi']['receipt_sha256'],
        actual_PMI_library_sha256=operations['pmi']['library_sha256'],
        reference_rate_cm_minus3_s_minus1=1e35,source_formula='fixed correlated 3D Gaussian segment -> exact y strip / 20nm -> actual BE interval average',
        source_clock='raw native PMI ReadTime/StepSize/StepType; no synthesis',additional_normalization=False,
        source_ledger_is_mathematical_input=True,native_source_qualified=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)


def binding(reader,cfg,matched,originals,projected,operations):
    r=validate_request(obj(reader.read('controlled-request.json')))
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,verifier_sha256=sha(Path(__file__).read_bytes()),
        shared_identity_implementation_sha256=ALPHA_SHA,activation_implementation_sha256=ACTIVATION_SHA,
        native_batch_adapter_sha256=MULTI_NATIVE_SHA,source_preparer_sha256=SOURCE_PREPARER_SHA,
        main_helper_sha256=MAIN_SHA,control_math_sha256=CONTROL_SHA,control_transform_sha256=sha(Path(__file__).read_bytes()),
        condition_id=r['condition_id'],gate_top_depth_nm=r['gate_top_depth_nm'],
        energy_MeV=r['energy_MeV'],theta_deg=r['theta_deg'],transport_seed=r['transport_seed'],
        control_package_manifest_sha256=reader.digest(CONTROL_PREFIX+CONTROL_MANIFEST),
        native_control_representation_sha256=reader.digest('native-control-representation.json'),
        stored_bit=cfg['stored_bit'],event_id=obj(reader.read('controlled-request.json'))['event_id'],
        source_case=obj(reader.read('controlled-request.json'))['source_case'],
        producer_run_id=cfg['producer_run_id'],mesh_sha256=reader.digest('cell_msh.tdr'),
        operation_timing_sha256=reader.digest('operation-timing.json'),numerical_relation_sha256=reader.digest('numerical-relation.json'),
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        source_frame_protocol_sha256=reader.digest('source-frame-protocol.json'),
        input_generation_binding_sha256=reader.digest(GENERATION_FILE),
        source_table_sha256=reader.digest('projection-sources3d.dat'),source_context_sha256=reader.digest('projection-context.dat'),
        complete_source_package_manifest_sha256=reader.digest(SOURCE_PREFIX+'candidate-input-manifest.json'),
        complete_batch_package_manifest_sha256=reader.digest(BATCH_PREFIX+'adapter-manifest.json'),
        activation_package_manifest_sha256=reader.digest(ACTIVATION_PREFIX+'candidate-input-manifest.json'),
        actual_PMI_library_sha256=reader.digest(LIBRARY),matched_a0=matched,original_files=originals,
        operations=operations,original_event_ids=event_ids(r),omitted_event_ids=[],
        all_event_source_rows=[len(s['terms']) for s in projected['sources']],
        guest_replay_scope='Original operation archives/inputs/exits + A0 clock/metrics + pinned complete control package/activation; G4/control math replay host-only',
        compiled_PMI_is_not_native_activation=True,source_native_activation_unverified=True,
        native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)


def source_spec(reader,r,binding_sha):
    source=obj(reader.read('source-contract.json'))
    return dict(schema=SPEC_SCHEMA,role='CONFIGURED_ZERO' if r['source_case']=='Z' else 'CONTROL',
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],particle='proton',dimension=2,stored_bit=r['stored_bit'],numerical_variant='main',
        gate_top_depth_nm=r["gate_top_depth_nm"],sn_junction_depth_nm=87,event_id=r['event_id'],seed=r['transport_seed'],
        original_request_event_ids=event_ids(r),condition_id=r["condition_id"],energy_MeV=r["energy_MeV"],theta_deg=r["theta_deg"],phi_deg=180,source_configured=True,
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),source_segment_frames_proton_control_binding_sha256=binding_sha,
        source_field='OpticalGeneration',common_pair_source=True,effective_width_applied_once=True,
        currentplot_domain='Semiconductor',currentplot_integration_unit='um',
        currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False,pmi_r12_fixed=False,scientific_evidence_verified=False,training_admitted=False,
        source_representation_is_not_native_field_proof=True)


def role_contract(match,r,binding_sha,source_sha):
    result=dict(match['role']);result.pop('source_segment_frames_operating_binding_sha256')
    result.update(schema=ROLE_SCHEMA,role=role_id(r),case=r['source_case'],source_configured=True,
        source_segment_frames_proton_control_binding_sha256=binding_sha,matched_a0_operating_binding_sha256=match['operating_binding_sha256'],
        event_id=r['event_id'],seed=r['transport_seed'],original_request_event_ids=event_ids(r),
        condition_id=r["condition_id"],energy_MeV=r["energy_MeV"],theta_deg=r["theta_deg"],phi_deg=180,source_contract_sha256=source_sha,
        native_syntax_verified=False,native_source_qualified=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)
    return result


def native_representation(reader,r):
    prefix=CONTROL_PREFIX+CONTROL_CASES[r['source_case']]+'/event-'+str(r['event_id'])+'/'
    index=obj(reader.read(CONTROL_PREFIX+'control-input-index.json'));contract=obj(reader.read(prefix+'control-contract.json'))
    return dict(schema='dram-see-v4-proton-multicondition-control-native-representation-r1',
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],event_id=r['event_id'],
        stored_bit=r['stored_bit'],role_id=role_id(r),source_branch=BRANCH,
        control_package_manifest_sha256=reader.digest(CONTROL_PREFIX+CONTROL_MANIFEST),original_event_ids=event_ids(r),
        original_step_count=index["original_step_denominator"],original_empty_LET_count=index["original_empty_LET_denominator"],parent_kernel_count=contract["parent_kernel_count"],
        active_rows=contract["represented_source_count"],
        source_table_sha256=reader.digest('projection-sources3d.dat'),
        context_sha256=reader.digest('projection-context.dat'),
        parent_child_map_sha256=reader.digest(prefix+'parent-child-map.json'),
        control_contract_sha256=reader.digest(prefix+'control-contract.json'),
        linear_reference_sha256=reader.digest(prefix+'input-only-linear-reference.json'),
        parser_sha256=PMI_HEADER_SHA,callback_sha256=PMI_CPP_SHA,math_header_sha256=PMI_MATH_SHA,
        operation_timing_sha256=reader.digest("operation-timing.json"),raw_Geant4_records_unchanged=True,
        new_physical_events=False,half_device_linearity_required=False,
        compiled_library_does_not_prove_control_activation=True,
        native_executed=False,native_source_qualified=False,scientific_evidence_verified=False,training_admitted=False)


def verify_frozen(reader,cfg):
    S=shared();P=S.parameterized();D=S.dimensional()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH
        and cfg.get('mode')=='reuse' and 'source_segment_frames_branch' not in cfg,'explicit proton source root required')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'fixed runtime differs: '+name)
    for name,(_,digest) in HOST_SOURCES.items():require(reader.digest('proton-implementations/'+name)==digest,'host replay snapshot differs')
    result,_,_=P._verify_sources(reader,cfg);r=validate_request(obj(reader.read('controlled-request.json')))
    verify_generation(reader,cfg,r)
    bound=obj(reader.read('source-segment-frames-proton-control-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('source-segment-frames-proton-control-binding.json')==cfg.get('source_segment_frames_proton_control_binding_sha256'),
        'proton binding identity differs')
    originals=bound['original_files'];expected={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    require(set(originals)==expected,'all original A0/G4/build/PMI archives required')
    for name,row in originals.items():require(row==dict(sha256=reader.digest(name),size_bytes=reader.size(name)),'original proof bytes differ: '+name)
    operations={key:frozen_operation(reader,prefix,kind) for key,prefix,kind in
        [('transport',TRANSPORT_PREFIX,'transport'),('build',BUILD_PREFIX,'bcat-build'),('pmi',PMI_PREFIX,'pmi')]}
    require(reader.digest(LIBRARY)==operations['pmi']['library_sha256'],'active library is not actual new 2D compile output')
    require(reader.read('optical.currentplot.inc')==CURRENT_DIAGNOSTIC,'full accepted G diagnostic differs')
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
        and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'),'original A0 outer identity differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as aa,tarfile.open(fileobj=i,mode='r:*') as ii:
            prior=D.ArchiveReader(aa);match=verify_matched_a0(prior,manifest,D.ArchiveReader(ii),r)
            matched=matched_a0_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            request_matches(r,match,matched)
            for name,raw in match['shared'].items():require(reader.read(name)==raw,'signal/A0 fixed physical or timing input differs: '+name)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                and reader.read('d2-source-binding.json')==prior.read('d2-source-binding.json'),'actual matching D2 mesh/source differs')
            projected,time=frozen_sources(reader,r,match,operations)
            activation=frozen_activation(reader,match,r)
    require(obj(reader.read('native-control-representation.json'))==native_representation(reader,r),'control native representation differs')
    require(reader.read('source-frame-protocol.json')==protocol_api().encoded(time['source_frame_protocol'])
        and reader.digest('source-frame-protocol.json')==cfg['source_frame_protocol_sha256'],'actual source frame protocol differs')
    require(obj(reader.read('source-time-contract.json'))==time,'full source-time statement differs')
    require(obj(reader.read('source-contract.json'))==source_contract(r,projected,operations,time),'source definition differs')
    require(bound==binding(reader,cfg,matched,originals,projected,operations),'complete original proton binding differs')
    spec=source_spec(reader,r,reader.digest('source-segment-frames-proton-control-binding.json'))
    role=role_contract(match,r,reader.digest('source-segment-frames-proton-control-binding.json'),reader.digest('source-contract.json'))
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role['role'],'proton source/role declaration differs')
    result.update(operation_timing=match['verified']['operation_timing'],operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,
        projection=projected,proton_control_binding=bound,matched_a0=matched,source_time_contract=time,
        activation=activation,pmi_build=operations['pmi'],native_batch=operations['transport'],source_frame_protocol=time['source_frame_protocol'])
    require(set(result)==FROZEN_RESULT_KEYS,'public result shape differs');return result


def require_input_coverage(reader,hashes):
    """Every consumed proof/source must be in the original runner input manifest."""
    S=shared();D=S.dimensional();r=validate_request(obj(reader.read('controlled-request.json')))
    needed={GENERATION_FILE}|set(D.SHARED_INPUTS)|set(SHARED)|set(RUNTIME_FILES)|set(obj(reader.read('d2-source-binding.json'))['original_files'])
    needed|={'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py',
        'generator-prepare_case.py','task-authorization.json','resource-policy.json','provenance.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'source-contract.json','source-time-contract.json','source-segment-frames-proton-control-binding.json','source-spec.json','role-contract.json',
        'projection-sources3d.dat','projection-context.dat',LIBRARY,'proton-reference-apd.plx','proton-reference-spectrum.txt',
        'optical.currentplot.inc'}
    needed|={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}
    needed|={p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    needed|={BATCH_PREFIX+n for n in ['adapter-manifest.json','native-batch-binding.json','replay-request.json']+
        ['event-'+str(i)+'-g3-source.json' for i in event_ids(r)]}
    needed|={SOURCE_PREFIX+n for n in ('candidate-input-manifest.json','input-hashes.sha256','all-event-source-inputs.json')}
    needed|={SOURCE_PREFIX+'event-'+str(i)+'/'+n for i in event_ids(r) for n in SOURCE_FILES}
    needed|={ACTIVATION_PREFIX+n for n in list(FRAGMENTS)+['activation-contract.json','candidate-input-manifest.json']+
        ['original/'+n for n in ('geometry-contract.json','dimensional-contract.json','operation-timing.json')]}
    needed|={'native-control-representation.json'}|{CONTROL_PREFIX+n for n in control_package_files(r)}
    needed|={'proton-implementations/'+n for n in HOST_SOURCES}
    needed|={'operation-selection/'+n for n in obj(reader.read('operation-timing.json'))['selection_provenance']['references']}
    require(needed<=set(hashes),'runner input manifest omits consumed proof/source: '+str(sorted(needed-set(hashes))))
    return needed


def admit(project,spec,runner_sha,bridge):
    project=Path(project);S=shared();O=S.operation();D=S.dimensional();cfg=spec['s2_geometry']
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),'UNIT cannot be submitted')
    r=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and spec.get('execution_enabled') is True and spec.get('role')==cfg.get('role_id')==role_id(r)
        and O.plain_name(cfg.get('run_id')) and cfg['run_id'] not in (cfg['producer_run_id'],O.source_name(r['matched_a0_run']))
        and spec.get('native_threads')==spec.get('native_cores')==1
        and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],'native role/serial pipeline differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    require_input_coverage(D.FolderReader(project),hashes)
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'submitted byte changed: '+name)
    result=verify_frozen(D.FolderReader(project),cfg)
    require(result['operation_timing']['origin']=='prescribed_input','UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'actual observations only, no resource quotas')
    return cfg


def prepare(request,run_id,runner=None,output=None,input_entry=None):
    """Create one original-runner input only after genuine complete dependency replay."""
    r=validate_request(request);S=shared();P=S.parameterized();O=S.operation();D=S.dimensional()
    C=prepare_contract(input_entry);bridge=module('geometry_bridge.py')
    require((C is None or getattr(C,'SCHEMA_2D_PROTON_SEGMENT_FRAMES_CONTROL',None)==REQUEST_SCHEMA) and hasattr(bridge,'geometry_source_segment_frames_proton_controls_module'),
        'proton dispatch not integrated; no project created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
        and run_id not in (O.source_name(r['matched_a0_run']),O.source_name(r['d2_source_run'])),'new real run ID required')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve();require(runner==(ROOT/'scripts/tcad.py').resolve(),'original runner only')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/source-segment-frames-proton-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new explicit project path required')
    for k in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation'):
        r[k]=str(Path(r[k]).resolve())
    a0=Path(r['matched_a0_run']);require(a0.is_dir() and not a0.is_symlink()
        and 'fixture' not in str(a0).lower() and not (a0/'SYNTHETIC_NOT_NATIVE').exists(),'actual A0 originals required')
    host=baseline_api().reduce_archive(a0)
    require(host.get('native_engineering_chain_verified') is True and host.get('complete_clock_evidence_verified') is True
        and host.get('candidate_functional_pass') is True,'actual matching A0 original collection/clock/five criteria required')
    manifest_raw=(a0/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    require(manifest.get('state')=='COLLECTED' and manifest.get('run_id')==a0.name,'actual A0 COLLECTED manifest required')
    originals={A0_PREFIX+n:dict(path=str(a0/n),sha256=D.file_sha(a0/n),size_bytes=(a0/n).stat().st_size)
               for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
        and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'A0 original archive mismatch')
    with tarfile.open(str(a0/'results.tar'),'r:*') as aa,tarfile.open(str(a0/'inputs.tar'),'r:*') as ii:
        match=verify_matched_a0(D.ArchiveReader(aa),manifest,D.ArchiveReader(ii),r)
    require(host['candidate_metrics']==match['metrics'],'host/guest A0 replay differs')
    matched=matched_a0_identity(match,manifest,sha(manifest_raw),originals[A0_PREFIX+'results.tar']['sha256']);request_matches(r,match,matched)
    source=_source_package_host(r['transport_batch_package'],r['pmi_source_inputs'],match,r)
    time=source_time_contract(match['device'],match['verified']['operation_timing'],r,source['replay']['sources'])
    native=source['replay']['binding'];N=native_api()
    # Reuse complete_operation for the actual new PMI build, never execute its task.
    with N.A.v1().proton_modules() as (old,_,__):
        pmi_folder,_=old.complete_operation(r['pmi_build_operation'],
            (LIBRARY,'cmi-exit-code.txt','context-exit-code.txt','native-build-sha256.txt','candidate-input-manifest.json',
             'pmi_projection_qy_r1.C','projection_pmi_math_r1.hpp','source_kernel_r12.hpp','exported-symbols.txt','linked-libraries.txt'))
    originals.update(_operation_originals(Path(native['operation']['path']).parent,TRANSPORT_PREFIX))
    originals.update(_operation_originals(Path(native['build_operation']['path']).parent,BUILD_PREFIX))
    originals.update(_operation_originals(pmi_folder,PMI_PREFIX))
    activation=activation_api().candidate_payload(match['shared']['geometry-contract.json'],match['shared']['dimensional-contract.json'],match['shared']['operation-timing.json'])
    files=dict(match['shared']);files['controlled-request.json']=encoded(r)
    files[GENERATION_FILE]=encoded(generation_record(r,input_entry))
    files.update({BATCH_PREFIX+n:v for n,v in source['batch_files'].items()})
    files.update({SOURCE_PREFIX+n:v for n,v in source['source_files'].items()})
    files.update({CONTROL_PREFIX+n:v for n,v in source['control_files'].items()})
    files.update({ACTIVATION_PREFIX+n:v for n,v in activation['files'].items()})
    files['source-time-contract.json']=encoded(time)
    for name in ('projection-sources3d.dat','projection-context.dat'):
        files[name]=source['selected_files'][name]
    for name in ('proton-reference-apd.plx','proton-reference-spectrum.txt'):files[name]=activation['files'][name]
    files['device.cmd']=render_signal(match['device'],activation['files'])
    files['optical.currentplot.inc']=CURRENT_DIAGNOSTIC
    files[LIBRARY]=(Path(pmi_folder)/'collected'/LIBRARY).read_bytes()
    role=role_id(r);cfg=dict(match['cfg']);cfg.pop('source_segment_frames_branch');cfg.pop('source_segment_frames_operating_binding_sha256')
    cfg.update(role_id=role,run_id=run_id,source_branch=BRANCH,source_run_directory=r['d2_source_run'],
        base_source_run_directory=r['base_d2_source_run'],execution_enabled=True,synthetic=False)
    cfg['input_generation_binding_sha256']=sha(files[GENERATION_FILE])
    bundle=P.source_bundle(target,cfg)
    require(bundle['mesh_sha256']==match['cfg']['mesh_sha256'] and bundle['d2_source_binding_sha256']==match['cfg']['d2_source_binding_sha256'],
        'proton/A0 real D2 source identity differs')
    files.update(bundle['generated_files']);external=dict(originals)
    # Reuse the actual A0 mesh bytes, not a rebuilt or relabelled geometry.
    with tarfile.open(str(a0/'results.tar'),'r:*') as aa:
        mesh_reader=D.ArchiveReader(aa)
        require(mesh_reader.digest('cell_msh.tdr')==cfg['mesh_sha256'],'actual matching mesh differs')
        files['cell_msh.tdr']=mesh_reader.read('cell_msh.tdr')
    check=CompositeReader(files,external)
    operations={key:frozen_operation(check,prefix,kind) for key,prefix,kind in
        [('transport',TRANSPORT_PREFIX,'transport'),('build',BUILD_PREFIX,'bcat-build'),('pmi',PMI_PREFIX,'pmi')]}
    projected,again=frozen_sources(check,r,match,operations)
    require(again==time,'source timing changed after native/frozen replay')
    frozen_activation(check,match,r)
    files['native-control-representation.json']=encoded(native_representation(check,r))
    files['source-contract.json']=encoded(source_contract(r,projected,operations,time))
    original_rows={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()}
    bound=binding(check,cfg,matched,original_rows,projected,operations)
    files['source-segment-frames-proton-control-binding.json']=encoded(bound);cfg['source_segment_frames_proton_control_binding_sha256']=sha(files['source-segment-frames-proton-control-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,r,cfg['source_segment_frames_proton_control_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,r,cfg['source_segment_frames_proton_control_binding_sha256'],sha(files['source-contract.json'])))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='真实同条件完整请求 G4与真实新二维PMI编译、匹配A0原证据后，沿原runner进行二维质子同事件零源/半幅/同源项拆分控制实验；保持原owner/共享锁与串行单核单线程，无项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-source-segment-frames-proton-control-input-provenance-r1',run_id=run_id,role=role,
            matched_a0=matched,host_A0_replayed=True,host_complete_G4_and_source_math_replayed=True,
            actual_new_PMI_build_replayed=True,all_original_event_ids=event_ids(r),selected_event_id=r['event_id'],
            source_free_deck_byte_identical=True,additional_normalization=False,actual_native_submissions=0,input_generation_binding_sha256=sha(files[GENERATION_FILE]),
            input_entry_mode=obj(files[GENERATION_FILE])['entry_mode'],
            native_activation_verified=False,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False))})
    for name,(family,digest) in HOST_SOURCES.items():
        raw=(HERE.parent/family/name).read_bytes();require(sha(raw)==digest,'host replay source changed')
        files['proton-implementations/'+name]=raw
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py'):files[name]=(HERE/name).read_bytes()
    files.update(_runtime_bytes());files['generator-prepare_case.py']=(HERE/'prepare_case.py').read_bytes()
    hashes={n:sha(v) for n,v in files.items()}
    for n,digest in bundle['exports'].items():require(n not in hashes or hashes[n]==digest,'actual D2 import collision');hashes[n]=digest
    for n,row in originals.items():require(n not in hashes,'original proof collision');hashes[n]=row['sha256']
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    runner_sha=D.file_sha(runner)
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,
        producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():bridge.geometry_write(target/name,raw)
    for name,row in originals.items():
        require(D.file_sha(row['path'])==row['sha256'],'original dependency changed during prepare')
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
        with Path(row['path']).open('rb') as src,path.open('xb') as dst:
            for chunk in iter(lambda:src.read(1048576),b''):dst.write(chunk)
        require(D.file_sha(path)==row['sha256'],'streamed original proof copy differs')
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,event_id=r['event_id'],original_event_ids=event_ids(r),
        source_segment_frames_proton_control_binding_sha256=cfg['source_segment_frames_proton_control_binding_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        matched_a0=matched,native_submissions=0,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False)

