"""Provider boundaries and Yahoo conversion with synthetic, in-memory market data."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from morphiq_sdk import MorphIQ, PriceBar, PriceHistory, PriceProvider, RegimeRequest
from morphiq_sdk_yahoo import YahooPriceProvider


def daily_frame():
    return pd.DataFrame(
        {"Close": [100.12345678912345, 101.75], "Adj Close": [90.5, 91.25]},
        index=pd.date_range("2026-01-05", periods=2, tz="America/New_York"),
    )


def test_yahoo_boundary_preserves_close_values_and_download_semantics():
    calls = []
    frame = daily_frame()

    def download(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return frame

    provider: PriceProvider = YahooPriceProvider(downloader=download)
    history = provider.history(" spy ", start=date(2026, 1, 5), end=date(2026, 1, 7))
    assert history.symbol == "SPY" and history.source == "Yahoo Finance"
    assert history.adjustment == "split" and history.interval == "1d"
    assert history.prices == (100.12345678912345, 101.75)
    assert history.latest == PriceBar(date(2026, 1, 6), 101.75)
    assert all(type(bar.time) is date and type(bar.close) is float for bar in history.bars)
    assert calls == [
        (
            "SPY",
            dict(
                start=date(2026, 1, 5),
                end=date(2026, 1, 7),
                interval="1d",
                prepost=False,
                ignore_tz=False,
                auto_adjust=False,
                keepna=False,
                repair=False,
                rounding=False,
                multi_level_index=False,
                progress=False,
                threads=False,
            ),
        )
    ]


def test_intraday_keeps_timezones_gaps_and_final_bar():
    index = pd.DatetimeIndex(["2026-10-16 15:55", "2026-10-19 09:30"], tz="America/New_York")
    frame = pd.DataFrame({"Close": [101.125, 102.375]}, index=index)
    provider = YahooPriceProvider(downloader=lambda *args, **kwargs: frame)
    history = provider.history(
        "SPY", start=date(2026, 10, 16), end=date(2026, 10, 20), interval="5m"
    )
    assert history.prices == (101.125, 102.375)
    assert [bar.time.isoformat() for bar in history.bars] == [t.isoformat() for t in index]
    assert all(type(bar.time) is datetime for bar in history.bars)
    assert str(history.latest.time.tzinfo) == "America/New_York"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_latest_close_is_rejected_not_replaced(bad):
    frame = daily_frame()
    frame.iloc[-1, 0] = bad
    provider = YahooPriceProvider(downloader=lambda *args, **kwargs: frame)
    with pytest.raises(ValueError, match="finite and positive"):
        provider.history("SPY", start=date(2026, 1, 5), end=date(2026, 1, 7))


@pytest.mark.parametrize("case", ["empty", "reverse", "duplicate", "outside", "missing_close"])
def test_invalid_yahoo_history_is_rejected(case):
    frame = daily_frame()
    if case == "empty":
        frame = frame.iloc[:0]
    elif case == "reverse":
        frame = frame.iloc[::-1]
    elif case == "duplicate":
        frame.index = [frame.index[0], frame.index[0]]
    elif case == "outside":
        frame.index = pd.date_range("2026-01-01", periods=2)
    else:
        frame = frame.drop(columns="Close")
    provider = YahooPriceProvider(downloader=lambda *args, **kwargs: frame)
    with pytest.raises(ValueError):
        provider.history("SPY", start=date(2026, 1, 5), end=date(2026, 1, 7))


def test_download_failure_is_not_retried():
    calls = []

    def download(*args, **kwargs):
        calls.append(args)
        raise TimeoutError("synthetic timeout")

    provider = YahooPriceProvider(downloader=download)
    with pytest.raises(TimeoutError):
        provider.history("SPY", start=date(2026, 1, 5), end=date(2026, 1, 7))
    assert len(calls) == 1


def test_bad_query_is_rejected_before_download():
    def download(*args, **kwargs):
        pytest.fail("Invalid query reached downloader")

    provider = YahooPriceProvider(downloader=download)
    for symbol in ["", "SPY QQQ", "SPY,QQQ"]:
        with pytest.raises(ValueError):
            provider.history(symbol, start=date(2026, 1, 5), end=date(2026, 1, 7))
    with pytest.raises(ValueError):
        provider.history("SPY", start=date(2026, 1, 7), end=date(2026, 1, 5))
    with pytest.raises(ValueError):
        provider.history("SPY", start=datetime(2026, 1, 5), end=date(2026, 1, 7))


def test_intraday_timezone_is_required_and_dst_order_uses_absolute_time():
    with pytest.raises(ValueError, match="timezone"):
        PriceBar(datetime(2026, 1, 5, 9, 30), 100.0)
    ny = ZoneInfo("America/New_York")
    bars = (
        PriceBar(datetime(2026, 11, 1, 1, 55, tzinfo=ny, fold=0), 100.0),
        PriceBar(datetime(2026, 11, 1, 1, 0, tzinfo=ny, fold=1), 101.0),
    )
    history = PriceHistory("TEST", "5m", "unadjusted", "synthetic", bars)
    assert history.prices == (100.0, 101.0)
    with pytest.raises(ValueError, match="ordered"):
        PriceHistory("TEST", "5m", "unadjusted", "synthetic", bars[::-1])


def test_another_provider_feeds_the_existing_client_without_yahoo(regime_cases):
    case = regime_cases[0]

    class SyntheticProvider:
        def history(self, symbol, *, start, end, interval="1d"):
            return PriceHistory(
                symbol,
                interval,
                "split",
                "synthetic",
                tuple(
                    PriceBar(start + timedelta(days=i), price)
                    for i, price in enumerate(case["request"]["prices"])
                ),
            )

    provider: PriceProvider = SyntheticProvider()
    history = provider.history("TEST", start=date(2020, 1, 1), end=date(2023, 1, 1))
    received = []

    def handle(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=case["response"])

    with MorphIQ(api_key="synthetic-test-key", transport=httpx.MockTransport(handle)) as client:
        response = client.regime(RegimeRequest(prices=list(history.prices)))
    assert received == [case["request"]]
    assert response.metadata.request_id == case["response"]["metadata"]["request_id"]
