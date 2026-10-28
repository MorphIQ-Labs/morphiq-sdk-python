# Cost schedules, quotes and execution ceilings

These methods require an API deployment and SDK release that support cost utilities.
Use your normal API key. Utility calls consume zero commercial CUs, perform no
numerical calculation and reserve no funds or execution capacity.

```python
from morphiq_sdk import MorphIQ, PriceRequest

# Synthetic inputs, not market observations.
request = PriceRequest(
    exercise_style="european",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.2,
)
with MorphIQ() as client:
    schedule = client.cost_schedule(operation="price", model="black_scholes_merton/1")
    quote = client.quote(request)
    print(quote.quote.total_fcu, quote.resolved_models)
    # Explicit execution: one additional, potentially billable request.
    result = client.price(request, max_cu=quote.quote.total_fcu)
    print(result.metadata.fcu_charged)
```

`AsyncMorphIQ` exposes the same methods with `await`. All nine existing typed
single and batch request models can be passed to `quote`; the SDK infers the
operation and serializes the same body it uses for execution. It performs no
local pricing or CU calculation. The response keeps the original JSON in `raw_body`;
`model_dump_json(indent=2, exclude_none=True)` prints its typed fields. Every single/batch execution method accepts
optional `max_cu`. For a chunked workflow, quote and submit each chunk explicitly
when you need per-request ceilings; a ceiling does not cap an entire session.

`cost_schedule()` returns the caller's active schedule, including account-specific
overrides, identity/version, policy revision, effective dates, rates, fixed fee,
minimum and charging rule. Filters combine with AND; known filters with no matching
rows return an empty list. A rate does not establish entitlement or availability. `record_version` identifies
the immutable policy record, while `schedule_version` identifies the rate schedule.
A null `effective_until` means no fixed end date on that record, not a price lock.
Operation filters are `price`, `implied_volatility`, `greeks`, `analytics`, `regime`;
batch calls use those same schedule rows. Model filters use versioned identifiers.

`quote.quote.total_fcu` is exact conditional on the same policy and resolved work
at execution. Fixed fees and minimums apply once to a batch, not once per item.
The minimum is a floor on the request total, not an extra fee. Each line groups
contracts sharing a rate class; mixed-model batches can have several lines.
`quote.quote.lines` identifies rate classes; `resolved_models` identifies actual
selected algorithms. These can differ when algorithms share a billing class.
`quote.metadata.fcu_charged` describes the utility call and is zero.

A quote does not lock a price or guarantee funding, capacity, numerical convergence
or success. Its policy revision identifies the quote's snapshot. `max_cu` sends
`X-MorphIQ-Max-CU`; it accepts an integer from zero through 2**64 - 1. An actual
quote above the ceiling produces `APIError` with status 409 and code
`cost_limit_exceeded`, before commitment and at zero charge. Equality is allowed.
Once execution commits, a subsequent timeout or failure retains the committed
charge. The SDK never automatically retries.

Cost utility calls use separate account rate buckets from execution, with the
pinned plan's sustained and burst request allowances. Target request/body limits,
account concurrency and service bounds still apply. Invalid or unavailable work
is an error, never a free quote. Utility responses are private and not cacheable.

Run the executable example with explicit actions:

```sh
# Two zero-CU utility calls: schedule and single-request quote.
python examples/cost_quote.py
# Two zero-CU utility calls: schedule and two-contract batch quote.
python examples/cost_quote.py --batch
# Adds one potentially billable batch execution, capped at its quoted CU.
python examples/cost_quote.py --batch --execute
# Adds one execution with your chosen cap; may produce a ceiling refusal.
python examples/cost_quote.py --batch --execute --max-cu 1
```

No command retries or raises its ceiling automatically. The
[cost workspace](../notebooks/cost/quotation.ipynb) provides separate schedule,
quote and capped execution buttons, with synthetic inputs and no setup-time calls.


## Response examples

These are wire responses from synthetic requests against the local API example
schedule, captured for [API !188](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/merge_requests/188)
at source `ae243c62bf2c3c06182f845bab4f8131c60e3d48`. Request IDs are normalized;
optional policy and budget metadata is omitted for readability. Your account's
rates, policy identity and service version can differ. These examples do not
establish that the endpoints are deployed or that the SDK feature is released.

A filtered schedule, accessed as `response.schedule`:

```json
{
  "schedule": {
    "effective_from": "2026-10-19T00:00:00Z",
    "effective_until": null,
    "failure_charging": "commit_at_execution_start",
    "fixed_request_fcu": 0,
    "minimum_charge_fcu": 0,
    "policy_revision": "5f33de9e901762390e72bb9820f01e64b704e43155973871672973878405f0f5",
    "rates": [
      {
        "billing_unit": "contract",
        "fcu_per_unit": 1,
        "max_discrete_dividends": 0,
        "model": "black_scholes_merton/1",
        "operation": "price"
      }
    ],
    "record_version": 2,
    "rounding": "none",
    "schedule_id": "fcu-student-v1",
    "schedule_version": "2026-10-19-r2"
  },
  "metadata": {
    "api_version": "v1",
    "fcu_charged": 0,
    "fcu_schedule_id": "fcu-student-v1",
    "fcu_schedule_version": "2026-10-19-r2",
    "request_id": "example-schedule",
    "service_version": "0.4.1"
  }
}
```

A single-contract quote, accessed as `response.quote` and `response.resolved_models`:

```json
{
  "quote": {
    "fixed_fcu": 0,
    "lines": [
      {
        "billing_unit": "contract",
        "fcu_per_unit": 1,
        "model": "black_scholes_merton/1",
        "operation": "price",
        "quantity": 1,
        "variable_fcu": 1
      }
    ],
    "minimum_charge_fcu": 0,
    "total_fcu": 1,
    "variable_fcu": 1
  },
  "resolved_models": [
    {
      "model": "black_scholes_merton/1",
      "quantity": 1
    }
  ],
  "metadata": {
    "api_version": "v1",
    "fcu_charged": 0,
    "fcu_schedule_id": "fcu-student-v1",
    "fcu_schedule_version": "2026-10-19-r2",
    "request_id": "example-quote",
    "service_version": "0.4.1"
  }
}
```

Here the prospective execution charge is **one CU**, and the quote call's
actual charge is **zero CU**. Utility quotes put the prospective amount in
`response.quote.total_fcu`. Execution responses use `metadata.fcu_quoted` for
their own quote and `metadata.fcu_charged` for the committed charge.

## Quote and execute a batch

This complete example submits one zero-CU quote and then one potentially billable
execution. Both use the same two-contract request. The ceiling applies to the
whole batch. Choose whether to run the execution step.

```python
from morphiq_sdk import APIError, BatchPriceRequest, MorphIQ, PriceRequest

# Two identical synthetic contracts, not market data.
option = PriceRequest(
    exercise_style="european",
    pricing_model="auto",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.2,
)
batch = BatchPriceRequest(requests=[option, option])
with MorphIQ() as client:
    quote = client.quote(batch)
    print(quote.model_dump_json(indent=2, exclude_none=True))
    try:
        result = client.price_batch(batch, max_cu=quote.quote.total_fcu)
    except APIError as error:
        print(error.status_code, error.code, error.request_id)
        if error.metadata is not None:
            print("Execution quote CU:", error.metadata.fcu_quoted)
            print("CU charged:", error.metadata.fcu_charged)
        # Missing charge metadata means unknown, never zero. No automatic retry.
        raise
    print("Batch CU charged:", result.metadata.fcu_charged)
    for item in result.results:
        if item.status == "success":
            print(item.index, item.result.price)
        else:
            print(item.index, item.error.code)
```

The quote for those two contracts under the example schedule is:

```json
{
  "quote": {
    "fixed_fcu": 0,
    "lines": [
      {
        "billing_unit": "contract",
        "fcu_per_unit": 1,
        "model": "black_scholes_merton/1",
        "operation": "price",
        "quantity": 2,
        "variable_fcu": 2
      }
    ],
    "minimum_charge_fcu": 0,
    "total_fcu": 2,
    "variable_fcu": 2
  },
  "resolved_models": [
    {
      "model": "black_scholes_merton/1",
      "quantity": 2
    }
  ],
  "metadata": {
    "api_version": "v1",
    "fcu_charged": 0,
    "fcu_schedule_id": "fcu-student-v1",
    "fcu_schedule_version": "2026-10-19-r2",
    "request_id": "example-batch_quote",
    "service_version": "0.4.1"
  }
}
```

The single line has `quantity: 2` because both contracts share a billing class.
The API resolves models and computes the total; the SDK forwards and preserves
that evidence. `AsyncMorphIQ` takes the same typed batch with
`await client.quote(batch)` and `await client.price_batch(batch, max_cu=...)`.
For a chunked workload, repeat the quote/execute choice for each chunk: there is
no implicit session-wide ceiling.

## Inspect a ceiling refusal

Submitting that batch with `max_cu=1` under the example schedule produces
HTTP 409 and raises `APIError`. The original JSON is available in `error.body`;
its typed evidence is in `error.metadata`:

```json
{
  "error": {
    "code": "cost_limit_exceeded",
    "message": "the quoted CU charge exceeds x-morphiq-max-cu"
  },
  "metadata": {
    "api_version": "v1",
    "compute_schedule_version": "2026-09-11",
    "engine_version": "0.39.1",
    "engines": [
      {
        "name": "morphiq-risk",
        "revision": "b4c29d492ff96dddf9b25f745d2be4d253202164",
        "version": "0.39.1"
      }
    ],
    "fcu_charged": 0,
    "fcu_quoted": 2,
    "fcu_schedule_id": "fcu-student-v1",
    "fcu_schedule_version": "2026-10-19-r2",
    "request_id": "example-ceiling_error",
    "units_charged": 0
  }
}
```

`fcu_quoted: 2` records the execution quote; `fcu_charged: 0` records the
zero committed charge. `units_charged` is internal execution accounting, not
commercial CU. Engine identity does not establish that calculation ran.
Inspect the error code, the current quote and your budget before choosing a new
ceiling. Other admission errors, including funding refusals, can occur before
the ceiling check. Malformed or duplicate HTTP ceilings return 422; the SDK
rejects invalid `max_cu` values locally before sending a request.
