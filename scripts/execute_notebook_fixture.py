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
    "start-here.ipynb": (),
    "pricing/options.ipynb": (
        "european",
        "greeks-european",
        "iv-european",
        "american",
        "greeks-american",
        "iv-american",
    ),
    "regime/identification.ipynb": ("regime",),
}


def workspace_exercise(filename: str, prices: list[float]) -> str:
    """Exercise real widget actions with explicit synthetic market data in offline checks."""
    if filename == "pricing/options.ipynb":
        return """
assert price_history == []
assert sweep_results == []
spot.value = 120
use_yahoo_close(pd.DataFrame({'Close': [100.0]}, index=pd.to_datetime(['2026-01-02'])), 'SPY')
assert spot.value == 100.0 and 'SPY' in spot_source
price_button.click()
assert len(price_history) == 1 and last_response.result.price == 10.450583572185538
greeks_button.click()
assert last_greeks_response.metadata.request_id == 'fixture-greeks-european'
assert len(greeks_table) == 10 and greeks_table.loc['vega', 'Value'] == 37.52403469169381
assert greeks_table.loc['theta', 'Value'] == -6.4140275464382
assert sum('text/html' in o.get('data', {}) for o in greeks_output.outputs) == 2
assert greeks_snapshot['Style'] == 'european' and greeks_snapshot['CU charged'] == 'not reported'
market_price.value = 10.450583572185538
volatility.value = 0  # Solving IV must not validate an unused volatility assumption.
iv_button.click()
assert last_iv_response.metadata.request_id == 'fixture-iv-european'
assert abs(last_iv_response.result.implied_volatility - 0.2) < 1e-12
assert last_iv_response.result.used_fallback is False
assert iv_snapshot['residual_basis'] == 'forward_normalised_price'
assert iv_snapshot['Requested model'] == 'auto'
assert iv_snapshot['pricing_model'] == 'black_scholes_merton'
assert 'volatility' not in iv_snapshot and volatility.value == 0
assert sum('text/html' in o.get('data', {}) for o in iv_output.outputs) == 1
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
greeks_button.click()
assert last_greeks_response.metadata.request_id == 'fixture-greeks-american'
assert greeks_snapshot['Style'] == 'american'
market_price.value = 7.584143004464017
iv_button.click()
assert last_iv_response.metadata.request_id == 'fixture-iv-american'
assert last_iv_response.result.used_fallback is True
assert iv_snapshot['residual_basis'] == 'option_price'
assert iv_snapshot['market_price'] == market_price.value
strike.value = 110
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
