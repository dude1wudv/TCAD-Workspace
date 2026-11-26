import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from campaign_fsm import (
    BLOCK_TOTALS,
    CAMPAIGN_STATES,
    advance_phase,
    apply_progress,
    ensure_campaign_files,
    holdout_read_allowed,
    mark_task,
    public_campaign_with_metrics,
    ready_tasks,
    register_blocked,
)
from codex_supervisor import actionable, record_wakeup
from config import Config
from runtime import load_state
from schemas import DirectorState, write_json
from status_publisher import observe_campaign
from watchdog import _check_campaign_dispatch, _execute_decision, _pump_queued_orders, _reject_campaign_task, tick


NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


class CampaignFsmTests(unittest.TestCase):
    def test_dry_run_preserves_existing_files_and_does_not_initialize_missing_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            cfg = Config(state_dir=state_dir, public_status_url="")
            with patch("watchdog.probe_server", return_value={}), patch("watchdog.probe_thesis", return_value={}):
                self.assertTrue(tick(cfg, dry_run=True, now=NOW)["dry_run"])
                self.assertFalse(state_dir.exists())
                state, _ = ensure_campaign_files(state_dir)
                state["wakeups_without_progress"] = 1
                write_json(state_dir / "campaign_state.json", state)
                (state_dir / "campaign_backlog.json").unlink()
                before = (state_dir / "campaign_state.json").read_bytes()
                self.assertTrue(tick(cfg, dry_run=True, now=NOW)["dry_run"])
                self.assertEqual({path.name for path in state_dir.iterdir()}, {"campaign_state.json"})
                self.assertEqual((state_dir / "campaign_state.json").read_bytes(), before)

    def test_observation_counts_only_new_archive_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            cfg = Config(state_dir=state_dir)
            campaign, _ = ensure_campaign_files(state_dir, create=False)
            archive_path = state_dir / "archive-summary.json"
            server = {"server_free_bytes": 0, "summary": {"running": 16, "r06_released_runs": 256}}
            self.assertFalse(observe_campaign(cfg, campaign, server, NOW))
            self.assertEqual(list(state_dir.iterdir()), [])
            self.assertEqual(public_campaign_with_metrics(campaign)["disks"]["server_free_bytes"], 0)
            self.assertTrue(all(block["accepted"] is None for block in campaign["blocks"].values()))
            self.assertFalse(holdout_read_allowed(campaign))
            archive = {"schema": "tcad-result-archive-summary-v1", "mirrored": 2, "cloud_verified": 1}
            write_json(archive_path, archive)
            before = archive_path.read_bytes()
            self.assertTrue(observe_campaign(cfg, campaign, server, NOW))
            self.assertEqual(campaign["last_progress_at"], NOW.isoformat())
            self.assertFalse(observe_campaign(cfg, campaign, server, NOW))
            self.assertEqual(archive_path.read_bytes(), before)
            write_json(archive_path, archive | {"mirrored": 1, "cloud_verified": 0})
            self.assertFalse(observe_campaign(cfg, campaign, server, NOW))
            self.assertEqual(campaign["archive"], {"mirrored": 2, "cloud_verified": 1})
            self.assertEqual(list(state_dir.iterdir()), [archive_path])

    def test_dispatch_uses_campaign_identity_clock_and_distinct_retry_order(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(state_dir=Path(directory), campaign_execution_enabled=True)
            campaign, backlog = ensure_campaign_files(cfg.state_dir)
            task = backlog["tasks"][0]
            state = DirectorState()
            decision = {"action": "dispatch", "task": task["task"], "phase": campaign["phase"], "reason": "ready",
                        "next_check_seconds": 600, "blocked_reason": None}

            def queue_order(config, director, order, *, campaign_task, now):
                self.assertIs(config, cfg)
                self.assertEqual(now, NOW)
                self.assertEqual(order.created_at, NOW.isoformat())
                director.active_order = {"order": order.to_dict(), "status": "queued", "campaign_task": campaign_task}

            with patch("director_ctl.dispatch", side_effect=queue_order):
                self.assertFalse(_execute_decision(cfg, state, campaign, backlog, decision, None, NOW))
                first_order = state.active_order["order"]["order_id"]
                self.assertEqual(task["status"], "running")
                self.assertEqual(state.active_order["campaign_task"], task["task"])
                mark_task(backlog, task["task"], "pending", error="check failed")
                state.active_order["status"] = "cancelled"
                _execute_decision(cfg, state, campaign, backlog, decision, None, NOW)
            self.assertNotEqual(state.active_order["order"]["order_id"], first_order)
            self.assertEqual(task["attempts"], 2)

    def test_failed_deliveries_block_on_the_third_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(state_dir=Path(directory))
            campaign, backlog = ensure_campaign_files(cfg.state_dir, create=False)
            task = backlog["tasks"][0]
            state = DirectorState()
            with patch("director_ctl.cancel") as cancel:
                for attempt in range(1, 4):
                    mark_task(backlog, task["task"], "running")
                    state.active_order = {
                        "status": "awaiting_review", "campaign_task": task["task"],
                        "order": {"order_id": f"order-{attempt}"},
                    }
                    _reject_campaign_task(cfg, state, campaign, backlog, "failed checks")
                    self.assertEqual(task["status"], "pending" if attempt < 3 else "blocked")
                self.assertEqual(cancel.call_count, 3)
            self.assertEqual(campaign["blocked"][0]["failures"], 3)
            self.assertNotIn(task, ready_tasks(backlog, campaign["phase"]))

    def test_campaign_dispatch_saves_budget_before_queued_worker_and_respects_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(state_dir=Path(directory), campaign_execution_enabled=True)
            campaign, backlog = ensure_campaign_files(cfg.state_dir)
            task = backlog["tasks"][0]
            day = cfg.local_time(NOW).date().isoformat()
            routine_cap = cfg.codex_daily_cap - cfg.codex_reserved_urgent
            state = DirectorState(daily_date=day, daily_codex_used=routine_cap)
            decision = {"action": "dispatch", "task": task["task"], "phase": campaign["phase"], "reason": "ready",
                        "next_check_seconds": 600, "blocked_reason": None}

            def check_budget(config, order, **kwargs):
                saved = load_state(config)
                self.assertEqual(saved.daily_codex_used, routine_cap)
                self.assertEqual(saved.active_order["campaign_task"], task["task"])
                self.assertEqual(saved.active_order["order"], order.to_dict())
                return {"pid": 1234}

            with (
                patch("director_ctl._watchdog_daemon_running", return_value=True),
                patch("director_ctl.launch_worker") as direct_launch,
                patch("watchdog.launch_worker", side_effect=check_budget) as queued_launch,
                patch("watchdog.refresh_status"),
            ):
                with self.assertRaisesRegex(ValueError, "daily Codex cap"):
                    _execute_decision(cfg, state, campaign, backlog, decision, None, NOW)
                self.assertEqual(task["status"], "pending")
                state.daily_codex_used -= 1
                _execute_decision(cfg, state, campaign, backlog, decision, None, NOW)
                self.assertTrue(_pump_queued_orders(cfg))
                direct_launch.assert_not_called()
                queued_launch.assert_called_once()
            self.assertEqual(load_state(cfg).active_order["status"], "running")
            self.assertEqual(load_state(cfg).daily_codex_used, routine_cap)

    def test_urgent_campaign_dispatch_passes_reserved_budget_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(state_dir=Path(directory), campaign_execution_enabled=True)
            campaign, backlog = ensure_campaign_files(cfg.state_dir)
            task = backlog["tasks"][0]
            state = DirectorState(
                daily_date=cfg.local_time(NOW).date().isoformat(),
                daily_codex_used=cfg.codex_daily_cap - cfg.codex_reserved_urgent,
            )
            decision = {
                "action": "dispatch",
                "task": task["task"],
                "phase": campaign["phase"],
                "reason": "urgent",
                "next_check_seconds": 600,
                "blocked_reason": None,
            }

            def queue_order(config, director, order, *, campaign_task, now, urgent):
                self.assertIs(config, cfg)
                self.assertEqual(campaign_task, task["task"])
                self.assertEqual(now, NOW)
                self.assertTrue(urgent)
                director.active_order = {
                    "order": order.to_dict(),
                    "status": "queued",
                    "campaign_task": campaign_task,
                }

            with patch("director_ctl.dispatch", side_effect=queue_order):
                _execute_decision(cfg, state, campaign, backlog, decision, None, NOW, urgent=True)

            self.assertEqual(state.active_order["campaign_task"], task["task"])
            self.assertEqual(state.daily_codex_used, cfg.codex_daily_cap - cfg.codex_reserved_urgent)

    def test_no_progress_cooldown_suppresses_scheduled_pulse(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Config(state_dir=Path(directory), campaign_execution_enabled=True)
            campaign, backlog = ensure_campaign_files(cfg.state_dir, create=False)
            for _ in range(2):
                record_wakeup(cfg, campaign, "noop", None, "no progress", changed=False, now=NOW)
            self.assertEqual(
                actionable(cfg, campaign, backlog, {"online": True}, {}, now=NOW, scheduled_pulse=True),
                (False, "cooldown"),
            )

    def test_initial_state_is_sealed_and_does_not_claim_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backlog = ensure_campaign_files(Path(directory))
            self.assertEqual(state["phase"], CAMPAIGN_STATES[0])
            self.assertFalse(holdout_read_allowed(state))
            self.assertEqual(len(backlog["tasks"]), 15)
            self.assertTrue(all(state["blocks"][key]["accepted"] is None for key in BLOCK_TOTALS))
            self.assertIsNone(public_campaign_with_metrics(state)["codex"]["used"])

    def test_gates_require_verified_counts_and_explicit_milestones(self):
        with tempfile.TemporaryDirectory() as directory:
            state, _ = ensure_campaign_files(Path(directory))
            apply_progress(
                state,
                {
                    "blocks": {"Z": 26, "T": 68, "S": 150, "R": 12},
                    "milestones": {"bootstrap_ready": True},
                },
            )
            self.assertTrue(state["gates"]["G1"])
            self.assertEqual(advance_phase(state), "P1A_SIM_DEV")
            state["phase"] = "P1A_SIM_DEV"
            self.assertEqual(advance_phase(state), "P2A_DEV_TRAIN_AL1")

    def test_holdout_unlock_requires_freeze_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            state, _ = ensure_campaign_files(Path(directory))
            self.assertFalse(holdout_read_allowed(state))
            state["phase"] = "P2D_HOLDOUT_BLIND_EVAL"
            apply_progress(state, {"milestones": {"blind_eval_complete": True, "desk_verified": True},
                                   "blind_eval_count": 1})
            self.assertFalse(state["gates"]["G4"])
            self.assertIsNone(advance_phase(state))
            with self.assertRaises(PermissionError):
                _check_campaign_dispatch(state, "holdout-blind-eval")
            apply_progress(
                state,
                {
                    "freeze_manifest": {
                        "sha256": "a" * 64,
                        "model_id": "r06-dev-final",
                    },
                    "training": "ready",
                },
            )
            self.assertTrue(holdout_read_allowed(state))
            self.assertTrue(state["gates"]["G3"])
            with self.assertRaises(ValueError):
                _check_campaign_dispatch(state, "holdout-blind-eval")
            self.assertEqual(advance_phase(state), "P3_DESK_PROD_DEPLOY")

    def test_failed_task_is_visible_as_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backlog = ensure_campaign_files(Path(directory))
            task = backlog["tasks"][0]
            task["failures"] = 3
            register_blocked(state, task["task"], "checks_failed", "three failed checks", 3)
            self.assertEqual(state["blocked"][0]["task"], task["task"])
            self.assertEqual(state["blocked"][0]["reason"], "checks_failed")

    def test_ready_tasks_honor_phase_and_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backlog = ensure_campaign_files(Path(directory))
            ready = {task["task"] for task in ready_tasks(backlog, state["phase"])}
            self.assertEqual(ready, {"campaign-fsm-supervisor", "local-archive-sync"})


if __name__ == "__main__":
    unittest.main()
