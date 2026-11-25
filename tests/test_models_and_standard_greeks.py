"""Model catalog discovery, standard Greeks and explicit unavailable quantities."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from morphiq_sdk import (
    AsyncMorphIQ,
    Greeks,
    ModelsListResponse,
    MorphIQ,
    OptionsBatchStandardGreeksRequest,
    OptionsBatchStandardGreeksResponse,
    OptionsPriceRequest,
    OptionsStandardGreeksRequest,
    StandardGreeks,
)
from morphiq_sdk.client import _quote_payload
from morphiq_sdk.models import ValidityCondition, ValidityInterval

ROOT = Path(__file__).parents[1]
STANDARD = json.loads((ROOT / "tests/fixtures/standard_greeks.json").read_text())["cases"]
CATALOG = json.loads((ROOT / "tests/fixtures/models.json").read_text())


def invoke(mode, handler, action, key=None):
    transport = httpx.MockTransport(handler)
    if mode == "sync":
        with MorphIQ(api_key=key, transport=transport) as client:
            return action(client)

    async def run():
        async with AsyncMorphIQ(api_key=key, transport=transport) as client:
            return await action(client)

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("key", [None, "private-test-key"])
def test_discovery_is_public_and_never_sends_credentials(mode, key):
    calls = []
    payload = {**CATALOG, "future_catalog_property": {"version": 3}}

    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1/models"
        assert "Authorization" not in request.headers
        assert not request.content
        return httpx.Response(200, json=payload)

    response = invoke(mode, handle, lambda c: c.models.list(), key)
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert json.loads(response.raw_body) == payload
    assert {m.id for m in response.models} >= {"black_scholes_merton", "black_scholes_merton_fd"}


def test_catalog_lists_canonical_operation_ids_and_validity():
    catalog = ModelsListResponse.model_validate(CATALOG)
    for model in catalog.models:
        assert "options.price" in model.operations
        assert all("." in operation for operation in model.operations)
        assert model.validity
    bounds = [
        bound
        for model in catalog.models
        for validity in model.validity
        for bound in validity.region or []
    ]
    assert any(isinstance(bound, ValidityInterval | ValidityCondition) for bound in bounds)
    assert catalog.validity_symbols


def test_catalog_retains_unknown_ids_enums_and_bound_kinds():
    payload = copy.deepcopy(CATALOG)
    model = payload["models"][0]
    model["id"] = "future_model"
    model["exercise_styles"].append("bermudan")
    model["validity"].append(
        {
            "quantity": "speed",
            "status": "experimental",
            "criterion": "future_criterion",
            "region": [{"kind": "polytope", "vertices": [[0, 1]]}],
        }
    )
    parsed = ModelsListResponse.model_validate(payload)
    assert parsed.models[0].id == "future_model"
    assert parsed.models[0].exercise_styles[-1] == "bermudan"
    validity = parsed.models[0].validity[-1]
    assert validity.status == "experimental" and validity.criterion == "future_criterion"
    assert validity.region[0].kind == "polytope"
    assert parsed.model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_protected_call_without_key_fails_before_transport(mode):
    def handle(request):
        pytest.fail("Unauthenticated protected call reached transport")

    with pytest.raises(ValueError, match="MORPHIQ_API_KEY"):
        invoke(mode, handle, lambda c: c.rate_card.get())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("batch", [False, True])
def test_standard_single_batch_preserve_wire_values_and_spend_cap(mode, batch):
    calls = []
    case = STANDARD[1]
    request = OptionsStandardGreeksRequest.model_validate(case["request"])
    payload = copy.deepcopy(case["response"])
    payload["metadata"]["billing"] = {"charged_cu": 2}
    path = "/v1/options:standard-greeks"
    if batch:
        request = OptionsBatchStandardGreeksRequest(items=[request])
        payload = {
            "metadata": payload["metadata"],
            "results": [{"index": 0, "status": "success", "result": payload["result"]}],
        }
        path = "/v1/options:batch-standard-greeks"
    method = "batch_standard_greeks" if batch else "standard_greeks"

    def handle(incoming):
        calls.append(incoming)
        assert incoming.url.path == path
        assert incoming.headers["x-morphiq-max-cu"] == "5"
        assert json.loads(incoming.content) == request.to_wire()
        return httpx.Response(200, json=payload)

    response = invoke(
        mode, handle, lambda c: getattr(c.options, method)(request, max_cu=5), "test-key"
    )
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert response.metadata.charged_cu == 2
    assert _quote_payload(request) == {
        "operation": f"options.{method}",
        "request": request.to_wire(),
    }


def _problem(code):
    return {
        "type": f"https://developers.morphiqlabs.com/docs/errors#{code}",
        "title": "Unavailable",
        "status": 422,
        "detail": "Not available",
        "code": code,
    }


@pytest.mark.parametrize("model", [StandardGreeks, Greeks])
def test_unavailable_quantities_are_distinct_from_real_zero(model):
    values = {name: 0.0 for name in model.model_fields if name != "unavailable"}
    values.pop("rho")
    values["unavailable"] = {"rho": _problem("unsupported_quantity")}
    result = model.model_validate(values)
    assert result.rho is None and result.delta == 0.0
    assert result.unavailable["rho"].code == "unsupported_quantity"
    assert result.unavailable["rho"].detail == "Not available"
    assert result.model_dump(exclude_unset=True) == values
    for invalid in [
        {**values, "rho": None},
        {**values, "rho": 0.0},
        {**values, "unavailable": {}},
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(invalid)


@pytest.mark.parametrize(
    "selector",
    ["auto", "black_scholes_merton", "black_scholes_merton_qdfp", "black_scholes_merton_fd"],
)
def test_selectors_are_forwarded_without_client_model_substitution(selector):
    wire = copy.deepcopy(STANDARD[1]["request"])
    wire["model"] = {"id": selector}
    assert OptionsPriceRequest.model_validate(wire).to_wire()["model"] == {"id": selector}


@pytest.mark.parametrize(
    "selector", ["bjerksund_stensland_2002", "qd_fixed_point", "cash_dividend_american", "bs1993"]
)
def test_removed_aliases_and_unknown_selectors_are_rejected_before_sending(selector):
    wire = copy.deepcopy(STANDARD[1]["request"])
    wire["model"] = {"id": selector}
    with pytest.raises(ValidationError):
        OptionsPriceRequest.model_validate(wire)


def test_standard_batch_ceiling_and_partial_greeks_dataframe():
    from morphiq_sdk.pandas import batch_to_frames

    request = OptionsStandardGreeksRequest.model_validate(STANDARD[0]["request"])
    assert len(OptionsBatchStandardGreeksRequest(items=[request] * 100).items) == 100
    with pytest.raises(ValidationError):
        OptionsBatchStandardGreeksRequest(items=[request] * 101)
    partial = copy.deepcopy(STANDARD[0]["response"]["result"])
    partial["greeks"].pop("rho")
    partial["greeks"]["delta"] = 0.0
    partial["greeks"]["unavailable"] = {"rho": _problem("unavailable")}
    response = OptionsBatchStandardGreeksResponse.model_validate(
        {
            "metadata": STANDARD[0]["response"]["metadata"],
            "results": [
                {"index": 0, "status": "success", "result": partial},
                {"index": 1, "status": "success", "result": STANDARD[0]["response"]["result"]},
            ],
        }
    )
    frames = batch_to_frames(response)
    import pandas as pd

    assert pd.isna(frames.results.loc[0, "result.greeks.rho"])
    assert frames.results.loc[0, "result.greeks.delta"] == 0.0
    assert frames.results.loc[0, "result.greeks.unavailable"]["rho"]["code"] == "unavailable"
    assert "rho" not in frames.results.loc[0, "outcome"]["result"]["greeks"]


@pytest.mark.parametrize(
    "filename,button,result",
    [
        ("pricing/models.ipynb", "load_button", "last_catalog"),
        ("pricing/standard-five.ipynb", "calculate_button", "last_result"),
    ],
)
def test_notebook_setup_and_changes_are_inert_actions_are_explicit(
    filename, button, result, monkeypatch
):
    import morphiq_sdk as sdk

    seen = []

    def handle(request):
        seen.append(request)
        if filename.endswith("models.ipynb"):
            assert request.url.path == "/v1/models"
            assert "Authorization" not in request.headers
            return httpx.Response(200, json=CATALOG)
        assert request.url.path == "/v1/options:standard-greeks"
        body = json.loads(request.content)
        assert body["option"] == STANDARD[0]["request"]["option"]
        assert body["market"] == STANDARD[0]["request"]["market"]
        assert body["model"]["id"] == "black_scholes_merton"
        return httpx.Response(200, json=STANDARD[0]["response"])

    monkeypatch.setenv("MORPHIQ_API_KEY", "notebook-test-key")
    original = sdk.MorphIQ
    monkeypatch.setattr(
        sdk, "MorphIQ", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle))
    )
    scope = {}
    notebook = json.loads((ROOT / "notebooks" / filename).read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert not cell["outputs"] and cell["execution_count"] is None
            exec("".join(cell["source"]), scope)
    assert not seen
    if "spot" in scope:
        scope["spot"].value = 105
        scope["spot"].value = 100
    assert not seen
    scope[button].click()
    assert len(seen) == 1 and scope[result] is not None
    assert not scope[button].disabled
