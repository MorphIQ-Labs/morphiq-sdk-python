"""Rate card and quotes: synthetic responses, since open admission has no signed policy."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from support import problem

import morphiq_sdk as sdk

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())
RATE_CARD_ID = {"id": "fcu-qdfp-v1", "version": "2026-11-12-regime-rate"}
# Shaped like the service's rate-card responses; utility reads report a zero charge.
METADATA = {
    "request_id": "cost-fixture",
    "service_version": "0.10.0",
    "contract": {"version": "0.1.0", "sha256": "a" * 64},
    "billing": {"charged_cu": 0, "rate_card": RATE_CARD_ID},
}
QUOTE = {
    "metadata": METADATA,
    "quote": {
        "total_cu": 1,
        "fixed_cu": 0,
        "variable_cu": 1,
        "minimum_charge_cu": 0,
        "lines": [
            {
                "rate_class": "price",
                "model": "black_scholes_merton/1",
                "billing_unit": "contract",
                "quantity": 1,
                "cu_per_unit": 1,
                "variable_cu": 1,
            }
        ],
    },
    "resolved_models": [{"model": "black_scholes_merton/1", "quantity": 1}],
}
SCHEDULE = {
    "metadata": METADATA,
    "schedule": {
        "schedule_id": "fcu-qdfp-v1",
        "schedule_version": "2026-11-12-regime-rate",
        "record_version": 7,
        "policy_revision": "a" * 64,
        "effective_from": "2026-11-12T00:00:00Z",
        "fixed_request_cu": 0,
        "minimum_charge_cu": 0,
        "rounding": "none",
        "failure_charging": "commit_at_execution_start",
        "rates": [
            {
                "rate_class": "price",
                "model": "black_scholes_merton/1",
                "billing_unit": "contract",
                "cu_per_unit": 1,
                "max_discrete_dividends": 0,
            }
        ],
    },
}


def _fixture(name):
    return json.loads((ROOT / f"tests/fixtures/{name}.json").read_text())["cases"]


def cases():
    """(request, canonical operation id, client.options/series method, recorded case)."""
    for file, model, operation in [
        ("pricing", sdk.OptionsPriceRequest, "options.price"),
        ("greeks", sdk.OptionsGreeksRequest, "options.greeks"),
        ("standard_greeks", sdk.OptionsStandardGreeksRequest, "options.standard_greeks"),
        ("implied_volatility", sdk.OptionsImpliedVolatilityRequest, "options.implied_volatility"),
        ("implied_greeks", sdk.OptionsImpliedGreeksRequest, "options.implied_greeks"),
        ("regime", sdk.SeriesIdentifyRegimeRequest, "series.identify_regime"),
    ]:
        case = _fixture(file)[0]
        yield model.model_validate(case["request"]), operation, case
    batches = _fixture("batch")
    for index, (model, operation) in enumerate(
        [
            (sdk.OptionsBatchPriceRequest, "options.batch_price"),
            (sdk.OptionsBatchGreeksRequest, "options.batch_greeks"),
            (sdk.OptionsBatchImpliedVolatilityRequest, "options.batch_implied_volatility"),
            (sdk.OptionsBatchImpliedGreeksRequest, "options.batch_implied_greeks"),
        ]
    ):
        yield model.model_validate(batches[index]["request"]), operation, batches[index]

    case = _fixture("standard_greeks")[0]
    request = sdk.OptionsBatchStandardGreeksRequest(
        items=[sdk.OptionsStandardGreeksRequest.model_validate(case["request"])]
    )
    yield (
        request,
        "options.batch_standard_greeks",
        {
            "path": "/v1/options:batch-standard-greeks",
            "request": request.to_wire(),
            "response": {
                "metadata": case["response"]["metadata"],
                "results": [
                    {"index": 0, "status": "success", "result": case["response"]["result"]}
                ],
            },
        },
    )


def _execute(client, operation, request, max_cu):
    collection, method = operation.split(".")
    return getattr(getattr(client, collection), method)(request, max_cu=max_cu)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("input_request,operation,case", list(cases()))
def test_quote_uses_the_execution_body_and_ceiling_is_per_call(
    mode, input_request, operation, case
):
    seen = []

    def handler(http_request):
        assert http_request.headers["Authorization"] == "Bearer synthetic-test-key"
        seen.append(http_request)
        if http_request.url.path == "/v1/rate-card:quote":
            assert json.loads(http_request.content) == {
                "operation": operation,
                "request": input_request.to_wire(),
            }
            assert "x-morphiq-max-cu" not in http_request.headers
            return httpx.Response(200, json=QUOTE)
        assert http_request.url.path == case["path"]
        assert json.loads(http_request.content) == input_request.to_wire()
        assert http_request.headers["x-morphiq-max-cu"] == "1"
        return httpx.Response(200, json=case["response"])

    assert sdk.operation_id(input_request) == operation
    settings = {"api_key": "synthetic-test-key", "transport": httpx.MockTransport(handler)}
    if mode == "sync":
        with sdk.MorphIQ(**settings) as client:
            quote = client.rate_card.quote(input_request)
            _execute(client, operation, input_request, quote.quote.total_cu)
    else:

        async def run():
            async with sdk.AsyncMorphIQ(**settings) as client:
                quote = await client.rate_card.quote(input_request)
                await _execute(client, operation, input_request, quote.quote.total_cu)

        asyncio.run(run())
    assert len(seen) == 2


def test_quote_rejects_unsupported_inputs_before_transport():
    def handler(_):
        pytest.fail("unsupported quote input reached transport")

    with sdk.MorphIQ(api_key="synthetic-test-key", transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(TypeError):
            c.rate_card.quote({"operation": "options.price"})
        with pytest.raises(TypeError):
            sdk.operation_id(sdk.Market(spot=1.0, risk_free_rate=0.0, dividend_yield=0.0))


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "filters,params",
    [
        ({}, {}),
        ({"rate_class": "price"}, {"rate_class": "price"}),
        (
            {"rate_class": "price", "model": "black_scholes_merton/1"},
            {"rate_class": "price", "model": "black_scholes_merton/1"},
        ),
    ],
)
def test_rate_card_filter_encoding_and_evidence(mode, filters, params):
    def handler(request):
        assert request.method == "GET" and not request.content
        assert request.url.path == "/v1/rate-card"
        assert dict(request.url.params) == params
        return httpx.Response(200, json=SCHEDULE, headers={"x-request-id": "cost-fixture"})

    settings = {"api_key": "synthetic-test-key", "transport": httpx.MockTransport(handler)}
    if mode == "sync":
        with sdk.MorphIQ(**settings) as client:
            result = client.rate_card.get(**filters)
    else:

        async def run():
            async with sdk.AsyncMorphIQ(**settings) as client:
                return await client.rate_card.get(**filters)

        result = asyncio.run(run())
    assert result.metadata.charged_cu == 0
    assert result.metadata.billing.rate_card.id == result.schedule.schedule_id
    assert result.schedule.rates[0].rate_class == "price"
    assert result.schedule.rates[0].cu_per_unit == 1
    # An open-ended rate card omits effective_until; it is not null.
    assert result.schedule.effective_until is None
    assert result.model_dump(exclude_unset=True) == SCHEDULE
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
            client.options.price(next(cases())[0], max_cu=maximum)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_ceiling_refusal_reports_quote_and_zero_charge(mode):
    refusal = problem(
        "cost_limit_exceeded",
        "the quoted CU charge exceeds x-morphiq-max-cu",
        status=409,
        metadata={**METADATA, "billing": {"quoted_cu": 2, "charged_cu": 0}},
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["x-morphiq-max-cu"] == "1"
        return httpx.Response(409, json=refusal)

    request = next(cases())[0]
    settings = {"api_key": "synthetic-test-key", "transport": httpx.MockTransport(handler)}
    with pytest.raises(sdk.APIError) as raised:
        if mode == "sync":
            with sdk.MorphIQ(**settings) as client:
                client.options.price(request, max_cu=1)
        else:

            async def run():
                async with sdk.AsyncMorphIQ(**settings) as client:
                    await client.options.price(request, max_cu=1)

            asyncio.run(run())
    assert len(calls) == 1
    assert raised.value.code == "cost_limit_exceeded"
    assert raised.value.metadata.billing.quoted_cu == 2
    assert raised.value.metadata.charged_cu == 0


def test_quote_timeout_is_non_billable_and_not_retried():
    seen = []

    def handler(request):
        seen.append(request)
        raise httpx.ReadTimeout("fixture")

    with sdk.MorphIQ(
        api_key="synthetic-test-key", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(sdk.RequestTimeout, match="no calculation or CU charge"):
            client.rate_card.quote(next(cases())[0])
    assert len(seen) == 1


def _validate(name, value):
    Draft202012Validator({"$ref": f"#/components/schemas/{name}", **SCHEMA}).validate(value)


def test_cost_wire_contract():
    _validate("RateCardGetResponse", SCHEDULE)
    _validate("RateCardQuoteResponse", QUOTE)
    assert sdk.RateCardGetResponse.model_validate(SCHEDULE).model_dump(exclude_unset=True) == (
        SCHEDULE
    )
    assert sdk.RateCardQuoteResponse.model_validate(QUOTE).model_dump(exclude_unset=True) == (QUOTE)
    for request, operation, case in cases():
        if case["path"] == "/v1/options:batch-price":
            continue  # Its recorded batch deliberately carries a schema-invalid item.
        _validate("RateCardQuoteRequest", {"operation": operation, "request": request.to_wire()})


def test_cost_notebook_actions_are_explicit_and_ceiling_is_forwarded(monkeypatch):
    """Execute setup and real button callbacks against a local mock transport."""
    notebook = json.loads((ROOT / "notebooks/cost/quotation.ipynb").read_text())
    recorded = []
    price_case = next(cases())[2]

    def handler(request):
        recorded.append(request)
        if request.url.path == "/v1/rate-card":
            return httpx.Response(200, json=SCHEDULE)
        if request.url.path == "/v1/rate-card:quote":
            return httpx.Response(200, json=QUOTE)
        assert request.url.path == "/v1/options:price"
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
def test_rate_card_example_requests_and_refusal_evidence(
    monkeypatch, capsys, arguments, quantity, execute, ceiling
):
    import runpy
    import sys

    recorded = []
    price_case = next(cases())[2]
    quoted = copy.deepcopy(QUOTE)
    quoted["quote"].update(total_cu=quantity, variable_cu=quantity)
    quoted["quote"]["lines"][0].update(quantity=quantity, variable_cu=quantity)
    quoted["resolved_models"][0]["quantity"] = quantity

    def handler(request):
        recorded.append(request)
        if request.url.path == "/v1/rate-card":
            assert dict(request.url.params) == {"rate_class": "price"}
            return httpx.Response(200, json=SCHEDULE)
        body = json.loads(request.content)
        if request.url.path == "/v1/rate-card:quote":
            assert body["operation"] == (
                "options.batch_price" if quantity == 2 else "options.price"
            )
            return httpx.Response(200, json=quoted)
        assert request.headers["x-morphiq-max-cu"] == str(ceiling)
        assert body == json.loads(recorded[1].content)["request"]
        if quantity == 2:
            assert request.url.path == "/v1/options:batch-price" and len(body["items"]) == 2
        else:
            assert request.url.path == "/v1/options:price"
        if ceiling < quantity:
            return httpx.Response(
                409,
                json=problem(
                    "cost_limit_exceeded",
                    "ceiling exceeded",
                    status=409,
                    metadata={**METADATA, "billing": {"quoted_cu": quantity, "charged_cu": 0}},
                ),
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
    monkeypatch.setattr(sys, "argv", ["rate_card_quote.py", *arguments])
    if execute and ceiling < quantity:
        with pytest.raises(SystemExit) as failure:
            runpy.run_path(str(ROOT / "examples/rate_card_quote.py"), run_name="__main__")
        assert failure.value.code == 1
    else:
        runpy.run_path(str(ROOT / "examples/rate_card_quote.py"), run_name="__main__")
    assert len(recorded) == (3 if execute else 2)
    output = capsys.readouterr()
    assert "synthetic-test-key" not in output.out + output.err
    assert f"Prospective execution CU: {quantity}" in output.out
    assert "Utility CU charged: 0" in output.out
    if execute and ceiling < quantity:
        assert "409: cost_limit_exceeded" in output.err
        assert "Execution quote CU: 2" in output.err and "CU charged: 0" in output.err
        assert "No retry or automatic ceiling increase." in output.err
