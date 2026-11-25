# Batch workflows

Use a workflow when you explicitly want to divide an ordered list into multiple
HTTP batch requests. The `client.options.batch_*()` methods still send exactly one
request. Numerical pricing and implied Greeks run on the API.

`client.options` provides these factories on both `MorphIQ` and `AsyncMorphIQ`:

| Factory | Input sequence | Response retained per chunk |
| --- | --- | --- |
| `price_workflow()` | `OptionsPriceRequest` | `OptionsBatchPriceResponse` |
| `greeks_workflow()` | `OptionsGreeksRequest` | `OptionsBatchGreeksResponse` |
| `standard_greeks_workflow()` | `OptionsStandardGreeksRequest` | `OptionsBatchStandardGreeksResponse` |
| `implied_volatility_workflow()` | `OptionsImpliedVolatilityRequest` | `OptionsBatchImpliedVolatilityResponse` |
| `implied_greeks_workflow()` | `OptionsImpliedGreeksRequest` | `OptionsBatchImpliedGreeksResponse` |

Every factory requires `chunk_size=`. Choose a positive integer allowed by your
account; the SDK checks the reviewed wire ceiling of 100, not customer plan
limits. A smaller final chunk is allowed. Empty input completes without HTTP
requests and has total cost zero. Execution is sequential by default. Async
workflows accept an explicit
`max_concurrency`; no automatic waiting, retries or plan-limit discovery is added.

## Prepare, execute and inspect

This constructs five synthetic pricing scenarios and explicitly submits three
HTTP requests, with at most two items each:

```python
from morphiq_sdk import (
    BatchFailure,
    BatchSuccess,
    Market,
    MorphIQ,
    MorphIQError,
    Option,
    OptionsPriceRequest,
    RateLimitError,
)

option = Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0)
requests = [
    OptionsPriceRequest(
        option=option,
        market=Market(spot=spot, risk_free_rate=0.05, dividend_yield=0.0),
        volatility=0.20,
    )
    for spot in (80.0, 85.0, 90.0, 95.0, 100.0)
]

with MorphIQ() as client:  # Reads MORPHIQ_API_KEY; defaults to https://api.morphiqlabs.com.
    workflow = client.options.price_workflow(requests, chunk_size=2)
    try:
        workflow.run()
    except RateLimitError as error:
        print("Stopped on 429. Retry-After:", error.retry_after)
    except MorphIQError as error:
        print("Stopped:", error)
    finally:
        for attempt in workflow.attempts:
            print("Chunk:", attempt.start, attempt.stop, attempt.request_id)
            print("Reported chunk CU:", attempt.charged_cu)
            if attempt.response is not None:
                for item in attempt.response.results:
                    index = attempt.start + item.index
                    if isinstance(item, BatchSuccess):
                        print(index, item.result.model_dump(exclude_unset=True))
                    elif isinstance(item, BatchFailure):
                        print(index, item.error.code, item.error.detail)
        print("Reported CU subtotal:", workflow.reported_charged_cu)
        print("Unknown-charge attempts:", workflow.unknown_charge_count)
        print("Whole-workflow CU:", workflow.total_charged_cu)
        print("Unattempted input ranges:", workflow.unattempted_ranges)
```

Factories validate and snapshot **all** inputs before execution; edits to the
original list or `Market.dividends` lists do not change prepared requests. Validation
errors send nothing. Preparation holds all chunks in memory: this is for finite
sequences, not streaming input. Keep the client open while running the workflow.

Async factories are also synchronous preparation methods. Use
`workflow = client.options.price_workflow(requests, chunk_size=2)` inside
`async with AsyncMorphIQ()`, then **`await workflow.run()`**. With the default
`max_concurrency=1`, each chunk completes
before the next starts. The returned types are `BatchWorkflow` and
`AsyncBatchWorkflow`; `run()` returns `None`, with progress retained on the object.

Full standalone scripts include credentials, response/provenance handling and
partial-progress reporting:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
python -m examples.chunked_price
python -m examples.chunked_price_async
```

Each script independently sends three requests on success. Running both sends six.

## Progress and costs

| Property | Meaning |
| --- | --- |
| `state` | `ready`, `running`, `completed`, or `stopped` |
| `planned_chunk_count` | Total planned HTTP requests, known before execution |
| `attempts` | Ordered tuple of `ChunkAttempt` records, including a failed/in-flight chunk |
| `unattempted_ranges` | Original input `[start, stop)` ranges never submitted |
| `reported_charged_cu` | Exact integer subtotal of reported commercial charges |
| `unknown_charge_count` | Attempted chunks with an absent charge, including in-flight requests |
| `total_charged_cu` | Total only when completed and all charges are known; otherwise `None` |

Each attempt retains its original input `start` and exclusive `stop`, full typed
`response` or original `error`, `finished`, `request_id` and `charged_cu` (the
attempt's `metadata.billing.charged_cu`).
While in flight, both response and error are `None` and `finished` is false.
A response preserves its original local item indices and raw response evidence;
add `attempt.start` to an item index to locate the original input. Failed items
remain in place. No rows are silently dropped or assigned a zero result.

A commercial charge belongs to the whole chunk, including failed items. It is
captured **once per HTTP attempt**, including API errors and malformed successful
responses with valid charge metadata. Integer sums preserve large CU amounts
exactly. A missing charge remains unknown; reported zero is known. Quotes and
item counts do not contribute to the charge total.
An error can stop execution with every attempted charge known, while the
whole-workflow total remains `None` because the work is incomplete.

## Opt-in async concurrency

All five async factories accept `max_concurrency=1`. Pass a positive integer to
bound simultaneous batch requests, for example:

```python
# Inside async with AsyncMorphIQ() as client:
workflow = client.options.price_workflow(requests, chunk_size=2, max_concurrency=2)
await workflow.run()
```

Five inputs still create three total HTTP requests, with at most two in flight.
`chunk_size` bounds items per request; `max_concurrency` bounds requests in flight.
Choose both for your account. The SDK does not infer plan limits or increase
HTTP connection limits. The setting applies to this workflow, not all clients
or workflows in the process. Sync factories remain sequential.

For `max_concurrency > 1`, execution uses Python's standard `asyncio.TaskGroup`
and a fixed worker pool. Workers take chunks in input order; a free worker can
take the next chunk without waiting for a slower earlier request. Only calls
that start receive attempt records. There is no task created for every input.
`workflow.max_concurrency` exposes the configured bound.

Completions may arrive out of order, but `attempts`, original input ranges and
per-chunk result indices retain submission order. Each receipt's CU is counted
once, including errors; never infer charges from completion order or item count.

Run the async example with explicit concurrency:

```sh
python -m examples.chunked_price_async --max-concurrency 2
```

## Stopping and subsequent work

An accepted response containing item-level failures is retained and processing
continues. HTTP errors (including 429), timeouts, transport failures and invalid
responses stop new submissions as soon as the failure is observed. With
concurrency enabled, already-running calls finish and retain their results and
charges before the **first observed exception** is raised. A slow in-flight call
can therefore delay the error until it finishes or reaches its client timeout.
Other in-flight failures remain accessible in their attempts. Item-level failures
inside accepted responses do not trigger this stop behavior.

On caller cancellation, concurrent workers are cancelled and awaited before
`run()` propagates `CancelledError`; no owned client worker tasks remain in the
background. Client cancellation does not establish that server execution or
billing stopped. Interrupted requests without validated receipts have unknown charges.
If a valid response arrives during cancellation, its receipt and charge are kept
without starting another chunk. Repeated cancellation does not skip worker
cleanup. An operation-level interrupt also stops new submissions; other in-flight
calls drain before that interrupt is propagated. There is no automatic retry,
backoff, chunk-size reduction or concurrency adjustment.

A workflow is single-use. Calling `run()` twice, including while it is running or
after failure, raises `RuntimeError` without another submission. Inspect the
failed attempt's error, request ID and [429 guidance](BATCH.md#http-429).
The interrupted/failed chunk is **excluded** from `unattempted_ranges`: its
execution or charge may already have occurred. Reconcile it separately before
choosing any new attempt.

For later work, explicitly construct a new workflow from the original inputs at
`unattempted_ranges`, using the same input values as the prepared workflow.
This does not include completed or failed chunks. New workflow indices start at
zero; keep the original range offset when correlating its results. Nothing is
resumed automatically, and progress is in memory, not a durable checkpoint.

For ordered tables including failed and unattempted rows, use the optional
[pandas adapter](PANDAS.md). Its separate request table retains one charge per
HTTP attempt. Conversion never runs or resumes a workflow.
