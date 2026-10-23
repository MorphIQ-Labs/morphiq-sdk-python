"""Exercise release checks against disposable Git history, never repository tags."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_release_version import check


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.name", "Release test")
    run_git(tmp_path, "config", "user.email", "test@example.invalid")
    run_git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def metadata(root: Path, version: str, manifest: dict[str, str]) -> None:
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (root / ".release-please-manifest.json").write_text(json.dumps(manifest))


def test_unreleased_bootstrap(repository: Path) -> None:
    metadata(repository, "0.1.0.dev0", {})
    check(repository)
    with pytest.raises(ValueError, match="stable version"):
        check(repository, "chore: release v0.1.0.dev0")


def test_generated_release_proposal(repository: Path) -> None:
    metadata(repository, "0.1.0", {".": "0.1.0"})
    check(repository, "chore: release v0.1.0")
    with pytest.raises(ValueError, match="title"):
        check(repository, "chore: release v0.2.0")


def test_manifest_mismatch(repository: Path) -> None:
    metadata(repository, "0.1.1", {".": "0.1.0"})
    with pytest.raises(ValueError, match="manifest"):
        check(repository)


def test_tag_uses_its_own_commit_version(repository: Path) -> None:
    metadata(repository, "0.1.0", {".": "0.1.0"})
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-m", "chore: release v0.1.0")
    run_git(repository, "tag", "v0.1.0")
    metadata(repository, "0.1.1", {".": "0.1.1"})
    check(repository, "chore: release v0.1.1")
    # A tag naming the wrong historical version must fail even if HEAD matches.
    run_git(repository, "tag", "v0.1.1")
    with pytest.raises(ValueError, match="Tag v0.1.1"):
        check(repository)


def test_release_without_manifest_is_rejected(repository: Path) -> None:
    metadata(repository, "0.1.0", {})
    with pytest.raises(ValueError, match="empty release manifest"):
        check(repository)
