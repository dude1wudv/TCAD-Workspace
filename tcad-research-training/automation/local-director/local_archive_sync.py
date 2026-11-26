"""Mirror a collected TCAD run from a local, complete retention bundle.

Use the original trusted Runtime ledger and frozen r0.6 plan. Supply separate,
existing archive roots and restrict the sealed root to the archive operator.
pull-verify reads an already mounted or locally staged source; it never opens a
network connection, writes source receipts, or removes source files. Keep the
state directory private and export only archive-summary.json.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parents[1] / "server-codex" / "retention.py"
SPEC = importlib.util.spec_from_file_location("_phase0_retention", SOURCE)
ret = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ret)
INDEX_SCHEMA = "tcad-result-archive-index-v1"
SUMMARY_SCHEMA = "tcad-result-archive-summary-v1"


def _overlaps(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _roots(run, development_root, sealed_root):
    roots = tuple(ret._checked_path(path) for path in (development_root, sealed_root))
    ret.need(not _overlaps(*roots), "Archive roots must be separate")
    listing = subprocess.check_output(
        ["git", "-C", str(SOURCE.parent), "worktree", "list", "--porcelain", "-z"])
    worktrees = [Path(item[9:].decode("utf-8")).resolve()
                 for item in listing.split(b"\0") if item.startswith(b"worktree ")]
    ret.need(worktrees, "Unable to verify repository locations")
    for root in roots:
        ret.need(root.is_dir() and not _overlaps(root, run.parent)
                 and not any(_overlaps(root, worktree) for worktree in worktrees)
                 and not any(ret._exists(parent / ".git") for parent in (root, *root.parents)),
                 "Archive roots must be outside repositories and the source runs tree")
    return roots


def _check_run_id(run_id):
    ret.need(isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id)
             and not re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", run_id, re.IGNORECASE),
             "Run ID is not portable")


def _mirror(run, source_root, *, runtime_state, case_manifest, development_root, sealed_root,
            allow_sealed=False, state_dir=None):
    _check_run_id(run.name)
    manifest, manifest_sha = ret._manifest(run)
    partition = ret.archive_partition(manifest, runtime_state, case_manifest)
    ret.need(partition == "development" or allow_sealed is True, "Sealed result requires the archive operator")
    dev, sealed = _roots(run, development_root, sealed_root)
    ret.need(not any(_overlaps(root, source_root) for root in (dev, sealed)), "Archive overlaps source root")
    if state_dir is not None:
        state_dir = Path(state_dir).resolve()
        ret.need(not any(state_dir.is_relative_to(root) for root in (source_root, dev, sealed)),
                 "Archive state must be outside the source and archive roots")
    target_root = sealed if partition == "sealed" else dev
    archive = target_root / "runs"
    dest = archive / run.name
    doc, retention_sha = ret._json(run / ret.RECEIPT)
    if ret._exists(dest):
        ret.need(ret.verify_retained(run, manifest), "Source retention failed verification")
        proof = ret._match_mirror(run, doc, dest)
        ret.need(proof["partition"] == partition, "Existing mirror partition differs")
    else:
        with tempfile.TemporaryDirectory(prefix=".mirror-", dir=target_root) as temporary:
            staged_runs = Path(temporary) / "runs"
            staged_runs.mkdir(mode=0o700)
            staged = staged_runs / run.name
            staged.mkdir(mode=0o700)
            for name in ret.mirror_inventory(doc):
                ret._copy_file(run / name, staged / name)
            proof = ret.mirror_snapshot(staged, partition)
            ret.need(proof["manifest_sha256"] == manifest_sha and proof["retention_sha256"] == retention_sha
                     and ret._sha(run / ret.RECEIPT) == retention_sha
                     and ret._sha(run / ret.GUEST_RECEIPT) == proof["guest_reclaim_sha256"],
                     "Source evidence changed while mirroring")
            ret._same_manifest(run, manifest_sha)
            ret._write_record(staged, ret.MIRROR_RECEIPT, proof)
            if ret._exists(archive):
                ret._checked_path(archive)
                ret.need(not ret._exists(dest), "Mirror destination appeared during publication")
                staged.rename(dest)
                ret._sync_dir(archive)
            else:
                ret._sync_dir(staged_runs)
                staged_runs.rename(archive)
                ret._sync_dir(target_root)
    result = {"verified": True, "mirrored": 1}
    if state_dir is not None:
        result["summary"] = _write_summary(state_dir, dest)
    return result


def _write_summary(state, verified_mirror):
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    state = ret._checked_path(state)
    index_name = "archive-index.json"
    run_key = hashlib.sha256(verified_mirror.name.casefold().encode("ascii")).hexdigest()
    receipt_sha = ret._sha(verified_mirror / ret.MIRROR_RECEIPT)
    with ret._lock(state):
        index = {"schema": INDEX_SCHEMA, "receipts": {}}
        if ret._exists(state / index_name):
            index, _ = ret._json(state / index_name)
        receipts = index["receipts"]
        ret.need(index["schema"] == INDEX_SCHEMA and isinstance(receipts, dict)
                 and all(ret.HEX.fullmatch(key) and isinstance(value, str) and ret.HEX.fullmatch(value)
                         for key, value in receipts.items()), "Invalid archive index")
        ret.need(receipts.get(run_key, receipt_sha) == receipt_sha, "Conflicting archive receipt for run")
        if run_key not in receipts:
            receipts[run_key] = receipt_sha
            ret._write_record(state, index_name, index)
        summary = dict(schema=SUMMARY_SCHEMA, mirrored=len(receipts), cloud_verified=0)
        ret._write_record(state, "archive-summary.json", summary)
    return summary


def mirror_run(run_dir, *, runtime_state, case_manifest, development_root, sealed_root,
               allow_sealed=False, state_dir=None):
    """Publish an immutable bundle atomically and optionally update aggregate counts."""
    run = ret._run_path(run_dir)
    return _mirror(run, run.parent, runtime_state=runtime_state, case_manifest=case_manifest,
                   development_root=development_root, sealed_root=sealed_root,
                   allow_sealed=allow_sealed, state_dir=state_dir)


def pull_verify(remote_root, run_id, *, runtime_state, case_manifest, development_root,
                sealed_root, allow_sealed=False, state_dir=None):
    """Verify and mirror an already locally reachable source, without writing to it."""
    _check_run_id(run_id)
    remote = ret._checked_path(remote_root)
    source = ret._run_path(remote / "runs" / run_id)
    return _mirror(source, remote, runtime_state=runtime_state, case_manifest=case_manifest,
                   development_root=development_root, sealed_root=sealed_root,
                   allow_sealed=allow_sealed, state_dir=state_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mirror", "pull-verify"))
    parser.add_argument("run_dir", type=Path, nargs="?")
    for option in ("runtime-state", "case-manifest", "development-root", "sealed-root"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--remote-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--allow-sealed", action="store_true", help="Archive operator only")
    args = vars(parser.parse_args())
    action = args.pop("action")
    try:
        run_dir = args.pop("run_dir")
        remote_root = args.pop("remote_root")
        run_id = args.pop("run_id")
        if action == "mirror":
            ret.need(run_dir is not None and remote_root is None and run_id is None,
                     "mirror requires a local run directory")
            result = mirror_run(run_dir, **args)
        else:
            ret.need(run_dir is None and remote_root is not None and isinstance(run_id, str) and run_id,
                     "pull-verify requires --remote-root and --run-id")
            result = pull_verify(remote_root, run_id, **args)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        parser.exit(2, "Archive refused: check local evidence and root permissions.\n")


if __name__ == "__main__":
    raise SystemExit(main())
