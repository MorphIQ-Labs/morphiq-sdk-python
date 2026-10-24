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
    APIError,
    AsyncMorphIQ,
    DividendEvent,
    Greeks,
    GreeksRequest,
    GreeksResponse,
    GreeksResult,
    MorphIQ,
    RequestTimeout,
    ResponseError,
)

ROOT = Path(__file__).resolve().parents[1]


def invoke(mode, transport, request):
    if mode == "sync":
        with MorphIQ(api_key="greeks-test-key", transport=transport) as client:
            return client.greeks(request)

    async def run():
        async with AsyncMorphIQ(api_key="greeks-test-key", transport=transport) as client:
            return await client.greeks(request)

    return asyncio.run(run())


def test_greeks_contract_and_native_fixture_identity(greeks_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    fixture = json.loads((ROOT / "tests/fixtures/greeks.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    assert schema["paths"]["/v1/greeks"]["post"]["operationId"] == "greeksAllTen"
    for model, name in [
        (GreeksRequest, "GreeksAllTenRequest"),
        (Greeks, "GreeksAllTen"),
        (GreeksResult, "GreeksAllTenResult"),
        (GreeksResponse, "GreeksAllTenResponse"),
    ]:
        assert set(model.model_fields) == set(schema["components"]["schemas"][name]["properties"])
    for case in greeks_cases:
        for name, value in [
            ("GreeksAllTenRequest", GreeksRequest(**case["request"]).to_wire()),
            ("GreeksAllTenResponse", case["response"]),
        ]:
            Draft202012Validator(
                {"$ref": f"#/components/schemas/{name}", "components": schema["components"]}
            ).validate(value)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", [0, 1])
def test_greeks_roundtrip_preserves_every_value_and_evidence(mode, index, greeks_cases):
    case = copy.deepcopy(greeks_cases[index])
    body = case["response"]
    body["metadata"]["fcu_charged"] = 0
    body["result"]["diagnostics"] = {"future_field": [0, 1.23456789012345]}
    body["result"]["pricing_model"] = "future_model"
    body["result"]["greeks"]["future_greek"] = 0.12345678912345
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/v1/greeks"
        assert request.headers["Authorization"] == "Bearer greeks-test-key"
        assert request.headers["Accept"] == "application/json"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=body, headers={"x-request-id": "greeks-header"})

    response = invoke(mode, httpx.MockTransport(handle), GreeksRequest(**case["request"]))
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == body
    assert json.loads(response.raw_body) == body
    assert response.headers["x-request-id"] == "greeks-header"
    assert response.metadata.fcu_charged == 0
    assert response.result.greeks.theta == body["result"]["greeks"]["theta"]
    assert response.result.greeks.vega == body["result"]["greeks"]["vega"]


def test_greeks_request_preserves_schedule_edits_and_null(greeks_cases):
    request = GreeksRequest(**greeks_cases[0]["request"], model_version=None)
    request.dividend_schedule.append(DividendEvent(ex_time_years=0.25, cash_amount=1.5))
    wire = request.to_wire()
    assert wire["model_version"] is None
    assert wire["dividend_schedule"] == [{"ex_time_years": 0.25, "cash_amount": 1.5}]
    request.dividend_schedule[0] = {"ex_time_years": float("nan"), "cash_amount": 1.5}
    with pytest.raises(ValidationError):
        request.to_wire()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["api", "invalid", "timeout"])
def test_greeks_failures_preserve_charges_and_do_not_retry(mode, failure, greeks_cases):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure == "invalid":
            body = copy.deepcopy(greeks_cases[0]["response"])
            del body["result"]["greeks"]["vega"]
            return httpx.Response(200, json=body, headers={"x-request-id": "greeks-error"})
        return httpx.Response(
            500,
            json={
                "error": {"code": "pricing_failed", "message": "greeks-test-key"},
                "metadata": {**greeks_cases[0]["response"]["metadata"], "fcu_charged": 7},
            },
        )

    error_type = {"api": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    with pytest.raises(error_type) as error:
        invoke(mode, httpx.MockTransport(handle), GreeksRequest(**greeks_cases[0]["request"]))
    assert len(calls) == 1
    if failure == "api":
        assert error.value.metadata.fcu_charged == 7
        assert "greeks-test-key" not in str(error.value) + error.value.body.decode()
    elif failure == "invalid":
        assert error.value.request_id == "greeks-error"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "0.1"])
def test_greeks_do_not_replace_invalid_values_with_zero(greeks_cases, bad):
    body = copy.deepcopy(greeks_cases[0]["response"])
    body["result"]["greeks"]["gamma"] = bad
    with pytest.raises(ValidationError):
        GreeksResponse.model_validate(body)


@pytest.mark.parametrize("script", ["greeks", "greeks_async"])
def test_greeks_examples_are_self_contained(fixture_api, greeks_cases, tmp_path, script):
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
    for name, value in greeks_cases[0]["response"]["result"]["greeks"].items():
        assert f"{name}: {value}" in result.stdout
    assert "Commercial CU charged: not reported" in result.stdout
    assert received == [("/v1/greeks", "Bearer example-key", greeks_cases[0]["request"])]
