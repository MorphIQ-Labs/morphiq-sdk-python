"""Exercise analysis controls through Jupyter, without patching SDK or Yahoo functions."""

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
        notebook,
        timeout=60,
        skip_cells_with_tag="requires-network",
        resources={"metadata": {"path": str(tmp_path)}},
    ).execute(
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "ui-test-key"}
    )
    assert "ui-test-key" not in json.dumps(executed)
    return json.dumps(executed)


@pytest.fixture(params=[None, 3])
def scenario_api(request, cases):
    """One synthetic batch with optional item failure, not an engine accuracy test."""
    received = []
    failed_index = request.param
    values = [2.0, 2.8, 3.9, 5.0, 6.1, 7.5, 9.0, 11.0, 14.0]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            assert self.path == "/v1/price:batch"
            results = []
            for index, value in enumerate(values):
                if index == failed_index:
                    results.append(
                        {
                            "index": index,
                            "status": "error",
                            "error": {"code": "pricing_failed", "message": "Synthetic failure"},
                        }
                    )
                else:
                    results.append(
                        {
                            "index": index,
                            "status": "success",
                            "result": {**cases[0]["response"]["result"], "price": value},
                        }
                    )
            payload = {
                "results": results,
                "metadata": {
                    **cases[0]["response"]["metadata"],
                    "request_id": "scenario-batch",
                    "fcu_charged": 7,
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, failed_index, values
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_spot_sweep_preserves_failed_rows_and_counts_batch_once(scenario_api, tmp_path):
    endpoint, received, failed_index, values = scenario_api
    expected = [None if i == failed_index else v for i, v in enumerate(values)]
    expected_spots = [100 * (1 + i * 0.05) for i in range(-4, 5)]
    code = f"""
sweep_button.click()
assert len(sweep_results) == 9
assert [row['Price'] for row in sweep_results] == {expected!r}
assert [row['Spot'] for row in sweep_results] == {expected_spots!r}
assert all('CU charged' not in row for row in sweep_results)
assert len(charge_history) == 1 and charge_history[0]['CU charged'] == 7
assert usage_summary.value == 'Kernel session total: 7 CU. Requests: 1.'
assert sum('image/png' in o.get('data', {{}}) for o in sweep_output.outputs) == 1
assert not any(control.disabled for control in controls)
assert price_history == []
"""
    output = run_workspace("pricing/options.ipynb", code, endpoint, tmp_path)
    assert len(received) == 1
    assert [body["spot"] for body in received[0]["requests"]] == expected_spots
    if failed_index is not None:
        assert "pricing_failed" in output


@pytest.mark.parametrize(
    "filename,action",
    [
        ("pricing/options.ipynb", "price_button.click()"),
        ("pricing/options.ipynb", "greeks_button.click()"),
        ("pricing/options.ipynb", "iv_button.click()"),
        ("pricing/options.ipynb", "sweep_button.click()"),
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
    code += "assert not ticker.disabled\n"
    if action == "iv_button.click()":
        code += "assert last_iv_response is None and iv_snapshot is None\n"
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


def test_invalid_market_history_is_rejected_without_request(fixture_api, tmp_path):
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
    assert loaded_closes is None and not analyze_button.disabled
"""
    run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert received == []


def test_regime_button_is_ready_without_a_loading_cell(fixture_api, tmp_path):
    endpoint, received = fixture_api
    code = """
assert loaded_closes is None and last_response is None
assert not analyze_button.disabled
ticker.value = ''
analyze_button.click()
assert 'Enter a ticker' in analysis_status.value
assert loaded_closes is None and last_response is None
assert not analyze_button.disabled and not ticker.disabled and not price_interval.disabled
ticker.value = 'SPY'
assert not analyze_button.disabled
"""
    run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert received == []


def test_one_regime_click_publishes_complete_result_and_redraw_uses_cache(
    fixture_api, regime_cases, tmp_path
):
    endpoint, received = fixture_api
    code = (
        fixture_prices_source(regime_cases[0]["request"]["prices"])
        + """
use_history(closes, 'SPY')
analyze_button.click()
assert last_response is not None
assert analysis_status.value.startswith('Analysis complete')
assert analyze_button.description == 'Show analysis'
# Verify the widget's actual state immediately after the first callback returns.
outputs = analysis_output.outputs
tables = [o['data']['text/html'] for o in outputs if 'text/html' in o.get('data', {})]
assert len(tables) == 2
assert all(head in tables[0] for head in ['Decision', 'Direction', 'State'])
assert 'Model SHA-256' in tables[1] and 'Engine(s)' in tables[1]
assert sum('image/png' in o.get('data', {}) for o in outputs) == 1
text = ''.join(o.get('text', '') for o in outputs)
assert 'fixture-regime' in text and 'CU charged: not reported' in text
assert not analyze_button.disabled and not ticker.disabled and not price_interval.disabled
response = last_response
analysis_output.outputs = ()
analyze_button.click()
assert last_response is response
assert analysis_output.outputs == outputs
ticker.value = 'QQQ'
assert last_response is None and analysis_output.outputs == ()
assert not analyze_button.disabled
assert analyze_button.description == 'Analyze regime · 1 request'
"""
    )
    run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert len(received) == 1


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
assert not price_button.disabled and not ticker.disabled
"""
    run_workspace("pricing/options.ipynb", code, endpoint, tmp_path)
    assert received == []


def test_regime_intraday_prices_and_selection_invalidation(fixture_api, regime_cases, tmp_path):
    endpoint, received = fixture_api
    code = (
        fixture_prices_source(regime_cases[0]["request"]["prices"])
        + """
assert price_interval.value == '1d'
assert set(price_interval.options) == {
    ('Daily close', '1d'), ('1 minute', '1m'), ('5 minutes', '5m'),
    ('15 minutes', '15m'), ('30 minutes', '30m'), ('1 hour', '60m')
}
assert yahoo_history_options('1d')['end'] == date.today()
assert yahoo_history_options('60m') == {'interval': '60m', 'period': '6mo'}
price_interval.value = '5m'
# Include an overnight gap, a weekend, and a missing bar within a session.
closes.index = pd.DatetimeIndex([
    stamp
    for day in ['2026-10-15', '2026-10-16', '2026-10-19', '2026-10-20',
                '2026-10-21', '2026-10-22', '2026-10-23']
    for stamp in pd.date_range(day + ' 09:30', periods=78, freq='5min',
                               tz='America/New_York')
]).delete(100)[-512:]
original = closes['Close'].copy()
fig = price_history_figure(original, 'SPY', '5m')
lines = fig.axes[0].lines
assert len(lines) == 8
for line in lines:
    timestamps = pd.DatetimeIndex(line.get_xdata())
    assert (timestamps.to_series().diff().dropna() == pd.Timedelta(minutes=5)).all()
assert [value for line in lines for value in line.get_ydata()] == original.tolist()
assert [stamp for line in lines for stamp in line.get_xdata()] == list(original.index)
assert 'America/New_York' in fig.axes[0].get_xlabel()
plt.close(fig)
daily_fig = price_history_figure(original, 'SPY', '1d')
assert len(daily_fig.axes[0].lines) == 1
plt.close(daily_fig)
pd.testing.assert_series_equal(original, closes['Close'])
use_history(closes, 'SPY', '5m')
assert loaded_interval == '5m'
assert loaded_closes.tolist() == closes['Close'].tolist()
assert 'America/New_York' in price_timestamp(loaded_closes.index[-1], loaded_interval)
assert '-04:00' in price_timestamp(loaded_closes.index[-1], loaded_interval)
assert last_response is None
analyze_button.click()
assert last_response is not None
price_interval.value = '60m'
assert loaded_closes is None and loaded_interval is None and last_response is None
assert not analyze_button.disabled
ticker.value = 'QQQ'
assert loaded_closes is None and loaded_ticker is None and not analyze_button.disabled
"""
    )
    output = run_workspace("regime/identification.ipynb", code, endpoint, tmp_path)
    assert "may still be forming" in output
    assert len(received) == 1
