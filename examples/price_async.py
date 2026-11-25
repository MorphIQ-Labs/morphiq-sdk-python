"""Price European and American options asynchronously.

Run: python examples/price_async.py
"""

import asyncio
import os
import sys
from getpass import getpass

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    Market,
    ModelSelection,
    Option,
    OptionsPriceRequest,
    ResponseError,
    TransportError,
)


async def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # Package each option as its own request; this is two sequential API calls.
    requests = [
        OptionsPriceRequest(
            option=Option(
                type="call",
                exercise_style="european",
                strike=100.0,
                time_to_expiry_years=1.0,  # Years from valuation.
            ),
            market=Market(
                spot=100.0,
                risk_free_rate=0.05,  # 5% annual rate.
                dividend_yield=0.0,
            ),
            volatility=0.20,  # 20% annual volatility.
            model=ModelSelection(id="auto"),
        ),
        OptionsPriceRequest(
            option=Option(
                type="put",
                exercise_style="american",
                strike=105.0,
                time_to_expiry_years=0.5,  # Years from valuation.
            ),
            market=Market(
                spot=100.0,
                risk_free_rate=0.05,  # 5% annual rate.
                dividend_yield=0.01,
            ),
            volatility=0.20,  # 20% annual volatility.
            model=ModelSelection(id="auto"),
        ),
    ]

    try:
        async with AsyncMorphIQ(api_key=api_key) as client:
            for request in requests:
                response = await client.options.price(request)
                # Results name the resolved model, not the request's option terms.
                print(f"{request.option.exercise_style} {request.option.type}")
                print(f"Price: {response.result.price}")
                print(f"Model: {response.result.model.id} ({response.result.model.version})")
                print(f"Request ID: {response.metadata.request_id}")
                for engine in response.metadata.engines or []:
                    print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
                # The charge is metadata.billing.charged_cu; missing means unreported, not zero.
                billing = response.metadata.billing
                charged = billing.charged_cu if billing is not None else None
                print("Commercial CU charged:", charged if charged is not None else "not reported")
    except APIError as error:
        print(f"HTTP {error.status_code}: {error.code}: {error.detail}", file=sys.stderr)
        print(f"Request ID: {error.request_id}", file=sys.stderr)
        charged = error.metadata.charged_cu if error.metadata else None
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
