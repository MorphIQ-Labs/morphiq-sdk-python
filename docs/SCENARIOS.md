# Option scenarios and spot-target solving

This SDK candidate targets the scenario contract in API MR !209. Merge and
release are held until the matching API is deployed and its live schema,
permissions, quotes and receipts are verified. Existing published SDK versions
may not provide these methods. Use a compatible controlled service for testing.

Both `MorphIQ` and `AsyncMorphIQ` provide `evaluate_scenarios()` and `solve_spot()`.
Each call sends exactly one HTTP JSON request. All numerical work runs on the
server; the SDK does not price, interpolate or find roots locally. There are no
automatic retries, hidden preliminary prices, request splitting or parallel calls.

## A five-dollar underlying move

```python
from morphiq_sdk import MorphIQ, PriceRequest, ScenarioPoint, ScenarioPosition, ScenarioRequest

contract = PriceRequest(
    exercise_style="european",
    pricing_model="black_scholes_merton",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.20,
)
request = ScenarioRequest(
    contract=contract,
    scenarios=[ScenarioPoint(spot_change=5.0)],
    position=ScenarioPosition(quantity=1.0, multiplier=100.0),
)
with MorphIQ() as client:
    quote = client.quote(request)  # One zero-CU utility request; no execution.
    print(quote.quote.total_fcu)
    result = client.evaluate_scenarios(request, max_cu=2)  # One capped request.
    for item in result.results:
        if item.status == "success":
            print(item.inputs.spot, item.result.price, item.price_change, item.position_pnl)
        else:
            print(item.index, item.error.code, item.error.message)
    print("Commercial CU charged:", result.metadata.fcu_charged)
```

The example uses synthetic inputs and an explicit two-CU ceiling. Obtain the
account's active quote before choosing a ceiling; quotes do not reserve funds
or lock policy. Use `bjerksund_stensland_1993` with American exercise for BS1993.
These routes require an explicit model: Auto, QdFp and cash-dividend models are
not supported. Model-domain validation remains server-owned.

`spot_change=5` means five quote-currency units, not five percent. Alternatively,
`spot` sets an absolute price; do not combine them. Optional `volatility` is an
absolute annualized decimal (0.25 is 25%). `elapsed_time_years` subtracts from
remaining life, defaults to zero and cannot exceed expiry. Exactly expiry is
allowed. Each point starts from the original contract; shocks do not accumulate.
Rates, yield, strike and direction remain fixed. These are conditional model
valuations, not forecasts or market quotes.

Send 1–99 points in display order for a curve or flattened grid. The base plus
points must fit the account's price-batch limit. Duplicates remain distinct.
The SDK rejects missing, duplicate or reordered response indexes with
`ResponseError`, preserving available billing metadata. It never silently drops
failed points or sorts the server's output.

Evaluation uses existing price-batch rates for the base and every point. Signed
quantity and positive multiplier scale base-relative P&L; they do not multiply
CU charges. Prices/changes are per underlying unit. P&L excludes fees, financing,
trade-entry cost and currency conversion. A negative quantity is short.

## Solve for a target price or position P&L

```python
from morphiq_sdk import MorphIQ, PriceRequest, ScenarioOptionPriceTarget, ScenarioSpotSolveRequest

request = ScenarioSpotSolveRequest(
    contract=PriceRequest(
        exercise_style="european",
        pricing_model="black_scholes_merton",
        option_type="call",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        volatility=0.20,
    ),
    target=ScenarioOptionPriceTarget(kind="option_price", value=15.0),
    min_spot=50.0,
    max_spot=150.0,
)
with MorphIQ() as client:
    print("Quoted CU:", client.quote(request).quote.total_fcu)
    response = client.solve_spot(request, max_cu=100)
    print(response.result.coverage.status)
    for boundary in response.result.boundaries:
        print(boundary.model_dump())
    print("Commercial CU charged:", response.metadata.fcu_charged)
```

For position P&L, replace the target with:

```python
from morphiq_sdk import ScenarioPosition, ScenarioPositionPnlTarget

target = ScenarioPositionPnlTarget(
    kind="position_pnl",
    value=500.0,
    position=ScenarioPosition(quantity=2.0, multiplier=100.0),
)
```

The P&L target is relative to the original model mark, before optional volatility
or elapsed-time adjustments. Quantity is nonzero and signed; multiplier is
positive. Option-price targets are per underlying unit; P&L is position currency.
Bounds must be finite, positive and ordered. Positive tolerances default to
`spot_tolerance=1e-9` and `value_tolerance=1e-6`; the latter uses target units.
Large positions may require tighter spot tolerances to achieve the value tolerance.

Async uses the same requests, types and semantics:

```python
from morphiq_sdk import AsyncMorphIQ


async def solve(request):
    async with AsyncMorphIQ() as client:
        quote = await client.quote(request)
        print(quote.quote.total_fcu)
        return await client.solve_spot(request, max_cu=100)
```

## Flat charges and receipts

| Model | CU per complete solve request |
| --- | ---: |
| BSM | 100 |
| BS1993 | 200 |

The approved schedule includes every internal base, reference and search price.
Target kind, position scaling, evaluation count, iterations and returned
boundaries do not change the flat charge. `result.price_evaluations` is a
diagnostic count, not a billing unit. No additional trial-price charge applies.
The SDK never derives a CU amount from the count or internal `units_charged`.

`client.quote(request)` chooses `scenario_spot_solve` or `scenario_evaluate`
from the request type. A solve quote resolves quantity one without executing
numerical work. The service reserves the full known amount before execution.
`max_cu` forwards `X-MorphIQ-Max-CU` unchanged; a ceiling below the quote refuses
with zero charge, equality is accepted. Solver access needs its own permission
and matching signed schedule; price-batch access alone is insufficient.

The charge commits at execution start. No-root and unresolved searches, and
numerical failures/timeouts after commitment, retain the full flat charge.
Pre-commit validation/admission refusals or cancellation charge zero. Inspect
`APIError.metadata`, `ResponseError.metadata`, raw bodies and request IDs.
Absent commercial metadata is unknown, never zero. A missing response or async
cancellation does not establish whether the server charged; do not retry blindly.

## Read every returned outcome

- `ScenarioSolvePoint`: evaluated spot/value, crossing flag, refinement count and
  bracket width. Compare its value with the requested target for the residual.
- `ScenarioSolveInterval`: sampled plateau bounds and evaluated value. It does
  not certify every real-valued spot inside the interval.
- `regions`: above-target, below-target or at-target segments.
- `coverage.status == "resolved"`: candidates resolved at the declared scan
  resolution; smaller structures can still be missed. Empty boundaries mean no
  solution found at that resolution, not global nonexistence.
- `coverage.status == "unresolved"`: inspect every cell's bounds, best spot,
  absolute value error and typed reason. The SDK preserves these cells and
  does not choose a unique answer or retry with looser tolerances.

The returned profile identifies 32 scan intervals, 64 refinements per candidate
and a conservative 4,775-price ceiling. This is a computational bound, not a CU
reservation. `base` retains the original valuation; `inputs` contains adjusted
fixed assumptions for repricing a boundary using `client.price()` explicitly.
No repricing is performed automatically.

Executable examples: [evaluation](../examples/scenario_evaluate.py),
[sync solve](../examples/solve_spot.py), [async solve](../examples/solve_spot_async.py).
They quote only unless you supply `--max-cu`. Interactive workspaces:
[evaluation](../notebooks/scenarios/evaluate.ipynb) and
[spot targeting](../notebooks/scenarios/solve-spot.ipynb). Setup and control edits
send no requests; action buttons state request counts and require an explicit ceiling.

For a complete client demonstration, run the [solver example app](../examples/solver_app/README.md).
It supplies a browser form, a Python SDK adapter, explicit quote/solve actions,
boundary/coverage tables and session receipts. Its acceptance walkthrough covers
both models, both target types, cap refusal and incomplete/non-unique outcomes.
