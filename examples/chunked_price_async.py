"""Price five synthetic spot scenarios in three sequential batch requests.

Run: python -m examples.chunked_price_async
Set MORPHIQ_API_KEY first, or enter it at the masked prompt.
"""

import asyncio
import os
from getpass import getpass

from morphiq_sdk import AsyncMorphIQ, MorphIQError, PriceRequest, RateLimitError


async def main() -> None:
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")
    requests = [
        PriceRequest(
            exercise_style="european",
            option_type="call",
            spot=spot,
            strike=100.0,
            time_to_expiry_years=1.0,
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        for spot in (80.0, 85.0, 90.0, 95.0, 100.0)
    ]

    async with AsyncMorphIQ(api_key=api_key) as client:
        # Choose a size allowed for your account. Two is illustrative, not a plan limit.
        workflow = client.price_workflow(requests, chunk_size=2)
        print("Planned HTTP requests:", workflow.planned_chunk_count)
        try:
            await workflow.run()
        except RateLimitError as error:
            print("Stopped on HTTP 429. Retry-After:", error.retry_after)
        except MorphIQError as error:
            print("Stopped:", error)
        finally:
            # Also runs on interruption; preserve partial results and unknown charges.
            for attempt in workflow.attempts:
                print(f"Input range [{attempt.start}, {attempt.stop}): {attempt.request_id}")
                charge = attempt.fcu_charged
                print("Chunk CU:", charge if charge is not None else "not reported")
                if attempt.response is None:
                    print("No validated results for this chunk; do not replay automatically.")
                    continue
                for item in attempt.response.results:
                    index = attempt.start + item.index
                    if item.status == "success":
                        print(
                            f"Item {index}: spot={requests[index].spot}; price={item.result.price}"
                        )
                        print("Model:", item.result.pricing_model, item.result.model_version)
                    else:
                        print(f"Item {index}: {item.error.code}: {item.error.message}")
                for engine in attempt.response.metadata.engines:
                    print("Engine:", engine.name, engine.version, engine.revision)
            print("Workflow state:", workflow.state)
            print("Reported CU subtotal:", workflow.reported_fcu_charged)
            print("Attempts with unknown CU:", workflow.unknown_charge_count)
            total = workflow.total_fcu_charged
            print("Whole-workflow CU:", total if total is not None else "unknown or incomplete")
            print("Unattempted input ranges:", workflow.unattempted_ranges)
        if workflow.state != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
