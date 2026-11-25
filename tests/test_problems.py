"""Flat RFC 9457 problems on every error, including target-solve context."""

import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from support import charged, problem

from morphiq_sdk import (
    APIError,
    ErrorResponse,
    Market,
    MorphIQ,
    Option,
    OptionsPriceRequest,
    Problem,
    RateLimitError,
    SolveTrialContext,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())
REQUEST = OptionsPriceRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.2,
)


def fail(status, body, content_type="application/problem+json", **headers):
    def handle(request):
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(
            status, content=content, headers={"Content-Type": content_type, **headers}
        )

    with MorphIQ(api_key="problem-key", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(APIError) as raised:
            client.options.price(REQUEST)
    return raised.value


def test_problem_members_are_exposed_on_the_error(cases):
    metadata = charged(cases[0]["response"]["metadata"], 0, quoted=1)
    body = problem(
        "invalid_field", "invalid input: spot = -1", metadata=metadata, field="market.spot"
    )
    Draft202012Validator({"$ref": "#/components/schemas/ErrorResponse", **SCHEMA}).validate(body)
    error = fail(422, body)
    assert error.status_code == 422
    assert (error.code, error.field) == ("invalid_field", "market.spot")
    assert error.title == "Invalid field"
    assert error.detail == "invalid input: spot = -1"
    assert error.solve_trial is None
    assert isinstance(error.problem, ErrorResponse)
    assert error.problem.type.endswith("#invalid_field")
    assert error.problem.model_dump(exclude_unset=True) == body
    assert error.metadata.charged_cu == 0 and error.metadata.billing.quoted_cu == 1
    assert error.request_id == metadata["request_id"]
    assert str(error) == (
        f"HTTP 422 (invalid_field): invalid input: spot = -1; request_id={metadata['request_id']}"
    )


def test_solve_trial_context_is_typed_and_open(cases):
    trial = {
        "phase": "search",
        "coordinate": "spot",
        "coordinate_value": 81.5,
        "evaluations": 3,
    }
    body = problem(
        "pricing_failed",
        "the pricing engine could not produce a result",
        status=422,
        metadata=cases[0]["response"]["metadata"],
        solve_trial=trial,
    )
    error = fail(422, body)
    assert isinstance(error.solve_trial, SolveTrialContext)
    assert error.solve_trial.phase == "search" and error.solve_trial.evaluations == 3
    future = {**trial, "phase": "bracketing", "coordinate": "volatility"}
    parsed = SolveTrialContext.model_validate(future)
    assert (parsed.phase, parsed.coordinate) == ("bracketing", "volatility")


def test_unknown_problem_codes_and_extensions_are_retained(cases):
    body = problem(
        "future_refusal",
        "a refusal this SDK does not know",
        status=403,
        metadata=cases[0]["response"]["metadata"],
        instance="/v1/options:price",
        retry_hint={"after": "later"},
    )
    error = fail(403, body)
    assert error.code == "future_refusal"
    assert error.problem.model_extra == {
        "instance": "/v1/options:price",
        "retry_hint": {"after": "later"},
    }


@pytest.mark.parametrize(
    "body",
    [
        # The retired envelope is not a problem; its evidence stays in body and headers.
        {"error": {"code": "pricing_failed", "message": "old"}, "metadata": {}},
        {"type": "about:blank", "title": "No metadata", "status": 502, "detail": "x", "code": "y"},
        b"<html>gateway</html>",
    ],
)
def test_non_problem_bodies_do_not_invent_fields(body):
    error = fail(502, body, content_type="text/html", **{"x-request-id": "edge-id"})
    assert error.problem is None and error.code is None and error.metadata is None
    assert error.detail == "Non-standard API or gateway response"
    assert error.request_id == "edge-id"
    assert error.body == (body if isinstance(body, bytes) else json.dumps(body).encode())


def test_rate_limit_problem_keeps_retry_guidance(cases):
    body = problem(
        "concurrency_limited",
        "too many concurrent requests",
        status=429,
        metadata=charged(cases[0]["response"]["metadata"], 0),
    )
    error = fail(429, body, **{"Retry-After": "3"})
    assert isinstance(error, RateLimitError)
    assert error.retry_delay() == 3 and error.metadata.charged_cu == 0


def test_problem_model_matches_the_contract_and_requires_core_members():
    assert set(Problem.model_fields) == set(
        SCHEMA["components"]["schemas"]["Problem"]["properties"]
    )
    complete = problem("x")
    for member in ("type", "title", "status", "detail", "code"):
        with pytest.raises(ValueError):
            Problem.model_validate({k: v for k, v in complete.items() if k != member})
