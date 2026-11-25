"""Native API 0.10 fixtures plus transport, quotation and uncertainty contracts."""

import asyncio
import copy
import json
import os
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from support import charged, problem

import morphiq_sdk as sdk

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())
CASES = json.loads((ROOT / "tests/fixtures/scenarios.json").read_text())["cases"]
QUOTES = json.loads((ROOT / "tests/fixtures/scenario_quotes.json").read_text())["cases"]


def invoke(client, case, request, **kwargs):
    collection, method = case["operation"].split(".")
    return getattr(getattr(client, collection), method)(request, **kwargs)


def validate(name, body):
    name = name.replace("BooksExplain", "BooksRevalue")
    Draft202012Validator({"$ref": f"#/components/schemas/{name}", **SCHEMA}).validate(body)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_native_wire_round_trip_and_contract(case):
    request = getattr(sdk, case["request_model"]).model_validate(case["request"])
    assert request.to_wire() == case["request"]
    validate(case["request_model"], request.to_wire())
    response = getattr(sdk, case["response_model"]).model_validate(case["response"])
    assert response.model_dump(exclude_unset=True) == case["response"]
    if case["name"] != "option-partial":
        validate(case["response_model"], case["response"])
    else:
        # The service echoes the invalid spot in an error item's inputs; the
        # OpenAPI reuses a positive-spot request schema for that echoed object.
        assert response.result.scenarios[1].status == "error"
        assert response.result.scenarios[1].inputs.market.spot == -1
        validate("Problem", case["response"]["result"]["scenarios"][1]["error"])


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "case,quote", list(zip(CASES, QUOTES, strict=True)), ids=[c["name"] for c in CASES]
)
def test_quote_and_execution_use_exact_wire_and_one_charge(mode, case, quote):
    request = getattr(sdk, case["request_model"]).model_validate(case["request"])
    body = copy.deepcopy(case["response"])
    body["metadata"] = charged(body["metadata"], 200, 200)
    received = []

    def handle(wire):
        received.append(wire)
        assert wire.headers["Authorization"] == "Bearer fixture-key"
        if wire.url.path == "/v1/rate-card:quote":
            assert json.loads(wire.content) == quote["request"]
            validate("RateCardQuoteRequest", quote["request"])
            validate("RateCardQuoteResponse", quote["response"])
            return httpx.Response(200, json=quote["response"])
        assert wire.url.path == case["path"]
        assert wire.headers["X-MorphIQ-Max-CU"] == "200"
        assert json.loads(wire.content) == request.to_wire()
        return httpx.Response(200, json=body, headers={"X-Request-ID": "fixture"})

    async def asynchronous():
        async with sdk.AsyncMorphIQ(
            api_key="fixture-key", transport=httpx.MockTransport(handle)
        ) as c:
            estimate = await c.rate_card.quote(request)
            return estimate, await invoke(c, case, request, max_cu=200)

    if mode == "async":
        estimate, result = asyncio.run(asynchronous())
    else:
        with sdk.MorphIQ(api_key="fixture-key", transport=httpx.MockTransport(handle)) as c:
            estimate = c.rate_card.quote(request)
            result = invoke(c, case, request, max_cu=200)
    assert estimate.metadata.charged_cu == 0
    assert result.metadata.charged_cu == 200
    assert result.model_dump(exclude_unset=True) == body
    assert json.loads(result.raw_body) == body
    assert result.headers["x-request-id"] == "fixture"
    assert len(received) == 2


def test_order_duplicates_partial_errors_and_signed_position_survive():
    case = next(c for c in CASES if c["name"] == "option-partial")
    result = sdk.OptionsRevalueResponse.model_validate(case["response"]).result
    assert [item.index for item in result.scenarios] == [0, 1, 2]
    assert [item.status for item in result.scenarios] == ["success", "error", "success"]
    assert result.scenarios[0].result == result.scenarios[2].result
    assert result.position.quantity == -2
    assert result.scenarios[0].pnl == pytest.approx(result.scenarios[0].price_change * -200)


def test_book_attribution_partitions_and_overlapping_strategies():
    result = sdk.BooksExplainResponse.model_validate(CASES[3]["response"]).result
    book = result.books[0]
    assert [p.id for p in book.positions] == ["long-call", "short-call"]
    assert book.positions[1].quantity < 0
    assert result.pnl == pytest.approx(sum(p.pnl for p in book.positions))
    assert sum(s.pnl for s in book.strategies) != pytest.approx(result.pnl)
    for attribution in (result.attribution, book.attribution):
        assert sum(b.pnl for b in attribution.expiry_buckets) == pytest.approx(result.pnl)
        assert sum(b.pnl for b in attribution.strike_buckets) == pytest.approx(result.pnl)
    solve = sdk.BooksSolveScenarioResponse.model_validate(CASES[4]["response"]).result
    assert solve.pnl_basis == "signed_reference_net_value"
    assert solve.signed_reference_net_value == 200
    assert solve.boundaries[0].coordinate == pytest.approx(102, abs=1e-6)


def test_incomplete_solve_is_preserved_not_misreported_as_no_solution():
    case = next(c for c in CASES if c["name"] == "option-unresolved")
    result = sdk.OptionsSolveScenarioResponse.model_validate(case["response"]).result
    assert result.outcome == "incomplete"
    assert result.coverage.status == "unresolved" and result.coverage.cells
    assert result.coverage.cells[0].best_abs_value_error > 0


@pytest.mark.parametrize("case", [CASES[1], CASES[4]])
def test_unknown_solver_variants_and_enums_remain_visible(case):
    body = copy.deepcopy(case["response"])
    body["result"].update(
        outcome="future_outcome",
        coordinate="future_axis",
        coordinate_unit="future_unit",
        coverage={"status": "future_coverage", "evidence": [1, 2]},
        boundaries=[{"kind": "future_boundary", "certificate": "preserved"}],
    )
    if "target" in body["result"]:
        body["result"]["target"] = {"kind": "future_target", "value": 1}
    else:
        body["result"]["scenario"]["shocks"].append({"kind": "future_shock", "axis": "x"})
    if "positions" in body["result"]:
        body["result"]["positions"][0]["contract"]["model"]["id"] = "future_model"
    parsed = getattr(sdk, case["response_model"]).model_validate(body)
    assert parsed.model_dump(exclude_unset=True) == body


@pytest.mark.parametrize("kind", ["timeout", "problem", "malformed", "reordered"])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_failure_evidence_and_no_automatic_retry(kind, mode):
    case = CASES[0]
    request = sdk.OptionsRevalueRequest.model_validate(case["request"])
    calls = []
    body = copy.deepcopy(case["response"])
    metadata = charged(body["metadata"], 100)

    def handle(wire):
        calls.append(wire)
        if kind == "timeout":
            raise httpx.ReadTimeout("uncertain", request=wire)
        if kind == "problem":
            return httpx.Response(
                422, json=problem("invalid_field", metadata=metadata, field="market.spot")
            )
        if kind == "malformed":
            return httpx.Response(200, json={"metadata": metadata, "result": {}})
        body["result"]["scenarios"].reverse()
        return httpx.Response(200, json=body)

    expected = {"timeout": sdk.RequestTimeout, "problem": sdk.APIError}.get(kind, sdk.ResponseError)

    async def asynchronous():
        async with sdk.AsyncMorphIQ(api_key="fixture", transport=httpx.MockTransport(handle)) as c:
            await c.options.revalue(request)

    with pytest.raises(expected) as failure:
        if mode == "async":
            asyncio.run(asynchronous())
        else:
            with sdk.MorphIQ(api_key="fixture", transport=httpx.MockTransport(handle)) as c:
                c.options.revalue(request)
    assert len(calls) == 1
    if kind == "problem":
        assert failure.value.metadata.charged_cu == 100
        assert failure.value.field == "market.spot"


def test_closed_requests_revalidate_mutable_lists_and_reject_future_variants():
    request = sdk.OptionsRevalueRequest.model_validate(CASES[0]["request"])
    request.scenarios.append({"spot": float("nan")})
    with pytest.raises(ValidationError):
        request.to_wire()
    request = copy.deepcopy(CASES[2]["request"])
    request["scenario"]["shocks"] = [{"kind": "future_shock", "amount": 1}]
    with pytest.raises(ValidationError):
        sdk.BooksRevalueRequest.model_validate(request)
    request = sdk.BooksRevalueRequest.model_validate(CASES[2]["request"])
    request.markets["SPY"] = {"spot": float("inf"), "risk_free_rate": 0.05, "dividend_yield": 0}
    with pytest.raises(ValidationError):
        request.to_wire()


@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_native_scenario_and_book_operations(case):
    endpoint = os.environ.get("MORPHIQ_TEST_API_URL")
    if not endpoint:
        pytest.skip("Set MORPHIQ_TEST_API_URL to a controlled pinned local API")
    assert httpx.URL(endpoint).host in {"localhost", "127.0.0.1", "::1"}
    request = getattr(sdk, case["request_model"]).model_validate(case["request"])
    with sdk.MorphIQ(base_url=endpoint, allow_unauthenticated=True) as client:
        response = invoke(client, case, request)
    assert response.result.model_dump(exclude_unset=True) == case["response"]["result"]
    assert response.metadata.contract.sha256 == SCHEMA_DIGEST


SCHEMA_DIGEST = json.loads((ROOT / "contracts/provenance.json").read_text())["sha256"]


def test_interval_and_no_solution_are_distinct_from_incomplete():
    interval = next(c for c in CASES if c["name"] == "book-interval")
    result = sdk.BooksSolveScenarioResponse.model_validate(interval["response"]).result
    assert result.coverage.status == "resolved"
    assert result.boundaries[0].kind == "interval"
    assert (result.boundaries[0].lower, result.boundaries[0].upper) == (50, 90)
    absent = next(c for c in CASES if c["name"] == "option-no-solution")
    result = sdk.OptionsSolveScenarioResponse.model_validate(absent["response"]).result
    assert result.coverage.status == "resolved"
    assert result.outcome == "no_solution_detected" and not result.boundaries


def test_all_shocks_multiple_underlyings_and_selected_strategy_are_preserved():
    case = next(c for c in CASES if c["name"] == "books-all-shocks")
    request = sdk.BooksExplainRequest.model_validate(case["request"])
    assert [s.kind for s in request.scenario.shocks] == [
        "spot_relative",
        "parallel_vol",
        "skew",
        "rate",
        "roll_down",
        "vol_term",
    ]
    result = sdk.BooksExplainResponse.model_validate(case["response"]).result
    assert [b.id for b in result.books] == ["spread", "second"]
    assert result.pnl == pytest.approx(sum(b.pnl for b in result.books))
    assert result.scenario.model_dump(exclude_unset=True) == case["request"]["scenario"]
    strategy = next(c for c in CASES if c["name"] == "book-strategy")
    result = sdk.BooksSolveScenarioResponse.model_validate(strategy["response"]).result
    assert result.strategy_id == "long-leg"
    assert [p.id for p in result.positions] == ["long-call"]


@pytest.mark.parametrize("case", CASES[:5], ids=lambda c: c["name"])
def test_standalone_examples_send_one_request_and_preserve_unreported_charge(
    case, fixture_api, tmp_path
):
    import shutil
    import subprocess
    import sys

    endpoint, received = fixture_api
    source = ROOT / "examples" / (case["name"] + ".py")
    script = tmp_path / source.name
    shutil.copyfile(source, script)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "example-key"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(received) == 1
    assert received[0] == (case["path"], "Bearer example-key", case["request"])
    assert "Commercial CU charged: not reported" in result.stdout
    assert "example-key" not in result.stdout + result.stderr
