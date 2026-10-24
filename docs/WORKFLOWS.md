# Sequential batch workflows

Use a workflow when you explicitly want to divide an ordered list into multiple
HTTP batch requests. The existing `*_batch()` methods still send exactly one
request. Numerical pricing and combined analytics run on the API.

Both `MorphIQ` and `AsyncMorphIQ` provide these factories:

| Factory | Input sequence | Response retained per chunk |
| --- | --- | --- |
| `price_workflow()` | `PriceRequest` | `BatchPriceResponse` |
| `greeks_workflow()` | `GreeksRequest` | `BatchGreeksResponse` |
| `implied_volatility_workflow()` | `ImpliedVolatilityRequest` | `BatchImpliedVolatilityResponse` |
| `analytics_workflow()` | `AnalyticsRequest` | `BatchAnalyticsResponse` |

Every factory requires `chunk_size=`. Choose a positive integer allowed by your
account; the SDK checks the reviewed wire ceiling of 1024, not customer plan
limits. A smaller final chunk is allowed. Empty input completes without HTTP
requests and has total cost zero. No concurrency, waiting or retries are added.

## Prepare, execute and inspect

This constructs five synthetic pricing scenarios and explicitly submits three
HTTP requests, with at most two items each:

```python
from morphiq_sdk import MorphIQ, MorphIQError, PriceRequest, RateLimitError

requests = [
    PriceRequest(
        exercise_style="european",
        option_type="call",
        spot=spot,
        strike=100.0,
        time_to_expiry_years=1.0,
        volatility=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    for spot in (80.0, 85.0, 90.0, 95.0, 100.0)
]

with MorphIQ() as client:  # Reads MORPHIQ_API_KEY; defaults to https://api.morphiqlabs.com.
    workflow = client.price_workflow(requests, chunk_size=2)
    try:
        workflow.run()
    except RateLimitError as error:
        print("Stopped on 429. Retry-After:", error.retry_after)
    except MorphIQError as error:
        print("Stopped:", error)
    finally:
        for attempt in workflow.attempts:
            print("Chunk:", attempt.start, attempt.stop, attempt.request_id)
            print("Reported chunk CU:", attempt.fcu_charged)
            if attempt.response is not None:
                for item in attempt.response.results:
                    index = attempt.start + item.index
                    if item.status == "success":
                        print(index, item.result.model_dump(exclude_unset=True))
                    else:
                        print(index, item.error.code, item.error.message)
        print("Reported CU subtotal:", workflow.reported_fcu_charged)
        print("Unknown-charge attempts:", workflow.unknown_charge_count)
        print("Whole-workflow CU:", workflow.total_fcu_charged)
        print("Unattempted input ranges:", workflow.unattempted_ranges)
```

Factories validate and snapshot **all** inputs before execution; edits to the
original list or dividend schedules do not change prepared requests. Validation
errors send nothing. Preparation holds all chunks in memory: this is for finite
sequences, not streaming input. Keep the client open while running the workflow.

Async factories are also synchronous preparation methods. Use
`workflow = client.price_workflow(requests, chunk_size=2)` inside
`async with AsyncMorphIQ()`, then **`await workflow.run()`**. Each chunk completes
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
| `reported_fcu_charged` | Exact integer subtotal of reported commercial charges |
| `unknown_charge_count` | Attempted chunks with absent/null charge, including in-flight requests |
| `total_fcu_charged` | Total only when completed and all charges are known; otherwise `None` |

Each attempt retains its original input `start` and exclusive `stop`, full typed
`response` or original `error`, `finished`, `request_id` and `fcu_charged`.
While in flight, both response and error are `None` and `finished` is false.
A response preserves its original local item indices and raw response evidence;
add `attempt.start` to an item index to locate the original input. Failed items
remain in place. No rows are silently dropped or assigned a zero result.

A commercial charge belongs to the whole chunk, including failed items. It is
captured **once per HTTP attempt**, including API errors and malformed successful
responses with valid charge metadata. Integer sums preserve large CU amounts
exactly. Missing/null charge remains unknown; reported zero is known. Quotes,
internal `units_charged`, and item counts do not contribute to the charge total.
An error can stop execution with every attempted charge known, while the
whole-workflow total remains `None` because the work is incomplete.

## Stopping and subsequent work

An accepted response containing item-level failures is retained and processing
continues. HTTP errors (including 429), timeouts, transport failures and invalid
responses stop immediately and propagate the original exception. Keyboard
interrupts and async cancellation also propagate after retaining the interrupted
attempt with unknown charge. There is no automatic retry or chunk-size reduction.

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
