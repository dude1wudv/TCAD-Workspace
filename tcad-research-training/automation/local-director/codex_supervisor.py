from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from campaign_fsm import (
    BLOCKED_REASONS,
    CAMPAIGN_STATES,
    advance_phase,
    cooldown_active,
    is_operational_task,
    next_phase,
    operational_cooldown_active,
    operational_tasks,
    public_campaign_with_metrics,
    ready_tasks,
    register_blocked,
    set_cooldown,
)
from codex_runner import _codex_executable, _worker_command
from config import Config
from notifier import redact_text
from runtime import hidden_subprocess_kwargs
from schemas import read_json
from status_publisher import redact_configured_text


DECISION_SCHEMA = Path(__file__).resolve().parent / "prompts" / "supervisor_decision.schema.json"
MAX_REASON_LENGTH = 500


def _timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _deep_check_due(campaign: dict[str, Any], now: datetime) -> bool:
    value = campaign.get("last_deep_check_at")
    if not isinstance(value, str) or not value:
        return True
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return True
    if stamp.tzinfo is None:
        return True
    return now - stamp.astimezone(timezone.utc) >= timedelta(hours=12)


def actionable(
    cfg: Config,
    campaign: dict[str, Any],
    backlog: dict[str, Any],
    server: dict[str, Any],
    director_state: dict[str, Any],
    *,
    now: datetime | None = None,
    scheduled_pulse: bool = False,
) -> tuple[bool, str | None]:
    moment = now or datetime.now(timezone.utc)
    if not cfg.campaign_execution_enabled:
        return False, "monitor_only"
    if cooldown_active(campaign, moment):
        return False, "cooldown"
    active = director_state.get("active_order") if isinstance(director_state, dict) else None
    if isinstance(active, dict) and active.get("status") in {"queued", "retry_queued", "running"}:
        return False, "worker_busy"
    if isinstance(active, dict) and active.get("status") in {"awaiting_review", "stalled"}:
        return True, "worker_receipt_or_stall"
    summary = server.get("summary") if isinstance(server.get("summary"), dict) else {}
    if (server.get("online") is False or server.get("service_active") is False or summary.get("quarantined", 0) > 0) and not operational_cooldown_active(campaign, "sim-repair", server, now=moment):
        return True, "server_health"
    disk = server.get("disks", {}).get("server_free_bytes")
    if disk is None:
        disk = summary.get("server_free_bytes")
    if type(disk) is int and disk < 35 * 1024**3 and not operational_cooldown_active(campaign, "archive-remote-sync", server, now=moment):
        return True, "disk_floor"
    actionable_blocked = summary.get("actionable_blocked_count", summary.get("blocked_count", 0))
    if (
        (summary.get("starved")
         or (summary.get("free_slots", 0) >= 2 and not summary.get("ready") and actionable_blocked > 0)
         or summary.get("awaiting_acceptance")
         or summary.get("decision_pending")
         or summary.get("missing_material"))
        and not operational_cooldown_active(campaign, "sim-ops-refill", server, now=moment)
    ):
        return True, "simulation_supply"
    if next_phase(campaign):
        return True, "phase_gate"
    if ready_tasks(backlog, campaign["phase"]) or operational_tasks(campaign["phase"], server, campaign=campaign, now=moment):
        return True, "backlog_ready"
    if scheduled_pulse and _deep_check_due(campaign, moment):
        return True, "deep_check_due"
    return False, None


def _public_request(
    campaign: dict[str, Any],
    backlog: dict[str, Any],
    server: dict[str, Any],
    director_state: dict[str, Any],
    reason: str,
    delivery: dict[str, Any] | None,
) -> dict[str, Any]:
    active = director_state.get("active_order") if isinstance(director_state, dict) else None
    order = active.get("order") if isinstance(active, dict) else None
    summary = server.get("summary") if isinstance(server.get("summary"), dict) else {}
    ops_ready = operational_tasks(campaign["phase"], server, campaign=campaign)
    backlog_ready = [task["task"] for task in ready_tasks(backlog, campaign["phase"])]
    return {
        "reason": reason,
        "campaign": public_campaign_with_metrics(campaign),
        "next_phase": next_phase(campaign),
        "ready_tasks": [*ops_ready, *backlog_ready],
        "operational_tasks": ops_ready,
        "backlog": [
            {
                "task": task["task"],
                "title": task["title"],
                "phase": task["phase"],
                "prerequisites": task["prerequisites"],
                "status": task["status"],
                "attempts": task["attempts"],
                "failures": task["failures"],
            }
            for task in backlog["tasks"]
        ],
        "server": {
            "online": server.get("online"),
            "service_active": server.get("service_active"),
            "summary": {key: summary[key] for key in (
                "running", "free_slots", "slots_total", "ready", "preparing", "starved",
                "blocked_count", "awaiting_acceptance", "decision_pending", "waiting_cases",
                "run_bound", "missing_material",
            ) if type(summary.get(key)) in (int, bool)},
        },
        "active_order": {
            "task": active.get("campaign_task") if isinstance(active, dict) and isinstance(order, dict) else None,
            "status": active.get("status") if isinstance(active, dict) else None,
            "attempt": active.get("attempt") if isinstance(active, dict) else None,
        },
        "delivery": delivery,
    }


def build_prompt(request: dict[str, Any]) -> str:
    return (
        "You are the autonomous 30-day campaign supervisor with full authorization to keep simulations, "
        "refills, archive mirroring, ML training, active learning, and research desk delivery moving forward without waiting for human approval. "
        "Use only the supplied JSON request and return one concrete action decision. "
        "Priority: (1) If active_order is awaiting_review or stalled, accept when delivery.passed is true or reject otherwise; "
        "(2) If next_phase is non-null, immediately return action=advance; "
        "(3) If no active work is running and operational_tasks is non-empty (e.g. sim-repair, sim-ops-refill, archive-remote-sync), immediately dispatch the highest-priority operational task to keep 16 slots busy and disk safe; "
        "(4) Otherwise if ready_tasks is non-empty, dispatch a ready task to advance parallel engineering/training/desk delivery. "
        "Never defer to a maintainer or pause for human confirmation; return noop only when no task or phase advance is available. "
        "A blocked action requires three observed failures. Write a short Chinese reason. "
        "Return exactly one JSON object matching the supplied output schema. Do not include progress or any extra fields.\n\n"
        "REQUEST\n" + json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


def _valid_suggestion(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("supervisor result must be an object")
    required = {"action", "task", "phase", "reason", "next_check_seconds", "blocked_reason"}
    if set(value) != required:
        raise ValueError("supervisor result has unknown or missing fields")
    if value["action"] not in ("noop", "dispatch", "accept", "reject", "advance", "blocked", "cooldown", "log"):
        raise ValueError("invalid supervisor action")
    if value["task"] is not None and (
        type(value["task"]) is not str
        or not value["task"]
        or len(value["task"]) > 40
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in value["task"])
        or not value["task"][0].isalpha()
    ):
        raise ValueError("invalid supervisor task")
    if value["phase"] not in CAMPAIGN_STATES:
        raise ValueError("invalid supervisor phase")
    if type(value["reason"]) is not str or not 1 <= len(value["reason"]) <= MAX_REASON_LENGTH:
        raise ValueError("invalid supervisor reason")
    if type(value["next_check_seconds"]) is not int or not 60 <= value["next_check_seconds"] <= 43200:
        raise ValueError("invalid supervisor next check")
    if value["blocked_reason"] is not None and value["blocked_reason"] not in BLOCKED_REASONS:
        raise ValueError("invalid supervisor blocked reason")
    if (value["task"] is not None) != (value["action"] in ("dispatch", "accept", "reject", "blocked")):
        raise ValueError("supervisor action and task do not match")
    if (value["blocked_reason"] is not None) != (value["action"] == "blocked"):
        raise ValueError("supervisor action and blocked reason do not match")
    return value


def run_supervisor(
    cfg: Config,
    campaign: dict[str, Any],
    backlog: dict[str, Any],
    server: dict[str, Any],
    director_state: dict[str, Any],
    reason: str,
    delivery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = _public_request(campaign, backlog, server, director_state, reason, delivery)
    with tempfile.TemporaryDirectory(prefix="supervisor-", dir=cfg.state_dir) as directory:
        output = Path(directory) / "decision.json"
        suggestion = _invoke_supervisor(cfg, output, request)
    suggestion["reason"] = redact_configured_text(cfg, redact_text(suggestion["reason"]))[:MAX_REASON_LENGTH]
    return _valid_suggestion(suggestion)


def _invoke_supervisor(cfg: Config, output: Path, request: dict[str, Any]) -> dict[str, Any]:
    argv = _worker_command([
        *_codex_executable(),
        "exec",
        "--json",
        "--ephemeral",
        "-c",
        "approval_policy=never",
        "--model",
        cfg.codex_supervisor_model,
        "--sandbox",
        "read-only",
        "--cd",
        str(cfg.repo_root.resolve()),
        "-c",
        f"model_reasoning_effort={cfg.codex_supervisor_effort}",
        "--output-schema",
        str(DECISION_SCHEMA),
        "--output-last-message",
        str(output),
        "-",
    ])
    try:
        result = subprocess.run(
            argv,
            cwd=cfg.repo_root,
            input=build_prompt(request),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.codex_supervisor_timeout_seconds,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"supervisor launch failed: {type(error).__name__}") from error
    if result.returncode:
        raise RuntimeError(f"supervisor exited with code {result.returncode}")
    try:
        return _valid_suggestion(read_json(output))
    except (OSError, ValueError) as error:
        raise RuntimeError("supervisor did not produce a valid decision") from error


def validate_action(
    cfg: Config,
    campaign: dict[str, Any],
    backlog: dict[str, Any],
    decision: dict[str, Any],
    director_state: dict[str, Any],
    delivery: dict[str, Any] | None,
) -> None:
    decision = _valid_suggestion(decision)
    if decision["phase"] != campaign["phase"]:
        raise ValueError("supervisor phase does not match campaign phase")
    action = decision["action"]
    task_id = decision["task"]
    active = director_state.get("active_order") or {}
    if action == "dispatch":
        if not (is_operational_task(task_id) or any(task["task"] == task_id for task in ready_tasks(backlog, campaign["phase"]))):
            raise ValueError("supervisor selected a task that is not ready")
        if active.get("status") in ("queued", "retry_queued", "running", "stalled", "awaiting_review"):
            raise ValueError("finish the active work order before dispatching")
    elif action in ("accept", "reject"):
        if active.get("campaign_task") != task_id or active.get("status") not in ("awaiting_review", "stalled"):
            raise ValueError("decision must match the current campaign work order in review")
        if action == "accept" and (not delivery or delivery.get("passed") is not True):
            raise ValueError("accept requires a verified delivery")
    elif action == "blocked":
        if task_id is None or decision["blocked_reason"] is None:
            raise ValueError("blocked requires a task and reason")
        task = next((item for item in backlog["tasks"] if item["task"] == task_id), None)
        if task is None or task["failures"] < cfg.codex_max_task_failures:
            raise ValueError("blocked requires the configured failure threshold")
    elif action == "advance" and not next_phase(campaign):
        raise ValueError("campaign gate does not permit phase advance")


def record_wakeup(cfg: Config, campaign: dict, action: str, task_id: str | None, reason: str,
                  *, changed: bool, now: datetime) -> None:
    stamp = _timestamp(now)
    if changed:
        campaign["wakeups_without_progress"] = 0
        campaign["last_progress_at"] = stamp
    else:
        campaign["wakeups_without_progress"] += 1
    if action == "cooldown" or campaign["wakeups_without_progress"] >= 2:
        set_cooldown(campaign, cfg.codex_no_progress_cooldown_seconds, now=now)
        campaign["wakeups_without_progress"] = 0
        campaign["cooldown_reason"] = reason
    campaign["last_decision"] = {
        "action": action,
        "task": task_id,
        "reason": reason,
        "generated_at": stamp,
    }
    campaign["last_deep_check_at"] = stamp
