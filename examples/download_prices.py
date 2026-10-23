"""Download Yahoo daily closes for the regime examples.

Install: python -m pip install -e '.[market-data]'
Run: python examples/download_prices.py
"""

from datetime import date, timedelta

import yfinance as yf


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
    closes.to_csv("prices.csv", index_label="Date")
    print(f"{ticker}: saved {len(closes)} split-adjusted daily closes to prices.csv")
    print(closes.tail().to_string())


if __name__ == "__main__":
    main()
