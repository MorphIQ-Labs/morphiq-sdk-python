"""Seed missing notebook files, preserve edits, then run authenticated JupyterLab."""

import os
from pathlib import Path


def main() -> None:
    workspace = Path("/home/notebook/work")
    workspace.mkdir(parents=True, exist_ok=True)
    for source in Path("/opt/morphiq/notebooks").glob("*.ipynb"):
        destination = workspace / source.name
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
            "--ServerApp.default_url=/lab/tree/00-start-here.ipynb",
            f"--ServerApp.custom_display_url=http://127.0.0.1:{port}",
        ],
    )


if __name__ == "__main__":
    main()
