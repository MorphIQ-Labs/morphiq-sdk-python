"""Install a built/downloaded wheel in a clean environment, without a source checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

CORE_CHECK = """
import sys
from importlib.metadata import version
from importlib.resources import files
from importlib.util import find_spec
import morphiq_sdk as sdk
import morphiq_sdk_yahoo
assert sdk.__version__ == version('morphiq-sdk') == sys.argv[1]
assert find_spec('pandas') is None and find_spec('yfinance') is None
assert files('morphiq_sdk').joinpath('py.typed').is_file()
assert files('morphiq_sdk_yahoo').joinpath('py.typed').is_file()
surface = {
    'options': ('price', 'implied_volatility', 'greeks', 'standard_greeks', 'implied_greeks',
                'batch_price', 'batch_implied_volatility', 'batch_greeks',
                'batch_standard_greeks', 'batch_implied_greeks', 'price_workflow',
                'implied_volatility_workflow', 'greeks_workflow', 'standard_greeks_workflow',
                'implied_greeks_workflow'),
    'series': ('identify_regime',),
    'models': ('list',),
    'rate_card': ('get', 'quote'),
}
for client_type in (sdk.MorphIQ, sdk.AsyncMorphIQ):
    client = client_type(api_key='offline-install-check')
    for collection, methods in surface.items():
        for method in methods:
            assert callable(getattr(getattr(client, collection), method))
with sdk.MorphIQ(api_key='offline-install-check') as client:
    workflow = client.options.price_workflow([], chunk_size=1)
    workflow.run()
    assert workflow.total_charged_cu == 0
assert not any(name in sys.modules for name in ('pandas', 'yfinance', 'matplotlib'))
print('Core install, client surface, typing and optional dependency isolation verified')
"""

EXTRAS_CHECK = """
import json
import sys
from pathlib import Path
import ipykernel, ipywidgets, jupyterlab, matplotlib, pandas, yfinance
from morphiq_sdk import (OptionsBatchPriceResponse, OptionsBatchGreeksResponse,
                        OptionsBatchImpliedVolatilityResponse,
                        OptionsBatchImpliedGreeksResponse,
                        OptionsBatchStandardGreeksResponse)
from morphiq_sdk.pandas import batch_to_frames
cases = json.loads(Path(sys.argv[1]).read_text())['cases']
for cls, case in zip((OptionsBatchPriceResponse, OptionsBatchGreeksResponse,
                     OptionsBatchImpliedVolatilityResponse,
                     OptionsBatchImpliedGreeksResponse), cases):
    body = case['response']
    body['metadata']['billing'] = {'charged_cu': 2**100}
    frames = batch_to_frames(cls.model_validate(body), identifiers=[1, None, 2**100])
    assert frames.results['outcome'].tolist() == body['results']
    assert frames.results['identifier'].tolist() == [1, None, 2**100]
    assert frames.total_charged_cu == 2**100
standard = json.loads(Path(sys.argv[1]).with_name('standard_greeks.json').read_text())['cases'][0]
billing = {'charged_cu': 2**100}
body = {'metadata': {**standard['response']['metadata'], 'billing': billing}, 'results': [
    {'index': 0, 'status': 'success', 'result': standard['response']['result']}
]}
frames = batch_to_frames(OptionsBatchStandardGreeksResponse.model_validate(body))
assert frames.results['outcome'].tolist() == body['results']
assert frames.total_charged_cu == 2**100
print('All extras import; all five batch conversions preserve outcomes and exact charges')
"""


def check(wheel: Path, version: str, fixture: Path) -> None:
    wheel, fixture = wheel.resolve(), fixture.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError("Expected an existing wheel")
    with tempfile.TemporaryDirectory(prefix="morphiq-published-install-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        # Ignore local pip configuration and index env vars. Only the SDK comes from
        # TestPyPI; dependencies always resolve against the production PyPI index.
        def run(*args: str) -> None:
            subprocess.run([str(python), "-I", *args], cwd=root, check=True)

        def install(target: str) -> None:
            run(
                "-m",
                "pip",
                "--isolated",
                "install",
                "--no-cache-dir",
                "--index-url",
                "https://pypi.org/simple/",
                target,
            )

        install(str(wheel))
        run("-c", CORE_CHECK, version)
        install(f"{wheel}[pandas,market-data,notebooks]")
        run("-m", "pip", "--isolated", "check")
        run("-c", EXTRAS_CHECK, str(fixture))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/batch.json"))
    args = parser.parse_args()
    check(args.wheel, args.version, args.fixture)
