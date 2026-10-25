"""Fail closed before public uploads; verify the exact files served by an index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STABLE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
INDEX_HOSTS = {"testpypi": "test.pypi.org", "pypi": "pypi.org"}
FILE_HOSTS = {"files.pythonhosted.org", "test-files.pythonhosted.org"}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def github(path: str) -> Any:
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def check_environments(environments: list[dict[str, Any]]) -> None:
    for name in ("testpypi", "pypi"):
        environment = next((env for env in environments if env["name"] == name), {})
        reviewers: dict[str, Any] = next(
            (
                r
                for r in environment.get("protection_rules", [])
                if r["type"] == "required_reviewers"
            ),
            {},
        )
        if (
            not reviewers.get("reviewers")
            or reviewers.get("prevent_self_review") is not True
            or not (environment.get("deployment_branch_policy") or {}).get("custom_branch_policies")
        ):
            raise ValueError(f"{name} must have reviewers, no self-review and selected refs")


def check_project(project: dict[str, Any], manifest: dict[str, str], tag: str) -> None:
    if not STABLE_TAG.fullmatch(tag):
        raise ValueError("Expected a stable Release Please tag: vX.Y.Z")
    if (
        project.get("name") != "morphiq-sdk"
        or project.get("version") != tag[1:]
        or manifest != {".": tag[1:]}
    ):
        raise ValueError("Tag, package name/version and release manifest must agree")
    if any(c.startswith("Private ::") for c in project.get("classifiers", [])):
        raise ValueError("Private package: publication has not been approved")
    if not isinstance(project.get("license"), str) or not project["license"].strip():
        raise ValueError("A reviewed SPDX license expression is required")
    if not project.get("license-files"):
        raise ValueError("Explicit license-files are required in the distribution")


def preflight(root: Path, tag: str, repository: str) -> str:
    if not STABLE_TAG.fullmatch(tag):
        raise ValueError("Expected a stable Release Please tag: vX.Y.Z")
    commit = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/main"], cwd=root, check=True
    )
    project = tomllib.loads(git(root, "show", f"{commit}:pyproject.toml"))["project"]
    manifest = json.loads(git(root, "show", f"{commit}:.release-please-manifest.json"))
    check_project(project, manifest, tag)
    release = github(f"repos/{repository}/releases/tags/{tag}")
    if release.get("draft") or release.get("prerelease") or release.get("tag_name") != tag:
        raise ValueError("An existing published, stable GitHub release is required")
    environments = github(f"repos/{repository}/environments?per_page=100")["environments"]
    check_environments(environments)
    return commit


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_names(version: str) -> set[str]:
    if not STABLE_TAG.fullmatch(f"v{version}"):
        raise ValueError("Expected a stable package version")
    return {f"morphiq_sdk-{version}-py3-none-any.whl", f"morphiq_sdk-{version}.tar.gz"}


def record_artifacts(root: Path, directory: Path, tag: str, report: Path) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    check_project(project, json.loads((root / ".release-please-manifest.json").read_text()), tag)
    version = tag[1:]
    names = artifact_names(version)
    if {p.name for p in directory.iterdir()} != names:
        raise ValueError("Expected only the release wheel and sdist")
    for name in sorted(names):
        path = directory / name
        if name.endswith(".whl"):
            with zipfile.ZipFile(path) as wheel:
                metadata_name = f"morphiq_sdk-{version}.dist-info/METADATA"
                metadata = BytesParser().parsebytes(wheel.read(metadata_name))
                license_paths = [
                    f"morphiq_sdk-{version}.dist-info/licenses/{item}"
                    for item in metadata.get_all("License-File", [])
                ]
                licenses_present = bool(license_paths) and all(
                    item in wheel.namelist() and wheel.read(item) for item in license_paths
                )
        else:
            with tarfile.open(path) as source:
                metadata_file = source.extractfile(f"morphiq_sdk-{version}/PKG-INFO")
                if metadata_file is None:
                    raise ValueError("Missing sdist metadata")
                metadata = BytesParser().parsebytes(metadata_file.read())
                license_paths = [
                    f"morphiq_sdk-{version}/{item}" for item in metadata.get_all("License-File", [])
                ]
                licenses_present = bool(license_paths) and all(
                    item in source.getnames() and source.getmember(item).size > 0
                    for item in license_paths
                )
        if (
            metadata["Name"] != "morphiq-sdk"
            or metadata["Version"] != version
            or metadata["License-Expression"] != project["license"]
            or any(c.startswith("Private ::") for c in metadata.get_all("Classifier", []))
            or not licenses_present
        ):
            raise ValueError(f"Distribution identity/license mismatch: {name}")
    report.write_text(
        json.dumps(
            {
                "tag": tag,
                "version": version,
                "commit": git(root, "rev-parse", "HEAD"),
                "files": {name: digest(directory / name) for name in sorted(names)},
            },
            indent=2,
        )
        + "\n"
    )


def check_local(directory: Path, report: dict[str, Any]) -> None:
    if report["tag"] != f"v{report['version']}" or set(report["files"]) != artifact_names(
        report["version"]
    ):
        raise ValueError("Invalid artifact manifest")
    if {p.name for p in directory.iterdir()} != set(report["files"]):
        raise ValueError("Unexpected local artifacts")
    if any(digest(directory / name) != sha for name, sha in report["files"].items()):
        raise ValueError("Local artifact digest mismatch")


def check_index_metadata(
    data: dict[str, Any], report: dict[str, Any], *, partial: bool = False
) -> dict[str, str]:
    files = data["urls"]
    names = {f["filename"] for f in files}
    expected = set(report["files"])
    if len(files) != len(names) or not names <= expected or (not partial and names != expected):
        raise ValueError("Index file set does not match the built release")
    urls = {}
    for file in files:
        name, url = file["filename"], file["url"]
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname not in FILE_HOSTS
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
        ):
            raise ValueError("Unexpected package download origin")
        if file.get("yanked") or file["digests"]["sha256"] != report["files"][name]:
            raise ValueError("Index artifact is yanked or its digest differs")
        urls[name] = url
    return urls


def prepare_upload(index: str, report: dict[str, Any], directory: Path, destination: Path) -> int:
    url = f"https://{INDEX_HOSTS[index]}/pypi/morphiq-sdk/{report['version']}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            existing = check_index_metadata(json.load(response), report, partial=True)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        existing = {}
    destination.mkdir(parents=True, exist_ok=False)
    missing = report["files"].keys() - existing.keys()
    for name in missing:
        shutil.copyfile(directory / name, destination / name)
    return len(missing)


def verify_index(index: str, report: dict[str, Any], destination: Path) -> None:
    url = f"https://{INDEX_HOSTS[index]}/pypi/morphiq-sdk/{report['version']}/json"
    # Only index reads are retried, to allow CDN propagation; uploads are never retried here.
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.load(response)
            urls = check_index_metadata(data, report)
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or attempt == 5:
                raise
            time.sleep(10)
    destination.mkdir(parents=True, exist_ok=False)
    for name, file_url in urls.items():
        with urllib.request.urlopen(file_url, timeout=60) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != report["files"][name]:
            raise ValueError(f"Downloaded artifact digest mismatch: {name}")
        (destination / name).write_bytes(content)
    print(f"Verified {index} wheel and sdist against the build manifest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("preflight")
    prepare.add_argument("--tag", required=True)
    prepare.add_argument("--repository", required=True)
    artifacts = commands.add_parser("artifacts")
    artifacts.add_argument("--tag", required=True)
    for command in (
        artifacts,
        commands.add_parser("local"),
        commands.add_parser("index"),
        commands.add_parser("pending"),
    ):
        command.add_argument("--directory", type=Path, default=Path("dist"))
        command.add_argument("--report", type=Path, default=Path("release-artifacts.json"))
        if command.prog.endswith((" index", " pending")):
            command.add_argument("--index", choices=INDEX_HOSTS, required=True)
            command.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    if args.command == "preflight":
        commit = preflight(root, args.tag, args.repository)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"commit={commit}\ntag={args.tag}\nversion={args.tag[1:]}\n")
    elif args.command == "artifacts":
        record_artifacts(root, args.directory, args.tag, args.report)
    else:
        report = json.loads(args.report.read_text())
        check_local(args.directory, report)
        if args.command == "index":
            verify_index(args.index, report, args.destination)
        elif args.command == "pending":
            count = prepare_upload(args.index, report, args.directory, args.destination)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"count={count}\n")


if __name__ == "__main__":
    main()
