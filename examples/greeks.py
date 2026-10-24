"""Calculate the price and all ten Greeks for a synthetic European call.

Run: python examples/greeks.py
"""

import os
import sys
from getpass import getpass

from morphiq_sdk import APIError, GreeksRequest, MorphIQ, ResponseError, TransportError


def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # Synthetic European call; spot and strike use the same currency.
    request = GreeksRequest(
        exercise_style="european",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,  # Years from valuation.
        risk_free_rate=0.05,  # 5% annual rate.
        dividend_yield=0.0,
        volatility=0.20,  # 20% annual volatility.
        pricing_model="auto",
    )

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        with MorphIQ(api_key=api_key) as client:
            response = client.greeks(request)
    except APIError as error:
        print(f"HTTP {error.status_code}: {error.code}: {error.message}", file=sys.stderr)
        print(f"Request ID: {error.request_id}", file=sys.stderr)
        charged = error.metadata.fcu_charged if error.metadata else None
        print(
            f"Commercial CU charged: {charged if charged is not None else 'not reported'}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except TransportError:
        # Includes timeouts. The service may already have committed a charge.
        raise SystemExit(
            "No complete response; execution and charges may be unknown. No retry."
        ) from None
    except ResponseError as error:
        raise SystemExit(
            f"Invalid response; request_id={error.request_id}. Charges may be unknown. No retry."
        ) from None

    print(f"Price: {response.result.price}")
    # API time derivatives are per year; vega/rho use unit volatility/rate.
    print("Greeks (raw API units):")
    for name in (
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "vanna",
        "volga",
        "charm",
        "veta",
        "color",
    ):
        print(f"  {name}: {getattr(response.result.greeks, name)}")
    print(f"Model: {response.result.pricing_model} ({response.result.model_version})")
    print(f"Request ID: {response.metadata.request_id}")
    for engine in response.metadata.engines:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    # Missing commercial CU is unreported, not zero.
    charged = response.metadata.fcu_charged
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    main()
