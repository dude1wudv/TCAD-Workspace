"""Offline tests for the local director and its worker handoffs."""

import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from config import Config, NotifyConfig, can_consume_wakeup, load_config
from runtime import LockBusy, file_lock, load_state, save_state
from schemas import DecisionEntry, DeliveryReceipt, DirectorState, QueueItem, WorkOrder, read_json, utc_now, write_json


NOW = datetime(2026, 11, 24, 4, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()
LOCAL_POPEN = subprocess.Popen


def work_order(**overrides):
    return WorkOrder.from_dict({
        "order_id": "test-order",
        "category": "thesis_assets",
        "title": "Update figure index",
        "objective": "Record the available figure evidence",
        "allowed_paths": ["thesis/**"],
        "forbidden_actions": ["Modify the archived results"],
        "acceptance_checks": ["python -B -m unittest test_figures"],
        "priority": 2,
        "created_by_turn": "test-turn",
        "created_at": NOW.isoformat(),
        **overrides,
    })


def delivery_receipt(order, **overrides):
    return DeliveryReceipt.from_dict({
        "order_id": order.order_id,
        "codex_session_id": "test-session",
        "attempt": 1,
        "status": "passed",
        "exit_code": 0,
        "duration_seconds": 3.5,
        "git_changed_files": ["thesis/index.md"],
        "git_diff_stat": "1 file changed",
        "verification_results": [{"command": order.acceptance_checks[0], "exit_code": 0}],
        "artifacts_produced": ["thesis/index.md"],
        "codex_final_summary": "Updated the figure index",
        "precheck_passed": True,
        "precheck_errors": [],
        "generated_at": NOW.isoformat(),
        **overrides,
    })


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=BASE_DIR)))
        self.cfg = Config(repo_root=self.root, state_dir=self.root / "state", public_status_url="")
        self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("unexpected DNS lookup")))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("unexpected connection")))
        self.enterContext(patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected subprocess")))


class SchemaTests(OfflineCase):
    def test_serialization_round_trips_through_json_files(self):
        order = work_order(title="更新图表索引")
        receipt = delivery_receipt(order)
        state = DirectorState(daily_date=TODAY, active_order={"order": order.to_dict()})
        decision = DecisionEntry(decision_type="strategy", title="调查顺序", body="先核对原始记录")
        queued = QueueItem(order=order.to_dict())
        for record in (order, receipt, state, decision, queued):
            with self.subTest(record=type(record).__name__):
                path = self.root / f"{type(record).__name__}.json"
                write_json(path, record.to_dict())
                self.assertEqual(type(record).from_dict(read_json(path)), record)
        self.assertEqual(order.timeout_seconds, 2100)
        self.assertEqual(order.max_rejections, 3)
        self.assertEqual(datetime.fromisoformat(utc_now()).utcoffset(), timedelta(0))

    def test_work_order_rejects_bad_fields_and_paths(self):
        order_data = work_order().to_dict()
        for updates in (
            {"order_id": "../escape"},
            {"order_id": "NUL"},
            {"category": "unknown"},
            {"title": " "},
            {"allowed_paths": ["../outside"]},
            {"allowed_paths": ["/absolute"]},
            {"allowed_paths": ["C:\\outside"]},
            {"allowed_paths": ["thesis/../outside"]},
            {"acceptance_checks": [""]},
            {"timeout_seconds": 0},
            {"timeout_seconds": 3601},
            {"max_rejections": 0},
            {"priority": True},
            {"priority": 6},
            {"created_at": "2026-11-24T04:00:00"},
            {"extra": "unknown"},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                WorkOrder.from_dict(order_data | updates)
        del order_data["objective"]
        with self.assertRaises(ValueError):
            WorkOrder.from_dict(order_data)

    def test_receipt_and_state_reject_inconsistent_values(self):
        order = work_order()
        for updates in (
            {"attempt": 0},
            {"status": "accepted"},
            {"status": "failed", "precheck_passed": True},
            {"precheck_errors": ["scope error"]},
            {"duration_seconds": -1},
            {"duration_seconds": float("inf")},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                delivery_receipt(order, **updates)
        for updates in (
            {"daily_wakeups_used": -1},
            {"daily_codex_used": True},
            {"daily_date": "11/24/2026"},
            {"last_periodic_at": "2026-11-24T04:00:00"},
            {"pending_events": ["not an event object"]},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                DirectorState.from_dict(updates)

    def test_json_reader_rejects_duplicate_keys_and_nonfinite_numbers(self):
        path = self.root / "malformed.json"
        for text in ('{"value": 1, "value": 2}', '{"value": NaN}', '{"value": Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                path.write_text(text, encoding="utf-8")
                read_json(path)


class ConfigTests(OfflineCase):
    def test_default_wakeup_reservations(self):
        for bucket, limit in (("routine", 18), ("urgent", 22), ("daily", 24)):
            with self.subTest(bucket=bucket):
                state = DirectorState(daily_date=TODAY, daily_wakeups_used=limit - 1)
                self.assertTrue(can_consume_wakeup(state, bucket, TODAY))
                self.assertEqual(state.daily_wakeups_used, limit - 1)
                state.daily_wakeups_used += 1
                self.assertFalse(can_consume_wakeup(state, bucket, TODAY))
        with self.assertRaises(ValueError):
            can_consume_wakeup(state, "unknown", TODAY)

    def test_custom_reservations_and_day_reset_preserve_urgent_events(self):
        cfg = replace(self.cfg, gemini_daily_cap=5, gemini_reserved_urgent=2, gemini_reserved_daily=1)
        urgent = {"reason": "CODEX_DELIVERED", "bucket": "urgent"}
        state = DirectorState(
            daily_date=TODAY,
            daily_wakeups_used=5,
            daily_codex_used=3,
            daily_executed=["DAILY_THESIS_SPRINT"],
            pending_events=[urgent, {"reason": "DAILY_DIGEST", "bucket": "daily"}],
        )
        next_day = NOW.date() + timedelta(days=1)
        self.assertTrue(can_consume_wakeup(state, "routine", next_day, cfg))
        self.assertEqual(state.daily_date, next_day.isoformat())
        self.assertEqual(state.daily_wakeups_used, 0)
        self.assertEqual(state.daily_codex_used, 0)
        self.assertEqual(state.daily_executed, [])
        self.assertEqual(state.pending_events, [urgent])
        state.daily_wakeups_used = 2
        self.assertFalse(cfg.can_consume_wakeup(state, "routine", next_day))
        self.assertTrue(cfg.can_consume_wakeup(state, "urgent", next_day))

    def test_config_load_resolves_paths_and_rejects_invalid_settings(self):
        path = self.root / "config.json"
        options = {
            "repo_root": "repo",
            "state_dir": "runtime",
            "remote_controller_cmd": ["python", "controller.py"],
            "notify": {"smtp_env_file": "smtp.env", "enabled": False},
        }
        write_json(path, options)
        cfg = load_config(path)
        self.assertEqual(cfg.repo_root, self.root / "repo")
        self.assertEqual(cfg.state_dir, cfg.repo_root / "runtime")
        self.assertEqual(cfg.remote_controller_cmd, ("python", "controller.py"))
        self.assertEqual(cfg.notify.smtp_env_file, self.root / "smtp.env")
        self.assertFalse(cfg.notify.enabled)
        self.assertEqual(cfg.local_time(NOW).hour, 12)
        for updates in (
            {"gemini_daily_cap": 5},
            {"heartbeat_interval_seconds": True},
            {"codex_default_timeout_seconds": 3601},
            {"daily_digest_hour": 24},
            {"branch_name": "main"},
            {"public_status_url": "http://example.invalid/status"},
            {"notify": {"enabled": "false"}},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                write_json(path, options | updates)
                load_config(path)


class RuntimeTests(OfflineCase):
    def test_nonblocking_watchdog_lock_rejects_second_holder_and_releases(self):
        path = self.cfg.state_dir / "watchdog.lock"
        with file_lock(path, blocking=False):
            with self.assertRaises(LockBusy), file_lock(path, blocking=False):
                self.fail("a second watchdog acquired the lock")
        with file_lock(path, blocking=False):
            self.assertTrue(path.is_file())

    def test_failed_atomic_replace_preserves_state_and_cleans_staging(self):
        state = DirectorState(daily_date=TODAY, daily_wakeups_used=3)
        save_state(self.cfg, state)
        path = self.cfg.state_dir / "state.json"
        before = path.read_bytes()
        with patch("schemas.os.replace", side_effect=PermissionError("fixture failure")):
            with self.assertRaises(PermissionError):
                save_state(self.cfg, replace(state, daily_wakeups_used=4))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.cfg.state_dir.iterdir()), [path])


class ControlTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.config_path = self.root / "config.json"
        write_json(self.config_path, {
            "repo_root": str(self.root), "state_dir": "state", "public_status_url": "",
        })
        self.order = work_order()
        self.order_path = self.root / "order.json"
        write_json(self.order_path, self.order.to_dict())
        self.receipt_path = self.cfg.state_dir / "orders" / self.order.order_id / "receipt.json"

    def cli(self, *args, code=0, config_last=False):
        from director_ctl import main

        options = ("--config", str(self.config_path))
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(list(args + options if config_last else options + args))
        self.assertEqual(result, code, output.getvalue())
        return json.loads(output.getvalue())

    def review(self, receipt):
        state = load_state(self.cfg)
        state.active_order = {
            "order": self.order.to_dict(), "attempt": receipt.attempt,
            "status": "awaiting_review", "rejections": receipt.attempt - 1,
            "run_meta": {"pid": 1234},
        }
        state.pending_events = [{"reason": "CODEX_DELIVERED", "bucket": "urgent"}]
        write_json(self.receipt_path, receipt.to_dict())
        save_state(self.cfg, state)

    def test_dispatch_persists_order_and_rejects_a_second_active_order(self):
        with patch("director_ctl.launch_worker", return_value={"pid": 1234}) as launch:
            reply = self.cli("dispatch", "--file", str(self.order_path), config_last=True)
            self.assertEqual(reply, {"order_id": self.order.order_id, "pid": 1234, "status": "running"})
            another = self.root / "another.json"
            write_json(another, work_order(order_id="other-order").to_dict())
            self.cli("dispatch", "--file", str(another), code=1)
            launch.assert_called_once_with(self.cfg, self.order, attempt=1)
        state = load_state(self.cfg)
        self.assertEqual(state.daily_codex_used, 1)
        self.assertEqual(state.active_order["order"], self.order.to_dict())
        self.assertEqual(self.cli("status")["active_order"]["attempt"], 1)

    def test_dispatch_failure_does_not_spend_slot_or_mark_order_running(self):
        with patch("director_ctl.launch_worker", side_effect=OSError("worker unavailable")):
            self.cli("dispatch", "--file", str(self.order_path), code=1)
        state = load_state(self.cfg)
        self.assertIsNone(state.active_order)
        self.assertEqual(state.daily_codex_used, 0)

    def test_accept_checks_receipt_attempt_and_precheck(self):
        receipt = delivery_receipt(self.order, status="failed", precheck_passed=False, precheck_errors=["check failed"])
        self.review(receipt)
        args = ("accept", "--order", self.order.order_id, "--note", "Reviewed the evidence")
        self.cli(*args, code=1)
        write_json(self.receipt_path, delivery_receipt(self.order, attempt=2).to_dict())
        self.cli(*args, "--force", code=1)
        self.assertEqual(load_state(self.cfg).active_order["status"], "awaiting_review")
        write_json(self.receipt_path, delivery_receipt(self.order).to_dict())
        self.assertEqual(self.cli(*args)["status"], "accepted")
        state = load_state(self.cfg)
        self.assertEqual(state.active_order["status"], "accepted")
        self.assertEqual(state.pending_events, [])

    def test_reject_resumes_same_session_and_third_rejection_breaks_circuit(self):
        args = ("reject", "--order", self.order.order_id, "--feedback", "Attach command evidence")
        with (
            patch("director_ctl.launch_worker", return_value={"pid": 1234}) as launch,
            patch("director_ctl.notify", return_value={"status": "drafted"}) as notify,
        ):
            for attempt in (1, 2):
                receipt = delivery_receipt(self.order, attempt=attempt)
                self.review(receipt)
                self.assertEqual(self.cli(*args)["attempt"], attempt + 1)
                launch.assert_called_with(self.cfg, self.order, attempt=attempt + 1,
                                          previous_receipt=receipt, feedback="Attach command evidence")
                self.assertEqual(load_state(self.cfg).active_order["rejections"], attempt)
            self.review(delivery_receipt(self.order, attempt=3))
            reply = self.cli(*args)
            self.assertEqual(reply["status"], "circuit_broken")
            self.assertEqual(reply["rejections"], 3)
            self.assertEqual(launch.call_count, 2)
            notify.assert_called_once()
        state = load_state(self.cfg)
        self.assertEqual(state.active_order["status"], "circuit_broken")
        self.assertEqual(state.pending_events[0]["reason"], "CODEX_CIRCUIT_BROKEN")

    def test_cancel_review_and_finish_turn_release_pending_state(self):
        self.review(delivery_receipt(self.order))
        state = load_state(self.cfg)
        state.active_turn = {"reason": "PERIODIC_REVIEW"}
        save_state(self.cfg, state)
        with patch("director_ctl.terminate_worker") as terminate:
            result = self.cli("cancel", "--order", self.order.order_id, "--reason", "Superseded by scoped follow-up")
            self.assertEqual(result["status"], "cancelled")
            terminate.assert_not_called()
        with patch("director_ctl.refresh_status") as refresh:
            self.assertEqual(self.cli("finish-turn", "--summary", "Plan recorded", "--next-wake-hint", "90")["status"], "finished")
            refresh.assert_called_once()
            self.assertFalse(refresh.call_args.kwargs["publish"])
        state = load_state(self.cfg)
        self.assertEqual(state.active_order["status"], "cancelled")
        self.assertEqual(state.pending_events, [])
        self.assertIsNone(state.active_turn)
        self.assertEqual(state.last_decision, "Plan recorded")
        self.assertTrue(state.next_wake_at)

    def test_queue_priority_duplicate_and_pop(self):
        high = work_order(order_id="high-priority", priority=5)
        high_path = self.root / "high.json"
        write_json(high_path, high.to_dict())
        self.cli("queue-add", "--file", str(self.order_path))
        self.cli("queue-add", "--file", str(high_path))
        self.cli("queue-add", "--file", str(high_path), code=1)
        self.assertEqual([item["order"]["order_id"] for item in self.cli("queue-list")],
                         [high.order_id, self.order.order_id])
        self.assertEqual(self.cli("queue-pop")["order"], high.to_dict())
        self.assertEqual(self.cli("queue-pop")["order"], self.order.to_dict())
        self.assertIsNone(self.cli("queue-pop"))

    def test_log_decision_appends_sanitized_amendment_and_notifies(self):
        log = self.root / "fixture-decisions.md"
        log.write_text("# Existing evidence\n\nOriginal criterion.\n", encoding="utf-8")
        original = log.read_bytes()
        body = self.root / "decision.md"
        body.write_text("Update the criterion using paired observations.\nTOKEN=fixture-secret\n", encoding="utf-8")
        with (
            patch("director_ctl.DECISION_LOG", Path(log.name)),
            patch("director_ctl.notify", return_value={"status": "drafted"}) as notify,
        ):
            result = self.cli("log-decision", "--type", "criterion_amendment", "--title", "Refine criterion",
                              "--body-file", str(body), "--cases", "fixture-a, fixture-b")
        self.assertEqual(result["status"], "logged")
        self.assertTrue(log.read_bytes().startswith(original))
        decision = json.loads((self.cfg.state_dir / "decisions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(decision["cases"], ["fixture-a", "fixture-b"])
        self.assertEqual(load_state(self.cfg).last_decision, "Refine criterion")
        self.assertNotIn("fixture-secret", log.read_text(encoding="utf-8"))
        self.assertNotIn("fixture-secret", decision["body"])
        notify.assert_called_once_with(self.cfg, "alert", "判据修订：Refine criterion", decision["body"])


class NotificationTests(OfflineCase):
    def test_digest_archives_and_failed_smtp_falls_back_to_local_draft(self):
        from notifier import notify

        options = self.root / "smtp.env"
        options.write_text("SMTP_HOST=example.invalid\nSMTP_FROM=sender@example.invalid\n", encoding="utf-8")
        cfg = replace(self.cfg, notify=NotifyConfig(recipient="reader@example.invalid", smtp_env_file=options))
        with patch("notifier._send_smtp", side_effect=OSError("offline fixture")) as smtp:
            result = notify(cfg, "digest", "Daily progress", "Two figure entries updated.")
        smtp.assert_called_once()
        self.assertEqual(result["status"], "drafted")
        self.assertEqual(result["mode"], "draft_fallback")
        self.assertEqual(result["warning"], "smtp_OSError")
        self.assertIn("Two figure entries updated.", Path(result["archive_path"]).read_text(encoding="utf-8"))
        self.assertIn("To: reader@example.invalid", Path(result["draft_path"]).read_text(encoding="utf-8"))

    def test_sensitive_digest_blocks_delivery_and_redacts_archive(self):
        from notifier import notify

        cfg = replace(self.cfg, notify=NotifyConfig(recipient="reader@example.invalid"))
        with patch("notifier._send_smtp") as smtp:
            result = notify(cfg, "digest", "Daily progress", "TOKEN=fixture-secret")
        smtp.assert_not_called()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("credential", result["reasons"])
        self.assertNotIn("fixture-secret", Path(result["archive_path"]).read_text(encoding="utf-8"))
        self.assertFalse((self.cfg.state_dir / "pending_drafts").exists())


class WatchdogTests(OfflineCase):
    def setUp(self):
        super().setUp()
        import watchdog

        self.watchdog = watchdog
        self.server = self.enterContext(patch.object(watchdog, "probe_server", return_value={"online": True}))
        self.enterContext(patch.object(watchdog, "probe_thesis", return_value={}))
        self.worker = self.enterContext(patch.object(watchdog, "probe_codex_worker", return_value={"status": "idle"}))
        self.conversation = self.enterContext(patch.object(watchdog, "new_conversation", return_value="mock-conversation"))
        self.refresh = self.enterContext(patch.object(watchdog, "refresh_status"))

    def tick(self, now=NOW, **kwargs):
        return self.watchdog.tick(self.cfg, now=now, **kwargs)

    def test_prompt_goal_mode_toggle(self):
        brief = self.root / "brief.md"
        goal = self.watchdog.build_prompt(self.cfg, brief)
        plain = self.watchdog.build_prompt(replace(self.cfg, use_goal_mode=False), brief)
        self.assertEqual(goal, "/goal " + plain)
        for token in (str(brief), "director-system.md", "finish-turn"):
            self.assertIn(token, plain)

    def test_dry_run_previews_urgent_wakeup_without_writes_or_launch(self):
        state = DirectorState(daily_date=TODAY, daily_wakeups_used=2)
        save_state(self.cfg, state)
        path = self.cfg.state_dir / "state.json"
        before = path.read_bytes()
        reply = self.tick(dry_run=True, force_trigger="MANUAL_TEST")
        self.assertTrue(reply["dry_run"])
        self.assertEqual(reply["reason"], "MANUAL_TEST")
        self.assertEqual(reply["bucket"], "urgent")
        self.assertIn("brief-preview.md", reply["prompt"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.cfg.state_dir.iterdir()), [path])
        self.conversation.assert_not_called()
        self.refresh.assert_not_called()

    def test_periodic_wakeup_honors_active_turn_and_interval(self):
        reply = self.tick()
        self.assertEqual(reply["reason"], "PERIODIC_REVIEW")
        self.assertEqual(reply["conversation_id"], "mock-conversation")
        brief = Path(reply["briefing"])
        self.assertTrue(brief.is_relative_to(self.cfg.state_dir))
        self.assertIn("PERIODIC_REVIEW", brief.read_text(encoding="utf-8"))
        self.conversation.assert_called_once_with(self.cfg, "PERIODIC_REVIEW", self.watchdog.build_prompt(self.cfg, brief))
        later = NOW + timedelta(seconds=1)
        self.assertIsNone(self.tick(later, force_trigger="MANUAL_TEST")["reason"])
        state = load_state(self.cfg)
        self.assertEqual(state.active_turn["conversation_id"], "mock-conversation")
        self.assertEqual(state.daily_wakeups_used, 1)
        self.assertEqual(state.pending_events[0]["reason"], "MANUAL_TEST")
        state.active_turn = None
        state.pending_events.clear()
        save_state(self.cfg, state)
        self.assertIsNone(self.tick(later)["reason"])
        self.assertEqual(self.tick(NOW + timedelta(seconds=self.cfg.periodic_review_seconds))["reason"], "PERIODIC_REVIEW")

    def test_daily_slots_fire_once_in_shanghai_and_preserve_the_reservations(self):
        save_state(self.cfg, DirectorState(daily_date=TODAY, daily_wakeups_used=22))
        thesis_due = NOW + timedelta(hours=10)
        self.assertIsNone(self.tick(thesis_due - timedelta(seconds=1))["reason"])
        for moment, reason in ((thesis_due, "DAILY_THESIS_SPRINT"), (thesis_due + timedelta(hours=1), "DAILY_DIGEST")):
            with self.subTest(reason=reason):
                self.assertEqual(self.tick(moment, force_trigger="MANUAL_TEST")["reason"], reason)
                state = load_state(self.cfg)
                self.assertIn(reason, state.daily_executed)
                state.active_turn = None
                save_state(self.cfg, state)
                self.assertIsNone(self.tick(moment + timedelta(seconds=1))["reason"])
        self.assertEqual(load_state(self.cfg).daily_wakeups_used, 24)
        self.assertEqual(self.conversation.call_count, 2)

    def test_failed_conversation_keeps_event_and_budget_until_retry_succeeds(self):
        self.conversation.side_effect = [RuntimeError("fixture unavailable"), "recovered-conversation"]
        reply = self.tick(force_trigger="MANUAL_TEST")
        self.assertIsNone(reply["conversation_id"])
        self.assertEqual(reply["daily_wakeups_used"], 0)
        state = load_state(self.cfg)
        self.assertEqual(state.wakeup_failures, 1)
        self.assertIsNone(state.active_turn)
        self.assertIn("MANUAL_TEST", [event["reason"] for event in state.pending_events])
        retry_at = datetime.fromisoformat(state.wakeup_backoff_until)
        self.assertGreater(retry_at, NOW)
        self.assertIsNone(self.tick(retry_at - timedelta(seconds=1))["reason"])
        self.conversation.assert_called_once()
        self.assertEqual(self.tick(retry_at)["conversation_id"], "recovered-conversation")
        state = load_state(self.cfg)
        self.assertEqual(state.daily_wakeups_used, 1)
        self.assertEqual(state.wakeup_failures, 0)
        self.assertEqual(state.wakeup_backoff_until, "")

    def test_server_outage_and_recovery_are_edge_triggered(self):
        save_state(self.cfg, DirectorState(daily_date=TODAY, last_periodic_at=NOW.isoformat()))
        self.server.return_value = {"online": False}
        self.assertEqual(self.tick()["reason"], "SERVER_UNREACHABLE")
        state = load_state(self.cfg)
        self.assertTrue(state.server_offline)
        state.active_turn = None
        save_state(self.cfg, state)
        self.assertIsNone(self.tick(NOW + timedelta(seconds=1))["reason"])
        self.server.return_value = {"online": True}
        self.assertEqual(self.tick(NOW + timedelta(seconds=2))["reason"], "SERVER_RECOVERED")
        self.assertFalse(load_state(self.cfg).server_offline)

    def test_expired_turn_releases_lock_and_wakes_director(self):
        active = {"conversation_id": "stale-conversation", "reason": "PERIODIC_REVIEW", "started_at": NOW.isoformat()}
        save_state(self.cfg, DirectorState(daily_date=TODAY, active_turn=active))
        deadline = NOW + timedelta(seconds=self.cfg.director_turn_timeout_seconds)
        self.assertIsNone(self.tick(deadline - timedelta(seconds=1))["reason"])
        self.assertEqual(self.tick(deadline)["reason"], "DIRECTOR_TURN_EXPIRED")
        history = json.loads((self.cfg.state_dir / "turns.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(history["status"], "expired")
        self.assertEqual(history["conversation_id"], "stale-conversation")

    def test_worker_status_drives_urgent_review_events(self):
        order = work_order()
        meta = {"pid": 1234, "order_id": order.order_id, "attempt": 1}
        for status, precheck, reason in (
            ("exited", True, "CODEX_DELIVERED"),
            ("exited", False, "CODEX_FAILED_OR_TIMEOUT"),
            ("timeout", False, "CODEX_FAILED_OR_TIMEOUT"),
            ("stalled", False, "CODEX_STALLED"),
        ):
            with self.subTest(status=status, precheck=precheck):
                active = {"order": order.to_dict(), "status": "running", "attempt": 1, "rejections": 0, "run_meta": meta}
                save_state(self.cfg, DirectorState(daily_date=TODAY, active_order=active))
                self.worker.return_value = {"status": status}
                receipt = delivery_receipt(order, status="passed" if precheck else "failed", precheck_passed=precheck)
                with (
                    patch.object(self.watchdog, "finalize_and_precheck", return_value=receipt) as finalize,
                    patch.object(self.watchdog, "terminate_worker", return_value=True) as terminate,
                ):
                    reply = self.tick()
                    self.assertEqual(reply["reason"], reason)
                    self.assertEqual(reply["bucket"], "urgent")
                    if status == "timeout":
                        terminate.assert_called_once_with(meta, "timeout")
                    else:
                        terminate.assert_not_called()
                    if status == "stalled":
                        finalize.assert_not_called()
                    else:
                        expected = meta | ({"status_override": "timeout"} if status == "timeout" else {})
                        finalize.assert_called_once_with(self.cfg, order, expected)
                expected_status = "stalled" if status == "stalled" else "awaiting_review"
                self.assertEqual(load_state(self.cfg).active_order["status"], expected_status)

    def test_cli_refuses_second_watchdog_instance(self):
        with (
            patch.object(self.watchdog, "load_config", return_value=self.cfg),
            patch.object(self.watchdog, "tick") as tick,
            file_lock(self.cfg.state_dir / "watchdog.lock", blocking=False),
            redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(self.watchdog.main(["--tick"]), 1)
        tick.assert_not_called()
        self.assertIn("error", json.loads(stdout.getvalue()))


class ProbeTests(OfflineCase):
    def test_server_uses_public_fallback_after_failed_ssh(self):
        from probes import probe_server

        cfg = replace(self.cfg, server_ssh_target="fixture", public_status_url="https://example.invalid/status")
        payload = {"simulation": {"phase": "collecting"}, "services": [{"id": "tcad-controller", "state": "operational"}]}
        response = io.BytesIO(json.dumps(payload).encode())
        with (
            patch("probes.subprocess.run", return_value=subprocess.CompletedProcess(["ssh"], 255)) as ssh,
            patch("probes.request.urlopen", return_value=response) as public,
        ):
            result = probe_server(cfg)
        self.assertTrue(result["online"])
        self.assertEqual(result["source"], "public")
        self.assertEqual(result["observation"], payload["simulation"])
        self.assertTrue(result["service_active"])
        self.assertTrue(result["errors"])
        ssh.assert_called_once()
        public.assert_called_once_with(cfg.public_status_url, timeout=10)

    def test_fingerprint_ignores_timestamps_progress_and_list_order(self):
        from probes import compute_state_fingerprint

        server = {
            "online": True, "observation": {"stage": "collecting", "updated_at": NOW.isoformat(), "progress": 10},
        }
        thesis = {"chapters": [{"id": "intro", "status": "DRAFT"}, {"id": "methods", "status": "REVISED"}]}
        noisy = server | {"observation": server["observation"] | {"updated_at": "later", "progress": 80}}
        reordered = {"chapters": thesis["chapters"][::-1]}
        fingerprint = compute_state_fingerprint(server, thesis)
        self.assertEqual(fingerprint, compute_state_fingerprint(noisy, reordered))
        self.assertNotEqual(fingerprint, compute_state_fingerprint(server | {"online": False}, thesis))
        self.assertNotEqual(fingerprint, compute_state_fingerprint(server, {"chapters": []}))

    def test_thesis_probe_reads_fixture_blueprint_and_unique_assets(self):
        from probes import probe_thesis

        thesis = self.root / "论文草稿"
        write_json(thesis / "thesis-blueprint.json", {
            "stage": "draft", "chapters": [{"id": "first", "status": "REVISED"}, {"id": "second", "status": "DRAFT"}],
            "last_sprint_utc": NOW.isoformat(), "last_build_ok": False,
        })
        registry = thesis / "materials" / "asset-registry.jsonl"
        registry.parent.mkdir()
        registry.write_text('{"asset_id":"figure-a"}\ninvalid\n{"asset_id":"figure-a"}\n', encoding="utf-8")
        result = probe_thesis(self.cfg)
        self.assertEqual(result["chapters_done"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["assets_count"], 1)
        self.assertEqual(result["last_sprint_utc"], NOW.isoformat())
        self.assertIs(result["build_ok"], False)
        self.assertEqual(result["errors"], ["asset registry: invalid line 2"])


class WorkerTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.order = work_order()
        self.folder = self.cfg.state_dir / "orders" / self.order.order_id
        self.file = "thesis/index.md"
        artifact = self.root / self.file
        artifact.parent.mkdir()
        artifact.write_text("Figure index\n", encoding="utf-8")
        self.enterContext(patch("codex_runner._head", return_value="fixture-head"))
        self.snapshot = self.enterContext(patch("codex_runner._snapshot", return_value={}))
        self.enterContext(patch("codex_runner._codex_executable", return_value=["codex-fixture"]))

    def launch(self, **kwargs):
        from codex_runner import launch_worker

        with patch("codex_runner.subprocess.Popen", return_value=Mock(pid=1234)) as popen:
            meta = launch_worker(self.cfg, self.order, **kwargs)
        popen.assert_called_once()
        self.assertEqual(Path(popen.call_args.kwargs["cwd"]), self.root)
        return meta

    def complete(self, meta, *, command_exit=0, changed=None):
        command = self.order.acceptance_checks[0]
        changed = [self.file] if changed is None else changed
        self.snapshot.return_value = {path: ["??", [], ["fixture-content"]] for path in changed}
        write_json(Path(meta["exit_path"]), {
            "order_id": self.order.order_id, "attempt": meta["attempt"], "pid": meta["pid"], "exit_code": 0,
        })
        write_json(Path(meta["last_msg_path"]), {
            "order_id": self.order.order_id, "outcome": "completed", "summary": "Updated figure evidence",
            "changed_files": changed, "artifacts_produced": [self.file], "blockers": [], "next_recommendation": "",
            "commands_run": [{"command": command, "exit_code": 0, "summary": "Checks passed"}],
        })
        events = [{"type": "thread.started", "thread_id": "fixture-session"}]
        if command_exit is not None:
            events.append({"type": "item.completed", "item": {
                "type": "command_execution", "command": command, "exit_code": command_exit,
            }})
        Path(meta["events_path"]).write_text(
            "partial event\n" + "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8",
        )

    def test_worker_resume_keeps_session_and_archives_distinct_attempts(self):
        from codex_runner import finalize_and_precheck, parse_thread_id

        first = self.launch()
        self.complete(first)
        self.assertEqual(parse_thread_id(first["events_path"]), "fixture-session")
        first_receipt = finalize_and_precheck(self.cfg, self.order, first)
        self.assertTrue(first_receipt.precheck_passed, first_receipt.precheck_errors)
        self.assertEqual(first_receipt.git_changed_files, [self.file])
        second = self.launch(attempt=2, previous_receipt=first_receipt, feedback="Add provenance details")
        self.assertEqual(read_json(Path(second["run_path"]))["argv"][-3:], ["resume", "fixture-session", "-"])
        self.assertIn("Add provenance details", Path(second["prompt_path"]).read_text(encoding="utf-8"))
        self.complete(second)
        second_receipt = finalize_and_precheck(self.cfg, self.order, second)
        self.assertTrue(second_receipt.precheck_passed, second_receipt.precheck_errors)
        self.assertEqual(finalize_and_precheck(self.cfg, self.order, first), first_receipt)
        for meta, expected in ((first, first_receipt), (second, second_receipt)):
            self.assertEqual(read_json(Path(meta["attempt_dir"]) / "receipt.json"), expected.to_dict())
        self.assertEqual(read_json(self.folder / "receipt.json"), second_receipt.to_dict())

    def test_precheck_rejects_unverified_checks_and_out_of_scope_changes(self):
        from codex_runner import finalize_and_precheck

        meta = self.launch()
        self.complete(meta, command_exit=None, changed=[self.file, "unrelated.md"])
        receipt = finalize_and_precheck(self.cfg, self.order, meta)
        self.assertEqual(receipt.status, "failed")
        self.assertFalse(receipt.precheck_passed)
        self.assertFalse(receipt.verification_results[0]["passed"])
        self.assertIn("unrelated.md", receipt.git_changed_files)
        self.assertTrue(any("outside allowed_paths" in error for error in receipt.precheck_errors))

    def test_precheck_rejects_oversize_and_sensitive_paths(self):
        from codex_runner import MAX_FILE_BYTES, finalize_and_precheck

        large = self.root / "thesis" / "oversize.bin"
        with large.open("wb") as handle:
            handle.truncate(MAX_FILE_BYTES + 1)
        credential = self.root / "thesis" / "secrets.env"
        credential.write_text("TOKEN=fixture-credential-value\n", encoding="utf-8")
        meta = self.launch()
        self.complete(meta, changed=[self.file, "thesis/oversize.bin", "thesis/secrets.env"])
        receipt = finalize_and_precheck(self.cfg, self.order, meta)
        self.assertFalse(receipt.precheck_passed)
        errors = "\n".join(receipt.precheck_errors)
        self.assertIn("exceeds 5 MB", errors)
        self.assertRegex(errors, "sensitive|protected")

    def test_precheck_rejects_invalid_final_schema(self):
        from codex_runner import finalize_and_precheck

        meta = self.launch()
        self.complete(meta)
        result_path = Path(meta["last_msg_path"])
        outcome = read_json(result_path)
        outcome["commands_run"][0]["exit_code"] = True
        write_json(result_path, outcome)
        receipt = finalize_and_precheck(self.cfg, self.order, meta)
        self.assertFalse(receipt.precheck_passed)
        self.assertTrue(any("order_result.schema.json" in error for error in receipt.precheck_errors))

    def test_retry_starts_fresh_without_session_and_keeps_feedback(self):
        from codex_runner import finalize_and_precheck

        first = self.launch()
        self.complete(first)
        path = Path(first["events_path"])
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(line for line in lines if "thread.started" not in line), encoding="utf-8")
        receipt = finalize_and_precheck(self.cfg, self.order, first)
        self.assertIsNone(receipt.codex_session_id)
        second = self.launch(attempt=2, previous_receipt=receipt, feedback="Review the missing session")
        self.assertNotIn("resume", read_json(Path(second["run_path"]))["argv"])
        self.assertIn("Review the missing session", Path(second["pushback_path"]).read_text(encoding="utf-8"))

    def test_precheck_keeps_receipt_at_most_four_kib(self):
        from codex_runner import finalize_and_precheck

        meta = self.launch()
        paths = [self.file, *[f"outside/{'长' * 30}/{index}.md" for index in range(50)]]
        self.complete(meta, changed=paths)
        receipt = finalize_and_precheck(self.cfg, self.order, meta)
        self.assertFalse(receipt.precheck_passed)
        self.assertLessEqual((self.folder / "receipt.json").stat().st_size, 4096)
        full = read_json(Path(meta["attempt_dir"]) / "worker-manifest.json")
        self.assertEqual(set(full["receipt"]["git_changed_files"]), set(paths))

    def test_detached_supervisor_captures_exit_from_local_dummy_worker(self):
        from codex_runner import launch_worker, parse_thread_id

        event = json.dumps({"type": "thread.started", "thread_id": "local-dummy-session"})
        local_worker = [sys.executable, "-B", "-c", f"print({event!r})"]
        with patch("subprocess.Popen", LOCAL_POPEN), patch("codex_runner._codex_executable", return_value=local_worker):
            meta = launch_worker(self.cfg, self.order)
            exit_path = Path(meta["exit_path"])
            deadline = time.monotonic() + 10
            while not exit_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertTrue(exit_path.is_file())
        record = read_json(exit_path)
        self.assertEqual(record["exit_code"], 0, record["error"])
        self.assertEqual(parse_thread_id(meta["events_path"]), "local-dummy-session")

    def test_detached_supervisor_confirms_local_worker_cancellation(self):
        from codex_runner import launch_worker, terminate_worker

        local_worker = [sys.executable, "-B", "-c", "import time; time.sleep(12)"]
        with patch("subprocess.Popen", LOCAL_POPEN), patch("codex_runner._codex_executable", return_value=local_worker):
            meta = launch_worker(self.cfg, self.order)
            pid_path = Path(meta["worker_pid_path"])
            deadline = time.monotonic() + 8
            while not pid_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            stopped = terminate_worker(meta, "cancelled", wait_seconds=10)
        self.assertTrue(pid_path.is_file())
        self.assertTrue(stopped)
        exit_record = read_json(Path(meta["exit_path"]))
        self.assertEqual(exit_record["status"], "cancelled")
        self.assertNotEqual(exit_record["exit_code"], 0)


class StatusTests(OfflineCase):
    def test_public_snapshot_uses_whitelist_and_discards_sensitive_note(self):
        from status_publisher import refresh_status

        state = DirectorState(
            active_order={"order": work_order().to_dict(), "status": "awaiting_review", "attempt": 2},
            last_decision="TOKEN=fixture-secret", recent_public_note="Contact reader@example.invalid",
        )
        thesis = {"total": 2, "chapters_done": 1, "last_sprint_utc": NOW.isoformat(), "build_ok": False}
        cfg = replace(self.cfg, server_ssh_target="fixture")
        with patch("status_publisher._send_snapshot", return_value=None) as publish:
            snapshot = refresh_status(cfg, state, {"online": True, "private": "internal fixture"}, thesis)
        publish.assert_called_once_with(cfg, snapshot)
        self.assertEqual(read_json(cfg.state_dir / "auto-director-public.json"), snapshot)
        self.assertEqual(snapshot["active_order_state"], "awaiting_audit")
        self.assertEqual(snapshot["active_order_attempt"], 2)
        self.assertEqual(snapshot["thesis_chapters_total"], 2)
        self.assertIs(snapshot["thesis_build_ok"], False)
        self.assertIsNone(snapshot["recent_public_note"])
        self.assertNotIn("test-order", json.dumps(snapshot))
        self.assertNotIn("internal fixture", json.dumps(snapshot))
        self.assertNotIn("fixture-secret", (cfg.state_dir / "DASHBOARD.md").read_text(encoding="utf-8"))
        self.assertEqual(set(snapshot), {
            "schema_version", "director_state", "mode", "updated_at", "daily_wakeups_used", "daily_wakeups_cap",
            "active_order_category", "active_order_state", "active_order_attempt", "thesis_chapters_done",
            "thesis_chapters_total", "thesis_last_sprint_utc", "thesis_build_ok", "recent_public_note",
        })


class GitAcceptanceTests(OfflineCase):
    @unittest.skipUnless(shutil.which("git"), "Git is unavailable")
    def test_accept_commits_only_receipted_paths_and_preserves_index(self):
        from director_ctl import accept
        from codex_runner import finalize_and_precheck, launch_worker
        from types import SimpleNamespace

        repo = self.root / "repo"
        repo.mkdir()
        cfg = replace(self.cfg, repo_root=repo)
        order = work_order(allowed_paths=["thesis"], acceptance_checks=[])

        def git(*args):
            return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True, text=True, encoding="utf-8").stdout

        with patch("subprocess.Popen", LOCAL_POPEN):
            git("init", "-q", "-b", cfg.branch_name)
            git("config", "user.name", "Offline test")
            git("config", "user.email", "test@example.invalid")
            (repo / "existing.md").write_text("base\n", encoding="utf-8")
            git("add", "--", "existing.md")
            git("commit", "-q", "-m", "baseline")
            (repo / "existing.md").write_text("staged independently\n", encoding="utf-8")
            git("add", "--", "existing.md")
            def git_or_fake_worker(argv, *args, **kwargs):
                return LOCAL_POPEN(argv, *args, **kwargs) if argv[0] == "git" else Mock(pid=1234)

            with patch("codex_runner._codex_executable", return_value=["offline-test"]), patch(
                    "codex_runner.subprocess.Popen", side_effect=git_or_fake_worker):
                meta = launch_worker(cfg, order)
            changed = "thesis/new-file.md"
            (repo / "thesis").mkdir()
            (repo / changed).write_text("工单资料\n", encoding="utf-8")
            write_json(Path(meta["exit_path"]), {"order_id": order.order_id, "attempt": 1, "pid": meta["pid"], "exit_code": 0})
            write_json(Path(meta["last_msg_path"]), {
                "order_id": order.order_id, "outcome": "completed", "summary": "Added an index",
                "changed_files": [changed], "artifacts_produced": [changed], "commands_run": [],
                "blockers": [], "next_recommendation": "",
            })
            receipt = finalize_and_precheck(cfg, order, meta)
            self.assertTrue(receipt.precheck_passed, receipt.precheck_errors)
            state = DirectorState(active_order={
                "order": order.to_dict(), "status": "awaiting_review", "attempt": 1, "run_meta": meta,
            })
            args = SimpleNamespace(order=order.order_id, note="Reviewed", commit_msg="Add work-order index", force=False, push_pr=False)
            result = accept(cfg, state, args)
            self.assertEqual(result["status"], "accepted")
            self.assertEqual(git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines(), [changed])
            self.assertEqual(git("diff", "--cached", "--name-only").splitlines(), ["existing.md"])


class CutoverTests(OfflineCase):
    def test_rollback_restores_saved_policy_and_refuses_drift(self):
        import cutover_server_planner as cutover

        planner = cutover.Cutover.__new__(cutover.Cutover)
        planner.controller = ("fixture-python", "controller.py")
        planner.policy_path = self.root / "policy.json"
        before = b'{"planner_mode":"on_demand_async"}\n'
        after = b'{"planner_mode":"disabled"}\n'
        manifest = {
            "policy": str(planner.policy_path), "controller": list(planner.controller),
            "units": [], "active_timers": [], "files": {str(planner.policy_path): [cutover.encoded(before), cutover.encoded(after)]},
        }

        def write_fixture(path, value, expected):
            self.assertEqual(path, planner.policy_path)
            self.assertEqual(path.read_bytes(), expected)
            path.write_bytes(value)

        with (
            patch.object(planner, "idle_policy", return_value=nullcontext()),
            patch.object(planner, "controller_read") as controller,
            patch.object(cutover, "atomic_write", side_effect=write_fixture) as write,
            patch.object(cutover, "systemctl") as systemctl,
        ):
            planner.policy_path.write_bytes(b"unexpected edit\n")
            with self.assertRaisesRegex(cutover.Refused, "Rollback file drift"):
                planner.restore(manifest, {})
            write.assert_not_called()
            self.assertEqual(planner.policy_path.read_bytes(), b"unexpected edit\n")

            planner.policy_path.write_bytes(after)
            planner.restore(manifest, {})
            self.assertEqual(planner.policy_path.read_bytes(), before)
            planner.restore(manifest, {})
            write.assert_called_once_with(planner.policy_path, before, after)
            controller.assert_called_once_with("status")
            systemctl.assert_not_called()


class SlotStarvationTests(OfflineCase):
    def test_starved_slots_and_milestones_trigger_urgent_events(self):
        import watchdog
        from probes import summarize_server

        cfg = self.cfg
        base_obs = {
            "running_count": 4,
            "active_count": 4,
            "max_parallel_jobs": 16,
            "scheduler": {"pool": {"slots": {"total": 16, "free": 12, "quarantined": 0}}},
            "runs": [
                {"id": "r06-p0-lhs01-hold22-zero-h8-b0-r1", "collected": True, "success": True, "occupied": False},
            ],
            "repair_requests": [{"id": "r06-repair-1"}],
        }
        base_explain = {
            "replenishment": {
                "ready": 0,
                "preparing": False,
                "blocked_count": 95,
                "blocked_by_stage": {"missing_material": 48, "awaiting_acceptance": 47, "other": 0},
                "blocked": {"r06-lhs01-g0-proton-r1": "no enabled profile with a pinned P0 qualification"},
            }
        }
        snap = {"online": True, "source": "ssh", "service_active": True, "observation": base_obs, "explain": base_explain}
        summary = summarize_server(snap)
        self.assertTrue(summary["starved"])
        self.assertEqual(summary["free_slots"], 12)
        self.assertEqual(summary["awaiting_acceptance"], 47)
        self.assertEqual(summary["lhs_eighthsteps_count"], 1)
        self.assertEqual(summary["repair_requests"], 1)

        snap["summary"] = summary
        now = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
        thesis = {"chapters_done": 0, "chapters_total": 6, "assets_count": 0, "build_ok": True}
        with patch("watchdog.probe_server", return_value=snap), patch("watchdog.probe_thesis", return_value=thesis):
            dry = watchdog.tick(cfg, dry_run=True, now=now)
        self.assertEqual(dry["bucket"], "urgent")
        self.assertIn(dry["reason"], {"SLOTS_STARVING", "SIM_MILESTONE_COLLECTED"})
        self.assertIn("SLOTS_STARVING", dry["pending_events"])

    def test_briefing_contains_action_mandate_and_compact_summary(self):
        import watchdog
        from probes import summarize_server

        cfg = self.cfg
        state = DirectorState()
        snap = {
            "online": True,
            "source": "ssh",
            "service_active": True,
            "observation": {
                "running_count": 4,
                "scheduler": {"pool": {"slots": {"total": 16, "free": 12, "quarantined": 0}}},
                "runs": [{"id": f"pad-{i}", "payload": "x" * 500} for i in range(400)],
            },
            "explain": {
                "replenishment": {
                    "ready": 0,
                    "preparing": False,
                    "blocked_count": 95,
                    "blocked_by_stage": {"missing_material": 48, "awaiting_acceptance": 47},
                }
            },
        }
        snap["summary"] = summarize_server(snap)
        brief = watchdog._write_briefing(
            cfg, state, {"reason": "SLOTS_STARVING", "bucket": "urgent", "detail": "空闲 12/16 槽"},
            snap, {"chapters_done": 0, "chapters_total": 6, "assets_count": 0, "build_ok": True},
            datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc),
        )
        text = brief.read_text(encoding="utf-8")
        self.assertIn("严禁再派只读诊断", text)
        self.assertIn("month_one_supply.py", text)
        self.assertIn('"awaiting_acceptance": 47', text)
        self.assertLessEqual(len(text.encode("utf-8")), 6144)

    def test_semantic_fingerprint_ignores_raw_observation_jitter(self):
        from probes import compute_state_fingerprint, summarize_server

        base_obs = {
            "running_count": 8,
            "active_count": 8,
            "max_parallel_jobs": 16,
            "fingerprint": "aaa111",
            "scheduler": {"pool": {"slots": {"total": 16, "free": 8, "quarantined": 0}}},
            "runs": [{"id": "r06-run-1", "collected": True, "success": True, "occupied": False}],
        }
        base_explain = {
            "pending_reasons_at_observation": {"admission_telemetry": 10},
            "replenishment": {"ready": 18, "preparing": True, "blocked_count": 59, "blocked_by_stage": {"missing_material": 48, "awaiting_acceptance": 11}},
        }
        snap1 = {"online": True, "service_active": True, "observation": base_obs, "explain": base_explain}
        snap1["summary"] = summarize_server(snap1)
        snap2 = {
            "online": True,
            "service_active": True,
            "observation": base_obs | {"fingerprint": "bbb222", "running_count": 9},
            "explain": base_explain | {"pending_reasons_at_observation": {"admission_server_disk": 6}},
        }
        snap2["summary"] = summarize_server(snap2)
        thesis = {"chapters_done": 1, "chapters_total": 6, "assets_count": 5, "build_ok": True}
        self.assertEqual(compute_state_fingerprint(snap1, thesis), compute_state_fingerprint(snap2, thesis))

        snap3 = {
            "online": True,
            "service_active": True,
            "observation": base_obs | {"runs": base_obs["runs"] + [{"id": "r06-p0-lhs03-hold22-zero-h8-b1-r1", "collected": True, "success": True, "occupied": False}]},
            "explain": base_explain,
        }
        snap3["summary"] = summarize_server(snap3)
        self.assertNotEqual(compute_state_fingerprint(snap1, thesis), compute_state_fingerprint(snap3, thesis))

    def test_worker_busy_suppresses_state_changed_and_routine_milestones_stay_routine(self):
        import watchdog
        from probes import summarize_server

        cfg = self.cfg
        order = work_order()
        state = DirectorState(
            daily_date=TODAY,
            last_periodic_at=NOW.isoformat(),
            fingerprint="initial-fp",
            active_order={"order": order.to_dict(), "status": "running", "attempt": 1, "run_meta": {"pid": 1234}},
        )
        save_state(cfg, state)
        write_json(cfg.state_dir / "milestones.json", {"counts": {"r06_released_runs": 10, "lhs_eighthsteps_count": 8}})
        snap = {
            "online": True,
            "service_active": True,
            "observation": {"running_count": 8, "runs": [{"id": f"r06-r-{i}", "collected": True, "success": True, "occupied": False} for i in range(11)]},
            "explain": {"replenishment": {"ready": 10, "blocked_count": 0}},
        }
        snap["summary"] = summarize_server(snap)
        with (
            patch("watchdog.probe_server", return_value=snap),
            patch("watchdog.probe_thesis", return_value={}),
            patch("watchdog.probe_codex_worker", return_value={"status": "running"}),
            patch("watchdog.new_conversation", return_value="mock-conv") as conv,
            patch("watchdog.refresh_status"),
        ):
            result = watchdog.tick(cfg, now=NOW)
        self.assertIsNone(result["reason"])
        conv.assert_not_called()
        updated = load_state(cfg)
        self.assertNotIn("STATE_CHANGED", [e["reason"] for e in updated.pending_events])
        milestone_events = [e for e in updated.pending_events if e["reason"] == "SIM_MILESTONE_COLLECTED"]
        self.assertEqual(len(milestone_events), 1)
        self.assertEqual(milestone_events[0]["bucket"], "routine")

    def test_state_changed_sets_routine_cooldown(self):
        import watchdog

        cfg = self.cfg
        save_state(cfg, DirectorState(daily_date=TODAY, last_periodic_at=NOW.isoformat(), fingerprint="old-fp"))
        with (
            patch("watchdog.probe_server", return_value={"online": True, "service_active": True, "summary": {"running": 8, "free_slots": 8, "ready": 5, "starved": False}}),
            patch("watchdog.probe_thesis", return_value={}),
            patch("watchdog.probe_codex_worker", return_value={"status": "idle"}),
            patch("watchdog.new_conversation", return_value="mock-conv"),
            patch("watchdog.refresh_status"),
        ):
            first = watchdog.tick(cfg, now=NOW)
        self.assertEqual(first["reason"], "STATE_CHANGED")
        state = load_state(cfg)
        self.assertTrue(state.next_wake_at)
        state.active_turn = None
        state.fingerprint = "another-old-fp"
        save_state(cfg, state)
        with (
            patch("watchdog.probe_server", return_value={"online": True, "service_active": True, "summary": {"running": 8, "free_slots": 8, "ready": 5, "starved": False}}),
            patch("watchdog.probe_thesis", return_value={}),
            patch("watchdog.probe_codex_worker", return_value={"status": "idle"}),
            patch("watchdog.new_conversation", return_value="mock-conv") as conv,
            patch("watchdog.refresh_status"),
        ):
            second = watchdog.tick(cfg, now=NOW + timedelta(minutes=3))
        self.assertIsNone(second["reason"])
        conv.assert_not_called()

    def test_reclaim_orphaned_watchdog_only_terminates_dead_parent_holder(self):
        from runtime import reclaim_orphaned_watchdog

        lock_path = self.cfg.state_dir / "watchdog.lock"
        owner_path = self.cfg.state_dir / "watchdog.owner.json"
        write_json(owner_path, {"pid": 42424, "ppid": 99999, "started_at": NOW.isoformat()})
        with (
            patch("probes.pid_alive", side_effect=lambda p: p == 42424),
            patch("runtime._process_is_watchdog", return_value=True),
            patch("runtime._terminate_pid", return_value=True) as kill_fn,
        ):
            # pid_alive returns True for 42424 on initial check and False after kill if we use a counter:
            alive_calls = {"n": 0}
            def fake_alive(p):
                if p == 99999:
                    return False
                alive_calls["n"] += 1
                return alive_calls["n"] == 1
            with patch("probes.pid_alive", side_effect=fake_alive):
                self.assertTrue(reclaim_orphaned_watchdog(lock_path, wait_seconds=0.5))
            kill_fn.assert_called_once_with(42424)

        with (
            patch("probes.pid_alive", return_value=True),
            patch("runtime._terminate_pid") as kill_fn,
        ):
            self.assertFalse(reclaim_orphaned_watchdog(lock_path, wait_seconds=0.5))
            kill_fn.assert_not_called()

    def test_daemon_exits_cleanly_when_parent_exits(self):
        import watchdog

        fake_watcher = Mock(ppid=99999)
        fake_watcher.parent_exited.return_value = True
        with (
            patch.object(watchdog, "load_config", return_value=self.cfg),
            patch.object(watchdog, "ParentWatcher", return_value=fake_watcher),
            patch.object(watchdog, "tick") as mock_tick,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            code = watchdog.main(["--daemon", "--exit-with-parent"])
        self.assertEqual(code, 0)
        mock_tick.assert_not_called()
        fake_watcher.close.assert_called_once()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "parent_exited")


if __name__ == "__main__":
    unittest.main()
