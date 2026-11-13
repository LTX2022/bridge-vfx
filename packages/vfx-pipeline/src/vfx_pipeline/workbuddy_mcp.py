"""Small stdio MCP diagnostic adapter. No host or approval capabilities."""
from __future__ import annotations

import json
import sys
from typing import Any

MAX_MESSAGE_BYTES = 1024 * 1024
VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')


def _schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
IDENTIFIER = {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,100}$'}
OBSERVATION = _schema({'description': TEXT, 'shape': TEXT, 'direction': TEXT,
    'dominant_colors': {'type': 'array', 'items': TEXT}, 'uncertainties': {'type': 'array', 'items': TEXT}}, ('description',))
TOOLS = [
    {'name': 'health', 'description': 'Read diagnostic status; never certifies model identity or DCC success.', 'inputSchema': _schema()},
    {'name': 'catalog', 'description': 'List registered non-private synthetic image asset IDs.', 'inputSchema': _schema()},
    {'name': 'media', 'description': 'Read actual image content for one registered synthetic asset. No file paths accepted.',
     'inputSchema': _schema({'asset_id': IDENTIFIER}, ('asset_id',))},
    {'name': 'submit_observation', 'description': 'Persist your own image observation using a stable request ID. Does not grade it or execute DCC.',
     'inputSchema': _schema({'asset_id': IDENTIFIER, 'request_id': IDENTIFIER, 'observation': OBSERVATION}, ('asset_id', 'request_id', 'observation'))},
]
for _tool in TOOLS:
    _tool['annotations'] = {'readOnlyHint': _tool['name'] != 'submit_observation',
                            'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}


def _error(identifier, code, message):
    return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': code, 'message': message}}


def _text_content(value):
    return {'type': 'text', 'text': json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))}


class DiagnosticMCP:
    def __init__(self, facade):
        self.facade = facade
        self.tools = TOOLS
        self.server_name = 'bridge-hy3-diagnostic'
        self.instructions = 'Synthetic diagnostic only. Model selection and permission boundary remain unverified. No DCC tools.'
        self.initializing = False
        self.ready = False

    def dispatch(self, request: Any):
        if not isinstance(request, dict):
            return _error(None, -32600, 'Invalid request')
        identifier = request.get('id')
        notification = 'id' not in request
        valid_id = identifier is None or isinstance(identifier, (str, int)) and not isinstance(identifier, bool)
        if (request.get('jsonrpc') != '2.0' or not valid_id or not isinstance(request.get('method'), str)
                or set(request) - {'jsonrpc', 'id', 'method', 'params'}):
            return None if notification else _error(None, -32600, 'Invalid request')
        method, params = request['method'], request.get('params', {})
        if not isinstance(params, dict):
            return None if notification else _error(identifier, -32602, 'Parameters must be an object')
        if notification:
            if method == 'notifications/initialized' and self.initializing:
                self.ready = True
            return None
        try:
            if method == 'initialize':
                if self.initializing:
                    return _error(identifier, -32600, 'Session already initialized')
                if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('clientInfo'), dict) or not isinstance(params.get('capabilities'), dict):
                    return _error(identifier, -32602, 'Invalid initialization parameters')
                requested = params['protocolVersion']
                self.facade.record_event('mcp_initialize', {'requested_protocol': requested[:100]})
                self.initializing = True
                result = {'protocolVersion': requested if requested in VERSIONS else VERSIONS[0],
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': self.server_name, 'version': '0.1.0'},
                          'instructions': self.instructions}
            elif method == 'ping':
                result = {}
            elif not self.ready:
                return _error(identifier, -32000, 'Initialize this MCP session first')
            elif method == 'tools/list':
                if set(params) - {'_meta'}:
                    return _error(identifier, -32602, 'Invalid tool listing parameters')
                result = {'tools': self.tools}
            elif method == 'tools/call':
                result = self._call(params)
            else:
                return _error(identifier, -32601, 'Method not found')
            return {'jsonrpc': '2.0', 'id': identifier, 'result': result}
        except Exception:
            # Do not expose local paths, exception payloads or private logs.
            return _error(identifier, -32603, 'Diagnostic service unavailable; controller inspection required')

    def _call(self, params):
        name, arguments = params.get('name'), params.get('arguments', {})
        if set(params) - {'name', 'arguments', '_meta'} or not isinstance(arguments, dict):
            return {'isError': True, 'content': [_text_content({'code': 'INVALID_ARGUMENTS'})]}
        tool = next((item for item in TOOLS if item['name'] == name), None)
        if tool is None:
            self.facade.record_event('mcp_tool_rejected', {'code': 'UNKNOWN_TOOL'})
            return {'isError': True, 'content': [_text_content({'code': 'UNKNOWN_TOOL'})]}
        schema = tool['inputSchema']
        if set(arguments) - set(schema['properties']) or set(schema['required']) - set(arguments):
            self.facade.record_event('mcp_tool_rejected', {'tool': name, 'code': 'INVALID_ARGUMENTS'})
            return {'isError': True, 'content': [_text_content({'code': 'INVALID_ARGUMENTS'})]}
        self.facade.record_event('mcp_tool_requested', {'tool': name})
        try:
            if name == 'health':
                content = [_text_content(self.facade.health())]
            elif name == 'catalog':
                content = [_text_content(self.facade.catalog())]
            elif name == 'media':
                content = [self.facade.media(arguments['asset_id'])]
            else:
                content = [_text_content(self.facade.submit_observation(arguments['asset_id'], arguments['observation'], arguments['request_id']))]
        except (ValueError, TypeError, KeyError):
            self.facade.record_event('mcp_tool_rejected', {'tool': name, 'code': 'INVALID_OR_CHANGED_INPUT'})
            return {'isError': True, 'content': [_text_content({'code': 'INVALID_OR_CHANGED_INPUT', 'hint': 'Use registered asset IDs and the documented tool schema; reuse request IDs only for identical observations.'})]}
        self.facade.record_event('mcp_tool_completed', {'tool': name,
            **({'asset_id': arguments['asset_id']} if 'asset_id' in arguments else {})})
        return {'content': content, 'isError': False}


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def serve(facade, stdin=None, stdout=None, *, adapter_class=DiagnosticMCP):
    """Serve newline-delimited JSON-RPC; oversize input terminates this session."""
    source = stdin if stdin is not None else sys.stdin.buffer
    target = stdout if stdout is not None else sys.stdout
    if stdout is None and callable(getattr(target, 'reconfigure', None)):
        target.reconfigure(encoding='utf-8', errors='strict', newline='\n')
    adapter = adapter_class(facade)
    while True:
        line = source.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            return
        oversized = len(line if isinstance(line, bytes) else line.encode('utf-8')) > MAX_MESSAGE_BYTES
        if oversized:
            response = _error(None, -32600, 'Message exceeds diagnostic limit; reconnect required')
        else:
            try:
                request = json.loads(line, object_pairs_hook=_object,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
                response = adapter.dispatch(request)
            except (ValueError, UnicodeError, RecursionError):
                response = _error(None, -32700, 'Invalid JSON')
        if response is not None:
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
            try:
                target.write(encoded)
                target.flush()
            except (BrokenPipeError, OSError):
                return
        if oversized:
            return
