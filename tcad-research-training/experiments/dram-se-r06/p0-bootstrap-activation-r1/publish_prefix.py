"""Publish reviewed P0 proposals; never invoke the Runtime or a solver."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PREPARED = ROOT / "experiments/dram-se-r06/p0-bootstrap-r1/prepared-prefix-r1"
QUEUE = ROOT / "plans/dram-se-ddr5-lpddr5/work-items.json"
ADMISSIONS = ROOT / "plans/dram-se-ddr5-lpddr5/r06-gate/p0-admissions"
IDS = ("r06-p0-d0-o2-zero-prefix-a-r1", "r06-p0-d0-o2-zero-prefix-b-r1")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def save_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    review_path = HERE / "independent-prefix-review.json"
    review = read(review_path)
    need(review.get("ready_for_original_queue_proposal") is True,
         "Independent review does not support publication")
    for relative, digest in review["protected_files_sha256"].items():
        need(sha(ROOT / relative) == digest, "Reviewed file drift: " + relative)
    need(not (HERE / "queue-receipt.json").exists(), "Publication already recorded")
    before_bytes = QUEUE.read_bytes()
    before = json.loads(before_bytes)
    before_sha = hashlib.sha256(before_bytes).hexdigest()
    proposals = read(PREPARED / "proposals.json")
    tasks = proposals["tasks"]
    need(before["schema"] == proposals["schema"] == "tcad-work-items-v1", "Queue schema differs")
    need(tuple(task["id"] for task in tasks) == IDS, "Unexpected proposals")
    need(len({t["id"] for t in before["tasks"]}) == len(before["tasks"]), "Old queue duplicate")
    need(not set(IDS).intersection(t["id"] for t in before["tasks"]), "Task already proposed")
    policy = read(Path("/etc/tcad-autonomy/policy.json"))
    need(Path(policy["workspace"]) == ROOT and Path(policy["queue_file"]) == QUEUE,
         "Not the original configured queue")
    runtime = read(Path(policy["state_dir"]) / "runtime.json")
    need(not set(IDS).intersection(runtime["intents"]), "Task already submitted")
    gate_path = ROOT / "automation/server-codex/r06_gate.py"
    spec = importlib.util.spec_from_file_location("r06_prefix_publication_gate", gate_path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    for task in tasks:
        source = PREPARED / "admissions" / (task["id"] + ".json")
        destination = ADMISSIONS / source.name
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
    admitted = {task["id"]: gate.verify(ROOT, policy, task, intents=runtime["intents"])
                for task in tasks}
    save_new(HERE / "prepublication-gate.json", {
        "utc": datetime.now(timezone.utc).isoformat(), "gate_sha256": sha(gate_path),
        "policy_sha256": sha(Path("/etc/tcad-autonomy/policy.json")), "results": admitted,
        "scientific_acceptance": "not_assessed", "formal_case_credit": 0})
    after = dict(before, tasks=before["tasks"] + tasks)
    after_bytes = (json.dumps(after, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".work-items-r06-prefix-", suffix=".tmp", dir=QUEUE.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(after_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        need(QUEUE.read_bytes() == before_bytes, "Queue changed during proposal preparation")
        for task in tasks:
            gate.verify(ROOT, policy, task, intents=runtime["intents"])
        os.replace(temporary, QUEUE)
        directory = os.open(QUEUE.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    need(QUEUE.read_bytes() == after_bytes, "Queue readback differs; inspect before writing again")
    need(read(QUEUE)["tasks"][:len(before["tasks"])] == before["tasks"], "Old history changed")
    receipt = {
        "schema": "tcad-r06-prefix-queue-receipt-v1", "utc": datetime.now(timezone.utc).isoformat(),
        "task_ids": list(IDS), "queue_before_sha256": before_sha,
        "queue_after_sha256": sha(QUEUE), "old_task_count": len(before["tasks"]),
        "new_task_count": len(after["tasks"]), "all_original_task_definitions_preserved": True,
        "independent_review_sha256": sha(review_path), "actual_semantic_gate": admitted,
        "input_sha256": {t["id"]: gate.input_hashes(ROOT / t["project"]) for t in tasks},
        "submission_owner": "original Runtime only", "solver_or_runner_called": False,
        "scientific_acceptance": "not_assessed", "formal_case_credit": 0,
        "statistics_eligible": False,
    }
    save_new(HERE / "queue-receipt.json", receipt)
    print(json.dumps({k: receipt[k] for k in ("task_ids", "old_task_count", "new_task_count", "queue_after_sha256")}))


if __name__ == "__main__":
    main()
