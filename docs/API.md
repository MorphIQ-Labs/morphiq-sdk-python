# Python client and model reference

This is the Python interface to the [reviewed API contract](CONTRACT.md).
The SDK validates wire types and preserves server results; numerical models,
admission, account limits and commercial charges belong to the service.
See the [guide index](README.md) for runnable examples and result interpretation,
and the [0.10.0 migration guide](API_0_10_ADOPTION.md) for changes from SDK 0.2.1.

## Clients and lifecycle

Import `MorphIQ` or `AsyncMorphIQ` from `morphiq_sdk`. Both constructors accept
these keyword-only arguments:

| Argument | Default and behavior |
| --- | --- |
| `api_key: str \| None` | Explicit key, otherwise `MORPHIQ_API_KEY`. Required for protected calls unless open development access is explicitly enabled. Public `models.list()` needs no key. |
| `base_url: str \| None` | Explicit URL, otherwise `MORPHIQ_API_BASE_URL`, otherwise `https://api.morphiqlabs.com`. Use the API root, not an operation path. |
| `timeout: float \| httpx.Timeout` | `30.0` seconds per connection/read/write/pool wait, not a total request deadline. |
| `allow_unauthenticated: bool` | `False`. Set `True` only for a controlled open development service; it does not bypass authentication on a protected service. |
| `transport` | `None`. Optional `httpx.BaseTransport` for sync or `httpx.AsyncBaseTransport` for async, including controlled test transports. |

Use `with MorphIQ() as client` or `async with AsyncMorphIQ() as client` to close
connection pools. Explicit alternatives are `client.close()` and
`await client.aclose()`. Every async method must be awaited. Async calls do not
add concurrency or retries; workflow concurrency is explicit. HTTP redirects are
disabled; proxy and CA environment variables are not applied automatically.

The Python client reads process environment variables; it does **not** load a
`.env` file. Docker Compose reads the repository's `.env` and passes configured
values into the notebook container. An exported shell variable takes precedence
in Compose. See [credentials and Docker configuration](NOTEBOOKS.md).

## Operations by collection

Each client groups its operations by the contract's collections:
`client.options`, `client.books`, `client.series`, `client.models` and `client.rate_card`. A
method spells the operation's canonical id: `client.options.batch_price(...)` is
`options.batch_price`, served at `POST /v1/options:batch-price`. The quote
endpoint and the model catalog's `operations` list use the same ids;
`operation_id(request)` returns the id a typed request executes.

This grouping follows ADR 0011's one-id-per-operation scheme. It also keeps
operations that share a method name in different collections distinct (`options.revalue` and `books.revalue`, `options.solve_scenario`
and `books.solve_scenario`). The SDK's other conventions are unchanged: typed
request models, sync/async parity, explicit batches and workflows, and no
automatic retries.

Each call makes one HTTP request. The async client has the same methods; await
them. All request/response classes below are exported from `morphiq_sdk`.

| Method | Request type | Response type | Route |
| --- | --- | --- | --- |
| `options.price(request)` | `OptionsPriceRequest` | `OptionsPriceResponse` | `POST /v1/options:price` |
| `options.implied_volatility(request)` | `OptionsImpliedVolatilityRequest` | `OptionsImpliedVolatilityResponse` | `POST /v1/options:implied-volatility` |
| `options.greeks(request)` | `OptionsGreeksRequest` | `OptionsGreeksResponse` | `POST /v1/options:greeks` |
| `options.standard_greeks(request)` | `OptionsStandardGreeksRequest` | `OptionsStandardGreeksResponse` | `POST /v1/options:standard-greeks` |
| `options.implied_greeks(request)` | `OptionsImpliedGreeksRequest` | `OptionsImpliedGreeksResponse` | `POST /v1/options:implied-greeks` |
| `options.batch_price(request)` | `OptionsBatchPriceRequest` | `OptionsBatchPriceResponse` | `POST /v1/options:batch-price` |
| `options.batch_implied_volatility(request)` | `OptionsBatchImpliedVolatilityRequest` | `OptionsBatchImpliedVolatilityResponse` | `POST /v1/options:batch-implied-volatility` |
| `options.batch_greeks(request)` | `OptionsBatchGreeksRequest` | `OptionsBatchGreeksResponse` | `POST /v1/options:batch-greeks` |
| `options.batch_standard_greeks(request)` | `OptionsBatchStandardGreeksRequest` | `OptionsBatchStandardGreeksResponse` | `POST /v1/options:batch-standard-greeks` |
| `options.batch_implied_greeks(request)` | `OptionsBatchImpliedGreeksRequest` | `OptionsBatchImpliedGreeksResponse` | `POST /v1/options:batch-implied-greeks` |
| `series.identify_regime(request)` | `SeriesIdentifyRegimeRequest` | `SeriesIdentifyRegimeResponse` | `POST /v1/series:identify-regime` |
| `models.list()` | none | `ModelsListResponse` | `GET /v1/models` (public) |
| `rate_card.get(*, rate_class=None, model=None)` | none | `RateCardGetResponse` | `GET /v1/rate-card` |
| `rate_card.quote(request)` | any request above | `RateCardQuoteResponse` | `POST /v1/rate-card:quote` |

Every numerical method accepts an optional keyword `max_cu`, sent as
`X-MorphIQ-Max-CU`; see [the rate card guide](RATE_CARD.md).
`options.implied_greeks()` uses the API's single combined operation: it solves IV
from the premium, then evaluates price and all ten Greeks at it. The SDK does not
chain requests to reproduce it. Batch methods send one `items` envelope; they do
not split requests or start parallel calls.

Scenario and book methods use the same transport, authentication, `max_cu` and
error semantics. See [scenario and book inputs, results and examples](SCENARIOS.md).

| Method | Request | Response |
| --- | --- | --- |
| `client.options.revalue` | `OptionsRevalueRequest` | `OptionsRevalueResponse` |
| `client.options.solve_scenario` | `OptionsSolveScenarioRequest` | `OptionsSolveScenarioResponse` |
| `client.books.revalue` | `BooksRevalueRequest` | `BooksRevalueResponse` |
| `client.books.explain` | `BooksExplainRequest` | `BooksExplainResponse` |
| `client.books.solve_scenario` | `BooksSolveScenarioRequest` | `BooksSolveScenarioResponse` |

`BooksExplainRequest` uses the same wire body as `BooksRevalueRequest`, but its
separate type makes `rate_card.quote(request)` select `books.explain` correctly.
`BooksExplainResponse` shares the book revaluation shape with attribution.

## Workflow factories

`client.options` exposes `price_workflow(requests, *, chunk_size)`,
`implied_volatility_workflow(...)`, `greeks_workflow(...)`,
`standard_greeks_workflow(...)` and `implied_greeks_workflow(...)`. Each takes a
sequence of the corresponding single-operation request models and
validates/snapshots all inputs without sending HTTP requests.

Sync factories return `BatchWorkflow`; async factories return
`AsyncBatchWorkflow`. Call `workflow.run()` or `await workflow.run()` once while
the client is open. Sync execution is sequential. Async factories also accept
`max_concurrency=1`; larger positive integers opt into bounded asyncio workers.
Request-level failures stop new submissions while in-flight calls drain; caller
cancellation cancels and awaits the workers.
`ChunkAttempt` records preserve results, errors, original input ranges and each
request's `charged_cu`. See [workflow properties, exact CU accounting and
stopping behavior](WORKFLOWS.md).

## Option requests

Every option request has `option`, `market` and `model`, plus either
`volatility` (forward operations) or `market_price` (inverse operations).

| Model | Field | Type/default | Meaning |
| --- | --- | --- | --- |
| `Option` | `type` | Required: `"call"` or `"put"` | Payoff type. |
| `Option` | `exercise_style` | Required: `"european"` or `"american"` | Exercise convention. |
| `Option` | `strike` | Required finite number | Strike in the spot's currency. |
| `Option` | `time_to_expiry_years` | Required finite number | Time from valuation in years. No date/day-count conversion is performed. |
| `Market` | `spot` | Required finite number | Underlying price. |
| `Market` | `risk_free_rate`, `dividend_yield` | Required finite numbers | Continuously compounded annual rate and yield as decimals; 0.05 means 5%. |
| `Market` | `dividends` | Empty list of `DividendEvent` | Discrete cash dividends; cash-dividend model only. At most 16. An empty list is omitted from the request. |
| `ModelSelection` | `id` | `"auto"` | `"auto"`, `"black_scholes_merton"`, `"bjerksund_stensland_1993"`, `"black_scholes_merton_qdfp"` or `"black_scholes_merton_fd"`. |
| `ModelSelection` | `version` | Optional string | Algorithm pin such as `qd_fixed_point/1`; omit to use the current version. |

Each `DividendEvent` contains finite `ex_time_years` and `cash_amount` fields.
Use the same per-share currency basis as spot/strike. No contract multiplier,
currency conversion or dividend adjustment is performed by the SDK.

| Request | Operation-specific field |
| --- | --- |
| `OptionsPriceRequest`, `OptionsGreeksRequest`, `OptionsStandardGreeksRequest` | Required finite `volatility`, as a decimal fraction; 0.20 means 20%. |
| `OptionsImpliedVolatilityRequest`, `OptionsImpliedGreeksRequest` | Required finite `market_price`, the option premium per share. `volatility` is not accepted. |

Request models reject unknown fields, unknown enum values, malformed types and
non-finite numbers. Model-domain checks remain server-side. Attributes are frozen,
but contained lists remain editable and are revalidated by `to_wire()` before
submission. Absent optional members are omitted, never sent as null. `model` is
always sent, including its default `{"id": "auto"}`. Use constructors or
`model_validate()` for validation; Pydantic's `model_copy` updates do not
themselves validate changed values.

## Batch and regime requests

Every batch envelope takes `items`, a list of the corresponding single request
type. The reviewed wire schema accepts 1–100 items; service/account limits can be
lower. Empty/oversized lists and invalid list edits fail locally. The SDK
preserves item order. See [batch construction examples](BATCH.md#constructing-each-batch-type).

`SeriesIdentifyRegimeRequest` takes `prices`, an ordered list of at least 512
finite positive prices, and optional `as_of: str | None` (maximum 64 characters,
omitted when `None`). The service validates timestamp semantics, request byte
limits and its consumed window. It expects comparable split-adjusted prices
without cash-dividend total-return adjustment, not returns. See
[regime semantics](REGIME.md).

## Response access

Single-operation responses expose `result` and `metadata`. Batch responses expose
`results` and one `metadata` block for the whole request. Result and metadata
types are exported at the package root; additional nested models live in
`morphiq_sdk.models`. Class names match the contract's schema names.
`morphiq_sdk.__version__` identifies the installed SDK, independently of server
and engine versions in response metadata.

| Result | Main fields |
| --- | --- |
| `PriceResult` | `price`, `model` (`ModelIdentity`: `id`, `version`) |
| `GreeksResult` | `price`, `greeks`, `model`; `greeks` has delta, gamma, theta, vega, rho, vanna, volga, charm, veta and color in [raw API units](GREEKS.md#units). |
| `StandardGreeksResult` | `price`, `greeks` (delta, gamma, theta, vega, rho), `model` |
| `ImpliedVolatilityResult` | `implied_volatility`, `iterations`, `used_fallback`, `residual`, `residual_basis`, `model`; [interpretation](IMPLIED_VOLATILITY.md#interpreting-the-result). |
| `ImpliedGreeksResult` | `price`, `greeks`, `model` and nested `implied_volatility` with the IV solve. |
| `RegimeResult` | `score_contract`, `decision`, `direction`, `state`, `volatility`, `crisis_score_contract`, `crisis`, plus `input`, `timing`, `provenance` and `response_contract_version`. [Head semantics](REGIME.md#request-and-result-semantics). |
| Batch item | `BatchSuccess`: `index`, `status="success"`, typed `result`; `BatchFailure`: `index`, `status="error"`, `error` as a `Problem`; `BatchUnrecognized` for a status this SDK does not know. |

`ResponseMetadata` is shared by every response, success or error:

| Field | Meaning |
| --- | --- |
| `request_id` | Service request identifier; equals the `x-request-id` header. Quote it for support. |
| `service_version` | Service release that produced the response. |
| `contract` | `version` label and `sha256` of the served HTTP contract. |
| `engines` | Numerical engines selected, with revisions; absent when none was selected. |
| `billing` | `quoted_cu`, `charged_cu` and the `rate_card` (`id`, `version`) on metered responses. |
| `budget` | `period`, `resets_at` and `remaining_estimate_cu` on metered responses. |
| `policy` | `plan` and `revision` of the pinned policy on metered responses. |

`metadata.charged_cu` is shorthand for `metadata.billing.charged_cu`. Count it
once per response, including an implied-Greeks result or a batch. Missing means
unreported, not zero. `quoted_cu` is not an additional charge, and
`remaining_estimate_cu` is not an authoritative account balance. See
[CU accounting](IMPLIED_GREEKS.md#commercial-cu).

The API omits absent members; it never sends null. `model_dump(exclude_unset=True)`
and `model_dump_json(exclude_unset=True)` reproduce what the server sent,
including additive fields. Response enums may gain values: a value this SDK does
not list (for example a newer `model.id`) is kept as a plain string, and a
response variant it does not know is kept as `Unrecognized`, `BatchUnrecognized`
or `UnrecognizedValidityBound` with all wire members. Treat such values as ones
your code does not handle. `raw_body` and `headers` retain response evidence with
reflected API credentials redacted; they do not retain the outgoing
credential-bearing request. Malformed required result fields raise an error
rather than being replaced with zero. Batch outcome count/order/index mismatches
also raise `ResponseError`.

## Exceptions and throttling

| Exception | Meaning and evidence |
| --- | --- |
| Pydantic `ValidationError` / `ValueError` | Invalid local request or configuration. No HTTP call when validation fails before submission. |
| `MorphIQError` | Common base for SDK transport/API/response exceptions. |
| `APIError` | Non-200 response, an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem. Inspect `status_code`, `code`, `title`, `detail`, `field`, `solve_trial`, `request_id`, `metadata`, the typed `problem` (`ErrorResponse`), `body`, `headers`, `retry_after`. A nonstandard gateway body leaves the problem attributes `None`. |
| `RateLimitError` | Every HTTP 429; subclasses `APIError`. `retry_after` is the raw header; `retry_delay(now=...)` interprets seconds or an HTTP date, returning `None` for absent/invalid guidance. No waiting or resubmission occurs. |
| `TransportError` | No complete response; execution/charge may be unknown. |
| `RequestTimeout` | A timeout; subclasses `TransportError`. A timeout does not prove no execution or no charge. |
| `ResponseError` | A malformed success response or invalid batch correlation. Inspect `request_id`, `body`, `headers` and independently valid `metadata`, if available. |

`field` names the public request path at fault, such as `market.spot`,
`option.strike` or `model.id`. Catch `RateLimitError` before `APIError`, and
`RequestTimeout` before `TransportError`, when you need specialized handling. See
the [complete error-handling pattern](QUICKSTART.md#configuration-and-errors) and
[429 scheduling guidance](BATCH.md#http-429). No automatic retries, request
splitting or failed-item replay occurs. Async cancellation propagates to the caller.

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
`reported_charged_cu`, `unknown_charge_count` and `total_charged_cu`.
The optional `pandas` extra is required only at conversion time. See the
[table schema, units, missing-value and cost semantics](PANDAS.md).

## Rate card and model catalog

`client.rate_card.get()` returns your active `RateCard` and
`client.rate_card.quote(request)` an exact `Quote` for a typed request, both
without executing or charging. See [the rate card and request quotes](RATE_CARD.md).
Public `client.models.list()` returns a typed `ModelsListResponse` without
authentication; see [model discovery](MODELS.md).
