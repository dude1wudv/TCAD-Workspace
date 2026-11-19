"""Owner-lock checks only: temporary paths, no SSH, API or native solvers."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import supervisor as s


CHILD = """
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import supervisor
try:
    with supervisor.ownership(Path(sys.argv[2])):
        print("ACQUIRED")
except RuntimeError:
    print("CONTENDED")
    sys.exit(75)
"""


class OwnershipBranchTests(unittest.TestCase):
    def test_posix_uses_nonblocking_exclusive_flock_and_keeps_lock_inode(self):
        fake = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8,
                                     flock=mock.Mock())
        with tempfile.TemporaryDirectory(prefix="tcad-owner-") as temp:
            lock = Path(temp) / "owner.lock"
            lock.write_bytes(b"original-owner-evidence")
            before = lock.stat()
            with mock.patch.object(s.sys, "platform", "linux"), \
                 mock.patch.dict(sys.modules, {"fcntl": fake}):
                with s.ownership(lock):
                    self.assertEqual(lock.read_bytes(), b"original-owner-evidence")
            self.assertEqual([call.args[1] for call in fake.flock.call_args_list],
                             [fake.LOCK_EX | fake.LOCK_NB, fake.LOCK_UN])
            self.assertEqual(lock.stat().st_ino, before.st_ino)
            self.assertEqual(lock.read_bytes(), b"original-owner-evidence")

    def test_posix_acquisition_failure_keeps_existing_file_and_closes_stream(self):
        fake = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8,
                                     flock=mock.Mock(side_effect=BlockingIOError("held")))
        with tempfile.TemporaryDirectory(prefix="tcad-owner-") as temp:
            lock = Path(temp) / "owner.lock"
            lock.write_bytes(b"existing")
            stream = lock.open("a+b")
            fake_path = mock.Mock()
            fake_path.open.return_value = stream
            with mock.patch.object(s.sys, "platform", "linux"), \
                 mock.patch.object(s, "Path", return_value=fake_path), \
                 mock.patch.dict(sys.modules, {"fcntl": fake}):
                with self.assertRaisesRegex(RuntimeError, "Another scheduler"):
                    with s.ownership(lock):
                        self.fail("Occupied lock must not yield")
            self.assertTrue(stream.closed)
            self.assertEqual(lock.read_bytes(), b"existing")
            fake.flock.assert_called_once()

    def test_posix_unlock_failure_still_closes_stream(self):
        fake = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8,
                                     flock=mock.Mock(side_effect=[None, OSError("unlock")]))
        with tempfile.TemporaryDirectory(prefix="tcad-owner-") as temp:
            lock = Path(temp) / "owner.lock"
            stream = lock.open("a+b")
            fake_path = mock.Mock()
            fake_path.open.return_value = stream
            with mock.patch.object(s.sys, "platform", "linux"), \
                 mock.patch.object(s, "Path", return_value=fake_path), \
                 mock.patch.dict(sys.modules, {"fcntl": fake}):
                with self.assertRaisesRegex(OSError, "unlock"):
                    with s.ownership(lock):
                        pass
            self.assertTrue(stream.closed)
            self.assertTrue(lock.is_file())


class NativeOwnershipProcessTests(unittest.TestCase):
    def child(self, lock):
        return subprocess.run([sys.executable, "-B", "-c", CHILD, str(HERE), str(lock)],
                              capture_output=True, text=True, timeout=20)

    def test_another_process_is_excluded_until_release(self):
        with tempfile.TemporaryDirectory(prefix="tcad-owner-process-") as temp:
            lock = Path(temp) / "owner.lock"
            with s.ownership(lock):
                before = lock.stat()
                blocked = self.child(lock)
                self.assertEqual(blocked.returncode, 75, blocked.stderr)
                self.assertEqual(blocked.stdout.strip(), "CONTENDED")
                self.assertEqual(lock.stat().st_ino, before.st_ino)
            acquired = self.child(lock)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            self.assertEqual(acquired.stdout.strip(), "ACQUIRED")
            self.assertEqual(lock.read_bytes(), b"0")
            self.assertEqual(lock.stat().st_ino, before.st_ino)

    def test_body_exception_releases_original_lock(self):
        with tempfile.TemporaryDirectory(prefix="tcad-owner-process-") as temp:
            lock = Path(temp) / "owner.lock"
            with self.assertRaisesRegex(ValueError, "body failure"):
                with s.ownership(lock):
                    raise ValueError("body failure")
            acquired = self.child(lock)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            self.assertEqual(acquired.stdout.strip(), "ACQUIRED")
            self.assertTrue(lock.is_file())

    @unittest.skipUnless(os.name == "posix", "Requires a real POSIX flock runtime")
    def test_posix_process_exit_releases_original_lock(self):
        code = """
from pathlib import Path
import os, sys
sys.path.insert(0, sys.argv[1])
import supervisor
with supervisor.ownership(Path(sys.argv[2])):
    os._exit(0)
"""
        with tempfile.TemporaryDirectory(prefix="tcad-owner-process-") as temp:
            lock = Path(temp) / "owner.lock"
            exited = subprocess.run([sys.executable, "-B", "-c", code, str(HERE), str(lock)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(exited.returncode, 0, exited.stderr)
            acquired = self.child(lock)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            self.assertEqual(acquired.stdout.strip(), "ACQUIRED")


if __name__ == "__main__":
    unittest.main()
