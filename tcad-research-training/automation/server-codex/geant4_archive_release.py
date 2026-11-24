#!/usr/bin/env python3
"""Verify a Geant4 Drive backup and release only the two hot copies."""

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
from urllib.parse import quote, urlencode

import geant4_archive as archive
import gdrive_offload as drive


BACKUP_SCHEMA = "tcad-geant4-research-archive-backup-v1"
RAW_GZIP = "results.raw.tar.gz"
MEMBER_INDEX = "_collection-members.json"


def _object(raw, name):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {name}")
    return value


def _signature(info):
    if info is None:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _file_stat(path, missing_ok=False):
    return archive._path_stat(path, stat.S_ISREG, missing_ok=missing_ok)


def _unchanged(path, original):
    if _signature(_file_stat(path, missing_ok=True)) != _signature(original):
        raise ValueError(f"File changed during archive verification: {path}")


class _HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.sha256 = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size)
        self.sha256.update(data)
        return data


def _verify_tar(path, info, expected_sha, expected_bytes, index_bytes, steps):
    if info.st_size != expected_bytes:
        raise ValueError("Original results.tar size differs")
    seen = set()
    with archive._open_regular(path) as stream:
        reader = _HashingReader(stream)
        with tarfile.open(fileobj=reader, mode="r|", bufsize=archive.BLOCK) as source:
            for member in source:
                if member.name not in (archive.STEPS, MEMBER_INDEX):
                    continue
                if not member.isfile() or member.name in seen:
                    raise ValueError(f"Expected a unique regular tar member: {member.name}")
                seen.add(member.name)
                with source.extractfile(member) as payload:
                    if member.name == MEMBER_INDEX:
                        if member.size != len(index_bytes) or payload.read() != index_bytes:
                            raise ValueError("Collected source index differs from the original tar")
                    elif (member.size != steps["bytes"]
                          or hashlib.file_digest(payload, "sha256").hexdigest() != steps["sha256"]):
                        raise ValueError("Original tar steps.csv differs from the audited source index")
        # tarfile stops at the end marker. Include all remaining archive padding in the SHA.
        while reader.read(archive.BLOCK):
            pass
    if seen != {archive.STEPS, MEMBER_INDEX} or reader.sha256.hexdigest() != expected_sha:
        raise ValueError("Original results.tar digest or required member set differs")


def _verify_drive(file_id, folder_id, raw, config_path):
    cfg = drive.load_config(config_path)
    if cfg.get("enabled") is not True or cfg.get("mode") != "oauth":
        raise ValueError("An enabled Google Drive OAuth config is required")
    opener = drive._build_opener(cfg.get("proxy"))
    token = drive._refresh_access_token(cfg, opener)
    query = urlencode({
        "fields": "id,name,size,parents,md5Checksum,sha256Checksum,trashed",
        "supportsAllDrives": "true",
    })
    metadata = drive._request_json(
        opener, f"{drive.DRIVE_FILES_URL}/{quote(file_id, safe='')}?{query}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=int(cfg.get("timeout_seconds", drive.DEFAULT_TIMEOUT)),
    )
    if (not isinstance(metadata, dict)
            or metadata.get("id") != file_id or metadata.get("name") != RAW_GZIP
            or metadata.get("parents") != [folder_id] or metadata.get("trashed") is not False
            or str(metadata.get("size")) != str(raw["bytes"])
            or metadata.get("md5Checksum") != raw["md5"]
            or metadata.get("sha256Checksum") not in (None, "", raw["sha256"])):
        raise ValueError("Drive backup metadata differs from the research backup receipt")


def _require_closed(targets):
    if not targets:
        return
    if sys.platform != "linux":
        raise OSError("Checking open archive files requires Linux /proc")
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for fd in (process / "fd").iterdir():
                try:
                    info = fd.stat()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                path = targets.get((info.st_dev, info.st_ino))
                if path is not None:
                    raise ValueError(f"{path} is open by PID {process.name}")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise PermissionError(f"Cannot inspect open files for PID {process.name}") from exc


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_receipt(path, receipt, owner):
    fd, name = tempfile.mkstemp(prefix=".transport-archive-offload-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            info = os.fstat(stream.fileno())
            if (info.st_uid, info.st_gid) != (owner.st_uid, owner.st_gid):
                os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
            os.fchmod(stream.fileno(), owner.st_mode & 0o666)
            stream.write((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path)
    finally:
        pending.unlink()


def release(folder, backup_receipt, ledger_dir, *, config_path=None, commit=False):
    folder = archive._directory(folder)
    ledger_dir = archive._directory(ledger_dir)
    with archive.archive_lock(folder) if commit else nullcontext():
        return _release(folder, Path(backup_receipt), ledger_dir, config_path, commit)


def _release(folder, backup_path, ledger_dir, config_path, commit):
    operation_path = folder / archive.OPERATION
    receipt_path = folder / archive.RECEIPT
    collected = archive._directory(folder / "collected")
    audit_path = ledger_dir / "audit.json"
    deposition_path = ledger_dir / "event-deposition.json"
    index_path = collected / MEMBER_INDEX
    tar_path = folder / archive.ARCHIVE
    steps_path = collected / archive.STEPS
    evidence = {path: _file_stat(path) for path in (
        operation_path, backup_path, audit_path, deposition_path, index_path,
    )}
    hot = {path: _file_stat(path, missing_ok=True) for path in (tar_path, steps_path)}
    existing = _file_stat(receipt_path, missing_ok=True)
    if existing is None and any(info is None for info in hot.values()):
        raise ValueError("Missing hot file without an existing cold receipt")

    operation_bytes = operation_path.read_bytes()
    record = _object(operation_bytes, operation_path.name)
    operation_sha = hashlib.sha256(operation_bytes).hexdigest()
    archive_sha = record.get("archive_sha256")
    archive_bytes = record.get("collected_bytes")
    if (record.get("schema") != "dram-see-v4-transport-operation-v2"
            or record.get("origin") != "native_pipeline" or record.get("synthetic") is not False
            or record.get("label") != folder.name or record.get("parallel_slot_released") is not True
            or record.get("state") not in ("COLLECTED_PENDING_AUDIT", "COLLECTED")
            or record.get("collection_verified") is not True
            or not archive._matches(archive.SHA256, archive_sha)
            or not archive._positive_size(archive_bytes)
            or any(type(record.get(key)) is not int or record[key] != 0 for key in (
                "remote_exit_code", "operation_task_exit_code", "collection_exit_code",
            ))):
        raise ValueError("Expected a verified, released, successful original Geant4 operation")

    backup = _object(backup_path.read_bytes(), backup_path.name)
    ledger_sha = backup.get("event_deposition_sha256")
    if (backup.get("schema") != BACKUP_SCHEMA or backup.get("run_id") != folder.name
            or backup.get("operation_sha256") != operation_sha
            or backup.get("original_archive_sha256") != archive_sha
            or type(backup.get("original_archive_bytes")) is not int
            or backup["original_archive_bytes"] != archive_bytes
            or not archive._positive_size(backup.get("primary_count"))
            or not archive._matches(archive.SHA256, ledger_sha)):
        raise ValueError("Research backup receipt differs from the original operation")
    artifact = backup["drive_artifacts"][RAW_GZIP]
    file_id, folder_id = artifact["drive_file_id"], backup["drive_folder_id"]
    raw = {"file_id": file_id, "bytes": artifact["size"], "sha256": artifact["sha256"], "md5": artifact["md5"]}
    if (not archive._matches(archive.DRIVE_ID, file_id) or not archive._matches(archive.DRIVE_ID, folder_id)
            or not archive._positive_size(raw["bytes"]) or not archive._matches(archive.SHA256, raw["sha256"])
            or not archive._matches(archive.MD5, raw["md5"])):
        raise ValueError("Invalid research backup artifact identity")

    audit = _object(audit_path.read_bytes(), audit_path.name)
    steps_sha = audit["members"][archive.STEPS]
    if (audit["operation"]["sha256"] != operation_sha or audit.get("archive_sha256") != archive_sha
            or audit.get("transport_run_id") != folder.name or audit.get("event_deposition_sha256") != ledger_sha
            or not archive._matches(archive.SHA256, steps_sha)):
        raise ValueError("Research ledger differs from the original operation")
    with archive._open_regular(deposition_path) as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != ledger_sha:
            raise ValueError("event-deposition.json SHA-256 differs")
    index_bytes = index_path.read_bytes()
    indexed_steps = _object(index_bytes, MEMBER_INDEX)[archive.STEPS]
    steps_bytes = indexed_steps["size"]
    if (not archive._positive_size(steps_bytes) or steps_bytes > archive_bytes
            or indexed_steps["sha256"] != steps_sha):
        raise ValueError("steps.csv differs between the original source index and research ledger")
    steps = {"bytes": steps_bytes, "sha256": steps_sha}
    receipt = {
        "schema": archive.SCHEMA, "run_id": folder.name, "operation_sha256": operation_sha,
        "archive_sha256": archive_sha, "archive_bytes": archive_bytes, "raw": raw, "steps": steps,
        "primary_ledger_sha256": ledger_sha, "cloud_verified": True,
    }
    if existing is not None:
        old = _object(receipt_path.read_bytes(), receipt_path.name)
        if old != receipt or not archive.verify_cold(operation_path, record):
            raise ValueError("Existing cold receipt differs or does not verify")

    _verify_drive(file_id, folder_id, raw, config_path)
    if hot[tar_path] is not None:
        _verify_tar(tar_path, hot[tar_path], archive_sha, archive_bytes, index_bytes, steps)
    if hot[steps_path] is not None:
        with archive._open_regular(steps_path) as stream:
            if (hot[steps_path].st_size != steps_bytes
                    or hashlib.file_digest(stream, "sha256").hexdigest() != steps_sha):
                raise ValueError("Collected steps.csv size or SHA-256 differs")
    for path, info in (evidence | hot | {receipt_path: existing}).items():
        _unchanged(path, info)

    present = {path: info for path, info in hot.items() if info is not None}
    targets = {(info.st_dev, info.st_ino): path for path, info in present.items()}
    _require_closed(targets)
    deleted = []
    if commit:
        if existing is None:
            _publish_receipt(receipt_path, receipt, evidence[operation_path])
        _sync_directory(folder)
        if not archive.verify_cold(operation_path, record):
            raise ValueError("Cold receipt verification failed before release")
        receipt_stat = _file_stat(receipt_path)
        # Check again after publishing. For a retry, only the still-present files are candidates.
        _require_closed(targets)
        for path, info in present.items():
            archive._directory(path.parent)
            for source, source_info in evidence.items():
                _unchanged(source, source_info)
            _unchanged(receipt_path, receipt_stat)
            _unchanged(path, info)
            path.unlink()
            _sync_directory(path.parent)
            deleted.append(path.relative_to(folder).as_posix())

    return {
        "run_id": folder.name, "verified": True, "committed": commit,
        "reclaimable_bytes": sum(info.st_size for info in present.values()),
        "deleted": deleted,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation_dir", metavar="OP_DIR", type=Path)
    parser.add_argument("--backup-receipt", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path, metavar="LEDGER_DIR")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--commit", action="store_true", help="Publish the cold receipt and remove the verified hot files")
    args = parser.parse_args(argv)
    try:
        result = release(args.operation_dir, args.backup_receipt, args.ledger, config_path=args.config,
                         commit=args.commit)
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError) as exc:
        print(f"Geant4 archive release failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
