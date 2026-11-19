"""Storage maintenance for consumed results; never submits or collects a run."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


def retention():
    source = Path(__file__).with_name("retention.py")
    spec = importlib.util.spec_from_file_location("_result_retention_worker", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gdrive():
    source = Path(__file__).with_name("gdrive_offload.py")
    spec = importlib.util.spec_from_file_location("_result_gdrive_offload_worker", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def readj(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 64 * 1024**2:
        raise ValueError("Unsafe or oversized metadata")
    return json.loads(path.read_text(encoding="utf-8"))


def writej(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def context(folder):
    folder = Path(folder).absolute()
    if folder.resolve() != folder or folder.parent.name != "runs":
        raise ValueError("Expected an original, nonsymlink run directory")
    manifest = readj(folder / "manifest.json")
    if (manifest.get("run_id") != folder.name or manifest.get("state") != "COLLECTED"
            or manifest.get("remote_exit_code") != 0
            or manifest.get("collection_verified") is not True
            or manifest.get("parallel_slot_released") is not True):
        raise ValueError("Only successful, verified and released original runs qualify")
    return folder, manifest


@contextmanager
def transaction(folder, blocking=True):
    """Serialize the whole storage/read transaction, outside inner file locks."""
    path = Path(folder) / ".retention-transaction.lock"
    if path.is_symlink():
        raise ValueError("Unsafe transaction lock")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as stream:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"\0")
            stream.seek(0)
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(stream.fileno(), mode, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def ready(folder, evidence):
    folder, manifest = context(folder)
    evidence = Path(evidence).resolve()
    result = readj(evidence)
    proof = result.get("provenance", {})
    if (result.get("synthetic") is not False or proof.get("run_id") != manifest["run_id"]
            or proof.get("manifest_sha256") != sha(folder / "manifest.json")
            or proof.get("archive_sha256") != manifest["results_sha256"]):
        raise ValueError("Key numerical evidence does not bind this original result")
    cache_receipt = evidence.with_name("receipt.json")
    receipt = readj(cache_receipt)
    if receipt.get("extraction_sha256") != sha(evidence):
        raise ValueError("Derived cache receipt differs")
    marker = {
        "schema": "tcad-result-retention-ready-v1",
        "run_id": manifest["run_id"], "manifest_sha256": sha(folder / "manifest.json"),
        "original_archive_sha256": manifest["results_sha256"],
        "is_scientific_acceptance": False,
        "evidence": [{"path": str(path), "sha256": sha(path)}
                     for path in (evidence, cache_receipt)],
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    if (folder / "retention-ready.json").exists():
        old = readj(folder / "retention-ready.json")
        if {k: v for k, v in old.items() if k != "utc"} != {k: v for k, v in marker.items() if k != "utc"}:
            raise ValueError("A different storage handoff already exists")
        return old
    writej(folder / "retention-ready.json", marker)
    return marker


GUEST_RECLAIM = r'''
import datetime,hashlib,json,os,pathlib
request=REQUEST
os.nice(10)
if hasattr(os,"sched_setaffinity") and os.cpu_count()>8:os.sched_setaffinity(0,{8})
root=pathlib.Path(request["remote_root"])/"runs"
folder=root/request["run_id"]
assert folder.resolve()==folder and root.resolve()==root
assert request["remote_directory"]==str(folder)
assert (folder/"exit-code.txt").read_bytes().strip()==b"0"
receipt=folder/".collection/receipt.json"
assert receipt.is_file() and not receipt.is_symlink()
proof=json.loads(receipt.read_text())
assert proof["sha256"]==request["original_archive_sha256"]
for proc in pathlib.Path("/proc").iterdir():
 if not proc.name.isdigit():continue
 try:cwd=(proc/"cwd").resolve()
 except (OSError,RuntimeError):continue
 assert cwd!=folder and folder not in cwd.parents,("Completed directory has a live process",proc.name)
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as stream:
  for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
 return h.hexdigest()
def signature(path):
 s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
plans=[]
for item in request["files"]:
 target=folder/item["name"]
 assert target.resolve()==target and folder in target.parents and not target.is_symlink()
 if not target.exists():continue
 before=signature(target)
 assert before[2]==item["size"] and digest(target)==item["sha256"]
 assert before==signature(target)
 plans.append(dict(item,path=str(target),signature=before))
# All candidates are verified before the first removal. No input, numerical,
# field snapshot, identity, receipt, lock or running directory is removed.
for plan in plans:
 target=pathlib.Path(plan["path"])
 assert signature(target)==plan["signature"]
 target.unlink()
result={"schema":"tcad-result-guest-reclaim-v1","run_id":request["run_id"],
 "original_archive_sha256":request["original_archive_sha256"],
 "removed_bytes":sum(p["size"] for p in plans),"removed":plans,
 "utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
print(json.dumps(result))
'''


def reclaim_guest(folder, manifest, connection, module):
    if not module.verify_retained(folder, manifest):
        raise ValueError("Retained host result failed verification")
    cfg = readj(connection)
    alias = str(cfg.get("ssh_target", ""))
    if (cfg.get("backend") != "ssh-runtime" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", alias)
            or alias.lower() in {"hk", "hk-tail", "hk-live", "sub2"}
            or re.fullmatch(r"[\d.]+", alias)):
        raise ValueError("Use the original explicit TCAD guest SSH alias")
    if Path(cfg["local_state_root"]).resolve() != folder.parent.parent:
        raise ValueError("Connection belongs to a different original state root")
    policy = readj(folder / "retention.json")
    files = [{"name": row["name"], "size": row["size"], "sha256": row["sha256"]}
             for row in policy["original_members"] if row.get("policy") == "projected_log"]
    files.append({"name": ".collection/results.tar", "size": manifest["collected_bytes"],
                  "sha256": manifest["results_sha256"]})
    request = {"run_id": manifest["run_id"], "remote_root": cfg["remote_root"],
               "remote_directory": manifest["remote_directory"],
               "original_archive_sha256": manifest["results_sha256"], "files": files}
    code = GUEST_RECLAIM.replace("REQUEST", repr(request), 1)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", alias, "python3", "-"],
        input=code.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if proc.returncode:
        raise ValueError("Guest reclaim refused: " + proc.stderr.decode(errors="replace")[-4000:])
    result = json.loads(proc.stdout)
    if result.get("run_id") != manifest["run_id"]:
        raise ValueError("Guest reclaim returned a different run")
    writej(folder / "guest-reclaim.json", result)
    return result


def _maintain(folder, connection):
    folder, manifest = context(folder)
    marker = readj(folder / "retention-ready.json")
    if (marker.get("schema") != "tcad-result-retention-ready-v1"
            or marker.get("run_id") != manifest["run_id"]
            or marker.get("manifest_sha256") != sha(folder / "manifest.json")
            or marker.get("original_archive_sha256") != manifest["results_sha256"]):
        raise ValueError("Storage handoff changed")
    # Freeze small derived numerical evidence next to the retained result.
    copied = []
    for index, evidence in enumerate(marker["evidence"]):
        source = Path(evidence["path"])
        if sha(source) != evidence["sha256"]:
            raise ValueError("Consumed key evidence changed")
        target = folder / ("key-extraction.json" if index == 0 else "key-cache-receipt.json")
        if target.is_symlink():
            raise ValueError("Unsafe key evidence target")
        if target.exists() and sha(target) != evidence["sha256"]:
            raise ValueError("A different frozen key file exists")
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        copied.append(target)
    module = retention()
    result = module.compact(folder)
    record = readj(folder / "retention.json")
    before_record = json.loads(json.dumps(record))
    for path in copied:
        record["artifacts"][path.name] = {"sha256": sha(path), "bytes": path.stat().st_size}
    writej(folder / "retention.json", record)
    if not module.verify_retained(folder, manifest):
        writej(folder / "retention.json", before_record)
        raise ValueError("Retained evidence did not pass final verification")
    guest = (readj(folder / "guest-reclaim.json") if (folder / "guest-reclaim.json").is_file()
             else reclaim_guest(folder, manifest, connection, module))
    return {"run_id": manifest["run_id"], "retained": result, "guest": guest}


def maintain(folder, connection):
    folder, _ = context(folder)
    with transaction(folder, blocking=False):
        return _maintain(folder, connection)


def read_with_original(reader, args):
    """Restore exact original bytes around a frozen reader; its code stays fixed."""
    reader = Path(reader).resolve()
    if reader.name != "extract.py" or reader.parent.name != "multicore-response-reader-r1":
        raise ValueError("Only the existing frozen multicore result reader is supported")
    if not args or args[0] not in ("extract", "compare"):
        raise ValueError("Expected the original extract/compare arguments")
    if args[0] == "extract":
        folders = [Path(args[1])]
    else:
        folders = [Path(readj(Path(cache) / "extraction.json")["provenance"]["run_directory"])
                   for cache in args[1:3]]
    module = retention()
    restored = []
    folders = sorted({context(folder)[0] for folder in folders})
    with ExitStack() as locks:
        # Fixed order prevents paired event/zero readers deadlocking each other.
        for folder in folders:
            locks.enter_context(transaction(folder))
        try:
            for folder in folders:
                if not (folder / "results.tar").exists():
                    module.restore(folder)
                    restored.append(folder)
            return subprocess.run([sys.executable, "-B", str(reader), *args]).returncode
        finally:
            for folder in restored:
                module.dematerialize(folder)


def _finalize(folder, evidence):
    """Retire the lossless backup only after an explicit completed review."""
    folder, manifest = context(folder)
    module = retention()
    if not module.verify_retained(folder, manifest):
        raise ValueError("Retained result failed verification")
    proof = readj(evidence)
    if (proof.get("schema") != "tcad-result-retention-release-v1"
            or proof.get("run_id") != manifest["run_id"]
            or proof.get("manifest_sha256") != sha(folder / "manifest.json")
            or proof.get("original_archive_sha256") != manifest["results_sha256"]
            or proof.get("scientific_review_complete") is not True
            or proof.get("release_original_archive") is not True
            or not proof.get("key_evidence")):
        raise ValueError("A completed review and retained key evidence are required")
    record = readj(folder / "retention.json")
    before_record = json.loads(json.dumps(record))
    for item in proof["key_evidence"]:
        path = Path(item["path"]).resolve()
        if sha(path) != item["sha256"]:
            raise ValueError("Final review evidence changed")
        # The final, compact result keeps a copy, not just an external pointer.
        target = folder / ("review-" + item["sha256"][:16] + "-" + path.name)
        if target.exists() and sha(target) != item["sha256"]:
            raise ValueError("Conflicting review evidence")
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(path.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        record["artifacts"][target.name] = {"sha256": sha(target), "bytes": target.stat().st_size}
    release = folder / "raw-backup-release.json"
    if release.exists() and readj(release) != proof:
        raise ValueError("Conflicting archive release evidence")
    writej(release, proof)
    record["raw_backup_retired"] = True
    record["raw_backup_release"] = {"evidence_file": release.name, "sha256": sha(release)}
    writej(folder / "retention.json", record)
    if not module.verify_retained(folder, manifest):
        writej(folder / "retention.json", before_record)
        raise ValueError("Key-only preservation failed verification; backup kept")
    raw = folder / "results.tar"
    if raw.exists():
        module.dematerialize(folder)
    backup = folder / "results.raw.tar.gz"
    if backup.is_symlink():
        raise ValueError("Unsafe backup path")
    if backup.exists():
        backup.unlink()
    return {"run_id": manifest["run_id"], "key_data_only": True,
            "is_scientific_acceptance": False}


def finalize(folder, evidence):
    folder, _ = context(folder)
    with transaction(folder):
        return _finalize(folder, evidence)


def _record_offload_status(folder, state, error=None, extra=None):
    status_path = folder / "gdrive-offload-status.json"
    prev = {}
    if status_path.is_file() and not status_path.is_symlink():
        try:
            prev = readj(status_path)
        except (OSError, ValueError):
            prev = {}
    failures = 0 if state in ("BACKED_UP", "OFFLOADED", "DISABLED_FALLBACK_LOCAL") else int(prev.get("consecutive_failures") or 0) + 1
    doc = {
        "schema": "tcad-result-gdrive-status-v1",
        "run_id": folder.name,
        "state": state,
        "consecutive_failures": failures,
        "fallback_to_local": state != "OFFLOADED",
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        doc["error"] = str(error)[:1000]
        backoff = min(3600, 300 * (2 ** min(failures - 1, 3)))
        doc["retry_after"] = datetime.now(timezone.utc).timestamp() + backoff
    if extra:
        doc.update(extra)
    writej(status_path, doc)
    return doc


def offload(folder, config_path=None, delete_local_raw=None, uploader=None):
    """Upload retained raw backup & key metadata to Google Drive with local fallback.

    Never pauses tasks or deletes local files on any error.
    """
    folder, manifest = context(folder)
    ret = retention()
    gd = gdrive()
    try:
        cfg = gd.load_config(config_path)
    except (OSError, ValueError, TypeError) as exc:
        return _record_offload_status(folder, "FAILED_FALLBACK_LOCAL", error=exc)

    if cfg.get("enabled") is not True:
        return _record_offload_status(
            folder, "DISABLED_FALLBACK_LOCAL",
            extra={"reason": cfg.get("reason", "disabled_in_config")},
        )

    remove_local = cfg.get("delete_local_raw", False) is True if delete_local_raw is None else bool(delete_local_raw)
    with transaction(folder, blocking=False):
        if not ret.verify_retained(folder, manifest):
            raise ValueError("Retained result failed verification before Drive offload")
        record = readj(folder / "retention.json")
        if record.get("raw_backup_retired") is True:
            return {"run_id": manifest["run_id"], "state": "ALREADY_RETIRED", "fallback_to_local": False}
        raw_path = folder / "results.raw.tar.gz"
        if record.get("raw_backup_offloaded") is True and not raw_path.exists():
            return {"run_id": manifest["run_id"], "state": "ALREADY_OFFLOADED", "fallback_to_local": False}
        if not raw_path.is_file():
            raise ValueError("Missing results.raw.tar.gz for Drive offload")
        raw_entry = record["artifacts"]["results.raw.tar.gz"]
        expected_manifest_sha = sha(folder / "manifest.json")
        upload_names = ["results.raw.tar.gz", "retention.json", "manifest.json"]
        for optional_name in ("results.essential.tar.gz", "results.log-witness.jsonl.gz",
                              "key-extraction.json", "key-cache-receipt.json"):
            if (folder / optional_name).is_file():
                upload_names.append(optional_name)

    try:
        upload_fn = uploader or gd.upload_run_artifacts
        uploaded = upload_fn(folder, upload_names, config_path=config_path)
        raw_meta = uploaded["uploaded"]["results.raw.tar.gz"]
        if raw_meta["sha256"] != raw_entry["sha256"] or int(raw_meta["size"]) != int(raw_entry["bytes"]):
            raise ValueError("Uploaded Drive raw backup SHA/size differs from retention.json")
    except Exception as exc:
        return _record_offload_status(folder, "FAILED_FALLBACK_LOCAL", error=exc)

    with transaction(folder, blocking=False):
        folder, current_manifest = context(folder)
        if sha(folder / "manifest.json") != expected_manifest_sha:
            return _record_offload_status(folder, "FAILED_FALLBACK_LOCAL", error="Manifest changed during upload")
        record = readj(folder / "retention.json")
        if record.get("raw_backup_retired") is True:
            return {"run_id": manifest["run_id"], "state": "ALREADY_RETIRED", "fallback_to_local": False}
        if not ret.verify_retained(folder, current_manifest):
            return _record_offload_status(folder, "FAILED_FALLBACK_LOCAL", error="Local retention changed during upload")

        state = "OFFLOADED" if remove_local else "BACKED_UP"
        proof = {
            "schema": gd.OFFLOAD_SCHEMA,
            "run_id": current_manifest["run_id"],
            "manifest_sha256": expected_manifest_sha,
            "original_archive_sha256": current_manifest["results_sha256"],
            "raw_backup_sha256": raw_entry["sha256"],
            "raw_backup_bytes": raw_entry["bytes"],
            "raw_backup_md5": raw_meta["md5"],
            "drive_parent_folder_id": uploaded["drive_parent_folder_id"],
            "drive_folder_id": uploaded["drive_folder_id"],
            "drive_file_id": raw_meta["drive_file_id"],
            "artifacts": uploaded["uploaded"],
            "verified": True,
            "state": state,
            "local_raw_deleted": False,
            "utc": datetime.now(timezone.utc).isoformat(),
        }
        proof_path = folder / gd.OFFLOAD_RECEIPT
        writej(proof_path, proof)

        if remove_local:
            before_record = json.loads(json.dumps(record))
            record["raw_backup_offloaded"] = True
            record["raw_backup_offload"] = {"evidence_file": proof_path.name, "sha256": sha(proof_path)}
            writej(folder / "retention.json", record)
            if not ret.verify_retained(folder, current_manifest):
                writej(folder / "retention.json", before_record)
                return _record_offload_status(folder, "FAILED_FALLBACK_LOCAL",
                                             error="Offload receipt failed retention verification; local backup kept")
            raw_path = folder / "results.raw.tar.gz"
            if raw_path.is_symlink():
                writej(folder / "retention.json", before_record)
                raise ValueError("Unsafe backup path")
            if raw_path.exists():
                raw_path.unlink()
            proof["local_raw_deleted"] = True
            writej(proof_path, proof)
            before_record = json.loads(json.dumps(record))
            record["raw_backup_offload"] = {"evidence_file": proof_path.name, "sha256": sha(proof_path)}
            writej(folder / "retention.json", record)
            if not ret.verify_retained(folder, current_manifest):
                writej(folder / "retention.json", before_record)
                raise ValueError("Post-delete offload receipt verification failed")

        _record_offload_status(folder, state, extra={"drive_file_id": raw_meta["drive_file_id"]})
        return {"run_id": current_manifest["run_id"], "state": state,
                "drive_file_id": raw_meta["drive_file_id"],
                "local_raw_deleted": bool(proof["local_raw_deleted"]),
                "fallback_to_local": not remove_local}


def rehydrate(folder, config_path=None, fetcher=None):
    """Revert a Drive-offloaded run back to pure local retention."""
    folder, _ = context(folder)
    ret = retention()
    gd = gdrive()
    with transaction(folder):
        use_fetcher = fetcher
        if use_fetcher is None and config_path is not None:
            use_fetcher = lambda run, doc, dest: gd.fetch_backup_from_receipt(run, doc, dest, config_path=config_path)
        result = ret.rehydrate(folder, fetcher=use_fetcher)
        _record_offload_status(folder, "REHYDRATED_LOCAL", extra={"pulled": result["pulled"]})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    item = modes.add_parser("ready")
    item.add_argument("run")
    item.add_argument("--evidence", required=True)
    item = modes.add_parser("maintain")
    item.add_argument("run")
    item.add_argument("--connection", required=True)
    item = modes.add_parser("read")
    item.add_argument("reader")
    item.add_argument("reader_args", nargs=argparse.REMAINDER)
    item = modes.add_parser("finalize")
    item.add_argument("run")
    item.add_argument("--evidence", required=True)
    item = modes.add_parser("offload")
    item.add_argument("run")
    item.add_argument("--config")
    item.add_argument("--delete-local-raw", action="store_true", default=None)
    item.add_argument("--keep-local-raw", dest="delete_local_raw", action="store_false")
    item = modes.add_parser("rehydrate")
    item.add_argument("run")
    item.add_argument("--config")
    args = parser.parse_args()
    if hasattr(os, "nice"):
        os.nice(10)
    try:
        if args.mode == "read":
            return read_with_original(args.reader, args.reader_args)
        if args.mode == "ready":
            result = ready(args.run, args.evidence)
        elif args.mode == "finalize":
            result = finalize(args.run, args.evidence)
        elif args.mode == "offload":
            result = offload(args.run, config_path=args.config, delete_local_raw=args.delete_local_raw)
        elif args.mode == "rehydrate":
            result = rehydrate(args.run, config_path=args.config)
        else:
            result = maintain(args.run, args.connection)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
