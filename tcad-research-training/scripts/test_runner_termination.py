"""Linux process fixtures only; never starts a scientific solver."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import runner_termination as termination


@unittest.skipUnless(sys.platform.startswith('linux'), 'requires Linux /proc and signals')
class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runner-cancel-test-')
        self.folder = Path(self.temp.name)
        self.children = []

    def tearDown(self):
        if hasattr(self, 'native_identity'):
            pid, ticks = self.native_identity
            try:
                stat = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
                if int(stat[19]) == ticks:os.kill(pid, 9)
            except (OSError, ProcessLookupError):pass
        for process in self.children:
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
        self.temp.cleanup()

    def start(self, legacy=False, raw_exit=True, ignore_term=False):
        script = self.folder / 'run.sh'
        lines = ['#!/bin/bash', 'cd ' + str(self.folder)]
        if raw_exit:lines += ["trap 'rc=$?; echo $rc > exit-code.txt' EXIT"]
        if ignore_term:lines += ["trap '' TERM"]
        if legacy:
            installation = self.folder / 'installation'
            installation.mkdir()
            shutil.copy2('/usr/bin/sleep', installation / 'sdevice')
            lines += [str(installation / 'sdevice') + ' 120 &', 'echo $! > native-pid.txt', 'wait $!']
        else:lines += ['sleep 120 &', 'echo $! > native-pid.txt', 'wait $!']
        script.write_text('\n'.join(lines) + '\n')
        process = subprocess.Popen(['bash', str(script)], cwd=self.folder,
                                   start_new_session=not legacy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(process)
        deadline = time.monotonic() + 3
        while not (self.folder / 'native-pid.txt').is_file():
            if time.monotonic() > deadline:raise AssertionError('fixture failed to start')
            time.sleep(.01)
        def proc(pid):
            fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
            return int(fields[19])
        native_pid = int((self.folder / 'native-pid.txt').read_text())
        self.native_identity = (native_pid, proc(native_pid))
        identity = {'schema': 'tcad-process-identity-r1', 'pid': process.pid, 'start_ticks': proc(process.pid),
                    'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'run_id': 'fixture',
                    'cwd': str(self.folder), 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
        if not legacy:identity.update(process_group=process.pid, session_id=process.pid)
        (self.folder / 'process-identity.json').write_text(json.dumps(identity))
        record = {'run_id': 'fixture', 'remote_directory': str(self.folder), 'process_identity': identity,
                  'script_sha256': identity['script_sha256']}
        if legacy:
            native = int((self.folder / 'native-pid.txt').read_text())
            observation = {'status': 'OBSERVED', 'wrapper_pid': process.pid, 'native_pid': native,
                           'native_start_ticks': proc(native), 'installation_root': str(installation)}
            (self.folder / 'native.json').write_text(json.dumps(observation))
            record['tool_evidence'] = {'native': {'tool': 'sdevice', 'process_observation_file': 'native.json'}}
        return record

    def invoke(self, record, expect_success=True):
        request = {'record': record, 'reason': 'test fixture', 'requested_by': 'test',
                   'requested_at': time.time(), 'grace_seconds': .1, 'request_id': 'fixture'}
        result = subprocess.run([sys.executable, '-c', termination.CANCEL_CODE, json.dumps(request)],
                                capture_output=True, text=True, timeout=12)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def test_group_term_records_signal_exit_and_idempotent_receipt(self):
        record = self.start()
        result = self.invoke(record)
        self.assertEqual(result['execution_outcome'], 'TERMINATED_BY_OPERATOR')
        self.assertTrue(result['quiescent'])
        self.assertEqual(result['raw_exit_code'], 143)
        self.assertTrue(result['signals'])
        again = self.invoke(record)
        self.assertEqual(again, result)

    def test_legacy_exact_native_does_not_signal_unrelated_group_member(self):
        record = self.start(legacy=True)
        unrelated = subprocess.Popen(['sleep', '120'], cwd='/tmp')
        self.children.append(unrelated)
        result = self.invoke(record)
        self.assertEqual(result['mode'], 'verified_original_native')
        self.assertEqual(result['execution_outcome'], 'TERMINATED_BY_OPERATOR')
        self.assertIsNone(unrelated.poll())

    def test_pid_identity_mismatch_refuses_without_signal(self):
        record = self.start()
        record['process_identity'] = dict(record['process_identity'], start_ticks=1)
        self.invoke(record, expect_success=False)
        self.assertIsNone(self.children[0].poll())
        self.assertFalse((self.folder / 'termination-events.jsonl').exists())

    def test_legacy_without_original_native_proof_requires_review(self):
        record = self.start(legacy=True)
        record.pop('tool_evidence')
        self.invoke(record, expect_success=False)
        self.assertIsNone(self.children[0].poll())
        self.assertFalse((self.folder / 'termination-events.jsonl').exists())

    def test_missing_raw_exit_stays_missing_with_separate_derived_exit(self):
        record = self.start(raw_exit=False, ignore_term=True)
        result = self.invoke(record)
        self.assertEqual(result['execution_outcome'], 'TERMINATED_BY_OPERATOR')
        self.assertIsNone(result['raw_exit_code'])
        self.assertEqual(result['derived_exit_code'], 137)
        self.assertFalse((self.folder / 'exit-code.txt').exists())

    def test_finished_before_request_is_not_called_terminated(self):
        record = self.start()
        self.children[0].terminate()
        self.children[0].wait(timeout=5)
        # Terminate only the fixture child, and preserve a real successful exit.
        native = int((self.folder / 'native-pid.txt').read_text())
        try:os.kill(native, 15)
        except ProcessLookupError:pass
        (self.folder / 'exit-code.txt').write_text('0\n')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                status = Path('/proc/{}/stat'.format(native)).read_text().rsplit(')', 1)[1].split()[0]
                if status == 'Z':break
            except OSError:break
            time.sleep(.01)
        result = self.invoke(record)
        self.assertEqual(result['execution_outcome'], 'NATURAL_COMPLETION')
        self.assertFalse(result['signals'])
