"""Persistent submission intents above the existing TCAD/transport runners.

This module owns no scientific ledger, remote lock, execution shell, or solver.
The caller holds the controller lifecycle lock. Original manifests and verified
collection receipts remain authoritative; an uncertain launch is never replayed.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid


_watchdog_spec = importlib.util.spec_from_file_location("tcad_progress_watchdog", Path(__file__).with_name("watchdog.py"))
watchdog = importlib.util.module_from_spec(_watchdog_spec)
_watchdog_spec.loader.exec_module(watchdog)
_pool_spec = importlib.util.spec_from_file_location("tcad_scheduler_pool", Path(__file__).with_name("scheduler_pool.py"))
scheduler_pool = importlib.util.module_from_spec(_pool_spec)
_pool_spec.loader.exec_module(scheduler_pool)


QUEUE_SCHEMA = "tcad-work-items-v1"
STATE_SCHEMA = "tcad-autonomy-intents-v1"
TCAD_RUNNER = "scripts/tcad.py"
TRANSPORT_RUNNER = "experiments/dram-see-v4/transport-probe/operation.py"
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,95}\Z")
TERMINAL = {"COLLECTED", "FAILED_COLLECTED", "COLLECTED_PENDING_AUDIT",
            "INTERRUPTED_COLLECTED"}
SUCCESS = {"COLLECTED", "COLLECTED_PENDING_AUDIT"}
CONNECTION_KEYS = ("backend", "ssh_target", "runtime_entry", "remote_root")


LEGACY_MULTICORE_LAYOUTS = {
    (4, ((0, 1), (2, 3), (4, 5), (6, 7))): "tcad-shared-gate-slots-r4",
    (2, ((0, 1, 2, 3), (4, 5, 6, 7))): "tcad-shared-gate-slots-r5",
    (5, ((0, 1), (2, 3), (4, 5), (6, 7), (8, 9))): "tcad-shared-gate-slots-r6",
    (8, ((0,), (1,), (2,), (3,), (4,), (5,), (6, 7), (8, 9))): "tcad-shared-gate-slots-r7",
    (10, tuple((cpu,) for cpu in range(10))): "tcad-shared-gate-slots-r8",
    (1, (tuple(range(10)),)): "tcad-shared-gate-slots-r9",
}
DYNAMIC_SLOTS_SCHEMA = "tcad-shared-gate-slots-v2"
PREFLIGHT_EXIT_CODE = 75


def resolve_ref_path(ref):
    """Accept an absolute path string or legacy {path, sha256?} dict."""
    raw = ref if isinstance(ref, str) else ref.get("path") if isinstance(ref, dict) else None
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise ValueError("Expected an absolute config file path")
    path = Path(raw)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Referenced config file is missing or symlinked: " + raw)
    return path.resolve()


def profile_resources(cfg):
    """Mirror the original runner's resource contract; data-driven for any valid cpu_sets."""
    if not isinstance(cfg, dict):
        raise ValueError("Connection profile must be an object")
    capacity = cfg.get("parallel_capacity", 3)
    if "cpu_sets" in cfg:
        if type(capacity) is not int or not 1 <= capacity <= 64:
            raise ValueError("Unsupported parallel_capacity for cpu_sets profile")
        groups = cfg.get("cpu_sets")
        if not isinstance(groups, list) or len(groups) != capacity:
            raise ValueError("cpu_sets length must match parallel_capacity")
        seen = set()
        widths = []
        for group in groups:
            if (not isinstance(group, list) or not group
                    or any(type(cpu) is not int or not 0 <= cpu <= 4095 for cpu in group)
                    or group != sorted(set(group))):
                raise ValueError("Each cpu_set must be a sorted non-empty list of unique CPU IDs")
            for cpu in group:
                if cpu in seen:
                    raise ValueError("Overlapping CPU across slots: " + str(cpu))
                seen.add(cpu)
            widths.append(len(group))
        configured = cfg.get("requested_threads")
        if configured is not None:
            if type(configured) is int:
                if len(set(widths)) != 1 or configured != widths[0]:
                    raise ValueError("Scalar requested_threads must match uniform cpu_sets width")
            elif isinstance(configured, list):
                if len(configured) != len(widths) or any(type(t) is not int or t != w for t, w in zip(configured, widths)):
                    raise ValueError("Per-slot requested_threads must match cpu_sets widths")
            else:
                raise ValueError("Invalid requested_threads")
        key = (capacity, tuple(tuple(group) for group in groups))
        schema = LEGACY_MULTICORE_LAYOUTS.get(key, DYNAMIC_SLOTS_SCHEMA)
        req_threads = widths[0] if len(set(widths)) == 1 else widths
        return {
            "schema": schema,
            "capacity": capacity,
            "cpu_sets": [list(group) for group in groups],
            "requested_threads": req_threads,
        }
    if "requested_threads" in cfg:
        raise ValueError("Legacy single-core profiles cannot reinterpret resource fields")
    if type(capacity) is not int or capacity not in (3, 7, 9):
        raise ValueError("Unsupported original shared pool capacity")
    return {
        "schema": {3: "tcad-shared-gate-slots-r1", 7: "tcad-shared-gate-slots-r2",
                   9: "tcad-shared-gate-slots-r3"}[capacity],
        "capacity": capacity,
        "cpu_sets": [[slot] for slot in range(capacity)],
        "requested_threads": 1,
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def transport_profile(policy, ready, primary):
    """An optional, explicitly configured single-thread profile for the SAME pool."""
    selected, pinned = policy.get("transport_connection_file"), ready.get("transport_connection")
    if selected is None and pinned is None:
        return None
    if selected is None or pinned is None:
        raise ValueError("transport_connection_file requires matching readiness.transport_connection")
    path = resolve_ref_path(selected)
    ready_path = resolve_ref_path(pinned)
    if path != ready_path:
        raise ValueError("transport_connection_file must resolve to the same path as readiness.transport_connection")
    cfg = read_json(path)
    resources = profile_resources(cfg)
    if ({key: cfg.get(key) for key in CONNECTION_KEYS} !=
            {key: primary.get(key) for key in CONNECTION_KEYS}
            or Path(cfg["local_state_root"]).resolve() != Path(primary["local_state_root"]).resolve()):
        raise ValueError("Transport profile must retain the same original connection identity, state root and shared pool")
    if "cpu_sets" in cfg or resources["requested_threads"] != 1:
        raise ValueError("Transport profile must use the original single-thread resource contract")
    primary_capacity = profile_resources(primary)["capacity"]
    if policy["max_parallel_jobs"] > max(primary_capacity, resources["capacity"]):
        raise ValueError("Backend profile scheduling exceeds configured pool capacity")
    limit = policy.get("transport_max_parallel_jobs", policy["max_parallel_jobs"])
    if type(limit) is not int or not 1 <= limit <= min(policy["max_parallel_jobs"], resources["capacity"]):
        raise ValueError("Transport parallel limit must fit the original profile and global limit")
    return {"connection": {"path": str(path), "sha256": file_digest(path)},
            "cfg": cfg, "resources": resources, "limit": limit}


def write_json(path, value):
    """Durable pre-launch intent; never leave a partially written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(10):
            try:os.replace(temporary,path);break
            except PermissionError as exc:
                if os.name!='nt' or getattr(exc,'winerror',None) not in (5,32) or attempt==9:raise
                time.sleep(.001*(attempt+1))
        if os.name != "nt":
            descriptor = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


class Runtime:
    def __init__(self, policy, ready):
        self.policy = policy
        self.ready = ready
        self.workspace = Path(policy["workspace"]).resolve()
        self.state_dir = Path(policy["state_dir"]).resolve()
        self.queue_file = Path(policy["queue_file"]).resolve()
        if not self.queue_file.is_relative_to(self.workspace):
            raise ValueError("queue_file must be inside the workspace")
        if self.state_dir.is_relative_to(self.workspace):
            raise ValueError("Runtime state_dir must be outside the mutable research workspace")
        self.path = self.state_dir / "runtime.json"
        self.python = str(policy["runner_python"])
        self.capacity = int(policy["max_parallel_jobs"])
        if not 1 <= self.capacity <= 64:
            raise ValueError("max_parallel_jobs must be between 1 and 64")
        self.timeout = float(policy.get("runner_timeout_seconds", 60))
        self.repair_limit = int(policy.get("repair_attempt_limit", 2))
        self.backoff = float(policy.get("failure_backoff_seconds", 300))
        self.max_backoff = float(policy.get("max_failure_backoff_seconds", 3600))
        if self.timeout <= 0 or self.repair_limit < 0 or self.backoff < 0 or self.max_backoff < self.backoff:
            raise ValueError("Invalid timeout or repair/backoff policy")
        self.state = read_json(self.path) if self.path.exists() else {
            "schema": STATE_SCHEMA, "intents": {}}
        if self.state.get("schema") != STATE_SCHEMA or not isinstance(self.state.get("intents"), dict):
            raise ValueError("Unsupported or invalid runtime intent file")
        self.intents = self.state["intents"]
        self._archive_cache = {}
        self._input_cache = {}
        self._retention_process = None
        self._retention_retry_at = 0
        self._offload_process = None
        self._offload_retry_at = 0
        self.can_submit = lambda: True

    def _save(self):
        write_json(self.path, self.state)

    def _profile(self):
        path = resolve_ref_path(self.ready["connection"])
        cfg = read_json(path)
        if cfg.get("backend") != "ssh-runtime":
            raise ValueError("Autonomous submission requires an explicit ssh-runtime profile")
        root = Path(cfg["local_state_root"]).resolve()
        allowed = (self.workspace / "local_runtime/cloud-benchmark").resolve()
        if root == allowed or not root.is_relative_to(allowed):
            raise ValueError("Runner state root must be below local_runtime/cloud-benchmark")
        self.connection = {"path": str(path), "sha256": file_digest(path)}
        self.identity = {key: cfg[key] for key in CONNECTION_KEYS}
        self.original_root = root
        self.cloud_root = allowed
        self.cfg = cfg
        self.resources = profile_resources(cfg)
        self.slots = self.resources["capacity"]
        if self.capacity > self.slots:
            raise ValueError("Parallel limit exceeds the original runner profile capacity")
        self.limit = self.capacity
        primary = {"connection": self.connection, "cfg": cfg, "resources": self.resources}
        self.transport = transport_profile(self.policy, self.ready, cfg)
        self.profiles = {"tcad": primary, "geant4": self.transport or primary}

    def _slot_resources(self, slot, cfg=None):
        resources = self.resources if cfg is None else profile_resources(cfg)
        cpu_set = list(resources["cpu_sets"][slot])
        return {"schema": resources["schema"], "capacity": resources["capacity"],
                "cpu_set": cpu_set,
                "requested_threads": len(cpu_set)}

    def _intent_profile(self, intent):
        """Configured original profiles may recover; other history is read-only."""
        intent_path = resolve_ref_path(intent["connection"])
        for profile in self.profiles.values():
            if intent_path == Path(profile["connection"]["path"]).resolve():
                return profile["cfg"]
        cfg = read_json(intent_path)
        identity = {key: cfg[key] for key in self.identity}
        if identity != self.identity or Path(cfg["local_state_root"]).resolve() != self.original_root:
            raise ValueError("Historical intent belongs to a different identity or state root")
        profile_resources(cfg)
        return cfg

    def _configured_intent(self, intent):
        try:
            intent_path = resolve_ref_path(intent["connection"])
        except ValueError:
            return False
        return any(intent_path == Path(profile["connection"]["path"]).resolve()
                   for profile in self.profiles.values())

    def _match_profile(self, backend, run_id, record, path):
        """Match frozen policies, including old TCAD runs on the transport profile."""
        for profile in self.profiles.values():
            try:
                self._validate_record(backend, run_id, record, path, profile["cfg"])
                return profile
            except (ValueError, KeyError, TypeError):
                pass
        raise ValueError("Original record does not match any explicitly configured pool profile")

    def _relative_path(self, value):
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ValueError("Expected a nonempty workspace-relative path")
        raw = self.workspace / value
        if ".." in Path(value).parts:
            raise ValueError("Parent traversal is not allowed")
        candidate = raw.resolve()
        if candidate == self.workspace or not candidate.is_relative_to(self.workspace):
            raise ValueError("Path escapes workspace")
        current = raw
        while current != self.workspace:
            if current.is_symlink():
                raise ValueError("Input symlinks are not allowed")
            current = current.parent
        return candidate

    def _load_tasks(self):
        if not self.queue_file.exists():
            return {}, [{"id": None, "reason": "queue_missing"}]
        try:
            data = read_json(self.queue_file)
            if data.get("schema") != QUEUE_SCHEMA or not isinstance(data.get("tasks"), list):
                raise ValueError("Expected tcad-work-items-v1 with tasks array")
        except (OSError, ValueError, AttributeError) as exc:
            return {}, [{"id": None, "reason": "invalid_queue", "detail": str(exc)}]
        return self._parse_tasks(data["tasks"])

    def _parse_tasks(self, proposals):
        tasks, errors, duplicates = {}, [], set()
        for proposal in proposals:
            task_id = proposal.get("id") if isinstance(proposal, dict) else None
            try:
                if not isinstance(task_id, str) or not ID_PATTERN.fullmatch(task_id):
                    raise ValueError("Task ID must use lowercase letters, digits and hyphens")
                if task_id in tasks or task_id in duplicates:
                    duplicates.add(task_id)
                    tasks.pop(task_id, None)
                    raise ValueError("Duplicate task ID")
                if proposal.get("backend") not in ("tcad", "geant4"):
                    raise ValueError("backend must be tcad or geant4")
                project = self._relative_path(proposal.get("project"))
                deps, requires = proposal.get("depends_on", []), proposal.get("requires", [])
                if not isinstance(deps, list) or any(not isinstance(v, str) for v in deps):
                    raise ValueError("depends_on must be an array of task IDs")
                if not isinstance(requires, list):
                    raise ValueError("requires must be an array of workspace-relative paths")
                for item in requires:
                    self._relative_path(item)
                parent = proposal.get("repair_of")
                if parent is not None and (not isinstance(parent, str) or parent == task_id):
                    raise ValueError("repair_of must name a different task")
                reason = proposal.get("repair_reason", "")
                if not isinstance(reason, str) or (parent and not reason.strip()):
                    raise ValueError("Repairs require a nonempty repair_reason")
                adopted = proposal.get("adopt_run_id")
                if adopted is not None and (not isinstance(adopted, str) or
                                             not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", adopted)):
                    raise ValueError("Invalid original adopt_run_id")
                if adopted and proposal["backend"] == "geant4" and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", adopted):
                    raise ValueError("Transport label must use lowercase letters, digits and hyphens")
                task = {key: proposal[key] for key in ("id", "backend", "project")}
                task.update(depends_on=deps, requires=requires, repair_of=parent,
                            repair_reason=reason, adopt_run_id=adopted)
                task["project"] = project.relative_to(self.workspace).as_posix()
                if 'wave_admission_sha256' in proposal:
                    value = proposal['wave_admission_sha256']
                    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) or 'scientific_gate' not in self.policy:
                        raise ValueError('Wave task requires a pinned scientific admission')
                    task['wave_admission_sha256'] = value
                if 'supply_input_digest' in proposal:
                    value = proposal['supply_input_digest']
                    if not task_id.startswith('raw-dev-') or not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
                        raise ValueError('Invalid staged raw development input digest')
                    task['supply_input_digest'] = value
                if "priority" in proposal:
                    if type(proposal["priority"]) is not int:
                        raise ValueError("priority must be an integer; smaller values run first")
                    task["priority"] = proposal["priority"]
                tasks[task_id] = task
            except (ValueError, TypeError) as exc:
                errors.append({"id": task_id, "reason": "invalid_task", "detail": str(exc)})
        return tasks, errors

    def _dependency_errors(self, tasks):
        errors, visiting, visited = {}, set(), set()

        def visit(task_id):
            if task_id in visited or task_id not in tasks:
                return
            if task_id in visiting:
                errors[task_id] = "dependency_cycle"
                return
            visiting.add(task_id)
            for dependency in tasks[task_id]["depends_on"]:
                if dependency not in tasks and dependency not in self.intents:
                    errors[task_id] = "unknown_dependency"
                visit(dependency)
                if errors.get(dependency) == "dependency_cycle":
                    errors[task_id] = "dependency_cycle"
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in tasks:
            visit(task_id)
        return errors

    def _manifest_path(self, backend, run_id, root=None):
        root = self.original_root if root is None else root
        if backend == "tcad":
            return root / "runs" / run_id / "manifest.json"
        return root / "dram-see-v4/transport-probe/operations" / run_id / "operation.json"

    def _validate_record(self, backend, run_id, record, path, cfg=None):
        resources = self.resources if cfg is None else profile_resources(cfg)
        expected_schema = ("tcad-native-run-r2" if backend == "tcad"
                           else "dram-see-v4-transport-operation-v2")
        if record.get("schema") != expected_schema:
            raise ValueError("Original record requires its historical recovery path")
        if record.get("connection_identity") != self.identity:
            raise ValueError("Original record belongs to a different connection identity")
        if record.get("run_id" if backend == "tcad" else "label") != run_id:
            raise ValueError("Original record ID differs")
        base = self.identity["remote_root"].rstrip("/")
        if backend == "tcad":
            if record.get("remote_layout"):
                if (record["remote_layout"] != "tcad-data-root-layout-r1"
                        or record.get("control_root") != self.identity["remote_root"]
                        or record.get("shared_lock_path") != base + "/.solver.lock"
                        or not re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)+", record.get("data_root", ""))):
                    raise ValueError("Unsupported original data-root binding")
                base = record["data_root"]
            expected = base + "/runs/" + run_id
        else:
            expected = base + "/dram-see-v4/transport-probe/operations/" + run_id
        if record.get("remote_directory") != expected:
            raise ValueError("Original remote directory differs")
        active_cfg = self.cfg if cfg is None else cfg
        is_mc = "cpu_sets" in active_cfg
        policy = record.get("parallel_policy")
        if is_mc and (backend != "tcad" or not policy):
            raise ValueError("Multicore shared pool requires a TCAD parallel run")
        if policy:
            if not isinstance(policy, dict):
                raise ValueError("Invalid original parallel policy")
            capacity = resources["capacity"]
            slot = policy.get("slot")
            if type(slot) is not int or not 0 <= slot < capacity:
                raise ValueError("Original slot is outside the pinned pool")
            expected_policy = {
                "schema": resources["schema"],
                "slot": slot, "pool_root": self.identity["remote_root"],
                "connection_identity": self.identity, "work_id": run_id,
                "remote_directory": expected, "kind": "run" if backend == "tcad" else "operation"}
            if capacity != 3 or is_mc:
                expected_policy["capacity"] = capacity
            if is_mc:
                if expected != self.identity["remote_root"].rstrip("/") + "/runs/" + run_id:
                    raise ValueError("Multicore run must retain the original control-root layout")
                cpu_set = resources["cpu_sets"][slot]
                expected_policy.update(cpu_set=cpu_set, requested_threads=len(cpu_set))
                if resources["schema"] == DYNAMIC_SLOTS_SCHEMA:
                    expected_policy["cpu_sets"] = resources["cpu_sets"]
            else:
                expected_policy["cpu"] = slot
            if digest(policy) != digest(expected_policy):
                raise ValueError("Original slot/CPU/pool policy differs from the pinned profile")
        if path.is_symlink() or not path.resolve().is_relative_to(self.cloud_root):
            raise ValueError("Unsafe original record path")
        return record

    def _record(self, intent):
        cfg = self._intent_profile(intent)
        historical = not self._configured_intent(intent)
        path = self._manifest_path(intent["backend"], intent["run_id"])
        if not path.exists():
            return None
        record = self._validate_record(intent["backend"], intent["run_id"], read_json(path), path, cfg)
        slot = (record.get("parallel_policy") or {}).get("slot")
        if slot != intent["slot"]:
            raise ValueError("Original slot differs from persisted submission intent")
        source = record.get("project_directory" if intent["backend"] == "tcad" else "input_directory")
        if not source or Path(source).resolve() != self._relative_path(intent["project"]):
            raise ValueError("Original input directory differs from pre-launch intent")
        # The original runner may generate admitted geometry binding files before
        # freezing inputs. Preserve both hashes, but do not replace its admission
        # with an equality gate against this earlier scheduling snapshot.
        if not isinstance(record.get("input_sha256"), dict):
            raise ValueError("Original input snapshot is missing")
        if "requested_resources" in intent and digest(intent["requested_resources"]) != digest(
                self._slot_resources(slot, cfg)):
            raise ValueError("Original resources differ from persisted submission intent")
        if historical and (record.get("parallel_slot_released") is not True or not self._receipt(intent, record)):
            raise ValueError("Historical profile run requires a verified released collection; recover with its original profile before switching an idle pool")
        return record

    def _receipt(self, intent, record, manifest_path=None):
        if record.get("state") not in TERMINAL or record.get("collection_verified") is not True:
            return False
        expected = record.get("results_sha256" if intent["backend"] == "tcad" else "archive_sha256")
        original = manifest_path or self._manifest_path(intent["backend"], intent["run_id"])
        path = original.parent / "results.tar"
        if not expected or path.is_symlink():
            return False
        if not path.is_file():
            if intent["backend"] != "tcad":
                return False
            try:
                return self._retention_module().verify_retained(path.parent, record, self._archive_cache)
            except (OSError, ValueError, TypeError, KeyError):
                return False
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, expected)
        if key not in self._archive_cache:
            stamp=(str(path),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,expected)
            token=digest(stamp);memo_path=self.state_dir/'verified-archives.json'
            try:memo=read_json(memo_path) if memo_path.is_file() and not memo_path.is_symlink() else {}
            except (OSError,ValueError):memo={}
            entries=memo.get('verified',{}) if isinstance(memo,dict) and memo.get('schema')=='tcad-verified-archives-v1' else {}
            if not isinstance(entries,dict):entries={}
            if entries.get(token)==expected:
                self._archive_cache[key]=True
            else:
                verified=file_digest(path)==expected
                after=path.stat()
                verified=verified and stamp[1:6]==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                self._archive_cache[key]=verified
                if verified and not getattr(self,'read_only',False):
                    entries[token]=expected
                    write_json(memo_path,{'schema':'tcad-verified-archives-v1','verified':dict(list(entries.items())[-4096:])})
        return self._archive_cache[key]

    def _unlaunched(self, backend, record, path, cfg):
        """An independently verified no-launch failure is not a collection."""
        if backend != "geant4" or record.get("state") != "FAILED_BEFORE_LAUNCH":
            return False
        if not (path.parent / "launch-reconciliation.json").exists():
            return False
        source = self.workspace / "experiments/dram-see-v4/transport-probe/launch_reconciliation.py"
        if source.is_symlink() or not source.is_file():
            raise ValueError("Missing original unlaunched-receipt verifier")
        spec = importlib.util.spec_from_file_location("_original_launch_reconciliation", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.verified_unlaunched_receipt(cfg, record, path.parent)

    def _scientific_admission(self, task, inputs=None):
        # A new development deck can be run for raw data, without declaring a
        # formal case or writing a scientific admission. Never reinterpret an
        # existing proposal, repair, transport request or holdout as raw work.
        if task['id'].startswith('raw-dev-'):
            expected = 'local_runtime/raw-development/' + task['id']
            if (task['backend'] != 'tcad' or task['project'] != expected
                    or task.get('adopt_run_id') or task.get('repair_of')
                    or 'wave_admission_sha256' in task):
                raise ValueError('Raw development requires its own new TCAD task and input directory')
            original, comparison = self._inputs(task)
            if 'supply_input_digest' in task and task['supply_input_digest'] != digest(original):
                raise ValueError('Raw development inputs differ from approved supply')
            if not original or (inputs is not None and inputs != original):
                raise ValueError('Raw development inputs changed before submission')
            if any(v.get('input_digest') == comparison or v.get('input_sha256') == original
                   or v.get('project') == expected for v in self.intents.values()):
                raise ValueError('Raw development input already has an original intent')
            return {'scope': 'raw_development', 'input_digest': comparison,
                    'statistics_eligible': False, 'training_eligible': False}
        if "scientific_gate" not in self.policy:
            return None
        source = Path(__file__).with_name("r06_gate.py")
        spec = importlib.util.spec_from_file_location("_tcad_r06_scientific_gate", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.verify(self.workspace, self.policy, task, inputs, self.intents)

    @staticmethod
    def _retention_module():
        source = Path(__file__).with_name("retention.py")
        spec = importlib.util.spec_from_file_location("_tcad_result_retention", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _maintain_results(self, views):
        """One storage worker; only explicitly consumed, released successes qualify."""
        if self.policy.get("result_retention_enabled") is not True or not self.can_submit():
            return
        if self._retention_process is not None:
            if self._retention_process.poll() is None:
                return
            self._retention_process = None
            self._retention_retry_at = time.time() + 60
        if time.time() < self._retention_retry_at:
            return
        for task_id, view in views.items():
            if view.get("backend") != "tcad" or not view.get("collected") or not view.get("success"):
                continue
            intent = self.intents[task_id]
            folder = self._manifest_path("tcad", intent["run_id"]).parent
            if not (folder / "retention-ready.json").is_file():
                continue
            if (folder / "retention.json").is_file() and (folder / "guest-reclaim.json").is_file():
                continue
            worker = Path(__file__).with_name("result_maintenance.py")
            if not worker.is_file():
                return
            with (self.state_dir / "retention-worker.log").open("ab", buffering=0) as log:
                self._retention_process = subprocess.Popen(
                    [self.python, "-B", str(worker), "maintain", str(folder),
                     "--connection", intent["connection"]["path"]],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    env=self._runner_environment(), start_new_session=True)
            self._retention_retry_at = time.time() + 300
            return

    def _offload_results(self, views):
        """One optional non-blocking Google Drive offload worker; failures fall back to local retention."""
        if self.policy.get("result_gdrive_offload_enabled") is not True or not self.can_submit():
            return
        try:
            if self._offload_process is not None:
                if self._offload_process.poll() is None:
                    return
                self._offload_process = None
                self._offload_retry_at = time.time() + 60
            now = time.time()
            if now < self._offload_retry_at:
                return
            for task_id, view in views.items():
                if view.get("backend") != "tcad" or not view.get("collected") or not view.get("success"):
                    continue
                intent = self.intents[task_id]
                folder = self._manifest_path("tcad", intent["run_id"]).parent
                if not ((folder / "retention.json").is_file() and (folder / "guest-reclaim.json").is_file()):
                    continue
                if not (folder / "results.raw.tar.gz").is_file():
                    continue
                if (folder / "gdrive-offload.json").is_file():
                    continue
                status_file = folder / "gdrive-offload-status.json"
                if status_file.is_file() and not status_file.is_symlink():
                    status = read_json(status_file)
                    if float(status.get("retry_after") or 0) > now:
                        continue
                worker = Path(__file__).with_name("result_maintenance.py")
                if not worker.is_file():
                    return
                argv = [self.python, "-B", str(worker), "offload", str(folder)]
                cfg_path = self.policy.get("result_gdrive_config")
                if isinstance(cfg_path, str) and cfg_path.strip():
                    argv.extend(["--config", cfg_path.strip()])
                argv.append("--delete-local-raw" if self.policy.get("result_gdrive_delete_local_raw") is True else "--keep-local-raw")
                with (self.state_dir / "gdrive-offload-worker.log").open("ab", buffering=0) as log:
                    self._offload_process = subprocess.Popen(
                        argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        env=self._runner_environment(), start_new_session=True)
                self._offload_retry_at = now + 300
                return
        except Exception as exc:
            try:
                with (self.state_dir / "gdrive-offload-worker.log").open("ab", buffering=0) as log:
                    log.write(f"offload scheduling fallback to local retention: {exc}\n".encode("utf-8", errors="replace"))
            except OSError:
                pass
            self._offload_retry_at = time.time() + 300

    def _argv(self, intent, command):
        if not self._configured_intent(intent):
            raise ValueError("Historical profile intents cannot execute through configured profiles")
        intent_path = resolve_ref_path(intent["connection"])
        backend_path = Path(self.profiles[intent["backend"]]["connection"]["path"]).resolve()
        if command == "run" and intent_path != backend_path:
            raise ValueError("New work must use its explicitly configured backend profile")
        script = TCAD_RUNNER if intent["backend"] == "tcad" else TRANSPORT_RUNNER
        result = [self.python, str(self.workspace / script), "--connection", str(intent_path)]
        if command != "run":
            return result + [command, intent["run_id"], "--json"]
        project = str(self.workspace / intent["project"])
        if intent["backend"] == "tcad":
            result += ["run", project, "--run-id", intent["run_id"]]
        else:
            result += [intent["run_id"], project]
        return result + ["--detach", "--parallel-slot", str(intent["slot"])]

    def _confirmed_transport_failure(self, intent, payload):
        """Recognize a completed failed launch, never infer one from CLI status alone."""
        if intent["backend"] != "geant4" or not isinstance(payload, dict):
            return False
        exit_code = payload.get("remote_exit_code")
        if (payload.get("label") != intent["run_id"] or payload.get("status") != "FINISHED"
                or payload.get("alive") is not False or payload.get("local_state") != "EXECUTED"
                or type(exit_code) is not int or not 1 <= exit_code <= 255):
            return False
        try:
            record = self._record(intent)
        except (ValueError, TypeError, OSError, KeyError, AttributeError):
            return False
        if (not record or record.get("state") != "EXECUTED"
                or type(record.get("remote_exit_code")) is not int
                or record["remote_exit_code"] != exit_code
                or payload.get("directory") != record["remote_directory"]):
            return False
        identity, observed = record.get("process_identity"), record.get("last_observation")
        if not isinstance(identity, dict) or not isinstance(observed, dict):
            return False
        return (
            identity.get("schema") == "tcad-process-identity-r1"
            and identity.get("run_id") == intent["run_id"]
            and identity.get("cwd") == record["remote_directory"]
            and isinstance(identity.get("script_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", identity["script_sha256"]) is not None
            and identity["script_sha256"] == record.get("script_sha256")
            and all(type(identity.get(key)) is int and identity[key] > 0
                    for key in ("pid", "start_ticks"))
            and isinstance(identity.get("boot_id"), str)
            and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                             identity["boot_id"]) is not None
            and identity == payload.get("identity") == observed.get("identity")
            and all(observed.get(key) == payload.get(key)
                    for key in ("label", "directory", "status", "alive", "remote_exit_code"))
        )

    def _invoke(self, intent, command):
        """The only execution boundary; fixed script and argv, never shell text."""
        if time.time() < self.state.get("endpoint_next_probe_at", 0):
            return {"ok": False, "kind": "endpoint_unavailable"}
        try:
            result = subprocess.run(self._argv(intent, command), cwd=str(self.workspace),
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=self.timeout,
                                    check=False, shell=False, env=self._runner_environment())
        except subprocess.TimeoutExpired:
            self._delay_endpoint()
            return {"ok": False, "kind": "endpoint_unavailable"}
        except (OSError, ValueError) as exc:
            return {"ok": False, "kind": "runner_unavailable", "detail": str(exc)[:500]}
        payload = None
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            pass
        # Transport's CLI returns 1 for a real failed task as well as launch errors.
        # Only corroborated original-run evidence bypasses the generic retry delay;
        # normal status/collect still verifies the archive before declaring failure.
        confirmed_failure = (command == "run" and result.returncode == 1
                             and self._confirmed_transport_failure(intent, payload))
        if (result.returncode != 0 and not confirmed_failure) or not isinstance(payload, dict):
            error_text = (result.stderr or "").lower()
            disconnected = any(marker in error_text for marker in (
                "connection timed out", "connection refused", "no route to host",
                "network is unreachable", "returned non-zero exit status 255"))
            if result.returncode == 255 or disconnected:
                self._delay_endpoint()
                return {"ok": False, "kind": "endpoint_unavailable"}
            return {"ok": False, "kind": "runner_error" if result.returncode else "invalid_runner_response",
                    "returncode": result.returncode, "detail": (result.stderr or "")[-1000:]}
        self.state.pop("endpoint_next_probe_at", None)
        self.state.pop("endpoint_failures", None)
        return {"ok": True, "payload": payload, "runner_returncode": result.returncode}

    def _runner_environment(self):
        """Do not pass LLM credentials or local proxies into SSH/solver children."""
        excluded = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "OPENAI_API_KEY",
                    "OPENAI_BASE_URL", "TCAD_MAGPIE_API_KEY"}
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() not in excluded}
        inherited_path = next((value for key, value in environment.items()
                               if key.upper() == "PATH"), "")
        environment = {key: value for key, value in environment.items() if key.upper() != "PATH"}
        environment["PATH"] = str(Path(self.python).resolve().parent) + os.pathsep + inherited_path
        environment["GIT_TERMINAL_PROMPT"] = "0"
        return environment

    def _delay_endpoint(self):
        failures = min(int(self.state.get("endpoint_failures", 0)) + 1, 30)
        self.state["endpoint_failures"] = failures
        self.state["endpoint_next_probe_at"] = time.time() + min(
            self.max_backoff, self.backoff * 2 ** (failures - 1))
        self._save()

    def _delay(self, intent, error):
        failures = min(int(intent.get("probe_failures", 0)) + 1, 30)
        intent.update(probe_failures=failures,
                      next_probe_at=time.time() + min(self.max_backoff, self.backoff * 2 ** (failures - 1)),
                      reconciliation_error=error)
        self._save()

    def _stop_stalled(self, intent, reason):
        """Stop hook for a runner with a verified stop operation."""
        return {"status": "unavailable", "reason": "original_runner_has_no_stop_command"}

    def _observe_watchdog(self, task_id, intent, view, events, observed, record):
        cfg = self.policy.get("watchdog")
        log_tail = observed.get("transient_log_tail")
        if not isinstance(log_tail, str):
            log_tail = observed.get("log_tail")
        if cfg is None or not isinstance(log_tail, str):
            return
        progress = watchdog.parse_transient_progress(log_tail)
        view["progress"] = intent["watchdog_state"] = progress
        if observed.get("status") != "RUNNING" or cfg.get("enabled") is not True:
            return

        if "started_at" not in intent and record and record.get("started_utc"):
            intent["started_at"] = datetime.fromisoformat(record["started_utc"]).timestamp()
        now = time.time()
        result = watchdog.evaluate_watchdog(cfg, intent, progress, now,
                                            view["requested_resources"]["requested_threads"])
        if not result["triggered"]:
            return

        reason = result["reason"]
        view.update(watchdog_triggered=True, watchdog_reason=reason)
        if intent.get("watchdog_triggered", {}).get("reason") != reason:
            intent["watchdog_triggered"] = {"reason": reason, "triggered_at": now}
            events.append({"type": "watchdog_triggered", "id": task_id,
                           "run_id": intent["run_id"], "reason": reason})
            if cfg.get("auto_stop") is True:
                self._save()
                view["watchdog_stop"] = self._stop_stalled(intent, reason)

    def _observe(self, task_id, intent, events, probe=True):
        view = {"id": task_id, "run_id": intent["run_id"], "backend": intent["backend"],
                "slot": intent["slot"], "status": "reconciliation_pending",
                "collected": False, "success": False, "occupied": True}
        try:
            record = self._record(intent)
            view["requested_resources"] = self._slot_resources(intent["slot"], self._intent_profile(intent))
            if record is None and intent["backend"] == "tcad":
                source = Path(__file__).with_name("intent_reconciliation.py")
                sidecar = self.state_dir / "intent-reconciliations" / (intent["run_id"] + ".json")
                if os.path.lexists(sidecar):
                    spec = importlib.util.spec_from_file_location("_tcad_intent_reconciliation", source)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if module.verified_receipt(self.workspace, self.state_dir, task_id, intent):
                        view.update(original_state="FAILED_BEFORE_MANIFEST", remote_exit_code=None,
                                    status="failed_unlaunched", occupied=False,
                                    launch_reconciled=True, terminal_reconciled=True,
                                    reason="verified_original_intent_not_launched")
                        return view
            if record is None and not self._configured_intent(intent):
                raise ValueError("Historical profile run requires a verified collection or an original launch reconciliation receipt")
            if record and self._unlaunched(intent["backend"], record,
                    self._manifest_path(intent["backend"], intent["run_id"]), self._intent_profile(intent)):
                view.update(original_state=record["state"], remote_exit_code=None,
                            status="failed_unlaunched", occupied=False,
                            launch_reconciled=True, terminal_reconciled=True,
                            reason="verified_original_not_launched")
                return view
            if record and self._receipt(intent, record):
                if record.get("parallel_policy") and record.get("parallel_slot_released") is not True:
                    command = "collect"
                else:
                    command = None
            else:
                command = "status"
            if (probe and command and time.time() >= intent.get("next_probe_at", 0)
                    and time.time() >= self.state.get("endpoint_next_probe_at", 0)):
                outcome = self._invoke(intent, command)
                if not outcome["ok"]:
                    self._delay(intent, outcome)
                else:
                    intent.pop("reconciliation_error", None)
                    intent.pop("probe_failures", None)
                    intent.pop("next_probe_at", None)
                    observed = outcome["payload"]
                    response_id = observed.get("run_id" if intent["backend"] == "tcad" else "label")
                    if response_id is not None and response_id != intent["run_id"]:
                        raise ValueError("Runner response belongs to a different original run")
                    if command == "status" and intent["backend"] == "tcad":
                        self._observe_watchdog(task_id, intent, view, events, observed, record)
                    self._save()
                    if command == "status" and observed.get("status") == "FINISHED" and observed.get("alive") is False:
                        collection = self._invoke(intent, "collect")
                        if not collection["ok"]:
                            self._delay(intent, collection)
                        else:
                            events.append({"type": "collected", "id": task_id, "run_id": intent["run_id"]})
                record = self._record(intent)
            if record:
                state = record.get("state", "UNKNOWN")
                view["original_state"] = state
                view["remote_exit_code"] = record.get("remote_exit_code")
                if self._receipt(intent, record):
                    view["collected"] = True
                    view["success"] = state in SUCCESS and record.get("remote_exit_code") == 0
                    view["status"] = "succeeded" if view["success"] else "failed"
                    view["occupied"] = bool(record.get("parallel_policy")) and record.get("parallel_slot_released") is not True
                    if view["occupied"]:
                        view["reason"] = "original_slot_release_pending"
                elif state == "RUNNING":
                    view["status"] = "running"
                else:
                    view["reason"] = "original_receipt_or_launch_reconciliation_required"
            else:
                view["reason"] = "original_manifest_missing_launch_unknown"
            if intent.get("reconciliation_error"):
                view["reconciliation_error"] = intent["reconciliation_error"]["kind"]
        except (ValueError, TypeError, OSError, KeyError) as exc:
            view["reason"] = "original_record_unusable"
            view["detail"] = str(exc)
        return view

    def _discovery(self):
        """Reserve external work locally; original shared remote locks arbitrate races."""
        references = {(v["backend"], v["run_id"]) for v in self.intents.values()}
        external, uncertain = [], False
        patterns = (("tcad", "**/runs/*/manifest.json"),
                    ("geant4", "**/dram-see-v4/transport-probe/operations/*/operation.json"))
        for backend, pattern in patterns:
            for path in sorted(self.cloud_root.glob(pattern)):
                if path.parent.name.startswith("."):
                    continue
                try:
                    record = read_json(path)
                    run_id = record.get("run_id" if backend == "tcad" else "label", path.parent.name)
                    if (backend, run_id) in references and path == self._manifest_path(backend, run_id):
                        continue
                    identity = record.get("connection_identity")
                    # A separate remote_root is a separate pool, never infer equivalence from an alias.
                    if identity and identity.get("remote_root") != self.identity["remote_root"]:
                        continue
                    if backend == "geant4" and record.get("state") == "FAILED_BEFORE_LAUNCH":
                        matched = self._match_profile(backend, run_id, record, path)
                        if self._unlaunched(backend, record, path, matched["cfg"]):
                            continue
                    released = record.get("state") in TERMINAL and (
                        not record.get("parallel_policy") or record.get("parallel_slot_released") is True)
                    if self.transport:
                        # An idle phase boundary requires a verified archive, not
                        # a status string alone. Never collect external work implicitly.
                        released = released and self._receipt({"backend": backend, "run_id": run_id}, record, path)
                    if released:
                        continue
                    if backend == "tcad" and self._closed_archived_attempt(path, record, run_id):
                        continue
                    policy = record.get("parallel_policy") or {}
                    slot = policy.get("slot")
                    try:
                        matched = self._match_profile(backend, run_id, record, path)
                        compatible = type(slot) is int and 0 <= slot < matched["resources"]["capacity"]
                    except (ValueError, KeyError, TypeError):
                        compatible = False
                    if not compatible:
                        uncertain = True
                    view = {"backend": backend, "run_id": run_id, "slot": slot,
                            "status": record.get("state", "UNKNOWN"),
                            "reason": "external_original_work" if compatible else "original_pool_identity_or_capacity_unresolved"}
                    if compatible:
                        view["requested_resources"] = self._slot_resources(slot, matched["cfg"])
                    external.append(view)
                except (OSError, ValueError, AttributeError, TypeError) as exc:
                    uncertain = True
                    external.append({"path": str(path), "reason": "unreadable_original_record", "detail": str(exc)})
        return external, uncertain

    def _closed_archived_attempt(self, path, record, run_id):
        if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", run_id) is None
                or not path.parent.name.startswith("reconciliation-failed-" + run_id + "-")
                or record.get("state") != "TRANSFER_OR_CONNECTION_FAILED"
                or record.get("process_identity") or record.get("last_observation")):
            return False
        canonical = path.parent.parent / run_id / path.name
        if not canonical.is_file() or canonical.is_symlink() or canonical.parent.is_symlink():
            return False
        settled = read_json(canonical)
        return (settled.get("run_id") == run_id
                and all(settled.get(key) == record.get(key) for key in
                        ("connection_identity", "remote_directory", "parallel_policy", "input_sha256"))
                and settled.get("parallel_slot_released") is True
                and self._receipt({"backend": "tcad", "run_id": run_id}, settled, canonical))

    def _eligible_slots(self, task):
        resources = self.profiles[task["backend"]]["resources"]
        widths = resources["requested_threads"]
        if isinstance(widths, int):
            return range(resources["capacity"])
        spec = read_json(self._relative_path(task["project"]) / "project.json")
        if not isinstance(spec, dict):
            raise ValueError("TCAD project.json must be an object")
        threads, cores = spec.get("native_threads", 1), spec.get("native_cores", 1)
        if type(threads) is not int or type(cores) is not int or cores != threads or threads not in widths:
            raise ValueError("Frozen native_threads and native_cores must match an available slot width")
        return [slot for slot, width in enumerate(widths) if width == threads]

    def _inputs(self, task, slot=None):
        project = self._relative_path(task["project"])
        if not project.is_dir():
            raise ValueError("Project directory does not exist")
        if task["backend"] == "tcad":
            if not (project / "project.json").is_file():
                raise ValueError("TCAD project requires project.json")
            tcad_profile = self.profiles["tcad"]
            if "cpu_sets" in tcad_profile["cfg"]:
                spec = read_json(project / "project.json")
                expected_threads = (len(tcad_profile["resources"]["cpu_sets"][slot])
                                    if slot is not None else tcad_profile["resources"]["requested_threads"])
                if isinstance(expected_threads, int):
                    default = 1 if isinstance(tcad_profile["resources"]["requested_threads"], list) else None
                    if (not isinstance(spec, dict)
                            or any(type(spec.get(key, default)) is not int or spec.get(key, default) != expected_threads
                                   for key in ("native_threads", "native_cores"))):
                        raise ValueError(
                            f"Multicore project must explicitly declare native_threads={expected_threads} "
                            f"and native_cores={expected_threads} in a new input directory")
        else:
            if "cpu_sets" in self.profiles["geant4"]["cfg"]:
                raise ValueError("Multicore shared pool does not admit Geant4; use the original single-core profile only in an idle pool, never switch profiles while mixed work remains")
            allowed = self.workspace / "local_runtime/cloud-benchmark/geant4-preparation/inputs"
            if not project.is_relative_to(allowed.resolve()) or not (project / "task.sh").is_file():
                raise ValueError("Geant4 inputs require task.sh below the original cloud Geant4 input root")
        inputs, comparison = {}, {}
        for path in sorted(project.rglob("*")):
            if path.is_symlink() or not path.resolve().is_relative_to(project):
                raise ValueError("Input symlinks or escaping paths are not allowed")
            if path.is_file():
                name = path.relative_to(project).as_posix()
                signature = self._file_signature(path)
                cached = self._input_cache.get(str(path))
                if cached is None or cached[0] != signature:
                    input_hash = file_digest(path)
                    comparison_hash = input_hash
                    if name == "project.json":
                        spec = read_json(path)
                        if not isinstance(spec, dict):
                            raise ValueError("TCAD project.json must be an object")
                        # Renamed project/run metadata is not a changed simulation.
                        spec.pop("name", None)
                        geometry = spec.get("s2_geometry")
                        if isinstance(geometry, dict):
                            geometry.pop("run_id", None)
                        comparison_hash = digest(spec)
                    if self._file_signature(path) != signature:
                        raise ValueError("Project input changed while reading its scheduling snapshot")
                    cached = (signature, input_hash, comparison_hash)
                    self._input_cache[str(path)] = cached
                inputs[name], comparison[name] = cached[1:]
        return inputs, digest(comparison)

    @staticmethod
    def _file_signature(path):
        info = path.stat()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def _successful(self, task_id, views, visited=None):
        visited = set() if visited is None else visited
        if task_id in visited:
            return False
        visited.add(task_id)
        if views.get(task_id, {}).get("success"):
            return True
        return any(self._successful(child, views, visited.copy())
                   for child, intent in self.intents.items() if intent.get("repair_of") == task_id)

    def _lineage(self, task_id):
        seen = set()
        while task_id in self.intents and self.intents[task_id].get("repair_of"):
            if task_id in seen:
                raise ValueError("Repair lineage cycle")
            seen.add(task_id)
            task_id = self.intents[task_id]["repair_of"]
        return task_id

    def _repair_count(self, root):
        return sum(bool(intent.get("repair_of")) and self._lineage(task_id) == root
                   for task_id, intent in self.intents.items())

    def _new_intent_fields(self):
        return {}

    def _staged_tasks(self, queued, allow_submit):
        return {}

    def _publish_candidates(self, tasks, staged, candidates, allow_submit):
        return candidates

    def _order_candidates(self, candidates):
        return sorted(candidates, key=lambda task: (task.get("priority", 100), not bool(task["repair_of"])))

    def _submit(self, task, slot, inputs, input_digest, events):
        # Rechecked per item, so a disarm/signal during a batch takes
        # effect before the next intent is committed or original runner called.
        if not self.can_submit():
            return None
        profile = self.profiles[task["backend"]]
        connection = profile["connection"]
        if not (self.workspace / ".git").exists():
            raise ValueError("Original runner requires workspace Git metadata; initialize the deployed checkout before submission")
        task_id = task["id"]
        run_id = "auto-" + task_id[:45] + "-" + uuid.uuid4().hex[:16]
        if task["backend"] == "tcad":
            spec = read_json(self.workspace / task["project"] / "project.json")
            if "s2_geometry" in spec:
                geometry = spec["s2_geometry"]
                run_id = geometry.get("run_id") if isinstance(geometry, dict) else None
                if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", run_id):
                    raise ValueError("Existing geometry project must declare its exact immutable run_id")
        if (self._manifest_path(task["backend"], run_id).parent.exists()
                or any(v["run_id"] == run_id for v in self.intents.values())
                or (self.workspace / "local_runtime/runs" / run_id).exists()):
            raise ValueError("Original run ID already exists; recover it with adopt_run_id, never relaunch")
        # Re-enumerate paths and stats immediately before committing the intent.
        # Cache hits avoid rereading unchanged bytes; the original runner still
        # performs the authoritative freeze and content hashing.
        current_inputs, current_digest = self._inputs(task, slot=slot)
        if current_inputs != inputs or current_digest != input_digest:
            raise ValueError("Project inputs changed before submission; reconsider the updated task next tick")
        scientific_admission = self._scientific_admission(task, current_inputs)
        if not self.can_submit():
            return None
        intent = {"run_id": run_id, "backend": task["backend"], "project": task["project"],
                  "slot": slot, "connection": connection.copy(), "task_digest": digest(task),
                  "input_sha256": inputs, "input_digest": input_digest,
                  "repair_of": task["repair_of"], "repair_reason": task["repair_reason"],
                  "requested_resources": self._slot_resources(slot, profile["cfg"]),
                  "submission_intent_at": time.time(), **self._new_intent_fields()}
        if scientific_admission is not None:
            intent["scientific_admission"] = scientific_admission
        self.intents[task_id] = intent
        if self.transport:
            self.state["last_submission_schema"] = profile["resources"]["schema"]
        self._save()  # Crash here is deliberately uncertain, never automatic resubmission.
        result = self._invoke(intent, "run")
        if (not result["ok"] and intent["backend"] == "tcad"
                and result.get("returncode") == PREFLIGHT_EXIT_CODE
                and not self._manifest_path("tcad", run_id).exists()):
            # Runner deterministically rejected preflight/reserve before creating
            # any remote lease or local manifest: roll back the ghost intent cleanly.
            self.intents.pop(task_id, None)
            self._save()
            events.append({"type": "preflight_rejected", "id": task_id, "run_id": run_id,
                           "slot": slot, "detail": result.get("detail", "")[-400:]})
            return None
        if not result["ok"]:
            self._delay(intent, result)
        events.append({"type": "submission_requested", "id": task_id, "run_id": run_id, "slot": slot})
        return intent

    def _adopt(self, task, events):
        run_id, backend = task["adopt_run_id"], task["backend"]
        if any(v["run_id"] == run_id and v["backend"] == backend for v in self.intents.values()):
            raise ValueError("Original run is already attached to another task")
        path = self._manifest_path(backend, run_id)
        record = read_json(path)
        profile = self._match_profile(backend, run_id, record, path)
        source = record.get("project_directory" if backend == "tcad" else "input_directory")
        if not source or Path(source).resolve() != self._relative_path(task["project"]):
            raise ValueError("Adoption project differs from the original input directory")
        slot = (record.get("parallel_policy") or {}).get("slot")
        if type(slot) is not int or not 0 <= slot < profile["resources"]["capacity"]:
            raise ValueError("Adoption requires a compatible original parallel slot")
        if task["repair_of"]:
            raise ValueError("Adopt original runs first; do not invent retrospective repair lineage")
        intent = {"run_id": run_id, "backend": backend, "project": task["project"],
                  "slot": slot, "connection": profile["connection"].copy(), "task_digest": digest(task),
                  "input_sha256": record.get("input_sha256", {}), "input_digest": None,
                  "requested_resources": self._slot_resources(slot, profile["cfg"]),
                  "repair_of": None, "repair_reason": "", "adopted": True}
        self.intents[task["id"]] = intent
        self._save()
        events.append({"type": "adopted_original_run", "id": task["id"], "run_id": run_id})
        return intent

    def _ready(self, task, eligible):
        pass

    def _admission(self, task, slot):
        """Compatibility runtime; the production engine adds live resource checks."""
        return {"allowed": True}

    def _switch_ready(self, task, live):
        return True

    def tick(self, allow_submit=True):
        idle_validated=set()
        self._profile()
        tasks, blocked = self._load_tasks()
        staged = self._staged_tasks(tasks, allow_submit)
        proposals = {**staged, **tasks}
        dependency_errors = self._dependency_errors(proposals)
        blocked.extend({"id": task_id, "reason": reason} for task_id, reason in dependency_errors.items())
        events, views = [], {}
        for task_id, intent in self.intents.items():
            views[task_id] = self._observe(task_id, intent, events)
        # Explicit adoption is recovery, not submission; it is allowed in recovery-only mode.
        for task_id, task in tasks.items():
            if task_id not in self.intents and task["adopt_run_id"]:
                try:
                    intent = self._adopt(task, events)
                    views[task_id] = self._observe(task_id, intent, events)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    blocked.append({"id": task_id, "reason": "adoption_failed", "detail": str(exc)})
        external, uncertain = self._discovery()
        uncertain = uncertain or any(view.get("reason") == "original_record_unusable"
                                     for view in views.values())
        occupied = {v["slot"] for v in views.values() if v["occupied"]}
        occupied.update(v["slot"] for v in external if type(v.get("slot")) is int)
        live = [view for view in views.values() if view["occupied"]] + external
        active_count = len(live)
        schemas = {view.get("requested_resources", {}).get("schema") for view in live}
        if self.transport and (None in schemas or len(schemas) > 1):
            uncertain = True
        phase = next(iter(schemas)) if len(schemas) == 1 else None
        pending, candidates, needed_transport = [], [], set()
        switching = self.policy.get("pool_switching", {})
        dependency_mode = switching.get("dependency_mode") is True
        for task_id, task in proposals.items():
            if task_id in self.intents:
                if self.intents[task_id]["task_digest"] != digest(task):
                    blocked.append({"id": task_id, "reason": "submitted_task_definition_changed",
                                    "detail": "Create a new task ID; the original run remains recoverable"})
                continue
            if task["adopt_run_id"]:
                continue
            if task_id in dependency_errors:
                continue
            try:
                staged_inputs = self._inputs(task)[0] if task_id in staged else None
                self._scientific_admission(task, staged_inputs)
            except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
                pending.append({"id": task_id, "reason": "scientific_gate_pending",
                                "detail": str(exc)})
                continue
            waiting = [dep for dep in task["depends_on"] if not self._successful(dep, views)]
            missing = [path for path in task["requires"] if not self._relative_path(path).exists()]
            reason = "dependencies_pending" if waiting else "required_artifacts_pending" if missing else None
            if reason:
                pending.append({"id": task_id, "reason": reason, "depends_on": waiting, "requires": missing})
                if dependency_mode and task['backend'] == 'tcad' and waiting:
                    try:
                        self._inputs(task)
                        self._eligible_slots(task)
                    except (OSError, ValueError, TypeError, KeyError):
                        continue
                    needed_transport.update(waiting)
                continue
            try:
                if "cpu_sets" in self.profiles[task["backend"]]["cfg"] and task["backend"] == "geant4":
                    raise ValueError("Multicore shared pool does not admit Geant4; single-thread transport requires the original profile in an idle pool, never automatic pool switching")
                parent = task["repair_of"]
                if parent:
                    if (parent not in self.intents
                            or not (views.get(parent, {}).get("collected")
                                    or views.get(parent, {}).get("terminal_reconciled"))):
                        raise ValueError("Repair parent must have a verified original terminal collection")
                    if views[parent]["success"]:
                        raise ValueError("Successful runs require a new ordinary research task, not a failure repair")
                    root = self._lineage(parent)
                    if self._repair_count(root) >= self.repair_limit:
                        blocked.append({"id": task_id, "reason": "repair_budget_exhausted", "status": "deferred"})
                        continue
                    old = self.intents[parent]
                    if old["backend"] != task["backend"] or old["project"] == task["project"]:
                        raise ValueError("Repair must retain the backend and use a new project directory")
                    if any(views.get(key, {}).get("occupied") for key in self.intents if self._lineage(key) == root):
                        pending.append({"id": task_id, "reason": "repair_lineage_active"})
                        continue
                # Invalid frozen inputs must not start a global profile drain.
                eligible = self._eligible_slots(task)
                schema=self.profiles[task['backend']]['resources']['schema']
                if (not live and schema not in idle_validated) or (phase and schema!=phase):
                    self._inputs(task);idle_validated.add(schema)
                if phase and schema!=phase:
                    if not self._switch_ready(task,live):
                        pending.append({"id":task_id,"reason":"drain_target_resources_unavailable"})
                        continue
                self._ready(task, eligible)
                candidates.append(task)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                blocked.append({"id": task_id, "reason": "task_requires_revision", "detail": str(exc)})
        candidates = self._publish_candidates(tasks, staged, candidates, allow_submit and not uncertain)
        pool = scheduler_pool.PoolStateMachine(self.state.setdefault("pool_state", {}), switching)
        ready_profiles = [{"id": task["id"],
                           "profile": self.profiles[task["backend"]]["resources"]["schema"],
                           "priority": task.get("priority", 100),
                           "required_transport": task["backend"] == "geant4" and (
                               task["id"] in needed_transport or (task.get("repair_of") is not None
                               and self._lineage(task["repair_of"]) in needed_transport)),
                           "repair": bool(task["repair_of"]), "order": index}
                          for index, task in enumerate(candidates)]
        transport_profile = self.profiles.get("geant4", {}).get("resources", {}).get("schema")
        terminal = {key for key, view in views.items()
                    if not view["occupied"] and (view["collected"] or view.get("terminal_reconciled") or view["status"] == "collection_pending")}
        _, selected = pool.reconcile(live, ready_profiles, time.time(), transport_profile=transport_profile, terminal_ids=terminal)
        draining = pool.state["state"] == "DRAINING"
        for task in self._order_candidates(candidates):
            task_id, parent = task["id"], task["repair_of"]
            profile = self.profiles[task["backend"]]
            target = profile["resources"]["schema"]
            try:
                if not allow_submit or self.ready.get("new_jobs_authorized") is not True:
                    pending.append({"id": task_id, "reason": "submission_not_authorized"})
                elif uncertain:
                    pending.append({"id": task_id, "reason": "original_pool_discovery_uncertain"})
                elif draining or not pool.allows(task_id, target) or (selected is not None and selected != target):
                    pending.append({"id": task_id, "reason": "pool_profile_waiting_for_idle",
                                    "current_schema": phase, "requested_schema": target,
                                    "detail": "Wait for verified collection and lease release; keep original task/run identities"})
                elif time.time() < self.state.get("endpoint_next_probe_at", 0):
                    pending.append({"id": task_id, "reason": "endpoint_backoff"})
                elif not self.can_submit():
                    pending.append({"id": task_id, "reason": "submission_paused"})
                else:
                    eligible = self._eligible_slots(task)
                    limit = self.transport["limit"] if self.transport and task["backend"] == "geant4" else self.limit
                    free = (next((slot for slot in eligible if slot not in occupied), None)
                            if active_count < limit else None)
                    if free is None:
                        pending.append({"id": task_id, "reason": "all_slots_occupied",
                                        "eligible_slots": list(eligible)})
                        continue
                    inputs, input_digest = self._inputs(task, slot=free)
                    if parent:
                        root = self._lineage(parent)
                        # Compare every actual attempt, not merely the last one.
                        relatives = [v for key, v in self.intents.items() if self._lineage(key) == root]
                        if any(v.get("input_digest") == input_digest or v.get("input_sha256") == inputs
                               for v in relatives):
                            raise ValueError("Repair repeats unchanged inputs from this lineage")
                    verdict = self._admission(task, free)
                    if not verdict["allowed"]:
                        pending.append({"id": task_id, "reason": "admission_" + verdict["blocking_dimension"],
                                        "detail": verdict["detail"]})
                        continue
                    intent = self._submit(task, free, inputs, input_digest, events)
                    if intent is None:
                        reason = "preflight_rejected" if any(
                            ev.get("type") == "preflight_rejected" and ev.get("id") == task_id for ev in events
                        ) else "submission_paused"
                        pending.append({"id": task_id, "reason": reason})
                        continue
                    phase = target
                    selected = target
                    pool.submitted(target, time.time())
                    views[task_id] = self._observe(task_id, intent, events, probe=False)
                    if views[task_id]["occupied"]:
                        occupied.add(free)
                        active_count += 1
            except (OSError, ValueError, TypeError, KeyError) as exc:
                blocked.append({"id": task_id, "reason": "task_requires_revision", "detail": str(exc)})
        repair_requests = []
        for task_id, view in views.items():
            if ((view["collected"] or view.get("terminal_reconciled"))
                    and not view["success"] and not self._successful(task_id, views)):
                if "cpu_sets" in self.profiles[view["backend"]]["cfg"] and view["backend"] == "geant4":
                    blocked.append({"id": task_id, "reason": "geant4_requires_idle_single_core_profile",
                                    "status": "deferred",
                                    "detail": "Single-thread transport requires the original profile in an idle pool; never switch pools/profiles automatically"})
                    continue
                root = self._lineage(task_id)
                has_next = any(task.get("repair_of") == task_id for task in tasks.values())
                if not has_next and self._repair_count(root) < self.repair_limit:
                    repair_requests.append({"id": task_id, "run_id": view["run_id"], "backend": view["backend"],
                                            "reason": ("original_run_failed_unlaunched"
                                                       if view.get("terminal_reconciled")
                                                       else "original_run_failed_collected"),
                                            "attempts_remaining": self.repair_limit - self._repair_count(root),
                                            "required_resources": self.profiles[view["backend"]]["resources"],
                                            "required_action": "Propose a new task ID, project directory and run ID with changed inputs, repair_of and repair_reason"})
                elif not has_next and self._repair_count(root) >= self.repair_limit:
                    blocked.append({"id": task_id, "reason": "repair_budget_exhausted", "status": "deferred"})
            elif view["status"] == "reconciliation_pending":
                blocked.append({"id": task_id, "reason": view.get("reason", "original_reconciliation_pending"),
                                "run_id": view["run_id"]})
        complete = bool(tasks) and not blocked and all(self._successful(key, views) for key in tasks)
        stable = {"tasks": sorted(tasks.values(), key=lambda item: item["id"]),
                  "runs": sorted(views.values(), key=lambda item: item["id"]),
                  "external": external, "pending": pending, "blocked": blocked,
                  "profile_resources": self.resources, "max_parallel_jobs": self.limit,
                  "backend_resources": {backend: profile["resources"] for backend, profile in self.profiles.items()},
                  "pool_phase": {"schema": phase, "draining": draining},
                  "repair_requests": repair_requests, "discovery_uncertain": uncertain,
                  "submission_allowed": bool(allow_submit and self.ready.get("new_jobs_authorized") is True)}
        if self.intents or pool.state.get("target"):
            self._save()
        self._maintain_results(views)
        self._offload_results(views)
        # Raw progress changes each poll; watchdog alerts still change the event fingerprint.
        fingerprint = dict(stable, runs=[{key: value for key, value in view.items()
                                         if key not in {"progress", "watchdog_stop", "remote_observed_at"}}
                                         for view in stable["runs"]])
        return {"fingerprint": digest(fingerprint), "events": events,
                "active_count": active_count, "running_count": sum(v["status"] == "running" for v in views.values()),
                "pending_count": len(pending), "repair_requests": repair_requests,
                "blocked_tasks": blocked, "queue_complete": complete,
                "discovery_uncertain": uncertain, "runs": stable["runs"],
                "external_runs": external, "pending_tasks": pending,
                "needs_planning": not tasks or bool(repair_requests) or complete,
                "profile_resources": self.resources, "max_parallel_jobs": self.limit,
                "backend_resources": stable["backend_resources"], "pool_phase": stable["pool_phase"],
                "scientific_acceptance": "not_assessed"}
