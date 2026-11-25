# Batch operations

See [model capabilities](MODELS.md) for supported operations,
100-item batch limits and unavailable-Greek semantics.

Submit one explicit ordered batch with either `MorphIQ` or `AsyncMorphIQ`:

| Method | Request | Response |
| --- | --- | --- |
| `client.options.batch_price()` | `OptionsBatchPriceRequest` | `OptionsBatchPriceResponse` |
| `client.options.batch_standard_greeks()` | `OptionsBatchStandardGreeksRequest` | `OptionsBatchStandardGreeksResponse` |
| `client.options.batch_greeks()` | `OptionsBatchGreeksRequest` | `OptionsBatchGreeksResponse` |
| `client.options.batch_implied_volatility()` | `OptionsBatchImpliedVolatilityRequest` | `OptionsBatchImpliedVolatilityResponse` |
| `client.options.batch_implied_greeks()` | `OptionsBatchImpliedGreeksRequest` | `OptionsBatchImpliedGreeksResponse` |

Each envelope takes `items`, a list of the corresponding single-operation
request models, and is sent to `POST /v1/options:batch-{method}`. One call sends
one HTTP request. These methods do not split batches, create concurrent work,
retry rejected requests, or replay failed items. For caller-sized chunks,
optional async concurrency and per-request costs, use an explicit
[batch workflow](WORKFLOWS.md). The reviewed wire schema allows 1–100 items; the
service applies the account's actual limit, which may be lower. The SDK does not
hardcode plan limits.

Set `MORPHIQ_API_KEY`, then run a self-contained example:

```sh
python -m examples.batch_price
python -m examples.batch_price_async
```

These scripts construct two complete option requests, send one batch, handle
individual results, and print its request ID, provenance and charge once.
For async calls, use `async with AsyncMorphIQ()` and await the same method.

## Constructing each batch type

This builds all five envelope types without sending requests, then submits **one
implied-Greeks batch**. The single item is a synthetic European call. Add
explicitly constructed items to each list to send more contracts in that batch.

```python
from morphiq_sdk import (
    BatchFailure,
    BatchSuccess,
    Market,
    MorphIQ,
    Option,
    OptionsBatchGreeksRequest,
    OptionsBatchImpliedGreeksRequest,
    OptionsBatchImpliedVolatilityRequest,
    OptionsBatchPriceRequest,
    OptionsBatchStandardGreeksRequest,
    OptionsGreeksRequest,
    OptionsImpliedGreeksRequest,
    OptionsImpliedVolatilityRequest,
    OptionsPriceRequest,
    OptionsStandardGreeksRequest,
)

terms = {
    "option": Option(
        type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0
    ),
    "market": Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
}
price_batch = OptionsBatchPriceRequest(items=[OptionsPriceRequest(**terms, volatility=0.20)])
greeks_batch = OptionsBatchGreeksRequest(items=[OptionsGreeksRequest(**terms, volatility=0.20)])
standard_batch = OptionsBatchStandardGreeksRequest(
    items=[OptionsStandardGreeksRequest(**terms, volatility=0.20)]
)
iv_batch = OptionsBatchImpliedVolatilityRequest(
    items=[OptionsImpliedVolatilityRequest(**terms, market_price=10.450583572185538)]
)
implied_greeks_batch = OptionsBatchImpliedGreeksRequest(
    items=[OptionsImpliedGreeksRequest(**terms, market_price=10.450583572185538)]
)

with MorphIQ() as client:
    response = client.options.batch_implied_greeks(implied_greeks_batch)

for item in response.results:
    if isinstance(item, BatchSuccess):
        print(item.index, item.result.model_dump(exclude_unset=True))
    elif isinstance(item, BatchFailure):
        print(item.index, item.error.code, item.error.detail)
    else:
        print(item.index, "unrecognized status:", item.status)
charged = response.metadata.charged_cu
print("Batch CU:", charged if charged is not None else "not reported")
print("Request ID:", response.metadata.request_id)
```

The other calls are `client.options.batch_price(price_batch)`,
`client.options.batch_standard_greeks(standard_batch)`,
`client.options.batch_greeks(greeks_batch)` and
`client.options.batch_implied_volatility(iv_batch)`. Each sends a separate
request if executed. Each operation keeps the corresponding
[single-request fields and units](API.md#option-requests).

For async execution, reuse the constructed envelope with this replacement for
the synchronous call; this sends one implied-Greeks batch when run:

```python
import asyncio

from morphiq_sdk import AsyncMorphIQ


async def analyze():
    async with AsyncMorphIQ() as client:
        return await client.options.batch_implied_greeks(implied_greeks_batch)


response = asyncio.run(analyze())  # In Jupyter: response = await analyze()
```

## Outcomes and costs

`response.results` retains submission order and explicit zero-based `index`.
Each entry is a typed `BatchSuccess` with `status="success"` and `result`, or a
`BatchFailure` with `status="error"` and `error`, an RFC 9457 `Problem` (`code`,
`title`, `detail`, `status` and an optional `field` such as `market.spot`). A
status this SDK version does not know is kept as `BatchUnrecognized`, with its
`index`, `status` and all wire members.
A numerical failure can coexist with successes in an accepted batch. Structural
or admission failures can reject the whole request and raise `APIError`.

Results are never filtered, sorted, or paired by position without validation.
A missing/extra outcome, duplicate or reordered index, or malformed result raises
`ResponseError`. Valid billing metadata remains accessible on that exception;
the raw body and headers retain evidence. There is no automatic replay.

`response.metadata.billing.charged_cu` (shorthand `metadata.charged_cu`) covers
the entire batch. Count it once, including when some items fail. Do not multiply
it by item count, add it once per row, or infer per-item costs. Missing means
unreported, not zero. The quote (`billing.quoted_cu`) is not a charge. The pricing notebook's session ledger includes
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
