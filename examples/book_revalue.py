"""Synthetic books.revalue example. Sends one explicit calculation; no retries.

Run: python examples/book_revalue.py
"""

import json
import os
from getpass import getpass

from morphiq_sdk import APIError, BooksRevalueRequest, MorphIQ


def main() -> None:
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")
    # Edit the synthetic inputs below. Currency and Greek units are the API's units.
    request = BooksRevalueRequest.model_validate(
        {
            "currency": "USD",
            "markets": {"SPY": {"spot": 100.0, "risk_free_rate": 0.05, "dividend_yield": 0.0}},
            "books": [
                {
                    "id": "spread",
                    "positions": [
                        {
                            "id": "long-call",
                            "underlying": "SPY",
                            "quantity": 1.0,
                            "multiplier": 100.0,
                            "option": {
                                "type": "call",
                                "exercise_style": "european",
                                "strike": 100.0,
                                "time_to_expiry_years": 1.0,
                            },
                            "volatility": 0.2,
                            "model": {"id": "black_scholes_merton"},
                        },
                        {
                            "id": "short-call",
                            "underlying": "SPY",
                            "quantity": -1.0,
                            "multiplier": 100.0,
                            "option": {
                                "type": "call",
                                "exercise_style": "european",
                                "strike": 110.0,
                                "time_to_expiry_years": 1.0,
                            },
                            "volatility": 0.2,
                            "model": {"id": "black_scholes_merton"},
                        },
                    ],
                    "strategies": [
                        {"id": "vertical", "position_ids": ["long-call", "short-call"]},
                        {"id": "long-leg", "position_ids": ["long-call"]},
                    ],
                }
            ],
            "scenario": {
                "name": "up-and-steeper",
                "shocks": [
                    {"kind": "spot_relative", "relative": 0.05},
                    {"kind": "parallel_vol", "shift": 0.01},
                ],
            },
        }
    )
    with MorphIQ(api_key=api_key) as client:
        try:
            response = client.books.revalue(request)
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
