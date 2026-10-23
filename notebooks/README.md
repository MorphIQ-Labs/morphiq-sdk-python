# Analysis workspaces

Open [Start Here](start-here.ipynb), choose a workspace, and run all cells once.
Use the controls to load data and run an analysis; no code edits are required.

| Workspace | Tools | API requests per action |
| --- | --- | --- |
| [Option pricing](pricing/options.ipynb) | European/American and model selectors, call/put, option inputs, automatic Yahoo daily/intraday underlying prices, comparison table, spot-sensitivity chart | Price: 1; sensitivity: 9 sequential |
| [Regime analysis](regime/identification.ipynb) | Ticker and interval selection, automatic Yahoo daily/intraday price-history chart, latest regime assessment, score charts, provenance | Analyze: 1 |

Setup, control changes and Yahoo downloads make no MorphIQ requests. Data stays
in memory. Run `docker compose up --build`, or install `.[notebooks]` and open
JupyterLab. Set `MORPHIQ_API_KEY` before startup, or use the masked prompt.
See [the notebook guide](../docs/NOTEBOOKS.md) for environment and persistence.

These notebooks are analysis tools. The Python scripts in `examples/` separately
demonstrate SDK usage. Notebook code is self-contained and can be expanded for
inspection. Committed notebooks contain no executed outputs or widget state.

`python scripts/generate_notebook.py --check` verifies the start page and clean
notebooks. Tests exercise widget actions against synthetic contract fixtures,
including input conversion, scenario ordering, failure handling and stale-data clearing.
