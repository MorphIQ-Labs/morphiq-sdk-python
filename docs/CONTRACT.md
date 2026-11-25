# Contract ownership and handoff

The API repository's services/api/openapi.json remains the reviewed HTTP source.
This SDK consumes a versioned artifact without owning another schema or installing
the numerical engines. The SDK is a JSON client; it does not consume the API's
Protobuf or gRPC contract.

[SDK #2](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2)
coordinates the producer/import workflow with
[API #106](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106).
contracts/openapi.json contains the reviewed snapshot byte-for-byte.
contracts/provenance.json records its digest, API source commit, contract
version and covered operations. This snapshot is the API **0.10.0** contract
(ADR 0011 naming, [API #161](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/161)),
tag `v0.10.0` (commit `4809233ade17132517a74dfc0ea4aebb087386d9`), SHA-256
`68985d43f276fe525f46fbc9dc650a172f1303298bcc831da59f8cfee2dbb4c8`. It was copied
from the immutable v0.10.0 source and is byte-identical to the deployed production
document. The beta wire contract version remains
`0.1.0` (**API v1 · Beta**); API and SDK release versions are separate. The SDK
treats `metadata.contract.version` as an opaque label (production reports
`0.1.0`; fixtures recorded from an earlier native build report `v1`) and identifies the exact revision by `metadata.contract.sha256`. SDK tests and builds use the offline snapshot without private
repository or numerical engine access.

## Coverage

The SDK covers 19 operations, each spelled by its canonical `collection.method`
id:

| Operation id | Route | SDK method |
| --- | --- | --- |
| `options.price` | `POST /v1/options:price` | `client.options.price` |
| `options.batch_price` | `POST /v1/options:batch-price` | `client.options.batch_price` |
| `options.implied_volatility` | `POST /v1/options:implied-volatility` | `client.options.implied_volatility` |
| `options.batch_implied_volatility` | `POST /v1/options:batch-implied-volatility` | `client.options.batch_implied_volatility` |
| `options.greeks` | `POST /v1/options:greeks` | `client.options.greeks` |
| `options.batch_greeks` | `POST /v1/options:batch-greeks` | `client.options.batch_greeks` |
| `options.standard_greeks` | `POST /v1/options:standard-greeks` | `client.options.standard_greeks` |
| `options.batch_standard_greeks` | `POST /v1/options:batch-standard-greeks` | `client.options.batch_standard_greeks` |
| `options.implied_greeks` | `POST /v1/options:implied-greeks` | `client.options.implied_greeks` |
| `options.batch_implied_greeks` | `POST /v1/options:batch-implied-greeks` | `client.options.batch_implied_greeks` |
| `series.identify_regime` | `POST /v1/series:identify-regime` | `client.series.identify_regime` |
| `models.list` | `GET /v1/models` | `client.models.list` |
| `rate_card.get` | `GET /v1/rate-card` | `client.rate_card.get` |
| `rate_card.quote` | `POST /v1/rate-card:quote` | `client.rate_card.quote` |
| `options.revalue` | `POST /v1/options:revalue` | `client.options.revalue` |
| `options.solve_scenario` | `POST /v1/options:solve-scenario` | `client.options.solve_scenario` |
| `books.revalue` | `POST /v1/books:revalue` | `client.books.revalue` |
| `books.explain` | `POST /v1/books:explain` | `client.books.explain` |
| `books.solve_scenario` | `POST /v1/books:solve-scenario` | `client.books.solve_scenario` |

All served v1 operations are covered. Tests require the coverage inventory to match
the pinned schema. Scenario outcome unions are checked variant-by-variant.

## Checks against the snapshot

Hand-written models are named after the contract's schemas. Tests check that
every covered object schema has a same-named model with exactly its fields, that
known enum values match the contract's enums, and that the SDK's canonical
operation ids match the quote endpoint's `operation` values and the covered
routes. Serialized requests and recorded responses are validated against the
pinned schema. Digest/version checks detect accidental snapshot changes.
Intentional upgrades need reviewed provenance and tests; this is not a complete
future-operation compatibility generator.

Generate repetitive wire models where useful. Deliberately review the Python
interface, errors, lifecycle and documentation. Contract updates produce a diff
and flag missing operation coverage/incompatibilities without overwriting
hand-written behavior.

## Wire conventions the SDK preserves

- Requests are closed: unknown fields and enum values are rejected locally.
  Absent optional members are omitted, never sent as null.
- Responses are open. Additive fields are retained. Response enums may gain
  values: an unknown value is kept as a plain string, and an unknown variant of a
  tagged union (regime heads, crisis status, batch outcome status, validity bound
  kind) is kept as `Unrecognized`, `BatchUnrecognized` or
  `UnrecognizedValidityBound` with its wire members.
- The API omits absent members and never sends null. `exclude_unset=True`
  reproduces exactly what the server sent.
- Numerical results, diagnostics, ordered batch results, request IDs,
  engine/model provenance (`result.model`, `metadata.engines`) and commercial
  evidence (`metadata.billing`) are preserved unchanged.
- Errors are RFC 9457 problems carrying the shared `metadata`.

The regime contract has its own semantics; pricing batching/transport/error
assumptions do not automatically apply. Numerical inference, model selection
and commercial policy remain server-owned.

## Fixtures and controlled-service testing

Public CI uses reviewed synthetic fixtures. Controlled service integration can
run in the API's private pipeline with both source identities recorded. Neither
needs a production key here or establishes a public deployment.

Pricing, Greeks, standard-Greeks, implied-volatility, implied-Greeks, batch and
model-catalog fixtures contain synthetic inputs evaluated by a native release
build of the pinned commit (MorphIQ Risk 0.46.1, MorphIQ Analytics 0.7.6) in
open admission. Tests verify unscaled Greeks and explicit unavailable-quantity
reasons, IV solver diagnostics and residual bases, model identity, metadata,
error evidence and sync/async parity against native JSON. American Auto without
cash events resolves to BS1993.

Regime tests use a hand-authored synthetic wire fixture, not a recorded model
prediction. They cover the three head statuses, ordered scores, input and timing
facts, model provenance and service errors. Optional controlled-service
integration checks SDK results against native JSON; it does not expect synthetic
fixture scores.

An open-admission service has no signed policy publication, so it refuses the
rate-card utilities with `policy_unavailable`. Rate-card and quote tests use
synthetic responses in the contract's shape.

Scenario and book fixtures are recorded from the same native API v0.10.0 tag,
including all seven solve coordinates, position P&L and Greek targets, American
pricing, duplicate scenarios, partial errors and unresolved coverage. The partial
error fixture deliberately echoes a negative spot: the service returns that
invalid input even though OpenAPI reuses a positive-spot input schema for the
response. The SDK preserves the error and its inputs; it does not discard the row.
Quote fixtures are synthetic, clearly marked, and do not assert live policy rates.
