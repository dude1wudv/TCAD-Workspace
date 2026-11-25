#!/usr/bin/env python3
"""Back up one released Geant4 operation and its audited deposition ledger."""

import argparse
from contextlib import nullcontext
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zlib

import gdrive_offload as drive
import geant4_archive_release as release


archive = release.archive
require = archive._require
AUDIT = "audit.json"
DEPOSITION = "event-deposition.json"


def _ledger_counts(audit, data):
    events = json.loads(data)
    totals = audit["ledger_audit"]
    count, audited_zero = totals["primary_count"], totals["zero_si_ionizing_count"]
    require(archive._positive_size(count) and isinstance(events, list) and len(events) == count,
            "Deposition ledger does not contain the audited number of primaries")
    zero = 0
    for event_id, event in enumerate(events):
        energy = event["deposition_energy_eV"]
        require(event["event_id"] == str(event_id), f"Expected consecutive original primary {event_id}")
        require(type(energy) in (int, float) and math.isfinite(energy) and energy >= 0,
                f"Invalid Si deposition for primary {event_id}")
        zero += energy == 0
    require(type(audited_zero) is int and audited_zero == zero, "Ledger zero Si deposition count differs")
    return count, zero


def _check_archive(stream, size, expected_sha, target=None):
    digest = hashlib.sha256()
    count = 0
    for chunk in iter(lambda: stream.read(archive.BLOCK), b""):
        count += len(chunk)
        require(count <= size, "Archive exceeds original size")
        digest.update(chunk)
        if target is not None:
            target.write(chunk)
    require(count == size and digest.hexdigest() == expected_sha, "Original archive size or SHA-256 differs")


def _verify_uploaded(receipt, config):
    item = receipt["drive_artifacts"][release.RAW_GZIP]
    file_id, folder_id = item["drive_file_id"], receipt["drive_folder_id"]
    require(archive._matches(archive.DRIVE_ID, file_id) and archive._matches(archive.DRIVE_ID, folder_id)
            and archive._positive_size(item["size"]) and archive._matches(archive.SHA256, item["sha256"])
            and archive._matches(archive.MD5, item["md5"]), "Invalid Drive backup artifact identity")
    release._verify_drive(file_id, folder_id, {
        "file_id": file_id, "bytes": item["size"], "sha256": item["sha256"], "md5": item["md5"],
    }, config)


def _publish(path, receipt):
    fd, name = tempfile.mkstemp(prefix=".geant4-backup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(receipt, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)  # Atomic publication without replacing an existing receipt.
        if os.name == "posix":
            release._sync_directory(path.parent)
    finally:
        Path(name).unlink()


def backup(folder, ledger_dir, receipt_out, *, config_path=None, floor_gib=20):
    require(type(floor_gib) is int and floor_gib >= 0, "--floor-gib must be a nonnegative integer")
    folder, ledger_dir = archive._directory(folder), archive._directory(ledger_dir)
    out = Path(receipt_out)
    out = archive._directory(out.parent) / out.name
    require(out != folder / archive.RECEIPT, "Use a separate path for the research backup receipt")
    with archive.archive_lock(folder) if os.name == "posix" else nullcontext():
        return _backup(folder, ledger_dir, out, config_path, floor_gib * 1024**3)


def _backup(folder, ledger_dir, out, config, reserve):
    op, audit_path, ledger_path = folder / archive.OPERATION, ledger_dir / AUDIT, ledger_dir / DEPOSITION
    evidence = {path: release._file_stat(path) for path in (op, audit_path, ledger_path)}
    record, op_bytes = archive._read_json(op)
    size, sha = record.get("collected_bytes"), record.get("archive_sha256")
    require(record.get("schema") == "dram-see-v4-transport-operation-v2" and record.get("label") == folder.name
            and record.get("origin") == "native_pipeline" and record.get("synthetic") is False
            and record.get("state") in ("COLLECTED_PENDING_AUDIT", "COLLECTED")
            and record.get("parallel_slot_released") is True and record.get("collection_verified") is True
            and all(type(record.get(key)) is int and record[key] == 0 for key in (
                "remote_exit_code", "operation_task_exit_code", "collection_exit_code"))
            and archive._positive_size(size) and archive._matches(archive.SHA256, sha),
            "Expected a verified, released, successful original Geant4 operation")
    audit, audit_bytes = archive._read_json(audit_path)
    with archive._open_regular(ledger_path) as stream:
        ledger_bytes = stream.read()
    op_sha, ledger_sha = (hashlib.sha256(data).hexdigest() for data in (op_bytes, ledger_bytes))
    require(audit.get("transport_run_id") == folder.name and audit["operation"]["sha256"] == op_sha
            and audit.get("archive_sha256") == sha and audit.get("event_deposition_sha256") == ledger_sha
            and archive._matches(archive.SHA256, audit["members"][archive.STEPS]),
            "Deposition audit differs from the original operation or ledger")
    count, zero = _ledger_counts(audit, ledger_bytes)
    receipt = {"schema": release.BACKUP_SCHEMA, "run_id": folder.name, "operation_sha256": op_sha,
               "original_archive_sha256": sha, "original_archive_bytes": size,
               "event_deposition_sha256": ledger_sha, "primary_count": count,
               "zero_si_deposition": zero, "source_retained_locally": True}
    if release._file_stat(out, missing_ok=True) is not None:
        old, _ = archive._read_json(out)
        require(all(type(old.get(key)) is type(value) and old[key] == value for key, value in receipt.items()),
                "Existing backup receipt conflicts with this operation or ledger")
        artifacts = old["drive_artifacts"]
        if AUDIT in artifacts:
            require(artifacts[AUDIT]["sha256"] == hashlib.sha256(audit_bytes).hexdigest(),
                    "Existing backup receipt conflicts with this audit")
        _verify_uploaded(old, config)
        return old

    source = folder / archive.ARCHIVE
    evidence[source] = release._file_stat(source)
    require(evidence[source].st_size == size, "Original results.tar size differs")
    require(evidence[source].st_dev == folder.stat().st_dev, "Original archive and staging must share a filesystem")
    files = {op.name: op_bytes, AUDIT: audit_bytes, DEPOSITION: ledger_bytes}
    # Allow gzip expansion on incompressible input plus filesystem overhead.
    budget = size + size // 100 + 65536 + sum(map(len, files.values())) + archive.BLOCK
    require(shutil.disk_usage(folder).free >= reserve + budget, "Insufficient disk space above backup reserve")
    cfg = drive.load_config(config)
    require(cfg.get("enabled") is True and cfg.get("mode") == "oauth", "Enabled Drive OAuth config required")
    with tempfile.TemporaryDirectory(prefix=".geant4-backup-", dir=folder) as temp:
        stage = Path(temp) / folder.name  # The Drive uploader uses the directory basename as the run ID.
        stage.mkdir()
        compressed = stage / release.RAW_GZIP
        with archive._open_regular(source) as original, compressed.open("xb") as output:
            with gzip.GzipFile(filename="", fileobj=output, mode="wb", compresslevel=1, mtime=0) as packed:
                _check_archive(original, size, sha, packed)
        with gzip.open(compressed, "rb") as unpacked:
            _check_archive(unpacked, size, sha)
        for name, data in files.items():
            (stage / name).write_bytes(data)
        for path, info in evidence.items():
            release._unchanged(path, info)
        uploaded = drive.upload_run_artifacts(stage, (release.RAW_GZIP, *files), config_path=config)
        receipt.update(drive_artifacts=uploaded["uploaded"], drive_folder_id=uploaded["drive_folder_id"])
        _verify_uploaded(receipt, config)
        for path, info in evidence.items():
            release._unchanged(path, info)
        _publish(out, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation_dir", metavar="OP_DIR", type=Path)
    parser.add_argument("--ledger", metavar="LEDGER_DIR", required=True, type=Path)
    parser.add_argument("--receipt-out", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--floor-gib", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        result = backup(args.operation_dir, args.ledger, args.receipt_out,
                        config_path=args.config, floor_gib=args.floor_gib)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, EOFError, zlib.error) as exc:
        print(f"Geant4 archive backup failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
