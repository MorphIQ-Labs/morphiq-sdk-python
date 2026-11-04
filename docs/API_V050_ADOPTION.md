# API v0.5.0 SDK adoption

The SDK consumes the deployed API contract at source
`2284d802b5ac0b37b43ee269bbf4bfeec3777776`, SHA-256
`e206327e13aee32c02dbfa22e1d8e8a80ea2d549083971a1cc87aa2b67f401e7`.
The beta wire version remains `0.1.0`; API and SDK releases have separate versions.
See [model capabilities](MODELS.md) and [contract provenance](CONTRACT.md).

## Compatibility changes

- Sync and async clients expose all 14 numerical/discovery/cost operations,
  including public model discovery and standard-five single/batch Greeks.
- All 11 execution methods accept `max_cu`; both standard-five request types
  participate in conditional cost quotation. Rates remain server-owned.
- Batch envelopes and workflow chunks enforce the wire ceiling of 100. BSM and
  BS1993 support all five batch operations; the server rejects other models.
- Greek fields may be unavailable. Their Python value is `None`, accompanied by
  typed reason codes/messages; real zero remains zero. Use
  `model_dump(exclude_unset=True)` to preserve wire presence.
- Construction without a key permits public discovery. Protected calls still
  reject a missing key before transport unless open-development access is explicit.
- Auto American selects QdFp. American Greeks/analytics/batch examples select
  BS1993 explicitly. The server retains authority over capability admission.
- Disabled operations return 400; the retired BS2002 selector returns 422
  `invalid_field`. The SDK preserves those errors without retries or substitutions.

## Verification

On 2026-11-04, Ruff lint/format and mypy passed. The isolated sdist-to-wheel check
verified core dependency isolation and all five pandas batch conversions.
Eighteen native integration tests passed against an optimized, locked build of
the exact API source above, including sync/async parity, 100-item standard-five
batches, explicit chunk workflows, QdFp/finite-difference price and IV, capability
refusals and BS2002 retirement. The debug build exceeded the deadline on
finite-difference IV; optimized validation completed within the service deadline.
This is client contract validation, not a new engine performance benchmark.

Native pricing, Greek, IV, analytics and batch fixtures use synthetic inputs from
that service. An invalid IV premium is now rejected before batch execution, so
mixed-outcome transport tests explicitly inject a synthetic item failure rather
than mislabeling it as a native result. Regime prediction fixtures remain clearly
identified synthetic wire fixtures. No production keys or private data are used.

Reproduce local checks with the repository's pinned development requirements:

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/generate_notebook.py --check
python -m pytest -q
python scripts/check_package.py
docker build -t morphiq-sdk-notebook:test .
python scripts/check_notebook_container.py --image morphiq-sdk-notebook:test
```

For native checks, run the pinned API with open admission on an isolated loopback
address, using `cargo build --release --locked -p morphiq-api-service --bin
morphiq-api-service`, then set `MORPHIQ_TEST_API_URL` for `tests/test_integration.py`.
The test verifies the served schema digest. Before publishing, use
`scripts/check_release_candidate.py` on the built release-PR wheel in a clean
interpreter; [RELEASE.md](../RELEASE.md) owns publication and versioning.
