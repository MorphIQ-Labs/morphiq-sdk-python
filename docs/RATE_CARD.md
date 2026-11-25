# Rate card, quotes and execution ceilings

`client.rate_card.get()` (`rate_card.get`, `GET /v1/rate-card`) and
`client.rate_card.quote(request)` (`rate_card.quote`, `POST /v1/rate-card:quote`)
use your normal API key. They consume zero commercial CUs, perform no numerical
calculation and reserve no funds or execution capacity.

```python
from morphiq_sdk import Market, MorphIQ, Option, OptionsPriceRequest

# Synthetic inputs, not market observations.
request = OptionsPriceRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.2,
)
with MorphIQ() as client:
    card = client.rate_card.get(rate_class="price", model="black_scholes_merton/1")
    quote = client.rate_card.quote(request)
    print(quote.quote.total_cu, quote.resolved_models)
    # Explicit execution: one additional, potentially billable request.
    result = client.options.price(request, max_cu=quote.quote.total_cu)
    print(result.metadata.charged_cu)
```

`AsyncMorphIQ` exposes the same methods with `await`. Every typed single and
batch request model, and `SeriesIdentifyRegimeRequest`, can be passed to
`quote`. The SDK sends the request's canonical operation id (for example
`options.price` or `options.batch_price`; `operation_id(request)` returns it) and
serializes the same body it uses for execution. It performs no local pricing or
CU calculation. The response keeps the original JSON in `raw_body`;
`model_dump_json(indent=2, exclude_unset=True)` prints what the server sent.
Every numerical method accepts optional `max_cu`. For a chunked workflow, quote
and submit each chunk explicitly when you need per-request ceilings; a ceiling
does not cap an entire session.

`rate_card.get()` returns your active `RateCard` in `response.schedule`,
including account-specific overrides, identity/version, policy revision,
effective dates, rates, fixed fee, minimum and charging rule. Filters combine
with AND; known filters with no matching rows return an empty list. A rate does
not establish entitlement or availability. `record_version` identifies the
immutable policy record, while `schedule_version` identifies the rate schedule.
An omitted `effective_until` means no fixed end date on that record, not a price
lock. Each `Rate` has a `rate_class`: `price`, `implied_volatility`, `greeks`,
`standard_greeks`, `implied_greeks`, `solve` or `regime`. Every operation prices
at exactly one rate class, and batches use the same rows as their single
operations. Model filters use versioned identifiers such as
`black_scholes_merton/1`.

`quote.quote.total_cu` is exact conditional on the same policy and resolved work
at execution. Fixed fees and minimums apply once to a batch, not once per item.
The minimum is a floor on the request total, not an extra fee. Each `QuoteLine`
groups contracts sharing a rate class and model; mixed-model batches can have
several lines. `resolved_models` identifies the actual selected algorithms.
`quote.metadata.billing.charged_cu` describes the utility call and is zero.

A quote does not lock a price or guarantee funding, capacity, numerical convergence
or success. The response's `metadata.policy.revision` identifies the quote's
snapshot. `max_cu` sends `X-MorphIQ-Max-CU`; it accepts an integer from zero
through 2**64 - 1. An actual quote above the ceiling produces `APIError` with
status 409 and code `cost_limit_exceeded`, before commitment and at zero charge.
Equality is allowed. Once execution commits, a subsequent timeout or failure
retains the committed charge. The SDK never automatically retries.

Rate-card calls use separate account rate buckets from execution, with the
pinned plan's sustained and burst request allowances. Target request/body limits,
account concurrency and service bounds still apply. Invalid or unavailable work
is an error, never a free quote. Rate-card responses are private and not cacheable.

Run the executable example with explicit actions:

```sh
# Two zero-CU calls: rate card and single-request quote.
python examples/rate_card_quote.py
# Two zero-CU calls: rate card and two-contract batch quote.
python examples/rate_card_quote.py --batch
# Adds one potentially billable batch execution, capped at its quoted CU.
python examples/rate_card_quote.py --batch --execute
# Adds one execution with your chosen cap; may produce a ceiling refusal.
python examples/rate_card_quote.py --batch --execute --max-cu 1
```

No command retries or raises its ceiling automatically. The
[cost workspace](../notebooks/cost/quotation.ipynb) provides separate rate card,
quote and capped execution buttons, with synthetic inputs and no setup-time calls.

## Wire-response shapes

These shapes follow the API's published rate-card examples for the pinned
contract. Request IDs are normalized and optional `policy` and `budget` metadata
is omitted for readability. Your account's rates, rate-card identity and service
version can differ: fetch your current rate card instead of copying these values.

A filtered rate card, accessed as `response.schedule`:

```json
{
  "schedule": {
    "effective_from": "2026-11-12T00:00:00Z",
    "failure_charging": "commit_at_execution_start",
    "fixed_request_cu": 0,
    "minimum_charge_cu": 0,
    "policy_revision": "a6bb4c33ace42cb814aa22f0fefc8ba03d0831518c8395d852ec302f9ecbba2a",
    "rates": [
      {
        "billing_unit": "contract",
        "cu_per_unit": 1,
        "max_discrete_dividends": 0,
        "model": "black_scholes_merton/1",
        "rate_class": "price"
      }
    ],
    "record_version": 7,
    "rounding": "none",
    "schedule_id": "fcu-qdfp-v1",
    "schedule_version": "2026-11-12-regime-rate"
  },
  "metadata": {
    "request_id": "example-schedule",
    "service_version": "0.9.1",
    "contract": {"version": "0.1.0", "sha256": "<sha-256 of GET /openapi.json>"},
    "billing": {
      "charged_cu": 0,
      "rate_card": {"id": "fcu-qdfp-v1", "version": "2026-11-12-regime-rate"}
    }
  }
}
```

A single-contract quote, accessed as `response.quote` and `response.resolved_models`:

```json
{
  "quote": {
    "fixed_cu": 0,
    "lines": [
      {
        "billing_unit": "contract",
        "cu_per_unit": 1,
        "model": "black_scholes_merton/1",
        "rate_class": "price",
        "quantity": 1,
        "variable_cu": 1
      }
    ],
    "minimum_charge_cu": 0,
    "total_cu": 1,
    "variable_cu": 1
  },
  "resolved_models": [{"model": "black_scholes_merton/1", "quantity": 1}],
  "metadata": {
    "request_id": "example-quote",
    "service_version": "0.9.1",
    "contract": {"version": "0.1.0", "sha256": "<sha-256 of GET /openapi.json>"},
    "billing": {
      "charged_cu": 0,
      "rate_card": {"id": "fcu-qdfp-v1", "version": "2026-11-12-regime-rate"}
    }
  }
}
```

Here the prospective execution charge is **one CU**, and the quote call's actual
charge is **zero CU**. Quotes put the prospective amount in
`response.quote.total_cu`. Execution responses report their own quote in
`metadata.billing.quoted_cu` and the committed charge in
`metadata.billing.charged_cu`.

## Quote and execute a batch

This complete example submits one zero-CU quote and then one potentially billable
execution. Both use the same two-contract request. The ceiling applies to the
whole batch. Choose whether to run the execution step.

```python
from morphiq_sdk import (
    APIError,
    BatchSuccess,
    Market,
    MorphIQ,
    Option,
    OptionsBatchPriceRequest,
    OptionsPriceRequest,
)

# Two identical synthetic contracts, not market data.
contract = OptionsPriceRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.2,
)
batch = OptionsBatchPriceRequest(items=[contract, contract])
with MorphIQ() as client:
    quote = client.rate_card.quote(batch)
    print(quote.model_dump_json(indent=2, exclude_unset=True))
    try:
        result = client.options.batch_price(batch, max_cu=quote.quote.total_cu)
    except APIError as error:
        print(error.status_code, error.code, error.request_id)
        billing = error.metadata.billing if error.metadata else None
        if billing is not None:
            print("Execution quote CU:", billing.quoted_cu)
            print("CU charged:", billing.charged_cu)
        # Missing charge metadata means unknown, never zero. No automatic retry.
        raise
    print("Batch CU charged:", result.metadata.charged_cu)
    for item in result.results:
        if isinstance(item, BatchSuccess):
            print(item.index, item.result.price)
        else:
            print(item.index, item.status)
```

Two contracts sharing a rate class and model appear as one line with
`quantity: 2`. The API resolves models and computes the total; the SDK forwards
and preserves that evidence. `AsyncMorphIQ` takes the same typed batch with
`await client.rate_card.quote(batch)` and
`await client.options.batch_price(batch, max_cu=...)`. For a chunked workload,
repeat the quote/execute choice for each chunk: there is no implicit
session-wide ceiling.

## Inspect a ceiling refusal

Submitting the single-contract request with `max_cu=0` produces HTTP 409 and
raises `APIError`. The original JSON is available in `error.body`; its typed
evidence is in `error.problem` and `error.metadata`:

```json
{
  "type": "https://developers.morphiqlabs.com/docs/errors#cost_limit_exceeded",
  "title": "CU ceiling exceeded",
  "status": 409,
  "detail": "the quoted CU charge exceeds x-morphiq-max-cu",
  "code": "cost_limit_exceeded",
  "metadata": {
    "request_id": "example-ceiling_error",
    "service_version": "0.9.1",
    "contract": {"version": "0.1.0", "sha256": "<sha-256 of GET /openapi.json>"},
    "engines": [
      {
        "name": "morphiq-risk",
        "revision": "1550e4e41b243b8a978677bc5e9b46916c08cb0e",
        "version": "0.46.1"
      }
    ],
    "billing": {
      "quoted_cu": 1,
      "charged_cu": 0,
      "rate_card": {"id": "fcu-qdfp-v1", "version": "2026-11-12-regime-rate"}
    }
  }
}
```

`billing.quoted_cu: 1` records the execution quote; `billing.charged_cu: 0`
records the zero committed charge. Engine identity does not establish that
calculation ran. Inspect the error code, the current quote and your budget
(`metadata.budget.remaining_estimate_cu`) before choosing a new ceiling. Other
admission errors, including funding refusals, can occur before the ceiling check.
Malformed or duplicate HTTP ceilings return 422; the SDK rejects invalid `max_cu`
values locally before sending a request.
