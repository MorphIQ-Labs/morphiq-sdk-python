"""Synthetic options.solve_scenario example. Sends one explicit calculation; no retries.

Run: python examples/option_solve.py
"""

import json
import os
from getpass import getpass

from morphiq_sdk import APIError, MorphIQ, OptionsSolveScenarioRequest


def main() -> None:
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")
    # Edit the synthetic inputs below. Currency and Greek units are the API's units.
    request = OptionsSolveScenarioRequest.model_validate(
        {
            "option": {
                "type": "call",
                "exercise_style": "european",
                "strike": 100.0,
                "time_to_expiry_years": 1.0,
            },
            "market": {"spot": 100.0, "risk_free_rate": 0.05, "dividend_yield": 0.0},
            "volatility": 0.2,
            "model": {"id": "black_scholes_merton"},
            "target": {"kind": "option_price", "value": 10.0},
            "coordinate": "spot",
            "lower": 50.0,
            "upper": 150.0,
        }
    )
    with MorphIQ(api_key=api_key) as client:
        try:
            response = client.options.solve_scenario(request)
        except APIError as error:
            print(f"HTTP {error.status_code}: {error.code}: {error.detail}")
            print("Request ID:", error.request_id)
            charge = error.metadata.charged_cu if error.metadata else None
            print("Commercial CU charged:", charge if charge is not None else "not reported")
            raise SystemExit(1) from None
    # Full boundaries, coverage, attribution and any partial errors remain visible.
    print(json.dumps(response.result.model_dump(mode="json", exclude_unset=True), indent=2))
    print("Request ID:", response.metadata.request_id)
    charge = response.metadata.charged_cu
    print("Commercial CU charged:", charge if charge is not None else "not reported")


if __name__ == "__main__":
    main()
