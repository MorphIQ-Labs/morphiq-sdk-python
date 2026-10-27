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
local pricing or CU calculation. Every single/batch execution method accepts
optional `max_cu`. For a chunked workflow, quote and submit each chunk explicitly
when you need per-request ceilings; a ceiling does not cap an entire session.

`cost_schedule()` returns the caller's active schedule, including account-specific
overrides, identity/version, policy revision, effective dates, rates, fixed fee,
minimum and charging rule. Filters combine with AND; known filters with no matching
rows return an empty list. A rate does not establish entitlement or availability.
Operation filters are `price`, `implied_volatility`, `greeks`, `analytics`, `regime`;
batch calls use those same schedule rows. Model filters use versioned identifiers.

`quote.quote.total_fcu` is exact conditional on the same policy and resolved work
at execution. Fixed fees and minimums apply once to a batch, not once per item.
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

Run `python examples/cost_quote.py` for schedule discovery and quotation only;
add `--execute` to explicitly submit the quoted request. The
[cost workspace](../notebooks/cost/quotation.ipynb) provides separate schedule,
quote and capped execution buttons, with synthetic inputs and no setup-time calls.
