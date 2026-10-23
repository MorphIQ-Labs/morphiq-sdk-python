# Contributing

Start with the development commands in [README.md](README.md), then read
[AGENTS.md](AGENTS.md) and [the contract design](docs/CONTRACT.md).

Create a feature branch from main, link the relevant [GitLab work item](docs/ROADMAP.md),
and open a GitHub pull request. Use a conventional commit title such as
`feat(client): add synchronous pricing`. Changes merge by squash after review
and successful checks.

Run Ruff lint and formatting, mypy, and package verification before opening a PR.
Behavior changes need focused tests against the reviewed contract and updated
runnable examples. Routine CI must not call a billed production API.

Verify installed wheels outside the checkout so source-tree imports cannot hide
a broken distribution. Update pinned development tools in a separate verified
change; keep the Hatchling pins in pyproject.toml and requirements-dev.txt aligned.

Public distribution and automated releases are dedicated work in [RELEASE.md](RELEASE.md).
Do not add licensing, change visibility or publish as an incidental code change.
