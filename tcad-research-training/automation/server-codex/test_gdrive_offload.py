"""Offline tests for optional Google Drive cold-archive offload, restore, and local fallback."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error


HERE = Path(__file__).resolve().parent


def load_mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


retention = load_mod("retention_gdrive_tested", "retention.py")
maintenance = load_mod("maintenance_gdrive_tested", "result_maintenance.py")
gdrive_offload = load_mod("gdrive_offload_tested", "gdrive_offload.py")
runtime = load_mod("runtime_gdrive_tested", "runtime.py")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_retained_run(root, run_id="run-gd-1"):
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    raw = run / "results.tar"
    payload = b"hello tcad simulation output\n" * 64
    with tarfile.open(raw, "w") as archive:
        info = tarfile.TarInfo("access_device.plt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        log_data = b"R04_QY_CALLBACK n=1 region=r time=1 dt=1 type=1 x=0 y=0 z=0 G=1 eta=1\n" * 300000
        linfo = tarfile.TarInfo("transient_des.log")
        linfo.size = len(log_data)
        archive.addfile(linfo, io.BytesIO(log_data))
    raw_bytes = raw.read_bytes()
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    manifest = {
        "run_id": run_id,
        "state": "COLLECTED",
        "remote_exit_code": 0,
        "collection_verified": True,
        "parallel_slot_released": True,
        "results_sha256": raw_sha,
        "collected_bytes": len(raw_bytes),
    }
    write_json(run / "manifest.json", manifest)
    retention.compact(run)
    write_json(run / "guest-reclaim.json", {"schema": "tcad-result-guest-reclaim-v1", "run_id": run_id})
    return run, manifest, raw_bytes


class GDriveOffloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run_dir, self.manifest, self.raw_bytes = make_retained_run(self.root)
        self.cfg_path = self.root / "gdrive-config.json"
        self.token_path = self.root / "oauth.json"
        write_json(self.token_path, {
            "client_id": "cid", "client_secret": "csec", "refresh_token": "rtok",
        })
        write_json(self.cfg_path, {
            "enabled": True,
            "delete_local_raw": False,
            "folder_id": "parent-folder-1",
            "token_file": str(self.token_path),
        })

    def test_mirror_offload_keeps_local_raw_and_passes_verify(self):
        cloud = {}

        def fake_uploader(run_dir, names, config_path=None):
            uploaded = {}
            for name in names:
                data = (Path(run_dir) / name).read_bytes()
                fid = f"file-{name}"
                cloud[fid] = data
                uploaded[name] = {
                    "drive_file_id": fid,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "md5": hashlib.md5(data).hexdigest(),
                }
            return {
                "drive_parent_folder_id": "parent-folder-1",
                "drive_folder_id": "sub-1",
                "uploaded": uploaded,
            }

        res = maintenance.offload(self.run_dir, config_path=self.cfg_path, delete_local_raw=False, uploader=fake_uploader)
        self.assertEqual(res["state"], "BACKED_UP")
        self.assertFalse(res["local_raw_deleted"])
        self.assertTrue((self.run_dir / "results.raw.tar.gz").is_file())
        self.assertTrue((self.run_dir / "gdrive-offload.json").is_file())
        self.assertTrue(retention.verify_retained(self.run_dir, self.manifest))

    def test_cold_offload_deletes_local_raw_and_transparently_restores_and_rehydrates(self):
        cloud = {}

        def fake_uploader(run_dir, names, config_path=None):
            uploaded = {}
            for name in names:
                data = (Path(run_dir) / name).read_bytes()
                fid = f"fid-{name}"
                cloud[fid] = data
                uploaded[name] = {
                    "drive_file_id": fid,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "md5": hashlib.md5(data).hexdigest(),
                }
            return {
                "drive_parent_folder_id": "parent-folder-1",
                "drive_folder_id": "sub-1",
                "uploaded": uploaded,
            }

        res = maintenance.offload(self.run_dir, config_path=self.cfg_path, delete_local_raw=True, uploader=fake_uploader)
        self.assertEqual(res["state"], "OFFLOADED")
        self.assertTrue(res["local_raw_deleted"])
        self.assertFalse((self.run_dir / "results.raw.tar.gz").exists())
        self.assertTrue(retention.verify_retained(self.run_dir, self.manifest))

        def fake_fetcher(run, doc, dest_path):
            proof = json.loads((Path(run) / doc["raw_backup_offload"]["evidence_file"]).read_text(encoding="utf-8"))
            Path(dest_path).write_bytes(cloud[proof["drive_file_id"]])

        restored = retention.restore(self.run_dir, fetcher=fake_fetcher)
        self.assertTrue(restored["restored"])
        self.assertTrue(restored["fetched_from_offload"])
        self.assertEqual((self.run_dir / "results.tar").read_bytes(), self.raw_bytes)
        retention.dematerialize(self.run_dir)
        self.assertFalse((self.run_dir / "results.tar").exists())

        # Rehydrate permanently back to pure local retention
        rehydrated = maintenance.rehydrate(self.run_dir, fetcher=fake_fetcher)
        self.assertTrue(rehydrated["pulled"])
        self.assertFalse(rehydrated["raw_backup_offloaded"])
        self.assertTrue((self.run_dir / "results.raw.tar.gz").is_file())
        self.assertTrue(retention.verify_retained(self.run_dir, self.manifest))

    def test_upload_failure_or_disabled_falls_back_to_local_without_touching_backup(self):
        raw_gz_before = (self.run_dir / "results.raw.tar.gz").read_bytes()
        retention_before = (self.run_dir / "retention.json").read_text(encoding="utf-8")

        def broken_uploader(*args, **kwargs):
            raise OSError("Google Drive unreachable")

        res = maintenance.offload(self.run_dir, config_path=self.cfg_path, delete_local_raw=True, uploader=broken_uploader)
        self.assertEqual(res["state"], "FAILED_FALLBACK_LOCAL")
        self.assertTrue(res["fallback_to_local"])
        self.assertGreater(res["retry_after"], time.time())
        self.assertEqual((self.run_dir / "results.raw.tar.gz").read_bytes(), raw_gz_before)
        self.assertEqual((self.run_dir / "retention.json").read_text(encoding="utf-8"), retention_before)
        self.assertTrue(retention.verify_retained(self.run_dir, self.manifest))

        write_json(self.cfg_path, {"enabled": False})
        res2 = maintenance.offload(self.run_dir, config_path=self.cfg_path, delete_local_raw=True)
        self.assertEqual(res2["state"], "DISABLED_FALLBACK_LOCAL")
        self.assertTrue(res2["fallback_to_local"])

    def test_resumable_oauth_upload_and_download_with_chunked_308(self):
        store = {"files": {}, "folders": {}}
        state = {"put_calls": 0}

        class FakeResp:
            def __init__(self, body=b"", headers=None):
                self._bio = io.BytesIO(body)
                self.headers = headers or {}

            def read(self, n=-1):
                return self._bio.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def open(self, req, timeout=120):
                url = req.full_url
                method = req.get_method()
                if "oauth2.googleapis.com/token" in url:
                    return FakeResp(json.dumps({"access_token": "tok-1"}).encode())
                if url.startswith(gdrive_offload.DRIVE_FILES_URL) and method == "GET" and "alt=media" not in url:
                    return FakeResp(json.dumps({"files": []}).encode())
                if url.startswith(gdrive_offload.DRIVE_FILES_URL) and method == "POST":
                    return FakeResp(json.dumps({"id": "folder-xyz", "name": self.run_name if hasattr(self, "run_name") else "sub"}).encode())
                if url.startswith(gdrive_offload.DRIVE_UPLOAD_URL) and method == "POST":
                    return FakeResp(b"", headers={"Location": "https://upload.example/session-1"})
                if url == "https://upload.example/session-1" and method == "PUT":
                    state["put_calls"] += 1
                    cr = req.headers.get("Content-range") or req.headers.get("Content-Range") or ""
                    buf = store["files"].setdefault("fid-blob", bytearray())
                    buf.extend(req.data or b"")
                    total = int(cr.split("/")[-1]) if "/" in cr else len(buf)
                    if len(buf) < total:
                        raise urllib.error.HTTPError(url, 308, "Resume Incomplete", {}, None)
                    data = bytes(buf)
                    meta = {
                        "id": "fid-blob",
                        "name": "results.raw.tar.gz",
                        "size": str(len(data)),
                        "md5Checksum": hashlib.md5(data).hexdigest(),
                    }
                    return FakeResp(json.dumps(meta).encode())
                if "alt=media" in url:
                    return FakeResp(bytes(store["files"]["fid-blob"]))
                raise AssertionError(f"Unexpected request: {method} {url}")

        with patch.object(gdrive_offload, "_build_opener", return_value=FakeOpener()), \
                patch.object(gdrive_offload, "CHUNK_SIZE", 64 * 1024):
            up = gdrive_offload.upload_run_artifacts(self.run_dir, ["results.raw.tar.gz"], config_path=self.cfg_path)
            self.assertGreaterEqual(state["put_calls"], 1)
            fid = up["uploaded"]["results.raw.tar.gz"]["drive_file_id"]
            dl_target = self.root / "downloaded.tar.gz"
            dl = gdrive_offload.download_file(
                fid, dl_target,
                expected_sha256=up["uploaded"]["results.raw.tar.gz"]["sha256"],
                expected_bytes=up["uploaded"]["results.raw.tar.gz"]["size"],
                config_path=self.cfg_path,
            )
            self.assertEqual(dl["sha256"], up["uploaded"]["results.raw.tar.gz"]["sha256"])

    def test_runtime_offload_worker_is_nonblocking_and_respects_rollback_flag(self):
        workspace = self.root / "ws"
        state_dir = self.root / "state"
        queue = workspace / "queue.json"
        ready = workspace / "ready.json"
        conn = workspace / "local_runtime/cloud-benchmark/conn.json"
        run_root = workspace / "local_runtime/cloud-benchmark/guest"
        run_dir = run_root / "runs/run-1"
        run_dir.mkdir(parents=True)
        (workspace / "local_runtime/cloud-benchmark").mkdir(parents=True, exist_ok=True)
        write_json(conn, {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/local/bin/tcad-runtime",
            "remote_root": "/home/tcad/research-training",
            "local_state_root": str(run_root),
            "parallel_capacity": 3,
        })
        write_json(queue, {"schema": "tcad-work-items-v1", "tasks": []})
        write_json(ready, {"new_jobs_authorized": False, "connection": str(conn)})
        write_json(run_dir / "manifest.json", {
            "run_id": "run-1", "state": "COLLECTED", "remote_exit_code": 0,
            "collection_verified": True, "parallel_slot_released": True,
            "results_sha256": "b" * 64,
        })
        (run_dir / "retention.json").write_text("{}", encoding="utf-8")
        (run_dir / "guest-reclaim.json").write_text("{}", encoding="utf-8")
        (run_dir / "results.raw.tar.gz").write_bytes(b"gz")

        policy = {
            "workspace": str(workspace),
            "state_dir": str(state_dir),
            "queue_file": str(queue),
            "runner_python": "python",
            "max_parallel_jobs": 3,
            "result_gdrive_offload_enabled": False,
        }
        state_dir.mkdir(parents=True)
        rt = runtime.Runtime(policy, json.loads(ready.read_text()))
        rt._profile()
        rt.intents["t1"] = {"backend": "tcad", "run_id": "run-1"}
        views = {"t1": {"backend": "tcad", "collected": True, "success": True}}

        with patch.object(runtime.subprocess, "Popen") as popen:
            rt._offload_results(views)
            popen.assert_not_called()

        rt.policy["result_gdrive_offload_enabled"] = True
        rt.policy["result_gdrive_delete_local_raw"] = True

        class DummyProc:
            def poll(self):
                return 0

        with patch.object(runtime.subprocess, "Popen", return_value=DummyProc()) as popen:
            rt._offload_results(views)
            popen.assert_called_once()
            argv = popen.call_args[0][0]
            self.assertIn("offload", argv)
            self.assertIn("--delete-local-raw", argv)

        # Even if Popen raises, runtime never pauses or crashes.
        rt._offload_process = None
        rt._offload_retry_at = 0
        with patch.object(runtime.subprocess, "Popen", side_effect=OSError("spawn error")):
            rt._offload_results(views)
        self.assertGreater(rt._offload_retry_at, time.time())


if __name__ == "__main__":
    unittest.main()
