import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import status_checker as checker


UTC = dt.timezone.utc
COUNTER_FIELDS = (
    "daily_wakeups_used", "daily_wakeups_cap", "active_order_attempt",
    "thesis_chapters_done", "thesis_chapters_total",
)


class AutoDirectorProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.path = root / "auto-director.json"
        self.missing = root / "missing"
        self.now = dt.datetime.now(UTC).replace(microsecond=0)
        self.updated_at = self.timestamp(self.now)
        self.last_sprint = self.timestamp(self.now - dt.timedelta(minutes=5))
        self.snapshot = {
            "director_state": "codex_running",
            "mode": "event_driven",
            "updated_at": self.updated_at,
            "daily_wakeups_used": 2,
            "daily_wakeups_cap": 8,
            "active_order_category": "thesis_assets",
            "active_order_state": "running",
            "active_order_attempt": 1,
            "thesis_chapters_done": 3,
            "thesis_chapters_total": 6,
            "thesis_last_sprint_utc": self.last_sprint,
            "thesis_build_ok": True,
            "recent_public_note": "已整理第三章图表",
        }
        self.research = {"schema_version": 1, "available": True, "revision": "r0.6", "cases": []}

    @staticmethod
    def timestamp(value):
        return value.isoformat().replace("+00:00", "Z")

    def write_snapshot(self, **changes):
        self.path.write_text(json.dumps({**self.snapshot, **changes}), encoding="utf-8")

    def build(self, research=None, mode="live"):
        source = self.research if research is None else research
        with (
            patch.object(checker, "research_site_state", return_value="operational"),
            patch.object(checker, "systemd_state", return_value="operational"),
            patch.object(checker, "system_metrics", return_value={}),
            patch.object(checker, "build_research", return_value=dict(source)),
            patch.object(checker, "PROGRESS_PATH", self.missing),
            patch.object(checker, "RESPONSE_SUPPLY_PATH", self.missing),
            patch.object(checker, "WORK_ITEMS_PATH", self.missing),
            patch.object(checker, "STATS_SNAPSHOT_PATH", None),
        ):
            status = checker.build_status(
                observation_path=self.missing, runtime_path=self.missing,
                runs_root=self.missing, pause_path=self.missing, scheduler_path=self.missing,
                mode=mode, research=dict(source), auto_director_path=self.path,
            )
        live = checker.build_live(status, {})
        for payload in (status, live):
            checker.check_public_payload(payload)
        return status, live

    def test_missing_or_unreadable_snapshot_keeps_existing_status(self):
        for raw in (None, b"{", b"[]", b"\xff", b"{}"):
            with self.subTest(raw=raw):
                if raw is not None:
                    self.path.write_bytes(raw)
                self.assertIsNone(checker.load_auto_director(self.path, now=self.now))
                status, live = self.build()
                for payload, research_key in ((status, "research"), (live, "research_summary")):
                    self.assertEqual(payload["overall"], "operational")
                    self.assertEqual(payload[research_key]["revision"], "r0.6")
                    self.assertNotIn("director", payload["health"])
                    self.assertNotIn("paper_progress", payload[research_key])
        self.assertIsNone(checker.load_auto_director(self.path.parent, now=self.now))

    def test_valid_snapshot_projects_exact_public_fields(self):
        self.write_snapshot()
        expected_director = {
            "director_state": "codex_running",
            "mode": "event_driven",
            "updated_at": self.updated_at,
            "stale": False,
            "daily_wakeups_used": 2,
            "daily_wakeups_cap": 8,
            "active_order_category": "thesis_assets",
            "active_order_state": "running",
            "active_order_attempt": 1,
            "recent_public_note": "已整理第三章图表",
        }
        expected_progress = {
            "chapters_done": 3, "chapters_total": 6,
            "last_sprint_utc": self.last_sprint, "build_ok": True, "updated_at": self.updated_at,
        }
        status, live = self.build(mode="both")
        self.assertEqual(status["health"]["director"], expected_director)
        self.assertEqual(live["health"]["director"], expected_director)
        self.assertEqual(status["research"]["paper_progress"], expected_progress)
        self.assertEqual(live["research_summary"]["paper_progress"], expected_progress)

    def test_snapshot_becomes_stale_after_900_seconds(self):
        now = dt.datetime(2026, 11, 24, 12, tzinfo=UTC)
        for age, stale in ((899, False), (900, False), (901, True)):
            with self.subTest(age=age):
                self.write_snapshot(updated_at=self.timestamp(now - dt.timedelta(seconds=age)))
                result = checker.load_auto_director(self.path, now=now)
                self.assertIsNotNone(result)
                self.assertEqual(result["age_seconds"], age)
                self.assertIs(result["stale"], stale)

    def test_live_progress_refreshes_then_removes_cached_value_when_source_disappears(self):
        self.write_snapshot()
        first_status, first_live = self.build()
        cached_research = first_status["research"]
        self.write_snapshot(thesis_chapters_done=4, thesis_build_ok=False)
        second_status, second_live = self.build(research=cached_research)
        self.assertEqual(first_live["research_summary"]["paper_progress"]["chapters_done"], 3)
        updated = second_live["research_summary"]["paper_progress"]
        self.assertEqual(updated["chapters_done"], 4)
        self.assertIs(updated["build_ok"], False)
        self.assertEqual(second_status["research"]["paper_progress"], updated)
        self.assertNotEqual(first_live["research_hash"], second_live["research_hash"])

        self.path.unlink()
        status, live = self.build(research=second_status["research"])
        self.assertNotIn("director", live["health"])
        self.assertNotIn("paper_progress", status["research"])
        self.assertNotIn("paper_progress", live["research_summary"])
        self.assertEqual(live["research_summary"]["revision"], "r0.6")

    def test_nullable_fields_and_maximum_note_length(self):
        self.write_snapshot(thesis_last_sprint_utc=None, thesis_build_ok=None, recent_public_note="文" * 160)
        status, live = self.build()
        self.assertEqual(status["health"]["director"]["recent_public_note"], "文" * 160)
        progress = live["research_summary"]["paper_progress"]
        self.assertIsNone(progress["last_sprint_utc"])
        self.assertIsNone(progress["build_ok"])

    def test_unsafe_notes_clear_only_note_and_never_reach_public_payloads(self):
        notes = (
            "/home/tcad", "127.0.0.1", "run_id", "ssh sim-host", "<script>",
            "sim-host", "r06-hr-case-001", "r06-hp-case-001", "HR-001", "HP-001",
            "https://example.invalid", "python -m example", "文" * 161,
        )
        self.write_snapshot(recent_public_note=None)
        clean = checker.load_auto_director(self.path, now=self.now)
        self.assertIsNotNone(clean)
        self.assertIsNone(clean["recent_public_note"])
        for note in notes:
            with self.subTest(note=note):
                self.write_snapshot(recent_public_note=note)
                self.assertEqual(checker.load_auto_director(self.path, now=self.now), clean)
                status, live = self.build()
                for payload, research_key in ((status, "research"), (live, "research_summary")):
                    self.assertIsNone(payload["health"]["director"]["recent_public_note"])
                    self.assertEqual(payload[research_key]["paper_progress"]["chapters_done"], 3)
                    self.assertNotIn(note, json.dumps(payload, ensure_ascii=False))

    def test_schema_errors_reject_entire_snapshot(self):
        invalid_values = (
            ("unexpected", "private-value"),
            ("director_state", "unknown"),
            ("mode", "always"),
            ("active_order_category", "other"),
            ("active_order_state", []),
            ("active_order_state", "finished"),
            ("daily_wakeups_cap", "8"),
            ("active_order_attempt", 1.5),
            ("thesis_chapters_done", -1),
            ("thesis_build_ok", 1),
            ("updated_at", "2026-11-24T12:00:00+01:00"),
            ("updated_at", "2026-11-24T12:00:00"),
            ("thesis_last_sprint_utc", "2026-11-24T12:00:00-07:00"),
            ("thesis_last_sprint_utc", "2026-11-31T12:00:00Z"),
        ) + tuple((field, True) for field in COUNTER_FIELDS)
        for field, invalid in invalid_values:
            with self.subTest(field=field, value=invalid):
                self.write_snapshot(**{field: invalid})
                self.assertIsNone(checker.load_auto_director(self.path, now=self.now))

        for field in self.snapshot:
            with self.subTest(missing=field):
                incomplete = dict(self.snapshot)
                del incomplete[field]
                self.path.write_text(json.dumps(incomplete), encoding="utf-8")
                self.assertIsNone(checker.load_auto_director(self.path, now=self.now))

    def test_duplicate_field_rejects_entire_snapshot(self):
        body = json.dumps(self.snapshot)
        self.path.write_text('{"mode":"event_driven",' + body[1:], encoding="utf-8")
        self.assertIsNone(checker.load_auto_director(self.path, now=self.now))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for dashboard rendering checks")
    def test_public_paper_progress_renders_in_both_languages_and_hides_when_absent(self):
        self.write_snapshot()
        _, live = self.build(research={"available": False})
        self.path.unlink()
        _, empty_live = self.build(research={"available": False})
        module = (Path(__file__).resolve().parents[1] / "src/research-dashboard.js").as_uri()
        script = (
            "import assert from 'node:assert/strict';\n"
            f"import {{renderResearch}} from {json.dumps(module)};\n"
            f"const research = {json.dumps(live['research_summary'])};\n"
            f"const empty = {json.dumps(empty_live['research_summary'])};\n"
            """
for (const [lang, locale, heading, build, sprint] of [
  ['zh', 'zh-CN', '论文 v2 渐进进度', '成功', '最近冲刺'],
  ['en', 'en-US', 'Thesis v2 progress', 'Passed', 'Latest sprint'],
]) {
  const html = renderResearch(research, lang);
  const sprintDate = new Intl.DateTimeFormat(locale, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(research.paper_progress.last_sprint_utc));
  for (const text of [heading, '3 / 6', build, sprint, sprintDate]) assert.ok(html.includes(text), text);
  assert.ok(!renderResearch(empty, lang).includes(heading), heading);
}
"""
        )
        result = subprocess.run(
            ["node", "--input-type=module"], input=script, encoding="utf-8",
            capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
