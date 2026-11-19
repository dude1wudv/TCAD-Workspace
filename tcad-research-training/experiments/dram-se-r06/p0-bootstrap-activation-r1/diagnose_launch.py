"""Read-only local reproduction of the new TCAD launch preflight error.

No SSH, status/run/collect CLI, solver, lease operation or state write.
Only the diagnosis file in this experiment directory is created.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = ROOT / "scripts/tcad.py"
    spec = importlib.util.spec_from_file_location("r06_local_launch_diagnosis", source)
    tcad = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tcad)
    connection = ROOT / "local_runtime/cloud-benchmark/connection-local-centos79-mc2-four.json"
    cfg = tcad.select_connection(connection)
    paths = list((tcad.state_root() / "runs").glob("*/manifest.json"))
    paths += list((tcad.state_root() / "dram-see-v4/transport-probe/operations").glob("*/operation.json"))
    unrecognized_terminals = []
    first_error = None
    for path in paths:
        record = json.loads(path.read_text())
        complete = record.get("state") in ("COLLECTED", "FAILED_COLLECTED", "COLLECTED_PENDING_AUDIT")
        if complete and (not record.get("parallel_policy") or record.get("parallel_slot_released")):
            continue
        if record.get("state") == "FAILED_BEFORE_LAUNCH":
            unrecognized_terminals.append({
                "path": str(path.relative_to(ROOT)), "sha256": sha(path),
                "label": record.get("label"), "state": record["state"],
                "parallel_slot_released": record.get("parallel_slot_released"),
                "terminal_reconciliation": {k: v for k, v in record.items()
                                            if "unlaunch" in k or "reconcil" in k},
            })
        if first_error is None:
            try:
                tcad.parallel_record_policy(cfg, record)
            except (ValueError, RuntimeError) as error:
                first_error = {"path": str(path.relative_to(ROOT)), "sha256": sha(path),
                               "state": record.get("state"), "message": str(error)}
    try:
        tcad.parallel_assert_local(cfg)  # existing function performs local reads only
    except (ValueError, RuntimeError) as error:
        reproduction = str(error)
    else:
        raise ValueError("Expected launch-preflight error no longer reproduces; inspect new evidence")
    original = json.loads((HERE / "original-submission-readback.json").read_text())
    intent = original["original_intents"]["r06-p0-d0-o2-zero-prefix-a-r1"]
    expected_error = intent["reconciliation_error"]["detail"].removeprefix("ERROR: ").strip()
    assert first_error is not None and first_error["message"] == reproduction == expected_error
    report = {
        "schema": "tcad-r06-launch-preflight-diagnosis-v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "run_id": intent["run_id"], "task_id": "r06-p0-d0-o2-zero-prefix-a-r1",
        "classification": "engineering_launch_unknown_not_numerical_failure",
        "read_only_reproduction_matches_original_stderr": True,
        "original_stderr": intent["reconciliation_error"]["detail"],
        "first_blocking_local_record": first_error,
        "unrecognized_failed_before_launch_records": unrecognized_terminals,
        "mechanism": "parallel_assert_local complete-state whitelist omits FAILED_BEFORE_LAUNCH; it attempts to reinterpret original r3 operation policy under the new r4 TCAD configuration, and parallel_policy rejects operation kind on multicore before local new-run directory creation",
        "evidence_bindings": {
            str(source.relative_to(ROOT)): sha(source),
            "automation/server-codex/runtime.py": sha(ROOT / "automation/server-codex/runtime.py"),
            str(connection.relative_to(ROOT)): sha(connection),
            str((HERE / "original-submission-readback.json").relative_to(ROOT)): sha(HERE / "original-submission-readback.json"),
        },
        "code_anchors": {"scripts/tcad.py": [895, 904, 921, 1435, 2016, 2029, 2032],
                         "automation/server-codex/runtime.py": [481, 488, 493, 824, 834, 835]},
        "safety_boundary": "Local reproduction identifies this guard defect, but does not certify the uncertain new run as unlaunched or authorize replay; original Runtime must reconcile that exact ID using original evidence",
        "required_maintenance": "Teach the original runner local preflight to recognize only verified terminal unlaunched receipts without reinterpreting historical profiles; preserve rejection of incomplete/unknown receipts. Independently resolve the already committed new TCAD intent along its original ID before further scheduling. Add focused regression coverage for verified terminal vs incomplete records.",
        "changes_made_to_runner_controller_policy_profiles_queue_or_ledger": False,
        "ssh_run_collect_status_or_lease_calls": False,
        "repair_task_created": False, "scientific_gate_passed": False,
    }
    with (HERE / "launch-diagnosis.json").open("x") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"classification": report["classification"],
                      "first_blocking_record": first_error["path"],
                      "exact_original_stderr_reproduced": True,
                      "run_id": intent["run_id"]}))


if __name__ == "__main__":
    main()
