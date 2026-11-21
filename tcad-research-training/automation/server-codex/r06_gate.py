"""Fail-closed, per-submission admission for the approved r0.6 research plan.

This verifies bindings and recorded scientific decisions; it does not manufacture
scientific decisions from engineering exit codes. No runner or solver is called.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


PLAN = "dram-se-ddr5-lpddr5"
REVISION = "r0.6"
OWNER = "server-codex"
P0_RECIPES = {"zero_whr", "geometry_dc", "prefix_repeatability",
              "logging_short_probe", "logging_long_pair", "timing_sensitivity", "pmi_build"}
PARTICLE_RECIPES = P0_RECIPES - {"zero_whr", "geometry_dc", "pmi_build"}
BUILD_TASK = "#!/bin/bash\nset -euo pipefail\nexec /bin/bash ./compile-in-original-vm.sh\n"


class Pending(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise Pending(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path_at(workspace, name):
    need(isinstance(name, str) and name and "\\" not in name, "invalid relative path")
    relative = PurePosixPath(name)
    need(not relative.is_absolute() and ".." not in relative.parts
         and ":" not in name, "path escapes workspace")
    root = Path(workspace).resolve()
    path = root.joinpath(*relative.parts)
    for current in [path, *path.parents]:
        if current == root:
            break
        need(not current.is_symlink(), "linked evidence or input")
    need(path.resolve().is_relative_to(root) and path.resolve() != root,
         "path escapes workspace")
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_reference(workspace, reference):
    path = referenced(workspace, reference)
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == reference["sha256"],
         "referenced artifact changed while reading")
    return json.loads(raw.decode("utf-8-sig"))


def referenced(workspace, reference):
    need(isinstance(reference, dict), "missing hash-bound reference")
    value = reference.get("sha256")
    need(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
         "invalid reference SHA256")
    path = path_at(workspace, reference.get("path"))
    need(path.is_file() and sha(path) == value, "referenced artifact missing or changed")
    return path


def envelope(value, schema):
    need(isinstance(value, dict) and value.get("schema") == schema,
         "invalid admission schema")
    need((value.get("plan_id"), value.get("revision"), value.get("owner"))
         == (PLAN, REVISION, OWNER), "admission plan/revision/owner differs")


def input_hashes(project):
    result = {}
    for file in sorted(project.rglob("*")):
        need(not file.is_symlink(), "linked input")
        if file.is_file():
            result[file.relative_to(project).as_posix()] = sha(file)
    need(bool(result), "empty input")
    return result


def evidence_passed(workspace, value, name):
    need(isinstance(value, dict) and value.get("status") == "passed",
         name + " has not passed")
    evidence = value.get("evidence")
    need(isinstance(evidence, list) and bool(evidence), name + " lacks evidence")
    for reference in evidence:
        referenced(workspace, reference)


def matching_admission(workspace, contract, task, kind):
    folder = path_at(workspace, contract[kind + "_admissions_dir"])
    path = folder / (task["id"] + ".json")
    need(not path.is_symlink() and path.is_file(), kind + " admission pending")
    raw = path.read_bytes()
    admission = json.loads(raw.decode("utf-8-sig"))
    envelope(admission, "tcad-r06-" + kind + "-admission-v1")
    need(all(admission.get(key) == task[key] for key in ("backend", "project")),
         "admission backend/project differs")
    need(admission.get("task_id") == task["id"], "admission task differs")
    need(isinstance(admission.get("created_at"), str) and admission["created_at"],
         "missing admission creation time")
    admission["_verified_binding"] = {
        "path": path.relative_to(Path(workspace).resolve()).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest()}
    if 'wave_admission_sha256' in task:
        need(admission['_verified_binding']['sha256'] == task['wave_admission_sha256'],
             'admission changed since wave preparation')
    return admission


def verify_p0(workspace, contract, manifest, task, inputs, intents):
    admission = matching_admission(workspace, contract, task, "p0")
    need(admission.get("scope") == "p0_diagnostic"
         and admission.get("formal_case_id") is None
         and admission.get("statistics_eligible") is False
         and admission.get("budget_account") == "p0_diagnostics",
         "P0 cannot claim formal or statistical credit")
    need(admission.get("input_sha256") == inputs, "P0 input snapshot differs")
    recipe = admission.get("recipe_id")
    need(recipe in P0_RECIPES, "unsupported P0 recipe")
    profile_id = admission.get("profile_id")
    profiles = {item["id"] for item in manifest["profiles"]}
    need(profile_id in profiles, "unknown P0 profile")
    purpose = admission.get("purpose")
    need(isinstance(purpose, str) and len(purpose.strip()) >= 12, "missing diagnostic purpose")
    plan = read_reference(workspace, admission.get("diagnostic_plan"))
    need(plan.get("schema") == "tcad-r06-diagnostic-plan-v1"
         and plan.get("recipe_id") == recipe
         and plan.get("profile_id") == profile_id
         and plan.get("frozen_before_submission") is True
         and isinstance(plan.get("acceptance_criteria"), str)
         and len(plan["acceptance_criteria"].strip()) >= 20,
         "diagnostic plan/criteria not frozen")
    submitted = [value.get("scientific_admission", {}) for value in intents.values()
                 if value.get("scientific_admission", {}).get("scope") == "p0_diagnostic"]
    need(len(submitted) + 1 <= contract["max_p0_tasks"], "P0 diagnostic budget exhausted")
    need(sum(value.get("recipe_id") in PARTICLE_RECIPES for value in submitted)
         + int(recipe in PARTICLE_RECIPES) <= contract["max_p0_particle_tasks"],
         "P0 particle diagnostic budget exhausted")
    project = path_at(workspace, task["project"])
    if recipe == "pmi_build":
        need(task["backend"] == "geant4" and profile_id == "D0-nominal",
             "PMI build uses the original single-core operation backend")
        approved = contract.get("pmi_build_recipe", {})
        need((project / "task.sh").read_text(encoding="utf-8") == BUILD_TASK,
             "PMI build task differs from frozen compile-only launcher")
        for field, name in (("compile_script", "compile-in-original-vm.sh"),
                            ("source", "pmi_r04_nodal.C")):
            reference = approved.get(field)
            referenced(workspace, reference)
            need(sha(project / name) == reference["sha256"], "PMI build source/script changed")
        need(set(inputs) == {"task.sh", "compile-in-original-vm.sh", "pmi_r04_nodal.C",
                             "nodal_source.hpp", "voxel_source.hpp",
                             "build-request.json", "build-inputs.sha256"},
             "PMI build has unexpected inputs")
        request = read(project / "build-request.json")
        need(request.get("schema") == "tcad-r06-pmi-build-request-v1"
             and request.get("solver_called") is False
             and request.get("command") == [
                 "/usr/synopsys/sentaurus/W-2024.09/bin/cmi", "-O", "-v", "pmi_r04_nodal.C"],
             "PMI build request differs")
        for name, value in approved.get("headers_sha256", {}).items():
            need(inputs.get(name) == value
                 and request.get("headers_sha256", {}).get(name) == value,
                 "PMI physical source header changed")
        need(set(approved.get("headers_sha256", {})) == {"nodal_source.hpp", "voxel_source.hpp"},
             "PMI build header authority missing")
        return {"scope": "p0_diagnostic", "recipe_id": recipe,
                "admission": admission["_verified_binding"],
                "scientific_object": {"scope": "p0_diagnostic", "recipe_id": recipe,
                                      "profile_id": profile_id,
                                      "diagnostic_plan_sha256": admission["diagnostic_plan"]["sha256"]}}
    need(task["backend"] == "tcad", "TCAD diagnostic backend differs")
    spec = read(project / "project.json")
    threads, cores = spec.get("native_threads"), spec.get("native_cores")
    need(type(threads) is int and type(cores) is int and threads == cores and threads in (1, 2, 4),
         "P0 requires matching native_threads and native_cores set to 1, 2 or 4")
    tools = {step.get("tool") for step in spec.get("steps", [])}
    need(bool(tools) and tools <= {"sde", "snmesh", "sdevice", "tdx", "svisual"},
         "unsupported diagnostic tool")
    decks = "\n".join(file.read_text(encoding="utf-8")
                      for file in project.glob("*.cmd"))
    times = re.findall(r"\bFinalTime\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
                       decks)
    need(all(math.isfinite(float(value)) and 0 <= float(value) <= 35.000001e-9
             for value in times), "P0 transient exceeds approved diagnostic duration")
    source = project / "nodal-source.dat"
    if recipe == "geometry_dc":
        need(not source.exists() and not re.search(r"Optics|HeavyIon|PMIPath", decks),
             "geometry/DC recipe must have no particle source")
    else:
        need(source.is_file() and bool(times), "P0 requires explicit source and transient")
        with source.open(encoding="utf-8") as stream:
            header = stream.readline().split()
        need(len(header) == 5 and header[:2] == ["R04_NODAL_SOURCE", "1"],
             "unsupported nodal source format")
        nodes, records, assignments = map(int, header[2:])
        need(nodes > 0 and records >= 0 and assignments >= 0, "invalid nodal source counts")
        if recipe == "zero_whr":
            need(records == 0 and assignments == 0, "zero recipe has a particle source")
        else:
            need(profile_id == "D0-nominal", "particle diagnostics are limited to D0")
            need(plan.get("independent_primary_count") == 1,
                 "P0 particle diagnostic must bind one primary")
            need(isinstance(plan.get("event_provenance"), list)
                 and bool(plan["event_provenance"]), "missing diagnostic event provenance")
            for reference in plan["event_provenance"]:
                referenced(workspace, reference)
    return {"scope": "p0_diagnostic", "recipe_id": recipe,
            "admission": admission["_verified_binding"],
            "scientific_object": {"scope": "p0_diagnostic", "recipe_id": recipe,
                                  "profile_id": profile_id,
                                  "diagnostic_plan_sha256": admission["diagnostic_plan"]["sha256"]}}


def common_gate(workspace, contract, admission):
    gate = read_reference(workspace, admission.get("p0_gate"))
    envelope(gate, "tcad-r06-p0-scientific-gate-v1")
    need(gate.get("manifest_sha256") == contract["manifest"]["sha256"]
         and gate.get("p1_authorized") is True, "P0 gate belongs to another plan")
    for name in ("numerics", "logging", "timing", "source_integral"):
        evidence_passed(workspace, gate.get(name), name)
    error = gate["source_integral"].get("relative_error")
    need(type(error) in (int, float) and math.isfinite(error) and 0 <= error < 1e-9,
         "source integral relative error must be below 1e-9")
    return gate


def qualified_profile(workspace, gate, profile_id):
    qualification = gate.get("profiles", {}).get(profile_id, {})
    evidence_passed(workspace, qualification, "profile " + profile_id)
    need(set(qualification.get("qualified_bits", [])) == {0, 1},
         "profile requires both state baselines")


def training_freeze(workspace, admission):
    frozen = read_reference(workspace, admission.get("training_freeze"))
    envelope(frozen, "tcad-r06-training-freeze-v1")
    for key in ("model", "preprocessing", "split", "calibration", "acquisition"):
        referenced(workspace, frozen.get(key))
    need(frozen.get("frozen") is True
         and frozen.get("holdout_used_for_training") is False,
         "holdout requires a frozen development model")
    return admission["training_freeze"]


def case_draw_binding(workspace, contract, manifest, admission, case, selection):
    reference = admission.get("case_draw_map")
    binding = read_reference(workspace, reference)
    envelope(binding, "tcad-r06-cell-case-binding-v1")
    coordinates = ("block", "profile_id", "radiation_id")
    need(all(binding.get(key) == case[key] for key in coordinates)
         and binding.get("manifest_sha256") == contract["manifest"]["sha256"]
         and binding.get("selection_sha256") == selection["selection_sha256"],
         "cell/case sampling binding differs")
    expected = [item for item in manifest["cases"] if item.get("statistics_intent")
                and all(item.get(key) == case[key] for key in coordinates)]
    q1 = sum(item["stored_bit"] == 1 for item in expected)
    q0 = sum(item["stored_bit"] == 0 for item in expected)
    design = selection["design"]
    need(design["q"] == q1 and design["b0_count"] == q0
         and design["method"] == ("simple_random" if case["block"] == "R" else "stratified"),
         "selection size/method differs from planned cell allocation")
    rows = binding.get("case_draws")
    need(isinstance(rows, list) and len(rows) == len(expected), "incomplete case/draw mapping")
    by_case = {row["case_id"]: row for row in rows}
    need(set(by_case) == {item["case_id"] for item in expected}
         and len(by_case) == len(rows), "duplicate or missing planned case binding")
    actual_draws = [(row["event_id"], row["stored_bit"]) for row in rows]
    selected_draws = {(row["event_id"], row["stored_bit"]) for row in selection["draws"]}
    need(len(set(actual_draws)) == len(rows) and set(actual_draws) == selected_draws,
         "case/draw mapping repeats or omits a selected event/state")
    pairs = {}
    for item in expected:
        row = by_case[item["case_id"]]
        need(type(row["stored_bit"]) is int and row["stored_bit"] == item["stored_bit"],
             "case/draw state differs")
        if item.get("pair_id") is not None:
            pairs.setdefault(item["pair_id"], set()).add(row["event_id"])
    need(all(len(values) == 1 for values in pairs.values()), "matched pair event differs")
    row = by_case[case["case_id"]]
    need(row["event_id"] == admission.get("event_id"), "admission uses another case's draw")
    return reference


def replay_selection(source, verifier_sha, frame, selection, interpreters):
    """Use the exact frozen verifier and interpreter; never normalize the design."""
    version = (selection.get('design') or {}).get('python_version')
    if version == sys.version.split()[0]:
        spec = importlib.util.spec_from_file_location('_r06_frozen_sampler', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_selection(frame, selection)
        return
    # Only administrator-installed policy, never a proposal, supplies an executable.
    binary = interpreters.get(version) if isinstance(interpreters, dict) else None
    need(isinstance(binary, str) and Path(binary).is_absolute(),
         'frozen sampling interpreter not configured: ' + str(version))
    program = '''import hashlib,json,sys
from pathlib import Path
version, expected, file = sys.argv[1:]
if sys.version.split()[0] != version: sys.exit('frozen sampling interpreter version differs')
raw = Path(file).read_bytes()
if hashlib.sha256(raw).hexdigest() != expected: sys.exit('frozen sampling verifier changed')
ns = {'__name__':'_r06_frozen_sampler','__file__':file}
exec(compile(raw,file,'exec'),ns)
f,s = json.load(sys.stdin)
ns['validate_selection'](f,s)
'''
    try:
        checked = subprocess.run([binary, '-I', '-B', '-c', program, version, verifier_sha, str(source)],
                                 input=json.dumps([frame, selection], allow_nan=False).encode(),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Pending('frozen sampling interpreter unavailable: ' + str(version)) from exc
    need(checked.returncode == 0, 'frozen selection replay failed: ' +
         checked.stderr.decode('utf-8', errors='replace').strip().split('\n')[-1][:200])


def verify_production(workspace, contract, manifest, task, inputs, interpreters=None):
    admission = matching_admission(workspace, contract, task, "production")
    need(admission.get("input_sha256") == inputs, "production input snapshot differs")
    need(admission.get("manifest_sha256") == contract["manifest"]["sha256"],
         "production manifest differs")
    gate = common_gate(workspace, contract, admission)
    if task["backend"] == "geant4":
        need(admission.get("scope") == "transport_pool", "transport needs its own pool admission")
        profile = next((item for item in manifest["profiles"]
                        if item["id"] == admission.get("profile_id")), None)
        need(profile is not None, "unknown transport profile")
        qualified_profile(workspace, gate, profile["id"])
        pools = {(item["crn_group_id"], item["radiation_id"])
                 for item in manifest["cases"]
                 if item["block"] != "AL" and item.get("radiation_id") is not None}
        pool = (profile["crn_group_id"], admission.get("radiation_id"))
        need(pool in pools, "transport pool is absent from frozen design")
        request = read_reference(workspace, admission.get("pool_request"))
        need(request.get("schema") == "tcad-r06-transport-request-v1"
             and request.get("profile_id") == profile["id"]
             and request.get("crn_group_id") == pool[0]
             and request.get("radiation_id") == pool[1]
             and type(request.get("primary_count")) is int
             and request["primary_count"] in (100000, 1000000)
             and type(request.get("seed")) is int
             and request.get("uniform_source_area_sampling") is True
             and request.get("retain_zero_deposition_primaries") is True,
             "transport denominator/source request differs")
        if request["primary_count"] == 1000000:
            evidence_passed(workspace, request.get("expansion_need"), "pool expansion")
        area = request.get("source_area_cm2")
        need(type(area) in (int, float) and math.isfinite(area) and area > 0,
             "transport needs physical source area")
        radiation = next(item for item in manifest["radiations"] if item["id"] == pool[1])
        result = {"scope": "transport_pool", "pool": list(pool),
                  "admission": admission["_verified_binding"],
                  "scientific_object": {"scope": "transport_pool", "pool": list(pool),
                                        "pool_request_sha256": admission["pool_request"]["sha256"]}}
        if profile["partition"] != "development" or radiation.get("role") != "development":
            result["training_freeze"] = training_freeze(workspace, admission)
        return result
    cases = {item["case_id"]: item for item in manifest["cases"]}
    case = cases.get(admission.get("case_id"))
    need(case is not None and task["backend"] == "tcad", "case is absent from frozen manifest")
    if case["block"] == "AL":
        acquisition = read_reference(workspace, admission.get("acquisition"))
        envelope(acquisition, "tcad-r06-al-acquisition-v1")
        need(acquisition.get("case_id") == case["case_id"]
             and acquisition.get("holdout_used") is False, "AL selection scope differs")
        for key in ("development_snapshot", "candidate_model", "selection_rule"):
            referenced(workspace, acquisition.get(key))
        profile = next((item for item in manifest["profiles"]
                        if item["id"] == admission.get("profile_id")), None)
        need(profile is not None and profile["partition"] == "development",
             "AL must use a development profile")
        radiation = next((item for item in manifest["radiations"]
                          if item["id"] == admission.get("radiation_id")), None)
        need(radiation is not None and radiation.get("role") == "development",
             "AL must use development radiation")
        need(all(acquisition.get(key) == admission.get(key)
                 for key in ("profile_id", "radiation_id", "stored_bit"))
             and type(admission.get("stored_bit")) is int
             and admission["stored_bit"] == case["stored_bit"], "AL assignment/state differs")
        need(acquisition.get("response_input_sha256") == inputs,
             "AL response input binding differs")
        for key in ("event_provenance", "response_context"):
            referenced(workspace, acquisition.get(key))
        need(all(isinstance(acquisition.get(key), str) and acquisition[key]
                 for key in ("event_id", "transport_run_id")), "AL event provenance missing")
        case = dict(case, profile_id=profile["id"], radiation_id=radiation["id"],
                    stored_bit=case["stored_bit"])
    need(all(admission.get(key) == case.get(key)
             for key in ("profile_id", "radiation_id", "stored_bit", "block")),
         "production case coordinates differ")
    need(gate.get("deck_timing_version") == case["deck_timing_version"],
         "timing version differs")
    if case["kind"] == "response":
        need(gate.get("source_time_ns") == case["source_time_ns"],
             "source time differs from frozen manifest")
    qualified_profile(workspace, gate, case["profile_id"])
    scope = admission.get("scope")
    holdout = case["block"] in {"HR", "HP"} or case.get("holdout") is not None
    need(scope == ("holdout_evaluation" if holdout else "development_production"),
         "production/holdout scope differs")
    result = {"scope": scope, "case_id": case["case_id"],
              "admission": admission["_verified_binding"],
              "scientific_object": {key: case.get(key) for key in (
                  "case_id", "profile_id", "radiation_id", "stored_bit", "block",
                  "source_shape_id", "scale_factor")}}
    if case["block"] == "AL":
        result["scientific_object"]["al_selection"] = {
            key: acquisition[key] for key in (
                "event_id", "transport_run_id", "event_provenance", "response_context",
                "development_snapshot", "candidate_model", "selection_rule")}
    if holdout:
        result["training_freeze"] = training_freeze(workspace, admission)
    if case.get("statistics_intent"):
        selection = read_reference(workspace, admission.get("selection"))
        frame = read_reference(workspace, admission.get("frame"))
        source = path_at(workspace, contract["sampling_verifier"]["path"])
        need(sha(source) == contract["sampling_verifier"]["sha256"],
             "sampling verifier changed")
        replay_selection(source, contract['sampling_verifier']['sha256'], frame, selection, interpreters)
        need(selection["condition"]["profile_id"] == case["profile_id"]
             and selection["condition"]["radiation_id"] == case["radiation_id"],
             "sampling condition differs")
        draws = [row for row in selection["draws"]
                 if row["event_id"] == admission.get("event_id")
                 and row["stored_bit"] == case["stored_bit"]]
        need(len(draws) == 1 and 0 < draws[0]["inclusion_probability"] <= 1,
             "case is not in the frozen probability sample")
        result.update(cell_key=[case[key] for key in ("block", "profile_id", "radiation_id")],
                      cell_binding=case_draw_binding(
                          workspace, contract, manifest, admission, case, selection))
        result["scientific_object"].update(
            event_id=admission["event_id"],
            selection_sha256=selection["selection_sha256"])
    return result


def verify(workspace, policy, task, inputs=None, intents=None):
    """Return allowed metadata, or raise Pending. Missing policy is legacy only."""
    if "scientific_gate" not in policy:
        return {"scope": "legacy"}
    intents = {} if intents is None else intents
    settings = policy["scientific_gate"]
    need(isinstance(settings, dict)
         and settings.get("schema") == "tcad-r06-scientific-gate-policy-v1",
         "invalid scientific gate policy")
    need(task["id"] not in settings.get("deferred_task_ids", []),
         "legacy proposal deferred by r0.6")
    need(task["id"].startswith("r06-"), "new legacy tasks held by r0.6")
    contract = read_reference(workspace, settings.get("contract"))
    envelope(contract, "tcad-r06-scientific-gate-contract-v1")
    referenced(workspace, contract.get("authority"))
    manifest = read_reference(workspace, contract.get("manifest"))
    need(manifest.get("revision") == REVISION and manifest.get("plan_id") == PLAN,
         "frozen manifest identity differs")
    need(type(contract.get("max_p0_tasks")) is int and 1 <= contract["max_p0_tasks"] <= 64
         and type(contract.get("max_p0_particle_tasks")) is int
         and 0 <= contract["max_p0_particle_tasks"] <= 12, "invalid P0 budget")
    project = path_at(workspace, task["project"])
    actual = input_hashes(project)
    if inputs is not None:
        need(inputs == actual, "input snapshot changed during admission")
    if task["id"].startswith("r06-p0-"):
        result = verify_p0(workspace, contract, manifest, task, actual, intents)
    else:
        result = verify_production(workspace, contract, manifest, task, actual, settings.get('sampling_interpreters'))
    ancestors = set()
    parent = task.get("repair_of")
    while parent is not None:
        need(parent not in ancestors and parent in intents, "unknown/cyclic repair lineage")
        ancestors.add(parent)
        parent = intents[parent].get("repair_of")
    if task.get("repair_of") is not None:
        previous = intents[task["repair_of"]].get("scientific_admission", {})
        need(previous.get("scope") == result["scope"]
             and previous.get("case_id") == result.get("case_id")
             and previous.get("scientific_object") == result.get("scientific_object"),
             "repair must retain the parent's exact scientific object")
    for task_id, intent in intents.items():
        previous = intent.get("scientific_admission", {})
        if 'wave_admission_sha256' in task and result.get('scope') == 'transport_pool' and previous.get('scientific_object') == result['scientific_object']:
            need(task_id in ancestors, 'exact transport request already has an intent; reuse or explicit repair required')
        if result.get("case_id") is not None and previous.get("case_id") == result["case_id"]:
            need(task_id in ancestors, "formal case already has a submission intent")
        if (result.get("cell_key") is not None
                and previous.get("cell_key") == result["cell_key"]):
            need(previous.get("cell_binding", {}).get("sha256") == result["cell_binding"]["sha256"],
                 "cell sampling design changed after first submission")
        if result.get("training_freeze") and previous.get("training_freeze"):
            need(result["training_freeze"]["sha256"] == previous["training_freeze"]["sha256"],
                 "holdout was already unsealed for another frozen development version")
    result.update(contract=settings["contract"],
                  manifest_sha256=contract["manifest"]["sha256"])
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    try:
        configured = read(args.policy)
        proposals = read(configured["queue_file"])["tasks"]
        matches = [task for task in proposals if task["id"] == args.task_id]
        need(len(matches) == 1, "expected exactly one queue task")
        state = read(Path(configured["state_dir"]) / "runtime.json")
        print(json.dumps({"allowed": True, **verify(
            configured["workspace"], configured, matches[0], intents=state["intents"])},
            ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.exit(1, "scientific_gate_pending: " + str(exc) + "\n")
