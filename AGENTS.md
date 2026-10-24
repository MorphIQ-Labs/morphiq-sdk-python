# MorphIQ SDK for Python

This repository owns the Python API client, cookbook and notebook companions.
The API repository owns the reviewed OpenAPI contract. Numerical engines,
commercial policy, account authority and execution remain server-side.

- Preserve wire semantics, numerical values, diagnostics/provenance, ordering
  and optional commercial CU fields. Internal `units_charged` is not the
  commercial `fcu_charged` amount.
- Consume an immutable reviewed OpenAPI artifact with its digest and source
  identity. Do not maintain a second authoritative contract.
- Keep credentials, private market data and engine source out of fixtures,
  notebook outputs, logs and distributions.
- Do not introduce blanket retries: a timeout may occur after charge commitment.
  Keep chunking/concurrency explicit and avoid hardcoded customer plan limits.
- Keep pandas, plotting and notebook tooling optional. Examples are executable
  scripts with synthetic fixtures. Notebooks are ready-to-use analysis workspaces
  with controls, data loading and results, verified against the contract/examples.
  Keep SDK demonstrations in examples/, not in the notebook user flow.
- Maintain the quickstart plus a standalone notebook for each implemented feature.
  Organize feature notebooks in topic folders; keep `notebooks/start-here.ipynb` at the root.
  Never submit API requests merely by running notebook setup or changing controls.
  Label action request counts and keep scenario execution sequential and explicit.
  Keep request construction and response handling visible in every Python example.
  README files describe available functionality and usage; keep plans in the roadmap.
- Use feature branches and reviewed squash PRs with conventional commit titles.
  Never push implementation directly to main or hand-cut release tags.
- Run Ruff lint/format, mypy and `python scripts/check_package.py` for setup
  changes. Add meaningful transport/contract/integration tests with behavior.
- Follow RELEASE.md: no manual release version bumps or package publication.
  Release Please owns pyproject.toml version, manifest and changelog updates.

The unreleased preview implements sync/async single-option JSON pricing, all-ten-Greeks analysis, implied volatility, combined analytics and
regime identification, plus explicit ordered batches for the four option operations,
with a local quickstart and feature notebooks. Other endpoints, package/image publication and hosted
notebooks remain planned. Keep availability statements precise.
