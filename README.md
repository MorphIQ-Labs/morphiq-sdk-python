# Option pricing, Greeks, volatility and market regimes in Python

Price European and American options, calculate standard-five or all-ten Greeks, solve implied
volatility, and identify market regimes from price histories.

`morphiq-sdk` is a typed Python client for the MorphIQ API, with synchronous and
asynchronous calls. Pricing, Greeks, implied volatility and implied Greeks
support ordered batches. Runnable examples and interactive notebooks cover option
valuation, sensitivity analysis and market-regime identification.

See the [documentation index](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/README.md) for all feature guides and the
[Python API reference](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/API.md) for methods, models and errors.

This client targets the MorphIQ API **0.10.0** contract (**API v1 · Beta**,
contract label `0.1.0`): `collection:verb` routes, `option` / `market` / `model`
requests, grouped response metadata and RFC 9457 problem errors. Methods are
grouped by collection and spell each operation's canonical id, for example
`client.options.price(...)` for `options.price`. SDK 0.2.1 on PyPI targets the
earlier contract; this client is unreleased until the next SDK release. See the
[0.10.0 migration guide](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/API_0_10_ADOPTION.md)
and [model capabilities](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/MODELS.md): BSM/BS1993 support batches
up to 100; QdFp and cash-dividend finite difference support single price and IV.

## Quickstart

### 1. Get API access

Start at the [MorphIQ Labs developer portal](https://developers.morphiqlabs.com)
to get your API key, then set it in your terminal:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
```

`MorphIQ()` reads `MORPHIQ_API_KEY` automatically and connects to
`https://api.morphiqlabs.com`.

### 2. Install the SDK

With Python 3.11 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install morphiq-sdk
```

### 3. Make your first API request

Save the following as `price_option.py`. It prices a European call with spot and
strike of 100, one year to expiry, 20% volatility, and a 5% interest rate:

```python
from morphiq_sdk import Market, MorphIQ, Option, OptionsPriceRequest

request = OptionsPriceRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.20,
)

with MorphIQ() as client:
    response = client.options.price(request)
    print(response.model_dump_json(indent=2, exclude_unset=True))
```

Run it in the same terminal where you set your API key:

```sh
python price_option.py
```

This sends one authenticated `POST https://api.morphiqlabs.com/v1/options:price`
request with `model: {"id": "auto"}` and prints the JSON response. Example
response from the recorded synthetic fixture:

```json
{
  "metadata": {
    "request_id": "fr-18eb0de772f9d5a8-0000000000000014",
    "service_version": "0.9.2",
    "contract": {
      "version": "v1",
      "sha256": "23ee6e9f9ad5841def5b34c0d45b43b1c6a8b628179493f9640da58baafe598a"
    },
    "engines": [
      {
        "name": "morphiq-risk",
        "version": "0.46.1",
        "revision": "1550e4e41b243b8a978677bc5e9b46916c08cb0e"
      }
    ]
  },
  "result": {
    "price": 10.450583572185577,
    "model": {
      "id": "black_scholes_merton",
      "version": "black_scholes_merton/1"
    }
  }
}
```

Your request ID and engine metadata will reflect the live service. This fixture
was recorded in open development mode; authenticated responses also report
commercial charges in `metadata.billing.charged_cu`, the plan in
`metadata.policy` and the budget estimate in `metadata.budget`. Keep the request
ID for support.
See [the quickstart guide](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/QUICKSTART.md)
for input units, async usage, configuration and errors.

## Repository examples and notebooks

The executable examples and Docker notebooks live in the repository. Clone it
to use either:

```sh
git clone https://github.com/MorphIQ-Labs/morphiq-sdk-python.git
cd morphiq-sdk-python
```

### Run the examples

From the repository root, with your Python environment active and API key set:

```sh
python -m pip install -e .
python -m examples.quickstart
```

This sends two requests, for European and American pricing. Run
`python -m examples.price_async` for the async version, or
`python -m examples.price_european` and `python -m examples.price_american`
individually. See the
[executable cookbook](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/examples/README.md)
for all examples.

### Start a notebook with Docker

With Docker running, from the repository root, set your API key and start
the notebook:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
docker compose up --build
```

Open the local token-authenticated URL printed by Jupyter to reach Start Here.
Choose an analysis workspace and run all cells once to display its controls:

- [Option pricing](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/notebooks/pricing/options.ipynb): European/American and model
  dropdowns, call/put selection, editable assumptions, automatic Yahoo daily/intraday underlying prices,
  a valuation comparison table, a price-and-Greeks panel, an implied-volatility solver,
  implied-Greeks premium analysis, a session CU total and a spot-sensitivity chart.
- [Regime analysis](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/notebooks/regime/identification.ipynb): ticker selection,
  Yahoo daily/intraday price history, latest regime assessment, score charts and provenance.

Compose passes your API key into the container; if unset, the workspace prompts
for it. Setup and control changes make no MorphIQ requests. Pricing loads Yahoo prices automatically
on setup and when the ticker or interval changes. In regime, **Analyze regime** loads
Yahoo history and displays the complete assessment in one click. Click **Price option**
or **Price + Greeks**, **Solve IV**, **Analyze premium** or **Analyze regime** for one
request. **Spot sensitivity** submits nine scenarios in one batch request. Yahoo data remains in memory.
Dependencies are installed at build time, and notebook edits persist in a named volume.

Stop with Ctrl-C, then `docker compose down`; the workspace is retained. If port
8888 is occupied, use `MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build`.
See [notebook instructions](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/docs/NOTEBOOKS.md) for networking and persistence.

## Development

From a repository checkout, use Python 3.11 or newer. CI checks Python 3.11 and 3.14.

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
[CONTRIBUTING.md](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/CONTRIBUTING.md) and [RELEASE.md](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/RELEASE.md).

Clients make no automatic retries and do not follow redirects. A timeout
may leave work charged. Only `metadata.billing.quoted_cu` and
`metadata.billing.charged_cu` report commercial CUs. A missing `charged_cu` means
unreported, not zero. Optional members are omitted by the API, never sent as
null. Response enums may gain values: the SDK keeps an unknown value as a plain
string and an unknown variant as an `Unrecognized` model instead of failing.

The SDK preserves server results, numerical diagnostics, request IDs, engine
provenance and commercial Compute Units (CU). Numerical engines, model selection,
policy decisions and charging remain server-owned. The client will not duplicate
pricing engines or calculate authoritative customer charges.

## Project layout

```text
src/morphiq_sdk/    Installable, typed Python package
scripts/           Development and package verification
examples/          Runnable pricing, Greeks, IV, implied-Greeks, batch and regime examples
notebooks/         Quickstart and standalone feature notebooks
contracts/         Reviewed OpenAPI snapshot, digest and source provenance
docker/            Non-root notebook startup and workspace seeding
docs/              Usage guides and contract documentation
.github/           CI and pull request template
```

## License

The SDK, examples and notebooks are licensed under the
[MIT License](https://github.com/MorphIQ-Labs/morphiq-sdk-python/blob/main/LICENSE).

See [the rate card and request quotes](docs/RATE_CARD.md) for zero-CU discovery, conditional quotes, and the optional `max_cu` execution ceiling.
