import ctypes
from contextlib import nullcontext
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from dcc_task_runtime import platform_support


class PrivatePermissionValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='permissions synthetic ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'synthetic.key'
        self.path.write_text('synthetic unit-only value ' * 4, encoding='utf-8')

    @unittest.skipUnless(os.name == 'nt', 'Windows native DACL')
    def test_shared_approval_private_windows_file_is_accepted(self):
        from dcc_task_runtime import windows_process
        from vfx_pipeline.paths import load_approval_secret
        self.path.chmod(0o600)
        windows_process.set_private_permissions(self.path)
        before = private_dacl_sddl(self.path)
        self.assertTrue(self.path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
        with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(self.path)}, clear=True):
            self.assertTrue(len(load_approval_secret()) >= 32)
        self.assertEqual(private_dacl_sddl(self.path), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows native DACL addon parity')
    def test_houdini_addon_uses_same_private_file_identity_check(self):
        import importlib.util
        addon_path = Path(__file__).resolve().parents[2] / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        module_spec = importlib.util.spec_from_file_location('private_permissions_addon_test', addon_path)
        addon = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(addon)
        platform_support.set_private_permissions(self.path)
        with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(self.path)}, clear=True):
            self.assertEqual(addon._approval_secret_value(), self.path.read_text(encoding='utf-8').strip())
            with patch.object(platform_support, 'private_permissions_valid', return_value=False) as rejected:
                with self.assertRaisesRegex(addon.BridgeCommandError, 'private current-user'):
                    addon._approval_secret_value()
                self.assertIsInstance(rejected.call_args.kwargs['file_descriptor'], int)
        self.set_synthetic_dacl('D:P(A;;FA;;;SY)')
        try:
            with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(self.path)}, clear=True):
                with self.assertRaises(addon.BridgeCommandError):
                    addon._approval_secret_value()
        finally:
            from dcc_task_runtime import windows_process
            windows_process.set_private_permissions(self.path)

    def set_synthetic_dacl(self, sddl, *, protected=True):
        from ctypes import wintypes
        from dcc_task_runtime import windows_process
        descriptor = ctypes.c_void_p()
        windows_process._check(windows_process.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None))
        try:
            if protected:
                windows_process._check(windows_process.advapi32.SetFileSecurityW(
                    str(self.path), 4 | 0x80000000, descriptor))
            else:
                windows_process._bind(windows_process.advapi32, 'SetNamedSecurityInfoW', wintypes.DWORD,
                                      [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
                present, acl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
                windows_process._check(windows_process.advapi32.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)))
                error = windows_process.advapi32.SetNamedSecurityInfoW(
                    str(self.path), 1, 4 | 0x20000000, None, None, acl, None)
                if error:
                    raise ctypes.WinError(error)
        finally:
            windows_process.kernel32.LocalFree(descriptor)

    @unittest.skipUnless(os.name == 'nt', 'Windows native DACL')
    def test_native_protected_user_only_and_user_system_are_valid_without_acl_changes(self):
        from dcc_task_runtime import windows_process
        user = windows_process._current_user_sid()
        for label, sddl in [('user_only', 'D:P(A;;FR;;;' + user + ')'),
                            ('user_system', 'D:P(A;;FA;;;SY)(A;;FA;;;' + user + ')')]:
            with self.subTest(case=label):
                self.set_synthetic_dacl(sddl)
                before = private_dacl_sddl(self.path)
                with patch.object(windows_process.advapi32, 'SetFileSecurityW', side_effect=AssertionError('read mutated ACL')):
                    self.assertTrue(windows_process.private_permissions_valid(self.path))
                    self.assertTrue(platform_support.private_permissions_valid(self.path))
                    with self.path.open('rb') as stream:
                        self.assertTrue(platform_support.private_permissions_valid(self.path, file_descriptor=stream.fileno()))
                self.assertEqual(private_dacl_sddl(self.path), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows native DACL')
    def test_native_other_sid_empty_null_unprotected_and_deny_acls_are_rejected_read_only(self):
        from dcc_task_runtime import windows_process
        from dcc_task_runtime.errors import PolicyDenied
        from vfx_pipeline.paths import load_approval_secret
        user = windows_process._current_user_sid()
        user_ace = '(A;;FA;;;' + user + ')'
        cases = [('world_read', 'D:P' + user_ace + '(A;;FR;;;WD)', True),
                 ('admin_read', 'D:P' + user_ace + '(A;;GR;;;BA)', True),
                 ('foreign_write', 'D:P' + user_ace + '(A;;FW;;;WD)', True),
                 ('empty', 'D:P', True), ('null', 'D:NO_ACCESS_CONTROL', True),
                 ('unprotected', 'D:' + user_ace, False),
                 ('system_only', 'D:P(A;;FA;;;SY)', True),
                 ('inherit_only', 'D:P(A;IO;FA;;;' + user + ')', True),
                 ('deny', 'D:P(D;;FR;;;WD)' + user_ace, True)]
        for label, sddl, protected in cases:
            with self.subTest(case=label):
                self.set_synthetic_dacl(sddl, protected=protected)
                before = private_dacl_sddl(self.path)
                with patch.object(windows_process.advapi32, 'SetFileSecurityW', side_effect=AssertionError('read repaired ACL')):
                    self.assertFalse(windows_process.private_permissions_valid(self.path))
                    self.assertFalse(platform_support.private_permissions_valid(self.path))
                    with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(self.path)}, clear=True):
                        with self.assertRaises(PolicyDenied):
                            load_approval_secret()
                self.assertEqual(private_dacl_sddl(self.path), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows native security descriptors')
    def test_foreign_owner_and_unknown_ace_type_are_not_private_evidence(self):
        from dcc_task_runtime import windows_process
        user = windows_process._current_user_sid()
        for label, owner in [('system_owner', 'SY'), ('world_owner', 'WD')]:
            with self.subTest(case=label):
                descriptor = ctypes.c_void_p()
                windows_process._check(windows_process.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    'O:' + owner + 'D:P(A;;FA;;;' + user + ')', 1, ctypes.byref(descriptor), None))
                try:
                    self.assertFalse(windows_process._private_security_descriptor_valid(descriptor, user))
                finally:
                    windows_process.kernel32.LocalFree(descriptor)
        descriptor = ctypes.c_void_p()
        windows_process._check(windows_process.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            'O:' + user + 'D:P(A;;FA;;;' + user + ')', 1, ctypes.byref(descriptor), None))
        try:
            actual_get_ace = windows_process.advapi32.GetAce

            def unknown_ace(acl, index, output):
                result = actual_get_ace(acl, index, output)
                ace = ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents
                ctypes.cast(ace, ctypes.POINTER(windows_process.ACE_HEADER)).contents.kind = 9
                return result

            with patch.object(windows_process.advapi32, 'GetAce', side_effect=unknown_ace):
                self.assertFalse(windows_process._private_security_descriptor_valid(descriptor, user))
        finally:
            windows_process.kernel32.LocalFree(descriptor)

    @unittest.skipUnless(os.name == 'nt', 'Windows native API boundary')
    def test_native_api_errors_and_missing_observations_fail_closed(self):
        from dcc_task_runtime import windows_process
        windows_process.set_private_permissions(self.path)
        before = private_dacl_sddl(self.path)
        cases = [(windows_process.kernel32, 'CreateFileW', ctypes.c_void_p(-1).value),
                 (windows_process.kernel32, 'GetFileInformationByHandle', 0),
                 (windows_process.advapi32, 'GetSecurityInfo', 5)]
        cases += [(windows_process.advapi32, name, 0) for name in (
            'IsValidSecurityDescriptor', 'GetSecurityDescriptorControl', 'GetSecurityDescriptorOwner',
            'GetSecurityDescriptorDacl', 'IsValidAcl', 'GetAclInformation', 'GetAce', 'IsValidSid',
            'ConvertSidToStringSidW', 'OpenProcessToken', 'GetTokenInformation')]
        cases += [(windows_process, '_current_user_sid', None),
                  (windows_process.advapi32, 'GetSecurityInfo', 0),
                  (windows_process.advapi32, 'GetSecurityDescriptorDacl', 1)]
        for library, name, result in cases:
            with self.subTest(api=name, result_missing=result in (None, 0, 1)):
                with patch.object(library, name, return_value=result):
                    self.assertFalse(platform_support.private_permissions_valid(self.path))
        with patch.object(windows_process, '_current_user_sid', side_effect=OSError('synthetic missing token')):
            self.assertFalse(platform_support.private_permissions_valid(self.path))
        self.assertEqual(private_dacl_sddl(self.path), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows native handles')
    def test_open_file_descriptor_must_match_validated_file(self):
        from dcc_task_runtime import windows_process
        windows_process.set_private_permissions(self.path)
        other = self.root / 'other synthetic file'
        other.write_bytes(b'unit-only unrelated bytes')
        windows_process.set_private_permissions(other)
        with other.open('rb') as stream:
            self.assertFalse(platform_support.private_permissions_valid(self.path, file_descriptor=stream.fileno()))
        self.assertFalse(platform_support.private_permissions_valid(self.path, file_descriptor=-1))

    def test_missing_directory_and_hardlink_files_are_rejected_before_read(self):
        from dcc_task_runtime.errors import PolicyDenied
        from vfx_pipeline.paths import load_approval_secret
        platform_support.set_private_permissions(self.path)
        alias = self.root / 'hardlink'
        os.link(self.path, alias)
        for candidate in (self.root / 'missing', self.root, self.path, alias):
            with self.subTest(case=candidate.name):
                self.assertFalse(platform_support.private_permissions_valid(candidate))
                with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(candidate)}, clear=True):
                    with patch.object(Path, 'open', side_effect=AssertionError('invalid file content opened')):
                        with self.assertRaises(PolicyDenied):
                            load_approval_secret()

    @unittest.skipUnless(os.name == 'nt', 'Windows reparse boundary')
    def test_reparse_file_and_parent_api_observations_are_rejected(self):
        from dcc_task_runtime import windows_process
        windows_process.set_private_permissions(self.path)
        original_lstat = Path.lstat
        for candidate_to_replace in (self.path, self.root):
            def reparse_observation(candidate, *arguments, **keywords):
                information = original_lstat(candidate, *arguments, **keywords)
                if candidate == candidate_to_replace:
                    return SimpleNamespace(st_mode=information.st_mode, st_nlink=information.st_nlink,
                                           st_file_attributes=0x400)
                return information

            with self.subTest(case=candidate_to_replace.name), patch.object(Path, 'lstat', reparse_observation):
                self.assertFalse(windows_process.private_permissions_valid(self.path))
                self.assertFalse(platform_support.private_permissions_valid(self.path))

    def test_symlink_files_and_parent_links_are_rejected(self):
        platform_support.set_private_permissions(self.path)
        link = self.root / 'symlink'
        parent_link = self.root / 'parent-link'
        try:
            os.symlink(self.path, link)
            os.symlink(self.root, parent_link, target_is_directory=True)
        except OSError as failure:
            self.skipTest('NOT_RUN: synthetic symlink creation unavailable, errno=' + str(failure.errno))
        self.assertFalse(platform_support.private_permissions_valid(link))
        self.assertFalse(platform_support.private_permissions_valid(parent_link / self.path.name))

    @unittest.skipUnless(os.name == 'nt', 'Windows native junction')
    def test_native_junction_parent_is_rejected(self):
        from ctypes import wintypes
        from dcc_task_runtime import windows_process
        target = self.root / 'junction target'
        target.mkdir()
        path = target / 'synthetic file'
        path.write_bytes(b'unit-only synthetic bytes')
        platform_support.set_private_permissions(path)
        self.assertTrue(platform_support.private_permissions_valid(path))
        junction = self.root / 'junction'
        junction.mkdir()
        self.addCleanup(junction.rmdir)
        substitute = ('\\??\\' + str(target)).encode('utf-16-le')
        printable = str(target).encode('utf-16-le')
        names = substitute + b'\0\0' + printable + b'\0\0'
        data = struct.pack('<LHHHHHH', 0xA0000003, 8 + len(names), 0,
                           0, len(substitute), len(substitute) + 2, len(printable)) + names
        windows_process._bind(windows_process.kernel32, 'DeviceIoControl', wintypes.BOOL,
                              [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p])
        handle = windows_process.kernel32.CreateFileW(str(junction), 0x40000000, 0, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            buffer = ctypes.create_string_buffer(data)
            returned = wintypes.DWORD()
            windows_process._check(windows_process.kernel32.DeviceIoControl(
                handle, 0x900A4, buffer, len(data), None, 0, ctypes.byref(returned), None))
        finally:
            windows_process.kernel32.CloseHandle(handle)
        self.assertTrue(junction.lstat().st_file_attributes & 0x400)
        self.assertFalse(windows_process.private_permissions_valid(junction / path.name))
        self.assertFalse(platform_support.private_permissions_valid(junction / path.name))

    def test_posix_owner_mode_regular_file_and_link_semantics(self):
        information = dict(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=42)
        with patch.object(platform_support.os, 'getuid', return_value=42, create=True):
            for mode in (0o600, 0o400):
                self.assertTrue(platform_support._private_posix_stat_valid(SimpleNamespace(**{**information, 'st_mode': stat.S_IFREG | mode})))
            for replacement in ({'st_uid': 43}, {'st_mode': stat.S_IFREG | 0o644},
                                {'st_mode': stat.S_IFREG | 0o660}, {'st_mode': stat.S_IFDIR | 0o700},
                                {'st_mode': stat.S_IFLNK | 0o600}, {'st_nlink': 2}):
                with self.subTest(fields=sorted(replacement)):
                    self.assertFalse(platform_support._private_posix_stat_valid(SimpleNamespace(**{**information, **replacement})))

    def test_posix_open_descriptor_identity_and_unknown_owner_fail_closed(self):
        information = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=42, st_dev=1, st_ino=7)
        with patch.object(platform_support, '_plain_path', return_value=self.path), \
                patch.object(platform_support.os, 'name', 'posix'), \
                patch.object(platform_support.os, 'getuid', return_value=42, create=True), \
                patch.object(Path, 'lstat', return_value=information):
            self.assertTrue(platform_support.private_permissions_valid(self.path))
            with patch.object(platform_support.os, 'fstat', return_value=information):
                self.assertTrue(platform_support.private_permissions_valid(self.path, file_descriptor=11))
            changed = SimpleNamespace(**{**vars(information), 'st_ino': 8})
            with patch.object(platform_support.os, 'fstat', return_value=changed):
                self.assertFalse(platform_support.private_permissions_valid(self.path, file_descriptor=11))
            with patch.object(platform_support.os, 'fstat', side_effect=OSError('synthetic missing descriptor')):
                self.assertFalse(platform_support.private_permissions_valid(self.path, file_descriptor=11))
            with patch.object(platform_support.os, 'getuid', side_effect=AttributeError('synthetic missing uid')):
                self.assertFalse(platform_support.private_permissions_valid(self.path))

    def test_direct_override_does_not_read_files_and_short_override_remains_denied(self):
        from dcc_task_runtime.errors import PolicyDenied
        from vfx_pipeline.paths import load_approval_secret
        with patch.object(Path, 'open', side_effect=AssertionError('direct override read a file')):
            with patch.dict(os.environ, {'HOUDINI_BRIDGE_APPROVAL_SECRET': 'synthetic override only ' * 4}, clear=True):
                self.assertTrue(len(load_approval_secret()) >= 32)
            with patch.dict(os.environ, {'HOUDINI_BRIDGE_APPROVAL_SECRET': 'short synthetic'}, clear=True):
                with self.assertRaises(PolicyDenied):
                    load_approval_secret()

    @unittest.skipUnless(os.name == 'nt', 'Windows native DACL')
    def test_loader_validates_same_open_file_and_rejects_short_values(self):
        from vfx_pipeline import paths
        from dcc_task_runtime.errors import PolicyDenied
        platform_support.set_private_permissions(self.path)
        actual_validate = platform_support.private_permissions_valid
        observed = []

        def validate_open_file(path, *, file_descriptor=None):
            observed.append(file_descriptor is not None and stat.S_ISREG(os.fstat(file_descriptor).st_mode))
            return actual_validate(path, file_descriptor=file_descriptor)

        with patch.dict(os.environ, {'BRIDGE_SKILLS_APPROVAL_SECRET_FILE': str(self.path)}, clear=True):
            with patch.object(paths, 'private_permissions_valid', side_effect=validate_open_file):
                self.assertTrue(len(paths.load_approval_secret()) >= 32)
            self.assertEqual(observed, [True])
            self.path.write_text('short synthetic', encoding='utf-8')
            with self.assertRaises(PolicyDenied):
                paths.load_approval_secret()


def private_dacl_sddl(path):
    from ctypes import wintypes
    from dcc_task_runtime import windows_process
    library = windows_process.advapi32
    windows_process._bind(library, 'GetFileSecurityW', wintypes.BOOL,
                          [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)])
    windows_process._bind(library, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', wintypes.BOOL,
                          [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                           ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p])
    size = wintypes.DWORD()
    library.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(size))
    descriptor = ctypes.create_string_buffer(size.value)
    windows_process._check(library.GetFileSecurityW(str(path), 4, descriptor, size, ctypes.byref(size)))
    result = wintypes.LPWSTR()
    windows_process._check(library.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        descriptor, 1, 4, ctypes.byref(result), None))
    try:
        return result.value
    finally:
        windows_process.kernel32.LocalFree(ctypes.cast(result, ctypes.c_void_p))


class PlatformSupportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='Bridge 中文 space ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def spawn(self, source, *arguments):
        executable = getattr(sys, '_base_executable', sys.executable)
        source_root = str(Path(platform_support.__file__).resolve().parent.parent)
        environment = {**os.environ, 'PYTHONPATH': source_root + os.pathsep + os.environ.get('PYTHONPATH', '')}
        process = subprocess.Popen([executable, '-c', source, *map(str, arguments)], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def wait_for(self, path, process):
        deadline = time.monotonic() + 5
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        if not path.exists():
            self.fail('child did not signal readiness: ' + repr(process.communicate(timeout=5)))

    def test_process_identity_is_read_only_and_requires_exact_birth(self):
        process = self.spawn('import time; time.sleep(30)')
        query_guard = (patch.object(platform_support.os, 'kill', side_effect=AssertionError('Windows query signaled'))
                       if os.name == 'nt' else nullcontext())
        with query_guard:
            identity = platform_support.process_identity(process.pid)
            self.assertEqual(identity['state'], 'alive')
            self.assertIsInstance(identity['birth'], str)
            for attempt in range(10):
                self.assertEqual(platform_support.process_status(identity), 'alive')
                self.assertTrue(platform_support.pid_alive(process.pid))
            self.assertIsNone(process.poll())
        observed = {**identity, 'birth': 'different-creation'}
        with patch.object(platform_support, 'process_identity', return_value=observed):
            self.assertEqual(platform_support.process_status(identity), 'unknown')
        process.terminate()
        process.wait(5)
        self.assertEqual(platform_support.process_status(identity), 'stopped')

    def test_unknown_queries_retain_slots_and_invalid_identity_is_unknown(self):
        for identity in ({}, None, {'pid': os.getpid(), 'platform': 'other', 'birth': '1'},
                         {'pid': os.getpid(), 'platform': 'windows' if os.name == 'nt' else 'posix', 'birth': None}):
            with self.subTest(identity=identity):
                self.assertEqual(platform_support.process_status(identity), 'unknown')
        with patch.object(platform_support, 'process_identity', return_value={'state': 'unknown'}):
            self.assertTrue(platform_support.pid_alive(os.getpid()))

    @unittest.skipUnless(os.name == 'nt', 'Windows handle permissions')
    def test_access_denied_is_unknown_without_signaling(self):
        from dcc_task_runtime import windows_process
        with patch.object(windows_process.kernel32, 'OpenProcess', return_value=0), \
                patch.object(windows_process.ctypes, 'get_last_error', return_value=5), \
                patch.object(platform_support.os, 'kill', side_effect=AssertionError('unexpected signal')):
            self.assertEqual(platform_support.process_identity(os.getpid())['state'], 'unknown')
            self.assertTrue(platform_support.pid_alive(os.getpid()))

    def test_lock_preserves_empty_file_and_cursor(self):
        path = self.root / 'empty.lock'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        second = os.open(path, os.O_RDWR)
        try:
            os.lseek(descriptor, 7, os.SEEK_SET)
            platform_support.lock_file(descriptor, blocking=False)
            self.assertEqual(os.lseek(descriptor, 0, os.SEEK_CUR), 7)
            self.assertEqual(path.stat().st_size, 0)
            with self.assertRaises(OSError):
                platform_support.lock_file(second, blocking=False)
            platform_support.unlock_file(descriptor)
            self.assertEqual(os.lseek(descriptor, 0, os.SEEK_CUR), 7)
            platform_support.lock_file(second, blocking=False)
            platform_support.unlock_file(second)
        finally:
            os.close(second)
            os.close(descriptor)

    def test_cross_process_lock_is_released_by_crash(self):
        path = self.root / 'task.lock'
        ready = self.root / 'holder-ready'
        source = ('import os,sys,time; from pathlib import Path; '
                  'from dcc_task_runtime.platform_support import lock_file; '
                  'descriptor=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600); '
                  'lock_file(descriptor); Path(sys.argv[2]).touch(); time.sleep(30)')
        holder = self.spawn(source, path, ready)
        self.wait_for(ready, holder)
        descriptor = os.open(path, os.O_RDWR)
        try:
            with self.assertRaises(OSError):
                platform_support.lock_file(descriptor, blocking=False)
            holder.kill()
            holder.wait(5)
            platform_support.lock_file(descriptor, blocking=False)
            platform_support.unlock_file(descriptor)
        finally:
            os.close(descriptor)

    def test_blocking_lock_waits_for_release(self):
        path = self.root / 'task.lock'
        acquired = self.root / 'waiter-acquired'
        attempting = self.root / 'waiter-attempting'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            platform_support.lock_file(descriptor)
            source = ('import os,sys; from pathlib import Path; '
                      'from dcc_task_runtime.platform_support import lock_file,unlock_file; '
                      'descriptor=os.open(sys.argv[1],os.O_RDWR); Path(sys.argv[2]).touch(); '
                      'lock_file(descriptor); Path(sys.argv[3]).touch(); unlock_file(descriptor)')
            waiter = self.spawn(source, path, attempting, acquired)
            self.wait_for(attempting, waiter)
            self.assertFalse(acquired.exists())
            platform_support.unlock_file(descriptor)
            self.assertEqual(waiter.wait(5), 0)
            self.assertTrue(acquired.exists())
        finally:
            os.close(descriptor)

    def test_private_files_and_scoped_readonly_replacement_cleanup(self):
        root = platform_support.ensure_private_directory(self.root / 'owned')
        target = root / '中文 result.json'
        platform_support.atomic_write(target, b'first', owned_root=root)
        target.chmod(stat.S_IREAD)
        platform_support.atomic_write(target, b'second', owned_root=root)
        self.assertEqual(target.read_bytes(), b'second')
        target.chmod(stat.S_IREAD)
        platform_support.remove_owned_path(target, owned_root=root)
        self.assertFalse(target.exists())
        outside = self.root / 'outside'
        outside.write_bytes(b'unchanged')
        outside.chmod(stat.S_IREAD)
        try:
            with self.assertRaisesRegex(ValueError, 'OUTSIDE_ROOT'):
                platform_support.remove_owned_path(outside, owned_root=root)
            with self.assertRaisesRegex(ValueError, 'OUTSIDE_ROOT'):
                platform_support.atomic_write(outside, b'changed', owned_root=root)
            self.assertEqual(outside.read_bytes(), b'unchanged')
            self.assertFalse(outside.stat().st_mode & stat.S_IWRITE)
        finally:
            outside.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_private_files_reject_hardlinks(self):
        outside = self.root / 'foreign'
        outside.write_bytes(b'foreign')
        root = platform_support.ensure_private_directory(self.root / 'owned')
        target = root / 'linked'
        os.link(outside, target)
        with self.assertRaisesRegex(ValueError, 'HARDLINK'):
            platform_support.remove_owned_path(target, owned_root=root)
        with self.assertRaisesRegex(ValueError, 'PRIVATE_PATH_INVALID'):
            platform_support.open_private_file(target, os.O_WRONLY)
        self.assertEqual(outside.read_bytes(), b'foreign')

    def test_owned_tree_cleanup_handles_readonly_files(self):
        root = platform_support.ensure_private_directory(self.root / 'owned')
        nested = platform_support.ensure_private_directory(root / 'nested')
        child = nested / 'read-only'
        platform_support.atomic_write(child, b'owned', owned_root=root)
        child.chmod(stat.S_IREAD)
        if os.name == 'nt':
            nested.chmod(stat.S_IREAD | stat.S_IEXEC)
        platform_support.remove_owned_path(nested, owned_root=root)
        self.assertFalse(nested.exists())
        self.assertTrue(root.is_dir())

    def delete_blocking_reader(self, path):
        from ctypes import wintypes
        from dcc_task_runtime import windows_process
        windows_process._bind(windows_process.kernel32, 'CreateFileW', wintypes.HANDLE,
                              [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE])
        handle = windows_process.kernel32.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_atomic_replace_retries_real_reader_then_preserves_readonly_policy(self):
        from dcc_task_runtime import windows_process
        root = platform_support.ensure_private_directory(self.root / 'owned')
        target = root / 'shared.json'
        platform_support.atomic_write(target, b'original', owned_root=root)
        target.chmod(stat.S_IREAD)
        handle = self.delete_blocking_reader(target)
        failed_replace = threading.Event()
        release_requested = threading.Event()
        released_after_failure = threading.Event()
        actual_replace = os.replace

        def release_after_failed_attempt():
            release_requested.wait()
            if windows_process.kernel32.CloseHandle(handle) and failed_replace.is_set():
                released_after_failure.set()

        def observed_replace(source, destination):
            try:
                return actual_replace(source, destination)
            except OSError:
                failed_replace.set()
                release_requested.set()
                raise

        reader = threading.Thread(target=release_after_failed_attempt)
        reader.start()
        try:
            with patch.object(platform_support.os, 'replace', side_effect=observed_replace):
                platform_support.atomic_write(target, b'replacement', owned_root=root)
        finally:
            release_requested.set()
            reader.join(3)
        self.assertFalse(reader.is_alive())
        self.assertTrue(failed_replace.is_set())
        self.assertTrue(released_after_failure.is_set())
        self.assertEqual(target.read_bytes(), b'replacement')
        self.assertEqual(list(root.glob('*.tmp-*')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_controller_binding_replaces_real_locked_readonly_file(self):
        import json
        from dcc_task_runtime import windows_process
        from vfx_pipeline.workbuddy_assembly import _persist_boundary_binding
        root = platform_support.ensure_private_directory(self.root / 'controller')
        target = root / 'configured-houdini-binding.json'
        _persist_boundary_binding(target, {'task_id': 'synthetic-task', 'rebind_count': 1})
        target.chmod(stat.S_IREAD)
        handle = self.delete_blocking_reader(target)
        failed_replace = threading.Event()
        release_requested = threading.Event()
        released_after_failure = threading.Event()
        actual_replace = os.replace

        def observed_replace(source, destination):
            try:
                return actual_replace(source, destination)
            except OSError:
                failed_replace.set()
                release_requested.set()
                raise

        def release_reader():
            release_requested.wait()
            if windows_process.kernel32.CloseHandle(handle) and failed_replace.is_set():
                released_after_failure.set()

        reader = threading.Thread(target=release_reader)
        reader.start()
        try:
            with patch.object(platform_support.os, 'replace', side_effect=observed_replace):
                _persist_boundary_binding(target, {'task_id': 'synthetic-task', 'rebind_count': 2})
        finally:
            release_requested.set()
            reader.join(3)
        self.assertFalse(reader.is_alive())
        self.assertTrue(failed_replace.is_set())
        self.assertTrue(released_after_failure.is_set())
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')),
                         {'task_id': 'synthetic-task', 'rebind_count': 2})
        self.assertEqual(list(root.glob('*.tmp-*')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_fx_state_manifest_replaces_real_locked_readonly_file(self):
        import importlib.util
        import json
        from dcc_task_runtime import windows_process
        addon_path = Path(__file__).resolve().parents[2] / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        specification = importlib.util.spec_from_file_location('fx_state_addon_test', addon_path)
        addon = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(addon)
        original = {'task_id': 'synthetic-task', 'revision': 1, 'label': '中文'}
        updated = {**original, 'revision': 2}
        with patch.dict(os.environ, {'HOUDINI_BRIDGE_STATE_DIR': str(self.root / 'FX 中文 state')}):
            addon._fx_write_state(original['task_id'], original)
            target = addon._fx_state_path(original['task_id'])
            target.chmod(stat.S_IREAD)
            handle = self.delete_blocking_reader(target)
            failed_replace = threading.Event()
            release_requested = threading.Event()
            released_after_failure = threading.Event()
            actual_replace = os.replace

            def observed_replace(source, destination):
                try:
                    return actual_replace(source, destination)
                except OSError:
                    failed_replace.set()
                    release_requested.set()
                    raise

            def release_reader():
                release_requested.wait()
                if windows_process.kernel32.CloseHandle(handle) and failed_replace.is_set():
                    released_after_failure.set()

            reader = threading.Thread(target=release_reader)
            reader.start()
            try:
                with patch.object(platform_support.os, 'replace', side_effect=observed_replace):
                    addon._fx_write_state(original['task_id'], updated)
            finally:
                release_requested.set()
                reader.join(3)
            self.assertFalse(reader.is_alive())
            self.assertTrue(failed_replace.is_set())
            self.assertTrue(released_after_failure.is_set())
            expected = (json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
            self.assertEqual(target.read_bytes(), expected)
            self.assertTrue(platform_support.private_permissions_valid(target))
            self.assertEqual(list(target.parent.glob('*.tmp*')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_fx_state_manifest_permanent_lock_preserves_original_and_raises(self):
        import importlib.util
        from dcc_task_runtime import windows_process
        addon_path = Path(__file__).resolve().parents[2] / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        specification = importlib.util.spec_from_file_location('fx_state_failure_addon_test', addon_path)
        addon = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(addon)
        original = {'task_id': 'synthetic-task', 'revision': 1}
        with patch.dict(os.environ, {'HOUDINI_BRIDGE_STATE_DIR': str(self.root / 'FX 中文 state')}):
            addon._fx_write_state(original['task_id'], original)
            target = addon._fx_state_path(original['task_id'])
            before = target.read_bytes()
            target.chmod(stat.S_IREAD)
            handle = self.delete_blocking_reader(target)
            started = time.monotonic()
            try:
                with self.assertRaises(OSError):
                    addon._fx_write_state(original['task_id'], {**original, 'revision': 2})
            finally:
                windows_process.kernel32.CloseHandle(handle)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(target.stat().st_mode & stat.S_IWRITE)
            self.assertEqual(list(target.parent.glob('*.tmp*')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_permanently_blocked_replace_is_bounded_and_keeps_original_bytes(self):
        from dcc_task_runtime import windows_process
        root = platform_support.ensure_private_directory(self.root / 'owned')
        target = root / 'shared.json'
        platform_support.atomic_write(target, b'original', owned_root=root)
        target.chmod(stat.S_IREAD)
        handle = self.delete_blocking_reader(target)
        started = time.monotonic()
        try:
            with self.assertRaises(OSError) as failure:
                platform_support.atomic_write(target, b'replacement', owned_root=root)
            self.assertIn(failure.exception.winerror, (5, 32, 33))
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(target.stat().st_mode & stat.S_IWRITE)
            self.assertEqual(list(root.glob('*.tmp-*')), [])
        finally:
            windows_process.kernel32.CloseHandle(handle)

    @unittest.skipUnless(os.name == 'nt', 'Windows DACL')
    def test_private_dacl_contains_only_current_user_and_system(self):
        from dcc_task_runtime import windows_process
        root = platform_support.ensure_private_directory(self.root / 'private')
        path = root / 'secret'
        platform_support.atomic_write(path, b'secret', owned_root=root)
        for candidate in (root, path):
            with self.subTest(candidate=candidate):
                sddl = private_dacl_sddl(candidate)
                self.assertTrue(sddl.startswith('D:P'))
                self.assertEqual(sddl.count('(A;'), 2)
                self.assertIn(';;;SY)', sddl)
                self.assertIn(';;;' + windows_process._current_user_sid() + ')', sddl)
