"""Publication guards must fail before any upload and support exact-file recovery."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.error
import zipfile
from copy import deepcopy

import pytest

from scripts.check_publish import (
    check_environments,
    check_index_metadata,
    check_local,
    check_project,
    preflight,
    prepare_upload,
    record_artifacts,
    verify_index,
)


@pytest.fixture
def report():
    return {
        "tag": "v0.1.0",
        "version": "0.1.0",
        "commit": "a" * 40,
        "files": {
            "morphiq_sdk-0.1.0-py3-none-any.whl": hashlib.sha256(b"wheel").hexdigest(),
            "morphiq_sdk-0.1.0.tar.gz": hashlib.sha256(b"sdist").hexdigest(),
        },
    }


@pytest.fixture
def index(report):
    return {
        "urls": [
            {
                "filename": name,
                "url": f"https://files.pythonhosted.org/packages/{name}",
                "digests": {"sha256": sha},
                "yanked": False,
            }
            for name, sha in report["files"].items()
        ]
    }


@pytest.fixture
def project():
    # Synthetic package metadata, not a license selection for this repository.
    return {
        "name": "morphiq-sdk",
        "version": "0.1.0",
        "license": "MIT",
        "license-files": ["LICENSE"],
    }


@pytest.mark.parametrize("tag", ["", "v0.1.0.dev0", "v1.0.0rc1", "--help", "v01.0.0", "v1.0.0\nx"])
def test_bad_tags_rejected_before_git_or_github(tmp_path, tag):
    with pytest.raises(ValueError, match="stable"):
        preflight(tmp_path, tag, "example/repo")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "other"}, "agree"),
        ({"version": "0.1.1"}, "agree"),
        ({"classifiers": ["Private :: Do Not Upload"]}, "Private"),
        ({"license": None}, "license expression"),
        ({"license": {"file": "LICENSE"}}, "license expression"),
        ({"license-files": []}, "license-files"),
    ],
)
def test_publication_metadata_rejects_unapproved_or_mismatched_source(project, change, message):
    project.update(change)
    with pytest.raises(ValueError, match=message):
        check_project(project, {".": "0.1.0"}, "v0.1.0")


def test_manifest_must_match_release(project):
    check_project(project, {".": "0.1.0"}, "v0.1.0")
    with pytest.raises(ValueError, match="agree"):
        check_project(project, {}, "v0.1.0")


@pytest.fixture
def environments():
    return [
        {
            "name": name,
            "deployment_branch_policy": {"custom_branch_policies": True},
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "reviewers": [{"type": "Team", "id": 1}],
                    "prevent_self_review": True,
                }
            ],
        }
        for name in ("testpypi", "pypi")
    ]


def test_both_environments_must_be_protected(environments):
    check_environments(environments)
    for envs in ([], environments[:1]):
        with pytest.raises(ValueError, match="must have reviewers"):
            check_environments(envs)
    for key, value in (("deployment_branch_policy", None),):
        broken = deepcopy(environments)
        broken[1][key] = value
        with pytest.raises(ValueError, match="pypi"):
            check_environments(broken)
    for key, value in (("reviewers", []),):
        broken = deepcopy(environments)
        broken[0]["protection_rules"][0][key] = value
        with pytest.raises(ValueError, match="testpypi"):
            check_environments(broken)


def test_index_requires_exact_complete_release_except_when_resuming(index, report):
    assert len(check_index_metadata(index, report)) == 2
    index["urls"].pop()
    assert len(check_index_metadata(index, report, partial=True)) == 1
    with pytest.raises(ValueError, match="file set"):
        check_index_metadata(index, report)
    index["urls"].append(deepcopy(index["urls"][0]))
    with pytest.raises(ValueError, match="file set"):
        check_index_metadata(index, report, partial=True)


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("change", ["digest", "yanked", "extra", "origin", "credentials"])
def test_conflicting_or_unsafe_index_file_is_never_skipped(index, report, partial, change):
    file = index["urls"][0]
    if change == "digest":
        file["digests"]["sha256"] = "b" * 64
    elif change == "yanked":
        file["yanked"] = True
    elif change == "extra":
        file["filename"] = "other.whl"
    elif change == "origin":
        file["url"] = "https://example.invalid/wheel.whl"
    else:
        file["url"] = "https://user:secret@files.pythonhosted.org/wheel.whl"
    with pytest.raises(ValueError):
        check_index_metadata(index, report, partial=partial)


def test_local_artifact_tampering_or_addition_rejected(tmp_path, report):
    (tmp_path / "morphiq_sdk-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    source = tmp_path / "morphiq_sdk-0.1.0.tar.gz"
    source.write_bytes(b"sdist")
    check_local(tmp_path, report)
    source.write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest"):
        check_local(tmp_path, report)
    source.write_bytes(b"sdist")
    (tmp_path / "unexpected.txt").touch()
    with pytest.raises(ValueError, match="Unexpected"):
        check_local(tmp_path, report)


def test_partial_upload_resumes_only_missing_matching_files(tmp_path, report, index, monkeypatch):
    source = tmp_path / "dist"
    source.mkdir()
    wheel, sdist = report["files"]
    (source / wheel).write_bytes(b"wheel")
    (source / sdist).write_bytes(b"sdist")
    index["urls"].pop()
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: io.BytesIO(json.dumps(index).encode())
    )
    destination = tmp_path / "upload"
    assert prepare_upload("testpypi", report, source, destination) == 1
    assert list(destination.iterdir()) == [destination / sdist]
    assert (destination / sdist).read_bytes() == b"sdist"


def test_complete_upload_is_noop_and_conflicts_create_no_upload_dir(
    tmp_path, report, index, monkeypatch
):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: io.BytesIO(json.dumps(index).encode())
    )
    assert prepare_upload("pypi", report, tmp_path, tmp_path / "empty") == 0
    index["urls"][0]["digests"]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="digest"):
        prepare_upload("pypi", report, tmp_path, tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()


def test_index_download_checks_actual_bytes_not_just_advertised_hash(
    tmp_path, report, index, monkeypatch
):
    replies = iter([json.dumps(index).encode(), b"tampered"])
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(next(replies)))
    with pytest.raises(ValueError, match="Downloaded artifact digest"):
        verify_index("testpypi", report, tmp_path / "downloads")
    assert not list((tmp_path / "downloads").iterdir())


def test_index_download_recovers_from_initial_404(tmp_path, report, index, monkeypatch):
    replies = iter([None, json.dumps(index).encode(), b"wheel", b"sdist"])
    pauses = []

    def fetch(*args, **kwargs):
        value = next(replies)
        if value is None:
            raise urllib.error.HTTPError("https://test.pypi.org", 404, "pending", {}, None)
        return io.BytesIO(value)

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    monkeypatch.setattr("time.sleep", pauses.append)
    verify_index("testpypi", report, tmp_path / "downloads")
    check_local(tmp_path / "downloads", report)
    assert pauses == [10]


def test_record_checks_both_distribution_metadata_and_license_files(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="morphiq-sdk"\nversion="0.1.0"\nlicense="MIT"\nlicense-files=["LICENSE"]\n'
    )
    (tmp_path / ".release-please-manifest.json").write_text('{".": "0.1.0"}')
    directory = tmp_path / "dist"
    directory.mkdir()
    wheel = directory / "morphiq_sdk-0.1.0-py3-none-any.whl"
    source = directory / "morphiq_sdk-0.1.0.tar.gz"
    metadata = (
        b"Name: morphiq-sdk\nVersion: 0.1.0\nLicense-Expression: MIT\nLicense-File: LICENSE\n\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("morphiq_sdk-0.1.0.dist-info/METADATA", metadata)
        archive.writestr(
            "morphiq_sdk-0.1.0.dist-info/licenses/LICENSE", "Synthetic license fixture"
        )
    with tarfile.open(source, "w:gz") as archive:
        for name, content in (("PKG-INFO", metadata), ("LICENSE", b"Synthetic license fixture")):
            info = tarfile.TarInfo(f"morphiq_sdk-0.1.0/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    monkeypatch.setattr("scripts.check_publish.git", lambda *args: "a" * 40)
    report = tmp_path / "report.json"
    record_artifacts(tmp_path, directory, "v0.1.0", report)
    check_local(directory, json.loads(report.read_text()))
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("morphiq_sdk-0.1.0.dist-info/METADATA", metadata)
    with pytest.raises(ValueError, match="identity/license"):
        record_artifacts(tmp_path, directory, "v0.1.0", report)


def test_preflight_resolves_existing_release_to_tagged_main_commit(
    tmp_path, project, environments, monkeypatch
):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init")
    git("config", "user.name", "Release fixture")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="morphiq-sdk"\nversion="0.1.0"\nlicense="MIT"\nlicense-files=["LICENSE"]\n'
    )
    (tmp_path / ".release-please-manifest.json").write_text('{".": "0.1.0"}')
    git("add", ".")
    git("commit", "-m", "chore: release v0.1.0")
    git("tag", "v0.1.0")
    commit = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", commit)
    release = {"tag_name": "v0.1.0", "draft": False, "prerelease": False}
    monkeypatch.setattr(
        "scripts.check_publish.github",
        lambda path: {"environments": environments} if "/environments?" in path else release,
    )
    assert preflight(tmp_path, "v0.1.0", "example/repo") == commit
    for key in ("draft", "prerelease"):
        release[key] = True
        with pytest.raises(ValueError, match="published, stable"):
            preflight(tmp_path, "v0.1.0", "example/repo")
        release[key] = False
    git("commit", "--allow-empty", "-m", "unmerged release")
    git("tag", "v0.1.1")
    with pytest.raises(subprocess.CalledProcessError):
        preflight(tmp_path, "v0.1.1", "example/repo")


def test_new_index_release_stages_both_files_but_server_failure_does_not(
    tmp_path, report, monkeypatch
):
    source = tmp_path / "dist"
    source.mkdir()
    for name, content in zip(report["files"], (b"wheel", b"sdist"), strict=True):
        (source / name).write_bytes(content)
    status = 404

    def fetch(*args, **kwargs):
        raise urllib.error.HTTPError("https://test.pypi.org", status, "index error", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    assert prepare_upload("testpypi", report, source, tmp_path / "new") == 2
    check_local(tmp_path / "new", report)
    status = 503
    with pytest.raises(urllib.error.HTTPError):
        prepare_upload("testpypi", report, source, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()


def test_sole_maintainer_can_review_without_removing_approval_gate(environments):
    for env in environments:
        env["protection_rules"][0]["prevent_self_review"] = False
    check_environments(environments)
    environments[0]["protection_rules"][0]["reviewers"] = []
    with pytest.raises(ValueError, match="must have reviewers"):
        check_environments(environments)
