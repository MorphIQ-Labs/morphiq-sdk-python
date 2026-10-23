# Releases

The SDK has its own version stream, independent of the API, service and engines.
Installations and Docker builds read the version from `pyproject.toml`; no version
environment variable is required. Before the first release, `0.1.0.dev0` identifies
an unreleased checkout. It is not a tag or a published package.

## Automated release process

1. Merge reviewed feature PRs using conventional commit titles.
2. The **SDK releases** workflow runs on `main`. Release Please opens or updates
   a `chore: release vX.Y.Z` PR containing the generated `pyproject.toml` version,
   `CHANGELOG.md` and `.release-please-manifest.json`.
3. Review that PR and its normal Python, package, version and Docker checks, then
   squash-merge it. The workflow creates the matching `vX.Y.Z` tag and GitHub
   release at that release PR's merge commit.

The empty initial manifest means there has been no release. The Python release
strategy proposes **v0.1.0** first. Subsequently, below 1.0, `fix` and `feat` changes
increment the patch version; breaking changes (`!` or `BREAKING CHANGE`) increment
the minor version. This follows the organization's pre-1.0 release convention.
Minor versions may break compatibility; patch releases should preserve it. The
API contract and engine versions continue to be reported separately.

Release Please owns version, manifest and changelog changes. Do not hand-bump
release versions, edit released changelog sections, create release tags manually,
or move/delete existing tags. Organization rules protect `v*` tags. CI checks
that every fetched release tag matches the package and manifest at its commit,
and that release PR titles match the proposed package version. Package checks
build a wheel from the sdist and verify its installed version against the source.

The action is pinned to a commit and uses the existing organization secret
`RELEASE_PLZ_TOKEN`, shared with the other MorphIQ release workflows. Its token
must retain repository contents, pull request and label access. Using this token
allows generated PRs and tags to trigger CI; the default `GITHUB_TOKEN` would
suppress those runs. No release token is passed to PR builds.

## Recovery and distribution

If a workflow fails, inspect its log, fix the cause through review, and rerun
**SDK releases** on `main` using **Run workflow**. Release Please reconciles merged
release PRs and existing releases; reruns do not deliberately bump a version or
replace a tag. Keep its `autorelease: pending` / `autorelease: tagged` labels intact.
If an already released version needs correction, merge a fix and release a new
version. Never overwrite an existing release's identity.

GitHub tagging does not publish to PyPI or a container registry. The repository
remains private with `Private :: Do Not Upload` and no selected open-source
license. [Issue #9](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/9)
tracks distribution-name ownership, licensing/public visibility, TestPyPI and
trusted publishing, public support and package recovery/yanking policy.
[Issue #14](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/14) tracks
versioned notebook image publication. No package upload or deployment follows
from running these builds or creating a GitHub release.
