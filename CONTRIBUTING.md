# Contributing

Start with the development commands in [README.md](README.md), then read
[AGENTS.md](AGENTS.md) and [the contract design](docs/CONTRACT.md).

Create a feature branch from main, link the relevant [GitHub issue](docs/ROADMAP.md),
and open a GitHub pull request. Use a conventional commit title such as
`feat(client): add synchronous pricing`. Changes merge by squash after review
and successful checks.

Run Ruff lint and formatting, mypy, and package verification before opening a PR.
Behavior changes need focused tests against the reviewed contract and updated
runnable examples. Routine CI must not call a billed production API.

Verify installed wheels outside the checkout so source-tree imports cannot hide
a broken distribution. Notebook tests require the development lock installed;
`python scripts/generate_notebook.py --check` must pass after example changes.

Regenerate each dependency lock with pinned uv, retaining hashes and platform markers:

```sh
python -m uv pip compile --universal --python-version 3.11 --generate-hashes requirements-dev.in -o requirements-dev.txt
python -m uv pip compile --universal --python-version 3.11 --generate-hashes requirements-notebook.in -o requirements-notebook.txt
python -m uv pip compile --universal --python-version 3.11 --generate-hashes requirements-build.in -o requirements-build.txt
```

Keep the Hatchling pin aligned with pyproject.toml. Its runtime bounds remain
suitable for downstream consumers; locks make CI/container builds reproducible.

Ordinary tests use synthetic native-response fixtures and a loopback replay
server. To opt into native service comparison, build the API source recorded in
contracts/provenance.json, start it on a controlled local port in open admission
mode, then run:

```sh
MORPHIQ_TEST_API_URL=http://127.0.0.1:18080 python -m pytest -q -m integration
```

The test verifies the served contract digest before sending pricing requests.
Never point it at a billed production endpoint. Native integration requires the
API repository's build access; public SDK tests/builds do not.

For Docker changes run `docker compose build` and
`python scripts/check_notebook_container.py`. This removes only its own randomly
named test container and volume.

Public distribution and automated releases are dedicated work in [RELEASE.md](RELEASE.md).
Do not add licensing, change visibility or publish as an incidental code change.
