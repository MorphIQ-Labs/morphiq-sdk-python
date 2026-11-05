# Available models and API v0.5.0 compatibility

```python
from morphiq_sdk import MorphIQ

with MorphIQ() as client:
    catalog = client.pricing_models()
for model in catalog.models:
    print(model.id, model.operations, model.batch_operations, model.constraints)
```

This public GET sends no API key, even when a key is configured. `AsyncMorphIQ`
provides the same method with `await`. The catalog includes aliases, engine/model
versions, Greek units, supported dividends, constraints and guidance. It describes
compiled service capabilities; account entitlements and rates come from the
authenticated `cost_schedule()` and `quote(request)` methods.

| Canonical selector | Single operations | Batch operations |
| --- | --- | --- |
| `black_scholes_merton` | Price, IV, standard five, all ten, analytics | All five |
| `bjerksund_stensland_1993` | Price, IV, standard five, all ten, analytics | All five |
| `black_scholes_merton_qdfp` | Price, IV | None |
| `black_scholes_merton_fd` | Price, IV | None |

The finite-difference model supports cash-dividend schedules. Legacy aliases
`qd_fixed_point` and `cash_dividend_american` are forwarded unchanged. BS2002 is
retired: the SDK forwards that selector so callers receive the server's migration
error. It does not substitute a model or calculate numerical fallbacks.

`auto` selects BSM for European options and QdFp for American options. Select
BS1993 explicitly for American Greeks, analytics and batching. Unsupported
operations and a batch containing QdFp or the cash-dividend model receive HTTP 400
(`APIError`); batches contain 1–100 items. Account limits may be lower.

A Greek may be omitted with an entry in `greeks.unavailable`, whose value contains
`code`, `message` and optionally `field`. Python exposes the omitted quantity as
`None`; it is never replaced by zero. `model_dump(exclude_unset=True)` preserves
wire omission and all reasons. DataFrame numeric cells remain missing, with
reasons available in the `result.greeks.unavailable` column and full `outcome`.

The API owns these capabilities and may evolve them. Query discovery for current
capabilities and preserve actionable server errors instead of copying this table
into client admission logic.

The candidate catalog adds `scenario_operations`: BSM and BS1993 expose
`evaluate` and `solve_spot`; other models expose an empty list. This describes
compiled capability, not account entitlement or live deployment. See
[scenario availability and usage](SCENARIOS.md).
