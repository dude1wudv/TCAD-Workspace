"""Move planning off the TCAD server while preserving the original scheduler.

Dry-run inventories system systemd units and standard Cronie locations. Apply
blocks dedicated units with reversible condition drop-ins. Direct, unambiguous
system cron entries are commented in place. Personal crontabs, periodic scripts
and opaque wrappers with planner markers need separate review. Discovery covers
system units, direct commands and visible markers. Use a quiet configuration window.
"""

import argparse
import base64
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time


SYSTEMD = Path("/etc/systemd/system")
CRON_D = Path("/etc/cron.d")
CRONTAB = Path("/etc/crontab")
CRON_SPOOL = Path("/var/spool/cron")
CRON_PERIODIC = tuple(Path("/etc/cron." + period) for period in ("hourly", "daily", "weekly", "monthly"))
SCHEDULER = "tcad-autonomy.service"
PROTECTED_UNITS = {SCHEDULER, "tcad-centos79-vm.service"}
DROPIN = "99-local-director-cutover.conf"
BACKUP_PREFIX = ".local-director-cutover-"
UNIT = re.compile(r"[A-Za-z0-9_.:@\\-]+\.(?:timer|service)")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
EXEC_FIELDS = (
    "ExecStartPre", "ExecStartPost", "ExecCondition", "ExecStop", "ExecStopPost", "ExecReload",
)
DEPENDENCIES = (
    "RequiredBy", "RequisiteOf", "BoundBy", "ConsistsOf", "PropagatesStopTo", "OnFailure", "OnSuccess",
)
PROPERTIES = (
    "Id", "Names", "LoadState", "ActiveState", "MainPID", "ControlGroup", "ExecStart",
    "DropInPaths", "NeedDaemonReload", "Triggers", "TriggeredBy", "User", "UnitFileState", *EXEC_FIELDS, *DEPENDENCIES,
)


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def command(*argv, timeout=30):
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                            env={**os.environ, "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode:
        raise Refused(f"{Path(argv[0]).name} {argv[-1]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def systemctl(*argv):
    return command("systemctl", "--system", "--no-pager", *argv)


def show_units(names):
    rows = {}
    names = sorted(set(names))
    for offset in range(0, len(names), 32):
        output = systemctl("show", "--all", "--property=" + ",".join(PROPERTIES), "--", *names[offset:offset + 32])
        for block in output.strip().split("\n\n"):
            fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            if fields.get("Id"):
                rows[fields["Id"]] = fields
    return rows


def unit_argv(value):
    match = re.fullmatch(r"\{ path=([^ ;]+) ; argv\[\]=([^;]+) ; ignore_errors=no ; [^{}]*\}", value)
    if match:
        argv = tuple(match[2].strip().split())
        if argv and argv[0] == match[1]:
            return argv
    return ()


def absolute(value):
    return (isinstance(value, str) and SAFE_PATH.fullmatch(value) is not None
            and str(PurePosixPath(value)) == value and ".." not in PurePosixPath(value).parts)


def python_path(value):
    return absolute(value) and re.fullmatch(r"python(?:3(?:\.\d+)?)?", PurePosixPath(value).name) is not None


def trusted_directory(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                f"Untrusted directory: {parent}")


def trusted_file(path):
    try:
        info = path.stat()
        trusted_directory(path.parent)
        return stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    except (FileNotFoundError, Refused):
        return False


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    start: str
    argv: tuple
    exe: str
    cgroup: str = ""


def process(pid):
    path = Path("/proc") / str(pid)
    try:
        fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        argv = tuple(os.fsdecode(arg) for arg in (path / "cmdline").read_bytes().rstrip(b"\0").split(b"\0"))
        if not argv[0]:
            return None
        return Process(pid, int(fields[1]), fields[19], argv, os.readlink(path / "exe"), (path / "cgroup").read_text())
    except (FileNotFoundError, ProcessLookupError):
        return None


def processes():
    rows = (process(int(path.name)) for path in Path("/proc").iterdir() if path.name.isdecimal())
    return {row.pid: row for row in rows if row is not None}


def atomic_write(path, value, before):
    trusted_directory(path.parent)
    info = path.lstat() if before is not None else None
    if info is not None:
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == 0,
                f"Expected a root-owned, single-link regular file: {path}")
    require(file_bytes(path) == before, f"File changed during cutover: {path}")
    if value is None:
        path.unlink()
    else:
        fd, name = tempfile.mkstemp(prefix=".cutover-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                if info is not None:
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                    os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                    inherited_attrs = os.listxattr(temporary, follow_symlinks=False)
                    for attr in os.listxattr(path, follow_symlinks=False):
                        attr_value = os.getxattr(path, attr, follow_symlinks=False)
                        if attr not in inherited_attrs or os.getxattr(temporary, attr, follow_symlinks=False) != attr_value:
                            os.setxattr(temporary, attr, attr_value, follow_symlinks=False)
                else:
                    os.fchmod(stream.fileno(), 0o644)
                stream.flush()
                if info is not None and (path == CRONTAB or path.parent == CRON_D):
                    now = time.time_ns()
                    if now // 10**9 == info.st_mtime_ns // 10**9:
                        os.utime(stream.fileno(), ns=(now, now - 10**9))
                os.fsync(stream.fileno())
            require(file_bytes(path) == before and (info is None or identity(path.lstat()) == identity(info)),
                    f"File changed during cutover: {path}")
            if info is None:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    fsync_directory(path.parent)
    require(file_bytes(path) == value, f"Could not verify file: {path}")


def identity(info):
    return info.st_dev, info.st_ino, info.st_ctime_ns


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def file_bytes(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISREG(info.st_mode), f"Expected a regular file: {path}")
    return path.read_bytes()


def encoded(value):
    return None if value is None else base64.b64encode(value).decode("ascii")


def decoded(value):
    return None if value is None else base64.b64decode(value, validate=True)


def dropin(unit):
    return SYSTEMD / (unit + ".d") / DROPIN


def condition(unit):
    return f"[Unit]\nConditionPathExists=!{dropin(unit)}\n".encode("ascii")


class Cutover:
    def __init__(self, request):
        self.controller = tuple(request["controller"])
        self.policy_path = Path(request["policy"])
        self.configured = set(request["units"])
        self.wait = request["wait"]
        require(all(UNIT.fullmatch(unit) and unit not in PROTECTED_UNITS for unit in self.configured),
                "Invalid dedicated planner unit list")
        scripts = [arg for arg in self.controller if Path(arg).name == "controller.py" and absolute(arg)]
        require(self.controller and python_path(self.controller[0]) and len(scripts) == 1
                and absolute(str(self.policy_path)), "Expected absolute Python, controller.py and policy paths")
        self.controller_script = Path(scripts[0]).resolve(strict=True)
        self.install_root = Path(scripts[0]).parent.parent.resolve()
        require(trusted_file(self.controller_script) and trusted_file(Path(self.controller[0]).resolve()),
                "Controller and Python must resolve to trusted installation files")
        trusted_directory(self.policy_path.parent)
        self.policy_bytes = file_bytes(self.policy_path)
        self.policy = json.loads(self.policy_bytes)
        require(self.policy.get("schema") == "tcad-server-codex-v2"
                and self.policy.get("planner_mode", "on_demand_async") in {"disabled", "on_demand_async", "repair_only_async"}
                and absolute(self.policy.get("state_dir")), "Unsupported controller policy")
        self.state = Path(self.policy["state_dir"]).resolve()
        self.codex = self.policy.get("codex_binary")
        self.scheduler_user = ""

    def controller_read(self, *args, timeout=30):
        argv = (*self.controller, "--policy", str(self.policy_path), *args)
        if self.scheduler_user not in {"", "root"}:
            argv = ("runuser", "-u", self.scheduler_user, "--", "env", "PYTHONDONTWRITEBYTECODE=1", *argv)
        return json.loads(command(*argv, timeout=timeout))

    def leader(self, argv, executable=None):
        if not argv or not python_path(argv[0]):
            return None
        tokens = list(argv[1:])
        while tokens and tokens[0] in {"-B", "-I", "-E", "-s", "-u"}:
            tokens.pop(0)
        if not tokens or not absolute(tokens[0]) or Path(tokens[0]).name != "team_leader.py":
            return None
        script = Path(tokens.pop(0)).resolve()
        in_trusted_opt = self.install_root in script.parents or script.parent.parent == self.install_root.parent
        if not in_trusted_opt or not trusted_file(script):
            return None
        interpreter = Path(argv[0]).resolve()
        if not trusted_file(interpreter) or (executable is not None and Path(executable) != interpreter):
            return None
        flags = {}
        while tokens:
            option = tokens.pop(0)
            if option in {"--force", "--observe"}:
                continue
            if option not in {"--policy", "--release", "--state", "--maintenance-summary"} or option in flags:
                return None
            if not tokens or not absolute(tokens[0]):
                return None
            flags[option] = Path(tokens.pop(0))
        if (len(flags) != 4 or flags["--policy"] != self.policy_path
                or flags["--release"].resolve() != self.controller_script.parent):
            return None
        state = flags["--state"].resolve()
        if state == self.state or state in self.state.parents or self.state in state.parents:
            return None
        return str(flags["--state"])

    def inventory(self):
        installed = systemctl("list-unit-files", "--type=service,timer", "--no-legend", "--plain")
        loaded = systemctl("list-units", "--all", "--type=service,timer", "--no-legend", "--plain")
        names = {line.split()[0] for line in (installed + "\n" + loaded).splitlines()
                 if line.split() and UNIT.fullmatch(line.split()[0]) and "@." not in line.split()[0]}
        rows = show_units(names | {SCHEDULER})
        require(rows.get(SCHEDULER, {}).get("LoadState") == "loaded", "Original scheduler unit is unavailable")
        scheduler_argv = unit_argv(rows[SCHEDULER].get("ExecStart", ""))
        require(scheduler_argv[-1:] == ("serve",)
                and ("--policy", str(self.policy_path)) in zip(scheduler_argv, scheduler_argv[1:])
                and any(Path(arg).name == "controller.py" and absolute(arg) and Path(arg).resolve() == self.controller_script
                        for arg in scheduler_argv), "Configured policy/controller do not match the original scheduler unit")
        leads, states, blockers = {}, set(), []
        for name, row in rows.items():
            if row.get("LoadState") != "loaded" or not name.endswith(".service") or name in PROTECTED_UNITS:
                continue
            argv = unit_argv(row.get("ExecStart", ""))
            state = self.leader(argv)
            if state:
                leads[name] = row
                states.add(state)
            elif re.search(r"team[-_]leader|research[-_]lead", " ".join(
                    [name, *(row.get(key, "") for key in ("ExecStart", *EXEC_FIELDS))]), re.I):
                blockers.append(f"Unverified leader service: {name}")
        services = set(leads)
        for name, row in rows.items():
            targets = set(row.get("Triggers", "").split())
            if name.endswith(".timer") and targets & services:
                if len(targets) != 1:
                    blockers.append(f"Timer also triggers other units: {name}")
                else:
                    leads[name] = row
            elif name.endswith(".timer") and re.search(r"team[-_]leader|research[-_]lead", name, re.I):
                blockers.append(f"Unverified leader timer: {name}")
        for name, row in leads.items():
            if ("\\" in name or row.get("NeedDaemonReload") != "no"
                    or any(row.get(key) for key in (*EXEC_FIELDS, *DEPENDENCIES))
                    or row.get("ActiveState") not in {"active", "inactive", "failed", "activating", "deactivating"}):
                blockers.append(f"Planner unit needs review: {name}")
            if name.endswith(".timer") and row.get("ActiveState") in {"activating", "deactivating"}:
                blockers.append(f"Planner timer is transitioning: {name}")
            extra_triggers = set(row.get("TriggeredBy", "").split()) - leads.keys()
            if extra_triggers:
                blockers.append(f"Additional activation sources for {name}: {sorted(extra_triggers)}")
            if row.get("UnitFileState") not in {"enabled", "disabled", "static"}:
                blockers.append(f"Planner enablement needs review: {name}")
            if row.get("UnitFileState") == "enabled" and re.search(r"(?m)^\s*Also\s*=", systemctl("cat", "--", name)):
                blockers.append(f"Planner enablement also affects other units: {name}")
        aliases = {alias for row in leads.values() for alias in row.get("Names", "").split()} | set(leads)
        for row in rows.values():
            if self.configured.intersection(row.get("Names", "").split() + [row["Id"]]) and row["Id"] not in leads:
                blockers.append(f"Configured unit was not proved dedicated: {row['Id']}")
        return rows[SCHEDULER], leads, aliases, states, blockers

    def cron(self, aliases):
        files = [CRONTAB, *(sorted(CRON_D.iterdir()) if CRON_D.is_dir() else ())]
        personal = sorted(CRON_SPOOL.iterdir()) if CRON_SPOOL.is_dir() else []
        edits, found, states, blockers = {}, [], set(), []
        markers = {"team_leader", "team-leader", "research-lead", "research_lead", *(Path(name).stem for name in self.configured | aliases)}
        direct_unit = re.compile(r"(?:/usr/bin/|/bin/)?systemctl (?:--system )?start ([A-Za-z0-9_.:@-]+)")
        for path in files + personal:
            if path.name.startswith("."):
                continue
            if not path.is_file():
                continue
            raw = path.read_bytes()
            updated = []
            system = path in files
            for number, line in enumerate(raw.split(b"\n"), 1):
                text = line.decode("utf-8", errors="surrogateescape").strip()
                updated.append(line)
                if not text or text.startswith("#") or re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*=", text):
                    continue
                fields = text.split(None, (2 if system else 1) if text.startswith("@") else (6 if system else 5))
                command_text = fields[-1]
                if not any(marker in command_text for marker in markers):
                    continue
                address = f"{path}:{number}"
                expected_fields = (3 if system else 2) if text.startswith("@") else (7 if system else 6)
                unit = direct_unit.fullmatch(command_text)
                if len(fields) == expected_fields and unit and unit[1] in aliases:
                    found.append({"line": address, "action": "covered_by_unit_condition"})
                    continue
                state = None
                if len(fields) == expected_fields and not re.search(r"[;&|<>%$`\\#\r\0]", command_text):
                    try:
                        state = self.leader(tuple(shlex.split(command_text)))
                    except ValueError:
                        pass
                if (not state or not system or path.is_symlink()
                        or (path != CRONTAB and not re.fullmatch(r"[A-Za-z0-9_-]+", path.name))):
                    blockers.append(f"Cron entry needs manual review: {address}")
                    continue
                states.add(state)
                found.append({"line": address, "action": "comment_exact_line"})
                updated[-1] = b"# local-director cutover: " + line
            changed = b"\n".join(updated)
            if changed != raw:
                edits[path] = (raw, changed)
        for directory in CRON_PERIODIC:
            if directory.is_dir():
                for path in sorted(directory.iterdir()):
                    if not path.name.startswith(".") and path.is_file():
                        content = path.read_bytes()
                        if any(marker in path.name or marker.encode() in content for marker in markers):
                            blockers.append(f"Periodic cron script needs manual review: {path}")
        return edits, found, states, blockers

    def planner_processes(self, known_states):
        rows = processes()
        leaders, codex, unknown = {}, {}, []
        for row in rows.values():
            if "--inspect" in row.argv or not any(Path(arg).name == "team_leader.py" for arg in row.argv[1:]):
                continue
            state = self.leader(row.argv, row.exe)
            if state:
                leaders[row.pid] = state
            elif re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(row.exe).name):
                unknown.append(row.pid)
        for pid in list(leaders):
            if any(unit in rows[pid].cgroup for unit in PROTECTED_UNITS):
                unknown.append(pid)
                continue
            ancestor = rows.get(rows[pid].parent)
            while ancestor:
                if (ancestor.pid in leaders or ancestor.pid in unknown
                        or (ancestor.argv[1:2] == ("exec",) and Path(ancestor.exe).name == "codex")
                        or any(Path(arg).name == "controller.py" for arg in ancestor.argv[1:])):
                    unknown.append(pid)
                    break
                ancestor = rows.get(ancestor.parent)
        for pid in unknown:
            leaders.pop(pid, None)
        for row in rows.values():
            if row.argv[1:2] != ("exec",):
                continue
            state = leaders.get(row.parent)
            report = any(option == "--output-last-message" and Path(value).name == "leader-report.json"
                         for option, value in zip(row.argv, row.argv[1:]))
            if not report:
                continue
            matches = [root for root in set(known_states) | set(leaders.values())
                       if ("--cd", root) in zip(row.argv, row.argv[1:])
                       and ("--output-last-message", str(PurePosixPath(root) / "leader-report.json"))
                       in zip(row.argv, row.argv[1:])]
            if (matches and state in matches and absolute(self.codex) and row.argv[0] == self.codex
                    and row.exe == str(Path(self.codex).resolve()) and row.argv[-1] == "-"
                    and not any(unit in row.cgroup for unit in PROTECTED_UNITS)
                    and ("--output-schema", str(self.controller_script.parent / "report.schema.json"))
                    in zip(row.argv, row.argv[1:])):
                codex[row.pid] = row.parent
            elif matches or (absolute(self.codex) and row.exe == str(Path(self.codex).resolve())):
                unknown.append(row.pid)
        return rows, leaders, codex, sorted(set(unknown))

    def scheduler_idle(self):
        row = show_units([SCHEDULER])[SCHEDULER]
        jobs = systemctl("list-jobs", "--no-legend", "--plain")
        require(row.get("ActiveState") in {"inactive", "failed"} and row.get("MainPID") == "0"
                and not any(SCHEDULER in line.split()[1:2] for line in jobs.splitlines()),
                "Planner policy change requires the original scheduler to be offline")
        for proc in processes().values():
            if "serve" in proc.argv and any(Path(arg).name == "controller.py" for arg in proc.argv[1:]):
                raise Refused(f"Controller serve process is still present: PID {proc.pid}")

    def reconcile(self, *, empty=False, no_pending=False, no_collecting=False):
        observation = self.controller_read("reconcile", "--read-only", timeout=90)
        scheduler = observation.get("scheduler", {})
        slots = scheduler.get("pool", {}).get("slots", {})
        require(scheduler.get("read_only") is True and scheduler.get("probe", {}).get("ok") is True
                and observation.get("discovery_uncertain") is False and observation.get("external_runs") == [],
                "Read-only reconciliation could not confirm the original pool")
        if empty:
            require(observation.get("active_count") == observation.get("running_count") == 0
                    and slots.get("total", 0) > 0 and slots.get("free") == slots.get("total")
                    and slots.get("collecting") == slots.get("quarantined") == 0,
                    "Original pool still has active, collecting or quarantined work")
        elif no_collecting:
            require(slots.get("collecting", 0) == 0,
                    "Original pool has an active collection in progress")
        if no_pending:
            require(observation.get("pending_count") == 0 and not observation.get("repair_requests"),
                    "Original scheduler may start pending work during the restart")

    def stop_scheduler(self, *, allow_active=False):
        row = show_units([SCHEDULER])[SCHEDULER]
        if row.get("ActiveState") == "active":
            self.reconcile(empty=not allow_active, no_pending=not allow_active, no_collecting=allow_active)
            current = show_units([SCHEDULER])[SCHEDULER]
            require(current.get("MainPID") == row.get("MainPID") and current.get("ActiveState") == "active",
                    "Original scheduler changed during the maintenance check")
            argv = unit_argv(current.get("ExecStart", ""))
            pid = int(current["MainPID"])
            rows = processes()
            def _safe_mux(other):
                return bool(other.argv and other.argv[0].startswith(f"ssh: {self.state}/ssh-mux/") and other.argv[0].endswith(" [mux]"))

            require(pid in rows and rows[pid].argv == argv and argv[-1:] == ("serve",)
                    and any(Path(arg).name == "controller.py" and Path(arg).resolve() == self.controller_script for arg in argv)
                    and ("--policy", str(self.policy_path)) in zip(argv, argv[1:])
                    and not current.get("ExecStop") and not current.get("ExecStopPost")
                    and not current.get("PropagatesStopTo")
                    and not any(other.pid != pid and SCHEDULER in other.cgroup and not _safe_mux(other) for other in rows.values()),
                    "Original scheduler identity or process group needs manual review")
            command("systemctl", "--system", "stop", "--", SCHEDULER, timeout=1600)
        self.scheduler_idle()

    def start_scheduler(self):
        if show_units([SCHEDULER])[SCHEDULER].get("ActiveState") != "active":
            systemctl("start", "--", SCHEDULER)
        require(show_units([SCHEDULER])[SCHEDULER].get("ActiveState") == "active", "Original scheduler did not start")

    @contextmanager
    def idle_policy(self, *, allow_active=False):
        import fcntl

        self.scheduler_idle()
        lock = self.state / "controller.lock"
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.scheduler_idle()
            self.reconcile(empty=not allow_active, no_collecting=allow_active)
            self.scheduler_idle()
            yield

    def drain(self, units, states, force):
        deadline = time.monotonic() + self.wait
        signalled = set()
        while True:
            rows, leaders, children, unknown = self.planner_processes(states)
            states.update(leaders.values())
            current = show_units(units)
            require(current.keys() == units.keys(), "Planner unit inventory changed while waiting")
            active = [name for name, row in current.items()
                      if row.get("ActiveState") not in {"inactive", "failed"}]
            if not (active or leaders or children or unknown):
                return sorted(signalled)
            require(not unknown, f"Unattributed planner processes: {unknown}")
            if force:
                for pid in (*children, *leaders):
                    if pid in signalled or (pid in leaders and pid in children.values()):
                        continue
                    if any(row.parent == pid for row in rows.values()):
                        continue
                    if self.terminate(rows[pid], states):
                        signalled.add(pid)
            require(time.monotonic() < deadline,
                    f"Planner did not quiesce: units={active}, leaders={sorted(leaders)}, codex={sorted(children)}")
            time.sleep(1)

    def terminate(self, expected, states):
        require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
                "--force requires Linux pidfd support")
        try:
            fd = os.pidfd_open(expected.pid)
        except ProcessLookupError:
            return False
        try:
            rows, leaders, children, _ = self.planner_processes(states)
            if (rows.get(expected.pid) != expected or process(expected.pid) != expected
                    or any(row.parent == expected.pid for row in rows.values())
                    or expected.pid not in (leaders.keys() | children.keys())):
                return False
            if expected.pid in children and process(expected.parent) != rows.get(expected.parent):
                return False
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False
        finally:
            os.close(fd)

    def backup(self, files, units, timers, scheduler_running):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        folder = Path(tempfile.mkdtemp(prefix=f"{BACKUP_PREFIX}{stamp}-", dir=self.policy_path.parent))
        manifest = {"policy": str(self.policy_path), "controller": list(self.controller),
                    "units": sorted(units), "active_timers": sorted(timers),
                    "enabled_units": sorted(name for name, row in units.items() if row.get("UnitFileState") == "enabled"),
                    "scheduler_running": scheduler_running,
                    "files": {str(path): [encoded(before), encoded(after)] for path, (before, after) in files.items()}}
        with (folder / "policy.json").open("xb") as stream:
            stream.write(self.policy_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        target = folder / "manifest.json"
        with target.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(folder)
        fsync_directory(folder.parent)
        print(json.dumps({"backup": str(folder), "state": "prepared"}), flush=True)
        return folder, manifest

    def restore(self, manifest, units):
        require(manifest["policy"] == str(self.policy_path) and manifest["controller"] == list(self.controller),
                "Backup belongs to a different controller")
        unit_names = set(manifest["units"])
        timers = set(manifest["active_timers"])
        enabled = set(manifest.get("enabled_units", ()))
        require(unit_names <= units.keys() and enabled <= unit_names
                and timers <= {name for name in unit_names if name.endswith(".timer")},
                "Backup planner units could not be revalidated")
        files = {Path(name): tuple(map(decoded, values)) for name, values in manifest["files"].items()}
        expected_dropins = {dropin(name): condition(name) for name in unit_names}
        for path, (before, after) in files.items():
            allowed = (path == self.policy_path or path == CRONTAB
                       or (path.parent == CRON_D and re.fullmatch(r"[A-Za-z0-9_-]+", path.name))
                       or (path in expected_dropins and before is None and after == expected_dropins[path]))
            require(allowed and file_bytes(path) in (before, after), f"Rollback file drift: {path}")
        if self.policy_path in files:
            before, after = files.pop(self.policy_path)
            if file_bytes(self.policy_path) != before:
                if manifest.get("scheduler_running"):
                    self.stop_scheduler()
                with self.idle_policy():
                    atomic_write(self.policy_path, before, after)
                self.controller_read("status")
        for path, (before, after) in files.items():
            if file_bytes(path) != before:
                atomic_write(path, before, after)
        if unit_names:
            systemctl("daemon-reload")
            restored_units = show_units(unit_names)
            for name in unit_names:
                loaded = str(dropin(name)) in restored_units[name].get("DropInPaths", "").split()
                require(loaded == (file_bytes(dropin(name)) == condition(name)), f"Rollback drop-in mismatch: {name}")
                if name in enabled and restored_units[name].get("UnitFileState") != "enabled":
                    require(not re.search(r"(?m)^\s*Also\s*=", systemctl("cat", "--", name)), f"Enablement drift: {name}")
                    systemctl("enable", "--", name)
                    require(show_units([name])[name].get("UnitFileState") == "enabled", f"Enablement was not restored: {name}")
        if manifest.get("scheduler_running"):
            self.start_scheduler()
        for name in sorted(timers):
            if show_units([name])[name].get("ActiveState") != "active":
                systemctl("start", "--", name)
            require(show_units([name])[name].get("ActiveState") == "active", f"Timer did not resume: {name}")

    def run(self, request):
        scheduler, units, aliases, states, blockers = self.inventory()
        self.scheduler_user = scheduler.get("User", "")
        before_status = self.controller_read("status")
        cron_edits, cron_lines, cron_states, cron_blockers = self.cron(aliases)
        states.update(cron_states)
        rows, leaders, children, unknown = self.planner_processes(states)
        states.update(leaders.values())
        mode = self.policy.get("planner_mode", "on_demand_async")
        scheduler_running = scheduler.get("ActiveState") == "active"
        blockers = [*blockers, *cron_blockers]
        if unknown:
            blockers.append(f"Unattributed planner processes: {unknown}")
        allow_active = bool(request.get("force"))
        if mode != "disabled" and request["mode"] != "rollback":
            try:
                if not scheduler_running:
                    self.scheduler_idle()
                self.reconcile(empty=not allow_active, no_pending=scheduler_running and not allow_active, no_collecting=allow_active)
            except Refused as error:
                blockers.append(str(error))
        if request["mode"] == "dry-run":
            return {"mode": "dry-run", "planner_mode": mode, "target_planner_mode": "disabled",
                    "scheduler": {key: scheduler.get(key) for key in ("Id", "ActiveState", "MainPID")},
                    "controller": {key: before_status.get(key) for key in ("enabled", "prerequisites_passed", "ready_to_start")},
                    "units": {name: row.get("ActiveState") for name, row in units.items()},
                    "missing_configured_units": sorted(self.configured - aliases), "cron": cron_lines,
                    "leader_pids": sorted(leaders), "attributed_codex_pids": sorted(children), "blockers": blockers}
        if request["mode"] == "rollback":
            folder = Path(request["backup"])
            require(folder.parent == self.policy_path.parent and folder.name.startswith(BACKUP_PREFIX),
                    "Use the exact backup directory printed by apply")
            trusted_directory(folder)
            require(trusted_file(folder / "manifest.json"), "Untrusted cutover manifest")
            self.restore(json.loads((folder / "manifest.json").read_bytes()), units)
            return {"mode": "rollback", "backup": str(folder), "verified": True}
        require(not blockers, "\n".join(blockers))
        timers = {name for name, row in units.items() if name.endswith(".timer") and row.get("ActiveState") == "active"}
        files = dict(cron_edits)
        for name in units:
            path = dropin(name)
            current = file_bytes(path)
            require(current is None or current == condition(name), f"Conflicting drop-in: {path}")
            if current is None:
                files[path] = (None, condition(name))
        if mode != "disabled":
            policy = json.dumps({**self.policy, "planner_mode": "disabled"}, ensure_ascii=False, indent=2) + "\n"
            files[self.policy_path] = (self.policy_bytes, policy.encode("utf-8"))
        if not files and not timers and not leaders and not children and not any(
                row.get("ActiveState") not in {"inactive", "failed"} or row.get("UnitFileState") == "enabled"
                for row in units.values()):
            require(all(str(dropin(name)) in row.get("DropInPaths", "").split() for name, row in units.items()),
                    "Existing planner drop-in has not been loaded")
            self.controller_read("check")
            self.reconcile()
            return {"mode": "apply", "verified": True, "changed": False}
        original_pid = int(scheduler.get("MainPID", "0"))
        original = rows.get(original_pid)
        require(not original_pid or original is not None, "Original scheduler process identity could not be confirmed")
        folder, manifest = self.backup(files, units, timers, scheduler_running and self.policy_path in files)
        try:
            for path, (before, after) in files.items():
                if path == self.policy_path:
                    continue
                if path in {dropin(name) for name in units}:
                    trusted_directory(path.parent.parent)
                    path.parent.mkdir(exist_ok=True)
                atomic_write(path, after, before)
            if units:
                systemctl("daemon-reload")
                _, current, _, _, reload_blockers = self.inventory()
                require(current.keys() == units.keys() and not reload_blockers, "Planner units changed during daemon-reload")
                for name, row in current.items():
                    paths = row.get("DropInPaths", "").split()
                    require(str(dropin(name)) in paths and all(Path(path).name <= DROPIN for path in paths),
                            f"Could not verify final cutover drop-in: {name}")
                    require(unit_argv(row.get("ExecStart", "")) == unit_argv(units[name].get("ExecStart", ""))
                            and all(row.get(key) == units[name].get(key) for key in ("Triggers", "TriggeredBy")),
                            f"Planner unit definition changed during reload: {name}")
                    if name.endswith(".timer"):
                        require((row.get("ActiveState") == "active") == (name in timers),
                                f"Timer state changed during reload: {name}")
            for name in sorted(timers):
                systemctl("stop", "--", name)
            if cron_edits:
                print(json.dumps({"state": "waiting_for_cron_poll", "seconds": 65}), flush=True)
                time.sleep(65)
            terminated = self.drain(units, states, request["force"])
            if self.policy_path in files:
                before, after = files[self.policy_path]
                if scheduler_running:
                    self.stop_scheduler(allow_active=allow_active)
                with self.idle_policy(allow_active=allow_active):
                    atomic_write(self.policy_path, after, before)
            self.controller_read("check")
            for name in sorted(units):
                if units[name].get("UnitFileState") == "enabled":
                    systemctl("disable", "--now", "--", name)
                    require(show_units([name])[name].get("UnitFileState") == "disabled", f"Planner unit still enabled: {name}")
            if manifest["scheduler_running"]:
                self.start_scheduler()
            after_status = self.controller_read("status")
            self.reconcile()
            require(all(after_status.get(key) == before_status.get(key) for key in ("enabled", "max_parallel_jobs", "pause"))
                    and (not before_status.get("prerequisites_passed") or after_status.get("prerequisites_passed")),
                    "Original controller status changed unexpectedly")
            live_scheduler, live_units, live_aliases, live_states, unit_blockers = self.inventory()
            fresh_edits, _, _, cron_blockers = self.cron(live_aliases)
            require(live_units.keys() == units.keys() and not unit_blockers and not fresh_edits and not cron_blockers,
                    "Planner activation inventory changed during cutover")
            require(all(file_bytes(path) == after for path, (_, after) in files.items())
                    and json.loads(file_bytes(self.policy_path)).get("planner_mode") == "disabled",
                    "Final policy, cron or drop-in contents did not verify")
            if original and self.policy_path not in files:
                require(live_scheduler.get("MainPID") == str(original.pid) and process(original.pid) == original,
                        "Original scheduler process identity changed")
            self.drain(live_units, states | live_states, False)
        except (Exception, KeyboardInterrupt) as error:
            try:
                self.restore(manifest, self.inventory()[1])
            except (Exception, KeyboardInterrupt) as recovery:
                raise Refused(f"Apply failed: {error}. Recovery incomplete: {recovery}. Backup: {folder}") from recovery
            raise Refused(f"Apply failed and saved configuration was restored: {error}. Backup: {folder}") from error
        return {"mode": "apply", "backup": str(folder), "verified": True, "signalled_pids": terminated}


@contextmanager
def transaction(directory, read_only):
    import fcntl

    trusted_directory(directory)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        mode = fcntl.LOCK_SH if read_only else fcntl.LOCK_EX
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def remote_main(request):
    require(os.geteuid() == 0, "Use the configured TCAD management account with system-level read access")
    os.umask(0o077)
    if request["mode"] != "dry-run":
        for mode in (signal.SIGHUP, signal.SIGTERM):
            signal.signal(mode, interrupted)
    with transaction(Path(request["policy"]).parent, request["mode"] == "dry-run"):
        result = Cutover(request).run(request)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def interrupted(signum, _frame):
    raise InterruptedError(f"Cutover interrupted by signal {signum}")


def main(argv=None):
    from config import load_config, ssh_command

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--dry-run", action="store_true", help="Inspect only (default)")
    actions.add_argument("--apply", action="store_true", help="Disable the verified server planner entry points")
    actions.add_argument("--rollback", metavar="BACKUP", help="Restore the exact server backup printed by apply")
    parser.add_argument("--force", action="store_true", help="Allow SIGTERM to individually verified planner processes")
    parser.add_argument("--wait-seconds", type=int, default=30, help="Planner exit wait (1–300 seconds)")
    args = parser.parse_args(argv)
    if args.force and not args.apply:
        parser.error("--force requires --apply")
    if not 1 <= args.wait_seconds <= 300:
        parser.error("--wait-seconds must be in 1..300")
    cfg = load_config(args.config)
    require(isinstance(cfg.remote_controller_cmd, (tuple, list)) and cfg.remote_controller_cmd
            and python_path(cfg.remote_controller_cmd[0]), "remote_controller_cmd must start with an absolute Python path")
    request = {"mode": "apply" if args.apply else "rollback" if args.rollback else "dry-run",
               "backup": args.rollback, "force": args.force, "wait": args.wait_seconds,
               "controller": cfg.remote_controller_cmd, "policy": cfg.remote_policy_path, "units": cfg.server_lead_units}
    script = "exec " + shlex.join([cfg.remote_controller_cmd[0], "-I", "-B", "-", "--remote", json.dumps(request)])
    result = subprocess.run(ssh_command(cfg, script), input=Path(__file__).read_bytes())
    if result.returncode == 255 and request["mode"] != "dry-run":
        print("SSH outcome unknown. Review the printed backup and run --dry-run before taking further action.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    try:
        exit_status = remote_main(json.loads(sys.argv[2])) if sys.argv[0] == "-" and sys.argv[1:2] == ["--remote"] else main()
    except (Refused, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        print(str(exc), file=sys.stderr)
        exit_status = 2
    sys.exit(exit_status)
