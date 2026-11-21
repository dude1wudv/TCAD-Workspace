import json
import unittest
from scheduler_pool import PoolStateMachine


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.pool = PoolStateMachine(self.state, {"min_profile_dwell_seconds": 100, "max_profile_ready_wait_seconds": 200})
        self.live = [{"requested_resources": {"schema": "tcad"}, "status": "running"}]
        self.ready = [{"id": "t", "profile": "tcad", "priority": 100},
                      {"id": "g", "profile": "geant4", "priority": 100}]

    def test_new_other_profile_does_not_block_backfill(self):
        state, selected = self.pool.reconcile(self.live, self.ready, 10)
        self.assertEqual(selected, "tcad")
        self.assertEqual(state["state"], "ACTIVE")

    def test_same_priority_wait_is_bounded_and_target_survives_idle(self):
        self.pool.reconcile(self.live, self.ready, 10)
        state, selected = self.pool.reconcile(self.live, self.ready, 210)
        self.assertEqual(state["state"], "DRAINING")
        self.assertIsNone(selected)
        state, selected = PoolStateMachine(self.state).reconcile([], list(reversed(self.ready)), 215)
        self.assertEqual(selected, "geant4")
        self.pool.submitted("geant4", 215)
        self.assertNotIn("target", self.state)

    def test_higher_priority_waits_for_dwell(self):
        self.ready[1]["priority"] = 1
        self.assertEqual(self.pool.reconcile(self.live, self.ready, 10)[1], "tcad")
        self.assertIsNone(self.pool.reconcile(self.live, self.ready, 110)[1])

    def test_current_queue_exhausted_drains_immediately(self):
        self.assertIsNone(self.pool.reconcile(self.live, self.ready[1:], 10)[1])
        self.assertEqual(self.state["reason"], "current_profile_queue_exhausted")

    def test_target_loses_readiness_restores_backfill(self):
        self.pool.reconcile(self.live, self.ready[1:], 10)
        self.assertEqual(self.pool.reconcile(self.live, self.ready[:1], 11)[1], "tcad")

    def test_manual_drain_survives_restart_and_unready_target(self):
        self.pool.request_drain("geant4", "operator", 1)
        state, selected = PoolStateMachine(self.state).reconcile([], self.ready[:1], 10)
        self.assertEqual(selected, "geant4")
        self.assertEqual(state["blocked_reason"], "drain_target_not_ready")

    def test_quarantine_restores_automatic_backfill_but_preserves_manual(self):
        self.pool.reconcile(self.live, self.ready[1:], 10)
        self.live[0]["task_state"] = "QUARANTINED"
        state, selected = self.pool.reconcile(self.live, self.ready, 11)
        self.assertEqual(selected, "tcad")
        self.assertEqual(state["blocked_reason"], "blocked_by_quarantined_slot")
        self.pool.request_drain("geant4", "operator", 12)
        state, selected = self.pool.reconcile(self.live, self.ready, 13)
        self.assertIsNone(selected)
        self.assertEqual(state["target"], "geant4")

    def test_mixed_live_identity_never_selects(self):
        state, selected = self.pool.reconcile(self.live + [{"requested_resources": {"schema": "other"}}], self.ready, 10)
        self.assertIsNone(selected)
        self.assertEqual(state["blocked_reason"], "pool_identity_unresolved")


class DependencyPoolTests(unittest.TestCase):
    def setUp(self):
        self.pool = PoolStateMachine({}, {"dependency_mode": True})
        self.tcad = {"id": "tcad-ready", "profile": "tcad"}
        self.first = self.transport("first")
        self.second = self.transport("second")
        self.extra = self.transport("extra", required=False)

    def transport(self, key, required=True):
        return {"id": key, "profile": "geant4", "required_transport": required}

    def live(self, profile, state="RUNNING"):
        return {"requested_resources": {"schema": profile}, "task_state": state}

    def reconcile(self, live, ready, now, done=()):
        return self.pool.reconcile(live, ready, now, transport_profile="geant4", terminal_ids=done)

    def test_unrequired_transport_does_not_trigger_automatic_switch(self):
        state, selected = self.reconcile([], [self.extra], 1)
        self.assertIsNone(selected)
        self.assertNotIn("transport_batch_ids", state)
        self.assertFalse(self.pool.allows("extra", "geant4"))
        self.assertEqual(self.reconcile([self.live("tcad")], [self.extra], 2)[1], "tcad")

    def test_frozen_batch_survives_restart_and_finishes_before_next_batch(self):
        state, selected = self.reconcile([self.live("tcad")], [self.first, self.second, self.tcad], 1)
        self.assertIsNone(selected)
        self.assertEqual(state["target"], "geant4")
        self.assertEqual(state["transport_batch_ids"], ["first", "second"])
        self.pool = PoolStateMachine(json.loads(json.dumps(state)), {"dependency_mode": True})
        new = self.transport("new")
        self.assertEqual(self.reconcile([], [new, self.second, self.first, self.tcad], 2)[1], "geant4")
        self.assertFalse(self.pool.allows("new", "geant4"))
        self.pool.submitted("geant4", 2)
        self.assertEqual(self.reconcile([self.live("geant4")], [new, self.second, self.tcad], 3,
                                        done=("first",))[1], "geant4")
        self.assertTrue(self.pool.allows("second", "geant4"))
        self.assertEqual(self.pool.state["transport_batch_ids"], ["first", "second"])
        state, selected = self.reconcile([], [new, self.tcad], 4, done=("first", "second"))
        self.assertEqual(selected, "tcad")
        self.assertNotIn("transport_batch_ids", state)

    def test_quarantine_keeps_current_profile_eligible_and_preserves_batch(self):
        self.reconcile([self.live("tcad")], [self.first, self.second, self.tcad], 1)
        state, selected = self.reconcile([self.live("tcad", "QUARANTINED")],
                                         [self.first, self.second, self.tcad], 2)
        self.assertEqual(selected, "tcad")
        self.assertEqual(state["blocked_reason"], "blocked_by_quarantined_slot")
        self.assertEqual(state["transport_batch_ids"], ["first", "second"])
        self.assertEqual(self.reconcile([], [self.first, self.second], 3)[1], "geant4")
        state, selected = self.reconcile([self.live("geant4", "QUARANTINED")],
                                         [self.second, self.extra, self.tcad], 4)
        self.assertEqual(selected, "geant4")
        self.assertTrue(self.pool.allows("second", "geant4"))
        self.assertFalse(self.pool.allows("extra", "geant4"))

    def test_temporarily_unready_member_leaves_tcad_eligible(self):
        self.reconcile([self.live("tcad")], [self.first, self.tcad], 1)
        state, selected = self.reconcile([], [self.tcad], 2)
        self.assertEqual(selected, "tcad")
        self.assertEqual(state["transport_batch_ids"], ["first"])
        self.assertEqual(state["blocked_reason"], "transport_batch_not_ready")
        self.assertEqual(self.reconcile([], [self.first, self.tcad], 3)[1], "geant4")

    def test_finished_batch_waits_for_other_transport_lease_to_release(self):
        self.reconcile([], [self.first], 1)
        for stamp in (2, 3):
            state, selected = self.reconcile([self.live("geant4")], [self.second, self.tcad], stamp,
                                             done=("first",))
            self.assertIsNone(selected)
            self.assertEqual(state["target"], "tcad")
            self.assertFalse(self.pool.allows("second", "geant4"))
        self.assertEqual(self.reconcile([], [self.second, self.tcad], 4, done=("first",))[1], "tcad")

    def test_partial_batch_keeps_transport_until_release_then_restores_tcad(self):
        self.reconcile([], [self.first, self.second, self.tcad], 1)
        self.pool.submitted("geant4", 1)
        new = self.transport("new")
        ready = [self.tcad, new, self.extra]
        state, selected = self.reconcile([self.live("geant4", "COLLECTING")], ready, 2)
        self.assertEqual(selected, "geant4")
        self.assertEqual(state["state"], "ACTIVE")
        self.assertFalse(self.pool.allows("second", "geant4"))
        self.assertFalse(self.pool.allows("new", "geant4"))
        self.assertFalse(self.pool.allows("extra", "geant4"))
        state, selected = self.reconcile([], ready, 3, done=("first",))
        self.assertEqual(selected, "tcad")
        self.assertEqual(state["transport_batch_ids"], ["first", "second"])
        self.assertEqual(self.reconcile([], [self.second, *ready], 4, done=("first",))[1], "geant4")
        self.assertTrue(self.pool.allows("second", "geant4"))

    def test_manual_selection_can_admit_unmarked_transport(self):
        self.pool.request_drain("geant4", "operator", 1)
        self.assertEqual(self.reconcile([], [self.extra, self.tcad], 2)[1], "geant4")
        self.assertTrue(self.pool.allows("extra", "geant4"))
