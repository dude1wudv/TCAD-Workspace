"""One engineering build only. No SDevice, native field extraction or campaign.

The existing operation adapter supplies strict SSH, solver lock and affinity.
The production active-entry must stay at its frozen READ_ONLY_HOLD identity.
Imports and package preparation never launch a process.
"""
from pathlib import Path
import csv
import hashlib
import math
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common as c
import supervisor_storage_r4 as s
import native_compile_r2 as archive_checks

LABEL = "nc-r1-qy-candidate-build-r12"
SOURCE_NAMES = ("pmi_nuclear_qy_r12.C", "source_kernel_r12.hpp",
                "candidate_math_r12.hpp", "test_context_r12.C")
SDK = "/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64"
CMI = "/usr/synopsys/sentaurus/W-2024.09/bin/cmi"
INC = "/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/sdevice/include"


def release():
    p = HERE / "release-build-only.json"
    value = c.read(p)
    c.require(value.get("scope") == "engineering_build_only" and
              value.get("execution_enabled") is True and
              value.get("tcad_execution_enabled") is False,
              "Only the independent build-only release is permitted")
    c.require(c.ref(c.RT / "active-entry.json") == value["production_hold"],
              "Production entry changed; reassess ownership/release")
    hold = c.read(c.RT / "active-entry.json")
    c.require(hold.get("execution_enabled") is False and
              hold.get("execution_mode") == "READ_ONLY_HOLD",
              "Production must remain on read-only hold during candidate build")
    for item in value["files"]:
        c.check_ref(item)
    for name in SOURCE_NAMES + ("build_candidate_r12.py",):
        c.require(c.ref(HERE / name) in value["files"], "Build source not bound")
    return c.ref(p)


def package():
    released = release()
    spec = c.read(c.HERE / "pmi-recovery-r2.json")
    vectors_path = c.check_ref(spec["original"]["vectors"])
    vectors = c.read(vectors_path)
    files = {name: (HERE / name).read_bytes() for name in SOURCE_NAMES}
    files["native-oracle-vectors.json"] = vectors_path.read_bytes()
    for row in vectors["vectors"]:
        files["probes/" + row["name"] + ".dat"] = c.check_ref(row["native"]).read_bytes()
    files["build-request.json"] = c.encoded(dict(
        schema="nuclear-closure-source-candidate-build-r12", label=LABEL,
        release=released, compiled=False, qualified=False,
        solver_dispatch=False, scope="engineering_build_only",
        source_interface="PMI_OpticalQuantumYield candidate; not activated"))
    expected = dict(spec["runtime_hashes"])
    for line in (c.OLD_OPS / "operations/nc-r1-pmi-build/collected/native-tool-header-sha256.txt").read_text().splitlines():
        digest, path = line.split(None, 1)
        expected[path.strip()] = digest
    expected.update({name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()})
    files["expected-sha256.txt"] = "".join(h + "  " + n + "\n" for n, h in sorted(expected.items())).encode()
    script = r'''set -euo pipefail
SDK=/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64
CMI=/usr/synopsys/sentaurus/W-2024.09/bin/cmi
export LD_LIBRARY_PATH="$SDK/lib:$SDK/tcad_mpi_mpich_ifort/lib:$SDK/lib/gds2tcadLib:$SDK/lib/gds2tcadLib/tbcload1.7:${LD_LIBRARY_PATH-}"
if [ ! -e /lib64/libudev.so.0 ]; then export LD_LIBRARY_PATH="$SDK/lib/patch:$LD_LIBRARY_PATH"; fi
sha256sum -c expected-sha256.txt > verified-input-runtime-hashes.txt
command -v g++ > compiler-path.txt
g++ --version > compiler-version.txt
"$CMI" -a > cmi-actual-compiler.txt
"$CMI" --compiler-version > cmi-vendor-compiler.txt
set +e
"$CMI" -O -v pmi_nuclear_qy_r12.C
code=$?
set -e
printf '%s\n' "$code" > cmi-exit-code.txt
if [ "$code" -ne 0 ]; then exit "$code"; fi
test -s pmi_nuclear_qy_r12.so.linux64
nm -D pmi_nuclear_qy_r12.so.linux64 > exported-symbols.txt
grep -E '[[:space:]]T[[:space:]]new_PMI_OpticalQuantumYield$' exported-symbols.txt
check_dependencies() {
  set +e
  ldd "$1" > "$2.txt" 2> "$2.stderr.txt"
  code=$?
  set -e
  printf '%s\n' "$code" > "$2.exit-code.txt"
  if [ "$code" -ne 0 ] || grep -q 'not found' "$2.txt" "$2.stderr.txt"; then exit 78; fi
  grep -F "libstdc++.so.6 => $SDK/lib/libstdc++.so.6" "$2.txt"
  grep -F "libgcc_s.so.1 => $SDK/lib/libgcc_s.so.1" "$2.txt"
}
check_dependencies ./pmi_nuclear_qy_r12.so.linux64 linked-libraries
g++ -O2 -std=c++14 -DR12_STANDALONE pmi_nuclear_qy_r12.C -o source_probe
g++ -O2 -std=c++14 test_context_r12.C -o context_test
check_dependencies ./source_probe probe-libraries
check_dependencies ./context_test context-libraries
set +e
./context_test > context-result.json
code=$?
set -e
printf '%s\n' "$code" > context-exit-code.txt
if [ "$code" -ne 0 ]; then exit "$code"; fi
printf 'name,actual\n' > native-oracle.csv
'''
    for row in vectors["vectors"]:
        c.require(re.fullmatch(r"[a-z_]+", row["name"]), "Unsafe oracle name")
        values = row["xyz_um"] + row["window_s"]
        c.require(all(math.isfinite(x) for x in values), "Invalid oracle arguments")
        script += "printf '" + row["name"] + ",' >> native-oracle.csv\n"
        script += " ".join(["./source_probe", "probes/" + row["name"] + ".dat"] +
                           [format(x, ".17g") for x in values]) + " >> native-oracle.csv\n"
    script += "sha256sum pmi_nuclear_qy_r12.C source_kernel_r12.hpp candidate_math_r12.hpp test_context_r12.C pmi_nuclear_qy_r12.so.linux64 source_probe context_test > native-build-sha256.txt\n"
    files["task.sh"] = script.encode()
    return files, vectors


def assert_fresh(attempt, operation):
    c.require(not Path(attempt).exists() and not Path(operation).exists(),
              "Original build attempt/operation already exists: inspect it, never redispatch")


def operation_end_state(attempt, operation):
    """A local child exit alone does not establish a disconnected remote job."""
    terminal = (attempt.get("state") in ("EXECUTED", "FAILED_OR_UNKNOWN") and
                type(attempt.get("exit_code")) is int and attempt.get("finished_utc"))
    known_remote = (operation.get("state") in ("COLLECTED_PENDING_AUDIT", "FAILED_COLLECTED") and
                    all(type(operation.get(k)) is int for k in
                        ("ssh_exit_code", "remote_exit_code", "collection_exit_code")) and
                    operation.get("collection_exit_code") == 0 and
                    bool(operation.get("archive_sha256")))
    return "READ_ONLY_HOLD" if terminal and known_remote else "RECOVERY_REQUIRED"


def recorded_operation(folder):
    out = c.RT / "source-route-r12/build-operation-status"
    status = c.RT / "status.json"
    c.write(out / "before.json", c.read(status) if status.exists() else {})
    try:
        return s.operation(LABEL, folder, "compile", timeout=1800)
    finally:
        attempt = c.RT / "attempts" / (LABEL + ".json")
        receipt = c.OLD_OPS / "operations" / LABEL / "operation.json"
        if attempt.exists():
            row = c.read(attempt)
            op = c.read(receipt) if receipt.exists() else {}
            state = operation_end_state(row, op)
            fields = dict(state=state, last_engineering_label=LABEL,
                          execution_enabled=False,
                          reason="Candidate engineering operation ended; production source qualification remains on hold")
            if state == "READ_ONLY_HOLD":
                fields.update(owner_pid=None, active_child=None, active_label=None)
            else:
                fields["reason"] = "Original candidate operation needs reconciliation; protect original directory and never redispatch"
            s.update_status(**fields)
        c.write(out / "after.json", c.read(status) if status.exists() else {})


def run_build_only():
    with s.ownership():
        release()
        attempt = c.RT / "attempts" / (LABEL + ".json")
        operation = c.OLD_OPS / "operations" / LABEL
        assert_fresh(attempt, operation)
        files, vectors = package()
        folder = c.OLD_OPS / "inputs" / LABEL
        if folder.exists():
            existing = {p.relative_to(folder).as_posix(): p.read_bytes()
                        for p in folder.rglob("*") if p.is_file()}
            c.require(existing == files, "Unsubmitted package differs; preserve it")
        else:
            folder.mkdir(parents=True, exist_ok=False)
            for name, raw in files.items():
                q = folder / name
                q.parent.mkdir(parents=True, exist_ok=True)
                with q.open("xb") as f:
                    f.write(raw)
        operation = recorded_operation(folder)
        op = c.read(operation / "operation.json")
        a = c.read(attempt)
        c.require(a["state"] == "EXECUTED" and a["exit_code"] == 0 and
                  all(op.get(k) == 0 for k in ("ssh_exit_code", "remote_exit_code", "collection_exit_code")),
                  "Build exits unknown or failed; preserve original attempt")
        archive_checks.verify_archive(operation)
        output = operation / "collected"
        for name, raw in files.items():
            c.require((output / name).read_bytes() == raw, "Archived build input changed")
        for name in ("exit-code.txt", "cmi-exit-code.txt", "context-exit-code.txt"):
            c.require((output / name).read_text().strip() == "0", "Build subcommand exit failed")
        for stem in ("linked-libraries", "probe-libraries", "context-libraries"):
            c.require((output / (stem + ".exit-code.txt")).read_text().strip() == "0", "ldd exit failed")
            text = (output / (stem + ".txt")).read_text() + (output / (stem + ".stderr.txt")).read_text()
            c.require("not found" not in text, "ldd unresolved dependency")
            for library in ("libstdc++.so.6", "libgcc_s.so.1"):
                c.require(library + " => " + SDK + "/lib/" + library in text, "Unexpected runtime")
        symbols = (output / "exported-symbols.txt").read_text()
        c.require(re.search(r"\bT\s+new_PMI_OpticalQuantumYield\s*$", symbols, re.M), "Factory missing")
        with (output / "native-oracle.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        c.require([r["name"] for r in rows] == [v["name"] for v in vectors["vectors"]], "Oracle identities changed")
        comparisons = []
        for row, v in zip(rows, vectors["vectors"]):
            actual = float(row["actual"])
            limit = max(v["comparison_abs"], v["comparison_relative"]*abs(v["expected_cm_minus3_s_minus1"]))
            error = abs(actual-v["expected_cm_minus3_s_minus1"])
            c.require(math.isfinite(actual) and error <= limit, "Original arithmetic oracle failed")
            comparisons.append(dict(name=row["name"], actual=actual, error=error, limit=limit))
        context = c.read(output / "context-result.json")
        c.require(context.get("status") == "pass" and context.get("tests") == 12,
                  "Context arithmetic tests failed or coverage changed")
        proof = dict(schema="nuclear-closure-candidate-engineering-build-r12", utc=c.utc(),
                     label=LABEL, compiled=True, qualified=False, solver_calls=0,
                     production_entry_unchanged=True, release=release(), attempt=c.ref(attempt),
                     operation=c.ref(operation / "operation.json"), archive=c.ref(operation / "results.tar"),
                     binary=c.ref(output / "pmi_nuclear_qy_r12.so.linux64"),
                     arithmetic_oracles=comparisons, simulated_context_tests=context,
                     all_outputs=[c.ref(p) for p in sorted(output.rglob("*")) if p.is_file()],
                     boundary="Compilation/linkage and isolated arithmetic only; runtime ABI, native callback/rollback, APD conversion and science qualification unproven")
        c.write(c.RT / "source-route-r12/native-build.json", proof)
        c.write(c.RT / "source-route-r12/post-build-budget.json", s.budget())
        print(c.RT / "source-route-r12/native-build.json")


if __name__ == "__main__":
    if sys.argv[1:] != ["--build-only"]:
        raise SystemExit("Only --build-only is supported; no solver or campaign entry")
    run_build_only()
