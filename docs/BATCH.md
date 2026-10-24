# Batch operations

Submit one explicit ordered batch with either `MorphIQ` or `AsyncMorphIQ`:

| Method | Request | Response |
| --- | --- | --- |
| `price_batch()` | `BatchPriceRequest` | `BatchPriceResponse` |
| `greeks_batch()` | `BatchGreeksRequest` | `BatchGreeksResponse` |
| `implied_volatility_batch()` | `BatchImpliedVolatilityRequest` | `BatchImpliedVolatilityResponse` |
| `analytics_batch()` | `BatchAnalyticsRequest` | `BatchAnalyticsResponse` |

Each envelope takes `requests`, a list of the corresponding single-operation
request models. One call sends one HTTP request. The SDK does not split batches,
create concurrent work, retry rejected requests, or replay failed items.
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
