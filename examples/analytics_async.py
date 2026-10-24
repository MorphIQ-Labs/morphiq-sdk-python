"""Solve IV and calculate price and Greeks for a synthetic European call.

Run: python examples/analytics_async.py
"""

import asyncio
import os
import sys
from getpass import getpass

from morphiq_sdk import (
    AnalyticsRequest,
    APIError,
    AsyncMorphIQ,
    ResponseError,
    TransportError,
)


async def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # Synthetic European call; spot and strike use the same currency.
    request = AnalyticsRequest(
        exercise_style="european",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,  # Years from valuation.
        risk_free_rate=0.05,  # 5% annual rate.
        dividend_yield=0.0,
        volatility=0.35,  # Required wire field; ignored when a market premium is supplied.
        market_price=10.450583572185538,  # Synthetic per-share option premium.
        pricing_model="auto",
    )

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        async with AsyncMorphIQ(api_key=api_key) as client:
            response = await client.analytics(request)
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
        charged = error.metadata.fcu_charged if error.metadata else None
        print(
            f"Commercial CU charged: {charged if charged is not None else 'not reported'}",
            file=sys.stderr,
        )
        raise SystemExit(
            f"Invalid response; request_id={error.request_id}. Charges may be unknown. No retry."
        ) from None

    print(f"Price: {response.result.price}")
    solved = response.result.implied_volatility
    if solved is not None:
        print(f"Implied volatility: {solved.implied_volatility}")
        print(f"Iterations: {solved.iterations}; used fallback: {solved.used_fallback}")
        print(f"Residual: {solved.residual}; basis: {solved.residual_basis}")
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
    # The combined response reports one charge, not one charge per result component.
    print(f"Model: {response.result.pricing_model} ({response.result.model_version})")
    print(f"Request ID: {response.metadata.request_id}")
    for engine in response.metadata.engines:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    # Missing commercial CU is unreported, not zero.
    charged = response.metadata.fcu_charged
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    asyncio.run(main())
