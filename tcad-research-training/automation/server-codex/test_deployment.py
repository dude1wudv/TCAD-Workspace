"""Offline deployment contracts: every Linux command is mocked; nothing starts."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


d = load("tcad_deployment_installer", "install.py")
p = load("tcad_deployment_packager", "package.py")
c = load("tcad_deployment_migration", "controller.py")
HEAD = "a" * 40
RELEASE = "2026-11-16T120000Z"


def result(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def bundle_at(path, files):
    manifest = {
        "schema": "tcad-server-source-snapshot-v1",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "excluded": {},
    }
    members = dict(files, **{"SNAPSHOT.json": json.dumps(manifest).encode()})
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return d.sha(path), manifest


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.here = self.root / "automation/server-codex"
        self.here.mkdir(parents=True)
        for name in ("AGENTS.md", "README.md", "docs/server-workflow.md", "docs/server-codex.md"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("offline source\n")
        for name in p.RUNTIME:
            (self.here / name).write_text("# offline runtime fixture\n")
        (self.here / "work-items.example.json").write_text(
            json.dumps({"schema": "tcad-work-items-v1", "tasks": []})
        )
        self.patch = mock.patch.multiple(p, ROOT=self.root, HERE=self.here)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_plan_and_runtime_ship_but_live_queue_private_state_and_results_do_not(self):
        handoff = self.base / "output/server-benchmark-20261115/HANDOFF.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_bytes(b"another thread owns this changing handoff\n")
        original_handoff = handoff.read_bytes()
        self.write("plans/research/PLAN.md", "new plan")
        self.write("plans/research/protocol.yaml", "threads: 1\n")
        self.write("plans/research/work-items.json", '{"private":"sk-' + "A" * 30 + '"}')
        self.write("plans/research/nested/work-items.json", '{"tasks":[{"execute":true}]}')
        self.write("experiments/results/result.json", '{"raw":true}')
        self.write("experiments/local_runtime/secret.json", '{"secret":true}')
        self.write("experiments/connection-private.json", '{"private":true}')
        output = self.base / "source.tar.gz"
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("No command during packaging")):
            report = p.package(output)
        self.assertTrue(report["source_state_only"])
        with tarfile.open(output) as archive:
            names = set(archive.getnames())
            manifest = json.load(archive.extractfile("SNAPSHOT.json"))
            example = json.load(archive.extractfile("runtime/work-items.example.json"))
        self.assertIn("project/plans/research/PLAN.md", names)
        self.assertIn("project/plans/research/protocol.yaml", names)
        for name in ("runtime.py", "test_runtime.py", "work-items.example.json",
                     "r06_gate.py", "intent_reconciliation.py"):
            self.assertIn("runtime/" + name, names)
        self.assertEqual(example["tasks"], [])
        for forbidden in ("work-items.json", "result.json", "secret.json", "connection-private.json"):
            self.assertFalse(any(Path(name).name == forbidden for name in names))
        self.assertFalse(any(name.startswith("handoff/") for name in names))
        self.assertEqual(handoff.read_bytes(), original_handoff)
        self.assertFalse(handoff.with_name("CURRENT-DECISIONS.md").exists())
        self.assertIn("plans/research/work-items.json", manifest["excluded"])

    def test_nonempty_runtime_example_is_rejected(self):
        (self.here / "work-items.example.json").write_text(
            json.dumps({"schema": "tcad-work-items-v1", "tasks": [{"id": "do-not-ship"}]})
        )
        with self.assertRaisesRegex(ValueError, "empty task list"):
            p.package(self.base / "source.tar.gz")

    def test_live_secret_in_included_source_is_rejected_without_echoing_value(self):
        secret = "sk-" + "B" * 30
        self.write("scripts/review.py", 'token = "' + secret + '"')
        with self.assertRaises(ValueError) as raised:
            p.package(self.base / "source.tar.gz")
        self.assertIn("scripts/review.py", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))


class GitAndUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.commands = []
        self.staged = b""

    def git(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        if "--show-toplevel" in argv:
            return result("", 128)
        if "init" in argv:
            (self.root / ".git").mkdir()
        if "add" in argv:
            self.staged = kwargs["input"]
        if "ls-tree" in argv:
            return result(self.staged)
        if "rev-parse" in argv:
            return result(HEAD + "\n")
        return result()

    def test_new_snapshot_commits_exact_manifest_sources_with_fixed_identity(self):
        (self.root / "source.py").write_text("# source\n")
        (self.root / ".server-codex-snapshot.json").write_text("{}")
        (self.root / "local_runtime").mkdir()
        (self.root / "local_runtime/secret-result.json").write_text("do not stage")
        manifest = {"files": {"project/source.py": "unused", "runtime/controller.py": "unused"}}
        with mock.patch.object(d.subprocess, "run", side_effect=self.git), \
             mock.patch.dict(os.environ, {"GIT_INDEX_FILE": "do-not-use-this-index"}):
            report = d.source_git(self.root, manifest, "b" * 64)
        self.assertEqual(report, {"created": True, "head": HEAD})
        self.assertEqual(set(self.staged.decode().strip("\0").split("\0")),
                         {"source.py", ".server-codex-snapshot.json"})
        commits = [args for args, _ in self.commands if "commit" in args]
        self.assertEqual(len(commits), 1)
        self.assertIn("user.name=TCAD snapshot installer", commits[0])
        self.assertIn("user.email=tcad-snapshot@localhost", commits[0])
        self.assertTrue(any("b" * 64 in arg for arg in commits[0]))
        for _, kwargs in self.commands:
            self.assertNotIn("GIT_INDEX_FILE", kwargs["env"])
            self.assertEqual(kwargs["env"]["GIT_LITERAL_PATHSPECS"], "1")

    def test_existing_repository_only_verifies_head_and_preserves_dirty_index(self):
        (self.root / ".git").mkdir()
        index = self.root / ".git/index"
        index.write_bytes(b"existing staged user changes")
        with mock.patch.object(d.subprocess, "run", side_effect=self.git):
            report = d.source_git(self.root, {"files": {}}, "b" * 64)
        self.assertFalse(report["created"])
        self.assertEqual(index.read_bytes(), b"existing staged user changes")
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.commands[0][0][-3:], ["rev-parse", "--verify", "HEAD"])

    def test_inherited_parent_repository_is_not_initialized_or_committed(self):
        with mock.patch.object(d.subprocess, "run", return_value=result(str(self.root.parent))) as run:
            with self.assertRaisesRegex(RuntimeError, "inside another repository"):
                d.source_git(self.root, {"files": {}}, "b" * 64)
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.root / ".git").exists())

    def test_unit_uses_preserved_paths_and_quotes_systemd_special_characters(self):
        template = (HERE / "tcad-autonomy.service").read_text(encoding="utf-8")
        rendered = d.render_unit(
            template, "/srv/TCAD source/100%case", "/var/lib/tcad-custom",
            "/opt/python custom/bin/python3", "/opt/tcad-current", "/etc/tcad/policy.json",
        )
        self.assertIn('WorkingDirectory=/srv/TCAD source/100%%case\n', rendered)
        self.assertIn('ConditionPathExists=/etc/tcad/policy.json\n', rendered)
        self.assertNotIn('WorkingDirectory="', rendered)
        self.assertNotIn('ConditionPathExists="', rendered)
        self.assertIn('ReadWritePaths="/srv/TCAD source/100%%case" "/var/lib/tcad-custom"', rendered)
        self.assertIn('ExecStart="/opt/python custom/bin/python3"', rendered)
        self.assertIn('Environment="PATH=/opt/python custom/bin:/usr/local/bin:/usr/bin:/bin"', rendered)
        self.assertIn('"--policy" "/etc/tcad/policy.json" "serve"', rendered)
        self.assertNotIn("/home/tcad/projects/tcad-research-training", rendered)
        with self.assertRaisesRegex(ValueError, "Control characters"):
            d.unit_quote("/srv/work\nExecStart=bad")
        with self.assertRaisesRegex(ValueError, "Control characters"):
            d.unit_scalar_path("/srv/work\nExecStart=bad")

    def test_prepared_python_symlink_is_accepted_but_workspace_symlink_is_refused(self):
        workspace = self.root / "source"
        state = self.root / "state"
        runner = self.root / "python/bin/python3"
        policy = {
            "schema": "tcad-server-codex-v2", "workspace": str(workspace),
            "state_dir": str(state), "runner_python": str(runner),
        }
        with mock.patch.object(Path, "is_symlink", lambda path: path in (runner, runner.parent.parent)):
            self.assertEqual(d.deployment_paths(policy)["runner_python"], runner)
        with mock.patch.object(Path, "is_symlink", lambda path: path == workspace):
            with self.assertRaisesRegex(RuntimeError, "existing symlink"):
                d.deployment_paths(policy)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "projects/explicit-snapshot"
        self.config = self.base / "etc/tcad-autonomy"
        self.state = self.base / "state"
        self.releases = self.base / "opt/releases"
        self.current = self.base / "opt/current"
        self.unit = self.base / "etc/systemd/system/tcad-autonomy.service"
        self.unit.parent.mkdir(parents=True)
        self.runner_python = self.base / "python-custom/bin/python3"
        self.commands = []
        self.staged = b""
        self.policy = json.loads((HERE / "policy.example.json").read_text())
        self.policy.update(
            workspace=str(self.root), state_dir=str(self.state), runner_python=str(self.runner_python),
            source_codex_config=str(self.base / "preserved-magpie/config.toml"),
            codex_binary=str(self.base / "preserved-tools/codex"),
            task_file=str(self.config / "task.md"),
            plan_file=str(self.root / "plans/dram-se-ddr5-lpddr5/PLAN.md"),
            queue_file=str(self.root / "plans/dram-se-ddr5-lpddr5/work-items.json"),
        )
        self.files = {
            "project/AGENTS.md": b"offline project instructions\n",
            "project/scripts/tcad.py": b"# frozen runner fixture, never executed\n",
            "runtime/controller.py": b"# not executed by offline deployment tests\n",
            "runtime/policy.example.json": (HERE / "policy.example.json").read_bytes(),
            "runtime/operator-task.example.md": b"offline instructions\n",
            "runtime/readiness.example.json": b"{}\n",
            "runtime/tcad-autonomy.service": (HERE / "tcad-autonomy.service").read_bytes(),
            "handoff/HANDOFF.md": b"offline handoff\n",
        }
        self.bundle = self.base / "source.tar.gz"
        self.expected, self.manifest = bundle_at(self.bundle, self.files)
        patcher = mock.patch.multiple(
            d, CONFIG_DIR=self.config, STATE_DIR=self.state, DEFAULT_WORKSPACE=self.root,
            DEFAULT_RUNNER_PYTHON=self.runner_python, RELEASES_DIR=self.releases,
            CURRENT_LINK=self.current, UNIT_PATH=self.unit,
            pwd=types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_uid=1234, pw_gid=1234)),
            grp=types.SimpleNamespace(getgrnam=lambda _: types.SimpleNamespace(gr_gid=1234)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("chown", "fchown"):
            patcher = mock.patch.object(d.os, name, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(d.os, "geteuid", return_value=0, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            Path, "symlink_to", lambda link, target, target_is_directory=False: link.write_text(str(target))
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(d.subprocess, "run", side_effect=self.command)
        self.run = patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        if argv[:2] == ["systemctl", "is-active"]:
            return result("", 3)
        if "git" in argv:
            if "--show-toplevel" in argv:
                return result("", 128)
            if "init" in argv:
                (self.root / ".git").mkdir()
            if "add" in argv:
                self.staged = kwargs["input"]
            if "ls-tree" in argv:
                return result(self.staged)
            if "rev-parse" in argv:
                return result(HEAD + "\n")
        if argv[-1] == "migrate":
            return result(json.dumps(c.migrate_policy(self.config / "policy.json")))
        return result()

    def write_policy(self, value=None):
        self.config.mkdir(parents=True, exist_ok=True)
        path = self.config / "policy.json"
        path.write_text(json.dumps(self.policy if value is None else value, indent=2) + "\n")
        return path

    def own_workspace(self):
        self.root.mkdir(parents=True)
        old = {"schema": "tcad-server-source-snapshot-v1", "files": {}}
        (self.root / ".server-codex-snapshot.json").write_text(json.dumps(old))

    def assert_nothing_started(self):
        for args, _ in self.commands:
            self.assertNotIn("start", args)
            self.assertNotIn("enable", args)
            self.assertNotIn("serve", args)
            self.assertNotIn("arm", args)
            self.assertNotIn("ssh", args)
            self.assertNotIn("sdevice", args)
            self.assertNotIn("codex", args)
        self.assertTrue(any(args[-1] == "init" for args, _ in self.commands))

    def test_fresh_install_creates_source_provenance_and_disabled_rendered_unit(self):
        report = d.install(self.bundle, self.expected, RELEASE)
        self.assertTrue(report["source_git"]["created"])
        self.assertFalse(report["service_started"])
        self.assertFalse(report["service_enabled_by_installer"])
        policy = json.loads((self.config / "policy.json").read_text())
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["workspace"], str(self.root))
        self.assertEqual(policy["runner_python"], str(self.runner_python))
        self.assertIn(d.unit_quote(self.root), self.unit.read_text())
        self.assert_nothing_started()

    def test_v1_upgrade_backs_up_disables_and_preserves_explicit_source_bindings(self):
        self.own_workspace()
        legacy = dict(self.policy, schema="tcad-server-codex-v1", enabled=True, readiness={"old": True})
        legacy.pop("plan_file")
        legacy.pop("queue_file")
        policy_path = self.write_policy(legacy)
        original = policy_path.read_bytes()
        report = d.install(self.bundle, self.expected, RELEASE)
        migrated = json.loads(policy_path.read_text())
        self.assertEqual(migrated["schema"], "tcad-server-codex-v2")
        self.assertFalse(migrated["enabled"])
        self.assertIsNone(migrated["readiness"])
        for key in ("workspace", "runner_python", "source_codex_config", "codex_binary", "task_file", "state_dir"):
            self.assertEqual(migrated[key], legacy[key])
        self.assertEqual(Path(report["policy_migration"]["backup"]).read_bytes(), original)
        unit = self.unit.read_text()
        self.assertIn("WorkingDirectory=" + d.unit_scalar_path(self.root), unit)
        self.assertIn("ReadWritePaths=" + d.unit_quote(self.root) + " " + d.unit_quote(self.state), unit)
        self.assertIn("ExecStart=" + d.unit_quote(self.runner_python, command=True), unit)
        self.assert_nothing_started()

    def legacy_task_fixture(self, content):
        self.own_workspace()
        self.write_policy(dict(self.policy, schema="tcad-server-codex-v1"))
        task = Path(self.policy["task_file"])
        task.write_bytes(content)
        old_release = self.releases / "old-release"
        old_release.mkdir(parents=True)
        (old_release / "operator-task.example.md").write_bytes(b"legacy P0/P1 three slots\r\n")
        self.current.write_text(str(old_release))
        # symlink creation is mocked on Windows: model only this old pointer's
        # resolution, while every other resolve keeps its real filesystem check.
        original_resolve = Path.resolve
        patcher = mock.patch.object(
            Path, "resolve", autospec=True,
            side_effect=lambda path, *args, **kwargs: (
                old_release if path == self.current else original_resolve(path, *args, **kwargs)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return task

    def test_v1_exact_old_default_task_is_backed_up_and_replaced_with_same_metadata(self):
        original = b"legacy P0/P1 three slots\r\n"
        task = self.legacy_task_fixture(original)
        os.chmod(task, 0o640)
        metadata = task.stat()
        with mock.patch.object(d.os, "chmod", wraps=os.chmod) as chmod:
            report = d.install(self.bundle, self.expected, RELEASE)
        migrated = report["task_migration"]
        backup = Path(migrated["backup"])
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(task.read_bytes(), self.files["runtime/operator-task.example.md"])
        self.assertEqual(migrated["status"], "task_default_migrated")
        self.assertFalse(migrated["task_preserved_custom"])
        self.assertFalse(migrated["needs_alignment"])
        pending = task.with_name(task.name + ".v2-default-" + RELEASE + ".tmp")
        for path in (backup, pending):
            d.os.chown.assert_any_call(path, metadata.st_uid, metadata.st_gid)
            chmod.assert_any_call(path, metadata.st_mode & 0o7777)
        self.assertEqual(task.stat().st_mode & 0o7777, metadata.st_mode & 0o7777)
        self.assertFalse(pending.exists())
        self.assert_nothing_started()

    def test_v1_custom_task_is_preserved_and_marked_for_alignment(self):
        # Even content matching the NEW default is custom relative to the OLD
        # release, proving that comparison happens before current is switched.
        original = self.files["runtime/operator-task.example.md"]
        task = self.legacy_task_fixture(original)
        report = d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(task.read_bytes(), original)
        self.assertEqual(report["task_migration"]["status"], "task_preserved_custom")
        self.assertTrue(report["task_migration"]["task_preserved_custom"])
        self.assertTrue(report["task_migration"]["needs_alignment"])
        self.assertNotIn("backup", report["task_migration"])
        self.assertFalse(list(task.parent.glob(task.name + ".v1-default-*.bak")))
        with mock.patch.object(Path, "is_symlink", lambda path: path == task):
            with self.assertRaisesRegex(RuntimeError, "existing symlink"):
                d.plan_legacy_task_migration(
                    dict(self.policy, schema="tcad-server-codex-v1"), RELEASE,
                )
        self.assert_nothing_started()

    def test_v1_without_runner_python_uses_migrator_default_without_manual_policy_edit(self):
        self.own_workspace()
        legacy = dict(self.policy, schema="tcad-server-codex-v1")
        legacy.pop("runner_python")
        self.write_policy(legacy)
        default = Path("/opt/tcad-autonomy/python/bin/python3")
        with mock.patch.object(d, "DEFAULT_RUNNER_PYTHON", default):
            d.install(self.bundle, self.expected, RELEASE)
        migrated = json.loads((self.config / "policy.json").read_text())
        self.assertEqual(migrated["runner_python"], default.as_posix())
        self.assertFalse(migrated["enabled"])
        self.assert_nothing_started()

    def test_existing_v2_policy_and_existing_git_index_stay_unchanged(self):
        self.own_workspace()
        (self.root / ".git").mkdir()
        index = self.root / ".git/index"
        index.write_bytes(b"do not mutate existing staged data")
        policy_path = self.write_policy()
        policy_bytes = policy_path.read_bytes()
        report = d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(policy_path.read_bytes(), policy_bytes)
        self.assertEqual(index.read_bytes(), b"do not mutate existing staged data")
        self.assertFalse(report["source_git"]["created"])
        git_commands = [args for args, _ in self.commands if "git" in args]
        self.assertEqual(len(git_commands), 1)
        self.assertEqual(git_commands[0][-3:], ["rev-parse", "--verify", "HEAD"])
        self.assertFalse(any(args[-1] == "migrate" for args, _ in self.commands))
        self.assert_nothing_started()

    def test_existing_unowned_course_workspace_is_refused_before_writes(self):
        self.root = self.base / "projects/course-workspace"
        self.policy["workspace"] = str(self.root)
        self.write_policy()
        self.root.mkdir(parents=True)
        original = self.root / "uncommitted.txt"
        original.write_text("another thread owns this workspace")
        with self.assertRaisesRegex(RuntimeError, "Existing unowned workspace"):
            d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(original.read_text(), "another thread owns this workspace")
        self.assertFalse((self.releases / RELEASE).exists())
        self.assertFalse((self.root / ".git").exists())

    def test_inherited_repository_is_refused_before_any_source_replacement(self):
        self.own_workspace()
        self.write_policy()
        marker = self.root / ".server-codex-snapshot.json"
        previous = marker.read_bytes()

        def commands(argv, **kwargs):
            if "--show-toplevel" in argv:
                return result(str(self.root.parent))
            return self.command(argv, **kwargs)

        self.run.side_effect = commands
        with self.assertRaisesRegex(RuntimeError, "inside another repository"):
            d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(marker.read_bytes(), previous)
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.releases / RELEASE).exists())

    def test_changed_owned_source_is_refused_before_any_replacement(self):
        self.own_workspace()
        self.write_policy()
        source = self.root / "scripts/tcad.py"
        source.parent.mkdir()
        source.write_text("# uncommitted scientific runner changes\n")
        marker = self.root / ".server-codex-snapshot.json"
        old = json.loads(marker.read_text())
        old["files"]["project/scripts/tcad.py"] = hashlib.sha256(b"# previous\n").hexdigest()
        marker.write_text(json.dumps(old))
        with self.assertRaisesRegex(RuntimeError, "Preserve changed server source"):
            d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(source.read_text(), "# uncommitted scientific runner changes\n")
        self.assertFalse((self.releases / RELEASE).exists())

    def test_old_bundle_handoff_conflict_preserves_other_thread_evidence(self):
        self.own_workspace()
        self.write_policy()
        handoff = self.root.parent / "output/server-benchmark-20261115/HANDOFF.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_bytes(b"newer handoff owned by another thread\n")
        original = handoff.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Preserve existing server handoff"):
            d.install(self.bundle, self.expected, RELEASE)
        self.assertEqual(handoff.read_bytes(), original)
        self.assertFalse((self.releases / RELEASE).exists())

    def test_active_controller_is_refused_before_any_installation(self):
        self.run.side_effect = lambda *args, **kwargs: result("", 0)
        with self.assertRaisesRegex(RuntimeError, "Controller is active"):
            d.install(self.bundle, self.expected, RELEASE)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.releases.exists())
        self.assertEqual(self.run.call_count, 1)

    def test_wrong_bundle_hash_is_rejected_without_any_command(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            d.install(self.bundle, "0" * 64, RELEASE)
        self.assertEqual(self.run.call_count, 0)
        self.assertFalse(self.root.exists())

    def test_installer_itself_rejects_a_live_proposal_in_an_old_bundle(self):
        self.files["project/plans/research/work-items.json"] = b'{"tasks":[{"id":"live"}]}'
        expected, _ = bundle_at(self.bundle, self.files)
        with self.assertRaisesRegex(ValueError, "Live execution proposals"):
            d.install(self.bundle, expected, RELEASE)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.releases.exists())

    def test_install_lock_uses_preserved_state_and_closes_without_removing_evidence(self):
        self.write_policy()
        self.state.mkdir()
        lock = self.state / "controller.lock"
        lock.write_bytes(b"original lifecycle lock inode")
        flock = mock.Mock()
        stub = types.SimpleNamespace(flock=flock, LOCK_EX=1, LOCK_NB=2)
        with mock.patch.object(d, "fcntl", stub), \
             mock.patch.object(d.os, "fchmod", create=True):
            with d.controller_install_lock():
                descriptor = flock.call_args.args[0]
                os.fstat(descriptor)
                self.assertEqual(flock.call_args.args[1], 3)
            with self.assertRaises(OSError):
                os.fstat(descriptor)
            self.assertEqual(lock.read_bytes(), b"original lifecycle lock inode")
            flock.side_effect = BlockingIOError("already held")
            with self.assertRaisesRegex(RuntimeError, "manually started controller"):
                with d.controller_install_lock():
                    self.fail("Must not enter the installation critical section")
        self.assertEqual(lock.read_bytes(), b"original lifecycle lock inode")


if __name__ == "__main__":
    unittest.main()
