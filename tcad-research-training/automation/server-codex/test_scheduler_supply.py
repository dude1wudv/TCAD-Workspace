import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import r06_gate as gate
import scheduler_supply as supply


class SupplyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.queue = self.root / "queue.json"
        self.write(self.queue, {"schema": supply.QUEUE_SCHEMA, "tasks": []})
        (self.root / "admissions").mkdir()
        self.manifest_sha = "a" * 64
        contract = self.put("contract.json", {
            "schema": "tcad-r06-scientific-gate-contract-v1", "owner": gate.OWNER,
            "plan_id": gate.PLAN, "revision": gate.REVISION, "production_admissions_dir": "admissions",
            "manifest": {"sha256": self.manifest_sha},
        })
        self.policy = {"workspace": self.root, "queue_file": self.queue, "planner_mode": "disabled",
                       "scientific_gate": {"contract": contract}, "scheduler_supply": {"waves": []}}
        self.runtime = SimpleNamespace(intents={}, can_submit=lambda: True, limit=3, profiles={
            "tcad": {"resources": {"requested_threads": [1, 1, 4], "capacity": 3}},
            "geant4": {"resources": {"requested_threads": 1, "capacity": 3}, "limit": 1},
        })

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def put(self, name, value):
        path = self.root / name
        self.write(path, value)
        return {"path": name, "sha256": gate.sha(path)}

    def proposal(self, key, backend="tcad", **fields):
        raw = key.startswith("raw-dev-")
        project = ("local_runtime/raw-development/" if raw else "frozen/") + key
        task = {"id": key, "project": project, "backend": backend, **fields}
        proposal = self.put(key + ".json", {"schema": supply.QUEUE_SCHEMA, "tasks": [task]})
        if raw:
            return {"proposal": proposal, "input_digest": "b" * 64}
        admission = self.put(f"admissions/{key}.json", {
            "schema": "tcad-r06-production-admission-v1", "owner": gate.OWNER, "plan_id": gate.PLAN,
            "revision": gate.REVISION, "created_at": "frozen", "task_id": key, "backend": backend,
            "project": project, "profile_id": "D0-nominal", "block": "S", "manifest_sha256": self.manifest_sha,
            "scope": "transport_pool" if backend == "geant4" else "development_production",
        })
        return {"proposal": proposal, "admission_sha256": admission["sha256"]}

    def wave(self, *entries):
        refs = self.policy["scheduler_supply"]["waves"]
        refs.append(self.put(f"wave-{len(refs)}.json", {"schema": supply.WAVE_SCHEMA, "entries": list(entries)}))

    def load(self):
        return supply.load(self.policy, self.runtime, gate)

    def publish(self, snapshot, ready, queued=None):
        return supply.publish(self.policy, self.runtime, gate, self.write, staged=snapshot[0],
                              report=snapshot[1], ready=ready, queued=queued or {})

    def test_publish_ready_only_formal_first_fifo_and_preserves_originals(self):
        original = {"id": "old-identity", "backend": "tcad", "project": "original"}
        self.write(self.queue, {"schema": supply.QUEUE_SCHEMA, "tasks": [original], "metadata": "keep"})
        self.runtime.intents["old-failed"] = {"run_id": "original-run"}
        self.wave(self.proposal("raw-dev-first"), self.proposal("r06-first", repair_of="old-failed",
                  repair_reason="solver settings changed"), self.proposal("r06-blocked", depends_on=["uncollected"]))
        self.wave(self.proposal("r06-second"), self.proposal("raw-dev-later"))
        ready = {"r06-second": ("tcad", 1), "raw-dev-later": ("tcad", 4),
                 "r06-first": ("tcad", 1), "raw-dev-first": ("tcad", 4)}
        result = self.publish(self.load(), ready)
        self.assertEqual(result["published"], ["r06-first", "r06-second", "raw-dev-first"])
        queue = gate.read(self.queue)
        self.assertEqual(queue["metadata"], "keep")
        self.assertEqual(queue["tasks"][0], original)
        self.assertEqual(queue["tasks"][1]["repair_of"], "old-failed")
        self.assertEqual(queue["tasks"][3]["supply_input_digest"], "b" * 64)
        self.assertEqual(self.runtime.intents, {"old-failed": {"run_id": "original-run"}})
        again = self.publish(self.load(), ready, {key: ready[key] for key in result["published"]})
        self.assertEqual(set(again["existing"]), set(result["published"]))
        self.assertEqual(again["published"], [])
        self.assertEqual(gate.read(self.queue), queue)

    def test_existing_ready_work_and_geant_limit_bound_width_backlog(self):
        self.wave(self.proposal("r06-t1"), self.proposal("r06-t4"),
                  self.proposal("r06-g1", "geant4"), self.proposal("r06-g2", "geant4"))
        ready = {"r06-t1": ("tcad", 1), "r06-t4": ("tcad", 4),
                 "r06-g1": ("geant4", 1), "r06-g2": ("geant4", 1)}
        queued = {"first": ("tcad", 1), "second": ("tcad", 1)}
        result = self.publish(self.load(), ready, queued)
        self.assertEqual(result["published"], ["r06-t4", "r06-g1"])

    def test_reject_mutation_wrong_raw_scope_and_claimed_intent_independently(self):
        claimed = self.proposal("r06-claimed")
        self.runtime.intents["r06-claimed"] = {"run_id": "historical"}
        changed = self.proposal("r06-changed")
        (self.root / changed["proposal"]["path"]).write_text("{}", encoding="utf-8")
        self.wave(claimed, changed, self.proposal("raw-dev-wrong", "geant4"), self.proposal("r06-good"))
        staged, report = self.load()
        self.assertEqual(list(staged), ["r06-good"])
        self.assertEqual(set(report["blocked"]), {"r06-claimed", "wave-0-entry-1", "wave-0-entry-2"})

    def test_paused_or_changed_queue_keeps_original_content(self):
        self.wave(self.proposal("r06-ready"))
        snapshot = self.load()
        ready = {"r06-ready": ("tcad", 1)}
        self.runtime.can_submit = lambda: False
        with self.assertRaisesRegex(ValueError, "paused"):
            self.publish(snapshot, ready)
        replacement = {"schema": supply.QUEUE_SCHEMA, "tasks": [], "changed": True}
        self.write(self.queue, replacement)
        self.runtime.can_submit = lambda: True
        with self.assertRaisesRegex(ValueError, "queue changed"):
            self.publish(snapshot, ready)
        self.assertEqual(gate.read(self.queue), replacement)

    def test_async_planner_requires_explicit_isolation_from_canonical_queue(self):
        self.policy["planner_mode"] = "on_demand_async"
        self.wave(self.proposal("r06-ready"))
        with self.assertRaisesRegex(ValueError, "write-isolated"):
            self.load()
        staged, _ = supply.load(self.policy, self.runtime, gate, planner_isolated=True)
        self.assertEqual(list(staged), ["r06-ready"])
