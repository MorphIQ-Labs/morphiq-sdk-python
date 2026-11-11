"""Scenario wire, transport and receipt parity against the pinned native API."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    MorphIQ,
    RateLimitError,
    RequestTimeout,
    ResponseError,
    ScenarioFailure,
    ScenarioOptionPriceTarget,
    ScenarioPoint,
    ScenarioPosition,
    ScenarioPositionPnlTarget,
    ScenarioPriceInputs,
    ScenarioRequest,
    ScenarioResponse,
    ScenarioSolveInterval,
    ScenarioSolvePoint,
    ScenarioSolveProfile,
    ScenarioSolveRegion,
    ScenarioSolveResolved,
    ScenarioSolveUnresolved,
    ScenarioSolveUnresolvedCell,
    ScenarioSpotSolveRequest,
    ScenarioSpotSolveResponse,
    ScenarioSpotSolveResult,
    ScenarioSuccess,
    ScenarioValuation,
)

ROOT = Path(__file__).parents[1]
ARTIFACT = json.loads((ROOT / "tests/fixtures/scenarios.json").read_text())
CASES = ARTIFACT["cases"]
SUCCESS = [case for case in CASES if case["status"] == 200]
SOLVES = [case for case in SUCCESS if case["name"].startswith("solve-")]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())


def request_for(case):
    model = ScenarioSpotSolveRequest if case["path"].endswith("solve-spot") else ScenarioRequest
    return model.model_validate(case["request"])


def method_for(case):
    return "solve_spot" if case["path"].endswith("solve-spot") else "evaluate_scenarios"


def invoke(mode, handler, action):
    transport = httpx.MockTransport(handler)
    if mode == "sync":
        with MorphIQ(api_key="scenario-test-key", transport=transport) as client:
            return action(client)

    async def run():
        async with AsyncMorphIQ(api_key="scenario-test-key", transport=transport) as client:
            return await action(client)

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("case", SUCCESS, ids=lambda case: case["name"])
def test_native_response_and_request_parity(mode, case):
    calls = []
    request = request_for(case)

    def handle(incoming):
        calls.append(incoming)
        assert incoming.method == "POST" and incoming.url.path == case["path"]
        assert incoming.headers["authorization"] == "Bearer scenario-test-key"
        assert incoming.headers["x-morphiq-max-cu"] == str(case["expected_cu"])
        assert json.loads(incoming.content) == case["request"]
        return httpx.Response(200, json=case["response"], headers={"x-request-id": "fixture-id"})

    result = invoke(
        mode, handle, lambda c: getattr(c, method_for(case))(request, max_cu=case["expected_cu"])
    )
    assert len(calls) == 1
    assert result.model_dump(exclude_unset=True) == case["response"]
    assert json.loads(result.raw_body) == case["response"]
    assert result.headers["x-request-id"] == "fixture-id"
    assert result.metadata.fcu_charged == case["expected_cu"]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("case", SUCCESS, ids=lambda case: case["name"])
def test_quotes_send_one_free_utility_call_with_the_right_operation(mode, case):
    calls = []

    def handle(incoming):
        calls.append(incoming)
        assert incoming.url.path == "/v1/cost/quote"
        assert "x-morphiq-max-cu" not in incoming.headers
        assert json.loads(incoming.content) == {
            "operation": "scenario_spot_solve"
            if method_for(case) == "solve_spot"
            else "scenario_evaluate",
            "request": case["request"],
        }
        return httpx.Response(200, json=case["quote"])

    result = invoke(mode, handle, lambda c: c.quote(request_for(case)))
    assert len(calls) == 1
    assert result.quote.total_fcu == case["expected_cu"]
    assert result.metadata.fcu_charged == 0
    if case in SOLVES:
        assert result.resolved_models[0].quantity == 1


def test_fixture_and_wire_model_coverage_matches_exact_api_snapshot():
    provenance = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert ARTIFACT["source"]["api_commit"] == provenance["source_commit"]
    assert ARTIFACT["source"]["schema_sha256"] == provenance["sha256"]
    schemas = SCHEMA["components"]["schemas"]
    for model, name in [
        (ScenarioPosition, "ScenarioPosition"),
        (ScenarioPoint, "ScenarioPoint"),
        (ScenarioRequest, "ScenarioRequest"),
        (ScenarioSpotSolveRequest, "ScenarioSpotSolveRequest"),
        (ScenarioPriceInputs, "PriceRequest"),
        (ScenarioValuation, "ScenarioValuation"),
        (ScenarioResponse, "ScenarioResponse"),
        (ScenarioSpotSolveResponse, "ScenarioSpotSolveResponse"),
        (ScenarioSpotSolveResult, "ScenarioSpotSolveResult"),
        (ScenarioSolveProfile, "ScenarioSolveProfile"),
        (ScenarioSolveRegion, "ScenarioSolveRegion"),
        (ScenarioSolveUnresolvedCell, "ScenarioSolveUnresolvedCell"),
    ]:
        assert set(model.model_fields) == set(schemas[name]["properties"])
    for models, name in [
        ([ScenarioOptionPriceTarget, ScenarioPositionPnlTarget], "ScenarioSolveTarget"),
        ([ScenarioSolvePoint, ScenarioSolveInterval], "ScenarioSolveBoundary"),
        ([ScenarioSolveResolved, ScenarioSolveUnresolved], "ScenarioSolveCoverage"),
        ([ScenarioSuccess, ScenarioFailure], "ScenarioOutcome"),
    ]:
        for model, variant in zip(models, schemas[name]["oneOf"], strict=True):
            extra = {"index", "inputs"} if name == "ScenarioOutcome" else set()
            assert set(model.model_fields) == set(variant["properties"]) | extra
    for case in CASES:
        solving = method_for(case) == "solve_spot"
        pairs = [
            (
                "ScenarioSpotSolveRequest" if solving else "ScenarioRequest",
                request_for(case).to_wire(),
            ),
            (
                ("ScenarioSpotSolveResponse" if solving else "ScenarioResponse")
                if case["status"] == 200
                else "ErrorEnvelope",
                case["response"],
            ),
        ]
        if case["quote"]:
            pairs.append(("CostQuoteResponse", case["quote"]))
        for name, value in pairs:
            Draft202012Validator(
                {"$ref": f"#/components/schemas/{name}", "components": SCHEMA["components"]}
            ).validate(value)


def test_omission_null_zero_and_nested_list_edits_are_preserved_or_revalidated():
    case = SOLVES[0]
    request = request_for(case)
    assert request.to_wire() == case["request"]
    assert "spot_tolerance" not in request.to_wire()
    changed = ScenarioSpotSolveRequest.model_validate(
        {**case["request"], "volatility": None, "elapsed_time_years": 0.0}
    )
    assert changed.to_wire()["volatility"] is None
    assert changed.to_wire()["elapsed_time_years"] == 0.0
    evaluate = request_for(SUCCESS[0])
    evaluate.scenarios.append(ScenarioPoint(spot_change=0.0, volatility=None))
    assert evaluate.to_wire()["scenarios"][-1] == {"spot_change": 0.0, "volatility": None}
    evaluate.scenarios.append({"spot_change": float("nan")})
    with pytest.raises(ValidationError):
        evaluate.to_wire()
    request.contract.dividend_schedule.append({"ex_time_years": "wrong", "cash_amount": 1})
    with pytest.raises(ValidationError):
        request.to_wire()
    for count in (0, 100):
        with pytest.raises(ValidationError):
            ScenarioRequest(contract=request.contract, scenarios=[ScenarioPoint()] * count)
    with pytest.raises(ValidationError):
        ScenarioSpotSolveRequest.model_validate({**case["request"], "max_spot": float("inf")})
    with pytest.raises(ValidationError):
        ScenarioSpotSolveRequest.model_validate(
            {**case["request"], "target": {"kind": "position_pnl", "value": 0.0}}
        )


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("case", [c for c in CASES if c["status"] != 200], ids=lambda c: c["name"])
def test_errors_preserve_zero_or_committed_charge_and_never_retry(mode, case):
    calls = []

    def handle(incoming):
        calls.append(incoming)
        return httpx.Response(case["status"], json=case["response"])

    with pytest.raises(APIError) as error:
        invoke(mode, handle, lambda c: c.solve_spot(request_for(case)))
    assert len(calls) == 1
    assert error.value.metadata.fcu_charged == case["expected_cu"]
    assert error.value.body == json.dumps(case["response"], separators=(",", ":")).encode()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["missing_boundary_value", "invalid_coverage", "bad_count"])
def test_malformed_solve_response_keeps_charge_evidence(mode, failure):
    case = SOLVES[0]
    payload = copy.deepcopy(case["response"])
    if failure == "missing_boundary_value":
        del payload["result"]["boundaries"][0]["value"]
    elif failure == "invalid_coverage":
        payload["result"]["coverage"] = {"status": "unresolved"}
    else:
        payload["result"]["price_evaluations"] = 2**64
    with pytest.raises(ResponseError) as error:
        invoke(
            mode,
            lambda r: httpx.Response(200, json=payload),
            lambda c: c.solve_spot(request_for(case)),
        )
    assert error.value.metadata.fcu_charged == 100
    assert json.loads(error.value.body) == payload


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["reordered", "missing", "duplicate"])
def test_scenario_results_cannot_be_silently_misassociated(mode, failure):
    case = next(c for c in SUCCESS if c["name"] == "scenario-bsm-partial")
    payload = copy.deepcopy(case["response"])
    if failure == "reordered":
        payload["results"].reverse()
    elif failure == "missing":
        payload["results"].pop()
    else:
        payload["results"][1]["index"] = 0
    with pytest.raises(ResponseError) as error:
        invoke(
            mode,
            lambda r: httpx.Response(200, json=payload),
            lambda c: c.evaluate_scenarios(request_for(case)),
        )
    assert error.value.metadata.fcu_charged == case["expected_cu"]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_additive_fields_and_large_diagnostic_counts_do_not_recalculate_charges(mode):
    case = SOLVES[0]
    payload = copy.deepcopy(case["response"])
    payload["result"]["future_diagnostic"] = {"value": 0}
    payload["result"]["boundaries"][0]["future_boundary"] = None
    payload["result"]["inputs"]["future_input"] = 0
    payload["result"]["price_evaluations"] = 2**53 + 1
    result = invoke(
        mode, lambda r: httpx.Response(200, json=payload), lambda c: c.solve_spot(request_for(case))
    )
    assert result.model_dump(exclude_unset=True) == payload
    assert result.result.price_evaluations == 2**53 + 1
    assert result.metadata.fcu_charged == 100


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["timeout", "rate_limit"])
@pytest.mark.parametrize("case", [SUCCESS[0], SOLVES[0]], ids=lambda c: c["name"])
def test_scenarios_never_retry_after_uncertain_execution_or_rate_limit(mode, failure, case):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("late response")
        return httpx.Response(429, json={"message": "slow down"}, headers={"Retry-After": "3"})

    with pytest.raises(RequestTimeout if failure == "timeout" else RateLimitError):
        invoke(mode, handle, lambda c: getattr(c, method_for(case))(request_for(case)))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "module,mode",
    [
        ("scenario_evaluate", "point"),
        ("scenario_evaluate", "grid"),
        ("solve_spot", "price"),
        ("solve_spot", "pnl"),
        ("solve_spot_async", "price"),
        ("solve_spot_async", "pnl"),
    ],
)
@pytest.mark.parametrize("model", ["bsm", "bs1993"])
def test_executable_examples_quote_then_optionally_execute_once(
    fixture_api, tmp_path, module, mode, model
):
    import os
    import shutil
    import subprocess
    import sys

    endpoint, received = fixture_api
    script = tmp_path / f"{module}.py"
    shutil.copyfile(ROOT / "examples" / script.name, script)
    args = [sys.executable, str(script), "--model", model]
    if module == "scenario_evaluate":
        args += ["--mode", mode]
        cost = (2 if mode == "point" else 10) * (1 if model == "bsm" else 2)
    else:
        cost = 100 if model == "bsm" else 200
        if mode == "pnl":
            args += ["--target-pnl", "500"]
    env = {**os.environ, "MORPHIQ_API_BASE_URL": endpoint, "MORPHIQ_API_KEY": "fixture-key"}
    quoted = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert quoted.returncode == 0, quoted.stderr
    assert len(received) == 1 and received[0][0] == "/v1/cost/quote"
    assert f"Quoted CU: {cost}" in quoted.stdout
    refused = subprocess.run(
        args + ["--max-cu", str(cost - 1)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert refused.returncode == 2 and len(received) == 2
    assert "no execution submitted" in refused.stderr
    executed = subprocess.run(
        args + ["--max-cu", str(cost)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert executed.returncode == 0, executed.stderr
    assert len(received) == 4
    assert f'"fcu_charged": {cost}' in executed.stdout
    assert "fixture-key" not in executed.stdout + executed.stderr


@pytest.mark.integration
def test_native_scenarios_sync_async_quotes_and_receipts():
    import hashlib
    import os

    endpoint = os.environ.get("MORPHIQ_TEST_API_URL")
    if not endpoint:
        pytest.skip("controlled API not set")
    key = os.environ.get("MORPHIQ_TEST_API_KEY")
    with httpx.Client(
        base_url=endpoint,
        trust_env=False,
        headers={"Authorization": f"Bearer {key}"} if key else {},
    ) as raw:
        provenance = json.loads((ROOT / "contracts/provenance.json").read_text())
        assert hashlib.sha256(raw.get("/openapi.json").content).hexdigest() == provenance["sha256"]

        async def run_async(case):
            async with AsyncMorphIQ(
                base_url=endpoint, api_key=key, allow_unauthenticated=key is None
            ) as client:
                return await getattr(client, method_for(case))(
                    request_for(case), max_cu=case["expected_cu"]
                )

        with MorphIQ(base_url=endpoint, api_key=key, allow_unauthenticated=key is None) as client:
            for case in SUCCESS:
                response = getattr(client, method_for(case))(
                    request_for(case), max_cu=case["expected_cu"]
                )
                asynchronous = asyncio.run(run_async(case))
                direct = raw.post(case["path"], json=case["request"])
                direct.raise_for_status()
                for candidate in (response, asynchronous):
                    assert {
                        k: v
                        for k, v in candidate.model_dump(exclude_unset=True).items()
                        if k != "metadata"
                    } == {k: v for k, v in direct.json().items() if k != "metadata"}
                    assert candidate.metadata.fcu_charged == (case["expected_cu"] if key else None)
                if key:
                    quote = client.quote(request_for(case))
                    assert quote.quote.total_fcu == case["expected_cu"]
                    assert quote.metadata.fcu_charged == 0
                    with pytest.raises(APIError) as refused:
                        getattr(client, method_for(case))(
                            request_for(case), max_cu=case["expected_cu"] - 1
                        )
                    assert refused.value.code == "cost_limit_exceeded"
                    assert refused.value.metadata.fcu_charged == 0
