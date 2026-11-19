#!/usr/bin/env python3
"""Install a SHA-verified source snapshot and a disabled unit; never start/enable it.

Run as the TCAD host administrator, not on the HK host. The input bundle is
created by package.py and contains no credentials, VM images or old raw results.
Existing settings/state and locally changed deployed source are preserved.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile

try:
    import fcntl
    import grp
    import pwd
except ImportError:  # Pure helpers and offline deployment tests also run on Windows.
    fcntl = grp = pwd = None


CONFIG_DIR = Path("/etc/tcad-autonomy")
STATE_DIR = Path("/var/lib/tcad-autonomy")
DEFAULT_WORKSPACE = Path("/home/tcad/projects/tcad-research-training")
DEFAULT_RUNNER_PYTHON = Path("/opt/tcad-autonomy/python/bin/python3")
RELEASES_DIR = Path("/opt/tcad-autonomy/releases")
CURRENT_LINK = Path("/opt/tcad-autonomy/current")
UNIT_PATH = Path("/etc/systemd/system/tcad-autonomy.service")


def preserved_policy():
    path = CONFIG_DIR / "policy.json"
    refuse_symlinks(path)
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema") not in ("tcad-server-codex-v1", "tcad-server-codex-v2"):
        raise ValueError("Unsupported preserved policy schema")
    return value


def deployment_paths(policy):
    policy = policy or {}
    paths = {}
    for field, default in (
        ("workspace", DEFAULT_WORKSPACE), ("state_dir", STATE_DIR),
        ("runner_python", DEFAULT_RUNNER_PYTHON),
    ):
        if policy and field not in policy and not (
                field == "runner_python" and policy.get("schema") == "tcad-server-codex-v1"):
            raise ValueError("Preserved policy is missing its source/runtime path: " + field)
        value = policy.get(field, default.as_posix())
        if (not isinstance(value, str) or not (
                Path(value).is_absolute() or PurePosixPath(value).is_absolute())
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("Deployment requires an absolute, printable path: " + field)
        path = Path(value)
        # prepare_python.py intentionally supplies python -> python-<version>,
        # and a CPython distribution may also link bin/python3. These are
        # executable inputs, never installer write destinations.
        if field != "runner_python":
            refuse_symlinks(path)
        if path == Path(path.anchor):
            raise ValueError("Deployment target cannot be a filesystem root: " + field)
        paths[field] = path
    root, state = paths["workspace"].resolve(), paths["state_dir"].resolve()
    if root == state or root in state.parents:
        raise ValueError("Controller state must remain outside the source workspace")
    return paths


def unit_quote(value, command=False):
    value = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Control characters are not valid in a systemd path")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def unit_scalar_path(value):
    """Single-path directives do not use ExecStart's shell-like quoting."""
    value = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Control characters are not valid in a systemd path")
    if value != value.strip():
        raise ValueError("Single-path systemd directives cannot preserve edge whitespace")
    return value.replace("%", "%%")


def render_unit(template, workspace, state, runner_python, current, policy_file):
    """Render actual preserved paths without adding start/enable commands."""
    changes = {
        "ConditionPathExists": unit_scalar_path(policy_file),
        "WorkingDirectory": unit_scalar_path(workspace),
        "ExecStart": " ".join(unit_quote(arg, command=True) for arg in (
            runner_python, "-B", PurePosixPath(str(current)) / "controller.py",
            "--policy", policy_file, "serve",
        )),
        "ReadWritePaths": " ".join(unit_quote(path) for path in (workspace, state)),
    }
    seen = set()
    result = []
    for line in template.splitlines():
        key = line.partition("=")[0]
        if key in changes:
            if key in seen:
                raise ValueError("Duplicate systemd deployment directive: " + key)
            seen.add(key)
            line = key + "=" + changes[key]
        elif line.startswith("Environment=PATH="):
            line = "Environment=" + unit_quote(
                "PATH=" + str(PurePosixPath(str(runner_python)).parent) + ":/usr/local/bin:/usr/bin:/bin"
            )
        result.append(line)
    if seen != set(changes):
        raise ValueError("Systemd template lacks required deployment directives")
    return "\n".join(result) + "\n"


def git_environment():
    # An administrator's Git overrides, hooks, signing or index must not leak
    # into a synthetic source-only provenance repository.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1")
    return env


def source_git(root, manifest, bundle_sha, existing_head=None):
    """Only a new snapshot gets a commit; an existing repository keeps its index."""
    root = Path(root)
    prefix = ["runuser", "-u", "tcad", "--", "git", "-c", "core.hooksPath=/dev/null",
              "-C", str(root)]
    env = git_environment()

    def git(args, **kwargs):
        return subprocess.run(prefix + args, env=env, check=True, capture_output=True, **kwargs)

    if existing_head is not None:
        return {"created": False, "head": existing_head}
    refuse_symlinks(root / ".git")
    if (root / ".git").exists():
        head = git(["rev-parse", "--verify", "HEAD"], text=True).stdout.strip()
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
            raise ValueError("Existing source repository has no verified HEAD")
        return {"created": False, "head": head}
    inherited = subprocess.run(prefix + ["rev-parse", "--show-toplevel"], env=env,
                               capture_output=True, text=True)
    if inherited.returncode == 0:
        raise RuntimeError("Snapshot workspace is inside another repository; preserve it")
    paths = sorted(name[len("project/"):] for name in manifest["files"] if name.startswith("project/"))
    paths.append(".server-codex-snapshot.json")
    for name in paths:
        refuse_symlinks(root / name)
        if not (root / name).is_file():
            raise ValueError("Missing manifest source before provenance commit: " + name)
    git(["init", "--template=", "--initial-branch=snapshot"], text=True)
    git(["add", "--force", "--pathspec-from-file=-", "--pathspec-file-nul"],
        input=("\0".join(paths) + "\0").encode("utf-8"))
    git(["-c", "user.name=TCAD snapshot installer", "-c", "user.email=tcad-snapshot@localhost",
         "-c", "commit.gpgsign=false", "commit", "--no-verify", "-m",
         "TCAD source snapshot " + bundle_sha
         + "\n\nSource-only SHA256-verified installer snapshot; not upstream history."], text=True)
    committed = git(["ls-tree", "-rz", "--name-only", "HEAD"]).stdout
    if set(committed.decode("utf-8").rstrip("\0").split("\0")) != set(paths):
        raise ValueError("Snapshot commit contains files outside its source manifest")
    head = git(["rev-parse", "--verify", "HEAD"], text=True).stdout.strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
        raise ValueError("Snapshot repository has no verified HEAD")
    return {"created": True, "head": head}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def refuse_symlinks(path):
    for part in (Path(path), *Path(path).parents):
        if part.is_symlink():
            raise RuntimeError("Refuse deployment through an existing symlink: " + str(part))


def make_owned_dirs(path, uid, gid):
    """Set ownership only on directories this invocation actually creates."""
    path = Path(path)
    refuse_symlinks(path)
    missing = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    for candidate in reversed(missing):
        candidate.mkdir(mode=0o755)
        os.chown(candidate, uid, gid)


def plan_legacy_task_migration(policy, release_id):
    """Read the old release before replacing current; never guess custom content."""
    if not policy or policy["schema"] != "tcad-server-codex-v1":
        return None
    value = policy.get("task_file")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("Legacy task_file must be an absolute path")
    task = Path(value)
    refuse_symlinks(task)
    report = {
        "task_file": str(task), "status": "task_preserved_custom",
        "task_preserved_custom": True, "needs_alignment": True,
    }
    plan = {"report": report}
    if not task.is_file() or not CURRENT_LINK.exists():
        return plan
    old_template = CURRENT_LINK.resolve() / "operator-task.example.md"
    refuse_symlinks(old_template)
    if not old_template.is_file():
        return plan
    original = task.read_bytes()
    if original != old_template.read_bytes():
        return plan
    backup = task.with_name(task.name + ".v1-default-" + release_id + ".bak")
    pending = task.with_name(task.name + ".v2-default-" + release_id + ".tmp")
    for path in (backup, pending):
        refuse_symlinks(path)
        if path.exists():
            raise RuntimeError("Preserve existing task migration evidence: " + str(path))
    plan.update(task=task, original=original, metadata=task.stat(),
                backup=backup, pending=pending)
    return plan


def apply_legacy_task_migration(plan, new_default):
    if plan is None:
        return None
    if "original" not in plan:
        return plan["report"]
    task, backup, pending = (plan[key] for key in ("task", "backup", "pending"))
    for path in (task, backup, pending):
        refuse_symlinks(path)
    if task.read_bytes() != plan["original"]:
        raise RuntimeError("Preserve task changed during policy migration")
    metadata = plan["metadata"]
    mode = stat.S_IMODE(metadata.st_mode)
    with backup.open("xb") as stream:
        stream.write(plan["original"])
    os.chown(backup, metadata.st_uid, metadata.st_gid)
    os.chmod(backup, mode)
    created = False
    try:
        with pending.open("xb") as stream:
            created = True
            stream.write(new_default)
        os.chown(pending, metadata.st_uid, metadata.st_gid)
        os.chmod(pending, mode)
        os.replace(str(pending), str(task))
        created = False
    finally:
        if created:
            pending.unlink(missing_ok=True)
    return dict(plan["report"], status="task_default_migrated",
                task_preserved_custom=False, needs_alignment=False, backup=str(backup))


@contextmanager
def controller_install_lock():
    """Also exclude manually started controllers, not only the systemd unit."""
    if fcntl is None or pwd is None:
        raise RuntimeError("Installation requires a POSIX TCAD host")
    state = deployment_paths(preserved_policy())["state_dir"]
    user = pwd.getpwnam("tcad")
    refuse_symlinks(state / "controller.lock")
    if not state.exists():
        make_owned_dirs(state, user.pw_uid, user.pw_gid)
        os.chmod(state, 0o700)
    lock = state / "controller.lock"
    existed = lock.exists()
    with lock.open("a+b") as stream:
        if not existed:
            os.fchown(stream.fileno(), user.pw_uid, user.pw_gid)
            os.fchmod(stream.fileno(), 0o600)
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A manually started controller owns the lifecycle lock")
        yield


def install(bundle, expected, release_id, stage_runtime_only=False):
    if pwd is None or grp is None:
        raise RuntimeError("Installation requires a POSIX TCAD host")
    if os.geteuid() != 0:
        raise RuntimeError("Install as the TCAD host administrator")
    if not re.fullmatch(r"[0-9TZ-]{16,32}", release_id):
        raise ValueError("Invalid release ID")
    if sha(bundle) != expected:
        raise ValueError("Deployment bundle SHA256 mismatch")
    active = subprocess.run(["systemctl", "is-active", "--quiet", "tcad-autonomy.service"])
    if active.returncode == 0:
        raise RuntimeError("Controller is active; do not replace its code during a cycle")
    prior_policy = preserved_policy()
    paths = deployment_paths(prior_policy)
    root, state, runtime_python = (paths[name] for name in ("workspace", "state_dir", "runner_python"))
    subprocess.run([
        str(runtime_python), "-I", "-B", "-c",
        "import hashlib,inspect,pathlib,sys;"
        "assert sys.version_info >= (3,11);"
        "assert hasattr(hashlib,'file_digest');"
        "assert 'newline' in inspect.signature(pathlib.Path.write_text).parameters",
    ], check=True, capture_output=True, text=True)
    user = pwd.getpwnam("tcad")
    gid = grp.getgrnam("tcad").gr_gid
    release = RELEASES_DIR / release_id
    if release.exists():
        raise RuntimeError("Release already exists; inspect it instead of overwriting")
    files = {}
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 20000 or sum(m.size for m in members) > 96 * 1024**2:
            raise ValueError("Unexpectedly large source-only bundle")
        for member in members:
            p = PurePosixPath(member.name)
            if (not member.isfile() or p.is_absolute() or ".." in p.parts or ".git" in p.parts
                    or "\\" in member.name or member.name == "project/.server-codex-snapshot.json"
                    or p.as_posix() != member.name or len(p.parts) < (1 if member.name == "SNAPSHOT.json" else 2)
                    or member.name in files or member.size > 8 * 1024**2):
                raise ValueError("Unsafe deployment member: " + member.name)
            if member.name != "SNAPSHOT.json" and p.parts[0] not in {"project", "runtime", "handoff"}:
                raise ValueError("Unknown deployment namespace")
            if p.parts[:2] == ("project", "plans") and p.name == "work-items.json":
                raise ValueError("Live execution proposals do not belong in a source snapshot")
            files[member.name] = archive.extractfile(member).read()
    manifest = json.loads(files.pop("SNAPSHOT.json"))
    if manifest.get("schema") != "tcad-server-source-snapshot-v1" or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported source snapshot manifest")
    if set(manifest["files"]) != set(files):
        raise ValueError("Bundle membership differs from manifest")
    for name, data in files.items():
        if hashlib.sha256(data).hexdigest() != manifest["files"][name]:
            raise ValueError("Bundle file SHA256 mismatch: " + name)
    if stage_runtime_only:
        if any(not name.startswith("runtime/") for name in files):
            raise ValueError("Runtime staging requires a runtime-only snapshot")
        required = {"runtime/controller.py", "runtime/runtime.py", "runtime/tcad-autonomy.service"}
        if not required <= files.keys():
            raise ValueError("Runtime snapshot lacks required controller files")
        refuse_symlinks(release)
        make_owned_dirs(release, 0, 0)
        for name, data in files.items():
            target = release / name.removeprefix("runtime/")
            make_owned_dirs(target.parent, 0, 0)
            with target.open("xb") as stream:
                stream.write(data)
            os.chmod(target, 0o644)
        subprocess.run(["restorecon", "-R", str(release)], check=True, capture_output=True)
        return {"release": str(release), "files_verified": len(files), "staged_only": True}
    old_manifest = root / ".server-codex-snapshot.json"
    refuse_symlinks(old_manifest)
    refuse_symlinks(release)
    old = json.loads(old_manifest.read_text(encoding="utf-8")) if old_manifest.exists() else None
    if root.exists() and not old:
        raise RuntimeError("Existing unowned workspace; do not merge a snapshot over it")
    existing_head = None
    refuse_symlinks(root / ".git")
    if (root / ".git").exists():
        result = subprocess.run(
            ["runuser", "-u", "tcad", "--", "git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            env=git_environment(), check=True, capture_output=True, text=True,
        )
        existing_head = result.stdout.strip()
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", existing_head):
            raise ValueError("Existing source repository has no verified HEAD")
    else:
        probe = root
        while not probe.exists():
            probe = probe.parent
        inherited = subprocess.run(
            ["runuser", "-u", "tcad", "--", "git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            env=git_environment(), capture_output=True, text=True,
        )
        if inherited.returncode == 0:
            raise RuntimeError("Snapshot workspace is inside another repository; preserve it")
    for path in (CONFIG_DIR, state, UNIT_PATH, CURRENT_LINK.with_name("current-" + release_id)):
        refuse_symlinks(path)
    destinations = []
    for name, data in files.items():
        if name.startswith("runtime/"):
            dest = release / name[len("runtime/"):]
            uid, group = 0, 0
        elif name.startswith("project/"):
            dest = root / name[len("project/"):]
            uid, group = user.pw_uid, gid
            if old:
                if dest.exists() and sha(dest) != old["files"].get(name):
                    raise RuntimeError("Preserve changed server source: " + str(dest))
        else:
            dest = root.parent / "output/server-benchmark-20261115" / name[len("handoff/"):]
            uid, group = user.pw_uid, gid
            if dest.exists() and dest.read_bytes() != data:
                raise RuntimeError("Preserve existing server handoff: " + str(dest))
        refuse_symlinks(dest)
        destinations.append((dest, data, uid, group))
    task_plan = plan_legacy_task_migration(prior_policy, release_id)
    make_owned_dirs(release, 0, 0)
    make_owned_dirs(root, user.pw_uid, gid)
    for dest, data, uid, group in destinations:
        make_owned_dirs(dest.parent, uid, group)
        dest.write_bytes(data)
        os.chown(dest, uid, group)
        os.chmod(dest, 0o644)
    old_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chown(old_manifest, user.pw_uid, gid)
    git_provenance = source_git(root, manifest, expected, existing_head)
    config = CONFIG_DIR
    config.mkdir(mode=0o750, exist_ok=True)
    os.chown(config, 0, gid)
    for source, target in (
        ("policy.example.json", "policy.json"), ("operator-task.example.md", "task.md"),
        ("readiness.example.json", "readiness.example.json"),
    ):
        dest = config / target
        refuse_symlinks(dest)
        if not dest.exists():
            if target == "policy.json":
                policy = json.loads((release / source).read_text(encoding="utf-8-sig"))
                policy.update(workspace=str(root), state_dir=str(state), runner_python=str(runtime_python),
                              task_file=str(config / "task.md"),
                              plan_file=str(root / "plans/dram-se-ddr5-lpddr5/PLAN.md"),
                              queue_file=str(root / "plans/dram-se-ddr5-lpddr5/work-items.json"),
                              enabled=False, readiness=None)
                dest.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                shutil.copyfile(release / source, dest)
            os.chown(dest, 0, gid)
            os.chmod(dest, 0o640)
    migration = None
    if prior_policy and prior_policy["schema"] == "tcad-server-codex-v1":
        result = subprocess.run(
            [str(runtime_python), "-I", "-B", str(release / "controller.py"),
             "--policy", str(config / "policy.json"), "migrate"],
            check=True, capture_output=True, text=True,
        )
        migration = json.loads(result.stdout)
        migrated = preserved_policy()
        if (migrated["schema"] != "tcad-server-codex-v2" or migrated.get("enabled") is not False
                or migrated.get("readiness") is not None
                or any(Path(migrated.get(key, "")) != value for key, value in paths.items())):
            raise ValueError("Policy migration did not preserve disabled source/runtime bindings")
        for key in ("workspace", "state_dir", "runner_python",
                    "source_codex_config", "codex_binary", "task_file"):
            if key in prior_policy and migrated.get(key) != prior_policy[key]:
                raise ValueError("Policy migration changed preserved source field: " + key)
    task_migration = apply_legacy_task_migration(
        task_plan, files["runtime/operator-task.example.md"],
    )
    new_state = not state.exists()
    make_owned_dirs(state, user.pw_uid, gid)
    if new_state:
        os.chmod(state, 0o700)
    current = CURRENT_LINK
    pending = current.with_name("current-" + release_id)
    pending.symlink_to(release, target_is_directory=True)
    os.replace(str(pending), str(current))
    unit = UNIT_PATH
    unit.write_text(render_unit(
        (release / "tcad-autonomy.service").read_text(encoding="utf-8"),
        root, state, runtime_python, current, config / "policy.json",
    ), encoding="utf-8")
    os.chmod(unit, 0o644)
    subprocess.run(["systemd-analyze", "verify", str(unit)], check=True, capture_output=True, text=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["restorecon", "-RF", str(config), str(state), str(current.parent)],
                   check=True, capture_output=True)
    touched = [str(dest) for dest, _, _, _ in destinations] + [str(old_manifest), str(unit)]
    for offset in range(0, len(touched), 100):
        subprocess.run(["restorecon", "-F"] + touched[offset:offset + 100],
                       check=True, capture_output=True)
    subprocess.run(["runuser", "-u", "tcad", "--", str(runtime_python), "-B", str(current / "controller.py"),
                    "--policy", str(config / "policy.json"), "init"], check=True)
    return {
        "release": str(release), "workspace": str(root),
        "files_verified": len(files), "policy_preserved": True,
        "policy_migration": migration, "task_migration": task_migration,
        "source_git": git_provenance,
        "service_started": False, "service_enabled_by_installer": False,
        "note": "Source snapshot only; original state and VM acceptance must be handed over before arming",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--stage-runtime-only", action="store_true",
                        help="Verify and stage runtime files without changing the active release or live state")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Install as the TCAD host administrator")
    with controller_install_lock():
        result = install(args.bundle, args.sha256, args.release, stage_runtime_only=args.stage_runtime_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
