"""Exercise analysis controls through Jupyter, without patching SDK or Yahoo functions."""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient

from scripts.execute_notebook_fixture import fixture_prices_source

ROOT = Path(__file__).resolve().parents[1]


def run_workspace(filename, code, endpoint, tmp_path):
    notebook = nbformat.read(ROOT / "notebooks" / filename, as_version=4)
    notebook.cells.append(nbformat.v4.new_code_cell(code))
    executed = NotebookClient(
        notebook, timeout=60, resources={"metadata": {"path": str(tmp_path)}}
    ).execute(
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "ui-test-key"}
    )
    assert "ui-test-key" not in json.dumps(executed)
    return json.dumps(executed)


@pytest.fixture(params=[None, 3])
def scenario_api(request, cases):
    """Synthetic response values exercise plotting/partial completion, not engine accuracy."""
    received = []
    fail_after = request.param
    values = [2.0, 2.8, 3.9, 5.0, 6.1, 7.5, 9.0, 11.0, 14.0]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            assert self.path == "/v1/price"
            if fail_after is not None and len(received) > fail_after:
                status = 503
                payload = {
                    "error": {"code": "unavailable", "message": "Synthetic failure"},
                    "metadata": {
                        "request_id": "scenario-error",
                        "api_version": "v1",
                        "service_version": "fixture",
                        "fcu_charged": 0,
                    },
                }
            else:
                status = 200
                payload = copy.deepcopy(cases[0]["response"])
                payload["result"]["price"] = values[len(received) - 1]
                payload["metadata"].update(request_id=f"scenario-{len(received)}", fcu_charged=1)
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
        yield f"http://127.0.0.1:{server.server_port}", received, fail_after, values
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_spot_sweep_prices_each_point_and_stops_on_failure(scenario_api, tmp_path):
    endpoint, received, fail_after, values = scenario_api
    count = fail_after if fail_after is not None else 9
    expected_spots = [100 * (1 + i * 0.05) for i in range(-4, -4 + count)]
    code = f"""
assert price_history == [] and sweep_results == []
sweep_button.click()
assert [row['Price'] for row in sweep_results] == {values[:count]!r}
assert [row['Spot'] for row in sweep_results] == {expected_spots!r}
assert all(row['CU charged'] == 1 for row in sweep_results)
assert not any(control.disabled for control in controls)
assert price_history == []
"""
    output = run_workspace("pricing/options.ipynb", code, endpoint, tmp_path)
    assert len(received) == count + (fail_after is not None)
    assert [body["spot"] for body in received] == [
        100 * (1 + i * 0.05) for i in range(-4, -4 + len(received))
    ]
    assert all(body["volatility"] == 0.2 and body["strike"] == 100 for body in received)
    if fail_after is not None:
        assert "Stopped after 3 completed scenarios" in output
        assert "scenario-error" in output


@pytest.mark.parametrize(
    "filename,action",
    [
        ("pricing/options.ipynb", "price_button.click()"),
        ("regime/identification.ipynb", "analyze_button.click()"),
    ],
)
def test_analysis_errors_keep_charge_evidence_and_reenable_actions(
    failing_api, regime_cases, tmp_path, filename, action
):
    endpoint, received, expected = failing_api
    code = ""
    if filename.startswith("regime"):
        code = (
            fixture_prices_source(regime_cases[0]["request"]["prices"])
            + "use_history(closes, 'SPY')\n"
        )
    code += action + "\nassert last_response is None\n"
    code += "assert not load_button.disabled\n"
    output = run_workspace(filename, code, endpoint, tmp_path)
    assert len(received) == 1
    if "charged" in expected:
        assert "CU charged: " + expected.split(": ")[-1] in output
    elif "Invalid response" in expected:
        assert "failure-test-id" in output
    else:
        assert "charges may be unknown" in output


@pytest.mark.parametrize(
    "status,reason",
    [
        ("not_applicable", "predicted_not_eligible"),
        ("unavailable", "prediction_unavailable"),
    ],
)
def test_regime_renders_absent_predictions_without_score_charts(
    fixture_api, regime_cases, tmp_path, status, reason
):
    endpoint, received = fixture_api
    regime_cases[0]["response"]["result"]["direction"].update(
        status=status, reason_code=reason, prediction=None
    )
    code = (
        fixture_prices_source(regime_cases[0]["request"]["prices"])
        + f"""
use_history(closes, 'SPY')
analyze_button.click()
assert last_response.result.direction.status == {status!r}
assert not analyze_button.disabled
"""
    )
    output = run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert reason in output and len(received) == 1


def test_invalid_market_history_does_not_enable_analysis(fixture_api, tmp_path):
    endpoint, received = fixture_api
    code = """
for frame in [pd.DataFrame(), pd.DataFrame({'Close': [100.] * 511}),
              pd.DataFrame({'Close': [100.] * 511 + [float('nan')]}),
              pd.DataFrame({'Close': [100.] * 511 + [-1.]})]:
    try:
        use_history(frame, 'SPY')
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid history accepted')
    assert loaded_closes is None and analyze_button.disabled
"""
    run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert received == []


def test_pricing_interval_selection_and_timestamp_provenance(fixture_api, tmp_path):
    endpoint, received = fixture_api
    code = """
assert price_interval.value == '1d'
assert set(price_interval.options) == {
    ('Daily close', '1d'), ('1 minute', '1m'), ('5 minutes', '5m'),
    ('15 minutes', '15m'), ('30 minutes', '30m'), ('1 hour', '60m')
}
daily = yahoo_price_options('1d')
assert daily['end'] == date.today()
assert daily['start'] == date.today() - timedelta(days=14)
for interval in ['1m', '5m', '15m', '30m', '60m']:
    price_interval.value = interval
    assert yahoo_price_options(interval) == {'interval': interval, 'period': '5d'}
assert price_history == [] and last_response is None
history = pd.DataFrame({'Close': [101.25, 102.75]}, index=pd.date_range(
    '2026-10-23 10:00', periods=2, freq='5min', tz='America/New_York'))
use_yahoo_close(history, 'SPY', '5m')
assert spot.value == 102.75
assert '5m' in spot_source and '2026-10-23T10:05:00-04:00' in spot_source
assert 'America/New_York' in spot_source
source = spot_source
price_interval.value = '1d'
assert spot_source == source  # Selecting a new interval does not relabel the loaded price.
spot.value = 103
assert spot_source == 'Manual input'
history.iloc[-1, 0] = float('nan')
try:
    use_yahoo_close(history, 'SPY', '5m')
except ValueError:
    pass
else:
    raise AssertionError('Missing latest bar silently replaced')
assert spot.value == 103
assert not price_button.disabled and not load_button.disabled
"""
    run_workspace("pricing/options.ipynb", code, endpoint, tmp_path)
    assert received == []
