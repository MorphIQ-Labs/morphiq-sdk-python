# Python client and model reference

This is the Python interface to the [reviewed API contract](CONTRACT.md).
The SDK validates wire types and preserves server results; numerical models,
admission, account limits and commercial charges belong to the service.
See the [guide index](README.md) for runnable examples and result interpretation.

## Clients and lifecycle

Import `MorphIQ` or `AsyncMorphIQ` from `morphiq_sdk`. Both constructors accept
these keyword-only arguments:

| Argument | Default and behavior |
| --- | --- |
| `api_key: str \| None` | Explicit key, otherwise `MORPHIQ_API_KEY`. Required unless open development access is explicitly enabled. |
| `base_url: str \| None` | Explicit URL, otherwise `MORPHIQ_API_BASE_URL`, otherwise `https://api.morphiqlabs.com`. Use the API root, not an operation path. |
| `timeout: float \| httpx.Timeout` | `30.0` seconds per connection/read/write/pool wait, not a total request deadline. |
| `allow_unauthenticated: bool` | `False`. Set `True` only for a controlled open development service; it does not bypass authentication on a protected service. |
| `transport` | `None`. Optional `httpx.BaseTransport` for sync or `httpx.AsyncBaseTransport` for async, including controlled test transports. |

Use `with MorphIQ() as client` or `async with AsyncMorphIQ() as client` to close
connection pools. Explicit alternatives are `client.close()` and
`await client.aclose()`. Every async numerical method must be awaited. Async
numerical calls do not add concurrency or retries; workflow concurrency is explicit.
HTTP redirects are disabled;
proxy and CA environment variables are not applied automatically.

The Python client reads process environment variables; it does **not** load a
`.env` file. Docker Compose reads the repository's `.env` and passes configured
values into the notebook container. An exported shell variable takes precedence
in Compose. See [credentials and Docker configuration](NOTEBOOKS.md).

## Numerical methods

These names exist on both clients. Each call makes one HTTP POST request.
All request/response classes below are exported from `morphiq_sdk`.

| Method | Request type | Response type | Route |
| --- | --- | --- | --- |
| `price(request)` | `PriceRequest` | `PriceResponse` | `/v1/price` |
| `greeks(request)` | `GreeksRequest` | `GreeksResponse` | `/v1/greeks` |
| `implied_volatility(request)` | `ImpliedVolatilityRequest` | `ImpliedVolatilityResponse` | `/v1/implied-volatility` |
| `analytics(request)` | `AnalyticsRequest` | `AnalyticsResponse` | `/v1/analytics` |
| `regime(request)` | `RegimeRequest` | `RegimeResponse` | `/v1/regime` |
| `price_batch(request)` | `BatchPriceRequest` | `BatchPriceResponse` | `/v1/price:batch` |
| `greeks_batch(request)` | `BatchGreeksRequest` | `BatchGreeksResponse` | `/v1/greeks:batch` |
| `implied_volatility_batch(request)` | `BatchImpliedVolatilityRequest` | `BatchImpliedVolatilityResponse` | `/v1/implied-volatility:batch` |
| `analytics_batch(request)` | `BatchAnalyticsRequest` | `BatchAnalyticsResponse` | `/v1/analytics:batch` |

`analytics()` uses the API's native combined operation. The SDK does not chain
price, IV and Greeks requests to reproduce it. Batch methods likewise send one
batch envelope; they do not split requests or start parallel calls.

## Workflow factories

Both clients expose `price_workflow(requests, *, chunk_size)`,
`greeks_workflow(requests, *, chunk_size)`,
`implied_volatility_workflow(requests, *, chunk_size)` and
`analytics_workflow(requests, *, chunk_size)`. Each takes a sequence of the
corresponding single-operation request models and validates/snapshots all inputs
without sending HTTP requests.

Sync factories return `BatchWorkflow`; async factories return
`AsyncBatchWorkflow`. Call `workflow.run()` or `await workflow.run()` once while
the client is open. Sync execution is sequential. Async factories also accept
`max_concurrency=1`; larger positive integers opt into bounded asyncio workers.
Request-level failures stop new submissions while in-flight calls drain; caller
cancellation cancels and awaits the workers.
`ChunkAttempt` records preserve results, errors, original input ranges and each
request's commercial charge. See [workflow properties, exact CU accounting and
stopping behavior](WORKFLOWS.md).

## Option request fields

`PriceRequest`, `GreeksRequest`, `ImpliedVolatilityRequest` and `AnalyticsRequest`
share these fields:

| Field | Type/default | Meaning |
| --- | --- | --- |
| `exercise_style` | Required: `"european"` or `"american"` | Exercise convention. |
| `option_type` | Required: `"call"` or `"put"` | Payoff type. |
| `spot`, `strike` | Required finite numbers | Underlying and strike prices in the same currency. |
| `time_to_expiry_years` | Required finite number | Time from valuation in years. No date/day-count conversion is performed. |
| `risk_free_rate`, `dividend_yield` | Required finite numbers | Annual rate and continuous yield as decimals; 0.05 means 5%. |
| `pricing_model` | `"auto"` | Also accepts `"black_scholes_merton"`, `"bjerksund_stensland_2002"`, `"bjerksund_stensland_1993"`. The service validates compatibility and chooses the resolved model. |
| `model_version` | Optional string or explicit null | Forwarded to the service; omitted unless supplied. |
| `dividend_schedule` | Optional list of `DividendEvent` | Cash per share at each ex-dividend time. Wire maximum: 16 events. Support and domain constraints remain server-owned. |

Each `DividendEvent` contains finite `ex_time_years` and `cash_amount` fields.
Use the same per-share currency basis as spot/strike. No contract multiplier,
currency conversion or dividend adjustment is performed by the SDK.

Operation-specific fields:

| Request | Additional fields |
| --- | --- |
| `PriceRequest`, `GreeksRequest` | Required finite `volatility`, as a decimal fraction; 0.20 means 20%. |
| `ImpliedVolatilityRequest` | Required finite `market_price`, the option premium per share. `volatility` is not accepted. |
| `AnalyticsRequest` | Required finite `volatility`; optional finite `market_price` or null. With a premium, the API solves IV and ignores supplied volatility. Without a premium, it uses supplied volatility. |

Request models reject unknown fields, malformed types and non-finite numbers.
Model-domain checks remain server-side. Attributes are frozen, but contained
lists remain editable and are revalidated by `to_wire()` before submission.
Omitted fields stay omitted; explicit null and empty values remain explicit.
`pricing_model` is always sent, including its convenience default `"auto"`.
Use constructors or `model_validate()` for validation; Pydantic's `model_copy`
updates do not themselves validate changed values.

## Batch and regime requests

Every batch envelope requires `requests`, a list of the corresponding single
request type. The reviewed wire schema accepts 1–1024 items; service/account
limits can be lower. Empty/oversized lists and invalid list edits fail locally.
The SDK preserves item order and single-request omission/null semantics.
See [all four batch construction examples](BATCH.md#constructing-each-batch-type).

`RegimeRequest` takes `prices`, an ordered list of at least 512 finite positive
prices, and optional `as_of: str | None` (maximum 64 characters). The service
validates timestamp semantics, request byte limits and its consumed window.
It expects comparable split-adjusted prices without cash-dividend total-return
adjustment, not returns. See [regime semantics](REGIME.md) for exact timestamps,
window selection and interpretation of head scores.

## Response access

Single-operation responses expose `result` and `metadata`. Batch responses expose
`results` and one `metadata` block for the whole request. `Greeks`, `GreeksResult`,
`ImpliedVolatilityResult` and `AnalyticsResult` are exported at the package root
for type annotations; additional nested models live in `morphiq_sdk.models`.
`morphiq_sdk.__version__` identifies the installed SDK, independently of server
and engine versions in response metadata.

| Result | Main fields |
| --- | --- |
| Pricing | `price`, `exercise_style`, `option_type`, `pricing_model`, `model_version` |
| Greeks | `price`, `greeks`, `pricing_model`, `model_version`; `greeks` has delta, gamma, theta, vega, rho, vanna, volga, charm, veta and color in [raw API units](GREEKS.md#units). |
| IV | `implied_volatility`, `iterations`, `used_fallback`, `residual`, `residual_basis`, `pricing_model`, `model_version`; [interpretation](IMPLIED_VOLATILITY.md#interpreting-the-result). |
| Analytics | `price`, `greeks`, `pricing_model`, `model_version`, optional/null nested `implied_volatility` containing the IV result. |
| Regime | `score_contract`, `decision`, `direction`, `state`; each head has an explicit status and conditional prediction/reason. [Head semantics](REGIME.md#request-and-result-semantics). |
| Batch item | `BatchSuccess`: `index`, `status="success"`, typed `result`; `BatchFailure`: `index`, `status="error"`, `error` with code, message and optional field. |

Pricing-family metadata contains request/API/engine identities, `engines`,
internal `units_charged` and `compute_schedule_version`. Regime metadata instead
includes model provenance and consumed-window indices.
Both preserve optional commercial fields: `fcu_quoted`, `fcu_charged`,
`fcu_schedule_id`, `fcu_schedule_version`, `policy`,
`remaining_fcu_instance_estimate`, `budget_period` and `budget_reset_at`.

Count `fcu_charged` once per response, including a combined result or a batch.
Missing/null means unreported, not zero. Neither `fcu_quoted` nor internal
`units_charged` is an additional commercial charge. The remaining estimate is
not an authoritative account balance. See [CU accounting](ANALYTICS.md#commercial-cu).

`model_dump(exclude_unset=True)` and `model_dump_json(exclude_unset=True)` retain
additive fields and omitted/null distinctions. Unknown resolved model names are
preserved. `raw_body` and `headers` retain response evidence with reflected API
credentials redacted; they do not retain the outgoing credential-bearing request.
Malformed required result fields raise an error rather than being replaced with
zero. Batch outcome count/order/index mismatches also raise `ResponseError`.

## Exceptions and throttling

| Exception | Meaning and evidence |
| --- | --- |
| Pydantic `ValidationError` / `ValueError` | Invalid local request or configuration. No HTTP call when validation fails before submission. |
| `MorphIQError` | Common base for SDK transport/API/response exceptions. |
| `APIError` | Non-200 response. Inspect `status_code`, `code`, `message`, `field`, `request_id`, optional `metadata`, `body`, `headers`, `retry_after`. A nonstandard gateway body may lack typed metadata/error fields. |
| `RateLimitError` | Every HTTP 429; subclasses `APIError`. `retry_after` is the raw header; `retry_delay(now=...)` interprets seconds or an HTTP date, returning `None` for absent/invalid guidance. No waiting or resubmission occurs. |
| `TransportError` | No complete response; execution/charge may be unknown. |
| `RequestTimeout` | A timeout; subclasses `TransportError`. A timeout does not prove no execution or no charge. |
| `ResponseError` | A malformed success response or invalid batch correlation. Inspect `request_id`, `body`, `headers` and independently valid pricing-family `metadata`, if available. |

Catch `RateLimitError` before `APIError`, and `RequestTimeout` before
`TransportError`, when you need specialized handling. See the
[complete error-handling pattern](QUICKSTART.md#configuration-and-errors) and
[429 scheduling guidance](BATCH.md#http-429). No automatic retries, request splitting
or failed-item replay occurs. Async cancellation propagates to the caller.

## Optional price data

`PriceProvider` is a standard-library protocol. `PriceBar` and `PriceHistory`
are immutable dataclasses; `PriceInterval` and `PriceAdjustment` describe their
supported string values. They do not fetch data or call MorphIQ.
`morphiq_sdk_yahoo.YahooPriceProvider` implements the protocol using the optional
`market-data` extra. Its `history(symbol, *, start, end, interval="1d")` returns
`PriceHistory`, including `.bars`, `.prices`, `.latest`, symbol/source/interval
and adjustment identity. See [provider setup and semantics](PRICE_PROVIDERS.md).

## Optional pandas adapter

`morphiq_sdk.pandas` provides `batch_to_frames(response, *, identifiers=None)`
and `workflow_to_frames(workflow, *, identifiers=None)`. Both return `BatchFrames`
with separate `results` and `requests` DataFrames, execution `state`,
`reported_fcu_charged`, `unknown_charge_count` and `total_fcu_charged`.
The optional `pandas` extra is required only at conversion time. See the
[table schema, units, missing-value and cost semantics](PANDAS.md).
