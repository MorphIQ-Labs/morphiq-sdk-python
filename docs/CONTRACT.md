# Contract ownership and handoff

The API repository's services/api/openapi.json remains the reviewed HTTP source.
This SDK consumes a versioned artifact without owning another schema or installing
the numerical engines.

[SDK #2](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2)
coordinates the producer/import workflow with
[API #106](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106).
contracts/openapi.json now contains the reviewed snapshot byte-for-byte.
contracts/provenance.json records its digest, API source commit and contract
version. This snapshot is from deployed API **v0.7.0**, commit
`525627cd2334053270214208a70d15450934e54b`, SHA-256
`89aed6a6d6af982251c2cdac455113228f0ccb823e693f7f3fa0e8709071d33a`.
The beta wire contract version remains `0.1.0`; API and SDK release versions are separate.
It was copied from immutable reviewed main source; automated published
artifact delivery remains #2. SDK tests and builds use the offline snapshot
without private repository or numerical engine access.

The SDK covers POST /v1/price, POST /v1/greeks, POST /v1/implied-volatility,
POST /v1/analytics, POST /v1/greeks/standard, their five `:batch` routes,
POST /v1/regime, GET /v1/pricing/models, GET /v1/cost/schedule and
POST /v1/cost/quote (14 operations). Hand-written model field sets and serialized
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
native service built from the pinned API commit. Tests verify unscaled
Greeks and explicit unavailable-quantity reasons, IV solver diagnostics and residual bases, model identity, metadata, error
evidence and sync/async parity against native JSON.

The current snapshot includes preferred `cu_*` commercial fields, deprecated
`fcu_*` aliases, the regime crisis detector and the low/high/crisis volatility
label. The client keeps older response support: omitted new regime fields are
`None`, never a fabricated prediction; omitted CU fields use the old alias when
reported. `exclude_unset=True` preserves what the server actually sent. The
retired capacity attributes remain optional Python compatibility fields and are
not part of the current wire contract. Scenario and book routes are not deployed
and are not part of this snapshot.

The v0.7.0 adoption refreshes synthetic numerical fixtures against a locked
native build of release `525627cd2334053270214208a70d15450934e54b`, with
Risk 0.45.0. American Auto without cash events now resolves to BS1993, so its
IV fixture premium is obtained by pricing the same inputs at 20% volatility.
The public model catalog fixture is refreshed from that service as well.
