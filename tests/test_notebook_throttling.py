import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_analysis_notebooks import run_workspace


@pytest.mark.parametrize("gateway", [False, True])
def test_sweep_429_shows_retry_after_and_keeps_charge_unknown_when_absent(cases, tmp_path, gateway):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            assert self.path == "/v1/price:batch"
            self.send_response(429)
            self.send_header("Retry-After", "120")
            self.send_header("x-request-id", "throttle-check")
            self.end_headers()
            if gateway:
                self.wfile.write(b"<html>Rate limited</html>")
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "metadata": {**cases[0]["response"]["metadata"], "fcu_charged": 0},
                            "error": {"code": "concurrency_limited", "message": "Try later"},
                        }
                    ).encode()
                )

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        code = f"""
sweep_button.click()
assert sweep_results == []
assert len(charge_history) == 1
assert charge_history[0]['CU charged'] is {None if gateway else 0!r}
assert 'Retry-After: 120' in str(sweep_output.outputs)
assert 'No retry or batch splitting' in str(sweep_output.outputs)
assert ('total incomplete' in usage_summary.value) == {gateway!r}
assert not any(control.disabled for control in controls)
"""
        run_workspace(
            "pricing/options.ipynb", code, f"http://127.0.0.1:{server.server_port}", tmp_path
        )
        assert len(received) == 1 and len(received[0]["requests"]) == 9
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
