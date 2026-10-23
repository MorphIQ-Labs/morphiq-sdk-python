"""Execute a notebook against loopback native-response fixtures; no external API calls."""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient

NOTEBOOK_CASES = {
    "00-start-here.ipynb": ("european", "american", "european", "american"),
    "01-european-pricing.ipynb": ("european",),
    "02-american-pricing.ipynb": ("american",),
    "03-async-pricing.ipynb": ("european", "american"),
}


def execute(notebook_path: Path, fixture_path: Path) -> None:
    cases = json.loads(fixture_path.read_text())["cases"]
    by_name = {case["name"]: case for case in cases}
    expected = [by_name[name]["request"] for name in NOTEBOOK_CASES[notebook_path.name]]
    received: list[dict[str, Any]] = []
    credential = "notebook-container-test-only"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            match = next((case for case in cases if case["request"] == body), None)
            if (
                self.path != "/v1/price"
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
        executed = NotebookClient(notebook, timeout=60, kernel_name="python3").execute(
            env={
                **os.environ,
                "MORPHIQ_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "MORPHIQ_API_KEY": credential,
            }
        )
        if received != expected or credential in json.dumps(executed):
            raise RuntimeError("Unexpected requests or a credential in notebook output")
        print(f"{notebook_path.name}: {len(received)} fixture requests; no credential in output.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path)
    args = parser.parse_args()
    execute(args.notebook, args.fixtures)


if __name__ == "__main__":
    main()
