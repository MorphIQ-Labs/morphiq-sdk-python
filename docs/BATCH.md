# Batch operations

Submit one explicit ordered batch with either `MorphIQ` or `AsyncMorphIQ`:

| Method | Request | Response |
| --- | --- | --- |
| `price_batch()` | `BatchPriceRequest` | `BatchPriceResponse` |
| `greeks_batch()` | `BatchGreeksRequest` | `BatchGreeksResponse` |
| `implied_volatility_batch()` | `BatchImpliedVolatilityRequest` | `BatchImpliedVolatilityResponse` |
| `analytics_batch()` | `BatchAnalyticsRequest` | `BatchAnalyticsResponse` |

Each envelope takes `requests`, a list of the corresponding single-operation
request models. One call sends one HTTP request. These methods do not split batches,
create concurrent work, retry rejected requests, or replay failed items.
For caller-sized chunks, optional async concurrency and per-request costs, use an
explicit [batch workflow](WORKFLOWS.md).
The reviewed wire schema allows 1–1024 items; the service applies the account's
actual limit, which may be lower. The SDK does not hardcode plan limits.

Set `MORPHIQ_API_KEY`, then run a self-contained example:

```sh
python -m examples.batch_price
python -m examples.batch_price_async
```

These scripts construct two complete option requests, send one batch, handle
individual results, and print its request ID, provenance and charge once.
For async calls, use `async with AsyncMorphIQ()` and await the same method name.

## Constructing each batch type

This builds all four envelope types without sending requests, then submits **one
analytics batch**. The single item is a synthetic European call. Add explicitly
constructed items to each list to send more contracts in that batch.

```python
from morphiq_sdk import (
    AnalyticsRequest,
    BatchAnalyticsRequest,
    BatchGreeksRequest,
    BatchImpliedVolatilityRequest,
    BatchPriceRequest,
    GreeksRequest,
    ImpliedVolatilityRequest,
    MorphIQ,
    PriceRequest,
)

option = {
    "exercise_style": "european",
    "option_type": "call",
    "spot": 100.0,
    "strike": 100.0,
    "time_to_expiry_years": 1.0,
    "risk_free_rate": 0.05,
    "dividend_yield": 0.0,
    "pricing_model": "auto",
}
price_batch = BatchPriceRequest(requests=[PriceRequest(**option, volatility=0.20)])
greeks_batch = BatchGreeksRequest(requests=[GreeksRequest(**option, volatility=0.20)])
iv_batch = BatchImpliedVolatilityRequest(
    requests=[ImpliedVolatilityRequest(**option, market_price=10.450583572185538)]
)
analytics_batch = BatchAnalyticsRequest(
    requests=[AnalyticsRequest(**option, volatility=0.35, market_price=10.450583572185538)]
)

with MorphIQ() as client:
    response = client.analytics_batch(analytics_batch)

for item in response.results:
    if item.status == "success":
        print(item.index, item.result.model_dump(exclude_unset=True))
    else:
        print(item.index, item.error.code, item.error.message)
charged = response.metadata.fcu_charged
print("Batch CU:", charged if charged is not None else "not reported")
print("Request ID:", response.metadata.request_id)
```

The other calls are `client.price_batch(price_batch)`,
`client.greeks_batch(greeks_batch)` and `client.implied_volatility_batch(iv_batch)`.
Each sends a separate request if executed. Each operation keeps the corresponding
[single-request fields and units](API.md#option-request-fields).

For async execution, reuse the constructed envelope with this replacement for
the synchronous call; this sends one analytics batch when run:

```python
import asyncio

from morphiq_sdk import AsyncMorphIQ


async def analyze():
    async with AsyncMorphIQ() as client:
        return await client.analytics_batch(analytics_batch)


response = asyncio.run(analyze())  # In Jupyter: response = await analyze()
```

## Outcomes and costs

`response.results` retains submission order and explicit zero-based `index`.
Each entry is a typed `BatchSuccess` with `status="success"` and `result`, or a
`BatchFailure` with `status="error"` and `error` (code, message, optional field).
A numerical failure can coexist with successes in an accepted batch. Structural
or admission failures can reject the whole request and raise `APIError`.

Results are never filtered, sorted, or paired by position without validation.
A missing/extra outcome, duplicate or reordered index, or malformed result raises
`ResponseError`. Valid billing metadata remains accessible on that exception;
the raw body and headers retain evidence. There is no automatic replay.

`response.metadata.fcu_charged` covers the entire batch. Count it once, including
when some items fail. Do not multiply it by item count, add it once per row, or
infer per-item costs. Missing/null means unreported, not zero. Quotes and internal
`units_charged` are not charges. The pricing notebook's session ledger includes
reported batch-level charges on successes and failures and flags unknown totals.

The notebook's **Spot sensitivity** action submits nine spots in one batch.
Each row keeps its index, original inputs and success/error status; failed points
are gaps in the chart, not zero prices. One batch charge is shown above the table.

## HTTP 429

Every HTTP 429 raises `RateLimitError`, a subclass of `APIError`, including a
non-JSON gateway response. Existing `except APIError` handlers continue to work.
The SDK preserves status, raw `retry_after`, headers, request ID, error code and
available charge metadata. It never assumes that a 429 is free.

`error.retry_delay()` interprets `Retry-After` as delta-seconds or an HTTP date.
It returns a nonnegative delay in seconds, or `None` if the header is absent or
invalid. A past HTTP date returns zero. For deterministic scheduling, pass an
aware UTC datetime as `now`. This method does not sleep or submit anything.

After inspecting the error and charge evidence, the caller may schedule a new
attempt after the indicated delay. A missing header is not permission to retry
immediately. Do not spin on 429, split a refused batch automatically, or replay
an accepted batch merely because some items failed. The notebook shows the
server's retry guidance and waits for a user action; it never retries itself.

Timeouts and cancellation can occur after execution or charge commitment.
Cancellation propagates to the async caller without replay. Unknown charges
remain unknown; use the request ID and account records to reconcile them.

## Tabular analysis

Use the optional [pandas adapter](PANDAS.md) to convert batch results into ordered
analysis rows and a separate per-request charge table. Core SDK calls do not
require pandas.
