"""Isolated integration checks for storage-r4 preflight and input recovery."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
VALIDATION = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/storage-r4/validation'
sys.path.insert(0, str(HERE))


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


SUP = load(HERE / 'supervisor_storage_r4.py', '_supervisor_storage_r4_validation')
PREPARED = load(HERE / 'prepared_inputs_r4.py', '_prepared_inputs_r4_validation')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IsolatedCommon:
    def __init__(self, root: Path):
        self.ROOT = root
        self.RT = root / 'runtime'
        self.OLD_OPS = root / 'old-ops'
        self.HERE = root / 'source'
        self.GEOMETRY = self.HERE / 'geometry-contract.json'
        self.writes = []

    @staticmethod
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def encoded(value):
        return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def utc():
        return 'mock-utc'

    @staticmethod
    def ref(path):
        return {'path': str(Path(path))}

    def write(self, path, value, **kwargs):
        path = Path(path)
        self.writes.append((path, value, kwargs))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.encoded(value))

    @staticmethod
    def read(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))


class StoragePreflightTests(unittest.TestCase):
    GIB = 1024 ** 3
    FORECAST = 8192

    def run_preflight(self, *, local_free, remote_free, available, used, stage):
        with tempfile.TemporaryDirectory(prefix='preflight-r4-', dir=VALIDATION) as temp:
            root = Path(temp)
            common = IsolatedCommon(root)
            runs = common.RT / 'transport/runs'
            runs.mkdir(parents=True)
            history = runs / 'existing/record.json'
            history.parent.mkdir()
            history.write_text('{}', encoding='utf-8')
            request = {'label': 'isolated-future', 'event_count': 50}
            budgets = {'minimum_local_free_GiB': 20, 'minimum_remote_free_GiB': 8,
                       'minimum_remote_available_memory_GiB': 2, 'storage_GiB': 160}
            common.contract = lambda: {'budgets': budgets}
            local = types.SimpleNamespace(free=local_free)
            fake_shutil = types.SimpleNamespace(disk_usage=lambda _path: local)
            remote = {'active_solver_lines': [], 'values': {
                'LOCK_FREE': 1, 'FREE_KIB': remote_free / 1024,
                'AVAILABLE_MEMORY_KIB': available / 1024, 'STAGE_KIB': stage / 1024,
            }}
            cost = types.SimpleNamespace(forecast=lambda observed, records: {
                'request': observed, 'records': [Path(path).as_posix() for path in records],
                'estimated_output_bytes': self.FORECAST,
            })
            with patch.object(SUP, 'c', common), patch.object(SUP, 'shutil', fake_shutil), \
                 patch.object(SUP, 'local_processes', return_value=[]), \
                 patch.object(SUP, 'assert_no_competing_scheduler', return_value=None), \
                 patch.object(SUP, 'remote_probe', return_value=remote), \
                 patch.object(SUP, 'storage_bytes', return_value=used), \
                 patch.object(SUP, 'budget', return_value={'fixture': True}), \
                 patch.dict(sys.modules, {'storage_forecast_r4': cost}):
                try:
                    ref = SUP.preflight('isolated', request)
                    error = None
                except (ValueError, RuntimeError) as exc:
                    ref, error = None, exc
            return common, error, ref, request, history

    def test_local_remote_memory_and_combined_storage_boundaries(self):
        forecast = self.FORECAST
        local_floor = 20 * self.GIB + 3 * forecast
        remote_floor = 8 * self.GIB + forecast
        memory_floor = 2 * self.GIB
        storage_cap = 160 * self.GIB

        _, error, ref, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor,
            available=memory_floor, used=0, stage=0)
        self.assertIsNone(error)
        self.assertIsNotNone(ref)
        _, error, _, _, _ = self.run_preflight(local_free=local_floor + 1, remote_free=remote_floor,
            available=memory_floor, used=0, stage=0)
        self.assertIsNone(error)
        _, error, _, _, _ = self.run_preflight(local_free=local_floor - 1, remote_free=remote_floor,
            available=memory_floor, used=0, stage=0)
        self.assertRegex(str(error), 'Local free storage')
        _, error, _, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor + 1,
            available=memory_floor, used=0, stage=0)
        self.assertIsNone(error)
        _, error, _, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor - 1,
            available=memory_floor, used=0, stage=0)
        self.assertRegex(str(error), 'Remote free storage')
        _, error, _, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor,
            available=memory_floor + 1, used=0, stage=0)
        self.assertIsNone(error)
        _, error, _, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor,
            available=memory_floor - 1, used=0, stage=0)
        self.assertRegex(str(error), 'Remote memory')

        # The retained-storage cap is strict: cap-1 passes; cap and cap+1 fail.
        for delta, should_pass in ((-1, True), (0, False), (1, False)):
            with self.subTest(cap_delta=delta):
                _, error, _, _, _ = self.run_preflight(local_free=local_floor, remote_free=remote_floor,
                    available=memory_floor, used=storage_cap - 4 * forecast + delta, stage=0)
                self.assertEqual(error is None, should_pass)

    def test_preflight_binds_forecast_input_history_and_records_isolated_evidence(self):
        forecast = self.FORECAST
        common, error, ref, request, history = self.run_preflight(local_free=100 * self.GIB,
            remote_free=100 * self.GIB, available=10 * self.GIB, used=0, stage=0)
        self.assertIsNone(error)
        self.assertIsNotNone(ref)
        detail = common.writes[0][1]['transport_forecast_evidence']
        self.assertEqual(detail['request'], request)
        self.assertEqual(detail['records'], [history.as_posix()])


class SupervisorAndPreparedInputTests(unittest.TestCase):
    def test_operation_function_ast_matches_material_r2_exactly(self):
        old = ast.parse((HERE / 'supervisor_material_r2.py').read_text(encoding='utf-8'))
        new = ast.parse((HERE / 'supervisor_storage_r4.py').read_text(encoding='utf-8'))
        old_operation = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == 'operation')
        new_operation = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == 'operation')
        self.assertEqual(ast.dump(old_operation, include_attributes=False), ast.dump(new_operation, include_attributes=False))

    def test_scheduler_ancestor_is_allowed_but_unrelated_scheduler_is_rejected(self):
        base = SUP.base
        with patch.object(base, 'assert_no_competing_scheduler', return_value=None), \
             patch.object(SUP.os, 'getpid', return_value=100):
            ancestor_rows = [
                {'ProcessId': 100, 'ParentProcessId': 200, 'CommandLine': 'python worker.py'},
                {'ProcessId': 200, 'ParentProcessId': 1, 'CommandLine': 'python continue_storage_r4.py'},
            ]
            SUP.assert_no_competing_scheduler(ancestor_rows)
            competitor = ancestor_rows + [
                {'ProcessId': 300, 'ParentProcessId': 1, 'CommandLine': 'python continue_audit_r3.py'},
            ]
            with self.assertRaisesRegex(RuntimeError, 'Other live scheduler PID 300'):
                SUP.assert_no_competing_scheduler(competitor)

    def test_expected_inputs_reconstructs_real_n2_package_bytes_without_writes(self):
        import common as c
        import transport_material_r2 as transport
        old_ops = c.OLD_OPS
        label = 'nc-r1-h-001'
        build = old_ops / 'operations/nc-r1-transport-build-material-r2'
        package = old_ops / 'inputs' / label
        self.assertTrue(package.is_dir(), 'Original N2 prepared package is missing')
        self.assertFalse((c.RT / 'attempts' / (label + '.json')).exists())
        self.assertFalse((old_ops / 'operations' / label).exists())
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in package.iterdir() if path.is_file()}
        expected = PREPARED.expected_inputs(label, build)
        expected_hashes = {name: sha(raw) for name, raw in expected.items()}
        self.assertEqual(set(before), set(expected_hashes))
        self.assertEqual(before, expected_hashes)

    def test_prepared_package_tamper_unknown_entry_attempt_and_operation_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='prepared-input-r4-', dir=VALIDATION) as temp:
            root = Path(temp)
            fake = IsolatedCommon(root)
            fake.OLD_OPS.mkdir(parents=True)
            fake.RT.mkdir(parents=True)
            request = {'label': 'isolated-label', 'mode': 'init', 'event_count': 0}
            expected = {'binary': b'fixed binary\n', 'request.json': b'fixed request\n'}
            class FakeTransport:
                @staticmethod
                def request(_label): return request
                @staticmethod
                def assert_operation_complete(_build): return True
                @staticmethod
                def header(_contract): return 'header\n'
                @staticmethod
                def contract(): return {'frozen': True}
                @staticmethod
                def prepare(*_args): raise AssertionError('Unexpected package preparation')
            PREPARED.c = fake
            PREPARED.t = FakeTransport
            build = root / 'build'
            collected = build / 'collected'
            collected.mkdir(parents=True)
            (build / 'operation.json').write_bytes(b'operation receipt')
            sources = fake.HERE
            sources.mkdir()
            for name, content in [('transport_material_r2.cc', b'cc'),
                                  ('transport_material_r2.py', b'control source'),
                                  ('transport-contract-material-r2.json', b'contract'),
                                  ('geometry-contract.json', b'geometry')]:
                (sources / name).write_bytes(content)
            fake.GEOMETRY = sources / 'geometry-contract.json'
            for name, content in {
                'transport_matched': b'binary', 'transport_matched.cc': b'cc',
                'matched-contract.json': b'contract', 'geometry.hh': b'header\n',
                'geometry-contract.json': b'geometry', 'environment.sh': b'env',
                'dataset-inventory.json': b'data', 'environment-spec.json': b'spec',
            }.items():
                (collected / name).write_bytes(content)

            generated = PREPARED.expected_inputs(request['label'], build)
            folder = fake.OLD_OPS / 'inputs' / request['label']
            folder.mkdir(parents=True)
            for name, data in generated.items(): (folder / name).write_bytes(data)
            (folder / 'unregistered.bin').write_bytes(b'unknown')
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                PREPARED.reuse_or_prepare(request['label'], build)
            (folder / 'unregistered.bin').unlink()
            (folder / 'task.sh').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'bytes differ'):
                PREPARED.reuse_or_prepare(request['label'], build)
            (folder / 'task.sh').write_bytes(generated['task.sh'])
            attempt = fake.RT / 'attempts' / (request['label'] + '.json')
            attempt.parent.mkdir(parents=True)
            attempt.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'Attempt already exists'):
                PREPARED.reuse_or_prepare(request['label'], build)
            attempt.unlink()
            operation = fake.OLD_OPS / 'operations' / request['label']
            operation.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'Original operation exists'):
                PREPARED.reuse_or_prepare(request['label'], build)

    def test_storage_continuation_checks_release_and_routes_unlaunched_input_to_recovery_helper(self):
        continuation = load(HERE / 'continue_storage_r4.py', '_continue_storage_r4_mock_integration')
        with tempfile.TemporaryDirectory(prefix='continue-storage-r4-', dir=VALIDATION) as temp:
            root = Path(temp)
            request = {'label': 'nc-r1-h-mock', 'closure_stage': 'N2', 'event_count': 2}
            contract = {'transport': {'stage_order': ['N2']}}
            fake_c = IsolatedCommon(root)
            fake_c.contract = lambda: contract
            fake_c.HERE.mkdir(parents=True)
            (fake_c.HERE / 'contract.json').write_text('{}', encoding='utf-8')
            (fake_c.HERE / 'release-storage-r4.json').write_bytes(fake_c.encoded({
                'execution_enabled': True, 'contract_sha256': fake_c.sha(fake_c.HERE / 'contract.json'), 'files': []}))
            build_label = 'mock-build'
            build_attempt = fake_c.RT / 'attempts' / (build_label + '.json')
            build_attempt.parent.mkdir(parents=True)
            build_attempt.write_text('{}', encoding='utf-8')
            calls = []
            class FakeSupervisor:
                @staticmethod
                def operation(label, inputs, kind, request=None, **kwargs):
                    calls.append(('operation', label, kind, Path(inputs)))
                    return root / 'mock-operation'
                @staticmethod
                def assert_operation_complete(_path): return True
                @staticmethod
                def update_status(**_kwargs): calls.append(('status',))
            class FakePrepared:
                @staticmethod
                def reuse_or_prepare(label, build):
                    calls.append(('reuse_or_prepare', label, Path(build)))
                    return fake_c.OLD_OPS / 'inputs' / label
            class FakeTransport:
                BUILD_LABEL = build_label
                @staticmethod
                def check_release(): calls.append(('audit_release',))
                @staticmethod
                def assert_operation_complete(_path): return True
                @staticmethod
                def contract(): return {'requests': [request]}
                @staticmethod
                def collect(_operation): calls.append(('collect',))
                @staticmethod
                def audit(_label): return {'passed': True}
                @staticmethod
                def choose(_stage): return None
            continuation.c, continuation.s = fake_c, FakeSupervisor
            continuation.prepared, continuation.t = FakePrepared, FakeTransport
            result = continuation.transport_stage()
            self.assertFalse(result)
            self.assertEqual(calls[0], ('audit_release',))
            recovery_index = next(i for i, call in enumerate(calls) if call[0] == 'reuse_or_prepare')
            transport_index = next(i for i, call in enumerate(calls)
                                   if call[0] == 'operation' and call[2] == 'transport')
            self.assertLess(recovery_index, transport_index)
            self.assertIn(('reuse_or_prepare', request['label'], root / 'old-ops/operations/mock-build'), calls)
            self.assertGreaterEqual(sum(call[0] == 'audit_release' for call in calls), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
