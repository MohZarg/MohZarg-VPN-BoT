"""
Fake 3x-ui HTTP server for tests — mirrors the REAL API contract read from the 3x-ui source
(internal/web/controller/client.go): Bearer token, {"success","msg","obj"} envelope,
totalGB in bytes, traffic endpoint returns obj=null for unknown clients.
This is a TEST DOUBLE only; it is never imported by production code.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


class FakeXui:
    def __init__(self, token: str = "test-token", base_path: str = "", tls: tuple | None = None):
        self.token = token
        self.tls = tls  # (certfile, keyfile) → HTTPS (شبیه‌سازی سرور راه‌دور با گواهی self-signed)
        self.base_path = base_path.rstrip("/")
        self.clients: dict[str, dict] = {}
        self.traffic: dict[str, dict] = {}
        self.requests: list[tuple[str, str]] = []
        self.down = False            # → HTTP 503
        self.reject_writes = False   # → success=false
        self.drop_writes = False     # → success=true but change NOT applied (lying panel)
        self.fail_next = 0           # next N requests → HTTP 503
        self._srv: ThreadingHTTPServer | None = None

    # -- lifecycle
    def start(self) -> "FakeXui":
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                path = unquote(self.path.split("?")[0])
                outer.requests.append((method, path))
                if outer.down:
                    return self._send(503, {})
                if outer.fail_next > 0:
                    outer.fail_next -= 1
                    return self._send(503, {})
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                prefix = outer.base_path + "/panel/api"
                if not path.startswith(prefix):
                    return self._send(404, {})
                rel = path[len(prefix):]
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                code, payload = outer.route(method, rel, body)
                self._send(code, payload)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        if self.tls:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*self.tls)
            self._srv.socket = ctx.wrap_socket(self._srv.socket, server_side=True)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()

    @property
    def url(self) -> str:
        scheme = "https" if self.tls else "http"
        return f"{scheme}://127.0.0.1:{self._srv.server_address[1]}{self.base_path}"

    # -- routing
    @staticmethod
    def ok(obj=None):
        return 200, {"success": True, "msg": "", "obj": obj}

    @staticmethod
    def err(msg="boom"):
        return 200, {"success": False, "msg": msg, "obj": None}

    def route(self, method, rel, body):
        if method == "GET" and rel in ("/inbounds/list/slim", "/inbounds/list"):
            return self.ok([{"id": 1, "remark": "main", "protocol": "vless", "port": 443}])
        if rel.startswith("/clients/traffic/") and method == "GET":
            return self.ok(self.traffic.get(rel.split("/")[-1]))
        if rel.startswith("/clients/get/") and method == "GET":
            e = rel.split("/")[-1]
            c = self.clients.get(e)
            return self.err("record not found") if c is None else self.ok(
                {"client": c, "inboundIds": [1], "usedTraffic": 0})
        if rel.startswith("/clients/links/") and method == "GET":
            e = rel.split("/")[-1]
            return self.ok([f"vless://{self.clients[e]['uuid']}@host:443?type=tcp#{e}"]) if e in self.clients else self.ok([])
        if method == "POST" and rel.startswith("/clients/"):
            if self.reject_writes:
                return self.err("rejected")
            if rel == "/clients/add":
                c = dict(body["client"])
                if c["email"] in self.clients:
                    return self.err("duplicate email")
                if not self.drop_writes:
                    c["uuid"] = c.pop("id")
                    self.clients[c["email"]] = c
                    self.traffic[c["email"]] = {
                        "email": c["email"], "enable": c["enable"], "expiryTime": c["expiryTime"],
                        "total": c["totalGB"], "up": 0, "down": 0, "subId": c["subId"], "uuid": c["uuid"]}
                return self.ok()
            e = rel.split("/")[-1]
            if rel.startswith("/clients/update/"):
                if e not in self.clients:
                    return self.err("record not found")
                if not self.drop_writes:
                    c = self.clients[e]
                    c.update({k: v for k, v in body.items() if k != "id"})
                    t = self.traffic[e]
                    t.update(enable=c["enable"], expiryTime=c["expiryTime"], total=c["totalGB"])
                return self.ok()
            if rel.startswith("/clients/del/"):
                self.clients.pop(e, None)
                self.traffic.pop(e, None)
                return self.ok()
            if rel.startswith("/clients/resetTraffic/"):
                if e in self.traffic:
                    self.traffic[e].update(up=0, down=0)
                return self.ok()
        return 404, {}

    # -- helpers for tests
    def use(self, email: str, up: int = 0, down: int = 0):
        self.traffic[email].update(up=up, down=down)
