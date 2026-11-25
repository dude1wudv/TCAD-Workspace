import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from fnmatch import fnmatchcase
from pathlib import Path
from uuid import uuid4

from config import BASE_DIR, Config
from schemas import DeliveryReceipt, WorkOrder, atomic_write, parse_time, read_json, utc_now, write_json


PROMPTS = BASE_DIR / "prompts"
MAX_FILE_BYTES = 5_000_000
MAX_RECEIPT_BYTES = 4096
STOP_STATUSES = {"timeout", "stalled"}
STOP_ACTIONS = STOP_STATUSES | {"cancelled"}
_LOCAL_RUNS = {}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "--literal-pathspecs", "-c", "core.quotePath=false", *args],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=60,
    )
    return result.stdout.decode("utf-8")


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def _file_state(path: Path) -> list:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(details.st_mode):
        return [details.st_mode, os.readlink(path)]
    if stat.S_ISREG(details.st_mode) and details.st_size <= MAX_FILE_BYTES:
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) <= MAX_FILE_BYTES:
            return [details.st_mode, hashlib.sha256(data).hexdigest()]
    return [details.st_mode, details.st_size, details.st_mtime_ns, details.st_ctime_ns]


def _snapshot(root: Path) -> dict:
    records = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames",
                   "--ignore-submodules=none")
    entries = [(record[:2], record[3:]) for record in records.split("\0") if record]
    tracked = {name for flags, name in entries if flags != "??"}
    index = {}
    if tracked:
        for entry in _git(root, "ls-files", "--stage", "-z").split("\0"):
            if entry:
                value, name = entry.split("\t", 1)
                if name in tracked:
                    index.setdefault(name, []).append(value)
    return {
        name: [flags, index.get(name, []), _file_state(root / name)]
        for flags, name in entries
    }


def _allowed(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True

    def match(parts, pattern):
        if not pattern:
            return not parts
        if pattern[0] == "**":
            return match(parts, pattern[1:]) or bool(parts and match(parts[1:], pattern))
        return bool(parts and fnmatchcase(parts[0], pattern[0]) and match(parts[1:], pattern[1:]))

    parts = path.split("/")
    for pattern in patterns:
        pattern = pattern.replace("\\", "/")
        if pattern.endswith("/"):
            pattern += "**"
        elif not any(char in pattern for char in "*?[") and path.startswith(pattern + "/"):
            return True
        if match(parts, pattern.split("/")):
            return True
    return False


def _path_error(root: Path, name: str, patterns: list[str], *, must_exist: bool = False, ssh_target: str = "") -> str | None:
    from status_publisher import find_sensitive

    parts = name.split("/")
    if (any(not part or part.endswith((".", " ")) for part in parts) or any(char in name for char in "\\:\0\r\n")
            or not _allowed(name, patterns)):
        return "outside allowed_paths"
    if any(part.lower() in {".git", "local_runtime", "output", "node_modules", "__pycache__", "agents.local.md", "secrets.env", ".ssh"}
           or part.lower() == ".env" or part.lower().startswith(".env.") for part in parts):
        return "protected path"
    reasons = find_sensitive(name)
    if reasons:
        return "sensitive path: " + ", ".join(reasons)
    target = root
    for part in parts:
        target = target / part
        try:
            details = target.lstat()
        except FileNotFoundError:
            return "artifact is missing" if must_exist else None
        if (stat.S_ISLNK(details.st_mode)
                or getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return "symbolic link or reparse point"
    if not stat.S_ISREG(details.st_mode):
        return "not a regular file"
    if details.st_size > MAX_FILE_BYTES:
        return "file exceeds 5 MB"
    with target.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return "file exceeds 5 MB"
    if data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"%PDF-")):
        return None
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    content = data.decode(encoding, errors="replace")
    reasons = [reason for reason in find_sensitive(content) if reason not in {"internal_identifier", "ssh_detail"}]
    alias = ssh_target.rpartition("@")[2]
    if alias and re.search(rf"(?<![\w.-]){re.escape(alias)}(?![\w.-])", content, re.I):
        reasons.append("configured SSH alias")
    return "sensitive content: " + ", ".join(reasons) if reasons else None


def _codex_executable() -> list[str]:
    located = shutil.which("codex")
    if os.name != "nt":
        if not located:
            raise FileNotFoundError("Codex executable was not found on PATH")
        return [located]
    located = located or shutil.which("codex.exe") or shutil.which("codex.cmd") or shutil.which("codex.ps1")
    if not located:
        raise FileNotFoundError("Codex executable was not found on PATH")
    path = Path(located).resolve()
    if path.suffix.lower() not in {".exe", ".com", ".ps1", ".cmd", ".bat"}:
        path = next((candidate for extension in (".exe", ".cmd", ".ps1")
                     if (candidate := path.with_suffix(extension)).is_file()), path)
    if path.suffix.lower() in {".cmd", ".ps1", ".bat"}:
        package = path.parent / "node_modules" / "@openai" / "codex"
        executable = package / "bin" / "codex.js"
        if executable.is_file():
            node = path.parent / "node.exe"
            node_path = str(node) if node.is_file() else shutil.which("node.exe")
            if node_path:
                return [node_path, str(executable)]
    if path.suffix.lower() == ".ps1":
        pwsh = shutil.which("pwsh") or "pwsh.exe"
        return [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(path)]
    if path.suffix.lower() not in {".exe", ".com", ".cmd", ".bat"}:
        raise FileNotFoundError("Codex entry point has no supported Windows executable or script")
    return [str(path)]


def _worker_command(argv: list[str]) -> list[str] | str:
    if os.name != "nt" or Path(argv[0]).suffix.lower() not in {".cmd", ".bat"}:
        return argv
    if not Path(argv[0]).is_absolute() or any(re.search(r'[\x00-\x1f"%!^&|<>()]', arg) for arg in argv):
        raise ValueError("unsafe argument for standalone Codex batch launcher")
    body = " ".join(f'"{arg}"' for arg in argv)
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    return f'{subprocess.list2cmdline([str(shell)])} /D /V:OFF /S /C "{body}"'


def _valid_session(session: str | None) -> bool:
    return isinstance(session, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session) is not None


def _attempt_dir(cfg: Config, order: WorkOrder, attempt: int) -> Path:
    if type(attempt) is not int or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    return cfg.state_dir.resolve() / "orders" / order.order_id / "attempts" / str(attempt)


def launch_worker(
    cfg: Config, order: WorkOrder, attempt: int = 1,
    previous_receipt: DeliveryReceipt | None = None, feedback: str = "",
) -> dict:
    """Persist an attempt and return without waiting for Codex."""
    root = cfg.repo_root.resolve()
    folder = _attempt_dir(cfg, order, attempt)
    order_dir = folder.parents[1]
    baseline_path = order_dir / "git-baseline.json"
    order_data = order.to_dict()
    head = _head(root)
    executable = _codex_executable()
    preamble = (PROMPTS / "codex-worker-preamble.md").read_text(encoding="utf-8")
    if attempt == 1:
        if previous_receipt is not None:
            raise ValueError("first attempt cannot resume a prior receipt")
        baseline = {"head": head, "files": _snapshot(root), "order": order_data}
        session = None
    else:
        baseline = read_json(baseline_path)
        if baseline["head"] != head or baseline["order"] != order_data:
            raise ValueError("work order or repository HEAD changed since launch")
        if (previous_receipt is None or previous_receipt.order_id != order.order_id
                or previous_receipt.attempt != attempt - 1):
            raise ValueError("retry requires the preceding receipt")
        previous_folder = _attempt_dir(cfg, order, attempt - 1)
        if (previous_receipt.to_dict() != read_json(previous_folder / "receipt.json")
                or previous_receipt.to_dict() != read_json(order_dir / "receipt.json")):
            raise ValueError("retry requires the latest finalized attempt")
        previous_run = read_json(previous_folder / "run.json")
        previous_manifest = read_json(previous_folder / "worker-manifest.json")
        previous_run["pid"] = previous_manifest["pid"]
        previous_exit = _read_exit(previous_run)
        if not _exit_confirmed(previous_exit) and not _tree_stopped(previous_run):
            raise ValueError("preceding worker exit was not confirmed")
        session = previous_receipt.codex_session_id if _valid_session(previous_receipt.codex_session_id) else None

    run_path = folder / "run.json"
    prompt_path = folder / "prompt.md"
    meta = {
        "order_id": order.order_id, "attempt": attempt, "started_at": utc_now(),
        "timeout_seconds": order.timeout_seconds, "codex_session_id": session,
        "repo_root": str(root), "order_dir": str(order_dir), "attempt_dir": str(folder),
        "run_path": str(run_path), "prompt_path": str(prompt_path),
        "events_path": str(folder / f"events_attempt_{attempt}.jsonl"),
        "stderr_path": str(folder / f"stderr_attempt_{attempt}.log"),
        "last_msg_path": str(folder / ("last_msg.json" if attempt == 1 else f"last_msg_attempt_{attempt}.json")),
        "exit_path": str(folder / "exit.json"),
        "worker_pid_path": str(folder / "worker-pid.json"), "stop_path": str(folder / "stop.json"),
        "job_name": f"Local\\TCADDirector-{uuid4().hex}" if os.name == "nt" else None,
    }
    playbook = ""
    if order.category in {"sim_ops", "sim_repair"}:
        playbook_path = PROMPTS / "server-ops-playbook.md"
        if playbook_path.is_file():
            playbook = "\n\n" + playbook_path.read_text(encoding="utf-8-sig").strip()
    prompt = preamble + playbook + "\n\n## Work order\n" + json.dumps(order_data, ensure_ascii=False, indent=2)
    prompt += ("\nReport cumulative changed files for this order using repository-relative paths. "
               "Run each acceptance check as a separate shell command exactly as supplied. "
               "Do not stage or commit files. Preserve existing worktree changes.\n")
    if previous_receipt is not None:
        pushback = order_dir / f"pushback_{attempt - 1}.md"
        meta["pushback_path"] = str(pushback)
        prompt += "\n## Previous receipt\n" + json.dumps(previous_receipt.to_dict(), ensure_ascii=False, indent=2)
        prompt += "\n\n## Director feedback\n" + feedback
    argv = [
        *executable, "exec", "--json", "-c", "approval_policy=never",
        "--model", cfg.codex_model, "--sandbox", cfg.codex_sandbox, "--cd", str(root),
        "-c", f"model_reasoning_effort={cfg.codex_effort}",
        "--output-schema", str(PROMPTS / "order_result.schema.json"),
        "--output-last-message", meta["last_msg_path"],
    ]
    argv.extend(["resume", session, "-"] if session else ["-"])
    _worker_command(argv)
    folder.mkdir(parents=True, exist_ok=False)
    if attempt == 1:
        write_json(baseline_path, baseline)
    if previous_receipt is not None:
        atomic_write(Path(meta["pushback_path"]), feedback + "\n")
    atomic_write(prompt_path, prompt)
    write_json(run_path, {**meta, "argv": argv})
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    supervisor = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--supervise", str(run_path)],
        cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach,
    )
    threading.Thread(target=supervisor.wait, daemon=True).start()
    result = {**meta, "pid": supervisor.pid}
    _LOCAL_RUNS[supervisor.pid] = result
    return result


def _kill_tree(worker: subprocess.Popen) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(worker.pid), "/T", "/F"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        if result.returncode and worker.poll() is None:
            raise RuntimeError("taskkill failed: " + result.stdout.decode(errors="replace").strip())
    else:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            if worker.poll() is None:
                raise


def _windows_job(name: str, *, create: bool):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    if not create:
        kernel.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenJobObjectW.restype = wintypes.HANDLE
        handle = kernel.OpenJobObjectW(4, False, name)
        if handle:
            kernel.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        if error == 2:
            return False
        raise ctypes.WinError(error)

    class Limits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
            ("working_set_min", ctypes.c_size_t), ("working_set_max", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD), ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD), ("scheduling_class", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", Limits), ("io", ctypes.c_uint64 * 6), ("memory", ctypes.c_size_t * 4)]

    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError("worker job name already exists")
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000
    if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    return handle


def _resume_missing(meta: dict) -> bool:
    if not meta["codex_session_id"] or parse_thread_id(meta["events_path"]):
        return False
    messages = [
        event.get("message", "") for event in _events(Path(meta["events_path"]))
        if event.get("type") == "error"
    ]
    with Path(meta["stderr_path"]).open("rb") as handle:
        handle.seek(max(0, handle.seek(0, os.SEEK_END) - 16384))
        messages.append(handle.read().decode("utf-8", errors="replace"))
    pattern = r"session not found|no (?:recorded )?session (?:found|with)|no rollout found|invalid (?:thread|session) id"
    return any(isinstance(message, str) and re.search(pattern, message, re.I) for message in messages)


def _supervise(run_path: Path) -> None:
    meta = read_json(run_path)
    stop = Path(meta["stop_path"])
    start = time.monotonic()
    worker = None
    exit_code = None
    status = None
    error = None
    resume_fallback = False
    with (Path(meta["events_path"]).open("wb") as events,
          Path(meta["stderr_path"]).open("wb") as stderr,
          Path(meta["prompt_path"]).open("rb") as prompt):
        try:
            if stop.is_file():
                status = read_json(stop)["status"]
            else:
                if os.name == "nt":
                    _windows_job(meta["job_name"], create=True)
                    flags = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    flags = {"process_group": 0}
                argv = meta["argv"]
                while True:
                    prompt.seek(0)
                    worker = subprocess.Popen(_worker_command(argv), cwd=meta["repo_root"], stdin=prompt,
                                              stdout=events, stderr=stderr, **flags)
                    write_json(Path(meta["worker_pid_path"]), {
                        "pid": worker.pid, "supervisor_pid": os.getpid(), "argv": argv,
                    })
                    while worker.poll() is None and not stop.is_file() and time.monotonic() - start < meta["timeout_seconds"]:
                        time.sleep(0.2)
                    if worker.poll() is None:
                        status = read_json(stop)["status"] if stop.is_file() else "timeout"
                        _kill_tree(worker)
                    exit_code = worker.wait()
                    if (status or stop.is_file() or not exit_code or resume_fallback
                            or time.monotonic() - start >= meta["timeout_seconds"] or not _resume_missing(meta)):
                        break
                    _kill_tree(worker)
                    resume_fallback = True
                    argv = argv[:-3] + ["-"]
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if worker is not None and worker.poll() is None:
                try:
                    _kill_tree(worker)
                except (OSError, RuntimeError, subprocess.SubprocessError) as cleanup_error:
                    error += f" | process tree termination failed: {cleanup_error}"
                else:
                    exit_code = worker.wait()
            stderr.write((error + "\n").encode("utf-8"))
    write_json(Path(meta["exit_path"]), {
        "order_id": meta["order_id"], "attempt": meta["attempt"], "pid": os.getpid(),
        "worker_pid": worker.pid if worker is not None else None, "exit_code": exit_code,
        "status": status, "error": error, "resume_fallback": resume_fallback,
        "finished_at": utc_now(), "duration_seconds": time.monotonic() - start,
    })


def _windows_process(pid: int) -> dict | None:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
         f"Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' -ErrorAction Stop | "
         "Select-Object CommandLine, ParentProcessId, CreationDate | ConvertTo-Json -Compress"],
        capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def _read_exit(run_meta: dict) -> dict:
    try:
        record = read_json(Path(run_meta["exit_path"]))
    except FileNotFoundError:
        return {}
    if not isinstance(record, dict) or any(record.get(key) != run_meta[key] for key in ("order_id", "attempt", "pid")):
        raise ValueError("supervisor exit record does not match attempt")
    return record


def _exit_confirmed(record: dict) -> bool:
    return bool(record) and (record.get("worker_pid") is None or type(record.get("exit_code")) is int)


def _tree_stopped(run_meta: dict) -> bool:
    pid = run_meta["pid"]
    if type(pid) is not int or pid <= 1:
        return False
    if os.name == "nt":
        if not run_meta.get("job_name") or _windows_process(pid) or _windows_job(run_meta["job_name"], create=False):
            return False
        worker_path = Path(run_meta["worker_pid_path"])
        return not worker_path.is_file() or _windows_process(read_json(worker_path)["pid"]) is None
    if not Path("/proc/self/stat").is_file():
        return False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            details = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if details[0] != "Z" and (int(entry.name) == pid or int(details[3]) == pid):
            return False
    return True


def _live_run_for_pid(pid: int) -> dict | None:
    script = Path(__file__).resolve()
    if os.name == "nt":
        process = _windows_process(pid)
        if process is None:
            return None
        script_arg = re.escape(subprocess.list2cmdline([str(script)]))
        match = re.fullmatch(r'(?i)(?:"[^"]+"|\S+) -B ' + script_arg + r' --supervise (?:"([^"]+)"|(\S+))',
                             process.get("CommandLine") or "")
        if not match:
            return None
        run_path = Path(match.group(1) or match.group(2))
    else:
        try:
            arguments = (Path("/proc") / str(pid) / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        except FileNotFoundError:
            return None
        if len(arguments) != 5 or arguments[1:4] != [b"-B", os.fsencode(script), b"--supervise"]:
            return None
        run_path = Path(os.fsdecode(arguments[4]))
    if not run_path.is_absolute() or run_path.name != "run.json":
        return None
    meta = read_json(run_path)
    if Path(meta["run_path"]) != run_path or run_path.parent != Path(meta["attempt_dir"]):
        return None
    return {**meta, "pid": pid}


def _stop_live_child(run_meta: dict) -> None:
    supervisor_pid = run_meta["pid"]
    meta = _live_run_for_pid(supervisor_pid)
    if meta is None or meta["run_path"] != run_meta["run_path"]:
        return
    worker_path = Path(meta["worker_pid_path"])
    if not worker_path.is_file():
        return
    worker = read_json(worker_path)
    pid = worker["pid"]
    if worker["supervisor_pid"] != supervisor_pid or type(pid) is not int or pid <= 1:
        return
    if os.name == "nt":
        process = _windows_process(pid)
        command = _worker_command(worker["argv"])
        command_line = subprocess.list2cmdline(command) if isinstance(command, list) else command
        if (process and process["ParentProcessId"] == supervisor_pid
                and process["CommandLine"] == command_line
                and _windows_process(pid) == process):
            subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], capture_output=True, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    else:
        try:
            details = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            if int(details[1]) == supervisor_pid and int(details[2]) == pid:
                os.killpg(pid, signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            return


def terminate_worker(run_meta: dict | int, status: str = "timeout", *, wait_seconds: float = 12) -> bool:
    """Ask the supervisor to stop the owned tree and confirm its exit."""
    if status not in STOP_ACTIONS:
        raise ValueError("termination action must be timeout, stalled or cancelled")
    if type(run_meta) is int:
        run_meta = (_LOCAL_RUNS.get(run_meta) or _live_run_for_pid(run_meta)) if run_meta > 1 else None
        if run_meta is None:
            return False
    exit_path = Path(run_meta["exit_path"])
    if not exit_path.is_file() and _tree_stopped(run_meta):
        _LOCAL_RUNS.pop(run_meta["pid"], None)
        return True
    if not exit_path.is_file():
        stop = Path(run_meta["stop_path"])
        if not stop.is_file():
            write_json(stop, {"status": status, "requested_at": utc_now()})
        deadline = time.monotonic() + wait_seconds
        while not exit_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not exit_path.is_file():
            _stop_live_child(run_meta)
            deadline = time.monotonic() + min(wait_seconds, 2)
            while not exit_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.1)
    confirmed = _exit_confirmed(_read_exit(run_meta)) or _tree_stopped(run_meta)
    if confirmed:
        _LOCAL_RUNS.pop(run_meta["pid"], None)
    return confirmed


def _events(events_path: Path):
    if not events_path.is_file():
        return
    with events_path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def parse_thread_id(events_path: Path | str) -> str | None:
    for event in _events(Path(events_path)):
        thread_id = event.get("thread_id")
        if event.get("type") == "thread.started" and _valid_session(thread_id):
            return thread_id
    return None


def _result_matches(value, schema: dict) -> bool:
    expected = {"object": dict, "array": list, "string": str, "integer": int}[schema["type"]]
    if type(value) is not expected or ("enum" in schema and value not in schema["enum"]):
        return False
    if expected is dict:
        return set(value) == set(schema["required"]) and all(
            _result_matches(item, schema["properties"][name]) for name, item in value.items()
        )
    if expected is list:
        return all(_result_matches(item, schema["items"]) for item in value)
    return expected is not str or schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value))


def _shell_body(command: str) -> str:
    wrapper = re.fullmatch(
        r'''(?is)("[^"\n]+"|\S+) +(?:(?:-nologo|-noprofile|-noninteractive|-l) +)*(?:-command|-lc|-c) +(["'])(.*)\2''',
        command.strip(),
    )
    if wrapper is None:
        return command.strip()
    shell = wrapper.group(1).strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if shell not in {"pwsh", "powershell", "bash", "sh", "zsh"}:
        return command.strip()
    body = wrapper.group(3).strip()
    if wrapper.group(2) == '"':
        return body.replace(r'\"', '"')
    return body.replace("''", "'") if shell in {"pwsh", "powershell"} else body.replace("'\\''", "'")


def _verification(checks: list[str], reported: list[dict], events_path: Path) -> list[dict]:
    observed = {}
    for event in _events(events_path):
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "command_execution":
            command, code = item.get("command"), item.get("exit_code")
            if isinstance(command, str) and type(code) is int:
                observed[command.strip()] = item
                observed[_shell_body(command)] = item
    reported_by_command = {item["command"].strip(): item for item in reported}
    results = []
    for check in checks:
        command = check.strip()
        item = reported_by_command.get(command, {})
        event = observed.get(command, {})
        code = event.get("exit_code")
        results.append({
            "command": check, "exit_code": code, "reported_exit_code": item.get("exit_code"),
            "event_item_id": event.get("id"), "event_command": event.get("command"),
            "summary": item.get("summary", ""),
            "passed": code == 0 and item.get("exit_code") == 0 and event.get("status") in {None, "completed"},
        })
    return results


def _diff_stat(root: Path, changed: list[str], current: dict, baseline: dict) -> str:
    tracked = [name for name in changed if (current.get(name) or baseline[name])[0] != "??"]
    lines = [_git(root, "diff", "--no-ext-diff", "--stat", "HEAD", "--", *tracked).strip()] if tracked else []
    lines.extend(f"{name} | untracked" for name in changed if name not in tracked)
    return "\n".join(filter(None, lines))


def _receipt_payload(full: dict) -> str:
    def encode(value):
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"

    data = full.copy()
    rendered = encode(data)
    if len(rendered) <= MAX_RECEIPT_BYTES:
        return rendered
    list_fields = ("precheck_errors", "verification_results", "git_changed_files", "artifacts_produced")
    for key in list_fields:
        data[key] = []
    data["git_diff_stat"] = ""
    summary_note = "Full evidence in worker-manifest.json."
    data["codex_final_summary"] = summary_note
    for key in list_fields:
        for value in full[key]:
            data[key].append(value)
            if len(encode(data)) > MAX_RECEIPT_BYTES:
                data[key].pop()
                break
    remaining = MAX_RECEIPT_BYTES - len(encode(data))
    snippet = (" " + full["codex_final_summary"])[:max(0, remaining)]
    while snippet and len(encode(snippet)) - len(encode("")) > remaining:
        snippet = snippet[:len(snippet) // 2]
    data["codex_final_summary"] += snippet
    rendered = encode(data)
    if len(rendered) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt cannot fit within 4096 bytes")
    return rendered


def _publish_receipt(archive: Path, latest: Path, attempt: int, payload: str) -> None:
    if len(payload.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt exceeds 4096 bytes")
    if not archive.is_file():
        atomic_write(archive, payload)
    if not latest.is_file() or read_json(latest)["attempt"] <= attempt:
        atomic_write(latest, payload)


def finalize_and_precheck(cfg: Config, order: WorkOrder, run_meta: dict) -> DeliveryReceipt:
    """Archive a machine receipt using the supervisor exit and the current scoped Git delta."""
    attempt = run_meta["attempt"]
    if run_meta["order_id"] != order.order_id:
        raise ValueError("run metadata does not match work order")
    folder = _attempt_dir(cfg, order, attempt)
    order_dir = folder.parents[1]
    archive = folder / "receipt.json"
    latest = order_dir / "receipt.json"
    if archive.is_file():
        payload = archive.read_text(encoding="utf-8")
        _publish_receipt(archive, latest, attempt, payload)
        return DeliveryReceipt.from_dict(json.loads(payload))

    override = run_meta.get("status_override")
    if override is not None and override not in STOP_STATUSES:
        raise ValueError("status_override must be timeout or stalled")
    record = _read_exit(run_meta)
    if not _exit_confirmed(record) and not _tree_stopped(run_meta):
        raise RuntimeError("supervisor or worker tree has not exited")
    status = override or record.get("status")
    errors = []
    manifest_errors = []
    if not record:
        manifest_errors.append("supervisor exit record missing; process tree confirmed stopped")
    elif type(record.get("exit_code")) is not int:
        manifest_errors.append("no confirmed Codex exit")
    if status == "cancelled":
        manifest_errors.append("worker was cancelled")
    if record.get("error"):
        errors.append(record["error"])
    if record.get("exit_code") != 0:
        errors.append(f"Codex exit code: {record.get('exit_code')}")
    if status:
        errors.append(f"worker status: {status}")

    result = {}
    try:
        candidate = read_json(Path(run_meta["last_msg_path"]))
        if not _result_matches(candidate, read_json(PROMPTS / "order_result.schema.json")):
            raise ValueError("does not match order_result.schema.json")
        if candidate["order_id"] != order.order_id:
            raise ValueError("unexpected order_id")
        result = candidate
    except (OSError, ValueError) as exc:
        manifest_errors.append(f"invalid final result: {exc}")
    if result and result["outcome"] != "completed":
        errors.append(f"Codex outcome: {result['outcome']}")
    if result.get("blockers"):
        errors.append("Codex reported blockers")

    events_path = Path(run_meta["events_path"])
    verification = _verification(order.acceptance_checks, result.get("commands_run", []), events_path)
    errors.extend(f"acceptance check failed or unverified: {item['command']}" for item in verification if not item["passed"])
    root = cfg.repo_root.resolve()
    baseline = read_json(order_dir / "git-baseline.json")
    if _head(root) != baseline["head"] or order.to_dict() != baseline["order"]:
        manifest_errors.append("work order or repository HEAD changed since launch")
    before = baseline["files"]
    current = _snapshot(root)
    changed = sorted(name for name in before.keys() | current.keys() if before.get(name) != current.get(name))
    for name in changed:
        if name in before:
            manifest_errors.append(f"preexisting worktree or index change was touched: {name}")
        entry = current.get(name)
        if entry and (entry[0][0] not in {" ", "?"} or entry[0] == " A"):
            manifest_errors.append(f"worker changed the index: {name}")
        if entry and any(value.startswith(("120000 ", "160000 ")) for value in entry[1]):
            manifest_errors.append(f"Git link or submodule: {name}")
        issue = _path_error(root, name, order.allowed_paths, ssh_target=cfg.server_ssh_target)
        if issue:
            manifest_errors.append(f"{name}: {issue}")
    if result and {name.replace("\\", "/") for name in result["changed_files"]} != set(changed):
        manifest_errors.append("reported changed_files do not match the Git delta from dispatch")
    artifacts = result.get("artifacts_produced", [])
    for artifact in artifacts:
        issue = _path_error(root, artifact.replace("\\", "/"), order.allowed_paths, must_exist=True, ssh_target=cfg.server_ssh_target)
        if issue:
            manifest_errors.append(f"artifact {artifact}: {issue}")

    errors.extend(manifest_errors)
    finished = record.get("finished_at", utc_now())
    duration = (parse_time(finished) - parse_time(run_meta["started_at"])).total_seconds()
    session = parse_thread_id(events_path)
    if session is None and not record.get("resume_fallback") and not record.get("exit_code"):
        previous_session = run_meta.get("codex_session_id")
        session = previous_session if _valid_session(previous_session) else None
    receipt = DeliveryReceipt(
        order_id=order.order_id, attempt=attempt, exit_code=record.get("exit_code"),
        codex_session_id=session,
        status=status if status in STOP_STATUSES else ("failed" if errors else "passed"),
        duration_seconds=max(0, record.get("duration_seconds", duration)), git_changed_files=changed,
        git_diff_stat=_diff_stat(root, changed, current, before), verification_results=verification,
        artifacts_produced=artifacts, codex_final_summary=result.get("summary", ""),
        precheck_passed=not errors, precheck_errors=errors, generated_at=utc_now(),
    )
    full = receipt.to_dict()
    write_json(folder / "worker-manifest.json", {
        "pid": run_meta["pid"], "order_id": order.order_id, "attempt": attempt,
        "errors": manifest_errors, "files": {name: current.get(name) for name in changed}, "receipt": full,
    })
    payload = _receipt_payload(full)
    _publish_receipt(archive, latest, attempt, payload)
    _LOCAL_RUNS.pop(run_meta["pid"], None)
    return DeliveryReceipt.from_dict(json.loads(payload))


def commit_paths(cfg: Config, order: WorkOrder, run_meta: dict, receipt: DeliveryReceipt) -> list[str]:
    """Revalidate paths for a literal, path-limited commit. The caller handles acceptance status."""
    if receipt.order_id != order.order_id or run_meta["order_id"] != order.order_id or run_meta["attempt"] != receipt.attempt:
        raise ValueError("receipt, work order and attempt do not match")
    folder = _attempt_dir(cfg, order, receipt.attempt)
    order_dir = folder.parents[1]
    if (folder.parent / str(receipt.attempt + 1) / "run.json").is_file():
        raise ValueError("a later worker attempt was launched")
    if any(receipt.to_dict() != read_json(path) for path in (order_dir / "receipt.json", folder / "receipt.json")):
        raise ValueError("receipt is not the latest recorded receipt")
    manifest = read_json(folder / "worker-manifest.json")
    if any(manifest[key] != run_meta[key] for key in ("order_id", "attempt", "pid")):
        raise ValueError("manifest does not match the worker attempt")
    if json.loads(_receipt_payload(manifest["receipt"])) != receipt.to_dict():
        raise ValueError("manifest does not match finalized receipt")
    if manifest["errors"]:
        raise ValueError("worker manifest is blocked: " + " | ".join(manifest["errors"]))
    baseline = read_json(order_dir / "git-baseline.json")
    root = cfg.repo_root.resolve()
    branch = _git(root, "branch", "--show-current").strip()
    if not branch or branch.casefold() in {"main", "master"} or branch != cfg.branch_name:
        raise ValueError("repository is not on the configured work branch")
    if baseline["order"] != order.to_dict() or baseline["head"] != _head(root):
        raise ValueError("work order or repository HEAD changed after dispatch")
    approved = manifest["files"]
    current = _snapshot(root)
    names = sorted(approved)
    if names != sorted(manifest["receipt"]["git_changed_files"]) or set(names) & baseline["files"].keys():
        raise ValueError("receipt contains an unapproved or preexisting path")
    for name in names:
        issue = _path_error(root, name, order.allowed_paths, ssh_target=cfg.server_ssh_target)
        entry = current.get(name)
        if issue or entry is None or entry != approved[name]:
            raise ValueError(f"approved path failed revalidation: {name}: {issue or 'Git state changed'}")
    for artifact in manifest["receipt"]["artifacts_produced"]:
        issue = _path_error(root, artifact.replace("\\", "/"), order.allowed_paths, must_exist=True, ssh_target=cfg.server_ssh_target)
        if issue:
            raise ValueError(f"artifact {artifact}: {issue}")
    return names


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--supervise":
        raise SystemExit("codex_runner.py is an internal worker supervisor")
    _supervise(Path(sys.argv[2]))
