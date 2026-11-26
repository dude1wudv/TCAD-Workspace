import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from types import UnionType
from typing import Any, Literal, get_args, get_origin, get_type_hints


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def load_json(text: str):
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def read_json(path: Path):
    return load_json(path.read_text(encoding="utf-8-sig"))


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8", newline="\n") as handle:
        staging = Path(handle.name)
        try:
            handle.write(text)
        except BaseException:
            handle.close()
            staging.unlink(missing_ok=True)
            raise
    try:
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def append_jsonl(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def _matches(value, annotation) -> bool:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any:
        if type(value) is dict:
            return _matches(value, dict[str, Any])
        if type(value) is list:
            return _matches(value, list[Any])
        return type(value) in (str, int, bool, type(None)) or type(value) is float and math.isfinite(value)
    if origin is UnionType:
        return any(_matches(value, option) for option in args)
    if origin is Literal:
        return any(type(value) is type(option) and value == option for option in args)
    if origin is list:
        return type(value) is list and all(_matches(item, args[0]) for item in value)
    if origin is dict:
        return type(value) is dict and all(_matches(key, args[0]) and _matches(item, args[1]) for key, item in value.items())
    if annotation is float:
        return type(value) in (int, float) and math.isfinite(value)
    return type(value) is annotation


class JsonRecord:
    def __post_init__(self):
        for name, annotation in get_type_hints(type(self)).items():
            if not _matches(getattr(self, name), annotation):
                raise ValueError(f"{type(self).__name__}.{name}: invalid value type")

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or value.keys() - {item.name for item in fields(cls)}:
            raise ValueError(f"{cls.__name__}: unknown fields or invalid object")
        try:
            return cls(**value)
        except TypeError as error:
            raise ValueError(f"{cls.__name__}: {error}") from error

    def to_dict(self):
        self.__post_init__()
        return asdict(self)


Category = Literal["sim_ops", "sim_repair", "data_extract", "predictor", "thesis_assets", "latex_build", "web_status"]
DecisionType = Literal["strategy", "criterion_amendment", "escalation", "thesis_plan"]


def check_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value) or re.fullmatch(
        r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])", value, re.I
    ):
        raise ValueError("invalid record ID")
    return value


@dataclass(kw_only=True)
class WorkOrder(JsonRecord):
    order_id: str
    category: Category
    title: str
    objective: str
    allowed_paths: list[str]
    forbidden_actions: list[str]
    acceptance_checks: list[str]
    timeout_seconds: int = 1500
    max_rejections: int = 3
    priority: int
    created_by_turn: str
    created_at: str

    def __post_init__(self):
        super().__post_init__()
        check_id(self.order_id)
        parse_time(self.created_at)
        if not all(text.strip() for text in (self.title, self.objective, self.created_by_turn)):
            raise ValueError("title, objective and created_by_turn must be nonempty")
        if not 1 <= self.timeout_seconds <= 1500 or not 1 <= self.priority <= 5 or self.max_rejections < 1:
            raise ValueError("invalid timeout_seconds, max_rejections or priority")
        for pattern in self.allowed_paths:
            path = pattern.replace("\\", "/").rstrip("/")
            if not path or path.startswith("/") or ":" in path or any(part in ("", ".", "..") for part in path.split("/")):
                raise ValueError("allowed_paths must contain repository-relative paths or glob patterns")
        if any(not item.strip() for item in self.forbidden_actions + self.acceptance_checks):
            raise ValueError("empty forbidden action or acceptance check")


@dataclass(kw_only=True)
class DeliveryReceipt(JsonRecord):
    order_id: str
    codex_session_id: str | None
    attempt: int
    status: Literal["passed", "failed", "timeout", "stalled"]
    exit_code: int | None
    duration_seconds: float
    git_changed_files: list[str]
    git_diff_stat: str
    verification_results: list[dict[str, Any]]
    artifacts_produced: list[str]
    codex_final_summary: str
    precheck_passed: bool
    precheck_errors: list[str]
    generated_at: str

    def __post_init__(self):
        super().__post_init__()
        check_id(self.order_id)
        parse_time(self.generated_at)
        if self.attempt < 1 or self.duration_seconds < 0:
            raise ValueError("invalid receipt attempt or duration")
        if self.precheck_passed != (self.status == "passed") or (self.precheck_passed and self.precheck_errors):
            raise ValueError("inconsistent precheck result")


@dataclass(kw_only=True)
class DirectorState(JsonRecord):
    daily_date: str = ""
    daily_wakeups_used: int = 0
    daily_codex_used: int = 0
    daily_executed: list[str] = field(default_factory=list)
    active_order: dict[str, Any] | None = None
    active_turn: dict[str, Any] | None = None
    pending_events: list[dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""
    server_offline: bool = False
    server_service_blocked: bool = False
    last_periodic_at: str = ""
    last_stall_at: str = ""
    wakeup_failures: int = 0
    wakeup_backoff_until: str = ""
    next_wake_at: str = ""
    last_decision: str = ""
    recent_public_note: str = ""
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self):
        super().__post_init__()
        if min(self.daily_wakeups_used, self.daily_codex_used, self.wakeup_failures) < 0:
            raise ValueError("negative director counter")
        for value in (self.updated_at, self.last_periodic_at, self.last_stall_at, self.wakeup_backoff_until, self.next_wake_at):
            if value:
                parse_time(value)
        if self.daily_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.daily_date):
            raise ValueError("invalid director calendar date")


@dataclass(kw_only=True)
class DecisionEntry(JsonRecord):
    decision_type: DecisionType
    title: str
    body: str
    cases: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self):
        super().__post_init__()
        parse_time(self.created_at)
        if not self.title.strip() or not self.body.strip():
            raise ValueError("decision title and body are required")


@dataclass(kw_only=True)
class QueueItem(JsonRecord):
    order: dict[str, Any]
    enqueued_at: str = field(default_factory=utc_now)

    def __post_init__(self):
        super().__post_init__()
        WorkOrder.from_dict(self.order)
        parse_time(self.enqueued_at)
