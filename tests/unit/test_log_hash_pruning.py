import hashlib
import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import run_logged


class LogHashPruningTests(unittest.TestCase):
    def test_scandir_open_and_iteration_io_errors_propagate_before_hashing(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / 'outputs')))
        directory = root / 'packages'
        directory.mkdir()
        (directory / 'source.py').write_bytes(b'actual source')
        scandir = os.scandir
        failure = OSError(errno.EIO, 'actual scanner fault boundary')

        class BrokenScan:
            def __enter__(self):
                return self

            def __exit__(self, *arguments):
                return False

            def __next__(self):
                raise failure

        for stage in ('open', 'iteration'):
            def scan(path):
                if Path(path) == directory:
                    if stage == 'open':
                        raise failure
                    return BrokenScan()
                return scandir(path)

            with self.subTest(stage=stage), patch.object(run_logged.os, 'scandir', side_effect=scan):
                with self.assertRaises(OSError) as observed:
                    run_logged.build_hash(root)
                self.assertIs(observed.exception, failure)

    def test_hash_preserves_logical_order_and_never_opens_excluded_directories(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / 'outputs')))
        expected = hashlib.sha256()
        files = {'Z.txt': b'upper', 'a/中文.txt': b'unicode', 'a.txt': b'lower'}
        for name, payload in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        for name, payload in sorted(files.items()):
            expected.update(name.encode('utf-8'))
            expected.update(b'\0')
            expected.update(hashlib.sha256(payload).digest())
        for name in run_logged.EXCLUDED:
            directory = root / name
            directory.mkdir()
            (directory / 'must-not-visit.txt').write_bytes(b'ignored')
        scandir = os.scandir
        visited = []

        def observe_scan(directory):
            path = Path(directory)
            self.assertFalse(set(path.relative_to(root).parts) & run_logged.EXCLUDED)
            visited.append(path)
            return scandir(directory)

        with patch.object(run_logged.os, 'scandir', side_effect=observe_scan):
            self.assertEqual(run_logged.build_hash(root), expected.hexdigest())
        self.assertEqual(set(visited), {root, root / 'a'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
