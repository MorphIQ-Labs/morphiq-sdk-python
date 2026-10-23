"""Identify a regime from Yahoo daily closes in prices.csv.

First run python examples/download_prices.py. Set MORPHIQ_API_KEY,
then run: python examples/identify_regime_async.py
"""

import asyncio
import csv
import os
import sys
from datetime import date
from getpass import getpass
from pathlib import Path

from morphiq_sdk import APIError, AsyncMorphIQ, RegimeRequest, ResponseError, TransportError


async def main() -> None:
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")

    # download_prices.py saves Yahoo's split-adjusted Close, without dividend adjustment.
    # The CSV keeps dates and prices visible and can be reused without downloading again.
    with Path("prices.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    dates = [date.fromisoformat(row["Date"]) for row in rows]
    if dates != sorted(set(dates)):
        raise SystemExit("CSV dates must be unique and ordered oldest to newest.")
    prices = [float(row["Close"]) for row in rows]
    request = RegimeRequest(prices=prices)
    # Daily dates are not exact close timestamps, so leave as_of unspecified.
    # If known, pass the final observation's RFC 3339 timestamp with its UTC offset.
    print(f"Sending {len(prices)} closes: {dates[0]} through {dates[-1]}")

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        async with AsyncMorphIQ(api_key=api_key) as client:
            response = await client.regime(request)
    except APIError as error:
        print(f"HTTP {error.status_code}: {error.code}: {error.message}", file=sys.stderr)
        print(f"Request ID: {error.request_id}", file=sys.stderr)
        charged = error.metadata.fcu_charged if error.metadata else None
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

    # Each head has its own status. Unresolved is an available decision label;
    # not_applicable and unavailable instead have a reason and no prediction.
    for name, head in (
        ("Decision", response.result.decision),
        ("Direction", response.result.direction),
        ("State", response.result.state),
    ):
        print(f"{name}: {head.status} (target: {head.basis.target})")
        if head.status == "available":
            print(f"  Label: {head.prediction.label}")
            for score in head.prediction.scores:
                print(f"  {score.label}: {score.value}")
        else:
            print(f"  Reason: {head.reason_code}")

    # Scores are uncalibrated softmax values, not probabilities or p-values.
    # Do not multiply heads. LOWER_VOL/HIGHER_VOL are relative model states,
    # not historical volatility levels or price directions.
    print("Score kind:", response.result.score_contract.kind)
    metadata = response.metadata
    consumed = metadata.consumed_price_range
    print("Prices received:", metadata.received_price_count)
    print("Window size:", metadata.window_price_count)
    print(f"Consumed prices: [{consumed.start_index}, {consumed.end_index_exclusive})")
    print(f"Selected input price index: {metadata.input_price_index}; as_of: {metadata.as_of}")
    print(f"Model: {metadata.provenance.model_id} ({metadata.provenance.model_status})")
    print("Model SHA-256:", metadata.provenance.model_sha256)
    print("Reference teacher executed:", metadata.provenance.teacher_executed)
    print("Request ID:", metadata.request_id)
    for engine in metadata.engines:
        print(f"Engine: {engine.name} {engine.version} ({engine.revision})")
    charged = metadata.fcu_charged
    print("Commercial CU charged:", charged if charged is not None else "not reported")


if __name__ == "__main__":
    asyncio.run(main())
