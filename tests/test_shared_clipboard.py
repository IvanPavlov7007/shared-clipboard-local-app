"""Integration tests against a real local HTTP/WebSocket server."""

import asyncio
import unittest
import socket
import sys
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from shared_clipboard import main, make_app, run_server


class ClipboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(make_app(port=8080, lan_ip="192.0.2.10")))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def receive(self, ws):
        return await asyncio.wait_for(ws.receive_json(), timeout=2)

    async def test_page_and_qr(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn('<textarea id="text"', await response.text())
        response = await self.client.get("/qr.svg")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/svg+xml")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        svg = ElementTree.fromstring(await response.read())
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")

    async def test_sync_clear_and_late_join(self):
        first = await self.client.ws_connect("/ws")
        second = await self.client.ws_connect("/ws")
        self.assertEqual((await self.receive(first))["text"], "")
        await self.receive(second)
        await first.send_json({"type": "update", "clientId": "first", "text": "Hello \U0001f44b"})
        acknowledgement = await self.receive(first)
        self.assertEqual(acknowledgement, await self.receive(second))
        self.assertEqual(acknowledgement["text"], "Hello \U0001f44b")
        self.assertEqual(acknowledgement["revision"], 1)
        third = await self.client.ws_connect("/ws")
        self.assertEqual((await self.receive(third))["text"], "Hello \U0001f44b")
        await second.send_json({"type": "update", "clientId": "second", "text": ""})
        for ws in (first, second, third):
            cleared = await self.receive(ws)
            self.assertEqual(cleared["text"], "")
            self.assertEqual(cleared["revision"], 2)

    async def test_invalid_messages_do_not_disconnect_or_change_state(self):
        ws = await self.client.ws_connect("/ws")
        await self.receive(ws)
        for invalid in ("not json", "null", "[]", '\"text\"', "42",
                        '{"type":"update","text":42}', '{"type":"other","text":"bad"}'):
            await ws.send_str(invalid)
        await ws.send_json({"type": "update", "text": "Still connected"})
        update = await self.receive(ws)
        self.assertEqual(update["text"], "Still connected")
        self.assertEqual(update["revision"], 1)

    async def test_foreign_origin_is_rejected(self):
        with self.assertRaises(WSServerHandshakeError) as raised:
            await self.client.ws_connect("/ws", origin="http://example.com")
        self.assertEqual(raised.exception.status, 403)

    async def test_matching_origin_is_accepted(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        ws = await self.client.ws_connect("/ws", origin=origin)
        self.assertEqual((await self.receive(ws))["revision"], 0)


class StartupTests(unittest.TestCase):
    def test_browser_startup_options(self):
        for options, expected in (([], True), (["--open"], True), (["--no-open"], False)):
            with self.subTest(options=options):
                with patch.object(sys, "argv", ["shared-clipboard", "--port", "9090", *options]):
                    with patch("shared_clipboard.run_server", new_callable=AsyncMock) as server:
                        main()
                        server.assert_awaited_once_with("0.0.0.0", 9090, expected)


class BrowserStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_opens_after_server_is_ready(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        opened = asyncio.Event()
        with patch("shared_clipboard.webbrowser.open", side_effect=lambda url: opened.set()) as browser:
            task = asyncio.create_task(run_server("127.0.0.1", port))
            try:
                await asyncio.wait_for(opened.wait(), timeout=3)
                browser.assert_called_once_with("http://localhost:{}".format(port))
                from aiohttp import ClientSession
                async with ClientSession() as client:
                    async with client.get("http://127.0.0.1:{}".format(port)) as response:
                        self.assertEqual(response.status, 200)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task


if __name__ == "__main__":
    unittest.main()
