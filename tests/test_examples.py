import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient

from scripts.execute_notebook_fixture import NOTEBOOK_CASES

ROOT = Path(__file__).resolve().parents[1]


def test_examples_import_without_credentials_or_requests():
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in ("MORPHIQ_API_BASE_URL", "MORPHIQ_API_KEY")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import examples.price_european, examples.price_american, "
            "examples.price_async, examples.quickstart",
        ],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("standalone", [False, True])
def test_scripts_use_same_requests_and_preserve_unreported_charges(
    fixture_api, cases, tmp_path, standalone
):
    endpoint, received = fixture_api
    environment = {**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "fixture-key"}
    for module in ("price_european", "price_american", "price_async", "quickstart"):
        if standalone:
            script = tmp_path / (module + ".py")
            shutil.copyfile(ROOT / "examples" / script.name, script)
            command = [sys.executable, str(script)]
        else:
            command = [sys.executable, "-m", "examples." + module]
        result = subprocess.run(
            command,
            cwd=tmp_path if standalone else ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "not reported" in result.stdout
        assert "fixture-key" not in result.stdout + result.stderr
        expected = cases[:1] if module == "price_european" else cases[1:]
        if module in ("quickstart", "price_async"):
            expected = cases
        for case in expected:
            assert f"Price: {case['response']['result']['price']}" in result.stdout
            assert case["response"]["result"]["model_version"] in result.stdout
            assert case["response"]["metadata"]["request_id"] in result.stdout
            assert case["response"]["metadata"]["engines"][0]["revision"] in result.stdout
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
    assert received == [("/v1/price", "Bearer readme-test-key", cases[0]["request"])]
    assert json.loads(result.stdout) == json.loads(documented_response.group(1))
    assert json.loads(result.stdout) == cases[0]["response"]
    assert "readme-test-key" not in result.stdout + result.stderr


def test_scripts_report_failures_without_retry(failing_api):
    endpoint, received, expected = failing_api
    for module in ("price_european", "price_american", "price_async", "quickstart"):
        result = subprocess.run(
            [sys.executable, "-m", "examples." + module],
            cwd=ROOT,
            env={
                **os.environ,
                "MORPHIQ_API_BASE_URL": endpoint,
                "MORPHIQ_API_KEY": "error-test-key",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert expected in result.stderr
        assert "error-test-key" not in result.stdout + result.stderr
        assert "Price:" not in result.stdout
    assert len(received) == 4


@pytest.mark.parametrize("filename", NOTEBOOK_CASES)
def test_generated_notebook_executes_without_source_tree(fixture_api, cases, tmp_path, filename):
    endpoint, received = fixture_api
    subprocess.run(
        [sys.executable, "scripts/generate_notebook.py", "--check"], cwd=ROOT, check=True
    )
    assert {path.name for path in (ROOT / "notebooks").glob("*.ipynb")} == set(NOTEBOOK_CASES)
    notebook = nbformat.read(ROOT / "notebooks" / filename, as_version=4)
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
    by_name = {case["name"]: case for case in cases}
    assert [item[2] for item in received] == [
        by_name[name]["request"] for name in NOTEBOOK_CASES[filename]
    ]
    assert all(item[1] == "Bearer notebook-fixture-key" for item in received)
    assert "notebook-fixture-key" not in json.dumps(executed)
    assert "not reported" in json.dumps(executed)
