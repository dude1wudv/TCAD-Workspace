import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_runner import commit_paths, finalize_and_precheck, launch_worker, terminate_worker
from config import load_config
from notifier import notify
from probes import probe_codex_worker
from runtime import LockBusy, add_event, clear_order_events, file_lock, load_state, order_dir, save_state, state_lock
from schemas import DecisionEntry, DeliveryReceipt, QueueItem, WorkOrder, append_jsonl, read_json, utc_now, write_json
from status_publisher import redact_configured_text, redact_text, refresh_status


DECISION_LOG = Path("tcad-research-training/plans/dram-se-ddr5-lpddr5/AUTO-DECISION-LOG.md")


def brief_state(state):
    active = state.active_order
    result = {"updated_at": state.updated_at, "daily_date": state.daily_date,
              "daily_codex_used": state.daily_codex_used,
              "active_turn": bool(state.active_turn), "pending_events": [entry["reason"] for entry in state.pending_events]}
    result["active_order"] = {
        "order_id": active["order"]["order_id"], "status": active["status"], "attempt": active["attempt"],
        "category": active["order"]["category"],
    } if active else None
    return result


def _order_from_file(cfg, path):
    raw = read_json(path)
    if type(raw) is dict:
        raw.setdefault("timeout_seconds", cfg.codex_default_timeout_seconds)
        raw.setdefault("created_at", utc_now())
        raw.setdefault("created_by_turn", "manual")
        raw.setdefault("priority", 3)
        raw.setdefault("max_rejections", 3)
        raw.setdefault("forbidden_actions", [])
        raw.setdefault("acceptance_checks", [])
    return WorkOrder.from_dict(raw)


def _active(state, order_id):
    active = state.active_order
    if not active or active["order"]["order_id"] != order_id:
        raise ValueError("order is not the active order")
    return active


def _receipt(cfg, active):
    order_id = active["order"]["order_id"]
    receipt = DeliveryReceipt.from_dict(read_json(order_dir(cfg, order_id) / "receipt.json"))
    if receipt.order_id != order_id or receipt.attempt != active["attempt"]:
        raise ValueError("receipt does not match this order attempt")
    return receipt


def _codex_slot(cfg, state, *, urgent: bool = False, now: datetime | None = None):
    moment = now or datetime.now(timezone.utc)
    local_date = cfg.local_time(moment).date()
    bucket = "urgent" if urgent else "routine"
    if not cfg.can_consume_codex(state, bucket, local_date):
        raise ValueError("daily Codex cap reached")


def _watchdog_daemon_running(cfg) -> bool:
    try:
        with file_lock(cfg.state_dir / "watchdog.lock"):
            return False
    except LockBusy:
        return True
    except OSError:
        return False


def _wait_for_order(cfg, order_id: str) -> dict:
    while True:
        state = load_state(cfg)
        active = _active(state, order_id)
        if active["status"] not in {"running", "stalled"}:
            return {"order_id": order_id, "status": active["status"]}
        worker = probe_codex_worker(cfg, state)
        if worker["status"] in {"exited", "timeout"}:
            with state_lock(cfg):
                state = load_state(cfg)
                active = _active(state, order_id)
                order = WorkOrder.from_dict(active["order"])
                meta = active["run_meta"]
                if worker["status"] == "timeout":
                    if not terminate_worker(meta, "timeout"):
                        raise RuntimeError("worker timeout termination was not confirmed")
                    meta = {**meta, "status_override": "timeout"}
                receipt = finalize_and_precheck(cfg, order, meta)
                active["status"] = "awaiting_review"
                clear_order_events(state)
                state.recent_public_note = "工单等待审阅"
                save_state(cfg, state)
                refresh_status(cfg, state, publish=False)
                return {"order_id": order_id, "status": "awaiting_review", "receipt": receipt.to_dict()}
        time.sleep(2.0)


def dispatch(cfg, state, order, *, wait: bool = False, campaign_task: str | None = None,
             now: datetime | None = None, urgent: bool = False):
    if state.active_order and state.active_order["status"] in {"queued", "retry_queued", "running", "stalled", "awaiting_review"}:
        raise ValueError("finish the current order before dispatching another")
    _codex_slot(cfg, state, urgent=urgent, now=now)
    directory = order_dir(cfg, order.order_id)
    directory.mkdir(parents=True, exist_ok=False)
    active = {
        "order": order.to_dict(),
        "status": "queued",
        "attempt": 1,
        "rejections": 0,
        "run_meta": None,
        "campaign_task": campaign_task,
    }
    if not wait and _watchdog_daemon_running(cfg):
        state.active_order = active
        state.daily_codex_used += 1
        state.last_stall_at = ""
        clear_order_events(state)
        save_state(cfg, state)
        return {"order_id": order.order_id, "status": "queued"}
    state.active_order = active
    state.daily_codex_used += 1
    state.last_stall_at = ""
    clear_order_events(state)
    save_state(cfg, state)
    try:
        run_meta = launch_worker(cfg, order, attempt=1)
    except (OSError, RuntimeError, ValueError) as error:
        state.daily_codex_used -= 1
        state.active_order = None
        write_json(directory / "launch_error.json", {"error": redact_text(str(error))})
        save_state(cfg, state)
        raise
    active.update(status="running", run_meta=run_meta)
    state.active_order = active
    save_state(cfg, state)
    return {"order_id": order.order_id, "pid": run_meta["pid"], "status": "running"}


def _git(cfg, *argv, env=None):
    result = subprocess.run(["git", *argv], cwd=cfg.repo_root, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise RuntimeError(f"git {argv[0]} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def _work_branch(cfg):
    branch = _git(cfg, "branch", "--show-current")
    if branch != cfg.branch_name or branch.casefold() in {"main", "master"}:
        raise ValueError("Git writes require the configured work branch")
    return branch


def _push_pr(cfg, branch, title):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    _git(cfg, "push", "origin", f"HEAD:refs/heads/{branch}", env=env)
    query = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "open", "--limit", "1", "--json", "url"],
                           cwd=cfg.repo_root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    existing = json.loads(query.stdout)
    if existing:
        return existing[0]["url"]
    result = subprocess.run(["gh", "pr", "create", "--draft", "--head", branch, "--base", "main", "--title", title,
                             "--body", "Local Director 工单交付。请审阅改动、验证收据及未验证范围。"],
                            cwd=cfg.repo_root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return result.stdout.strip()


def accept(cfg, state, args):
    active = _active(state, args.order)
    if active["status"] != "awaiting_review":
        raise ValueError("order is not awaiting review")
    receipt = _receipt(cfg, active)
    if not receipt.precheck_passed and not args.force:
        raise ValueError("receipt precheck failed; explicit --force is required")
    order = WorkOrder.from_dict(active["order"])
    if any(redact_configured_text(cfg, value) != value for value in (args.note, args.commit_msg or "")):
        raise ValueError("acceptance note or commit message contains sensitive text")
    branch = _work_branch(cfg) if args.commit_msg or args.push_pr else None
    if args.commit_msg and not active.get("commit"):
        paths = commit_paths(cfg, order, active["run_meta"], receipt)
        if paths:
            env = dict(os.environ, GIT_LITERAL_PATHSPECS="1")
            untracked = _git(cfg, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths, env=env).strip("\0").split("\0")
            if untracked[0]:
                subprocess.run(["git", "add", "-N", "--", *untracked], cwd=cfg.repo_root, env=env, check=True, timeout=60)
            _git(cfg, "commit", "--only", "-m", args.commit_msg, "--", *paths, env=env)
            active["commit"] = _git(cfg, "rev-parse", "HEAD")
            save_state(cfg, state)
    if args.push_pr:
        active["pr_url"] = _push_pr(cfg, branch, args.commit_msg or f"Local Director {order.order_id}")
    active.update(status="accepted", note=args.note, closed_at=utc_now(), forced=args.force)
    clear_order_events(state)
    state.recent_public_note = "工单已完成审阅"
    save_state(cfg, state)
    return {"order_id": args.order, "status": "accepted", "commit": active.get("commit"), "pr_url": active.get("pr_url")}


def reject(cfg, state, args):
    active = _active(state, args.order)
    if active["status"] not in {"awaiting_review", "stalled"}:
        raise ValueError("order has no delivery or stall to reject")
    order = WorkOrder.from_dict(active["order"])
    rejections = active["rejections"] + 1
    if rejections < order.max_rejections:
        _codex_slot(cfg, state)
    if active["status"] == "stalled":
        from codex_runner import finalize_and_precheck

        if not terminate_worker(active["run_meta"], "stalled"):
            raise RuntimeError("worker termination was not confirmed")
        finalize_and_precheck(cfg, order, {**active["run_meta"], "status_override": "stalled"})
        active["status"] = "awaiting_review"
        save_state(cfg, state)
    receipt = _receipt(cfg, active)
    feedback = redact_text(args.feedback)
    clear_order_events(state)
    if rejections >= order.max_rejections:
        active.update(status="circuit_broken", rejections=rejections, note=feedback, closed_at=utc_now())
        add_event(state, "CODEX_CIRCUIT_BROKEN", "urgent", order.order_id)
        state.recent_public_note = "工单熔断，等待换策略"
        save_state(cfg, state)
        notification = notify(cfg, "alert", f"工单 {order.order_id} 已熔断", feedback)
        return {"order_id": order.order_id, "status": "circuit_broken", "rejections": rejections, "notification": notification}
    attempt = active["attempt"] + 1
    wait = bool(getattr(args, "wait", False))
    if not wait and _watchdog_daemon_running(cfg):
        active.update(status="retry_queued", attempt=attempt, rejections=rejections,
                      pending_retry={"previous_receipt": receipt.to_dict(), "feedback": feedback})
        state.last_stall_at = ""
        state.daily_codex_used += 1
        save_state(cfg, state)
        return {"order_id": order.order_id, "status": "retry_queued", "attempt": attempt}
    run_meta = launch_worker(cfg, order, attempt=attempt, previous_receipt=receipt, feedback=feedback)
    active.update(status="running", attempt=attempt, rejections=rejections, run_meta=run_meta)
    active.pop("pending_retry", None)
    state.last_stall_at = ""
    state.daily_codex_used += 1
    save_state(cfg, state)
    return {"order_id": order.order_id, "pid": run_meta["pid"], "status": "running", "attempt": attempt}


def cancel(cfg, state, args):
    active = _active(state, args.order)
    if active["status"] not in {"queued", "retry_queued", "running", "stalled", "awaiting_review"}:
        raise ValueError("order is already closed")
    if active["status"] in {"running", "stalled"}:
        if not terminate_worker(active["run_meta"], "cancelled"):
            raise RuntimeError("worker termination was not confirmed")
    active.update(status="cancelled", note=redact_text(args.reason), closed_at=utc_now())
    append_jsonl(cfg.state_dir / "order-events.jsonl", {"order_id": args.order, "status": "cancelled", "reason": active["note"], "at": active["closed_at"]})
    clear_order_events(state)
    save_state(cfg, state)
    return {"order_id": args.order, "status": "cancelled"}


def _append(path, markdown):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)


def log_decision(cfg, state, args):
    body = args.body_file.read_text(encoding="utf-8-sig")
    entry = DecisionEntry(decision_type=args.type, title=redact_configured_text(cfg, args.title),
                          body=redact_configured_text(cfg, body), cases=[
                              redact_configured_text(cfg, item.strip())
                              for item in (args.cases or "").split(",") if item.strip()
                          ])
    destination = cfg.repo_root / DECISION_LOG
    if not destination.resolve().is_relative_to(cfg.repo_root.resolve()):
        raise ValueError("decision log must stay in the repository")
    cases = f"\n\n案例：{', '.join(entry.cases)}" if entry.cases else ""
    markdown = f"\n## {entry.created_at} · {entry.decision_type} · {entry.title}\n\n{entry.body.strip()}{cases}\n"
    _append(cfg.state_dir / "worklog.md", markdown)
    append_jsonl(cfg.state_dir / "decisions.jsonl", entry.to_dict())
    _append(destination, markdown)
    state.last_decision = entry.title[:240]
    state.recent_public_note = "科研决策已登记"
    save_state(cfg, state)
    result = {"status": "logged", "type": entry.decision_type}
    if entry.decision_type == "criterion_amendment":
        result["notification"] = notify(cfg, "alert", f"判据修订：{entry.title}", entry.body)
    return result


def _queue(cfg, args):
    path = cfg.state_dir / "queue.json"
    try:
        items = [QueueItem.from_dict(item) for item in read_json(path)]
    except FileNotFoundError:
        items = []
    if args.command == "queue-add":
        order = _order_from_file(cfg, args.file)
        if any(item.order["order_id"] == order.order_id for item in items) or order_dir(cfg, order.order_id).exists():
            raise ValueError("order ID already exists")
        items.append(QueueItem(order=order.to_dict()))
    items.sort(key=lambda item: (-item.order["priority"], item.enqueued_at))
    if args.command == "queue-list":
        return [item.to_dict() for item in items]
    result = items.pop(0).to_dict() if args.command == "queue-pop" and items else None
    write_json(path, [item.to_dict() for item in items])
    return result if args.command == "queue-pop" else {"order_id": order.order_id, "status": "queued"}


def _parser():
    parser = argparse.ArgumentParser(description="Local Director 工单和决策控制")
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "dispatch", "accept", "reject", "cancel", "log-decision", "queue-add", "queue-list", "queue-pop", "notify", "finish-turn"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, default=argparse.SUPPRESS)
        if name in {"dispatch", "queue-add"}:
            command.add_argument("--file", type=Path, required=True)
        if name in {"dispatch", "reject"}:
            command.add_argument("--wait", action="store_true")
        if name in {"accept", "reject", "cancel"}:
            command.add_argument("--order", required=True)
        if name == "accept":
            command.add_argument("--note", required=True)
            command.add_argument("--commit-msg")
            command.add_argument("--push-pr", action="store_true")
            command.add_argument("--force", action="store_true")
        if name == "reject":
            command.add_argument("--feedback", required=True)
        if name == "cancel":
            command.add_argument("--reason", required=True)
        if name in {"log-decision", "notify"}:
            command.add_argument("--body-file", type=Path, required=True)
        if name == "log-decision":
            command.add_argument("--type", choices=("strategy", "criterion_amendment", "escalation", "thesis_plan"), required=True)
            command.add_argument("--title", required=True)
            command.add_argument("--cases")
        if name == "notify":
            command.add_argument("--level", choices=("alert", "digest"), required=True)
            command.add_argument("--subject", required=True)
        if name == "finish-turn":
            command.add_argument("--summary", required=True)
            command.add_argument("--next-wake-hint", type=int)
    return parser


def _execute(cfg, args):
    if args.command == "notify":
        return notify(cfg, args.level, args.subject, args.body_file.read_text(encoding="utf-8-sig"))
    if args.command == "status":
        return brief_state(load_state(cfg))
    wait_order_id = None
    with state_lock(cfg):
        state = load_state(cfg)
        if args.command.startswith("queue-"):
            return _queue(cfg, args)
        if args.command == "dispatch":
            result = dispatch(cfg, state, _order_from_file(cfg, args.file), wait=bool(getattr(args, "wait", False)))
            if getattr(args, "wait", False) and result.get("status") == "running":
                wait_order_id = result["order_id"]
            else:
                return result
        elif args.command == "accept":
            return accept(cfg, state, args)
        elif args.command == "reject":
            result = reject(cfg, state, args)
            if getattr(args, "wait", False) and result.get("status") == "running":
                wait_order_id = result["order_id"]
            else:
                return result
        elif args.command == "cancel":
            return cancel(cfg, state, args)
        elif args.command == "log-decision":
            return log_decision(cfg, state, args)
        else:
            if args.next_wake_hint is not None and args.next_wake_hint < 0:
                raise ValueError("next wake hint must be nonnegative")
            state.active_turn = None
            state.last_decision = redact_configured_text(cfg, args.summary)[:500]
            state.next_wake_at = (datetime.now(timezone.utc) + timedelta(seconds=args.next_wake_hint)).isoformat() if args.next_wake_hint else ""
            append_jsonl(cfg.state_dir / "turns.jsonl", {"status": "finished", "summary": state.last_decision, "at": utc_now()})
            save_state(cfg, state)
            refresh_status(cfg, state, publish=False)
            return {"status": "finished", "next_wake_at": state.next_wake_at}
    if wait_order_id:
        return _wait_for_order(cfg, wait_order_id)
    return result


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        print(json.dumps(_execute(cfg, args), ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": redact_text(str(error))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
