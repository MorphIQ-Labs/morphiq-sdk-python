# MorphIQ SDK for Python

Python access to the MorphIQ Labs API, with runnable examples and notebooks for
pricing, risk and market analytics.

**Status: project foundation.** The package builds and installs, but the API
client and cookbook are not implemented yet. Nothing has been published to PyPI.
The distribution name `morphiq-sdk` and import name `morphiq_sdk` are provisional
until the release work confirms name ownership and licensing.

## Development

Use Python 3.11 or newer. The initial CI matrix checks Python 3.11 and 3.14;
release acceptance will establish the complete supported-version matrix.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export MORPHIQ_SDK_BUILD_VERSION=0.0.0.dev0
python -m pip install --no-build-isolation -e .
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/check_package.py
```

`0.0.0.dev0` is a development build value, not a release. `check_package.py`
builds an sdist and a wheel from that sdist, then installs the wheel in a fresh
environment outside the checkout. These checks make no API calls and need no
credentials. See [CONTRIBUTING.md](CONTRIBUTING.md) and [RELEASE.md](RELEASE.md).

## Planned scope

- Typed synchronous and asynchronous JSON clients.
- Price, implied volatility, all-ten-Greek and fused analytics, individually
  and in ordered batches; the reviewed regime operation has its own contract.
- Authentication, timeouts, errors, conservative retries and response metadata.
- Optional DataFrame conversion, eight executable recipes and notebook companions.

The SDK preserves server results, numerical diagnostics, request IDs, engine
provenance and commercial Compute Units (CU). Numerical engines, model selection,
policy decisions and charging remain server-owned. The client will not duplicate
pricing engines or calculate authoritative customer charges.

## Project layout

```text
src/morphiq_sdk/    Installable, typed Python package
scripts/           Development and package verification
examples/          Cookbook implementation and execution conventions
notebooks/         Planned notebook companions and hosted experience
docs/              Roadmap and contract handoff design
.github/           CI and pull request template
```

## Delivery plan

Implementation, issues and the SDK delivery milestone live in this GitHub repository:

- [SDK v0.1 and cookbook milestone](https://github.com/MorphIQ-Labs/morphiq-sdk-python/milestone/1)
- [Work breakdown and dependencies](docs/ROADMAP.md)
- [Hosted notebook exploration](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11)

API contract publication and website implementation stay in the API repository,
linked from their SDK dependency issues. Public distribution and support routing
are tracked before launch; this private scaffold grants no open-source license.
Hosted notebooks are a follow-on experiment, not a prerequisite for local SDK use.
