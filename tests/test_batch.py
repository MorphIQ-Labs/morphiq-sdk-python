import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from support import BATCH_OPERATIONS, charged, problem, set_charge

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchUnrecognized,
    MorphIQ,
    OptionsBatchPriceRequest,
    RateLimitError,
    RequestTimeout,
    ResponseError,
)

# (client.options method, request type, response type) in batch fixture order.
OPERATIONS = [operation[:3] for operation in BATCH_OPERATIONS]
ROOT = Path(__file__).parents[1]


def invoke(mode, transport, method, request):
    if mode == "sync":
        with MorphIQ(api_key="batch-test-key", transport=transport) as client:
            return getattr(client.options, method)(request)

    async def run():
        async with AsyncMorphIQ(api_key="batch-test-key", transport=transport) as client:
            return await getattr(client.options, method)(request)

    return asyncio.run(run())


def test_batch_fixture_identity_and_routes(batch_cases):
    fixture = json.loads((ROOT / "tests/fixtures/batch.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    for case, (method, request, response) in zip(batch_cases, OPERATIONS, strict=False):
        assert case["path"] == "/v1/options:" + method.replace("_", "-")
        assert request.model_validate(case["request"]).to_wire() == case["request"]
        parsed = response.model_validate(case["response"])
        assert parsed.model_dump(exclude_unset=True) == case["response"]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
def test_ordered_mixed_outcomes_and_one_charge(mode, index, batch_cases):
    method, cls, _ = OPERATIONS[index]
    case = copy.deepcopy(batch_cases[index])
    calls = []
    set_charge(case["response"]["metadata"], 2**53 + 1, quoted=999)

    def handle(request):
        calls.append(request)
        assert request.url.path == case["path"] and request.method == "POST"
        assert request.headers["Authorization"] == "Bearer batch-test-key"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=case["response"])

    result = invoke(mode, httpx.MockTransport(handle), method, cls.model_validate(case["request"]))
    assert len(calls) == 1
    assert result.model_dump(exclude_unset=True) == case["response"]
    assert json.loads(result.raw_body) == case["response"]
    assert [x.status for x in result.results] == (
        ["success", "error", "success"] if index < 2 else ["success"] * 3
    )
    assert [x.index for x in result.results] == [0, 1, 2]
    assert result.metadata.charged_cu == 2**53 + 1
    if index < 2:
        error = result.results[1].error
        assert error.code and error.detail and error.type.startswith("https://")
        assert error.status == batch_cases[index]["response"]["results"][1]["error"]["status"]
        assert error.field == ("market.spot" if index == 0 else None)


@pytest.mark.parametrize("index", range(4))
def test_batch_inputs_revalidate_edits_without_plan_assumptions(index, batch_cases):
    _, cls, _ = OPERATIONS[index]
    values = batch_cases[index]["request"]["items"]
    with pytest.raises(ValidationError):
        cls(items=[])
    with pytest.raises(ValidationError):
        cls(items=[values[0]] * 101)
    with pytest.raises(ValidationError):
        cls.model_validate({"requests": values})
    assert len(cls(items=[values[0]] * 100).to_wire()["items"]) == 100
    request = cls.model_validate({"items": values})
    request.items[0].market.dividends.append({"ex_time_years": float("nan"), "cash_amount": 1.0})
    with pytest.raises(ValidationError):
        request.to_wire()
    request.items.clear()
    with pytest.raises(ValidationError):
        request.to_wire()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["missing", "duplicate", "reordered", "extra", "timeout"])
def test_invalid_batch_correlation_preserves_charge_and_never_retries(
    mode, index, failure, batch_cases
):
    method, cls, _ = OPERATIONS[index]
    case = copy.deepcopy(batch_cases[index])
    calls = []
    body = case["response"]
    set_charge(body["metadata"], 7)
    if failure == "missing":
        body["results"].pop()
    if failure == "duplicate":
        body["results"][1]["index"] = 0
    if failure == "reordered":
        body["results"].reverse()
    if failure == "extra":
        body["results"].append(body["results"][0])

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        return httpx.Response(200, json=body)

    with pytest.raises(RequestTimeout if failure == "timeout" else ResponseError) as raised:
        invoke(mode, httpx.MockTransport(handle), method, cls.model_validate(case["request"]))
    assert len(calls) == 1
    if failure != "timeout":
        assert raised.value.metadata.charged_cu == 7


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
def test_unknown_outcome_status_is_retained_not_rejected(mode, index, batch_cases):
    method, cls, _ = OPERATIONS[index]
    case = copy.deepcopy(batch_cases[index])
    body = case["response"]
    body["results"][0] = {"index": 0, "status": "deferred", "ticket": {"id": "t-1"}}
    result = invoke(
        mode,
        httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        method,
        cls.model_validate(case["request"]),
    )
    item = result.results[0]
    assert isinstance(item, BatchUnrecognized)
    assert item.status == "deferred" and item.index == 0
    assert item.model_extra == {"ticket": {"id": "t-1"}}
    assert result.model_dump(exclude_unset=True) == body


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("kind", ["service", "gateway"])
def test_429_preserves_retry_guidance_charges_and_credentials(mode, index, kind, batch_cases):
    method, cls, _ = OPERATIONS[index]
    case = batch_cases[index]
    calls = []

    def handle(request):
        calls.append(request)
        headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT", "x-request-id": "throttled"}
        if kind == "gateway":
            return httpx.Response(429, text="gateway batch-test-key", headers=headers)
        return httpx.Response(
            429,
            json=problem(
                "concurrency_limited",
                "batch-test-key",
                status=429,
                metadata=charged(case["response"]["metadata"], 0),
            ),
            headers=headers,
        )

    with pytest.raises(RateLimitError) as raised:
        invoke(mode, httpx.MockTransport(handle), method, cls.model_validate(case["request"]))
    error = raised.value
    assert isinstance(error, APIError) and len(calls) == 1 and error.status_code == 429
    assert error.retry_delay(now=datetime(2015, 10, 21, 7, 27, tzinfo=UTC)) == 60
    assert error.retry_after == "Wed, 21 Oct 2015 07:28:00 GMT"
    assert "batch-test-key" not in str(error) + error.body.decode() + str(error.headers)
    if kind == "service":
        assert error.metadata.charged_cu == 0
        assert error.code == "concurrency_limited"
    else:
        assert error.metadata is None and error.problem is None
        assert error.request_id == "throttled"


@pytest.mark.parametrize(
    "header,delay",
    [
        ("120", 120),
        ("0", 0),
        (None, None),
        ("garbage", None),
        ("-1", None),
        ("1.5", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0),
    ],
)
def test_retry_after_parsing_is_explicit_and_does_not_invent_a_delay(header, delay):
    error = RateLimitError(
        status_code=429,
        problem=None,
        request_id=None,
        body=b"",
        headers={} if header is None else {"retry-after": header},
    )
    assert error.retry_delay(now=datetime(2026, 1, 1, tzinfo=UTC)) == delay


def test_async_cancellation_is_propagated_without_replay(batch_cases):
    calls = []

    async def handle(request):
        calls.append(request)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        invoke(
            "async",
            httpx.MockTransport(handle),
            "batch_price",
            OptionsBatchPriceRequest.model_validate(batch_cases[0]["request"]),
        )
    assert len(calls) == 1
