#!/usr/bin/env python3
"""Validate Geant4 cold receipts and restore the original native artifacts."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib


RECEIPT = "transport-archive-offload.json"
SCHEMA = "tcad-geant4-cold-archive-v1"
LOCK_NAME = ".transport-archive.lock"
OPERATION = "operation.json"
ARCHIVE = "results.tar"
STEPS = "steps.csv"
BLOCK = 1024 * 1024
WORKER_STAGING = ".transport-worker-restore"
SHA256 = re.compile(r"[0-9a-f]{64}")
MD5 = re.compile(r"[0-9a-f]{32}")
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]+")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _path_stat(path, predicate, missing_ok=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    _require(predicate(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
             f"Unsafe path: {path}")
    return info


def _directory(path):
    path = Path(path).absolute()
    for parent in reversed(path.parents):
        _path_stat(parent, stat.S_ISDIR)
    _path_stat(path, stat.S_ISDIR)
    return path


@contextmanager
def _open_regular(path, flags=os.O_RDONLY):
    if not flags & os.O_CREAT:
        _path_stat(path, stat.S_ISREG)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "rb") as stream:
        info = _path_stat(path, stat.S_ISREG)
        _require(os.path.samestat(os.fstat(fd), info), f"File changed while opening: {path}")
        yield stream


@contextmanager
def archive_lock(operation_dir):
    """Exclusively lock the operation for restore or release on the server."""
    import fcntl

    directory = _directory(operation_dir)
    lock = directory / LOCK_NAME
    # Keep the lock inode so concurrent callers always lock the same file.
    _path_stat(lock, stat.S_ISREG, missing_ok=True)
    with _open_regular(lock, os.O_RDWR | os.O_CREAT) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        lock_info = os.fstat(stream.fileno())
        _require(os.path.samestat(lock_info, _path_stat(lock, stat.S_ISREG)),
                 "Archive lock was replaced while waiting")
        owner = directory.stat()
        if os.geteuid() == 0 and lock_info.st_uid == 0 and owner.st_uid != 0:
            # The controller runs as the operation owner. Keep the existing lock inode.
            os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
        yield


def _read_json(path):
    with _open_regular(path) as stream:
        raw = stream.read(4 * BLOCK + 1)
    _require(len(raw) <= 4 * BLOCK, f"Archive metadata exceeds 4 MiB: {path.name}")
    doc = json.loads(raw)
    _require(isinstance(doc, dict), f"Expected a JSON object: {path.name}")
    return doc, raw


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _positive_size(value):
    return type(value) is int and value > 0


def _identity(operation_path, record=None, *, require_receipt=True):
    _require(operation_path.name == OPERATION, f"Expected {OPERATION}")
    receipt = _read_json(operation_path.with_name(RECEIPT))[0] if require_receipt else None
    original, data = _read_json(operation_path)
    label = operation_path.parent.name
    _require(record is None or original == record, "Operation differs from the supplied record")
    _require(original.get("schema") == "dram-see-v4-transport-operation-v2"
             and original.get("origin") == "native_pipeline" and original.get("synthetic") is False
             and original.get("label") == label and original.get("parallel_slot_released") is True
             and original.get("state") in ("COLLECTED", "COLLECTED_PENDING_AUDIT")
             and original.get("collection_verified") is True
             and all(type(original.get(key)) is int and original[key] == 0 for key in (
                 "remote_exit_code", "operation_task_exit_code", "collection_exit_code",
             )),
             "Expected a released, successfully collected native Geant4 v2 operation")
    archive_sha, archive_size = original.get("archive_sha256"), original.get("collected_bytes")
    _require(_matches(SHA256, archive_sha) and _positive_size(archive_size), "Invalid original archive identity")
    if receipt is None:
        return {"archive_sha256": archive_sha, "archive_bytes": archive_size}
    _require(receipt.get("schema") == SCHEMA and receipt.get("cloud_verified") is True
             and receipt.get("run_id") == label
             and receipt.get("operation_sha256") == hashlib.sha256(data).hexdigest()
             and receipt.get("archive_sha256") == archive_sha
             and _positive_size(receipt.get("archive_bytes"))
             and receipt["archive_bytes"] == archive_size
             and _matches(SHA256, receipt.get("primary_ledger_sha256")), "Cold receipt identity differs")
    raw, steps = receipt.get("raw"), receipt.get("steps")
    _require(isinstance(raw, dict) and _matches(DRIVE_ID, raw.get("file_id"))
             and _positive_size(raw.get("bytes")) and _matches(SHA256, raw.get("sha256"))
             and _matches(MD5, raw.get("md5")), "Invalid raw gzip identity")
    _require(isinstance(steps, dict) and _positive_size(steps.get("bytes"))
             and steps["bytes"] <= receipt["archive_bytes"]
             and _matches(SHA256, steps.get("sha256")), "Invalid steps.csv identity")
    return receipt


def _output_paths(directory):
    collected = directory / "collected"
    _path_stat(collected, stat.S_ISDIR, missing_ok=True)
    return directory / ARCHIVE, collected / STEPS


def verify_cold(operation_path, record) -> bool:
    """Verify local metadata for an offloaded operation without reading bulk data."""
    if not isinstance(record, dict):
        return False
    try:
        operation_path = Path(operation_path)
        directory = _directory(operation_path.parent)
        receipt = _identity(directory / operation_path.name, record)
        archive, steps = _output_paths(directory)
        for path, size in ((archive, receipt["archive_bytes"]), (steps, receipt["steps"]["bytes"])):
            info = _path_stat(path, stat.S_ISREG, missing_ok=True)
            if info is not None and info.st_size != size:
                return False
        return True
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def _local_matches(path, size, sha256):
    info = _path_stat(path, stat.S_ISREG, missing_ok=True)
    if info is None:
        return False
    with _open_regular(path) as stream:
        _require(info.st_size == size and hashlib.file_digest(stream, "sha256").hexdigest() == sha256,
                 f"Existing file differs: {path}")
    return True


def _space(path, floor_bytes, *sizes):
    usage = os.statvfs(path)
    block = usage.f_frsize
    needed = floor_bytes + block * (2 + sum((size + block - 1) // block for size in sizes))
    free = block * usage.f_bavail
    _require(free >= needed, f"Insufficient disk space: {free} bytes available, {needed} required")


def _download_limited(raw, target, config_path):
    import resource

    import gdrive_offload

    target = Path(target)
    config = gdrive_offload.resolve_config_path(config_path)
    config = _directory(config.parent) / config.name
    _path_stat(config, stat.S_ISREG)
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = raw["bytes"] if soft == resource.RLIM_INFINITY else min(raw["bytes"], soft)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
    gdrive_offload.download_file(raw["file_id"], target, expected_sha256=raw["sha256"],
                                expected_bytes=raw["bytes"], config_path=config)
    with _open_regular(target) as stream:
        _require(hashlib.file_digest(stream, "md5").hexdigest() == raw["md5"], "Downloaded gzip MD5 differs")


def _download(raw, target, config_path):
    # The worker runs inside the controller. Limit writes in the child only.
    request = json.dumps([raw, str(target), str(config_path) if config_path is not None else None])
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "import json,sys; from geant4_archive import _download_limited; "
         "_download_limited(*json.load(sys.stdin))"],
        cwd=Path(__file__).resolve().parent, input=request, text=True, capture_output=True, timeout=600,
    )
    _require(result.returncode == 0, "Drive archive download failed or did not match its receipt")


def _copy_verified(source, target, size, sha256):
    total = 0
    digest = hashlib.sha256()
    with target.open("xb") as out:
        for block in iter(lambda: source.read(BLOCK), b""):
            total += len(block)
            _require(total <= size, f"Restored {target.name} exceeds its original size")
            digest.update(block)
            out.write(block)
        _require(total == size and digest.hexdigest() == sha256, f"Restored {target.name} SHA-256/size differs")
        out.flush()
        os.fsync(out.fileno())


def _stage_archive(staging, receipt, config_path, floor_bytes, *later_sizes):
    raw, size = receipt["raw"], receipt["archive_bytes"]
    compressed, archive = staging / "results.tar.gz", staging / ARCHIVE
    _space(staging, floor_bytes, raw["bytes"], size, *later_sizes)
    _download(raw, compressed, config_path)
    _space(staging, floor_bytes, size, *later_sizes)
    with gzip.open(compressed, "rb") as stream:
        _copy_verified(stream, archive, size, receipt["archive_sha256"])
    compressed.unlink()
    return archive


def _extract_steps(archive, target, expected):
    with _open_regular(archive) as stream, tarfile.open(fileobj=stream, mode="r:") as source:
        steps = None
        for member in source:
            if PurePosixPath(member.name).name == STEPS:
                _require(steps is None and member.name == STEPS
                         and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not member.issparse(),
                         "Expected exactly one regular, top-level steps.csv in the archive")
                steps = member
        _require(steps is not None and steps.size == expected["bytes"], "Missing or wrong-sized steps.csv")
        with source.extractfile(steps) as content:
            _copy_verified(content, target, expected["bytes"], expected["sha256"])


def _publish(source, dest, size, sha256):
    # Creating the link publishes the whole verified file and refuses clobbering.
    fd = os.open(dest.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.link(source, dest.name, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError:
            if not _local_matches(dest, size, sha256):
                raise
        os.fsync(fd)
    finally:
        os.close(fd)


def _clear_worker_staging(staging, archive, identity=None, installed=None):
    if _path_stat(staging, stat.S_ISDIR, missing_ok=True) is None:
        return
    link = _path_stat(staging / ARCHIVE, stat.S_ISREG, missing_ok=True)
    current = _path_stat(archive, stat.S_ISREG, missing_ok=True)
    if link is not None and current is not None and os.path.samestat(link, current):
        if identity is not None:
            _local_matches(archive, identity["archive_bytes"], identity["archive_sha256"])
        if installed is None or (installed.st_size, installed.st_mtime_ns) == (current.st_size, current.st_mtime_ns):
            archive.unlink()
    shutil.rmtree(staging)


@contextmanager
def materialized_tar(operation_directory, config_path=None, floor_bytes=20 * 1024**3):
    """Yield the verified original results.tar under the operation's archive lock."""
    _require(type(floor_bytes) is int and floor_bytes >= 0, "floor_bytes must be a nonnegative integer")
    directory = _directory(operation_directory)
    archive, operation = directory / ARCHIVE, directory / OPERATION
    with archive_lock(directory):
        staging = directory / WORKER_STAGING
        if staging.exists():
            _clear_worker_staging(staging, archive, identity=_identity(operation))
        hot = _path_stat(archive, stat.S_ISREG, missing_ok=True) is not None
        receipt = _identity(operation, require_receipt=not hot)
        size, sha = receipt["archive_bytes"], receipt["archive_sha256"]
        if hot:
            _require(_local_matches(archive, size, sha), "Hot archive differs from its receipt")
            yield archive
            return

        _space(directory, floor_bytes, receipt["raw"]["bytes"], size)
        staging.mkdir(mode=0o700)
        installed = None
        try:
            staged_archive = _stage_archive(staging, receipt, config_path, floor_bytes)
            _require(receipt == _identity(operation), "Cold receipt changed during restore")
            installed = staged_archive.stat()
            _publish(staged_archive, archive, size, sha)
            yield archive
        finally:
            _clear_worker_staging(staging, archive, installed=installed)


def _restore(operation_dir, config_path, floor_bytes):
    directory = _directory(operation_dir)
    with archive_lock(directory):
        operation = directory / OPERATION
        receipt = _identity(operation)
        archive, steps = _output_paths(directory)
        archive_size, archive_sha = receipt["archive_bytes"], receipt["archive_sha256"]
        steps_info = receipt["steps"]
        steps_size, steps_sha = steps_info["bytes"], steps_info["sha256"]
        have_archive = _local_matches(archive, archive_size, archive_sha)
        have_steps = _local_matches(steps, steps_size, steps_sha)
        if have_archive and have_steps:
            return

        raw = receipt["raw"]
        peak = (steps_size,) if have_archive else (raw["bytes"], archive_size, steps_size)
        _space(directory, floor_bytes, *peak)
        with tempfile.TemporaryDirectory(prefix=".transport-restore-", dir=directory) as staging:
            staging = Path(staging)
            staged_archive = archive if have_archive else _stage_archive(
                staging, receipt, config_path, floor_bytes, steps_size)
            staged_steps = staging / STEPS
            _space(staging, floor_bytes, steps_size)
            _extract_steps(staged_archive, staged_steps, steps_info)
            _require(receipt == _identity(operation), "Cold receipt changed during restore")
            steps.parent.mkdir(exist_ok=True)
            collected = _path_stat(steps.parent, stat.S_ISDIR)
            _require(collected.st_dev == staging.stat().st_dev, "Collected data is on a separate filesystem")
            if not have_archive:
                _publish(staged_archive, archive, archive_size, archive_sha)
            if not have_steps:
                _publish(staged_steps, steps, steps_size, steps_sha)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    restore = commands.add_parser("restore", help="Restore the original results.tar and collected/steps.csv")
    restore.add_argument("operation_directory", type=Path)
    restore.add_argument("--config", type=Path)
    restore.add_argument("--floor-gib", type=int, default=20)
    args = parser.parse_args(argv)
    if args.floor_gib < 0:
        restore.error("--floor-gib must be nonnegative")
    try:
        _restore(args.operation_directory, args.config, args.floor_gib * 1024**3)
    except (OSError, ValueError, EOFError, ImportError, KeyError, RecursionError, tarfile.TarError,
            zlib.error, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Restore failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
