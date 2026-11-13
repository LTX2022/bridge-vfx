"""Software-only receipt, byte and supersession checks; no DCC launch."""
from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest import mock

from test_registry_operation_receipts import RegistryOperationReceiptTests
from dcc_task_runtime.artifact_registry import ArtifactError
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.historical_artifacts import verify_historical_operation_receipt, verify_historical_artifact


class HistoricalCreativeArtifactsTests(unittest.TestCase):
    setUp = RegistryOperationReceiptTests.setUp
    operation_source = RegistryOperationReceiptTests.operation_source
    register = RegistryOperationReceiptTests.register
    replace_fact = RegistryOperationReceiptTests.replace_fact

    def revisions(self):
        one = 'graph:fixture-owner:graph-a:version:1'
        two = 'graph:fixture-owner:graph-a:version:2'
        self.fact['dependencies'] = [one]
        self.replace_fact(self.fact)
        first = self.register(dependencies=[one])['registry_operation_receipt']
        later_fact = copy.deepcopy(self.fact)
        later_fact.update(operation_id='fixture-operation-2', dependencies=[two])
        with sqlite3.connect(self.producer_db) as db:
            db.execute('INSERT INTO facts VALUES (?, ?)', (later_fact['operation_id'], json.dumps(later_fact)))
        second = self.register(operation_id=later_fact['operation_id'], dependencies=[two])['registry_operation_receipt']
        feedback = {'task_id':'fixture-owner', 'version':2, 'state':'COMPLETE', 'after':{'exposure':1}}
        with sqlite3.connect(self.root/'diagnostic.sqlite3') as db:
            db.execute('CREATE TABLE feedback_versions(graph_id,version,state,payload)')
            db.execute('INSERT INTO feedback_versions VALUES(?,?,?,?)', ('graph-a',2,'COMPLETE',json.dumps({'task_id':'fixture-owner','after':{'exposure':1}})))
        return first, {'registry':self.registry, 'receipt':second, 'feedback':feedback, 'control':self.root}

    def invalidate(self, reason):
        with self.registry._connect() as db:
            db.execute('INSERT INTO artifact_invalidations VALUES(?,?,?)', ('fixture-output',1,reason))

    def ledger(self):
        with sqlite3.connect(self.registry.path) as db:
            return {name:db.execute('SELECT * FROM '+name).fetchall() for name in
                    ('artifacts','artifact_versions','artifact_operation_receipts','artifact_invalidations')}

    def test_superseded_bytes_are_observation_only_and_ledger_unchanged(self):
        first, later = self.revisions()
        self.invalidate('graph graph-a version 2')
        before = self.ledger()
        with mock.patch('subprocess.Popen', side_effect=AssertionError('No process launch')):
            result = verify_historical_operation_receipt(self.registry, first, superseding=later)
        self.assertTrue(result['historical'])
        self.assertFalse(result['consumable'])
        self.assertEqual(result['invalidation_reason'], 'graph graph-a version 2')
        self.assertEqual(before,self.ledger())
        with self.assertRaisesRegex(ArtifactError,'CURRENT_VERSION_CHANGED'):
            self.registry.verify_operation_receipt(first)
        self.assertTrue(self.registry.verify_operation_receipt(later['receipt']))

    def test_manual_invalidation_cannot_be_relabelled_as_supersession(self):
        first,later=self.revisions();self.invalidate('manual rejection')
        with self.assertRaisesRegex(ArtifactError,'SUPERSESSION'):
            verify_historical_operation_receipt(self.registry,first,superseding=later)

    def test_missing_or_changed_feedback_source_rejected(self):
        first,later=self.revisions();self.invalidate('graph graph-a version 2')
        with sqlite3.connect(self.root/'diagnostic.sqlite3') as db:
            db.execute("UPDATE feedback_versions SET state='FAILED'")
        with self.assertRaisesRegex(ArtifactError,'GRAPH_SOURCE'):
            verify_historical_operation_receipt(self.registry,first,superseding=later)

    def test_forged_historical_receipt_rejected_even_with_new_hash(self):
        first,later=self.revisions()
        first['producer_fact_sha256']='0'*64
        first.pop('registry_operation_receipt_sha256')
        first['registry_operation_receipt_sha256']=canonical_sha256(first)
        with self.assertRaisesRegex(ArtifactError,'DB_MISMATCH'):
            verify_historical_operation_receipt(self.registry,first,superseding=later)

    def test_original_output_bytes_still_required(self):
        first,later=self.revisions()
        Path(self.pattern.replace('%03d','001')).write_bytes(b'changed')
        with self.assertRaises((ArtifactError,ValueError)):
            verify_historical_operation_receipt(self.registry,first,superseding=later)

    def test_unsupported_artifact_dependency_closure_is_rejected(self):
        first,later=self.revisions();first['dependency_records']={'parent':{'version':1}}
        first.pop('registry_operation_receipt_sha256')
        first['registry_operation_receipt_sha256']=canonical_sha256(first)
        with self.assertRaisesRegex(ArtifactError,'BINDING'):
            verify_historical_operation_receipt(self.registry,first,superseding=later)


    def test_feedback_changes_during_each_historical_admission_are_rejected(self):
        first,later=self.revisions();self.invalidate('graph graph-a version 2')
        entry=self.registry.lookup_version('fixture-output',1)
        original=self.registry._typed_admission
        baseline=json.dumps({'task_id':'fixture-owner','after':{'exposure':1}})
        for api in ('receipt','artifact'):
            for column,value in (('state','FAILED'),('payload','{}')):
                for phase in ('enter','exit'):
                    with self.subTest(api=api,column=column,phase=phase):
                        with sqlite3.connect(self.root/'diagnostic.sqlite3') as db:
                            db.execute("UPDATE feedback_versions SET state='COMPLETE',payload=?",(baseline,))
                        def mutate():
                            with sqlite3.connect(self.root/'diagnostic.sqlite3') as db:
                                db.execute('UPDATE feedback_versions SET '+column+'=?',(value,))
                        @contextmanager
                        def admission(fact,*args,**kwargs):
                            with original(fact,*args,**kwargs) as observed:
                                if fact['operation_id']=='fixture-operation' and phase=='enter':mutate()
                                yield observed
                                if fact['operation_id']=='fixture-operation' and phase=='exit':mutate()
                        with mock.patch.object(self.registry,'_typed_admission',admission):
                            with self.assertRaisesRegex(ArtifactError,'GRAPH_CHANGED_DURING_READ'):
                                if api=='receipt':
                                    verify_historical_operation_receipt(self.registry,first,superseding=later)
                                else:
                                    verify_historical_artifact(self.registry,entry,self.fact,superseding=later)

    def test_successor_changes_during_historical_admission_are_rejected(self):
        first,later=self.revisions();self.invalidate('graph graph-a version 2')
        entry=self.registry.lookup_version('fixture-output',1)
        original=self.registry._typed_admission
        @contextmanager
        def admission(fact,*args,**kwargs):
            with original(fact,*args,**kwargs) as observed:
                yield observed
                if fact['operation_id']=='fixture-operation':
                    with self.registry._connect() as db:
                        db.execute("UPDATE artifacts SET payload_json='{}' WHERE artifact_id='fixture-output'")
        with mock.patch.object(self.registry,'_typed_admission',admission):
            with self.assertRaisesRegex(ArtifactError,'SUPERSESSION_CHANGED_DURING_READ'):
                verify_historical_artifact(self.registry,entry,self.fact,superseding=later)


if __name__=='__main__':unittest.main()
