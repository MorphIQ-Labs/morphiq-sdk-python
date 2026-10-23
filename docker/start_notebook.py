"""Preserve notebook edits and serve authenticated dashboards with a JupyterLab editor."""

import os
from pathlib import Path


def main() -> None:
    workspace = Path("/home/notebook/work")
    workspace.mkdir(parents=True, exist_ok=True)
    notebooks = Path("/opt/morphiq/notebooks")
    for source in notebooks.rglob("*.ipynb"):
        destination = workspace / source.relative_to(notebooks)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as target:
                target.write(source.read_bytes())
        except FileExistsError:
            pass  # User edits survive restarts and image upgrades.
    port = int(os.environ.get("MORPHIQ_NOTEBOOK_PORT", "8888"))
    if not 1 <= port <= 65535:
        raise SystemExit("MORPHIQ_NOTEBOOK_PORT must be between 1 and 65535")
    # Keep Jupyter's default random token. The displayed URL uses the HOST port;
    # inside the container the listener always uses 8888.
    os.execvp(
        "jupyter",
        [
            "jupyter",
            "lab",
            "--ServerApp.ip=0.0.0.0",
            "--ServerApp.port=8888",
            "--ServerApp.port_retries=0",
            "--ServerApp.open_browser=False",
            f"--ServerApp.root_dir={workspace}",
            "--LabApp.default_url=/voila/render/start-here.ipynb",
            f"--ServerApp.custom_display_url=http://127.0.0.1:{port}",
        ],
    )


if __name__ == "__main__":
    main()
