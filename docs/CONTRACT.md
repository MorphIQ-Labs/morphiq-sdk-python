# Contract ownership and handoff

The API repository's services/api/openapi.json remains the reviewed HTTP source.
This SDK consumes a versioned artifact without owning another schema or installing
the numerical engines.

[SDK #2](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2)
coordinates the producer/import workflow with
[API #106](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106).
contracts/openapi.json now contains the reviewed snapshot byte-for-byte.
contracts/provenance.json records its digest, API source commit and contract
version. This candidate snapshot is from draft API MR !209, commit
`7b4f233b2222fbb95b2492d5c57dbde1ac32e571`, SHA-256
`38a0c933ea805f132bc4245867c3130c5a1db94e23cb4837872abf8c27e33ccc`. It is not yet deployed; SDK merge/release is held until the
matching API deployment is verified.
The beta wire contract version remains `0.1.0`; API and SDK release versions are separate.
It was copied byte-for-byte from immutable draft source; automated published
artifact delivery remains #2. SDK tests and builds use the offline snapshot
without private repository or numerical engine access.

The SDK covers POST /v1/price, POST /v1/greeks, POST /v1/implied-volatility,
POST /v1/analytics, POST /v1/greeks/standard, their five `:batch` routes,
POST /v1/regime, GET /v1/pricing/models, GET /v1/cost/schedule and
POST /v1/cost/quote, POST /v1/scenarios/evaluate and POST
/v1/scenarios/solve-spot (16 operations). Hand-written model field sets and serialized
requests/responses are checked against the pinned schema. Digest/version
checks detect accidental snapshot changes. Intentional upgrades need reviewed
provenance and tests; this is not a complete future-operation compatibility generator.

Generate repetitive wire models where useful. Deliberately review the Python
interface, errors, lifecycle and documentation. Contract updates produce a diff
and flag missing operation coverage/incompatibilities without overwriting
hand-written behavior.

Preserve omitted/null distinctions, numerical results, diagnostics, ordered
batch results, request IDs, engine/model provenance and optional CU metadata.
The regime contract has its own semantics; pricing batching/transport/error
assumptions do not automatically apply. Numerical inference, model selection
and commercial policy remain server-owned.

Public CI uses reviewed synthetic fixtures. Controlled service integration can
run in the API's private pipeline with both source identities recorded. Neither
needs a production key here or establishes a public deployment.

Regime tests use a hand-authored synthetic wire fixture, not a recorded model
prediction. They cover the three head statuses, ordered scores, consumed-range
metadata, model provenance and service errors. The reviewed OpenAPI bytes and
source identity are unchanged. Optional controlled-service integration checks
SDK results against native JSON; it does not expect synthetic fixture scores.

Greeks, implied-volatility and analytics fixtures contain synthetic inputs evaluated by the
native service at their recorded capture commit and revalidated against the
candidate API. Tests verify unscaled
Greeks and explicit unavailable-quantity reasons, IV solver diagnostics and residual bases, model identity, metadata, error
evidence and sync/async parity against native JSON.

Historical Greeks/IV/analytics/batch fixtures retain their original capture commit,
schema digest, request IDs and metadata. Their separate `validation` identity
records revalidation against the candidate contract and controlled native service.
Scenario fixtures were captured directly from the candidate protected preview;
all inputs and account keys are synthetic. No historical capture is relabeled as
a response produced by a newer commit.
