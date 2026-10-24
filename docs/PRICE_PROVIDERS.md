# Price provider prototype

The SDK defines `PriceProvider`, `PriceHistory` and `PriceBar` using only the
Python standard library. A provider fetches data; the API client accepts prices.
Neither `MorphIQ` nor `AsyncMorphIQ` imports, constructs or calls a provider.

`morphiq_sdk_yahoo.YahooPriceProvider` is an optional implementation. This prototype
ships the adapter namespace in the same wheel, with its runtime dependencies in
the existing `market-data` extra. It is not a separate distribution. Importing the
SDK or adapter does not import Yahoo, pandas, or perform network requests.

## Fetch prices

From a checkout:

```sh
python -m pip install -e '.[market-data]'
```

```python
from datetime import date, timedelta

from morphiq_sdk import PriceProvider
from morphiq_sdk_yahoo import YahooPriceProvider

provider: PriceProvider = YahooPriceProvider()
end = date.today()
history = provider.history("SPY", start=end - timedelta(days=3 * 366), end=end, interval="1d")
print(history.latest.time, history.latest.close)
```

`history.prices` is a tuple of Python floats. `history.bars` retains each close's
label, while `source`, `symbol`, `interval` and `adjustment` describe the series.
There is no pandas object at the interface boundary. Another provider can implement
the same method without inheriting from a framework class.

## Supply prices to the API

```python
from morphiq_sdk import MorphIQ, RegimeRequest

if history.adjustment != "split":
    raise ValueError("Regime requires split-adjusted prices without dividend adjustment")
request = RegimeRequest(prices=list(history.prices[-512:]))
with MorphIQ() as client:  # MORPHIQ_API_KEY must be set.
    response = client.regime(request)
print(response.model_dump_json(indent=2))
```

The caller selects the 512-price window; the request model rejects too few prices.
The provider has no knowledge of regime, pricing models, API credentials or CU.
For an option request, the caller can use `history.latest.close` as `PriceRequest.spot`
and supply the remaining option inputs normally.

The executable [provider example](../examples/provider_regime.py) combines these
steps. Running it submits one real regime request. Existing examples and notebooks
continue to work independently of this prototype.

## Data semantics

- Bounds are exchange-calendar **dates**, start inclusive and end exclusive.
  Use `end=date.today()` for completed daily history.
- Intervals are `1d`, `1m`, `5m`, `15m`, `30m` and `60m`. Intraday windows may span
  multiple sessions. No values are inserted for market closures or missing bars.
- Daily labels are session dates. Intraday labels are timezone-aware bar starts;
  the final bar may still be forming or delayed. Neither label establishes an
  exact final observation time for `RegimeRequest.as_of`.
- Prices must be finite and positive, with unique labels in chronological order.
  Invalid returned bars cause an error; they are not replaced with older prices.
  Units remain those quoted by the source; no currency conversion is performed.
- Yahoo returns `adjustment="split"`, using `Close` with `auto_adjust=False`.
  Dividend-adjusted closes are not substituted. See
  [yfinance's adjustment documentation](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html).
- Yahoo availability and interval limits remain provider-specific. The adapter
  submits one download call with the requested bounds, adding no retries or
  chunking. Yahoo can return fewer observations than the requested span suggests;
  callers check the count needed for their analysis. An empty result raises an error.
- The adapter uses yfinance's standard empty-row cleanup. yfinance aggregates
  15-minute data for its 30-minute interval; the adapter performs no further
  resampling. See [download behavior](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html).

Offline tests use the adapter's optional `downloader` constructor argument to replay
synthetic frames. Production callers normally use `YahooPriceProvider()` directly.
The isolated package check verifies that the base SDK and adapter import without
Yahoo or pandas installed, and that downloading explains the missing optional extra.

See the [client/model reference](API.md) for shared configuration and errors,
and the [documentation index](README.md) for related features.
