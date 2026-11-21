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
