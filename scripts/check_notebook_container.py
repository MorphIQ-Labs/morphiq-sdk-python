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
        endpoint: str, token: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request = Request(
            endpoint + "/api/contents/00-start-here.ipynb",
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
        saved = contents(endpoint, token)
        if "MorphIQ SDK for Python" not in saved["content"]["cells"][0]["source"]:
            raise RuntimeError("Start Here was not seeded")
        print(
            "Local Jupyter startup, token authentication and seeded notebook verified.", flush=True
        )
        docker("cp", str(ROOT / "tests/fixtures/pricing.json"), identifier + ":/tmp/pricing.json")
        docker(
            "cp",
            str(ROOT / "scripts/execute_notebook_fixture.py"),
            identifier + ":/tmp/execute_notebook_fixture.py",
        )
        print(
            docker(
                "exec",
                identifier,
                "python",
                "/tmp/execute_notebook_fixture.py",
                "--notebook",
                "/home/notebook/work/00-start-here.ipynb",
                "--fixtures",
                "/tmp/pricing.json",
            ),
            flush=True,
        )
        marker = "Workspace persistence verified"
        saved["content"]["cells"][0]["source"] += "\n\n" + marker
        contents(endpoint, token, {"type": "notebook", "content": saved["content"]})
        docker("rm", "--force", identifier)
        endpoint, token = start()
        if marker not in contents(endpoint, token)["content"]["cells"][0]["source"]:
            raise RuntimeError("Recreating the container overwrote user notebook edits")
        print(
            "Notebook edits survived container recreation with the same workspace volume.",
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
