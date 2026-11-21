"""Append ready proposals from explicitly approved, hash-pinned waves."""
import re
from collections import Counter
from pathlib import Path

from month_one_wave import ANCHORS


QUEUE_SCHEMA = "tcad-work-items-v1"
WAVE_SCHEMA = "tcad-r06-development-wave-v1"
TASK_FIELDS = {"id", "backend", "project", "depends_on", "requires", "priority",
               "repair_of", "repair_reason"}
TASK_ID = re.compile(r"(?:r06-|raw-dev-)[a-z0-9-]+\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
INVALID = (OSError, ValueError, KeyError, TypeError, AttributeError)


def _task(work, gate, entry, contract):
    blob = gate.read_reference(work, entry["proposal"])
    gate.need(blob.get("schema") == QUEUE_SCHEMA and isinstance(blob.get("tasks"), list)
              and len(blob["tasks"]) == 1 and isinstance(blob["tasks"][0], dict),
              "expected one staged proposal")
    task = dict(blob["tasks"][0])
    key = task["id"]
    gate.need(isinstance(key, str) and len(key) <= 96 and TASK_ID.fullmatch(key),
              "invalid staged task ID")
    gate.need(task.keys() <= TASK_FIELDS, "unexpected staged field or adoption request")
    gate.path_at(work, task["project"])
    gate.need(type(task.get("priority", 100)) is int, "invalid priority")
    for field in ("depends_on", "requires"):
        values = task.get(field, [])
        gate.need(isinstance(values, list) and all(isinstance(value, str) for value in values),
                  "invalid " + field)
    for path in task.get("requires", []):
        gate.path_at(work, path)
    parent = task.get("repair_of")
    reason = task.get("repair_reason", "")
    gate.need(isinstance(reason, str) and (parent is None or
              (isinstance(parent, str) and parent != key and reason.strip())), "invalid repair")
    if key.startswith("raw-dev-"):
        pin = entry.get("input_digest")
        gate.need(set(entry) == {"proposal", "input_digest"} and isinstance(pin, str)
                  and SHA256.fullmatch(pin), "raw development requires a frozen input digest")
        gate.need(task["backend"] == "tcad" and task["project"] == "local_runtime/raw-development/" + key
                  and parent is None, "raw development requires a new scoped TCAD task")
        task["supply_input_digest"] = pin
    else:
        pin = entry.get("admission_sha256")
        gate.need(set(entry) == {"proposal", "admission_sha256"} and isinstance(pin, str)
                  and SHA256.fullmatch(pin), "formal proposal requires a frozen admission digest")
        task["wave_admission_sha256"] = pin
        admission = gate.matching_admission(work, contract, task, "production")
        gate.need(admission.get("profile_id") in ANCHORS
                  and admission.get("manifest_sha256") == contract["manifest"]["sha256"]
                  and not admission.get("training_freeze") and (
                      (task["backend"] == "tcad" and admission.get("block") in ("S", "R", "T")
                       and admission.get("scope") == "development_production") or
                      (task["backend"] == "geant4" and admission.get("scope") == "transport_pool")),
                  "outside the frozen development wave")
    return task


def _queue(gate, path):
    queue = gate.read(path)
    gate.need(queue.get("schema") == QUEUE_SCHEMA and isinstance(queue.get("tasks"), list),
              "invalid original queue")
    known = {task["id"]: task for task in queue["tasks"]}
    gate.need(len(known) == len(queue["tasks"]), "ambiguous original task ID")
    return queue, known


def load(policy, runtime, gate, *, planner_isolated=False):
    """Read the allowlist in FIFO order and return staged proposals and a publication report.

    A raw entry's input_digest binds the canonical digest of the exact input hash map.
    Runtime validates that pin before reporting the proposal ready and before submission.
    Only pass planner_isolated after blocking planner writes to the canonical queue.
    """
    planner_mode = policy.get("planner_mode")
    gate.need(planner_mode == "disabled" or (planner_mode == "on_demand_async" and planner_isolated is True),
              "scheduler supply requires a disabled or write-isolated proposal-only planner")
    gate.need("scientific_gate" in policy, "scheduler supply requires the scientific gate")
    work = Path(policy["workspace"])
    queue_path = Path(policy["queue_file"])
    report = {"published": [], "existing": [], "blocked": {}, "_queue_sha256": gate.sha(queue_path)}
    _, known = _queue(gate, queue_path)
    waves = policy["scheduler_supply"]["waves"]
    gate.need(isinstance(waves, list) and bool(waves), "expected an explicit wave allowlist")
    contract = gate.read_reference(work, policy["scientific_gate"]["contract"])
    gate.envelope(contract, "tcad-r06-scientific-gate-contract-v1")
    staged, conflicts = {}, set()
    for wave_index, reference in enumerate(waves):
        wave_key = f"wave-{wave_index}"
        try:
            wave = gate.read_reference(work, reference)
            entries = wave.get("entries")
            gate.need(wave.get("schema") == WAVE_SCHEMA and isinstance(entries, list)
                      and 1 <= len(entries) <= 13, "expected one wave of 1..13 proposals")
        except INVALID as exc:
            report["blocked"][wave_key] = str(exc)[:200]
            continue
        for index, entry in enumerate(entries):
            key = f"{wave_key}-entry-{index}"
            try:
                task = _task(work, gate, entry, contract)
                key = task["id"]
                if key in known or key in runtime.intents:
                    gate.need(known.get(key) == task, "original identity already claimed")
                    if key not in report["existing"]:
                        report["existing"].append(key)
                    continue
                if key in staged and staged[key] != task:
                    conflicts.add(key)
                    staged.pop(key)
                gate.need(key not in conflicts, "conflicting staged proposals for one ID")
                staged.setdefault(key, task)
            except INVALID as exc:
                report["blocked"][key] = str(exc)[:200]
    return staged, report


def publish(policy, runtime, gate, write, *, staged, report, ready, queued):
    """Append one bounded ready backlog using Runtime-validated (backend, width) pairs."""
    queue_path = Path(policy["queue_file"])
    original = report["_queue_sha256"]
    result = {key: report[key].copy() for key in ("published", "existing", "blocked")}
    if not ready:
        return result
    gate.need(gate.sha(queue_path) == original, "queue changed since supply validation")
    queue, known = _queue(gate, queue_path)
    by_width = Counter(queued.values())
    by_backend = Counter(backend for backend, _ in queued.values())
    selected = []
    ordered = sorted(staged.values(), key=lambda task: "supply_input_digest" in task)
    for task in ordered:
        key = task["id"]
        if key not in ready:
            continue
        if key in known or key in runtime.intents:
            result["blocked"][key] = "original identity already claimed"
            continue
        backend, width = ready[key]
        gate.need(backend == task["backend"], "validated backend differs from proposal")
        profile = runtime.profiles[backend]
        resources = profile["resources"]
        widths = resources["requested_threads"]
        width_limit = (widths.count(width) if isinstance(widths, list) else
                       resources["capacity"] if widths == width else 0)
        backend_limit = min(runtime.limit, profile.get("limit", runtime.limit))
        if by_width[(backend, width)] >= width_limit or by_backend[backend] >= backend_limit:
            continue
        selected.append(task)
        by_width[(backend, width)] += 1
        by_backend[backend] += 1
    if selected:
        gate.need(gate.sha(queue_path) == original and runtime.can_submit(), "queue changed or publication paused")
        queue["tasks"].extend(selected)
        write(queue_path, queue)
        result["published"] = [task["id"] for task in selected]
    return result
