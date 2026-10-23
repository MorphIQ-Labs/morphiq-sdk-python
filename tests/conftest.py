import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cases():
    return json.loads((ROOT / "tests/fixtures/pricing.json").read_text())["cases"]


@pytest.fixture
def regime_cases():
    return json.loads((ROOT / "tests/fixtures/regime.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch):
    monkeypatch.delenv("MORPHIQ_API_KEY", raising=False)
    monkeypatch.delenv("MORPHIQ_API_BASE_URL", raising=False)


@pytest.fixture
def fixture_api(cases, regime_cases):
    """Loopback replay of contract fixtures; no numerical implementation or external calls."""
    received = []
    cases = cases + regime_cases

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), body))
            match = next((case for case in cases if case["request"] == body), None)
            if match is None or self.path != match.get("path", "/v1/price"):
                self.send_error(422)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(match["response"]).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(params=["api_zero", "api_charged", "invalid", "disconnect"])
def failing_api(request, cases):
    """Controlled HTTP failures for executable examples, without runtime patching."""
    failure = request.param
    received = []
    expected = {
        "api_zero": "Commercial CU charged: 0",
        "api_charged": "Commercial CU charged: 7",
        "invalid": "Invalid response; request_id=failure-test-id",
        "disconnect": "execution and charges may be unknown",
    }[failure]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if failure == "disconnect":
                self.close_connection = True
                return
            if failure == "invalid":
                status, body = 200, {}
            else:
                charged = 7 if failure == "api_charged" else 0
                status = 500 if charged else 422
                body = {
                    "error": {"code": "pricing_failed", "message": "Synthetic failure"},
                    "metadata": {
                        **cases[0]["response"]["metadata"],
                        "request_id": "failure-test-id",
                        "fcu_charged": charged,
                    },
                }
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("x-request-id", "failure-test-id")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
