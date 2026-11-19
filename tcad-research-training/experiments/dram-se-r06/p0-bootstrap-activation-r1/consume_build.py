"""Verify the collected original compile operation and copy its exact return.

Local archive consumer only: no SSH, compiler, solver, runner submission or
collection. Existing return directories and review files are never overwritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN_ID = "auto-r06-p0-o2-cmi-build-r1-8fcbf3ff83ef4722"
TASK_ID = "r06-p0-o2-cmi-build-r1"
RUN = ROOT / "local_runtime/cloud-benchmark/centos79-guest-20261116/dram-see-v4/transport-probe/operations" / RUN_ID
PACKAGE = ROOT / "experiments/dram-se-r06/p0-bootstrap-r1"
RETURN = PACKAGE / "build-returned-r1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def need(condition, message):
    if not condition:
        raise ValueError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ref(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}


def main():
    operation_path = RUN / "operation.json"
    operation_hash = sha(operation_path)
    operation = read(operation_path)
    intent = read(Path("/var/lib/tcad-autonomy/runtime.json"))["intents"][TASK_ID]
    need(operation["label"] == intent["run_id"] == RUN_ID, "Run identity differs")
    need(operation["input_directory"] == str(ROOT / intent["project"]), "Input path differs")
    need(operation["input_sha256"] == intent["input_sha256"], "Input manifest differs")
    need(operation["collection_verified"] is True
         and operation["parallel_slot_released"] is True, "Collection/release incomplete")
    for key in ("remote_exit_code", "operation_task_exit_code", "collection_exit_code", "ssh_exit_code"):
        need(type(operation[key]) is int and operation[key] == 0, "Original exit failed: " + key)
    need(operation["capture_exit_errors"] == {}, "Capture errors present")
    policy = operation["parallel_policy"]
    need(policy["schema"] == "tcad-shared-gate-slots-r3"
         and policy["capacity"] == 9 and policy["slot"] == policy["cpu"] == 0,
         "Not the original single-core compile profile")
    archive_path = RUN / "results.tar"
    need(sha(archive_path) == operation["archive_sha256"]
         == operation["collection_snapshot"]["sha256"], "Archive SHA differs")
    need(archive_path.stat().st_size == operation["collected_bytes"]
         == operation["collection_snapshot"]["bytes"], "Archive size differs")
    adapter = load(ROOT / "experiments/dram-see-v4/transport-probe/operation.py", "r06_build_adapter")
    tcad = adapter.load_tcad()  # imports the original local archive verifier only
    index = adapter.verify_operation_archive(tcad, archive_path, operation)
    adapter.verify_extracted(RUN / "collected", index, archive_path)
    for name, digest in intent["input_sha256"].items():
        need(sha(ROOT / intent["project"] / name) == digest, "Frozen input changed: " + name)
    with tarfile.open(archive_path) as archive:
        for name in ("exit-code.txt", "operation-task-exit-code.txt", "cmi-exit-code.txt"):
            need(archive.extractfile(name).read().strip() == b"0", "Raw exit failed: " + name)
        need(b"V4_OPERATION_COMPLETED" in archive.extractfile("execution.log").read(),
             "Original operation completion missing")
        need(not RETURN.exists(), "Never overwrite an existing returned build")
        need(not (HERE / "build-review.json").exists(), "Never overwrite a build review")
        RETURN.mkdir()
        for member in archive:
            adapter.safe_member_name(member.name)
            need(member.isfile(), "Only original regular files accepted")
            target = RETURN / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                output.write(source.read())
    adapter.verify_extracted(RETURN, index, archive_path)
    need(sha(operation_path) == operation_hash, "Operation changed while reading")
    receipt = read(RETURN / "build-receipt.json")
    need(receipt["status"] == "compiled_only" and receipt["solver_called"] is False,
         "Wrong build scope")
    need(sha(RETURN / "pmi_r04_nodal.so.linux64") == receipt["elf_sha256"], "ELF differs")
    report = {
        "schema": "tcad-r06-pmi-build-consumption-v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID, "run_id": RUN_ID,
        "status": "original_compile_verified_only",
        "operation": ref(operation_path), "archive": ref(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "verified_index_members": len(index),
        "returned_directory": str(RETURN.relative_to(ROOT)),
        "returned_files": {str(p.relative_to(RETURN)): sha(p) for p in sorted(RETURN.rglob("*")) if p.is_file()},
        "build_receipt": ref(RETURN / "build-receipt.json"),
        "new_elf_sha256": receipt["elf_sha256"],
        "new_source_sha256": receipt["source_sha256"],
        "consumed_original_verified_collection": True,
        "original_slot_released": True,
        "input_identity_matches_original_intent": True,
        "compiler_or_solver_called_by_consumer": False,
        "queue_modified": False, "scientific_gate_passed": False,
        "formal_case_credit": 0, "statistics_eligible": False,
        "verifiers": [ref(ROOT / "scripts/tcad.py"), ref(ROOT / "experiments/dram-see-v4/transport-probe/operation.py")],
    }
    with (HERE / "build-review.json").open("x") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "new_elf_sha256": receipt["elf_sha256"],
                      "returned_directory": report["returned_directory"], "verified_members": len(index)}))


if __name__ == "__main__":
    main()
