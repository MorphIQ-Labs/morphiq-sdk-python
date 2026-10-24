"""Acceptance must reject unintended endpoints before installing or submitting anything."""

import sys

import pytest

from scripts.check_release_candidate import check


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.morphiqlabs.com",
        "http://api.morphiqlabs.com",
        "http://127.0.0.1.example.com",
        "file:///tmp/openapi.json",
        "http://user:password@localhost:19871",
        "http://127.0.0.1:19871?key=example",
        "http://127.0.0.1:19871#fragment",
    ],
)
def test_rejects_nonlocal_or_credential_bearing_endpoints_before_side_effects(endpoint, tmp_path):
    report = tmp_path / "evidence.json"
    with pytest.raises(ValueError):
        check(tmp_path / "not-built.whl", tmp_path, sys.executable, endpoint, report)
    assert not report.exists() and not report.with_suffix(".log").exists()


def test_acceptance_requires_wheel_not_source_install(tmp_path):
    with pytest.raises(ValueError, match="built wheel"):
        check(
            tmp_path / "sdk.tar.gz",
            tmp_path,
            sys.executable,
            "http://127.0.0.1:19871",
            tmp_path / "report.json",
        )
