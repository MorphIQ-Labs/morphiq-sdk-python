"""Price European and American options asynchronously.

Run: python examples/price_async.py
"""

import asyncio
import os
import sys
from getpass import getpass

from morphiq_sdk import APIError, AsyncMorphIQ, PriceRequest, ResponseError, TransportError


async def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # Package each option as its own request; this is two sequential API calls.
    requests = [
        PriceRequest(
            exercise_style="european",
            option_type="call",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,  # Years from valuation.
            risk_free_rate=0.05,  # 5% annual rate.
            dividend_yield=0.0,
            volatility=0.20,  # 20% annual volatility.
            pricing_model="auto",
        ),
        PriceRequest(
            exercise_style="american",
            option_type="put",
            spot=100.0,
            strike=105.0,
            time_to_expiry_years=0.5,  # Years from valuation.
            risk_free_rate=0.05,  # 5% annual rate.
            dividend_yield=0.01,
            volatility=0.20,  # 20% annual volatility.
            pricing_model="auto",
        ),
    ]

    try:
        async with AsyncMorphIQ(api_key=api_key) as client:
            for request in requests:
                response = await client.price(request)
                print(f"{response.result.exercise_style} {response.result.option_type}")
                print(f"Price: {response.result.price}")
                print(f"Model: {response.result.pricing_model} ({response.result.model_version})")
                print(f"Request ID: {response.metadata.request_id}")
                for engine in response.metadata.engines:
                    print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
                # Missing commercial CU is unreported, not zero.
                charged = response.metadata.fcu_charged
                print("Commercial CU charged:", charged if charged is not None else "not reported")
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


if __name__ == "__main__":
    asyncio.run(main())
