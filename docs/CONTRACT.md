# Contract ownership and handoff

The API repository's services/api/openapi.json remains the reviewed HTTP source.
This SDK consumes a versioned artifact without owning another schema or installing
the numerical engines.

[SDK #2](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2)
coordinates the producer/import workflow with
[API #106](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106).
contracts/openapi.json now contains the reviewed snapshot byte-for-byte.
contracts/provenance.json records its digest, API source commit and contract
version. It was copied from immutable reviewed main source; automated published
artifact delivery remains #2. SDK tests and builds use the offline snapshot
without private repository or numerical engine access.

The SDK covers POST /v1/price, POST /v1/greeks, POST /v1/implied-volatility and
POST /v1/regime. Hand-written model field sets and serialized
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

Greeks and implied-volatility fixtures contain synthetic inputs evaluated by the
native service built from the pinned API commit. Tests verify all ten unscaled
Greeks, IV solver diagnostics and residual bases, model identity, metadata, error
evidence and sync/async parity against native JSON.
