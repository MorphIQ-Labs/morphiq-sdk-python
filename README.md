# MorphIQ SDK for Python

Python access to the MorphIQ Labs API, with runnable examples and notebooks for
pricing, risk and market analytics.

## Quickstart

From a checkout with Python 3.11 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m examples.quickstart
```

Enter your account's API base URL and API key at the masked prompt, or supply
`MORPHIQ_API_BASE_URL` and `MORPHIQ_API_KEY` through your environment. This submits
two real requests and prints each price, selected model, request ID, engine
identity and reported commercial CU charge.

Run `python -m examples.price_async` for the same two requests with sequential
awaits. Individual scripts are `examples.price_european` and `examples.price_american`.
See [the quickstart guide](docs/QUICKSTART.md) for input units, reference results,
configuration and errors.

## Start a notebook with Docker

With Docker running, from the repository root:

```sh
docker compose up --build
```

Open the local token-authenticated URL printed by Jupyter to reach Start Here.
Enter the API endpoint and key when prompted. Opening Jupyter makes no API calls;
running all cells submits four pricing requests, including the async examples.
Dependencies are installed at build time, and notebook edits persist in a named volume.

Stop with Ctrl-C, then `docker compose down`; the workspace is retained. If port
8888 is occupied, use `MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build`.
See [notebook instructions](docs/NOTEBOOKS.md) for networking and persistence.

## Development

Use Python 3.11 or newer. The initial CI matrix checks Python 3.11 and 3.14;
release acceptance will establish the complete supported-version matrix.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
python -m pip install --no-build-isolation -e .
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -q
python scripts/generate_notebook.py --check
python scripts/check_package.py
```

Versions are managed through reviewed release PRs; no version environment variable
is needed. `check_package.py` builds an sdist and a wheel from that sdist, then
installs the wheel in a fresh environment outside the checkout. Routine tests use local fixture replay and need
no real credentials; native API integration is opt-in. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [RELEASE.md](RELEASE.md).

Pricing clients make no automatic retries and do not follow redirects. A timeout
may leave work charged. Missing `fcu_charged` means unreported, not zero; internal
`units_charged` is not a commercial CU charge.

The SDK preserves server results, numerical diagnostics, request IDs, engine
provenance and commercial Compute Units (CU). Numerical engines, model selection,
policy decisions and charging remain server-owned. The client will not duplicate
pricing engines or calculate authoritative customer charges.

## Project layout

```text
src/morphiq_sdk/    Installable, typed Python package
scripts/           Development and package verification
examples/          Runnable European/American sync and async examples
notebooks/         Generated standalone Start Here notebook
contracts/         Reviewed OpenAPI snapshot, digest and source provenance
docker/            Non-root notebook startup and workspace seeding
docs/              Roadmap and contract handoff design
.github/           CI and pull request template
```
