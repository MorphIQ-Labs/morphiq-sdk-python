# Analysis workspaces

Open the Docker dashboard launcher and choose a workspace. Its controls initialize
automatically through Voilà. Use the controls to load data and run an analysis; no code edits are required.

| Workspace | Tools | API requests per action |
| --- | --- | --- |
| [Option pricing](pricing/options.ipynb) | European/American and model selectors, call/put, option inputs, Yahoo underlying close, comparison table, spot-sensitivity chart | Price: 1; sensitivity: 9 sequential |
| [Regime analysis](regime/identification.ipynb) | Ticker selection, Yahoo price-history chart, latest regime assessment, score charts, provenance | Analyze: 1 |

Setup, control changes and Yahoo downloads make no MorphIQ requests. Data stays
in memory. Run `docker compose up --build`, or install `.[notebooks]` and open
JupyterLab and visit `/voila/render/start-here.ipynb`. Set `MORPHIQ_API_KEY` before
startup; otherwise API actions remain disabled. The JupyterLab editor is available
through each dashboard’s **Edit notebook** link and requires Run All Cells.
See [the notebook guide](../docs/NOTEBOOKS.md) for environment and persistence.

These notebooks are analysis tools. The Python scripts in `examples/` separately
demonstrate SDK usage. Notebook code is self-contained and can be expanded for
inspection. Committed notebooks contain no executed outputs or widget state.

`python scripts/generate_notebook.py --check` verifies the start page and clean
notebooks. Tests exercise widget actions against synthetic contract fixtures,
including input conversion, scenario ordering, failure handling and stale-data clearing.
