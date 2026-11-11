"""Quote a +5 underlying move or a 3×3 grid; --max-cu explicitly executes once.

Run: python examples/scenario_evaluate.py --mode point --model bsm --max-cu 2
"""

import argparse
import sys

from morphiq_sdk import (
    APIError,
    MorphIQ,
    PriceRequest,
    ResponseError,
    ScenarioPoint,
    ScenarioPosition,
    ScenarioRequest,
    TransportError,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["point", "grid"], default="point")
    parser.add_argument("--model", choices=["bsm", "bs1993"], default="bsm")
    parser.add_argument(
        "--max-cu", type=int, help="execute once with this ceiling; otherwise quote only"
    )
    args = parser.parse_args()
    if args.max_cu is not None and not 0 <= args.max_cu <= 2**64 - 1:
        parser.error("--max-cu must be an unsigned 64-bit integer")
    contract = PriceRequest(
        exercise_style="american" if args.model == "bs1993" else "european",
        pricing_model="bjerksund_stensland_1993"
        if args.model == "bs1993"
        else "black_scholes_merton",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        volatility=0.20,
    )
    points = [ScenarioPoint(spot_change=5.0)]
    if args.mode == "grid":
        points = [
            ScenarioPoint(spot=spot, volatility=vol)
            for spot in (95.0, 100.0, 105.0)
            for vol in (0.15, 0.20, 0.25)
        ]
    request = ScenarioRequest(
        contract=contract,
        scenarios=points,
        position=ScenarioPosition(quantity=1.0, multiplier=100.0),
    )
    try:
        with MorphIQ() as client:
            quote = client.quote(request)
            print("Quoted CU:", quote.quote.total_fcu)
            if args.max_cu is None:
                return
            if quote.quote.total_fcu > args.max_cu:
                parser.error("Quote exceeds --max-cu; no execution submitted")
            response = client.evaluate_scenarios(request, max_cu=args.max_cu)
    except APIError as error:
        charged = error.metadata.fcu_charged if error.metadata else None
        print(
            f"HTTP {error.status_code}: {error.code}; request_id={error.request_id}",
            file=sys.stderr,
        )
        print(
            "Commercial CU charged:",
            charged if charged is not None else "not reported",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (ResponseError, TransportError) as error:
        raise SystemExit(f"{error}; inspect receipt evidence. No retry.") from None
    # Includes ordered successes/errors and one request-level commercial receipt.
    print(response.model_dump_json(indent=2, exclude_unset=True))


if __name__ == "__main__":
    main()
