"""Output encoding and bounded retry contracts; no native producer is simulated."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from vfx_pipeline.domain_readiness import DomainReadinessError, DomainReadinessRunner


class FormalOutputRegistrationTests(unittest.TestCase):
    def encoding(self):
        return {'completion_metadata_status': 'AVAILABLE', 'frame_set': [1, 3],
                'metadata': {str(frame): {'colorspace': 'observed-space', 'premultiplied': True}
                             for frame in (1, 3)}}

    def test_encoding_uses_all_producer_frames_without_color_or_alpha_defaults(self):
        self.assertEqual(DomainReadinessRunner._formal_output_encoding(self.encoding(), [1, 3]),
                         ('observed-space', True))

    def test_missing_native_facts_remain_actionable_and_blocked(self):
        fact = {'completion_metadata_status': 'BLOCKED_MISSING_NATIVE_FACTS',
                'completion_metadata_missing_facts': ['OCIO_REQUIRED', 'ALPHA_REQUIRED'], 'metadata': {}}
        with self.assertRaisesRegex(DomainReadinessError, 'OCIO_REQUIRED.*ALPHA_REQUIRED'):
            DomainReadinessRunner._formal_output_encoding(fact, [1, 3])

    def test_inconsistent_incomplete_or_untyped_encoding_is_rejected(self):
        for change in ({'colorspace': 'another-space'}, {'colorspace': ''},
                       {'premultiplied': False}, {'premultiplied': 1}, {}):
            fact = copy.deepcopy(self.encoding())
            fact['metadata']['3'] = change
            with self.subTest(change=change), self.assertRaises(DomainReadinessError):
                DomainReadinessRunner._formal_output_encoding(fact, [1, 3])
        for frames in ([1], [1, True], [3, 1]):
            with self.subTest(frames=frames), self.assertRaises(DomainReadinessError):
                DomainReadinessRunner._formal_output_encoding(self.encoding(), frames)
        fact = self.encoding()
        fact['frame_set'] = [True, 3]
        with self.assertRaises(DomainReadinessError):
            DomainReadinessRunner._formal_output_encoding(fact, [1, 3])
        fact['frame_set'] = [1, 1, 3]
        with self.assertRaises(DomainReadinessError):
            DomainReadinessRunner._formal_output_encoding(fact, [1, 1, 3])

    def test_real_sqlite_busy_retries_the_same_registration_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'ledger.sqlite'
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('CREATE TABLE effects (operation TEXT)')
                connection.commit()
            with closing(sqlite3.connect(database)) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                calls = []

                def register(attempt):
                    calls.append((attempt, 'already-completed-operation'))
                    try:
                        with closing(sqlite3.connect(database, timeout=0)) as connection:
                            connection.execute('INSERT INTO effects VALUES (?)',
                                               ('already-completed-operation',))
                            connection.commit()
                    except sqlite3.OperationalError:
                        blocker.rollback()
                        raise
                    return 'registered'

                self.assertEqual(DomainReadinessRunner._formal_registration_retry(register), 'registered')
            self.assertEqual(calls, [(1, 'already-completed-operation'), (2, 'already-completed-operation')])
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT operation FROM effects').fetchall(),
                                 [('already-completed-operation',)])

    def test_non_busy_sqlite_error_and_semantic_rejection_are_not_retried(self):
        for error in (sqlite3.OperationalError('no such table'),
                      DomainReadinessError('native facts missing')):
            calls = []

            def register(attempt):
                calls.append(attempt)
                raise error

            with self.subTest(error=error), self.assertRaises(type(error)):
                DomainReadinessRunner._formal_registration_retry(register)
            self.assertEqual(calls, [1])

    def test_persistent_busy_is_bounded_to_two_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'ledger.sqlite'
            with closing(sqlite3.connect(database)) as blocker:
                blocker.execute('CREATE TABLE effects (operation TEXT)')
                blocker.commit()
                blocker.execute('BEGIN IMMEDIATE')
                calls = []

                def register(attempt):
                    calls.append(attempt)
                    with closing(sqlite3.connect(database, timeout=0)) as connection:
                        connection.execute('INSERT INTO effects VALUES (?)', ('existing-operation',))

                with self.assertRaises(sqlite3.OperationalError):
                    DomainReadinessRunner._formal_registration_retry(register)
                self.assertEqual(calls, [1, 2])


if __name__ == '__main__':
    unittest.main()
