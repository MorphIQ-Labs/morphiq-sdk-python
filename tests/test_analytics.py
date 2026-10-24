import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import (
    AnalyticsRequest,
    AnalyticsResponse,
    AnalyticsResult,
    APIError,
    AsyncMorphIQ,
    DividendEvent,
    MorphIQ,
    RequestTimeout,
    ResponseError,
)

ROOT = Path(__file__).resolve().parents[1]


def invoke(mode, transport, request):
    if mode == "sync":
        with MorphIQ(api_key="analytics-test-key", transport=transport) as client:
            return client.analytics(request)

    async def run():
        async with AsyncMorphIQ(api_key="analytics-test-key", transport=transport) as client:
            return await client.analytics(request)

    return asyncio.run(run())


def test_analytics_contract_and_native_identity(analytics_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    fixture = json.loads((ROOT / "tests/fixtures/analytics.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    assert schema["paths"]["/v1/analytics"]["post"]["operationId"] == "fusedAnalytics"
    for model, name in [
        (AnalyticsRequest, "FusedAnalyticsRequest"),
        (AnalyticsResult, "FusedAnalyticsResult"),
        (AnalyticsResponse, "FusedAnalyticsResponse"),
    ]:
        assert set(model.model_fields) == set(schema["components"]["schemas"][name]["properties"])
    for case in analytics_cases:
        for name, body in [
            ("FusedAnalyticsRequest", AnalyticsRequest(**case["request"]).to_wire()),
            ("FusedAnalyticsResponse", case["response"]),
        ]:
            Draft202012Validator(
                {"$ref": f"#/components/schemas/{name}", "components": schema["components"]}
            ).validate(body)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(4))
def test_analytics_roundtrip_preserves_nested_results_and_single_charge(
    mode, index, analytics_cases
):
    case = copy.deepcopy(analytics_cases[index])
    body = case["response"]
    body["metadata"].update(fcu_charged=2**53 + 1, fcu_quoted=999, units_charged=444)
    body["result"]["future_diagnostic"] = {"values": [0, 1.23456789012345]}
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/v1/analytics"
        assert request.headers["Authorization"] == "Bearer analytics-test-key"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=body, headers={"x-request-id": "analytics-header"})

    response = invoke(mode, httpx.MockTransport(handle), AnalyticsRequest(**case["request"]))
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == body
    assert json.loads(response.raw_body) == body
    assert response.metadata.fcu_charged == 2**53 + 1
    assert response.headers["x-request-id"] == "analytics-header"
    if "market_price" in case["request"]:
        assert response.result.implied_volatility.implied_volatility == pytest.approx(0.2)
        assert case["request"]["volatility"] == 0.35
    else:
        assert response.result.implied_volatility is None


def test_analytics_preserves_optional_fields_and_validates_schedule_edits(analytics_cases):
    payload = analytics_cases[0]["request"]
    assert "market_price" not in AnalyticsRequest(**payload).to_wire()
    request = AnalyticsRequest(
        **payload, market_price=None, model_version=None, dividend_schedule=[]
    )
    assert request.to_wire()["market_price"] is None
    assert request.to_wire()["model_version"] is None
    assert request.to_wire()["dividend_schedule"] == []
    request.dividend_schedule.append(DividendEvent(ex_time_years=0.25, cash_amount=1.5))
    assert request.to_wire()["dividend_schedule"] == [{"ex_time_years": 0.25, "cash_amount": 1.5}]
    request.dividend_schedule.append({"ex_time_years": float("nan"), "cash_amount": 1.5})
    with pytest.raises(ValidationError):
        request.to_wire()
    with pytest.raises(ValidationError):
        AnalyticsRequest(
            **{k: v for k, v in payload.items() if k != "volatility"}, market_price=10.0
        )
    body = copy.deepcopy(analytics_cases[0]["response"])
    body["result"]["implied_volatility"] = None
    assert AnalyticsResponse.model_validate(body).model_dump(exclude_unset=True) == body


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["api", "invalid", "timeout"])
@pytest.mark.parametrize("charge", [None, 0, 7])
def test_analytics_errors_preserve_billing_evidence_without_retries(
    mode, failure, charge, analytics_cases
):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        body = copy.deepcopy(analytics_cases[1]["response"])
        body["metadata"]["fcu_charged"] = charge
        if failure == "invalid":
            del body["result"]["greeks"]["vega"]
            return httpx.Response(200, json=body)
        return httpx.Response(
            500,
            json={
                "metadata": body["metadata"],
                "error": {"code": "pricing_failed", "message": "analytics-test-key"},
            },
        )

    cls = {"api": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    with pytest.raises(cls) as caught:
        invoke(mode, httpx.MockTransport(handle), AnalyticsRequest(**analytics_cases[1]["request"]))
    assert len(calls) == 1
    if failure != "timeout":
        assert caught.value.metadata.fcu_charged == charge
        assert caught.value.request_id == "fixture-analytics-european-premium"
        assert "analytics-test-key" not in str(caught.value) + caught.value.body.decode()


@pytest.mark.parametrize("script", ["analytics", "analytics_async"])
def test_analytics_examples_are_self_contained(fixture_api, analytics_cases, tmp_path, script):
    endpoint, received = fixture_api
    path = tmp_path / f"{script}.py"
    shutil.copyfile(ROOT / "examples" / path.name, path)
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=tmp_path,
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "example-key"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "example-key" not in result.stdout + result.stderr
    for name, value in analytics_cases[1]["response"]["result"]["greeks"].items():
        assert f"{name}: {value}" in result.stdout
    assert "Commercial CU charged: not reported" in result.stdout
    assert received == [("/v1/analytics", "Bearer example-key", analytics_cases[1]["request"])]


@pytest.mark.parametrize("charge", ["7", -1, True, 1.5])
def test_invalid_billing_metadata_is_not_trusted(analytics_cases, charge):
    body = copy.deepcopy(analytics_cases[1]["response"])
    body["metadata"]["fcu_charged"] = charge
    with pytest.raises(ResponseError) as caught:
        invoke(
            "sync",
            httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            AnalyticsRequest(**analytics_cases[1]["request"]),
        )
    assert caught.value.metadata is None


@pytest.mark.parametrize("script", ["analytics", "analytics_async"])
def test_examples_report_charge_even_if_numerical_result_is_invalid(
    fixture_api, analytics_cases, tmp_path, script
):
    endpoint, received = fixture_api
    body = analytics_cases[1]["response"]
    body["result"].pop("greeks")
    body["metadata"]["fcu_charged"] = 11
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / (script + ".py"))],
        cwd=tmp_path,
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "example-key"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and len(received) == 1
    assert "Commercial CU charged: 11" in result.stderr
    assert "example-key" not in result.stdout + result.stderr
