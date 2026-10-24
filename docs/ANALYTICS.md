# Combined option analytics

`MorphIQ.analytics()` and `AsyncMorphIQ.analytics()` call `POST /v1/analytics`.
With a market premium, the service solves implied volatility and evaluates price
and all ten Greeks at that solved volatility in one request. Without a premium,
it evaluates price and Greeks at the supplied volatility.

Set `MORPHIQ_API_KEY`, then run a self-contained example:

```sh
python -m examples.analytics
python -m examples.analytics_async
```

Each example sends one request with synthetic option terms and a synthetic
premium, then prints price, IV diagnostics, Greeks, provenance and commercial CU.

```python
from morphiq_sdk import AnalyticsRequest, MorphIQ

request = AnalyticsRequest(
    exercise_style="european",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.35,
    market_price=10.450583572185538,
    pricing_model="auto",
)
with MorphIQ() as client:
    response = client.analytics(request)
print(response.model_dump_json(indent=2, exclude_unset=True))
```

The pinned contract requires `volatility` even with `market_price`; the service
ignores it when a premium is supplied. This example solves to approximately 0.20,
and its Greeks use that solved value, not 0.35. Omit `market_price` or pass null to
use the supplied volatility. Omission and explicit null remain distinct on the
wire. Cash-dividend schedules and model choices are forwarded to the service for
validation, without local adjustment or numerical computation.

Time is in years, rates and volatility are decimals, and premium/spot/strike share
a per-share currency basis. [Greek units](GREEKS.md) and
[IV diagnostics and residual bases](IMPLIED_VOLATILITY.md) are unchanged.
`result.implied_volatility` may be absent or null; the SDK never invents a solve.

## Commercial CU

The response's `metadata.fcu_charged` is the reported charge for the entire
combined request. Count it **once**. Price, the ten Greeks and the nested IV result
are components of that response, not separate billable responses to sum.
Commercial policy and the calculation of this charge belong to the service.
Do not add quotes (`fcu_quoted`) or internal compute weights (`units_charged`).

The [pricing workspace](../notebooks/pricing/options.ipynb) records every request
from Price option, Price + Greeks, Solve IV, Analyze premium and Spot sensitivity:

- Reported charges are summed with exact integer arithmetic, including zero.
- API failures with reported charges count toward the sum, including failures
  that reject a sweep. The nine-item sensitivity batch counts once, including
  mixed per-item outcomes. Successful and failed attempts each appear once.
- A malformed numerical response can still carry valid metadata. The SDK exposes
  independently validated metadata on `ResponseError.metadata`, and its reported
  charge is included. Invalid metadata is not trusted.
- Missing/null charges, malformed metadata and transport failures remain unknown.
  The UI labels the sum as a **reported subtotal**, with an unknown-charge count;
  it cannot claim a complete total until every attempt has a reported charge.
- Redrawing results does not add charges. Clicking an action again sends a new
  request and creates a new ledger entry. Local input failures make no request
  and create no entry. No automatic retries occur.

The ledger covers this pricing workspace's current kernel session, not account
usage or cash billing. Rerunning setup retains it; restarting the kernel resets
it. Its rows retain action, outcome, request ID and reported commercial charge.

## Pricing workspace

Enter option terms and an **Option premium**, then select **Analyze premium**.
One click displays price, solved IV, diagnostics, a labeled ten-Greek table,
submitted inputs, resolved model and engine identity, request ID and charge.
The volatility assumption used by the other pricing actions stays unchanged.
Yahoo supplies the underlying price; the option premium is entered manually.
