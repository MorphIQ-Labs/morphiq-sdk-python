import asyncio
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

import morphiq_sdk as sdk

ROOT = Path(__file__).resolve().parents[1]
METADATA = {
    "request_id": "cost-fixture",
    "api_version": "v1",
    "service_version": "0.4.1",
    "fcu_charged": 0,
}
QUOTE = {
    "quote": {
        "total_fcu": 1,
        "fixed_fcu": 0,
        "variable_fcu": 1,
        "minimum_charge_fcu": 0,
        "lines": [
            {
                "operation": "price",
                "model": "black_scholes_merton/1",
                "billing_unit": "contract",
                "quantity": 1,
                "fcu_per_unit": 1,
                "variable_fcu": 1,
            }
        ],
    },
    "resolved_models": [{"model": "black_scholes_merton/1", "quantity": 1}],
    "metadata": METADATA,
}
SCHEDULE = {
    "schedule": {
        "schedule_id": "test",
        "schedule_version": "1",
        "record_version": 1,
        "policy_revision": "a" * 64,
        "effective_from": "2026-10-19T00:00:00Z",
        "effective_until": None,
        "fixed_request_fcu": 0,
        "minimum_charge_fcu": 0,
        "rounding": "none",
        "failure_charging": "commit_at_execution_start",
        "rates": [
            {
                "operation": "price",
                "model": "black_scholes_merton/1",
                "billing_unit": "contract",
                "fcu_per_unit": 1,
                "max_discrete_dividends": 0,
            }
        ],
    },
    "metadata": METADATA,
}


def cases():
    for file, model, operation in [
        ("pricing", sdk.PriceRequest, "price"),
        ("regime", sdk.RegimeRequest, "regime"),
        ("greeks", sdk.GreeksRequest, "greeks"),
        ("implied_volatility", sdk.ImpliedVolatilityRequest, "implied_volatility"),
        ("analytics", sdk.AnalyticsRequest, "analytics"),
    ]:
        case = json.loads((ROOT / f"tests/fixtures/{file}.json").read_text())["cases"][0]
        yield model.model_validate(case["request"]), operation, case
    batches = json.loads((ROOT / "tests/fixtures/batch.json").read_text())["cases"]
    for index, (model, operation) in enumerate(
        [
            (sdk.BatchPriceRequest, "price_batch"),
            (sdk.BatchGreeksRequest, "greeks_batch"),
            (sdk.BatchImpliedVolatilityRequest, "implied_volatility_batch"),
            (sdk.BatchAnalyticsRequest, "analytics_batch"),
        ]
    ):
        yield model.model_validate(batches[index]["request"]), operation, batches[index]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("input_request,operation,case", list(cases()))
def test_quote_uses_the_execution_body_and_ceiling_is_per_call(
    mode, input_request, operation, case
):
    seen = []

    def handler(http_request):
        assert http_request.headers["Authorization"] == "Bearer synthetic-test-key"
        seen.append(http_request)
        if http_request.url.path == "/v1/cost/quote":
            assert json.loads(http_request.content) == {
                "operation": operation,
                "request": input_request.to_wire(),
            }
            assert "x-morphiq-max-cu" not in http_request.headers
            return httpx.Response(200, json=QUOTE)
        assert http_request.url.path == case.get("path", "/v1/price")
        assert json.loads(http_request.content) == input_request.to_wire()
        assert http_request.headers["x-morphiq-max-cu"] == "1"
        return httpx.Response(200, json=case["response"])

    settings = {"api_key": "synthetic-test-key", "transport": httpx.MockTransport(handler)}
    if mode == "sync":
        with sdk.MorphIQ(**settings) as client:
            quote = client.quote(input_request)
            getattr(client, operation)(input_request, max_cu=quote.quote.total_fcu)
    else:

        async def run():
            async with sdk.AsyncMorphIQ(**settings) as client:
                quote = await client.quote(input_request)
                await getattr(client, operation)(input_request, max_cu=quote.quote.total_fcu)

        asyncio.run(run())
    assert len(seen) == 2


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_schedule_filter_encoding_and_evidence(mode):
    def handler(request):
        assert request.method == "GET" and not request.content
        assert dict(request.url.params) == {"operation": "price", "model": "black_scholes_merton/1"}
        return httpx.Response(200, json=SCHEDULE, headers={"x-request-id": "cost-fixture"})

    settings = {"api_key": "synthetic-test-key", "transport": httpx.MockTransport(handler)}
    if mode == "sync":
        with sdk.MorphIQ(**settings) as client:
            result = client.cost_schedule(operation="price", model="black_scholes_merton/1")
    else:

        async def run():
            async with sdk.AsyncMorphIQ(**settings) as client:
                return await client.cost_schedule(operation="price", model="black_scholes_merton/1")

        result = asyncio.run(run())
    assert result.metadata.fcu_charged == 0
    assert result.schedule.rates[0].fcu_per_unit == 1
    assert json.loads(result.raw_body) == SCHEDULE
    assert result.headers["x-request-id"] == "cost-fixture"


@pytest.mark.parametrize("maximum", [-1, True, 1.5, "1", 2**64])
def test_invalid_ceiling_sends_nothing(maximum):
    def handler(_):
        pytest.fail("invalid ceiling reached transport")

    with sdk.MorphIQ(
        api_key="synthetic-test-key", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="max_cu"):
            client.price(next(cases())[0], max_cu=maximum)


def test_quote_timeout_is_non_billable_and_not_retried():
    seen = []

    def handler(request):
        seen.append(request)
        raise httpx.ReadTimeout("fixture")

    with sdk.MorphIQ(
        api_key="synthetic-test-key", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(sdk.RequestTimeout, match="no calculation or CU charge"):
            client.quote(next(cases())[0])
    assert len(seen) == 1


def test_cost_wire_contract():
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    for name, value in [("CostScheduleResponse", SCHEDULE), ("CostQuoteResponse", QUOTE)]:
        Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": schema["components"]}
        ).validate(value)
    validator = Draft202012Validator(
        {"$ref": "#/components/schemas/CostQuoteRequest", "components": schema["components"]}
    )
    for request, operation, _ in cases():
        validator.validate({"operation": operation, "request": request.to_wire()})


def test_cost_notebook_actions_are_explicit_and_ceiling_is_forwarded(monkeypatch):
    """Execute setup and real button callbacks against a local mock transport."""
    notebook = json.loads((ROOT / "notebooks/cost/quotation.ipynb").read_text())
    recorded = []
    price_case = next(cases())[2]

    def handler(request):
        recorded.append(request)
        if request.url.path == "/v1/cost/schedule":
            return httpx.Response(200, json=SCHEDULE)
        if request.url.path == "/v1/cost/quote":
            return httpx.Response(200, json=QUOTE)
        assert request.headers["x-morphiq-max-cu"] == "1"
        return httpx.Response(200, json=price_case["response"])

    original = sdk.MorphIQ
    monkeypatch.setenv("MORPHIQ_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        sdk, "MorphIQ", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    scope = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            source = cell["source"]
            exec("".join(source) if isinstance(source, list) else source, scope)
    assert not recorded
    scope["spot"].value = 105.0
    assert not recorded and scope["execute_button"].disabled
    scope["spot"].value = 100.0
    scope["schedule_button"].click()
    scope["quote_button"].click()
    assert len(recorded) == 2 and scope["last_quote"] is not None
    scope["execute_button"].click()
    assert len(recorded) == 3 and scope["last_result"] is not None
    scope["strike"].value = 101.0
    scope["execute_request"](None)
    assert len(recorded) == 3 and scope["execute_button"].disabled


@pytest.mark.parametrize(
    "arguments,quantity,execute,ceiling",
    [
        ([], 1, False, None),
        (["--batch"], 2, False, None),
        (["--execute"], 1, True, 1),
        (["--batch", "--execute"], 2, True, 2),
        (["--batch", "--execute", "--max-cu", "1"], 2, True, 1),
    ],
)
def test_cost_example_requests_and_refusal_evidence(
    monkeypatch, capsys, arguments, quantity, execute, ceiling
):
    import copy
    import runpy
    import sys

    recorded = []
    price_case = next(cases())[2]
    quoted = copy.deepcopy(QUOTE)
    quoted["quote"].update(total_fcu=quantity, variable_fcu=quantity)
    quoted["quote"]["lines"][0].update(quantity=quantity, variable_fcu=quantity)
    quoted["resolved_models"][0]["quantity"] = quantity

    def handler(request):
        recorded.append(request)
        if request.url.path == "/v1/cost/schedule":
            return httpx.Response(200, json=SCHEDULE)
        body = json.loads(request.content)
        if request.url.path == "/v1/cost/quote":
            assert body["operation"] == ("price_batch" if quantity == 2 else "price")
            return httpx.Response(200, json=quoted)
        assert request.headers["x-morphiq-max-cu"] == str(ceiling)
        assert body == json.loads(recorded[1].content)["request"]
        if quantity == 2:
            assert request.url.path == "/v1/price:batch" and len(body["requests"]) == 2
        else:
            assert request.url.path == "/v1/price"
        if ceiling < quantity:
            return httpx.Response(
                409,
                json={
                    "metadata": {**METADATA, "fcu_quoted": quantity},
                    "error": {"code": "cost_limit_exceeded", "message": "ceiling exceeded"},
                },
            )
        response = price_case["response"]
        if quantity == 2:
            response = {
                "metadata": response["metadata"],
                "results": [
                    {"index": index, "status": "success", "result": response["result"]}
                    for index in range(quantity)
                ],
            }
        return httpx.Response(200, json=response)

    original = sdk.MorphIQ
    monkeypatch.setenv("MORPHIQ_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(sdk, "MorphIQ", lambda: original(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sys, "argv", ["cost_quote.py", *arguments])
    if execute and ceiling < quantity:
        with pytest.raises(SystemExit) as failure:
            runpy.run_path(str(ROOT / "examples/cost_quote.py"), run_name="__main__")
        assert failure.value.code == 1
    else:
        runpy.run_path(str(ROOT / "examples/cost_quote.py"), run_name="__main__")
    assert len(recorded) == (3 if execute else 2)
    output = capsys.readouterr()
    assert "synthetic-test-key" not in output.out + output.err
    assert f"Prospective execution CU: {quantity}" in output.out
    assert "Utility CU charged: 0" in output.out
    if execute and ceiling < quantity:
        assert "409: cost_limit_exceeded" in output.err
        assert "Execution quote CU: 2" in output.err and "CU charged: 0" in output.err
        assert "No retry or automatic ceiling increase." in output.err
