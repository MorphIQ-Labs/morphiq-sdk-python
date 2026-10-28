"""Generate the notebook start page and validate the analysis notebooks."""

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


def regime_sources(filename: str = "identify_regime.py") -> tuple[str, str]:
    """Keep download and API cells separate while copying the executable example."""
    source = example_source(filename)
    download, separator, request = source.partition(
        "# Submit the downloaded prices directly to MorphIQ.\n"
    )
    if not separator:
        raise ValueError("Regime example is missing its API section marker")
    tree = ast.parse((ROOT / "examples" / filename).read_text())
    download = download[download.index("ticker =") :]

    def with_imports(body: str) -> str:
        names = {node.id for node in ast.walk(ast.parse(body)) if isinstance(node, ast.Name)}
        groups: dict[str, list[str]] = {"stdlib": [], "third_party": [], "sdk": []}
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if not any((alias.asname or alias.name) in names for alias in node.names):
                continue
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            group = (
                "sdk"
                if module == "morphiq_sdk"
                else ("third_party" if module == "yfinance" else "stdlib")
            )
            groups[group].append(ast.unparse(node))
        imports = "\n\n".join("\n".join(group) for group in groups.values() if group)
        return imports + "\n\n" + body.strip()

    return with_imports(download), with_imports(request)


def notebook() -> dict[str, Any]:
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "id": "welcome",
                "metadata": {},
                "source": """# MorphIQ SDK for Python — Start Here

## Choose an analysis

- [Cost quotation](cost/quotation.ipynb): inspect active rates, quote a synthetic
  option, and explicitly execute with a maximum CU charge.
- [Option pricing](pricing/options.ipynb): value European or American calls and puts,
  load a daily or intraday underlying price from Yahoo, inspect Greeks, solve implied
  volatility, analyze a premium with Greeks, track session CU, and chart sensitivity.
- [Regime analysis](regime/identification.ipynb): load daily or intraday price history
  and inspect the latest regime assessment, scores and model provenance.

Open a workspace and select **Run → Run All Cells** once to display its controls.
Then use its buttons. Running the setup makes no MorphIQ requests; each action button
states how many requests it sends. All market data stays in memory.

## API access

Get your API key from [the developer portal](https://developers.morphiqlabs.com).
Set `MORPHIQ_API_KEY` before starting Docker or Jupyter, or enter it at the masked
prompt in a workspace. The SDK connects to `https://api.morphiqlabs.com`.

Docker includes the SDK, widgets, plotting and Yahoo dependencies. Outside Docker,
install this repository with `pip install -e '.[notebooks]'`, then open JupyterLab.

Workspaces retain results in the current kernel. Clear outputs before sharing and
shut down the kernel when finished. Notebook edits persist across Docker restarts.
The executable Python scripts in `examples/` demonstrate SDK usage separately.
""",
            }
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def notebooks() -> dict[str, dict[str, Any]]:
    result = {"start-here.ipynb": notebook()}
    # Analysis notebooks are authored directly; tests verify their SDK requests.
    for filename in (
        "pricing/options.ipynb",
        "regime/identification.ipynb",
        "cost/quotation.ipynb",
    ):
        content = json.loads((ROOT / "notebooks" / filename).read_text())
        if "widgets" in content["metadata"]:
            raise ValueError(f"{filename}: remove saved widget state before committing")
        for cell in content["cells"]:
            if cell["cell_type"] == "code" and (
                cell["outputs"] or cell["execution_count"] is not None
            ):
                raise ValueError(f"{filename}: clear executed outputs before committing")
        result[filename] = content
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for filename, content in notebooks().items():
        target = ROOT / "notebooks" / filename
        expected = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not target.exists() or target.read_text() != expected:
                raise SystemExit(f"{filename} is stale: run python scripts/generate_notebook.py")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected)
    if args.check:
        print("Start page is current; analysis notebooks contain no saved outputs or widget state.")


if __name__ == "__main__":
    main()
