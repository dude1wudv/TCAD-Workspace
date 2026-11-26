"""Write a local director dashboard and publish its whitelisted status projection."""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import unicodedata
from datetime import datetime, timezone

from campaign_fsm import apply_progress, load_campaign, public_campaign_with_metrics, update_public_metrics
from config import ssh_command
from notifier import find_sensitive, redact_text
from runtime import hidden_subprocess_kwargs
from schemas import atomic_write, read_json, utc_now, write_json


LOG = logging.getLogger(__name__)
_ORDER_CATEGORIES = {
    "sim_ops", "sim_repair", "data_extract", "predictor", "thesis_assets", "latex_build", "web_status",
}
_ORDER_STATES = {
    "idle": "idle",
    "queued": "running",
    "retry_queued": "retrying",
    "running": "running",
    "dispatching": "running",
    "delivered": "awaiting_audit",
    "awaiting_audit": "awaiting_audit",
    "awaiting_review": "awaiting_audit",
    "failed": "awaiting_audit",
    "timeout": "awaiting_audit",
    "stalled": "awaiting_audit",
    "retrying": "retrying",
    "circuit_broken": "circuit_broken",
}
_PRIVATE_NOTE = re.compile(
    r"[a-z0-9]+-[a-z0-9]+|[a-z0-9]+\.[a-z]{2,}|(?<![a-z0-9])--?[a-z]"
    r"|\b(?:hr|hp)[0-9]*\b|\b[0-9a-f]{12,}\b"
    r"|\b(?:tcad|hk|sub[0-9]+|localhost|tailscale|hostname|holdout|run[ -]?ids?"
    r"|password|passwd|token|secret|credential|authorization|bearer|license|api[ -]?key"
    r"|rsync|sftp|cmd|python[0-9]*|npm|docker|git|chmod|chown|mkdir|rm|cat|grep|cd|ls"
    r"|whoami|scp|sudo|systemctl|curl|wget|bash|powershell|accepted|succeeded|converged)\b"
    r"|\b(?:solver|simulation|validation)\s+(?:success\w*|passed)\b"
    r"|密码|密钥|令牌|凭据|许可证|连接地址|内部编号|封存留出"
    r"|求解成功|仿真成功|验收通过|已验收|验证通过|复验通过|已收敛",
    re.IGNORECASE | re.ASCII,
)


def _public_note(value, ssh_target):
    if not isinstance(value, str) or len(value) > 160:
        return None
    if any(unicodedata.category(char).startswith("C") for char in value):
        return None
    text = unicodedata.normalize("NFKC", value)
    if not all(char.isalnum() or char in " .,!?()-。！？、，" for char in text):
        return None
    if find_sensitive(text) or _PRIVATE_NOTE.search(text):
        return None
    alias = ssh_target.rpartition("@")[2]
    if alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text, re.I | re.ASCII):
        return None
    return value.strip() or None


def _utc(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _count(value) -> int:
    return value if type(value) is int and value >= 0 else 0


def redact_configured_text(cfg, text: str) -> str:
    paths = (
        cfg.repo_root, cfg.state_dir,
        cfg.remote_policy_path, cfg.remote_observation_path, cfg.remote_director_status_path,
    )
    values = {form for path in paths if path
              for form in (str(path), str(path).replace("\\", "/"))}
    aliases = {cfg.server_ssh_target, cfg.server_ssh_target.rpartition("@")[2]}
    patterns = [re.escape(value) for value in sorted(values, key=len, reverse=True) if len(value) > 2]
    patterns.extend(rf"(?<![a-z0-9_.-]){re.escape(alias)}(?![a-z0-9_.-])"
                    for alias in sorted(aliases, key=len, reverse=True) if alias)
    if patterns:
        text = re.sub("|".join(patterns), "[REDACTED]", text, flags=re.IGNORECASE)
    return redact_text(text)


def _public_snapshot(cfg, state, server, thesis, now, stamp) -> dict:
    active_order = state.get("active_order") or {}
    order = active_order.get("order") or {}
    category = order.get("category") if isinstance(order, dict) else None
    status = active_order.get("status")
    valid_order = (
        isinstance(category, str) and category in _ORDER_CATEGORIES
        and isinstance(status, str) and status in _ORDER_STATES
    )
    order_state = _ORDER_STATES[status] if valid_order else "idle"
    attempt = _count(active_order.get("attempt")) if valid_order else 0
    if order_state == "running" and attempt > 1:
        order_state = "retrying"

    backoff = _utc(state.get("wakeup_backoff_until"))
    if state.get("server_offline") or server.get("online") is False:
        director_state = "offline"
    elif state.get("active_turn") is not None:
        director_state = "codex_supervisor_active"
    elif order_state in {"running", "retrying"}:
        director_state = "codex_running"
    elif backoff is not None and backoff > now:
        director_state = "backoff"
    elif server or active_order or state.get("pending_events"):
        director_state = "monitoring"
    else:
        director_state = "idle"

    total = _count(thesis.get("total", thesis.get("chapters_total")))
    sprint = _utc(thesis.get("last_sprint_utc"))
    build_ok = thesis.get("build_ok", thesis.get("last_build_ok"))
    return {
        "schema_version": 1,
        "director_state": director_state,
        "mode": "event_driven",
        "updated_at": stamp,
        "daily_codex_used": _count(state.get("daily_codex_used")),
        "daily_codex_cap": _count(cfg.codex_daily_cap),
        "active_order_category": category if valid_order else "none",
        "active_order_state": order_state,
        "active_order_attempt": attempt,
        "thesis_chapters_done": min(_count(thesis.get("chapters_done")), total),
        "thesis_chapters_total": total,
        "thesis_last_sprint_utc": sprint.isoformat().replace("+00:00", "Z") if sprint else None,
        "thesis_build_ok": build_ok if type(build_ok) is bool else None,
        "recent_public_note": _public_note(state.get("recent_public_note"), cfg.server_ssh_target),
    }


def _metric(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _first_metric(*values) -> int | None:
    return next((value for value in values if _metric(value) is not None), None)


def _campaign_disks(server: dict) -> dict[str, int | None]:
    summary = server.get("summary") if isinstance(server.get("summary"), dict) else {}
    observation = server.get("observation") if isinstance(server.get("observation"), dict) else {}
    scheduler = observation.get("scheduler") if isinstance(observation.get("scheduler"), dict) else {}
    virtual_machine = scheduler.get("virtual_machine") if isinstance(scheduler.get("virtual_machine"), dict) else {}
    storage = virtual_machine.get("storage") if isinstance(virtual_machine.get("storage"), dict) else {}
    server_storage = server.get("storage") if isinstance(server.get("storage"), dict) else {}
    growth = server.get("vm_disk_growth") if isinstance(server.get("vm_disk_growth"), dict) else {}
    return {
        "server_free_bytes": _first_metric(
            server.get("server_free_bytes"), summary.get("server_free_bytes"), server_storage.get("available_bytes")
        ),
        "vm_allocated_bytes": _first_metric(
            server.get("vm_allocated_bytes"), summary.get("vm_allocated_bytes"), storage.get("total_bytes")
        ),
        "vm_free_bytes": _first_metric(
            server.get("vm_free_bytes"), summary.get("vm_free_bytes"), storage.get("available_bytes")
        ),
        "vm_growth_bytes": _first_metric(
            server.get("vm_growth_bytes"), summary.get("vm_growth_bytes"), growth.get("available_bytes")
        ),
    }


def observe_campaign(cfg, campaign, server, now) -> bool:
    """Project verified server, progress, and archive evidence into campaign state."""
    update_public_metrics(campaign, disks=_campaign_disks(server))
    changed = False
    summary = server.get("summary") if isinstance(server.get("summary"), dict) else {}
    block_counts = summary.get("block_accepted_counts")
    if isinstance(block_counts, dict) and block_counts:
        before_blocks = {k: v.get("accepted") for k, v in campaign.get("blocks", {}).items()}
        apply_progress(campaign, {"blocks": block_counts})
        after_blocks = {k: v.get("accepted") for k, v in campaign.get("blocks", {}).items()}
        if any((after_blocks.get(k) or 0) > (before_blocks.get(k) or 0) for k in after_blocks if after_blocks.get(k) is not None):
            changed = True
    progress_path = cfg.state_dir / "campaign-progress.json"
    if progress_path.is_file():
        try:
            progress = read_json(progress_path)
            if isinstance(progress, dict):
                before_snapshot = json.dumps(
                    {k: campaign.get(k) for k in ("blocks", "milestones", "training", "desk", "holdout")},
                    sort_keys=True,
                )
                apply_progress(campaign, progress)
                after_snapshot = json.dumps(
                    {k: campaign.get(k) for k in ("blocks", "milestones", "training", "desk", "holdout")},
                    sort_keys=True,
                )
                if after_snapshot != before_snapshot:
                    changed = True
        except (OSError, ValueError):
            LOG.warning("Campaign progress file is unreadable or invalid.")
    try:
        archive = read_json(cfg.state_dir / "archive-summary.json")
    except FileNotFoundError:
        archive = None
    except (OSError, ValueError):
        LOG.warning("Campaign archive summary is unreadable.")
        archive = None
    if isinstance(archive, dict) and archive.get("schema") == "tcad-result-archive-summary-v1":
        counts = {key: _metric(archive.get(key)) for key in ("mirrored", "cloud_verified")}
        if all(value is not None for value in counts.values()):
            for key, value in counts.items():
                if value > campaign["archive"][key]:
                    campaign["archive"][key] = value
                    changed = True
        else:
            LOG.warning("Campaign archive summary has invalid counts.")
    elif archive is not None:
        LOG.warning("Campaign archive summary has an unexpected schema.")
    if changed:
        campaign["last_progress_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    return changed


def _campaign_snapshot(cfg, server, state):
    campaign = load_campaign(cfg.state_dir, create=False)
    public = public_campaign_with_metrics(campaign)
    public["codex"] = {
        "used": _count(state.get("daily_codex_used")),
        "cap": _count(cfg.codex_daily_cap),
        "reserved": _count(cfg.codex_reserved_urgent),
    }
    public["disks"] = _campaign_disks(server)
    return public


def _send_snapshot(cfg, snapshot) -> str | None:
    target = cfg.remote_director_status_path
    if not target.startswith("/") or target.rsplit("/", 1)[-1] in {"", ".", ".."} or "\0" in target:
        return "invalid_publish_path"
    script = (
        f"set -eu\ntarget={shlex.quote(target)}\n"
        'staging=$(mktemp -- "${target}.XXXXXX")\n'
        'trap \'rm -f -- "$staging"\' EXIT\n'
        'cat > "$staging"\nchmod 0644 -- "$staging"\n'
        'mv -fT -- "$staging" "$target"\n'
    )
    payload = (json.dumps(snapshot, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    try:
        result = subprocess.run(
            ssh_command(cfg, script), input=payload, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30, check=False, **hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return "publish_timeout"
    except OSError:
        return "publish_unavailable"
    except ValueError:
        return "invalid_publish_config"
    return None if result.returncode == 0 else f"publish_exit_{result.returncode}"


def _is_recent(value, now, interval) -> bool:
    stamp = _utc(value)
    return stamp is not None and 0 <= (now - stamp).total_seconds() < interval


def _publish(cfg, snapshot, now) -> tuple[str, str | None]:
    if not cfg.server_ssh_target or not cfg.remote_director_status_path:
        return "unconfigured", "publish_unconfigured"
    receipt_path = cfg.state_dir / "status-publish.json"
    try:
        receipt = read_json(receipt_path)
    except FileNotFoundError:
        receipt = {}
    except (OSError, ValueError):
        return "failed", "publish_receipt_unreadable"
    destination = [cfg.server_ssh_target, cfg.remote_director_status_path]
    if not isinstance(receipt, dict) or receipt.get("destination") != destination:
        receipt = {"destination": destination}

    content = {key: value for key, value in snapshot.items() if key != "updated_at"}
    interval = min(cfg.heartbeat_interval_seconds, 300)
    if receipt.get("warning") and _is_recent(receipt.get("attempted_at"), now, interval):
        return "retry_wait", receipt["warning"]
    if receipt.get("content") == content and _is_recent(receipt.get("published_at"), now, interval):
        return "unchanged", None

    warning = _send_snapshot(cfg, snapshot)
    receipt.update(attempted_at=snapshot["updated_at"], warning=warning)
    if warning is None:
        receipt.update(published_at=snapshot["updated_at"], content=content)
    try:
        write_json(receipt_path, receipt)
    except OSError:
        return ("published" if warning is None else "failed"), "publish_receipt_write_failed"
    return ("published" if warning is None else "failed"), warning


def refresh_status(cfg, state, server_snap=None, thesis_snap=None, *, publish=True) -> dict:
    """Refresh local files and optionally ship only the public JSON over SSH."""
    local_state = state.to_dict()
    now = _utc(utc_now())
    stamp = now.isoformat().replace("+00:00", "Z")
    snapshot_path = cfg.state_dir / "auto-director-public.json"
    dashboard_only = not publish and server_snap is None and thesis_snap is None
    warning = None
    if thesis_snap is None:
        try:
            previous = read_json(snapshot_path)
            if not isinstance(previous, dict):
                raise ValueError("invalid cached snapshot")
        except FileNotFoundError:
            previous = {}
        except (OSError, ValueError):
            previous = {}
            warning = "local_snapshot_unreadable"
        thesis_snap = {
            "chapters_done": previous.get("thesis_chapters_done"),
            "total": previous.get("thesis_chapters_total"),
            "last_sprint_utc": previous.get("thesis_last_sprint_utc"),
            "build_ok": previous.get("thesis_build_ok"),
        }
    server = server_snap or {}
    snapshot = _public_snapshot(cfg, local_state, server, thesis_snap or {}, now, stamp)
    try:
        snapshot["campaign"] = _campaign_snapshot(cfg, server, local_state)
    except (OSError, ValueError):
        snapshot["campaign"] = None
    if not dashboard_only:
        write_json(snapshot_path, snapshot)
    publish_state, publish_warning = _publish(cfg, snapshot, now) if publish else ("skipped", None)
    decision = redact_configured_text(cfg, local_state.get("last_decision") or "—")
    active = local_state.get("active_order") or {}
    turn = local_state.get("active_turn") or {}
    pending = ", ".join(event["reason"] for event in local_state["pending_events"]) or "—"
    server = server_snap or {}
    lines = [
        "# Auto-Director", "",
        f"- 刷新时间：{stamp}",
        f"- 状态记录时间：{local_state.get('updated_at') or '—'}",
        f"- 总监状态：{snapshot['director_state']}",
        f"- 今日 Codex：{snapshot['daily_codex_used']} / {snapshot['daily_codex_cap']}",
        f"- 工单：{snapshot['active_order_category']} / {snapshot['active_order_state']}"
        f"（第 {snapshot['active_order_attempt']} 次）",
        f"- 本地工单状态：{(active.get('order') or {}).get('order_id', '—')} / {active.get('status', '—')}",
        f"- 活动回合：{turn.get('reason', '—')} / {turn.get('started_at', '—')}",
        f"- 待处理事件：{redact_configured_text(cfg, pending)}",
        f"- 服务器采样：{server.get('source', '—')} / 调度服务运行 {server.get('service_active', '—')}",
        f"- 唤醒退避截止：{local_state.get('wakeup_backoff_until') or '—'}",
        f"- 论文章节：{snapshot['thesis_chapters_done']} / {snapshot['thesis_chapters_total']}",
        f"- 最近论文推进：{snapshot['thesis_last_sprint_utc'] or '—'}",
        f"- 论文构建结果：{snapshot['thesis_build_ok']}",
        f"- 公开说明：{snapshot['recent_public_note'] or '—'}",
        f"- 远端发布：{publish_state}",
    ]
    campaign = snapshot.get("campaign")
    if isinstance(campaign, dict):
        blocks = campaign.get("blocks", {})
        lines.extend(
            (
                f"- 当前阶段：{campaign.get('phase', '—')}",
                "- 科研块："
                + " · ".join(
                    f"{key} {value.get('accepted') if isinstance(value, dict) else '—'}/"
                    f"{value.get('total') if isinstance(value, dict) else '—'}"
                    for key, value in blocks.items()
                ),
                f"- 归档：本地镜像 {campaign.get('archive', {}).get('mirrored', 0)} · 云盘核验 {campaign.get('archive', {}).get('cloud_verified', 0)}",
                f"- 训练：{campaign.get('training', 'waiting')} · 工作台：{campaign.get('desk', 'waiting')}",
            )
        )
        for item in campaign.get("blocked", []):
            if isinstance(item, dict):
                lines.append(f"- BLOCKED：{item.get('task', 'unknown')} / {item.get('reason', 'dependency_blocked')}")
    if warning:
        lines.append(f"- 本地警告：{warning}")
    if publish_warning:
        lines.append(f"- 发布警告：{publish_warning}")
    lines.extend(("", "## 最近决策", "", decision, ""))
    atomic_write(cfg.state_dir / "DASHBOARD.md", "\n".join(lines))
    return snapshot
