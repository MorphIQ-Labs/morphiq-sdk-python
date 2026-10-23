"""Build an sdist and wheel, then verify an isolated wheel installation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.setdefault("MORPHIQ_SDK_BUILD_VERSION", "0.0.0.dev0")
    with tempfile.TemporaryDirectory(prefix="morphiq-sdk-package-") as directory:
        temporary = Path(directory)
        artifacts = temporary / "dist"
        # With no target flags, build creates the sdist, then builds its wheel.
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(artifacts), str(root)],
            env=environment,
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
                "import morphiq_sdk; "
                "assert morphiq_sdk.__version__ == version('morphiq-sdk'); "
                "assert files('morphiq_sdk').joinpath('py.typed').is_file(); "
                "print('Isolated wheel import and typing marker verified:', "
                "morphiq_sdk.__version__)",
            ],
            cwd=temporary,
            check=True,
        )


if __name__ == "__main__":
    main()
