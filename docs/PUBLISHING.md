# Package publishing runbook

The **Publish SDK package** workflow (`.github/workflows/publish.yml`) prepares
TestPyPI verification and PyPI promotion. It is disabled unless the repository
variable `PYPI_PUBLISHING_ENABLED` is exactly `true`. Merging the workflow does
not enable uploads. Release Please continues to own versions, tags and GitHub
releases; this workflow never creates or moves them.

## First activation

Complete these steps before setting the enablement variable:

1. Create separate personal maintainer accounts on
   [PyPI](https://pypi.org/account/register/) and
   [TestPyPI](https://test.pypi.org/account/register/), verify their email addresses,
   enable 2FA and store recovery codes in the maintainer's password manager.
   Register the pending publishers below while signed in to the intended owner
   accounts. They create the project on first upload; they do not reserve its name.
   Organization management and a second owner can be added when available.
2. The SDK, examples and notebooks use the [MIT license](../LICENSE), selected by
   MorphIQ Labs. Metadata declares `MIT` and includes `LICENSE` in both artifacts.
   Public repository visibility has been selected for preparation; review the
   release tree/history before the separate visibility change. The copyright
   holder is MorphIQ Labs.
3. Make the installation guide, API reference, compatibility/contract information,
   examples and support route accessible to public users. Choose public repository
   URLs or hosted documentation and replace README-relative links with working
   public URLs for the package description. The current source distributions do
   not include `docs/` or `contracts/`; a private repository link is insufficient.
   Verify the rendered description and project URLs on TestPyPI before promotion.
4. Create GitHub environments named **`testpypi`** and **`pypi`** before running
   the workflow. Require review from `thestephenromano`, allow self-review for the current sole
   maintainer, disallow administrator bypass, and select only branch `main` and tags `v*` as
   deployment refs. Keep `main` and release tags protected against unreviewed
   changes. Preflight checks that both environments exist with reviewers and selected-ref
   policies. Self-review is intentional: otherwise the sole maintainer cannot
   approve manually initiated runs. When another maintainer joins, add that reviewer
   and enable self-review prevention. Inspect the exact ref rules and administrator
   bypass setting in GitHub's UI as part of activation.
5. Configure a GitHub trusted publisher separately on each index:

   | Setting | TestPyPI | PyPI |
   | --- | --- | --- |
   | Project | `morphiq-sdk` | `morphiq-sdk` |
   | Owner | `MorphIQ-Labs` | `MorphIQ-Labs` |
   | Repository | `morphiq-sdk-python` | `morphiq-sdk-python` |
   | Workflow filename | `publish.yml` | `publish.yml` |
   | Environment | `testpypi` | `pypi` |

   Add pending publishers at [PyPI publishing](https://pypi.org/manage/account/publishing/)
   and [TestPyPI publishing](https://test.pypi.org/manage/account/publishing/).
   The GitHub owner field is `MorphIQ-Labs`, not the PyPI account username. Do not add a PyPI
   password or API token to repository secrets. The publishing jobs use OIDC and
   create attestations; build and install jobs have no OIDC permission. Follow the
   [PyPI trusted publisher instructions](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
6. Record candidate acceptance in the [release readiness checklist](RELEASE_READINESS.md).
   Set `PYPI_PUBLISHING_ENABLED=true` only when the preceding decisions and setup
   are complete. Review the generated Release Please PR and its CI before merging.

GitHub's required-reviewer availability depends on repository visibility and plan.
If the selected repository/plan cannot enforce the required environments, leave
publishing disabled until that is resolved; naming an environment alone does not
protect it. See [GitHub environment protections](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

## Setup recorded on 2026-10-25

- GitHub owner: `MorphIQ-Labs`; sole release maintainer: `thestephenromano`.
- License decision: MIT; repository prepared for public visibility, still private.
- Both environments exist with exactly branch `main` and tag `v*` allowed.
- `PYPI_PUBLISHING_ENABLED=false` is set explicitly. No uploads have occurred.
- Required reviewers and administrator bypass controls still need configuration
  after the repository becomes public; the current GitHub Team plan cannot
  enforce required reviewers on this private repository.
- PyPI/TestPyPI accounts, 2FA and pending publisher registrations remain to be
  completed by the maintainer. Package ownership is not yet established.
- Gitleaks 8.30.1 reviewed all reachable local Git history through publishing
  preparation commit `f10bb6f`. Its four detections were duplicate references to
  the pinned API source commit in the historical release audit, not credentials.
  No credential findings remained after inspecting those matches. This is a
  scoped scan result, not a guarantee about all possible sensitive information.
  A separate scan of the 35 issue/PR bodies accessible on that date found no
  credentials; there were no issue or review comments returned by the API.

## Release sequence

A published GitHub release starts the workflow. To publish an existing release,
run **Publish SDK package** from **main**, entering its existing `vX.Y.Z` tag.
The tag must resolve to a commit on `origin/main`; its project version and Release
Please manifest must match, and a non-draft, non-prerelease GitHub release must exist.
The tagged commit must contain this publishing tooling and the approved metadata.
Do not create a new tag just to retry a failed upload.

1. Preflight validates release identity, publication metadata and environments.
2. The tagged source passes lint, formatting, typing, notebook generation and the
   test suite. Controlled-service integration tests still require a separate
   candidate-acceptance run; publishing CI does not have production API credentials.
3. Build one sdist and then its wheel. Record the tag, commit and SHA-256 hashes in
   `release-artifacts.json`. Retain the files and manifest as the GitHub Actions
   artifact **release-artifacts** for 90 days.
4. On Python 3.11 and 3.14, install that wheel in a clean virtual environment.
   Verify core imports without pandas/Yahoo, typing markers, all client operations
   and an empty workflow. Install all extras and check dependency consistency and
   exact batch charges using synthetic fixtures. No market-data or numerical API
   requests occur.
5. A reviewer approves **testpypi**. Upload the files using trusted publishing.
6. Download both files from TestPyPI, compare their advertised and actual SHA-256
   hashes to the build manifest, and repeat clean wheel installs on both Python
   versions. Dependencies resolve exclusively against PyPI, never TestPyPI. There
   is no mixed-index `--extra-index-url` installation.
7. Inspect TestPyPI metadata, attestations, rendered documentation links and the
   successful install checks. Approve **pypi** to upload the **same built bytes**.
8. Download and verify both production files and repeat the clean install matrix.
   Record the successful workflow URL and manifest alongside release acceptance.

The checks verify package installation and offline SDK behavior. They do not
replace native-service contract tests, notebook UI acceptance, account signup or
fresh-customer public documentation checks. The sdist is exercised by building
its wheel; the downloaded sdist must match those exact bytes.

## Public installation and compatibility

After a successful production release, the public installation path is:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install morphiq-sdk
```

Choose optional extras only when needed:

```bash
python -m pip install 'morphiq-sdk[pandas]'
python -m pip install 'morphiq-sdk[market-data]'
python -m pip install 'morphiq-sdk[notebooks]'
```

`morphiq-sdk` is the distribution name; `morphiq_sdk` is the core import and
`morphiq_sdk_yahoo` is the optional provider import. Python 3.11 or newer is
required; publication checks cover 3.11 and 3.14. The core requires neither Yahoo,
pandas nor a numerical engine. API access is separate: obtain a key through
[the developer portal](https://developers.morphiqlabs.com), set `MORPHIQ_API_KEY`,
and use the SDK's default `https://api.morphiqlabs.com` endpoint.

The SDK, API contract and engines have independent versions. The reviewed API
contract's identity and SHA-256 digest are recorded in
[contract guide](CONTRACT.md); the [API reference](API.md)
and feature guides describe the supported operations and wire semantics. A package
version is not a promise of compatibility with every future API or engine release.

Before 1.0, patch releases preserve the supported public interface; breaking
changes require a minor release and migration notes. Prefer a documented warning
and replacement path before removing an interface. Announce removals and changes
to supported Python/dependency ranges in the generated release notes, with migration
instructions in the same reviewed change. No fixed deprecation period or LTS window
is promised. Consumers requiring stability should constrain the minor series
(for example, `morphiq-sdk>=0.1,<0.2`) and test upgrades against their use cases.

For SDK defects, use the [repository issue tracker](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues)
once the public visibility change is complete.
Account/key/billing requests go through the developer portal. Reports should include
SDK/Python versions, operation, request ID and a minimal synthetic reproduction.
Never post keys, private market inputs or account data in public issues.

## Recovery and yanking

- **Build/check failure before upload:** fix through review. If the tagged code
  needs correction, Release Please must generate a new version. For an external
  transient failure, rerun the failed jobs against the existing release.
- **Index propagation:** verification retries an index 404 up to six reads with
  ten-second intervals. Other errors and digest mismatches fail immediately.
  These are package-index reads, not SDK API request retries.
- **Interrupted/partial upload:** use **Re-run failed jobs** to reuse the retained
  build artifact. Each publishing job checks existing index files first. Files
  with matching names and hashes are left in place; only missing files are staged.
  Extra files, yanked files or differing hashes stop the job. The upload action
  does not use `skip-existing` and never overwrites a file.
- **Verification failure after production upload:** the package may already be
  available; inspect the index and manifest before taking action. Do not interpret
  a failed workflow as proof that no upload happened.
- **Artifact expired or a full rerun rebuilds different bytes:** stop on any hash
  conflict. Recover the original recorded artifacts if available, or release a
  corrected version through Release Please. Never delete/re-upload the same
  filename or move a release tag to bypass an immutable-file conflict.
- **Defective public release:** disable the enablement variable to stop new runs,
  cancel any active publication run, record the affected version and reason, and
  have a project owner yank it in PyPI. Publish the reviewed correction as a new
  version. Do not remove historical artifacts merely to hide a defect. Exact
  version pins may still install a yanked release; notify affected consumers and
  update the release notes with the replacement. See [PyPI yanking guidance](https://docs.pypi.org/project-management/yanking/).
- **Publisher/account incident:** disable publishing, cancel active runs, remove
  the affected trusted publisher on the index and follow the organization's
  account recovery process. OIDC does not eliminate the need to secure GitHub,
  environment reviewers and PyPI owners.

Neither this workflow nor Release Please publishes notebook container images;
image publication has a separate release path.
