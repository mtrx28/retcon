"""Tiny stdlib JSON/HTML router shared by the sandbox services (no extra dependencies).

A route handler is `fn(req) -> (status, body)`; `body` is a dict/list (JSON) or str (HTML).
`req` has .method .path .params (path captures) .query (dict of str) .json (parsed body or None).
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Raw:
    """A pre-encoded response body with an explicit content type (static files)."""

    def __init__(self, data, content_type):
        self.data, self.content_type = data, content_type


class Request:
    def __init__(self, method, path, params, query, body):
        self.method, self.path, self.params, self.query, self.json = method, path, params, query, body


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, fn):
        rx = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, rx, fn))

    def mount(self, prefix, other):
        for m, rx, fn in other.routes:
            self.routes.append((m, re.compile("^" + re.escape(prefix) + rx.pattern[1:]), fn))

    def dispatch(self, method, raw_path, body=None):
        u = urlparse(raw_path)
        query = {k: v[0] for k, v in parse_qs(u.query).items()}
        for m, rx, fn in self.routes:
            hit = rx.match(u.path)
            if m == method and hit:
                return fn(Request(method, u.path, hit.groupdict(), query, body))
        return 404, {"error": {"code": "NOT_FOUND", "message": f"{method} {u.path}", "details": {}}}


def serve(router, port=0, host="127.0.0.1"):
    """Start in a daemon thread; returns (server, base_url). port=0 picks a free port."""
    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = None
            if n:
                try:
                    body = json.loads(self.rfile.read(n))
                except ValueError:
                    return self._send(400, {"error": {"code": "INVALID_ARGUMENT",
                                                      "message": "body is not JSON", "details": {}}})
            self._send(*router.dispatch(method, self.path, body))

        def _send(self, status, body):
            if isinstance(body, Raw):
                data, ctype = body.data, body.content_type
            else:
                html = isinstance(body, str)
                data = (body if html else json.dumps(body)).encode("utf8")
                ctype = "text/html; charset=utf-8" if html else "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")   # dev services: never serve a stale page or API reply
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://{host}:{srv.server_address[1]}"
