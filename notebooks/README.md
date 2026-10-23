# Notebook examples

`00-start-here.ipynb` covers European/American pricing with sync and async clients.
Each pricing cell includes the complete script: request data, API call, response
fields and error handling.
Run `docker compose up --build`, or install the notebook extra and open it with
JupyterLab. See [the notebook guide](../docs/NOTEBOOKS.md) for credentials, four-call
Run All behavior, persistence and networking.

Regenerate it with `python scripts/generate_notebook.py`; `--check` verifies
agreement with the executable examples. Committed cells contain no executed
outputs or credentials. CI executes them against a loopback native-response replay.
