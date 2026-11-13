from __future__ import annotations
import io
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parents[2]
for package_source in (ROOT/'packages').glob('*/src'):
    sys.path.insert(0,str(package_source))
sys.path.insert(0,str(ROOT/'tools'))
import build_readiness_report as reports
import readiness_evidence as evidence
import preflight_real_acceptance as preflight
import run_readiness_evidence as execution_runner
import verify_skill_lifecycle as lifecycle
import assemble_final_delivery as delivery


def _require_symlink(target, source):
    try:
        target.symlink_to(source)
    except OSError as error:
        if os.name == 'nt' and getattr(error, 'winerror', None) == 1314:
            raise unittest.SkipTest('Windows symbolic-link privilege unavailable; symbolic-link case not run') from error
        raise


class FinalDeliveryGateTests(unittest.TestCase):
    def test_delivery_manifest_ignores_only_paths_below_the_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / ".pytest_cache" / "中文 源码"
            source.mkdir(parents=True)
            (source / "Z.txt").write_bytes(b"upper")
            (source / "a.txt").write_bytes(b"lower")
            (source / "__pycache__").mkdir()
            (source / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
            manifest = delivery._manifest(source)
            self.assertEqual([entry["path"] for entry in manifest], ["Z.txt", "a.txt"])
            self.assertEqual([entry["sha256"] for entry in manifest],
                             [hashlib.sha256(b"upper").hexdigest(), hashlib.sha256(b"lower").hexdigest()])

    def test_actual_cli_rejects_missing_not_ready_and_failed_review_without_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'; source.mkdir()
            (source / 'README.md').write_text('partial source fixture\n')
            index = source / delivery.LIVE_INDEX
            index.parent.mkdir(parents=True)
            index.write_text(json.dumps({'schema_version':1, 'entries':[], 'model_routes':[], 'workbuddy_runs':[]}))
            original = root / 'original'; original.mkdir()
            (original / 'README.md').write_text('original\n')
            readiness = root / 'readiness'; readiness.mkdir()
            review = readiness / 'independent-review.json'
            review.write_text(json.dumps({'schema':'bridge.readiness.independent_review/1',
                'build_id':evidence.build_id(source), 'reviewer':'independent', 'implementers':['implementer'],
                'reviewed_contracts':list(evidence.REQUIRED), 'open_findings':['sentinel'], 'passed':False}))
            for name in ('executed-contracts.json', 'domain-cases.json', 'media-readiness.json', 'skill-lifecycle.json'):
                (readiness / name).write_text('{}')
            release = root / 'release'; release.mkdir()
            review_evidence = root / 'review-evidence'; review_evidence.mkdir()
            input_zip = root / 'input.zip'
            import zipfile
            with zipfile.ZipFile(input_zip, 'w') as archive:
                archive.writestr('README.md', 'frozen source fixture\n')
            log = root / 'execution.log'; log.write_text('FAILED (errors=1)\n')
            contract = root / 'contract.md'; contract.write_text('software-only fixture\n')
            argv = [sys.executable, str(ROOT / 'tools/assemble_final_delivery.py'),
                '--source',str(source), '--original-source',str(original),
                '--original-zip',str(input_zip), '--review-zip',str(input_zip),
                '--review-report',str(review), '--review-evidence-dir',str(review_evidence),
                '--contract',str(contract), '--original-contract',str(contract),
                '--readiness-dir',str(readiness), '--release-dir',str(release),
                '--target-dir',str(root / 'delivery'), '--package-name','negative-probe']
            for name in ('full-log','targeted-log','build-log','lifecycle-log'):
                argv += ['--' + name, str(log)]
            for state in ('missing', 'NOT_READY', 'forged-PASS'):
                with self.subTest(state=state):
                    matrix = readiness / 'acceptance_matrix.json'
                    if state != 'missing':
                        value = reports.assess({}, {}, {}, {}, {}, root=source)
                        if state == 'forged-PASS':
                            value['software_preparation_status'] = 'PASS'
                            value['errors'] = []
                        matrix.write_text(json.dumps(value))
                    result = subprocess.run(argv, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn('M1 delivery rejected', result.stderr)
                    self.assertIn('independent review is not closed', result.stderr)
                    self.assertIn('recorded acceptance matrix', result.stderr)
                    self.assertFalse((root / 'delivery').exists())

    def test_actual_forward_reverse_replay_includes_binary_empty_and_no_final_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); before = root / 'before'; after = root / 'after'
            before.mkdir(); after.mkdir()
            old = {'same.txt':b'same\n', 'edit.txt':b'old', 'remove.bin':b'\0old',
                   'empty-delete.txt':b'', 'crlf.txt':b'old\r\n', 'text-delete.txt':b'delete\n',
                   'becomes-empty.txt':b'content\n', 'was-empty.txt':b'',
                   'empty-same.txt':b'', 'edit.bin':b'\0old binary'}
            new = {'same.txt':b'same\n', 'edit.txt':b'new', 'add.exr':b'\x76\x2f\x31\x01\0new',
                   'empty-add.txt':b'', 'crlf.txt':b'new\r\n', 'text-add.txt':b'added\n',
                   'becomes-empty.txt':b'', 'was-empty.txt':b'content\n',
                   'empty-same.txt':b'', 'edit.bin':b'\0new binary'}
            for name, content in old.items(): (before / name).write_bytes(content)
            for name, content in new.items(): (after / name).write_bytes(content)
            patch = root / 'patch'
            forward = delivery._make_patch(before, after, patch / 'forward.patch')
            reverse = delivery._make_patch(after, before, patch / 'reverse.patch')
            self.assertEqual(forward['changed_files'], 11)
            self.assertEqual({change['path'] for change in forward['binary_changes']},
                             {'remove.bin', 'add.exr', 'edit.bin', 'empty-delete.txt',
                              'empty-add.txt', 'becomes-empty.txt', 'was-empty.txt'})
            for direction, baseline, expected, info in (
                    ('forward', before, after, forward), ('reverse', after, before, reverse)):
                with self.subTest(direction=direction):
                    result = delivery._run_patch(patch / (direction+'.patch'), baseline, expected,
                                                 info['binary_changes'])
                    self.assertTrue(result['passed'], result)
            (patch / 'forward.patch').write_text('invalid patch\n')
            self.assertFalse(delivery._run_patch(patch / 'forward.patch', before, after, forward['binary_changes'])['passed'])
            (patch / 'forward.patch').write_text('')
            self.assertFalse(delivery._run_patch(patch / 'forward.patch', before, after, forward['binary_changes'])['passed'])
            blob = patch / next(change['old_payload'] for change in forward['binary_changes'] if 'old_payload' in change)
            blob.write_bytes(b'tampered')
            self.assertFalse(delivery._run_patch(patch / 'reverse.patch', after, before, reverse['binary_changes'])['passed'])

    def test_clean_source_keeps_live_declaration_and_excludes_process_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; target = root / 'target'
            contents = {'tools/entry.py':b'pass\n', delivery.LIVE_INDEX:b'{"entries":[],"status":"NOT_RUN"}\n',
                        'docs/fixtures/native.exr':b'\0real-fixture', 'README.md':b'current\n',
                        'agent-plugin/plugin.json':b'{}', 'handover/plan.md':b'scope\n',
                        'outputs/m1-takeover/debug/old.zip':b'old', 'reports/debug.log':b'debug',
                        'tools/__pycache__/entry.pyc':b'cache', '.DS_Store':b'metadata'}
            for name, data in contents.items():
                path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            delivery._copy_source(source, target)
            self.assertEqual({item['path'] for item in delivery._manifest(target)},
                             {'tools/entry.py', delivery.LIVE_INDEX, 'docs/fixtures/native.exr', 'README.md',
                              'agent-plugin/plugin.json', 'handover/plan.md'})
            self.assertEqual((target / delivery.LIVE_INDEX).read_bytes(), contents[delivery.LIVE_INDEX])
            receipt = source / 'outputs/receipt.json'
            frame = source / 'outputs/frame.exr'; frame.write_bytes(b'\0frame')
            scene = source / 'outputs/scene.hip'; scene.write_bytes(b'\0scene')
            review = source / 'reports/closed-review.md'; review.write_text('closed review fixture\n')
            receipt.write_text(json.dumps({'frame':{'path':str(frame),'sha256':delivery._sha256(frame)},
                'scene':{'snapshot_path':str(scene),'snapshot_sha256':delivery._sha256(scene)},
                'review':{'path':'reports/closed-review.md','sha256':delivery._sha256(review)}}))
            destination = root / 'evidence'
            delivery._copy_bound_evidence([{'path':'outputs/receipt.json','sha256':delivery._sha256(receipt)}],source,destination)
            names = {item['path'] for item in delivery._manifest(destination)}
            self.assertEqual(names, {'path-map.json','source-paths/outputs/receipt.json',
                                   'source-paths/outputs/frame.exr','source-paths/outputs/scene.hip',
                                   'source-paths/reports/closed-review.md'})
            frame.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'bound evidence file'):
                delivery._copy_bound_evidence([{'path':'outputs/receipt.json','sha256':delivery._sha256(receipt)}],source,root/'changed-evidence')

class ReadinessEvidenceTests(unittest.TestCase):
    def test_prepared_claims_preserve_full_matrix_refusal(self):
        cases = [{'domain_pack': domain, 'scenario': scenario, 'case_id': domain + '__' + scenario,
                  'status': 'PASS', 'case_execution': 'prepared_production_controller',
                  'formal_controller_verified': True, 'formal_domain_lifecycle_verified': True,
                  'recovery': {'tested': True}, 'semantic_control_coverage': ['all'],
                  'stage_receipts': [{'operation': 'graph_trial', 'result': {'status': 'PASS'}}]}
                 for domain in evidence.DOMAINS
                 for scenario in ('build_inspect', 'causal_candidate', 'approval_recovery')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            domain = {'cases': cases, 'build_id': evidence.build_id(root)}
            result = reports.assess({}, domain, {}, {}, {}, root=root)
        self.assertEqual(result['software_preparation_status'], 'NOT_READY')
        self.assertEqual(result['row_count'], 54)
        rows = [row for row in result['rows'] if row['id'].startswith('DOMAIN-')]
        self.assertEqual(len(rows), 16)
        for row in rows:
            self.assertFalse(row['software_gate_passed'])
            observed = row['observed_execution_binding']
            self.assertFalse(observed['passed'])
            self.assertEqual(observed['stages'], [])
            self.assertTrue(any('full_semantic' in error for error in observed['errors']))
            self.assertTrue(any('recovery' in error for error in observed['errors']))

    def test_nuke_formal_receipt_observes_real_producer_and_rejects_fact_drift(self):
        from test_nuke_unified_entries import UnifiedEntryTests
        from nuke_bridge.operation_receipts import finalize_render_operation
        helper = UnifiedEntryTests('test_same_request_reuses_and_executes_once')
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        captured = {}
        class RenderCase(unittest.TestCase):
            def test_render(self):
                case_id = 'nuke-formal-producer'
                first = helper.addon.dispatch('render_write', {'node':'Write1', 'background':False,
                                                              'request_id':'formal-source-request'})
                legacy = helper.addon.dispatch('render_fact', {'operation_id':first['operation_id']})
                receipt = legacy['formal_receipt']
                captured.update(receipt=receipt, legacy=legacy, operation_id=first['operation_id'])
                self.assertEqual(receipt['operation_id'], first['operation_id'])
                self.assertEqual(receipt['execution_fact']['task_id'], first['operation_id'])
                self.assertEqual(evidence._formal_receipt_source_errors(receipt, 'receipt'), [])
                self.assertEqual(evidence._render_file_errors(receipt, 'receipt'), [])
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=execution_runner.Result).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(RenderCase))
        self.assertTrue(result.wasSuccessful(), result.errors)
        receipt = captured['receipt']
        execution = next(iter(result.test_executions.values()))
        context = {'build_id':evidence.build_id(ROOT), 'case_id':'nuke-formal-producer',
                   'provider_sha256':evidence._canonical_sha256(receipt),
                   'operation_receipt_sha256':receipt['operation_receipt_sha256']}
        self.assertIn(context, execution['provider_facts'])
        self.assertEqual(evidence._producer_stage(receipt), 'render')
        self.assertEqual(receipt['artifact_operation_receipt_sha256'], captured['legacy']['operation_receipt_sha256'])
        task = helper.addon._RENDERS[captured['operation_id']]
        class WrapperCase(unittest.TestCase):
            def test_wrapper(self):
                case_id = 'wrapper-case'
                self.assertIsNotNone(finalize_render_operation(task, captured['legacy']))
        wrapper = unittest.TextTestRunner(stream=io.StringIO(), resultclass=execution_runner.Result).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(WrapperCase))
        self.assertEqual(next(iter(wrapper.test_executions.values()))['provider_facts'], [])
        for key, value in (('request_id','other'), ('frame_set',[3]), ('task_id','wrong-operation'),
                           ('stop_confirmed',False), ('frame_snapshots',{})):
            altered = json.loads(json.dumps(receipt))
            altered['execution_fact'][key] = value
            altered['operation_receipt_sha256'] = evidence._canonical_sha256(
                {k:v for k,v in altered.items() if k != 'operation_receipt_sha256'})
            self.assertTrue(evidence._formal_receipt_source_errors(altered, 'receipt'), key)
        output = Path(next(iter(receipt['frame_snapshots'].values()))['path'])
        output.write_bytes(b'changed')
        self.assertTrue(evidence._render_file_errors(receipt, 'receipt'))
        from vfx_pipeline.workbuddy_assembly import software_nuke_client
        from dcc_task_runtime.owned_process import OwnedProcessHandle
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            root = Path(temp).resolve()
            environment = {'BRIDGE_SKILLS_STATE_ROOT':str(root/'state'),
                           'BRIDGE_SKILLS_SCHEDULER_ROOT':str(root/'scheduler')}
            with mock.patch.dict(os.environ, environment):
                client = software_nuke_client(ROOT/'plugins/nuke/nuke_bridge_addon.py', root/'host',
                                              worker_script=ROOT/'tools/nuke_owned_render_worker.py')
                api = sys.modules['nuke']
                pattern = str(root/'owned.%03d.exr')
                api.toNode('Read1')['file'].setValue(str(root/'input.%03d.exr'))
                api.toNode('Write1')['file'].setValue(pattern)
                api.toNode('Write1').setInput(0, api.toNode('Read1'))
                for frame in (1,3): (root/('input.%03d.exr' % frame)).write_bytes(encode_tiny_exr(float(frame)))
                api.scriptSaveAs(str(root/'scene.nk'))
                class OwnedCase(unittest.TestCase):
                    def test_owned(self):
                        case_id = 'nuke-owned-formal-producer'
                        started = client.call('render_write', {'node':'Write1','background':True,
                            'frame_set':[1,3], 'request_id':'owned-formal-request'})
                        process = started['process']
                        handle = OwnedProcessHandle(process['supervisor_directory'], process['supervisor_identity'])
                        self.assertEqual(handle.wait(timeout=10), 0)
                        status = client.call('render_status', {'task_id':started['task_id']})
                        self.assertEqual(status['state'], 'COMPLETED')
                        provider = client.call('render_fact', {'operation_id':started['operation_id']})['formal_receipt']
                        captured['owned'] = provider
                        self.assertIsNotNone(provider)
                        self.assertEqual(evidence._formal_receipt_source_errors(provider, 'owned'), [])
                        self.assertEqual(evidence._render_file_errors(provider, 'owned'), [])
                owned = unittest.TextTestRunner(stream=io.StringIO(), resultclass=execution_runner.Result).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(OwnedCase))
                self.assertTrue(owned.wasSuccessful(), owned.errors + owned.failures)
                provider = captured['owned']
                self.assertIn({'build_id':evidence.build_id(ROOT), 'case_id':'nuke-owned-formal-producer',
                    'provider_sha256':evidence._canonical_sha256(provider),
                    'operation_receipt_sha256':provider['operation_receipt_sha256']},
                    next(iter(owned.test_executions.values()))['provider_facts'])

    def test_empty_inputs_are_not_ready(self):
        matrix = reports.assess({}, {}, {}, {}, {})
        self.assertEqual(matrix['software_preparation_status'],'NOT_READY')
        self.assertEqual(len(matrix['rows']),len(evidence.REQUIRED))
        self.assertFalse(any(row['software_gate_passed'] for row in matrix['rows']))
        self.assertTrue(matrix['errors'])

    def test_automated_checks_cannot_replace_independent_review(self):
        errors = reports.check_review({'schema':'bridge.readiness.automated_checks/1','passed':True},ROOT)
        self.assertIn('independent reviewer report required; automated source checks are not review',errors)

    def test_missing_failed_test_build_and_log_reject(self):
        payload = {'schema':'bridge.readiness.executed_contracts/2','build_id':'stale','rows':[],'returncode':0}
        errors = evidence.validate_contract(payload,ROOT)
        self.assertIn('source build does not match executed evidence',errors)
        self.assertTrue(any('contract IDs' in error for error in errors))

    def test_live_evidence_append_does_not_recursively_change_source_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); index = root/'outputs/live-validation/index.json'
            index.parent.mkdir(parents=True); index.write_text(json.dumps({'schema_version':1,'entries':[]}))
            before = evidence.build_id(root)
            for relative in ('handover/.DS_Store', 'tools/.DS_Store'):
                metadata = root/relative; metadata.parent.mkdir(parents=True, exist_ok=True)
                for data in (b'OS metadata', b'updated OS metadata'):
                    metadata.write_bytes(data)
                    with self.subTest(relative=relative, data=data):
                        self.assertEqual(before, evidence.build_id(root))
            for relative in ('tools/source.py', 'tools/.DS_Store.extra'):
                path = root/relative
                for data in (b'original bytes', b'changed bytes'):
                    previous = evidence.build_id(root)
                    path.write_bytes(data)
                    with self.subTest(relative=relative, data=data):
                        self.assertNotEqual(previous, evidence.build_id(root))
            before = evidence.build_id(root)
            index.write_text(json.dumps({'schema_version':1,'entries':[{'build_id':before}]}))
            self.assertEqual(before,evidence.build_id(root))
            index.write_text(json.dumps({'schema_version':2,'entries':[]}))
            self.assertNotEqual(before,evidence.build_id(root))

    def test_unexecuted_id_cannot_be_counted_as_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)/'execution.log';log.write_text('real execution placeholder for schema unit test')
            payload = {'schema':'bridge.readiness.executed_contracts/2','build_id':evidence.build_id(ROOT),'rows':[],
                       'test_results':{'positive':'PASS','negative':'FAIL'},'test_count':2,'returncode':0,'log':{'path':str(log),'sha256':evidence.digest(log)}}
            for identifier in evidence.REQUIRED:
                payload['rows'].append({'id':identifier,'source':'software_unittest','positive_tests':['positive'],'negative_tests':['negative'],
                                        'production_entry':'entry','implementation':['tools/readiness_evidence.py'],'release_files':['tools/readiness_evidence.py'],'live_card':'card'})
            self.assertTrue(any('evidence_bindings' in e or 'negative test' in e for e in evidence.validate_contract(payload,ROOT)))
            payload['test_results']['negative']='PASS'
            errors = evidence.validate_contract(payload,ROOT)
            self.assertTrue(any('evidence_bindings' in e or 'evidence_ref' in e for e in errors))
            log.write_text('changed')
            self.assertIn('execution log hash mismatch',evidence.validate_contract(payload,ROOT))

    def test_generic_global_pass_cannot_promote_any_row(self):
        build = evidence.build_id(ROOT)
        rows = []
        results = {}
        for index, identifier in enumerate(evidence.REQUIRED):
            case_id = 'case-' + str(index)
            operation_id = 'operation-' + str(index)
            evidence_ref = 'evidence-' + str(index)
            positive = 'positive-' + str(index)
            negative = 'negative-' + str(index)
            results.update({positive: 'PASS', negative: 'PASS'})
            rows.append({
                'id': identifier, 'source': 'software_unittest',
                'evidence_ref': evidence_ref, 'case_id': case_id,
                'stage': 'unit_test', 'operation_id': operation_id,
                'build_id': build, 'positive_tests': [positive],
                'negative_tests': [negative],
                'execution_binding': {
                    'kind': 'unit_test', 'evidence_ref': evidence_ref,
                    'build_id': build, 'case_ids': [case_id],
                    'operation_ids': [operation_id],
                    'test_ids': sorted([positive, negative]),
                },
                'evidence_bindings': [
                    {'kind': 'positive', 'test_id': positive,
                     'outcome': 'PASS', 'evidence_ref': evidence_ref,
                     'case_id': case_id, 'stage': 'unit_test',
                     'operation_id': operation_id, 'build_id': build,
                     'subtest_id': 'sub-' + str(index) + '-positive'},
                    {'kind': 'negative', 'test_id': negative,
                     'outcome': 'PASS', 'evidence_ref': evidence_ref,
                     'case_id': case_id, 'stage': 'unit_test',
                     'operation_id': operation_id, 'build_id': build,
                     'subtest_id': 'sub-' + str(index) + '-negative'},
                ],
                # These are deliberately the old vacuous fields: a global
                # green result must not turn them into row-local evidence.
                'production_entry': 'tools/run_readiness_evidence.py',
                'implementation': ['tools/readiness_evidence.py'],
                'release_files': ['tools/readiness_evidence.py'],
                'live_card': 'readiness-card',
            })
        contract = {
            'schema': 'bridge.readiness.executed_contracts/2',
            'build_id': build, 'rows': rows, 'test_results': results,
            'returncode': 0, 'test_count': len(results),
        }
        matrix = reports.assess(contract, {}, {}, {}, {}, root=ROOT)
        self.assertEqual(matrix['software_preparation_status'], 'NOT_READY')
        self.assertFalse(any(row['status'] == 'PASS' for row in matrix['rows']))
        self.assertTrue(any('evidence_class' in error or 'pending-execution card binding' in error
                            for row in matrix['rows']
                            for error in row['evidence_validation_errors']))

    def test_evidence_tool_and_synthetic_card_are_not_production_receipts(self):
        temporary = tempfile.TemporaryDirectory(prefix='bridge-negative-card-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'tools').mkdir()
        for name in ('run_readiness_evidence.py', 'readiness_evidence.py'):
            (root / 'tools' / name).write_bytes((ROOT / 'tools' / name).read_bytes())
        build = evidence.build_id(root)
        card_path = root / 'outputs/synthetic-card.json'
        card_path.parent.mkdir()
        card_path.write_text(json.dumps({'schema': 'bridge.full_readiness.domain_cases/2.0',
                                        'fixture': 'negative synthetic card'}), encoding='utf-8')
        row = {
            'id': 'P2-PRODUCTION', 'evidence_ref': 'row-evidence',
            'case_id': 'case-production', 'stage': 'unit_test',
            'operation_id': 'readiness-operation-1', 'build_id': build,
            'production_entry': {
                'path': 'tools/run_readiness_evidence.py',
                'sha256': evidence.digest(root / 'tools/run_readiness_evidence.py'),
                'symbol': 'main',
            },
            'implementation': [{
                'path': 'tools/readiness_evidence.py',
                'sha256': evidence.digest(root / 'tools/readiness_evidence.py'),
            }],
            'release_files': [{
                'path': 'tools/readiness_evidence.py',
                'sha256': evidence.digest(root / 'tools/readiness_evidence.py'),
            }],
            'live_card': {
                'path': 'outputs/synthetic-card.json',
                'sha256': evidence.digest(card_path),
                'schema': 'bridge.full_readiness.domain_cases/2.0',
            },
        }
        inspected = evidence.inspect_row_execution_artifacts(row, root, build)
        joined = '\n'.join(inspected['errors'])
        self.assertIn('not a production/release file', joined)
        self.assertIn('live_card', joined)
        self.assertEqual(inspected['operation_ids'], [])

class LivePreflightTests(unittest.TestCase):
    @staticmethod
    def snapshot(request_id, operation_ids, request_operation_ids):
        value = {'request_id':request_id,'source':'controller.operation_registry',
                 'operation_ids':operation_ids,'request_operation_ids':request_operation_ids}
        value['snapshot_sha256'] = preflight._canonical_sha256(value)
        return value

    def current_card_inputs(self, domain='lighting_camera_render_v1'):
        card = json.loads((ROOT / 'docs/real-acceptance-cards' / (domain + '.json')).read_text())
        config = {app: {'version': versions[0], 'plugin_build': 'software-preflight-fixture',
                        'executable': sys.executable}
                  for app, versions in card['required_versions'].items()}
        request = 'software-preflight-request'
        scope = dict(domain_pack=domain, case_id=card['case_id'], frames=[1], seconds=1,
                     disk_bytes=1000, confirmed=True, confirmed_by='software-fixture',
                     task_root='/synthetic/task', content_version='v1', request_id=request,
                     operation_snapshot_before=self.snapshot(request, [], []),
                     operation_snapshot_after=self.snapshot(request, [], []))
        return config, card, scope

    def test_declared_cases_keep_native_basis_gate_and_reject_undeclared_ids(self):
        config, card, scope = self.current_card_inputs()
        with mock.patch('subprocess.Popen', side_effect=AssertionError('preflight must not launch')):
            for case_id in card['case_ids']:
                with self.subTest(case_id=case_id):
                    scope['case_id'] = case_id
                    self.assertEqual(preflight.validate(config, card, scope),
                                     ['native interface basis unresolved'])
            scope['case_id'] = 'foreign__build_inspect'
            self.assertIn('scope/card mismatch', preflight.validate(config, card, scope))
            scope['case_id'] = card['case_id']
            for malformed in (None, [], 'not-a-list', [card['case_id'], card['case_id']],
                              [None], ['other-case']):
                with self.subTest(malformed=malformed):
                    card['case_ids'] = malformed
                    self.assertTrue(any('card case_ids' in error
                                        for error in preflight.validate(config, card, scope)))

    def test_current_card_versions_and_explicit_legacy_card_are_separate(self):
        config, card, scope = self.current_card_inputs()
        for version in ('21.0.631', '22.0.459'):
            config['houdini']['version'] = version
            self.assertEqual(preflight.validate(config, card, scope),
                             ['native interface basis unresolved'])
        config['houdini']['version'] = '22.0.429'
        self.assertIn('houdini: configured version is not allowed by card required_versions',
                      preflight.validate(config, card, scope))
        card['required_versions']['houdini'] = ['22.0.429']
        self.assertEqual(preflight.validate(config, card, scope),
                         ['native interface basis unresolved'])
        for malformed in (None, [], 'not-a-list', [None]):
            card['required_versions']['houdini'] = malformed
            self.assertTrue(any('card required_versions' in error
                                for error in preflight.validate(config, card, scope)))
        config, card, scope = self.current_card_inputs('nuke_composite_v1')
        config.pop('houdini', None)
        self.assertEqual(preflight.validate(config, card, scope),
                         ['native interface basis unresolved'])

    def test_no_host_start_and_missing_exact_scope_refused(self):
        errors = preflight.validate({}, {'domain_pack':'nuke_composite_v1'}, {})
        self.assertTrue(any('version' in e for e in errors))
        self.assertTrue(any('frames' in e for e in errors))
        self.assertTrue(any('confirmation' in e for e in errors))

    def test_valid_preflight_is_only_read_only(self):
        card = {key:['concrete expected fact'] for key in ('expected_nodes','expected_connections','key_parameters','native_basis','save_reopen','stop_recovery','artifact_checks','raw_evidence_path','human_checks')}
        card.update(domain_pack='nuke_composite_v1',case_id='nuke-build',native_basis_status='VERIFIED_SOURCE')
        config = {'nuke':{'version':'17.0v1','plugin_build':'synthetic-build','executable':sys.executable}}
        request_id='request-nuke-build'
        before=self.snapshot(request_id,['historical-op-1'],['historical-op-1'])
        after=self.snapshot(request_id,['historical-op-1'],['historical-op-1'])
        scope = dict(domain_pack='nuke_composite_v1',case_id='nuke-build',frames=[1,2],seconds=5,disk_bytes=1000,confirmed=True,confirmed_by='operator',task_root='/synthetic/task',content_version='v1',request_id=request_id,operation_snapshot_before=before,operation_snapshot_after=after)
        with mock.patch('subprocess.run',side_effect=AssertionError('preflight must not launch')):
            self.assertEqual(preflight.validate(config,card,scope),[])
        scope['operation_snapshot_after']=self.snapshot(request_id,['historical-op-1','new-op'],['historical-op-1','new-op'])
        self.assertTrue(any('before/after operation snapshots' in error for error in preflight.validate(config,card,scope)))
        scope['seconds']=float('nan')
        self.assertTrue(preflight.validate(config,card,scope))


class EvidenceExecutionSemanticsTests(unittest.TestCase):
    def test_functional_row_cannot_be_reclassified_as_static(self):
        row={'id':'P2-PRODUCTION','evidence_class':'static','evidence_ref':'row-ref',
             'build_id':evidence.build_id(ROOT),'positive_tests':['p'],'negative_tests':['n'],
             'execution_binding':{'kind':'unit_test','evidence_ref':'row-ref','build_id':evidence.build_id(ROOT),
                                  'case_ids':['case'],'stages':['stage'],'operation_ids':[],'test_ids':['n','p']},
             'evidence_bindings':[]}
        errors=evidence.validate_contract_rows({'build_id':evidence.build_id(ROOT),'rows':[row]},ROOT,
                                               check_results=False,check_artifacts=False)
        self.assertTrue(any('frozen row policy' in error for error in errors['P2-PRODUCTION']))

    def test_actual_runner_captures_assertion_refs_and_real_subtests(self):
        class TracedCase(unittest.TestCase):
            def test_assertions(self):
                completed=subprocess.run([sys.executable,'-c',"print('runner-observed')"],
                                         capture_output=True,text=True)
                self.assertEqual(completed.stdout,'runner-observed\n')
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertGreater(value, 0)

        stream=io.StringIO()
        result=unittest.TextTestRunner(stream=stream,resultclass=execution_runner.Result).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(TracedCase))
        self.assertTrue(result.wasSuccessful(),stream.getvalue())
        test_id=next(iter(result.test_executions))
        execution=result.test_executions[test_id]
        self.assertEqual(execution['outcome'],'PASS')
        self.assertEqual(execution['static_invocations'],[{
            'argv':[sys.executable,'-c',"print('runner-observed')"],
            'returncode':0,'stdout':'runner-observed\n','stderr':''}])
        self.assertEqual(len(execution['subtests']),2)
        self.assertTrue(execution['assertion_refs'])
        self.assertTrue(all('subtest_id' not in subtest for subtest in execution['subtests']))
        source_paths={source['path'] for source in execution['source_files']}
        self.assertTrue(all(ref.rsplit(':',1)[0] in source_paths for ref in execution['assertion_refs']))

    def test_same_real_test_and_assertion_can_support_multiple_rows(self):
        class TracedCase(unittest.TestCase):
            def test_assertions(self):
                self.assertTrue(True)
                self.assertEqual(2, 2)

        result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=execution_runner.Result).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(TracedCase))
        test_id=next(iter(result.test_executions))
        execution=result.test_executions[test_id]
        refs=execution['assertion_refs']
        self.assertGreaterEqual(len(refs),2)
        build=evidence.build_id(ROOT)
        rows=[]
        for identifier in ('C1-A','P2-PRODUCTION'):
            ref='evidence-'+identifier
            rows.append({
                'id':identifier,'evidence_class':'functional','evidence_ref':ref,'build_id':build,
                'positive_tests':[test_id],'negative_tests':[test_id],
                'execution_binding':{'kind':'unit_test','evidence_ref':ref,'build_id':build,
                                     'case_ids':['case-'+identifier],'stages':['unit-test'],
                                     'operation_ids':[],'test_ids':[test_id]},
                'evidence_bindings':[
                    {'kind':'positive','test_id':test_id,'evidence_type':'formal_operation',
                     'evidence_ref':ref,'build_id':build,'outcome':'PASS','assertion_refs':[refs[0]]},
                    {'kind':'negative','test_id':test_id,'evidence_type':'preflight_rejection',
                     'evidence_ref':ref,'build_id':build,'outcome':'PASS','assertion_refs':[refs[1]]},
                ],
            })
        payload={'build_id':build,'rows':rows,'test_results':result.outcomes,
                 'test_executions':result.test_executions}
        self.assertEqual(evidence.validate_contract_rows(payload,ROOT,check_artifacts=False),{})

    def test_static_receipt_binds_executed_script_inputs_and_output_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            package=root/'packages'/'native_contract.py'
            package.parent.mkdir(parents=True)
            package.write_text('def inspect_native_basis():\n    return True\n')
            script=root/'tests'/'check_native.py'
            script.parent.mkdir(parents=True)
            script.write_text("from pathlib import Path\nassert 'verified' in Path(__file__).parents[1].joinpath('docs','native.txt').read_text()\nimport sys\nassert sys.argv[1:] == ['ok']\nprint('verified')\n")
            input_path=root/'docs'/'native.txt'
            input_path.parent.mkdir(parents=True)
            input_path.write_text('verified\n')
            release=root/'outputs'/'release.bin'
            release.parent.mkdir(parents=True)
            release.write_bytes(b'release')
            captured={}
            class StaticCase(unittest.TestCase):
                def test_script(self):
                    completed=subprocess.run(captured['argv'],cwd=root,capture_output=True,text=True)
                    captured['completed']=completed
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    self.assertEqual(completed.stdout,'verified\n')
            captured['argv']=[sys.executable,str(script),'ok']
            runner_result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=execution_runner.Result).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(StaticCase))
            self.assertTrue(runner_result.wasSuccessful())
            completed=captured['completed']
            observed=next(iter(runner_result.test_executions.values()))['static_invocations']
            self.assertEqual(observed,[{'argv':captured['argv'],'returncode':0,
                                       'stdout':completed.stdout,'stderr':completed.stderr}])
            build=evidence.build_id(root)
            card_doc={'schema':'bridge.readiness.live_card/1','state':'PENDING_EXECUTION',
                      'build_id':build,'case_id':'native-case','content_version':'native-v1',
                      'resource_id':'hda-capture','confirmations':{}}
            for field,value in (('case_id','native-case'),('content_version','native-v1'),('resource_id','hda-capture')):
                card_doc['confirmations'][field]={'value':value,'confirmed':False,
                                                  'step':'Confirm the exact '+field+' before execution'}
            card_path=root/'outputs'/'card.json'
            card_path.write_text(json.dumps(card_doc))
            receipt={
                'schema':'bridge.readiness.static_check/1','build_id':build,
                'case_id':'native-case','stage':'native-doc-audit','status':'PASS',
                'script':{'path':'tests/check_native.py','sha256':evidence.digest(script)},
                'inputs':[{'path':'docs/native.txt','sha256':evidence.digest(input_path)}],
                'execution':{'argv':captured['argv'],'returncode':completed.returncode,
                             'script_sha256':evidence.digest(script),'stdout':completed.stdout,
                             'stdout_sha256':hashlib.sha256(completed.stdout.encode('utf-8')).hexdigest(),
                             'stderr':completed.stderr,
                             'stderr_sha256':hashlib.sha256(completed.stderr.encode('utf-8')).hexdigest(),
                             'started_at':'2026-09-30T00:00:00Z','finished_at':'2026-09-30T00:00:01Z'},
                'assertions':[{'assertion_ref':'tests/check_native.py:2','outcome':'PASS'}],
            }
            receipt['receipt_sha256']=evidence._canonical_sha256(receipt)
            receipt_path=root/'outputs'/'static-check.json'

            def make_row():
                receipt_path.write_text(json.dumps(receipt))
                return {
                    'id':'P3-NATIVE-VERSIONS','build_id':build,'evidence_ref':'static-row-1',
                    'content_version':'native-v1','resource_id':'hda-capture',
                    'production_entry':{'path':'packages/native_contract.py',
                                       'sha256':evidence.digest(package),'symbol':'inspect_native_basis'},
                    'implementation':[{'path':'packages/native_contract.py','sha256':evidence.digest(package)}],
                    'release_files':[{'path':'outputs/release.bin','sha256':evidence.digest(release)}],
                    'live_card':{'path':'outputs/card.json','sha256':evidence.digest(card_path),
                                 'schema':'bridge.readiness.live_card/1'},
                    'execution_binding':{'case_ids':['native-case'],'stages':['native-doc-audit'],
                                         'operation_ids':[]},
                    'evidence_bindings':[{'kind':'positive','evidence_type':'static_check',
                        'assertion_refs':['tests/check_native.py:2'],
                        'receipt':{'path':'outputs/static-check.json',
                                   'sha256':evidence.digest(receipt_path)}}],
                }

            inspected=evidence.inspect_row_execution_artifacts(make_row(),root,build)
            self.assertEqual(inspected['errors'],[])
            for argv in ([sys.executable,'-I','-u',str(script),'ok'],
                         [sys.executable,'--',str(script),'ok']):
                captured['argv']=argv
                runner_result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=execution_runner.Result).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(StaticCase))
                self.assertTrue(runner_result.wasSuccessful())
                invocation=receipt['execution']
                invocation['argv']=argv
                completed=captured['completed']
                self.assertEqual(next(iter(runner_result.test_executions.values()))['static_invocations'],
                                 [{'argv':argv,'returncode':completed.returncode,
                                   'stdout':completed.stdout,'stderr':completed.stderr}])
                receipt.pop('receipt_sha256')
                receipt['receipt_sha256']=evidence._canonical_sha256(receipt)
                self.assertEqual(evidence.inspect_row_execution_artifacts(make_row(),root,build)['errors'],[])
            for argv in (['/usr/bin/true'],[sys.executable,'-c',str(script),'ok'],
                         [sys.executable,'-m',str(script),'ok']):
                receipt['execution']['argv']=argv
                receipt.pop('receipt_sha256')
                receipt['receipt_sha256']=evidence._canonical_sha256(receipt)
                inspected=evidence.inspect_row_execution_artifacts(make_row(),root,build)
                self.assertTrue(any('argv does not execute the bound script' in error for error in inspected['errors']))
            receipt['execution']['argv']=[sys.executable,str(script),'ok']
            del card_doc['confirmations']['resource_id']['step']
            card_path.write_text(json.dumps(card_doc))
            receipt.pop('receipt_sha256')
            receipt['receipt_sha256']=evidence._canonical_sha256(receipt)
            inspected=evidence.inspect_row_execution_artifacts(make_row(),root,build)
            self.assertTrue(any('resource_id confirmation' in error for error in inspected['errors']))
            receipt['inputs']=[]
            receipt.pop('receipt_sha256')
            receipt['receipt_sha256']=evidence._canonical_sha256(receipt)
            inspected=evidence.inspect_row_execution_artifacts(make_row(),root,build)
            self.assertTrue(any('inputs must be content-addressed' in error for error in inspected['errors']))

    def test_operation_receipt_digest_is_recomputed_not_shape_checked(self):
        render={'schema':'bridge.houdini.render.execution_fact/1.0', 'command':'render.start',
                'kind':'render', 'operation_id':'formal-render', 'request_id':'formal-render',
                'state':'COMPLETED', 'frame_set':[1], 'frame_snapshots':{}, 'stop_confirmed':True}
        render['operation_receipt_sha256']=evidence._canonical_sha256(render)
        self.assertEqual(evidence._receipt_digest(render),
                         (render['operation_receipt_sha256'],render['operation_receipt_sha256']))
        self.assertEqual(evidence._producer_stage(render),'render')
        self.assertTrue(evidence._formal_receipt_source_errors(render,'receipt'))
        render['command']='agent.fx.collect_evidence'
        self.assertIsNone(evidence._producer_stage(render))
        document={'schema':'bridge.houdini.scene-transition-operation/1.0',
                  'operation_id':'scene-real-source-1','state':'COMPLETED','stage':'save',
                  'build_id':'build-1','case_id':'case-1'}
        document['operation_receipt_sha256']=evidence._canonical_sha256(document)
        supplied,computed=evidence._receipt_digest(document)
        self.assertEqual(supplied,computed)
        document['state']='FAILED'
        supplied,computed=evidence._receipt_digest(document)
        self.assertNotEqual(supplied,computed)
        boundary={'schema':'bridge.houdini.software-boundary-fact/1.0','task_id':'task-1',
                  'operation_id':'op-1','result':{'operation_id':'op-1','formal_operation':False,
                                                  'software_boundary_execution':'diagnostic_only'}}
        boundary['operation_receipt_sha256']=evidence._canonical_sha256(boundary)
        supplied,computed=evidence._receipt_digest(boundary)
        self.assertEqual(supplied,computed)
        self.assertTrue(any('diagnostic' in error or 'not a formal operation' in error
                            for error in evidence._formal_receipt_source_errors(boundary,'receipt')))
        boundary['result']={'operation_id':'op-1','formal_operation':True,
                            'software_boundary_execution':'production_formal'}
        boundary.pop('operation_receipt_sha256',None)
        boundary['operation_receipt_sha256']=evidence._canonical_sha256(boundary)
        self.assertTrue(evidence._formal_receipt_source_errors(boundary,'receipt'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            entry=root/'packages'/'formal_entry.py'
            entry.parent.mkdir(parents=True)
            entry.write_text('def launch():\n    return True\n')
            release=root/'outputs'/'skill.zip'
            release.parent.mkdir(parents=True)
            release.write_bytes(b'candidate')
            build=evidence.build_id(root)
            card_doc={'schema':'bridge.readiness.live_card/1','state':'PENDING_EXECUTION',
                      'build_id':build,'case_id':'case-1','content_version':'v1',
                      'resource_id':'resource-1','confirmations':{}}
            for field,value in (('case_id','case-1'),('content_version','v1'),('resource_id','resource-1')):
                card_doc['confirmations'][field]={'value':value,'confirmed':False,
                                                  'step':'Confirm the exact '+field+' before execution'}
            card_path=root/'outputs'/'card.json'
            card_path.write_text(json.dumps(card_doc))
            receipt_path=root/'outputs'/'operation.json'

            def wrap(provider_fact, stage):
                return {'schema':'bridge.readiness.formal_operation/1','build_id':build,
                        'case_id':'case-1','stage':stage,
                        'operation_id':provider_fact['operation_id'],'state':provider_fact['state'],
                        'operation_receipt_sha256':provider_fact['operation_receipt_sha256'],
                        'provider_fact':provider_fact}

            diagnostic_fact={'schema':'bridge.houdini.software-boundary-fact/1.0',
                             'task_id':'task-1','operation_id':'op-1','state':'COMPLETED',
                             'result':{'operation_id':'op-1','formal_operation':False,
                                       'software_boundary_execution':'diagnostic_only'}}
            diagnostic_fact['operation_receipt_sha256']=evidence._canonical_sha256(diagnostic_fact)
            operation=wrap(diagnostic_fact,'render')

            def row_for_current_receipt():
                receipt_path.write_text(json.dumps(operation))
                entry_binding={'path':'packages/formal_entry.py','sha256':evidence.digest(entry)}
                return {
                    'id':'P2-PRODUCTION','build_id':build,'evidence_ref':'row-1',
                    'content_version':'v1','resource_id':'resource-1',
                    'production_entry':dict(entry_binding,symbol='launch'),
                    'implementation':[entry_binding],
                    'release_files':[{'path':'outputs/skill.zip','sha256':evidence.digest(release)}],
                    'live_card':{'path':'outputs/card.json','sha256':evidence.digest(card_path),
                                 'schema':'bridge.readiness.live_card/1'},
                    'execution_binding':{'case_ids':['case-1'],'stages':[operation['stage']],
                                         'operation_ids':[operation['operation_id']]},
                    'evidence_bindings':[{'kind':'positive','evidence_type':'formal_operation',
                                          'receipt':{'path':'outputs/operation.json',
                                                     'sha256':evidence.digest(receipt_path)}}],
                }

            inspected=evidence.inspect_row_execution_artifacts(row_for_current_receipt(),root,build)
            self.assertTrue(any('diagnostic' in error for error in inspected['errors']))
            nuke_fact={'schema':'bridge.nuke.execution_fact/1.0','task_id':'task-real',
                       'state':'COMPLETED','stop_confirmed':True,'kind':'owned_subprocess',
                       'pattern':'/tmp/out.%04d.exr','frame_set':[1],'frame_snapshots':{}}
            basis={'task_id':'task-real','pattern':nuke_fact['pattern'],'frame_set':[1],
                   'scene_fingerprint':'f'*64,'frame_snapshots':{},'state':'COMPLETED',
                   'execution_kind':'owned_subprocess'}
            for outer_schema in ('bridge.arbitrary/1','bridge.nuke.render-operation/1'):
                operation={'schema':outer_schema,'build_id':build,'case_id':'case-1',
                           'stage':'render','operation_id':'render-real-source-1','state':'COMPLETED',
                           'scene_fingerprint':'f'*64,'output_pattern':nuke_fact['pattern'],
                           'frame_set':[1],'frame_snapshots':{},'execution_fact':nuke_fact,'result':{},
                           'operation_receipt_sha256':evidence._canonical_sha256(basis)}
                inspected=evidence.inspect_row_execution_artifacts(row_for_current_receipt(),root,build)
                self.assertTrue(any('unsupported formal-operation' in error for error in inspected['errors']))
                self.assertIsNone(evidence._producer_stage(operation))
                self.assertEqual(evidence._receipt_digest(operation),(None,None))
            diagnostic_fact['schema']='bridge.houdini.scene-transition-operation/1.0'
            diagnostic_fact.pop('operation_receipt_sha256')
            diagnostic_fact['operation_receipt_sha256']=evidence._canonical_sha256(diagnostic_fact)
            operation=wrap(diagnostic_fact,'scene.open_hip')
            inspected=evidence.inspect_row_execution_artifacts(row_for_current_receipt(),root,build)
            self.assertTrue(any('diagnostic' in error for error in inspected['errors']))
            self.assertTrue(any('request' in error for error in inspected['errors']))
            environment={'HOUDINI_BRIDGE_STATE_DIR':str(root/'houdini-state'),
                         'BRIDGE_SKILLS_STATE_ROOT':str(root/'installation-state'),
                         'BRIDGE_SKILLS_SCHEDULER_ROOT':str(root/'scheduler-state')}
            with mock.patch.dict(os.environ,environment,clear=False), mock.patch.dict(sys.modules):
                from vfx_pipeline.workbuddy_assembly import software_host_client
                client,addon=software_host_client(
                    ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',root/'host')
                scene=root/'scene.hip'
                sys.modules['hou'].hipFile.save(str(scene))
                scene_hash=evidence.digest(scene)
                before=addon._host_identity()
                captured={}
                class SceneCase(unittest.TestCase):
                    def test_scene(self):
                        case_id='case-1'
                        result=client.call('scene.open_hip',{'path':str(scene),'sha256':scene_hash,
                            'task_id':'readiness-formal-source','operation_id':'scene-open-formal',
                            'request_id':'request-formal','scene_before_identity':before})
                        captured['provider_fact']=result['scene_transition']
                        self.assertEqual(result['scene_transition']['state'],'COMPLETED')
                runner_result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=execution_runner.Result).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(SceneCase))
                self.assertTrue(runner_result.wasSuccessful())
                provider_fact=captured['provider_fact']
                execution=next(iter(runner_result.test_executions.values()))
                context={'build_id':evidence.build_id(ROOT),'case_id':'case-1',
                         'provider_sha256':evidence._canonical_sha256(provider_fact),
                         'operation_receipt_sha256':provider_fact['operation_receipt_sha256']}
                self.assertIn(context,execution['provider_facts'])
                self.assertEqual(provider_fact['schema'],'bridge.houdini.scene-transition-operation/1.0')
                self.assertEqual(provider_fact['operation_receipt_sha256'],
                                 addon._fx_scene_transition_digest(provider_fact))
                operation=wrap(provider_fact,'scene.open_hip')
            inspected=evidence.inspect_row_execution_artifacts(row_for_current_receipt(),root,build)
            self.assertEqual(inspected['errors'],[])
            valid_row=row_for_current_receipt()
            binding=valid_row['evidence_bindings'][0]
            test_id=next(iter(runner_result.test_executions))
            binding.update(test_id=test_id,assertion_refs=execution['assertion_refs'])
            valid_row.update(evidence_class='functional',positive_tests=[test_id],negative_tests=[])
            valid_row['build_id']=context['build_id']
            valid_row['execution_binding'].update(kind='unit_test',evidence_ref='row-1',
                                                build_id=context['build_id'],test_ids=[test_id])
            payload={'build_id':context['build_id'],'rows':[valid_row],
                     'test_results':runner_result.outcomes,
                     'test_executions':runner_result.test_executions}
            errors=evidence.validate_contract_rows(payload,root)
            self.assertFalse(any('case/build/provider' in message
                                 for messages in errors.values() for message in messages))
            execution['provider_facts'][0]['case_id']='unrelated-case'
            errors=evidence.validate_contract_rows(payload,root)
            self.assertTrue(any('case/build/provider' in message
                                for messages in errors.values() for message in messages))
            operation['stage']='render'
            operation['case_id']='lighting_camera_render_v1__build_inspect'
            domain_row=row_for_current_receipt()
            domain_row['id']='DOMAIN-lighting_camera_render_v1'
            inspected=evidence.inspect_row_execution_artifacts(domain_row,root,build)
            self.assertTrue(any('stage does not match' in error for error in inspected['errors']))
            domain_row['execution_binding'].update(kind='domain_scenarios',build_id=build)
            observed=dict(domain_row['execution_binding'])
            self.assertTrue(reports._row_binding_matches(domain_row,observed,'domain_scenarios'))

class InstalledLifecycleTests(unittest.TestCase):
    def test_shipped_installer_requires_explicit_target(self):
        result = subprocess.run([sys.executable,'-I',str(ROOT/'skills/nuke-bridge/scripts/install_runtime.py')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--target is required',result.stderr)

    def test_real_upgrade_rollback_and_uninstall_all_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=subprocess.run([sys.executable,str(ROOT/'tools/build_release.py'),'2.0.0-lifecycle-test','--output',str(root/'release')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            release=root/'release/v2.0.0-lifecycle-test'
            manifest=json.loads((release/'release-manifest.json').read_text())
            for artifact in manifest['artifacts']:
                with self.subTest(skill=artifact['skill']):
                    receipt=lifecycle._artifact_lifecycle(release/artifact['archive'],artifact,root/artifact['skill'],root/'lifecycle-evidence')
                    self.assertTrue(receipt['passed'],receipt)

if __name__=='__main__':unittest.main()

class WorkBuddyCurrentSupportTests(unittest.TestCase):
    def fixture(self, root, *, provider=True):
        import verify_support_claims as support
        from test_workbuddy_acceptance import WorkBuddyAcceptanceTests
        helper=WorkBuddyAcceptanceTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        manifest=helper.manifest(route=helper.route(provider_verified=provider))
        path=root/'manifest.json'; path.write_text(json.dumps(manifest.to_dict()))
        route=manifest.route
        binding={'route':{'session_id':route.session_id,'manifest_sha256':manifest.manifest_sha256,'selected_model':'hy3','executable_sha256':route.app.executable_sha256}}
        if route.provider_evidence:
            p=route.provider_evidence
            binding['provider']={'session_id':route.session_id,'exchange_id':p.exchange_id,'model':'hy3','witness_sha256':p.witness_sha256,'provider_response_sha256':p.provider_response_sha256}
        row={'schema':'bridge.workbuddy.release_attestation/1','evidence_id':'synthetic-signed-fixture','route_id':'WorkBuddyDesktopRoute','source':'real_host','status':'passed','build_id':evidence.build_id(root),'manifest_path':'manifest.json','manifest_sha256':evidence.digest(path),'witness_bindings':binding}
        self.sign(row)
        return row
    def sign(self,row):
        import verify_support_claims as support
        row['evidence_identity']=support.evidence_identity(row)
        row['evidence_attestation']=support.evidence_attestation(row,b'synthetic-test-key')
    def test_signed_atomic_events_pass_recomputed_gate(self):
        import verify_support_claims as support
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();row=self.fixture(root)
            valid, errors=support._validated_workbuddy_runs({'workbuddy_runs':[row]},root,b'synthetic-test-key')
            self.assertEqual(errors,[])
            self.assertEqual(len(valid),1)
            self.assertEqual(valid[0]['evaluation']['case_count'],48)
    def test_unknown_provider_wrong_route_and_software_never_promote(self):
        import verify_support_claims as support
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();row=self.fixture(root,provider=False)
            self.assertTrue(support._validated_workbuddy_runs({'workbuddy_runs':[row]},root,b'synthetic-test-key')[1])
            for field,value in [('route_id','DoubaoDesktopRoute'),('source','software_unittest')]:
                row=self.fixture(root);row[field]=value;self.sign(row)
                self.assertTrue(support._validated_workbuddy_runs({'workbuddy_runs':[row]},root,b'synthetic-test-key')[1])
    def test_tampered_signature_and_changed_manifest_reject(self):
        import verify_support_claims as support
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();row=self.fixture(root)
            self.assertTrue(support._validated_workbuddy_runs({'workbuddy_runs':[row]},root,b'wrong-key')[1])
            (root/'manifest.json').write_text('{}')
            self.assertTrue(support._validated_workbuddy_runs({'workbuddy_runs':[row]},root,b'synthetic-test-key')[1])


class PackageEvidenceRelocationTests(unittest.TestCase):
    """Finite local fixtures exercise package reads, never native host acceptance."""

    def fixture(self, root):
        from dcc_task_runtime.exr_codec import encode_tiny_exr, read_exr
        root = root.resolve()
        source = root / 'original-development'
        for name, data in [('tools/static.py', b'print("fixture")\n'),
                           ('packages/entry.py', b'def launch(): return True\n'),
                           ('outputs/run.log', b'finite fixture log\n'),
                           ('outputs/scene.hip', b'finite saved scene fixture\n'),
                           ('outputs/frame.exr', encode_tiny_exr())]:
            path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        supervisor = source / 'outputs/supervisor'
        owned = evidence._owned_receipt_module()
        identity = {'task_id': 'finite-local-fixture', 'ownership_token': 'fixture-token'}
        executable = getattr(sys, '_base_executable', sys.executable)
        handle = owned.launch([executable, '-c', 'pass'], directory=supervisor, identity=identity,
                              supervisor_executable=executable, budget_seconds=10)
        try:
            self.assertEqual(handle.wait(10), 0)
        finally:
            if handle.poll() is None:
                handle.terminate()
                handle.wait(10)
        stop = handle.receipt()
        self.assertIsNotNone(stop)
        self.assertEqual(owned.read_receipt(supervisor, 'stopped', identity=identity), stop)
        frame = source / 'outputs/frame.exr'; scene = source / 'outputs/scene.hip'
        image = read_exr(frame, with_pixels=False)
        snapshot = {'path': str(frame), 'sha256': evidence.digest(frame),
                    'bytes': frame.stat().st_size, 'modified_ns': frame.stat().st_mtime_ns,
                    'exr': {key: image[key] for key in ('width', 'height', 'channels', 'compression')}}
        provider = {'schema': 'bridge.houdini.render.execution_fact/1.0',
                    'frame_snapshots': {'1': snapshot},
                    'render_config': {'1': {'exr_format': {'compression': 'none'}}},
                    'scene': {'snapshot_path': str(scene), 'snapshot_sha256': evidence.digest(scene)},
                    'stop_basis': stop, 'supervisor_binding': {'directory': str(supervisor), 'identity': identity}}
        provider['operation_receipt_sha256'] = evidence._canonical_sha256(provider)
        static = {'schema': 'bridge.readiness.static_check/1',
                  'script': {'path': 'tools/static.py', 'sha256': evidence.digest(source / 'tools/static.py')},
                  'execution': {'argv': [sys.executable, '-B', '--', str(source / 'tools/static.py')]}}
        receipt = source / 'outputs/receipt.json'; receipt.write_text(json.dumps(provider))
        log_binding = {'path': 'outputs/run.log', 'sha256': evidence.digest(source / 'outputs/run.log')}
        values = [provider, static, log_binding,
                  {'path': 'outputs/receipt.json', 'sha256': evidence.digest(receipt)}]
        build = evidence.build_id(source)
        package = root / 'relocated-package'
        delivery._copy_source(source, package / 'source/bridge-skills')
        delivery._copy_bound_evidence(values, source, package / 'evidence/bound-files')
        anchor = self.manifest(package)
        return source, package, anchor, provider, static, log_binding, build

    @staticmethod
    def manifest(package):
        manifest = package / 'package-manifest.json'
        manifest.unlink(missing_ok=True)
        files = delivery._manifest(package)
        delivery._write_json(manifest, {'schema': 'bridge.s06.package_manifest/1.0',
                                       'file_count': len(files), 'files': files})
        return evidence.digest(manifest)

    def test_original_directory_removed_preserves_raw_facts_and_existing_readers(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            source, package, anchor, provider, static, log, build = self.fixture(Path(tmp))
            original = {str(path): path.read_bytes() for path in (source / 'outputs').rglob('*') if path.is_file()}
            self.assertEqual(evidence._render_file_errors(provider, 'fixture'), [])
            argv = list(static['execution']['argv'])
            shutil.rmtree(source)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            self.assertEqual(evidence.build_id(resolver.source_root, resolver=resolver), build)
            self.assertEqual(evidence._render_file_errors(provider, 'fixture', resolver=resolver), [])
            nuke = {'schema': 'bridge.nuke.render-operation/1.0',
                    'frame_snapshots': provider['frame_snapshots'],
                    'execution_fact': {'kind': 'owned_subprocess',
                        'worker_receipt': {'snapshot': provider['scene']['snapshot_path'],
                                           'snapshot_sha256': provider['scene']['snapshot_sha256']},
                        'process_identity': {'supervisor_directory': provider['supervisor_binding']['directory'],
                                             'supervisor_identity': provider['supervisor_binding']['identity'],
                                             'pid': provider['stop_basis']['pid']}}}
            self.assertEqual(evidence._render_file_errors(nuke, 'fixture', resolver=resolver), [])
            self.assertEqual(resolver.read_supervisor(provider['supervisor_binding']['directory'],
                             provider['supervisor_binding']['identity']), provider['stop_basis'])
            self.assertTrue(evidence._static_argv_executes_script(argv, resolver.source_root,
                            'tools/static.py', resolver=resolver, script_sha256=static['script']['sha256']))
            self.assertEqual(static['execution']['argv'], argv)
            raw, _, errors = evidence._read_receipt(resolver.source_root,
                {'path': 'outputs/receipt.json', 'sha256': hashlib.sha256(original[str(source / 'outputs/receipt.json')]).hexdigest()},
                'fixture', ('outputs/',), check_files=True, resolver=resolver)
            self.assertEqual(errors, []); self.assertEqual(raw, provider)
            path = evidence._evidence_file(resolver.source_root, log['path'], log['sha256'], resolver)
            self.assertEqual(path.read_bytes(), original[str(source / log['path'])])
            for logical, entry in resolver.path_map.items():
                if logical in original:
                    self.assertEqual((package / entry['package_relative_path']).read_bytes(), original[logical])
            stale = {'schema': 'bridge.readiness.executed_contracts/2', 'build_id': '0' * 64, 'rows': []}
            self.assertIn('source build does not match executed evidence',
                          evidence.validate_contract(stale, resolver.source_root, resolver=resolver))

    def test_manifest_map_and_producer_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, package, anchor, provider, static, _, _ = self.fixture(Path(tmp))
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            frame = provider['frame_snapshots']['1']; logical = frame['path']
            for kwargs in ({'expected_sha256': '0' * 64},
                           {'expected_sha256': frame['sha256'], 'expected_bytes': frame['bytes'] + 1},
                           {'expected_sha256': frame['sha256'], 'producer_modified_ns': frame['modified_ns'] + 1}):
                with self.assertRaises(ValueError): resolver.resolve(logical, **kwargs)
            with self.assertRaises(ValueError): resolver.resolve('/unmapped/path', expected_sha256=frame['sha256'])
            with self.assertRaises(ValueError): evidence.PackageEvidenceResolver(package, manifest_sha256='0' * 64)
            with self.assertRaises(ValueError): resolver.source_file('../outside.py')
            with self.assertRaises(ValueError): resolver.package_input(source / 'outputs/receipt.json')
            bad = json.loads(json.dumps(provider)); bad['frame_snapshots']['1']['modified_ns'] += 1
            self.assertTrue(evidence._render_file_errors(bad, 'fixture', resolver=resolver))
            map_path = package / 'evidence/bound-files/path-map.json'
            baseline = map_path.read_bytes(); path_map = json.loads(baseline)
            mutations = []
            missing = dict(path_map); missing.pop(logical); mutations.append(missing)
            duplicate = dict(path_map); duplicate['/alias'] = dict(path_map[logical], original_logical_path='/alias', sha256='0' * 64); mutations.append(duplicate)
            for field, value in [('package_relative_path', '../escape'),
                                 ('package_relative_path', 'evidence/./bound-files/frame.exr'),
                                 ('package_relative_path', 'evidence//bound-files/frame.exr'),
                                 ('sha256', '0' * 64), ('bytes', frame['bytes'] + 1)]:
                changed = json.loads(baseline); changed[logical][field] = value; mutations.append(changed)
            for changed in mutations:
                map_path.write_text(json.dumps(changed)); changed_anchor = self.manifest(package)
                if logical not in changed:
                    candidate = evidence.PackageEvidenceResolver(package, manifest_sha256=changed_anchor)
                    with self.assertRaises(ValueError): candidate.resolve(logical, expected_sha256=frame['sha256'])
                else:
                    with self.assertRaises(ValueError): evidence.PackageEvidenceResolver(package, manifest_sha256=changed_anchor)
            map_path.write_bytes(baseline); anchor = self.manifest(package)
            target = package / path_map[logical]['package_relative_path']
            data = target.read_bytes(); target.write_bytes(b'changed')
            with self.assertRaises(ValueError): evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            with self.subTest(attack='symbolic-link'):
                target.write_bytes(data); target.unlink(); _require_symlink(target, source / 'outputs/frame.exr')
                with self.assertRaises(ValueError): evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)

    def test_original_supervisor_authentication_and_start_stop_binding_remain_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, package, anchor, provider, _, _, _ = self.fixture(Path(tmp))
            mapping = json.loads((package / 'evidence/bound-files/path-map.json').read_text())
            directory = provider['supervisor_binding']['directory']; identity = provider['supervisor_binding']['identity']
            with self.assertRaises(ValueError):
                evidence.PackageEvidenceResolver(package, manifest_sha256=anchor).read_supervisor(directory, {})
            stopped_logical = str(Path(directory) / 'stopped.json')
            started_logical = str(Path(directory) / 'started.json')
            stopped = package / mapping[stopped_logical]['package_relative_path']
            envelope = json.loads(stopped.read_text()); envelope['payload']['exit_code'] = 99
            stopped.write_text(json.dumps(envelope))
            # Rebind only package metadata; the original HMAC must still reject.
            entry = mapping[stopped_logical]; entry['sha256'] = evidence.digest(stopped); entry['bytes'] = stopped.stat().st_size
            delivery._write_json(package / 'evidence/bound-files/path-map.json', mapping)
            anchor = self.manifest(package)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            with self.assertRaises(ValueError): resolver.read_supervisor(directory, identity)
            owned = evidence._owned_receipt_module()
            payload = dict(provider['stop_basis'], started_sha256='0' * 64)
            owned._signed_write(stopped.parent, payload)
            entry['sha256'] = evidence.digest(stopped); entry['bytes'] = stopped.stat().st_size
            delivery._write_json(package / 'evidence/bound-files/path-map.json', mapping)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=self.manifest(package))
            with self.assertRaisesRegex(ValueError, 'SUPERVISOR_STOP_NOT_BOUND'):
                resolver.read_supervisor(directory, identity)
            started = package / mapping[started_logical]['package_relative_path']
            started.unlink()
            with self.assertRaises(ValueError): resolver.read_supervisor(directory, identity)

    def test_supervisor_private_snapshots_remain_readonly_and_are_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, package, anchor, provider, _, _, _ = self.fixture(Path(tmp))
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            directory = provider['supervisor_binding']['directory']
            identity = provider['supervisor_binding']['identity']
            owned = evidence._owned_receipt_module()
            verifier = owned.read_receipt
            snapshots = set()

            def observe(snapshot_directory, event, *, identity):
                root = Path(snapshot_directory)
                snapshots.add(root)
                for name in ('started.json', 'stopped.json', 'receipt.key'):
                    info = (root / name).stat()
                    if os.name == 'nt':
                        self.assertTrue(info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
                    else:
                        self.assertEqual(stat.S_IMODE(info.st_mode), 0o400)
                if os.name != 'nt':
                    self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
                return verifier(snapshot_directory, event, identity=identity)

            with mock.patch.object(owned, 'read_receipt', side_effect=observe):
                self.assertEqual(resolver.read_supervisor(directory, identity), provider['stop_basis'])
                with self.assertRaisesRegex(ValueError, 'SUPERVISOR_RECEIPT_MISMATCH'):
                    resolver.read_supervisor(directory, {})
            self.assertEqual(len(snapshots), 2)
            self.assertTrue(all(not root.exists() for root in snapshots))

    def test_distinct_logical_aliases_are_exact_and_never_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'source'
            path = source / 'outputs/run.log'; path.parent.mkdir(parents=True); path.write_bytes(b'local alias fixture\n')
            (source / 'tools').mkdir(); (source / 'tools/script.py').write_text('print(1)\n')
            package = root / 'package'; delivery._copy_source(source, package / 'source/bridge-skills')
            values = [{'path': name, 'sha256': evidence.digest(path)} for name in ('outputs/run.log', str(path))]
            delivery._copy_bound_evidence(values, source, package / 'evidence/bound-files')
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=self.manifest(package))
            self.assertEqual(set(resolver.path_map), {'outputs/run.log', str(path)})
            physical = [resolver.resolve(name, expected_sha256=evidence.digest(path)) for name in resolver.path_map]
            self.assertEqual(len(set(physical)), 2)
            self.assertEqual([item.read_bytes() for item in physical], [path.read_bytes()] * 2)


    def static_alias_fixture(self, root, spellings, *, include_symlink=False):
        root = root.resolve(); source = root / 'original-static-source'
        for name, data in [('tests/check.py', 'assert True\nprint("verified")\n'),
                           ('packages/entry.py', 'def inspect_basis(): return True\n'),
                           ('docs/input.txt', 'static input\n'), ('outputs/release.bin', 'release')]:
            path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(data)
        script = source / 'tests/check.py'
        aliases = [str(script), str(source) + '/tests/./check.py']
        if include_symlink:
            symlink = root / 'historical-script-alias.py'
            _require_symlink(symlink, script)
            aliases.append(str(symlink))
        build = evidence.build_id(source)
        card = {'schema': 'bridge.readiness.live_card/1', 'state': 'PENDING_EXECUTION',
                'build_id': build, 'case_id': 'static-alias-case', 'content_version': 'static-v1',
                'resource_id': 'static-resource', 'confirmations': {}}
        for field in ('case_id', 'content_version', 'resource_id'):
            card['confirmations'][field] = {'value': card[field], 'confirmed': False, 'step': 'Confirm ' + field}
        card_path = source / 'outputs/card.json'; card_path.write_text(json.dumps(card))
        rows = []; raw_receipts = {}
        for index, spelling in enumerate(spellings):
            argv = [sys.executable, '-B', '--', aliases[index % len(aliases)]]
            observed = subprocess.run(argv, cwd=source, capture_output=True, text=True)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            checksum = evidence.digest(script)
            receipt = {'schema': 'bridge.readiness.static_check/1', 'build_id': build,
                'case_id': card['case_id'], 'stage': 'static-audit', 'status': 'PASS',
                'script': {'path': spelling, 'sha256': checksum},
                'inputs': [{'path': 'docs/./input.txt', 'sha256': evidence.digest(source / 'docs/input.txt')}],
                'execution': {'argv': argv, 'returncode': observed.returncode, 'script_sha256': checksum,
                    'stdout': observed.stdout, 'stderr': observed.stderr,
                    'stdout_sha256': hashlib.sha256(observed.stdout.encode()).hexdigest(),
                    'stderr_sha256': hashlib.sha256(observed.stderr.encode()).hexdigest(),
                    'started_at': '2026-10-03T00:00:00Z', 'finished_at': '2026-10-03T00:00:01Z'},
                'assertions': [{'assertion_ref': 'tests/./check.py:1', 'outcome': 'PASS'}]}
            receipt['receipt_sha256'] = evidence._canonical_sha256(receipt)
            name = 'outputs/static-check-' + str(index) + '.json'
            path = source / name; path.write_text(json.dumps(receipt)); raw_receipts[name] = path.read_bytes()
            entry = {'path': 'packages/entry.py', 'sha256': evidence.digest(source / 'packages/entry.py')}
            rows.append({'id': 'P3-NATIVE-VERSIONS', 'build_id': build, 'evidence_ref': 'static-row-' + str(index),
                'content_version': card['content_version'], 'resource_id': card['resource_id'],
                'production_entry': dict(entry, symbol='inspect_basis'), 'implementation': [entry],
                'release_files': [{'path': 'outputs/release.bin', 'sha256': evidence.digest(source / 'outputs/release.bin')}],
                'live_card': {'path': 'outputs/card.json', 'sha256': evidence.digest(card_path), 'schema': card['schema']},
                'execution_binding': {'case_ids': [card['case_id']], 'stages': ['static-audit'], 'operation_ids': []},
                'evidence_bindings': [{'kind': 'positive', 'evidence_type': 'static_check',
                    'assertion_refs': ['tests/./check.py:1'], 'receipt': {'path': name, 'sha256': evidence.digest(path)}}]})
            self.assertEqual(evidence.inspect_row_execution_artifacts(rows[-1], source, build)['errors'], [])
        package = root / 'static-package'
        delivery._copy_source(source, package / 'source/bridge-skills')
        delivery._copy_bound_evidence(rows, source, package / 'evidence/bound-files')
        return source, package, self.manifest(package), rows, aliases, raw_receipts

    def test_static_absolute_argv_aliases_share_authenticated_source_after_relocation(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            source, package, anchor, rows, aliases, raw_receipts = self.static_alias_fixture(
                Path(tmp), ['tests/check.py'] * 3)
            mapping = json.loads((package / 'evidence/bound-files/path-map.json').read_text())
            self.assertEqual({mapping[name]['package_relative_path'] for name in aliases},
                             {'source/bridge-skills/tests/check.py'})
            # Each logical alias retains its own historical producer time.
            mapping[aliases[1]]['modified_ns'] += 1
            delivery._write_json(package / 'evidence/bound-files/path-map.json', mapping)
            anchor = self.manifest(package)
            shutil.rmtree(source)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            self.assertFalse(source.exists())
            for row in rows:
                self.assertEqual(evidence.inspect_row_execution_artifacts(row, resolver.source_root,
                                 row['build_id'], resolver=resolver)['errors'], [])
            for name, raw in raw_receipts.items():
                actual = resolver.resolve(name, expected_sha256=hashlib.sha256(raw).hexdigest())
                self.assertEqual(actual.read_bytes(), raw)
            for name in aliases:
                entry = mapping[name]
                self.assertEqual(resolver.resolve(name, expected_sha256=entry['sha256'], expected_bytes=entry['bytes'],
                    producer_modified_ns=entry['modified_ns']), resolver.source_root / 'tests/check.py')
                with self.assertRaises(ValueError):
                    resolver.resolve(name, expected_sha256=entry['sha256'], producer_modified_ns=entry['modified_ns'] + 1)
            with self.assertRaises(ValueError):
                resolver.resolve(str(source) + '/tests//check.py', expected_sha256=mapping[aliases[0]]['sha256'])
            for row in rows:
                receipt = json.loads(raw_receipts[row['evidence_bindings'][0]['receipt']['path']])
                self.assertFalse(evidence._static_argv_executes_script(receipt['execution']['argv'], resolver.source_root,
                    'tests/check.py', resolver=resolver, script_sha256='0' * 64))

    def test_static_symbolic_argv_aliases_remain_authenticated_after_relocation(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            source, package, anchor, rows, aliases, raw_receipts = self.static_alias_fixture(
                Path(tmp), ['tests/check.py'] * 3, include_symlink=True)
            mapping = json.loads((package / 'evidence/bound-files/path-map.json').read_text())
            self.assertEqual({mapping[name]['package_relative_path'] for name in aliases},
                             {'source/bridge-skills/tests/check.py'})
            shutil.rmtree(source)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            for row in rows:
                self.assertEqual(evidence.inspect_row_execution_artifacts(row, resolver.source_root,
                                 row['build_id'], resolver=resolver)['errors'], [])
            for name, raw in raw_receipts.items():
                self.assertEqual(resolver.resolve(name, expected_sha256=hashlib.sha256(raw).hexdigest()).read_bytes(), raw)

    def test_source_relative_spellings_normalize_without_weakening_package_paths(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            original, canonical, anchor, _, _, _, _ = self.fixture(Path(tmp) / 'source-reader')
            canonical_resolver = evidence.PackageEvidenceResolver(canonical, manifest_sha256=anchor)
            self.assertEqual(canonical_resolver.source_file('tools/./static.py'),
                             canonical_resolver.source_root / 'tools/static.py')
            source, package, anchor, rows, _, _ = self.static_alias_fixture(
                Path(tmp), ['tests/./check.py', 'tests//check.py', './tests///./check.py'])
            shutil.rmtree(source)
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=anchor)
            for row in rows:
                self.assertEqual(evidence.inspect_row_execution_artifacts(row, resolver.source_root,
                                 row['build_id'], resolver=resolver)['errors'], [])
            checksum = evidence.digest(resolver.source_root / 'tests/check.py')
            for spelling in ('tests/./check.py', 'tests//check.py', './tests///./check.py'):
                self.assertEqual(evidence._safe_relative_path(spelling).as_posix(), 'tests/check.py')
                self.assertEqual(resolver.source_file(spelling, expected_sha256=checksum),
                                 resolver.source_root / 'tests/check.py')
            for spelling in ('tests/../tests/check.py', '../tests/check.py', '/tests/check.py',
                             'tests/..//tests/check.py', 'tests\\check.py', 'C:/tests/check.py'):
                with self.subTest(spelling=spelling), self.assertRaises(ValueError):
                    resolver.source_file(spelling, expected_sha256=checksum)
                self.assertIsNone(evidence._safe_relative_path(spelling))
            with self.assertRaises(ValueError): resolver.source_file('tests/./check.py', expected_sha256='0' * 64)
            with self.assertRaises(ValueError): resolver.file(source, 'tests/check.py', expected_sha256=checksum)
            for spelling in ('source/bridge-skills/tests/./check.py', 'source//bridge-skills/tests/check.py'):
                with self.assertRaises(ValueError): resolver._relative(spelling)
            path = resolver.source_root / 'tests/check.py'; data = path.read_bytes(); path.write_bytes(b'changed')
            with self.assertRaises(ValueError): resolver.source_file('tests//check.py', expected_sha256=checksum)
            with self.subTest(attack='symbolic-link'):
                path.write_bytes(data); path.unlink(); _require_symlink(path, resolver.source_root / 'packages/entry.py')
                with self.assertRaises(ValueError): resolver.source_file('tests/./check.py', expected_sha256=checksum)
