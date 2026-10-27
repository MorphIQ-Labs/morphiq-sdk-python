"""Two non-billable utility requests; --execute adds one capped pricing request."""

import argparse

from morphiq_sdk import MorphIQ, PriceRequest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Execute once with the quoted CU ceiling"
    )
    args = parser.parse_args()
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
        quote = client.quote(request)
        print(quote.model_dump_json(indent=2))
        if args.execute:
            response = client.price(request, max_cu=quote.quote.total_fcu)
            print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
