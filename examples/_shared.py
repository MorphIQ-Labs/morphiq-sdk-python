"""Synthetic pricing inputs and presentation shared by scripts and the notebook."""

import json
import os
from getpass import getpass

from morphiq_sdk import PriceRequest, PriceResponse


def configure() -> None:
    """Read settings from the environment, or prompt without displaying the key."""
    if not os.environ.get("MORPHIQ_API_BASE_URL"):
        os.environ["MORPHIQ_API_BASE_URL"] = input("Your API base URL: ").strip()
    if not os.environ.get("MORPHIQ_API_KEY"):
        os.environ["MORPHIQ_API_KEY"] = getpass("Your API key (hidden): ").strip()


def european_call() -> PriceRequest:
    """Synthetic one-year European call: 20% volatility and 5% interest."""
    return PriceRequest(
        exercise_style="european",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        volatility=0.20,
    )


def american_put() -> PriceRequest:
    """Synthetic half-year American put with a 1% continuous dividend yield."""
    return PriceRequest(
        exercise_style="american",
        option_type="put",
        spot=100.0,
        strike=105.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        volatility=0.20,
    )


def show_price(response: PriceResponse) -> None:
    """Display server results; an absent commercial charge is not zero."""
    print(
        json.dumps(
            {
                "price": response.result.price,
                "exercise_style": response.result.exercise_style,
                "option_type": response.result.option_type,
                "pricing_model": response.result.pricing_model,
                "model_version": response.result.model_version,
                "request_id": response.metadata.request_id,
                "engines": [engine.model_dump() for engine in response.metadata.engines],
                "commercial_cu_charged": (
                    response.metadata.fcu_charged
                    if response.metadata.fcu_charged is not None
                    else "not reported (for example, open local development)"
                ),
            },
            indent=2,
        )
    )
