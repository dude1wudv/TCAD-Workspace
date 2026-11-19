#!/usr/bin/env python3
"""Private SQLite annotations for a read-only public status projection.

Python 3.9+, standard library only. This store never edits runner state.
"""

import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import unicodedata
from contextlib import contextmanager


DEFAULT_DB = Path("/var/lib/xjtu-shop-status/progress.sqlite3")
DEFAULT_TIMEOUT = 10.0
ISSUES = frozenset({
    "newton_nonconvergence", "mesh_quality", "license_wait",
    "resource_pressure", "input_validation", "solver_failure", "none",
})
ACTIONS = frozenset({
    "investigating", "fixing", "prepared", "retesting", "monitoring", "resolved",
})
PHASES = frozenset({"preparing", "transport", "device", "analysis", "validation"})
PUBLIC_FIELDS = (
    "case_id", "issue", "action", "phase", "note", "next_step",
    "updated_at", "evidence_recorded",
)
_CASE = re.compile(r"(?:m1-r05|r[0-9]{2,}|BENCH|DEV)-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\Z")
_SECRET = re.compile(
    r"(?:password|passwd|token|api[_ -]?key|secret|authorization|bearer)"
    r"\s*(?:[:=]|\s+\S+)"
    r"|(?:sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{8,}"
    r"|\bAKIA[A-Z0-9]{16}\b|-----BEGIN"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|(?:密码|密钥|令牌|许可证)\s*[:=：]",
    re.IGNORECASE,
)
_CLAIM = re.compile(
    r"\b(?:accepted|succeeded|converged)\b"
    r"|\b(?:solver|simulation|validation)\s+(?:success\w*|passed)\b"
    r"|求解成功|仿真成功|验收通过|已验收|验证通过|复验通过|已收敛",
    re.IGNORECASE,
)
_URL = re.compile(r"[a-z][a-z0-9+.-]*://|www\.", re.IGNORECASE)
_IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_IPV6 = re.compile(r"(?<![0-9a-f:])[0-9a-f:.%]*:[0-9a-f:.%]*:[0-9a-f:.%]*", re.I)
_ENTITY = re.compile(r"&(?:#\w+|lt|gt|amp|quot|apos);", re.IGNORECASE)
_COMMAND = re.compile(r"\b(?:ssh|scp|sudo|systemctl|curl|wget|bash|powershell|tcad\.py)\b", re.I)
_COLUMNS = (
    "case_id, issue, action, phase, note, next_step, updated_at, evidence"
)
_PUBLIC_SELECT = (
    "case_id, issue, action, phase, note, next_step, updated_at, "
    "(length(trim(evidence)) > 0) AS evidence_recorded"
)
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS progress (
        case_id TEXT PRIMARY KEY,
        issue TEXT NOT NULL, action TEXT NOT NULL, phase TEXT NOT NULL,
        note TEXT NOT NULL, next_step TEXT NOT NULL,
        updated_at TEXT NOT NULL, evidence TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation TEXT NOT NULL CHECK (operation IN ('set', 'clear')),
        case_id TEXT NOT NULL,
        issue TEXT NOT NULL, action TEXT NOT NULL, phase TEXT NOT NULL,
        note TEXT NOT NULL, next_step TEXT NOT NULL,
        updated_at TEXT NOT NULL, evidence TEXT NOT NULL
    )""",
    """CREATE TRIGGER IF NOT EXISTS history_no_update
        BEFORE UPDATE ON history BEGIN
        SELECT RAISE(ABORT, 'history is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS history_no_delete
        BEFORE DELETE ON history BEGIN
        SELECT RAISE(ABORT, 'history is append-only'); END""",
)


def _case_id(value):
    if (
        not isinstance(value, str) or len(value) > 96
        or not _CASE.fullmatch(value)
        or re.search(r"(?:^|-)r04(?:-|$)", value, re.I)
    ):
        raise ValueError("case_id must be a public r<revision>-..., m1-r05-..., DEV-... or BENCH-... identifier (excluding r04)")
    return value


def _text(value, field, limit=180, private=False):
    """Reject unsafe text rather than silently altering the operator's meaning."""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("{} exceeds its text limit".format(field))
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("{} contains control or invisible characters".format(field))
    normalized = unicodedata.normalize("NFKC", value)
    # Normalize for inspection too, so full-width punctuation cannot hide markup.
    if (
        _SECRET.search(normalized) or _URL.search(normalized)
        or "<" in normalized or ">" in normalized or _ENTITY.search(normalized)
        or _IPV4.search(normalized)
    ):
        raise ValueError("{} contains private or unsafe content".format(field))
    for match in _IPV6.finditer(normalized):
        try:
            ipaddress.ip_address(match.group().split("%", 1)[0])
        except ValueError:
            continue
        raise ValueError("{} contains an IP address".format(field))
    if not private and (
        "/" in normalized or "\\" in normalized
        or re.search(r"\b[A-Za-z]:", normalized) or _CLAIM.search(normalized) or _COMMAND.search(normalized)
    ):
        raise ValueError("{} contains a path, command, or solver/acceptance claim".format(field))
    return value.strip()


def _payload(case_id, issue, action, phase, note, next_step, evidence):
    case_id = _case_id(case_id)
    for field, value, allowed in (
        ("issue", issue, ISSUES), ("action", action, ACTIONS), ("phase", phase, PHASES),
    ):
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("invalid {}".format(field))
    note = _text(note, "note")
    next_step = _text(next_step, "next_step")
    evidence = _text(evidence, "evidence", limit=512, private=True)
    if action == "resolved" and not evidence:
        raise ValueError("resolved requires a private evidence reference")
    return case_id, issue, action, phase, note, next_step, evidence


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _path(path):
    path = Path(path).expanduser().absolute()
    # Reject symlinks in every existing path component, including the database.
    if any(part.is_symlink() for part in (path,) + tuple(path.parents)):
        raise ValueError("progress database path must not contain symlinks")
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("progress database must be a regular file")
    return path


def _timeout(value):
    value = float(value)
    if not 0 < value <= 60:
        raise ValueError("SQLite timeout must be between 0 and 60 seconds")
    return value


def _check_schema(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported progress database schema")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("invalid progress database")
    # Both tables must be readable, even when the public projection is empty.
    connection.execute("SELECT {} FROM progress LIMIT 0".format(_COLUMNS))
    connection.execute("SELECT id, operation, {} FROM history LIMIT 0".format(_COLUMNS))


@contextmanager
def _connection(path, timeout=DEFAULT_TIMEOUT, initialize=False, readonly=False):
    path = _path(path)
    timeout = _timeout(timeout)
    connection = None
    try:
        if initialize:
            path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            if os.name == "posix":
                path.parent.chmod(0o750)
            # Precreate with restrictive permissions before SQLite opens the file.
            descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o640)
            os.close(descriptor)
        if not readonly and path.exists() and os.name == "posix":
            path.chmod(0o640)
            path.parent.chmod(0o750)
        mode = "ro" if readonly else "rw"
        connection = sqlite3.connect(
            path.as_uri() + "?mode=" + mode, uri=True,
            timeout=timeout, isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        if readonly:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
        else:
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
        if initialize:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if version == 0 and tables:
                raise ValueError("refusing to initialize an unrelated database")
            if version not in (0, 1):
                raise ValueError("unsupported progress database schema")
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
        _check_schema(connection)
        yield connection
        connection.commit()
    except sqlite3.Error:
        raise ValueError("progress database is invalid, unavailable, or busy") from None
    except OSError:
        raise ValueError("progress database filesystem is unavailable") from None
    finally:
        if connection is not None:
            # close() rolls back any failed transaction, including both writes.
            connection.close()


def init_store(path=DEFAULT_DB, timeout=DEFAULT_TIMEOUT):
    """Initialize explicitly; set/clear never create an accidental empty store."""
    with _connection(path, timeout, initialize=True):
        pass


def set_progress(
    path=DEFAULT_DB, *, case_id, issue, action, phase,
    note="", next_step="", evidence="", timeout=DEFAULT_TIMEOUT
):
    values = _payload(case_id, issue, action, phase, note, next_step, evidence)
    case_id, issue, action, phase, note, next_step, evidence = values
    with _connection(path, timeout) as connection:
        # Timestamp after acquiring the write lock, in the same order as history.
        row = (case_id, issue, action, phase, note, next_step, _now(), evidence)
        connection.execute(
            "INSERT INTO progress ({}) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(case_id) DO UPDATE SET "
            "issue=excluded.issue, action=excluded.action, phase=excluded.phase, "
            "note=excluded.note, next_step=excluded.next_step, "
            "updated_at=excluded.updated_at, evidence=excluded.evidence".format(_COLUMNS),
            row,
        )
        connection.execute(
            "INSERT INTO history (operation, {}) VALUES ('set', ?, ?, ?, ?, ?, ?, ?, ?)".format(_COLUMNS),
            row,
        )
    return _public_row(dict(zip(_COLUMNS.split(", "), row)))


def clear_progress(path=DEFAULT_DB, *, case_id, timeout=DEFAULT_TIMEOUT):
    """Remove a current annotation while retaining its private audit snapshot."""
    case_id = _case_id(case_id)
    with _connection(path, timeout) as connection:
        old = connection.execute(
            "SELECT {} FROM progress WHERE case_id = ?".format(_COLUMNS), (case_id,)
        ).fetchone()
        if old is None:
            return False
        snapshot = dict(old)
        snapshot["updated_at"] = _now()
        connection.execute(
            "INSERT INTO history (operation, {}) VALUES ('clear', ?, ?, ?, ?, ?, ?, ?, ?)".format(_COLUMNS),
            tuple(snapshot[key] for key in _COLUMNS.split(", ")),
        )
        connection.execute("DELETE FROM progress WHERE case_id = ?", (case_id,))
    return True


def _public_row(row):
    # Revalidate public fields on read as SQLite may have external writers.
    evidence_recorded = bool(row.get("evidence_recorded", bool(row.get("evidence"))))
    values = _payload(
        row["case_id"], row["issue"], row["action"], row["phase"],
        row["note"], row["next_step"], "recorded" if evidence_recorded else "",
    )
    timestamp = row["updated_at"]
    if not isinstance(timestamp, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", timestamp
    ):
        raise ValueError("invalid progress timestamp")
    try:
        dt.datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError:
        raise ValueError("invalid progress timestamp") from None
    return dict(zip(PUBLIC_FIELDS, values[:6] + (timestamp, evidence_recorded)))


def load_public_progress(path=DEFAULT_DB, timeout=DEFAULT_TIMEOUT):
    """Read a consistent sanitized snapshot; missing DB yields [].

    ValueError means preserve the previous projection and flag stale data.
    Never replace a failed read with an empty successful status snapshot.
    """
    path = _path(path)
    if not path.exists():
        return []
    with _connection(path, timeout, readonly=True) as connection:
        rows = connection.execute(
            "SELECT {} FROM progress ORDER BY case_id".format(_PUBLIC_SELECT)
        ).fetchall()
        return [_public_row(dict(row)) for row in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "set", "list", "clear"):
        command = commands.add_parser(name)
        # Accept common options both before and after the subcommand.
        command.add_argument("--db", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--timeout", type=float, default=argparse.SUPPRESS)
        if name in ("set", "clear"):
            command.add_argument("--case", dest="case_id", required=True)
        if name == "set":
            command.add_argument("--issue", choices=sorted(ISSUES), required=True)
            command.add_argument("--action", choices=sorted(ACTIONS), required=True)
            command.add_argument("--phase", choices=sorted(PHASES), required=True)
            command.add_argument("--note", default="")
            command.add_argument("--next-step", default="")
            command.add_argument("--evidence", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_store(args.db, args.timeout)
            result = {"initialized": True}
        elif args.command == "set":
            result = set_progress(
                args.db, case_id=args.case_id, issue=args.issue, action=args.action,
                phase=args.phase, note=args.note, next_step=args.next_step,
                evidence=args.evidence, timeout=args.timeout,
            )
        elif args.command == "clear":
            result = {"cleared": clear_progress(
                args.db, case_id=args.case_id, timeout=args.timeout,
            )}
        else:
            result = load_public_progress(args.db, args.timeout)
    except ValueError as error:
        print("progress-store: {}".format(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
