"""Focused, offline synthetic-archive tests; no runner or remote operations."""
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("retention_tested", HERE / "retention.py")
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "runs" / "fixture-run"
        self.run.mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(retention, "LOG_THRESHOLD", 64).start()
        patch.object(retention, "BLOCK", 256).start()
        callback = (b"R04_QY_CALLBACK n=123 region=channel time=1.0e-12 dt=2E-15"
                    b" type=1 x=-.1 y=0 z=+0.0 G=1E20 eta=.5")
        self.big_log = (
            "求解开始\n".encode("utf-8") + (callback + b"\n") * 30
            + b" R04_QY_CALLBACK n=1\nR04_QY_CALLBACK n=2 extra\n"
            + b"R04_QY_CALLBACK n=-3\n" + callback + b"\r\n"
            + callback + b" trailing-field=preserve\n"
            + b"R04_QY_CALLBACK n=" + b"5" * 600 + b"\r\n"
            + b"ordinary-" + b"x" * 800 + b"\n"
            + b"\xff\x00binary-log\n" + callback)
        self.files = {
            "输入/设备.cmd": "电极与物理参数\n".encode("utf-8"),
            "数值.plt": b"1 2.000e-30\n",
            "plot.tdr": bytes(range(256)) * 4,
            "state.sav": b"state" * 100,
            "execution.log": self.big_log,
            "small.log": b"R04_QY_CALLBACK n=1\n",
            "other.bin": b"unchanged" * 100,
            "_collection-members.json": b'{"original": "index remains original"}',
        }
        self.make_archive()

    def make_archive(self, extra=None):
        with tarfile.open(self.run / retention.RAW, "w", format=tarfile.PAX_FORMAT) as archive:
            for name, content in self.files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if extra:
                archive.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isfile() else None)
        self.raw = (self.run / retention.RAW).read_bytes()
        self.manifest = dict(run_id=self.run.name, state="COLLECTED", remote_exit_code=0,
                             collection_verified=True, parallel_slot_released=True,
                             results_sha256=sha(self.raw), note="中文原清单不改")
        self.save_manifest()

    def save_manifest(self):
        self.manifest_bytes = (json.dumps(self.manifest, ensure_ascii=False, indent=3) + "\n").encode("utf-8")
        (self.run / "manifest.json").write_bytes(self.manifest_bytes)

    def save_receipt(self, doc):
        (self.run / retention.RECEIPT).write_text(json.dumps(doc), encoding="utf-8")

    def receipt(self):
        return json.loads((self.run / retention.RECEIPT).read_text(encoding="utf-8"))

    def intact_original(self):
        self.assertEqual((self.run / retention.RAW).read_bytes(), self.raw)
        self.assertEqual((self.run / "manifest.json").read_bytes(), self.manifest_bytes)

    def test_compact_exact_preservation_projection_and_line_witness(self):
        doc = retention.compact(self.run)
        self.assertFalse((self.run / retention.RAW).exists())
        self.assertEqual((self.run / "manifest.json").read_bytes(), self.manifest_bytes)
        self.assertTrue(retention.verify_retained(self.run, self.manifest))
        self.assertFalse(doc["is_scientific_acceptance"])
        self.assertEqual(doc["schema"], "tcad-result-retention-v1")
        with gzip.open(self.run / retention.RAW_GZ, "rb") as source:
            self.assertEqual(source.read(), self.raw)
        with tarfile.open(self.run / retention.ESSENTIAL) as archive:
            kept = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
        expected_lines = self.big_log.splitlines(keepends=True)
        expected = b"".join(line for line in expected_lines if not retention.CALLBACK.fullmatch(line))
        self.assertEqual(kept["execution.log"], expected)
        for name, content in self.files.items():
            if name != "execution.log":
                self.assertEqual(kept[name], content, name)
        inventory = {m["name"]: m for m in doc["original_members"]}
        self.assertEqual(set(inventory), set(self.files))
        for name, content in self.files.items():
            self.assertEqual(inventory[name]["sha256"], sha(content))
            self.assertEqual(inventory[name]["size"], len(content))
        log = inventory["execution.log"]
        self.assertEqual(log["policy"], "projected_log")
        self.assertEqual(log["dropped_callback_lines"], 32)
        self.assertEqual(log["retained_sha256"], sha(expected))
        self.assertEqual(log["original_lines"], len(expected_lines))
        with gzip.open(self.run / retention.WITNESS, "rt", encoding="utf-8") as source:
            witness = [json.loads(line) for line in source][1:]
        mapping = {}
        for row in witness:
            for offset in range(row["line_count"]):
                mapping[row["retained_start_line"] + offset] = row["original_start_line"] + offset
        retained = expected.splitlines(keepends=True)
        self.assertEqual(len(mapping), len(retained))
        for index, line in enumerate(retained, 1):
            self.assertEqual(line, expected_lines[mapping[index] - 1])

    def test_restore_exact_idempotence_and_dematerialize_without_recompress(self):
        retention.compact(self.run)
        original_receipt = (self.run / retention.RECEIPT).read_bytes()
        artifact_before = {n: ((self.run / n).stat().st_mtime_ns, (self.run / n).read_bytes())
                           for n in (retention.RAW_GZ, retention.ESSENTIAL, retention.WITNESS)}
        self.assertTrue(retention.restore(self.run)["restored"])
        self.intact_original()
        self.assertFalse(retention.restore(self.run)["restored"])
        with patch.object(retention, "_raw_backup", side_effect=AssertionError("must not recompress")):
            self.assertTrue(retention.compact(self.run)["results_tar_removed"])
            self.assertFalse(retention.compact(self.run)["results_tar_removed"])
        self.assertEqual((self.run / retention.RECEIPT).read_bytes(), original_receipt)
        for n, before in artifact_before.items():
            self.assertEqual(((self.run / n).stat().st_mtime_ns, (self.run / n).read_bytes()), before)
        retention.restore(self.run)
        self.assertTrue(retention.dematerialize(self.run)["results_tar_removed"])
        self.assertFalse(retention.dematerialize(self.run)["results_tar_removed"])

    def test_success_and_released_gates_preserve_active_failed_data(self):
        original = dict(self.manifest)
        for key, value in (("state", "RUNNING"), ("state", "FAILED"),
                           ("remote_exit_code", 143), ("collection_verified", False),
                           ("parallel_slot_released", False)):
            with self.subTest(key=key, value=value):
                self.manifest = dict(original, **{key: value})
                self.save_manifest()
                with self.assertRaises(ValueError):
                    retention.compact(self.run)
                self.intact_original()
                self.assertFalse((self.run / retention.RECEIPT).exists())

    def test_artifact_tamper_missing_and_stat_cache_invalidation(self):
        retention.compact(self.run)
        cache = {}
        self.assertTrue(retention.verify_retained(self.run, self.manifest, cache))
        with patch.object(retention.gzip, "GzipFile", side_effect=AssertionError("no inflation in verify")):
            self.assertTrue(retention.verify_retained(self.run, self.manifest, cache))
        for name in (retention.RAW_GZ, retention.ESSENTIAL, retention.WITNESS):
            with self.subTest(name=name):
                p = self.run / name
                original, metadata = p.read_bytes(), p.stat()
                modified = bytes([original[0] ^ 1]) + original[1:]
                p.write_bytes(modified)
                os.utime(p, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                self.assertFalse(retention.verify_retained(self.run, self.manifest, cache))
                with self.assertRaises(ValueError):
                    retention.restore(self.run)
                p.write_bytes(original)
                self.assertTrue(retention.verify_retained(self.run, self.manifest, cache))
                p.unlink()
                self.assertFalse(retention.verify_retained(self.run, self.manifest, cache))
                p.write_bytes(original)

    def test_manifest_bytes_binding_even_if_same_json_and_wrong_caller_manifest(self):
        retention.compact(self.run)
        (self.run / "manifest.json").write_bytes(self.manifest_bytes + b" ")
        self.assertFalse(retention.verify_retained(self.run, self.manifest))
        (self.run / "manifest.json").write_bytes(self.manifest_bytes)
        self.assertFalse(retention.verify_retained(self.run, dict(self.manifest, remote_exit_code=1)))
        self.assertTrue(retention.verify_retained(self.run, self.manifest))

    def test_different_existing_raw_is_never_overwritten_or_deleted(self):
        retention.compact(self.run)
        (self.run / retention.RAW).write_bytes(b"other original")
        for action in (retention.restore, retention.dematerialize, retention.compact):
            with self.subTest(action=action.__name__):
                with self.assertRaises(ValueError):
                    action(self.run)
                self.assertEqual((self.run / retention.RAW).read_bytes(), b"other original")
                self.assertTrue((self.run / retention.RAW_GZ).exists())

    def test_backup_validation_failure_keeps_original_and_manifest(self):
        with patch.object(retention, "_verify_raw_backup", side_effect=ValueError("injected gzip failure")):
            with self.assertRaises(ValueError):
                retention.compact(self.run)
        self.intact_original()
        self.assertFalse((self.run / retention.RECEIPT).exists())
        self.assertFalse(list(self.run.glob(".retention-*")))

    def test_atomic_receipt_failure_keeps_raw_and_retry_recovers_partial_artifacts(self):
        publish = retention._publish
        def fail_receipt(temp, target):
            if target.name == retention.RECEIPT:
                raise OSError("injected receipt commit failure")
            publish(temp, target)
        with patch.object(retention, "_publish", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                retention.compact(self.run)
        self.intact_original()
        self.assertFalse((self.run / retention.RECEIPT).exists())
        self.assertTrue(retention.compact(self.run)["results_tar_removed"])

    def test_source_signature_change_aborts_before_publication(self):
        build = retention._essential
        def changed(*args, **kwargs):
            result = build(*args, **kwargs)
            with (self.run / retention.RAW).open("ab") as stream:
                stream.write(b"concurrent mutation")
            return result
        with patch.object(retention, "_essential", side_effect=changed):
            with self.assertRaises(ValueError):
                retention.compact(self.run)
        self.assertEqual((self.run / retention.RAW).read_bytes(), self.raw + b"concurrent mutation")
        self.assertFalse((self.run / retention.RECEIPT).exists())

    def test_false_backup_flag_and_wrong_parent_are_refused(self):
        with self.assertRaises(ValueError):
            retention.compact(self.run, keep_raw_backup=False)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        with self.assertRaises(ValueError):
            retention.compact(outside)
        self.intact_original()

    def test_unsafe_tar_names_links_and_duplicates_preserve_raw(self):
        for name, kind in (
                ("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                ("C:/windows", tarfile.REGTYPE), ("nested\\escape", tarfile.REGTYPE),
                ("link", tarfile.SYMTYPE), ("hard", tarfile.LNKTYPE),
                ("fifo", tarfile.FIFOTYPE), ("plot.tdr", tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                member = tarfile.TarInfo(name)
                member.type = kind
                member.size = 1 if kind == tarfile.REGTYPE else 0
                member.linkname = "../outside" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                self.make_archive(member)
                with self.assertRaises(ValueError):
                    retention.compact(self.run)
                self.intact_original()
                self.assertFalse((self.run / retention.RECEIPT).exists())

    def test_filesystem_symlink_is_refused(self):
        target = self.run / retention.RAW
        elsewhere = Path(self.temp.name) / "outside.tar"
        elsewhere.write_bytes(self.raw)
        target.unlink()
        try:
            target.symlink_to(elsewhere)
        except OSError as exc:
            target.write_bytes(self.raw)
            self.skipTest("Symlink privilege unavailable: %s" % exc)
        with self.assertRaises((OSError, ValueError)):
            retention.compact(self.run)
        self.assertEqual(elsewhere.read_bytes(), self.raw)

    def test_retired_raw_requires_real_hashed_and_bound_release(self):
        retention.compact(self.run)
        doc = self.receipt()
        doc["raw_backup_retired"] = True
        doc["raw_backup_release"] = dict(evidence_file="release.json", sha256="0" * 64)
        self.save_receipt(doc)
        self.assertFalse(retention.verify_retained(self.run, self.manifest))
        proof = {k: doc[k] for k in ("run_id", "manifest_sha256", "original_archive_sha256")}
        proof.update(scientific_review_complete=True, release_original_archive=False)
        raw = json.dumps(proof).encode("utf-8")
        (self.run / "release.json").write_bytes(raw)
        doc["raw_backup_release"]["sha256"] = sha(raw)
        self.save_receipt(doc)
        self.assertFalse(retention.verify_retained(self.run, self.manifest))
        proof["release_original_archive"] = True
        raw = json.dumps(proof).encode("utf-8")
        (self.run / "release.json").write_bytes(raw)
        doc["raw_backup_release"]["sha256"] = sha(raw)
        self.save_receipt(doc)
        # Finalizer's required order: verify flag/proof while gzip still exists.
        self.assertTrue(retention.verify_retained(self.run, self.manifest))
        (self.run / retention.RAW_GZ).unlink()
        self.assertTrue(retention.verify_retained(self.run, self.manifest))
        proof["run_id"] = "forged-other-run"
        raw = json.dumps(proof).encode("utf-8")
        (self.run / "release.json").write_bytes(raw)
        doc["raw_backup_release"]["sha256"] = sha(raw)
        self.save_receipt(doc)
        self.assertFalse(retention.verify_retained(self.run, self.manifest))
        doc["raw_backup_release"]["evidence_file"] = "../outside.json"
        self.save_receipt(doc)
        self.assertFalse(retention.verify_retained(self.run, self.manifest))

    def test_cli_compact_verify_restore(self):
        script = HERE / "retention.py"
        for action in ("compact", "verify", "restore", "dematerialize"):
            cp = subprocess.run([sys.executable, "-B", str(script), action, str(self.run)],
                                capture_output=True, encoding="utf-8", check=False)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            json.loads(cp.stdout)
        self.assertFalse((self.run / retention.RAW).exists())
        self.assertTrue((self.run / retention.RAW_GZ).exists())


if __name__ == "__main__":
    unittest.main()
