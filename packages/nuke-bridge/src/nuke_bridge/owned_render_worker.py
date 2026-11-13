#!/usr/bin/env python3
"""Fixed owned-worker route for a task-scoped Nuke background render.

The worker owns the executable boundary but does not synthesize a completion
from bytes alone: it opens the task NK snapshot, resolves the requested node,
and calls the Nuke execution API once per exact sparse frame.  A small,
explicit software API adapter is available only for the repository's process
tests when the launcher marks the route as such.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
import struct
import sys
import stat
import tempfile
from pathlib import Path
from typing import Any


def _frame_path(pattern: str, frame: int) -> Path:
    if "%" in pattern:
        try:
            return Path(pattern % frame)
        except (TypeError, ValueError):
            pass
    marker = "#"
    if marker in pattern:
        start = pattern.index(marker)
        end = start
        while end < len(pattern) and pattern[end] == marker:
            end += 1
        return Path(pattern[:start] + ("{:0" + str(end - start) + "d}").format(frame) + pattern[end:])
    return Path(pattern)


def _safe_output(path: Path) -> Path:
    original = path.expanduser()
    if original.exists() and original.is_symlink():
        raise ValueError("output frame is a symlink")
    resolved = original.resolve(strict=False)
    if resolved.exists() and resolved.is_symlink():
        raise ValueError("output frame is a symlink")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _attribute(name: str, kind: str, payload: bytes) -> bytes:
    return name.encode("ascii") + b"\0" + kind.encode("ascii") + b"\0" + struct.pack("<I", len(payload)) + payload


def _valid_tiny_exr(sample: float) -> bytes:
    channels = b"R\0" + struct.pack("<i", 1) + b"\0\0\0\0" + struct.pack("<ii", 1, 1) + b"\0"
    box = struct.pack("<iiii", 0, 0, 0, 0)
    header = b"".join((
        _attribute("channels", "chlist", channels),
        _attribute("dataWindow", "box2i", box),
        _attribute("displayWindow", "box2i", box),
        _attribute("lineOrder", "lineOrder", b"\0"),
        _attribute("compression", "compression", b"\0"),
        _attribute("pixelAspectRatio", "float", struct.pack("<f", 1.0)),
        _attribute("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0)),
        _attribute("screenWindowWidth", "float", struct.pack("<f", 1.0)),
        _attribute("comments", "string", b"bridge-owned-worker" + b"x" * 1900),
        b"\0",
    ))
    scanline = struct.pack("<iI", 0, 2) + struct.pack("<e", float(sample))
    offset = 4 + 4 + len(header) + 8
    return b"\x76\x2f\x31\x01" + struct.pack("<I", 2) + header + struct.pack("<Q", offset) + scanline


def _read_software_snapshot(path: Path) -> dict[str, Any]:
    """Decode the explicit software fixture format, never a native NK file."""
    allowed_node_classes = {
        "Read", "Write", "Copy", "Blur", "Defocus", "Denoise2", "Denoise",
        "Sharpen", "Glow", "ColorCorrect", "EdgeBlur", "Grain2", "Grain",
        "Premult", "Merge2", "NoOp",
    }
    if path.is_symlink() or not path.is_file():
        raise ValueError("snapshot is not a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "bridge.software_nuke_snapshot/1":
        raise ValueError("unsupported software snapshot")
    nodes, root = payload.get("nodes"), payload.get("root")
    if not isinstance(nodes, dict) or not isinstance(root, dict):
        raise ValueError("snapshot nodes and root are required")
    if any(type(root.get(key)) is not int for key in ("first_frame", "last_frame")) or root["first_frame"] > root["last_frame"]:
        raise ValueError("invalid snapshot frame range")
    for name, node in nodes.items():
        if not name or not isinstance(node, dict) or node.get("class") not in allowed_node_classes:
            raise ValueError("unsupported software snapshot node")
        if not isinstance(node.get("file"), str) or not isinstance(node.get("inputs"), list):
            raise ValueError("invalid snapshot node parameters")
        if "knobs" in node and not isinstance(node.get("knobs"), dict):
            raise ValueError("invalid snapshot node knobs")
        if any(target is not None and (not isinstance(target, str) or target not in nodes) for target in node["inputs"]):
            raise ValueError("snapshot connection target is missing")
        if node["class"] == "Read" and any(target is not None for target in node["inputs"]):
            raise ValueError("Read cannot have input connections")
    def visit(name, active, complete):
        if name in active:
            raise ValueError("snapshot has a connection cycle")
        if name in complete:
            return
        active.add(name)
        for target in nodes[name]["inputs"]:
            if target is not None:
                visit(target, active, complete)
        active.remove(name)
        complete.add(name)

    complete = set()
    for name in nodes:
        visit(name, set(), complete)
    return payload


class _SoftwareKnob:
    def __init__(self, value): self._value = value
    def value(self): return self._value
    def setValue(self, value): self._value = value
    def isAnimated(self): return False
    def hasExpression(self): return False


class _SoftwareWrite:
    def __init__(self, pattern: str, kind: str = "Write", name: str = "", knobs=None):
        self.pattern = pattern
        self.kind = kind
        self._name = name
        self._knobs = {'file':_SoftwareKnob(pattern), **{key:_SoftwareKnob(value) for key,value in (knobs or {}).items()}}
        self.inputs: list[_SoftwareWrite | None] = []
    def input(self, index):
        return self.inputs[index] if 0 <= index < len(self.inputs) else None
    def Class(self):
        return self.kind
    def name(self): return self._name
    def knob(self, key): return self._knobs.get(key)
    def __getitem__(self, key): return self._knobs[key]


class _SoftwareNuke:
    """Test-only host API with the same worker-visible calls as Nuke."""

    NUKE_VERSION_STRING = "software-api"

    def __init__(self, pattern: str):
        self.nodes: dict[str, _SoftwareWrite] = {}
        self.script_opened: str | None = None
        self.execute_calls: list[int] = []

    def scriptOpen(self, path: str) -> None:
        snapshot = Path(path)
        payload = _read_software_snapshot(snapshot)
        nodes = {name: _SoftwareWrite(node["file"], node["class"], name, node.get('knobs'))
                 for name, node in payload["nodes"].items()}
        for name, record in payload["nodes"].items():
            nodes[name].inputs = [nodes[target] if target is not None else None for target in record["inputs"]]
        self.nodes = nodes
        self.script_opened = str(snapshot)

    def toNode(self, name: str) -> _SoftwareWrite | None:
        return self.nodes.get(name)

    def node(self, name: str) -> _SoftwareWrite | None:
        return self.toNode(name)

    def execute(self, node: _SoftwareWrite, first: int, last: int) -> None:
        if first != last:
            raise ValueError("software adapter requires exact single-frame calls")
        if node not in self.nodes.values() or node.Class() != "Write":
            raise ValueError("execution requires a Write from the loaded snapshot")
        frame = int(first)
        def reads(current, seen=None):
            seen = set() if seen is None else seen
            if current is None or id(current) in seen:
                return []
            seen.add(id(current))
            if current.Class() == "Read":
                return [current]
            found = []
            for child in current.inputs:
                found.extend(reads(child, seen))
            return found

        sources = reads(node)
        if not sources or any(not _frame_path(source.pattern, frame).is_file() for source in sources):
            raise ValueError("snapshot Read source frame is unavailable")
        output = _safe_output(_frame_path(node.pattern, frame))
        temporary = output.with_name(output.name + ".tmp-{}".format(os.getpid()))
        temporary.write_bytes(_valid_tiny_exr(float(frame)))
        os.replace(temporary, output)
        self.execute_calls.append(frame)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_nuke_api(pattern: str):
    try:
        import nuke  # type: ignore
        return nuke
    except ImportError:
        if os.environ.get("BRIDGE_NUKE_SOFTWARE_API") == "1":
            return _SoftwareNuke(pattern)
        raise RuntimeError("Nuke API is unavailable and software API was not authorized")


def _write_receipt(payload: dict[str, Any]) -> None:
    result_file = str(os.environ.get("BRIDGE_NUKE_RESULT_FILE") or "").strip()
    if not result_file:
        return
    target = Path(result_file).expanduser()
    if target.is_symlink():
        raise ValueError("worker receipt path is a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp-{}".format(os.getpid()))
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)


def _input_contract(_cold_inputs=None):
    path, expected = (os.environ.get(key) for key in ('BRIDGE_NUKE_INPUT_CONTRACT','BRIDGE_NUKE_INPUT_CONTRACT_SHA256'))
    if path is None and expected is None:return None
    source = Path(str(path or ''))
    result = Path(str(os.environ.get('BRIDGE_NUKE_RESULT_FILE') or ''))
    operation = os.environ.get('BRIDGE_NUKE_TASK_ID')
    if (not source.is_absolute() or source.is_symlink() or not source.is_file()
            or source.parent != result.parent or source.name != str(operation)+'.inputs.json'
            or source.stat().st_size > 2*1024*1024 or _sha256(source) != expected):
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: controller input contract changed')
    contract = json.loads(source.read_text(encoding='utf-8'))
    from nuke_bridge.operation_receipts import validate_registered_input_contract
    validator = (_cold_capability(_cold_inputs).validate_contract if _cold_inputs is not None else validate_registered_input_contract)
    validator(contract)
    return contract



def _composite_contract():
    path, expected = (os.environ.get(key) for key in ('BRIDGE_NUKE_COMPOSITE_CONTRACT','BRIDGE_NUKE_COMPOSITE_CONTRACT_SHA256'))
    if path is None and expected is None:return None
    source = Path(str(path or ''))
    result = Path(str(os.environ.get('BRIDGE_NUKE_RESULT_FILE') or ''))
    if (not source.is_absolute() or source.is_symlink() or not source.is_file()
            or source.parent != result.parent or source.name != str(os.environ.get('BRIDGE_NUKE_TASK_ID'))+'.composite.json'
            or source.stat().st_size > 2*1024*1024 or _sha256(source) != expected):
        raise ValueError('COMPOSITE_CONTRACT_INVALID: controller contract changed')
    contract = json.loads(source.read_text(encoding='utf-8'))
    if (not isinstance(contract,dict) or not isinstance(contract.get('task_id'),str)
            or not contract['task_id'] or contract['task_id'] != os.environ.get('BRIDGE_NUKE_OWNER_TASK_ID')):
        raise ValueError('COMPOSITE_CONTRACT_INVALID: logical owner differs from launch identity')
    return contract

@contextmanager
def _frozen_read_inputs(node, frames, contract, _cold_inputs=None):
    """Native Read consumes private verified bytes throughout execute."""
    if contract is None:
        yield None;return
    from nuke_bridge.operation_receipts import validate_registered_input_contract
    validator = (_cold_capability(_cold_inputs).validate_contract if _cold_inputs is not None else validate_registered_input_contract)
    binding = contract['input_binding']
    patterns = {item['path']:item for item in binding['frozen_inputs_manifest']}
    reads, seen = [], set()
    def visit(current):
        if current is None or id(current) in seen:return
        seen.add(id(current))
        if current.Class() == 'Read':reads.append(current);return
        inputs = current.inputs() if callable(current.inputs) else len(current.inputs)
        for index in range(inputs):visit(current.input(index))
    visit(node)
    if not reads:raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: Write has no frozen Read')
    result_root = Path(os.environ['BRIDGE_NUKE_RESULT_FILE']).parent
    with tempfile.TemporaryDirectory(prefix='verified-nuke-input-', dir=result_root) as directory:
        copies, consumed, matched, read_bindings = {}, [], set(), []
        for read in reads:
            knob = read.knob('file')
            if (knob is None or not callable(getattr(knob,'setValue',None))
                    or knob.isAnimated() or knob.hasExpression()):
                raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: static native Read required')
            item = patterns.get(str(knob.value()))
            if item is None:raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: unbound upstream Read')
            index = item['index']; matched.add(index)
            if index not in copies:
                suffix = Path(item['path']).suffix
                pattern = str(Path(directory)/('input-'+str(index)+'.%09d'+suffix))
                by_frame = {frame['frame']:frame for frame in item['frames']}
                for frame in frames:
                    expected = by_frame.get(frame)
                    if expected is None:raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: requested frame unbound')
                    source, target = Path(expected['uri']), _frame_path(pattern,frame)
                    fd = os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
                    digest, size = hashlib.sha256(), 0
                    with os.fdopen(fd,'rb') as stream, target.open('wb') as output:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode):raise ValueError('INPUT_SOURCE_HASH_MISMATCH: regular input required')
                        for chunk in iter(lambda:stream.read(1024*1024),b''):
                            size += len(chunk)
                            if size > 512*1024*1024:raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: input byte budget exceeded')
                            digest.update(chunk);output.write(chunk)
                        after = os.fstat(stream.fileno())
                    identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
                    if (size != expected['bytes'] or digest.hexdigest() != expected['sha256']
                            or identity(before) != identity(after) or identity(before) != identity(source.stat())):
                        raise ValueError('INPUT_SOURCE_HASH_MISMATCH: copied input differs from frozen completion')
                    target.chmod(0o400)
                    consumed.append({'input_index':index,'frame':frame,'sha256':digest.hexdigest(),
                        'bytes':size,'source':str(source),'copy':str(target),'readonly_copy':True})
                copies[index] = pattern
            read_bindings.append({'node':read.name(),'source_pattern':item['path'],'copy_pattern':copies[index]})
            knob.setValue(copies[index])
            if isinstance(read,_SoftwareWrite):read.pattern=copies[index]
            if str(knob.value()) != copies[index]:
                raise ValueError('INPUT_SOURCE_HASH_MISMATCH: native Read did not bind verified copy')
        if matched != {item['index'] for item in binding['frozen_inputs_manifest']}:
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: frozen input is not consumed by Write')
        validator(contract)
        proof={'owner_task_id':contract['owner_task_id'],'frozen_inputs_sha256':binding['frozen_inputs_sha256'],
            'contract_sha256':os.environ['BRIDGE_NUKE_INPUT_CONTRACT_SHA256'],
            'before_verified':True,'after_verified':False,'consumed':consumed,'read_bindings':read_bindings}
        yield proof
        validator(contract)
        for item in consumed:
            if Path(item['copy']).stat().st_size != item['bytes'] or _sha256(Path(item['copy'])) != item['sha256']:
                raise ValueError('INPUT_SOURCE_HASH_MISMATCH: consumed copy changed during execute')
        for read in reads:
            if str(read.knob('file').value()) not in copies.values():
                raise ValueError('INPUT_SOURCE_HASH_MISMATCH: native Read changed during execute')
        proof['after_verified']=True


def _verify_project_root(nuke, _cold_inputs=None):
    if _cold_inputs is not None:
        scope = _cold_capability(_cold_inputs).scope
        from nuke_bridge.task_host_worker import _root_ocio
        return _root_ocio(nuke, scope.scope['native_color_tokens']['houdini_static_config'],
                          scope.scope['project_color']['colorspace'], configure=False)
    from nuke_bridge.task_host import creative_cold_context
    creative = creative_cold_context()
    if creative is not None:
        _, scope, _ = creative
        from nuke_bridge.task_host_worker import _root_ocio
        return _root_ocio(nuke, scope.scope['native_color_tokens']['houdini_static_config'],
                          scope.scope['project_color']['colorspace'], configure=False)
    path = os.environ.get('BRIDGE_NUKE_HOST_CONFIG')
    expected = os.environ.get('BRIDGE_NUKE_HOST_CONFIG_SHA256')
    if path is None and expected is None:
        return None
    source = Path(str(path or ''))
    if (not source.is_absolute() or source != source.resolve() or source.is_symlink()
            or not source.is_file()):
        raise ValueError('NUKE_PROJECT_COLOR_HOST_CONFIG_CHANGED')
    with source.open('rb') as stream:
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024 or hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('NUKE_PROJECT_COLOR_HOST_CONFIG_CHANGED')
    from nuke_bridge.task_host_worker import _controlled_root_color
    return _controlled_root_color(nuke, json.loads(content), configure=False)


def _main_worker(argv: list[str], _cold_inputs=None) -> int:
    if len(argv) != 7:
        raise ValueError("worker requires snapshot, node, first, last, pattern and exact frame JSON")
    snapshot, node_name, first, last, pattern, frames_json = argv[1:]
    snapshot_path = Path(snapshot).expanduser()
    if snapshot_path.is_symlink() or not snapshot_path.is_file() or snapshot_path.suffix.lower() != ".nk":
        raise ValueError("task-owned NK snapshot is required")
    if not node_name or int(first) > int(last):
        raise ValueError("invalid render identity")
    frames = json.loads(frames_json)
    if (not isinstance(frames, list) or not frames or len(frames) > 12
            or any(type(frame) is not int or frame < 1 for frame in frames)
            or len(set(frames)) != len(frames)):
        raise ValueError("invalid exact frame set")

    if min(frames) != int(first) or max(frames) != int(last):
        raise ValueError("exact frames disagree with min/max bounds")
    snapshot_sha = _sha256(snapshot_path)
    nuke = _load_nuke_api(str(pattern))
    nuke.scriptOpen(str(snapshot_path))
    if _sha256(snapshot_path) != snapshot_sha:
        raise ValueError('snapshot changed while scriptOpen consumed it')
    _verify_project_root(nuke, _cold_inputs)
    resolver = getattr(nuke, "toNode", None) or getattr(nuke, "node", None)
    if not callable(resolver):
        raise RuntimeError("Nuke node resolver is unavailable")
    node = resolver(str(node_name))
    if node is None:
        raise RuntimeError("requested Write node was not found in task snapshot")
    if node.Class() != "Write":
        raise ValueError("requested node is not a Write")
    actual_pattern = str(node["file"].value())
    if actual_pattern != str(pattern):
        raise ValueError("snapshot Write output path differs from the approved pattern")
    # The fixed worker reads the loaded snapshot's native knobs. Missing older
    # software fixture/native readbacks retain legacy execution, never typed facts.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from nuke_bridge.operation_receipts import native_write_readback
    try:
        write_readback = native_write_readback(node)
    except (AttributeError, KeyError, TypeError, ValueError):
        write_readback = None
    execute = getattr(nuke, "execute", None)
    if not callable(execute):
        raise RuntimeError("Nuke execute API is unavailable")
    if _cold_inputs is not None:_cold_capability(_cold_inputs).bind_native(nuke,node)
    contract = _input_contract(_cold_inputs)
    composite = _composite_contract()
    composite_readback = None
    if composite is not None and contract is not None and contract.get('owner_task_id') != composite['task_id']:
        raise ValueError('COMPOSITE_CONTRACT_INVALID: input and graph logical owners differ')
    if composite is not None:
        from nuke_bridge.operation_receipts import verify_composite_graph
        verify_composite_graph(nuke,composite)
        composite_readback = {'owner_task_id':composite['task_id'], 'contract_sha256':os.environ['BRIDGE_NUKE_COMPOSITE_CONTRACT_SHA256'],
                              'before_verified':True,'after_verified':False}
    with _frozen_read_inputs(node,frames,contract,_cold_inputs) as input_readback:
        active_composite = json.loads(json.dumps(composite)) if composite is not None else None
        if active_composite is not None:
            for binding in (input_readback or {}).get('read_bindings',[]):
                record = active_composite['nodes'].get(binding['node'])
                if (record is None or record['class'] != 'Read'
                        or record['knobs'].get('file') != binding['source_pattern']):
                    raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: private Read binding is foreign')
                record['knobs']['file'] = binding['copy_pattern']
            verify_composite_graph(nuke,active_composite)
        from nuke_bridge.interruption_probe import frame_entry_probe
        # 故障注入默认关闭；只在原生帧入口暂停本范围认证的那一次实际操作。
        with frame_entry_probe(nuke, node, frames, snapshot_path, snapshot_sha, contract):
            for frame in frames:
                if _cold_inputs is not None:_cold_capability(_cold_inputs).authorize_execute()
                execute(node, int(frame), int(frame))
                if active_composite is not None:verify_composite_graph(nuke,active_composite)
        if composite_readback is not None:composite_readback['after_verified'] = True
    if _sha256(snapshot_path) != snapshot_sha:
        raise ValueError('snapshot changed during native execution')
    if write_readback is not None:
        if native_write_readback(node) != write_readback:
            raise ValueError('native Write readback changed during execution')
        write_readback.update(operation_id=str(os.environ.get('BRIDGE_NUKE_TASK_ID') or ''),
                              snapshot_sha256=snapshot_sha, frames=list(frames))
    receipt = {
        "task_id": str(os.environ.get("BRIDGE_NUKE_TASK_ID") or ""),
        "snapshot_sha256": snapshot_sha,
        "snapshot": str(snapshot_path),
        "node": str(node_name),
        "frames": list(frames),
        "script_opened": True,
        "node_resolved": True,
        "execute_calls": list(frames),
        "software_api": isinstance(nuke, _SoftwareNuke),
        "outputs": [str(_frame_path(str(pattern), frame)) for frame in frames],
    }
    if write_readback is not None: receipt['write_readback'] = write_readback
    if input_readback is not None:receipt['input_readback'] = input_readback
    if composite_readback is not None:receipt['composite_readback'] = composite_readback
    _write_receipt(receipt)
    return 0


def _cold_capability(value):
    """私有worker参数不能由字典、模型字段或过期上下文替代。"""
    from nuke_bridge.task_host import _OwnedColdInputs,_ProofColdInputs
    if type(value) not in (_OwnedColdInputs,_ProofColdInputs):raise ValueError('COLD_INPUT_CONTEXT_REQUIRED')
    try:value._valid()
    except AttributeError:raise ValueError('COLD_INPUT_CONTEXT_REQUIRED') from None
    return value


def main(argv: list[str]) -> int:
    if len(argv)!=7:return _main_worker(argv)
    from nuke_bridge.task_host import _owned_cold_inputs
    with _owned_cold_inputs(Path(argv[1])) as inputs:
        return _main_worker(argv,inputs)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
