# MorphIQ SDK for Python

This repository owns the Python API client, cookbook and notebook companions.
The API repository owns the reviewed OpenAPI contract. Numerical engines,
commercial policy, account authority and execution remain server-side.

## Strategic Pragmatism

Be strategically pragmatic in all MorphIQ Labs work. Choose the simplest solution that delivers the intended outcome and meets its correctness, performance, and operational contracts.

- **Keep the outcome and scope explicit.** Resist speculative features, general-purpose frameworks, and adjacent problems that are not needed for the agreed result. Added scope must earn its implementation, maintenance, and opportunity cost.
- **Challenge direction constructively.** Treat proposed approaches, including the owner's, as proposals to evaluate. Raise concerns early, explain the tradeoffs, and recommend a simpler or better-supported alternative when one exists. Agreement is not a substitute for judgment.
- **Respect ownership boundaries.** Prefer established libraries and supported provider capabilities. Do not turn a third-party limitation or a problem outside our domain into a subsystem we must build and maintain. Establish our boundary, surface the limitation, and recommend an upstream fix, a supported alternative, or an explicit scope reduction; custom machinery needs a clear domain benefit.
- **Bound investigations.** Name the question, the evidence needed to decide, and a stopping condition. When further investigation or engineering costs substantially more than its expected value, stop expanding the work and recommend a decision or rescope. Do not chase exhaustive explanations that cannot change that decision.
- **Prefer explicit failure to speculative recovery.** Reject unsupported inputs or conditions with an actionable error or exception at the owning boundary rather than adding fallbacks for every conceivable edge case. Preserve valid state and required cleanup; never silently approximate, discard data, or report success. Required supported cases and recovery guarantees still have to work.

Pragmatism governs which guarantees we undertake, not whether we honor them. If an existing commitment is disproportionate, make the tradeoff and proposed contract change explicit to the owner before narrowing it; do not disguise unfinished work as completion.

## Client contract

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

The published SDK implements sync/async single-option JSON pricing, all-ten-Greeks
analysis, implied volatility, combined analytics and regime identification, plus
explicit ordered batches and optional bounded concurrency for the four option
operations. PyPI publication is live; notebook images and hosted notebooks remain
separate work. Keep availability statements precise.
