"""Report local director prerequisites without changing the workspace."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfoNotFoundError
from pathlib import Path

from config import Config, load_config
from probes import probe_server
from schemas import utc_now


def _git_check(cfg: Config) -> dict:
    command = ["git", "--no-optional-locks", "-C", str(cfg.repo_root)]
    try:
        branch = subprocess.run([*command, "branch", "--show-current"], check=True,
                                capture_output=True, timeout=10).stdout.decode("utf-8", errors="replace").strip()
        status = subprocess.run([*command, "status", "--porcelain=v1", "-z", "--untracked-files=normal"],
                                check=True, capture_output=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": type(error).__name__}
    return {"ok": branch == cfg.branch_name, "branch": branch or None,
            "expected_branch": cfg.branch_name, "dirty": bool(status)}


def _power_check() -> dict:
    if os.name != "nt":
        return {"applicable": False}
    try:
        result = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
                                check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        return {"applicable": True, "ok": False, "error": type(error).__name__}
    values = re.findall(rb"0x([0-9a-f]{8})\s*$", result.stdout, flags=re.IGNORECASE | re.MULTILINE)
    if len(values) < 2:
        return {"applicable": True, "ok": False, "error": "sleep timers unavailable"}
    ac, dc = (int(value, 16) for value in values[-2:])
    return {"applicable": True, "ok": ac == 0, "ac_sleep_seconds": ac, "dc_sleep_seconds": dc}


def _executable_available(name: str) -> bool:
    if shutil.which(name):
        return True
    if os.name == "nt":
        return any(shutil.which(f"{name}{extension}") for extension in (".cmd", ".ps1", ".exe"))
    return False


def run_preflight(cfg: Config, *, offline: bool = False) -> dict:
    python = {"ok": sys.version_info >= (3, 13), "version": ".".join(map(str, sys.version_info[:3]))}
    git = _git_check(cfg)
    tools = {name: _executable_available(name) for name in ("codex", "agentapi", "xelatex", "latexmk", "gh")}
    power = _power_check()
    paths = {"state_dir": cfg.state_dir.is_dir(), "thesis_dir": (cfg.repo_root / "论文草稿").is_dir()}
    if offline:
        server = {"skipped": True, "ssh_configured": bool(cfg.server_ssh_target)}
    else:
        snap = probe_server(cfg)
        server = {"online": snap["online"], "source": snap["source"],
                  "service_active": snap["service_active"], "errors": snap["errors"],
                  "ssh_configured": bool(cfg.server_ssh_target)}
    return {
        "ok": all((python["ok"], git["ok"], *tools.values(), power.get("ok", True),
                   *paths.values(), offline or server.get("online"))),
        "generated_at": utc_now(), "python": python, "git": git, "tools": tools,
        "power": power, "paths": paths, "server": server,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--offline", action="store_true", help="Skip SSH and the public status request")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, ZoneInfoNotFoundError) as error:
        report = {"ok": False, "generated_at": utc_now(), "config_error": type(error).__name__}
    else:
        report = run_preflight(cfg, offline=args.offline)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
