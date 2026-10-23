import json
import os
import re
import subprocess
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

from examples import _shared

ROOT = Path(__file__).resolve().parents[1]


def test_configuration_only_needs_api_key():
    environment = {
        name: value for name, value in os.environ.items() if name != "MORPHIQ_API_BASE_URL"
    }
    environment["MORPHIQ_API_KEY"] = "example-test-only"
    result = subprocess.run(
        [sys.executable, "-c", "from examples._shared import configure; configure()"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == result.stderr == ""


def test_scripts_use_same_requests_and_preserve_unreported_charges(fixture_api):
    endpoint, received = fixture_api
    environment = {**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "fixture-key"}
    for module in ("price_european", "price_american", "price_async", "quickstart"):
        result = subprocess.run(
            [sys.executable, "-m", "examples." + module],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "not reported" in result.stdout
        assert "fixture-key" not in result.stdout + result.stderr
    assert len(received) == 6
    assert [request[2]["exercise_style"] for request in received] == [
        "european",
        "american",
        "european",
        "american",
        "european",
        "american",
    ]
    assert all(request[1] == "Bearer fixture-key" for request in received)


def test_readme_request_and_response_match_executable_example(fixture_api, cases):
    endpoint, received = fixture_api
    readme = (ROOT / "README.md").read_text()
    code = re.search(r"```python\n(.*?)\n```", readme, re.DOTALL)
    documented_response = re.search(r"```json\n(.*?)\n```", readme, re.DOTALL)
    assert code is not None and documented_response is not None
    result = subprocess.run(
        [sys.executable, "-c", code.group(1)],
        cwd=ROOT,
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "readme-test-key"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert received == [("/v1/price", "Bearer readme-test-key", _shared.european_call().to_wire())]
    assert json.loads(result.stdout) == json.loads(documented_response.group(1))
    assert json.loads(result.stdout) == cases[0]["response"]
    assert "readme-test-key" not in result.stdout + result.stderr


def test_generated_notebook_executes_without_source_tree(fixture_api, tmp_path):
    endpoint, received = fixture_api
    subprocess.run(
        [sys.executable, "scripts/generate_notebook.py", "--check"], cwd=ROOT, check=True
    )
    notebook = nbformat.read(ROOT / "notebooks/00-start-here.ipynb", as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            assert not cell.outputs and cell.execution_count is None
    executed = NotebookClient(
        notebook, timeout=60, kernel_name="python3", resources={"metadata": {"path": str(tmp_path)}}
    ).execute(
        env={
            **os.environ,
            "MORPHIQ_API_BASE_URL": endpoint,
            "MORPHIQ_API_KEY": "notebook-fixture-key",
        }
    )
    assert len(received) == 4
    assert "notebook-fixture-key" not in json.dumps(executed)
    assert "not reported" in json.dumps(executed)
