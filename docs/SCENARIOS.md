# Option scenarios and books

These methods target the pinned API 0.10.0 contract. Both `MorphIQ` and
`AsyncMorphIQ` expose them; every call sends one request without retries.
Execution, numerical validation, plan permissions and billing remain server-owned.
Use explicit BSM or BS1993 model selections for these operations.

SDK support and account availability are separate. Quote the intended request
first. Both solve methods require a solve-enabled account policy; a
`403 not_entitled` response is an account-policy refusal, not an SDK failure or
an invitation to retry. A catalog entry or a published rate does not grant
entitlement. See the [live solve availability and rate guide](https://developers.morphiqlabs.com/docs/scenarios#solve-rate-card).

| Operation | Request model | Result |
| --- | --- | --- |
| `client.options.revalue` | `OptionsRevalueRequest` | Base valuation and ordered scenario outcomes |
| `client.options.solve_scenario` | `OptionsSolveScenarioRequest` | Target boundaries, sign regions and coverage |
| `client.books.revalue` | `BooksRevalueRequest` | Position, strategy, book and portfolio valuations |
| `client.books.explain` | `BooksExplainRequest` | Revaluation plus expiry and strike P&L buckets |
| `client.books.solve_scenario` | `BooksSolveScenarioRequest` | Spot boundaries for a book or selected strategy |

## Option revaluation

`option`, `market`, `volatility` and explicit `model` define the base valuation.
Each `ScenarioPoint` applies independently to that base: absolute `spot` or
additive `spot_change`, optional absolute `volatility`, and elapsed years.
Do not supply both spot forms. Omitted assumptions stay at their base values.
The wire permits 1–99 scenarios; account limits may be smaller.

```python
from morphiq_sdk import (
    Market,
    ModelSelection,
    MorphIQ,
    Option,
    OptionsRevalueRequest,
    ScenarioPoint,
    ScenarioPosition,
)

request = OptionsRevalueRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.2,
    model=ModelSelection(id="black_scholes_merton"),
    scenarios=[ScenarioPoint(spot=90.0), ScenarioPoint(spot=110.0)],
    position=ScenarioPosition(quantity=-2.0, multiplier=100.0),
)
with MorphIQ() as client:
    response = client.options.revalue(request)
for item in response.result.scenarios:
    if item.status == "success":
        print(item.index, item.result.price, item.price_change, item.pnl)
    elif item.status == "error":
        print(item.index, item.error.code, item.error.detail)
    else:
        print(item.index, item.model_dump(exclude_unset=True))
print(response.metadata.charged_cu)
```

Duplicates remain separate ordered items. Partial failure does not discard
successful points. `ScenarioSuccess`, `ScenarioError` and `ScenarioUnrecognized`
retain their index and resolved inputs. Position P&L is the price change times
signed quantity times multiplier, relative to the **base model mark**.
It excludes entry cost, fees, financing and currency conversion.

## Option targets and solve coverage

`OptionsSolveScenarioRequest` uses the same base inputs plus `target`, finite
`lower`/`upper` bounds, optional tolerances and `scenario` assumptions.
`coordinate` defaults to spot. Accepted coordinates are `spot`, `strike`,
`time_to_expiry`, `elapsed_time`, `rate`, `dividend_yield` and `volatility`.
Volatility solves require a Greek target; solve price for volatility with
`options.implied_volatility` instead. The service validates each model/coordinate
combination and its domain.

Build a target with `ScenarioSolveTargetOptionPrice`,
`ScenarioSolveTargetPositionPnl` (including `ScenarioPosition`) or
`ScenarioSolveTargetGreek`. These are also accepted as discriminated dictionaries:
`{"kind": "greek", "greek": "delta", "value": 0.5}`. All ten Greeks use their
published API units; time Greeks are annual, not per-day. Scenario assumptions
may override volatility or elapsed time; elapsed time cannot also be held fixed
when solving elapsed time or remaining expiry.

Results retain the base, replay inputs, model identity, coordinate/target units,
profile, evaluation counts, boundaries and sign regions. Point boundaries carry
`coordinate`, evaluated `value`, crossing flag and refinement evidence. Interval
boundaries carry `lower`, `upper` and representative `value`. Intervals are
sampled evidence, not a proof for every interior coordinate.

Always inspect `coverage.status`, `coverage.basis` and `outcome` together.
An `incomplete` outcome has unresolved cells and is not a no-solution result.
Even resolved coverage is relative to scan resolution; smaller features can be
missed. Unknown response kinds or enum values are retained for inspection.
The SDK performs no local root finding or verification pricing.

## Books

A book has an `id`, `positions`, and optional `strategies`. A `BookPosition`
contains an option, underlying label, signed quantity, positive multiplier,
volatility and explicit model. Its market comes from `markets[underlying]`.
Strategies list position IDs in their book and may overlap. Book totals sum each
position once; **do not add strategy totals together**. Every value uses the
request's three-letter currency label, with no FX conversion.

`BookScenarioDefinition` contains ordered shocks. The six request variants are:

| Class | `kind` | Additional fields |
| --- | --- | --- |
| `BookShockSpotRelative` | `spot_relative` | `relative` |
| `BookShockParallelVol` | `parallel_vol` | `shift` |
| `BookShockSkew` | `skew` | `slope` |
| `BookShockRate` | `rate` | `shift` |
| `BookShockRollDown` | `roll_down` | `years` |
| `BookShockVolTerm` | `vol_term` | `front_tenor`, `front_shift`, `back_tenor`, `back_shift` |

Shocks compose left to right; do not sort or deduplicate them. Revaluation and
explanation take `books=[...]` and return positions, strategies, books and
portfolio totals in one response. Explanation adds `ScenarioPnlAttribution` at
book and portfolio levels. Each of the expiry and strike bucket sets separately
partitions the positions and reconciles to enclosing P&L.

Book solves take one `book`, optional `strategy_id`, non-spot scenario shocks,
`signed_reference_net_value`, optional `target_pnl` (default zero), and spot
bounds. The solved positions must share one underlying. Their P&L is horizon
value minus the signed reference: a debit paid is positive and a credit received
is negative. This differs from revaluation's base-model-value reference.
Roll-down may reach expiry but cannot pass it. The result retains selected
positions, reference, scenario, units and the same boundary/coverage evidence
as option solves. Wire limits and lower account limits are validated by the API.

## Quotes, async calls and receipts

All five request types work with `client.rate_card.quote(request)`. Use
`BooksExplainRequest` for an explanation quote; its wire body equals a
revaluation body, but the canonical operation is `books.explain`.

```python
from morphiq_sdk import AsyncMorphIQ, BooksExplainRequest


async def explain_books(body):
    request = BooksExplainRequest.model_validate(body)
    async with AsyncMorphIQ() as client:
        quote = await client.rate_card.quote(request)
        # Two explicit requests: one quote, then one capped calculation.
        response = await client.books.explain(request, max_cu=quote.quote.total_cu)
    return response
```

A quote is not a reservation or a charge. `metadata.billing.charged_cu` (also
`metadata.charged_cu`) is the commercial receipt; absence means unreported,
not zero. Do not multiply solve charges by iterations, refinements or price
calls. Ask the deployed rate card for the actual request's cost and set `max_cu`.
A timeout may occur after charge commitment. Exceptions retain available
problem, request ID and billing evidence; the SDK never automatically retries.

## Run and inspect

[Option revalue](../examples/option_revalue.py),
[option solve](../examples/option_solve.py),
[book revalue](../examples/book_revalue.py),
[book explain](../examples/book_explain.py), and
[book solve](../examples/book_solve.py) are standalone synthetic scripts.
The [local spot-solver app](../examples/solver_app/README.md) separates quote and
solve actions and retains receipts.

Each operation has a standalone notebook in `notebooks/scenarios/` or
`notebooks/books/`. Edit the JSON inputs or paste caller-supplied data; setup and
edits make no requests. Quote and Execute each send exactly one request. A quote
is consumed before execution, including failed or unknown outcomes, and edits
invalidate the current result while preserving receipt history.
