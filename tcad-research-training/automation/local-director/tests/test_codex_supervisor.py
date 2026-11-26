import tempfile
import unittest
import sys
import json
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from campaign_fsm import ensure_campaign_files, public_campaign_with_metrics
from codex_supervisor import _valid_suggestion, actionable, build_prompt, run_supervisor
from config import Config
from schemas import DirectorState


def decision(action="noop", task=None):
    return {
        "action": action,
        "task": task,
        "phase": "P0_BOOTSTRAP",
        "reason": "没有新的可执行进展",
        "next_check_seconds": 600,
        "blocked_reason": None,
    }


class CodexSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = Config(
            repo_root=self.root, state_dir=self.root / "state", public_status_url="",
            campaign_execution_enabled=True,
        )
        self.campaign, self.backlog = ensure_campaign_files(self.cfg.state_dir)

    def tearDown(self):
        self.temp.cleanup()

    def test_scheduled_pulse_stays_zero_token_when_nothing_is_actionable(self):
        reason = actionable(
            self.cfg,
            self.campaign,
            self.backlog,
            {"online": True, "service_active": True, "summary": {"starved": False}},
            DirectorState().to_dict(),
            now=None,
            scheduled_pulse=False,
        )
        self.assertEqual(reason, (True, "backlog_ready"))

        for task in self.backlog["tasks"]:
            task["status"] = "accepted"
        reason = actionable(
            self.cfg,
            self.campaign,
            self.backlog,
            {"online": True, "service_active": True, "summary": {"starved": False}},
            DirectorState().to_dict(),
            scheduled_pulse=False,
        )
        self.assertEqual(reason, (False, None))

    def test_supervisor_returns_only_a_redacted_suggestion(self):
        campaign_before = json.dumps(self.campaign, ensure_ascii=False, sort_keys=True)
        backlog_before = json.dumps(self.backlog, ensure_ascii=False, sort_keys=True)
        files_before = sorted(path.relative_to(self.cfg.state_dir).as_posix()
                              for path in self.cfg.state_dir.rglob("*") if path.is_file())
        suggestion = decision()
        suggestion["reason"] = f"检查 {self.root} /srv/private run_id=auto-r06-test-1234"
        with patch("codex_supervisor._invoke_supervisor", return_value=suggestion):
            result = run_supervisor(
                self.cfg, self.campaign, self.backlog,
                {"online": True, "service_active": True, "summary": {}},
                DirectorState().to_dict(), "periodic_review",
            )
        self.assertEqual(set(result), {"action", "task", "phase", "reason", "next_check_seconds", "blocked_reason"})
        self.assertNotIn("progress", result)
        self.assertNotIn(str(self.root), result["reason"])
        self.assertNotIn("/srv/private", result["reason"])
        self.assertNotIn("run_id", result["reason"])
        self.assertEqual(campaign_before, json.dumps(self.campaign, ensure_ascii=False, sort_keys=True))
        self.assertEqual(backlog_before, json.dumps(self.backlog, ensure_ascii=False, sort_keys=True))
        files_after = sorted(path.relative_to(self.cfg.state_dir).as_posix()
                             for path in self.cfg.state_dir.rglob("*") if path.is_file())
        self.assertEqual(files_before, files_after)

    def test_suggestion_schema_rejects_progress_and_invalid_combinations(self):
        valid = decision()
        self.assertEqual(_valid_suggestion(valid), valid)
        for invalid in (
            valid | {"progress": {}},
            {key: value for key, value in valid.items() if key != "reason"},
            valid | {"action": "dispatch"},
            valid | {"action": "blocked", "task": "task-a", "blocked_reason": None},
            valid | {"next_check_seconds": 30},
            valid | {"phase": "private-phase"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _valid_suggestion(invalid)

    def test_prompt_does_not_expose_private_paths(self):
        prompt = build_prompt({"campaign": public_campaign_with_metrics(self.campaign), "server": {}, "backlog": []})
        self.assertNotIn(str(self.root), prompt)
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn("Do not include progress", prompt)


if __name__ == "__main__":
    unittest.main()
