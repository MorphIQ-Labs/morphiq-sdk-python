"""Build an sdist and wheel, then verify an isolated wheel installation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import venv
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    expected_version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    with tempfile.TemporaryDirectory(prefix="morphiq-sdk-package-") as directory:
        temporary = Path(directory)
        artifacts = temporary / "dist"
        # With no target flags, build creates the sdist, then builds its wheel.
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(artifacts), str(root)],
            check=True,
        )
        wheels = list(artifacts.glob("*.whl"))
        sources = list(artifacts.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise RuntimeError("Expected exactly one wheel and one source distribution")

        installation = temporary / "installed"
        venv.EnvBuilder(with_pip=True).create(installation)
        python = installation / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheels[0])],
            cwd=temporary,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from importlib.metadata import version; "
                "from importlib.resources import files; "
                "import morphiq_sdk, morphiq_sdk_yahoo, sys; "
                "from importlib.util import find_spec; "
                "assert find_spec('yfinance') is None and find_spec('pandas') is None; "
                "assert 'yfinance' not in sys.modules and 'pandas' not in sys.modules; "
                "from morphiq_sdk import PriceProvider; "
                "provider: PriceProvider = morphiq_sdk_yahoo.YahooPriceProvider(); "
                "from datetime import date;\n"
                "try:\n"
                "    provider.history('SPY', start=date(2026, 1, 5), end=date(2026, 1, 7))\n"
                "except ImportError as error:\n"
                "    assert 'market-data' in str(error)\n"
                "else:\n"
                "    raise AssertionError('Yahoo worked without optional dependencies')\n"
                "from morphiq_sdk.pandas import workflow_to_frames;\n"
                "with morphiq_sdk.MorphIQ(api_key='package-test') as client:\n"
                "    workflow = client.price_workflow([], chunk_size=1)\n"
                "    workflow.run()\n"
                "    try:\n"
                "        workflow_to_frames(workflow)\n"
                "    except ImportError as error:\n"
                "        assert 'morphiq-sdk[pandas]' in str(error)\n"
                "    else:\n"
                "        raise AssertionError('DataFrame conversion worked without pandas')\n"
                "assert morphiq_sdk.__version__ == sys.argv[1]; "
                "assert morphiq_sdk.__version__ == version('morphiq-sdk'); "
                "assert files('morphiq_sdk').joinpath('py.typed').is_file(); "
                "assert files('morphiq_sdk_yahoo').joinpath('py.typed').is_file(); "
                "print('Isolated wheel import and typing marker verified:', "
                "morphiq_sdk.__version__)",
                expected_version,
            ],
            cwd=temporary,
            check=True,
        )

        # Check the optional extra independently of the notebook/Yahoo environment.
        subprocess.run(
            [str(python), "-m", "pip", "install", f"{wheels[0]}[pandas]"],
            cwd=temporary,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                textwrap.dedent("""\
                import json
                import sys
                from importlib.util import find_spec
                from pathlib import Path
                from morphiq_sdk import (
                    MorphIQ, BatchPriceResponse, BatchGreeksResponse,
                    BatchImpliedVolatilityResponse, BatchAnalyticsResponse,
                )
                from morphiq_sdk.pandas import batch_to_frames, workflow_to_frames
                assert find_spec('yfinance') is None
                assert 'pandas' not in sys.modules
                cases = json.loads(Path(sys.argv[1]).read_text())['cases']
                types = (BatchPriceResponse, BatchGreeksResponse,
                         BatchImpliedVolatilityResponse, BatchAnalyticsResponse)
                for cls, case in zip(types, cases):
                    body = case['response']
                    body['metadata']['fcu_charged'] = 2**100
                    frames = batch_to_frames(
                        cls.model_validate(body), identifiers=[1, None, 2**100]
                    )
                    assert frames.results['outcome'].tolist() == body['results']
                    assert frames.results['identifier'].tolist() == [1, None, 2**100]
                    assert frames.total_fcu_charged == 2**100
                    assert frames.requests.loc[0, 'fcu_charged'] == 2**100
                with MorphIQ(api_key='package-test') as client:
                    workflow = client.price_workflow([], chunk_size=1)
                    workflow.run()
                    frames = workflow_to_frames(workflow)
                    assert frames.results.empty and frames.requests.empty
                    assert frames.total_fcu_charged == 0
                print('Isolated pandas extra and all four batch conversions verified')
                """),
                str(root / "tests/fixtures/batch.json"),
            ],
            cwd=temporary,
            check=True,
        )


if __name__ == "__main__":
    main()
