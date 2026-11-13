"""Bounded parent-process OCIO observations; never effective writer proof."""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import re
import stat
from typing import Any
from houdini_bridge.render_observation_budget import FileReadBudget, RenderObservationLimit

SCHEMA = "bridge.houdini.ocio-preflight/1.0"
SOURCE = "parent_houdini_preflight"
DEPENDENCY_SCOPE = "explicit_reconstructed_processors_only"
MAX_STRING_LENGTH = 8192
MAX_ITEMS = 64
MAX_FILES = 32
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MISSING_FACTS = 64
MAX_TRANSFORM_REQUESTS = 16
MAX_REFERENCES = 128
_ABSENT = object()
_REQUIRED_GAPS = (
    ("PXL_EFFECTIVE_CONFIGURATION_UNOBSERVED", "effective_writer_configuration"),
    ("DEPENDENCY_CLOSURE_UNOBSERVED", "dependencies"),
    ("CONTEXT_VARIABLE_VALUES_UNCOLLECTED", "context.variables"),
    ("WRITER_COLOR_ALPHA_UNOBSERVED", "writer.color_alpha"),
)


def _text(value: Any) -> str:
    if type(value) is not str or len(value) > MAX_STRING_LENGTH or "\0" in value:
        raise ValueError("bounded native string required")
    return value


def _count(value: Any, limit: int = MAX_ITEMS) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("bounded native count required")
    return value


def _strings(value: Any) -> list[str]:
    if isinstance(value, (str, bytes, dict, set)):
        raise ValueError("ordered native strings required")
    size = _count(len(value))
    return [_text(value[index]) for index in range(size)]


def _requests(value: Any) -> list[dict[str, str]]:
    if type(value) not in {list, tuple} or len(value) > MAX_TRANSFORM_REQUESTS:
        raise ValueError("bounded explicit transform requests required")
    result = []
    labels = set()
    for request in value:
        if type(request) is not dict or set(request) != {"label", "source", "destination"}:
            raise ValueError("explicit label/source/destination required")
        pair = {key: _text(request[key]) for key in ("label", "source", "destination")}
        if not all(pair.values()) or pair["label"] in labels:
            raise ValueError("nonempty transform strings and unique labels required")
        labels.add(pair["label"])
        result.append(pair)
    return result


def _file_path(value: Any) -> Path:
    value = _text(value)
    path = Path(value)
    if (not value or not path.is_absolute() or ".." in path.parts or
            value.startswith("\\\\") or ":" in value[len(path.drive):]):
        raise ValueError("absolute local file path required")
    if len(path.parts) > MAX_ITEMS:
        raise ValueError("file path depth budget exceeded")
    return path


def _signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _chain(path: Path) -> tuple:
    observations = []
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("symlink or reparse point refused")
        if component == path:
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("regular file required")
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("directory ancestor required")
        observations.append((info.st_dev, info.st_ino, info.st_mode,
                             getattr(info, "st_file_attributes", 0)))
    return tuple(observations)


def _file_fact(value: str, remaining: int, read_budget=None) -> dict[str, Any]:
    path = _file_path(value)
    chain = _chain(path)
    before = path.lstat()
    limit = min(MAX_FILE_BYTES, remaining)
    if before.st_size > limit:
        raise ValueError("file byte budget exceeded")
    if read_budget is not None:
        read_budget.reserve(before.st_size + 1)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (_signature(opened) != _signature(before) or not stat.S_ISREG(opened.st_mode)
                or _chain(path) != chain):
            raise ValueError("file changed before read")
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(descriptor, min(65536, before.st_size - size + 1))
            if not block:
                break
            size += len(block)
            if size > before.st_size:
                raise ValueError("file byte budget exceeded during read")
            digest.update(block)
        if (size != before.st_size or _signature(os.fstat(descriptor)) != _signature(before)
                or _signature(path.lstat()) != _signature(before) or _chain(path) != chain):
            raise ValueError("file changed during read")
    finally:
        os.close(descriptor)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def collect_ocio_configuration(hou_module: Any, *, final_output_path: str,
                               ocio_module: Any = None,
                               transform_requests: Any = (), read_budget=None) -> dict[str, Any]:
    """Read HOM and optionally reload its observed file; do not infer output semantics."""
    read_budget = read_budget if read_budget is not None else FileReadBudget()
    if not _text(final_output_path):
        raise ValueError("final_output_path must be nonempty")
    facts: dict[str, Any] = {
        "schema": SCHEMA, "source": SOURCE, "final_output_path": final_output_path,
        "reconstruction_scope": "reloaded_config", "dependency_scope": DEPENDENCY_SCOPE,
        "transform_requests": _requests(transform_requests),
        "config": {"path": None, "file": None}, "dependencies": [],
        "api_facts": {}, "missing_facts": [],
    }

    def gap(code: str, api: str, error: Exception | None = None) -> None:
        missing = facts["missing_facts"]
        if len(missing) >= MAX_MISSING_FACTS:
            return
        item = {"code": code, "api": api}
        if error is not None:
            item["error_type"] = type(error).__name__[:128]
        missing.append(item)

    def observe(api: str, reader: Any, convert: Any = _text) -> Any:
        try:
            value = reader()
            if convert is None:
                if value is None:
                    raise ValueError("native object missing")
                facts["api_facts"][api] = {"observed": True}
            else:
                value = convert(value)
                facts["api_facts"][api] = {"observed": True, "value": value}
            return value
        except Exception as error:
            facts["api_facts"][api] = {"observed": False,
                                       "error_type": type(error).__name__[:128]}
            gap("API_UNAVAILABLE" if isinstance(error, AttributeError) else "API_READ_FAILED",
                api, error)
            return _ABSENT

    for code, api in _REQUIRED_GAPS:
        gap(code, api)
    observed_path = observe("hou.Color.ocio_configPath", lambda: hou_module.Color.ocio_configPath())
    if observed_path is not _ABSENT:
        facts["config"]["path"] = observed_path
    for name in ("ocio_spaces", "ocio_roles", "ocio_activeDisplays", "ocio_activeViews"):
        observe("hou.Color." + name, lambda name=name: getattr(hou_module.Color, name)(), _strings)

    if ocio_module is None:
        ocio_module = observe("import.PyOpenColorIO",
                              lambda: importlib.import_module("PyOpenColorIO"), None)
    if observed_path is _ABSENT:
        return facts
    try:
        facts["config"]["file"] = _file_fact(observed_path, MAX_TOTAL_BYTES, read_budget)
    except RenderObservationLimit:
        raise
    except Exception as error:
        gap("CONFIG_FILE_UNOBSERVED", "hou.Color.ocio_configPath", error)
        return facts
    if ocio_module is _ABSENT:
        return facts

    config = observe("Config.CreateFromFile",
                     lambda: ocio_module.Config.CreateFromFile(observed_path), None)
    if config is _ABSENT:
        return facts
    for name in ("getCacheID", "getSearchPath", "getWorkingDir"):
        observe("Config." + name, lambda name=name: getattr(config, name)())
    context = observe("Config.getCurrentContext", lambda: config.getCurrentContext(), None)
    if context is not _ABSENT:
        for name in ("getCacheID", "getSearchPath", "getWorkingDir"):
            observe("Context." + name, lambda name=name: getattr(context, name)())

    def rule_result(value: Any) -> list:
        if type(value) is not tuple or len(value) != 2:
            raise ValueError("documented Python file-rule tuple required")
        return [_text(value[0]), _count(value[1], 2**31 - 1)]

    observe("Config.getColorSpaceFromFilepath",
            lambda: config.getColorSpaceFromFilepath(final_output_path), rule_result)
    rules = observe("Config.getFileRules", lambda: config.getFileRules(), None)
    if rules is not _ABSENT:
        count = observe("FileRules.getNumEntries", lambda: rules.getNumEntries(), _count)
        if count is not _ABSENT:
            for index in range(count):
                for name in ("getName", "getPattern", "getExtension", "getRegex", "getColorSpace"):
                    observe(f"FileRules.{index}.{name}",
                            lambda name=name, index=index: getattr(rules, name)(index))

    total = facts["config"]["file"]["bytes"]
    seen = {facts["config"]["file"]["path"]}
    references = 0
    if not facts["transform_requests"]:
        gap("PROCESSOR_REQUESTS_ABSENT", "transform_requests")
    for index, request in enumerate(facts["transform_requests"]):
        api = f"Processor.{index}"
        if context is _ABSENT:
            gap("PROCESSOR_CONTEXT_UNOBSERVED", api)
            continue
        processor = observe(api + ".Config.getProcessor", lambda request=request:
                            config.getProcessor(context, request["source"], request["destination"]), None)
        if processor is _ABSENT:
            continue
        observe(api + ".getCacheID", lambda: processor.getCacheID())
        metadata = observe(api + ".getProcessorMetadata", lambda: processor.getProcessorMetadata(), None)
        if metadata is _ABSENT:
            continue
        filenames = observe(api + ".ProcessorMetadata.getFiles", lambda: metadata.getFiles(), _strings)
        if filenames is _ABSENT:
            continue
        for reference_index, reference in enumerate(filenames):
            references += 1
            if references > MAX_REFERENCES:
                gap("REFERENCE_BUDGET_EXCEEDED", api)
                break
            resolve_api = api + f".Context.resolveFileLocation.{reference_index}"
            resolved = observe(resolve_api, lambda: context.resolveFileLocation(reference))
            if resolved is _ABSENT:
                continue
            try:
                path = str(_file_path(resolved))
                if path in seen:
                    continue
                if len(seen) >= MAX_FILES:
                    raise ValueError("file count budget exceeded")
                dependency = _file_fact(path, MAX_TOTAL_BYTES - total, read_budget)
                facts["dependencies"].append(dependency)
                seen.add(path)
                total += dependency["bytes"]
            except RenderObservationLimit:
                raise
            except Exception as error:
                gap("DEPENDENCY_UNOBSERVED", resolve_api, error)
        if references > MAX_REFERENCES:
            break
    try:
        validate_ocio_configuration(facts, read_budget=read_budget)
    except RenderObservationLimit:
        raise
    except ValueError as error:
        facts["config"]["file"] = None
        facts["dependencies"] = []
        gap("FILES_CHANGED_DURING_COLLECTION", "file_bytes", error)
    return facts


def validate_ocio_configuration(fact: Any, *, read_budget=None) -> None:
    """Validate this observation contract and rehash recorded files, never assert readiness."""
    read_budget = read_budget if read_budget is not None else FileReadBudget()
    expected = {"schema", "source", "final_output_path", "reconstruction_scope",
                "dependency_scope", "transform_requests", "config", "dependencies",
                "api_facts", "missing_facts"}
    if (type(fact) is not dict or set(fact) != expected or fact["schema"] != SCHEMA
            or fact["source"] != SOURCE or fact["reconstruction_scope"] != "reloaded_config"
            or fact["dependency_scope"] != DEPENDENCY_SCOPE):
        raise ValueError("invalid OCIO preflight schema, source or scope")
    if not _text(fact["final_output_path"]):
        raise ValueError("final_output_path must be nonempty")
    if type(fact["transform_requests"]) is not list:
        raise ValueError("JSON transform request list required")
    _requests(fact["transform_requests"])
    config = fact["config"]
    if type(config) is not dict or set(config) != {"path", "file"}:
        raise ValueError("invalid config observation")
    if config["path"] is not None:
        _text(config["path"])
    dependencies = fact["dependencies"]
    if type(dependencies) is not list or len(dependencies) >= MAX_FILES:
        raise ValueError("invalid dependency file list")
    api_facts = fact["api_facts"]
    if type(api_facts) is not dict or len(api_facts) > 1024:
        raise ValueError("invalid API observations")
    for api, record in api_facts.items():
        _text(api)
        if (type(record) is not dict or type(record.get("observed")) is not bool
                or not set(record) <= {"observed", "value", "error_type"}
                or (not record["observed"] and ("value" in record or "error_type" not in record))
                or (record["observed"] and "error_type" in record)):
            raise ValueError("invalid API observation record")
        if "error_type" in record:
            _text(record["error_type"])
        if "value" in record:
            value = record["value"]
            values = value if type(value) is list else [value]
            _count(len(values))
            for item in values:
                if type(item) is int:
                    _count(item, 2**31 - 1)
                else:
                    _text(item)
    path_record = api_facts.get("hou.Color.ocio_configPath")
    if (type(path_record) is not dict or
            (path_record["observed"] and (type(path_record.get("value")) is not str
                                         or path_record["value"] != config["path"]))
            or (not path_record["observed"] and config["path"] is not None)):
        raise ValueError("config path differs from HOM observation")
    missing = fact["missing_facts"]
    if type(missing) is not list or len(missing) > MAX_MISSING_FACTS:
        raise ValueError("invalid missing facts")
    for gap in missing:
        if (type(gap) is not dict or not {"code", "api"} <= set(gap)
                or not set(gap) <= {"code", "api", "error_type"}):
            raise ValueError("invalid missing fact record")
        for value in gap.values():
            _text(value)
    if not set(_REQUIRED_GAPS) <= {(gap["code"], gap["api"]) for gap in missing}:
        raise ValueError("required scope gaps missing")
    files = ([config["file"]] if config["file"] is not None else []) + dependencies
    if dependencies and config["file"] is None:
        raise ValueError("dependencies require an observed config file")
    total = 0
    seen = set()
    for index, record in enumerate(files):
        if type(record) is not dict or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid file fact")
        path = str(_file_path(record["path"]))
        if path in seen or path != record["path"]:
            raise ValueError("duplicate or noncanonical file fact")
        seen.add(path)
        _count(record["bytes"], MAX_FILE_BYTES)
        digest = _text(record["sha256"])
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("invalid file SHA-256")
        total += record["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("total file byte budget exceeded")
        if index == 0 and path != str(_file_path(config["path"])):
            raise ValueError("config file differs from observed path")
    if dependencies:
        if not api_facts.get("Config.CreateFromFile", {}).get("observed"):
            raise ValueError("dependencies require reconstructed config observation")
        resolved_paths = set()
        for index in range(len(fact["transform_requests"])):
            prefix = f"Processor.{index}"
            metadata = api_facts.get(prefix + ".ProcessorMetadata.getFiles", {})
            if not metadata.get("observed"):
                continue
            if type(metadata.get("value")) is not list:
                raise ValueError("metadata references must be an observed string list")
            for reference_index in range(len(metadata.get("value", []))):
                record = api_facts.get(prefix + f".Context.resolveFileLocation.{reference_index}", {})
                if record.get("observed") and type(record.get("value")) is str:
                    try:
                        resolved_paths.add(str(_file_path(record["value"])))
                    except ValueError:
                        continue
        if not {record["path"] for record in dependencies} <= resolved_paths:
            raise ValueError("dependency file lacks an API-resolved reference")
    for record in files:
        try:
            current = _file_fact(record["path"], MAX_TOTAL_BYTES, read_budget)
        except RenderObservationLimit:
            raise
        except Exception as error:
            raise ValueError("observed OCIO file unavailable or unsafe") from error
        if current != record:
            raise ValueError("observed OCIO file bytes drifted")
