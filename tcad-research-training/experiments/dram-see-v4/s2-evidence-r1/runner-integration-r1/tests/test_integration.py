"""New-only offline integration checks for the original-runner geometry bridge.

Fixtures remain in an isolated UNIT_FIXTURE_NOT_NATIVE tree. No test creates a
native receipt or invokes a native tool, SSH client, compiler, or trainer.
"""
from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[5]
STAGE = ROOT / 'experiments/dram-see-v4/s2-evidence-r1/runner-integration-r1'
GEOMETRY_STAGE = ROOT / 'experiments/dram-see-v4/s2-evidence-r1/geometry-producer-r1'
GEOMETRY_CANDIDATE = ROOT / 'local_runtime/dram-see-v4/s2-geometry-r1/20261016T135638Z/candidate-r1'
INTEGRATION_CANDIDATE = ROOT / 'local_runtime/dram-see-v4/s2-runner-integration-r1/20261016T155822Z/candidate-r2'
VALIDATION = ROOT / 'local_runtime/dram-see-v4/s2-runner-integration-r1/20261016T155822Z/validation'
PACKAGE = ROOT / 'local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/packages-r2'
sys.path.insert(0, str(STAGE))
import geometry_bridge as bridge  # noqa: E402
import runner_patch  # noqa: E402
sys.path.insert(0, str(GEOMETRY_STAGE / 'tests'))
from test_geometry_producer import build_fixture  # noqa: E402


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def posix_path(path):
    value = Path(path).resolve().as_posix()
    return '/' + value[0].lower() + value[2:] if len(value) > 2 and value[1] == ':' else value


class RunnerGeometryIntegrationTests(unittest.TestCase):
    def setUp(self):
        VALIDATION.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='runner-integration-test-', dir=str(VALIDATION))
        self.base = Path(self.tmp.name)
        self.fixture_index = 0
        self.a0_fixture_index = 0
        self.runner_case_index = 0

    def tearDown(self):
        self.tmp.cleanup()

    def candidate_role(self, role):
        return INTEGRATION_CANDIDATE / 'roles' / role

    def fixture_role(self, role):
        self.fixture_index += 1
        dim = 2 if role == 'B1-D2' else 3
        native_role = self.candidate_role(role)
        plan = read_json(native_role / 'measurement-plan.json')
        folder = self.base / 'UNIT_FIXTURE_NOT_NATIVE' / role / ('fixture-run-' + role + '-' + str(self.fixture_index))
        build_fixture(plan, folder)
        shutil.copyfile(native_role / 'measurement-plan.json', folder / 'measurement-plan.json')
        for name in ('geometry-with-measurements.scm', 'measure-geometry.tcl'):
            shutil.copyfile(native_role / name, folder / name)
        shutil.copyfile(GEOMETRY_STAGE / 'evaluate.py', folder / 'evaluate.py')
        shutil.copyfile(STAGE / 'geometry_bridge.py', folder / 'geometry_bridge.py')
        geometry_contract = PACKAGE / 'roles' / role / 'geometry-contract.json'
        shutil.copyfile(geometry_contract, folder / 'geometry-contract.json')
        fixture_run_id = folder.name
        mesh_identity = folder/'mesh-identity.csv'
        old_mesh_fixture_id = 'fixture-run-' + str(plan['dimension'])
        mesh_identity.write_text(mesh_identity.read_text(encoding='utf-8').replace(old_mesh_fixture_id, fixture_run_id),
                                 encoding='utf-8')
        (folder/'SYNTHETIC_NOT_NATIVE').write_text('synthetic fixture only\n', encoding='utf-8')
        project = dict(schema='s2-review-fixture-project-r1', name='fixture-'+role.lower(), execution_enabled=False,
                       steps=[], s2_geometry=dict(schema='s2-runner-geometry-integration-r1', mode='produce',
                           role_id=role, run_id=fixture_run_id, producer_run_id=fixture_run_id,
                           synthetic=True, execution_enabled=False))
        write_json(folder / 'project.json', project)
        names = ('project.json', 'geometry_bridge.py', 'evaluate.py', 'measurement-plan.json',
                 'geometry-with-measurements.scm', 'measure-geometry.tcl', 'geometry-contract.json')
        write_json(folder / 'input-manifest.json', dict(schema='s2-role-inputs-r1', files_sha256={
            name:digest(folder/name) for name in names}))
        # The generic geometry fixture already contains canonical zero exits.
        # Replace each with its exact original runner member through the bridge.
        for source, canonical in bridge.GEOMETRY_EXITS.items():
            raw = (folder / canonical).read_bytes()
            (folder / source).write_bytes(raw)
            (folder / canonical).unlink()
            self.assertEqual(bridge.geometry_record_exit(folder, source, canonical), 0)
        (folder/'observation-context.json').unlink()
        return folder

    def accepted_synthetic_d3_source(self):
        source = self.fixture_role('B1-D3')
        run_id = read_json(source/'project.json')['s2_geometry']['run_id']
        (source/'cell_msh.log').write_text('SYNTHETIC_NOT_NATIVE mesh fixture\n', encoding='utf-8')
        (source/'exit-code.txt').write_text('0\n', encoding='utf-8')
        result = bridge.geometry_finalize(source, run_id, synthetic_fixture=True)
        report = read_json(source/'geometry-validation.json') if (source/'geometry-validation.json').exists() else {}
        self.assertEqual(result, 0, msg=repr(report.get('errors', report)))
        report_raw = (source/'geometry-validation.json').read_bytes()
        archive_path = source/'results.tar'
        archive_names = set(report['evidence_sha256']) | {
            'geometry-validation.json', 'project.json', 'exit-code.txt', 'cell_msh.tdr', 'cell_msh.log'}
        with tarfile.open(archive_path, 'w') as archive:
            for name in sorted(archive_names):
                archive.add(source/name, arcname=name, recursive=False)
        archive_sha = digest(archive_path)
        manifest = dict(run_id=run_id, state='COLLECTED', origin='synthetic_fixture',
                        synthetic=True, ssh_exit_code=0, remote_exit_code=0, collection_exit_code=0,
                        tool_exit_codes={'step-001-sde':0, 'step-002-snmesh':0,
                                         'step-003-svisual':0, 'step-004-sdevice':0},
                        results_sha256=archive_sha)
        write_json(source/'manifest.json', manifest)
        acceptance = self.base/'d3-reuse-acceptance.json'
        write_json(acceptance, dict(schema='s2-d3-geometry-reuse-acceptance-r1', status='ACCEPTED',
            synthetic=True, origin='synthetic_fixture', source_run_id=run_id,
            source_manifest_sha256=digest(source/'manifest.json'), source_archive_sha256=archive_sha,
            mesh_sha256=digest(source/'cell_msh.tdr'),
            geometry_validation_sha256=hashlib.sha256(report_raw).hexdigest()))
        return source, acceptance, manifest, report

    def a0_fixture(self, source, acceptance, manifest, report, *, conflict=None):
        self.a0_fixture_index += 1
        folder = self.base/'UNIT_FIXTURE_NOT_NATIVE'/'A0'/('fixture-a0-b0-' + str(self.a0_fixture_index))
        folder.mkdir(parents=True)
        (folder/'SYNTHETIC_NOT_NATIVE').write_text('UNIT_FIXTURE_NOT_NATIVE\n', encoding='utf-8')
        cfg = dict(schema='s2-runner-geometry-integration-r1', mode='reuse', role_id='B1-A0-main-b0',
                   run_id='fixture-a0-b0', producer_run_id=read_json(source/'project.json')['s2_geometry']['run_id'], synthetic=True,
                   execution_enabled=False, source_run_directory=str(source.resolve()),
                   acceptance_file=str(acceptance.resolve()))
        write_json(folder/'project.json', dict(schema='s2-project-fixture-r1', name='fixture-a0-b0',
                                               execution_enabled=False, steps=[], s2_geometry=cfg))
        execution = dict(synthetic=True, execution_enabled=False,
                         d3_acceptance_sha256=digest(acceptance),
                         d3_source_manifest_sha256=digest(source/'manifest.json'),
                         d3_source_archive_sha256=digest(source/'results.tar'),
                         d3_producer_run_id=read_json(source/'project.json')['s2_geometry']['run_id'],
                         d3_mesh_sha256=digest(source/'cell_msh.tdr'))
        write_json(folder/'execution-release.json', execution)
        exports = dict(report['evidence_sha256'])
        exports['geometry-validation.json'] = digest(source/'geometry-validation.json')
        exports['cell_msh.tdr'] = digest(source/'cell_msh.tdr')
        exports['cell_msh.log'] = digest(source/'cell_msh.log')
        if conflict:
            (folder/conflict).parent.mkdir(parents=True, exist_ok=True)
            (folder/conflict).write_bytes(b'conflicting fixture bytes\n')
        input_hashes = {'project.json':digest(folder/'project.json')}
        input_hashes.update(exports)
        write_json(folder/'input-manifest.json', dict(schema='s2-role-inputs-r1', files_sha256=input_hashes))
        return folder, cfg, execution, exports

    def run_candidate_with_mock_shell(self, *, failed_tool='', guard_rc=0, finalize_rc=0):
        self.runner_case_index += 1
        case = self.base/('runner-case-' + str(self.runner_case_index))
        case.mkdir()
        runner_path = INTEGRATION_CANDIDATE/'tcad.py.review'
        module = types.ModuleType('s2_runner_candidate_test')
        module.__file__ = str(runner_path)
        exec(compile(runner_path.read_bytes(), str(runner_path), 'exec'), module.__dict__)
        module.ROOT = case/'mock-repo'
        module.ROOT.mkdir()
        run_id = 'mock-run-produce-' + str(self.runner_case_index)
        qroot_win = case/'remote-root'
        qroot_win.mkdir()
        qdir_win = qroot_win/'runs'/run_id
        qdir_win.mkdir(parents=True)
        qroot = posix_path(qroot_win)
        steps = read_json(self.candidate_role('B1-D2')/'project.review.json')['steps']
        project = case/'runner-project'
        project.mkdir()
        cfg_geometry = dict(schema='s2-runner-geometry-integration-r1', mode='produce', role_id='B1-D2',
                            run_id=run_id, producer_run_id=run_id, synthetic=True, execution_enabled=False)
        write_json(project/'project.json', dict(name='unit-runner-project', steps=steps,
                                               execution_enabled=False, s2_geometry=cfg_geometry))
        module.geometry_admit = lambda folder, spec, runner_sha: spec['s2_geometry']
        module.native_capture_shell_lines = lambda: [
            'capture_native_step() {',
            '  local key="$1" tool="$2"; shift 2; shift 1',
            '  printf "capture:%s:%s\\n" "$key" "$tool" >> events.log',
            '  local rc=0; if [[ "$key" == step-* && "$tool" == "$MOCK_FAIL_TOOL" ]]; then rc="$MOCK_STEP_RC"; fi',
            '  printf "%s\\n" "$rc" > "${key}-exit-code.txt"',
            '  if [[ "$key" == metadata-sdevice-version ]]; then return "$rc"; fi',
            '  case "$tool" in',
            '    sde) for x in cell_bnd.tdr cell.cmd sde-contact-measurements.csv sde-contact-probes.csv sde-material-probes.csv sde-geometry-status.txt; do printf x > "$x"; done ;;',
            '    snmesh) printf x > cell_msh.tdr; printf x > cell_msh.log ;;',
            '    svisual) for x in geometry-status.json geometry-inventory.csv mesh-identity.csv material-measurements.csv contact-measurements.csv doping-measurements.csv; do printf x > "$x"; done ;;',
            '    sdevice) for x in idvg_low_dc_des.plt idvg_high_dc_des.plt dc_final_des.tdr dc_des.log; do printf x > "$x"; done ;;',
            '    *) return 125 ;;',
            '  esac',
            '  return "$rc"',
            '}']
        module.execute = lambda args, **kwargs: types.SimpleNamespace(stdout='fixture-commit\n', returncode=0)
        events_remote = []
        def fake_remote(ssh, script, **kwargs):
            events_remote.append(script)
            if 'tar -cf - -C ' in script:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w') as archive:
                    for path in sorted(qdir_win.rglob('*')):
                        if path.is_file():
                            archive.add(path, arcname=path.relative_to(qdir_win).as_posix(), recursive=False)
                kwargs['stdout'].write(buffer.getvalue())
            return types.SimpleNamespace(returncode=0)
        module.remote = fake_remote
        cfg = dict(remote_root=qroot, tool_bin='/mock/native/bin')
        shell_file = qdir_win/'run.sh'
        real_subprocess_run = subprocess.run
        bash_path = Path(r'C:\Program Files\Git\bin\bash.exe')
        self.assertTrue(bash_path.is_file(), 'Git Bash is required for isolated shell mock')
        def fake_subprocess_run(args, **kwargs):
            source_script = (module.ROOT/'local_runtime/runs'/run_id/'run.sh').read_text(encoding='utf-8')
            source_script = source_script.replace('/usr/bin/python3', 'python3')
            prelude = r'''set +e
MOCK_FAIL_TOOL="${MOCK_FAIL_TOOL:-}"
MOCK_STEP_RC="${MOCK_STEP_RC:-17}"
MOCK_GUARD_RC="${MOCK_GUARD_RC:-0}"
MOCK_FINALIZE_RC="${MOCK_FINALIZE_RC:-0}"
flock() { return 0; }
awk() { printf '0\n'; }
date() { printf '2000-01-01T00:00:00Z\n'; }
hostname() { printf 'fixture-host\n'; }
mkdir() { return 0; }
tee() { while IFS= read -r _line; do :; done; }
taskset() {
  if [[ "$1" == -pc ]]; then return 0; fi
  [[ "$1" == -c ]] || return 125; shift 2
  [[ "$1" == python3 ]] || return 125; shift
  python3 "$@"
}
python3() {
  printf 'python:%s\n' "$*" >> events.log
  if [[ "$1" == mesh_resource_guard.py ]]; then return "$MOCK_GUARD_RC"; fi
  if [[ "$1" == geometry_bridge.py ]]; then
    case "$2" in
      record-exit) local src= canonical=; while (($#)); do case "$1" in --source) src="$2"; shift 2 ;; --canonical) canonical="$2"; shift 2 ;; *) shift ;; esac; done; [[ -n "$src" && -f "$src" ]] || return 2; cat -- "$src" > "$canonical"; return $? ;;
      prepare) return 0 ;;
      finalize) return "$MOCK_FINALIZE_RC" ;;
    esac
  fi
  return 125
}
'''
            executable_script = qdir_win/'mock-run.sh'
            executable_script.write_text(prelude+'\n'+source_script, encoding='utf-8')
            proc = real_subprocess_run([str(bash_path), '--noprofile', '--norc', posix_path(executable_script)],
                                       cwd=str(qdir_win), stdout=kwargs.get('stdout'),
                                       stderr=kwargs.get('stderr'),
                                       env={**os.environ, 'MOCK_FAIL_TOOL':failed_tool,
                                            'MOCK_STEP_RC':'17', 'MOCK_GUARD_RC':str(guard_rc),
                                            'MOCK_FINALIZE_RC':str(finalize_rc)})
            return types.SimpleNamespace(returncode=proc.returncode)
        old_run = module.subprocess.run
        module.subprocess.run = fake_subprocess_run
        try:
            error = None
            try:
                module.run_project(cfg, ['mock-ssh-never-run'], project)
            except RuntimeError as exc:
                error = exc
            run_log = module.ROOT/'local_runtime/runs'/run_id
            events = (qdir_win/'events.log').read_text(encoding='utf-8').splitlines()
            manifest = read_json(run_log/'manifest.json')
            console = (run_log/'console.log').read_text(encoding='utf-8', errors='replace')
            return error, events, manifest, qdir_win, events_remote, console
        finally:
            module.subprocess.run = old_run

    def test_candidate_is_closed_and_allocates_only_two_geometry_plus_two_field_extractions(self):
        candidate = read_json(INTEGRATION_CANDIDATE / 'candidate.json')
        budget = read_json(INTEGRATION_CANDIDATE / 'budget-allocation.proposed.json')
        self.assertFalse(candidate['execution_enabled'])
        self.assertEqual(candidate['native_calls'], 0)
        self.assertEqual(candidate['approved_native_calls'], 0)
        self.assertEqual(budget['status'], 'PROPOSAL_NOT_AUTHORIZATION')
        self.assertFalse(budget['approved'])
        self.assertEqual(budget['reservations'], 0)
        self.assertEqual(budget['first_slice_proposed']['native_geometry_extractions'], 2)
        self.assertEqual(budget['first_slice_proposed']['native_field_extractions'], 2)
        self.assertEqual(budget['first_slice_proposed']['total_svisual_invocations'], 4)
        self.assertEqual(sum(x['units'] for x in budget['allocation']), 4)
        self.assertEqual(sum(x['units'] for x in budget['allocation']
                             if x['category']=='native_geometry_extractions'), 2)
        self.assertEqual(sum(x['units'] for x in budget['allocation']
                             if x['category']=='native_field_extractions'), 2)
        self.assertIn('no transfer of nuclear-closure balance', budget['ledger_scope'])

    def test_producer_steps_and_sde_mesh_boundary_guard_order(self):
        role = self.candidate_role('B1-D2')
        spec = read_json(role / 'project.review.json')
        self.assertEqual([step['tool'] for step in spec['steps']], ['sde','snmesh','svisual','sdevice'])
        self.assertEqual([step['tool'] for step in spec['steps']].count('sde'), 1)
        self.assertEqual([step['tool'] for step in spec['steps']].count('snmesh'), 1)
        self.assertEqual([step['tool'] for step in spec['steps']].count('svisual'), 1)
        self.assertEqual([step['tool'] for step in spec['steps']].count('sdevice'), 1)
        cad = (role/'geometry-with-measurements.scm').read_text(encoding='utf-8')
        self.assertNotIn('(sde:build-mesh "snmesh" "" "cell")', cad)
        save_at = cad.index('(sdeio:save-tdr-bnd (get-body-list) "cell_bnd.tdr")')
        cmd_at = cad.index('(sdedr:write-cmd-file "cell.cmd")')
        self.assertLess(save_at, cmd_at)
        self.assertFalse(any('mesh_resource_guard.py' in line and not line.lstrip().startswith(';')
                             for line in cad.splitlines()))
        run_source = (INTEGRATION_CANDIDATE/'tcad.py.review').read_text(encoding='utf-8')
        guard = run_source.index("geometry_bridge.py mesh_resource_guard.py") if "geometry_bridge.py mesh_resource_guard.py" in run_source else run_source.index("'taskset -c \"$cpu\" /usr/bin/python3 mesh_resource_guard.py'")
        prepare = run_source.index("geometry_bridge.py prepare")
        finalize = run_source.index("geometry_bridge.py finalize")
        self.assertLess(guard, prepare)
        self.assertLess(prepare, finalize)

    def test_record_exit_preserves_bytes_nonzero_and_missing_is_not_zero(self):
        folder = self.base / 'exit-capture'
        folder.mkdir()
        for source, canonical in bridge.GEOMETRY_EXITS.items():
            raw = b'17\n' if canonical == 'mesh-exit-code.txt' else b'0\n'
            (folder/source).write_bytes(raw)
            self.assertEqual(bridge.geometry_record_exit(folder, source, canonical), int(raw.strip()))
            self.assertEqual((folder/canonical).read_bytes(), raw)
        with self.assertRaises(ValueError):
            bridge.geometry_exit_sources(folder, complete=False)
        (folder/'step-001-sde-exit-code.txt').unlink()
        (folder/'sde-exit-code.txt').unlink()
        with self.assertRaises(ValueError):
            bridge.geometry_record_exit(folder, 'missing-sde-exit-code.txt', 'sde-exit-code.txt')
        self.assertFalse((folder/'sde-exit-code.txt').exists())

    def test_finalize_binds_actual_run_mesh_and_raw_exit_hashes_without_native_qualification(self):
        folder = self.fixture_role('B1-D2')
        run_id = read_json(folder/'project.json')['s2_geometry']['run_id']
        result = bridge.geometry_finalize(folder, run_id, synthetic_fixture=True)
        diagnostic = read_json(folder/'geometry-validation.json') if (folder/'geometry-validation.json').exists() else {}
        self.assertEqual(result, 0, msg=repr(diagnostic.get('errors', diagnostic)))
        context = read_json(folder/'observation-context.json')
        report = read_json(folder/'geometry-validation.json')
        self.assertEqual(context['producer_run_id'], run_id)
        self.assertEqual(context['mesh_sha256'], digest(folder/'cell_msh.tdr'))
        self.assertEqual(set(context['raw_exit_sha256']), set(bridge.GEOMETRY_EXITS.values()))
        for source, canonical in bridge.GEOMETRY_EXITS.items():
            self.assertEqual(context['raw_exit_sha256'][canonical], digest(folder/canonical))
            self.assertEqual(report['original_exit_sources'][canonical]['source'], source)
            self.assertEqual((folder/source).read_bytes(), (folder/canonical).read_bytes())
        self.assertTrue(report['passed'], report['errors'])
        self.assertTrue(report['synthetic'])
        self.assertEqual(report['origin'], 'synthetic_fixture')
        self.assertFalse(report['native_qualified'])
        self.assertFalse(report['is_tcad_result'])
        self.assertFalse((folder/'geometry-release.json').exists())
        for name, file_sha in report['evidence_sha256'].items():
            self.assertEqual(digest(folder/name), file_sha, name)

    def test_finalize_refuses_wrong_run_missing_exit_and_nonzero_exit(self):
        wrong = self.fixture_role('B1-D2')
        self.assertEqual(bridge.geometry_finalize(wrong, 'different-run', synthetic_fixture=True), 2)
        self.assertFalse((wrong/'geometry-validation.json').exists())
        missing = self.fixture_role('B1-D3')
        (missing/'step-002-snmesh-exit-code.txt').unlink()
        (missing/'mesh-exit-code.txt').unlink()
        missing_run_id = read_json(missing/'project.json')['s2_geometry']['run_id']
        self.assertEqual(bridge.geometry_finalize(missing, missing_run_id, synthetic_fixture=True), 2)
        self.assertFalse((missing/'geometry-validation.json').exists())
        nonzero = self.fixture_role('B1-D2')
        (nonzero/'step-003-svisual-exit-code.txt').write_bytes(b'9\n')
        (nonzero/'svisual-exit-code.txt').unlink()
        self.assertEqual(bridge.geometry_record_exit(nonzero, 'step-003-svisual-exit-code.txt', 'svisual-exit-code.txt'), 9)
        nonzero_run_id = read_json(nonzero/'project.json')['s2_geometry']['run_id']
        self.assertEqual(bridge.geometry_finalize(nonzero, nonzero_run_id, synthetic_fixture=True), 2)
        self.assertFalse((nonzero/'geometry-validation.json').exists())

    def test_native_admission_rejects_review_candidate_and_synthetic_marker(self):
        candidate_role = self.candidate_role('B1-D2')
        spec = read_json(candidate_role/'project.review.json')
        project = self.base/'unreleased-candidate'
        project.mkdir()
        write_json(project/'project.json', spec)
        with self.assertRaises(ValueError):
            bridge.geometry_admit(project, spec, '0'*64)
        with self.assertRaises(ValueError):
            bridge.geometry_new_budget_id('nuclear_postprocess')
        fixture = self.fixture_role('B1-D2')
        with self.assertRaises(ValueError):
            bridge.geometry_runtime(fixture, read_json(fixture/'project.json')['s2_geometry']['run_id'])
        self.assertFalse(read_json(fixture/'project.json')['s2_geometry']['execution_enabled'])

    def test_geometry_reservation_id_must_be_distinct_from_execution_reservation(self):
        project = self.base/'in-memory-native-admission-contract'
        project.mkdir()
        digest_value = 'a'*64
        role, run_id, budget_id, geometry_reservation = 'B1-D2', 's2-unit-run', 's2-new-ledger', 's2-geometry-reservation'
        policy = dict(approved=True, status='RELEASED', region_relative=0.005)
        plan = dict(schema='s2-geometry-measurement-plan-r1', role_id=role, dimension=2,
                    geometry_contract_sha256=digest_value, comparison_policy=policy)
        spec = dict(schema='s2-project-review-r1', role=role, execution_enabled=True,
                    native_threads=1, native_cores=1,
                    steps=[dict(tool=t, args=a) for t,a in bridge.GEOMETRY_STEPS],
                    s2_geometry=dict(schema='s2-runner-geometry-integration-r1', mode='produce',
                        role_id=role, run_id=run_id, producer_run_id=run_id, execution_enabled=True))
        execution = dict(schema='s2-execution-release-r1', status='RELEASED', execution_enabled=True,
                         explicit_native_authorization=True, synthetic=False, scheduler='root', threads=1, cpu_count=1,
                         role_id=role, run_id=run_id, expected_runner_sha256=digest_value,
                         input_manifest_sha256=digest_value, geometry_bridge_sha256=digest_value,
                         budget_id=budget_id, budget_reservation_id='s2-execution-reservation',
                         budget_ledger_sha256=digest_value, authorization_evidence_file='authorization.json',
                         authorization_evidence_sha256=digest_value,
                         geometry_release_sha256=digest_value)
        release = dict(schema='s2-geometry-producer-release-r1', status='RELEASED', execution_enabled=True,
                       explicit_native_authorization=True, synthetic=False, role_id=role, producer_run_id=run_id,
                       input_manifest_sha256=digest_value, plan_sha256=digest_value,
                       evaluator_sha256=digest_value, policy_sha256=digest_value,
                       authorization_sha256=digest_value, budget_reservation_sha256=digest_value,
                       budget_id=budget_id, budget_reservation_id=geometry_reservation)
        reservation = dict(schema='s2-geometry-budget-reservation-r1', status='RESERVED', synthetic=False,
                           category='native_geometry_extractions', units=1, role_id=role, run_id=run_id,
                           budget_id=budget_id, budget_ledger_sha256=digest_value,
                           budget_reservation_id=geometry_reservation)
        authority = dict(synthetic=False, explicit_native_authorization=True, role_ids=[role])
        objects = {
            'project.json':spec, 'execution-release.json':execution,
            'geometry-release.json':release, 'measurement-plan.json':plan,
            'geometry-policy.released.json':policy, 'geometry-budget-reservation.json':reservation,
        }
        hashes = {name:digest_value for name in bridge.GEOMETRY_PRODUCE_INPUTS | {'authorization.json'}}

        def admit(execution_reservation):
            execution['budget_reservation_id'] = execution_reservation
            with mock.patch.object(bridge, 'geometry_json', side_effect=lambda path: objects[Path(path).name]), \
                 mock.patch.object(bridge, 'geometry_digest', return_value=digest_value), \
                 mock.patch.object(bridge, 'geometry_authority', return_value=authority), \
                 mock.patch.object(bridge, 'geometry_resource_precheck', return_value=None), \
                 mock.patch.object(bridge, 'geometry_input_hashes', return_value=hashes):
                return bridge.geometry_admit(project, spec, digest_value)

        # The dictionaries above are transient in-memory gate fixtures. No false
        # native provenance is written to disk or emitted as a receipt.
        with self.assertRaisesRegex(ValueError, 'Geometry reservation scope differs'):
            admit(geometry_reservation)
        self.assertIs(admit('s2-execution-reservation'), spec['s2_geometry'])

    def test_a0_synthetic_copy_preserves_d3_identity_bytes_and_does_not_measure_geometry(self):
        role = self.candidate_role('B1-A0-main-b0')
        spec = read_json(role/'project.review.json')
        self.assertEqual(spec['s2_geometry']['mode'], 'reuse')
        self.assertEqual([step['tool'] for step in spec['steps']], ['sdevice'])
        self.assertFalse(any('geometry' in output or 'cell_msh' in output
                             for step in spec['steps'] for output in step['outputs']))
        source, acceptance, source_manifest, report = self.accepted_synthetic_d3_source()
        a0, cfg, execution, exports = self.a0_fixture(source, acceptance, source_manifest, report)
        self.assertFalse((a0/'cell_msh.tdr').exists())
        self.assertFalse((a0/'geometry-validation.json').exists())
        bundle = bridge.geometry_source_bundle(a0, cfg, execution, synthetic_fixture=True)
        self.assertEqual(bundle['exports'], exports)
        self.assertEqual(bridge.geometry_stage_reuse(a0, cfg, synthetic_fixture=True), cfg)
        self.assertEqual(read_json(a0/'observation-context.json')['producer_run_id'], read_json(source/'project.json')['s2_geometry']['run_id'])
        self.assertEqual(read_json(a0/'geometry-validation.json')['origin'], 'synthetic_fixture')
        self.assertTrue(read_json(a0/'geometry-validation.json')['synthetic'])
        self.assertFalse(read_json(a0/'geometry-validation.json')['native_qualified'])
        for name, expected in exports.items():
            self.assertEqual(digest(a0/name), expected, name)
        with tarfile.open(source/'results.tar', 'r:*') as archive:
            members = bridge.geometry_tar_members(archive)
            for name in ('cell_msh.tdr', 'cell_msh.log', 'geometry-validation.json',
                         'observation-context.json', 'geometry-producer-bindings/input-manifest.json'):
                self.assertEqual((a0/name).read_bytes(), bridge.geometry_tar_bytes(archive, members, name), name)

        bad_mesh_a0, bad_cfg, bad_execution, _ = self.a0_fixture(source, acceptance, source_manifest, report)
        bad_execution['d3_mesh_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            bridge.geometry_source_bundle(bad_mesh_a0, bad_cfg, bad_execution, synthetic_fixture=True)

        conflict_a0, conflict_cfg, _, _ = self.a0_fixture(source, acceptance, source_manifest, report,
                                                            conflict='cell_msh.tdr')
        before = (conflict_a0/'cell_msh.tdr').read_bytes()
        with self.assertRaises(ValueError):
            bridge.geometry_stage_reuse(conflict_a0, conflict_cfg, synthetic_fixture=True)
        self.assertEqual((conflict_a0/'cell_msh.tdr').read_bytes(), before)
        with self.assertRaises(ValueError):
            bridge.geometry_source_bundle(a0, cfg, execution, synthetic_fixture=False)

    def test_runner_shell_control_flow_calls_each_step_once_and_blocks_sdevice_on_failures(self):
        error, events, manifest, _, _, console = self.run_candidate_with_mock_shell()
        self.assertIsNone(error)
        tools = [line.split(':')[2] for line in events if line.startswith('capture:step-')]
        self.assertEqual(tools, ['sde','snmesh','svisual','sdevice'], msg='events='+repr(events)+' console='+console)
        hook_sequence = [line.split(':',1)[1] for line in events if line.startswith('python:')]
        self.assertTrue(any('geometry_bridge.py record-exit' in line and '--source step-001-sde-exit-code.txt' in line
                            and '--canonical sde-exit-code.txt' in line for line in hook_sequence))
        self.assertLess(next(i for i,x in enumerate(hook_sequence) if 'mesh_resource_guard.py' in x),
                        next(i for i,x in enumerate(hook_sequence) if 'geometry_bridge.py prepare' in x))
        self.assertLess(next(i for i,x in enumerate(hook_sequence) if 'geometry_bridge.py prepare' in x),
                        next(i for i,x in enumerate(hook_sequence) if 'geometry_bridge.py finalize' in x))
        self.assertEqual(manifest['tool_exit_codes']['step-001-sde'], 0)
        self.assertEqual(manifest['tool_exit_codes']['step-002-snmesh'], 0)
        self.assertEqual(manifest['tool_exit_codes']['step-003-svisual'], 0)

        error, events, manifest, _, _, console = self.run_candidate_with_mock_shell(failed_tool='snmesh')
        self.assertIsNotNone(error)
        tools = [line.split(':')[2] for line in events if line.startswith('capture:step-')]
        self.assertEqual(tools, ['sde','snmesh'], msg='events='+repr(events)+' console='+console)
        self.assertNotIn('prepare', '\n'.join(events))
        self.assertEqual(manifest['tool_exit_codes']['step-002-snmesh'], 17)
        self.assertEqual(manifest['state'], 'FAILED_COLLECTED')

        error, events, manifest, _, _, console = self.run_candidate_with_mock_shell(finalize_rc=2)
        self.assertIsNotNone(error)
        tools = [line.split(':')[2] for line in events if line.startswith('capture:step-')]
        self.assertEqual(tools, ['sde','snmesh','svisual'], msg='events='+repr(events)+' console='+console)
        self.assertNotIn('sdevice', tools)
        self.assertEqual(manifest['state'], 'FAILED_COLLECTED')

        error, events, manifest, _, _, console = self.run_candidate_with_mock_shell(guard_rc=4)
        self.assertIsNotNone(error)
        tools = [line.split(':')[2] for line in events if line.startswith('capture:step-')]
        self.assertEqual(tools, ['sde','snmesh'], msg='events='+repr(events)+' console='+console)
        self.assertNotIn('svisual', tools)
        self.assertNotIn('sdevice', tools)
        self.assertEqual(manifest['state'], 'FAILED_COLLECTED')


if __name__ == '__main__':
    unittest.main()
