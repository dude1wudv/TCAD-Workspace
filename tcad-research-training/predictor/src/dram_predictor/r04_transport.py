"""Offline adapter for the explicit, collected r0.4 development transport batch.

No SSH, directory discovery, solver, source injection, or model fitting. The
download receipt records remote archive verification; this adapter rechecks the
copied files and their frozen source chain. Unknown electrical quantities stay
unknown. A runner whose historical path contains v4 is not a v4 physics model.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

from .data import DataError, Snapshot, read_json, write_json
from .ingest import build_snapshot

R04 = "experiments/dram-se-r04/"
REGISTER = R04 + "transport/development-conditions-v1.json"
BATCH = R04 + "data/batch-native-r1/summary.json"
GEOMETRY = R04 + "model/baseline-geometry.json"
PROVENANCE = R04 + "model/parameter-provenance.json"
SELECTION = R04 + "data/event-handoff-r1/selected-events.json"
POLICY = R04 + "data/event-handoff-r1/selection-policy.json"
DIAGNOSTIC = R04 + "coupling/native-activation-r1/native-results-r1/comparison.json"


def require(test, message):
    if not test:
        raise DataError(message)


def number(value, name, *, nonnegative=False):
    require(not isinstance(value, bool), f"{name}: boolean is not a number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataError(f"{name}: expected numeric data") from exc
    require(math.isfinite(result) and (not nonnegative or result >= 0),
            f"{name}: invalid/nonfinite value")
    return result


def integer(value, name, *, minimum=0):
    result = number(value, name)
    require(result.is_integer() and result >= minimum, f"{name}: invalid integer")
    return int(result)


class Bundle:
    """Every consumed file is explicitly listed and its copied bytes are hashed."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.receipt = read_json(self.root / "copy-receipt.json")
        require(self.receipt.get("schema") == "r04-readonly-copy-v1", "Unsupported copy receipt")
        require(self.receipt.get("sealed_accessed") is False, "Copy must exclude sealed data")
        self.files = {}
        self.reads = {}
        for record in self.receipt["files"]:
            key = record["relative_path"]
            require(key not in self.files, "Duplicate receipt source")
            self.files[key] = record

    def raw(self, relative, expected=None):
        require(relative in self.files, f"Source missing from receipt: {relative}")
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root), "Source escapes copied bundle")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        record = self.files[relative]
        require(record["sha256"] == actual and record["size_bytes"] == len(raw),
                f"Copied file hash/size mismatch: {relative}")
        require(expected is None or expected == actual, f"Frozen source hash mismatch: {relative}")
        require(record.get("stable_during_read") is True, "Source was not stable during copying")
        self.reads[relative] = {"relative_path": relative, "sha256": actual,
                                "remote_path": record["remote_path"], "size_bytes": len(raw)}
        return raw

    def json(self, relative, expected=None):
        raw = self.raw(relative, expected)
        def pairs(items):
            out = {}
            for k, v in items:
                require(k not in out, "Duplicate source JSON key")
                out[k] = v
            return out
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              DataError(f"Nonfinite source JSON: {value}")))


def convert_events(rows, request, summary, event_sha, selected, *, preselected_ids=None):
    """Validate a full primary pool before producing unlabelled predictor rows."""
    output, seen = [], set()
    stats = Counter()
    expected_count = integer(request["event_count"], "event_count", minimum=1)
    for row in rows:
        event = integer(row["event_id"], "event_id")
        require(event not in seen and event < expected_count, "Duplicate/out-of-range event ID")
        seen.add(event)
        event_key = f"{request['id']}:{request['seed']}:{event}"
        for name, expected in {
            "event_key": event_key, "group_id": event_key, "input_task_id": request["id"],
            "transport_run_id": summary["transport_run_id"], "profile_id": request["profile_id"],
            "condition_id": request["condition_id"], "split": "development",
            "device_family": request["device_family"], "upset_label": "unknown",
            "electrical_response_status": "unsolved",
        }.items():
            require(row.get(name) == expected, f"Raw {name} mismatch for {event_key}")
        require(integer(row["seed"], "seed") == request["seed"], "Raw seed mismatch")
        require(row["event_complete"] == "1" and row["primary_count"] == "1",
                "Incomplete/non-primary transport record")
        for name in ("incident_energy_MeV", "theta_deg", "phi_deg"):
            require(number(row[name], name) == request[name], f"Raw {name} mismatch")
        area = number(row["source_area_cm2"], "source_area_cm2")
        require(math.isclose(area, request["source_plane"]["area_cm2"], rel_tol=1e-12),
                "Raw source area mismatch")
        energy = number(row["ionizing_si_MeV"], "ionizing_si_MeV", nonnegative=True)
        zero = integer(row["zero_si_ionizing"], "zero_si_ionizing")
        require(zero == int(energy == 0), "Zero Si deposition flag conflicts with energy")
        selected_row = selected.get(event_key)
        random_flag = integer(row["preselected_random_response"], "preselected_random_response")
        require(random_flag in (0, 1), "Invalid preselected response flag")
        if preselected_ids is not None:
            require(random_flag == int(event in preselected_ids), "Frozen preselection policy mismatch")
        sampling = None
        if selected_row is not None:
            for name, expected in {
                "event_key": event_key, "group_id": event_key, "event_id": event,
                "condition_id": request["condition_id"], "profile_id": request["profile_id"],
                "input_task_id": request["id"], "transport_run_id": summary["transport_run_id"],
                "split": "development", "upset_label": "unknown", "electrical_response_status": "unsolved",
            }.items():
                require(selected_row.get(name) == expected, f"Selection {name} mismatch")
            require(integer(selected_row["seed"], "selected seed") == request["seed"],
                    "Selection seed mismatch")
            require(integer(selected_row["zero_si_ionizing"], "selected zero flag") == zero,
                    "Selection zero flag mismatch")
            require(selected_row.get("population_frequency_weight") is None,
                    "Candidate selection must not invent population frequency weights")
            require(number(selected_row["ionizing_si_MeV"], "selected deposition") == energy,
                    "Selection deposition mismatch")
            sampling = {"preselected_random_response": "random",
                        "development_enrichment": "enriched"}.get(selected_row["selection_mechanism"])
            require(sampling is not None, "Unknown response selection mechanism")
        require(bool(random_flag) == (sampling == "random"), "Selection contradicts preselected random flag")
        if sampling == "enriched":
            require(energy > 0 and not random_flag, "Enrichment must be disjoint positive-deposition candidates")
        source_position = [number(row[f"source_{axis}_um"], "source position") for axis in "xyz"]
        stats["primary_count"] += 1
        stats["zero_si_ionizing_count"] += zero
        stats["positive_si_ionizing_count"] += 1 - zero
        stats["hadronic_event_count"] += int(integer(row["hadronic_step_count"], "hadronic steps") > 0)
        stats["step_count"] += integer(row["step_count"], "step_count", minimum=1)
        stats["track_count"] += integer(row["track_count"], "track_count", minimum=1)
        stats["selection_" + str(sampling)] += 1
        output.append({
            "primary_id": event_key, "condition_id": request["condition_id"],
            "source_primary_id": event_key, "source_hash": event_sha,
            "pool_member": True, "sampling": sampling, "source_off": None,
            "source_features": {"generated_charge_fC": None, "source_duration_ns": None,
                                "deposited_energy_MeV": None},
            "transport": {
                "run_id": summary["transport_run_id"], "input_task_id": request["id"],
                "event_id": event, "seed": request["seed"],
                "ionizing_si_MeV": energy, "zero_si_ionizing": bool(zero),
                "source_position_um": source_position,
                "source_position_is_strike_position": False,
                "event_complete": True, "native_source_qualified": False,
            },
        })
    require(len(seen) == expected_count, "Incomplete primary pool; preserve zero-deposition rows")
    for key in ("primary_count", "zero_si_ionizing_count", "hadronic_event_count", "step_count", "track_count"):
        require(stats[key] == summary["audit"][key], f"Raw rows disagree with frozen audit: {key}")
    return output, dict(stats)


def write_table(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_transport_snapshot(bundle_root, output_dir):
    """Return paths to a new snapshot, readiness and quality report; never fit."""
    bundle = Bundle(bundle_root)
    destination = Path(output_dir).resolve()
    require(not destination.exists(), "Output exists; preserve previous frozen snapshots")
    register = bundle.json(REGISTER)
    require(register.get("schema") == "dram-se-r04-first-development-v1"
            and register.get("cohort") == "development"
            and register.get("target_labels_seen") is False, "Not an unopened r0.4 development registry")
    requests = {}
    for request in register["conditions"]:
        require(request["split"] == "development" and request["particle"] == "proton"
                and 1 <= number(request["incident_energy_MeV"], "energy") <= 120,
                "Sealed/out-of-scope condition cannot enter this development adapter")
        require(request["schema"] == "dram-se-r04-transport-request-v1"
                and request["profile_id"] == register["profile_id"],
                "Request profile/schema does not match the registry")
        plane = request["source_plane"]
        require(plane["sampling"] == "independent_uniform_u_v_per_primary_in_beam_perpendicular_plane",
                "Unknown source distribution; cannot assume uniform")
        dimensions = []
        for axis in ("u", "v"):
            bounds = plane[axis + "_offsets_nm"]
            require(len(bounds) == 2, "Invalid source plane bounds")
            width = number(bounds[1], "plane bound") - number(bounds[0], "plane bound")
            require(width > 0, "Invalid source plane width")
            dimensions.append(width)
        area_nm2 = number(plane["area_nm2"], "source area nm2")
        area_cm2 = number(plane["area_cm2"], "source area cm2")
        require(area_nm2 > 0 and area_cm2 > 0
                and math.isclose(area_nm2, dimensions[0] * dimensions[1], rel_tol=1e-12)
                and math.isclose(area_cm2, area_nm2 * 1e-14, rel_tol=1e-12),
                "Source plane area/unit mismatch")
        cid = request["condition_id"]
        require(re.fullmatch(r"p\d+-c\d+", cid) is not None and cid not in requests,
                "Invalid/duplicate registered condition")
        requests[cid] = request
    batch = bundle.json(BATCH)
    require(batch.get("schema") == "dram-se-r04-native-transport-batch-v1", "Not an r0.4 batch")
    require(batch["condition_count"] == len(requests) == len(batch["snapshots"]),
            "Batch does not match registered development conditions")
    require({c["condition_id"] for c in batch["conditions"]} == set(requests)
            and all(c["split"] == "development" for c in batch["conditions"]),
            "Batch includes unregistered/sealed conditions")
    geometry = bundle.json(GEOMETRY)
    parameters = bundle.json(PROVENANCE)
    require(geometry["model_id"] == register["profile_id"], "Wrong geometry profile")
    require(geometry["calibrated_product"] is False, "Unexpected commercial-product claim")
    policy = bundle.json(POLICY)
    selection = bundle.json(SELECTION)
    require(selection["policy_sha256"] == bundle.reads[POLICY]["sha256"]
            and policy["development_only"] is True, "Selection policy hash/cohort mismatch")
    require(policy["preselected_random_response"]["fixed_before_transport_outcome"] is True
            and policy["preselected_random_response"]["selection_uses_deposition"] is False,
            "Random response selection must be frozen before transport outcomes")
    random_ids = policy["preselected_random_response"]["event_ids"]
    require(len(random_ids) == len(set(random_ids))
            and all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in random_ids),
            "Invalid preselected event IDs")
    selected = {}
    for event in selection["events"]:
        require(event["split"] == "development" and event["condition_id"] in requests,
                "Selection contains sealed/unknown event")
        key = event["event_key"]
        require(key not in selected, "Duplicate selection event")
        selected[key] = event
    diagnostics = bundle.json(DIAGNOSTIC) if DIAGNOSTIC in bundle.files else None
    archive_proofs = {x["run_id"]: x for x in bundle.receipt["archive_verification"]}
    conditions, primaries, quality_rows, lineage = [], [], [], []
    used_conditions = set()
    all_event_ids = set()
    for entry in batch["snapshots"]:
        # Authorize the copied development directory before opening its content.
        candidates = [cid for cid in requests
                      if re.fullmatch(rf"{re.escape(R04)}data/snapshots/\d{{8}}-{re.escape(cid)}-repair\d+",
                                      entry["snapshot"])]
        require(len(candidates) == 1, "Unrecognized/sealed snapshot directory")
        cid = candidates[0]
        require(cid not in used_conditions, "Duplicate physical condition")
        used_conditions.add(cid)
        request = requests[cid]
        summary = bundle.json(entry["snapshot"] + "/summary.json", entry["summary_sha256"])
        require(summary["schema"] == "dram-se-r04-development-transport-dataset-v1"
                and summary["input_task_id"] == request["id"]
                and summary["conditions_sha256"] == bundle.reads[REGISTER]["sha256"],
                "Snapshot does not match frozen r0.4 request")
        require(summary["output_events_sha256"] == entry["events_sha256"],
                "Event hash not bound to extraction summary")
        run = summary["transport_run_id"]
        require(re.fullmatch(r"auto-r04-[A-Za-z0-9_-]+", run) is not None, "Invalid original run ID")
        expected_locator = (
            r"local_runtime/cloud-benchmark/centos79-guest[-A-Za-z0-9_]*/"
            rf"dram-see-v4/transport-probe/operations/{re.escape(run)}/operation.json")
        require(re.fullmatch(expected_locator, entry["operation"]) is not None,
                "Operation locator must be the original runner record, never a sealed directory")
        remote_root = bundle.receipt["remote_workspace"].rstrip("/")
        require(summary["original_operation_json"] == remote_root + "/" + entry["operation"]
                == bundle.files[entry["operation"]]["remote_path"],
                "Original operation path is not bound to the copied record")
        require(entry["archive"] == str(Path(entry["operation"]).parent / "results.tar").replace("\\", "/")
                and summary["original_archive"] == remote_root + "/" + entry["archive"],
                "Archive locator is not the original operation archive")
        operation = bundle.json(entry["operation"], entry["operation_sha256"])
        require(operation["label"] == run and operation["state"] == "COLLECTED_PENDING_AUDIT"
                and operation["synthetic"] is False and operation["collection_verified"] is True
                and operation["origin"] == "native_pipeline",
                "Only original collected native transport is accepted")
        for key in ("remote_exit_code", "collection_exit_code", "operation_task_exit_code"):
            require(operation[key] == 0, f"Unsuccessful original operation: {key}")
        require(operation["collection_snapshot"]["sha256"] == entry["archive_sha256"]
                == summary["archive_sha256"], "Archive hash lineage mismatch")
        proof = archive_proofs.get(run, {})
        require(proof.get("sha256") == entry["archive_sha256"]
                and proof.get("stable_during_hash") is True
                and proof.get("remote_path") == summary["original_archive"]
                and proof.get("size_bytes") == operation["collection_snapshot"]["bytes"],
                "Missing stable remote archive verification")
        require(operation["input_sha256"] == summary["input_sha256"], "Frozen input hash mismatch")
        require(operation["input_sha256"]["geometry.json"] == bundle.reads[GEOMETRY]["sha256"]
                == request["geometry_sha256"], "Geometry is not the actual run geometry")
        require(operation["input_sha256"]["parameter-provenance.json"] == bundle.reads[PROVENANCE]["sha256"],
                "Parameter provenance is not the actual frozen run input")
        bundle.raw(R04 + "data/extract_transport.py", summary["extractor_sha256"])
        raw = bundle.raw(entry["snapshot"] + "/events.csv", entry["events_sha256"])
        rows, stats = convert_events(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))),
                                     request, summary, entry["events_sha256"], selected,
                                     preselected_ids=set(random_ids))
        for row in rows:
            require(row["primary_id"] not in all_event_ids, "Duplicate primary across sources")
            all_event_ids.add(row["primary_id"])
        primaries.extend(rows)
        xyz = request["source_plane"]["normal_toward_device"]
        require(len(xyz) == 3 and math.isclose(sum(number(x, "direction")**2 for x in xyz), 1.,
                                             rel_tol=1e-10), "Invalid declared beam direction")
        dimensions = geometry["parameters_nm"]
        bits = []
        for i, role in enumerate(geometry["storage_node_roles"]):
            regions = [r for r in geometry["regions"] if r["role"] == role]
            require(len(regions) == 1, "Ambiguous physical storage-node region")
            region = regions[0]
            bits.append({"bit_id": str(i), "node_role": role,
                         "position_definition": "declared_junction_region_centroid",
                         **{axis + "_nm": (region["lo_nm"][j] + region["hi_nm"][j]) / 2
                            for j, axis in enumerate("xyz")}})
        conditions.append({
            "condition_id": cid, "profile_id": request["profile_id"],
            "cohort": "development", "domain": request["device_family"],
            "categories": {"particle": "proton", "structure_family": geometry["construction"]},
            "features": {"gate_length_nm": dimensions["Lgt"], "fin_width_nm": dimensions["Wfin"],
                         "oxide_thickness_nm": dimensions["Tox"], "capacitance_fF": None,
                         "incident_energy_MeV": request["incident_energy_MeV"],
                         **{f"direction_{axis}": xyz[j] for j, axis in enumerate("xyz")}},
            "n_bits": geometry["sensitive_bits"], "bits": bits,
            "source_area_cm2": request["source_plane"]["area_cm2"],
            "source_distribution": "uniform", "area_normalization_validated": False,
            "primary_count": request["event_count"], "mechanism_validated": False,
            "provenance": {
                "transport_run_id": run, "original_input_task_id": request["id"],
                "geometry_sha256": request["geometry_sha256"],
                "parameter_provenance_sha256": bundle.reads[PROVENANCE]["sha256"],
                "source_plane": request["source_plane"], "physics": request["physics"],
                "source_angles_deg": {"theta": request["theta_deg"], "phi": request["phi_deg"]},
                "normal_incidence_vector": geometry["coordinate_contract"]["beam_normal_direction"],
                "direction_features": "actual native beam vector; source theta is measured from inward normal",
                "commercial_product_calibrated": False,
            },
        })
        quality_rows.append({"condition_id": cid, "energy_MeV": request["incident_energy_MeV"],
                             "theta_deg": request["theta_deg"], "phi_deg": request["phi_deg"], **stats})
        lineage.append({"condition_id": cid, "run_id": run, "operation": entry["operation"],
                        "archive_sha256": entry["archive_sha256"], "events_sha256": entry["events_sha256"],
                        "input_sha256": summary["input_sha256"]})
    require(set(selected) <= all_event_ids, "Selected event missing from the full pool")
    totals = Counter()
    for row in quality_rows:
        for key in ("primary_count", "zero_si_ionizing_count", "positive_si_ionizing_count",
                    "hadronic_event_count", "step_count", "track_count"):
            totals[key] += row[key]
    require(totals["primary_count"] == batch["independent_primary_records"], "Batch total mismatch")
    for key in ("zero_si_ionizing_count", "positive_si_ionizing_count", "step_count", "track_count"):
        require(totals[key] == batch[key], f"Batch total mismatch: {key}")
    destination.mkdir(parents=True, exist_ok=False)
    intake = destination / "intake"
    intake.mkdir()
    tables = {"conditions.jsonl": conditions, "primaries.jsonl": primaries,
              "responses.jsonl": [], "controls.jsonl": [], "counts.jsonl": []}
    hashes = {name: write_table(intake / name, rows) for name, rows in tables.items()}
    write_json(intake / "manifest.json", {
        "schema_version": 1, "plan_id": "dram-se-ddr5-lpddr5", "simulation_revision": "0.4",
        "kind": "native_simulation", "data_stage": "transport_only",
        "conditions_file": "conditions.jsonl", "primaries_file": "primaries.jsonl",
        "development": {"responses_file": "responses.jsonl", "controls_file": "controls.jsonl",
                        "counts_file": "counts.jsonl"},
        "sealed": {}, "sealed_design_status": "not_materialized_in_this_bundle",
        "files_sha256": hashes, "provenance": {
            "adapter": "r04_transport_v1", "bundle_receipt": str(bundle.root / "copy-receipt.json"),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "bundle_receipt_sha256": hashlib.sha256((bundle.root / "copy-receipt.json").read_bytes()).hexdigest(),
            "consumed_files": list(bundle.reads.values()), "runs": lineage,
            "parameter_source": parameters["source_pdf"],
            "transport_energy_is_electrical_supervision": False,
        },
    })
    manifest = build_snapshot(intake / "manifest.json", destination / "snapshot")
    snapshot = Snapshot.load(manifest)
    from .pipeline import prepare
    readiness = prepare(snapshot, destination / "prepared")
    quality = {
        "schema": "r04-transport-quality-v1", "source_capture_utc": bundle.receipt["utc"],
        "snapshot_manifest": str(manifest), "data_stage": "transport_only",
        "conditions": quality_rows, "condition_count": len(conditions),
        "profile_count": len({c["profile_id"] for c in conditions}),
        "independent_transport_primaries": totals["primary_count"], **dict(totals),
        "selected_response_candidates": dict(Counter(p["sampling"] or "not_selected" for p in primaries)),
        "verified_consumed_file_count": len(bundle.reads), "verified_transport_archives": len(lineage),
        "verification_scope": "copied bytes, frozen hashes and record consistency; original archive bytes hashed remotely",
        "native_responses": 0, "mechanism_controls": 0, "native_count_rows": 0,
        "R_ready": False, "F_ready": False, "training_started": False,
        "sealed_labels_read": False, "legacy_physics_imported": False,
        "source_injection_diagnostic": diagnostics,
        "missing_or_pending": [
            "Qualified native carrier-generation source and response-consistent space/time mapping",
            "Completed write/hold/read baselines, matched controls and explicit readout definition",
            "Mechanism calibration on training-side controls and sourced capacitance/protocol",
            "Actual state/bit responses; no upset labels inferred from transport energy",
            "Area/domain and cut/step sensitivity, then validated cross-section normalization",
            "Additional independent device profiles for grouped cross-validation; one profile is one group",
            "DDR5 external engineering counts and separate device domain",
        ],
        "interpretation": "Raw transport intake is usable; this is not a trainable R/F label set.",
        "read_sources": list(bundle.reads.values()), "runs": lineage, "readiness": readiness,
    }
    write_json(destination / "quality.json", quality)
    lines = [
        "# r0.4 训练数据快照与质量报告", "",
        f"来源截点：{quality['source_capture_utc']}。阶段：`transport_only`；未启动正式训练。", "",
        f"已接入 {len(conditions)} 个开发工况、{quality['profile_count']} 个器件 profile、"
        f"{totals['primary_count']:,} 个独立 primary；R/F 监督标签均为 0。", "",
        "| 工况 | 能量 MeV | θ/φ ° | primary | 硅电离沉积为正 | 硅电离沉积为零 |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in quality_rows:
        lines.append(f"| {row['condition_id']} | {row['energy_MeV']} | "
                     f"{row['theta_deg']}/{row['phi_deg']} | {row['primary_count']} | "
                     f"{row['positive_si_ionizing_count']} | {row['zero_si_ionizing_count']} |")
    lines += [
        "", "全部 primary（含零沉积）保留；候选选样身份与完整输运池成员身份分开记录。",
        "硅沉积为零不等于已验证的源关闭或未翻转；两状态、两位、源变体不增加独立 primary 数。", "",
        "能量与方向联合变化，当前结果不是独立能量扫描，也没有覆盖全部器件参数。"
        "一个 profile 不拆成多个交叉验证组；此快照不生成训练 folds。", "",
        "几何、原 run、事件身份、输入/归档/提取输出哈希均保留。"
        "沿用旧 runner 路径不表示采用旧 v4 物理数据。"
        "未复制或读取封存标签，活动求解输出未纳入。", "",
        "原生源诊断与电学/DC进展仅作为质量背景，不进入训练标签表。"
        "诊断报告来自服务器已完成原归档的提取；本轮没有重新解析其大型 TDR 或重做物理资格试验。", "",
        "## 后续数据缺项", "",
    ] + ["- " + item for item in quality["missing_or_pending"]]
    (destination / "QUALITY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"manifest": str(manifest), "quality_report": str(destination / "quality.json"),
            "quality_markdown": str(destination / "QUALITY.md"),
            "prepared": str(destination / "prepared"), "training_started": False}
