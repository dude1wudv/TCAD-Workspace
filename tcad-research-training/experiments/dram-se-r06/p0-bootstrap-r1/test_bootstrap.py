"""Offline package checks. No native ELF is fabricated, compiled, or executed."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import check
import logging_patch
import prepare

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORK = HERE / ".test-work"
WORK.mkdir(exist_ok=True)


class SourceTests(unittest.TestCase):
    def test_exact_logging_transform_and_error_call_sites(self):
        result = logging_patch.verify(HERE)
        self.assertTrue(result["physical_and_solver_code_unchanged"])
        before = (HERE / "evidence/original-pmi_r04_nodal.C").read_text()
        after = (HERE / "source/pmi_r04_nodal.C").read_text()
        self.assertEqual(after, logging_patch.patched(before.encode()).decode())
        self.assertNotIn("callbacks_{0}", after)
        self.assertEqual(after.count("source_ = r04nodal::Source::load_file"), 1)
        self.assertEqual(before.count("WriteUserField("), after.count("WriteUserField("))
        for error in ('LogData()->PMIError("R04_QY_INPUT: %s", error.what());',
                      'LogData()->PMIError("R04_QY_COMPUTE: %s", error.what());'):
            self.assertEqual(before.count(error), 1)
            self.assertEqual(after.count(error), 1)

    def test_drifted_parent_rejected(self):
        original = (HERE / "evidence/original-pmi_r04_nodal.C").read_bytes()
        with self.assertRaisesRegex(ValueError, "frozen"):
            logging_patch.patched(original.replace(b"1e38", b"2e38", 1))

    def test_build_script_has_original_environment_and_no_solver(self):
        text = (HERE / "compile-in-original-vm.sh").read_text()
        self.assertIn(prepare.CMI, text)
        self.assertIn('test ! -e pmi_r04_nodal.so.linux64', text)
        self.assertIn('grep -q \'CentOS Linux release 7\'', text)
        self.assertNotIn("sdevice --", text)
        self.assertNotIn("ssh ", text)
        self.assertNotIn("tcad.py", text)
        self.assertIn('"$CMI" -O -v pmi_r04_nodal.C', text)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / prepare.RELATIVE
        self.package.mkdir(parents=True)
        self.parent = self.root / "frozen-input"
        self.parent.mkdir()
        # Intentionally synthetic non-native fixture. Never submitted or compiled.
        for name in prepare.COPY:
            (self.parent / name).write_text("SYNTHETIC_OFFLINE_FIXTURE\n", encoding="utf-8")
        (self.parent / "nodal-source.dat").write_text(
            "R04_NODAL_SOURCE 1 10170 0 0\n", encoding="utf-8")
        for name, source in (
            ("device.cmd", HERE / "evidence/original-device.cmd"),
            (prepare.MODEL, HERE / "evidence/original-pmi_r04_nodal.C"),
        ):
            (self.parent / name).write_bytes(source.read_bytes())
        prepare.save(self.parent / "project.json", {
            "native_threads": 2, "native_cores": 2,
            "steps": [{"tool": "sdevice", "args": ["device.cmd"]}]})
        (self.package / "evidence").mkdir()
        (self.package / "source").mkdir()
        for relative in ("evidence/original-pmi_r04_nodal.C", "source/pmi_r04_nodal.C",
                         "compile-in-original-vm.sh"):
            (self.package / relative).write_bytes((HERE / relative).read_bytes())
        prepare.save(self.package / "evidence/remote-survey.json", {
            "prefix_inputs": [{"path": "frozen-input", "files": prepare.inventory(self.parent)}],
            "confirmed_15p2ns_decks": [],
        })
        self.initial_parent = prepare.inventory(self.parent)

    def test_audit_and_stage_copy_only_source_no_elf(self):
        result = prepare.audit(self.root, self.package)
        self.assertFalse(result["solver_called"])
        output = self.package / "fresh-build"
        prepare.stage_build(self.root, self.package, output)
        self.assertFalse((output / prepare.ELF).exists())
        self.assertFalse((output / "build-receipt.json").exists())
        self.assertEqual(prepare.sha(output / prepare.MODEL),
                         prepare.sha(HERE / "source" / prepare.MODEL))
        for name in ("nodal_source.hpp", "voxel_source.hpp"):
            self.assertEqual(prepare.sha(output / name), self.initial_parent[name])
        self.assertEqual(prepare.inventory(self.parent), self.initial_parent)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            prepare.stage_build(self.root, self.package, output)

    def test_changed_parent_fails_before_build_directory_creation(self):
        (self.parent / "device.cmd").write_text("changed", encoding="utf-8")
        output = self.package / "must-not-exist"
        with self.assertRaisesRegex(ValueError, "prefix changed"):
            prepare.stage_build(self.root, self.package, output)
        self.assertFalse(output.exists())

    def test_missing_real_cmi_receipt_blocks_materialization(self):
        build = self.package / "fresh-build"
        prepare.stage_build(self.root, self.package, build)
        output = self.package / "must-not-exist"
        with self.assertRaises(FileNotFoundError):
            prepare.materialize(self.root, self.package, build, output)
        self.assertFalse(output.exists())
        self.assertEqual(prepare.inventory(self.parent), self.initial_parent)

    def test_paths_cannot_escape_or_overwrite_frozen_parent(self):
        for name in ("../elsewhere", "C:/elsewhere", "/absolute", "a\\b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare.safe_path(self.root, name)


class LogTests(unittest.TestCase):
    def sample(self):
        return (
            "".join(f"R04_NODAL_INIT log_version=r06-o2-global-r1 n={n} nodes=10170\n"
                    for n in (2, 1, 4, 3))
            + "R06_O2_INIT_LIMIT log_version=r06-o2-global-r1\n"
            + "".join(f"R04_QY_CALLBACK n={n} region=R time=0 G=0 eta=0\n"
                      for n in range(512, 0, -1))
            +
            "R04_QY_TRACE_LIMIT: omitted globally\n"
            "R06_O2_CALLBACK_PROGRESS n=1024 callback_count_not_accepted_steps=true\n"
            "warning: native warning retained\n"
            "R04_QY_COMPUTE: synthetic failure inventory\n"
            "R06_O2_PLUGIN_UNLOAD_SUMMARY log_version=r06-o2-global-r1 "
            "initializations=27200 callbacks=1024 solver_success=unknown accepted_steps=unknown\n"
        )

    def run_check(self, content):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            path = Path(directory) / "synthetic-log.txt"
            path.write_text(content, encoding="utf-8")
            return check.log_check(path, require_unload_summary=True)

    def test_unordered_global_counters_are_not_accepted_steps(self):
        result = self.run_check(self.sample())
        self.assertEqual(result["status"], "passed_log_bounds_only")
        self.assertFalse(result["o2_scientific_gate_passed"])
        self.assertFalse(result["native_completion_verified"])

    def test_repeated_per_instance_ids_and_missing_summary_fail(self):
        sample = self.sample()
        cases = (
            sample + "R04_QY_CALLBACK n=1 region=R\n",
            sample + "R04_NODAL_INIT log_version=r06-o2-global-r1 n=1 nodes=10170\n",
            sample.split("R06_O2_PLUGIN_UNLOAD_SUMMARY")[0],
            sample.replace("n=1024", "n=1025"),
            sample.replace("callbacks=1024", "callbacks=1"),
        )
        for content in cases:
            with self.subTest(content=content[-50:]):
                self.assertEqual(self.run_check(content)["status"], "failed_log_bounds")


class GateContractTests(unittest.TestCase):
    def test_frozen_zero_bootstrap_criteria_fit_current_main_agent_gate(self):
        spec = importlib.util.spec_from_file_location(
            "_read_only_main_r06_gate", REPO / "automation/server-codex/r06_gate.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        # The gate is exercised on non-native synthetic files, with no ELF.
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            root = Path(directory)
            project = root / "inputs/zero"
            project.mkdir(parents=True)
            prepare.save(project / "project.json", {
                "native_threads": 2, "native_cores": 2,
                "steps": [{"tool": "sdevice", "args": ["device.cmd"]}]})
            (project / "device.cmd").write_text(
                "Transient(InitialTime=0 FinalTime=1e-13) {}\n", encoding="utf-8")
            (project / "nodal-source.dat").write_text(
                "R04_NODAL_SOURCE 1 10170 0 0\n", encoding="utf-8")
            plan = {"schema": "tcad-r06-diagnostic-plan-v1", "recipe_id": "zero_whr",
                    "profile_id": "D0-nominal", "frozen_before_submission": True,
                    "acceptance_criteria": prepare.CRITERIA}
            prepare.save(root / "plan.json", plan)
            task = {"id": prepare.TASKS[0], "backend": "tcad", "project": "inputs/zero"}
            admission = {
                "schema": "tcad-r06-p0-admission-v1", **prepare.ENVELOPE,
                "task_id": task["id"], "backend": "tcad", "project": task["project"],
                "input_sha256": gate.input_hashes(project), "scope": "p0_diagnostic",
                "formal_case_id": None, "statistics_eligible": False,
                "budget_account": "p0_diagnostics", "created_at": "2026-11-17T00:00:00Z",
                "profile_id": "D0-nominal", "recipe_id": "zero_whr",
                "purpose": prepare.PURPOSE, "diagnostic_plan": prepare.ref(root, root / "plan.json"),
            }
            (root / "admissions").mkdir()
            path = root / "admissions" / (task["id"] + ".json")
            prepare.save(path, admission)
            (root / "authority.txt").write_text("SYNTHETIC OFFLINE TEST AUTHORITY\n",
                                               encoding="utf-8")
            manifest = {**prepare.ENVELOPE, "profiles": [{"id": "D0-nominal"}]}
            prepare.save(root / "manifest.json", manifest)
            contract = {
                **prepare.ENVELOPE, "schema": "tcad-r06-scientific-gate-contract-v1",
                "p0_admissions_dir": "admissions", "max_p0_tasks": 64,
                "max_p0_particle_tasks": 12, "authority": prepare.ref(root, root / "authority.txt"),
                "manifest": prepare.ref(root, root / "manifest.json"),
            }
            prepare.save(root / "contract.json", contract)
            policy = {"scientific_gate": {
                "schema": "tcad-r06-scientific-gate-policy-v1",
                "contract": prepare.ref(root, root / "contract.json"),
            }}
            result = gate.verify(root, policy, task, intents={})
            self.assertEqual(result["scope"], "p0_diagnostic")
            self.assertEqual(result["recipe_id"], "zero_whr")
            wrong = copy.deepcopy(admission)
            wrong["input_sha256"] = {}
            path.write_text(json.dumps(wrong), encoding="utf-8")
            with self.assertRaises(gate.Pending):
                gate.verify(root, policy, task, intents={})


if __name__ == "__main__":
    unittest.main(verbosity=2)
