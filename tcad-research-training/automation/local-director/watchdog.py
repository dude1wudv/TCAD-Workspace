import argparse
import json
import logging
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from codex_runner import finalize_and_precheck, launch_worker, terminate_worker
from campaign_fsm import (
    advance_phase,
    assert_holdout_read_allowed,
    ensure_campaign_files,
    is_operational_task,
    mark_task,
    next_phase,
    operational_work_order,
    recompute_gates,
    record_operational_cooldown,
    register_blocked,
    save_backlog,
    save_campaign,
    task_work_order,
)
from codex_supervisor import actionable, record_wakeup, run_supervisor, validate_action
from config import load_config
from probes import compute_state_fingerprint, probe_codex_worker, probe_server, probe_thesis, summarize_server
from runtime import (
    LockBusy,
    ParentWatcher,
    add_event,
    file_lock,
    hidden_subprocess_kwargs,
    load_state,
    order_dir,
    reclaim_orphaned_watchdog,
    save_state,
    silent_python_executable,
    state_lock,
)
from schemas import DeliveryReceipt, WorkOrder, append_jsonl, atomic_write, parse_time, read_json, write_json
from status_publisher import observe_campaign, redact_configured_text, redact_text, refresh_status


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


_URGENT_MILESTONE_KEYS = (
    "lhs_zero_pairs_collected",
    "lhs_halfstep_pairs_collected",
    "lhs_quartersteps_count",
    "lhs_eighthsteps_count",
    "d2_x10_feedback_count",
    "d2_x30_feedback_count",
    "repair_requests",
)
_ROUTINE_MILESTONE_KEYS = (
    "r06_released_runs",
    "lhs_transport_collected",
)
_MILESTONE_KEYS = (*_URGENT_MILESTONE_KEYS, *_ROUTINE_MILESTONE_KEYS)
_STARVE_COOLDOWN_SECONDS = 1200
_URGENT_ACTIONS = {
    "disk_floor", "server_health", "phase_gate", "worker_receipt_or_stall",
    "simulation_supply", "SLOTS_STARVING",
}


def _load_milestones(cfg):
    path = cfg.state_dir / "milestones.json"
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _milestone_increased(previous, current, keys=_MILESTONE_KEYS):
    changed = []
    for key in keys:
        old = previous.get(key)
        new = current.get(key)
        if isinstance(new, int) and isinstance(old, int) and new > old:
            changed.append(f"{key}:{old}->{new}")
        elif isinstance(new, list) and isinstance(old, list) and len(new) > len(old):
            changed.append(f"{key}:{len(old)}->{len(new)}")
        elif old is None and ((isinstance(new, int) and new > 0 and key == "repair_requests") or False):
            changed.append(f"{key}:0->{new}")
    return changed


def _observe_events(cfg, state, server, thesis, now, *, dry_run):
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

    summary = server.get("summary") if isinstance(server.get("summary"), dict) else summarize_server(server)
    active = state.active_order
    worker_busy = bool(active and active.get("status") in {"queued", "retry_queued", "running", "stalled"})
    milestones = _load_milestones(cfg)
    prev_counts = milestones.get("counts") if isinstance(milestones.get("counts"), dict) else {}
    cur_counts = {key: summary.get(key) for key in _MILESTONE_KEYS}
    urgent_deltas = _milestone_increased(prev_counts, cur_counts, _URGENT_MILESTONE_KEYS)
    routine_deltas = _milestone_increased(prev_counts, cur_counts, _ROUTINE_MILESTONE_KEYS)
    deltas = [*urgent_deltas, *routine_deltas]
    if urgent_deltas:
        add_event(state, "SIM_MILESTONE_COLLECTED", "urgent", ", ".join(deltas[:4]))
    elif routine_deltas:
        add_event(state, "SIM_MILESTONE_COLLECTED", "routine", ", ".join(routine_deltas[:4]))
    if summary.get("starved") and not worker_busy and _due(now, milestones.get("last_starve_at"), _STARVE_COOLDOWN_SECONDS):
        detail = (
            f"空闲 {summary.get('free_slots', 0)}/{summary.get('slots_total', 0)} 槽 · "
            f"运行 {summary.get('running', 0)} · 待排 {summary.get('ready', 0)} · "
            f"待验收 {summary.get('awaiting_acceptance', 0)} · 缺料 {summary.get('missing_material', 0)}"
        )
        add_event(state, "SLOTS_STARVING", "urgent", detail)
        milestones["last_starve_at"] = _timestamp(now)
    elif not summary.get("starved"):
        state.pending_events = [event for event in state.pending_events if event["reason"] != "SLOTS_STARVING"]
    if not dry_run and (deltas or not prev_counts or milestones.get("last_starve_at") == _timestamp(now)):
        milestones["counts"] = cur_counts
        write_json(cfg.state_dir / "milestones.json", milestones)

    fingerprint = compute_state_fingerprint(server, thesis)
    state.fingerprint = fingerprint
    state.pending_events = [entry for entry in state.pending_events
                            if entry["reason"] not in {"STATE_CHANGED", "PERIODIC_REVIEW"} and entry["bucket"] != "daily"]


def _pick_event(cfg, state, now, local_date, action_reason, force_trigger=None):
    if state.active_turn or not _due(now, state.wakeup_backoff_until):
        return None
    if action_reason is None or action_reason in {"cooldown", "worker_busy", "monitor_only"}:
        return None
    bucket = "urgent" if action_reason in _URGENT_ACTIONS else "routine"
    if not cfg.can_consume_codex(state, bucket, local_date):
        return None
    if action_reason == "backlog_ready" and state.daily_codex_used + 1 >= cfg.codex_daily_cap - cfg.codex_reserved_urgent:
        return None
    if not _due(now, state.next_wake_at) and action_reason != "worker_receipt_or_stall":
        return None
    return {"reason": action_reason, "bucket": bucket,
            "detail": redact_configured_text(cfg, force_trigger or "")[:120]}


def _write_briefing(cfg, state, event, server, thesis, now):
    names = ", ".join(entry["reason"] for entry in state.pending_events)
    active = state.active_order
    summary = server.get("summary") if isinstance(server.get("summary"), dict) else summarize_server(server)
    lines = [
        f"# Local Director 简报 · {_timestamp(now)}",
        f"- 本轮触发 `{event['reason']}` {event['detail']}",
        f"- 待处理事件 {names}",
        f"- 已用每日 Codex {state.daily_codex_used}/{cfg.codex_daily_cap}",
        f"- 服务器在线 {server.get('online')} · 来源 {server.get('source')} · 调度服务 {server.get('service_active')}",
        (
            f"- 槽位态势：运行 {summary.get('running', 0)} / 总 {summary.get('slots_total', 0)} · "
            f"空闲 {summary.get('free_slots', 0)} · 待排 {summary.get('ready', 0)} · "
            f"饥饿 {summary.get('starved', False)} · 待验收 {summary.get('awaiting_acceptance', 0)} · "
            f"缺料 {summary.get('missing_material', 0)}"
        ),
        f"- 论文 {thesis.get('chapters_done', 0)}/{thesis.get('chapters_total', 0)} 章 · 素材 {thesis.get('assets_count', 0)} · 构建 {thesis.get('build_ok')}",
        f"- 最近决策 {state.last_decision}",
    ]
    if summary.get("free_slots") and not summary.get("ready"):
        lines.append("- 严禁再派只读诊断工单！立即派发 sim-ops-refill 端到端工单，通过原 Runtime 完成验收、备料、发布批次并复查填槽。")
    if active:
        order = active["order"]
        lines.append(f"- 工单 `{order['order_id']}` · `{order['category']}` · {active['status']} · 第 {active['attempt']} 次")
        if active["status"] == "awaiting_review":
            location = order_dir(cfg, order["order_id"]) / "receipt.json"
            lines.append(f"- 收据相对状态目录 `{location.relative_to(cfg.state_dir.resolve()).as_posix()}`")
    if event["reason"] == "CODEX_CIRCUIT_BROKEN":
        lines.append("- 原工单已熔断，请评估新策略。")
    compact_payload = {"server_summary": summary, "thesis": thesis}
    data = redact_configured_text(cfg, json.dumps(compact_payload, ensure_ascii=False, default=str))
    header = redact_configured_text(cfg, "\n".join(lines))
    path = cfg.state_dir / "briefings" / f"brief-{now.strftime('%Y%m%dT%H%M%S%fZ')}.md"
    text = f"{header}\n\n## 紧凑态势摘要\n{data}"
    atomic_write(path, text.encode("utf-8")[:6143].decode("utf-8", "ignore") + "\n")
    return path


def _delivery(cfg, state):
    from director_ctl import _receipt

    active = state.active_order or {}
    if active.get("status") != "awaiting_review" or not active.get("campaign_task"):
        return None
    try:
        receipt = _receipt(cfg, active)
    except (OSError, ValueError):
        return {"passed": False}
    task_id = active.get("campaign_task")
    category = (active.get("order") or {}).get("category")
    allow_no_diff = is_operational_task(task_id) or category in {"sim_ops", "sim_repair", "data_extract", "predictor"}
    return {"passed": receipt.precheck_passed and (bool(receipt.git_changed_files) or allow_no_diff),
            "checks_passed": sum(check.get("passed") is True for check in receipt.verification_results)}


def _reject_campaign_task(cfg, state, campaign, backlog, reason, *, server=None, now=None):
    from director_ctl import cancel

    active = state.active_order
    task_id = active["campaign_task"]
    cancel(cfg, state, SimpleNamespace(order=active["order"]["order_id"], reason=reason))
    if is_operational_task(task_id):
        record_operational_cooldown(campaign, task_id, server, now=now)
        return
    task = mark_task(backlog, task_id, "pending", error=reason)
    if task["failures"] >= cfg.codex_max_task_failures:
        mark_task(backlog, task_id, "blocked")
        register_blocked(campaign, task_id, "checks_failed", reason, task["failures"])


def _check_campaign_dispatch(campaign, task_id):
    if task_id == "holdout-blind-eval":
        assert_holdout_read_allowed(campaign)
        if campaign["training"] != "ready" or campaign["holdout"]["blind_eval_count"] != 0:
            raise ValueError("holdout blind evaluation requires a ready model and no previous evaluation")


def _execute_decision(cfg, state, campaign, backlog, decision, delivery, now, *, urgent=False):
    from director_ctl import accept, dispatch

    validate_action(cfg, campaign, backlog, decision, state.to_dict(), delivery)
    task_id = decision["task"]
    reason = decision["reason"]
    action = decision["action"]
    if action == "dispatch":
        if is_operational_task(task_id):
            order = WorkOrder.from_dict(operational_work_order(task_id, created_by_turn="campaign-supervisor",
                                                               timeout_seconds=cfg.codex_default_timeout_seconds, now=now))
            dispatch_args = {"campaign_task": task_id, "now": now}
            if urgent:
                dispatch_args["urgent"] = True
            dispatch(cfg, state, order, **dispatch_args)
            return False
        task = next(item for item in backlog["tasks"] if item["task"] == task_id)
        _check_campaign_dispatch(campaign, task_id)
        order = WorkOrder.from_dict(task_work_order(task, created_by_turn="campaign-supervisor",
                                                   timeout_seconds=cfg.codex_default_timeout_seconds, now=now))
        try:
            dispatch_args = {"campaign_task": task_id, "now": now}
            if urgent:
                dispatch_args["urgent"] = True
            dispatch(cfg, state, order, **dispatch_args)
        finally:
            active = state.active_order or {}
            if (active.get("campaign_task") == task_id
                    and active.get("order", {}).get("order_id") == order.order_id):
                mark_task(backlog, task_id, "running")
        return False
    if action == "accept":
        if is_operational_task(task_id):
            accept(cfg, state, SimpleNamespace(order=state.active_order["order"]["order_id"], note=reason,
                                               commit_msg=None, push_pr=False, force=False))
            return True
        result = accept(cfg, state, SimpleNamespace(order=state.active_order["order"]["order_id"], note=reason,
                                                   commit_msg=f"feat(campaign): {task_id}", push_pr=False, force=False))
        mark_task(backlog, task_id, "accepted")
        p0_tasks = [item for item in backlog["tasks"] if "P0_BOOTSTRAP" in item["phase"]]
        if p0_tasks and all(item["status"] == "accepted" for item in p0_tasks):
            campaign["milestones"]["bootstrap_ready"] = True
            recompute_gates(campaign)
        return bool(result["commit"]) or True
    if action == "reject":
        _reject_campaign_task(cfg, state, campaign, backlog, reason)
    elif action == "blocked":
        task = mark_task(backlog, task_id, "blocked")
        register_blocked(campaign, task_id, decision["blocked_reason"], reason, task["failures"])
    elif action == "advance":
        return advance_phase(campaign, now=_timestamp(now)) is not None
    return False


def _record_supervisor(cfg, state, campaign, backlog, event, server, delivery, now, observed_progress):
    reason = event["reason"]
    state.active_turn = {"type": "codex_supervisor", "started_at": _timestamp(now), "reason": reason}
    state.daily_codex_used += 1
    save_state(cfg, state)
    try:
        decision = run_supervisor(cfg, campaign, backlog, server, state.to_dict(), reason, delivery)
        changed = _execute_decision(
            cfg, state, campaign, backlog, decision, delivery, now,
            urgent=event["bucket"] == "urgent",
        )
        record_wakeup(cfg, campaign, decision["action"], decision["task"], decision["reason"],
                      changed=changed or observed_progress, now=now)
        state.last_decision = decision["reason"][:500]
        state.last_periodic_at = _timestamp(now)
        state.wakeup_failures = 0
        state.wakeup_backoff_until = ""
        state.next_wake_at = (_timestamp(now + timedelta(seconds=decision["next_check_seconds"]))
                              if decision["action"] in {"noop", "log"} else "")
        state.pending_events = [item for item in state.pending_events if item["reason"] != "SIM_MILESTONE_COLLECTED"]
        append_jsonl(
            cfg.state_dir / "turns.jsonl",
            {
                "status": "supervisor_complete",
                "action": decision["action"],
                "task": decision.get("task"),
                "reason": decision["reason"],
                "cooldown_until": campaign.get("cooldown_until"),
                "at": _timestamp(now),
            },
        )
        return decision
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        delay = BACKOFF_SECONDS[min(state.wakeup_failures, len(BACKOFF_SECONDS) - 1)]
        state.wakeup_failures += 1
        state.wakeup_backoff_until = _timestamp(now + timedelta(seconds=delay))
        failure = redact_configured_text(cfg, str(error))[:300]
        record_wakeup(cfg, campaign, "error", None, failure, changed=observed_progress, now=now)
        append_jsonl(
            cfg.state_dir / "turns.jsonl",
            {
                "status": "supervisor_failed",
                "reason": event["reason"],
                "at": _timestamp(now),
                "error": failure,
                "retry_at": state.wakeup_backoff_until,
            },
        )
        return None
    finally:
        state.active_turn = None
        save_state(cfg, state)


def _tick_state(cfg, state, server, thesis, now, dry_run, force_trigger, scheduled_pulse=False):
    local_time = cfg.local_time(now)
    cfg.reset_day(state, local_time.date())
    campaign, backlog = ensure_campaign_files(cfg.state_dir, create=not dry_run)
    worker = probe_codex_worker(cfg, state)
    _advance_worker(cfg, state, worker, now, dry_run=dry_run)
    _observe_events(cfg, state, server, thesis, now, dry_run=dry_run)
    observed_progress = observe_campaign(cfg, campaign, server, now)
    if observed_progress:
        campaign["wakeups_without_progress"] = 0
    delivery = _delivery(cfg, state)
    if not dry_run and cfg.campaign_execution_enabled and delivery is not None:
        if not delivery["passed"]:
            _reject_campaign_task(
                cfg, state, campaign, backlog,
                "工单未通过确定性验收；查看对应收据或启动错误记录。",
                server=server, now=now,
            )
            delivery = None
        else:
            active_task = (state.active_order or {}).get("campaign_task")
            auto_decision = {
                "action": "accept",
                "task": active_task,
                "phase": campaign["phase"],
                "reason": "确定性预检与验收命令已通过，零配额自动签收。",
                "next_check_seconds": 60,
                "blocked_reason": None,
            }
            _execute_decision(cfg, state, campaign, backlog, auto_decision, delivery, now, urgent=True)
            if is_operational_task(active_task):
                record_operational_cooldown(campaign, active_task, server, now=now)
            campaign["wakeups_without_progress"] = 0
            campaign["last_progress_at"] = _timestamp(now)
            state.last_decision = auto_decision["reason"]
            append_jsonl(
                cfg.state_dir / "turns.jsonl",
                {"status": "auto_accept", "action": "accept", "task": active_task,
                 "reason": auto_decision["reason"], "at": _timestamp(now)},
            )
            delivery = None
    if not dry_run and cfg.campaign_execution_enabled and next_phase(campaign) is not None:
        advanced_to = advance_phase(campaign, now=_timestamp(now))
        if advanced_to:
            note = f"门控已满足，自动推进阶段至 {advanced_to}。"
            state.last_decision = note
            append_jsonl(
                cfg.state_dir / "turns.jsonl",
                {"status": "auto_advance", "action": "advance", "task": None,
                 "phase": advanced_to, "reason": note, "at": _timestamp(now)},
            )
    is_actionable, action_reason = actionable(
        cfg,
        campaign,
        backlog,
        server,
        state.to_dict(),
        now=now,
        scheduled_pulse=scheduled_pulse,
    )
    if action_reason == "simulation_supply" and any(
        item["reason"] == "SLOTS_STARVING" for item in state.pending_events
    ):
        action_reason = "SLOTS_STARVING"
    if action_reason is None and any(item["reason"] == "SIM_MILESTONE_COLLECTED" for item in state.pending_events):
        is_actionable, action_reason = True, "phase_gate"
    if action_reason is None and force_trigger:
        is_actionable, action_reason = True, "manual_review"
    event = _pick_event(cfg, state, now, local_time.date(), action_reason, force_trigger)
    result = {
        "dry_run": dry_run,
        "reason": event["reason"] if event else None,
        "bucket": event["bucket"] if event else None,
        "pending_events": [item["reason"] for item in state.pending_events],
        "supervisor": None,
        "daily_codex_used": state.daily_codex_used,
        "backoff_until": state.wakeup_backoff_until,
        "action_reason": action_reason,
    }
    if dry_run:
        result["actionable"] = is_actionable
        return result
    if event:
        _write_briefing(cfg, state, event, server, thesis, now)
        decision = _record_supervisor(cfg, state, campaign, backlog, event, server, delivery, now, observed_progress)
        result["supervisor"] = decision
        result["daily_codex_used"] = state.daily_codex_used
        result["backoff_until"] = state.wakeup_backoff_until
    save_campaign(cfg.state_dir, campaign)
    save_backlog(cfg.state_dir, backlog)
    save_state(cfg, state)
    refresh_status(cfg, state, server, thesis, publish=cfg.publish_campaign_status)
    return result


def _pump_queued_orders(cfg) -> bool:
    if not cfg.campaign_execution_enabled:
        return False
    with state_lock(cfg):
        state = load_state(cfg)
        active = state.active_order
        if (not active or active.get("status") not in {"queued", "retry_queued", "running", "stalled", "awaiting_review"}):
            queue_path = cfg.state_dir / "queue.json"
            if queue_path.is_file():
                try:
                    raw_queue = read_json(queue_path)
                except (OSError, ValueError):
                    raw_queue = []
                if isinstance(raw_queue, list) and raw_queue:
                    queued_item = raw_queue.pop(0)
                    write_json(queue_path, raw_queue)
                    queued_order = WorkOrder.from_dict(queued_item["order"])
                    now_utc = datetime.now(timezone.utc)
                    if cfg.can_consume_codex(state, "urgent" if queued_order.priority <= 2 else "routine", cfg.local_time(now_utc).date()):
                        directory = order_dir(cfg, queued_order.order_id)
                        directory.mkdir(parents=True, exist_ok=True)
                        active = {
                            "order": queued_order.to_dict(),
                            "status": "queued",
                            "attempt": 1,
                            "rejections": 0,
                            "run_meta": None,
                            "campaign_task": queued_order.order_id,
                        }
                        state.active_order = active
                        state.daily_codex_used += 1
                        save_state(cfg, state)
        if not active or active.get("status") not in {"queued", "retry_queued"}:
            return False
        order = WorkOrder.from_dict(active["order"])
        attempt = int(active.get("attempt", 1))
        retry = active.get("pending_retry") or {}
        previous = DeliveryReceipt.from_dict(retry["previous_receipt"]) if retry.get("previous_receipt") else None
        feedback = retry.get("feedback", "")
        try:
            if active.get("campaign_task") == "holdout-blind-eval":
                campaign, _ = ensure_campaign_files(cfg.state_dir, create=False)
                _check_campaign_dispatch(campaign, active["campaign_task"])
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


def tick(cfg, *, dry_run=False, force_trigger=None, now=None, scheduled_pulse=False):
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if cfg.campaign_expired(moment):
        return {"status": "campaign_expired", "supervisor": None}
    if dry_run:
        server = probe_server(cfg)
        thesis = probe_thesis(cfg)
        return _tick_state(cfg, load_state(cfg), server, thesis, moment, True, force_trigger, scheduled_pulse)
    try:
        with file_lock(cfg.state_dir / "tick.lock"):
            _pump_queued_orders(cfg)
            server = probe_server(cfg)
            thesis = probe_thesis(cfg)
            with state_lock(cfg):
                return _tick_state(cfg, load_state(cfg), server, thesis, moment, False, force_trigger, scheduled_pulse)
    except LockBusy:
        return {"status": "tick_busy", "supervisor": None}


def _daemon_argv(cfg) -> list[str]:
    argv = [silent_python_executable(sys.executable), "-B", str(Path(__file__).resolve())]
    if cfg.config_path:
        argv.extend(["--config", str(cfg.config_path)])
    argv.append("--daemon")
    return argv


def keepalive(cfg) -> dict:
    if cfg.campaign_expired(datetime.now(timezone.utc)):
        return {"status": "campaign_expired"}
    lock_path = cfg.state_dir / "watchdog.lock"
    try:
        with file_lock(lock_path):
            argv = _daemon_argv(cfg)
            detach = hidden_subprocess_kwargs(detached=True)
            with (cfg.state_dir / "watchdog.log").open("ab") as output:
                process = subprocess.Popen(argv, cwd=cfg.repo_root, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=output, **detach)
    except LockBusy:
        return {"status": "already_running"}
    return {"status": "started", "pid": process.pid}


@contextmanager
def _acquire_watchdog_lock(lock_path: Path, *, reclaim_orphan: bool = False):
    deadline = time.monotonic() + (4.0 if reclaim_orphan else 0.0)
    reclaimed = False
    while True:
        try:
            with file_lock(lock_path):
                yield
            return
        except LockBusy:
            if not reclaim_orphan:
                raise
            if not reclaimed and reclaim_orphaned_watchdog(lock_path):
                reclaimed = True
                continue
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Director 本地看门狗")
    parser.add_argument("--config", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--daemon", action="store_true")
    modes.add_argument("--tick", action="store_true")
    modes.add_argument("--keepalive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-trigger")
    parser.add_argument("--scheduled-pulse", action="store_true")
    parser.add_argument("--exit-with-parent", action="store_true")
    args = parser.parse_args(argv)
    if args.daemon and (args.dry_run or args.force_trigger or args.scheduled_pulse):
        parser.error("daemon mode does not accept tick-only options")
    if args.keepalive and (args.dry_run or args.force_trigger or args.scheduled_pulse or args.exit_with_parent):
        parser.error("keepalive mode does not accept tick-only or daemon-only options")
    if args.scheduled_pulse and not args.tick:
        parser.error("--scheduled-pulse requires --tick")
    if args.exit_with_parent and not args.daemon:
        parser.error("--exit-with-parent requires --daemon")
    try:
        cfg = load_config(args.config)
        if args.keepalive:
            print(json.dumps(keepalive(cfg), ensure_ascii=False))
            return 0
        if args.dry_run:
            print(json.dumps(tick(
                cfg,
                dry_run=True,
                force_trigger=args.force_trigger,
                scheduled_pulse=args.scheduled_pulse,
            ), ensure_ascii=False))
            return 0
        if args.tick:
            print(json.dumps(tick(cfg, force_trigger=args.force_trigger,
                                  scheduled_pulse=args.scheduled_pulse), ensure_ascii=False))
            return 0
        watcher = ParentWatcher() if args.exit_with_parent else None
        try:
            with _acquire_watchdog_lock(cfg.state_dir / "watchdog.lock", reclaim_orphan=bool(args.exit_with_parent)):
                while True:
                    cfg = load_config(args.config)
                    if cfg.campaign_expired(datetime.now(timezone.utc)):
                        print('{"status": "campaign_expired"}', flush=True)
                        return 0
                    if watcher and watcher.parent_exited():
                        print(json.dumps({"status": "parent_exited", "ppid": watcher.ppid}, ensure_ascii=False), flush=True)
                        return 0
                    started = time.monotonic()
                    try:
                        result = tick(
                            cfg,
                            force_trigger=args.force_trigger,
                            scheduled_pulse=args.scheduled_pulse,
                        )
                        print(json.dumps(result, ensure_ascii=False), flush=True)
                    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                        if not args.daemon:
                            raise
                        LOG.error("watchdog tick failed: %s", redact_text(str(error)))
                    deadline = started + cfg.heartbeat_interval_seconds
                    while time.monotonic() < deadline:
                        if cfg.campaign_expired(datetime.now(timezone.utc)):
                            break
                        if watcher and watcher.parent_exited():
                            print(json.dumps({"status": "parent_exited", "ppid": watcher.ppid}, ensure_ascii=False), flush=True)
                            return 0
                        try:
                            _pump_queued_orders(cfg)
                        except (OSError, RuntimeError, ValueError) as error:
                            LOG.error("queued order pump failed: %s", redact_text(str(error)))
                        time.sleep(min(3.0, max(0.0, deadline - time.monotonic())))
        finally:
            if watcher is not None:
                watcher.close()
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, LockBusy, subprocess.SubprocessError) as error:
        print(json.dumps({"error": redact_text(str(error))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    raise SystemExit(main())
