# Notebook companions and hosted exploration

`00-start-here.ipynb` covers European/American pricing with sync and async clients.
Run `docker compose up --build`, or install the notebook extra and open it with
JupyterLab. See [the notebook guide](../docs/NOTEBOOKS.md) for credentials, four-call
Run All behavior, persistence and networking.

Regenerate it with `python scripts/generate_notebook.py`; `--check` verifies
agreement with the executable examples. Committed cells contain no executed
outputs or credentials. CI executes them against a loopback native-response replay.
The remaining cookbook is tracked in [#7](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/7).

[Hosted notebook exploration (#11)](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11)
compares managed notebook services, browser Python and isolated server kernels.
Prototype one recipe and scenario plot before selecting a platform. Check
dependency compatibility, API networking/CORS, keys, CU visibility, isolation,
session lifetime and hosting costs.

Offer download/local-run support and identify live versus recorded results.
Do not embed a shared production key or deploy a public arbitrary-code runtime
as part of the SDK foundation. This exploration is outside the first milestone.
