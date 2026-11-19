"""Input-only zero/half/duplicate-kernel controls for the fixed first real batch.

Uses the sealed a944 source-table serializer. Original G4 records and previously
verified per-kernel integrals are retained verbatim; no G4, CMI, TCAD, old
quadrature suite, scheduler, or native-positive fixture is invoked here.
"""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / "local_runtime/dram-see-v4/continuous/control-transition-r14-2d/proton-control-inputs-r1"
HEADER = ROOT / "local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation/pmi-2d-compile-inputs-r2/source_kernel_r12.hpp"
SCHEMA = "dram-see-v4-proton-source-math-controls-r1"
MANIFEST = "proton-control-input-manifest.json"
BATCH_MANIFEST_SHA = "641076af7f1a647f0b610727d9e56ec88981deb38a4a9ae311dd78db69b86134"
SOURCE_MANIFEST_SHA = "83207874143458947b04a5925312e83a12e635fe6d447990cc66a65ee12b29cd"
TIMING_SHA = "fdd2d332695f525dd00cde2297dd063ae7ed70e75a55bf74387d097934b0e395"
DEPENDENCIES = {
    "prepare_pmi_candidate.py": "a9446fe3e8fa04f634b82e965eb1a0dbad819b5598f373121f877c02019efcfe",
    "bcat_native_adapter.py": "139164c45e0673e13f80cf5821320fce1313a4f3a71e4f760b4344f94179c6dd",
    "kernel.py": "c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069",
    "pmi_projection_qy_r1.C": "1b8eb30bfcd001142235e9cf2f870cdfb38d98546305028d8ca70664805b05c6",
    "projection_pmi_math_r1.hpp": "bb1ff7fa938adc36ed3cdf5c2a91d60c24d50afcb338ccc68d8840dab1943c77",
}
HEADER_SHA = "7fccf1497de68fb3ce993c02b00ac4ca324f4f9ee5b5065f367c0533a82c7383"
CONTROLS = ("zero", "half", "split")
EVENT_IDS = [0, 1, 2, 3]
NUMERIC_KEYS = (
    "original_positive_Si_charge_fC", "outside_y_strip_fC", "inside_strip_outside_xz_box_fC",
    "inside_strip_box_non_silicon_fC", "response_silicon_outside_time_window_fC", "accepted_fC",
    "accepted_Mx_relative_fC_um", "accepted_Mz_relative_fC_um", "accepted_Mt_relative_fC_ps",
    "accepted_Mx_absolute_fC_um", "accepted_Mz_absolute_fC_um", "charge_partition_residual_fC",
)
FIVE_DESTINATIONS = NUMERIC_KEYS[1:6]
_PREPARER = None


def require(ok, message):
    if not ok:
        raise ValueError("proton control inputs: " + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def obj(raw):
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), "JSON object required")
    return value


def flags():
    return dict(is_native_result=False, native_source_qualified=False,
                pmi_r12_fixed=False, scientific_evidence_verified=False, training_admitted=False)


def exact_decimal(rational):
    # Binary64 values and division by two have only powers of two in their
    # denominators. This precision retains even a subnormal's exact decimal.
    with localcontext() as context:
        context.prec = 1100
        return str(Decimal(rational.numerator) / Decimal(rational.denominator))


def dependencies():
    for name, expected in DEPENDENCIES.items():
        path = HERE / name
        require(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == expected,
                "sealed dependency differs: " + name)
    require(HEADER.is_file() and not HEADER.is_symlink() and sha(HEADER.read_bytes()) == HEADER_SHA,
            "fixed actual source-table parser differs")
    return dict(DEPENDENCIES, **{"source_kernel_r12.hpp": HEADER_SHA})


def preparer():
    global _PREPARER
    dependencies()
    if _PREPARER is None:
        path = HERE / "prepare_pmi_candidate.py"
        spec = importlib.util.spec_from_file_location("_fixed_proton_control_serializer", path)
        _PREPARER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PREPARER)
    return _PREPARER


def directory_bytes(folder):
    folder = Path(folder).resolve()
    require(folder.is_dir() and not folder.is_symlink(), "original package missing/linked")
    result = {}
    for path in sorted(folder.rglob("*")):
        require(not path.is_symlink(), "linked package member")
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = path.read_bytes()
    return result


def identities(files):
    return {name: dict(sha256=sha(raw), size_bytes=len(raw)) for name, raw in sorted(files.items())}


def validate_parents(batch, source_inputs, timing_raw):
    """Reuse exact successful parent packages, without another native/build audit."""
    P = preparer()
    require(sha(batch.get("adapter-manifest.json", b"")) == BATCH_MANIFEST_SHA,
            "only fixed first real complete four-event batch accepted")
    bm = obj(batch["adapter-manifest.json"])
    require(bm["event_ids"] == EVENT_IDS and set(batch) == set(bm["files"]) | {"adapter-manifest.json"},
            "complete parent batch inventory required")
    for name, expected in bm["files"].items():
        require(sha(batch[name]) == expected, "parent batch bytes differ: " + name)
    require(sha(source_inputs.get("candidate-input-manifest.json", b"")) == SOURCE_MANIFEST_SHA,
            "only fixed first source-input package accepted")
    sm = obj(source_inputs["candidate-input-manifest.json"])
    require(set(source_inputs) == set(sm["files"]) | {"candidate-input-manifest.json", "input-hashes.sha256"},
            "complete original source-input inventory required")
    for name, expected in sm["files"].items():
        require(sha(source_inputs[name]) == expected, "original source input differs: " + name)
    original_hash_lines = "".join(
        sha(source_inputs[n]) + "  " + n + "\n"
        for n in sorted(set(source_inputs) - {"input-hashes.sha256"})).encode()
    require(source_inputs["input-hashes.sha256"] == original_hash_lines, "original full source hash file differs")
    require(sm["preparer"]["sha256"] == DEPENDENCIES["prepare_pmi_candidate.py"],
            "original source preparer identity differs")
    require(sha(timing_raw) == TIMING_SHA, "explicit current proton timing must remain byte-identical")
    timing = obj(timing_raw)
    binding = obj(batch["native-batch-binding.json"])
    index = obj(source_inputs["all-event-source-inputs.json"])
    require(index["batch_binding"] == binding and binding["original_request_event_ids"] == EVENT_IDS
            and binding["original_request_event_count"] == 4 and index["omitted_event_ids"] == [],
            "original complete request denominator differs")
    require(binding["adapter_implementation"]["sha256"] == DEPENDENCIES["bcat_native_adapter.py"]
            and binding["no_event_filter"] is True and all(value == 0 for value in binding["original_exits"].values()),
            "successful original batch/source identity differs")
    require(index["source_adapter"]["sha256"] == DEPENDENCIES["bcat_native_adapter.py"]
            and index["reference_kernel"]["sha256"] == DEPENDENCIES["kernel.py"],
            "original mathematical input implementations differ")
    require(binding["epoch_s"] == timing["source_epoch_s"] == 7.61e-8
            and index["complete_window_s"] == timing["simulation_window_s"] == [0., 8.82e-8],
            "physical epoch or complete electrical time changed")
    require(timing["native_observation_window_s"] == [7.6084e-8, 7.61161e-8],
            "current wide observation window changed")
    require(index["response_bindings"]["effective_width_cm"] == 2e-6,
            "effective width changed")
    sources, ledgers = [], []
    step_count = empty_let = 0
    support = []
    for eid, indexed in zip(EVENT_IDS, index["events"]):
        prefix = "event-" + str(eid) + "/"
        original = batch["event-" + str(eid) + "-g3-source.json"]
        require(original == source_inputs[prefix + "full-original-event-source.json"],
                "full original event is not the exact batch event")
        source = obj(original)
        ledger = obj(source_inputs[prefix + "input-only-projection-reference.json"])
        require(source["event_id"] == indexed["event_id"] == eid and source["seed"] == binding["seed"]
                and source["particle"] == "proton" and source["energy_MeV"] == 100
                and source["angle_deg"] == 0 and source["epoch_s"] == timing["source_epoch_s"],
                "only the actual fixed p100/0deg original events")
        require(source["all_selected_event_steps_retained"] is True and len(source["terms"]) == 500
                and len(source["step_records"]) == 503, "original event/step/kernel count differs")
        step_count += len(source["step_records"])
        records = {row["uid"]: row for row in source["step_records"]}
        require(len(records) == len(source["step_records"]), "duplicate original raw step UID")
        for row in source["step_records"]:
            raw = row["original_native_step"]
            require(row["input_epoch_s"] == timing["source_epoch_s"]
                    and row["physical_t0_s"] == timing["source_epoch_s"] + float(raw["pre_t_ns"]) * 1e-9
                    and row["physical_t1_s"] == timing["source_epoch_s"] + float(raw["post_t_ns"]) * 1e-9,
                    "original raw ns to seconds must add prescribed epoch once")
            if raw["local_ionizing_MeV_per_um"] == "":
                require(float(raw["step_um"]) == 0, "empty LET is only the original zero-path record")
                empty_let += 1
        rows = {row["uid"]: row for row in ledger["rows"]}
        require(len(rows) == 500 and set(rows) == {t["uid"] for t in source["terms"]},
                "original per-kernel five-destination denominator differs")
        for term in source["terms"]:
            P.K.validate_term(term)
            raw = records[term["uid"]]
            require(raw["disposition"] == "ACTIVE_SILICON_KERNEL"
                    and term["t0_s"] == raw["physical_t0_s"] and term["t1_s"] == raw["physical_t1_s"]
                    and term["p0_um"] == raw["physical_p0_um"] and term["p1_um"] == raw["physical_p1_um"]
                    and rows[term["uid"]]["original_positive_Si_charge_fC"] == term["charge_fC"],
                    "original kernel/step/reference mapping differs")
            lo, hi = term["t0_s"] - 8 * term["sigma_s"], term["t1_s"] + 8 * term["sigma_s"]
            require(timing["native_observation_window_s"][0] <= lo <= hi <= timing["native_observation_window_s"][1],
                    "full original +/-8sigma support not covered by fixed observation")
            support.append(dict(event_id=eid, parent_uid=term["uid"], lo_s=lo, hi_s=hi))
        require(P.source_table(source["terms"]) == source_inputs[prefix + "projection-sources3d.dat"],
                "parent table differs from fixed source serializer")
        require(P.context_bytes(timing["simulation_window_s"]) == source_inputs[prefix + "projection-context.dat"],
                "context must remain full physical time, not alpha/observation width")
        for key in NUMERIC_KEYS:
            require(math.fsum(row[key] for row in ledger["rows"]) == ledger["totals"][key],
                    "parent stored per-kernel totals differ: " + key)
        sources.append(source)
        ledgers.append(ledger)
    require(len(index["events"]) == 4 and step_count == 2012 and empty_let == 4,
            "complete original denominator or nullable LET lost")
    return dict(binding=binding, index=index, timing=timing, sources=sources, ledgers=ledgers,
                step_count=step_count, undefined_LET_count=empty_let, support=support)


def table_vector(term):
    return term["p0_um"] + term["p1_um"] + [
        term["t0_s"], term["t1_s"], term["charge_fC"], term["width_um"], term["sigma_s"]]


def control_event(control, source, parent_ledger, context_raw, timing):
    """Exact source-charge construction; reference integrals follow linearity."""
    require(control in CONTROLS, "unknown control")
    P = preparer()
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
            P.K.validate_term(child)
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
    table = P.source_table(terms)
    require(int(table.splitlines()[0].split()[1]) == 500 * copies,
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
        event_id=source["event_id"], original_event_count=4, parent_positive_kernel_count=500,
        represented_kernel_count=len(terms), rows=child_rows, all_parent_contributions=contributions,
        totals=totals, five_charge_destination_keys=list(FIVE_DESTINATIONS),
        complete_physical_time_window_s=timing["simulation_window_s"],
        native_observation_window_s=timing["native_observation_window_s"],
        mathematical_ledger_window="Full original [0,88.2ns]; not relabelled as a narrow observation integral",
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
        seed=source["seed"], particle="proton", energy_MeV=100, angle_deg=0,
        amplitude=amplitude, source_explicitly_configured=True,
        source_terms_present=bool(terms), parent_kernel_count=500, represented_source_count=len(terms),
        independent_physical_event=False, secondary_or_hadronic_process_inferred=False,
        source_terms_are_mathematical_representation_not_raw_G4_steps=True,
        original_physical_identity_per_copy_unchanged=True, half_device_response_linearity_required=False,
        all_original_step_records_retained=True, original_step_count=len(source["step_records"]),
        original_raw_ns_kept=True, epoch_addition_count=1, epoch_s=timing["source_epoch_s"],
        complete_physical_time_window_s=timing["simulation_window_s"],
        native_observation_window_s=timing["native_observation_window_s"],
        operation_timing_sha256=TIMING_SHA, context_sha256=sha(context_raw),
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
        current_main_runtime_accepts_control_package=False, formal_project_created=False,
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


def derive(batch, source_inputs, timing_raw, original_paths):
    audited = validate_parents(batch, source_inputs, timing_raw)
    payload = {"parents/batch/" + n: raw for n, raw in batch.items()}
    payload.update({"parents/source-inputs/" + n: raw for n, raw in source_inputs.items()})
    payload["parents/operation-timing.json"] = timing_raw
    binding = dict(schema=SCHEMA + "-parent-binding", original_paths=original_paths,
        original_batch_files=identities(batch), original_source_input_files=identities(source_inputs),
        timing_sha256=TIMING_SHA, implementations=dependencies(),
        adapter_manifest_sha256=BATCH_MANIFEST_SHA, source_input_manifest_sha256=SOURCE_MANIFEST_SHA,
        original_batch_native_exits=audited["binding"]["original_exits"],
        previous_successful_batch_replay_reused=True,
        original_batch_or_build_verify_rerun=False, parent_integrals_recomputed=False,
        original_request_event_ids=EVENT_IDS, original_step_count=audited["step_count"],
        original_empty_local_LET_count=audited["undefined_LET_count"],
        original_positive_kernel_count=2000, original_raw_energy_records_unchanged=True,
        response_bindings=audited["index"]["response_bindings"], source_epoch_s=audited["timing"]["source_epoch_s"],
        complete_time_window_s=audited["timing"]["simulation_window_s"],
        observation_window_s=audited["timing"]["native_observation_window_s"],
        original_source_support=audited["support"], **flags())
    payload["parent-bindings.json"] = encoded(binding)
    entries = []
    for control in CONTROLS:
        for source, ledger in zip(audited["sources"], audited["ledgers"]):
            eid = source["event_id"]
            prefix = control + "/event-" + str(eid) + "/"
            files = control_event(control, source, ledger,
                source_inputs["event-" + str(eid) + "/projection-context.dat"], audited["timing"])
            payload.update({prefix + n: raw for n, raw in files.items()})
            contract = obj(files["control-contract.json"])
            entries.append(dict(control=control, original_event_id=eid, prefix=prefix,
                parent_source="parents/batch/event-" + str(eid) + "-g3-source.json",
                parent_source_sha256=sha(batch["event-" + str(eid) + "-g3-source.json"]),
                original_reference="parents/source-inputs/event-" + str(eid) + "/input-only-projection-reference.json",
                parent_kernel_count=500, source_rows=contract["represented_source_count"],
                source_table_sha256=sha(files["projection-sources3d.dat"]),
                context_sha256=sha(files["projection-context.dat"]), **flags()))
    payload["control-input-index.json"] = encoded(dict(schema=SCHEMA + "-index",
        controls=list(CONTROLS), original_request_event_ids=EVENT_IDS, original_event_denominator=4,
        original_step_denominator=2012, original_empty_LET_denominator=4, entries=entries,
        mathematical_representations=12, independent_event_count_not_multiplied=True,
        new_native_calls=0, formal_project_created=False, **flags()))
    return payload


def manifest_for(payload, original_paths):
    return dict(schema=SCHEMA + "-manifest", files=identities(payload),
        implementation_sha256=sha(Path(__file__).read_bytes()), original_paths=original_paths,
        native_calls=0, compiled=False, formal_project_created=False, **flags())


def build(batch, source_inputs, timing, output):
    batch, source_inputs, timing, output = (Path(p).resolve() for p in (batch, source_inputs, timing, output))
    require(output.is_relative_to(EVIDENCE) and not output.exists(), "new output inside assigned evidence required")
    require(not timing.is_symlink(), "linked timing input")
    parents, inputs, timing_raw = directory_bytes(batch), directory_bytes(source_inputs), timing.read_bytes()
    original_paths = dict(batch=str(batch), source_inputs=str(source_inputs), operation_timing=str(timing))
    payload = derive(parents, inputs, timing_raw, original_paths)
    manifest = manifest_for(payload, original_paths)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in {**payload, MANIFEST: encoded(manifest)}.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    require(directory_bytes(batch) == parents and directory_bytes(source_inputs) == inputs
            and timing.read_bytes() == timing_raw, "original parent inputs changed during read-only derivation")
    return dict(status="INPUT_CONTROLS_GENERATED_NOT_NATIVE", output=str(output),
                manifest_sha256=sha(encoded(manifest)), entries=12,
                original_event_count=4, original_step_count=2012, original_empty_LET_count=4, **flags())


def verify_payload(raw):
    """In-memory full relation replay; useful for explicit tamper refusal."""
    require(MANIFEST in raw, "control manifest missing")
    manifest = obj(raw[MANIFEST])
    require(manifest.get("schema") == SCHEMA + "-manifest"
            and manifest.get("implementation_sha256") == sha(Path(__file__).read_bytes()),
            "control implementation identity differs")
    require(set(raw) == set(manifest["files"]) | {MANIFEST}, "control output inventory differs")
    for name, identity in manifest["files"].items():
        require(identity == dict(sha256=sha(raw[name]), size_bytes=len(raw[name])), "control bytes differ: " + name)
    batch = {name[len("parents/batch/"):]: value for name, value in raw.items() if name.startswith("parents/batch/")}
    inputs = {name[len("parents/source-inputs/"):]: value for name, value in raw.items() if name.startswith("parents/source-inputs/")}
    expected = derive(batch, inputs, raw["parents/operation-timing.json"], manifest["original_paths"])
    require(set(expected) == set(manifest["files"]) and all(raw[n] == v for n, v in expected.items()),
            "complete control generation replay differs")
    require(raw[MANIFEST] == encoded(manifest_for(expected, manifest["original_paths"])),
            "complete control manifest/scope differs; input replay cannot grant native/training status")
    return dict(status="INPUT_CONTROL_RELATIONS_REPLAYED_NOT_NATIVE",
        manifest_sha256=sha(raw[MANIFEST]), entries=12,
        original_event_count=4, original_step_count=2012, original_empty_LET_count=4, **flags())


def verify(package):
    package = Path(package).resolve()
    result = verify_payload(directory_bytes(package))
    return dict(result, output=str(package))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--source-inputs", type=Path, required=True)
    p.add_argument("--timing", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("verify")
    p.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.batch, args.source_inputs, args.timing, args.output) if args.command == "build" else verify(args.package)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, ArithmeticError) as error:
        print(json.dumps(dict(status="REFUSED_PROTON_CONTROL_INPUT", error_type=type(error).__name__,
                              error=str(error), **flags()), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
