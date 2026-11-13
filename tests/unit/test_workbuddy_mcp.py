import io
import json
import unittest

from vfx_pipeline.workbuddy_mcp import DiagnosticMCP, MAX_MESSAGE_BYTES, serve


class Facade:
    def __init__(self): self.events = []
    def record_event(self, kind, payload): self.events.append((kind, payload))
    def health(self): return {'dcc_dispatch_enabled': False}
    def catalog(self): return {'assets': [{'asset_id': 'a'}]}
    def media(self, asset_id):
        if asset_id != 'a': raise ValueError('/private/do-not-leak')
        return {'type': 'image', 'mimeType': 'image/png', 'data': 'eA=='}
    def submit_observation(self, asset_id, observation, request_id):
        return {'observation_recorded': True, 'visual_correctness_verified': False}


def request(method, params=None, identifier=1):
    return {'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params or {}}


class WorkBuddyMCPTests(unittest.TestCase):
    def setUp(self):
        self.facade = Facade()
        self.adapter = DiagnosticMCP(self.facade)

    def initialize(self):
        result = self.adapter.dispatch(request('initialize', {'protocolVersion': '2025-03-26', 'clientInfo': {'name': 'test', 'version': '1'}, 'capabilities': {}}))
        self.assertEqual(result['result']['protocolVersion'], '2025-03-26')
        self.assertIsNone(self.adapter.dispatch({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_handshake_and_real_image_block(self):
        self.assertIn('error', self.adapter.dispatch(request('tools/list')))
        self.initialize()
        listed = self.adapter.dispatch(request('tools/list'))['result']['tools']
        self.assertEqual({t['name'] for t in listed}, {'health', 'catalog', 'media', 'submit_observation'})
        image = self.adapter.dispatch(request('tools/call', {'name': 'media', 'arguments': {'asset_id': 'a'}}))['result']['content'][0]
        self.assertEqual(image['type'], 'image')

    def test_unknown_capabilities_and_extra_arguments_rejected(self):
        self.initialize()
        for name, args in [('dcc.execute', {}), ('health', {'path': '/private'}), ('media', {})]:
            result = self.adapter.dispatch(request('tools/call', {'name': name, 'arguments': args}))
            self.assertTrue(result['result']['isError'])
        self.assertEqual(self.adapter.dispatch(request('resources/read'))['error']['code'], -32601)

    def test_exception_does_not_expose_paths(self):
        self.initialize()
        result = self.adapter.dispatch(request('tools/call', {'name': 'media', 'arguments': {'asset_id': 'unknown'}}))
        self.assertNotIn('/private', json.dumps(result))
        self.assertTrue(result['result']['isError'])

    def test_stdio_invalid_and_oversize_messages(self):
        for data, code in [(b'{bad}\n', -32700), (b'{"jsonrpc":"2.0","id":1,"id":2}\n', -32700),
                           (b'x' * (MAX_MESSAGE_BYTES + 1), -32600), (b'[]\n', -32600)]:
            output = io.StringIO()
            serve(self.facade, io.BytesIO(data), output)
            self.assertEqual(json.loads(output.getvalue())['error']['code'], code)

    def test_notifications_never_return_reply(self):
        output = io.StringIO()
        serve(self.facade, io.BytesIO(b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}\n'), output)
        self.assertEqual(output.getvalue(), '')
