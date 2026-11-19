"""Edge recovery tests for the detached native runner; all data are local fixtures."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('tcad_edge_recovery', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)


class RunnerEdgeRecoveryTests(unittest.TestCase):
    def test_uncertain_launch_reconnect_only_queries_original_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / 'local_runtime/runs/launch-uncertain'
            run_dir.mkdir(parents=True)
            (run_dir / 'manifest.json').write_text(json.dumps({
                'schema': 'tcad-native-run-r2', 'state': 'LAUNCH_UNCERTAIN',
                'run_id': 'launch-uncertain',
                'remote_directory': '/original/runs/launch-uncertain',
            }))
            with patch.object(tcad, 'ROOT', root), \
                 patch.object(tcad, 'original_ownership'), \
                 patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}) as status, \
                 patch.object(tcad, '_run_project') as submit:
                result = tcad.run_project({'remote_root': '/original'}, ['ssh'], root, 'launch-uncertain', True)
            self.assertEqual(result['status'], 'RUNNING')
            status.assert_called_once_with({'remote_root': '/original'}, ['ssh'], 'launch-uncertain')
            submit.assert_not_called()

    def test_pid_reuse_without_original_exit_remains_unconfirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'runs' / 'original-id'
            proc_root = root / 'proc'
            pid = 4321
            proc = proc_root / str(pid)
            folder.mkdir(parents=True)
            proc.mkdir(parents=True)
            (proc / 'cwd').symlink_to(folder, target_is_directory=True)
            (proc / 'cmdline').write_bytes(b'bash\0./run.sh\0')
            # /proc stat fields after the comm field begin with state (field 3);
            # starttime is field 22, index 19 in this suffix.
            stat_fields = ['S'] + ['0'] * 18 + ['999']
            (proc / 'stat').write_text(f'{pid} (bash) ' + ' '.join(stat_fields))
            (proc_root / 'sys').mkdir(parents=True)
            (proc_root / 'sys/kernel').mkdir()
            (proc_root / 'sys/kernel/random').mkdir()
            (proc_root / 'sys/kernel/random/boot_id').write_text('fixture-boot')
            (folder / 'run.sh').write_text('echo fixture')
            script_hash = hashlib.sha256((folder / 'run.sh').read_bytes()).hexdigest()
            (folder / 'process-identity.json').write_text(json.dumps({
                'cwd': str(folder), 'run_id': folder.name, 'script_sha256': script_hash,
                'pid': pid, 'start_ticks': 123, 'boot_id': 'fixture-boot',
            }))
            code = tcad.STATUS_CODE.replace("Path('/proc')", f"Path({str(proc_root)!r})")
            code = code.replace("Path('/proc/sys/kernel/random/boot_id')", f"Path({str(proc_root / 'sys/kernel/random/boot_id')!r})")
            result = subprocess.run(
                [sys.executable, '-c', code, str(folder), script_hash],
                capture_output=True, text=True, check=True,
            )
            observed = json.loads(result.stdout)
            self.assertFalse(observed['alive'])
            self.assertIsNone(observed['remote_exit_code'])
            self.assertEqual(observed['status'], 'LOST_WITHOUT_EXIT')

    def test_interrupted_collection_can_resume_and_preserves_disconnect_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            payload = {
                'device.cmd': b'input', 'run.sh': b'script', 'result.plt': b'result',
                'exit-code.txt': b'1\n',
                'metadata-sdevice-version-exit-code.txt': b'0\n',
                'step-001-sdevice-exit-code.txt': b'1\n',
            }
            archive = self.make_archive(payload)
            evidence = {
                'schema': 'tcad-native-run-r2', 'state': 'EXECUTED', 'run_id': 'original',
                'remote_directory': '/original/original', 'remote_exit_code': 1,
                'ssh_exit_code': 255,
                'input_sha256': {'device.cmd': hashlib.sha256(b'input').hexdigest()},
                'script_sha256': hashlib.sha256(b'script').hexdigest(),
                'steps': [{'outputs': ['result.plt']}],
                'tool_evidence': {'step-001-sdevice': {'raw_exit_file': 'step-001-sdevice-exit-code.txt'}},
                'tool_exit_codes': {},
            }
            transfer_calls = 0
            remote_commands = []

            def remote(_ssh, command, **kwargs):
                nonlocal transfer_calls
                remote_commands.append(command)
                if 'stdout' in kwargs:
                    transfer_calls += 1
                    stream = kwargs['stdout']
                    stream.write(archive[:37] if transfer_calls == 1 else archive)
                    return type('Result', (), {'returncode': 255 if transfer_calls == 1 else 0})()
                return type('Result', (), {'stdout': json.dumps({
                    'sha256': hashlib.sha256(archive).hexdigest(), 'bytes': len(archive),
                })})()

            def read(_cfg, _id):
                return folder, evidence

            with patch.object(tcad, 'read_manifest', side_effect=read), \
                 patch.object(tcad, 'status_run', return_value={'status': 'FINISHED', 'alive': False}), \
                 patch.object(tcad, 'remote', side_effect=remote), \
                 patch.object(tcad, 'save_manifest'):
                with self.assertRaisesRegex(ValueError, 'Incomplete original archive transfer'):
                    tcad.collect_run({'remote_root': '/original'}, [], 'original')
                self.assertEqual(evidence['ssh_exit_code'], 255)
                result = tcad.collect_run({'remote_root': '/original'}, [], 'original')

            self.assertEqual(result['status'], 'FAILED_COLLECTED')
            self.assertEqual(evidence['ssh_exit_code'], 255)
            self.assertTrue(evidence['collection_verified'])
            self.assertEqual((folder / 'results.tar').read_bytes(), archive)
            self.assertEqual(transfer_calls, 2)
            self.assertTrue(any('exec 9>/original/.solver.lock; flock -n 9' in cmd for cmd in remote_commands))

    def test_runner_retains_shared_lock_and_single_thread_execution(self):
        source = (ROOT / 'scripts/tcad.py').read_text(encoding='utf-8')
        required = [
            "'flock -n 9 || { echo \"Another project run holds the solver lock\"",
            "'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1'",
            "args += ['--threads', '1', '--exit-on-failure']",
            "'taskset -c \"$cpu\"",
        ]
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    @staticmethod
    def make_archive(payload):
        index = {name: {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                 for name, raw in payload.items()}
        payload = dict(payload)
        payload['_collection-members.json'] = json.dumps(index).encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, raw in payload.items():
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        return stream.getvalue()


if __name__ == '__main__':
    unittest.main()
