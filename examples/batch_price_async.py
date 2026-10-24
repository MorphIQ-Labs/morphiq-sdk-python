"""Price two synthetic options in one explicit batch, preserving per-item outcomes.

Run: python examples/batch_price_async.py
"""

import asyncio
import os
import sys
from getpass import getpass

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchPriceRequest,
    PriceRequest,
    RateLimitError,
    ResponseError,
    TransportError,
)


async def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # The order of this list defines the index used in each response outcome.
    request = BatchPriceRequest(
        requests=[
            PriceRequest(
                exercise_style="european",
                pricing_model="auto",
                option_type="call",
                spot=100.0,
                strike=100.0,
                time_to_expiry_years=1,
                risk_free_rate=0.05,
                dividend_yield=0,
                volatility=0.2,
            ),
            PriceRequest(
                exercise_style="american",
                pricing_model="auto",
                option_type="put",
                spot=100.0,
                strike=105.0,
                time_to_expiry_years=0.5,
                risk_free_rate=0.05,
                dividend_yield=0.01,
                volatility=0.2,
            ),
        ]
    )

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        async with AsyncMorphIQ(api_key=api_key) as client:
            response = await client.price_batch(request)
    except APIError as error:
        if isinstance(error, RateLimitError):
            print("Rate limited. Retry-After:", error.retry_after, file=sys.stderr)
            print("No automatic retry or batch splitting.", file=sys.stderr)
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

    for item in response.results:
        if item.status == "success":
            print(
                f"Item {item.index}: price={item.result.price}; "
                f"model={item.result.pricing_model} ({item.result.model_version})"
            )
        else:
            print(f"Item {item.index}: {item.error.code}: {item.error.message}")
    # One metadata block and one commercial charge cover the entire batch.
    print(f"Request ID: {response.metadata.request_id}")
    for engine in response.metadata.engines:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    # Missing commercial CU is unreported, not zero.
    charged = response.metadata.fcu_charged
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    asyncio.run(main())
