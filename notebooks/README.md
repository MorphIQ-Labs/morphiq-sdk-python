# Notebook examples

| Notebook | Covers | Requests on Run All |
| --- | --- | --- |
| [Quickstart](00-start-here.ipynb) | European and American pricing, then async usage | 4 |
| [European pricing](01-european-pricing.ipynb) | European call inputs, price, model and charge metadata | 1 |
| [American pricing](02-american-pricing.ipynb) | American put inputs, continuous dividend yield and results | 1 |
| [Async pricing](03-async-pricing.ipynb) | Sequential requests with `AsyncMorphIQ` and `await` | 2 |

Each pricing cell includes the complete script: request data, API call, response
fields and error handling. Each notebook runs independently.
Run `docker compose up --build`, or install the notebook extra and open it with
JupyterLab. Docker opens the quickstart; its links and Jupyter's file browser open
the feature notebooks. See [the notebook guide](../docs/NOTEBOOKS.md) for credentials,
persistence and networking.

Regenerate all notebooks with `python scripts/generate_notebook.py`; `--check` verifies
agreement with the executable examples. Committed cells contain no executed
outputs or credentials. CI executes them against a loopback native-response replay.
