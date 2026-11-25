"""Price two synthetic options in one explicit batch, preserving per-item outcomes.

Run: python examples/batch_price.py
"""

import os
import sys
from getpass import getpass

from morphiq_sdk import (
    APIError,
    BatchFailure,
    BatchSuccess,
    Market,
    ModelSelection,
    MorphIQ,
    Option,
    OptionsBatchPriceRequest,
    OptionsPriceRequest,
    RateLimitError,
    ResponseError,
    TransportError,
)


def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # The order of this list defines the index used in each response outcome.
    request = OptionsBatchPriceRequest(
        items=[
            OptionsPriceRequest(
                option=Option(
                    type="call",
                    exercise_style="european",
                    strike=100.0,
                    time_to_expiry_years=1,
                ),
                market=Market(
                    spot=100.0,
                    risk_free_rate=0.05,
                    dividend_yield=0,
                ),
                volatility=0.2,
                model=ModelSelection(id="auto"),
            ),
            OptionsPriceRequest(
                option=Option(
                    type="put",
                    exercise_style="american",
                    strike=105.0,
                    time_to_expiry_years=0.5,
                ),
                market=Market(
                    spot=100.0,
                    risk_free_rate=0.05,
                    dividend_yield=0.01,
                ),
                volatility=0.2,
                model=ModelSelection(id="bjerksund_stensland_1993"),
            ),
        ]
    )

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        with MorphIQ(api_key=api_key) as client:
            response = client.options.batch_price(request)
    except APIError as error:
        if isinstance(error, RateLimitError):
            print("Rate limited. Retry-After:", error.retry_after, file=sys.stderr)
            print("No automatic retry or batch splitting.", file=sys.stderr)
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
        charged = error.metadata.charged_cu if error.metadata else None
        print(
            f"Commercial CU charged: {charged if charged is not None else 'not reported'}",
            file=sys.stderr,
        )
        raise SystemExit(
            f"Invalid response; request_id={error.request_id}. Charges may be unknown. No retry."
        ) from None

    for item in response.results:
        if isinstance(item, BatchSuccess):
            print(
                f"Item {item.index}: price={item.result.price}; "
                f"model={item.result.model.id} ({item.result.model.version})"
            )
        elif isinstance(item, BatchFailure):
            print(f"Item {item.index}: {item.error.code}: {item.error.detail}")
        else:
            # A newer outcome status this SDK does not know; keep it unhandled.
            print(f"Item {item.index}: unrecognized status {item.status}")
    # One metadata block and one commercial charge cover the entire batch.
    print(f"Request ID: {response.metadata.request_id}")
    for engine in response.metadata.engines or []:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    # The charge is metadata.billing.charged_cu; missing means unreported, not zero.
    billing = response.metadata.billing
    charged = billing.charged_cu if billing is not None else None
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    main()
