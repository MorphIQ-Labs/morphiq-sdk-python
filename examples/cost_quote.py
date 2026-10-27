"""Two non-billable utility requests; --execute adds one capped pricing request."""

import argparse
import sys

from morphiq_sdk import (
    APIError,
    BatchPriceRequest,
    BatchPriceResponse,
    MorphIQ,
    PriceRequest,
    PriceResponse,
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
    request = PriceRequest(
        exercise_style="european",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        volatility=0.2,
    )
    with MorphIQ() as client:
        schedule = client.cost_schedule(operation="price")
        print(schedule.model_dump_json(indent=2))
        batch = BatchPriceRequest(requests=[request, request])
        quote = client.quote(batch if args.batch else request)
        print(quote.model_dump_json(indent=2))
        print("Prospective execution CU:", quote.quote.total_fcu)
        print("Utility CU charged:", quote.metadata.fcu_charged)
        if args.execute:
            ceiling = quote.quote.total_fcu if args.max_cu is None else args.max_cu
            response: PriceResponse | BatchPriceResponse
            try:
                if args.batch:
                    response = client.price_batch(batch, max_cu=ceiling)
                else:
                    response = client.price(request, max_cu=ceiling)
            except APIError as error:
                print(f"HTTP {error.status_code}: {error.code}", file=sys.stderr)
                print("Request ID:", error.request_id, file=sys.stderr)
                quoted = error.metadata.fcu_quoted if error.metadata else None
                charged = error.metadata.fcu_charged if error.metadata else None
                print(
                    "Execution quote CU:",
                    quoted if quoted is not None else "not reported",
                    file=sys.stderr,
                )
                print(
                    "CU charged:",
                    charged if charged is not None else "not reported",
                    file=sys.stderr,
                )
                print("No retry or automatic ceiling increase.", file=sys.stderr)
                raise SystemExit(1) from None
            print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
