"""Shared sensitive-text checks and director notification delivery."""

from __future__ import annotations

import re
import smtplib
import ssl
import unicodedata
from datetime import datetime, timedelta, timezone
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from schemas import atomic_write, utc_now


_SENSITIVE = {
    "credential": re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"
        r"|\b(?:Bearer|Basic)[ \t]+[A-Za-z0-9._~+/=-]{8,}"
        r"|(?:\b(?:[\w-]*[_-])?(?:api[_ -]?key|access[_ -]?key|password|passwd|secret|token|authorization)"
        r"|密码|密钥|令牌|凭据)[\"']?[ \t]*[:=：][ \t]*(?:(?:Bearer|Basic)[ \t]+)?"
        r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;<>，。]+)"
        r"|\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})"
        r"|\bAKIA[A-Z0-9]{16}\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
        r"|\b[a-z][a-z0-9+.-]*://[^\s/@]+(?::[^\s/@]*)?@",
        re.I,
    ),
    "private_path": re.compile(
        r"(?:(?<![\w])(?:[a-z]:\\|[a-z]:/(?!/))|\\\\[^\s\\]+\\|/(?:home|srv|var|root|etc|mnt|opt|tmp|run|Users)/)"
        r"[^\r\n\"'`<>|,;，。]*"
        r"|(?<![\w.])(?:local_runtime|\.ssh)[/\\][^\s\"'`<>|,;，。]+",
        re.I,
    ),
    "network_address": re.compile(
        r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"
        r"|(?<![\w:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
        r"|(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{0,4}::(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{0,4})"
        r"(?:%[\w.-]+)?(?![\w:])"
        r"|\b(?:tcad[-_](?:sim(?:[-_]tail)?|tail|cloud)|hk[-_](?:tail|live)|public-ip-[a-z0-9]+)\b"
        r"|\b[a-z0-9.-]+\.(?:internal|local|ts\.net)\b",
        re.I,
    ),
    "email_address": re.compile(r"[\w.+%'-]+@[\w-]+(?:\.[\w-]+)+"),
    "license_detail": re.compile(
        r"(?<![a-z0-9])(?:lm_license_file|snpslmd_license_file)(?![a-z0-9])"
        r"(?:[\"']?[ \t]*[:=][ \t]*[^\r\n,;]*)?|\b\d{2,5}@[a-z0-9][a-z0-9.-]*",
        re.I,
    ),
    "ssh_detail": re.compile(r"(?<![a-z0-9])ssh(?![a-z0-9])[^\r\n]*", re.I),
    "internal_identifier": re.compile(
        r"(?<![a-z0-9])(?:run_id|pid|session_id|thread_id|turn_id|order_id)(?![a-z0-9])"
        r"(?:[\"']?[ \t]*[:=][ \t]*[^\s,;，。]+)?"
        r"|\bauto-r\d+[-\w]*-[0-9a-f]{12,}\b",
        re.I,
    ),
}


def _without_controls(text: str) -> str:
    return "".join(
        char for char in text.replace("\r\n", "\n").replace("\r", "\n")
        if char in "\t\n" or unicodedata.category(char) not in {"Cc", "Cf"}
    )


def find_sensitive(text: str) -> list[str]:
    """Return unique reason names, including separate identifier and SSH labels."""
    visible = _without_controls(text)
    normalized = unicodedata.normalize("NFKC", visible)
    return [reason for reason, pattern in _SENSITIVE.items()
            if pattern.search(visible) or pattern.search(normalized)]


def redact_text(text: str) -> str:
    """Redact overlapping matches while preserving unaffected text and typography."""
    visible = _without_controls(text)
    spans = sorted(match.span() for pattern in _SENSITIVE.values() for match in pattern.finditer(visible))
    chunks = []
    cursor = 0
    for start, stop in spans:
        if start >= cursor:
            chunks.extend((visible[cursor:start], "[REDACTED]"))
        cursor = max(cursor, stop)
    chunks.append(visible[cursor:])
    result = "".join(chunks)
    return "[REDACTED]" if find_sensitive(result) else result


def _smtp_options(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").partition("=")
        if not separator:
            raise ValueError("invalid SMTP environment file")
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _send_smtp(message: EmailMessage, options: dict[str, str]) -> None:
    host = options.get("SMTP_HOST", "smtp.gmail.com")
    user = options.get("SMTP_USER")
    password = options.get("SMTP_PASSWORD")
    sender = options.get("SMTP_FROM") or user
    if not host or not sender or not user or not password:
        raise ValueError("incomplete SMTP configuration")
    port = int(options.get("SMTP_PORT", "587"))
    context = ssl.create_default_context()
    message["From"] = Address(addr_spec=sender)
    client = smtplib.SMTP(host, port, timeout=15)
    try:
        client.starttls(context=context)
        client.login(user, password)
        client.send_message(message)
    finally:
        client.close()


def notify(cfg, level: str, subject: str, body: str) -> dict:
    """Archive digests and use TLS SMTP or a local Markdown draft."""
    level = level.lower()
    result = {"status": "disabled", "mode": "disabled"}
    reasons = find_sensitive("\n".join((level, subject, body)))
    runtime_dir = cfg.state_dir
    if level in {"digest", "daily_digest"}:
        shanghai = timezone(timedelta(hours=8), "Asia/Shanghai")
        day = datetime.fromisoformat(utc_now()).astimezone(shanghai).strftime("%Y%m%d")
        path = runtime_dir / "reports" / f"daily-{day}.md"
        title = " ".join(redact_text(subject).split())
        atomic_write(path, f"# {title}\n\n{redact_text(body)}\n")
        result["archive_path"] = str(path)
    if reasons:
        return {**result, "status": "blocked", "mode": "blocked", "reasons": reasons}

    settings = cfg.notify
    if not settings.enabled:
        return result
    title = " ".join(_without_controls(subject).split())
    content = _without_controls(body)
    try:
        recipient = Address(addr_spec=settings.recipient)
        if not recipient.username or not recipient.domain:
            raise ValueError("incomplete recipient")
    except (HeaderParseError, ValueError, TypeError, IndexError):
        recipient = None

    warning = "smtp_unconfigured" if recipient else "recipient_unconfigured"
    if recipient:
        try:
            message = EmailMessage()
            message["To"] = recipient
            message["Subject"] = title
            message.set_content(content)
            options = _smtp_options(settings.smtp_env_file or runtime_dir / "secrets.env")
            _send_smtp(message, options)
        except (HeaderParseError, OSError, ValueError, KeyError, IndexError) as error:
            warning = "smtp_" + type(error).__name__
        else:
            return {**result, "status": "sent", "mode": "smtp"}

    if settings.fallback_gmail_draft:
        path = runtime_dir / "pending_drafts" / f"{uuid4().hex}.md"
        draft = f"To: {recipient or ''}\nSubject: {title}\n\n{content}\n"
        try:
            atomic_write(path, draft)
        except OSError:
            return {**result, "status": "failed", "mode": "failed", "warning": "draft_write_failed",
                    "smtp_warning": warning}
        return {**result, "status": "drafted", "mode": "draft_fallback", "draft_path": str(path), "warning": warning}
    return {**result, "status": "failed", "mode": "failed", "warning": warning}
