#!/usr/bin/env python3
"""Package the current working source, not HEAD or private runtime/results.

The manifest lists every included SHA and every excluded candidate with a reason.
This is preparation only: no SSH, Codex, model request or simulation is invoked.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUFFIXES = {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".scm", ".cmd", ".tcl", ".sh", ".cc", ".cpp", ".h", ".c", ".csv", ".service"}
EXCLUDED = {
    "__pycache__", "local_runtime", ".git", ".venv", "node_modules", "data", "figures",
    "screenshots", "runs", "results", "archives", "archive", "submissions", "sources",
    "raw", "outputs", "logs", ".cache",
}
TOPS = ("scripts", "automation/server-codex", "design-notes", "courses", "shared", "skills", "experiments", "plans")
RUNTIME = ("controller.py", "task.md", "report.schema.json", "policy.example.json",
           "operator-task.example.md", "readiness.example.json", "tcad-autonomy.service",
           "runtime.py", "watchdog.py", "test_runtime.py", "test_watchdog.py", "work-items.example.json", "test_controller.py",
           "test_integration.py", "test_deployment.py", "install.py", "package.py", "README.md",
           "advisor.py", "astra_advisor.toml", "test_advisor.py", "verify_advisor.py", "ADVISOR.md",
           "retention.py", "result_maintenance.py", "gdrive_offload.py",
           "test_retention.py", "test_result_maintenance.py", "test_gdrive_offload.py",
           "r06_gate.py", "intent_reconciliation.py")


def package(destination, runtime_only=False):
    files, excluded = {}, {}
    candidates = set()
    if not runtime_only:
        candidates = {ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "docs/server-workflow.md",
                      ROOT / "docs/server-codex.md"}
        for top in TOPS:
            candidates.update(p for p in (ROOT / top).rglob("*") if p.is_file())
    for path in sorted(candidates):
        rel = path.relative_to(ROOT)
        if rel.parts[0] == "plans" and rel.name == "work-items.json":
            excluded[rel.as_posix()] = "live execution proposals require a separate reviewed handoff"
            continue
        if (set(rel.parts) & EXCLUDED or path.suffix not in SUFFIXES
                or path.name.startswith(("connection", ".env", "id_")) or path.is_symlink()):
            excluded[rel.as_posix()] = "non-source, raw evidence, private runtime, or unsupported asset"
            continue
        if path.stat().st_size > 4 * 1024**2:
            excluded[rel.as_posix()] = "large asset; requires separate reviewed handoff"
            continue
        files["project/" + rel.as_posix()] = path.read_bytes()
    for name in RUNTIME:
        files["runtime/" + name] = (HERE / name).read_bytes()
    example = json.loads(files["runtime/work-items.example.json"])
    if example.get("schema") != "tcad-work-items-v1" or example.get("tasks") != []:
        raise ValueError("Runtime work-items example must contain an empty task list")
    # Refuse likely live credentials without ever printing the matched value.
    secret_pattern = re.compile(
        rb"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|"
        rb"\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,})\b|"
        rb"(?i:(?:api_key|bearer_token|password)\s*[=:]\s*[\"'][A-Za-z0-9_+./=-]{24,}[\"'])"
    )
    for name, data in files.items():
        if secret_pattern.search(data):
            raise ValueError("Review possible credential before packaging: " + name)
    manifest = {
        "schema": "tcad-server-source-snapshot-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": ("Controller runtime files only" if runtime_only else
                      "Current dirty working source snapshot, not a full checkout or accepted scientific state migration"),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "excluded": excluded,
    }
    files["SNAPSHOT.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Do not overwrite a previous deployment bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
    return {
        "bundle": str(destination.resolve()), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "files": len(files) - 1, "excluded": len(excluded), "bytes": destination.stat().st_size,
        "source_state_only": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-only", action="store_true", help="Package only the controller runtime files")
    args = parser.parse_args()
    print(json.dumps(package(args.output, runtime_only=args.runtime_only), ensure_ascii=False, indent=2))
