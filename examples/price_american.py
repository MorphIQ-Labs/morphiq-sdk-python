"""Price a synthetic American put.

Run: python examples/price_american.py
"""

import os
import sys
from getpass import getpass

from morphiq_sdk import (
    APIError,
    Market,
    ModelSelection,
    MorphIQ,
    Option,
    OptionsPriceRequest,
    ResponseError,
    TransportError,
)


def main() -> None:
    # Set MORPHIQ_API_KEY in your environment, or enter it at the masked prompt.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # Synthetic American put; spot and strike use the same currency.
    request = OptionsPriceRequest(
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
    )

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        with MorphIQ(api_key=api_key) as client:
            response = client.options.price(request)
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

    print(f"Price: {response.result.price}")
    print(f"Model: {response.result.model.id} ({response.result.model.version})")
    print(f"Request ID: {response.metadata.request_id}")
    for engine in response.metadata.engines or []:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    # The charge is metadata.billing.charged_cu; missing means unreported, not zero.
    billing = response.metadata.billing
    charged = billing.charged_cu if billing is not None else None
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    main()
