"""Isolated manifest, selector and transport-audit checks; fixtures live only in validation-dev."""
import ast
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_DEV = ROOT / "local_runtime/dram-see-v4/nuclear-closure-r1/validation-dev"
sys.path.insert(0, str(HERE))
import common as c
import transport as t


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auditor = load("_nuclear_closure_validation_auditor", HERE / "transport_audit.py")
registrar = load("_nuclear_closure_validation_register", HERE / "register_contract.py")


def sandbox(test, prefix="transport-"):
    temp = tempfile.TemporaryDirectory(prefix=prefix, dir=VALIDATION_DEV)
    test.addCleanup(temp.cleanup)
    root = Path(temp.name) / "root"
    root.mkdir()
    rt = root / "local_runtime/dram-see-v4/nuclear-closure-r1"
    old = root / "local_runtime/dram-see-v4/transport-probe"
    here = root / "experiments/dram-see-v4/nuclear-closure-r1"
    geometry = root / "experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json"
    for path in (rt, old, here, geometry.parent):
        path.mkdir(parents=True, exist_ok=True)
    stack = mock.patch.multiple(c, ROOT=root, RT=rt, OLD_OPS=old, HERE=here, GEOMETRY=geometry)
    stack.start()
    test.addCleanup(stack.stop)
    stack_audit = mock.patch.multiple(auditor, ROOT=root, HERE=here)
    stack_audit.start()
    test.addCleanup(stack_audit.stop)
    return root, rt, old, here, geometry


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenManifestTests(unittest.TestCase):
    def test_contract_materializer_reproduces_fixed_107_request_manifest_without_writing(self):
        root, _, _, here, geometry = sandbox(self, "manifest-")
        old_contract = json.loads((HERE.parent / "matched-transport-r1/matched-contract.json").read_text(encoding="utf-8"))
        old_outcome = ROOT / "local_runtime/dram-see-v4/interface-completion-r1/outcomes/r5-a1-b1-fine-r1.json"
        old_tree = here.parent / "matched-transport-r1"
        old_tree.mkdir(parents=True)
        (old_tree / "matched-contract.json").write_text(json.dumps(old_contract), encoding="utf-8")
        source_geometry = HERE.parent / "source-interface-3d-r1/geometry-contract.json"
        geometry.write_bytes(source_geometry.read_bytes())
        failure_rel = Path("local_runtime/dram-see-v4/interface-completion-r1/outcomes/r5-a1-b1-fine-r1.json")
        failure = root / failure_rel
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_bytes(old_outcome.read_bytes())

        value, transport = registrar.values()
        checked_value = json.loads((HERE / "contract.json").read_text(encoding="utf-8"))
        checked_transport = json.loads((HERE / "transport-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(value, checked_value)
        self.assertEqual(transport, checked_transport)
        requests = transport["requests"]
        self.assertEqual(len(requests), 107)
        self.assertEqual(len({r["label"] for r in requests}), 107)
        self.assertEqual(sum(r["event_count"] for r in requests), 1000008)
        self.assertEqual({stage: sum(r["closure_stage"] == stage for r in requests)
                          for stage in ("P0", "N1", "N2", "N3", "N4")},
                         {"P0": 6, "N1": 1, "N2": 1, "N3": 9, "N4": 90})
        normal = [r for r in requests if r["closure_stage"] != "P0"]
        self.assertEqual(len({r["seed"] for r in normal}), 101)
        self.assertEqual([r["seed"] for r in normal], list(range(50150001, 50150102)))


class DeterministicSelectionTests(unittest.TestCase):
    def _prepare(self, test):
        root, rt, _, here, geometry = sandbox(test, "selection-")
        geo = {"fixture": "same-geometry"}
        geometry.write_text(json.dumps(geo, sort_keys=True), encoding="utf-8")
        digest = sha(geometry)
        req_a = {"label": "nc-r1-h-first", "mode": "normal", "arm": "H", "closure_stage": "N1",
                 "event_count": 1000, "geometry_sha256": digest}
        req_b = {"label": "nc-r1-h-second", "mode": "normal", "arm": "H", "closure_stage": "N1",
                 "event_count": 1000, "geometry_sha256": digest}
        manifest = {"schema": "fixture", "closure_revision": "nuclear-closure-r1",
                    "geometry_sha256": digest, "requests": [req_a, req_b]}
        (here / "transport-contract.json").write_text(json.dumps(manifest), encoding="utf-8")
        write_json(here / "contract.json", {"transport": {"selection": "frozen order then numeric event_id"}})
        for request, event_rows in ((req_a, [(8, 2, 2.0, 2.2, 1.0), (2, 3, 2.8, 3.2, 0.2),
                                           (2, 3, 3.5, 3.8, 50.0)]),
                                    (req_b, [(1, 9, 0.2, 0.3, 100.0)])):
            run = rt / "transport/runs" / request["label"]
            audit_dir = rt / "transport/audits" / request["label"]
            run.mkdir(parents=True)
            audit_dir.mkdir(parents=True)
            write_json(run / "record.json", {"request": request})
            write_json(audit_dir / "audit.json", {"passed": True})
            with (run / "steps.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["event_id", "track_id", "step_id", "pre_material", "ionizing_MeV", "pre_t_ns", "post_t_ns"])
                for eid, track, t0, t1, energy in event_rows:
                    writer.writerow([eid, track, 1, "G4_Si", energy, t0, t1])
        return req_a, req_b

    def test_selection_waits_for_every_audited_request_then_uses_request_and_numeric_event_order(self):
        req_a, req_b = self._prepare(self)
        calls = []
        reports = {
            req_a["label"]: {"passed": True, "mechanism_summary": {"qualifying_witnesses": [
                {"event_id": 8, "parent_track_id": 1, "parent_step_id": 2, "descendant_track_ids": [2]},
                {"event_id": 2, "parent_track_id": 1, "parent_step_id": 1, "descendant_track_ids": [3]},
            ]}},
            req_b["label"]: {"passed": True, "response_score": 999999,
                             "mechanism_summary": {"qualifying_witnesses": [
                                 {"event_id": 1, "parent_track_id": 1, "parent_step_id": 1, "descendant_track_ids": [9]}]}},
        }
        with mock.patch.object(t, "audit", side_effect=lambda label: calls.append(label) or reports[label]):
            selected = t.choose("N1")
        self.assertEqual(calls, [req_a["label"], req_b["label"]])
        self.assertEqual(selected["request"]["label"], req_a["label"])
        self.assertEqual(selected["event_id"], 2)
        self.assertAlmostEqual(selected["witness"]["window_descendant_si_ionizing_MeV"], 0.1)
        self.assertEqual(selected["witness"]["window_descendant_step_ids"], [[2, 3, 1]])

    def test_failed_or_incomplete_request_blocks_selection_for_the_whole_stage(self):
        req_a, req_b = self._prepare(self)
        calls = []
        reports = {req_a["label"]: {"passed": True, "mechanism_summary": {"qualifying_witnesses": [
            {"event_id": 2, "parent_track_id": 1, "parent_step_id": 1, "descendant_track_ids": [3]}]}},
            req_b["label"]: {"passed": False}}
        with mock.patch.object(t, "audit", side_effect=lambda label: calls.append(label) or reports[label]):
            with self.assertRaisesRegex(ValueError, "Incomplete/failed stage"):
                t.choose("N1")
        self.assertEqual(calls, [req_a["label"], req_b["label"]])


class ReceiptAndAncestryTests(unittest.TestCase):
    def _receipt_fixture(self, test):
        root, rt, old, here, geometry_path = sandbox(test, "receipt-")
        label = "nc-r1-h-000"
        request = {"label": label, "mode": "normal", "arm": "H", "geometry_sha256": "", "event_count": 1000}
        geometry = {"name": "isolated geometry"}
        geometry_bytes = (json.dumps(geometry, sort_keys=True) + "\n").encode()
        geometry_path.write_bytes(geometry_bytes)
        request["geometry_sha256"] = sha(geometry_path)
        contract = {"schema": "dram-see-v4-matched-transport-contract-r1", "geometry_sha256": sha(geometry_path),
                    "geometry": geometry,
                    "geometry_path": "experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json",
                    "csv_arithmetic_tolerances": dict(auditor.TOLERANCES), "requests": [request]}
        write_json(here / "transport-contract.json", contract)
        run = rt / "transport/runs" / label
        run.mkdir(parents=True)
        names = ["task.sh", "run.sh", "exit-code.txt", "execution.log", "affinity.txt", "metadata.json", "status.json",
                 "constructors.csv", "processes.csv", "hadronic-models.csv", "materials.csv", "elements.csv", "cuts.csv",
                 "events.csv", "tracks.csv", "steps.csv", "birth-links.csv", "status-history.jsonl", "particles.csv",
                 "material-energy.csv", "geometry-built.csv", "timings.csv", "geometry.hh", "geometry-contract.json",
                 "matched-contract.json", "request.json"]
        content = {name: (json.dumps(request, sort_keys=True) + "\n").encode() if name == "request.json" else
                   (b"0\n" if name == "exit-code.txt" else (name + "\n").encode()) for name in names}
        content["geometry-contract.json"] = geometry_bytes
        content["matched-contract.json"] = (json.dumps(contract, sort_keys=True) + "\n").encode()
        for name, data in content.items():
            (run / name).write_bytes(data)
        input_hashes = {name: sha(run / name) for name in ("task.sh", "request.json")}
        output_hashes = {name: sha(run / name) for name in names}
        raw_op_dir = old / "operations" / label
        raw_op_dir.mkdir(parents=True)
        archive = raw_op_dir / "results.tar"
        with tarfile.open(archive, "w") as tar:
            for name in names:
                tar.add(run / name, arcname=name)
        op_record = {"schema": "dram-see-v4-transport-operation-v1", "label": label,
                     "ssh_exit_code": 0, "remote_exit_code": 0, "collection_exit_code": 0,
                     "archive_sha256": sha(archive), "input_sha256": input_hashes}
        op_path = write_json(raw_op_dir / "operation.json", op_record)
        record = {"schema": "dram-see-v4-matched-run-r1", "run_id": label, "request": request,
                  "runner_exit_code": 0, "remote_exit_code": 0, "collection_exit_code": 0,
                  "input_sha256": input_hashes, "output_sha256": output_hashes,
                  "raw_archive": {"path": archive.relative_to(root).as_posix(), "sha256": sha(archive)},
                  "operation_evidence": {"path": op_path.relative_to(root).as_posix(), "sha256": sha(op_path)}}
        record_path = write_json(run / "record.json", record)
        return root, run, record_path, archive, op_path, request

    @staticmethod
    def _mechanism_fixture(folder):
        token = "e0:t1:s1:n1"
        tracks = [
            {"event_id": 0, "track_id": 1, "parent_id": 0, "particle": "proton", "pdg": 2212,
             "creator_type": 0, "creator_subtype": 0, "creator_process": "primary", "birth_token": "primary",
             "parent_step_id": 0, "end_track_status": 2, "termination_process": "protonInelastic",
             "termination_process_type": 4, "termination_process_subtype": 121, "termination_reason": "natural_stop_or_absorption", "end_ke_MeV": 0.0,
             "birth_t_ns": 0.0, "end_volume": "R.Si", "end_t_ns": 1.0, "ionizing_si_MeV": 0.0, "charge_e": 1.0,
             "ended_by_neutron_tracking_cut": 0, "direct_hadronic_child": 0, "creator_lineage_hadronic": 0,
             "em_from_hadronic_lineage": 0, "em_from_post_hadronic_primary": 0, "em_in_primary_hadronic_transition_step": 0},
            {"event_id": 0, "track_id": 2, "parent_id": 1, "particle": "proton", "pdg": 2212,
             "creator_type": 4, "creator_subtype": 121, "creator_process": "protonInelastic", "birth_token": token,
             "parent_step_id": 1, "end_track_status": 2, "termination_process": "ionIoni",
             "termination_process_type": 2, "termination_process_subtype": 2, "termination_reason": "natural_stop_or_absorption", "end_ke_MeV": 0.0,
             "birth_t_ns": 1.0, "end_volume": "R.Si", "end_t_ns": 1.5, "ionizing_si_MeV": 0.5, "charge_e": 1.0,
             "ended_by_neutron_tracking_cut": 0, "direct_hadronic_child": 1, "creator_lineage_hadronic": 1,
             "em_from_hadronic_lineage": 0, "em_from_post_hadronic_primary": 0, "em_in_primary_hadronic_transition_step": 0},
        ]
        steps = [
            {"event_id": 0, "track_id": 1, "parent_id": 0, "step_id": 1, "particle": "proton", "pdg": 2212,
             "post_process": "protonInelastic", "post_process_type": 4, "post_process_subtype": 121,
             "pre_step_status": 1, "post_step_status": 3, "secondary_count": 1, "pre_volume": "World",
             "post_volume": "R.Si", "pre_material": "G4_Galactic", "post_material": "G4_Si",
             "pre_x_um": 0.0, "pre_y_um": 0.0, "pre_z_um": 0.0, "post_x_um": 1.0, "post_y_um": 0.0,
             "post_z_um": 0.0, "pre_t_ns": 0.5, "post_t_ns": 1.0, "step_um": 1.0, "chord_um": 1.0,
             "edep_MeV": 0.0, "niel_MeV": 0.0, "ionizing_MeV": 0.0, "local_ionizing_MeV_per_um": 0.0,
             "deposit_kind": "zero_ionizing", "neutron_tracking_cut_step": 0,
             "track_hadronic_before": 0, "track_hadronic_after": 1},
            {"event_id": 0, "track_id": 2, "parent_id": 1, "step_id": 1, "particle": "proton", "pdg": 2212,
             "post_process": "ionIoni", "post_process_type": 2, "post_process_subtype": 2,
             "pre_step_status": 1, "post_step_status": 3, "secondary_count": 0, "pre_volume": "R.Si",
             "post_volume": "R.Si", "pre_material": "G4_Si", "post_material": "G4_Si",
             "pre_x_um": 1.0, "pre_y_um": 0.0, "pre_z_um": 0.0, "post_x_um": 1.5, "post_y_um": 0.0,
             "post_z_um": 0.0, "pre_t_ns": 1.0, "post_t_ns": 1.5, "step_um": 0.5, "chord_um": 0.5,
             "edep_MeV": 0.5, "niel_MeV": 0.0, "ionizing_MeV": 0.5, "local_ionizing_MeV_per_um": 1.0,
             "deposit_kind": "finite_path", "neutron_tracking_cut_step": 0,
             "track_hadronic_before": 0, "track_hadronic_after": 0},
        ]
        links = [{"event_id": 0, "parent_track_id": 1, "parent_step_id": 1, "secondary_ordinal": 1,
                  "child_track_id": 2, "creator_type": 4, "creator_subtype": 121, "parent_hadronic_before": 0,
                  "parent_hadronic_after": 1, "birth_token": token, "creator_process": "protonInelastic"}]
        report = {}
        return tracks, steps, links, {"arm": "H", "max_step_um": 1.0}, report

    def test_original_receipt_and_archive_hashes_are_bound_to_the_exact_frozen_request(self):
        _, run, _, _, _, request = self._receipt_fixture(self)
        report = {}
        record = auditor._receipt(run, report)
        self.assertEqual(record["request"], request)
        self.assertEqual(report["run_id"], request["label"])
        self.assertEqual(report["exit_codes"], {"runner_exit_code": 0, "remote_exit_code": 0, "collection_exit_code": 0})

    def test_changed_original_receipt_and_unknown_exit_fail_closed(self):
        _, run, _, _, op_path, _ = self._receipt_fixture(self)
        op = json.loads(op_path.read_text(encoding="utf-8"))
        op["remote_exit_code"] = None
        write_json(op_path, op)
        with self.assertRaisesRegex(ValueError, "Original operation receipt hash mismatch"):
            auditor._receipt(run, {})

    def test_native_proton_inelastic_birth_link_and_positive_si_descendant_define_witness(self):
        root, _, _, _, _ = sandbox(self, "ancestry-")
        folder = root / "fixture-run"
        folder.mkdir()
        headers = ["event_id", "parent_track_id", "parent_step_id", "secondary_ordinal", "child_track_id",
                   "creator_type", "creator_subtype", "parent_hadronic_before", "parent_hadronic_after",
                   "birth_token", "creator_process"]
        tracks, steps, links, metadata, report = self._mechanism_fixture(folder)
        with (folder / "birth-links.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers); writer.writeheader(); writer.writerows(links)
        with (folder / "processes.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["particle", "pdg", "process", "process_type", "process_subtype", "is_neutron_killer"])
            writer.writeheader()
            writer.writerows([
                {"particle": "proton", "pdg": 2212, "process": "protonInelastic", "process_type": 4,
                 "process_subtype": 121, "is_neutron_killer": 0},
                {"particle": "proton", "pdg": 2212, "process": "ionIoni", "process_type": 2,
                 "process_subtype": 2, "is_neutron_killer": 0},
            ])
        self.assertTrue(auditor._mechanisms(folder, metadata, ([], tracks, steps), report))
        witness = report["mechanism_summary"]["qualifying_witnesses"]
        self.assertEqual(len(witness), 1)
        self.assertEqual(witness[0]["process"], "protonInelastic")
        self.assertEqual(witness[0]["direct_child_track_ids"], [2])
        self.assertEqual(witness[0]["descendant_track_ids"], [2])
        self.assertAlmostEqual(witness[0]["descendant_si_ionizing_MeV"], 0.5)

    def test_nonprotoninelastic_creator_cannot_be_relabelled_as_a_nuclear_witness(self):
        root, _, _, _, _ = sandbox(self, "ancestry-negative-")
        folder = root / "fixture-run"; folder.mkdir()
        headers = ["event_id", "parent_track_id", "parent_step_id", "secondary_ordinal", "child_track_id",
                   "creator_type", "creator_subtype", "parent_hadronic_before", "parent_hadronic_after",
                   "birth_token", "creator_process"]
        tracks, steps, links, metadata, report = self._mechanism_fixture(folder)
        tracks[0]["termination_process"] = "protonNuclear"
        tracks[0]["termination_reason"] = "natural_stop_or_absorption"
        tracks[1]["creator_process"] = "protonNuclear"
        links[0]["creator_process"] = "protonNuclear"
        steps[0]["post_process"] = "protonNuclear"
        with (folder / "birth-links.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers); writer.writeheader(); writer.writerows(links)
        with (folder / "processes.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["particle", "pdg", "process", "process_type", "process_subtype", "is_neutron_killer"])
            writer.writeheader()
            writer.writerows([
                {"particle": "proton", "pdg": 2212, "process": "protonInelastic", "process_type": 4,
                 "process_subtype": 121, "is_neutron_killer": 0},
                {"particle": "proton", "pdg": 2212, "process": "protonNuclear", "process_type": 4,
                 "process_subtype": 121, "is_neutron_killer": 0},
                {"particle": "proton", "pdg": 2212, "process": "ionIoni", "process_type": 2,
                 "process_subtype": 2, "is_neutron_killer": 0},
            ])
        self.assertTrue(auditor._mechanisms(folder, metadata, ([], tracks, steps), report))
        self.assertFalse(report["mechanism_summary"]["witness_found"])
        self.assertEqual(report["mechanism_summary"]["qualifying_witnesses"], [])

    def test_audit_derivative_changes_only_explicit_identity_and_path_sites(self):
        original = HERE.parent / "matched-transport-r1/audit_matched.py"
        derivative = HERE / "transport_audit.py"
        original_source = original.read_text(encoding="utf-8")
        self.assertEqual(sha(original), "d538c3aa7fd2007fb7ebb252f9f89a5239415924411a8731a75c6d8de482e649")
        self.assertIn("original audit SHA256: d538c3aa7fd2007fb7ebb252f9f89a5239415924411a8731a75c6d8de482e649", derivative.read_text(encoding="utf-8").splitlines()[0])
        def functions(text):
            lines = text.splitlines()
            tree = ast.parse(text)
            return {n.name: (n, "\n".join(lines[n.lineno-1:n.end_lineno])) for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        old, new = functions(original_source), functions(derivative.read_text(encoding="utf-8"))
        self.assertEqual(set(old), set(new))
        changed = {name for name in old if ast.dump(old[name][0], include_attributes=False) !=
                   ast.dump(new[name][0], include_attributes=False)}
        self.assertEqual(changed, {"_receipt", "_provenance", "_audit", "_write"})
        replacements = {
            "_receipt": [(r"nc-r1-[a-z0-9-]+", r"matched-[a-z0-9-]+"),
                          ("local_runtime/dram-see-v4/nuclear-closure-r1/transport/runs", "local_runtime/dram-see-v4/matched-transport-r1/runs"),
                          ("HERE / 'transport-contract.json'", "HERE / 'matched-contract.json'"),
                          ("fixed nuclear-closure contract", "fixed six-call contract")],
            "_provenance": [("HERE/'transport.py'", "HERE/'control.py'")],
            "_audit": [("dram-see-v4-nuclear-closure-transport-audit-r1", "dram-see-v4-matched-audit-r1")],
            "_write": [("local_runtime/dram-see-v4/nuclear-closure-r1", "local_runtime/dram-see-v4/matched-transport-r1")],
        }
        for name, pairs in replacements.items():
            normalized = new[name][1]
            for before, after in pairs:
                normalized = normalized.replace(before, after)
            self.assertEqual(ast.dump(ast.parse(normalized).body[0], include_attributes=False),
                             ast.dump(old[name][0], include_attributes=False), name)
        self.assertEqual(auditor.TOLERANCES, {
            "energy_abs_MeV": 1e-12, "energy_relative": 1e-9, "time_abs_ns": 1e-9,
            "position_abs_um": 1e-9, "direction_norm_abs": 1e-10})


if __name__ == "__main__":
    unittest.main()
