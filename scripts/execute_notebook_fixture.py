"""Execute a notebook against loopback contract fixtures; no external API calls."""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import nbformat
from nbclient import NotebookClient

NOTEBOOK_CASES = {
    "scenarios/evaluate.ipynb": (
        "scenario-bsm-point-quote",
        "scenario-bsm-point",
        "scenario-bsm-grid-quote",
        "scenario-bsm-grid",
        "scenario-bs1993-point-quote",
        "scenario-bs1993-point",
    ),
    "scenarios/solve-spot.ipynb": (
        "solve-bsm-price-quote",
        "solve-bsm-price",
        "solve-bsm-pnl-quote",
        "solve-bsm-pnl",
        "solve-bs1993-pnl-quote",
        "solve-bs1993-pnl",
    ),
    "start-here.ipynb": (),
    "pricing/models.ipynb": (),  # Explicit actions tested in test_api_v050.
    "pricing/standard-five.ipynb": (),
    "cost/quotation.ipynb": (),  # Setup is inert; test_cost exercises explicit actions.
    "pricing/options.ipynb": (
        "batch-price-sweep",
        "european",
        "greeks-european",
        "iv-european",
        "analytics-european-premium",
        "american",
        "greeks-american",
        "iv-american",
        "analytics-american-premium",
    ),
    "regime/identification.ipynb": ("regime",),
}


def workspace_exercise(filename: str, prices: list[float]) -> str:
    """Exercise real widget actions with explicit synthetic market data in offline checks."""
    if filename == "scenarios/evaluate.ipynb":
        return """
assert history == [] and last_response is None and run_button.disabled
quote_button.click()
assert last_quote.quote.total_fcu == 2 and len(history) == 1
max_cu.value = 1
run_button.click()
assert len(history) == 1 and last_response is None
max_cu.value = 2
run_button.click()
assert last_response.results[0].status == 'success'
assert last_response.results[0].inputs.spot == 105
assert len(history) == 2 and history[-1]['cu_charged'] == 2
spot_change.value = 10
assert last_response is None and last_quote is None and run_button.disabled
assert history[-1]['request']['scenarios'][0]['spot_change'] == 5
mode.value = 'grid'
quote_button.click()
max_cu.value = 10
run_button.click()
assert len(last_response.results) == 9 and history[-1]['cu_charged'] == 10
model.value = 'bs1993'
mode.value = 'point'
spot_change.value = 5
quote_button.click()
max_cu.value = 4
run_button.click()
assert last_response.base.result.pricing_model == 'bjerksund_stensland_1993'
assert len(history) == 6 and history[-1]['cu_charged'] == 4
mode.value = 'grid'
grid_spots.value = 'invalid'
quote_button.click()
assert len(history) == 6 and last_response is None
assert not quote_button.disabled and run_button.disabled
"""
    if filename == "scenarios/solve-spot.ipynb":
        return """
assert history == [] and last_response is None and run_button.disabled
quote_button.click()
assert last_quote.quote.total_fcu == 100 and history[-1]['cu_charged'] == 0
run_button.click()
assert last_response.result.coverage.status == 'resolved'
assert last_response.result.boundaries[0].kind == 'point'
assert last_response.metadata.fcu_charged == 100
assert history[-1]['request']['target']['kind'] == 'option_price'
target_kind.value = 'position_pnl'
target_value.value = 500
assert last_response is None and run_button.disabled
quote_button.click()
run_button.click()
assert last_response.result.target.kind == 'position_pnl'
assert history[-1]['cu_charged'] == 100
model.value = 'bs1993'
quote_button.click()
max_cu.value = 199
run_button.click()
assert len(history) == 5 and last_response is None
max_cu.value = 200
run_button.click()
assert len(history) == 6 and history[-1]['cu_charged'] == 200
assert last_response.result.pricing_model == 'bjerksund_stensland_1993'
assert '400 CU' in usage.value and '0 unknown' in usage.value
assert not quote_button.disabled and run_button.disabled
"""
    if filename == "pricing/options.ipynb":
        return """
assert price_history == []
assert sweep_results == []
sweep_button.click()
assert len(sweep_results) == 9 and len(charge_history) == 1
spot.value = 120
use_yahoo_close(pd.DataFrame({'Close': [100.0]}, index=pd.to_datetime(['2026-01-02'])), 'SPY')
assert spot.value == 100.0 and 'SPY' in spot_source
price_button.click()
assert len(price_history) == 1 and last_response.result.price == 10.45058357218557
greeks_button.click()
assert last_greeks_response.metadata.request_id == 'fr-18e4e90129262501-0000000000000005'
assert len(greeks_table) == 10 and greeks_table.loc['vega', 'Value'] == 37.52403469169381
assert greeks_table.loc['theta', 'Value'] == -6.414027546438199
assert sum('text/html' in o.get('data', {}) for o in greeks_output.outputs) == 2
assert greeks_snapshot['Style'] == 'european' and greeks_snapshot['CU charged'] == 'not reported'
market_price.value = 10.450583572185538
volatility.value = 0  # Solving IV must not validate an unused volatility assumption.
iv_button.click()
assert last_iv_response.metadata.request_id == 'fr-18e4e90129262501-0000000000000007'
assert abs(last_iv_response.result.implied_volatility - 0.2) < 1e-12
assert last_iv_response.result.used_fallback is False
assert iv_snapshot['residual_basis'] == 'forward_normalised_price'
assert iv_snapshot['Requested model'] == 'auto'
assert iv_snapshot['pricing_model'] == 'black_scholes_merton'
assert 'volatility' not in iv_snapshot and volatility.value == 0
assert sum('text/html' in o.get('data', {}) for o in iv_output.outputs) == 1
volatility.value = 35
analytics_button.click()
assert last_analytics_response is not None and len(analytics_table) == 10
assert abs(last_analytics_response.result.implied_volatility.implied_volatility - .2) < 1e-12
assert analytics_snapshot['volatility'] == .35 and volatility.value == 35
assert sum('text/html' in o.get('data', {}) for o in analytics_output.outputs) == 2
volatility.value = 20
exercise.value = 'american'
assert 'black_scholes_merton' not in model.options
model.value = 'bjerksund_stensland_1993'
assert current_request().pricing_model == 'bjerksund_stensland_1993'
model.value = 'auto'
option_type.value = 'put'
strike.value = 105
expiry.value = 0.5
yield_input.value = 1
assert current_request().dividend_yield == 0.01
assert current_request().volatility == 0.2
price_button.click()
assert len(price_history) == 2
model.value = 'bjerksund_stensland_1993'
greeks_button.click()
assert last_greeks_response.metadata.request_id == 'fr-18e4e90129262501-0000000000000006'
assert greeks_snapshot['Style'] == 'american'
model.value = 'auto'
market_price.value = 7.6165316765775835
iv_button.click()
assert last_iv_response.metadata.request_id == 'fr-18e4e90129262501-0000000000000009'
assert last_iv_response.result.used_fallback is False
assert iv_snapshot['residual_basis'] == 'option_price'
assert iv_snapshot['market_price'] == market_price.value
volatility.value = 35
model.value = 'bjerksund_stensland_1993'
market_price.value = 7.5298454349124135
analytics_button.click()
assert last_analytics_response.result.implied_volatility.used_fallback is True
assert analytics_snapshot['Requested model'] == 'bjerksund_stensland_1993'
assert len(charge_history) == 9 and 'total incomplete' in usage_summary.value
show_usage()
assert len(charge_history) == 9
strike.value = 110
assert analytics_snapshot['strike'] == 105
assert iv_snapshot['strike'] == 105  # Later input edits must not relabel a solved result.
market_price.value = -1
iv_button.click()
assert last_iv_response is None and iv_snapshot is None
assert 'nonnegative' in str(iv_output.outputs)
assert not any(control.disabled for control in controls)
assert not greeks_button.disabled
assert price_history[0]['Style'] == 'european' and price_history[1]['Style'] == 'american'
assert price_history[0]['Strike'] == 100 and price_history[1]['Strike'] == 105
assert price_history[0]['CU charged'] == 'not reported'
spot.value = -1
price_button.click()
assert last_response is None and len(price_history) == 2
assert not price_button.disabled and not sweep_button.disabled
"""
    if filename == "regime/identification.ipynb":
        return (
            fixture_prices_source(prices)
            + """
assert loaded_closes is None and not analyze_button.disabled
use_history(closes, 'SPY')
assert len(loaded_closes) == 512 and not analyze_button.disabled
analyze_button.click()
assert last_response is not None and last_response.metadata.request_id == 'fixture-regime'
assert last_response.metadata.fcu_charged is None
assert not analyze_button.disabled
assert sum('text/html' in output.get('data', {}) for output in analysis_output.outputs) == 2
assert sum('image/png' in output.get('data', {}) for output in analysis_output.outputs) == 1
assert analyze_button.description == 'Show analysis'
analyze_button.click()  # Redraw the saved response; the server must still see one request.
ticker.value = 'AAPL'
assert loaded_closes is None and last_response is None and not analyze_button.disabled
"""
        )
    return ""


def fixture_prices_source(prices: list[float]) -> str:
    """An explicit synthetic-data cell for offline tests of the API cells."""
    return (
        "import pandas as pd\n"
        f"closes = pd.DataFrame({{'Close': {prices!r}}}, "
        f"index=pd.date_range('2020-01-01', periods={len(prices)}))\n"
    )


def execute(notebook_path: Path, fixture_paths: list[Path], notebook_root: Path) -> None:
    cases = [case for path in fixture_paths for case in json.loads(path.read_text())["cases"]]
    by_name = {case["name"]: case for case in cases}
    relative_path = notebook_path.relative_to(notebook_root).as_posix()
    expected = [by_name[name]["request"] for name in NOTEBOOK_CASES[relative_path]]
    received: list[dict[str, Any]] = []
    credential = "notebook-container-test-only"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            match = next(
                (
                    case
                    for case in cases
                    if case["request"] == body and case.get("path", "/v1/price") == self.path
                ),
                None,
            )
            if (
                self.path != (match or {}).get("path", "/v1/price")
                or self.headers.get("Authorization") != f"Bearer {credential}"
                or match is None
            ):
                self.send_error(422)
                return
            received.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(match["response"]).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        notebook = nbformat.read(notebook_path, as_version=4)  # type: ignore[no-untyped-call]
        nbformat.validate(notebook)
        with TemporaryDirectory() as working_directory:
            exercise = workspace_exercise(relative_path, by_name["regime"]["request"]["prices"])
            if exercise:
                notebook.cells.append(nbformat.v4.new_code_cell(exercise))  # type: ignore[no-untyped-call]
            executed = NotebookClient(
                notebook,
                timeout=60,
                kernel_name="python3",
                skip_cells_with_tag="requires-network",
                resources={"metadata": {"path": working_directory}},
            ).execute(
                env={
                    **os.environ,
                    "MORPHIQ_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "MORPHIQ_API_KEY": credential,
                }
            )
        if received != expected or credential in json.dumps(executed):
            raise RuntimeError("Unexpected requests or a credential in notebook output")
        print(f"{relative_path}: {len(received)} fixture requests; no credential in output.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", required=True, type=Path)
    parser.add_argument("--notebook-root", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    execute(args.notebook, args.fixtures, args.notebook_root)


if __name__ == "__main__":
    main()
