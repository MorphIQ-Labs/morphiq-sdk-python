# Notebook examples

| Notebook | Covers | Requests on Run All |
| --- | --- | --- |
| [Quickstart](start-here.ipynb) | European and American pricing, then async usage | 4 |
| [European pricing](pricing/european.ipynb) | European call inputs, price, model and charge metadata | 1 |
| [American pricing](pricing/american.ipynb) | American put inputs, continuous dividend yield and results | 1 |
| [Async pricing](pricing/async.ipynb) | Sequential requests with `AsyncMorphIQ` and `await` | 2 |

| [Regime identification](regime/identification.ipynb) | Yahoo ticker input, daily closes, regime heads and provenance | 1 |

Each API example cell includes the complete script: request data, API call, response
fields and error handling. Each notebook runs independently.
Run `docker compose up --build`, or install the notebook extra and open it with
JupyterLab. Docker opens the quickstart; its links and Jupyter's file browser open
the feature notebooks. See [the notebook guide](../docs/NOTEBOOKS.md) for credentials,
persistence and networking.

Regenerate all notebooks with `python scripts/generate_notebook.py`; `--check` verifies
agreement with the executable examples. Committed cells contain no executed
outputs or credentials. CI executes API cells against loopback contract fixtures with synthetic CSV data;
the Yahoo download cell is skipped in offline tests.
