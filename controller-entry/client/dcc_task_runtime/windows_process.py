"""Windows process handles and a Job assigned atomically by CreateProcessW."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time


class FILETIME(ctypes.Structure):
    _fields_ = [('low', wintypes.DWORD), ('high', wintypes.DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('descriptor', ctypes.c_void_p),
                ('inherit', wintypes.BOOL)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('sid', ctypes.c_void_p), ('attributes', wintypes.DWORD)]


class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [('attributes', wintypes.DWORD), ('created', FILETIME),
                ('accessed', FILETIME), ('written', FILETIME),
                ('volume_serial', wintypes.DWORD), ('size_high', wintypes.DWORD),
                ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]


class ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [('ace_count', wintypes.DWORD), ('bytes_in_use', wintypes.DWORD),
                ('bytes_free', wintypes.DWORD)]


class ACE_HEADER(ctypes.Structure):
    _fields_ = [('kind', wintypes.BYTE), ('flags', wintypes.BYTE), ('size', wintypes.WORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('reserved', wintypes.LPWSTR),
                ('desktop', wintypes.LPWSTR), ('title', wintypes.LPWSTR),
                ('x', wintypes.DWORD), ('y', wintypes.DWORD),
                ('xsize', wintypes.DWORD), ('ysize', wintypes.DWORD),
                ('xchars', wintypes.DWORD), ('ychars', wintypes.DWORD),
                ('fill', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('show', wintypes.WORD), ('reserved_size', wintypes.WORD),
                ('reserved_bytes', ctypes.POINTER(wintypes.BYTE)),
                ('stdin', wintypes.HANDLE), ('stdout', wintypes.HANDLE),
                ('stderr', wintypes.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [('startup', STARTUPINFOW), ('attributes', ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('process', wintypes.HANDLE), ('thread', wintypes.HANDLE),
                ('pid', wintypes.DWORD), ('tid', wintypes.DWORD)]


class JOB_BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                ('scheduling', wintypes.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        'read_operations', 'write_operations', 'other_operations',
        'read_bytes', 'write_bytes', 'other_bytes')]


class JOB_EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [('basic', JOB_BASIC_LIMIT), ('io', IO_COUNTERS),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


class JOB_ACCOUNTING(ctypes.Structure):
    _fields_ = [('user_time', ctypes.c_longlong), ('kernel_time', ctypes.c_longlong),
                ('period_user_time', ctypes.c_longlong), ('period_kernel_time', ctypes.c_longlong),
                ('page_faults', wintypes.DWORD), ('total_processes', wintypes.DWORD),
                ('active_processes', wintypes.DWORD), ('terminated_processes', wintypes.DWORD)]


def _bind(library, name, result, arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


if os.name == 'nt':
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    _bind(kernel32, 'GetCurrentProcess', wintypes.HANDLE, [])
    _bind(kernel32, 'CloseHandle', wintypes.BOOL, [wintypes.HANDLE])
    _bind(kernel32, 'LocalFree', ctypes.c_void_p, [ctypes.c_void_p])
    _bind(kernel32, 'OpenProcess', wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD])
    _bind(kernel32, 'WaitForSingleObject', wintypes.DWORD, [wintypes.HANDLE, wintypes.DWORD])
    _bind(kernel32, 'GetProcessTimes', wintypes.BOOL, [wintypes.HANDLE, *[ctypes.POINTER(FILETIME)] * 4])
    _bind(kernel32, 'GetExitCodeProcess', wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)])
    _bind(kernel32, 'CreateJobObjectW', wintypes.HANDLE, [ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.LPCWSTR])
    _bind(kernel32, 'SetInformationJobObject', wintypes.BOOL,
          [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD])
    _bind(kernel32, 'QueryInformationJobObject', wintypes.BOOL,
          [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p])
    _bind(kernel32, 'TerminateJobObject', wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT])
    _bind(kernel32, 'IsProcessInJob', wintypes.BOOL,
          [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)])
    _bind(kernel32, 'InitializeProcThreadAttributeList', wintypes.BOOL,
          [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)])
    _bind(kernel32, 'UpdateProcThreadAttribute', wintypes.BOOL,
          [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
           ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p])
    _bind(kernel32, 'DeleteProcThreadAttributeList', None, [ctypes.c_void_p])
    _bind(kernel32, 'DuplicateHandle', wintypes.BOOL,
          [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
           wintypes.DWORD, wintypes.BOOL, wintypes.DWORD])
    _bind(kernel32, 'CreateProcessW', wintypes.BOOL,
          [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
           wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
           ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)])
    _bind(advapi32, 'OpenProcessToken', wintypes.BOOL,
          [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)])
    _bind(advapi32, 'GetTokenInformation', wintypes.BOOL,
          [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)])
    _bind(advapi32, 'ConvertSidToStringSidW', wintypes.BOOL,
          [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)])
    _bind(advapi32, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', wintypes.BOOL,
          [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p])
    _bind(advapi32, 'SetFileSecurityW', wintypes.BOOL,
          [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p])
    _bind(kernel32, 'CreateFileW', wintypes.HANDLE,
          [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE])
    _bind(kernel32, 'GetFileInformationByHandle', wintypes.BOOL,
          [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)])
    _bind(advapi32, 'GetSecurityInfo', wintypes.DWORD,
          [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)])
    _bind(advapi32, 'IsValidSecurityDescriptor', wintypes.BOOL, [ctypes.c_void_p])
    _bind(advapi32, 'GetSecurityDescriptorControl', wintypes.BOOL,
          [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)])
    _bind(advapi32, 'GetSecurityDescriptorOwner', wintypes.BOOL,
          [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)])
    _bind(advapi32, 'GetSecurityDescriptorDacl', wintypes.BOOL,
          [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
           ctypes.POINTER(wintypes.BOOL)])
    _bind(advapi32, 'IsValidAcl', wintypes.BOOL, [ctypes.c_void_p])
    _bind(advapi32, 'GetAclInformation', wintypes.BOOL,
          [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int])
    _bind(advapi32, 'GetAce', wintypes.BOOL,
          [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)])
    _bind(advapi32, 'IsValidSid', wintypes.BOOL, [ctypes.c_void_p])


def _check(success):
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    return success


def _birth(handle):
    created, exited, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    _check(kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)))
    return str((created.high << 32) | created.low)


def query_process(pid):
    result = {'pid': pid, 'platform': 'windows', 'birth': None, 'state': 'unknown'}
    handle = kernel32.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            result['state'] = 'stopped'
        return result
    try:
        result['birth'] = _birth(handle)
        observed = kernel32.WaitForSingleObject(handle, 0)
        if observed in (0, 258):
            result['state'] = 'stopped' if observed == 0 else 'alive'
        return result
    except OSError:
        return result
    finally:
        kernel32.CloseHandle(handle)


def _current_user_sid():
    token = wintypes.HANDLE()
    _check(advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token)))
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        _check(advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
        user = ctypes.cast(buffer, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents
        sid = wintypes.LPWSTR()
        _check(advapi32.ConvertSidToStringSidW(user.sid, ctypes.byref(sid)))
        try:
            return sid.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _private_descriptor(directory=False):
    inheritance = 'OICI' if directory else ''
    sddl = 'D:P(A;{0};FA;;;SY)(A;{0};FA;;;{1})'.format(inheritance, _current_user_sid())
    descriptor = ctypes.c_void_p()
    _check(advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None))
    return descriptor


def set_private_permissions(path, *, directory=False):
    descriptor = _private_descriptor(directory)
    try:
        _check(advapi32.SetFileSecurityW(str(Path(path)), 0x4 | 0x80000000, descriptor))
    finally:
        kernel32.LocalFree(descriptor)


def _sid_string(sid):
    if not sid or not advapi32.IsValidSid(sid):
        raise ValueError('WINDOWS_PRIVATE_SID_INVALID')
    result = wintypes.LPWSTR()
    _check(advapi32.ConvertSidToStringSidW(sid, ctypes.byref(result)))
    try:
        if not result.value:
            raise ValueError('WINDOWS_PRIVATE_SID_MISSING')
        return result.value
    finally:
        kernel32.LocalFree(ctypes.cast(result, ctypes.c_void_p))


def _private_security_descriptor_valid(descriptor, current_user):
    if not descriptor or not current_user or not advapi32.IsValidSecurityDescriptor(descriptor):
        return False
    control, revision = wintypes.WORD(), wintypes.DWORD()
    _check(advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
    if control.value & 0x1004 != 0x1004:
        return False
    owner, defaulted = ctypes.c_void_p(), wintypes.BOOL()
    _check(advapi32.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
    if _sid_string(owner) != current_user:
        return False
    present, acl = wintypes.BOOL(), ctypes.c_void_p()
    _check(advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)))
    if not present.value or not acl.value or defaulted.value or not advapi32.IsValidAcl(acl):
        return False
    size = ACL_SIZE_INFORMATION()
    _check(advapi32.GetAclInformation(acl, ctypes.byref(size), ctypes.sizeof(size), 2))
    if not 0 < size.ace_count <= 4096 or not 8 <= size.bytes_in_use <= 65535:
        return False
    user_can_read = False
    for index in range(size.ace_count):
        ace = ctypes.c_void_p()
        _check(advapi32.GetAce(acl, index, ctypes.byref(ace)))
        if not ace.value or not acl.value + 8 <= ace.value <= acl.value + size.bytes_in_use - 16:
            return False
        header = ctypes.cast(ace, ctypes.POINTER(ACE_HEADER)).contents
        if header.kind != 0 or header.flags & ~0x3 or header.size < 16 or ace.value + header.size > acl.value + size.bytes_in_use:
            return False
        sid_address = ace.value + 8
        subauthorities = ctypes.c_ubyte.from_address(sid_address + 1).value
        if subauthorities > 15 or 8 + 4 * subauthorities > header.size - 8:
            return False
        sid = _sid_string(sid_address)
        if sid not in (current_user, 'S-1-5-18'):
            return False
        mask = wintypes.DWORD.from_address(ace.value + 4).value
        if sid == current_user and mask & 0x90000001:
            user_can_read = True
    return user_can_read


def _private_file_information(handle):
    information = BY_HANDLE_FILE_INFORMATION()
    _check(kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)))
    if information.attributes & (0x400 | 0x10) or information.links != 1:
        raise ValueError('WINDOWS_PRIVATE_FILE_INVALID')
    if not (information.index_high or information.index_low):
        raise ValueError('WINDOWS_PRIVATE_FILE_ID_MISSING')
    return information.volume_serial, information.index_high, information.index_low


def private_permissions_valid(path, *, file_descriptor=None):
    """Read only owner/DACL and file identity; unknown observations deny access."""
    if os.name != 'nt':
        return False
    handle = None
    descriptor = ctypes.c_void_p()
    try:
        path = Path(os.path.abspath(path))
        for candidate in (path, *path.parents):
            information = candidate.lstat()
            if stat.S_ISLNK(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
                return False
        information = path.lstat()
        if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1:
            return False
        handle = kernel32.CreateFileW(str(path), 0x20000, 1, None, 3, 0x00200000, None)
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            handle = None
            return False
        identity = _private_file_information(handle)
        if file_descriptor is not None:
            import msvcrt
            if _private_file_information(msvcrt.get_osfhandle(file_descriptor)) != identity:
                return False
        error = advapi32.GetSecurityInfo(handle, 1, 5, None, None, None, None, ctypes.byref(descriptor))
        if error:
            raise ctypes.WinError(error)
        return _private_security_descriptor_valid(descriptor, _current_user_sid())
    except (OSError, ValueError, TypeError, AttributeError, ctypes.ArgumentError):
        return False
    finally:
        if descriptor.value:
            kernel32.LocalFree(descriptor)
        if handle is not None:
            kernel32.CloseHandle(handle)


class WindowsJobProcess:
    """Own a child handle and its non-inherited kill-on-close Job handle."""

    def __init__(self, command, *, env=None, stdout, stderr):
        if os.name != 'nt':
            raise OSError('WINDOWS_PROCESS_UNAVAILABLE')
        if not command or any(not isinstance(item, str) or '\0' in item for item in command):
            raise ValueError('WINDOWS_COMMAND_INVALID')
        self._job = None
        self._process = None
        self.returncode = None
        self.job_name = 'BridgeOwnedJob-' + secrets.token_hex(24)
        self.job_facts = {'name': self.job_name, 'assigned_at_creation': True,
                          'kill_on_close': True, 'process_is_in_job': True}
        attributes = None
        attribute_initialized = False
        inherited = []
        information = PROCESS_INFORMATION()
        try:
            descriptor = _private_descriptor()
            try:
                security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
                ctypes.set_last_error(0)
                self._job = kernel32.CreateJobObjectW(ctypes.byref(security), self.job_name)
                error = ctypes.get_last_error()
                _check(self._job)
                if error == 183:
                    raise ValueError('WINDOWS_JOB_ALREADY_EXISTS')
            finally:
                kernel32.LocalFree(descriptor)
            limits = JOB_EXTENDED_LIMIT()
            limits.basic.flags = 0x2000
            _check(kernel32.SetInformationJobObject(self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            size = ctypes.c_size_t()
            kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if not size.value:
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = ctypes.create_string_buffer(size.value)
            _check(kernel32.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)))
            attribute_initialized = True
            job_list = (wintypes.HANDLE * 1)(self._job)
            _check(kernel32.UpdateProcThreadAttribute(attributes, 0, 0x2000d, job_list,
                                                     ctypes.sizeof(job_list), None, None))
            import msvcrt
            with open(os.devnull, 'rb') as input_stream:
                for stream in (input_stream, stdout, stderr):
                    duplicate = wintypes.HANDLE()
                    current = kernel32.GetCurrentProcess()
                    _check(kernel32.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()),
                                                     current, ctypes.byref(duplicate), 0, True, 2))
                    inherited.append(duplicate.value)
            handle_list = (wintypes.HANDLE * len(inherited))(*inherited)
            _check(kernel32.UpdateProcThreadAttribute(attributes, 0, 0x20002, handle_list,
                                                     ctypes.sizeof(handle_list), None, None))
            startup = STARTUPINFOEXW()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 0x100
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = inherited
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            environment = dict(os.environ if env is None else env)
            if any(not isinstance(name, str) or not name or '=' in name or '\0' in name
                   or not isinstance(value, str) or '\0' in value for name, value in environment.items()):
                raise ValueError('WINDOWS_ENV_INVALID')
            environment_block = ctypes.create_unicode_buffer('\0'.join(
                name + '=' + value for name, value in sorted(environment.items(), key=lambda item: item[0].upper())
            ) + '\0\0')
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            _check(kernel32.CreateProcessW(None, command_line, None, None, True,
                                           0x08000000 | 0x00080000 | 0x00000400,
                                           environment_block, None, ctypes.byref(startup), ctypes.byref(information)))
            self._process = information.process
            self.pid = information.pid
            self.birth = _birth(self._process)
            member = wintypes.BOOL()
            _check(kernel32.IsProcessInJob(self._process, self._job, ctypes.byref(member)))
            if not member.value:
                raise ValueError('WINDOWS_JOB_MEMBERSHIP_UNKNOWN')
        except BaseException:
            self.close()
            raise
        finally:
            if information.thread:
                kernel32.CloseHandle(information.thread)
            if attribute_initialized:
                kernel32.DeleteProcThreadAttributeList(attributes)
            for handle in inherited:
                kernel32.CloseHandle(handle)

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        result = kernel32.WaitForSingleObject(self._process, 0)
        if result == 258:
            return None
        if result != 0:
            raise OSError('WINDOWS_CHILD_WAIT_UNKNOWN')
        code = wintypes.DWORD()
        _check(kernel32.GetExitCodeProcess(self._process, ctypes.byref(code)))
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('owned Windows child', timeout)
            time.sleep(.01)
        return self.returncode

    def active_processes(self):
        information = JOB_ACCOUNTING()
        if not kernel32.QueryInformationJobObject(self._job, 1, ctypes.byref(information),
                                                   ctypes.sizeof(information), None):
            return None
        return information.active_processes

    def terminate(self):
        _check(kernel32.TerminateJobObject(self._job, 1))

    def kill(self):
        self.terminate()

    def close(self):
        if self._job:
            kernel32.CloseHandle(self._job)
            self._job = None
        if self._process:
            kernel32.CloseHandle(self._process)
            self._process = None
