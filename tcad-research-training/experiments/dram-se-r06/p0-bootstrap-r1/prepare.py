"""Prepare new inputs only. No subprocesses, SSH, solvers, or queue changes.

audit: verify frozen parents, read only.
stage-build: prepare a fresh compile-only bundle for the original VM/controller.
materialize: after real original-VM CMI compilation, prepare proposals/admissions.
Every output is confined to this package directory and created exclusively.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from logging_patch import ORIGINAL_SHA256, VERSION, verify as verify_patch

HERE = Path(__file__).resolve().parent
RELATIVE = "experiments/dram-se-r06/p0-bootstrap-r1"
CMI = "/usr/synopsys/sentaurus/W-2024.09/bin/cmi"
OLD_ELF = "ca05ab0350b27777fbce6a7aedea2b0c811bedb8bdee7581433af18804c98f65"
MODEL = "pmi_r04_nodal.C"
ELF = "pmi_r04_nodal.so.linux64"
COPY = ("cell_msh.tdr", "reference-apd.plx", "reference-spectrum.txt",
        "nodal_source.hpp", "voxel_source.hpp", "nodal-source.dat",
        "source-original.dat", "device.cmd")
TASKS = ("r06-p0-d0-o2-zero-prefix-a-r1", "r06-p0-d0-o2-zero-prefix-b-r1")
ENVELOPE = {"plan_id": "dram-se-ddr5-lpddr5", "revision": "r0.6", "owner": "server-codex"}
PURPOSE = ("D0 source-zero first-BE prefix: validate global O2 log bounds and "
           "record two-core numerical repeatability; no WHR qualification.")
PROFILE_MAPPING = (
    "D0-nominal admission bucket for the frozen r04 L08/p000 prototype only; "
    "does not qualify the r06 D0 geometry/doping baseline or any of the 26 Z cases."
)
CRITERIA = (
    "Use the unchanged frozen first-BE deck ending at 1e-13 s, identical mesh, "
    "zero source, physical code and original r4 2-thread/2-core resources. "
    "Require real solver completion/convergence, finite native device/circuit "
    "tables with original row order and times, and exactly zero generation "
    "including integrated G/UF0/UF4. Check <=4 initialization detail records, "
    "<=512 global callback detail records, single limit notices, bounded "
    "power-of-two callback milestones, unchanged error call sites and retained "
    "native warning/error/convergence/completion evidence. Report raw waveform "
    "differences against old zero prefixes and between the two new prefixes, "
    "wall/CPU time, log lines/bytes and archive bytes. Preserve the old strict "
    "comparison outcome including failures. This bootstrap does not establish "
    "a new full-transient tolerance, O2 scientific pass, source-active integral "
    "acceptance, WHR validity, 22 ns timing or any formal response label."
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def inventory(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        need(not path.is_symlink(), "Linked files are forbidden")
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = sha(path)
    return result


def safe_path(root, relative):
    need(isinstance(relative, str) and relative and "\\" not in relative,
         "Expected a workspace-relative POSIX path")
    path = Path(relative)
    need(not path.is_absolute() and ".." not in path.parts and ":" not in relative,
         "Path escapes workspace")
    result = root / path
    for part in [result, *result.parents]:
        if part == root:
            break
        need(not part.is_symlink(), "Linked path forbidden")
    need(result.resolve().is_relative_to(root.resolve()), "Path escapes workspace")
    return result


def rel(root, path):
    return path.relative_to(root).as_posix()


def ref(root, path):
    return {"path": rel(root, path), "sha256": sha(path)}


def package_for(root):
    package = safe_path(root, RELATIVE)
    need(package.resolve() == HERE, "Run the deployed package in the selected workspace")
    return package


def frozen_parent(root, package):
    survey = read(package / "evidence/remote-survey.json")
    record = survey["prefix_inputs"][0]
    parent = safe_path(root, record["path"])
    need(parent.is_dir(), "Frozen server prefix input is missing")
    need(inventory(parent) == record["files"], "Frozen prefix changed, including metadata")
    need(sha(parent / MODEL) == ORIGINAL_SHA256, "Unexpected original PMI version")
    with (parent / "nodal-source.dat").open(encoding="utf-8") as stream:
        header = stream.readline().strip()
    need(header == "R04_NODAL_SOURCE 1 10170 0 0", "Expected explicit source-zero input")
    deck = (parent / "device.cmd").read_text(encoding="utf-8")
    times = re.findall(r"\bFinalTime\s*=\s*([+\d.eE-]+)", deck)
    need(times == ["1e-13"] and deck.count("Transient(") == 1,
         "This bootstrap is only the verified first-BE prefix")
    spec = read(parent / "project.json")
    need(spec["native_threads"] == spec["native_cores"] == 2, "Resource version changed")
    patch = verify_patch(package)
    return parent, record, patch


def audit(root, package):
    parent, record, patch = frozen_parent(root, package)
    return {"status": "ready_for_original_vm_compilation_preparation",
            "parent": rel(root, parent), "frozen_parent_unchanged": True,
            "source": patch, "native_compiled": False, "solver_called": False,
            "queue_modified": False, "confirmed_final_time_s": 1e-13,
            "confirmed_15p2ns_decks": read(package / "evidence/remote-survey.json")[
                "confirmed_15p2ns_decks"]}


def stage_build(root, package, output):
    parent, record, patch = frozen_parent(root, package)
    need(not output.exists(), "Never overwrite a previous build bundle")
    output.mkdir()
    shutil.copyfile(package / "source" / MODEL, output / MODEL)
    for name in ("nodal_source.hpp", "voxel_source.hpp"):
        shutil.copyfile(parent / name, output / name)
    shutil.copyfile(package / "compile-in-original-vm.sh", output / "compile-in-original-vm.sh")
    request = {
        "schema": "tcad-r06-pmi-build-request-v1", **ENVELOPE,
        "log_version": VERSION, "status": "pending_original_vm_cmi",
        "source_sha256": patch["patched_sha256"],
        "headers_sha256": {name: sha(output / name)
                           for name in ("nodal_source.hpp", "voxel_source.hpp")},
        "command": [CMI, "-O", "-v", MODEL],
        "required_environment": "original_centOS7_sentaurus_W-2024.09_vm",
        "compiler_invoked_by_preparer": False, "solver_called": False,
        "parent": {"path": record["path"], "file_sha256": record["files"]},
        "deployment": "Original Runtime dispatches this compile-only bundle through "
                      "the existing Geant4 operation backend, recipe pmi_build, "
                      "in the idle shared pool. Collect before materialization; "
                      "no direct/manual VM compilation.",
    }
    save(output / "build-request.json", request)
    hashes = inventory(output)
    with (output / "build-inputs.sha256").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
    need(inventory(parent) == record["files"], "Parent changed during preparation")
    return {"status": "staged_only_pending_original_vm_cmi",
            "build_bundle": rel(root, output), "compiler_called": False, "solver_called": False}


def verify_build(package, build):
    need(build.is_dir() and not build.is_symlink(), "Build bundle must be a real directory")
    for path in build.rglob("*"):
        need(not path.is_symlink(), "Linked build artifact forbidden")
    receipt = read(build / "build-receipt.json")
    need(receipt.get("schema") == "tcad-r06-pmi-build-receipt-v1"
         and receipt.get("status") == "compiled_only"
         and receipt.get("log_version") == VERSION, "Missing real new-version compile receipt")
    need(receipt.get("command") == [CMI, "-O", "-v", MODEL]
         and receipt.get("build_environment") == "original_centOS7_sentaurus_W-2024.09_vm"
         and receipt.get("solver_called") is False, "Wrong build path/environment/scope")
    need(sha(build / MODEL) == sha(package / "source" / MODEL)
         == receipt.get("source_sha256"), "ELF receipt/source binding mismatch")
    request = read(build / "build-request.json")
    need(request["source_sha256"] == receipt["source_sha256"], "Build request source changed")
    for name, digest in request["headers_sha256"].items():
        need(sha(build / name) == digest, "Build header changed")
    for name, digest in receipt["evidence_sha256"].items():
        need(sha(safe_path(build, name)) == digest, "Build evidence changed")
    need((build / "cmi-exit-code.txt").read_text().strip() == "0", "CMI failed")
    binary = (build / ELF).read_bytes()
    need(binary[:6] == b"\x7fELF\x02\x01" and binary[18:20] == b"\x3e\x00",
         "Not an ELF64 little-endian x86-64 shared library")
    need(sha(build / ELF) == receipt["elf_sha256"] != OLD_ELF,
         "Old or unbound ELF cannot be called the new logging version")
    need(b"r06-o2-global-r1" in binary, "New log-version marker absent from ELF")
    return receipt


def materialize(root, package, build, output):
    parent, record, patch = frozen_parent(root, package)
    compiled = verify_build(package, build)  # Fail before creating any output.
    for name in ("nodal_source.hpp", "voxel_source.hpp"):
        need(sha(build / name) == record["files"][name], "Compiled source headers differ")
    need(not output.exists(), "Never overwrite existing inputs/proposals/admissions")
    output.mkdir()
    (output / "inputs").mkdir()
    (output / "admissions").mkdir()
    shutil.copyfile(build / "build-receipt.json", output / "build-receipt.json")
    save(output / "diagnostic-plan.json", {
        "schema": "tcad-r06-diagnostic-plan-v1", **ENVELOPE,
        "recipe_id": "zero_whr", "profile_id": "D0-nominal",
        "frozen_before_submission": True, "acceptance_criteria": CRITERIA,
        "subtype": "logging_first_BE_bootstrap_not_full_WHR",
        "profile_mapping": PROFILE_MAPPING,
        "log_version": VERSION, "final_time_s": 1e-13,
        "native_threads": 2, "native_cores": 2, "resource_profile": "original mc2-four/r4",
        "parent_input": record, "build_receipt": ref(root, output / "build-receipt.json"),
        "source_transform": patch, "independent_primary_count": 0,
        "same_version_short_source_pair_required_before_long_task": True,
        "o2_scientific_gate_passed": False,
        "formal_case_id": None, "statistics_eligible": False,
        "formal_plan_completed_credit": 0,
    })
    tasks = []
    for index, task_id in enumerate(TASKS):
        target = output / "inputs" / task_id
        target.mkdir()
        for name in COPY:
            shutil.copyfile(parent / name, target / name)
        shutil.copyfile(package / "source" / MODEL, target / MODEL)
        shutil.copyfile(build / ELF, target / ELF)
        project = read(parent / "project.json")
        project.update(name=task_id, purpose=PURPOSE)
        save(target / "project.json", project)
        save(target / "bootstrap-lineage.json", {
            "schema": "tcad-r06-o2-prefix-lineage-v1", **ENVELOPE,
            "parent_input": record, "log_version": VERSION,
            "build_receipt": ref(root, output / "build-receipt.json"),
            "source_transform": patch, "elf_sha256": compiled["elf_sha256"],
            "profile_mapping": PROFILE_MAPPING,
            "deck_byte_identical": True, "native_threads": 2, "native_cores": 2,
            "source_zero": True, "source_time_shifted": False,
            "formal_case_id": None, "statistics_eligible": False,
            "outcome": "unknown_pending_original_controller",
        })
        for name in COPY:
            need(sha(target / name) == record["files"][name], "Unrelated input changed")
        project_name = rel(root, target)
        save(output / "admissions" / (task_id + ".json"), {
            "schema": "tcad-r06-p0-admission-v1", **ENVELOPE,
            "task_id": task_id, "backend": "tcad", "project": project_name,
            "input_sha256": inventory(target),
            "scope": "p0_diagnostic", "formal_case_id": None,
            "statistics_eligible": False, "budget_account": "p0_diagnostics",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile_id": "D0-nominal", "recipe_id": "zero_whr",
            "purpose": PURPOSE, "diagnostic_plan": ref(root, output / "diagnostic-plan.json"),
        })
        tasks.append({
            "id": task_id, "backend": "tcad", "project": project_name,
            "depends_on": [] if index == 0 else [TASKS[index - 1]],
            "requires": [rel(root, p) for p in sorted(target.iterdir()) if p.is_file()],
            "repair_of": None, "repair_reason": "",
        })
    need(inventory(parent) == record["files"], "Protected parent changed")
    save(output / "proposals.json", {"schema": "tcad-work-items-v1", "tasks": tasks})
    save(output / "preparation-receipt.json", {
        "status": "prepared_only_not_admitted_or_submitted", "tasks": list(TASKS),
        "compiler_called": False, "solver_called": False, "queue_modified": False,
        "parent_unchanged": True, "admission_publication_by_original_controller_only": True,
        "budget_account": "p0_diagnostics", "formal_plan_completed_credit": 0,
    })
    return {"status": "prepared_only", "proposals": rel(root, output / "proposals.json"),
            "admissions": rel(root, output / "admissions"), "solver_called": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "stage-build", "materialize"))
    parser.add_argument("--workspace", type=Path, default=HERE.parents[2])
    parser.add_argument("--build-dir", default=RELATIVE + "/build-original-vm-r1")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    root = args.workspace.resolve()
    package = package_for(root)
    if args.action == "audit":
        result = audit(root, package)
    else:
        default = "build-original-vm-r1" if args.action == "stage-build" else "prepared-prefix-r1"
        output = safe_path(root, args.output or (RELATIVE + "/" + default))
        need(output.resolve().is_relative_to(package.resolve()) and output != package,
             "All preparation output must stay below this new package directory")
        if args.action == "stage-build":
            result = stage_build(root, package, output)
        else:
            result = materialize(root, package, safe_path(root, args.build_dir), output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
