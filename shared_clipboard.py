#!/usr/bin/env python3
"""A tiny, in-memory shared clipboard for devices on the same local network."""

import sys

if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9 or newer is required. Please install a current Python release.")

import argparse
import asyncio
import io
import json
import socket
import webbrowser
from urllib.parse import urlsplit

try:
    from aiohttp import WSMsgType, web
    import segno
except ImportError:
    raise SystemExit(
        "Missing dependency: aiohttp or segno\n"
        "Install them with:  python -m pip install aiohttp segno"
    )


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Shared Clipboard</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, -apple-system, sans-serif; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      min-height: 100dvh;
      background: Canvas;
      color: CanvasText;
    }
    main {
      width: min(100%, 1100px);
      min-height: 100vh;
      min-height: 100dvh;
      margin: auto;
      padding: max(12px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right))
               max(12px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    header { display: flex; align-items: center; gap: 10px; min-height: 36px; }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    #status { margin-left: auto; font-size: 14px; white-space: nowrap; }
    #status::before {
      content: "";
      display: inline-block;
      width: 9px;
      height: 9px;
      margin-right: 6px;
      border-radius: 50%;
      background: #d14343;
    }
    #status.connected::before { background: #2d9d55; }
    textarea {
      display: block;
      flex: 1 1 auto;
      width: 100%;
      min-height: 65vh;
      min-height: 65dvh;
      resize: none;
      padding: 14px;
      border: 1px solid #8888;
      border-radius: 10px;
      background: Field;
      color: FieldText;
      font: 16px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
      tab-size: 4;
      outline: none;
    }
    textarea:focus { border-color: #4388dd; box-shadow: 0 0 0 3px #4388dd33; }
    footer { display: flex; align-items: center; gap: 12px; min-height: 38px; }
    #count { color: GrayText; font-size: 14px; }
    button, .button {
      min-width: 72px;
      min-height: 38px;
      padding: 7px 14px;
      border: 1px solid #8888;
      border-radius: 8px;
      background: ButtonFace;
      color: ButtonText;
      font: inherit;
      cursor: pointer;
    }
    .button { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
    #qr { margin-left: auto; }
    button:active, .button:active { transform: translateY(1px); }
    @media (max-width: 600px) {
      main { padding-top: max(8px, env(safe-area-inset-top)); gap: 8px; }
      textarea { padding: 12px; border-radius: 8px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Shared Clipboard</h1>
      <span id="status" role="status" aria-live="polite">Connecting…</span>
    </header>
    <textarea id="text" autofocus spellcheck="false" aria-label="Shared text"></textarea>
    <footer>
      <span id="count">0 characters</span>
      <a id="qr" class="button" href="/qr.svg" target="_blank" rel="noopener">Phone QR</a>
      <button id="clear" type="button">Clear</button>
    </footer>
  </main>
  <script>
    (() => {
      "use strict";
      const area = document.querySelector("#text");
      const status = document.querySelector("#status");
      const count = document.querySelector("#count");
      const clear = document.querySelector("#clear");
      const clientId = (crypto.randomUUID ? crypto.randomUUID() :
        Date.now().toString(36) + Math.random().toString(36).slice(2));
      let ws = null;
      let sendTimer = null;
      let reconnectTimer = null;
      let reconnectDelay = 500;
      let lastRevision = -1;

      function updateCount() {
        const n = Array.from(area.value).length;
        count.textContent = `${n.toLocaleString()} character${n === 1 ? "" : "s"}`;
      }

      function setStatus(connected) {
        status.classList.toggle("connected", connected);
        status.textContent = connected ? "Connected" : "Disconnected / reconnecting";
      }

      function queueSend() {
        updateCount();
        clearTimeout(sendTimer);
        const text = area.value;
        sendTimer = setTimeout(() => {
          sendTimer = null;
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({type: "update", clientId, text}));
          }
        }, 100);
      }

      function connect() {
        clearTimeout(reconnectTimer);
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const connection = new WebSocket(`${protocol}//${location.host}/ws`);
        ws = connection;
        // Revisions restart at zero if the Python process itself was restarted.
        lastRevision = -1;

        connection.addEventListener("open", () => {
          if (ws !== connection) return;
          reconnectDelay = 500;
          setStatus(true);
        });

        connection.addEventListener("message", event => {
          if (ws !== connection) return;
          let message;
          try { message = JSON.parse(event.data); } catch (_) { return; }
          if (message.type !== "update" || typeof message.text !== "string") return;
          if (!Number.isSafeInteger(message.revision) || message.revision <= lastRevision) return;
          lastRevision = message.revision;

          // An acknowledgement of our own send must not disturb the cursor or a
          // newer pending edit. A remote update supersedes an unsent local edit.
          if (message.clientId === clientId) return;
          clearTimeout(sendTimer);
          sendTimer = null;
          if (area.value !== message.text) {
            area.value = message.text;
            updateCount();
          }
        });

        connection.addEventListener("close", () => {
          if (ws !== connection) return;
          ws = null;
          setStatus(false);
          reconnectTimer = setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 1.7, 10000);
        });

        connection.addEventListener("error", () => connection.close());
      }

      area.addEventListener("input", queueSend);
      clear.addEventListener("click", () => {
        if (area.value === "") return;
        area.value = "";
        queueSend();
        area.focus();
      });

      updateCount();
      setStatus(false);
      connect();
    })();
  </script>
</body>
</html>
"""


class Clipboard:
    def __init__(self):
        self.text = ""
        self.revision = 0
        self.clients = set()

    async def page(self, request):
        return web.Response(text=PAGE, content_type="text/html", charset="utf-8")

    async def qr_code(self, request):
        lan_ip = request.app["lan_ip"]
        if not lan_ip:
            raise web.HTTPServiceUnavailable(
                text="LAN address detection failed. Check the server window and use ipconfig."
            )

        phone_url = "http://{}:{}".format(lan_ip, request.app["port"])
        qr = segno.make(phone_url, error="m", micro=False)
        image = io.BytesIO()
        qr.save(image, kind="svg", scale=8, border=4, dark="#111827", light="#ffffff")
        return web.Response(
            body=image.getvalue(),
            content_type="image/svg+xml",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'inline; filename="shared-clipboard-phone-qr.svg"',
            },
        )

    async def websocket(self, request):
        # Browsers should only connect from the page served by this process.
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != request.host.lower():
            raise web.HTTPForbidden(text="WebSocket origin not allowed")

        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=10 * 1024 * 1024)
        await ws.prepare(request)
        self.clients.add(ws)

        await ws.send_json({
            "type": "update",
            "clientId": None,
            "text": self.text,
            "revision": self.revision,
        })

        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(message.data)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("type") != "update" or not isinstance(data.get("text"), str):
                        continue

                    new_text = data["text"]
                    if new_text == self.text:
                        continue
                    self.text = new_text
                    self.revision += 1
                    outgoing = json.dumps({
                        "type": "update",
                        "clientId": data.get("clientId"),
                        "text": self.text,
                        "revision": self.revision,
                    }, ensure_ascii=False)
                    await self.broadcast(outgoing)
                elif message.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def broadcast(self, message):
        stale = []
        for client in tuple(self.clients):
            if client.closed:
                stale.append(client)
                continue
            try:
                await client.send_str(message)
            except (ConnectionError, RuntimeError):
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


def find_lan_ipv4():
    """Ask the OS which local address it would use; no packet is sent."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))  # Reserved TEST-NET address.
        address = probe.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        probe.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    return None


def make_app(port=8080, lan_ip=None):
    clipboard = Clipboard()
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app["lan_ip"] = lan_ip or find_lan_ipv4()
    app["port"] = port
    app.router.add_get("/", clipboard.page)
    app.router.add_get("/qr.svg", clipboard.qr_code)
    app.router.add_get("/ws", clipboard.websocket)
    return app


async def run_server(host, port, open_browser=True):
    lan_ip = find_lan_ipv4()
    runner = web.AppRunner(make_app(port, lan_ip), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    print("Shared clipboard running")
    print("PC:        http://localhost:{}".format(port))
    if lan_ip:
        print("Phone/LAN: http://{}:{}".format(lan_ip, port))
    else:
        print("Phone/LAN: LAN IPv4 detection failed; run 'ipconfig' and use your Wi-Fi IPv4 address.")
    print("Press Ctrl+C to stop.")

    if open_browser:
        webbrowser.open("http://localhost:{}".format(port))

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description="Tiny LAN shared clipboard")
    parser.add_argument("--host", default="0.0.0.0", help="listen address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="listen port (default: 8080)")
    browser_options = parser.add_mutually_exclusive_group()
    browser_options.add_argument("--open", dest="open_browser", action="store_true",
                                 help="open the PC page in the default browser (default)")
    browser_options.add_argument("--no-open", dest="open_browser", action="store_false",
                                 help="start the server without opening a browser")
    parser.set_defaults(open_browser=True)
    args = parser.parse_args()

    try:
        asyncio.run(run_server(args.host, args.port, args.open_browser))
    except KeyboardInterrupt:
        print("\nShared clipboard stopped.")


if __name__ == "__main__":
    main()
