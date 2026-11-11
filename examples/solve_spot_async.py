"""Quote a synthetic spot-target solve; add --max-cu to explicitly execute once.

Requires the scenario API deployment and the account's approved solve schedule.
Examples: python examples/solve_spot_async.py --model bsm --max-cu 100
          python examples/solve_spot_async.py --model bs1993 --target-pnl 500 --max-cu 200
"""

import argparse
import asyncio
import sys

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    PriceRequest,
    ResponseError,
    ScenarioOptionPriceTarget,
    ScenarioPosition,
    ScenarioPositionPnlTarget,
    ScenarioSolveTarget,
    ScenarioSpotSolveRequest,
    TransportError,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["bsm", "bs1993"], default="bsm")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--target-price", type=float, default=15.0)
    targets.add_argument("--target-pnl", type=float)
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
    target: ScenarioSolveTarget = ScenarioOptionPriceTarget(
        kind="option_price", value=args.target_price
    )
    if args.target_pnl is not None:
        target = ScenarioPositionPnlTarget(
            kind="position_pnl",
            value=args.target_pnl,
            position=ScenarioPosition(quantity=2.0, multiplier=100.0),
        )
    request = ScenarioSpotSolveRequest(
        contract=contract, target=target, min_spot=50.0, max_spot=150.0
    )
    try:
        async with AsyncMorphIQ() as client:
            quote = await client.quote(request)
            print("Quoted CU:", quote.quote.total_fcu)
            if args.max_cu is None:
                return
            if quote.quote.total_fcu > args.max_cu:
                parser.error("Quote exceeds --max-cu; no execution submitted")
            response = await client.solve_spot(request, max_cu=args.max_cu)
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
    # Preserve every boundary, sampled interval, region and unresolved cell.
    # An empty boundary list is not a proof of global nonexistence.
    print(response.model_dump_json(indent=2, exclude_unset=True))


if __name__ == "__main__":
    asyncio.run(main())
