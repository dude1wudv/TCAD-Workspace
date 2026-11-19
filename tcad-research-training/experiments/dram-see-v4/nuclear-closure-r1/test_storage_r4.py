"""Isolated tests for the read-only storage forecast r4 API."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
VALIDATION = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/storage-r4/validation'
STORAGE_PATH = HERE / 'storage_forecast_r4.py'
SPEC = importlib.util.spec_from_file_location('_storage_forecast_r4_tests', STORAGE_PATH)
STORAGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(STORAGE)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def write_tar(path: Path, files: dict[str, bytes]):
    with tarfile.open(path, 'w') as archive:
        for name, data in sorted(files.items()):
            import io
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))


class StorageFixture:
    def __init__(self, root: Path, counts=(1, 100), variable_payloads=(1000, 100), states=()):
        self.root = root.resolve()
        self.operations = self.root / STORAGE.OPERATIONS
        self.runs = self.root / STORAGE.RUNTIME / 'transport/runs'
        self.contract_requests = [{'label': f'hist-{i}', 'event_count': n, 'mode': 'miss', 'arm': 'H'}
                                  for i, n in enumerate(counts)]
        self.future = {'label': 'future-request', 'event_count': 1000008,
                       'mode': 'normal', 'arm': 'H'}
        self.contract_requests.append(self.future)
        self.build_label = 'storage-r4-test-build'
        self.build_path = self.operations / self.build_label
        self.build_path.mkdir(parents=True)
        self.fixed = {
            'transport_matched': b'compiled test binary\n',
            'transport_matched.cc': b'unchanged matched source\n',
            'matched-contract.json': canonical_json({'requests': self.contract_requests}),
            'geometry.hh': b'geometry header\n',
            'geometry-contract.json': canonical_json({'geometry': 'same'}),
            'environment.sh': b'export ENV=test\n',
            'environment-spec.json': canonical_json({'environment': 'same'}),
            'dataset-inventory.json': canonical_json({'inventory': 'same'}),
        }
        self.fixed_hashes = {name: digest(data) for name, data in self.fixed.items()}
        self.build_archive_path = self.build_path / 'results.tar'
        write_tar(self.build_archive_path, self.fixed)
        self.build_operation = {
            'schema': 'dram-see-v4-transport-operation-v1', 'label': self.build_label,
            'state': 'COLLECTED_PENDING_AUDIT', 'ssh_exit_code': 0, 'remote_exit_code': 0,
            'collection_exit_code': 0, 'archive_sha256': digest(self.build_archive_path.read_bytes()),
            'input_sha256': self.fixed_hashes,
        }
        self._write_operation(self.build_path, self.build_operation)
        self._collect(self.build_path, self.fixed)
        self.samples = []
        chosen_states = list(states) + ['COLLECTED_PENDING_AUDIT'] * len(counts)
        for i, (count, payload_size, state) in enumerate(zip(counts, variable_payloads, chosen_states)):
            self.samples.append(self._make_sample(i, count, payload_size, state=state))

    def _write_operation(self, folder, operation):
        (folder / 'operation.json').write_bytes(canonical_json(operation))

    @staticmethod
    def _collect(folder, files):
        collected = folder / 'collected'
        collected.mkdir(exist_ok=True)
        for name, data in files.items():
            path = collected / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def _make_sample(self, index, count, payload_size, *, state='COLLECTED_PENDING_AUDIT', completed=None):
        label = f'hist-{index}'
        request = self.contract_requests[index]
        completed = count if completed is None and state == 'COLLECTED_PENDING_AUDIT' else (completed or 0)
        run = self.runs / label
        run.mkdir(parents=True)
        operation_folder = self.operations / label
        operation_folder.mkdir(parents=True)
        operation_path = operation_folder / 'operation.json'
        archive_path = operation_folder / 'results.tar'
        status_state = 'COMPLETED' if state == 'COLLECTED_PENDING_AUDIT' else 'FAILED'
        native_exit = 0 if status_state == 'COMPLETED' else 2
        operation = {
            'schema': 'dram-see-v4-transport-operation-v1', 'label': label, 'state': state,
            'ssh_exit_code': native_exit, 'remote_exit_code': native_exit,
            'collection_exit_code': 0, 'archive_sha256': None,
            'input_sha256': self.fixed_hashes,
        }
        origin = {'build_operation_path': self.build_path.relative_to(self.root).as_posix(),
                  'build_operation_sha256': digest((self.build_path / 'operation.json').read_bytes())}
        files = dict(self.fixed)
        files.update({
            'request.json': canonical_json(request),
            'status.json': canonical_json({'state': status_state, 'events_completed': completed}),
            'package-origin.json': canonical_json(origin),
            'particles.csv': b'particle inventory; new nuclear species pdg=1000822080\n' + b'x' * payload_size,
            'task.sh': b'per-request task; variable\n',
            'opaque-metadata.bin': b'unknown is variable\n',
        })
        write_tar(archive_path, files)
        operation['archive_sha256'] = digest(archive_path.read_bytes())
        self._write_operation(operation_folder, operation)
        self._collect(operation_folder, files)
        record = {
            'schema': 'dram-see-v4-matched-run-r1', 'run_id': label, 'request': request,
            'runner_exit_code': native_exit, 'remote_exit_code': native_exit,
            'collection_exit_code': 0, 'input_sha256': self.fixed_hashes,
            'output_sha256': {name: digest(data) for name, data in files.items()},
            'operation_evidence': {'path': operation_path.relative_to(self.root).as_posix(),
                                   'sha256': digest(operation_path.read_bytes())},
            'raw_archive': {'path': archive_path.relative_to(self.root).as_posix(),
                            'sha256': digest(archive_path.read_bytes())},
        }
        record_path = run / 'record.json'
        record_path.write_bytes(canonical_json(record))
        for name, data in files.items():
            exported = run / name
            exported.parent.mkdir(parents=True, exist_ok=True)
            exported.write_bytes(data)
        return record_path

    def forecast(self, event_count=None):
        request = dict(self.future)
        if event_count is not None:
            request['event_count'] = event_count
        paths = [sample for sample in self.samples]
        return STORAGE.forecast(request, paths, repository_root=self.root)


class StorageForecastTests(unittest.TestCase):
    def test_read_only_real_n2_forecast_matches_recovery_recalculation(self):
        contract = json.loads((HERE / 'transport-contract-material-r2.json').read_text(encoding='utf-8'))
        request = next(row for row in contract['requests'] if row['label'] == 'nc-r1-h-001')
        real_records = sorted((ROOT / STORAGE.RUNTIME / 'transport/runs').glob('*/record.json'))
        result = STORAGE.forecast(request, real_records)
        self.assertEqual(result['history_count'], 7)
        self.assertEqual(result['estimated_output_bytes'], 7_382_565_812)
        self.assertEqual(result['legacy_estimated_output_bytes'], 13_500_360_000)
        self.assertEqual(result['request'], request)

    def test_fixed_files_are_counted_once_and_unknown_inventory_remains_variable(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1, 100), variable_payloads=(1000, 100))
            result = fixture.forecast()
        expected_fixed = sum(len(v) for v in fixture.fixed.values())
        self.assertEqual(result['fixed_names'], sorted(fixture.fixed))
        self.assertEqual(result['fixed_bytes'], expected_fixed)
        self.assertEqual(result['fixed_history_max_bytes'], expected_fixed)
        for sample in result['history']:
            self.assertIn('particles.csv', sample['variable_files'])
            self.assertIn('opaque-metadata.bin', sample['variable_files'])
            self.assertEqual(sample['fixed_bytes'] + sample['variable_bytes'], sample['total_output_bytes'])
            for key in ('record', 'operation', 'archive', 'build_operation', 'build_archive'):
                self.assertEqual(set(sample[key]), {'path', 'sha256'})
        self.assertEqual(result['estimated_output_bytes'], max(
            result['minimum_forecast_bytes'],
            math.ceil(result['safety_multiplier'] * (expected_fixed + result['variable_per_primary'] * result['request']['event_count']))))

    def test_large_batch_does_not_reduce_variable_history_max(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-max-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1, 100), variable_payloads=(1000, 100))
            result = fixture.forecast()
        max_history = max(row['variable_bytes'] / row['variable_density_denominator'] for row in result['history'])
        self.assertEqual(result['variable_per_primary'], max_history)
        self.assertEqual(result['variable_history_max_record'], [result['history'][0]['record']])
        self.assertGreater(result['variable_per_primary'], result['history'][1]['variable_bytes'] / 100)

    def test_zero_completed_failed_archive_contributes_one_primary_conservative_floor(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-failed-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1,), variable_payloads=(50,), states=('FAILED_COLLECTED',))
            result = fixture.forecast()
        history = result['history'][0]
        self.assertEqual(history['completed_primaries'], 0)
        self.assertEqual(history['variable_density_denominator'], 1)
        self.assertEqual(history['variable_density_basis'], 'zero_completed_archive_conservative_one_primary_floor_not_a_measurement')

    def test_new_inventory_species_and_unknown_files_are_variable(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-inventory-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1,), variable_payloads=(80,))
            row = fixture.forecast()['history'][0]
        self.assertNotIn('particles.csv', row['fixed_files'])
        self.assertIn('particles.csv', row['variable_files'])
        self.assertEqual(row['variable_files']['particles.csv']['classification'], 'variable_or_unproven')
        self.assertIn('opaque-metadata.bin', row['variable_files'])

    def test_zero_or_negative_future_primary_count_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-count-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1,), variable_payloads=(80,))
            for count in (0, -1):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    fixture.forecast(event_count=count)

    def test_archive_or_receipt_tampering_is_rejected(self):
        for change in ('archive', 'recorded-operation-hash', 'collected-output'):
            with self.subTest(change=change), tempfile.TemporaryDirectory(prefix='storage-r4-tamper-', dir=VALIDATION) as temp:
                fixture = StorageFixture(Path(temp), counts=(1,), variable_payloads=(80,))
                sample = fixture.samples[0]
                record = json.loads(sample.read_text(encoding='utf-8'))
                operation_path = fixture.operations / 'hist-0/operation.json'
                if change == 'archive':
                    with (fixture.operations / 'hist-0/results.tar').open('ab') as stream:
                        stream.write(b'changed')
                elif change == 'recorded-operation-hash':
                    record['operation_evidence']['sha256'] = '0' * 64
                    sample.write_bytes(canonical_json(record))
                else:
                    (fixture.runs / 'hist-0/particles.csv').write_bytes(b'different')
                with self.assertRaises(ValueError):
                    fixture.forecast()

    def test_unfinished_operation_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-unfinished-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1,), variable_payloads=(80,))
            operation_path = fixture.operations / 'hist-0/operation.json'
            operation = json.loads(operation_path.read_text(encoding='utf-8'))
            operation['state'] = 'RUNNING'
            operation_path.write_bytes(canonical_json(operation))
            record_path = fixture.samples[0]
            record = json.loads(record_path.read_text(encoding='utf-8'))
            record['operation_evidence']['sha256'] = digest(operation_path.read_bytes())
            record_path.write_bytes(canonical_json(record))
            with self.assertRaisesRegex(ValueError, 'unfinished'):
                fixture.forecast()

    def test_missing_or_duplicate_history_is_not_silently_excluded(self):
        with tempfile.TemporaryDirectory(prefix='storage-r4-history-', dir=VALIDATION) as temp:
            fixture = StorageFixture(Path(temp), counts=(1, 100), variable_payloads=(1000, 100))
            request = fixture.future
            with self.assertRaisesRegex(ValueError, 'every canonical history record'):
                STORAGE.forecast(request, fixture.samples[:1], repository_root=fixture.root)
            with self.assertRaises(ValueError):
                STORAGE.forecast(request, fixture.samples + [fixture.samples[-1]], repository_root=fixture.root)

    def test_forecast_is_inactive_and_has_no_process_submission_calls(self):
        source = STORAGE_PATH.read_text(encoding='utf-8')
        self.assertIn('active=False', source)
        self.assertNotIn('subprocess', source)
        self.assertNotIn('Popen(', source)
        self.assertNotIn('ssh ', source.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
