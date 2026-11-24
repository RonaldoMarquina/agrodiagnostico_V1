"""Lightweight ASGI test client for the assistant extension."""
import asyncio
import json
from urllib.parse import urlencode


class Headers(dict):
    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class TestResponse:
    def __init__(self, status_code: int, headers: dict, body: bytes):
        self.status_code = status_code
        self.headers = Headers({k.lower(): v for k, v in headers.items()})
        self.body = body

    def json(self):
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self):
        return self.body.decode("utf-8") if self.body else ""


class TestClient:
    def __init__(self, app):
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        params: dict = None,
        headers: dict = None,
        json_data=None,
        raw_body: bytes = None,
    ) -> TestResponse:
        query_string = urlencode(params).encode("ascii") if params else b""

        raw_headers = []
        has_content_type = False
        if headers:
            for k, v in headers.items():
                if k.lower() == "content-type":
                    has_content_type = True
                raw_headers.append((k.lower().encode("latin1"), str(v).encode("latin1")))

        body_bytes = b""
        if raw_body is not None:
            body_bytes = raw_body
        elif json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            if not has_content_type:
                raw_headers.append((b"content-type", b"application/json"))
        raw_headers.append((b"content-length", str(len(body_bytes)).encode("ascii")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_string,
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }

        response_messages = []

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(message):
            response_messages.append(message)

        asyncio.run(self.app(scope, receive, send))

        status_code = 500
        resp_headers = {}
        resp_body = b""

        for msg in response_messages:
            if msg["type"] == "http.response.start":
                status_code = msg["status"]
                for k, v in msg.get("headers", []):
                    resp_headers[k.decode("latin1")] = v.decode("latin1")
            elif msg["type"] == "http.response.body":
                resp_body += msg.get("body", b"")

        return TestResponse(status_code, resp_headers, resp_body)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json=None, **kwargs):
        return self.request("POST", path, json_data=json, **kwargs)
