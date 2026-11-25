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
from pydantic import ValidationError
from support import charged, problem

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    DividendEvent,
    MorphIQ,
    OptionsImpliedVolatilityRequest,
    OptionsImpliedVolatilityResponse,
    RequestTimeout,
    ResponseError,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "implied_volatility-test-key"


def invoke(mode, transport, request):
    if mode == "sync":
        with MorphIQ(api_key=KEY, transport=transport) as client:
            return client.options.implied_volatility(request)

    async def run():
        async with AsyncMorphIQ(api_key=KEY, transport=transport) as client:
            return await client.options.implied_volatility(request)

    return asyncio.run(run())


def test_implied_volatility_route_and_native_fixture_identity(iv_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    fixture = json.loads((ROOT / "tests/fixtures/implied_volatility.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    operation = schema["paths"]["/v1/options:implied-volatility"]["post"]
    assert operation["operationId"] == "optionsImpliedVolatility"
    assert {case["path"] for case in iv_cases} == {"/v1/options:implied-volatility"}


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", [0, 1])
def test_implied_volatility_roundtrip_preserves_every_value_and_evidence(mode, index, iv_cases):
    case = copy.deepcopy(iv_cases[index])
    body = case["response"]
    body["metadata"]["billing"] = {"charged_cu": 0}
    body["result"]["diagnostics"] = {"future_field": [0, 1.23456789012345]}
    body["result"]["model"]["id"] = "future_model"
    body["result"]["residual_basis"] = "future_basis"
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/v1/options:implied-volatility"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        assert request.headers["Accept"] == "application/json"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=body, headers={"x-request-id": "implied_volatility-header"})

    response = invoke(
        mode,
        httpx.MockTransport(handle),
        OptionsImpliedVolatilityRequest.model_validate(case["request"]),
    )
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == body
    assert json.loads(response.raw_body) == body
    assert response.headers["x-request-id"] == "implied_volatility-header"
    assert response.metadata.charged_cu == 0
    assert response.result.residual == body["result"]["residual"]
    # Unknown residual bases and model ids are retained, not rejected.
    assert response.result.residual_basis == "future_basis"
    assert response.result.model.id == "future_model"


def test_implied_volatility_request_validates_dividend_edits(iv_cases):
    request = OptionsImpliedVolatilityRequest.model_validate(iv_cases[0]["request"])
    request.market.dividends.append(DividendEvent(ex_time_years=0.25, cash_amount=1.5))
    wire = request.to_wire()
    assert wire["market"]["dividends"] == [{"ex_time_years": 0.25, "cash_amount": 1.5}]
    request.market.dividends[0] = {"ex_time_years": float("nan"), "cash_amount": 1.5}
    with pytest.raises(ValidationError):
        request.to_wire()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["api", "invalid", "timeout"])
def test_implied_volatility_failures_preserve_charges_and_do_not_retry(mode, failure, iv_cases):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure == "invalid":
            body = copy.deepcopy(iv_cases[0]["response"])
            del body["result"]["residual_basis"]
            return httpx.Response(
                200, json=body, headers={"x-request-id": "implied_volatility-error"}
            )
        return httpx.Response(
            500,
            json=problem(
                "pricing_failed",
                KEY,
                status=500,
                metadata=charged(iv_cases[0]["response"]["metadata"], 7),
            ),
        )

    error_type = {"api": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    with pytest.raises(error_type) as error:
        invoke(
            mode,
            httpx.MockTransport(handle),
            OptionsImpliedVolatilityRequest.model_validate(iv_cases[0]["request"]),
        )
    assert len(calls) == 1
    if failure == "api":
        assert error.value.metadata.charged_cu == 7
        assert KEY not in str(error.value) + error.value.body.decode()
    elif failure == "invalid":
        assert error.value.request_id == "implied_volatility-error"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "0.1"])
def test_implied_volatility_do_not_replace_invalid_values_with_zero(iv_cases, bad):
    body = copy.deepcopy(iv_cases[0]["response"])
    body["result"]["implied_volatility"] = bad
    with pytest.raises(ValidationError):
        OptionsImpliedVolatilityResponse.model_validate(body)


@pytest.mark.parametrize("script", ["implied_volatility", "implied_volatility_async"])
def test_implied_volatility_examples_are_self_contained(fixture_api, iv_cases, tmp_path, script):
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
    result_values = iv_cases[0]["response"]["result"]
    for label, name in [
        ("Implied volatility", "implied_volatility"),
        ("Residual", "residual"),
        ("Residual basis", "residual_basis"),
        ("Iterations", "iterations"),
        ("Used fallback", "used_fallback"),
    ]:
        assert f"{label}: {result_values[name]}" in result.stdout
    assert "Commercial CU charged: not reported" in result.stdout
    assert received == [
        ("/v1/options:implied-volatility", "Bearer example-key", iv_cases[0]["request"])
    ]


def test_iv_rejects_volatility_input_and_omits_absent_members(iv_cases):
    payload = copy.deepcopy(iv_cases[0]["request"])
    with pytest.raises(ValidationError):
        OptionsImpliedVolatilityRequest.model_validate({**payload, "volatility": 0.2})
    with pytest.raises(ValidationError):
        OptionsImpliedVolatilityRequest.model_validate(
            {k: v for k, v in payload.items() if k != "market_price"}
        )
    wire = OptionsImpliedVolatilityRequest.model_validate(payload).to_wire()
    assert "volatility" not in wire
    assert "dividends" not in wire["market"]
    assert "version" not in wire["model"]


@pytest.mark.parametrize(
    "field,bad",
    [
        ("iterations", -1),
        ("iterations", 1.5),
        ("iterations", True),
        ("used_fallback", "false"),
        ("residual", float("nan")),
        ("residual_basis", None),
        ("model", None),
    ],
)
def test_iv_rejects_invalid_diagnostics(iv_cases, field, bad):
    body = copy.deepcopy(iv_cases[0]["response"])
    body["result"][field] = bad
    with pytest.raises(ValidationError):
        OptionsImpliedVolatilityResponse.model_validate(body)
