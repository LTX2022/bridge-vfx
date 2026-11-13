#!/usr/bin/env python3
"""Read-only Pyro SOP type-template capture, NOT a solver implementation.

Only use in a separately authorized, empty local Houdini session. No scene,
parameter values, asset-library paths or materials are read. Dynamic menu
script presence is queried, but no script body is emitted or executed.
No nodes, connections, parameters, permissions, caches or renders are changed.
Stdout is evidence for human review, never authority to register a binding or
unlock execution. A normal Python process is never used to launch Houdini.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from typing import Any

# Exact existing catalogue candidates, not guessed parameter identifiers.
NODE_TYPES = ('pyrosolver', 'pyrosolver::2.0')
MAX_TEMPLATES = 4096
MAX_DEPTH = 16
_MISSING = object()


class _CaptureReadFailure(Exception):
    """Internal fail-closed error carrying only fixed diagnostic metadata."""

    def __init__(self, stage: str, interface: str, exception_type: str,
                 context: dict[str, Any] | None = None) -> None:
        self.stage = stage
        self.interface = interface
        self.exception_type = exception_type
        self.context = dict(context or {})
        super().__init__(self.error_code())

    def error_code(self) -> str:
        return (f'TYPE_CAPTURE_FAILED:stage={self.stage}:'
                f'interface={self.interface}:exception={self.exception_type}')

    def as_dict(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            'stage': self.stage,
            'interface': self.interface,
            'exception_type': self.exception_type,
        }
        details.update(self.context)
        return details


def _safe_exception_type(exc: Exception) -> str:
    """Return a stable exception class name, never exception text."""
    name = type(exc).__name__
    return name if isinstance(name, str) and name.isidentifier() else 'Exception'


def _read(stage: str, interface: str, operation: Any,
          *, context: dict[str, Any] | None = None) -> Any:
    """Run one read and attach stable, non-sensitive failure metadata."""
    try:
        return operation()
    except _CaptureReadFailure:
        raise
    except Exception as exc:
        raise _CaptureReadFailure(
            stage, interface, _safe_exception_type(exc), context
        ) from None


def _optional_method(target: Any, attribute: str, stage: str, interface: str,
                    *, context: dict[str, Any] | None = None) -> Any:
    """Read an optional template method without treating absence as failure."""
    try:
        method = getattr(target, attribute, _MISSING)
    except AttributeError:
        return None
    except Exception as exc:
        raise _CaptureReadFailure(
            stage, interface, _safe_exception_type(exc), context
        ) from None
    return None if method is _MISSING or not callable(method) else method


def _required_method(target: Any, attribute: str, stage: str, interface: str,
                    *, context: dict[str, Any] | None = None) -> Any:
    """Read a method required by a recognized template type."""
    method = _read(
        stage, interface, lambda: getattr(target, attribute), context=context)
    if not callable(method):
        raise _CaptureReadFailure(stage, interface, 'TypeError', context)
    return method


def _optional_read(target: Any, attribute: str, stage: str, interface: str,
                   warnings: list[dict[str, Any]], *,
                   context: dict[str, Any] | None = None) -> Any:
    """Read optional metadata and retain a stable warning on AttributeError."""
    try:
        method = getattr(target, attribute)
    except AttributeError:
        failure = _CaptureReadFailure(stage, interface, 'AttributeError', context)
        detail = failure.as_dict()
        detail['kind'] = 'OPTIONAL_METADATA_UNAVAILABLE'
        warnings.append(detail)
        return _MISSING
    except Exception as exc:
        raise _CaptureReadFailure(
            stage, interface, _safe_exception_type(exc), context
        ) from None
    if not callable(method):
        failure = _CaptureReadFailure(stage, interface, 'TypeError', context)
        detail = failure.as_dict()
        detail['kind'] = 'OPTIONAL_METADATA_UNAVAILABLE'
        warnings.append(detail)
        return _MISSING
    try:
        return _read(stage, interface, method, context=context)
    except _CaptureReadFailure as failure:
        if failure.exception_type != 'AttributeError':
            raise
        detail = failure.as_dict()
        detail['kind'] = 'OPTIONAL_METADATA_UNAVAILABLE'
        warnings.append(detail)
        return _MISSING


def _template_context(node_type_index: int, requested_type: str,
                      template_index: tuple[int, ...] | None = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        'node_type_index': node_type_index,
        'requested_type': requested_type,
    }
    if template_index is not None:
        context['template_index'] = list(template_index)
    return context


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _record_warning(warnings: list[dict[str, Any]], kind: str, stage: str,
                    interface: str, exception_type: str,
                    context: dict[str, Any], **extra: Any) -> None:
    detail = _CaptureReadFailure(
        stage, interface, exception_type, context).as_dict()
    detail['kind'] = kind
    detail.update(extra)
    warnings.append(detail)


def _templates(entries: Any, parent: tuple[str, ...] = (),
               budget: list[int] | None = None, *, node_type_index: int,
               requested_type: str,
               template_index: tuple[int, ...] = (),
               template_types: Any,
               warnings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if budget is None:
        budget = [MAX_TEMPLATES]
    if warnings is None:
        warnings = []
    if len(parent) > MAX_DEPTH:
        raise ValueError('template nesting limit exceeded')
    rows = []
    for entry_index, template in enumerate(entries):
        current_index = template_index + (entry_index,)
        context = _template_context(node_type_index, requested_type, current_index)
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError('template count limit exceeded')
        name = _read(
            'template.name', 'hou.ParmTemplate.name',
            lambda: str(template.name()), context=context)
        template_type_value = _read(
            'template.type', 'hou.ParmTemplate.type',
            lambda: template.type(), context=context)
        template_type = str(template_type_value)
        row: dict[str, Any] = {
            'template_path': list(parent + (name,)),
            'name': name,
            'label': _read(
                'template.label', 'hou.ParmTemplate.label',
                lambda: str(template.label()), context=context),
            'type': template_type,
            'components': _read(
                'template.components', 'hou.ParmTemplate.numComponents',
                lambda: int(template.numComponents()), context=context),
        }
        is_folder = _read(
            'template.type_dispatch.folder', 'hou.parmTemplateType.Folder',
            lambda: template_type_value == getattr(template_types, 'Folder'),
            context=context)
        is_ramp = _read(
            'template.type_dispatch.ramp', 'hou.parmTemplateType.Ramp',
            lambda: template_type_value == getattr(template_types, 'Ramp'),
            context=context)
        if is_folder and is_ramp:
            raise _CaptureReadFailure(
                'template.type_dispatch', 'capture.template_type_dispatch',
                'ValueError', context)
        if is_folder or is_ramp:
            children_interface = (
                'hou.FolderParmTemplate.parmTemplates' if is_folder
                else 'hou.RampParmTemplate.parmTemplates')
            children = _required_method(
                template, 'parmTemplates', 'template.children_method',
                children_interface, context=context)
        else:
            children_interface = 'hou.ParmTemplate.parmTemplates'
            children = _optional_method(
                template, 'parmTemplates', 'template.children_method',
                children_interface, context=context)
        if children is not None:
            if is_folder:
                folder_type = _optional_read(
                    template, 'folderType', 'template.folder_type',
                    'hou.FolderParmTemplate.folderType', warnings,
                    context=context)
                if folder_type is not _MISSING:
                    row['folder_type'] = str(folder_type)
            elif not is_ramp:
                _record_warning(
                    warnings, 'UNKNOWN_CHILD_TEMPLATE_OWNER',
                    'template.type_dispatch', 'capture.template_type_dispatch',
                    'ValueError', context, observed_type=template_type)
            child_entries = _read(
                'template.children', children_interface,
                lambda: tuple(children()), context=context)
            row['children'] = _read(
                'template.walk', 'capture.template_walk',
                lambda: _templates(
                    child_entries, parent + (name,), budget,
                    node_type_index=node_type_index,
                    requested_type=requested_type,
                    template_index=current_index,
                    template_types=template_types,
                    warnings=warnings,
                ), context=context)
        # No instance Parm.menuItems(), eval(), defaultExpression(), tags(),
        # HDA sections or any menu-generator execution. Retain only a boolean
        # about a template script, never its body.
        menu_items = _optional_method(
            template, 'menuItems', 'template.menu_method',
            'hou.MenuParmTemplate.menuItems', context=context)
        if menu_items is not None:
            generator = _optional_method(
                template, 'itemGeneratorScript',
                'template.item_generator_script_method',
                'hou.MenuParmTemplate.itemGeneratorScript', context=context)
            dynamic = False if generator is None else _read(
                'template.item_generator_script',
                'hou.MenuParmTemplate.itemGeneratorScript',
                lambda: bool(generator()), context=context)
            row['dynamic_menu'] = dynamic
            if not dynamic:
                items = _read(
                    'template.menu_items', 'hou.MenuParmTemplate.menuItems',
                    lambda: [str(item) for item in menu_items()], context=context)
                labels = _read(
                    'template.menu_labels', 'hou.MenuParmTemplate.menuLabels',
                    lambda: [str(label) for label in template.menuLabels()],
                    context=context)
                if len(items) != len(labels):
                    raise _CaptureReadFailure(
                        'template.menu_alignment',
                        'capture.static_menu_alignment', 'ValueError', context)
                row['menu_items'] = items
                row['menu_labels'] = labels
        rows.append(row)
    return rows


def _capture_node_type(hou_module: Any, category: Any, requested_type: str,
                       node_type_index: int,
                       warnings: list[dict[str, Any]]) -> dict[str, Any]:
    context = _template_context(node_type_index, requested_type)
    native = _read(
        'node.lookup', 'hou.nodeType',
        lambda: hou_module.nodeType(category, requested_type), context=context)
    if native is None:
        return {'requested_type': requested_type, 'available': False}

    native_category = _read(
        'node.category', 'hou.NodeType.category',
        lambda: native.category(), context=context)
    category_name = _read(
        'node.category_name', 'hou.NodeTypeCategory.name',
        lambda: native_category.name(), context=context)
    native_name = _read(
        'node.name', 'hou.NodeType.name',
        lambda: str(native.name()), context=context)
    if category_name != 'Sop' or native_name != requested_type:
        raise _CaptureReadFailure(
            'node.identity', 'capture.native_type_identity', 'ValueError', context)

    min_inputs = _read(
        'node.min_inputs', 'hou.NodeType.minNumInputs',
        lambda: int(native.minNumInputs()), context=context)
    max_inputs = _read(
        'node.max_inputs', 'hou.NodeType.maxNumInputs',
        lambda: int(native.maxNumInputs()), context=context)
    group = _read(
        'node.parm_template_group', 'hou.NodeType.parmTemplateGroup',
        lambda: native.parmTemplateGroup(), context=context)
    entries = _read(
        'node.parm_template_entries', 'hou.ParmTemplateGroup.entries',
        lambda: tuple(group.entries()), context=context)
    template_types = _read(
        'host.parm_template_type', 'hou.parmTemplateType',
        lambda: hou_module.parmTemplateType, context=context)
    templates = _read(
        'template.walk', 'capture.template_walk',
        lambda: _templates(
            entries, node_type_index=node_type_index,
            requested_type=requested_type,
            template_types=template_types,
            warnings=warnings,
        ), context=context)
    return {
        'requested_type': requested_type,
        'resolved_type': native_name,
        'category': 'Sop',
        'available': True,
        'min_inputs': min_inputs,
        'max_inputs': max_inputs,
        'templates': templates,
    }


def _record_failure(result: dict[str, Any], failure: _CaptureReadFailure) -> None:
    result['errors'].append(failure.error_code())
    result['failure_details'].append(failure.as_dict())


def capture(hou_module: Any, *, synthetic: bool = False) -> dict[str, Any]:
    """Capture native type interfaces only; callers must label injected fakes."""
    result: dict[str, Any] = {
        'schema': 'bridge.pyro.sourcing-template-capture/1.0',
        'evidence_kind': 'FAKE_HOM_SOFTWARE_ONLY' if synthetic else 'UNATTESTED_LOCAL_TYPE_CAPTURE',
        'capture_state': 'INCOMPLETE',
        'solver_sourcing_implemented': False,
        'registered_bindings': [],
        'runtime_verified': False,
        'visual_verified': False,
        'route_verified': False,
        'provider_verified': False,
        'dcc_acceptance_unlocked': False,
        'nodes': [],
        'errors': [],
        'failure_details': [],
        'warnings': [],
    }
    try:
        version = _read(
            'host.version', 'hou.applicationVersion',
            lambda: list(hou_module.applicationVersion()))
        if len(version) < 3 or any(type(item) is not int or item < 0 for item in version):
            raise _CaptureReadFailure(
                'host.version_validation', 'capture.version_shape_validation',
                'ValueError')
        result['houdini_version'] = version
        category = _read(
            'host.sop_category', 'hou.sopNodeTypeCategory',
            lambda: hou_module.sopNodeTypeCategory())
    except _CaptureReadFailure as failure:
        _record_failure(result, failure)
        result['snapshot_sha256'] = hashlib.sha256(_json(result).encode('utf-8')).hexdigest()
        return result

    for node_type_index, name in enumerate(NODE_TYPES):
        try:
            result['nodes'].append(
                _capture_node_type(
                    hou_module, category, name, node_type_index,
                    result['warnings']))
        except _CaptureReadFailure as failure:
            _record_failure(result, failure)

    if result['failure_details'] or result['warnings']:
        result['capture_state'] = 'INCOMPLETE'
    elif not any(node['available'] for node in result['nodes']):
        result['errors'].append('NO_REGISTERED_SOLVER_TYPE')
    else:
        result['capture_state'] = 'CAPTURED_NOT_BOUND'
    result['snapshot_sha256'] = hashlib.sha256(_json(result).encode('utf-8')).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-read-only-type-capture', action='store_true',
                        help='explicitly permit type-interface reads in an already authorized local session')
    args = parser.parse_args(argv)
    if not args.confirm_read_only_type_capture:
        print(_json({'capture_state': 'NOT_RUN', 'reason': 'EXPLICIT_LOCAL_CAPTURE_CONFIRMATION_REQUIRED'}))
        return 2
    try:
        hou_module = importlib.import_module('hou')
    except ImportError:
        print(_json({'capture_state': 'NOT_RUN', 'reason': 'HOU_UNAVAILABLE'}))
        return 2
    result = capture(hou_module)
    print(_json(result))
    # Exit 0 means metadata capture only, never a sourcing/runtime pass.
    return 0 if result['capture_state'] == 'CAPTURED_NOT_BOUND' else 2


if __name__ == '__main__':
    raise SystemExit(main())
