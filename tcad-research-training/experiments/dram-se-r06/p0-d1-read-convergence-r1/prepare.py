"""Freeze one D1 read-convergence probe from the original two-core zero-source input."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PARENT = "r06-p0-d1-zero-whr-b1-r1"
TASK = "r06-p0-d1-read-cnorm-b1-r1"
GATE = ROOT / "plans/dram-se-ddr5-lpddr5/r06-gate"
ADMISSIONS = GATE / "p0-admissions"
MIXED_CONNECTION = "local_runtime/cloud-benchmark/connection-local-centos79-r06-mixed-six-one-two-two.json"
CHECKPOINT = ' Save(FilePrefix="pre_read")\n'
READ_MARKER = ' Set(rdrive."resistance"=1e15)\n'
READ_WINDOW = " Transient(InitialTime=3.0199999999999999e-08 FinalTime=3.18e-08"
STOP_NS = 30.925
PURPOSE = "Locate the Newton convergence hotspot during D1 write-1 readout with zero deposited charge."


def read(path):
    return json.loads(path.read_bytes())


def render(document):
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def diagnostics_deck(source):
    if source.count(READ_MARKER) != 1 or source.count(READ_WINDOW) != 1:
        raise ValueError("Original D1 read-window boundaries differ")
    math = "Math { Number_Of_Threads=2 CoordinateSystem"
    if source.count(math) != 1 or "CNormPrint" in source:
        raise ValueError("Original D1 solver settings differ")
    # Retain the original coupled equations and the step controls of the read segment.
    start = source.index(READ_WINDOW)
    end = source.index("\n }\n", start) + len("\n }\n")
    prefix = source[:end].replace(READ_WINDOW, READ_WINDOW.replace("3.18e-08", "30.925e-9"))
    return prefix.replace(math, math.replace("CoordinateSystem", "CNormPrint CoordinateSystem")).replace(
        READ_MARKER, CHECKPOINT + READ_MARKER) + "}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Freeze inputs and admission without publishing to the queue.")
    args = parser.parse_args()
    parent = read(ADMISSIONS / (PARENT + ".json"))
    if parent["task_id"] != PARENT or parent["profile_id"] != "D1-short-channel" or parent["recipe_id"] != "zero_whr":
        raise ValueError("Unexpected D1 baseline admission")
    source = ROOT / parent["project"]
    files = {name: (source / name).read_bytes() for name in parent["input_sha256"]}
    if {name: sha(data) for name, data in files.items()} != parent["input_sha256"]:
        raise ValueError("Original D1 inputs differ from their admission")
    header = files["nodal-source.dat"].split(b"\n", 1)[0].split()
    if header[:2] != [b"R04_NODAL_SOURCE", b"1"] or len(header) != 5 or header[-2:] != [b"0", b"0"]:
        raise ValueError("Expected the original empty nodal source")

    project = HERE / "inputs" / TASK
    plan_path = HERE / "diagnostic-plan.json"
    proposal_path = HERE / "proposal.json"
    admission_path = ADMISSIONS / (TASK + ".json")
    files["device.cmd"] = diagnostics_deck(files["device.cmd"].decode("utf-8")).encode("utf-8")
    spec = json.loads(files["project.json"])
    spec.update(name=TASK, purpose=PURPOSE)
    spec["steps"][0]["outputs"].remove("final_access_des.tdr")
    files["project.json"] = render(spec)
    protocol = json.loads(files["protocol.json"])
    protocol["diagnostic"] = {"task_id": TASK, "baseline_task": PARENT, "end_ns": STOP_NS,
                              "checkpoint_ns": 30.0, "read_margin_31p9_ns_expected": False}
    files["protocol.json"] = render(protocol)
    plan = {
        "schema": "tcad-r06-diagnostic-plan-v1", "recipe_id": "zero_whr", "profile_id": "D1-short-channel",
        "frozen_before_submission": True, "baseline_task_id": PARENT, "stored_bit": 1,
        "geometry_and_mesh": "identical to the baseline", "particle_source_rows": 0,
        "checkpoint_ns": 30.0, "end_ns": STOP_NS, "formal_case_credit": 0,
        "acceptance_criteria": (
            "Retain original timing and numerical settings up to the shortened read endpoint. "
            "Extract the worst equation, native vertex, coordinates and error on the final Newton "
            "iterations preceding rejected read steps. Require their spatial recurrence and alignment "
            "with the native region/interface before modifying the local mesh. For a follow-up, compare "
            "the same read interval, solver settings and two-core slot width without CNormPrint in either "
            "timing run. Report rejected steps, elapsed time and a native 31.9 ns signed BL margin "
            "(V_BL - 0.6 V) wherever that sample was actually reached."
        ),
    }
    proposal = {"id": TASK, "backend": "tcad", "project": relative(project), "depends_on": [],
                "requires": [MIXED_CONNECTION], "repair_of": None, "repair_reason": ""}
    plan_bytes = render(plan)
    admission = {
        "schema": "tcad-r06-p0-admission-v1", "plan_id": "dram-se-ddr5-lpddr5", "revision": "r0.6",
        "owner": "server-codex", "task_id": TASK, "backend": "tcad", "project": relative(project),
        "input_sha256": {name: sha(data) for name, data in files.items()}, "scope": "p0_diagnostic",
        "formal_case_id": None, "statistics_eligible": False, "budget_account": "p0_diagnostics",
        "created_at": datetime.now(timezone.utc).isoformat(), "profile_id": "D1-short-channel",
        "purpose": PURPOSE, "recipe_id": "zero_whr",
        "diagnostic_plan": {"path": relative(plan_path), "sha256": sha(plan_bytes)},
    }
    if args.write:
        if any(path.exists() for path in (project, plan_path, proposal_path, admission_path)):
            raise FileExistsError("The frozen diagnostic already exists")
        project.mkdir(parents=True)
        for path, data in [
            *((project / name, data) for name, data in files.items()),
            (plan_path, plan_bytes), (proposal_path, render(proposal)), (admission_path, render(admission)),
        ]:
            with path.open("xb") as handle:
                handle.write(data)
    print(json.dumps({"task_id": TASK, "frozen": args.write, "queued": False, "end_ns": STOP_NS,
                      "input_files": len(files), "mesh_sha256": admission["input_sha256"]["cell_msh.tdr"]}))


if __name__ == "__main__":
    main()
