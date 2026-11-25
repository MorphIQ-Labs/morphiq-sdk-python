# Available models

```python
from morphiq_sdk import MorphIQ

with MorphIQ() as client:
    catalog = client.models.list()
for model in catalog.models:
    print(model.id, model.model_version, model.operations, model.constraints)
```

`client.models.list()` calls `models.list` (`GET /v1/models`). This public GET
sends no API key, even when a key is configured. `AsyncMorphIQ` provides the same
method with `await`. The catalog includes engine/model versions, Greek units,
supported exercise styles and dividends, constraints, guidance and per-quantity
`validity` contracts, with `validity_symbols` naming the symbols those contracts
use. Each model's `operations` lists canonical operation ids such as
`options.price` or `options.batch_greeks`. The catalog describes compiled service
capabilities; account entitlements and rates come from the authenticated
`client.rate_card.get()` and `client.rate_card.quote(request)` methods.

| Model id | Algorithm pin | Operations |
| --- | --- | --- |
| `black_scholes_merton` | `black_scholes_merton/1` | Price, IV, Greeks, standard Greeks, implied Greeks and their batches |
| `bjerksund_stensland_1993` | `bjerksund_stensland_1993/1` | Price, IV, Greeks, standard Greeks, implied Greeks and their batches |
| `black_scholes_merton_qdfp` | `qd_fixed_point/1` | Price, IV |
| `black_scholes_merton_fd` | `cash_dividend_american/1` | Price, IV |

The catalog also lists scenario and book operations for BSM and BS1993; this SDK
release does not cover those operations. Select a model with
`ModelSelection(id=...)`, optionally pinning `version`; results report the
resolved model as `result.model.id` and `result.model.version`.

The finite-difference model supports cash-dividend schedules in
`Market.dividends`. The input enum contains only the selectors above and `auto`:
the former `qd_fixed_point` and `cash_dividend_american` selector aliases and the
retired `bjerksund_stensland_2002` model are not accepted, and the SDK rejects
them locally before sending. `qd_fixed_point/1` and `cash_dividend_american/1`
remain the algorithm pins (`model.version`) of the QdFp and cash-dividend models.

`auto` selects BSM for European options and BS1993 for American options without
cash-dividend events. A nonempty American cash-dividend schedule selects finite
difference. QdFp requires explicit selection. Unsupported operations and a batch
containing QdFp or the cash-dividend model receive HTTP 400 (`APIError`); batches
contain 1–100 items. Account limits may be lower.

A Greek may be omitted with an entry in `greeks.unavailable`, whose value is a
problem with `code`, `detail` and optionally `field`. Python exposes the omitted
quantity as `None`; it is never replaced by zero. `model_dump(exclude_unset=True)`
preserves wire omission and all reasons. DataFrame numeric cells remain missing,
with reasons available in the `result.greeks.unavailable` column and full `outcome`.

Response enums may gain values. A newer model id in `model.id` or the catalog is
kept as a plain string, and a validity bound of an unknown `kind` is kept as
`UnrecognizedValidityBound`. The API owns these capabilities and may evolve them.
Query discovery for current capabilities and preserve actionable server errors
instead of copying this table into client admission logic.
