"""Execute a notebook against loopback contract fixtures; no external API calls."""

from __future__ import annotations

import argparse
import csv
import json
import os
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import nbformat
from nbclient import NotebookClient

NOTEBOOK_CASES = {
    "start-here.ipynb": ("european", "american", "european", "american"),
    "pricing/european.ipynb": ("european",),
    "pricing/american.ipynb": ("american",),
    "pricing/async.ipynb": ("european", "american"),
    "regime/identification.ipynb": ("regime",),
}


def write_fixture_prices(directory: Path, prices: list[float]) -> None:
    """Supply synthetic CSV input without contacting Yahoo or modifying examples."""
    with (directory / "prices.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Date", "Close"])
        for index, price in enumerate(prices):
            writer.writerow([(date(2020, 1, 1) + timedelta(days=index)).isoformat(), price])


def execute(notebook_path: Path, fixture_paths: list[Path], notebook_root: Path) -> None:
    cases = [case for path in fixture_paths for case in json.loads(path.read_text())["cases"]]
    by_name = {case["name"]: case for case in cases}
    relative_path = notebook_path.relative_to(notebook_root).as_posix()
    expected = [by_name[name]["request"] for name in NOTEBOOK_CASES[relative_path]]
    received: list[dict[str, Any]] = []
    credential = "notebook-container-test-only"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            match = next((case for case in cases if case["request"] == body), None)
            if (
                self.path != (match or {}).get("path", "/v1/price")
                or self.headers.get("Authorization") != f"Bearer {credential}"
                or match is None
            ):
                self.send_error(422)
                return
            received.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(match["response"]).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        notebook = nbformat.read(notebook_path, as_version=4)  # type: ignore[no-untyped-call]
        nbformat.validate(notebook)
        with TemporaryDirectory() as working_directory:
            write_fixture_prices(Path(working_directory), by_name["regime"]["request"]["prices"])
            executed = NotebookClient(
                notebook,
                timeout=60,
                kernel_name="python3",
                skip_cells_with_tag="requires-network",
                resources={"metadata": {"path": working_directory}},
            ).execute(
                env={
                    **os.environ,
                    "MORPHIQ_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "MORPHIQ_API_KEY": credential,
                }
            )
        if received != expected or credential in json.dumps(executed):
            raise RuntimeError("Unexpected requests or a credential in notebook output")
        print(f"{relative_path}: {len(received)} fixture requests; no credential in output.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", required=True, type=Path)
    parser.add_argument("--notebook-root", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    execute(args.notebook, args.fixtures, args.notebook_root)


if __name__ == "__main__":
    main()
