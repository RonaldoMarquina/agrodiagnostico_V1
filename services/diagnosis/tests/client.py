"""Lightweight ASGI test client without external dependencies for Diagnosis tests."""
import asyncio
import json
from http.cookies import SimpleCookie
from urllib.parse import urlencode


class Headers(dict):
    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class TestResponse:
    def __init__(self, status_code: int, headers: dict, body: bytes, cookies: dict):
        self.status_code = status_code
        self.headers = Headers({k.lower(): v for k, v in headers.items()})
        self.body = body
        self.cookies = cookies

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
        json_data: dict = None,
        data: bytes = None,
        cookies: dict = None,
    ) -> TestResponse:
        query_string = b""
        if "?" in path:
            path, qs = path.split("?", 1)
            query_string = qs.encode("ascii")
        if params:
            encoded_params = urlencode(params).encode("ascii")
            if query_string:
                query_string = query_string + b"&" + encoded_params
            else:
                query_string = encoded_params

        raw_headers = []
        if headers:
            for k, v in headers.items():
                raw_headers.append((k.lower().encode("latin1"), str(v).encode("latin1")))

        if cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            raw_headers.append((b"cookie", cookie_str.encode("latin1")))

        body_bytes = b""
        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            raw_headers.append((b"content-type", b"application/json"))
        elif data is not None:
            body_bytes = data
        if not any(k.lower() == "content-length" for k in (headers or {})):
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
        resp_cookies = {}

        for msg in response_messages:
            if msg["type"] == "http.response.start":
                status_code = msg["status"]
                for k, v in msg.get("headers", []):
                    key = k.decode("latin1")
                    val = v.decode("latin1")
                    if key.lower() == "set-cookie":
                        parsed = SimpleCookie()
                        parsed.load(val)
                        resp_cookies.update({name: morsel.value for name, morsel in parsed.items()})
                    resp_headers[key] = val
            elif msg["type"] == "http.response.body":
                resp_body += msg.get("body", b"")

        return TestResponse(status_code, resp_headers, resp_body, resp_cookies)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json: dict = None, **kwargs):
        return self.request("POST", path, json_data=json, **kwargs)

    def patch(self, path: str, json: dict = None, **kwargs):
        return self.request("PATCH", path, json_data=json, **kwargs)

    def put(self, path: str, json: dict = None, **kwargs):
        return self.request("PUT", path, json_data=json, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)
