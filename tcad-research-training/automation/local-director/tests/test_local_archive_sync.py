"""Offline archive fixtures; every run and destination is temporary."""

import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "local_archive_sync.py"
SPEC = importlib.util.spec_from_file_location("local_archive_tested", SCRIPT)
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)
ret = archive.ret


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class LocalArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.run = root / "runtime" / "runs" / "opaque-id"
        self.run.mkdir(parents=True)
        self.dev, self.sealed = root / "dev", root / "sealed"
        self.dev.mkdir()
        self.sealed.mkdir()
        self.ledger = root / "runtime.json"
        self.plan = root / "frozen.json"
        self.args = dict(runtime_state=self.ledger, case_manifest=self.plan,
                         development_root=self.dev, sealed_root=self.sealed)
        payload = b"test numerical output"
        with tarfile.open(self.run / ret.RAW, "w") as stream:
            member = tarfile.TarInfo("sample.plt")
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
        raw_file = self.run / ret.RAW
        self.raw = raw_file.read_bytes()
        self.manifest = dict(run_id=self.run.name, state="COLLECTED", remote_exit_code=0,
                             collection_verified=True, parallel_slot_released=True,
                             results_sha256=ret._sha(raw_file), input_sha256={"project.json": "a" * 64},
                             private_path="private-location-marker")
        save(self.run / "manifest.json", self.manifest)
        self.doc = {key: value for key, value in ret.compact(self.run).items()
                    if key not in ("action", "results_tar_removed")}
        self.guest = dict(schema="tcad-result-guest-reclaim-v1", run_id=self.run.name,
                          original_archive_sha256=self.manifest["results_sha256"], removed=[], removed_bytes=0)
        save(self.run / ret.GUEST_RECEIPT, self.guest)
        self.identity()

    def identity(self, *, block="S", partition="development", role="development", scope=None, holdout=None):
        case = dict(case_id="fixed-case", profile_id="profile", radiation_id=None if block == "Z" else "beam",
                    block=block, stored_bit=1, holdout=holdout)
        save(self.plan, dict(plan_id="dram-se-ddr5-lpddr5", revision="r0.6", cases=[case],
                             profiles=[dict(id="profile", partition=partition)],
                             radiations=[dict(id="beam", role=role)]))
        sealed = block in ("HR", "HP") or role == "radiation_holdout" or partition == "profile_holdout"
        save(self.ledger, dict(schema="tcad-autonomy-intents-v1", intents={"unchanged-task": dict(
            run_id=self.run.name, backend="tcad", input_sha256=self.manifest["input_sha256"],
            scientific_admission=dict(case_id=case["case_id"], manifest_sha256=ret._sha(self.plan),
                                      scope=scope or ("holdout_evaluation" if sealed else "development_production"),
                                      scientific_object=case))}))

    def test_cli_mirrors_complete_bundle_and_retry_is_idempotent(self):
        summary_dir = self.run.parent.parent / "state"
        command = [sys.executable, "-B", str(SCRIPT), "mirror", str(self.run),
                   "--state-dir", str(summary_dir)]
        for name, path in self.args.items():
            command.extend(("--" + name.replace("_", "-"), str(path)))
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        cli_result = json.loads(result.stdout)
        self.assertEqual(cli_result["mirrored"], 1)
        self.assertIs(cli_result["verified"], True)
        mirror = self.dev / "runs" / self.run.name
        proof = ret.mirror_snapshot(mirror)
        self.assertEqual(proof["schema"], ret.MIRROR_SCHEMA)
        self.assertEqual(proof["partition"], "development")
        receipt = (mirror / ret.MIRROR_RECEIPT).read_bytes()
        for private in (self.run.name, "private-location-marker", "fixed-case", str(self.dev)):
            self.assertNotIn(private, receipt.decode("ascii"))
        rerun = archive.mirror_run(self.run, state_dir=summary_dir, **self.args)
        self.assertEqual(rerun, cli_result)
        self.assertEqual((mirror / ret.MIRROR_RECEIPT).read_bytes(), receipt)
        self.assertEqual(gzip.decompress((mirror / ret.RAW_GZ).read_bytes()), self.raw)
        self.assertTrue((self.run / ret.RAW_GZ).exists())

        self.assertEqual(rerun["summary"]["mirrored"], 1)
        self.assertEqual(rerun["summary"]["cloud_verified"], 0)
        self.assertEqual(set(json.loads((summary_dir / "archive-summary.json").read_text())),
                         {"schema", "mirrored", "cloud_verified"})
        index = json.loads((summary_dir / "archive-index.json").read_text())
        self.assertEqual(len(index["receipts"]), 1)
        (mirror / ret.MIRROR_RECEIPT).write_bytes(receipt + b" ")
        with self.assertRaisesRegex(ValueError, "Conflicting archive receipt"):
            archive.mirror_run(self.run, state_dir=summary_dir, **self.args)

    def test_sealed_identity_uses_only_privileged_root(self):
        for block, partition, role in (("HR", "development", "radiation_holdout"),
                                       ("HP", "profile_holdout", "development"),
                                       ("Z", "profile_holdout", "development")):
            with self.subTest(block=block):
                self.identity(block=block, partition=partition, role=role)
                with self.assertRaises(ValueError):
                    archive.mirror_run(self.run, **self.args)
        archive.mirror_run(self.run, allow_sealed=True, **self.args)
        self.assertEqual(list(self.dev.iterdir()), [])
        self.assertEqual(ret.mirror_snapshot(self.sealed / "runs" / self.run.name)["partition"], "sealed")

    def test_unknown_mismatched_or_unpinned_identity_refuses(self):
        for kw in ({"partition": "unknown"}, {"block": "HR", "scope": "development_production"}):
            with self.subTest(kw=kw):
                self.identity(**kw)
                with self.assertRaises(ValueError):
                    archive.mirror_run(self.run, **self.args)
        self.identity()
        self.plan.write_bytes(self.plan.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            archive.mirror_run(self.run, **self.args)
        self.assertEqual(list(self.dev.iterdir()), [])

    def test_missing_evidence_tampered_file_and_wrong_gzip_never_publish(self):
        raw = self.run / ret.RAW_GZ
        before = raw.read_bytes()
        guest = self.run / ret.GUEST_RECEIPT
        guest.unlink()
        with self.assertRaises(OSError):
            archive.mirror_run(self.run, **self.args)
        save(guest, dict(self.guest, run_id="other-run"))
        with self.assertRaises(ValueError):
            archive.mirror_run(self.run, **self.args)
        save(guest, self.guest)
        witness = self.run / ret.WITNESS
        witness_bytes = witness.read_bytes()
        witness.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            archive.mirror_run(self.run, **self.args)
        self.assertEqual(raw.read_bytes(), before)
        witness.write_bytes(witness_bytes)
        for data in (b"not a gzip", gzip.compress(b"wrong original")):
            raw.write_bytes(data)
            self.doc["artifacts"][ret.RAW_GZ] = ret._file_record(raw)
            save(self.run / ret.RECEIPT, self.doc)
            with self.assertRaises(ValueError):
                archive.mirror_run(self.run, **self.args)
            self.assertEqual(raw.read_bytes(), data)
        self.assertFalse((self.dev / "runs").exists())

    def test_failed_publication_keeps_original_and_cleans_staging(self):
        before = {path.name: path.read_bytes() for path in self.run.iterdir()}
        with patch.object(Path, "rename", side_effect=OSError("injected publish failure")):
            with self.assertRaises(OSError):
                archive.mirror_run(self.run, **self.args)
        self.assertEqual({path.name: path.read_bytes() for path in self.run.iterdir()}, before)
        self.assertEqual(list(self.dev.iterdir()), [])

    def test_pull_verify_reads_local_remote_root_without_mutating_source(self):
        remote = self.run.parent.parent / "remote"
        source = remote / "runs" / self.run.name
        source.mkdir(parents=True)
        for name in ret.mirror_inventory(self.doc):
            ret._copy_file(self.run / name, source / name)
        before = {path.name: path.read_bytes() for path in source.iterdir()}
        result = archive.pull_verify(remote, self.run.name, **self.args)
        self.assertIs(result["verified"], True)
        self.assertEqual(result["mirrored"], 1)
        self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)
        self.assertTrue((self.dev / "runs" / self.run.name / ret.MIRROR_RECEIPT).is_file())

    def test_pull_verify_rejects_bad_gzip_and_keeps_source_and_archive_empty(self):
        remote = self.run.parent.parent / "remote"
        source = remote / "runs" / self.run.name
        source.mkdir(parents=True)
        for name in ret.mirror_inventory(self.doc):
            ret._copy_file(self.run / name, source / name)
        raw_gz = source / ret.RAW_GZ
        raw_gz.write_bytes(b"not gzip")
        self.doc["artifacts"][ret.RAW_GZ] = ret._file_record(raw_gz)
        save(source / ret.RECEIPT, self.doc)
        before = {path.name: path.read_bytes() for path in source.iterdir()}
        with self.assertRaisesRegex(ValueError, "Unreadable raw gzip"):
            archive.pull_verify(remote, self.run.name, **self.args)
        self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)
        self.assertEqual(list(self.dev.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
