import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_runner import finalize_and_precheck, launch_worker, terminate_worker
from config import BASE_DIR, load_config
from probes import compute_state_fingerprint, probe_codex_worker, probe_server, probe_thesis
from runtime import LockBusy, add_event, file_lock, load_state, order_dir, save_state, state_lock
from schemas import DeliveryReceipt, WorkOrder, append_jsonl, atomic_write, parse_time, write_json
from status_publisher import redact_configured_text, redact_text, refresh_status


DAILY = {"DAILY_THESIS_SPRINT": "daily_thesis_hour", "DAILY_DIGEST": "daily_digest_hour"}
BACKOFF_SECONDS = (900, 1800, 3600)
LOG = logging.getLogger(__name__)


def _due(now, value, seconds=0):
    return not value or now >= parse_time(value) + timedelta(seconds=seconds)


def _timestamp(moment):
    return moment.isoformat(timespec="seconds")


def _advance_worker(cfg, state, worker, now, *, dry_run):
    active = state.active_order
    if not active or active["status"] not in {"running", "stalled"}:
        return
    status = worker["status"]
    if status in {"exited", "timeout"}:
        receipt = None
        if not dry_run:
            meta = active["run_meta"]
            if status == "timeout":
                if not terminate_worker(meta, "timeout"):
                    raise RuntimeError("worker timeout termination was not confirmed")
                meta = {**meta, "status_override": "timeout"}
            receipt = finalize_and_precheck(cfg, WorkOrder.from_dict(active["order"]), meta)
        active["status"] = "awaiting_review"
        state.pending_events = [event for event in state.pending_events if event["reason"] != "CODEX_STALLED"]
        failed = (status == "timeout" or worker.get("exit_status") in {"timeout", "stalled"}
                  or (receipt is not None and not receipt.precheck_passed)
                  or (dry_run and worker.get("exit_code") not in {None, 0}))
        add_event(state, "CODEX_FAILED_OR_TIMEOUT" if failed else "CODEX_DELIVERED", "urgent", status)
        state.recent_public_note = "工单等待审阅"
    elif status == "stalled" and _due(now, state.last_stall_at, cfg.codex_stall_seconds):
        active["status"] = "stalled"
        add_event(state, "CODEX_STALLED", "urgent", "工单长时间无新进度")
        state.last_stall_at = _timestamp(now)
        state.recent_public_note = "工单等待进度核查"
    elif status == "running" and active["status"] == "stalled":
        active["status"] = "running"
        state.pending_events = [event for event in state.pending_events if event["reason"] != "CODEX_STALLED"]


def _observe_events(cfg, state, server, thesis, now, local_time, force_trigger, *, dry_run):
    if state.active_turn and _due(now, state.active_turn["started_at"], cfg.director_turn_timeout_seconds):
        if not dry_run:
            append_jsonl(cfg.state_dir / "turns.jsonl", {"status": "expired", "at": _timestamp(now), **state.active_turn})
        state.active_turn = None
        add_event(state, "DIRECTOR_TURN_EXPIRED", "urgent", "上轮未按时释放回合锁")
    offline = not server.get("online", False)
    if offline and not state.server_offline:
        add_event(state, "SERVER_UNREACHABLE", "urgent", "服务器私有与公开探针均未报告在线")
    if not offline and state.server_offline:
        state.pending_events = [event for event in state.pending_events if event["reason"] != "SERVER_UNREACHABLE"]
        add_event(state, "SERVER_RECOVERED", "routine")
    state.server_offline = offline
    if server.get("service_active") is False:
        if not state.server_service_blocked:
            add_event(state, "SCHEDULER_UNAVAILABLE", "urgent", "探针报告调度服务未运行")
        state.server_service_blocked = True
    elif server.get("service_active") is True:
        state.server_service_blocked = False
        state.pending_events = [event for event in state.pending_events if event["reason"] != "SCHEDULER_UNAVAILABLE"]
    fingerprint = compute_state_fingerprint(server, thesis)
    if fingerprint != state.fingerprint:
        if state.fingerprint:
            add_event(state, "STATE_CHANGED", "routine")
        state.fingerprint = fingerprint
    for reason, field in DAILY.items():
        if local_time.hour >= getattr(cfg, field) and reason not in state.daily_executed:
            add_event(state, reason, "daily")
    if _due(now, state.last_periodic_at, cfg.periodic_review_seconds):
        add_event(state, "PERIODIC_REVIEW", "routine")
    if force_trigger:
        add_event(state, redact_text(" ".join(force_trigger.split()))[:120], "urgent", "手动触发")


def _pick_event(cfg, state, now, local_date):
    if state.active_turn or not _due(now, state.wakeup_backoff_until):
        return None
    for bucket in ("urgent", "daily", "routine"):
        if bucket == "routine" and not _due(now, state.next_wake_at):
            continue
        if cfg.can_consume_wakeup(state, bucket, local_date):
            event = next((entry for entry in state.pending_events if entry["bucket"] == bucket), None)
            if event is not None:
                return event
    return None


def _write_briefing(cfg, state, event, server, thesis, now):
    names = ", ".join(entry["reason"] for entry in state.pending_events)
    active = state.active_order
    lines = [
        f"# Local Director 简报 · {_timestamp(now)}",
        f"- 本轮触发 `{event['reason']}` {event['detail']}",
        f"- 待处理事件 {names}",
        f"- 已用每日唤醒 {state.daily_wakeups_used}/{cfg.gemini_daily_cap}",
        f"- 服务器在线 {server.get('online')} · 来源 {server.get('source')} · 调度服务 {server.get('service_active')}",
        f"- 论文 {thesis.get('chapters_done', 0)}/{thesis.get('chapters_total', 0)} 章 · 素材 {thesis.get('assets_count', 0)} · 构建 {thesis.get('build_ok')}",
        f"- 最近决策 {state.last_decision}",
    ]
    if active:
        order = active["order"]
        lines.append(f"- 工单 `{order['order_id']}` · `{order['category']}` · {active['status']} · 第 {active['attempt']} 次")
        if active["status"] == "awaiting_review":
            location = order_dir(cfg, order["order_id"]) / "receipt.json"
            lines.append(f"- 收据相对状态目录 `{location.relative_to(cfg.state_dir.resolve()).as_posix()}`")
    if event["reason"] == "DAILY_DIGEST":
        lines.append("- 使用 `director_ctl.py notify --level digest` 归档并投递日报。")
    if event["reason"] == "CODEX_CIRCUIT_BROKEN":
        lines.append("- 原工单已熔断，请评估新策略。")
    summaries = (server.get("observation") or {}, server.get("explain") or {}, thesis)
    data = redact_configured_text(cfg, json.dumps(summaries, ensure_ascii=False, default=str))
    header = redact_configured_text(cfg, "\n".join(lines))
    path = cfg.state_dir / "briefings" / f"brief-{now.strftime('%Y%m%dT%H%M%S%fZ')}.md"
    text = f"{header}\n\n## 采样摘要\n{data}"
    atomic_write(path, text.encode("utf-8")[:6143].decode("utf-8", "ignore") + "\n")
    return path


def build_prompt(cfg, brief_path):
    prefix = "/goal " if cfg.use_goal_mode else ""
    config_hint = f' Use --config "{cfg.config_path}" with director_ctl.py.' if cfg.config_path else ""
    return (
        f"{prefix}Read the Local Director protocol at {BASE_DIR / 'prompts' / 'director-system.md'} "
        f"and this turn's briefing at {brief_path}. Follow the listed trigger and review boundaries. "
        f"The workspace is {cfg.repo_root}. The runtime directory is {cfg.state_dir}. "
        f"Finish through the local director_ctl.py finish-turn command.{config_hint}"
    )


def _agentapi_argv():
    executable = shutil.which("agentapi")
    if not executable:
        raise FileNotFoundError("agentapi is not on PATH")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".bat", ".cmd"}:
        text = path.read_text(encoding="utf-8-sig")
        wrapper = re.fullmatch(r'\s*(?:@echo off\s*)?"([^"\r\n]+\.exe)"\s+agentapi\s+%\*\s*', text, re.I)
        if not wrapper:
            raise ValueError("agentapi batch launcher requires a native executable or the standard launcher")
        return [wrapper[1], "agentapi"]
    return [executable]


def new_conversation(cfg, reason, prompt):
    argv = [*_agentapi_argv(), "new-conversation", f"--model={cfg.gemini_model}", f"--title=[AutoDirector] {reason}", prompt]
    result = subprocess.run(argv, cwd=cfg.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    if result.returncode:
        raise RuntimeError(f"agentapi exited with code {result.returncode}")
    text = result.stdout.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    conversation = None
    if isinstance(data, dict):
        nested = (data.get("response") or {}).get("newConversation") if isinstance(data.get("response"), dict) else None
        for source in (data, nested):
            if isinstance(source, dict) and not conversation:
                conversation = source.get("conversation_id") or source.get("conversationId") or source.get("id")
    if not conversation:
        match = re.search(r'"?conversation(?:[ _-]?id)?"?\s*[:=]\s*["\']?([\w-]{8,100})', text, re.I)
        if match is None:
            match = re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", text)
            conversation = match[0] if match else None
        else:
            conversation = match[1]
    if not isinstance(conversation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", conversation):
        raise RuntimeError("agentapi did not return a conversation ID")
    return conversation


def _record_wakeup(cfg, state, event, brief_path, now):
    try:
        conversation = new_conversation(cfg, event["reason"], build_prompt(cfg, brief_path))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        delay = BACKOFF_SECONDS[min(state.wakeup_failures, len(BACKOFF_SECONDS) - 1)]
        state.wakeup_failures += 1
        state.wakeup_backoff_until = _timestamp(now + timedelta(seconds=delay))
        append_jsonl(cfg.state_dir / "turns.jsonl", {"status": "start_failed", "reason": event["reason"], "at": _timestamp(now),
                                                    "error": redact_text(str(error)), "retry_at": state.wakeup_backoff_until})
        return None
    reason = event["reason"]
    state.active_turn = {"conversation_id": conversation, "started_at": _timestamp(now), "reason": reason}
    state.daily_wakeups_used += 1
    if reason in DAILY and reason not in state.daily_executed:
        state.daily_executed.append(reason)
    if reason == "PERIODIC_REVIEW":
        state.last_periodic_at = _timestamp(now)
    state.pending_events.remove(event)
    state.wakeup_failures = 0
    state.wakeup_backoff_until = ""
    return conversation


def _tick_state(cfg, state, server, thesis, now, dry_run, force_trigger):
    local_time = cfg.local_time(now)
    cfg.reset_day(state, local_time.date())
    worker = probe_codex_worker(cfg, state)
    _advance_worker(cfg, state, worker, now, dry_run=dry_run)
    _observe_events(cfg, state, server, thesis, now, local_time, force_trigger, dry_run=dry_run)
    event = _pick_event(cfg, state, now, local_time.date())
    result = {"dry_run": dry_run, "reason": event["reason"] if event else None, "bucket": event["bucket"] if event else None,
              "pending_events": [item["reason"] for item in state.pending_events], "conversation_id": None,
              "daily_wakeups_used": state.daily_wakeups_used, "backoff_until": state.wakeup_backoff_until}
    if dry_run:
        if event:
            result["prompt"] = build_prompt(cfg, cfg.state_dir / "briefings" / "brief-preview.md")
        return result
    if event:
        brief_path = _write_briefing(cfg, state, event, server, thesis, now)
        save_state(cfg, state)
        result["conversation_id"] = _record_wakeup(cfg, state, event, brief_path, now)
        result["briefing"] = str(brief_path)
        result["daily_wakeups_used"] = state.daily_wakeups_used
        result["backoff_until"] = state.wakeup_backoff_until
    save_state(cfg, state)
    refresh_status(cfg, state, server, thesis)
    return result


def _pump_queued_orders(cfg) -> bool:
    with state_lock(cfg):
        state = load_state(cfg)
        active = state.active_order
        if not active or active.get("status") not in {"queued", "retry_queued"}:
            return False
        order = WorkOrder.from_dict(active["order"])
        attempt = int(active.get("attempt", 1))
        retry = active.get("pending_retry") or {}
        previous = DeliveryReceipt.from_dict(retry["previous_receipt"]) if retry.get("previous_receipt") else None
        feedback = retry.get("feedback", "")
        try:
            run_meta = launch_worker(cfg, order, attempt=attempt, previous_receipt=previous, feedback=feedback)
        except (OSError, RuntimeError, ValueError) as error:
            write_json(order_dir(cfg, order.order_id) / "launch_error.json", {"error": redact_text(str(error))})
            active["status"] = "awaiting_review"
            add_event(state, "CODEX_FAILED_OR_TIMEOUT", "urgent", f"queued launch failed: {redact_text(str(error))[:120]}")
            save_state(cfg, state)
            return True
        active["run_meta"] = run_meta
        active["status"] = "running"
        active.pop("pending_retry", None)
        state.recent_public_note = "工单执行中"
        save_state(cfg, state)
        refresh_status(cfg, state, publish=False)
        return True


def tick(cfg, *, dry_run=False, force_trigger=None, now=None):
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not dry_run:
        _pump_queued_orders(cfg)
    server = probe_server(cfg)
    thesis = probe_thesis(cfg)
    if dry_run:
        return _tick_state(cfg, load_state(cfg), server, thesis, moment, True, force_trigger)
    with state_lock(cfg):
        return _tick_state(cfg, load_state(cfg), server, thesis, moment, False, force_trigger)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Director 本地看门狗")
    parser.add_argument("--config", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--daemon", action="store_true")
    modes.add_argument("--tick", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-trigger")
    args = parser.parse_args(argv)
    if args.daemon and (args.dry_run or args.force_trigger):
        parser.error("--dry-run and --force-trigger require --tick")
    try:
        cfg = load_config(args.config)
        if args.dry_run:
            print(json.dumps(tick(cfg, dry_run=True, force_trigger=args.force_trigger), ensure_ascii=False))
            return 0
        with file_lock(cfg.state_dir / "watchdog.lock"):
            while True:
                started = time.monotonic()
                try:
                    result = tick(cfg, force_trigger=args.force_trigger)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                    if not args.daemon:
                        raise
                    LOG.error("watchdog tick failed: %s", redact_text(str(error)))
                if args.tick:
                    return 0
                deadline = started + cfg.heartbeat_interval_seconds
                while time.monotonic() < deadline:
                    try:
                        _pump_queued_orders(cfg)
                    except (OSError, RuntimeError, ValueError) as error:
                        LOG.error("queued order pump failed: %s", redact_text(str(error)))
                    time.sleep(min(3.0, max(0.0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, LockBusy, subprocess.SubprocessError) as error:
        print(json.dumps({"error": redact_text(str(error))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
