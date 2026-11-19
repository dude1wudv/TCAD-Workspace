import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

from progress_store import (
    PUBLIC_FIELDS, clear_progress, init_store, load_public_progress,
    main, set_progress,
)


class ProgressStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "private" / "progress.sqlite3"
        init_store(self.db)

    def write(self, **changes):
        payload = dict(
            case_id="r05-D0-C0-p001-b0", issue="newton_nonconvergence",
            action="investigating", phase="device", note="牛顿不收敛",
            next_step="检查迭代残差", evidence="",
        )
        payload.update(changes)
        return set_progress(self.db, **payload)

    @contextlib.contextmanager
    def connection(self, path=None):
        with contextlib.closing(sqlite3.connect(str(path or self.db))) as connection:
            with connection:
                yield connection

    def history(self):
        with self.connection() as connection:
            return connection.execute(
                "SELECT operation, action, evidence FROM history ORDER BY id"
            ).fetchall()

    def test_upsert_current_and_append_history(self):
        self.write()
        self.write(action="fixing", note="调整求解策略")
        rows = load_public_progress(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "fixing")
        self.assertEqual([row[:2] for row in self.history()],
                         [("set", "investigating"), ("set", "fixing")])
        self.assertTrue(rows[0]["updated_at"].endswith("Z"))

    def test_private_evidence_is_never_public(self):
        private_reference = "/home/tcad/private/electrical/main-acceptance.json"
        result = self.write(action="resolved", evidence=private_reference)
        self.assertTrue(result["evidence_recorded"])
        public = load_public_progress(self.db)
        self.assertEqual(set(public[0]), set(PUBLIC_FIELDS))
        self.assertNotIn(private_reference, json.dumps(public))
        self.assertNotIn("evidence", public[0])
        self.assertEqual(self.history()[0][2], private_reference)
        self.assertNotIn("accepted", public[0])
        self.assertNotIn("success", public[0])

    def test_resolved_requires_evidence(self):
        for evidence in ("", "   "):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.write(action="resolved", evidence=evidence)
        self.assertEqual(self.history(), [])

    def test_enum_whitelists(self):
        for key, value in (
            ("issue", "unknown"), ("action", "accepted"),
            ("phase", "succeeded"), ("issue", "NEWTON_NONCONVERGENCE"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.write(**{key: value})

    def test_public_case_ids(self):
        for case_id in ("BENCH-mc2-four-task-01", "r05-D0-C0-p001-b0",
                        "r06-z-d0-nominal-b0", "r06-s-d0-nominal-p00-b1",
                        "r06-hr-d0-nominal-p00-b1", "r07-trial-dramx-b1", "r010-next-b0"):
            self.write(case_id=case_id)
        for case_id in (
            "r04-real-run", "auto-r04-real-run", "r05-r04-real-run",
            "BENCH-../../run", "r05-", "r05-事件1", "r05-" + "a" * 100, "r7-short", "r07-../../run",
        ):
            with self.subTest(case_id=case_id), self.assertRaises(ValueError):
                self.write(case_id=case_id)

    def test_public_text_rejects_paths_ips_secrets_html_and_claims(self):
        unsafe = (
            "/srv/private", r"C:\private\run", "../inputs", r"\\host\share",
            "127.0.0.1", "203.0.113.10", "::1", "2001:db8::1",
            "https://example.com", "www.example.com",
            "systemctl restart simulation", "ssh tcad-tail", "sudo bash",
            "token=private-value", "api_key: private-value",
            "Bearer private-value", "密码：秘密", "sk-123456789abcdef",
            "<script>alert(1)</script>", "&lt;script&gt;",
            "＜img src=x＞", "ＡＰＩ＿ＫＥＹ＝private",
            "求解成功", "accepted", "solver succeeded", "验收通过",
            "已收敛", "复验通过", "牛顿\n不收敛", "test\x00text",
            "隐形\u200b字符", "\u202e倒序", "a" * 181,
        )
        for field in ("note", "next_step"):
            for text in unsafe:
                with self.subTest(field=field, text=text), self.assertRaises(ValueError):
                    self.write(**{field: text})
        self.assertEqual(self.history(), [])

    def test_private_evidence_still_rejects_credentials_and_markup(self):
        for evidence in ("token=secret", "https://private.example/a", "<b>log</b>",
                         "line\nbreak", "x" * 513):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.write(evidence=evidence)

    def test_clear_removes_current_and_preserves_history(self):
        self.write(evidence="audit:mc2-01")
        self.assertTrue(clear_progress(self.db, case_id="r05-D0-C0-p001-b0"))
        self.assertEqual(load_public_progress(self.db), [])
        self.assertEqual([row[0] for row in self.history()], ["set", "clear"])
        self.assertEqual(self.history()[-1][2], "audit:mc2-01")
        self.assertFalse(clear_progress(self.db, case_id="r05-D0-C0-p001-b0"))
        self.assertEqual(len(self.history()), 2)

    def test_history_is_append_only(self):
        self.write()
        with self.connection() as connection:
            for sql in ("UPDATE history SET note='changed'", "DELETE FROM history"):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql)
        self.assertEqual(len(self.history()), 1)

    def test_failed_history_append_rolls_back_upsert(self):
        self.write()
        with self.connection() as connection:
            connection.execute("""CREATE TRIGGER reject_history BEFORE INSERT ON history
                BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with self.assertRaises(ValueError):
            self.write(action="fixing")
        self.assertEqual(load_public_progress(self.db)[0]["action"], "investigating")
        self.assertEqual(len(self.history()), 1)
        with self.assertRaises(ValueError):
            clear_progress(self.db, case_id="r05-D0-C0-p001-b0")
        self.assertEqual(len(load_public_progress(self.db)), 1)

    def test_readonly_snapshot_and_missing_database(self):
        self.write()
        before = self.db.read_bytes()
        load_public_progress(self.db)
        self.assertEqual(before, self.db.read_bytes())
        missing = self.db.parent / "missing.sqlite3"
        self.assertEqual(load_public_progress(missing), [])
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            set_progress(missing, case_id="BENCH-01", issue="none",
                         action="monitoring", phase="preparing")
        self.assertFalse(missing.exists())

    def test_database_reads_are_opened_readonly(self):
        original = sqlite3.connect
        calls = []

        def inspect(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        with patch("progress_store.sqlite3.connect", side_effect=inspect):
            load_public_progress(self.db)
        self.assertIn("?mode=ro", calls[0][0][0])
        self.assertTrue(calls[0][1]["uri"])

    def test_corrupt_or_unrelated_database_raises_sanitized_value_error(self):
        self.db.write_bytes(b"not sqlite private /home/tcad/secret")
        for operation in (load_public_progress, init_store):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ValueError) as raised:
                    operation(self.db)
                self.assertNotIn("/home/tcad", str(raised.exception))
        unrelated = self.db.parent / "other.sqlite3"
        with self.connection(unrelated) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        with self.assertRaises(ValueError):
            init_store(unrelated)

    def test_external_unsafe_annotation_invalidates_snapshot(self):
        self.write()
        with self.connection() as connection:
            connection.execute("UPDATE progress SET note='<script>'")
        with self.assertRaises(ValueError):
            load_public_progress(self.db)

    def test_external_unsupported_status_and_timestamp_are_rejected(self):
        self.write()
        for column, value in (
            ("action", "accepted"),
            ("issue", "private-run-diagnostics"),
            ("updated_at", "2026-11-17Z"),
            ("updated_at", "2026-11-17T05:00:00+01:00"),
        ):
            self.write()
            with self.connection() as connection:
                connection.execute("UPDATE progress SET {}=?".format(column), (value,))
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                load_public_progress(self.db)

    def test_unknown_schema_and_missing_table_are_rejected(self):
        with self.connection() as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            load_public_progress(self.db)
        with self.connection() as connection:
            connection.execute("PRAGMA user_version=1")
            connection.execute("DROP TABLE progress")
        with self.assertRaises(ValueError):
            load_public_progress(self.db)

    def test_concurrent_writers_keep_all_history(self):
        def update(index):
            return self.write(case_id="BENCH-concurrent", note="处理阶段{}".format(index))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(update, range(12)))
        self.assertEqual(len(results), 12)
        self.assertEqual(len(self.history()), 12)
        self.assertEqual(len(load_public_progress(self.db)), 1)

    def test_busy_database_uses_bounded_timeout(self):
        with self.connection() as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ValueError):
                set_progress(self.db, case_id="BENCH-busy", issue="none",
                             action="monitoring", phase="device", timeout=0.02)
            blocker.rollback()
        self.assertEqual(self.history(), [])

    def test_cli_commands_and_argument_positions(self):
        destination = self.db.parent / "cli.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--db", str(destination), "init"]), 0)
            self.assertEqual(main([
                "set", "--db", str(destination), "--case", "BENCH-cli",
                "--issue", "newton_nonconvergence", "--action", "fixing",
                "--phase", "device", "--note", "调整求解策略",
            ]), 0)
            self.assertEqual(main(["list", "--db", str(destination)]), 0)
            self.assertEqual(main(["clear", "--db", str(destination),
                                   "--case", "BENCH-cli"]), 0)
        outputs = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(outputs[2][0]["action"], "fixing")
        self.assertEqual(outputs[3], {"cleared": True})

    def test_cli_failure_does_not_echo_unsafe_input(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main([
                "--db", str(self.db), "set", "--case", "BENCH-cli",
                "--issue", "none", "--action", "monitoring",
                "--phase", "device", "--note", "token=private-value",
            ]), 2)
        self.assertNotIn("private-value", errors.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits require Linux/Unix")
    def test_private_posix_permissions_and_symlink_rejection(self):
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.db.parent.stat().st_mode), 0o750)
        self.db.chmod(0o666)
        self.db.parent.chmod(0o777)
        self.write()
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.db.parent.stat().st_mode), 0o750)
        link = self.db.parent / "linked.sqlite3"
        link.symlink_to(self.db)
        with self.assertRaises(ValueError):
            load_public_progress(link)
        with self.assertRaises(ValueError):
            init_store(link)


if __name__ == "__main__":
    unittest.main()
