"""Compare five synthetic spot scenarios as tables; three sequential requests.

Install: python -m pip install -e '.[pandas]'
Run: python -m examples.tabular_price
Set MORPHIQ_API_KEY first, or enter it at the masked prompt.
"""

import os
from getpass import getpass

from morphiq_sdk import MorphIQ, MorphIQError, PriceRequest, RateLimitError
from morphiq_sdk.pandas import workflow_to_frames


def main() -> None:
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
    labels = [f"spot-{request.spot:g}" for request in requests]

    with MorphIQ(api_key=api_key) as client:
        workflow = client.price_workflow(requests, chunk_size=2)
        # Validate labels and the optional dependency before making paid requests.
        workflow_to_frames(workflow, identifiers=labels)
        print("Planned HTTP requests:", workflow.planned_chunk_count)
        try:
            workflow.run()
        except RateLimitError as error:
            print("Stopped on HTTP 429. Retry-After:", error.retry_after)
        except MorphIQError as error:
            print("Stopped:", error)
        finally:
            frames = workflow_to_frames(workflow, identifiers=labels)
            # Select result columns when available; failed/unattempted rows remain visible.
            columns = ["index", "identifier", "status"]
            columns += [name for name in ("result.price", "error.code") if name in frames.results]
            print(frames.results[columns].to_string(index=False))
            # Charges belong to requests, never to individual option rows.
            print(
                frames.requests[["request_index", "status", "request_id", "fcu_charged"]].to_string(
                    index=False
                )
            )
            print("Reported CU subtotal:", frames.reported_fcu_charged)
            print("Attempts with unknown CU:", frames.unknown_charge_count)
            total = frames.total_fcu_charged
            print("Whole-workflow CU:", total if total is not None else "unknown or incomplete")
        if workflow.state != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
