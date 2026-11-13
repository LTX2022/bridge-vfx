"""Task-owned husk post-frame observations; never effective image-writer proof."""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile

from .render_observation_budget import FileReadBudget, json_usage

SCHEMA = 'bridge.houdini.husk-postframe-observation/1.0'
MAX_BYTES = 65536
MAX_VALUES = 4096
PRIVATE_READ_ALLOWANCE = 4*MAX_BYTES+32
MISSING_FACTS = (
    'PXL_EFFECTIVE_WRITER_OCIO_INSTANCE_UNOBSERVED',
    'WRITER_AOV_EFFECTIVE_COLOR_COVERAGE_UNOBSERVED',
    'WRITER_ORDERED_FILTER_EXECUTION_UNOBSERVED',
    'WRITER_BEAUTY_ALPHA_ASSOCIATION_UNOBSERVED',
    'WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED',
)


class WriterStopUnconfirmed(ValueError):
    code = 'RENDER_WRITER_STOP_UNCONFIRMED'


def _require_foreground(node, frame, hou_module):
    parm = node.parm('soho_foreground')
    referenced = parm.getReferencedParm() if parm is not None else None
    # Real HOM returns a fresh Python wrapper per call, so channel-reference
    # state is compared by parm path, never by object identity.
    driven_elsewhere = (referenced is not parm
                        and (not hasattr(referenced, 'path') or referenced.path() != parm.path()))
    if (parm is None or parm.parmTemplate().type() != hou_module.parmTemplateType.Toggle
            or parm.keyframes() or driven_elsewhere):
        raise ValueError('native synchronous render toggle is unavailable or driven')
    value = parm.evalAtFrame(frame)
    if type(value) not in (int, bool) or value != 1:
        raise ValueError('native soho_foreground must already be enabled')


def _canonical(value):
    json_usage(value, max_bytes=MAX_BYTES, max_values=MAX_VALUES)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _private_bytes(path, *, limit=MAX_BYTES):
    from dcc_task_runtime.platform_support import _plain_path, private_permissions_valid
    path = _plain_path(path)
    path.lstat()
    if not private_permissions_valid(path):
        raise ValueError('writer observation file is not private')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        before = os.fstat(fd)
        if not private_permissions_valid(path, file_descriptor=fd) or before.st_size > limit:
            raise ValueError('writer observation file exceeds its private read allowance')
        data = b''
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size-len(data)+1))
            if not chunk:
                break
            data += chunk
        signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (len(data) != before.st_size or signature(before) != signature(os.fstat(fd))
                or signature(before) != signature(path.stat())):
            raise ValueError('writer observation file changed during read')
        return data
    finally:
        os.close(fd)


def _json(path):
    value = json.loads(_private_bytes(path))
    _canonical(value)
    return value


def _snapshot(path, read_budget):
    from .render_ocio_facts import _chain, _signature
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute frozen writer output required')
    chain = _chain(path); before = path.lstat()
    if not 0 < before.st_size <= 512*1024*1024:
        raise ValueError('writer output size is unsupported')
    read_budget.reserve(before.st_size+1)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        if _signature(os.fstat(fd)) != _signature(before):
            raise ValueError('writer output changed before read')
        digest = hashlib.sha256(); size = 0
        while True:
            chunk = os.read(fd, min(1024*1024, before.st_size-size+1))
            if not chunk:
                break
            size += len(chunk)
            if size > before.st_size:
                raise ValueError('writer output grew during read')
            digest.update(chunk)
        if (size != before.st_size or _signature(os.fstat(fd)) != _signature(before)
                or _signature(path.lstat()) != _signature(before) or _chain(path) != chain):
            raise ValueError('writer output changed during read')
    finally:
        os.close(fd)
    return {'path':str(path), 'bytes':size, 'sha256':digest.hexdigest(), 'modified_ns':before.st_mtime_ns}


def _raw(value):
    """Preserve supported native JSON values without coercing unknown objects."""
    count = 0; byte_count = 0
    def copy(item, depth=0):
        nonlocal count, byte_count
        count += 1
        if count > 512:
            raise ValueError('hook global value count exceeds capture allowance')
        if depth > 8:
            raise ValueError('hook global nesting exceeds capture allowance')
        if type(item) in (str, int, float, bool, type(None)):
            if type(item) is str and len(item) > 8192:
                raise ValueError('hook global string exceeds capture allowance')
            if type(item) is float and not math.isfinite(item):
                raise ValueError('non-finite hook global')
            byte_count += len(json.dumps(item,ensure_ascii=False,allow_nan=False).encode('utf-8'))
            if byte_count > MAX_BYTES//4:
                raise ValueError('hook global bytes exceed capture allowance')
            return item
        if type(item) in (list, tuple) and len(item) <= 128:
            return [copy(child, depth+1) for child in item]
        if type(item) is dict and len(item) <= 128 and all(type(key) is str for key in item):
            return {copy(key,depth+1):copy(child, depth+1) for key,child in item.items()}
        raise ValueError('hook global type or count is unsupported')
    result = {'python_type':type(value).__name__[:128], 'value':copy(value)}
    _canonical(result)
    return result


def _load_context(directory):
    directory = Path(directory)
    context = _json(directory/'context.json')
    if context.get('schema') != SCHEMA or context.get('directory') != str(directory):
        raise ValueError('writer context differs from its private directory')
    return context


def authenticated_writer_process_binding(host_identity, supervisor_binding):
    """Read the configured identity from the original signed supervisor start."""
    from dcc_task_runtime.owned_process import read_receipt
    digest = host_identity.get('writer_executable_sha256')
    identity = supervisor_binding.get('identity', {})
    if digest is None and identity.get('writer_executable_sha256') is None:
        return None
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in '0123456789abcdef' for char in digest)
            or identity.get('writer_executable_sha256') != digest
            or identity.get('task_id') != host_identity.get('task_id')
            or not identity.get('launch_nonce')
            or identity['launch_nonce'] != host_identity.get('launch_nonce')):
        raise ValueError('writer executable deployment identity differs from the producer')
    started = read_receipt(supervisor_binding['directory'], 'started', identity=identity)
    binding = started.get('writer_process_binding') if isinstance(started, dict) else None
    if (not started or type(started.get('pid')) is not int
            or started['pid'] != host_identity.get('pid')
            or 'writer_process_binding_error' in started
            or not isinstance(binding, dict)
            or set(binding) != {'expected_executable', 'host_anchor'}
            or not isinstance(binding['expected_executable'], dict)
            or not isinstance(binding['host_anchor'], dict)
            or binding['host_anchor'].get('pid') != started['pid']
            or binding['expected_executable'].get('version') != host_identity.get('version')
            or _digest(binding['expected_executable']) != digest):
        raise ValueError('writer executable requires its signed host process anchor')
    return json.loads(_canonical(binding))


def _validate_process_observation(context, body):
    binding = context.get('writer_process_binding')
    observed = body.get('process_observation')
    if binding is None:
        return list(MISSING_FACTS)
    from dcc_task_runtime.process_image import validate_process_proof
    if (not isinstance(observed, dict)
            or observed.get('identity_verification') != 'OS_IMAGE_AND_ANCESTRY_BOUND'):
        raise ValueError('writer OS process observation is missing')
    validate_process_proof(observed.get('proof'), binding['expected_executable'], binding['host_anchor'])
    current = observed['proof']['chain'][0]
    if (set(observed) != {'pid', 'parent_pid', 'identity_verification', 'proof'}
            or type(observed['pid']) is not int or observed['pid'] != current['pid']
            or type(observed['parent_pid']) is not int or observed['parent_pid'] != current['parent_pid']):
        raise ValueError('writer process fields differ from its OS observation')
    return [gap for gap in MISSING_FACTS
            if gap != 'WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED']


def capture_postframe(directory, hook_globals, hou_module):
    """Called only by the generated, verified native post-frame hook."""
    from .render_color_facts import collect_render_color_facts
    from dcc_task_runtime.platform_support import open_private_file, atomic_write
    directory = Path(directory); context = _load_context(directory)
    state = _json(directory/'read-budget.json')
    budget = FileReadBudget(state, persist=lambda:atomic_write(
        directory/'read-budget.json',_canonical(state),owned_root=directory))
    budget.reserve(PRIVATE_READ_ALLOWANCE)
    if hashlib.sha256(_private_bytes(directory/'postframe.py')).hexdigest() != context['hook_sha256']:
        raise ValueError('installed writer hook bytes changed')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != context['collector_sha256']:
        raise ValueError('writer collector source changed')
    version = hou_module.applicationVersionString()
    frame = hou_module.frame()
    if (version != context['houdini_version'] or type(frame) not in (int,float)
            or not math.isfinite(frame) or frame != context['frame']):
        raise ValueError('writer hook version or frame differs from frozen context')
    if type(hook_globals) is not dict or not {'stage','settings','husk_command'} <= set(hook_globals):
        raise ValueError('native post-frame globals are missing')
    raw = {}; missing = list(MISSING_FACTS)
    for name in ('settings','husk_command'):
        try:
            raw[name] = _raw(hook_globals[name])
        except ValueError:
            raw[name] = {'python_type':type(hook_globals[name]).__name__[:128], 'observed':False}
            missing.append('HUSK_'+name.upper()+'_TYPE_UNSUPPORTED')
    color = collect_render_color_facts(hook_globals['stage'], frame=frame,
                                      settings_path=context['settings_path'])
    try:
        ocio_path = _raw(hou_module.Color.ocio_configPath())
    except Exception as error:
        ocio_path = {'observed':False, 'error_type':type(error).__name__[:128]}
    process = {'pid':os.getpid(), 'parent_pid':os.getppid(),
               'python_executable':sys.executable, 'identity_verification':'UNVERIFIED_NATIVE_HUSK'}
    binding = context.get('writer_process_binding')
    if binding is not None:
        from dcc_task_runtime import process_image
        if hashlib.sha256(Path(process_image.__file__).read_bytes()).hexdigest() != context['process_image_sha256']:
            raise ValueError('writer process image collector source changed')
        proof = process_image.capture_ancestry(binding['expected_executable'], binding['host_anchor'],
                                               read_budget=budget)
        process = {'pid':os.getpid(), 'parent_pid':os.getppid(),
                   'identity_verification':'OS_IMAGE_AND_ANCESTRY_BOUND', 'proof':proof}
    body = {'schema':SCHEMA, 'context_sha256':_digest(context), 'frame':context['frame'],
            'producer_binding_sha256':context['producer_binding_sha256'],
            'hook_nonce':context['hook_nonce'], 'hook_sha256':context['hook_sha256'],
            'houdini_version':version, 'process_observation':process,
            'hook_globals':raw, 'composed_color_facts':color, 'hom_ocio_config_path':ocio_path,
            'output':_snapshot(context['output_path'],budget), 'missing_facts':missing,
            'read_budget_used_bytes':budget.state['used_bytes']}
    body['missing_facts'] = _validate_process_observation(context, body) + [
        gap for gap in missing if gap not in MISSING_FACTS]
    payload = _canonical(body)
    key = _private_bytes(directory/'capture.key', limit=32)
    if len(key) != 32:
        raise ValueError('invalid writer observation key')
    packet = {'body':body, 'hmac_sha256':hmac.new(key,payload,hashlib.sha256).hexdigest()}
    encoded = _canonical(packet)
    fd = open_private_file(directory/'observation.json')
    with os.fdopen(fd,'wb') as stream:
        stream.write(encoded); stream.flush(); os.fsync(stream.fileno())


def validate_writer_observation(observation, producer, frame, snapshot=None, *, expected_root,
                                read_budget=None, host_identity=None, supervisor_binding=None):
    """Reauthenticate original hook bytes and compare current final output bytes."""
    if type(observation) is not dict or set(observation) != {'directory','context_sha256','receipt_sha256','body'}:
        raise ValueError('invalid writer observation binding')
    read_budget = read_budget if read_budget is not None else FileReadBudget()
    directory = Path(observation['directory'])
    if not directory.is_absolute() or directory.parent != Path(expected_root):
        raise ValueError('writer observation directory is outside the owned operation root')
    if read_budget is not None:
        # Context, original hook, event and its key are each bounded before IO.
        read_budget.reserve(PRIVATE_READ_ALLOWANCE)
    context = _load_context(directory)
    if host_identity is None and supervisor_binding is None:
        if context.get('writer_process_binding') is not None:
            raise ValueError('writer OS process proof requires the frozen producer identity')
    elif host_identity is None or supervisor_binding is None:
        raise ValueError('writer producer identity is incomplete')
    else:
        binding = authenticated_writer_process_binding(host_identity, supervisor_binding)
        if context.get('writer_process_binding') != binding:
            raise ValueError('writer process context differs from the signed producer start')
    if (observation['context_sha256'] != _digest(context)
            or context['producer_binding_sha256'] != producer or context['frame'] != frame):
        raise ValueError('writer observation belongs to a different producer/frame')
    if hashlib.sha256(_private_bytes(directory/'postframe.py')).hexdigest() != context['hook_sha256']:
        raise ValueError('installed writer hook bytes changed')
    encoded = _private_bytes(directory/'observation.json')
    if hashlib.sha256(encoded).hexdigest() != observation['receipt_sha256']:
        raise ValueError('writer observation original bytes changed')
    packet = json.loads(encoded); key = _private_bytes(directory/'capture.key',limit=32)
    if (set(packet) != {'body','hmac_sha256'} or len(key) != 32
            or not hmac.compare_digest(packet['hmac_sha256'],hmac.new(key,_canonical(packet['body']),hashlib.sha256).hexdigest())
            or packet['body'] != observation['body']):
        raise ValueError('writer observation authentication failed')
    body = packet['body']
    required_missing = _validate_process_observation(context, body)
    missing = body.get('missing_facts')
    if (not isinstance(missing, list) or missing[:len(required_missing)] != required_missing
            or any(type(gap) is not str for gap in missing)
            or ('WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED' in missing)
                != ('WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED' in required_missing)):
        raise ValueError('writer observation missing facts differ from its process authentication')
    if (body.get('schema') != SCHEMA or body.get('context_sha256') != _digest(context)
            or body.get('producer_binding_sha256') != producer or body.get('frame') != frame
            or body.get('hook_nonce') != context['hook_nonce'] or body.get('hook_sha256') != context['hook_sha256']
            or body.get('houdini_version') != context['houdini_version']
            or body.get('read_budget_used_bytes') != _json(directory/'read-budget.json')['used_bytes']):
        raise ValueError('writer observation provenance differs from the installed hook')
    if _snapshot(context['output_path'],read_budget) != body['output']:
        raise ValueError('writer-observed output bytes changed')
    if snapshot is not None and any(snapshot.get(key) != body['output'][key]
                                    for key in ('path','bytes','sha256','modified_ns')):
        raise ValueError('writer observation differs from the final frame snapshot')
    return body


def writer_root(record):
    owner = Path(record['slot']['owner_root'])
    if not owner.is_absolute() or owner.suffix != '.json':
        raise ValueError('owned operation store path is unavailable')
    return owner.parent/'writer-observations'


@contextmanager
def _creative_usd_export(node, record, frame, hou_module):
    """创作续作在既有渲染锁内隔离USD导出；退出前恢复保存合同中的原值。"""
    binding = os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
    if not binding:
        yield
        return
    from dcc_task_runtime.native_scope import NativeScope
    scope = NativeScope(json.loads(binding))
    if not scope.scope.get('creative_phase'):
        yield
        return
    scope.check()
    from dcc_task_runtime.artifact_registry import frame_path
    target = frame_path(record['output_pattern'], frame).with_suffix('.usd')
    if (not target.is_absolute() or not target.is_relative_to(scope.root)
            or target.exists() or any(p.is_symlink() for p in (target, *target.parents))):
        raise ValueError('creative USD export requires a fresh owned output')
    parm = node.parm('lopoutput')
    if (parm is None or parm.parmTemplate().type() != hou_module.parmTemplateType.String
            or parm.keyframes() or parm.isLocked()):
        raise ValueError('creative USD export requires an editable constant output path')
    original = parm.unexpandedString()
    try:
        parm.set(str(target))
        if parm.unexpandedString() != str(target):
            raise ValueError('creative USD export readback differs')
        yield
        if parm.unexpandedString() != str(target):
            raise ValueError('creative USD export changed during render')
    finally:
        parm.set(original)
        if parm.unexpandedString() != original:
            raise ValueError('creative USD export restoration differs')


@contextmanager
def render_writer_frame(node, record, frame, private_root, *, hou_module):
    """Instrument only an owned usdrender with empty, disabled native hooks."""
    from .client import render_producer_binding, render_receipt_digest
    from dcc_task_runtime.artifact_registry import frame_path
    from dcc_task_runtime.platform_support import ensure_private_directory, open_private_file
    from dcc_task_runtime.runtime_resources import locate_package_source
    version = hou_module.applicationVersionString()
    if (version not in ('21.0.631','22.0.429', *PREPARATION_VERSIONS) or node.type().nameWithCategory() != 'Driver/usdrender'
            or node.path() != record['render_target']):
        raise ValueError('writer hook requires the exact supported native usdrender')
    _require_foreground(node, frame, hou_module)
    enable = node.parm('husk_tpostframe'); script = node.parm('husk_postframe')
    if (enable is None or script is None
            or enable.parmTemplate().type() != hou_module.parmTemplateType.Toggle
            or script.parmTemplate().type() != hou_module.parmTemplateType.String):
        raise ValueError('native husk post-frame hook templates are unavailable')
    old_enable = enable.evalAtFrame(frame); old_script = script.unexpandedString()
    if (type(old_enable) not in (int,bool) or old_enable != 0 or old_script != ''
            or enable.keyframes() or script.keyframes()):
        raise ValueError('existing or animated user husk hook is not replaceable')
    if type(frame) is not int or frame not in record['frames']:
        raise ValueError('writer frame is outside the frozen request')
    producer = render_receipt_digest(render_producer_binding(record))
    config = record['render_config'][str(frame)]
    settings_path = config['rendersettings']
    if Path(private_root) != writer_root(record):
        raise ValueError('writer hook directory differs from the owned operation root')
    budget = FileReadBudget(record.setdefault('ocio_read_budget',FileReadBudget().state))
    budget.reserve(PRIVATE_READ_ALLOWANCE)
    initial_used = budget.state['used_bytes']; imported = False
    root = ensure_private_directory(Path(private_root))
    directory = Path(tempfile.mkdtemp(prefix='frame-'+str(frame)+'-',dir=root))
    source_roots = [str(locate_package_source(name,start=Path(__file__),allow_installed=True))
                    for name in ('dcc-task-runtime','houdini-bridge')]
    hook = ('import sys\nfrom pathlib import Path\n'
            'sys.path[:0] = '+repr(source_roots)+'\n'
            'from houdini_bridge.render_writer_facts import capture_postframe\n'
            'import hou\ncapture_postframe('+repr(str(directory))+', globals(), hou)\n').encode('utf-8')
    context = {'schema':SCHEMA, 'directory':str(directory), 'frame':frame, 'houdini_version':version,
               'producer_binding_sha256':producer, 'hook_nonce':secrets.token_hex(32),
               'read_budget_initial_used_bytes':initial_used,
               'settings_path':settings_path, 'output_path':str(frame_path(record['output_pattern'],frame)),
               'hook_sha256':hashlib.sha256(hook).hexdigest(),
               'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    binding = authenticated_writer_process_binding(record['host_identity'], record['supervisor_binding'])
    if binding is not None:
        from dcc_task_runtime import process_image
        context['writer_process_binding'] = binding
        context['process_image_sha256'] = hashlib.sha256(Path(process_image.__file__).read_bytes()).hexdigest()
    for name,data in (('postframe.py',hook),('context.json',_canonical(context)),
                      ('capture.key',secrets.token_bytes(32)),('read-budget.json',_canonical(budget.state))):
        fd = open_private_file(directory/name)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
    installed = str(directory/'postframe.py')
    def import_child_budget():
        nonlocal imported
        if not imported:
            child = FileReadBudget(_json(directory/'read-budget.json'))
            used = child.state['used_bytes']
            if used < initial_used:
                raise ValueError('writer read allowance regressed')
            budget.reserve(used-initial_used); imported = True
    dispatched = False
    try:
        script.set(installed); enable.set(1)
        if script.unexpandedString() != installed or enable.evalAtFrame(frame) != 1:
            raise ValueError('native writer hook deployment readback differs')
        _require_foreground(node, frame, hou_module)
        dispatched = True
        with _creative_usd_export(node, record, frame, hou_module):
            yield directory
        import_child_budget()
        if script.unexpandedString() != installed or enable.evalAtFrame(frame) != 1:
            raise ValueError('native writer hook changed during render')
        encoded = _private_bytes(directory/'observation.json')
        packet = json.loads(encoded)
        observation = {'directory':str(directory), 'context_sha256':_digest(context),
                       'receipt_sha256':hashlib.sha256(encoded).hexdigest(), 'body':packet['body']}
        validate_writer_observation(observation,producer,frame,expected_root=root,read_budget=budget,
            host_identity=record['host_identity'], supervisor_binding=record['supervisor_binding'])
        record.setdefault('writer_observations',{})[str(frame)] = observation
    finally:
        stop_error = None
        if dispatched:
            try:
                _require_foreground(node, frame, hou_module)
            except Exception as error:
                stop_error = WriterStopUnconfirmed('native synchronous render mode could not be revalidated')
                stop_error.__cause__ = error
        try:
            try:
                import_child_budget()
            finally:
                enable.set(old_enable); script.set(old_script)
            if enable.evalAtFrame(frame) != old_enable or script.unexpandedString() != old_script:
                raise ValueError('native writer hook restoration readback differs')
        finally:
            if stop_error is not None:
                raise stop_error
