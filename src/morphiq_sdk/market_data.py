"""Provider-neutral price data. No data fetching or optional dependencies live here."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from typing import Literal, Protocol

PriceInterval = Literal["1d", "1m", "5m", "15m", "30m", "60m"]
PriceAdjustment = Literal["split", "split_and_dividend", "unadjusted"]


@dataclass(frozen=True)
class PriceBar:
    """A close with a session date or timezone-aware bar-start label.

    The label is not an exact quote/close timestamp. A final intraday bar may
    still be forming; it must not automatically become a regime request's as_of.
    """

    time: date | datetime
    close: float

    def __post_init__(self) -> None:
        if not isfinite(self.close) or self.close <= 0:
            raise ValueError("Close must be finite and positive")
        if not isinstance(self.time, date):
            raise ValueError("A price label must be a date or datetime")
        if isinstance(self.time, datetime) and self.time.utcoffset() is None:
            raise ValueError("Intraday timestamps must include a timezone")


@dataclass(frozen=True)
class PriceHistory:
    """Nonempty, oldest-first prices with explicit provider and adjustment identity.

    Gaps between bars are preserved. No interpolation, resampling or currency
    conversion is implied. Prices retain the source's quoted units.
    """

    symbol: str
    interval: PriceInterval
    adjustment: PriceAdjustment
    source: str
    bars: tuple[PriceBar, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.bars, tuple) or not self.bars:
            raise ValueError("History requires a nonempty tuple of bars")
        if self.interval not in ("1d", "1m", "5m", "15m", "30m", "60m"):
            raise ValueError("Unsupported price interval")
        if self.adjustment not in ("split", "split_and_dividend", "unadjusted"):
            raise ValueError("Unknown price adjustment")
        if not self.symbol.strip() or not self.source.strip():
            raise ValueError("Symbol and source are required")
        for bar in self.bars:
            intraday_label = isinstance(bar.time, datetime)
            if intraday_label != (self.interval != "1d"):
                raise ValueError("Daily bars need session dates; intraday bars need datetimes")
        labels = [
            bar.time.astimezone(UTC) if isinstance(bar.time, datetime) else bar.time
            for bar in self.bars
        ]
        if any(left >= right for left, right in zip(labels, labels[1:], strict=False)):
            raise ValueError("Price labels must be unique and ordered oldest to newest")

    @property
    def prices(self) -> tuple[float, ...]:
        return tuple(bar.close for bar in self.bars)

    @property
    def latest(self) -> PriceBar:
        return self.bars[-1]


class PriceProvider(Protocol):
    """Optional source of regular-session price bars, separate from the API client.

    Date bounds use the instrument's exchange calendar: start inclusive, end
    exclusive. Providers declare adjustments in the result and raise on invalid
    or unavailable data. Available history can be shorter than the requested
    date range; callers enforce their own required observation count.
    """

    def history(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        interval: PriceInterval = "1d",
    ) -> PriceHistory: ...
