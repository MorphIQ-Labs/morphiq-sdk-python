"""Local solver example: browser controls -> Python SDK -> MorphIQ API.

Run from a checkout with the SDK installed: python examples/solver_app/app.py
Credentials stay in this process. No requests on startup, no local option math,
no automatic execution/retry, and one upstream request per explicit action.
"""

from __future__ import annotations

import argparse
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from morphiq_sdk import (
    APIError,
    MorphIQ,
    ResponseError,
    ScenarioSpotSolveRequest,
    TransportError,
)

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class SolverApp(HTTPServer):
    """One local user, sequential actions, one current single-use quote."""

    def __init__(self, client: MorphIQ, port: int = 8765) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.client = client
        self.quote: tuple[str, dict[str, Any], int] | None = None
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def action(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path == "/api/quote":
            self.quote = None
        request = ScenarioSpotSolveRequest.model_validate(payload["request"])
        wire = request.to_wire()
        if path == "/api/quote":
            # Quoting does not execute the solver or reserve funds.
            quote = self.client.quote(request)
            token = secrets.token_urlsafe(24)
            self.quote = (token, wire, quote.quote.total_fcu)
            return {
                "ok": True,
                "quote_id": token,
                "quoted_cu": str(quote.quote.total_fcu),
                "raw_response": quote.raw_body.decode(errors="replace"),
                "charged_cu": str(quote.metadata.fcu_charged)
                if quote.metadata.fcu_charged is not None
                else None,
            }
        current = self.quote
        if current is None or payload.get("quote_id") != current[0] or wire != current[1]:
            raise ValueError("Get a new quote for these inputs before solving.")
        # Accept a decimal string so browser number rounding cannot change a CU cap.
        cap_text = payload.get("max_cu")
        if not isinstance(cap_text, str) or not cap_text.isascii() or not cap_text.isdecimal():
            raise ValueError("The CU limit must be a nonnegative whole number.")
        cap = int(cap_text)
        if cap > 2**64 - 1:
            raise ValueError("The CU limit must fit an unsigned 64-bit integer.")
        if cap < current[2]:
            raise ValueError("Quote exceeds the CU limit; no solve submitted.")
        # Consume before sending: even an unknown outcome cannot be replayed by
        # a double-click. A deliberate new quote is required for another solve.
        self.quote = None
        response = self.client.solve_spot(request, max_cu=cap)
        return {
            "ok": True,
            "raw_response": response.raw_body.decode(errors="replace"),
            "charged_cu": str(response.metadata.fcu_charged)
            if response.metadata.fcu_charged is not None
            else None,
        }


class Handler(BaseHTTPRequestHandler):
    server: SolverApp

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log credentials, inputs, query strings or response bodies.
        pass

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status: int, payload: dict[str, Any]) -> None:
        self.reply(status, json.dumps(payload).encode(), "application/json")

    def local_request(self) -> bool:
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            self.json_reply(403, {"ok": False, "message": "Use the printed local URL."})
            return False
        return True

    def do_GET(self) -> None:
        if not self.local_request():
            return
        asset = ASSETS.get(self.path)
        if asset is None:
            self.json_reply(404, {"ok": False, "message": "Not found"})
            return
        name, content_type = asset
        self.reply(200, Path(__file__).with_name(name).read_bytes(), content_type)

    def do_POST(self) -> None:
        if not self.local_request():
            return
        # No cross-origin billing through this local process, including requests
        # from unrelated localhost ports. There is no CORS or generic proxy route.
        if self.headers.get("Origin") != self.server.origin:
            self.json_reply(403, {"ok": False, "message": "Only this app may submit actions."})
            return
        if self.path not in ("/api/quote", "/api/solve"):
            self.json_reply(404, {"ok": False, "message": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768 or self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected a JSON request of at most 32 KiB.")
            payload = json.loads(self.rfile.read(length))
            allowed = (
                {"request"} if self.path == "/api/quote" else {"request", "quote_id", "max_cu"}
            )
            if not isinstance(payload, dict) or set(payload) != allowed:
                raise ValueError("Invalid action fields.")
            result = self.server.action(self.path, payload)
        except ValidationError:
            self.json_reply(
                400,
                {
                    "ok": False,
                    "message": "Invalid solver inputs; no API call.",
                    "local_refusal": True,
                },
            )
            return
        except (ValueError, KeyError, UnicodeError) as error:
            self.json_reply(400, {"ok": False, "message": str(error), "local_refusal": True})
            return
        except (APIError, ResponseError) as error:
            self.json_reply(
                502,
                {
                    "ok": False,
                    "message": str(error),
                    "upstream_status": error.status_code if isinstance(error, APIError) else None,
                    "request_id": error.request_id,
                    "metadata": error.metadata.model_dump(mode="json", exclude_unset=True)
                    if error.metadata
                    else None,
                    "raw_response": error.body.decode(errors="replace"),
                    "charged_cu": str(error.metadata.fcu_charged)
                    if error.metadata and error.metadata.fcu_charged is not None
                    else None,
                },
            )
            return
        except TransportError:
            self.json_reply(
                502,
                {
                    "ok": False,
                    "message": "No complete API response. Execution and charge unknown. "
                    "No retry attempted; reconcile before submitting again.",
                },
            )
            return
        self.json_reply(200, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=8765, help="loopback port (0 chooses a free port)"
    )
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    with MorphIQ() as client, SolverApp(client, args.port) as server:
        print(f"Solver app: {server.origin} (Ctrl+C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
