from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from schemas import read_json, utc_now, write_json


CAMPAIGN_STATES = (
    "P0_BOOTSTRAP",
    "P1A_SIM_DEV",
    "P2A_DEV_TRAIN_AL1",
    "P1B_SIM_AL1",
    "P2B_RETRAIN_AL2",
    "P1C_SIM_AL2_HOLDOUT",
    "P2C_FINAL_TRAIN_FREEZE",
    "P2D_HOLDOUT_BLIND_EVAL",
    "P3_DESK_PROD_DEPLOY",
    "P4_HANDOFF_AUDIT",
)

BLOCK_TOTALS = {
    "Z": 26,
    "T": 68,
    "S": 150,
    "R": 12,
    "AL": 82,
    "HR": 28,
    "HP": 30,
}

BLOCK_KEYS = tuple(BLOCK_TOTALS)
BLOCKED_REASONS = (
    "candidate_failed",
    "checks_failed",
    "supervisor_failed",
    "receipt_invalid",
    "dependency_blocked",
    "disk_floor",
    "holdout_sealed",
    "production_not_verified",
)

TASK_STATUSES = ("pending", "running", "accepted", "blocked", "cooldown")


def _now(value: str | None = None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("campaign timestamps require a timezone")
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _block_progress(accepted: int | None, total: int) -> dict[str, int | None]:
    if type(accepted) is not int or accepted < 0:
        accepted = None
    return {"accepted": accepted, "total": total}


def _default_state(now: str | None = None) -> dict[str, Any]:
    stamp = now or utc_now()
    return {
        "schema_version": 1,
        "campaign_id": "dram-se-r06",
        "phase": "P0_BOOTSTRAP",
        "phase_entered_at": stamp,
        "blocks": {key: _block_progress(None, total) for key, total in BLOCK_TOTALS.items()},
        "gates": {"G1": False, "G2": False, "G3": False, "G4": False},
        "milestones": {
            "bootstrap_ready": False,
            "al1_issued": False,
            "al1_complete": False,
            "al2_issued": False,
            "al2_complete": False,
            "holdout_archives_verified": False,
            "freeze_manifest_verified": False,
            "blind_eval_complete": False,
            "desk_verified": False,
            "handoff_audit_complete": False,
        },
        "holdout": {"sealed": True, "freeze_manifest": None, "blind_eval_count": 0},
        "training": "waiting",
        "desk": "waiting",
        "archive": {"mirrored": 0, "cloud_verified": 0},
        "blocked": [],
        "wakeups_without_progress": 0,
        "cooldown_until": None,
        "last_progress_at": stamp,
        "last_deep_check_at": stamp,
        "last_decision": None,
        "updated_at": stamp,
    }


def default_backlog() -> dict[str, Any]:
    tasks = [
        {
            "task": "campaign-fsm-supervisor",
            "title": "实现纯 Codex 督导和阶段门控",
            "category": "web_status",
            "phase": ["P0_BOOTSTRAP"],
            "prerequisites": [],
            "allowed_paths": ["tcad-research-training/automation/local-director"],
            "acceptance_checks": ["python -m unittest tcad-research-training/automation/local-director/tests/test_campaign_fsm.py"],
        },
        {
            "task": "local-archive-sync",
            "title": "实现本地冷归档同步和双端收据校验",
            "category": "data_extract",
            "phase": ["P0_BOOTSTRAP"],
            "prerequisites": [],
            "allowed_paths": ["tcad-research-training/automation/local-director/local_archive_sync.py"],
            "acceptance_checks": ["python -m unittest tcad-research-training/automation/local-director/tests/test_local_archive_sync.py"],
        },
        {
            "task": "status-campaign-projection",
            "title": "发布脱敏的 campaign 状态投影",
            "category": "web_status",
            "phase": ["P0_BOOTSTRAP"],
            "prerequisites": ["campaign-fsm-supervisor"],
            "allowed_paths": ["xjtu-shop-site/status-checker"],
            "acceptance_checks": ["npm run test:status"],
        },
        {
            "task": "windows-watchdog-tasks",
            "title": "准备双任务计划注册入口",
            "category": "web_status",
            "phase": ["P0_BOOTSTRAP"],
            "prerequisites": ["campaign-fsm-supervisor"],
            "allowed_paths": ["tcad-research-training/automation/local-director/register_campaign_tasks.ps1"],
            "acceptance_checks": [
                "pwsh -NoProfile -File tcad-research-training/automation/local-director/register_campaign_tasks.ps1 -Preflight"
            ],
        },
        {
            "task": "export-r06-dev",
            "title": "导出无留出泄漏的开发快照",
            "category": "data_extract",
            "phase": ["P2A_DEV_TRAIN_AL1"],
            "prerequisites": ["campaign-fsm-supervisor", "local-archive-sync"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_data_splits.py"],
        },
        {
            "task": "al-batch-1",
            "title": "生成第一批主动学习候选",
            "category": "predictor",
            "phase": ["P2A_DEV_TRAIN_AL1"],
            "prerequisites": ["export-r06-dev"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_aggregation.py"],
        },
        {
            "task": "tree-baselines",
            "title": "运行来源分组树模型基线",
            "category": "predictor",
            "phase": ["P2A_DEV_TRAIN_AL1", "P2C_FINAL_TRAIN_FREEZE"],
            "prerequisites": ["export-r06-dev"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_baselines.py"],
        },
        {
            "task": "factor-analysis",
            "title": "完成分组置换和受控参数切片",
            "category": "predictor",
            "phase": ["P2C_FINAL_TRAIN_FREEZE"],
            "prerequisites": ["export-r06-dev"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_pipeline.py"],
        },
        {
            "task": "al-batch-2",
            "title": "生成第二批主动学习候选",
            "category": "predictor",
            "phase": ["P2B_RETRAIN_AL2"],
            "prerequisites": ["al-batch-1"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_aggregation.py"],
        },
        {
            "task": "final-train-freeze",
            "title": "训练终版开发模型并写不可变冻结清单",
            "category": "predictor",
            "phase": ["P2C_FINAL_TRAIN_FREEZE"],
            "prerequisites": ["al-batch-2", "tree-baselines", "factor-analysis"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests"],
        },
        {
            "task": "holdout-blind-eval",
            "title": "按冻结清单执行一次留出盲测",
            "category": "predictor",
            "phase": ["P2D_HOLDOUT_BLIND_EVAL"],
            "prerequisites": ["final-train-freeze"],
            "allowed_paths": ["tcad-research-training/predictor"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/predictor/tests -p test_calibration.py"],
        },
        {
            "task": "desk-readonly-api",
            "title": "构建只读科研工作台 API",
            "category": "web_status",
            "phase": ["P3_DESK_PROD_DEPLOY"],
            "prerequisites": ["final-train-freeze"],
            "allowed_paths": ["tcad-research-training/research-desk"],
            "acceptance_checks": ["python -m compileall tcad-research-training/research-desk"],
        },
        {
            "task": "desk-tool-calling-mock",
            "title": "完成外部 LLM 工具调用 Mock 适配层",
            "category": "web_status",
            "phase": ["P3_DESK_PROD_DEPLOY"],
            "prerequisites": ["desk-readonly-api"],
            "allowed_paths": ["tcad-research-training/research-desk"],
            "acceptance_checks": ["python -m unittest discover -s tcad-research-training/research-desk -p test_*.py"],
        },
        {
            "task": "desk-production-acceptance",
            "title": "完成科研工作台生产验收",
            "category": "web_status",
            "phase": ["P3_DESK_PROD_DEPLOY"],
            "prerequisites": ["desk-readonly-api", "desk-tool-calling-mock", "holdout-blind-eval"],
            "allowed_paths": ["tcad-research-training/research-desk", "xjtu-shop-site"],
            "acceptance_checks": ["python -m compileall tcad-research-training/research-desk"],
        },
        {
            "task": "handoff-audit",
            "title": "生成 30 天托管结项审计材料",
            "category": "thesis_assets",
            "phase": ["P4_HANDOFF_AUDIT"],
            "prerequisites": ["desk-production-acceptance"],
            "allowed_paths": ["tcad-research-training/plans/dram-se-ddr5-lpddr5"],
            "acceptance_checks": ["python -m compileall tcad-research-training/automation"],
        },
    ]
    return {
        "schema_version": 1,
        "campaign_id": "dram-se-r06",
        "tasks": [
            {
                **task,
                "status": "pending",
                "attempts": 0,
                "failures": 0,
                "last_error": None,
                "updated_at": utc_now(),
            }
            for task in tasks
        ],
        "updated_at": utc_now(),
    }


def _validate_state(state: dict[str, Any]) -> dict[str, Any]:
    if type(state) is not dict or state.get("schema_version") != 1:
        raise ValueError("invalid campaign state")
    if state.get("campaign_id") != "dram-se-r06" or state.get("phase") not in CAMPAIGN_STATES:
        raise ValueError("invalid campaign identity or phase")
    blocks = state.get("blocks")
    if type(blocks) is not dict or set(blocks) != set(BLOCK_KEYS):
        raise ValueError("invalid campaign blocks")
    for key, total in BLOCK_TOTALS.items():
        block = blocks[key]
        if type(block) is not dict or block.get("total") != total:
            raise ValueError("invalid campaign block total")
        accepted = block.get("accepted")
        if accepted is not None and (type(accepted) is not int or not 0 <= accepted <= total):
            raise ValueError("invalid campaign block count")
    blocked = state.get("blocked")
    if type(blocked) is not list:
        raise ValueError("invalid campaign blocked list")
    for item in blocked:
        _validate_blocked(item)
    return state


def _validate_blocked(item: dict[str, Any]) -> None:
    if type(item) is not dict or set(item) - {"task", "reason", "detail", "failures", "updated_at"}:
        raise ValueError("invalid blocked item")
    task = item.get("task")
    if type(task) is not str or not task or len(task) > 40:
        raise ValueError("invalid blocked task")
    if item.get("reason") not in BLOCKED_REASONS:
        raise ValueError("invalid blocked reason")
    if type(item.get("detail")) is not str or len(item["detail"]) > 300:
        raise ValueError("invalid blocked detail")
    if type(item.get("failures")) is not int or item["failures"] < 3:
        raise ValueError("invalid blocked failure count")


def _validate_backlog(backlog: dict[str, Any]) -> dict[str, Any]:
    if type(backlog) is not dict or backlog.get("schema_version") != 1 or backlog.get("campaign_id") != "dram-se-r06":
        raise ValueError("invalid campaign backlog")
    tasks = backlog.get("tasks")
    if type(tasks) is not list:
        raise ValueError("invalid campaign backlog tasks")
    seen = set()
    for task in tasks:
        if type(task) is not dict or type(task.get("task")) is not str or task["task"] in seen:
            raise ValueError("invalid or duplicate backlog task")
        seen.add(task["task"])
        if task.get("status") not in TASK_STATUSES:
            raise ValueError("invalid backlog task status")
        if type(task.get("prerequisites")) is not list or any(item not in seen and item not in {row.get("task") for row in tasks} for item in task["prerequisites"]):
            raise ValueError("invalid backlog prerequisites")
        if type(task.get("failures")) is not int or task["failures"] < 0:
            raise ValueError("invalid backlog failure count")
    return backlog


def campaign_paths(state_dir: Path) -> tuple[Path, Path]:
    return state_dir / "campaign_state.json", state_dir / "campaign_backlog.json"


def ensure_campaign_files(state_dir: Path, *, create: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    state_path, backlog_path = campaign_paths(state_dir)
    if state_path.exists():
        state = _validate_state(read_json(state_path))
    else:
        state = _default_state()
        if create:
            write_json(state_path, state)
    if backlog_path.exists():
        backlog = _validate_backlog(read_json(backlog_path))
    else:
        backlog = default_backlog()
        if create:
            write_json(backlog_path, backlog)
    return state, backlog


def load_campaign(state_dir: Path, *, create: bool = True) -> dict[str, Any]:
    path = campaign_paths(state_dir)[0]
    if not path.exists():
        return ensure_campaign_files(state_dir)[0] if create else _default_state()
    return _validate_state(read_json(path))


def save_campaign(state_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    _validate_state(state)
    write_json(campaign_paths(state_dir)[0], state)


def load_backlog(state_dir: Path) -> dict[str, Any]:
    path = campaign_paths(state_dir)[1]
    if not path.exists():
        return ensure_campaign_files(state_dir)[1]
    return _validate_backlog(read_json(path))


def save_backlog(state_dir: Path, backlog: dict[str, Any]) -> None:
    backlog["updated_at"] = utc_now()
    _validate_backlog(backlog)
    write_json(campaign_paths(state_dir)[1], backlog)


def public_campaign(state: dict[str, Any]) -> dict[str, Any]:
    state = _validate_state(state)
    blocks = {
        key: {
            "accepted": block["accepted"],
            "total": block["total"],
        }
        for key, block in state["blocks"].items()
    }
    blocked = [
        {
            "task": item["task"],
            "reason": item["reason"],
        }
        for item in state["blocked"]
    ]
    return {
        "phase": state["phase"],
        "codex": {
            "used": None,
            "cap": None,
            "reserved": None,
        },
        "blocks": blocks,
        "disks": {
            "server_free_bytes": None,
            "vm_allocated_bytes": None,
            "vm_free_bytes": None,
            "vm_growth_bytes": None,
        },
        "archive": {
            "mirrored": max(0, int(state["archive"].get("mirrored", 0))),
            "cloud_verified": max(0, int(state["archive"].get("cloud_verified", 0))),
        },
        "training": state["training"] if state["training"] in {"waiting", "running", "ready", "blocked"} else "waiting",
        "desk": state["desk"] if state["desk"] in {"waiting", "running", "ready", "blocked"} else "waiting",
        "blocked": blocked,
    }


def update_public_metrics(
    state: dict[str, Any],
    *,
    codex_used: int | None = None,
    codex_cap: int | None = None,
    codex_reserved: int | None = None,
    disks: dict[str, int | None] | None = None,
) -> None:
    public = state.setdefault("_public_metrics", {})
    for key, value in {
        "codex_used": codex_used,
        "codex_cap": codex_cap,
        "codex_reserved": codex_reserved,
    }.items():
        if type(value) is int and value >= 0:
            public[key] = value
    if disks is not None:
        public_disks = {}
        for key in ("server_free_bytes", "vm_allocated_bytes", "vm_free_bytes", "vm_growth_bytes"):
            value = disks.get(key)
            public_disks[key] = value if type(value) is int and value >= 0 else None
        public["disks"] = public_disks


def public_campaign_with_metrics(state: dict[str, Any]) -> dict[str, Any]:
    result = public_campaign(state)
    metrics = state.get("_public_metrics") if type(state.get("_public_metrics")) is dict else {}
    codex = result["codex"]
    for key in ("used", "cap", "reserved"):
        value = metrics.get("codex_" + key)
        codex[key] = value if type(value) is int and value >= 0 else None
    disks = metrics.get("disks") if type(metrics.get("disks")) is dict else {}
    for key in result["disks"]:
        value = disks.get(key)
        result["disks"][key] = value if type(value) is int and value >= 0 else None
    return result


def apply_progress(state: dict[str, Any], progress: dict[str, Any] | None) -> None:
    if not isinstance(progress, dict):
        return
    blocks = progress.get("blocks")
    if isinstance(blocks, dict):
        for key, value in blocks.items():
            if key in BLOCK_TOTALS and type(value) is int and value >= 0:
                state["blocks"][key]["accepted"] = min(value, BLOCK_TOTALS[key])
    milestones = progress.get("milestones")
    if isinstance(milestones, dict):
        for key, value in milestones.items():
            if key in state["milestones"] and type(value) is bool:
                state["milestones"][key] = value
    for key in ("training", "desk"):
        value = progress.get(key)
        if value in {"waiting", "running", "ready", "blocked"}:
            state[key] = value
    archive = progress.get("archive")
    if isinstance(archive, dict):
        for key in ("mirrored", "cloud_verified"):
            value = archive.get(key)
            if type(value) is int and value >= 0:
                state["archive"][key] = value
    freeze_manifest = progress.get("freeze_manifest")
    if freeze_manifest is not None:
        if type(freeze_manifest) is not dict or set(freeze_manifest) - {"sha256", "created_at", "model_id"}:
            raise ValueError("invalid freeze manifest reference")
        if not freeze_manifest.get("sha256") or not freeze_manifest.get("model_id"):
            raise ValueError("incomplete freeze manifest reference")
        state["holdout"]["freeze_manifest"] = freeze_manifest
        state["milestones"]["freeze_manifest_verified"] = True
        state["holdout"]["sealed"] = False
    blind_eval_count = progress.get("blind_eval_count")
    if type(blind_eval_count) is int and blind_eval_count >= 0:
        state["holdout"]["blind_eval_count"] = blind_eval_count
    recompute_gates(state)


def recompute_gates(state: dict[str, Any]) -> dict[str, bool]:
    blocks = state["blocks"]
    development_ready = all(
        type(blocks[key]["accepted"]) is int and blocks[key]["accepted"] >= BLOCK_TOTALS[key]
        for key in ("Z", "T", "S", "R")
    )
    milestones = state["milestones"]
    state["gates"]["G1"] = development_ready
    state["gates"]["G2"] = (development_ready and milestones.get("holdout_archives_verified", False)
                            and milestones["al2_complete"] and blocks["AL"]["accepted"] == BLOCK_TOTALS["AL"])
    state["gates"]["G3"] = holdout_read_allowed(state) and state["training"] == "ready"
    state["gates"]["G4"] = (state["gates"]["G3"] and milestones["blind_eval_complete"] and state["holdout"]["blind_eval_count"] == 1
                            and milestones["desk_verified"])
    return state["gates"]


def next_phase(state: dict[str, Any]) -> str | None:
    phase = state["phase"]
    milestones = state["milestones"]
    gates = recompute_gates(state)
    allowed = {
        "P0_BOOTSTRAP": milestones["bootstrap_ready"],
        "P1A_SIM_DEV": gates["G1"],
        "P2A_DEV_TRAIN_AL1": milestones["al1_issued"],
        "P1B_SIM_AL1": milestones["al1_complete"],
        "P2B_RETRAIN_AL2": milestones["al2_issued"],
        "P1C_SIM_AL2_HOLDOUT": gates["G2"],
        "P2C_FINAL_TRAIN_FREEZE": gates["G3"],
        "P2D_HOLDOUT_BLIND_EVAL": (gates["G3"] and milestones["blind_eval_complete"]
                                  and state["holdout"]["blind_eval_count"] == 1),
        "P3_DESK_PROD_DEPLOY": gates["G4"],
        "P4_HANDOFF_AUDIT": milestones["handoff_audit_complete"],
    }
    if not allowed.get(phase, False):
        return None
    index = CAMPAIGN_STATES.index(phase)
    return CAMPAIGN_STATES[index + 1] if index + 1 < len(CAMPAIGN_STATES) else None


def advance_phase(state: dict[str, Any], *, now: str | None = None) -> str | None:
    target = next_phase(state)
    if target is None:
        return None
    state["phase"] = target
    state["phase_entered_at"] = now or utc_now()
    state["last_progress_at"] = state["phase_entered_at"]
    state["wakeups_without_progress"] = 0
    return target


def ready_tasks(backlog: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    accepted = {task["task"] for task in backlog["tasks"] if task["status"] == "accepted"}
    ready = []
    for task in backlog["tasks"]:
        if task["status"] not in {"pending", "cooldown"}:
            continue
        if phase not in task["phase"]:
            continue
        if all(prerequisite in accepted for prerequisite in task["prerequisites"]):
            ready.append(task)
    return sorted(ready, key=lambda task: task["task"])


def backlog_summary(backlog: dict[str, Any], phase: str) -> dict[str, int]:
    tasks = backlog["tasks"]
    return {
        "total": len(tasks),
        "pending": sum(task["status"] == "pending" for task in tasks),
        "running": sum(task["status"] == "running" for task in tasks),
        "accepted": sum(task["status"] == "accepted" for task in tasks),
        "blocked": sum(task["status"] == "blocked" for task in tasks),
        "ready": len(ready_tasks(backlog, phase)),
    }


def mark_task(backlog: dict[str, Any], task_id: str, status: str, *, error: str | None = None) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise ValueError("invalid task status")
    for task in backlog["tasks"]:
        if task["task"] != task_id:
            continue
        task["status"] = status
        task["attempts"] += 1 if status == "running" else 0
        if error is not None:
            task["failures"] += 1
            task["last_error"] = error[:300]
        task["updated_at"] = utc_now()
        return task
    raise ValueError("unknown backlog task")


def register_blocked(state: dict[str, Any], task_id: str, reason: str, detail: str, failures: int) -> None:
    if reason not in BLOCKED_REASONS or failures < 3:
        raise ValueError("invalid blocked task record")
    item = {
        "task": task_id[:40],
        "reason": reason,
        "detail": detail[:300],
        "failures": failures,
        "updated_at": utc_now(),
    }
    state["blocked"] = [entry for entry in state["blocked"] if entry["task"] != item["task"]]
    state["blocked"].append(item)


def holdout_read_allowed(state: dict[str, Any]) -> bool:
    return bool(state["milestones"]["freeze_manifest_verified"] and state["holdout"]["freeze_manifest"])


def assert_holdout_read_allowed(state: dict[str, Any]) -> None:
    if not holdout_read_allowed(state):
        raise PermissionError("holdout data is sealed until freeze_manifest.json is verified")


def task_work_order(task: dict[str, Any], *, created_by_turn: str, timeout_seconds: int = 1500,
                    now: datetime | None = None) -> dict[str, Any]:
    order_id = task["task"]
    if task.get("attempts", 0):
        order_id = f"{order_id}-attempt-{task['attempts'] + 1}"
    return {
        "order_id": order_id,
        "category": task["category"],
        "title": task["title"],
        "objective": task["title"],
        "allowed_paths": task["allowed_paths"],
        "forbidden_actions": [
            "do not read HR or HP data before freeze_manifest.json is verified",
            "do not run SSH, solver, deployment, cleanup, or external upload commands",
        ],
        "acceptance_checks": task["acceptance_checks"],
        "timeout_seconds": timeout_seconds,
        "max_rejections": 3,
        "priority": 4,
        "created_by_turn": created_by_turn,
        "created_at": _stamp(now),
    }


def set_cooldown(state: dict[str, Any], seconds: int, *, now: datetime | None = None) -> None:
    if seconds < 1:
        raise ValueError("cooldown must be positive")
    state["cooldown_until"] = _stamp((now or _now()) + timedelta(seconds=seconds))


def cooldown_active(state: dict[str, Any], now: datetime | None = None) -> bool:
    value = state.get("cooldown_until")
    if not value:
        return False
    return _now(value) > (now or datetime.now(timezone.utc))
