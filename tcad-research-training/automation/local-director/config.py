import re
import shlex
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from schemas import DirectorState, parse_time, read_json


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[2]


@dataclass(frozen=True)
class NotifyConfig:
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    repo_root: Path = REPO_ROOT
    branch_name: str = "agent/p0-pure-codex-autonomy"
    state_dir: Path = REPO_ROOT / "local_runtime" / "auto-director"
    server_ssh_target: str = ""
    remote_policy_path: str = "/etc/tcad-autonomy/policy.json"
    remote_controller_cmd: tuple[str, ...] = ()
    remote_observation_path: str = "/var/lib/tcad-autonomy/observation.json"
    remote_director_status_path: str = "/var/lib/xjtu-shop-status/auto-director.json"
    server_lead_units: tuple[str, ...] = ()
    public_status_url: str = "https://status.xjtu.shop/live.json"
    heartbeat_interval_seconds: int = 180
    periodic_review_seconds: int = 43200
    campaign_execution_enabled: bool = False
    campaign_expires_at: str = ""
    publish_campaign_status: bool = False
    codex_model: str = "auto/gpt-6.2-sol"
    codex_effort: str = "high"
    codex_sandbox: str = "workspace-write"
    codex_supervisor_model: str = "auto/gpt-6.2-sol"
    codex_supervisor_effort: str = "high"
    codex_supervisor_sandbox: str = "read-only"
    codex_daily_cap: int = 30
    codex_reserved_urgent: int = 6
    codex_default_timeout_seconds: int = 1500
    codex_supervisor_timeout_seconds: int = 600
    codex_stall_seconds: int = 720
    director_turn_timeout_seconds: int = 600
    codex_no_progress_cooldown_seconds: int = 7200
    codex_max_task_failures: int = 3
    timezone: str = "Asia/Shanghai"
    notify: NotifyConfig = NotifyConfig()
    config_path: Path | None = field(default=None, init=False, repr=False, compare=False)

    def local_time(self, now: datetime) -> datetime:
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            if self.timezone != "Asia/Shanghai":
                raise
            zone = timezone(timedelta(hours=8), "Asia/Shanghai")
        return now.astimezone(zone)

    def campaign_expired(self, now: datetime) -> bool:
        return bool(self.campaign_expires_at and now >= parse_time(self.campaign_expires_at))

    def reset_day(self, state: DirectorState, local_date: str | date) -> None:
        day = date.fromisoformat(local_date) if isinstance(local_date, str) else local_date
        if state.daily_date != day.isoformat():
            state.daily_date = day.isoformat()
            state.daily_wakeups_used = 0
            state.daily_codex_used = 0
            state.daily_executed.clear()
            state.pending_events = [event for event in state.pending_events if event.get("bucket") != "daily"]

    def can_consume_codex(self, state: DirectorState, priority_bucket: str, local_date: str | date) -> bool:
        self.reset_day(state, local_date)
        if self.codex_daily_cap < 1:
            return False
        caps = {
            "routine": self.codex_daily_cap - self.codex_reserved_urgent,
            "urgent": self.codex_daily_cap,
        }
        if priority_bucket not in caps:
            raise ValueError("unknown Codex priority bucket")
        return state.daily_codex_used < max(0, caps[priority_bucket])


def can_consume_codex(state: DirectorState, priority_bucket: str, local_date: str | date, cfg: Config | None = None) -> bool:
    return (cfg or Config()).can_consume_codex(state, priority_bucket, local_date)


def _object(raw, cls):
    if type(raw) is not dict or raw.keys() - {item.name for item in fields(cls) if item.init}:
        raise ValueError(f"invalid {cls.__name__} keys")
    return raw.copy()


def _path(value, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a nonempty string")
    return (base / Path(value).expanduser()).resolve()


def load_config(path: str | Path | None = None) -> Config:
    location = Path(path).resolve() if path is not None else BASE_DIR / "config.json"
    if path is None and not location.exists():
        return Config()
    raw = read_json(location)
    if type(raw) is not dict:
        raise ValueError("config must be an object")
    for legacy_key in (
        "gemini_model",
        "gemini_daily_cap",
        "gemini_reserved_urgent",
        "gemini_reserved_daily",
        "use_goal_mode",
        "daily_thesis_hour",
        "daily_digest_hour",
    ):
        raw.pop(legacy_key, None)
    values = _object(raw, Config)
    repo = _path(values.pop("repo_root", str(REPO_ROOT)), location.parent)
    runtime = _path(values.pop("state_dir", "local_runtime/auto-director"), repo)
    notify_raw = values.pop("notify", {})
    if type(notify_raw) is not dict:
        raise ValueError("invalid notify")
    for legacy_key in ("recipient", "smtp_env_file", "fallback_gmail_draft"):
        notify_raw.pop(legacy_key, None)
    notify_raw = _object(notify_raw, NotifyConfig)
    for key, value in notify_raw.items():
        if type(value) is not type(getattr(NotifyConfig(), key)):
            raise ValueError(f"invalid notify.{key}")
    for key, value in values.items():
        default = getattr(Config(), key)
        if type(default) is tuple:
            if key == "remote_controller_cmd" and type(value) is str:
                value = shlex.split(value)
            if type(value) is not list or any(type(part) is not str or not part.strip() or "\x00" in part for part in value):
                raise ValueError(f"{key} must be an array of nonempty strings")
            values[key] = tuple(value)
        elif key == "codex_daily_cap" and value is None:
            values[key] = Config.codex_daily_cap
        elif type(value) is not type(default) or (isinstance(value, str) and any(char in value for char in "\0\n\r")):
            raise ValueError(f"invalid {key}")
    cfg = Config(repo_root=repo, state_dir=runtime, notify=NotifyConfig(**notify_raw), **values)
    object.__setattr__(cfg, "config_path", location)
    if any(getattr(cfg, item.name) < 1 for item in fields(cfg) if item.name.endswith("_seconds")):
        raise ValueError("timeout and interval values must be positive")
    if not 1 <= cfg.codex_default_timeout_seconds <= 1500:
        raise ValueError("codex_default_timeout_seconds exceeds 25 minutes")
    if not 1 <= cfg.codex_supervisor_timeout_seconds <= 600:
        raise ValueError("codex_supervisor_timeout_seconds exceeds ten-minute limit")
    if not 1 <= cfg.codex_daily_cap <= 30 or not 0 <= cfg.codex_reserved_urgent <= cfg.codex_daily_cap:
        raise ValueError("invalid Codex daily cap or reservation")
    if cfg.codex_max_task_failures != 3:
        raise ValueError("campaign task failure threshold must be three")
    if cfg.campaign_execution_enabled and cfg.codex_sandbox != "workspace-write":
        raise ValueError("unattended workers require workspace-write sandbox")
    if cfg.campaign_expires_at:
        parse_time(cfg.campaign_expires_at)
    if any(not getattr(cfg, key).startswith("/") for key in ("remote_policy_path", "remote_observation_path", "remote_director_status_path")):
        raise ValueError("remote paths must be absolute")
    url = urlsplit(cfg.public_status_url)
    if cfg.public_status_url and (url.scheme != "https" or not url.hostname or url.username or url.password):
        raise ValueError("public_status_url must be a credential-free HTTPS URL")
    if not cfg.branch_name or cfg.branch_name.startswith("-") or cfg.branch_name in {"main", "master", "HEAD"}:
        raise ValueError("branch_name must name a work branch")
    if not cfg.codex_model or not cfg.codex_supervisor_model or cfg.codex_effort not in {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
        raise ValueError("invalid model or reasoning effort")
    if cfg.codex_supervisor_effort not in {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
        raise ValueError("invalid supervisor reasoning effort")
    if cfg.codex_sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ValueError("invalid Codex sandbox")
    if cfg.codex_supervisor_sandbox != "read-only":
        raise ValueError("Codex supervisor must use read-only sandbox")
    try:
        cfg.local_time(datetime.now(timezone.utc))
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone is unavailable on this system") from error
    return cfg


def ssh_command(cfg: Config, script: str) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?", cfg.server_ssh_target) or cfg.server_ssh_target.startswith("-"):
        raise ValueError("server_ssh_target must be a configured SSH alias")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", cfg.server_ssh_target, script]
