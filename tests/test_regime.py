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
from support import charged, problem

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    MorphIQ,
    RequestTimeout,
    ResponseError,
    SeriesIdentifyRegimeRequest,
    SeriesIdentifyRegimeResponse,
    Unrecognized,
    models,
)
from scripts.execute_notebook_fixture import fixture_prices_source
from scripts.generate_notebook import regime_sources

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())


def _validate(name, payload):
    Draft202012Validator({"$ref": f"#/components/schemas/{name}", **SCHEMA}).validate(payload)


def test_regime_route_and_fixture_cover_pinned_contract(regime_cases):
    operation = SCHEMA["paths"]["/v1/series:identify-regime"]["post"]
    assert operation["operationId"] == "seriesIdentifyRegime"
    for case in regime_cases:
        assert case["path"] == "/v1/series:identify-regime"
        _validate("SeriesIdentifyRegimeRequest", case["request"])
        _validate("SeriesIdentifyRegimeResponse", case["response"])
    # Regime facts live in the result; the metadata is the shared ResponseMetadata.
    assert set(models.RegimeResult.model_fields) >= {
        "input",
        "timing",
        "provenance",
        "response_contract_version",
    }
    assert models.SeriesIdentifyRegimeResponse.model_fields["metadata"].annotation is (
        models.ResponseMetadata
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_regime_roundtrip_preserves_evidence(regime_cases, asynchronous):
    case = copy.deepcopy(regime_cases[0])
    payload = case["response"]
    payload["metadata"]["billing"] = {"quoted_cu": 100, "charged_cu": 100}
    payload["result"]["diagnostics"] = {"additive": [1.23456789012345, 2]}
    # Caller array ordering, the timestamp and excess prefix must survive serialization.
    request = SeriesIdentifyRegimeRequest(
        prices=[99.0] + case["request"]["prices"], as_of="2026-10-22T16:00:00-04:00"
    )
    payload["result"]["input"].update(
        received_price_count=513, input_price_index=512, as_of="2026-10-22T16:00:00-04:00"
    )
    payload["result"]["input"]["consumed_price_range"] = {
        "start_index": 6,
        "end_index_exclusive": 513,
    }
    seen = []

    def handler(http_request):
        seen.append(http_request)
        assert http_request.url == "https://api.morphiqlabs.com/v1/series:identify-regime"
        assert http_request.headers["Authorization"] == "Bearer regime-key"
        assert http_request.headers["Accept"] == "application/json"
        assert json.loads(http_request.content) == request.to_wire()
        return httpx.Response(200, json=payload, headers={"x-request-id": "regime-id"})

    transport = httpx.MockTransport(handler)

    async def run():
        async with AsyncMorphIQ(api_key="regime-key", transport=transport) as client:
            return await client.series.identify_regime(request)

    if asynchronous:
        response = asyncio.run(run())
    else:
        with MorphIQ(api_key="regime-key", transport=transport) as client:
            response = client.series.identify_regime(request)
    assert len(seen) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert json.loads(response.raw_body) == payload
    assert response.headers["x-request-id"] == "regime-id"
    assert response.metadata.charged_cu == 100
    assert response.result.input.consumed_price_range.start_index == 6
    assert response.result.input.as_of == "2026-10-22T16:00:00-04:00"
    assert response.result.timing.inference_us == payload["result"]["timing"]["inference_us"]


@pytest.mark.parametrize("head", ["decision", "direction", "state"])
@pytest.mark.parametrize(
    "status,reason",
    [("not_applicable", "predicted_not_eligible"), ("unavailable", "prediction_unavailable")],
)
def test_regime_absent_predictions_are_omitted(regime_cases, head, status, reason):
    payload = copy.deepcopy(regime_cases[0]["response"])
    original = payload["result"][head]
    original.pop("prediction")
    original.update(status=status, reason_code=reason)
    _validate("SeriesIdentifyRegimeResponse", payload)
    response = SeriesIdentifyRegimeResponse.model_validate(payload)
    parsed = getattr(response.result, head)
    assert parsed.status == status and parsed.reason_code == reason
    assert "prediction" not in parsed.model_dump()
    assert response.model_dump(exclude_unset=True) == payload
    # An available head must carry its prediction.
    del original["reason_code"]
    original["status"] = "available"
    with pytest.raises(ValidationError):
        SeriesIdentifyRegimeResponse.model_validate(payload)


def test_regime_labels_are_lower_snake_case(regime_cases):
    result = SeriesIdentifyRegimeResponse.model_validate(regime_cases[0]["response"]).result
    assert result.direction.prediction.label == "up"
    assert [s.label for s in result.direction.prediction.scores] == ["up", "down", "neutral"]
    assert result.state.prediction.label == "higher_vol"
    assert [s.label for s in result.state.prediction.scores] == ["lower_vol", "higher_vol"]


def test_unresolved_is_an_available_decision(regime_cases):
    payload = copy.deepcopy(regime_cases[0]["response"])
    prediction = payload["result"]["decision"]["prediction"]
    prediction["label"] = "unresolved"
    prediction["scores"][1]["value"], prediction["scores"][3]["value"] = 0.1, 0.6
    response = SeriesIdentifyRegimeResponse.model_validate(payload)
    assert response.result.decision.status == "available"
    assert response.result.decision.prediction.label == "unresolved"


def test_unknown_head_status_and_labels_are_retained(regime_cases):
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"]["state"] = {"status": "deferred", "basis": {"target": "future_target"}}
    payload["result"]["direction"]["prediction"]["label"] = "sideways"
    payload["result"]["direction"]["prediction"]["scores"].append(
        {"label": "sideways", "value": 0.0}
    )
    payload["result"]["decision"]["basis"]["target"] = "future_target"
    response = SeriesIdentifyRegimeResponse.model_validate(payload)
    assert isinstance(response.result.state, Unrecognized)
    assert response.result.state.status == "deferred"
    assert response.result.direction.prediction.label == "sideways"
    assert response.result.decision.basis.target == "future_target"
    assert response.model_dump(exclude_unset=True) == payload


def test_regime_request_omits_absent_timestamp_and_revalidates_prices(regime_cases):
    prices = regime_cases[0]["request"]["prices"]
    assert "as_of" not in SeriesIdentifyRegimeRequest(prices=prices).to_wire()
    assert "as_of" not in SeriesIdentifyRegimeRequest(prices=prices, as_of=None).to_wire()
    timestamp = "2026-10-22T16:00:00-04:00"
    wire = SeriesIdentifyRegimeRequest(prices=prices, as_of=timestamp).to_wire()
    assert wire["as_of"] == timestamp
    with pytest.raises(ValidationError):
        SeriesIdentifyRegimeRequest(prices=prices, as_of="x" * 65)
    for bad in [0, -1, float("nan"), float("inf"), "100", True]:
        request = SeriesIdentifyRegimeRequest(prices=prices)
        request.prices[0] = bad
        with pytest.raises(ValidationError):
            request.to_wire()
    request = SeriesIdentifyRegimeRequest(prices=prices)
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
        metadata = charged(regime_cases[0]["response"]["metadata"], 0)
        metadata.pop("engines")  # Regime errors carry no engine identity.
        return httpx.Response(
            503, json=problem("model_unavailable", "synthetic", status=503, metadata=metadata)
        )

    request = SeriesIdentifyRegimeRequest.model_validate(regime_cases[0]["request"])
    transport = httpx.MockTransport(handler)

    async def run():
        async with AsyncMorphIQ(api_key="fixture-key", transport=transport) as client:
            await client.series.identify_regime(request)

    with pytest.raises(
        {"service": APIError, "invalid": ResponseError, "timeout": RequestTimeout}[failure]
    ) as raised:
        if asynchronous:
            asyncio.run(run())
        else:
            with MorphIQ(api_key="fixture-key", transport=transport) as client:
                client.series.identify_regime(request)
    assert len(seen) == 1
    if failure == "service":
        assert raised.value.metadata.charged_cu == 0
        assert raised.value.metadata.engines is None
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
    assert received == [
        ("/v1/series:identify-regime", "Bearer fixture-key", regime_cases[0]["request"])
    ]
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
