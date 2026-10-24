"""Exercise billing totals through actual notebook buttons and a loopback HTTP service."""

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import nbformat
from test_analysis_notebooks import run_workspace


def test_session_costs_include_errors_unknowns_and_partial_sweeps(
    cases, greeks_cases, iv_cases, analytics_cases, tmp_path
):
    large = 2**53 + 1
    steps = [
        (cases[0], 2, 200),
        (greeks_cases[0], 3, 200),
        (iv_cases[0], 4, 200),
        (analytics_cases[1], large, 200),
        (analytics_cases[1], 0, 200),
        (analytics_cases[1], None, 200),
        (analytics_cases[1], 7, 500),
        (analytics_cases[1], 11, "malformed"),
        (analytics_cases[1], None, "disconnect"),
        (cases[0], 13, 200),
        (cases[0], 17, 200),
        (cases[0], 19, 500),
    ]
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body))
            case, charge, status = steps[len(received) - 1]
            assert self.path == case.get("path", "/v1/price")
            if status == "disconnect":
                self.close_connection = True
                return
            payload = copy.deepcopy(case["response"])
            payload["metadata"].update(
                request_id=f"cost-{len(received)}",
                fcu_charged=charge,
                fcu_quoted=999,
                units_charged=888,
            )
            if status == 500:
                payload.pop("result")
                payload["error"] = {"code": "pricing_failed", "message": "Synthetic failure"}
            elif status == "malformed":
                del payload["result"]["greeks"]["vega"]
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        code = f"""
price_button.click()
greeks_button.click()
market_price.value = 10.450583572185538
iv_button.click()
volatility.value = 35
analytics_button.click()
assert len(charge_history) == 4
assert usage_summary.value == 'Kernel session total: {large + 9} CU. Requests: 4.'
assert str({large}) in str(usage_output.outputs)
show_usage()
show_usage()
assert len(charge_history) == 4
market_price.value = -1
analytics_button.click()
assert len(charge_history) == 4  # Local input errors made no request.
market_price.value = 10.450583572185538
analytics_button.click()  # Reported zero is complete, not unknown.
assert usage_summary.value == 'Kernel session total: {large + 9} CU. Requests: 5.'
analytics_button.click()  # Missing commercial charge.
assert 'total incomplete (1 unknown charges)' in usage_summary.value
analytics_button.click()  # Charged API failure.
assert charge_history[-1]['CU charged'] == 7
analytics_button.click()  # Malformed result with valid billing metadata.
assert charge_history[-1]['CU charged'] == 11
assert last_analytics_response is None
analytics_button.click()  # Connection loss: cannot assume a zero charge.
assert charge_history[-1]['CU charged'] is None
sweep_button.click()  # Two successes plus a charged failure.
assert len(sweep_results) == 2 and len(charge_history) == 12
assert usage_summary.value == ('Kernel session: {large + 76} CU reported; '
                              'total incomplete (2 unknown charges). Requests: 12.')
assert [r['CU charged'] for r in charge_history[-3:]] == [13, 17, 19]
assert not any(control.disabled for control in controls)
"""
        # Re-execute the real setup cell: the kernel-session ledger must survive Run All.
        notebook = nbformat.read(
            Path(__file__).parents[1] / "notebooks/pricing/options.ipynb", as_version=4
        )
        setup = next(cell.source for cell in notebook.cells if cell.id == "workspace")
        code += f"\nexec({setup!r})\nassert len(charge_history) == 12\n"
        output = run_workspace(
            "pricing/options.ipynb", code, f"http://127.0.0.1:{server.server_port}", tmp_path
        )
        assert len(received) == 12
        assert "cost-12" in output and str(large + 76) in output
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
