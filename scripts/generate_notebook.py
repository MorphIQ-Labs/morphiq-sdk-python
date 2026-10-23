"""Generate the standalone Start Here notebook from the runnable pricing examples."""

from __future__ import annotations

import argparse
import ast
import json
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def example_source(filename: str) -> str:
    """Copy imports and the main body; notebooks support top-level await."""
    source = (ROOT / "examples" / filename).read_text()
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    function = next(
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    lines = source.splitlines(keepends=True)
    import_source = "".join(lines[imports[0].lineno - 1 : imports[-1].end_lineno])
    if isinstance(function, ast.AsyncFunctionDef):
        # asyncio.run is only needed by the script's __main__ entry point.
        import_source = import_source.replace("import asyncio\n", "")
    body = textwrap.dedent("".join(lines[function.lineno : function.end_lineno]))
    return import_source + "\n" + body


def notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = []

    def cell(kind: str, identifier: str, text: str) -> None:
        value: dict[str, Any] = {
            "cell_type": kind,
            "id": identifier,
            "metadata": {},
            "source": text.strip() + ("\n" if kind == "markdown" else ""),
        }
        if kind == "code":
            value.update(execution_count=None, outputs=[])
        cells.append(value)

    cell(
        "markdown",
        "welcome",
        """
# MorphIQ SDK for Python — Start Here

Price a **European call** and an **American put**, then try the async client.
These inputs are synthetic. No market-data subscription is needed.

This notebook makes real requests only when you execute the pricing cells.
Each sync cell makes one request; the async cell makes two more. Running all
cells therefore makes **four pricing requests**, which may consume your API
allowance. Opening Jupyter does not call the API.

Docker includes the required Python environment. For a downloaded notebook,
install this repository with its `notebooks` extra using the quickstart, then
open it in JupyterLab. The notebook is self-contained; it needs no examples imports.
""",
    )
    cell(
        "code",
        "versions",
        """
import sys

import morphiq_sdk

print("Python:", sys.version.split()[0])
print("MorphIQ SDK:", morphiq_sdk.__version__)
""",
    )
    cell(
        "markdown",
        "configuration-help",
        """
## Connect to your API

Get your API key from the
[MorphIQ Labs developer portal](https://developers.morphiqlabs.com).
The SDK connects to `https://api.morphiqlabs.com` automatically. Before starting
Jupyter or Docker Compose, set your API key in the terminal:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
```

Docker Compose passes the key into the notebook container. If it is unset,
the cell below prompts. The key prompt is masked: **do not paste your key into a code
cell**. The key stays in this kernel's process environment, not notebook source
or outputs; clear it in the cleanup cell and shut down the kernel when finished.

For a local or controlled test service, set `MORPHIQ_API_BASE_URL` before startup
to override the default API URL.

Each pricing cell contains a complete example: request inputs, API call, response
fields and error handling. The code is copied from the executable Python scripts.
The server validates model domains and selects the pricing algorithm.
""",
    )
    cell(
        "code",
        "configure",
        """
import os
from getpass import getpass

if not os.environ.get("MORPHIQ_API_KEY"):
    os.environ["MORPHIQ_API_KEY"] = getpass("MorphIQ API key: ")
""",
    )
    cell(
        "markdown",
        "european-help",
        """
## 1. European call

Spot and strike are both 100 in the same currency. Expiry is **1 year**,
volatility is **0.20 = 20%**, interest is **0.05 = 5%**, and dividend yield is zero.
The Python default sends `pricing_model="auto"`; read the returned model and
algorithm version. The price uses the same currency units as spot and strike;
no contract multiplier is applied.
""",
    )
    cell("code", "european-price", example_source("price_european.py"))
    cell(
        "markdown",
        "american-help",
        """
## 2. American put

Spot is 100, strike is 105, expiry is **0.5 years**, volatility is 20%, interest
is 5%, and the continuous dividend yield is **0.01 = 1%**. This is a separate
synthetic contract, not a like-for-like exercise-premium comparison with the call.
Cash-dividend schedules and date/day-count conversion are outside this first example.
""",
    )
    cell("code", "american-price", example_source("price_american.py"))
    cell(
        "markdown",
        "async-help",
        """
## 3. The same requests with async

Jupyter supports top-level `await`; do not use `asyncio.run` in a running notebook
event loop. These requests are deliberately sequential, allowing use with plans
that permit only one request at a time. This cell makes **two additional calls**.
""",
    )
    cell(
        "code",
        "async-pricing",
        example_source("price_async.py"),
    )
    cell(
        "markdown",
        "errors-help",
        """
## Reading results and failures

Use `response.result.price`, `response.result.pricing_model`, and
`response.metadata.request_id`. Commercial charges are `metadata.fcu_charged`;
if absent they are **unreported**, not zero. `units_charged` is a separate
internal compute weight. Keep the request ID when contacting support.

`APIError` exposes HTTP status, server code, message, request ID, optional charge
metadata and `Retry-After`. `RequestTimeout` means execution/charges may be
unknown. Both clients make **no automatic retries**, including after timeouts,
and do not follow redirects. Correct the input/key/endpoint or inspect the
reported charge before deliberately submitting another request.

## Finish

The next cell removes the API key from this kernel's environment. Shut down the
kernel to release its remaining memory. If you exported the key in your terminal,
run `unset MORPHIQ_API_KEY` there when finished; `docker compose down` removes the
container configured with that key. Clear outputs before sharing a notebook.
""",
    )
    cell(
        "code",
        "cleanup",
        'if "MORPHIQ_API_KEY" in os.environ:\n'
        '    del os.environ["MORPHIQ_API_KEY"]\n'
        'print("API key removed from the kernel environment.")',
    )
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "notebooks/00-start-here.ipynb"
    expected = json.dumps(notebook(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not target.exists() or target.read_text() != expected:
            raise SystemExit("Notebook is stale: run python scripts/generate_notebook.py")
        print("Start Here notebook matches the executable examples.")
    else:
        target.write_text(expected)


if __name__ == "__main__":
    main()
