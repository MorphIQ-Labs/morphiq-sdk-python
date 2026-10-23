"""Identify a regime directly from Yahoo daily closes.

Install: python -m pip install -e '.[market-data]'
Set MORPHIQ_API_KEY, then run: python examples/identify_regime.py
"""

import os
import sys
from datetime import date, timedelta
from getpass import getpass

import yfinance as yf

from morphiq_sdk import APIError, MorphIQ, RegimeRequest, ResponseError, TransportError


def main() -> None:
    ticker = input("Ticker symbol [SPY]: ").strip().upper() or "SPY"
    # End is exclusive: omit today's potentially incomplete daily bar.
    end = date.today()
    history = yf.download(
        ticker,
        start=end - timedelta(days=3 * 366),
        end=end,
        interval="1d",
        auto_adjust=False,  # Close is split-adjusted; Adj Close also adjusts dividends.
        keepna=True,
        multi_level_index=False,
        progress=False,
        threads=False,
    )
    if history is None or history.empty:
        raise SystemExit("Yahoo returned no price history.")
    closes = history[["Close"]].tail(512)
    if len(closes) < 512 or closes["Close"].isna().any() or (closes["Close"] <= 0).any():
        raise SystemExit("Need 512 consecutive valid daily closes; no rows were filled or dropped.")
    if not closes.index.is_monotonic_increasing or not closes.index.is_unique:
        raise SystemExit("Expected unique daily dates ordered oldest to newest.")
    print(f"{ticker}: {len(closes)} split-adjusted daily closes")
    print(closes.tail().to_string())

    # Submit the downloaded prices directly to MorphIQ.
    api_key = os.environ.get("MORPHIQ_API_KEY") or getpass("MorphIQ API key: ")
    request = RegimeRequest(prices=closes["Close"].tolist())
    # Daily date labels do not establish exact close timestamps; omit as_of.
    print(f"Sending {len(request.prices)} closes: {closes.index[0]} through {closes.index[-1]}")

    try:
        # The client uses https://api.morphiqlabs.com and closes its connection pool here.
        with MorphIQ(api_key=api_key) as client:
            response = client.regime(request)
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
    main()
