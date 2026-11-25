# API 0.10.0 SDK adoption

This SDK targets the API 0.10.0 contract, pinned at API commit
`4809233ade17132517a74dfc0ea4aebb087386d9` (SHA-256
`68985d43f276fe525f46fbc9dc650a172f1303298bcc831da59f8cfee2dbb4c8`, contract
label `0.1.0`, **API v1 · Beta**). The contract gives every operation one
canonical `collection.method` id, splits option requests into `option`, `market`
and `model`, groups response metadata, and reports errors as RFC 9457 problems.
This is a breaking SDK change; SDK 0.2.1 remains the release for the earlier
contract. See [contract coverage](CONTRACT.md) and the
[client reference](API.md).

## Calls

| SDK 0.2.1 | This SDK | Route |
| --- | --- | --- |
| `client.price(r)` | `client.options.price(r)` | `POST /v1/options:price` |
| `client.greeks(r)` | `client.options.greeks(r)` | `POST /v1/options:greeks` |
| `client.greeks_standard(r)` | `client.options.standard_greeks(r)` | `POST /v1/options:standard-greeks` |
| `client.implied_volatility(r)` | `client.options.implied_volatility(r)` | `POST /v1/options:implied-volatility` |
| `client.analytics(r)` with `market_price` | `client.options.implied_greeks(r)` | `POST /v1/options:implied-greeks` |
| `client.analytics(r)` without `market_price` | `client.options.greeks(r)` | `POST /v1/options:greeks` |
| `client.price_batch(b)` | `client.options.batch_price(b)` | `POST /v1/options:batch-price` |
| `client.greeks_batch(b)` | `client.options.batch_greeks(b)` | `POST /v1/options:batch-greeks` |
| `client.greeks_standard_batch(b)` | `client.options.batch_standard_greeks(b)` | `POST /v1/options:batch-standard-greeks` |
| `client.implied_volatility_batch(b)` | `client.options.batch_implied_volatility(b)` | `POST /v1/options:batch-implied-volatility` |
| `client.analytics_batch(b)` | `client.options.batch_implied_greeks(b)` | `POST /v1/options:batch-implied-greeks` |
| `client.<op>_workflow(...)` | `client.options.<op>_workflow(...)`; `greeks_standard_workflow` is `standard_greeks_workflow`, `analytics_workflow` is `implied_greeks_workflow` | as the batch route |
| `client.regime(r)` | `client.series.identify_regime(r)` | `POST /v1/series:identify-regime` |
| `client.pricing_models()` | `client.models.list()` | `GET /v1/models` |
| `client.cost_schedule(operation=, model=)` | `client.rate_card.get(rate_class=, model=)` | `GET /v1/rate-card` |
| `client.quote(r)` | `client.rate_card.quote(r)` | `POST /v1/rate-card:quote` |

The async client changes the same way. `max_cu` is unchanged.

## Requests

| SDK 0.2.1 | This SDK |
| --- | --- |
| `PriceRequest`, `GreeksRequest`, `GreeksStandardRequest` | `OptionsPriceRequest`, `OptionsGreeksRequest`, `OptionsStandardGreeksRequest` |
| `ImpliedVolatilityRequest` | `OptionsImpliedVolatilityRequest` |
| `AnalyticsRequest` | `OptionsImpliedGreeksRequest` (requires `market_price`, takes no `volatility`) or `OptionsGreeksRequest` |
| `RegimeRequest` | `SeriesIdentifyRegimeRequest` |
| `Batch<Op>Request(requests=[...])` | `OptionsBatch<Op>Request(items=[...])` |
| `exercise_style`, `option_type`, `strike`, `time_to_expiry_years` | `option=Option(exercise_style=..., type=..., strike=..., time_to_expiry_years=...)` |
| `spot`, `risk_free_rate`, `dividend_yield`, `dividend_schedule` | `market=Market(spot=..., risk_free_rate=..., dividend_yield=..., dividends=[...])` |
| `pricing_model`, `model_version` | `model=ModelSelection(id=..., version=...)`, default `id="auto"` |
| `pricing_model="qd_fixed_point"` | `ModelSelection(id="black_scholes_merton_qdfp")` |
| `pricing_model="cash_dividend_american"` | `ModelSelection(id="black_scholes_merton_fd")` |
| `pricing_model="bjerksund_stensland_2002"` | Removed; use `bjerksund_stensland_1993` or `auto` |
| Explicit `None` values sent as null | Omitted; no request member is sent as null |

`volatility` stays on forward requests and `market_price` on inverse requests.
Unknown selectors are rejected locally. `qd_fixed_point/1` and
`cash_dividend_american/1` remain algorithm pins, used as `ModelSelection.version`
and reported in `result.model.version`.

## Results

| SDK 0.2.1 | This SDK |
| --- | --- |
| `result.pricing_model`, `result.model_version` | `result.model.id`, `result.model.version` |
| `result.exercise_style`, `result.option_type` | Removed; read them from your request |
| `PriceResponse`, `GreeksResponse`, ... | `OptionsPriceResponse`, `OptionsGreeksResponse`, ... |
| `GreeksStandard`, `GreeksStandardResult` | `StandardGreeks`, `StandardGreeksResult` |
| `AnalyticsResult` | `ImpliedGreeksResult` |
| `greeks.unavailable[name].message` | `greeks.unavailable[name].detail` (a `Problem`) |
| Batch `item.status == "success"` / `"error"` | Unchanged; an unknown status is `BatchUnrecognized` |
| `PricingModelCatalog`, `PricingModelDescriptor` | `ModelsListResponse`, `ModelDescriptor`; `aliases` and `batch_operations` are removed; `operations` lists canonical ids; `validity` and `validity_symbols` are added |
| `CostScheduleResponse`, `CostSchedule`, `CostRate` | `RateCardGetResponse`, `RateCard`, `Rate` (`operation` is `rate_class`) |
| `CostQuoteResponse`, `CostBreakdown`, `CostLine`, `ResolvedCostModel` | `RateCardQuoteResponse`, `Quote`, `QuoteLine` (`operation` is `rate_class`), `QuotedModel` |
| `fcu_*` fields (`total_fcu`, `fcu_per_unit`, ...) | Removed; use the `*_cu` names |
| `effective_until: null` | Omitted when open-ended |

## Metadata and charges

Every response, including regime responses and errors, carries one
`ResponseMetadata`:

| SDK 0.2.1 | This SDK |
| --- | --- |
| `api_version`, `engine_version` | Removed; `service_version` and `contract` (`version`, `sha256`) |
| `engines` | `engines`, absent when no numerical engine was selected |
| `cu_quoted` / `fcu_quoted` | `billing.quoted_cu` |
| `cu_charged` / `fcu_charged` | `billing.charged_cu` (shorthand `metadata.charged_cu`) |
| `cu_schedule_id`, `cu_schedule_version` | `billing.rate_card.id`, `billing.rate_card.version` |
| `remaining_cu_instance_estimate` | `budget.remaining_estimate_cu` |
| `budget_period`, `budget_reset_at` | `budget.period`, `budget.resets_at` |
| `policy.snapshot_id`, `policy.records` | Removed; `policy` has `plan` and `revision` |
| `units_charged`, `compute_schedule_version` | Removed |
| `ServiceErrorMetadata`, `RegimeMetadata` | `ResponseMetadata` |
| `ChunkAttempt.cu_charged` / `fcu_charged` | `ChunkAttempt.charged_cu` |
| `reported_cu_charged`, `total_cu_charged` (and `*_fcu_*`) | `reported_charged_cu`, `total_charged_cu` |
| pandas `cu_charged` / `fcu_charged` columns | `charged_cu` |

`charged_cu` keeps its meaning: count it once per response, and treat a missing
value as unreported, not zero.

## Errors

| SDK 0.2.1 | This SDK |
| --- | --- |
| `{"error": {...}, "metadata": {...}}` envelope (`ErrorEnvelope`, `ErrorDetails`) | RFC 9457 problem with `metadata` (`ErrorResponse`, `Problem`) |
| `APIError.message` | `APIError.detail` |
| `APIError.code`, `.field` | Unchanged; `field` names the public path, such as `market.spot` or `model.id` |
| — | `APIError.title`, `.solve_trial`, `.problem` |
| Batch `item.error.message` | `item.error.detail` |

## Regime

| SDK 0.2.1 | This SDK |
| --- | --- |
| Labels `UP`, `DOWN`, `NEUTRAL`, `LOWER_VOL`, `HIGHER_VOL` | `up`, `down`, `neutral`, `lower_vol`, `higher_vol` |
| `prediction: null` on non-available heads | `prediction` omitted |
| Crisis `score` / `episode_start_price_index: null` | Omitted when the status cannot have them |
| `metadata.response_contract_version`, `metadata.provenance` | `result.response_contract_version`, `result.provenance` |
| `metadata.received_price_count`, `window_price_count`, `price_count`, `return_count`, `consumed_price_range`, `observation_index`, `input_price_index`, `all_prices_consumed`, `return_type`, `return_unit`, `as_of` | `result.input.*` (`as_of` only when supplied) |
| `metadata.inference_time_us`, `metadata.crisis_time_us` | `result.timing.inference_us`, `result.timing.crisis_us` |

## Unknown response values

Response enums may gain values. The SDK keeps an unknown value, such as a newer
`model.id`, `residual_basis` or regime label, as a plain string, and an unknown
variant of a tagged union as `Unrecognized`, `BatchUnrecognized` or
`UnrecognizedValidityBound` with all its wire members. Handle the values you know
and treat others as unhandled, rather than failing the response.

## Scenarios and books

The SDK also covers `options.revalue`, `options.solve_scenario`, `books.revalue`,
`books.explain` and `books.solve_scenario`, sync and async. These are new SDK
methods; see [the scenario and book guide](SCENARIOS.md).
