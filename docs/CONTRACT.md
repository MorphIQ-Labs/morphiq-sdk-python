# Contract ownership and handoff

The API repository's services/api/openapi.json remains the reviewed HTTP source.
This SDK consumes a versioned artifact without owning another schema or installing
the numerical engines.

[SDK #2](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2)
coordinates the producer/import workflow with
[API #106](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106).
No snapshot is imported in this foundation.
Record SHA-256, service source/release identity and API contract version; verify
them before generation. Public SDK builds must work offline from the reviewed
snapshot without private GitLab access.

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
