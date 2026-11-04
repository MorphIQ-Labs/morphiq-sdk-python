"""Wire parity for discovery, standard five and explicit unavailable Greeks."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import (
    AsyncMorphIQ,
    BatchGreeksStandardRequest,
    BatchGreeksStandardResponse,
    Greeks,
    GreeksStandard,
    GreeksStandardRequest,
    GreeksStandardResponse,
    ModelConstraint,
    MorphIQ,
    PriceRequest,
    PricingModelCatalog,
    PricingModelDescriptor,
)
from morphiq_sdk.client import _quote_payload

ROOT = Path(__file__).parents[1]
STANDARD = json.loads((ROOT / "tests/fixtures/greeks_standard.json").read_text())["cases"]
CATALOG = json.loads((ROOT / "tests/fixtures/pricing_models.json").read_text())


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
        assert request.method == "GET" and request.url.path == "/v1/pricing/models"
        assert "Authorization" not in request.headers
        assert not request.content
        return httpx.Response(200, json=payload)

    response = invoke(mode, handle, lambda c: c.pricing_models(), key)
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert json.loads(response.raw_body) == payload
    assert {m.id for m in response.models} >= {"black_scholes_merton", "black_scholes_merton_fd"}


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_protected_call_without_key_fails_before_transport(mode):
    def handle(request):
        pytest.fail("Unauthenticated protected call reached transport")

    with pytest.raises(ValueError, match="MORPHIQ_API_KEY"):
        invoke(mode, handle, lambda c: c.cost_schedule())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("batch", [False, True])
def test_standard_single_batch_preserve_wire_values_and_spend_cap(mode, batch):
    calls = []
    case = STANDARD[1]
    request = GreeksStandardRequest(**case["request"])
    payload = copy.deepcopy(case["response"])
    payload["metadata"]["fcu_charged"] = 2
    if batch:
        request = BatchGreeksStandardRequest(requests=[request])
        payload = {
            "metadata": payload["metadata"],
            "results": [{"index": 0, "status": "success", "result": payload["result"]}],
        }
    method = "greeks_standard_batch" if batch else "greeks_standard"

    def handle(incoming):
        calls.append(incoming)
        assert incoming.url.path == case["path"] + (":batch" if batch else "")
        assert incoming.headers["x-morphiq-max-cu"] == "5"
        assert json.loads(incoming.content) == request.to_wire()
        return httpx.Response(200, json=payload)

    response = invoke(mode, handle, lambda c: getattr(c, method)(request, max_cu=5), "test-key")
    assert len(calls) == 1
    assert response.model_dump(exclude_unset=True) == payload
    assert response.metadata.fcu_charged == 2
    assert _quote_payload(request) == {"operation": method, "request": request.to_wire()}


def test_new_wire_models_and_fixture_schema():
    schemas = json.loads((ROOT / "contracts/openapi.json").read_text())["components"]["schemas"]
    for model, name in [
        (GreeksStandard, "GreeksStandard"),
        (Greeks, "GreeksAllTen"),
        (GreeksStandardRequest, "GreeksStandardRequest"),
        (GreeksStandardResponse, "GreeksStandardResponse"),
        (BatchGreeksStandardRequest, "BatchGreeksStandardRequest"),
        (BatchGreeksStandardResponse, "BatchGreeksStandardResponse"),
        (PricingModelCatalog, "PricingModelCatalog"),
        (PricingModelDescriptor, "PricingModelDescriptor"),
        (ModelConstraint, "ModelConstraint"),
    ]:
        assert set(model.model_fields) == set(schemas[name]["properties"])
    for name, payload in [("PricingModelCatalog", CATALOG)] + [
        ("GreeksStandardResponse", c["response"]) for c in STANDARD
    ]:
        Draft202012Validator(
            {"$ref": "#/components/schemas/" + name, "components": {"schemas": schemas}}
        ).validate(payload)


@pytest.mark.parametrize("model", [GreeksStandard, Greeks])
def test_unavailable_quantities_are_distinct_from_real_zero(model):
    values = {name: 0.0 for name in model.model_fields if name != "unavailable"}
    values.pop("rho")
    values["unavailable"] = {"rho": {"code": "unsupported_quantity", "message": "Not available"}}
    result = model.model_validate(values)
    assert result.rho is None and result.delta == 0.0
    assert result.unavailable["rho"].code == "unsupported_quantity"
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
    [
        "black_scholes_merton_qdfp",
        "qd_fixed_point",
        "black_scholes_merton_fd",
        "cash_dividend_american",
        "bjerksund_stensland_2002",
    ],
)
def test_selectors_are_forwarded_without_client_model_substitution(selector):
    request = PriceRequest(**{**STANDARD[1]["request"], "pricing_model": selector})
    assert request.to_wire()["pricing_model"] == selector


def test_standard_batch_ceiling_and_partial_greeks_dataframe():
    from morphiq_sdk.pandas import batch_to_frames

    request = GreeksStandardRequest(**STANDARD[0]["request"])
    assert len(BatchGreeksStandardRequest(requests=[request] * 100).requests) == 100
    with pytest.raises(ValidationError):
        BatchGreeksStandardRequest(requests=[request] * 101)
    partial = copy.deepcopy(STANDARD[0]["response"]["result"])
    partial["greeks"].pop("rho")
    partial["greeks"]["delta"] = 0.0
    partial["greeks"]["unavailable"] = {"rho": {"code": "unavailable", "message": "No result"}}
    response = BatchGreeksStandardResponse.model_validate(
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
def test_new_notebook_setup_and_changes_are_inert_actions_are_explicit(
    filename, button, result, monkeypatch
):
    import morphiq_sdk as sdk

    seen = []

    def handle(request):
        seen.append(request)
        if filename.endswith("models.ipynb"):
            assert request.url.path == "/v1/pricing/models"
            assert "Authorization" not in request.headers
            return httpx.Response(200, json=CATALOG)
        assert request.url.path == "/v1/greeks/standard"
        expected = {**STANDARD[0]["request"], "pricing_model": "black_scholes_merton"}
        assert json.loads(request.content) == expected
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
