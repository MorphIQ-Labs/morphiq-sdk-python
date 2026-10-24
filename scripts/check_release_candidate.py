"""Audit a built wheel in a clean interpreter against a pinned loopback service.

Copies acceptance resources without src/ so checkout imports cannot hide missing
wheel contents. Never accepts a production API URL or reads a .env file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen


def check(wheel: Path, source: Path, interpreter: str, api_url: str, report: Path) -> None:
    endpoint = urlparse(api_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Use an HTTP loopback controlled service, never a production API.")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("The controlled API URL must not contain credentials, query or fragment.")
    wheel, source, report = wheel.resolve(), source.resolve(), report.resolve()
    if wheel.suffix != ".whl":
        raise ValueError("Supply a built wheel, not an editable checkout.")
    expected_version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
    subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD"], check=True)
    pin = json.loads((source / "contracts/provenance.json").read_text())
    with urlopen(api_url.rstrip("/") + "/openapi.json", timeout=10) as response:
        served_digest = hashlib.sha256(response.read()).hexdigest()
    if served_digest != pin["sha256"]:
        raise ValueError("Controlled service contract does not match the reviewed source.")
    report.parent.mkdir(parents=True, exist_ok=True)
    log_path = report.with_suffix(".log")
    evidence: dict[str, Any] = {
        "source_commit": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip(),
        "wheel": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "contract_sha256": served_digest,
        "api_source_commit": pin["source_commit"],
        "steps_seconds": {},
        "status": "running",
        "production_calls": 0,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="morphiq-wheel-acceptance-") as directory:
            temporary = Path(directory)
            installation, resources = temporary / "venv", temporary / "resources"
            resources.mkdir()
            for name in (
                "tests",
                "scripts",
                "examples",
                "notebooks",
                "contracts",
                "docs",
                "docker",
            ):
                shutil.copytree(
                    source / name,
                    resources / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            for name in ("README.md", "pyproject.toml"):
                shutil.copyfile(source / name, resources / name)
            assert not (resources / "src").exists()
            environment = dict(os.environ)
            for name in ("PYTHONPATH", "PYTHONHOME", "MORPHIQ_API_KEY", "MORPHIQ_API_BASE_URL"):
                environment.pop(name, None)
            environment.update(
                MORPHIQ_TEST_API_URL=api_url,
                IPYTHONDIR=str(temporary / "ipython"),
                JUPYTER_CONFIG_DIR=str(temporary / "jupyter-config"),
                JUPYTER_RUNTIME_DIR=str(temporary / "jupyter-runtime"),
                MPLCONFIGDIR=str(temporary / "matplotlib"),
            )
            with log_path.open("w") as log:

                def run(name: str, args: list[str], *, capture: bool = False) -> str:
                    started = time.monotonic()
                    result = subprocess.run(
                        args,
                        cwd=resources,
                        env=environment,
                        stdout=subprocess.PIPE if capture else log,
                        stderr=log,
                        text=True,
                        check=False,
                    )
                    if capture:
                        log.write(result.stdout)
                        log.flush()
                    result.check_returncode()
                    evidence["steps_seconds"][name] = round(time.monotonic() - started, 2)
                    print(f"{name}: passed ({evidence['steps_seconds'][name]} s)", flush=True)
                    return result.stdout if capture else ""

                run("create_venv", [interpreter, "-m", "venv", str(installation)])
                python = str(installation / "bin/python")
                environment["PATH"] = (
                    str(installation / "bin") + os.pathsep + os.environ.get("PATH", "")
                )
                environment["VIRTUAL_ENV"] = str(installation)
                run("install_core_wheel", [python, "-m", "pip", "install", str(wheel)])
                evidence["core"] = json.loads(
                    run(
                        "verify_core_isolation",
                        [
                            python,
                            "-I",
                            "-c",
                            (
                                "import json,sys; from pathlib import Path; "
                                "from importlib.util import find_spec; "
                                "import morphiq_sdk; "
                                "module=Path(morphiq_sdk.__file__).resolve(); "
                                "assert module.is_relative_to(Path(sys.prefix).resolve()); "
                                "assert find_spec('pandas') is None; "
                                "assert find_spec('yfinance') is None; "
                                "print(json.dumps({'python':sys.version.split()[0], "
                                "'sdk':morphiq_sdk.__version__, "
                                "'module':str(module.relative_to(Path(sys.prefix).resolve()))}))"
                            ),
                        ],
                        capture=True,
                    )
                )

                if evidence["core"]["sdk"] != expected_version:
                    raise ValueError("Installed wheel version differs from the candidate source.")

                case = json.loads((source / "tests/fixtures/pricing.json").read_text())["cases"][0]
                received: list[dict[str, Any]] = []

                class Handler(BaseHTTPRequestHandler):
                    def do_POST(self) -> None:
                        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        received.append(body)
                        if (
                            self.path != "/v1/price"
                            or body != case["request"]
                            or self.headers.get("Authorization") != "Bearer release-audit-key"
                        ):
                            self.send_error(422)
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps(case["response"]).encode())

                    def log_message(self, format: str, *args: Any) -> None:
                        pass

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    environment.update(
                        MORPHIQ_API_KEY="release-audit-key",
                        MORPHIQ_API_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                    )
                    snippet = re.search(
                        r"```python\n(.*?)\n```", (source / "README.md").read_text(), re.S
                    )
                    if snippet is None:
                        raise ValueError("No README Python quickstart found.")
                    output = run(
                        "readme_first_request_fixture",
                        [python, "-c", snippet.group(1)],
                        capture=True,
                    )
                    assert json.loads(output) == case["response"] and received == [case["request"]]
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                    environment.pop("MORPHIQ_API_KEY", None)
                    environment.pop("MORPHIQ_API_BASE_URL", None)

                run(
                    "install_optional_extras_and_test_tools",
                    [
                        python,
                        "-m",
                        "pip",
                        "install",
                        f"{wheel}[pandas,notebooks]",
                        "pytest==9.1.1",
                        "jsonschema==4.26.0",
                        "nbclient==0.11.0",
                        "nbformat==5.11.1",
                    ],
                )
                run(
                    "register_isolated_kernel",
                    [
                        python,
                        "-m",
                        "ipykernel",
                        "install",
                        "--prefix",
                        str(installation),
                        "--name",
                        "python3",
                    ],
                )
                environment["JUPYTER_PATH"] = str(installation / "share/jupyter")
                evidence["extras"] = json.loads(
                    run(
                        "verify_extras",
                        [
                            python,
                            "-I",
                            "-c",
                            (
                                "import json; from importlib.metadata import version; "
                                "from morphiq_sdk import MorphIQ; "
                                "from morphiq_sdk.pandas import workflow_to_frames; "
                                "from morphiq_sdk_yahoo import YahooPriceProvider; "
                                "client=MorphIQ(api_key='release-audit-key'); "
                                "workflow=client.price_workflow([],chunk_size=1); workflow.run(); "
                                "assert workflow_to_frames(workflow).total_fcu_charged==0; "
                                "client.close(); "
                                "print(json.dumps({x:version(x) for x in "
                                "['pandas','jupyterlab','ipykernel','yfinance','ipywidgets','matplotlib']}))"
                            ),
                        ],
                        capture=True,
                    )
                )
                evidence["tests"] = (
                    run("installed_wheel_acceptance", [python, "-m", "pytest", "-q"], capture=True)
                    .strip()
                    .splitlines()[-1]
                )
                log.write(evidence["tests"] + "\n")
                evidence["status"] = "passed"
    except BaseException as error:
        evidence["status"] = "failed"
        evidence["error_type"] = type(error).__name__
        raise
    finally:
        report.write_text(json.dumps(evidence, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    check(args.wheel, args.source, args.python, args.api_url, args.report)


if __name__ == "__main__":
    main()
