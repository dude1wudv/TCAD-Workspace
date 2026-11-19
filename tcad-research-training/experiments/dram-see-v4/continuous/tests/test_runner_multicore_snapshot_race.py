"""Deterministic /proc races; no SSH, solver, or production resource changes.

Run with unittest alongside test_runner_multicore.py. On Linux, opt in to
read-only sampling of this test process's short-lived threads with
TCAD_SNAPSHOT_LINUX_CHURN=1.
"""
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
LOG_ROOT = (ROOT / 'local_runtime/server-codex/operations/'
            '20261117T1530Z-snapshot-race/tests')


def load_without_bytecode(path, name):
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


fixtures = load_without_bytecode(
    Path(__file__).with_name('test_runner_multicore.py'), '_snapshot_race_fixtures')


class SnapshotRaceTests(unittest.TestCase):
    stat = staticmethod(fixtures.MulticoreTests.stat)
    status = staticmethod(fixtures.MulticoreTests.status)
    snapshot = fixtures.MulticoreTests.snapshot
    process = fixtures.MulticoreTests.process

    def setUp(self):
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='proc-race-', dir=LOG_ROOT)
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.proc = self.tmp / 'proc'
        self.proc.mkdir()
        self.directory = '/home/tcad/research-training/runs/new'
        self.tcad = load_without_bytecode(ROOT / 'scripts/tcad.py', '_snapshot_race_tcad')
        self.helpers = self.tcad._MULTICORE_HELPERS
        self.base = self.process(self.proc)
        self.original_read = Path.read_text
        self.original_glob = Path.glob
        self.reads = []
        sleep_patch = patch('time.sleep')
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        readlink_patch = patch('os.readlink', return_value=self.directory)
        readlink_patch.start()
        self.addCleanup(readlink_patch.stop)

    def sample(self, ticks=20):
        return self.helpers['mc_snapshot'](
            self.proc, 101, [0, 1], None, self.directory, ticks)

    def record_reads(self, effect=None):
        def read(path, *args, **kwargs):
            self.reads.append(path)
            if effect is not None:
                value = effect(path)
                if value is not None:
                    return value
            return self.original_read(path, *args, **kwargs)
        return patch.object(Path, 'read_text', read)

    def fault_after_open(self, target, effect):
        """Open a real fixture file, then inject an error from its read()."""
        original_open = Path.open

        def opened(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if path != target or mode != 'r':
                return stream

            class FaultingReader:
                def __enter__(self):
                    stream.__enter__()
                    return self

                def __exit__(self, *error):
                    return stream.__exit__(*error)

                def read(self, *read_args, **read_kwargs):
                    effect(path)
                    return stream.read(*read_args, **read_kwargs)

            return FaultingReader()

        return patch.object(Path, 'open', opened)

    def change_members(self, tids):
        """Only mutate the temporary fixture, never a real /proc tree."""
        for folder in (self.base / 'task').iterdir():
            if int(folder.name) not in tids:
                for name in ('stat', 'status'):
                    (folder / name).unlink()
                folder.rmdir()
        raw = self.status(101, 100, 'sdevice', len(tids), '0-1')
        (self.base / 'status').write_text(raw)
        for tid in tids:
            folder = self.base / 'task' / str(tid)
            folder.mkdir(exist_ok=True)
            (folder / 'stat').write_text(self.stat(tid, 100, 'sdevice', 20 + tid - 101))
            (folder / 'status').write_text(
                self.status(tid, 100, 'sdevice', len(tids), '0-1', 101))

    def assert_complete(self, actual, tids):
        self.assertEqual(actual['schema'], 'tcad-task-resource-snapshot-r1')
        self.assertEqual(actual['threads'], len(tids))
        self.assertEqual([task['tid'] for task in actual['tasks']], tids)
        self.assertEqual(actual['status'], self.original_read(self.base / 'status'))
        for task in actual['tasks']:
            self.assertEqual(task['status'], self.original_read(
                self.base / 'task' / str(task['tid']) / 'status'))
        self.assertIs(self.helpers['mc_validate'](
            actual, [0, 1], None, 101, 20, self.directory), actual)

    def test_thread_disappears_after_enumeration_then_entire_snapshot_is_reacquired(self):
        disappeared = []

        def effect(path):
            if path == self.base / 'task/103/stat' and not disappeared:
                disappeared.append(path)
                self.change_members([101, 102])
                raise FileNotFoundError(2, 'thread exited after enumeration', str(path))

        with self.record_reads(effect):
            actual = self.sample()
        self.assert_complete(actual, [101, 102])
        self.assertEqual(len(disappeared), 1)
        # Both reads of the surviving main task must be repeated; skipping the
        # vanished worker would retain its stale Threads: 3 observations.
        self.assertEqual(self.reads.count(self.base / 'task/101/stat'), 4)
        self.sleep.assert_called_once_with(0.01)

    def test_continuous_thread_disappearance_fails_after_eight_whole_attempts(self):
        failures = []

        def effect(path):
            if path == self.base / 'task/103/stat':
                failures.append(path)
                raise FileNotFoundError(2, 'thread exited after enumeration', str(path))

        with self.record_reads(effect), self.assertRaises(FileNotFoundError):
            self.sample()
        self.assertEqual(len(failures), 8)
        self.assertEqual(self.reads.count(self.base / 'status'), 8)
        self.assertEqual(self.reads.count(self.base / 'task/101/stat'), 16)
        self.assertEqual(self.sleep.call_count, 7)
        self.assertTrue(all(call.args == (0.01,) for call in self.sleep.call_args_list))

    def test_task_esrch_after_open_reacquires_the_entire_snapshot(self):
        for filename, failure_read in (('stat', 1), ('status', 1), ('stat', 2)):
            with self.subTest(filename=filename, failure_read=failure_read):
                self.change_members([101, 102, 103])
                self.reads.clear()
                self.sleep.reset_mock()
                target = self.base / 'task/103' / filename
                task_reads = []
                # Remove the exited worker only after the open stream has been
                # closed, so this real-file fixture also works on Windows.
                self.sleep.side_effect = lambda delay: self.change_members([101, 102])

                def effect(path):
                    task_reads.append(path)
                    if len(task_reads) == failure_read:
                        raise ProcessLookupError(errno.ESRCH, 'No such process', str(path))

                try:
                    with self.record_reads(), self.fault_after_open(target, effect):
                        actual = self.sample()
                    self.assert_complete(actual, [101, 102])
                    self.assertEqual(len(task_reads), failure_read)
                    self.assertEqual(self.reads.count(self.base / 'task/101/stat'), 4)
                    self.sleep.assert_called_once_with(0.01)
                finally:
                    self.sleep.side_effect = None

    def test_continuous_task_esrch_is_bounded_and_preserves_the_original_cause(self):
        for filename in ('stat', 'status'):
            with self.subTest(filename=filename):
                self.reads.clear()
                self.sleep.reset_mock()
                target = self.base / 'task/103' / filename
                failures = []

                def effect(path):
                    error = ProcessLookupError(errno.ESRCH, 'No such process', str(path))
                    failures.append(error)
                    raise error

                with self.record_reads(), self.fault_after_open(target, effect), \
                        self.assertRaises(self.helpers['MCTransientSnapshotError']) as caught:
                    self.sample()
                self.assertEqual(len(failures), 8)
                self.assertIs(caught.exception.__cause__, failures[-1])
                self.assertEqual(caught.exception.__cause__.errno, errno.ESRCH)
                self.assertEqual(self.reads.count(self.base / 'status'), 8)
                self.assertEqual(self.reads.count(self.base / 'task/101/stat'), 16)
                self.assertEqual(self.sleep.call_count, 7)
                self.assertTrue(all(call.args == (0.01,) for call in self.sleep.call_args_list))

    def test_same_count_membership_replacement_reacquires_all_members(self):
        enumerations = []

        def glob(path, pattern, *args, **kwargs):
            if path == self.base / 'task':
                enumerations.append(path)
                if len(enumerations) == 2:
                    self.change_members([101, 102, 104])
            return self.original_glob(path, pattern, *args, **kwargs)

        with patch.object(Path, 'glob', glob), self.record_reads():
            actual = self.sample()
        self.assert_complete(actual, [101, 102, 104])
        self.assertGreaterEqual(self.reads.count(self.base / 'task/101/stat'), 4)
        self.sleep.assert_called_once_with(0.01)

    def test_process_threads_change_between_status_reads_reacquires_whole_snapshot(self):
        statuses = []

        def effect(path):
            if path == self.base / 'status':
                statuses.append(path)
                if len(statuses) == 2:
                    self.change_members([101, 102, 103, 104])

        with self.record_reads(effect):
            actual = self.sample()
        self.assert_complete(actual, [101, 102, 103, 104])
        self.assertGreaterEqual(self.reads.count(self.base / 'task/101/stat'), 4)
        self.sleep.assert_called_once_with(0.01)

    def test_task_threads_change_during_sampling_reacquires_whole_snapshot(self):
        changed = []

        def effect(path):
            if path == self.base / 'task/103/status' and not changed:
                changed.append(path)
                return self.status(103, 100, 'sdevice', 4, '0-1', 101)

        with self.record_reads(effect):
            actual = self.sample()
        self.assert_complete(actual, [101, 102, 103])
        self.assertGreaterEqual(self.reads.count(self.base / 'task/101/stat'), 4)
        self.sleep.assert_called_once_with(0.01)

    def test_cpu_escape_is_rejected_without_retry_even_if_next_read_would_be_valid(self):
        for relative in ('status', 'task/103/status'):
            with self.subTest(relative=relative):
                invalid = []
                self.sleep.reset_mock()

                def effect(path):
                    if path == self.base / relative and not invalid:
                        invalid.append(path)
                        return self.original_read(path).replace('0-1', '8')

                with self.record_reads(effect), self.assertRaisesRegex(ValueError, 'CPU'):
                    self.sample()
                self.assertEqual(len(invalid), 1)
                self.sleep.assert_not_called()

    def test_observed_tid_cpu_escape_cannot_be_masked_by_later_thread_churn(self):
        for race in ('disappearing_tid', 'changed_threads'):
            with self.subTest(race=race):
                self.change_members([101, 102, 103])
                self.reads.clear()
                self.sleep.reset_mock()
                invalid = []
                # If the CPU violation were incorrectly discarded by a retry,
                # the next observation would be entirely valid.
                self.sleep.side_effect = lambda delay: self.change_members([101, 102, 103])

                def effect(path):
                    if path == self.base / 'task/102/status' and not invalid:
                        invalid.append(path)
                        if race == 'disappearing_tid':
                            (self.base / 'task/103/stat').unlink()
                        else:
                            (self.base / 'task/103/status').write_text(
                                self.status(103, 100, 'sdevice', 4, '0-1', 101))
                        return self.original_read(path).replace('0-1', '8')

                try:
                    with self.record_reads(effect), self.assertRaisesRegex(ValueError, 'CPU'):
                        self.sample()
                    self.assertEqual(len(invalid), 1)
                    self.assertNotIn(self.base / 'task/103/stat', self.reads)
                    self.sleep.assert_not_called()
                finally:
                    self.sleep.side_effect = None

    def test_original_process_ticks_change_is_rejected_without_retry(self):
        stats = []

        def effect(path):
            if path == self.base / 'stat':
                stats.append(path)
                # One identity anchor, then the attempt's before/after reads.
                if len(stats) == 3:
                    return self.stat(101, 100, 'sdevice', 21)

        with self.record_reads(effect), self.assertRaises(ValueError):
            self.sample()
        self.assertEqual(len(stats), 3)
        self.sleep.assert_not_called()

    def test_wrong_original_start_ticks_is_rejected_without_retry(self):
        with self.record_reads(), self.assertRaisesRegex(ValueError, 'identity'):
            self.sample(ticks=19)
        self.assertNotIn(self.base / 'task/103/stat', self.reads)
        self.sleep.assert_not_called()

    def test_pid_reuse_between_retries_is_rejected_when_caller_omits_ticks(self):
        disappeared = []

        def effect(path):
            if path == self.base / 'task/103/stat' and not disappeared:
                disappeared.append(path)
                # Model a replacement process which would otherwise present a
                # complete, internally consistent snapshot on the next attempt.
                replacement = self.stat(101, 100, 'sdevice', 99)
                (self.base / 'stat').write_text(replacement)
                (self.base / 'task/101/stat').write_text(replacement)
                raise FileNotFoundError(2, 'old worker exited', str(path))

        with self.record_reads(effect), self.assertRaisesRegex(ValueError, 'identity'):
            self.sample(ticks=None)
        self.assertEqual(len(disappeared), 1)
        self.assertEqual(self.reads.count(self.base / 'status'), 1)
        self.sleep.assert_called_once_with(0.01)

    def test_permission_error_is_propagated_without_retry(self):
        for relative in ('stat', 'status', 'task/103/stat', 'task/103/status'):
            with self.subTest(relative=relative):
                self.sleep.reset_mock()
                denied = PermissionError(13, 'resource audit denied', str(self.base / relative))

                def effect(path):
                    if path == self.base / relative:
                        raise denied

                with self.record_reads(effect), self.assertRaises(PermissionError) as caught:
                    self.sample()
                self.assertIs(caught.exception, denied)
                self.sleep.assert_not_called()

    def test_ordinary_value_error_is_propagated_without_retry(self):
        self.sleep.reset_mock()
        invalid = []

        def effect(path):
            if path == self.base / 'task/103/status' and not invalid:
                invalid.append(path)
                return self.original_read(path).replace('0-1', '1-0')

        with self.record_reads(effect), self.assertRaises(ValueError):
            self.sample()
        self.assertEqual(len(invalid), 1)
        self.sleep.assert_not_called()

    def test_missing_process_files_are_not_treated_as_a_disappearing_thread(self):
        for relative in ('stat', 'status'):
            with self.subTest(relative=relative):
                self.sleep.reset_mock()
                missing = []

                def effect(path):
                    if path == self.base / relative and not missing:
                        missing.append(path)
                        raise FileNotFoundError(2, 'original process disappeared', str(path))

                with self.record_reads(effect), self.assertRaises(FileNotFoundError):
                    self.sample()
                self.sleep.assert_not_called()
        with self.subTest(relative='cwd'):
            self.sleep.reset_mock()
            missing = FileNotFoundError(
                2, 'original process cwd disappeared', str(self.base / 'cwd'))
            with patch('os.readlink', side_effect=missing), \
                    self.assertRaises(FileNotFoundError) as caught:
                self.sample()
            self.assertIs(caught.exception, missing)
            self.sleep.assert_not_called()

    def test_original_process_esrch_after_open_is_propagated_without_retry(self):
        for filename, failure_read in (
                ('stat', 1), ('stat', 2), ('stat', 3), ('status', 1), ('status', 2)):
            with self.subTest(filename=filename, failure_read=failure_read):
                self.sleep.reset_mock()
                target = self.base / filename
                process_reads = []
                gone = ProcessLookupError(errno.ESRCH, 'No such process', str(target))

                def effect(path):
                    process_reads.append(path)
                    if len(process_reads) == failure_read:
                        raise gone

                with self.fault_after_open(target, effect), \
                        self.assertRaises(ProcessLookupError) as caught:
                    self.sample()
                self.assertIs(caught.exception, gone)
                self.assertEqual(len(process_reads), failure_read)
                self.sleep.assert_not_called()
        with self.subTest(filename='cwd'):
            self.sleep.reset_mock()
            gone = ProcessLookupError(
                errno.ESRCH, 'No such process', str(self.base / 'cwd'))
            with patch('os.readlink', side_effect=gone), \
                    self.assertRaises(ProcessLookupError) as caught:
                self.sample()
            self.assertIs(caught.exception, gone)
            self.sleep.assert_not_called()


@unittest.skipUnless(
    sys.platform.startswith('linux') and os.environ.get('TCAD_SNAPSHOT_LINUX_CHURN') == '1',
    'opt-in Linux thread churn sampling; no Linux /proc on Windows')
class LinuxThreadChurnTests(unittest.TestCase):
    def test_read_only_sampling_during_real_short_thread_churn(self):
        tcad = load_without_bytecode(ROOT / 'scripts/tcad.py', '_linux_snapshot_race_tcad')
        proc = Path('/proc')
        pid = os.getpid()
        ticks = int((proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19])
        cpus = sorted(os.sched_getaffinity(0))
        cwd = os.getcwd()
        started = threading.Event()
        stopped = threading.Event()
        workers = []

        def churn():
            started.set()
            try:
                for unused in range(100):
                    if stopped.is_set():
                        break
                    worker = threading.Thread(target=lambda: stopped.wait(0.002))
                    workers.append(worker)
                    worker.start()
                    worker.join()
            finally:
                stopped.set()

        controller = threading.Thread(target=churn)
        controller.start()
        self.assertTrue(started.wait(2))
        successes = 0
        try:
            for unused in range(20):
                try:
                    actual = tcad._MULTICORE_HELPERS['mc_snapshot'](
                        proc, pid, cpus, None, cwd, ticks)
                except (FileNotFoundError, tcad._MULTICORE_HELPERS['MCTransientSnapshotError']):
                    # Bounded rejection under uninterrupted churn is permitted;
                    # successful observations must still satisfy the full contract.
                    continue
                tcad._MULTICORE_HELPERS['mc_validate'](
                    actual, cpus, None, pid, ticks, cwd)
                successes += 1
        finally:
            stopped.set()
            controller.join(5)
            for worker in workers:
                worker.join(5)
        self.assertFalse(controller.is_alive())
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        stable = tcad._MULTICORE_HELPERS['mc_snapshot'](proc, pid, cpus, None, cwd, ticks)
        self.assertEqual(stable['pid'], pid)
        # Do not turn a run containing only bounded rejections into a pass.
        self.assertGreater(successes, 0)


if __name__ == '__main__':
    unittest.main()
