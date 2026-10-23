# Notebook companions and hosted exploration

Cookbook notebook companions are planned with [#7](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/7).
Choose a reproducible script-to-notebook workflow during implementation. Verify
execution against controlled API fixtures and keep outputs free of credentials
and private data.

[Hosted notebook exploration (#11)](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11)
compares managed notebook services, browser Python and isolated server kernels.
Prototype one recipe and scenario plot before selecting a platform. Check
dependency compatibility, API networking/CORS, keys, CU visibility, isolation,
session lifetime and hosting costs.

Offer download/local-run support and identify live versus recorded results.
Do not embed a shared production key or deploy a public arbitrary-code runtime
as part of the SDK foundation. This exploration is outside the first milestone.
