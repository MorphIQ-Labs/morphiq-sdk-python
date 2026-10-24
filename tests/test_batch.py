import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchAnalyticsRequest,
    BatchAnalyticsResponse,
    BatchGreeksRequest,
    BatchGreeksResponse,
    BatchImpliedVolatilityRequest,
    BatchImpliedVolatilityResponse,
    BatchPriceRequest,
    BatchPriceResponse,
    MorphIQ,
    RateLimitError,
    RequestTimeout,
    ResponseError,
)

OPERATIONS = [
    ("price_batch", BatchPriceRequest, BatchPriceResponse, "BatchPrice"),
    ("greeks_batch", BatchGreeksRequest, BatchGreeksResponse, "BatchGreeksAllTen"),
    (
        "implied_volatility_batch",
        BatchImpliedVolatilityRequest,
        BatchImpliedVolatilityResponse,
        "BatchImpliedVolatility",
    ),
    ("analytics_batch", BatchAnalyticsRequest, BatchAnalyticsResponse, "BatchFusedAnalytics"),
]
ROOT = Path(__file__).parents[1]


def invoke(mode, transport, method, request):
    if mode == "sync":
        with MorphIQ(api_key="batch-test-key", transport=transport) as client:
            return getattr(client, method)(request)

    async def run():
        async with AsyncMorphIQ(api_key="batch-test-key", transport=transport) as client:
            return await getattr(client, method)(request)

    return asyncio.run(run())


def test_batch_contract_identity_and_native_fixtures(batch_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    fixture = json.loads((ROOT / "tests/fixtures/batch.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    for case, (_, request, response, wire) in zip(batch_cases, OPERATIONS, strict=False):
        for name, value in [
            (wire + "Request", request(**case["request"]).to_wire()),
            (
                wire + "Response",
                response.model_validate(case["response"]).model_dump(exclude_unset=True),
            ),
        ]:
            Draft202012Validator(
                {"$ref": "#/components/schemas/" + name, "components": schema["components"]}
            ).validate(value)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
def test_ordered_mixed_outcomes_and_one_charge(mode, index, batch_cases):
    method, cls, _, _ = OPERATIONS[index]
    case = copy.deepcopy(batch_cases[index])
    calls = []
    case["response"]["metadata"].update(fcu_charged=2**53 + 1, fcu_quoted=999)

    def handle(request):
        calls.append(request)
        assert request.url.path == case["path"] and request.method == "POST"
        assert request.headers["Authorization"] == "Bearer batch-test-key"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=case["response"])

    result = invoke(mode, httpx.MockTransport(handle), method, cls(**case["request"]))
    assert len(calls) == 1
    assert result.model_dump(exclude_unset=True) == case["response"]
    assert json.loads(result.raw_body) == case["response"]
    assert [x.status for x in result.results] == ["success", "error", "success"]
    assert [x.index for x in result.results] == [0, 1, 2]
    assert result.metadata.fcu_charged == 2**53 + 1


@pytest.mark.parametrize("index", range(4))
def test_batch_inputs_revalidate_edits_without_plan_assumptions(index, batch_cases):
    _, cls, _, _ = OPERATIONS[index]
    values = batch_cases[index]["request"]["requests"]
    with pytest.raises(ValidationError):
        cls(requests=[])
    with pytest.raises(ValidationError):
        cls(requests=[values[0]] * 1025)
    assert len(cls(requests=[values[0]] * 1024).to_wire()["requests"]) == 1024
    request = cls(requests=values)
    request.requests[0].dividend_schedule.append(
        {"ex_time_years": float("nan"), "cash_amount": 1.0}
    )
    with pytest.raises(ValidationError):
        request.to_wire()
    request.requests.clear()
    with pytest.raises(ValidationError):
        request.to_wire()
    request = cls(requests=[{**values[0], "model_version": None, "dividend_schedule": []}])
    assert request.to_wire()["requests"][0]["model_version"] is None
    assert request.to_wire()["requests"][0]["dividend_schedule"] == []


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "reordered", "extra", "unknown_status", "timeout"]
)
def test_invalid_batch_correlation_preserves_charge_and_never_retries(
    mode, index, failure, batch_cases
):
    method, cls, _, _ = OPERATIONS[index]
    case = copy.deepcopy(batch_cases[index])
    calls = []
    body = case["response"]
    body["metadata"]["fcu_charged"] = 7
    if failure == "missing":
        body["results"].pop()
    if failure == "duplicate":
        body["results"][1]["index"] = 0
    if failure == "reordered":
        body["results"].reverse()
    if failure == "extra":
        body["results"].append(body["results"][0])
    if failure == "unknown_status":
        body["results"][0]["status"] = "pending"

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        return httpx.Response(200, json=body)

    with pytest.raises(RequestTimeout if failure == "timeout" else ResponseError) as raised:
        invoke(mode, httpx.MockTransport(handle), method, cls(**case["request"]))
    assert len(calls) == 1
    if failure != "timeout":
        assert raised.value.metadata.fcu_charged == 7


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("kind", ["service", "gateway"])
def test_429_preserves_retry_guidance_charges_and_credentials(mode, index, kind, batch_cases):
    method, cls, _, _ = OPERATIONS[index]
    case = batch_cases[index]
    calls = []

    def handle(request):
        calls.append(request)
        headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT", "x-request-id": "throttled"}
        if kind == "gateway":
            return httpx.Response(429, text="gateway batch-test-key", headers=headers)
        return httpx.Response(
            429,
            json={
                "metadata": {**case["response"]["metadata"], "fcu_charged": 0},
                "error": {"code": "concurrency_limited", "message": "batch-test-key"},
            },
            headers=headers,
        )

    with pytest.raises(RateLimitError) as raised:
        invoke(mode, httpx.MockTransport(handle), method, cls(**case["request"]))
    error = raised.value
    assert isinstance(error, APIError) and len(calls) == 1 and error.status_code == 429
    assert error.retry_delay(now=datetime(2015, 10, 21, 7, 27, tzinfo=UTC)) == 60
    assert error.retry_after == "Wed, 21 Oct 2015 07:28:00 GMT"
    assert "batch-test-key" not in str(error) + error.body.decode() + str(error.headers)
    if kind == "service":
        assert error.metadata.fcu_charged == 0
    else:
        assert error.metadata is None and error.request_id == "throttled"


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
        envelope=None,
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
            "price_batch",
            BatchPriceRequest(**batch_cases[0]["request"]),
        )
    assert len(calls) == 1
