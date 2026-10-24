"""Verify local image startup, auth, notebook execution and workspace persistence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def docker(*arguments: str) -> str:
    return subprocess.check_output(["docker", *arguments], text=True).strip()


def check(image: str) -> None:
    identifier = "morphiq-notebook-check-" + uuid.uuid4().hex[:10]
    volume = identifier + "-work"

    def start() -> tuple[str, str]:
        docker(
            "run",
            "--detach",
            "--init",
            "--name",
            identifier,
            "--publish",
            "127.0.0.1::8888",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--mount",
            f"type=volume,src={volume},dst=/home/notebook/work",
            image,
        )
        binding = docker("port", identifier, "8888/tcp")
        if not binding.startswith("127.0.0.1:"):
            raise RuntimeError("Notebook port is not restricted to loopback")
        endpoint = "http://" + binding
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with urlopen(endpoint + "/login", timeout=2) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, ConnectionError):
                if docker("inspect", "--format", "{{.State.Running}}", identifier) != "true":
                    raise RuntimeError("Notebook container exited before readiness") from None
                time.sleep(1)
        else:
            raise RuntimeError("Notebook did not become ready within 90 seconds")
        # Capture the ephemeral Jupyter token in memory only; never print it.
        records = docker(
            "exec",
            identifier,
            "python",
            "-c",
            (
                "import json,pathlib; "
                "print(json.dumps([json.loads(p.read_text()) for p in "
                "pathlib.Path('/home/notebook/.local/share/jupyter/runtime').glob('jpserver-*.json')]))"
            ),
        )
        token = str(json.loads(records)[0]["token"])
        if not token or docker("exec", identifier, "id", "-u") == "0":
            raise RuntimeError("Notebook must use token authentication and a non-root user")
        return endpoint, token

    def contents(
        endpoint: str,
        token: str,
        filename: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = Request(
            endpoint + "/api/contents/" + filename,
            headers={"Authorization": "token " + token, "Content-Type": "application/json"},
            data=json.dumps(payload).encode() if payload is not None else None,
            method="PUT" if payload is not None else "GET",
        )
        with urlopen(request, timeout=10) as response:
            result: dict[str, Any] = json.load(response)
            return result

    try:
        endpoint, token = start()
        try:
            urlopen(endpoint + "/api/contents", timeout=5)
        except HTTPError as error:
            if error.code != 403:
                raise RuntimeError("Unexpected unauthenticated notebook response") from None
        else:
            raise RuntimeError("Notebook contents are accessible without authentication")
        notebook_root = ROOT / "notebooks"
        filenames = [
            path.relative_to(notebook_root).as_posix()
            for path in sorted(notebook_root.rglob("*.ipynb"))
        ]
        saved = {filename: contents(endpoint, token, filename) for filename in filenames}
        for filename, item in saved.items():
            if "MorphIQ SDK for Python" not in item["content"]["cells"][0]["source"]:
                raise RuntimeError(f"{filename} was not seeded")
        print(
            "Local Jupyter startup, token authentication and all seeded notebooks verified.",
            flush=True,
        )
        for name in ("pricing", "regime", "greeks", "implied_volatility"):
            docker(
                "cp", str(ROOT / f"tests/fixtures/{name}.json"), identifier + f":/tmp/{name}.json"
            )
        docker(
            "cp",
            str(ROOT / "scripts/execute_notebook_fixture.py"),
            identifier + ":/tmp/execute_notebook_fixture.py",
        )
        marker = "Workspace persistence verified"
        for filename, item in saved.items():
            print(
                docker(
                    "exec",
                    identifier,
                    "python",
                    "/tmp/execute_notebook_fixture.py",
                    "--notebook",
                    "/home/notebook/work/" + filename,
                    "--notebook-root",
                    "/home/notebook/work",
                    "--fixtures",
                    "/tmp/pricing.json",
                    "/tmp/regime.json",
                    "/tmp/greeks.json",
                    "/tmp/implied_volatility.json",
                ),
                flush=True,
            )
            item["content"]["cells"][0]["source"] += "\n\n" + marker
            contents(endpoint, token, filename, {"type": "notebook", "content": item["content"]})
        # An existing workspace must receive a missing feature notebook on restart.
        missing = next(filename for filename in saved if filename != "start-here.ipynb")
        docker(
            "exec",
            identifier,
            "python",
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink()",
            "/home/notebook/work/" + missing,
        )
        docker("rm", "--force", identifier)
        endpoint, token = start()
        for filename, item in saved.items():
            restored = contents(endpoint, token, filename)["content"]["cells"][0]["source"]
            expected = item["content"]["cells"][0]["source"]
            if filename == missing:
                expected = expected.removesuffix("\n\n" + marker)
            if restored != expected:
                raise RuntimeError(
                    f"Notebook persistence or missing-file seeding failed: {filename}"
                )
        print(
            "Notebook edits survived recreation and the missing feature notebook was seeded.",
            flush=True,
        )
    finally:
        for arguments in (("rm", "--force", identifier), ("volume", "rm", volume)):
            subprocess.run(["docker", *arguments], capture_output=True, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="morphiq-sdk-python-notebook")
    args = parser.parse_args()
    check(args.image)


if __name__ == "__main__":
    main()
