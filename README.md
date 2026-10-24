# MorphIQ SDK for Python

Python access to the MorphIQ Labs API, with runnable examples and notebooks for
European and American option pricing, all-ten-Greeks analysis, implied volatility
and regime identification.

## Quickstart

### 1. Get API access

Start at the [MorphIQ Labs developer portal](https://developers.morphiqlabs.com)
to get your API key, then set it in your terminal:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
```

The SDK connects to `https://api.morphiqlabs.com` automatically.

### 2. Install the SDK

With Python 3.11 or newer:

```sh
git clone https://github.com/MorphIQ-Labs/morphiq-sdk-python.git
cd morphiq-sdk-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### 3. Make your first API request

Run this to price a European call with spot and strike of 100, one year to expiry,
20% volatility, and a 5% interest rate. It sends one authenticated
`POST https://api.morphiqlabs.com/v1/price` request and prints the JSON response:

```python
from morphiq_sdk import MorphIQ, PriceRequest

request = PriceRequest(
    exercise_style="european",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.20,
)

with MorphIQ() as client:
    response = client.price(request)
    print(response.model_dump_json(indent=2, exclude_unset=True))
```

Example response from the recorded synthetic fixture:

```json
{
  "result": {
    "price": 10.450583572185538,
    "exercise_style": "european",
    "option_type": "call",
    "pricing_model": "black_scholes_merton",
    "model_version": "black_scholes_merton/1"
  },
  "metadata": {
    "request_id": "fixture-european",
    "api_version": "v1",
    "engine_version": "0.39.1",
    "engines": [
      {
        "name": "morphiq-risk",
        "version": "0.39.1",
        "revision": "b4c29d492ff96dddf9b25f745d2be4d253202164"
      }
    ],
    "units_charged": 1,
    "compute_schedule_version": "2026-09-11"
  }
}
```

Your request ID and engine metadata will reflect the live service. This fixture
was recorded in open development mode; authenticated responses may also report
commercial charges in `metadata.fcu_charged`. Keep the request ID for support.
Run `unset MORPHIQ_API_KEY` when finished.

Run `python -m examples.quickstart` for European and American pricing, or
`python -m examples.price_async` for sequential async requests. Individual scripts
are `examples.price_european` and `examples.price_american`.
See [the quickstart guide](docs/QUICKSTART.md) for input units, reference results,
configuration and errors.

## Start a notebook with Docker

With Docker running, from the repository root, set your API key and start
the notebook:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
docker compose up --build
```

Open the local token-authenticated URL printed by Jupyter to reach Start Here.
Choose an analysis workspace and run all cells once to display its controls:

- [Option pricing](notebooks/pricing/options.ipynb): European/American and model
  dropdowns, call/put selection, editable assumptions, automatic Yahoo daily/intraday underlying prices,
  a valuation comparison table, a price-and-Greeks panel, an implied-volatility solver
  and a spot-sensitivity chart.
- [Regime analysis](notebooks/regime/identification.ipynb): ticker selection,
  Yahoo daily/intraday price history, latest regime assessment, score charts and provenance.

Compose passes your API key into the container; if unset, the workspace prompts
for it. Setup and control changes make no MorphIQ requests. Pricing loads Yahoo prices automatically
on setup and when the ticker or interval changes. In regime, **Analyze regime** loads
Yahoo history and displays the complete assessment in one click. Click **Price option**
or **Price + Greeks** or **Solve IV** for one request, **Spot sensitivity** for nine
sequential requests, or
**Analyze regime** for one request. Yahoo data remains in memory.
Dependencies are installed at build time, and notebook edits persist in a named volume.

Stop with Ctrl-C, then `docker compose down`; the workspace is retained. If port
8888 is occupied, use `MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build`.
See [notebook instructions](docs/NOTEBOOKS.md) for networking and persistence.

## Development

Use Python 3.11 or newer. CI checks Python 3.11 and 3.14.

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

Clients make no automatic retries and do not follow redirects. A timeout
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
examples/          Runnable pricing and regime examples
notebooks/         Quickstart and standalone feature notebooks
contracts/         Reviewed OpenAPI snapshot, digest and source provenance
docker/            Non-root notebook startup and workspace seeding
docs/              Usage guides and contract documentation
.github/           CI and pull request template
```
