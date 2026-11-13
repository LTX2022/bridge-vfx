import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.errors import RuntimeV2Error


class ExecutionLockTests(unittest.TestCase):
    def test_nested_facade_calls_are_reentrant_and_release_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "db"
            with self.assertRaises(ValueError):
                with execution_lock(database, "one"):
                    with execution_lock(database, "one"):
                        raise ValueError("failed operation")
            with execution_lock(database, "one"):
                pass

    def test_competing_thread_rejected_but_distinct_task_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = []
            database = Path(directory) / "db"
            def competing():
                try:
                    with execution_lock(database, "one"):
                        errors.append("unexpected acquisition")
                except RuntimeV2Error:
                    errors.append("busy")
                with execution_lock(database, "two"):
                    errors.append("independent")
            with execution_lock(database, "one"):
                thread = threading.Thread(target=competing)
                thread.start()
                thread.join(5)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["busy", "independent"])

    def test_other_process_cannot_acquire_until_owner_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "db"
            program = "from dcc_task_runtime.execution_lock import execution_lock\nimport sys\nfrom dcc_task_runtime.errors import RuntimeV2Error\ntry:\n with execution_lock(sys.argv[1], 'one'): pass\nexcept RuntimeV2Error: sys.exit(23)\n"
            env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), PYTHONDONTWRITEBYTECODE="1")
            with execution_lock(database, "one"):
                result = subprocess.run([sys.executable, "-c", program, str(database)], env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 23, result.stderr.decode())
            result = subprocess.run([sys.executable, "-c", program, str(database)], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
