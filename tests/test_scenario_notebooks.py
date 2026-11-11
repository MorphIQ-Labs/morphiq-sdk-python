"""Exercise scenario notebook outcomes and receipt handling through real widget actions."""

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_analysis_notebooks import run_workspace

CASES = {
    c["name"]: c
    for c in json.loads((Path(__file__).parent / "fixtures/scenarios.json").read_text())["cases"]
}


@pytest.mark.parametrize(
    "outcome",
    ["interval", "no-root", "unresolved", "numerical-error", "invalid-response", "disconnect"],
)
def test_solver_workspace_preserves_outcomes_or_receipts(outcome, tmp_path):
    received = []
    case = CASES.get(f"solve-bsm-{outcome}", CASES["solve-bsm-price"])
    payload = copy.deepcopy(case["response"])
    if outcome == "invalid-response":
        del payload["result"]["boundaries"][0]["value"]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            if self.path == "/v1/cost/quote":
                status, response = 200, CASES["solve-bsm-price"]["quote"]
            else:
                assert self.path == "/v1/scenarios/solve-spot"
                assert self.headers["x-morphiq-max-cu"] == "100"
                if outcome == "disconnect":
                    self.close_connection = True
                    return
                status, response = case["status"], payload
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        checks = """
assert history == []
quote_button.click()
run_button.click()
assert len(history) == 2
assert not quote_button.disabled and run_button.disabled
assert not any(control.disabled for control in controls)
"""
        if outcome in ("numerical-error", "invalid-response", "disconnect"):
            checks += "assert last_response is None\n"
            if outcome == "disconnect":
                checks += "assert history[-1]['cu_charged'] is None\n"
            else:
                checks += "assert history[-1]['cu_charged'] == 100\n"
            checks += "assert 'No retry' in str(output.outputs)\n"
        else:
            checks += "assert history[-1]['cu_charged'] == 100\n"
            checks += (
                "assert last_response.result.model_dump(exclude_unset=True) == "
                f"{payload['result']!r}\n"
            )
            if outcome == "unresolved":
                checks += "assert 'Unresolved cells' in str(output.outputs)\n"
            elif outcome == "no-root":
                checks += "assert 'No boundaries found' in str(output.outputs)\n"
        run_workspace(
            "scenarios/solve-spot.ipynb", checks, f"http://127.0.0.1:{server.server_port}", tmp_path
        )
        assert [path for path, _ in received] == ["/v1/cost/quote", "/v1/scenarios/solve-spot"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
