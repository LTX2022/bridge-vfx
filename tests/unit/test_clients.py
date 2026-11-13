from __future__ import annotations

import json
import io
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch

from houdini_bridge.client import HoudiniClient
from nuke_bridge.client import NukeClient, NukeConnectionError


class HoudiniClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = []

        class Response:
            def __enter__(response):
                return response

            def __exit__(response, *_args):
                return False

            def read(response) -> bytes:
                return json.dumps({"status": "success", "data": {"ok": True}}).encode("utf-8")

        def urlopen(request, *, timeout):
            self.requests.append(request.data.decode("utf-8"))
            self.assertGreater(timeout, 0)
            return Response()

        self.urlopen_patch = patch("houdini_bridge.client.urllib.request.urlopen", urlopen)
        self.urlopen_patch.start()

    def tearDown(self) -> None:
        self.urlopen_patch.stop()

    def test_legacy_command_is_normalized(self) -> None:
        client = HoudiniClient(8100)
        self.assertEqual(client.call("scene_info"), {"ok": True})
        payload = json.loads(parse_qs(self.requests[0])["json"][0])
        self.assertEqual(payload[2]["command"], "scene.info")


class NukeClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.response = {"status": "success", "data": {"command": "nuke_ping"}}

        class Connection:
            def __init__(connection, response):
                connection.response = response

            def __enter__(connection):
                return connection

            def __exit__(connection, *_args):
                return False

            def sendall(connection, payload: bytes) -> None:
                connection.request = json.loads(payload.decode("utf-8"))

            def makefile(connection, _mode: str):
                return io.BytesIO((json.dumps(connection.response) + "\n").encode("utf-8"))

        def create_connection(address, *, timeout):
            self.assertEqual(address[0], "127.0.0.1")
            self.assertGreater(timeout, 0)
            return Connection(self.response)

        self.connection_patch = patch("nuke_bridge.client.socket.create_connection", create_connection)
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()

    def test_health_uses_nuke_ping(self) -> None:
        client = NukeClient(59555)
        self.assertEqual(client.health(), {"command": "nuke_ping"})

    def test_non_object_response_is_reported(self) -> None:
        self.response = None
        try:
            with self.assertRaises(NukeConnectionError):
                NukeClient(59556).health()
        finally:
            self.response = {"status": "success", "data": {"command": "nuke_ping"}}
