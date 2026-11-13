"""Only the current authenticated supervisor event releases software alpha hosts."""
import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from engineering_process_fixture import SUPERVISOR_START_SYNC
from dcc_task_runtime import owned_process
from dcc_task_runtime import native_scope


class EngineeringProcessFixtureTests(unittest.TestCase):
    def test_current_authenticated_event_or_explicit_refusal(self):
        namespace={};exec(SUPERVISOR_START_SYNC, namespace)
        wait=namespace['software_wait_for_supervisor_start']
        ticket={'id':'current','role':'alpha-husk','parent':None,'stopped_at':None,
            'directory':'/private/tmp/software-supervisor-test','identity':{'task_id':'task'},
            'admitted_at':time.time()}
        scope=SimpleNamespace(scope={'budget':{'per_operation_seconds':120}},
            snapshot=lambda:{'tickets':[ticket], 'closed_reason':None})
        env={'BRIDGE_NATIVE_SCOPE_BINDING':json.dumps({'path':'scope','sha256':'digest'}),
            'BRIDGE_NATIVE_SCOPE_TICKET':'current'}
        with patch.dict(os.environ,env,clear=True), patch.object(native_scope,'NativeScope',return_value=scope):
            with patch.object(owned_process,'read_receipt',side_effect=[None,{'pid':os.getpid()}]) as read, \
                    patch.object(time,'sleep') as poll:
                wait('alpha-husk')
                self.assertEqual(read.call_count,2)
                read.assert_called_with(ticket['directory'],'started',identity=ticket['identity'])
                poll.assert_called_once_with(.01)
            # A signed failure start still releases only the lifetime barrier;
            # production owns the subsequent binding rejection.
            with patch.object(owned_process,'read_receipt',return_value={
                    'pid':os.getpid(),'writer_process_binding_error':'original failure'}):
                wait('alpha-husk')
            for receipt in ({'pid':os.getpid()+1},{'pid':True}):
                with self.subTest(receipt=receipt), patch.object(owned_process,'read_receipt',return_value=receipt):
                    with self.assertRaisesRegex(ValueError,'SOFTWARE_SUPERVISOR_PID_MISMATCH'):wait('alpha-husk')
            with patch.object(owned_process,'read_receipt',side_effect=ValueError('SUPERVISOR_RECEIPT_MISMATCH')):
                with self.assertRaisesRegex(ValueError,'SUPERVISOR_RECEIPT_MISMATCH'):wait('alpha-husk')
            with patch.object(owned_process,'read_receipt') as read, patch.object(time,'monotonic',side_effect=[0.,23.]):
                with self.assertRaisesRegex(ValueError,'SOFTWARE_SUPERVISOR_START_TIMEOUT'):wait('alpha-husk')
                read.assert_not_called()
            with patch.object(owned_process,'read_receipt') as read:
                wait('alpha-nuke');read.assert_not_called()
            with patch.dict(os.environ,{'BRIDGE_NATIVE_SCOPE_TICKET':'other'}):
                with self.assertRaisesRegex(ValueError,'SOFTWARE_SUPERVISOR_TICKET_REQUIRED'):wait('alpha-husk')
        with patch.dict(os.environ,{},clear=True):wait('alpha-husk')
        with patch.dict(os.environ,{'BRIDGE_NATIVE_SCOPE_TICKET':'current'},clear=True):
            with self.assertRaisesRegex(ValueError,'SOFTWARE_SUPERVISOR_SCOPE_INCOMPLETE'):wait('alpha-husk')


if __name__=='__main__':unittest.main()
