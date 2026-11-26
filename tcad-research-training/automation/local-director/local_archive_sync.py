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
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile

SOURCE = Path(__file__).resolve().parents[1] / "server-codex" / "retention.py"
SPEC = importlib.util.spec_from_file_location("_phase0_retention", SOURCE)
ret = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ret)
INDEX_SCHEMA = "tcad-result-archive-index-v1"
SUMMARY_SCHEMA = "tcad-result-archive-summary-v1"


def _hidden_kwargs():
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flag} if flag else {}
    return {}


def _overlaps(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _roots(run, development_root, sealed_root):
    roots = tuple(ret._checked_path(path) for path in (development_root, sealed_root))
    ret.need(not _overlaps(*roots), "Archive roots must be separate")
    listing = subprocess.check_output(
        ["git", "-C", str(SOURCE.parent), "worktree", "list", "--porcelain", "-z"],
        **_hidden_kwargs(),
    )
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


def ssh_pull_verify(ssh_target, remote_runs_root, run_id, *, remote_runtime_state, case_manifest,
                    development_root, sealed_root, allow_sealed=False, state_dir=None, write_back=False):
    """Pull a completed retained run bundle over SSH, verify SHA-256 + gzip stream, and publish to local archive."""
    _check_run_id(run_id)
    ret.need(bool(re.fullmatch(r"[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?", ssh_target)) and not ssh_target.startswith("-"),
             "Invalid SSH target")
    ret.need(remote_runs_root.startswith("/") and remote_runtime_state.startswith("/"),
             "Remote paths must be absolute")
    remote_run = f"{remote_runs_root.rstrip('/')}/{run_id}"
    with tempfile.TemporaryDirectory(prefix=".ssh-pull-") as tmp:
        stage = Path(tmp)
        runtime_local = stage / "runtime.json"
        staged_runs = stage / "runs"
        staged_run = staged_runs / run_id
        staged_run.mkdir(parents=True, mode=0o700)
        rt_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", ssh_target,
                  f"cat -- {shlex.quote(remote_runtime_state)}"]
        rt_res = subprocess.run(rt_cmd, capture_output=True, timeout=60, check=True, **_hidden_kwargs())
        runtime_local.write_bytes(rt_res.stdout)
        tar_script = (
            f"set -eu; d={shlex.quote(remote_run)}; "
            'cd "$d"; files="manifest.json retention.json guest-reclaim.json"; '
            'for f in results.raw.tar.gz results.essential.tar.gz results.log-witness.jsonl.gz; do '
            '[ -f "$f" ] && files="$files $f"; done; tar -cf - $files'
        )
        tar_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", ssh_target, tar_script]
        tar_res = subprocess.run(tar_cmd, capture_output=True, timeout=600, check=True, **_hidden_kwargs())
        with tarfile.open(fileobj=io.BytesIO(tar_res.stdout), mode="r:") as archive_stream:
            for member in archive_stream.getmembers():
                ret.need(member.isfile() and "/" not in member.name and "\\" not in member.name
                         and not member.name.startswith("."), "Unsafe member in remote bundle")
                extracted = archive_stream.extractfile(member)
                ret.need(extracted is not None, "Missing stream member")
                (staged_run / member.name).write_bytes(extracted.read())
        result = _mirror(staged_run, stage, runtime_state=runtime_local, case_manifest=case_manifest,
                         development_root=development_root, sealed_root=sealed_root,
                         allow_sealed=allow_sealed, state_dir=state_dir)
        if write_back:
            manifest, _ = ret._manifest(staged_run)
            partition = ret.archive_partition(manifest, runtime_local, case_manifest)
            target_root = Path(sealed_root if partition == "sealed" else development_root)
            receipt_bytes = (target_root / "runs" / run_id / ret.MIRROR_RECEIPT).read_bytes()
            remote_receipt = f"{remote_run}/{ret.MIRROR_RECEIPT}"
            wb_script = (
                f"set -eu; t={shlex.quote(remote_receipt)}; "
                's=$(mktemp -- "${t}.XXXXXX"); trap \'rm -f -- "$s"\' EXIT; '
                'cat > "$s"; chmod 0644 -- "$s"; mv -fT -- "$s" "$t"'
            )
            wb_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", ssh_target, wb_script]
            subprocess.run(wb_cmd, input=receipt_bytes, capture_output=True, timeout=30, check=True, **_hidden_kwargs())
            result["receipt_written_back"] = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mirror", "pull-verify", "ssh-pull"))
    parser.add_argument("run_dir", type=Path, nargs="?")
    for option in ("runtime-state", "case-manifest", "development-root", "sealed-root"):
        parser.add_argument("--" + option, required=False, type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--remote-root", type=Path)
    parser.add_argument("--ssh-target")
    parser.add_argument("--remote-runs-root")
    parser.add_argument("--remote-runtime-state")
    parser.add_argument("--write-back", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--allow-sealed", action="store_true", help="Archive operator only")
    args = vars(parser.parse_args())
    action = args.pop("action")
    try:
        run_dir = args.pop("run_dir")
        remote_root = args.pop("remote_root")
        ssh_target = args.pop("ssh_target")
        remote_runs_root = args.pop("remote_runs_root")
        remote_runtime_state = args.pop("remote_runtime_state")
        write_back = args.pop("write_back")
        run_id = args.pop("run_id")
        if action == "mirror":
            ret.need(run_dir is not None and remote_root is None and run_id is None
                     and args["runtime_state"] is not None,
                     "mirror requires a local run directory and --runtime-state")
            result = mirror_run(run_dir, **args)
        elif action == "pull-verify":
            ret.need(run_dir is None and remote_root is not None and isinstance(run_id, str) and run_id
                     and args["runtime_state"] is not None,
                     "pull-verify requires --remote-root, --run-id, and --runtime-state")
            result = pull_verify(remote_root, run_id, **args)
        else:
            args.pop("runtime_state", None)
            ret.need(bool(ssh_target and remote_runs_root and remote_runtime_state and run_id),
                     "ssh-pull requires --ssh-target, --remote-runs-root, --remote-runtime-state, and --run-id")
            result = ssh_pull_verify(
                ssh_target, remote_runs_root, run_id,
                remote_runtime_state=remote_runtime_state, write_back=write_back, **args,
            )
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        parser.exit(2, "Archive refused: check local evidence and root permissions.\n")


if __name__ == "__main__":
    raise SystemExit(main())
