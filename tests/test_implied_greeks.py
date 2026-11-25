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
    OptionsImpliedGreeksRequest,
    OptionsImpliedGreeksResponse,
    RequestTimeout,
    ResponseError,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "implied-greeks-test-key"


def invoke(mode, transport, request):
    if mode == "sync":
        with MorphIQ(api_key=KEY, transport=transport) as client:
            return client.options.implied_greeks(request)

    async def run():
        async with AsyncMorphIQ(api_key=KEY, transport=transport) as client:
            return await client.options.implied_greeks(request)

    return asyncio.run(run())


def test_implied_greeks_route_and_native_identity(implied_greeks_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    fixture = json.loads((ROOT / "tests/fixtures/implied_greeks.json").read_text())
    pin = json.loads((ROOT / "contracts/provenance.json").read_text())["recorded_pricing_fixtures"]
    assert fixture["source_commit"] == pin["source_commit"]
    assert fixture["contract_sha256"] == pin["sha256"]
    operation = schema["paths"]["/v1/options:implied-greeks"]["post"]
    assert operation["operationId"] == "optionsImpliedGreeks"
    assert {case["path"] for case in implied_greeks_cases} == {"/v1/options:implied-greeks"}


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", range(2))
def test_implied_greeks_roundtrip_preserves_nested_results_and_single_charge(
    mode, index, implied_greeks_cases
):
    case = copy.deepcopy(implied_greeks_cases[index])
    body = case["response"]
    body["metadata"]["billing"] = {"quoted_cu": 999, "charged_cu": 2**53 + 1}
    body["result"]["future_diagnostic"] = {"values": [0, 1.23456789012345]}
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST" and request.url.path == "/v1/options:implied-greeks"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        assert json.loads(request.content) == case["request"]
        return httpx.Response(200, json=body, headers={"x-request-id": "implied-greeks-header"})

    response = invoke(
        mode,
        httpx.MockTransport(handle),
        OptionsImpliedGreeksRequest.model_validate(case["request"]),
    )
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == body
    assert json.loads(response.raw_body) == body
    assert response.metadata.charged_cu == 2**53 + 1
    assert response.headers["x-request-id"] == "implied-greeks-header"
    assert response.result.implied_volatility.implied_volatility == pytest.approx(0.2)
    assert response.result.model == response.result.implied_volatility.model


def test_implied_greeks_requires_a_premium_and_validates_dividend_edits(implied_greeks_cases):
    payload = copy.deepcopy(implied_greeks_cases[0]["request"])
    assert "volatility" not in payload
    with pytest.raises(ValidationError):
        OptionsImpliedGreeksRequest.model_validate(
            {k: v for k, v in payload.items() if k != "market_price"}
        )
    # A supplied volatility belongs to options.greeks, not the implied-Greeks request.
    with pytest.raises(ValidationError):
        OptionsImpliedGreeksRequest.model_validate({**payload, "volatility": 0.35})
    request = OptionsImpliedGreeksRequest.model_validate(payload)
    request.market.dividends.append(DividendEvent(ex_time_years=0.25, cash_amount=1.5))
    assert request.to_wire()["market"]["dividends"] == [{"ex_time_years": 0.25, "cash_amount": 1.5}]
    request.market.dividends.append({"ex_time_years": float("nan"), "cash_amount": 1.5})
    with pytest.raises(ValidationError):
        request.to_wire()
    # An omitted nested solve stays omitted; it is never reported as null.
    body = copy.deepcopy(implied_greeks_cases[0]["response"])
    del body["result"]["implied_volatility"]
    parsed = OptionsImpliedGreeksResponse.model_validate(body)
    assert parsed.result.implied_volatility is None
    assert parsed.model_dump(exclude_unset=True) == body


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["api", "invalid", "timeout"])
@pytest.mark.parametrize("charge", [None, 0, 7])
def test_implied_greeks_errors_preserve_billing_evidence_without_retries(
    mode, failure, charge, implied_greeks_cases
):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        body = copy.deepcopy(implied_greeks_cases[1]["response"])
        body["metadata"] = charged(body["metadata"], charge)
        if failure == "invalid":
            del body["result"]["greeks"]["vega"]
            return httpx.Response(200, json=body)
        return httpx.Response(
            500, json=problem("pricing_failed", KEY, status=500, metadata=body["metadata"])
        )

    cls = {"api": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    with pytest.raises(cls) as caught:
        invoke(
            mode,
            httpx.MockTransport(handle),
            OptionsImpliedGreeksRequest.model_validate(implied_greeks_cases[1]["request"]),
        )
    assert len(calls) == 1
    if failure != "timeout":
        assert caught.value.metadata.charged_cu == charge
        assert (
            caught.value.request_id == implied_greeks_cases[1]["response"]["metadata"]["request_id"]
        )
        assert KEY not in str(caught.value) + caught.value.body.decode()


@pytest.mark.parametrize("script", ["implied_greeks", "implied_greeks_async"])
def test_implied_greeks_examples_are_self_contained(
    fixture_api, implied_greeks_cases, tmp_path, script
):
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
    case = next(c for c in implied_greeks_cases if c["request"] == received[0][2])
    for name, value in case["response"]["result"]["greeks"].items():
        assert f"{name}: {value}" in result.stdout
    assert "Commercial CU charged: not reported" in result.stdout
    assert [(path, auth) for path, auth, _ in received] == [
        ("/v1/options:implied-greeks", "Bearer example-key")
    ]


@pytest.mark.parametrize("charge", ["7", -1, True, 1.5])
def test_invalid_billing_metadata_is_not_trusted(implied_greeks_cases, charge):
    body = copy.deepcopy(implied_greeks_cases[1]["response"])
    body["metadata"]["billing"] = {"charged_cu": charge}
    with pytest.raises(ResponseError) as caught:
        invoke(
            "sync",
            httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            OptionsImpliedGreeksRequest.model_validate(implied_greeks_cases[1]["request"]),
        )
    assert caught.value.metadata is None


@pytest.mark.parametrize("script", ["implied_greeks", "implied_greeks_async"])
def test_examples_report_charge_even_if_numerical_result_is_invalid(
    fixture_api, implied_greeks_cases, tmp_path, script
):
    endpoint, received = fixture_api
    for case in implied_greeks_cases:
        case["response"]["result"].pop("greeks")
        case["response"]["metadata"]["billing"] = {"charged_cu": 11}
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
