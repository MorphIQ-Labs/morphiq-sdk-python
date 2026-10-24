"""Use an optional price provider, then submit prices through the SDK.

Install: python -m pip install -e '.[market-data]'
Set MORPHIQ_API_KEY, then run: python -m examples.provider_regime
"""

from datetime import date, timedelta

from morphiq_sdk import MorphIQ, PriceProvider, RegimeRequest
from morphiq_sdk_yahoo import YahooPriceProvider


def main() -> None:
    # Any implementation of PriceProvider can replace Yahoo here.
    provider: PriceProvider = YahooPriceProvider()
    end = date.today()  # Exclusive: omit today's possibly incomplete daily bar.
    history = provider.history("SPY", start=end - timedelta(days=3 * 366), end=end)
    if history.adjustment != "split":
        raise ValueError("Regime requires split-adjusted prices without dividend adjustment")
    print(f"{history.symbol}: latest close {history.latest.close} on {history.latest.time}")

    # The provider knows nothing about the API or its 512-price requirement.
    request = RegimeRequest(prices=list(history.prices[-512:]))
    with MorphIQ() as client:  # Reads MORPHIQ_API_KEY; uses https://api.morphiqlabs.com.
        response = client.regime(request)
    # Includes all head results, scores, provenance, request ID and reported CU.
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
