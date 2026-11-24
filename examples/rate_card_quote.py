"""Read the rate card and quote one request (two non-billable utility requests).

--execute adds one pricing request capped at the quoted CU.
"""

import argparse
import sys

from morphiq_sdk import (
    APIError,
    Market,
    ModelSelection,
    MorphIQ,
    Option,
    OptionsBatchPriceRequest,
    OptionsBatchPriceResponse,
    OptionsPriceRequest,
    OptionsPriceResponse,
    operation_id,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Execute once with the quoted CU ceiling"
    )
    parser.add_argument("--batch", action="store_true", help="Quote two synthetic contracts")
    parser.add_argument(
        "--max-cu", type=int, help="Explicit execution ceiling; defaults to the quote"
    )
    args = parser.parse_args()
    if args.max_cu is not None and not 0 <= args.max_cu <= 2**64 - 1:
        parser.error("--max-cu must be an unsigned 64-bit integer")
    if args.max_cu is not None and not args.execute:
        parser.error("--max-cu requires --execute")
    request = OptionsPriceRequest(
        option=Option(
            type="call",
            exercise_style="european",
            strike=100.0,
            time_to_expiry_years=1.0,
        ),
        market=Market(
            spot=100.0,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        ),
        volatility=0.2,
        model=ModelSelection(id="auto"),
    )
    with MorphIQ() as client:
        batch = OptionsBatchPriceRequest(items=[request, request])
        quoted = batch if args.batch else request
        try:
            # Rate classes group operations; options.price and options.batch_price use "price".
            rate_card = client.rate_card.get(rate_class="price")
            print(rate_card.model_dump_json(indent=2, exclude_unset=True))
            # The quote names the canonical operation id the request would execute.
            print("Quoting operation:", operation_id(quoted))
            quote = client.rate_card.quote(quoted)
        except APIError as error:
            # Utility requests execute nothing and charge no CUs.
            print(f"HTTP {error.status_code}: {error.code}: {error.detail}", file=sys.stderr)
            print("Request ID:", error.request_id, file=sys.stderr)
            raise SystemExit(1) from None
        print(quote.model_dump_json(indent=2, exclude_unset=True))
        print("Prospective execution CU:", quote.quote.total_cu)
        billing = quote.metadata.billing
        utility_charge = billing.charged_cu if billing is not None else None
        print(
            "Utility CU charged:",
            utility_charge if utility_charge is not None else "not reported",
        )
        if args.execute:
            ceiling = quote.quote.total_cu if args.max_cu is None else args.max_cu
            response: OptionsPriceResponse | OptionsBatchPriceResponse
            try:
                if args.batch:
                    response = client.options.batch_price(batch, max_cu=ceiling)
                else:
                    response = client.options.price(request, max_cu=ceiling)
            except APIError as error:
                print(f"HTTP {error.status_code}: {error.code}", file=sys.stderr)
                print("Request ID:", error.request_id, file=sys.stderr)
                billing = error.metadata.billing if error.metadata else None
                quoted_cu = billing.quoted_cu if billing is not None else None
                charged = billing.charged_cu if billing is not None else None
                print(
                    "Execution quote CU:",
                    quoted_cu if quoted_cu is not None else "not reported",
                    file=sys.stderr,
                )
                print(
                    "CU charged:",
                    charged if charged is not None else "not reported",
                    file=sys.stderr,
                )
                print("No retry or automatic ceiling increase.", file=sys.stderr)
                raise SystemExit(1) from None
            print(response.model_dump_json(indent=2, exclude_unset=True))


if __name__ == "__main__":
    main()
