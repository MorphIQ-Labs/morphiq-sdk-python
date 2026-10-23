"""Keep package metadata, release proposals and immutable tags in agreement."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

RELEASE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


def check(root: Path, title: str = "") -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    manifest = json.loads((root / ".release-please-manifest.json").read_text())
    if not manifest:
        # Before the first generated release PR, this is explicitly unreleased.
        if version != "0.1.0.dev0":
            raise ValueError("An empty release manifest requires the unreleased bootstrap version")
    elif manifest != {".": version} or not RELEASE_VERSION.fullmatch(version):
        raise ValueError("Package version must match the stable release manifest version")

    if title.startswith("chore: release ") and title != f"chore: release v{version}":
        raise ValueError("Release PR title must match the package version")
    if title.startswith("chore: release ") and not RELEASE_VERSION.fullmatch(version):
        raise ValueError("Release PR must propose a stable version")

    for tag in git(root, "tag", "--list", "v*").splitlines():
        if not RELEASE_VERSION.fullmatch(tag[1:]):
            raise ValueError(f"Unexpected release tag format: {tag}")
        tagged_project = tomllib.loads(git(root, "show", f"{tag}:pyproject.toml"))["project"]
        tagged_manifest = json.loads(git(root, "show", f"{tag}:.release-please-manifest.json"))
        if tagged_project.get("version") != tag[1:] or tagged_manifest != {".": tag[1:]}:
            raise ValueError(f"Tag {tag} does not match its package and manifest versions")
    print(f"Package, release proposal and tags verified: {version}")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1], os.environ.get("PR_TITLE", ""))
