"""Optional Yahoo implementation of the SDK's price-provider interface."""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from morphiq_sdk.market_data import PriceBar, PriceHistory, PriceInterval

__all__ = ["YahooPriceProvider"]


class YahooPriceProvider:
    """Fetch split-adjusted regular-session closes, without dividend adjustment.

    Install morphiq-sdk[market-data] to fetch from Yahoo. The optional downloader
    argument accepts a yfinance.download-compatible callable for offline replay.
    Yahoo's availability limits apply; this adapter does not split requests,
    retry, fill gaps, or silently shorten the requested date range.
    """

    def __init__(self, *, downloader: Callable[..., Any] | None = None) -> None:
        self._downloader = downloader

    def history(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: PriceInterval = "1d",
    ) -> PriceHistory:
        symbol = symbol.strip().upper()
        if not symbol or any(character.isspace() for character in symbol) or "," in symbol:
            raise ValueError("Provide one Yahoo symbol")
        if type(start) is not date or type(end) is not date or start >= end:
            raise ValueError("Use date bounds with start before the exclusive end")
        if interval not in ("1d", "1m", "5m", "15m", "30m", "60m"):
            raise ValueError("Unsupported Yahoo price interval")
        download = self._downloader
        if download is None:
            try:
                import yfinance
            except ImportError as error:
                raise ImportError(
                    "Yahoo downloads require the optional extra: "
                    "pip install 'morphiq-sdk[market-data]'"
                ) from error
            download = yfinance.download
        history = download(
            symbol,
            start=start,
            end=end,
            interval=interval,
            prepost=False,
            ignore_tz=False,
            auto_adjust=False,
            # yfinance removes empty bins created by its 30m resampling.
            keepna=False,
            repair=False,
            rounding=False,
            multi_level_index=False,
            progress=False,
            threads=False,
        )
        if history is None or history.empty:
            raise ValueError("Yahoo returned no prices for the requested symbol and window")
        if "Close" not in history.columns or history.columns.nlevels != 1:
            raise ValueError("Expected a single-symbol Yahoo Close column")
        bars = []
        for timestamp, close in history["Close"].items():
            if not isinstance(timestamp, datetime) or timestamp != timestamp:
                raise ValueError("Yahoo returned an invalid timestamp")
            label: date | datetime = (
                timestamp.date()
                if interval == "1d"
                else datetime.combine(timestamp.date(), timestamp.timetz())
            )
            bar_date = label.date() if isinstance(label, datetime) else label
            if not start <= bar_date < end:
                raise ValueError("Yahoo returned a bar outside the requested date window")
            bars.append(PriceBar(time=label, close=float(close)))
        return PriceHistory(
            symbol=symbol,
            interval=interval,
            adjustment="split",
            source="Yahoo Finance",
            bars=tuple(bars),
        )
