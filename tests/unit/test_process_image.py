"""Tests replace only OS/tool/file boundaries; no commercial runtime is loaded."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dcc_task_runtime import process_image as image


class ProcessImageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='process image 中文 ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'explicit executable'
        self.path.write_bytes(b'explicit test executable bytes')
        self.path.chmod(0o700)
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.platform = patch.object(image.sys, 'platform', 'darwin')
        self.platform.start(); self.addCleanup(self.platform.stop)
        self.expected = image.freeze_executable(str(self.path), 'unit-only-v1', self.digest)
        self.current = os.getpid()
        self.host = 700
        self.processes = {self.current: (self.host, '2026-10-16 10:00:01.123 +0000'),
                          self.host: (1, '2026-10-16 10:00:00.123 +0000')}

    def tools(self, argv, deadline):
        """Native tools boundary with a real independently opened/hashable file."""
        self.assertGreater(deadline, time.monotonic())
        pid = int(argv[1] if argv[0] == '/usr/bin/sample' else
                  argv[3] if argv[0].endswith('vmmap') else argv[argv.index('-p') + 1])
        parent, birth = self.processes[pid]
        if argv[0] == '/bin/ps':
            when = image._birth(birth)
            return f'{pid} {parent} {when.strftime("%a %b %d %H:%M:%S %Y")} S\n'.encode()
        if argv[0] == '/usr/bin/sample':
            self.assertEqual(argv, ['/usr/bin/sample', str(pid), '1', '1000', '-file', '/dev/stdout'])
            return (f'Process: anything [{pid}]\nParent Process: arbitrary [{parent}]\n'
                    f'Load Address: 0x100000000\nLaunch Time: {birth}\nTarget Type: live task\n'
                    'Path: /untrusted/*/display-name\n').encode()
        if argv[0] == '/usr/bin/vmmap':
            self.assertEqual(argv[:4], ['/usr/bin/vmmap', '-w', '-interleaved', str(pid)])
            self.assertEqual(len(argv), 5, 'vmmap must address the independently observed main load, not scan all VM')
            address = int(argv[4], 16)
            return (f'--->  __TEXT {address:x}-{address + 0x4000:x} '
                    f'[ 16K 0K 0K 0K] r-x/r-x SM=COW {self.path}\n').encode()
        self.assertEqual(argv[0], '/usr/sbin/lsof')
        information = self.path.stat()
        return (f'p{pid}\0R{parent}\0\nftxt\0tREG\0D{hex(information.st_dev)}\0'
                f'i{information.st_ino}\0n{self.path}\0\n'
                'ftxt\0tREG\0D0x1\0i999\0n/usr/lib/dyld\0\n').encode()

    def boundary(self, change=None):
        def call(argv, deadline):
            data = self.tools(argv, deadline)
            return change(argv, data) if change else data
        return patch.object(image, '_run_tool', side_effect=call)

    def anchor(self):
        with self.boundary():
            return image.observe_process(self.host)

    def proof(self):
        anchor = self.anchor()
        with self.boundary():
            proof = image.capture_ancestry(self.expected, anchor)
        return proof, anchor

    def test_freeze_explicit_hash_version_and_json_format(self):
        self.assertEqual(self.expected['image']['sha256'], self.digest)
        self.assertEqual(self.expected['image']['stat']['inode'], self.path.stat().st_ino)
        self.assertEqual(json.loads(json.dumps(self.expected)), self.expected)
        self.assertEqual(self.expected['version'], 'unit-only-v1')
        for digest in (None, '', self.digest.upper(), '0' * 64):
            with self.subTest(digest=digest), self.assertRaises(image.ProcessImageError):
                image.freeze_executable(self.path, 'unit', digest)
        for version in (None, '', ' unit', 'line\nbreak'):
            with self.subTest(version=version), self.assertRaises(image.ProcessImageError):
                image.freeze_executable(self.path, version, self.digest)

    def test_no_links_at_leaf_or_parent_and_no_hardlinks(self):
        link = self.root / 'link'
        link.symlink_to(self.path)
        parent = self.root / 'parent-link'
        parent.symlink_to(self.root, target_is_directory=True)
        for path in (link, parent / self.path.name):
            with self.subTest(path=path), self.assertRaisesRegex(image.ProcessImageError, 'FILE_UNAVAILABLE'):
                image.freeze_executable(path, 'unit', self.digest)
        hardlink = self.root / 'hardlink'
        os.link(self.path, hardlink)
        with self.assertRaisesRegex(image.ProcessImageError, 'INVALID_FILE_IDENTITY'):
            image.freeze_executable(self.path, 'unit', self.digest)

    def test_missing_nonregular_nonexecutable_oversize_and_nonabsolute_refused(self):
        for path in ('relative', str(self.root / 'missing'), str(self.root), str(self.root / '..' / 'x')):
            with self.subTest(path=path), self.assertRaises(image.ProcessImageError):
                image.freeze_executable(path, 'unit', self.digest)
        self.path.chmod(0o600)
        with self.assertRaisesRegex(image.ProcessImageError, 'INVALID_FILE_IDENTITY'):
            image.freeze_executable(self.path, 'unit', self.digest)
        self.path.chmod(0o700)
        with self.path.open('r+b') as stream:
            stream.truncate(image.MAX_IMAGE_BYTES + 1)
        with self.assertRaisesRegex(image.ProcessImageError, 'INVALID_FILE_IDENTITY'), \
                patch.object(image.os, 'read', side_effect=AssertionError('oversize must not be hashed')):
            image.freeze_executable(self.path, 'unit', self.digest)

    def test_freeze_rechecks_open_fd_and_path_after_hash(self):
        read = image.os.read
        changed = False
        def mutate(descriptor, count):
            nonlocal changed
            data = read(descriptor, count)
            if not changed:
                changed = True
                replacement = self.root / 'replacement'
                replacement.write_bytes(self.path.read_bytes())
                replacement.chmod(0o700)
                replacement.replace(self.path)
            return data
        with patch.object(image.os, 'read', side_effect=mutate), \
                self.assertRaisesRegex(image.ProcessImageError, 'FILE_CHANGED'):
            image.freeze_executable(self.path, 'unit', self.digest)

    def test_freeze_cooperative_total_deadline(self):
        with patch.object(image, 'FREEZE_TIMEOUT_SECONDS', 0), \
                self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT'):
            image.freeze_executable(self.path, 'unit', self.digest)

    def test_observation_uses_main_load_address_and_vnode_not_display_name(self):
        with self.boundary():
            observed = image.observe_process(self.current)
        self.assertEqual(observed['image'], self.expected['image'])
        self.assertEqual(observed['parent_pid'], self.host)
        self.assertEqual(observed['birth'], self.processes[self.current][1])
        self.assertEqual(observed['load_address'], '0x100000000')

    def test_runtime_ready_gate_follows_first_ps_and_spends_original_observe_deadline(self):
        for outcome in ('ready', 'error', 'timeout'):
            with self.subTest(outcome=outcome):
                clock = [time.monotonic()]
                deadline = clock[0] + image.OBSERVE_TIMEOUT_SECONDS
                tools = []
                def tool(argv, end):
                    tools.append(argv[0])
                    self.assertLessEqual(end, deadline)
                    return self.tools(argv, end)
                def ready(end):
                    self.assertEqual(tools, ['/bin/ps'])
                    self.assertEqual(end, deadline)
                    if outcome == 'error': raise ValueError('runtime-ready rejected')
                    if outcome == 'timeout': clock[0] = end
                with patch.object(image.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(image, '_run_tool', side_effect=tool):
                    if outcome == 'ready':
                        observed = image._observe(self.host, deadline, before_image=ready)
                        self.assertEqual(observed['pid'], self.host)
                        self.assertEqual(tools, ['/bin/ps', '/usr/bin/sample', '/usr/bin/vmmap',
                            '/usr/sbin/lsof', '/usr/sbin/lsof', '/usr/bin/sample', '/usr/bin/vmmap', '/bin/ps'])
                    else:
                        with self.assertRaisesRegex(ValueError, 'runtime-ready rejected' if outcome == 'error' else 'TIMEOUT'):
                            image._observe(self.host, deadline, before_image=ready)
                        self.assertEqual(tools, ['/bin/ps'])

    def test_header_and_targeted_region_are_independent_and_both_reobserved(self):
        calls = []
        def call(argv, deadline):
            calls.append(argv)
            return self.tools(argv, deadline)
        with patch.object(image, '_run_tool', side_effect=call):
            image.observe_process(self.current)
        self.assertEqual([argv for argv in calls if argv[0] == '/usr/bin/sample'],
                         [['/usr/bin/sample', str(self.current), '1', '1000', '-file', '/dev/stdout']] * 2)
        self.assertEqual([argv for argv in calls if argv[0].endswith('vmmap') and '-summary' not in argv],
                         [['/usr/bin/vmmap', '-w', '-interleaved', str(self.current),
                           '0x100000000']] * 2)

    def test_automatic_corpse_snapshot_is_bracketed_by_live_observations(self):
        with self.boundary(lambda argv, data: data.replace(b'Target Type: live task', b'Target Type: corpse')):
            self.assertEqual(image.observe_process(self.current)['pid'], self.current)
        with self.boundary(lambda argv, data: data.replace(b' S\n', b' Z\n')), \
                self.assertRaisesRegex(image.ProcessImageError, 'INVALID_PS'):
            image.observe_process(self.current)

    def test_vmmap_missing_duplicate_fields_and_main_regions_refused(self):
        changes = [('header', lambda data: data.replace(b'Load Address:', b'Unrecognized:')),
                   ('header', lambda data: data + b'Load Address: 0x100000000\n'),
                   ('region', lambda data: data.replace(b'100000000-100004000', b'200000000-200004000')),
                   ('region', lambda data: data + b'__TEXT' + data.split(b'__TEXT', 1)[1]),
                   ('region', lambda data: data.replace(b'__TEXT', b'__DATA_CONST')),
                   ('header', lambda data: data.replace(b'Target Type: live task', b'Target Type: unknown'))]
        for tool, change in changes:
            with self.subTest(tool=tool, change=change), self.boundary(
                    lambda argv, data: change(data) if (tool == 'header' and argv[0] == '/usr/bin/sample'
                        or tool == 'region' and argv[0].endswith('vmmap') and '-summary' not in argv) else data), \
                    self.assertRaises(image.ProcessImageError):
                image.observe_process(self.current)

    def test_lsof_duplicate_vnodes_pid_parent_and_device_inode_mismatch_refused(self):
        changes = [lambda data: data + data.split(b'\n')[1] + b'\n',
                   lambda data: data.replace(f'p{self.current}\0'.encode(), b'p999\0'),
                   lambda data: data.replace(f'R{self.host}\0'.encode(), b'R999\0'),
                   lambda data: data.replace(f'i{self.path.stat().st_ino}\0'.encode(), b'i555\0'),
                   lambda data: data.replace(f'D{hex(self.path.stat().st_dev)}\0'.encode(), b'D0x99\0'),
                   lambda data: data.replace(b'\0\n', b'\n', 1)]
        for change in changes:
            with self.subTest(change=change), self.boundary(
                    lambda argv, data: change(data) if argv[0].endswith('lsof') else data), \
                    self.assertRaises(image.ProcessImageError):
                image.observe_process(self.current)

    def test_birth_or_main_mapping_change_during_one_observation_refused(self):
        for replacement in (b'Load Address: 0x200000000', b'Launch Time: 2026-10-16 10:00:02.123 +0000'):
            count = 0
            def change(argv, data):
                nonlocal count
                if argv[0] == '/usr/bin/sample':
                    count += 1
                    if count == 2:
                        if replacement.startswith(b'Load'):
                            return data.replace(b'0x100000000', b'0x200000000').replace(
                                b'100000000-100004000', b'200000000-200004000')
                        return data.replace(b'Launch Time: 2026-10-16 10:00:01.123 +0000', replacement)
                return data
            with self.subTest(replacement=replacement), self.boundary(change), \
                    self.assertRaisesRegex(image.ProcessImageError, 'PROCESS_CHANGED'):
                image.observe_process(self.current)

    def test_full_capture_offline_recheck_and_no_verified_input(self):
        proof, anchor = self.proof()
        with patch.object(image, '_run_tool', side_effect=AssertionError('offline validation ran a tool')):
            self.assertIsNone(image.validate_process_proof(proof, self.expected, anchor))
        self.assertEqual(proof['chain'], proof['rechecked_chain'])
        self.assertEqual([entry['pid'] for entry in proof['chain']], [self.current, self.host])
        self.assertEqual(json.loads(json.dumps(proof)), proof)
        proof['verified'] = True
        with self.assertRaisesRegex(image.ProcessImageError, 'INVALID_STRUCTURE'):
            image.validate_process_proof(proof, self.expected, anchor)

    def test_missing_expected_and_noncurrent_pid_and_self_anchor_refused_before_tools(self):
        anchor = self.anchor()
        with patch.object(image, '_run_tool', side_effect=AssertionError('invalid input ran a tool')):
            for expected in (None, {}, {'verified': True}):
                with self.subTest(expected=expected), self.assertRaises(image.ProcessImageError):
                    image.capture_ancestry(expected, anchor)
            with self.assertRaisesRegex(image.ProcessImageError, 'CURRENT_PROCESS_REQUIRED'):
                image.capture_ancestry(self.expected, anchor, self.host)
            with self.assertRaisesRegex(image.ProcessImageError, 'STRICT_ANCESTOR_REQUIRED'):
                image.capture_ancestry(self.expected, {**anchor, 'pid': self.current})

    def test_wrong_expected_hash_or_version_and_wrong_anchor_rejected(self):
        proof, anchor = self.proof()
        expected = copy.deepcopy(self.expected)
        expected['image']['sha256'] = 'a' * 64
        with self.boundary(), self.assertRaisesRegex(image.ProcessImageError, 'EXECUTABLE_MISMATCH'):
            image.capture_ancestry(expected, anchor)
        expected = {**self.expected, 'version': 'another-explicit-build'}
        with self.assertRaisesRegex(image.ProcessImageError, 'TRUSTED_BINDING_MISMATCH'):
            image.validate_process_proof(proof, expected, anchor)
        wrong = {**anchor, 'birth': '2026-10-16 09:00:00.123 +0000'}
        with self.boundary(), self.assertRaisesRegex(image.ProcessImageError, 'HOST_ANCHOR_MISMATCH'):
            image.capture_ancestry(self.expected, wrong)

    def test_nonancestor_cycle_depth_and_total_deadline_fail_closed(self):
        anchor = self.anchor()
        self.processes[self.host] = (0, self.processes[self.host][1])
        anchor = {**anchor, 'pid': 999}
        with self.boundary(), self.assertRaisesRegex(image.ProcessImageError, 'HOST_NOT_ANCESTOR'):
            image.capture_ancestry(self.expected, anchor)
        self.processes[self.host] = (self.current, self.processes[self.host][1])
        with self.boundary(), self.assertRaisesRegex(image.ProcessImageError, 'ANCESTRY_CYCLE'):
            image.capture_ancestry(self.expected, anchor)
        with patch.object(image, 'MAX_ANCESTRY_DEPTH', 1), self.boundary(), \
                self.assertRaisesRegex(image.ProcessImageError, 'ANCESTRY_DEPTH_LIMIT'):
            image.capture_ancestry(self.expected, anchor)
        with patch.object(image, 'CAPTURE_TIMEOUT_SECONDS', 0), \
                self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT'):
            image.capture_ancestry(self.expected, anchor)

    def test_reverse_chain_reobservation_rejects_birth_drift(self):
        anchor = self.anchor()
        calls = 0
        def change(argv, data):
            nonlocal calls
            if argv[0] == '/usr/bin/sample' and argv[1] == str(self.current):
                calls += 1
                if calls >= 3:
                    return data.replace(b'10:00:01.123', b'10:00:01.456')
            return data
        with self.boundary(change), self.assertRaisesRegex(image.ProcessImageError, 'PROCESS_CHANGED'):
            image.capture_ancestry(self.expected, anchor)

    def test_offline_strict_types_trust_binding_chain_edges_and_birth_order(self):
        proof, anchor = self.proof()
        def boolean_pid(value):
            value['chain'][0]['pid'] = True
            value['rechecked_chain'][0]['pid'] = True
        def edge(value):
            value['chain'][0]['parent_pid'] = 999
            value['rechecked_chain'][0]['parent_pid'] = 999
        def birth(value):
            value['chain'][0]['birth'] = '2026-10-16 09:00:00.123 +0000'
            value['rechecked_chain'][0]['birth'] = value['chain'][0]['birth']
        def recheck(value):
            value['rechecked_chain'][0]['load_address'] = '0x200000000'
        def unknown(value):
            value['chain'][0]['image']['verified'] = True
        for mutate in (boolean_pid, edge, birth, recheck, unknown):
            altered = copy.deepcopy(proof); mutate(altered)
            with self.subTest(mutate=mutate), self.assertRaises(image.ProcessImageError):
                image.validate_process_proof(altered, self.expected, anchor)

    def test_offline_all_objects_require_exact_keys_and_numeric_fields_reject_bools(self):
        proof, anchor = self.proof()
        paths = [(), ('expected_executable',), ('expected_executable', 'image'),
                 ('expected_executable', 'image', 'stat'), ('host_anchor',),
                 ('host_anchor', 'image'), ('host_anchor', 'image', 'stat')]
        for list_name in ('chain', 'rechecked_chain'):
            for index in range(len(proof[list_name])):
                base = (list_name, index)
                paths.extend([base, base + ('image',), base + ('image', 'stat')])
        def at(value, path):
            for key in path:
                value = value[key]
            return value
        for path in paths:
            for operation in ('missing', 'extra'):
                altered = copy.deepcopy(proof)
                target = at(altered, path)
                if operation == 'missing':
                    target.pop(next(iter(target)))
                else:
                    target['verified'] = True
                with self.subTest(path=path, operation=operation), self.assertRaises(image.ProcessImageError):
                    image.validate_process_proof(altered, self.expected, anchor)
            for key, value in at(proof, path).items():
                if type(value) is int:
                    altered = copy.deepcopy(proof)
                    at(altered, path)[key] = True
                    with self.subTest(path=path, bool_field=key), self.assertRaises(image.ProcessImageError):
                        image.validate_process_proof(altered, self.expected, anchor)
        malformed = copy.deepcopy(proof)
        malformed['expected_executable']['image']['path'] = self.path
        with self.assertRaisesRegex(image.ProcessImageError, 'INVALID_PATH'):
            image.validate_process_proof(malformed, self.expected, anchor)
        with self.assertRaises(image.ProcessImageError):
            image.validate_process_proof(proof, None, anchor)

    def test_single_observation_total_includes_hashing_and_rechecks(self):
        original_hash = image._hash
        def expired_hash(descriptor, size, deadline, read_budget=None):
            # Simulate the hashing boundary exhausting the caller's shared deadline.
            return original_hash(descriptor, size, time.monotonic() - 1, read_budget)
        with self.boundary(), patch.object(image, '_hash', side_effect=expired_hash), \
                self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT'):
            image.observe_process(self.current)
        with patch.object(image, 'OBSERVE_TIMEOUT_SECONDS', 0), \
                self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT'):
            image.observe_process(self.current)

    def test_hash_budget_reserves_each_maximum_read_including_eof_before_io(self):
        content = b'x' * (1024 * 1024 + 7)
        self.path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        events = []
        class Budget:
            def reserve(self, count):
                events.append(('reserve', count))
        read = image.os.read
        def observed_read(descriptor, count):
            events.append(('read', count))
            self.assertEqual(events[-2], ('reserve', count))
            return read(descriptor, count)
        with patch.object(image.os, 'read', side_effect=observed_read):
            image.freeze_executable(self.path, 'budget-test', digest, read_budget=Budget())
        self.assertEqual(events, [('reserve', 1024 * 1024), ('read', 1024 * 1024),
                                  ('reserve', 8), ('read', 8), ('reserve', 1), ('read', 1)])

    def test_hash_budget_rejection_propagates_before_read_and_no_refund(self):
        class BudgetRejected(RuntimeError):
            pass
        class Budget:
            def __init__(self):
                self.charges = []
            def reserve(self, count):
                self.charges.append(count)
                raise BudgetRejected('persistent budget exhausted')
        budget = Budget()
        with patch.object(image.os, 'read', side_effect=AssertionError('budget rejected before IO')), \
                self.assertRaises(BudgetRejected):
            image.freeze_executable(self.path, 'unit', self.digest, read_budget=budget)
        self.assertEqual(budget.charges, [self.path.stat().st_size + 1])

    def test_observe_and_both_capture_passes_share_the_supplied_aggregate_budget(self):
        class Budget:
            def __init__(self):
                self.charges = []
                self.limit = None
            def reserve(self, count):
                if self.limit is not None and sum(self.charges) + count > self.limit:
                    raise RuntimeError('aggregate budget exhausted')
                self.charges.append(count)
        per_hash = [self.path.stat().st_size + 1, 1]
        budget = Budget()
        with self.boundary():
            image.observe_process(self.current, read_budget=budget)
        self.assertEqual(budget.charges, per_hash)
        anchor = self.anchor()
        budget = Budget()
        with self.boundary():
            image.capture_ancestry(self.expected, anchor, read_budget=budget)
        # Two nodes, each read once in the outward and once in the return pass.
        self.assertEqual(budget.charges, per_hash * 4)
        budget = Budget()
        budget.limit = sum(per_hash) * 2
        with self.boundary(), self.assertRaisesRegex(RuntimeError, 'aggregate budget exhausted'):
            image.capture_ancestry(self.expected, anchor, read_budget=budget)
        self.assertEqual(budget.charges, per_hash * 2)

    def test_budget_reservation_does_not_extend_image_hash_deadline(self):
        class Budget:
            def reserve(self, count):
                now[0] = 1000
        now = [0]
        with patch.object(image.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(image.os, 'read', side_effect=AssertionError('expired before read')), \
                self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT'):
            image.freeze_executable(self.path, 'unit', self.digest, read_budget=Budget())

    def test_unsupported_platform_and_invalid_pid(self):
        with patch.object(image.sys, 'platform', 'linux'):
            for call in (lambda: image.observe_process(self.current),
                         lambda: image.freeze_executable(self.path, 'unit', self.digest),
                         lambda: image.capture_ancestry(None, None),
                         lambda: image.validate_process_proof(None, None, None)):
                with self.assertRaisesRegex(image.ProcessImageError, 'UNSUPPORTED_PLATFORM'):
                    call()
        for pid in (True, None, 0, -1, '1', 2**32):
            with self.subTest(pid=pid), self.assertRaisesRegex(image.ProcessImageError, 'INVALID_PID'):
                image.observe_process(pid)

    def test_real_tool_boundary_deadline_nonzero_stderr_and_output_limits(self):
        executable = str(Path(sys.executable).resolve())
        cases = [('import sys,time;sys.stderr.buffer.write(b"before timeout");sys.stderr.flush();time.sleep(30)', 'TIMEOUT'),
                 ('import sys;sys.stderr.buffer.write(b"exit diagnostic");sys.exit(7)', 'TOOL_FAILED'),
                 ('import sys;sys.stderr.write("warning")', 'TOOL_FAILED'),
                 ('import sys;sys.stderr.buffer.write(bytes([255,0,254]))', 'TOOL_FAILED'),
                 ('import sys;sys.stdout.write("x"*65536)', 'TOOL_OUTPUT_LIMIT'),
                 ('import sys;sys.stderr.write("x"*65536)', 'TOOL_OUTPUT_LIMIT')]
        for source, reason in cases:
            argv = [executable, '-B', '-c', source]
            with self.subTest(source=source), patch.object(image, 'MAX_STDOUT_BYTES', 1024), \
                    patch.object(image, 'MAX_STDERR_BYTES', 1024):
                started = time.monotonic()
                with self.assertRaisesRegex(image.ProcessImageError, reason) as raised:
                    image._run_tool(argv, time.monotonic() + image.TOOL_TIMEOUT_SECONDS + 1)
                self.assertLess(time.monotonic() - started, image.TOOL_TIMEOUT_SECONDS + 2)
                diagnostic = raised.exception.diagnostic
                self.assertEqual(diagnostic['reason'], str(raised.exception))
                self.assertEqual(diagnostic['tool_argv'], argv)
                self.assertLessEqual(len(json.dumps(diagnostic)), 16000)
                if 'exit diagnostic' in source:
                    self.assertEqual(diagnostic['exit_code'], 7)
                    self.assertEqual(bytes.fromhex(diagnostic['stderr_hex']), b'exit diagnostic')
                    self.assertEqual(diagnostic['stderr_observed_bytes'], 15)
                    self.assertFalse(diagnostic['stderr_truncated'])
                    self.assertTrue(diagnostic['stderr_complete'])
                if '255,0,254' in source:
                    self.assertEqual(bytes.fromhex(diagnostic['stderr_hex']), bytes([255,0,254]))
                if 'before timeout' in source:
                    self.assertEqual(bytes.fromhex(diagnostic['stderr_hex']), b'before timeout')
                    self.assertFalse(diagnostic['stderr_complete'])
                if 'stderr.write("x"' in source:
                    self.assertEqual(diagnostic['stderr_observed_bytes'], 1025)
                    self.assertFalse(diagnostic['stderr_complete'])
        # Failure payloads have their own smaller bound even when the native
        # stream fits its collection cap. This does not accept the failed tool.
        source = 'import sys;sys.stderr.buffer.write(b"z"*6000);sys.exit(7)#' + 'x'*6000
        with self.assertRaisesRegex(image.ProcessImageError, 'TOOL_FAILED') as raised:
            image._run_tool([executable, '-B', '-c', source], time.monotonic()+image.TOOL_TIMEOUT_SECONDS+1)
        diagnostic = raised.exception.diagnostic
        self.assertEqual(diagnostic['stderr_observed_bytes'], 6000)
        self.assertTrue(diagnostic['stderr_truncated'])
        self.assertTrue(diagnostic['stderr_complete'])
        self.assertTrue(diagnostic['tool_argv_truncated'])
        self.assertEqual(len(bytes.fromhex(diagnostic['stderr_hex'])), 4096)
        self.assertLessEqual(len(json.dumps(diagnostic)), 16000)
        with self.assertRaisesRegex(image.ProcessImageError, 'TOOL_UNAVAILABLE') as raised:
            image._run_tool(['/nonexistent/process-image-tool'], time.monotonic() + 2)
        self.assertEqual(raised.exception.diagnostic['tool_argv'], ['/nonexistent/process-image-tool'])
        self.assertIsNone(raised.exception.diagnostic['exit_code'])
        self.assertEqual(raised.exception.diagnostic['stage'], 'spawn')

    def test_failure_diagnostic_preserves_tool_pid_deadline_source_and_final_cleanup(self):
        for tool_limit, outer_limit, expected_source in ((.08, 1., 'tool'), (1., .03, 'observation')):
            with self.subTest(source=expected_source), patch.object(image, 'TOOL_TIMEOUT_SECONDS', tool_limit):
                with self.assertRaisesRegex(image.ProcessImageError, 'TIMEOUT') as raised:
                    image._run_tool([sys.executable, '-B', '-c', 'import time;time.sleep(3)'],
                                    time.monotonic()+outer_limit)
                value=raised.exception.diagnostic
                self.assertIsInstance(value['tool_pid'], int)
                self.assertGreater(value['tool_pid'], 0)
                self.assertEqual(value['timing']['deadline_source'], expected_source)
                self.assertGreaterEqual(value['timing']['elapsed_seconds'], value['timing']['effective_budget_seconds'])
                self.assertGreaterEqual(value['timing']['phase_seconds'], 0)
                self.assertGreaterEqual(value['timing']['spawn_seconds'], 0)
                self.assertLessEqual(value['timing']['effective_budget_seconds'], min(tool_limit,outer_limit)+1e-6)
                self.assertTrue(value['cleanup']['leader_reaped'])
                self.assertEqual(value['cleanup']['errors'], [])
                self.assertIsInstance(value['cleanup']['leader_exit_code'], int)
                with self.assertRaises(ProcessLookupError):os.kill(value['tool_pid'], 0)

    def test_tool_cleanup_cannot_replace_failure_or_claim_unknown_leader_reaped(self):
        import errno
        spawn = subprocess.Popen
        kill_group = os.killpg
        for fault in ('no_signal', 'denied_signal', 'pipe_close', 'successful_tool_close'):
            children = []
            streams = []
            class RefusedClose:
                def __init__(self, stream):
                    self.stream = stream
                def fileno(self):
                    return self.stream.fileno()
                def close(self):
                    raise PermissionError(errno.EPERM, 'software close refused')
            def launch(*args, **kwargs):
                child = spawn(*args, **kwargs)
                children.append(child)
                streams.extend((child.stdout, child.stderr))
                if fault in ('pipe_close', 'successful_tool_close'):
                    child.stdout = RefusedClose(child.stdout)
                return child
            def signal_group(pid, signum):
                if fault == 'denied_signal':
                    raise PermissionError(errno.EPERM, 'software signal refused')
                if fault != 'no_signal':
                    return kill_group(pid, signum)
            source = ('import time;time.sleep(3)' if fault in ('no_signal','denied_signal')
                      else 'import sys;sys.exit(7)' if fault == 'pipe_close' else 'pass')
            reason = ('TIMEOUT' if fault in ('no_signal','denied_signal') else
                      'TOOL_FAILED' if fault == 'pipe_close' else 'TOOL_CLEANUP_FAILED')
            try:
                with self.subTest(fault=fault), patch.object(image.subprocess, 'Popen', side_effect=launch), \
                     patch.object(image.os, 'killpg', side_effect=signal_group), \
                     patch.object(image, 'TOOL_TIMEOUT_SECONDS', .05 if 'signal' in fault else 2):
                    with self.assertRaisesRegex(image.ProcessImageError, reason) as raised:
                        image._run_tool([sys.executable, '-B', '-c', source], time.monotonic()+3)
                    diagnostic = raised.exception.diagnostic
                    self.assertEqual(diagnostic['reason'], str(raised.exception))
                    cleanup = diagnostic['cleanup']
                    self.assertEqual(cleanup['leader_reaped'], fault in ('pipe_close','successful_tool_close'))
                    phases = [entry['phase'] for entry in cleanup['errors']]
                    self.assertIn('wait' if 'signal' in fault else 'stdout_close', phases)
                    if fault == 'denied_signal':
                        self.assertIn('kill_group', phases)
                    self.assertLess(len(json.dumps(diagnostic)), 16000)
            finally:
                for child in children:
                    if child.poll() is None:
                        kill_group(child.pid, image.signal.SIGKILL)
                        child.wait(timeout=3)
                for stream in streams:
                    stream.close()

    def test_summary_tool_requires_success_with_empty_stderr(self):
        argv = ['/usr/bin/vmmap', '-w', '-interleaved', '-summary', str(self.current)]
        old_progress = (f'Sampling process {self.current} for 1 second with 1000 milliseconds of run time between samples\n'
                        'Sampling completed, processing symbols...\n'
                        f'Sample analysis of process {self.current} written to file /dev/stdout\n')
        launch = subprocess.Popen
        for diagnostic, returncode in (('', 0), ('warning\n', 0), (old_progress, 0), ('', 7)):
            source = ('import sys;sys.stdout.write("header");'
                      f'sys.stderr.write({diagnostic!r});sys.exit({returncode})')
            def substitute(actual, **kwargs):
                self.assertEqual(actual, argv)
                return launch([sys.executable, '-B', '-c', source], **kwargs)
            with self.subTest(diagnostic=diagnostic, returncode=returncode), \
                    patch.object(image.subprocess, 'Popen', side_effect=substitute):
                if diagnostic or returncode:
                    with self.assertRaisesRegex(image.ProcessImageError, 'TOOL_FAILED'):
                        image._run_tool(argv, time.monotonic() + 2)
                else:
                    self.assertEqual(image._run_tool(argv, time.monotonic() + 2), b'header')


@unittest.skipUnless(sys.platform == 'darwin', 'macOS OS tools integration')
class ProcessImageMacOSTests(unittest.TestCase):
    def record(self, name, value):
        retained = os.environ.get('BRIDGE_PROCESS_IMAGE_EVIDENCE')
        if retained:
            directory = Path(retained)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

    def stop(self, process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_real_python_parent_child_proof_and_forged_argv_cannot_select_image(self):
        anchor = image.observe_process(os.getpid())
        expected = image.freeze_executable(anchor['image']['path'], 'ordinary-python-test',
                                           anchor['image']['sha256'])
        source = ('import json,sys; from dcc_task_runtime.process_image import capture_ancestry; '
                  'print(json.dumps(capture_ancestry(json.loads(sys.argv[1]),json.loads(sys.argv[2]))))')
        env = {**os.environ, 'PYTHONPATH': str(Path(image.__file__).resolve().parent.parent),
               'PYTHONDONTWRITEBYTECODE': '1'}
        # executable controls the launch in this test, never the production observer.
        child = subprocess.Popen(['FAKE_HUSK_ARGV0', '-B', '-c', source,
                                  json.dumps(expected), json.dumps(anchor)],
                                 executable=anchor['image']['path'], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, child)
        output, errors = child.communicate(timeout=image.CAPTURE_TIMEOUT_SECONDS + 5)
        self.assertEqual(child.returncode, 0, errors.decode(errors='replace'))
        proof = json.loads(output)
        self.assertEqual(proof['chain'][0]['pid'], child.pid)
        self.assertEqual(proof['chain'][0]['image'], expected['image'])
        self.assertEqual(proof['chain'][0]['parent_pid'], os.getpid())
        self.assertIsNone(image.validate_process_proof(proof, expected, anchor))
        # Offline validation remains possible after the captured child has exited.
        self.assertNotIn('FAKE_HUSK_ARGV0', json.dumps(proof))
        self.record('native-python-proof.json', {'expected': expected, 'anchor': anchor, 'proof': proof})

    def test_real_sleep_is_observed_and_rejected_as_python_expected_image(self):
        child = subprocess.Popen(['/bin/sleep', '30'])
        self.addCleanup(self.stop, child)
        observed = image.observe_process(child.pid)
        self.assertEqual(observed['image']['path'], '/bin/sleep')
        expected = image.freeze_executable('/bin/sleep', 'ordinary-sleep-test',
                                           observed['image']['sha256'])
        # This is intentionally a non-ancestor: expected-image mismatch must be
        # rejected at the current process, before attempting any ancestry walk.
        with self.assertRaisesRegex(image.ProcessImageError, 'EXECUTABLE_MISMATCH'):
            image.capture_ancestry(expected, observed)
        self.record('native-wrong-executable.json', {'expected': expected, 'observed': observed,
            'result': 'PROCESS_IMAGE_EXECUTABLE_MISMATCH'})


if __name__ == '__main__':
    unittest.main()
