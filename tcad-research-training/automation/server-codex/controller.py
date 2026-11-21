#!/usr/bin/env python3
"""Event-driven research engineer; the original runners still own solver jobs.

Inspection and migration are offline. Nothing runs while policy is disabled.
Codex plans/repairs inputs; Runtime alone submits them through original runners.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid


HERE = Path(__file__).resolve().parent
SCHEMA = "tcad-server-codex-v2"
DEFAULTS = {
    "poll_interval_seconds": 30, "runner_timeout_seconds": 120,
    "failure_backoff_seconds": 300, "max_failure_backoff_seconds": 3600,
    "repair_attempt_limit": 2,
}
REPORT_KEYS = {"status", "summary", "next_step", "next_check_seconds", "evidence"}
_ADVISOR = None


def advisor_module():
    global _ADVISOR
    if _ADVISOR is None:
        spec = importlib.util.spec_from_file_location("tcad_native_advisor", HERE / "advisor.py")
        _ADVISOR = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ADVISOR)
    return _ADVISOR


class Refused(RuntimeError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat() if path.exists() else None
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as stream:
            if os.name != "nt":
                if previous is not None:
                    os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def validate_watchdog(cfg):
    if not isinstance(cfg, dict):
        raise Refused("watchdog must be an object")
    for key in ("enabled", "auto_stop"):
        if (key == "enabled" or key in cfg) and type(cfg.get(key)) is not bool:
            raise Refused("watchdog." + key + " must be a boolean")

    def positive(value):
        return type(value) in (int, float) and 0 < value < float("inf")

    for key in ("stall_window_seconds", "min_progress_ns_per_hour", "min_stepsize_s"):
        if key in cfg and not positive(cfg[key]):
            raise Refused("Invalid watchdog limit: " + key)
    rejections = cfg.get("max_consecutive_rejections", 40)
    if type(rejections) is not int or rejections <= 0:
        raise Refused("Invalid watchdog limit: max_consecutive_rejections")
    caps = cfg.get("max_wall_seconds_by_width", {})
    if not isinstance(caps, dict) or any(
        not re.fullmatch(r"[1-9][0-9]*", width) or not positive(cap) for width, cap in caps.items()
    ):
        raise Refused("Invalid watchdog limit: max_wall_seconds_by_width")
    windows = cfg.get("exempt_windows_ns", [])
    if not isinstance(windows, list) or any(
        not isinstance(window, list) or len(window) != 2
        or any(type(bound) not in (int, float) for bound in window)
        or not 0 <= window[0] <= window[1] < float("inf")
        for window in windows
    ):
        raise Refused("Invalid watchdog window: exempt_windows_ns")


def policy_at(path):
    policy = read_json(path)
    if policy.get("schema") != SCHEMA:
        raise Refused("Unsupported policy schema; use migrate for a disabled v2 policy")
    policy = dict(DEFAULTS, **policy)
    for name in ("workspace", "state_dir", "source_codex_config", "codex_binary",
                 "runner_python", "task_file", "plan_file", "queue_file"):
        if not isinstance(policy.get(name), str) or not Path(policy[name]).is_absolute():
            raise Refused("Policy requires an absolute path: " + name)
    if type(policy.get("enabled")) is not bool:
        raise Refused("enabled must be a boolean")
    transport_file = policy.get("transport_connection_file")
    if transport_file is not None and (not isinstance(transport_file, str) or not Path(transport_file).is_absolute()):
        raise Refused("transport_connection_file must be an absolute path")
    for key, low, high in (
        ("cycle_timeout_seconds", 60, 1200), ("minimum_interval_seconds", 60, 86400),
        ("maximum_cycles_per_start", 0, 10000), ("max_parallel_jobs", 1, 64),
        ("poll_interval_seconds", 1, 3600), ("runner_timeout_seconds", 10, 3600),
        ("failure_backoff_seconds", 1, 86400), ("max_failure_backoff_seconds", 1, 86400),
        ("repair_attempt_limit", 0, 10),
    ):
        value = policy.get(key)
        if type(value) is not int or not low <= value <= high:
            raise Refused("Invalid policy limit: " + key)
    workspace, state = Path(policy["workspace"]).resolve(), Path(policy["state_dir"]).resolve()
    if state == workspace or workspace in state.parents:
        raise Refused("Controller state must be outside the model workspace")
    for key in ("plan_file", "queue_file"):
        if workspace not in Path(policy[key]).resolve().parents:
            raise Refused(key + " must belong to the configured workspace")
    if policy["max_failure_backoff_seconds"] < policy["failure_backoff_seconds"]:
        raise Refused("Maximum backoff must not be shorter than initial backoff")
    if "watchdog" in policy:
        validate_watchdog(policy["watchdog"])
    if "planner_mode" in policy and policy["planner_mode"] not in ("disabled", "on_demand_async", "legacy_compat"):
        raise Refused("Invalid planner_mode; expected disabled, on_demand_async, or legacy_compat")
    if "collect_concurrency" in policy:
        cc = policy["collect_concurrency"]
        if type(cc) is not int or not 1 <= cc <= 16:
            raise Refused("Invalid policy limit: collect_concurrency")
    return policy


def migrate_policy(path, output=None):
    """Explicit, disabled migration; preserve the original policy byte-for-byte."""
    path = Path(path)
    old = read_json(path)
    if old.get("schema") not in ("tcad-server-codex-v1", SCHEMA):
        raise Refused("Cannot migrate unknown schema")
    new = dict(DEFAULTS, **old)
    base = Path(old["workspace"]) / "plans/dram-se-ddr5-lpddr5"
    new.update(schema=SCHEMA, enabled=False, readiness=None, max_parallel_jobs=9)
    new.setdefault("plan_file", str(base / "PLAN.md"))
    new.setdefault("queue_file", str(base / "work-items.json"))
    new.setdefault("runner_python", "/opt/tcad-autonomy/python/bin/python3")
    new["maximum_cycles_per_start"] = 0
    target = Path(output) if output else path
    backup = None
    if target.exists() and target.resolve() != path.resolve():
        raise Refused("Migration output exists; preserve it")
    if target.resolve() == path.resolve():
        backup = path.with_name(path.name + ".before-v2-" + uuid.uuid4().hex[:8])
        # Exact original bytes, private file, no credentials printed.
        with backup.open("xb") as stream:
            stream.write(path.read_bytes())
        if os.name != "nt":
            os.chmod(backup, 0o600)
    write_json(target, new)
    return {"policy": str(target), "backup": str(backup) if backup else None,
            "enabled": False, "codex_started": False, "max_parallel_jobs": 9}


def toml_string(text, section, key, required=True):
    """Read a single scalar from an existing config, without rewriting Magpie.

    Deliberately bounded: multiline strings or complex auth must be migrated by
    the operator rather than guessed. The installed Magpie config uses these
    single-line scalars; no general TOML parser dependency is needed on EL9.
    """
    active = ""
    matches = []
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("[") and value.endswith("]"):
            active = value[1:-1]
        elif active == section and re.match(re.escape(key) + r"\s*=", value):
            raw = value.split("=", 1)[1].strip()
            if raw.startswith('"'):
                parsed, end = json.JSONDecoder().raw_decode(raw)
                if raw[end:].strip() and not raw[end:].lstrip().startswith("#"):
                    raise Refused("Unsupported source config scalar: " + key)
            elif re.fullmatch(r"'[^'\r\n]*'\s*(?:#.*)?", raw):
                parsed = raw.split("'", 2)[1]
            else:
                raise Refused("Unsupported source config scalar: " + key)
            if not isinstance(parsed, str):
                raise Refused("Source config scalar must be a string: " + key)
            matches.append(parsed)
    if len(matches) > 1 or (required and not matches):
        raise Refused("Missing or duplicate source config scalar: " + key)
    return matches[0] if matches else None


def route_at(policy):
    text = Path(policy["source_codex_config"]).read_text(encoding="utf-8")
    provider = toml_string(text, "", "model_provider")
    if provider != "magpie":
        raise Refused("Source Codex must already use the server's Magpie provider")
    section = "model_providers." + provider
    base = toml_string(text, section, "base_url")
    url = urlsplit(base)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1", "localhost")
            or url.username or url.password or url.query or url.fragment
            or url.path.rstrip("/") != "/v1"):
        raise Refused("Use the server-local loopback Magpie /v1 endpoint")
    if toml_string(text, section, "wire_api") != "responses":
        raise Refused("The validated Magpie route must use responses")
    env_key = toml_string(text, section, "env_key", required=False)
    secret = os.environ.get(env_key, "") if env_key else ""
    secret = secret or toml_string(text, section, "experimental_bearer_token", required=False)
    if not secret:
        raise Refused("Magpie credential unavailable; no login or account switching is attempted")
    return {
        "model": toml_string(text, "", "model"),
        "effort": toml_string(text, "", "model_reasoning_effort", required=False) or "high",
        "base_url": base,
        "catalog": toml_string(text, "", "model_catalog_json", required=False),
        "secret": secret,
    }


def resolve_ref_path(ref):
    """Accept either an absolute path string or a legacy {path, sha256?} dict."""
    raw = ref if isinstance(ref, str) else ref.get("path") if isinstance(ref, dict) else None
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        return None
    path = Path(raw)
    if path.is_symlink() or not path.is_file():
        return None
    return path.resolve()


def reference_ok(ref):
    return resolve_ref_path(ref) is not None


def readiness_at(policy):
    ready_path = resolve_ref_path(policy.get("readiness"))
    if ready_path is None:
        raise Refused("Readiness file is absent or invalid")
    ready = read_json(ready_path)
    if (ready.get("schema") != SCHEMA or ready.get("new_jobs_authorized") is not True
            or ready.get("controller_owner") != "server-codex"
            or ready.get("sole_scheduler") is not True):
        raise Refused("Readiness must explicitly authorize this sole controller")
    if ready.get("workspace") != policy["workspace"]:
        raise Refused("Readiness belongs to a different server workspace")
    if ready.get("max_parallel_jobs") != policy["max_parallel_jobs"]:
        raise Refused("Parallel limit differs from accepted readiness")
    if ready.get("plan_file") != policy["plan_file"]:
        raise Refused("Handoff belongs to a different research plan")
    profile_path = resolve_ref_path(ready.get("connection"))
    if profile_path is None:
        raise Refused("Connection profile missing or invalid")
    profile = read_json(profile_path)
    if profile.get("backend") != "ssh-runtime":
        raise Refused("Server controller requires the original ssh-runtime backend")
    try:
        module = runtime_module()
        capacity = module.profile_resources(profile)["capacity"]
        transport = module.transport_profile(policy, ready, profile)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise Refused(str(exc)) from exc
    if policy["max_parallel_jobs"] > capacity:
        raise Refused("Parallel limit exceeds the original runner profile capacity")
    target = profile.get("ssh_target", "")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", target)
            or target.lower() in {"hk", "hk-tail", "hk-live", "sub2"}
            or re.fullmatch(r"[\d.]+", target)):
        raise Refused("Use an explicit TCAD guest SSH alias, never a business host or IP")
    state = Path(profile.get("local_state_root", "")).resolve()
    base = (Path(policy["workspace"]) / "local_runtime/cloud-benchmark").resolve()
    if base not in state.parents:
        raise Refused("Profile state must belong to this server checkout")
    for key in ("remote_root", "runtime_entry", "tool_bin"):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(profile.get(key, ""))):
            raise Refused("Invalid original runner profile field: " + key)
    if transport and not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(transport["cfg"].get("tool_bin", ""))):
        raise Refused("Invalid original transport profile tool_bin")
    return ready


def inspect(policy):
    errors = []
    route = {}
    try:
        route = {k: v for k, v in route_at(policy).items() if k != "secret"}
    except (Refused, OSError, ValueError) as exc:
        errors.append(str(exc))
    for relative in (
        "AGENTS.md", "scripts/tcad.py",
        "experiments/dram-see-v4/transport-probe/operation.py",
        "courses/README.md", "shared/research-brief.md",
    ):
        if not (Path(policy["workspace"]) / relative).is_file():
            errors.append("Workspace source missing: " + relative)
    for name in ("task_file", "codex_binary", "runner_python", "plan_file"):
        if not Path(policy[name]).is_file():
            errors.append("Required file missing: " + name)
    try:
        readiness_at(policy)
    except (Refused, OSError, ValueError) as exc:
        errors.append(str(exc))
    state = Path(policy["state_dir"])
    paused = read_json(state / "pause.json") if (state / "pause.json").exists() else None
    checkpoint = read_json(state / "checkpoint.json") if (state / "checkpoint.json").exists() else None
    return {
        "utc": utc(), "enabled": policy["enabled"], "prerequisites_passed": not errors,
        "ready_to_start": policy["enabled"] and not errors and paused is None,
        "errors": errors, "route": route, "max_parallel_jobs": policy["max_parallel_jobs"],
        "pause": paused, "checkpoint": checkpoint,
        "recovery_on_start": bool(checkpoint and checkpoint.get("state") in
                                 ("running", "uncertain", "retry_wait")),
        "execution_state": read_json(state / "runtime.json") if (state / "runtime.json").exists() else None,
    }


@contextmanager
def instance_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise Refused("Another server Codex controller owns the lifecycle lock")
    try:
        yield
    finally:
        # Closing releases the lock even after abnormal child/session failures.
        stream.close()


def pause(policy, reason, reconcile=False):
    write_json(Path(policy["state_dir"]) / "pause.json",
               {"utc": utc(), "reason": reason, "reconcile_required": reconcile})


def initialize(policy):
    state = Path(policy["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    (state / "cycles").mkdir(exist_ok=True)
    (state / "codex-home").mkdir(exist_ok=True)
    if os.name != "nt":
        os.chmod(state, 0o700)
    return {"initialized": True, "enabled": policy["enabled"], "codex_started": False}


def prepare_codex(policy, route):
    home = Path(policy["state_dir"]) / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    q = lambda value: json.dumps(str(value), ensure_ascii=False)
    lines = [
        'model_provider = "magpie"', "model = " + q(route["model"]),
        "model_reasoning_effort = " + q(route["effort"]), 'approval_policy = "never"',
        'sandbox_mode = "workspace-write"',
    ]
    if route.get("catalog"):
        if not Path(route["catalog"]).is_file():
            raise Refused("Source Magpie model catalog is missing")
        lines.append("model_catalog_json = " + q(route["catalog"]))
    lines += [
        "[sandbox_workspace_write]", "network_access = true",
        "[model_providers.magpie]", 'name = "Server-local Magpie"',
        "base_url = " + q(route["base_url"]), 'wire_api = "responses"',
        'env_key = "TCAD_MAGPIE_API_KEY"', "requires_openai_auth = false",
        'http_headers = { "x-magpie-agent" = "codex" }',
    ]
    lines += advisor_module().configure(home)
    config = home / "config.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(config, 0o600)
    env = dict(os.environ)
    # Inference uses the host's existing network; SSH must not inherit a laptop proxy.
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_HOME",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env.update(CODEX_HOME=str(home), TCAD_MAGPIE_API_KEY=route["secret"],
               GIT_TERMINAL_PROMPT="0", NO_PROXY="localhost,127.0.0.1,::1")
    env["PATH"] = str(Path(policy["runner_python"]).parent) + os.pathsep + env.get("PATH", "")
    return env


def invocation(policy, cycle):
    return [
        policy["codex_binary"], "exec", "--cd", policy["workspace"],
        "--skip-git-repo-check", "--sandbox", "workspace-write",
        "-c", 'approval_policy="never"',
        "-c", "sandbox_workspace_write.network_access=true",
        "--json", "--color", "never",
        "--output-schema", str(HERE / "report.schema.json"),
        "--output-last-message", str(cycle / "report.json"), "-",
    ]


def prompt_for(policy, ready, previous, observation=None):
    module = runtime_module()
    primary_path = resolve_ref_path(ready["connection"])
    primary_cfg = read_json(primary_path)
    primary_resources = module.profile_resources(primary_cfg)
    transport = module.transport_profile(policy, ready, primary_cfg)
    bounded = dict(observation or {})
    for key in ("runs", "external_runs", "pending_tasks", "repair_requests", "blocked_tasks", "events"):
        values = bounded.get(key)
        if isinstance(values, list) and len(values) > 64:
            bounded[key + "_total"] = len(values)
            if key == "runs":
                important = [item for item in values if item.get("occupied") or not item.get("success")]
                bounded[key] = (important or values[-64:])[:64]
            else:
                bounded[key] = values[:64]
    bounded["full_observation_file"] = str(Path(policy["state_dir"]) / "observation.json")
    return (
        (HERE / "task.md").read_text(encoding="utf-8")
        + "\n\n## 本轮研究上下文与执行接口\n"
        + json.dumps({
            "workspace": policy["workspace"], "connection": ready["connection"],
            "runner_python": policy["runner_python"],
            "max_parallel_jobs": policy["max_parallel_jobs"],
            "profile_resources": primary_resources,
            "transport_connection": transport["connection"] if transport else None,
            "transport_max_parallel_jobs": transport["limit"] if transport else None,
            "backend_resources": {"tcad": primary_resources,
                                  "geant4": transport["resources"] if transport else primary_resources},
            "resource_instructions": (
                "The pinned profile_resources override earlier generic task.md capacity/thread descriptions. "
                "Use only the original runner, owner, state root and shared pool. For r4, new TCAD input "
                "project.json must explicitly declare native_threads=2 and native_cores=2; "
                "mixed profiles require both declarations to match the intended slot width. "
                "Use the operator's routing rules when freezing new inputs. "
                "Geant4 requires the explicitly pinned single-thread transport_connection; without it "
                "r4 refuses transport. The sole controller drains and alternates these configured "
                "profiles only in an idle pool after verified collection and lease release, with "
                "the configured global maximum of tasks. "
                "Waiting for another profile is pending work: do not duplicate tasks, retry failed "
                "run IDs, clear locks, open another pool or change policy/profile bindings. "
                "Failure repairs require a new task ID, "
                "new input directory and new run ID, repair_of and repair_reason; preserve old run IDs "
                "and inputs, physics and scientific criteria. Requested numerical threads are distinct "
                "from OS thread count. Resource/collection validation does not establish scientific "
                "acceptance, multicore utilization or performance; those require original measurements."
            ),
            "plan_file": policy["plan_file"], "queue_file": policy["queue_file"],
            "repair_attempt_limit": policy.get("repair_attempt_limit", 2),
            "operator_task": Path(policy["task_file"]).read_text(encoding="utf-8"),
            "last_controller_checkpoint": previous,
            "original_runner_observation": bounded,
        }, ensure_ascii=False, indent=2)
        + "\n上一轮报告只是导航。原作业已由轻量监督对账；不要重复提交或空转验门禁。"
        + advisor_module().GUIDANCE
        + "\n原生顾问会话索引："
        + str(Path(policy["state_dir"]) / "advisory-sessions.json")
    )


def validate_report(report):
    if not isinstance(report, dict) or set(report) != REPORT_KEYS:
        raise Refused("Incomplete or unexpected Codex report fields")
    if report["status"] not in ("progress", "waiting", "blocked", "complete"):
        raise Refused("Unknown Codex report status")
    if any(not isinstance(report[k], str) or not report[k].strip()
           for k in ("summary", "next_step")):
        raise Refused("Codex report lacks a useful checkpoint")
    if type(report["next_check_seconds"]) is not int or not 60 <= report["next_check_seconds"] <= 86400:
        raise Refused("Invalid next check interval")
    if (not isinstance(report["evidence"], list)
            or any(not isinstance(x, str) for x in report["evidence"])):
        raise Refused("Invalid report evidence paths")
    return report


def run_cycle(policy, ready, previous, stop, observation=None, supervise=None):
    state = Path(policy["state_dir"])
    cycle = state / "cycles" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    cycle.mkdir(parents=True)
    checkpoint = {"utc": utc(), "state": "running", "cycle": str(cycle),
                  "failure_count": (previous or {}).get("failure_count", 0),
                  "event_key": (previous or {}).get("event_key"),
                  "report": (previous or {}).get("report")}
    write_json(state / "checkpoint.json", checkpoint)
    proc = None
    try:
        route = route_at(policy)
        env = prepare_codex(policy, route)
        text = prompt_for(policy, ready, previous, observation)
        (cycle / "prompt.md").write_text(text, encoding="utf-8")
        with (cycle / "events.jsonl").open("wb") as events, (cycle / "stderr.log").open("wb") as errors:
            proc = subprocess.Popen(invocation(policy, cycle), stdin=subprocess.PIPE,
                                    stdout=events, stderr=errors, env=env, cwd=policy["workspace"],
                                    start_new_session=(os.name != "nt"))
            # Native advisors run asynchronously inside Codex. Keep the ONE
            # existing Runtime alive while Sol/Astra think; never start a second
            # scheduler. Retrying communicate after TimeoutExpired is supported;
            # input is supplied once, and stdout/stderr already stream to files.
            if supervise is None:
                proc.communicate(text.encode("utf-8"), timeout=policy["cycle_timeout_seconds"])
            else:
                deadline = time.monotonic() + policy["cycle_timeout_seconds"]
                data = text.encode("utf-8")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(invocation(policy, cycle),
                                                        policy["cycle_timeout_seconds"])
                    try:
                        proc.communicate(data, timeout=min(policy["poll_interval_seconds"], remaining))
                        break
                    except subprocess.TimeoutExpired:
                        data = None
                        if stop["requested"] or (state / "pause.json").exists():
                            raise Refused("Model cycle interrupted by operator")
                        supervise()
        if proc.returncode:
            raise Refused("Codex exited nonzero")
        report = validate_report(read_json(cycle / "report.json"))
    except (Exception, KeyboardInterrupt) as exc:
        if proc is not None and proc.poll() is None:
            if os.name != "nt" and isinstance(getattr(proc, "pid", None), int):
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt" and isinstance(getattr(proc, "pid", None), int):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=10)
        failures = checkpoint["failure_count"] + 1
        delay = min(policy.get("max_failure_backoff_seconds", 3600),
                    policy.get("failure_backoff_seconds", 300) * 2 ** min(failures - 1, 16))
        checkpoint.update(state="retry_wait", finished_utc=utc(), failure_count=failures,
                          retry_after=time.time() + delay, error_type=type(exc).__name__,
                          recovery="Reconcile original run identities before the next planning cycle")
        write_json(state / "checkpoint.json", checkpoint)
        return checkpoint
    finally:
        try:
            advisor_module().record_events(state, cycle)
        except (OSError, ValueError, TypeError):
            # A navigation index failure must not alter solver state or turn a
            # completed model response into a retry of a paid consultation.
            checkpoint["advisor_index_warning"] = "See original cycle events.jsonl"
    checkpoint.update(state="reported", finished_utc=utc(), report=report,
                      failure_count=0, retry_after=0,
                      report_semantics="Navigation only; scientific/job status remains in original evidence")
    write_json(state / "checkpoint.json", checkpoint)
    return checkpoint


def runtime_module():
    # Loading by path also supports importlib-based offline tests and release dirs.
    import importlib.util
    spec = importlib.util.spec_from_file_location("tcad_autonomy_runtime", HERE / "runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scheduler_engine_module():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("tcad_autonomy_scheduler_engine", HERE / "scheduler_engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scheduler_planner_module():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("tcad_autonomy_scheduler_planner", HERE / "scheduler_planner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_runtime(policy, ready, wake_event=None, async_collect=True):
    if policy.get("scheduler_version") == "v2_legacy":
        return runtime_module().Runtime(policy, ready)
    return scheduler_engine_module().SchedulerEngine(
        policy, ready, wake_event=wake_event, async_collect=async_collect
    )


def watch_key(policy, previous, observation):
    """Stable semantic events, not every log append or refreshed status timestamp."""
    paths = {Path(policy[k]).resolve() for k in ("plan_file", "queue_file", "task_file")}
    workspace = Path(policy["workspace"]).resolve()
    for value in ((previous or {}).get("report") or {}).get("evidence", [])[:64]:
        path = Path(value)
        path = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        if (workspace in path.parents and "local_runtime" not in path.parts
                and path.suffix.lower() in {".md", ".py", ".json", ".yaml", ".yml", ".csv"}):
            paths.add(path)
    observed = []
    for path in sorted(paths, key=str):
        try:
            # Large artifacts are referenced, never read into the prompt.
            meta = path.stat()
            signature = digest(path) if path.is_file() and meta.st_size <= 4 * 1024**2 else [
                meta.st_size, meta.st_mtime_ns]
            observed.append([str(path), signature])
        except OSError:
            observed.append([str(path), "unavailable"])
    return hashlib.sha256(json.dumps(
        [observation["fingerprint"], observed], sort_keys=True).encode()).hexdigest()


def should_wake(policy, checkpoint, observation, event_key, now=None):
    now = time.time() if now is None else now
    if checkpoint is None:
        return True
    if now < checkpoint.get("retry_after", 0) or now < checkpoint.get("next_model_after", 0):
        return False
    if checkpoint.get("state") in ("running", "uncertain", "retry_wait"):
        return True
    if checkpoint.get("continue_pending"):
        return True
    return checkpoint.get("event_key") != event_key


def new_artifact_created(policy, prior, checkpoint, started_ns):
    old = set(((prior or {}).get("report") or {}).get("evidence", []))
    root = Path(policy["workspace"]).resolve()
    for value in (checkpoint.get("report") or {}).get("evidence", []):
        if value in old:
            continue
        path = (root / value).resolve()
        try:
            if root in path.parents and path.is_file() and path.stat().st_mtime_ns >= started_ns:
                return True
        except OSError:
            pass
    return False


def sleep_poll(seconds, stop, state, wake_event=None):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not stop["requested"]:
        if (state / "pause.json").exists() or (state / "control.json").exists():
            break
        remaining = max(0.0, until - time.monotonic())
        step = min(1.0, remaining)
        if wake_event is not None:
            if wake_event.wait(timeout=step):
                wake_event.clear()
                break
        else:
            time.sleep(step)


def binding(policy):
    ready_ref = policy.get("readiness")
    ready_path = ready_ref if isinstance(ready_ref, str) else (
        ready_ref.get("path") if isinstance(ready_ref, dict) else None)
    return {
        "workspace": policy.get("workspace"),
        "state_dir": policy.get("state_dir"),
        "queue_file": policy.get("queue_file"),
        "plan_file": policy.get("plan_file"),
        "runner_python": policy.get("runner_python"),
        "max_parallel_jobs": policy.get("max_parallel_jobs"),
        "repair_attempt_limit": policy.get("repair_attempt_limit"),
        "readiness_path": str(Path(ready_path).resolve()) if isinstance(ready_path, str) and Path(ready_path).is_absolute() else ready_path,
        "transport_connection_file": policy.get("transport_connection_file"),
        "transport_max_parallel_jobs": policy.get("transport_max_parallel_jobs"),
        "scientific_gate": policy.get("scientific_gate"),
    }


def _connection_semantics(path, module):
    cfg = read_json(path)
    return {
        "path": str(path),
        "identity": {key: cfg.get(key) for key in ("backend", "ssh_target", "runtime_entry", "remote_root")},
        "tool_bin": cfg.get("tool_bin"),
        "local_state_root": str(Path(cfg["local_state_root"]).resolve()) if cfg.get("local_state_root") else None,
        "resources": module.profile_resources(cfg),
    }


def identity_stamp(policy, ready):
    """Semantic change detection for execution topology/target; ignores whitespace/mtime."""
    module = runtime_module()
    ready_path = resolve_ref_path(policy.get("readiness"))
    if ready_path is None:
        raise Refused("Readiness file is absent or invalid")
    live_ready = read_json(ready_path)
    primary_path = resolve_ref_path(live_ready.get("connection"))
    if primary_path is None:
        raise Refused("Connection profile missing or invalid")
    result = {
        "readiness_path": str(ready_path),
        "new_jobs_authorized": live_ready.get("new_jobs_authorized"),
        "controller_owner": live_ready.get("controller_owner"),
        "sole_scheduler": live_ready.get("sole_scheduler"),
        "workspace": live_ready.get("workspace"),
        "plan_file": live_ready.get("plan_file"),
        "max_parallel_jobs": live_ready.get("max_parallel_jobs"),
        "connection": _connection_semantics(primary_path, module),
    }
    transport_ref = live_ready.get("transport_connection") or policy.get("transport_connection_file")
    if transport_ref is not None:
        transport_path = resolve_ref_path(transport_ref)
        if transport_path is None:
            raise Refused("Transport connection profile missing or invalid")
        result["transport_connection"] = _connection_semantics(transport_path, module)
    return result


def resolve_planner_mode(policy):
    if "planner_mode" in policy:
        return policy["planner_mode"]
    if policy.get("scheduler_version") == "v3":
        return "disabled"
    return "legacy_compat"


def _enqueue_control_command(state_dir, command):
    path = Path(state_dir) / "control.json"
    existing = []
    if path.is_file():
        try:
            loaded = read_json(path)
            existing = loaded if isinstance(loaded, list) else [loaded]
        except (OSError, ValueError):
            existing = []
    existing.append(dict(command, queued_utc=utc()))
    write_json(path, existing)
    return {"queued": True, "control_file": str(path), "command": command}


def explain_observation(policy):
    state = Path(policy["state_dir"])
    obs_path = state / "observation.json"
    if not obs_path.is_file():
        return {"available": False, "reason": "observation_missing", "observation_file": str(obs_path)}
    obs = read_json(obs_path)
    sched = obs.get("scheduler")
    if not isinstance(sched, dict):
        return {
            "available": True,
            "schema": "legacy",
            "utc": obs.get("utc"),
            "active_count": obs.get("active_count"),
            "running_count": obs.get("running_count"),
            "pending_count": obs.get("pending_count"),
            "pool_phase": obs.get("pool_phase"),
            "summary": "Legacy observation without structured v3 scheduler decision block",
        }
    return {
        "available": True,
        "schema": sched.get("schema"),
        "utc": obs.get("utc"),
        "pool": sched.get("pool"),
        "resources": sched.get("resources"),
        "last_decision": sched.get("last_decision"),
        "metrics": sched.get("metrics"),
        "quarantined_tasks": sched.get("quarantined_tasks", []),
        "planner": sched.get("planner"),
    }


def serve(policy_file, once=False):
    initial = policy_at(policy_file)
    # The disabled path is intentionally before init, locks, config writes or Popen.
    if not initial["enabled"]:
        raise Refused("Controller disabled; no Codex process or simulation was started")
    state = Path(initial["state_dir"])
    with instance_lock(state / "controller.lock"):
        checked = inspect(initial)
        if not checked["prerequisites_passed"]:
            pause(initial, "Execution configuration invalid: " + "; ".join(checked["errors"]))
            raise Refused("Preflight failed; no Codex process or solver was started")
        ready = readiness_at(initial)
        stamp = identity_stamp(initial, ready)
        runtime = create_runtime(initial, ready)
        wake_event = getattr(runtime, "wake_event", None)
        if once and hasattr(runtime, "async_collect"):
            runtime.async_collect = False
        planner_mode = resolve_planner_mode(initial)
        planner_sidecar = None
        if planner_mode == "on_demand_async":
            planner_sidecar = scheduler_planner_module().AsyncPlannerSidecar(
                mode=planner_mode,
                run_cycle_fn=lambda pol, rdy, prev, stp, obs: run_cycle(pol, rdy, prev, stp, obs),
                watch_key_fn=watch_key,
                should_wake_fn=should_wake,
                new_artifact_fn=new_artifact_created,
                save_checkpoint_fn=lambda cp: write_json(state / "checkpoint.json", cp),
                wake_event=wake_event,
            )
            if hasattr(runtime, "_planner_status_fn"):
                runtime._planner_status_fn = planner_sidecar.status_dict
        elif hasattr(runtime, "_planner_status_fn"):
            runtime._planner_status_fn = lambda: {"mode": planner_mode, "running": False}

        previous = read_json(state / "checkpoint.json") if (state / "checkpoint.json").exists() else None
        if previous and previous.get("state") in ("running", "uncertain") and previous.get("cycle"):
            try:
                advisor_module().record_events(state, Path(previous["cycle"]))
            except (OSError, ValueError, TypeError):
                pass  # Original cycle events remain the recovery source.
        stop = {"requested": False}
        runtime.can_submit = lambda: (
            not stop["requested"] and not (state / "pause.json").exists()
            and policy_at(policy_file)["enabled"]
            and binding(policy_at(policy_file)) == binding(initial)
            and identity_stamp(initial, ready) == stamp)
        old_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            def _on_stop(*_):
                stop.update(requested=True)
                if wake_event is not None:
                    wake_event.set()
            old_handlers[sig] = signal.signal(sig, _on_stop)
        try:
            cycles, runtime_errors, runtime_retry_after = 0, 0, 0
            recovering = True
            while True:
                policy = policy_at(policy_file)
                if not policy["enabled"] or stop["requested"]:
                    break
                if (state / "pause.json").exists():
                    break
                if binding(policy) != binding(initial):
                    pause(initial, "Execution identity changed; restart against the explicit new handoff")
                    raise Refused("Execution identity changed while holding the lifecycle lock")
                try:
                    new_stamp = identity_stamp(policy, ready)
                    if new_stamp != stamp:
                        raise Refused("Execution topology or target changed while running; restart controller to apply")
                except (OSError, ValueError, Refused):
                    pause(policy, "Original runner identity or sole-owner handoff changed")
                    raise Refused("Execution identity changed; no new task submitted")
                if time.time() < runtime_retry_after:
                    if once:
                        break
                    sleep_poll(policy["poll_interval_seconds"], stop, state, wake_event=wake_event)
                    continue
                try:
                    # Always reconcile existing IDs before considering any launch.
                    if recovering:
                        observation = runtime.tick(allow_submit=False)
                        recovering = False
                    if (runtime.can_submit()
                            and not observation.get("discovery_uncertain", False)):
                        observation = runtime.tick(allow_submit=True)
                    else:
                        recovering = True
                    runtime_errors = 0
                    write_json(state / "observation.json", {"utc": utc(), **observation})
                except Exception as exc:
                    recovering = True
                    runtime_errors += 1
                    delay = min(policy["max_failure_backoff_seconds"],
                                policy["failure_backoff_seconds"] * 2 ** min(runtime_errors - 1, 16))
                    runtime_retry_after = time.time() + delay
                    # Preserve last good observation and original intents. No LLM
                    # speculation about a missing or unreachable solver.
                    write_json(state / "runtime-error.json", {
                        "utc": utc(), "error_type": type(exc).__name__,
                        "retry_after": runtime_retry_after, "failure_count": runtime_errors})
                    if once:
                        break
                    sleep_poll(policy["poll_interval_seconds"], stop, state, wake_event=wake_event)
                    continue
                if (stop["requested"] or (state / "pause.json").exists()
                        or not policy_at(policy_file)["enabled"]):
                    break
                active_mode = resolve_planner_mode(policy)
                if active_mode == "disabled":
                    pass
                elif active_mode == "on_demand_async" and planner_sidecar is not None:
                    previous = read_json(state / "checkpoint.json") if (state / "checkpoint.json").exists() else previous
                    planner_sidecar.maybe_trigger(
                        policy=policy,
                        ready=ready,
                        checkpoint=previous,
                        observation=observation,
                        stop=stop,
                    )
                elif active_mode == "legacy_compat":
                    event_key = watch_key(policy, previous, observation)
                    if should_wake(policy, previous, observation, event_key):
                        prior, started_ns = previous, time.time_ns()
                        during_observation = observation

                        def supervise_while_model_runs():
                            nonlocal recovering, runtime_errors, runtime_retry_after, during_observation
                            if time.time() < runtime_retry_after:
                                return
                            try:
                                # The same Runtime, same intent ledger and same
                                # can_submit checks as the outer loop. No new owner.
                                during_observation = runtime.tick(allow_submit=False)
                                recovering = False
                                if (runtime.can_submit()
                                        and not during_observation.get("discovery_uncertain", False)):
                                    during_observation = runtime.tick(allow_submit=True)
                                runtime_errors = 0
                                write_json(state / "observation.json", {"utc": utc(), **during_observation})
                            except Exception as exc:
                                recovering = True
                                runtime_errors += 1
                                delay = min(policy["max_failure_backoff_seconds"],
                                            policy["failure_backoff_seconds"]
                                            * 2 ** min(runtime_errors - 1, 16))
                                runtime_retry_after = time.time() + delay
                                write_json(state / "runtime-error.json", {
                                    "utc": utc(), "error_type": type(exc).__name__,
                                    "retry_after": runtime_retry_after, "failure_count": runtime_errors})

                        previous = run_cycle(policy, ready, previous, stop, observation,
                                             supervise=supervise_while_model_runs)
                        cycles += 1
                        # Keep the observation Sol actually saw as its event
                        # baseline. A completion during consultation wakes the next
                        # cycle instead of being silently marked as consumed.
                        previous["event_key"] = watch_key(policy, previous, observation)
                        previous["continue_pending"] = (
                            previous["state"] == "reported"
                            and previous["report"]["status"] == "progress"
                            and (watch_key(policy, prior, observation) != event_key
                                 or new_artifact_created(policy, prior, previous, started_ns)))
                        previous["next_model_after"] = time.time() + policy["minimum_interval_seconds"]
                        if previous["state"] == "reported":
                            previous["research_complete_reported"] = (
                                previous["report"]["status"] == "complete"
                                and not recovering
                                and during_observation.get("queue_complete", False)
                                and during_observation.get("active_count", 0) == 0
                                and during_observation.get("pending_count", 0) == 0
                                and not during_observation.get("repair_requests")
                                and not during_observation.get("blocked_tasks"))
                            if previous["research_complete_reported"]:
                                previous["state"] = "idle"
                        else:
                            recovering = True
                        write_json(state / "checkpoint.json", previous)
                        if (policy["maximum_cycles_per_start"]
                                and cycles >= policy["maximum_cycles_per_start"]):
                            break
                if once:
                    break
                sleep_poll(policy["poll_interval_seconds"], stop, state, wake_event=wake_event)
        finally:
            if planner_sidecar is not None:
                planner_sidecar.join(timeout=5.0)
            if hasattr(runtime, "close"):
                runtime.close()
            for sig, old in old_handlers.items():
                signal.signal(sig, old)
    return {"stopped": True, "codex_started_only_if_enabled_and_accepted": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "check", "plan", "disarm", "explain"):
        commands.add_parser(name)
    arm = commands.add_parser("arm", help="Pin accepted handoff and enable policy; does not start a process")
    arm.add_argument("--readiness", required=True, type=Path)
    migrate = commands.add_parser("migrate", help="Migrate old policy, disabled; never start anything")
    migrate.add_argument("--output", type=Path)
    p = commands.add_parser("pause")
    p.add_argument("--reason", default="Operator requested pause")
    clear = commands.add_parser("clear-pause")
    clear.add_argument("--reconciled", action="store_true")
    cancel_cmd = commands.add_parser("cancel", help="Cancel a running job via verified runner cancel protocol")
    cancel_cmd.add_argument("target", help="task_id or run_id to cancel")
    cancel_cmd.add_argument("--reason", default="operator_cancel")
    cancel_cmd.add_argument("--grace-seconds", type=int, default=15)
    drain_cmd = commands.add_parser("drain", help="Explicitly drain pool toward a target profile or cancel drain")
    drain_group = drain_cmd.add_mutually_exclusive_group(required=True)
    drain_group.add_argument("--to", choices=("tcad", "geant4"), dest="target_profile")
    drain_group.add_argument("--cancel", action="store_true", dest="cancel_drain")
    drain_cmd.add_argument("--reason", default="operator_drain")
    start = commands.add_parser("serve")
    start.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "migrate":
            result = migrate_policy(args.policy, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        policy = policy_at(args.policy)
        if args.command == "init":
            result = initialize(policy)
        elif args.command == "explain":
            result = explain_observation(policy)
        elif args.command in ("status", "check", "plan"):
            result = inspect(policy)
            if args.command == "plan":
                result["command_preview"] = invocation(policy, Path(policy["state_dir"]) / "cycles/PREVIEW")
                result["codex_started"] = False
        elif args.command == "pause":
            pause(policy, args.reason)
            result = {"paused": True, "running_solver_jobs_stopped": False}
        elif args.command == "clear-pause":
            path = Path(policy["state_dir"]) / "pause.json"
            checkpoint_path = path.with_name("checkpoint.json")
            checkpoint = read_json(checkpoint_path) if checkpoint_path.exists() else None
            uncertain = checkpoint and checkpoint.get("state") in ("running", "uncertain")
            if ((path.exists() and read_json(path).get("reconcile_required")) or uncertain) and not args.reconciled:
                raise Refused("Explicit --reconciled required after checking original jobs")
            # Never allow clearing a live cycle's uncertainty while its process runs.
            with instance_lock(path.with_name("controller.lock")):
                if uncertain:
                    checkpoint.update(state="operator_reconciled", reconciled_utc=utc())
                    write_json(checkpoint_path, checkpoint)
                if path.exists():
                    path.unlink()
            result = {"pause_cleared": True, "codex_started": False}
        elif args.command == "cancel":
            state_dir = Path(policy["state_dir"])
            try:
                with instance_lock(state_dir / "controller.lock"):
                    ready = readiness_at(policy)
                    engine = scheduler_engine_module().SchedulerEngine(policy, ready, async_collect=False)
                    try:
                        result = engine.cancel_task(
                            args.target,
                            reason=args.reason,
                            requested_by="operator",
                            grace_seconds=args.grace_seconds,
                        )
                    finally:
                        engine.close()
            except Refused:
                # Active daemon holds lock; enqueue command for immediate execution.
                result = _enqueue_control_command(state_dir, {
                    "action": "cancel_task",
                    "target": args.target,
                    "reason": args.reason,
                    "requested_by": "operator",
                    "grace_seconds": args.grace_seconds,
                })
        elif args.command == "drain":
            state_dir = Path(policy["state_dir"])
            cmd = (
                {"action": "cancel_drain"}
                if args.cancel_drain
                else {"action": "drain", "target_profile": args.target_profile, "reason": args.reason}
            )
            result = _enqueue_control_command(state_dir, cmd)
        elif args.command == "arm":
            candidate = dict(policy, enabled=True,
                             readiness={"path": str(args.readiness.resolve()), "sha256": digest(args.readiness)})
            checked = inspect(candidate)
            if not checked["prerequisites_passed"]:
                raise Refused("Cannot arm: " + "; ".join(checked["errors"]))
            write_json(args.policy, candidate)
            result = {"armed": True, "codex_started": False}
        elif args.command == "disarm":
            write_json(args.policy, dict(policy, enabled=False))
            result = {"enabled": False, "codex_started": False}
        else:
            result = serve(args.policy, args.once)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if args.command == "check" and not result["prerequisites_passed"] else 0
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "utc": utc()}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
