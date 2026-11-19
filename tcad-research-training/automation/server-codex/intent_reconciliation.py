"""Close a proven pre-manifest TCAD submission failure, without replay or collection.

This deliberately supports one diagnosed, source-pinned preflight failure. Remote
absence alone cannot establish that an earlier launch never happened. The original
intent, original error readback and historical runner are all bound in the receipt.
"""
from datetime import datetime, timezone
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import uuid

SCHEMA = "tcad-intent-launch-reconciliation-r1"
PROOF_SCHEMA = "tcad-prove-unlaunched-intent-r1"
PREFLIGHT_RUNNER_SHA = "b9357fade5a7daa174513ca7afcbdf9b5104ae9fff1e59293af46e97fc80932f"
PREFLIGHT_ERROR = ("ERROR: Multicore shared pool does not admit Geant4 operations; "
                   "use the original single-core profile in an idle pool\n")
MUTABLE = {"next_probe_at", "probe_failures", "reconciliation_error"}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verifier(workspace):
    source = Path(workspace) / "experiments/dram-see-v4/transport-probe/launch_reconciliation.py"
    if source.is_symlink() or not source.is_file():
        raise ValueError("Missing original idle-evidence validator")
    return load(source, "_intent_original_evidence_validator")


def projection(intent):
    return {key: value for key, value in intent.items() if key not in MUTABLE}


def receipt_path(state_dir, intent):
    run_id = intent.get("run_id")
    if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id) is None:
        raise ValueError("Invalid original intent run ID")
    return Path(state_dir) / "intent-reconciliations" / (run_id + ".json")


def frozen_subject(workspace, task_id, intent, evidence):
    """Read-only revalidation; no mutable probe/backoff field is an identity."""
    workspace = Path(workspace)
    v = verifier(workspace)
    v.need(isinstance(intent, dict) and intent.get("backend") == "tcad",
           "Only an original TCAD intent can be reconciled")
    v.need(isinstance(task_id, str) and bool(task_id), "Missing original task ID")
    pin = intent["connection"]
    profile = v._unlinked(pin["path"])
    raw = v._bytes(profile)
    v.need(profile.is_absolute() and v.digest(raw) == pin["sha256"], "Original profile SHA changed")
    cfg = v._json(raw)
    identity = {key: cfg[key] for key in v.IDENTITY_KEYS}
    v.need(cfg.get("backend") == "ssh-runtime" and cfg.get("parallel_capacity") == 4
           and cfg.get("requested_threads") == 2
           and cfg.get("cpu_sets") == [[0, 1], [2, 3], [4, 5], [6, 7]],
           "Only the original r4 TCAD profile is supported")
    run_id, slot = intent["run_id"], intent["slot"]
    receipt_path(Path("/unused"), intent)  # Validate the ID before using it in any path.
    v.need(type(slot) is int and 0 <= slot < 4, "Invalid original intent slot")
    resources = dict(schema="tcad-shared-gate-slots-r4", capacity=4,
                     cpu_set=cfg["cpu_sets"][slot], requested_threads=2)
    v.need(intent.get("requested_resources") == resources, "Original intent resources differ")
    root = cfg["remote_root"]
    v.need(isinstance(root, str) and re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)+", root) is not None
           and all(part not in (".", "..") for part in root.split("/")),
           "Invalid original pool root")
    native_root = v._unlinked(cfg["local_state_root"])
    allowed = (workspace / "local_runtime/cloud-benchmark").absolute()
    v.need(native_root.is_absolute() and native_root != allowed
           and native_root.is_relative_to(allowed), "Original native state root escaped workspace")
    native = v._unlinked(native_root / "runs" / run_id)
    v.need(not os.path.lexists(native), "Original native run directory exists")
    project_name = v._input_name(intent["project"])
    project = v._unlinked(workspace / str(project_name))
    v.need(project.is_dir(), "Original project is missing")
    hashes = {}
    for path in sorted(project.rglob("*")):
        v._unlinked(path)
        if path.is_file():
            hashes[path.relative_to(project).as_posix()] = v.digest(v._bytes(path))
        else:
            v.need(path.is_dir(), "Unknown original input inode")
    v.need(bool(hashes) and hashes == intent.get("input_sha256")
           and all(v._hash(value) for value in hashes.values()), "Original input SHA map changed")
    # Mirror the original Runtime comparison digest: display names/run metadata
    # do not turn an otherwise identical simulation into a new physical input.
    comparison = dict(hashes)
    if "project.json" in hashes:
        spec = v._json(v._bytes(project / "project.json"))
        v.need(isinstance(spec, dict), "Original project specification is malformed")
        spec.pop("name", None)
        geometry = spec.get("s2_geometry")
        if isinstance(geometry, dict):
            geometry.pop("run_id", None)
        comparison["project.json"] = v.digest(json.dumps(
            spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    input_digest = v.digest(json.dumps(comparison, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False).encode("utf-8"))
    v.need(input_digest == intent.get("input_digest") and v._hash(intent.get("task_digest")),
           "Original input/task digest differs")
    v.need(type(intent.get("submission_intent_at")) in (int, float)
           and intent["submission_intent_at"] > 0, "Missing original submission time")
    v.need(isinstance(evidence, dict) and set(evidence) == {"diagnosis", "runner"},
           "Missing historical preflight evidence")
    bound = {}
    for key, item in evidence.items():
        path = v._unlinked(item["path"])
        payload = v._bytes(path)
        v.need(path.is_absolute() and v._hash(item["sha256"])
               and v.digest(payload) == item["sha256"], "Historical evidence SHA changed: " + key)
        bound[key] = dict(path=str(path), sha256=v.digest(payload))
    v.need(bound["runner"]["sha256"] == PREFLIGHT_RUNNER_SHA,
           "Historical runner is not the supported preflight version")
    diagnosis = v._json(v._bytes(bound["diagnosis"]["path"]))
    v.need(diagnosis.get("schema") == "tcad-r06-launch-preflight-diagnosis-v1"
           and diagnosis.get("task_id") == task_id and diagnosis.get("run_id") == run_id
           and diagnosis.get("read_only_reproduction_matches_original_stderr") is True
           and diagnosis.get("original_stderr") == PREFLIGHT_ERROR,
           "Historical diagnosis does not establish this original preflight failure")
    bindings = diagnosis["evidence_bindings"]
    v.need(bindings.get("scripts/tcad.py") == PREFLIGHT_RUNNER_SHA, "Diagnosis runner pin differs")
    readback_name = "experiments/dram-se-r06/p0-bootstrap-activation-r1/original-submission-readback.json"
    readback_path = workspace / readback_name
    readback_raw = v._bytes(readback_path)
    v.need(v.digest(readback_raw) == bindings.get(readback_name), "Original submission readback changed")
    original = v._json(readback_raw)["original_intents"][task_id]
    v.need(projection(original) == projection(intent), "Immutable original intent changed")
    error = original.get("reconciliation_error", {})
    v.need(error.get("ok") is False and error.get("kind") == "runner_error"
           and error.get("returncode") == 1 and error.get("detail") == PREFLIGHT_ERROR,
           "Original submit outcome is not the diagnosed preflight failure")
    v.need(v._time(diagnosis["utc"]).timestamp() >= intent["submission_intent_at"],
           "Diagnosis predates the original intent")
    policy = dict(schema="tcad-shared-gate-slots-r4", capacity=4, slot=slot,
                  cpu_set=cfg["cpu_sets"][slot], requested_threads=2, pool_root=root,
                  connection_identity=identity, work_id=run_id,
                  remote_directory=root + "/runs/" + run_id, kind="run")
    return dict(schema="tcad-pre-manifest-intent-subject-r1", task_id=task_id,
                intent=projection(intent), label=run_id, remote_directory=policy["remote_directory"],
                connection_identity=identity, parallel_policy=policy, script_sha256=None,
                native_directory=str(native), failure_evidence=bound,
                original_readback=dict(path=str(readback_path), sha256=v.digest(readback_raw)))


def validate_proof(workspace, proof, subject):
    v = verifier(workspace)
    v.need(isinstance(proof, dict) and proof.get("schema") == PROOF_SCHEMA
           and proof.get("action") == "prove-unlaunched-intent"
           and proof.get("status") == "NOT_LAUNCHED", "Unknown TCAD intent proof")
    v.need(subject.get("schema") == "tcad-pre-manifest-intent-subject-r1"
           and subject["parallel_policy"]["schema"] == "tcad-shared-gate-slots-r4"
           and subject["parallel_policy"]["kind"] == "run"
           and "script_sha256" in proof and proof["script_sha256"] is None
           and subject["script_sha256"] is None
           and proof.get("policy") == subject["parallel_policy"]
           and proof.get("subject_sha256") == v.canonical_sha256(subject),
           "Remote intent proof subject/profile differs")
    return v.validate_idle_evidence(proof, subject)


def verify_receipt(workspace, task_id, intent, receipt):
    v = verifier(workspace)
    v.need(isinstance(receipt, dict) and receipt.get("schema") == SCHEMA
           and receipt.get("status") == "not_launched" and receipt.get("outcome") == "failed",
           "Unknown intent reconciliation receipt")
    for key in ("reservation_acquired", "solver_launched", "success", "collected"):
        v.need(receipt.get(key) is False, "Invalid intent reconciliation outcome")
    v.need(receipt.get("receipt_sha256") == v.canonical_sha256(
        {k: x for k, x in receipt.items() if k != "receipt_sha256"}), "Intent receipt SHA differs")
    stored = receipt["subject"]
    subject = frozen_subject(workspace, task_id, intent, stored["failure_evidence"])
    v.need(stored == subject and receipt.get("subject_sha256") == v.canonical_sha256(subject),
           "Original intent subject changed")
    proof = receipt["proof"]
    v.need(receipt.get("proof_sha256") == v.canonical_sha256(proof), "Intent proof SHA differs")
    validate_proof(workspace, proof, subject)
    v.need(v._time(receipt["created_utc"]) >= v._time(proof["observed_utc"]),
           "Intent receipt predates remote proof")
    return True


def verified_receipt(workspace, state_dir, task_id, intent):
    v = verifier(workspace)
    path = v._unlinked(receipt_path(state_dir, intent))
    if not os.path.lexists(path):
        return False
    try:
        return verify_receipt(workspace, task_id, intent, v._json(v._bytes(path)))
    except (OSError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid original intent reconciliation evidence: " + str(exc)) from exc


def publish(path, receipt, reference):
    """Atomic no-replace publication; root-produced evidence remains readable by tcad."""
    path = Path(path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    owner = Path(reference).stat()
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chown(path.parent, owner.st_uid, owner.st_gid)
            os.chown(temporary, owner.st_uid, owner.st_gid)
            os.chmod(temporary, 0o640)
        os.link(temporary, path)  # Refuse an existing file or link; never overwrite.
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(policy_path, task_id, diagnosis_path, historical_runner):
    controller = load(Path(__file__).with_name("controller.py"), "_intent_original_controller")
    policy = controller.policy_at(policy_path)
    state = Path(policy["state_dir"])
    with controller.instance_lock(state / "controller.lock"):
        ready = controller.readiness_at(policy)
        runtime = controller.create_runtime(policy, ready)
        runtime._profile()
        intent = runtime.intents[task_id]
        workspace = runtime.workspace
        tcad = load(workspace / "scripts/tcad.py", "_intent_original_runner")
        tcad.select_connection(intent["connection"]["path"])
        with tcad.original_ownership():
            if verified_receipt(workspace, state, task_id, intent):
                return {"status": "not_launched", "outcome": "failed", "reused": True}
            v = verifier(workspace)
            evidence = {name: dict(path=str(Path(path).absolute()), sha256=v.digest(v._bytes(path)))
                        for name, path in (("diagnosis", diagnosis_path), ("runner", historical_runner))}
            subject = frozen_subject(workspace, task_id, intent, evidence)
            cfg, ssh, _ = tcad.connection()
            operation = load(workspace / "experiments/dram-see-v4/transport-probe/operation.py",
                             "_intent_original_transport")
            proof_ssh, sim_ssh, transport = operation._privileged_proof_ssh()
            boot = operation._sim_boot_id(tcad, sim_ssh)
            record = dict(run_id=intent["run_id"], remote_directory=subject["remote_directory"],
                          parallel_policy=subject["parallel_policy"], script_sha256=None)
            proof = tcad.parallel_query(cfg, ssh, record, "prove-unlaunched-intent",
                                       proof_subject_sha256=v.canonical_sha256(subject),
                                       proof_ssh=proof_ssh)
            v.need(proof["boot_id"] == boot, "Proof transport is a different virtual machine")
            proof["proof_transport"] = dict(transport, sim_boot_id=boot)
            validate_proof(workspace, proof, subject)
            # Detect a concurrent ledger/input/evidence change after the remote read.
            current = v._json(v._bytes(state / "runtime.json"))["intents"][task_id]
            v.need(frozen_subject(workspace, task_id, current, evidence) == subject,
                   "Original intent/evidence changed during proof")
            receipt = dict(schema=SCHEMA, status="not_launched", outcome="failed",
                           reservation_acquired=False, solver_launched=False, success=False, collected=False,
                           created_utc=datetime.now(timezone.utc).isoformat(), subject=subject,
                           subject_sha256=v.canonical_sha256(subject), proof=proof,
                           proof_sha256=v.canonical_sha256(proof))
            receipt["receipt_sha256"] = v.canonical_sha256(receipt)
            verify_receipt(workspace, task_id, current, receipt)
            publish(receipt_path(state, intent), receipt, state / "runtime.json")
            verified_receipt(workspace, state, task_id, current)
            return {"status": "not_launched", "outcome": "failed", "success": False,
                    "collected": False, "reused": False, "receipt_sha256": receipt["receipt_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--historical-runner", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.policy, args.task_id, args.diagnosis, args.historical_runner)))
