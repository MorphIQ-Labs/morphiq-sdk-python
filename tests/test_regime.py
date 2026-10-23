import asyncio
import copy
import json
import os
from pathlib import Path

import httpx
import nbformat
import pytest
from jsonschema import Draft202012Validator
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError
from pydantic import ValidationError

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    MorphIQ,
    RegimeRequest,
    RegimeResponse,
    RequestTimeout,
    ResponseError,
    models,
)
from scripts.execute_notebook_fixture import fixture_prices_source
from scripts.generate_notebook import regime_sources

ROOT = Path(__file__).resolve().parents[1]


def test_regime_models_and_fixtures_cover_pinned_contract(regime_cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    for name in (
        "RegimeRequest",
        "RegimeResponse",
        "RegimeResult",
        "RegimeMetadata",
        "RegimeBasis",
        "RegimeScoreContract",
        "RegimeProvenance",
        "RegimeConsumedPriceRange",
    ):
        assert set(getattr(models, name).model_fields) == set(
            schema["components"]["schemas"][name]["properties"]
        )
    for case in regime_cases:
        for name, payload in [
            ("RegimeRequest", case["request"]),
            ("RegimeResponse", case["response"]),
        ]:
            Draft202012Validator(
                {"$ref": f"#/components/schemas/{name}", "components": schema["components"]}
            ).validate(payload)
    assert schema["paths"]["/v1/regime"]["post"]["operationId"] == "identifyRegime"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_regime_roundtrip_preserves_evidence(regime_cases, asynchronous):
    case = copy.deepcopy(regime_cases[0])
    payload = case["response"]
    payload["metadata"]["fcu_charged"] = 0
    payload["result"]["diagnostics"] = {"additive": [1.23456789012345, 2]}
    # Caller array ordering, explicit null and excess prefix must survive serialization.
    request = RegimeRequest(prices=[99.0] + case["request"]["prices"], as_of=None)
    payload["metadata"].update(received_price_count=513, input_price_index=512)
    payload["metadata"]["consumed_price_range"] = {"start_index": 6, "end_index_exclusive": 513}
    seen = []

    def handler(http_request):
        seen.append(http_request)
        assert http_request.url == "https://api.morphiqlabs.com/v1/regime"
        assert http_request.headers["Authorization"] == "Bearer regime-key"
        assert http_request.headers["Accept"] == "application/json"
        assert json.loads(http_request.content) == request.to_wire()
        return httpx.Response(200, json=payload, headers={"x-request-id": "regime-id"})

    transport = httpx.MockTransport(handler)

    async def run():
        async with AsyncMorphIQ(api_key="regime-key", transport=transport) as client:
            return await client.regime(request)

    if asynchronous:
        response = asyncio.run(run())
    else:
        with MorphIQ(api_key="regime-key", transport=transport) as client:
            response = client.regime(request)
    assert len(seen) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert json.loads(response.raw_body) == payload
    assert response.headers["x-request-id"] == "regime-id"
    assert response.metadata.fcu_charged == 0


@pytest.mark.parametrize("head", ["decision", "direction", "state"])
@pytest.mark.parametrize(
    "status,reason",
    [("not_applicable", "predicted_not_eligible"), ("unavailable", "prediction_unavailable")],
)
def test_regime_absent_predictions_remain_distinct(regime_cases, head, status, reason):
    payload = copy.deepcopy(regime_cases[0]["response"])
    original = payload["result"][head]
    original.update(status=status, reason_code=reason, prediction=None)
    response = RegimeResponse.model_validate(payload)
    assert getattr(response.result, head).status == status
    assert getattr(response.result, head).prediction is None
    original["prediction"] = {"label": "unresolved"}
    with pytest.raises(ValidationError):
        RegimeResponse.model_validate(payload)


def test_unresolved_is_an_available_decision(regime_cases):
    payload = copy.deepcopy(regime_cases[0]["response"])
    prediction = payload["result"]["decision"]["prediction"]
    prediction["label"] = "unresolved"
    prediction["scores"][1]["value"], prediction["scores"][3]["value"] = 0.1, 0.6
    response = RegimeResponse.model_validate(payload)
    assert response.result.decision.status == "available"
    assert response.result.decision.prediction.label == "unresolved"


def test_regime_request_preserves_timestamp_and_revalidates_prices(regime_cases):
    prices = regime_cases[0]["request"]["prices"]
    assert "as_of" not in RegimeRequest(prices=prices).to_wire()
    assert RegimeRequest(prices=prices, as_of=None).to_wire()["as_of"] is None
    timestamp = "2026-10-22T16:00:00-04:00"
    assert RegimeRequest(prices=prices, as_of=timestamp).to_wire()["as_of"] == timestamp
    for bad in [0, -1, float("nan"), float("inf"), "100", True]:
        request = RegimeRequest(prices=prices)
        request.prices[0] = bad
        with pytest.raises(ValidationError):
            request.to_wire()
    request = RegimeRequest(prices=prices)
    request.prices.pop()
    with pytest.raises(ValidationError):
        request.to_wire()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["service", "invalid", "timeout"])
def test_regime_failures_never_retry(regime_cases, asynchronous, failure):
    seen = []

    def handler(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if failure == "invalid":
            return httpx.Response(200, json={}, headers={"x-request-id": "bad-response"})
        return httpx.Response(
            503,
            json={
                "error": {"code": "model_unavailable", "message": "synthetic"},
                "metadata": {
                    "request_id": "failure",
                    "api_version": "v1",
                    "service_version": "fixture",
                    "fcu_charged": 0,
                },
            },
        )

    request = RegimeRequest(**regime_cases[0]["request"])
    transport = httpx.MockTransport(handler)

    async def run():
        async with AsyncMorphIQ(api_key="fixture-key", transport=transport) as client:
            await client.regime(request)

    with pytest.raises(
        {"service": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    ) as raised:
        if asynchronous:
            asyncio.run(run())
        else:
            with MorphIQ(api_key="fixture-key", transport=transport) as client:
                client.regime(request)
    assert len(seen) == 1
    if failure == "service":
        assert raised.value.metadata.fcu_charged == 0
        assert raised.value.code == "model_unavailable"


@pytest.mark.parametrize("script", ["identify_regime.py", "identify_regime_async.py"])
def test_regime_api_cells_with_in_memory_prices(fixture_api, regime_cases, tmp_path, script):
    endpoint, received = fixture_api
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(fixture_prices_source(regime_cases[0]["request"]["prices"])),
            nbformat.v4.new_code_cell(regime_sources(script)[1]),
        ]
    )
    executed = NotebookClient(
        notebook, timeout=60, resources={"metadata": {"path": str(tmp_path)}}
    ).execute(
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "fixture-key"}
    )
    output = json.dumps(executed)
    for expected in [
        "Decision: available",
        "Label: supported",
        "Direction: available",
        "State: available",
        "Consumed prices: [5, 512)",
        "fixture-regime",
        "not reported",
    ]:
        assert expected in output
    assert "fixture-key" not in output
    assert received == [("/v1/regime", "Bearer fixture-key", regime_cases[0]["request"])]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("script", ["identify_regime.py", "identify_regime_async.py"])
def test_regime_api_cells_report_failures_without_retry(
    failing_api, regime_cases, tmp_path, script
):
    endpoint, received, expected = failing_api
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(fixture_prices_source(regime_cases[0]["request"]["prices"])),
            nbformat.v4.new_code_cell(regime_sources(script)[1]),
        ]
    )
    with pytest.raises(CellExecutionError):
        NotebookClient(
            notebook, timeout=60, resources={"metadata": {"path": str(tmp_path)}}
        ).execute(
            env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "fixture-key"}
        )
    assert expected in json.dumps(notebook)
    assert "fixture-key" not in json.dumps(notebook)
    assert len(received) == 1
