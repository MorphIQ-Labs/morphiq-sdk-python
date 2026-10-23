import json
import os
import subprocess
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


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
