# Notebook companions and hosted exploration

Cookbook notebook companions are planned with [#111](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/111).
Choose a reproducible script-to-notebook workflow during implementation. Verify
execution against controlled API fixtures and keep outputs free of credentials
and private data.

[Hosted notebook exploration (#115)](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/115)
compares managed notebook services, browser Python and isolated server kernels.
Prototype one recipe and scenario plot before selecting a platform. Check
dependency compatibility, API networking/CORS, keys, CU visibility, isolation,
session lifetime and hosting costs.

Offer download/local-run support and identify live versus recorded results.
Do not embed a shared production key or deploy a public arbitrary-code runtime
as part of the SDK foundation. This exploration is outside the first milestone.
