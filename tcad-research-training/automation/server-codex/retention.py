"""Lossless raw backup plus explicitly projected essentials for collected runs.

No runner calls, scientific acceptance, raw-backup retirement or loose-file cleanup.
Caller owns consumption/retention-ready admission. All mutations share .retention.lock.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile
import zlib

SCHEMA = "tcad-result-retention-v1"
OFFLOAD_SCHEMA = "tcad-result-gdrive-offload-v1"
OFFLOAD_RECEIPT = "gdrive-offload.json"
MIRROR_SCHEMA = "tcad-result-local-mirror-offload-v1"
MIRROR_RECEIPT = "local-mirror-offload.json"
GUEST_RECEIPT = "guest-reclaim.json"
MIRROR_METADATA = ("manifest.json", "retention.json", GUEST_RECEIPT)
LOCK_NAME = ".retention.lock"
RAW = "results.tar"
RAW_GZ = "results.raw.tar.gz"
ESSENTIAL = "results.essential.tar.gz"
WITNESS = "results.log-witness.jsonl.gz"
RECEIPT = "retention.json"
BLOCK = 1024 * 1024
LOG_THRESHOLD = 16 * 1024 * 1024
NUMBER = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
CALLBACK = re.compile(
    rb"R04_QY_CALLBACK n=\d+ region=\S+"
    rb" time=" + NUMBER + rb" dt=" + NUMBER + rb" type=\d+"
    rb" x=" + NUMBER + rb" y=" + NUMBER + rb" z=" + NUMBER
    + rb" G=" + NUMBER + rb" eta=" + NUMBER + rb"(?:\r?\n)?\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def _signature(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _same_file_stat(left, right):
    # Windows CPython fstat exposes ChangeTime where path lstat can expose
    # creation time as ctime. Compare identity/size/mtime across those APIs;
    # digest caches still use the full fstat signature, including ChangeTime.
    return left[:4] == right[:4] if os.name == "nt" else left == right


def _not_link(path):
    value = path.lstat()
    need(not stat.S_ISLNK(value.st_mode)
         and not (getattr(value, "st_file_attributes", 0) & 0x400), "Link/reparse point: " + str(path))
    return value


def _checked_path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for part in list(path.parents)[::-1] + [path]:
        _not_link(part)
    return path


def _run_path(run_dir):
    path = _checked_path(run_dir)
    need(path.is_dir() and path.parent.name == "runs", "Run must be a direct child of runs")
    return path


def _exists(path):
    return os.path.lexists(path)


@contextmanager
def _open(path, flags=os.O_RDONLY, mode="rb"):
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    try:
        before = os.fstat(fd)
        current = _not_link(path)
        need(stat.S_ISREG(before.st_mode) and _same_file_stat(_signature(before), _signature(current)),
             "Not a stable regular file: " + str(path))
        stream = os.fdopen(fd, mode)
        fd = None
        with stream:
            yield stream
    finally:
        if fd is not None:
            os.close(fd)


def _unchanged(path, signature):
    need(_same_file_stat(_signature(_not_link(path)), signature), "File changed during retention: " + str(path))


def _sha(path, cache=None):
    with _open(path) as stream:
        signature = _signature(os.fstat(stream.fileno()))
        key = str(path)
        old = cache.get(key) if cache is not None else None
        if old and old[0] == signature:
            value = old[1]
        else:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(BLOCK), b""):
                digest.update(block)
            value = digest.hexdigest()
        need(_signature(os.fstat(stream.fileno())) == signature, "Open file changed: " + str(path))
        _unchanged(path, signature)
        if cache is not None:
            cache[key] = (signature, value)
        return value


def _json(path):
    with _open(path) as stream:
        signature = _signature(os.fstat(stream.fileno()))
        raw = stream.read()
        _unchanged(path, signature)
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _manifest(run):
    manifest, digest = _json(run / "manifest.json")
    need(isinstance(manifest, dict) and manifest.get("state") == "COLLECTED"
         and type(manifest.get("remote_exit_code")) is int and manifest["remote_exit_code"] == 0
         and manifest.get("collection_verified") is True
         and manifest.get("parallel_slot_released") is True, "Run is not successfully collected/released")
    need(manifest.get("run_id") == run.name, "Manifest run_id differs from directory")
    need(isinstance(manifest.get("results_sha256"), str)
         and HEX.fullmatch(manifest["results_sha256"]), "Missing original results SHA-256")
    return manifest, digest


@contextmanager
def _lock(run):
    with _open(run / LOCK_NAME, os.O_RDWR | os.O_CREAT, "r+b") as stream:
        if os.name == "nt":
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _sync_dir(run):
    if os.name != "nt":
        fd = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _temp(run, pending):
    fd, name = tempfile.mkstemp(prefix=".retention-", dir=run)
    os.close(fd)
    path = Path(name)
    pending.append(path)
    return path


def _publish(temp, target):
    if _exists(target):
        need(stat.S_ISREG(_not_link(target).st_mode), "Unsafe artifact target")
    os.replace(temp, target)
    _sync_dir(target.parent)


def _safe_name(name):
    need(isinstance(name, str) and name and not name.startswith(("/", "\\"))
         and "\\" not in name and ":" not in name
         and all(ord(c) >= 32 for c in name), "Unsafe member/artifact name")
    parts = name.rstrip("/").split("/")
    need(all(p not in ("", ".", "..") for p in parts), "Unsafe member/artifact path: " + name)
    return "/".join(parts)


def _artifact_path(run, name):
    clean = _safe_name(name)
    need(clean == name and "/" not in clean, "Artifact must be a safe basename")
    return run / name


def _file_record(path):
    return dict(bytes=_not_link(path).st_size, sha256=_sha(path))


def _copy_file(source, target):
    with _open(source) as stream, _open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, "wb") as output:
        signature = _signature(os.fstat(stream.fileno()))
        shutil.copyfileobj(stream, output, BLOCK)
        output.flush()
        os.fsync(output.fileno())
        _unchanged(source, signature)


def _guest_sha(run, doc, manifest):
    proof, sha = _json(run / GUEST_RECEIPT)
    need(isinstance(proof, dict) and proof.get("schema") == "tcad-result-guest-reclaim-v1"
         and proof.get("run_id") == run.name
         and proof.get("original_archive_sha256") == doc["original_archive_sha256"],
         "Guest reclaim identity differs")
    removed = proof.get("removed")
    need(isinstance(removed, list) and type(proof.get("removed_bytes")) is int,
         "Guest reclaim inventory is missing")
    allowed = {row["name"]: (row["size"], row["sha256"]) for row in doc["original_members"]
               if row["policy"] == "projected_log"}
    allowed[".collection/results.tar"] = (doc["original_archive_bytes"], manifest["results_sha256"])
    seen, size = set(), 0
    for row in removed:
        name = _safe_name(row["name"])
        need(name not in seen and type(row["size"]) is int
             and allowed.get(name) == (row["size"], row["sha256"]), "Guest reclaim inventory differs")
        seen.add(name)
        size += row["size"]
    need(size == proof["removed_bytes"], "Guest reclaim byte count differs")
    return sha


def _unique(rows, key, value):
    matches = [row for row in rows if row[key] == value]
    need(len(matches) == 1, "Missing or ambiguous frozen identity")
    return matches[0]


def archive_partition(manifest, runtime_state, case_manifest):
    """Use the trusted pre-launch intent and its pinned r0.6 plan, not the run name."""
    state, _ = _json(_checked_path(runtime_state))
    plan, plan_sha = _json(_checked_path(case_manifest))
    need(state.get("schema") == "tcad-autonomy-intents-v1"
         and plan.get("plan_id") == "dram-se-ddr5-lpddr5" and plan.get("revision") == "r0.6",
         "Unknown Runtime ledger or frozen plan")
    intent = _unique(state["intents"].values(), "run_id", manifest["run_id"])
    inputs = intent["input_sha256"]
    need(intent.get("backend") == "tcad" and isinstance(inputs, dict) and inputs
         and all(HEX.fullmatch(value) and manifest["input_sha256"].get(name) == value
                 for name, value in inputs.items()), "Original input identity differs from the intent")
    admission = intent["scientific_admission"]
    need(admission.get("manifest_sha256") == plan_sha, "Frozen plan hash differs from the intent")
    identity = admission["scientific_object"]
    scope = admission["scope"]
    profile = _unique(plan["profiles"], "id", identity["profile_id"])
    partition = profile["partition"]
    need(partition in ("development", "profile_holdout"), "Unknown profile partition")
    if scope == "p0_diagnostic":
        need(identity.get("scope") == scope and admission["recipe_id"] == identity["recipe_id"],
             "Frozen diagnostic identity differs")
        return "sealed" if partition != "development" else "development"

    need(scope in ("development_production", "holdout_evaluation")
         and admission["case_id"] == identity["case_id"], "Unknown frozen case identity")
    case = _unique(plan["cases"], "case_id", identity["case_id"])
    need(case["block"] in ("Z", "T", "S", "R", "HR", "HP", "AL")
         and identity["block"] == case["block"] and type(identity["stored_bit"]) is int
         and identity["stored_bit"] == case["stored_bit"], "Frozen case coordinates differ")
    if case["block"] != "AL":
        need(all(identity[key] == case[key] for key in ("profile_id", "radiation_id")),
             "Frozen case coordinates differ")
    radiation = identity["radiation_id"]
    role = None if radiation is None else _unique(plan["radiations"], "id", radiation)["role"]
    need((radiation is None and case["block"] == "Z")
         or role in ("development", "radiation_holdout"), "Unknown radiation partition")
    need(case["holdout"] in (None, "profile", "radiation"), "Unknown holdout partition")
    sealed = (case["block"] in ("HR", "HP") or case["holdout"] is not None
              or partition == "profile_holdout" or role == "radiation_holdout")
    need(scope == ("holdout_evaluation" if sealed else "development_production"),
         "Frozen case scope disagrees with its partition")
    return "sealed" if sealed else "development"


def mirror_inventory(doc):
    names = tuple(doc["artifacts"]) + MIRROR_METADATA
    for name in names:
        _artifact_path(Path(), name)
        need(not name.endswith((".", " ")) and not any(char in name for char in '<>"|?*')
             and not re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]",
                                  name.split(".", 1)[0], re.IGNORECASE), "Nonportable mirror filename")
    need(len({name.casefold() for name in (*names, MIRROR_RECEIPT)}) == len(names) + 1,
         "Mirror inventory has conflicting names")
    return names


def _mirror_proof(doc, retention_sha, guest_sha, partition):
    need(partition in ("development", "sealed"), "Unknown mirror partition")
    return dict(schema=MIRROR_SCHEMA, verified=True, partition=partition,
                manifest_sha256=doc["manifest_sha256"], retention_sha256=retention_sha,
                guest_reclaim_sha256=guest_sha, original_archive_sha256=doc["original_archive_sha256"],
                raw_backup_sha256=doc["artifacts"][RAW_GZ]["sha256"],
                raw_backup_bytes=doc["artifacts"][RAW_GZ]["bytes"])


def mirror_snapshot(mirror_run, partition=None, *, inflate=True):
    """Verify a complete on-disk bundle. With partition set, build its receipt."""
    mirror = _run_path(mirror_run)
    manifest, _ = _manifest(mirror)
    doc, retention_sha = _json(mirror / RECEIPT)
    need(doc.get("raw_backup_retired") is False and not doc.get("raw_backup_offloaded")
         and "raw_backup_local_mirror" not in doc, "Mirror must carry the pre-offload retention record")
    names = set(mirror_inventory(doc))
    if partition is None:
        proof, _ = _json(mirror / MIRROR_RECEIPT)
        partition = proof["partition"]
        names.add(MIRROR_RECEIPT)
    else:
        proof = None
    need({path.name for path in mirror.iterdir()} == names, "Mirror file set differs")
    need(_verify(mirror, manifest) == doc, "Mirror retention record changed")
    guest_sha = _guest_sha(mirror, doc, manifest)
    expected = _mirror_proof(doc, retention_sha, guest_sha, partition)
    if proof is not None:
        need(proof == expected and type(proof.get("raw_backup_bytes")) is int
             and proof.get("verified") is True, "Mirror receipt differs")
    if inflate:
        _verify_raw_backup(mirror / RAW_GZ, manifest["results_sha256"], doc["original_archive_bytes"])
    need(_sha(mirror / RECEIPT) == retention_sha, "Mirror retention record changed")
    return expected


def _mirror_valid(run, doc):
    pointer = doc.get("raw_backup_local_mirror")
    need(isinstance(pointer, dict) and set(pointer) == {"sha256"}, "Missing mirror pointer")
    proof, sha = _json(run / MIRROR_RECEIPT)
    manifest, _ = _manifest(run)
    expected = _mirror_proof(doc, proof["retention_sha256"], _guest_sha(run, doc, manifest), proof["partition"])
    need(sha == pointer["sha256"] and proof == expected and proof.get("verified") is True
         and isinstance(proof["retention_sha256"], str) and HEX.fullmatch(proof["retention_sha256"]),
         "Local mirror receipt changed")
    return proof


def _match_mirror(run, doc, mirror_run, *, inflate=True):
    mirror = _run_path(mirror_run)
    need(not mirror.samefile(run), "Mirror must be a separate run directory")
    proof = mirror_snapshot(mirror, inflate=inflate)
    if "raw_backup_local_mirror" in doc:
        need(proof == _mirror_valid(run, doc)
             and _sha(mirror / MIRROR_RECEIPT) == doc["raw_backup_local_mirror"]["sha256"],
             "Mirror receipt differs from pinned copy")
        snapshot, _ = _json(mirror / RECEIPT)
        need(snapshot == {key: value for key, value in doc.items() if key != "raw_backup_local_mirror"},
             "Retention inventory differs from the pinned mirror")
    else:
        manifest, _ = _manifest(run)
        need(proof == _mirror_proof(doc, _sha(run / RECEIPT), _guest_sha(run, doc, manifest),
                                    proof["partition"]), "Mirror does not match this retention snapshot")
    return proof


def _release_valid(run, doc):
    release = doc.get("raw_backup_release")
    need(isinstance(release, dict) and HEX.fullmatch(release.get("sha256", "")), "Missing release evidence")
    name = _safe_name(release["evidence_file"])
    path = _checked_path(run / name)
    proof, sha = _json(path)
    need(sha == release["sha256"], "Release evidence SHA differs")
    need(isinstance(proof, dict) and proof.get("scientific_review_complete") is True
         and proof.get("release_original_archive") is True, "Scientific release is not complete")
    need(all(proof.get(k) == doc[k] for k in
             ("run_id", "original_archive_sha256", "manifest_sha256")), "Release identity differs")


def _offload_valid(run, doc):
    offload = doc.get("raw_backup_offload")
    need(isinstance(offload, dict) and HEX.fullmatch(offload.get("sha256", "")), "Missing offload evidence")
    name = _safe_name(offload["evidence_file"])
    path = _checked_path(run / name)
    proof, sha = _json(path)
    need(sha == offload["sha256"], "Offload evidence SHA differs")
    need(isinstance(proof, dict) and proof.get("schema") == OFFLOAD_SCHEMA
         and proof.get("verified") is True and proof.get("state") in ("BACKED_UP", "OFFLOADED"),
         "Offload verification is incomplete")
    need(all(proof.get(k) == doc[k] for k in
             ("run_id", "original_archive_sha256", "manifest_sha256")), "Offload identity differs")
    raw_entry = doc.get("artifacts", {}).get(RAW_GZ, {})
    need(proof.get("raw_backup_sha256") == raw_entry.get("sha256")
         and proof.get("raw_backup_bytes") == raw_entry.get("bytes")
         and isinstance(proof.get("drive_file_id"), str) and bool(proof["drive_file_id"].strip()),
         "Offload artifact identity differs")
    return proof


def _default_fetcher(run, doc, dest_path):
    source = Path(__file__).with_name("gdrive_offload.py")
    spec = importlib.util.spec_from_file_location("_tcad_gdrive_offload", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fetch_backup_from_receipt(run, doc, dest_path)


def _verify(run, manifest, cache=None):
    actual, manifest_sha = _manifest(run)
    need(actual == manifest, "Caller manifest differs from original manifest bytes")
    doc, _ = _json(run / RECEIPT)
    need(isinstance(doc, dict) and doc.get("schema") == SCHEMA and doc.get("run_id") == run.name
         and doc.get("manifest_sha256") == manifest_sha
         and doc.get("original_archive_sha256") == actual["results_sha256"]
         and doc.get("is_scientific_acceptance") is False, "Retention identity differs")
    need(doc.get("raw_backup_verified") is True
         and doc.get("raw_backup_uncompressed_sha256") == actual["results_sha256"]
         and type(doc.get("original_archive_bytes")) is int and doc["original_archive_bytes"] > 0,
         "Original backup verification is missing")
    need(type(doc.get("raw_backup_retired")) is bool, "Invalid retirement flag")
    retired = doc["raw_backup_retired"]
    if retired:
        _release_valid(run, doc)
    offloaded = doc.get("raw_backup_offloaded", False)
    need(type(offloaded) is bool, "Invalid offload flag")
    if offloaded:
        _offload_valid(run, doc)
    mirrored = "raw_backup_local_mirror" in doc
    if mirrored:
        need(not retired, "A mirrored backup must remain restorable")
        _mirror_valid(run, doc)
    artifacts = doc["artifacts"]
    need(isinstance(artifacts, dict) and {RAW_GZ, ESSENTIAL, WITNESS} <= set(artifacts),
         "Missing required artifact inventory")
    for name, entry in artifacts.items():
        path = _artifact_path(run, name)
        need(isinstance(entry, dict) and HEX.fullmatch(entry.get("sha256", ""))
             and type(entry.get("bytes")) is int and entry["bytes"] > 0, "Invalid artifact record")
        if name == RAW_GZ and (retired or ((offloaded or mirrored) and not _exists(path))):
            continue
        need(_not_link(path).st_size == entry["bytes"] and _sha(path, cache) == entry["sha256"],
             "Artifact missing/changed: " + name)
    members = doc["original_members"]
    need(isinstance(members, list) and members, "Missing original member inventory")
    names = set()
    for member in members:
        name = _safe_name(member["name"])
        need(name not in names and HEX.fullmatch(member.get("sha256", ""))
             and type(member.get("size")) is int and member["size"] >= 0
             and member.get("policy") in ("preserved", "projected_log"), "Invalid original member inventory")
        names.add(name)
        if member["policy"] == "projected_log":
            need(member.get("witness_artifact") == WITNESS
                 and HEX.fullmatch(member.get("retained_sha256", ""))
                 and member.get("original_lines", -1) == member.get("retained_lines", -2)
                 + member.get("dropped_callback_lines", -3)
                 and member["dropped_callback_lines"] > 0
                 and member.get("is_complete_log") is False, "Invalid projected log inventory")
    raw = run / RAW
    if _exists(raw):
        need(_not_link(raw).st_size == doc["original_archive_bytes"]
             and _sha(raw, cache) == actual["results_sha256"], "Materialized original archive changed")
    return doc


def verify_retained(run_dir, manifest, cache=None):
    """Verify receipt and every current artifact; raw gzip is hashed, not inflated.

    cache may be a caller-owned dict of path -> (stat signature, digest). It never
    bypasses manifest/release checks or changes to file size/inode/mtime/ctime.
    """
    try:
        _verify(_run_path(run_dir), manifest, cache)
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError):
        return False


@contextmanager
def _gzip_writer(path):
    with _open(path, os.O_WRONLY | os.O_TRUNC, "wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=1, mtime=0) as zipped:
            yield zipped
        stream.flush()
        os.fsync(stream.fileno())


def _raw_backup(raw, target, expected):
    digest = hashlib.sha256()
    with _open(raw) as source, _gzip_writer(target) as zipped:
        signature = _signature(os.fstat(source.fileno()))
        for block in iter(lambda: source.read(BLOCK), b""):
            digest.update(block)
            zipped.write(block)
        _unchanged(raw, signature)
    need(digest.hexdigest() == expected, "Original archive SHA differs")
    _verify_raw_backup(target, expected)
    return signature


def _verify_raw_backup(path, expected, expected_bytes=None, target=None):
    digest, size = hashlib.sha256(), 0
    with _open(path) as stream:
        signature = _signature(os.fstat(stream.fileno()))
        try:
            with gzip.GzipFile(fileobj=stream, mode="rb") as source:
                for block in iter(lambda: source.read(BLOCK), b""):
                    digest.update(block)
                    size += len(block)
                    need(expected_bytes is None or size <= expected_bytes, "Raw gzip exceeds original size")
                    if target is not None:
                        target.write(block)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError("Unreadable raw gzip backup") from exc
        _unchanged(path, signature)
    need(digest.hexdigest() == expected and (expected_bytes is None or size == expected_bytes),
         "Raw gzip does not restore the original archive SHA/size")


def _emit(stream, value):
    stream.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")


def _project(source, target, witness, name):
    """Bounded readline chunks; long lines spool to disk, never accumulate in RAM."""
    digest = hashlib.sha256()
    original_lines = retained_lines = dropped = 0
    mapping = None

    def flush_mapping():
        nonlocal mapping
        if mapping:
            _emit(witness, dict(member=name, retained_start_line=mapping[0],
                                original_start_line=mapping[1], line_count=mapping[2]))
            mapping = None

    with _open(target, os.O_RDWR | os.O_TRUNC, "w+b") as output:
        while True:
            part = source.readline(BLOCK)
            if not part:
                break
            original_lines += 1
            digest.update(part)
            # Exact full-format callbacks need no disk writes. Lines exceeding
            # BLOCK (1 MiB in production) stay verbatim rather than risk a
            # partial match or unbounded memory.
            if part.endswith(b"\n") or len(part) < BLOCK:
                discard = CALLBACK.fullmatch(part) is not None
                if not discard:
                    output.write(part)
            else:
                output.write(part)
                while not part.endswith(b"\n"):
                    part = source.readline(BLOCK)
                    if not part:
                        break
                    digest.update(part)
                    output.write(part)
                discard = False
            if discard:
                dropped += 1
                flush_mapping()
            else:
                retained_lines += 1
                if mapping is None:
                    mapping = [retained_lines, original_lines, 1]
                else:
                    mapping[2] += 1
        flush_mapping()
        output.flush()
        os.fsync(output.fileno())
    return dict(sha256=digest.hexdigest(), original_lines=original_lines,
                retained_lines=retained_lines, dropped_callback_lines=dropped)


class _HashReader:
    def __init__(self, source):
        self.source, self.digest, self.size = source, hashlib.sha256(), 0

    def read(self, size):
        need(size <= BLOCK, "Tar copy exceeded fixed block size")
        value = self.source.read(size)
        self.digest.update(value)
        self.size += len(value)
        return value


def _essential(raw, target, witness_path, run, pending, input_names=()):
    inventory, names, file_names = [], set(), set()
    with _open(raw) as source, _gzip_writer(target) as zipped, _gzip_writer(witness_path) as witness:
        _emit(witness, dict(schema=SCHEMA, kind="retained_log_line_mapping",
                            ranges="1-based inclusive starts and line_count; original raw log required for full text"))
        with tarfile.open(fileobj=source, mode="r|") as archive, tarfile.open(
                fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT, copybufsize=BLOCK) as output:
            while True:
                member = archive.next()
                if member is None:
                    break
                name = _safe_name(member.name)
                need(name not in names and (member.isfile() or member.isdir()) and not member.issparse(),
                     "Duplicate/link/nonregular/sparse tar member: " + name)
                need(not any("/".join(name.split("/")[:i]) in file_names
                             for i in range(1, len(name.split("/")))), "Tar file/directory collision")
                need(not (member.isfile() and any(n.startswith(name + "/") for n in names)),
                     "Tar file/directory collision")
                names.add(name)
                if member.isfile():
                    file_names.add(name)
                entry = dict(name=member.name, size=member.size,
                             type="directory" if member.isdir() else "file", policy="preserved")
                kept = copy.copy(member)
                kept.pax_headers = dict(member.pax_headers)
                if member.isdir():
                    need(member.size == 0, "Nonempty tar directory")
                    entry["sha256"] = hashlib.sha256(b"").hexdigest()
                    output.addfile(kept)
                elif member.size >= LOG_THRESHOLD and name.endswith(".log") and name not in input_names:
                    projection = _temp(run, pending)
                    with archive.extractfile(member) as log:
                        entry.update(_project(log, projection, witness, member.name))
                    need(sum((entry["retained_lines"], entry["dropped_callback_lines"]))
                         == entry["original_lines"], "Log line inventory differs")
                    kept.size = projection.stat().st_size
                    kept.pax_headers.pop("size", None)
                    with _open(projection) as projected:
                        output.addfile(kept, projected)
                    if entry["dropped_callback_lines"]:
                        entry.update(policy="projected_log", retained_sha256=_sha(projection),
                                     retained_bytes=kept.size, witness_artifact=WITNESS,
                                     is_complete_log=False)
                    projection.unlink()
                else:
                    with archive.extractfile(member) as content:
                        reader = _HashReader(content)
                        output.addfile(kept, reader)
                    need(reader.size == member.size, "Truncated member: " + name)
                    entry["sha256"] = reader.digest.hexdigest()
                inventory.append(entry)
                # TarInfo metadata is also retained in our required inventory;
                # discard tarfile's otherwise accumulating duplicate list.
                archive.members.clear()
                output.members.clear()
    need(inventory, "Empty original archive")
    return inventory


def _same_manifest(run, manifest_sha):
    _, current_sha = _manifest(run)
    need(current_sha == manifest_sha, "Original manifest changed")


def _write_record(run, name, record=None, source=None):
    pending = []
    temp = _temp(run, pending)
    try:
        with _open(temp, os.O_WRONLY | os.O_TRUNC, "wb") as stream:
            if source is None:
                _emit(stream, record)
            else:
                stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        _publish(temp, run / name)
    finally:
        temp.unlink(missing_ok=True)


def reclaim_mirror(run_dir, mirror_run, *, runtime_state, case_manifest, allow_sealed=False):
    """Reclaim only the raw gzip, using a verified separate mirror bundle."""
    run = _run_path(run_dir)
    with _lock(run):
        manifest, _ = _manifest(run)
        partition = archive_partition(manifest, runtime_state, case_manifest)
        need(partition == "development" or allow_sealed is True, "Sealed result requires the archive operator")
        cache = {}
        need(verify_retained(run, manifest, cache), "Retention verification failed before mirror reclaim")
        doc, retention_sha = _json(run / RECEIPT)
        need(not doc["raw_backup_retired"] and not doc.get("raw_backup_offloaded"),
             "Run already uses a different backup policy")
        proof = _match_mirror(run, doc, mirror_run)
        need(proof["partition"] == partition, "Mirror partition differs from the frozen identity")
        backup = run / RAW_GZ
        if not _exists(backup):
            need("raw_backup_local_mirror" in doc, "Local raw gzip is missing")
            return {"mirrored": 1, "raw_backup_removed": False}
        signature = cache[str(backup)][0]
        with _open(run / RECEIPT) as stream:
            before = stream.read()
        need(hashlib.sha256(before).hexdigest() == retention_sha, "Retention record changed")
        if _exists(run / MIRROR_RECEIPT):
            need(_json(run / MIRROR_RECEIPT)[0] == proof, "Conflicting mirror receipt")
        else:
            _write_record(run, MIRROR_RECEIPT, proof)
        proof_sha = _sha(run / MIRROR_RECEIPT)
        need(proof_sha == _sha(_run_path(mirror_run) / MIRROR_RECEIPT), "Mirror receipt bytes differ")
        doc["raw_backup_local_mirror"] = {"sha256": proof_sha}
        try:
            _write_record(run, RECEIPT, doc)
            need(verify_retained(run, manifest, cache), "Second retention verification failed; local backup kept")
            _unchanged(backup, signature)
            backup.unlink()
        except (OSError, ValueError, TypeError, KeyError):
            if _exists(backup) and _sha(run / RECEIPT) != retention_sha:
                _write_record(run, RECEIPT, source=before)
            raise
        _sync_dir(run)
        return {"mirrored": 1, "raw_backup_removed": True}


def _dematerialize(run, manifest):
    cache = {}
    doc = _verify(run, manifest, cache)
    raw = run / RAW
    removed = False
    if _exists(raw):
        need(_sha(raw, cache) == doc["original_archive_sha256"], "Different materialized raw")
        signature = _signature(_not_link(raw))
        _same_manifest(run, doc["manifest_sha256"])
        _unchanged(raw, signature)
        raw.unlink()
        _sync_dir(run)
        removed = True
    return dict(run_id=run.name, action="dematerialize", results_tar_removed=removed)


def dematerialize(run_dir):
    """Delete only a verified, materialized results.tar; never create/delete gzip."""
    run = _run_path(run_dir)
    with _lock(run):
        manifest, _ = _manifest(run)
        return _dematerialize(run, manifest)


def compact(run_dir, keep_raw_backup=True):
    need(keep_raw_backup is True, "This version requires a restorable raw backup")
    run = _run_path(run_dir)
    with _lock(run):
        manifest, manifest_sha = _manifest(run)
        if _exists(run / RECEIPT):
            doc = _verify(run, manifest)
            result = _dematerialize(run, manifest)
            return dict(doc, action="already_retained", results_tar_removed=result["results_tar_removed"])
        pending = []
        try:
            stages = {name: _temp(run, pending) for name in (RAW_GZ, ESSENTIAL, WITNESS)}
            raw = run / RAW
            signature = _raw_backup(raw, stages[RAW_GZ], manifest["results_sha256"])
            inventory = _essential(raw, stages[ESSENTIAL], stages[WITNESS], run, pending,
                                   input_names=manifest.get("input_sha256", {}))
            _unchanged(raw, signature)
            _same_manifest(run, manifest_sha)
            artifacts = {name: dict(sha256=_sha(path), bytes=path.stat().st_size)
                         for name, path in stages.items()}
            doc = dict(schema=SCHEMA, run_id=run.name, utc=datetime.now(timezone.utc).isoformat(),
                       manifest_sha256=manifest_sha, original_archive_sha256=manifest["results_sha256"],
                       original_archive_bytes=signature[2], original_members=inventory,
                       artifacts=artifacts, raw_backup_verified=True,
                       raw_backup_uncompressed_sha256=manifest["results_sha256"],
                       raw_backup_retired=False, raw_backup_release=None, is_scientific_acceptance=False,
                       essential_is_original_archive=False,
                       projection_notice="Projected logs are not complete original logs. Embedded original "
                       "collection indices describe the raw archive, not projected members.")
            for name, path in stages.items():
                _publish(path, run / name)
            receipt = _temp(run, pending)
            with _open(receipt, os.O_WRONLY | os.O_TRUNC, "wb") as stream:
                stream.write((json.dumps(doc, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            _same_manifest(run, manifest_sha)
            _unchanged(raw, signature)
            _publish(receipt, run / RECEIPT)
            result = _dematerialize(run, manifest)
            return dict(doc, action="compacted", results_tar_removed=result["results_tar_removed"])
        finally:
            for path in pending:
                path.unlink(missing_ok=True)


def _fetch_mirror(run, doc, mirror_run, target, allow_sealed):
    proof = _mirror_valid(run, doc)
    need(proof["partition"] == "development" or allow_sealed is True, "Sealed result requires the archive operator")
    need(mirror_run is not None, "Explicit verified mirror directory is required for restore")
    _match_mirror(run, doc, mirror_run, inflate=False)
    target.unlink()
    _copy_file(_run_path(mirror_run) / RAW_GZ, target)


def restore(run_dir, fetcher=None, *, mirror_run=None, allow_sealed=False):
    """Restore exact original bytes under the same lock; never overwrite a different raw."""
    run = _run_path(run_dir)
    with _lock(run):
        manifest, _ = _manifest(run)
        doc = _verify(run, manifest)
        mirrored = "raw_backup_local_mirror" in doc
        if mirrored:
            need(_mirror_valid(run, doc)["partition"] == "development" or allow_sealed is True,
                 "Sealed result requires the archive operator")
        raw = run / RAW
        if _exists(raw):
            return dict(run_id=run.name, action="restore", restored=False, already_materialized=True)
        need(doc["raw_backup_retired"] is False, "Lossless raw backup was retired after completed review")
        pending = []
        try:
            temp = _temp(run, pending)
            backup = run / RAW_GZ
            fetched = False
            if not _exists(backup) and (mirrored or doc.get("raw_backup_offloaded") is True):
                backup = _temp(run, pending)
                if mirrored:
                    _fetch_mirror(run, doc, mirror_run, backup, allow_sealed)
                else:
                    (fetcher or _default_fetcher)(run, doc, backup)
                raw_entry = doc["artifacts"][RAW_GZ]
                need(_file_record(backup) == raw_entry,
                     "Fetched raw gzip backup SHA/size differs")
                fetched = True
            backup_signature = _signature(_not_link(backup))
            with _open(temp, os.O_WRONLY | os.O_TRUNC, "wb") as target:
                _verify_raw_backup(backup, manifest["results_sha256"], doc["original_archive_bytes"], target)
                target.flush()
                os.fsync(target.fileno())
            _unchanged(backup, backup_signature)
            _same_manifest(run, doc["manifest_sha256"])
            # A hard-link install is atomic and exclusive; unlike replace it
            # cannot clobber a file installed by an uncooperative legacy reader.
            os.link(temp, raw)
            temp.unlink()
            _sync_dir(run)
            return dict(run_id=run.name, action="restore", restored=True,
                        already_materialized=False, fetched_from_offload=fetched)
        finally:
            for path in pending:
                path.unlink(missing_ok=True)


def rehydrate(run_dir, fetcher=None):
    """Pull an offloaded raw backup back to local disk and revert offload flag."""
    run = _run_path(run_dir)
    with _lock(run):
        manifest, _ = _manifest(run)
        doc = _verify(run, manifest)
        need(doc["raw_backup_retired"] is False, "Lossless raw backup was retired after completed review")
        backup = run / RAW_GZ
        raw_entry = doc["artifacts"][RAW_GZ]
        pending = []
        pulled = False
        try:
            if not _exists(backup):
                need(doc.get("raw_backup_offloaded") is True, "Missing local backup and offload record")
                temp_gz = _temp(run, pending)
                (fetcher or _default_fetcher)(run, doc, temp_gz)
                need(_not_link(temp_gz).st_size == raw_entry["bytes"] and _sha(temp_gz) == raw_entry["sha256"],
                     "Fetched raw gzip backup SHA/size differs")
                _verify_raw_backup(temp_gz, manifest["results_sha256"], doc["original_archive_bytes"])
                _publish(temp_gz, backup)
                pending.remove(temp_gz)
                pulled = True
            if doc.get("raw_backup_offloaded", False):
                before = copy.deepcopy(doc)
                doc["raw_backup_offloaded"] = False
                receipt = _temp(run, pending)
                with _open(receipt, os.O_WRONLY | os.O_TRUNC, "wb") as stream:
                    stream.write((json.dumps(doc, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                _publish(receipt, run / RECEIPT)
                pending.remove(receipt)
                if not verify_retained(run, manifest):
                    fallback = _temp(run, pending)
                    with _open(fallback, os.O_WRONLY | os.O_TRUNC, "wb") as stream:
                        stream.write((json.dumps(before, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
                        stream.flush()
                        os.fsync(stream.fileno())
                    _publish(fallback, run / RECEIPT)
                    pending.remove(fallback)
                    raise ValueError("Rehydrated retention receipt failed verification")
            return dict(run_id=run.name, action="rehydrate", pulled=pulled, raw_backup_offloaded=False)
        finally:
            for path in pending:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("compact", "restore", "verify", "dematerialize", "rehydrate"))
    parser.add_argument("run", type=Path)
    parser.add_argument("--mirror-run", type=Path)
    parser.add_argument("--allow-sealed", action="store_true", help="Archive operator only")
    args = parser.parse_args()
    try:
        if args.action == "verify":
            manifest, _ = _manifest(_run_path(args.run))
            result = dict(verified=verify_retained(args.run, manifest))
            print(json.dumps(result))
            return 0 if result["verified"] else 1
        if args.action == "restore":
            result = restore(args.run, mirror_run=args.mirror_run, allow_sealed=args.allow_sealed)
        else:
            result = globals()[args.action](args.run)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, EOFError, tarfile.TarError) as exc:
        parser.exit(1, "Retention refused: %s\n" % exc)


if __name__ == "__main__":
    raise SystemExit(main())
