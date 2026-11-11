"""The runnable example's HTTP -> SDK -> API boundary and billing controls."""

import copy
import hashlib
import importlib.util
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from morphiq_sdk import MorphIQ

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("solver_example", ROOT / "examples/solver_app/app.py")
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)
CASES = json.loads((ROOT / "tests/fixtures/scenarios.json").read_text())["cases"]
SOLVES = [case for case in CASES if case["name"].startswith("solve-")]
SUCCESS = [case for case in SOLVES if case["status"] == 200]


@contextmanager
def running_app(client):
    with APP.SolverApp(client, port=0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=server.origin, headers={"Origin": server.origin}) as browser:
                yield browser
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


@contextmanager
def fixture_app(case, *, fault=None):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer app-test-key"
        if request.url.path == "/v1/cost/quote":
            return httpx.Response(200, json=case["quote"])
        assert request.url.path == "/v1/scenarios/solve-spot"
        assert json.loads(request.content) == case["request"]
        assert request.headers["x-morphiq-max-cu"] == str(case["expected_cu"])
        if fault:
            return fault(request)
        return httpx.Response(case["status"], json=case["response"])

    with MorphIQ(api_key="app-test-key", transport=httpx.MockTransport(upstream)) as client:
        with running_app(client) as browser:
            yield browser, calls


def quote_and_solve(browser, case):
    quote = browser.post("/api/quote", json={"request": case["request"]})
    assert quote.status_code == 200, quote.text
    payload = {
        "request": case["request"],
        "quote_id": quote.json()["quote_id"],
        "max_cu": str(case["expected_cu"]),
    }
    return quote.json(), browser.post("/api/solve", json=payload), payload


@pytest.mark.parametrize("case", SUCCESS, ids=lambda case: case["name"])
def test_app_preserves_native_results_receipts_and_has_no_hidden_calls(case):
    with fixture_app(case) as (browser, calls):
        for path, content in [
            ("/", "Find the underlying price"),
            ("/app.js", "solve"),
            ("/style.css", "@media"),
        ]:
            result = browser.get(path)
            assert result.status_code == 200 and content in result.text
            assert "frame-ancestors 'none'" in result.headers["content-security-policy"]
            assert "app-test-key" not in result.text
        assert not calls
        quote, result, payload = quote_and_solve(browser, case)
        assert quote["quoted_cu"] == str(case["expected_cu"])
        assert json.loads(quote["raw_response"]) == case["quote"]
        assert result.status_code == 200
        assert result.json()["charged_cu"] == str(case["expected_cu"])
        assert json.loads(result.json()["raw_response"]) == case["response"]
        assert len(calls) == 2
        # A stale click/replay cannot submit another billable solve.
        assert browser.post("/api/solve", json=payload).status_code == 400
        assert len(calls) == 2


def test_app_refuses_below_cap_changed_inputs_and_unquoted_requests_locally():
    case = SUCCESS[0]
    with fixture_app(case) as (browser, calls):
        payload = {"request": case["request"], "quote_id": "none", "max_cu": "100"}
        assert browser.post("/api/solve", json=payload).status_code == 400
        assert not calls
        quote = browser.post("/api/quote", json={"request": case["request"]}).json()
        payload["quote_id"] = quote["quote_id"]
        for cap in ("99", "-1", "1.2", "NaN", str(2**64), 100, True, None):
            payload["max_cu"] = cap
            result = browser.post("/api/solve", json=payload)
            assert result.status_code == 400 and result.json()["local_refusal"]
        payload["max_cu"] = "100"
        payload["request"] = copy.deepcopy(case["request"])
        payload["request"]["target"]["value"] += 1
        assert browser.post("/api/solve", json=payload).status_code == 400
        assert len(calls) == 1


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://example.com"}, {"Origin": "null"}, {"Host": "example.com"}]
)
def test_other_origins_cannot_bill_through_local_process(headers):
    with fixture_app(SUCCESS[0]) as (browser, calls):
        result = browser.post(
            "/api/quote", json={"request": SUCCESS[0]["request"]}, headers=headers
        )
        assert result.status_code == 403
        assert not calls


def test_local_route_and_body_validation_never_call_api():
    with fixture_app(SUCCESS[0]) as (browser, calls):
        assert browser.get("/../app.py").status_code == 404
        assert browser.post("/v1/pricing/price", json={}).status_code == 404
        for body in ("[]", "{}", '{"request": {}}', "!", "x" * 32769):
            assert (
                browser.post(
                    "/api/quote", content=body, headers={"Content-Type": "application/json"}
                ).status_code
                == 400
            )
        assert browser.post("/api/quote", data={"request": "bad"}).status_code == 400
        assert not calls


@pytest.mark.parametrize("name", ["solve-bsm-numerical-error", "solve-bsm-invalid"])
def test_api_errors_preserve_known_charge_and_request_id(name):
    error = next(case for case in SOLVES if case["name"] == name)
    case = SUCCESS[0]
    with fixture_app(
        case, fault=lambda _: httpx.Response(error["status"], json=error["response"])
    ) as (browser, calls):
        _, result, payload = quote_and_solve(browser, case)
        assert result.status_code == 502
        body = result.json()
        assert body["upstream_status"] == error["status"]
        assert json.loads(body["raw_response"]) == error["response"]
        assert body["metadata"] == error["response"]["metadata"]
        assert body["charged_cu"] == str(error["response"]["metadata"]["fcu_charged"])
        assert browser.post("/api/solve", json=payload).status_code == 400
        assert len(calls) == 2


def test_invalid_api_result_preserves_receipt_without_retry():
    case = SUCCESS[0]
    malformed = copy.deepcopy(case["response"])
    malformed.pop("result")
    with fixture_app(case, fault=lambda _: httpx.Response(200, json=malformed)) as (browser, calls):
        _, result, _ = quote_and_solve(browser, case)
        assert result.status_code == 502
        assert result.json()["charged_cu"] == str(case["expected_cu"])
        assert result.json()["metadata"] == malformed["metadata"]
        assert len(calls) == 2


def test_disconnected_response_has_unknown_charge_and_cannot_replay():
    def disconnect(request):
        raise httpx.ReadTimeout("fixture disconnect", request=request)

    with fixture_app(SUCCESS[0], fault=disconnect) as (browser, calls):
        _, result, payload = quote_and_solve(browser, SUCCESS[0])
        assert result.status_code == 502
        assert "charge unknown" in result.json()["message"]
        assert "charged_cu" not in result.json()
        assert browser.post("/api/solve", json=payload).status_code == 400
        assert len(calls) == 2


@pytest.mark.integration
def test_example_app_against_protected_native_api():
    url, key = os.getenv("MORPHIQ_TEST_API_URL"), os.getenv("MORPHIQ_TEST_API_KEY")
    if not url or not key:
        pytest.skip("Requires an explicitly configured protected candidate API")
    provenance = json.loads((ROOT / "contracts/provenance.json").read_text())
    schema = httpx.get(f"{url}/openapi.json", trust_env=False)
    assert hashlib.sha256(schema.content).hexdigest() == provenance["sha256"]
    with MorphIQ(base_url=url, api_key=key) as client, running_app(client) as browser:
        for case in SUCCESS:
            quote, response, _ = quote_and_solve(browser, case)
            assert response.status_code == 200, response.text
            result = json.loads(response.json()["raw_response"])
            assert (
                int(quote["quoted_cu"]) == result["metadata"]["fcu_charged"] == case["expected_cu"]
            )
            assert result["result"] == case["response"]["result"]


@pytest.mark.parametrize("charge", [None, 0, 2**100])
def test_app_keeps_missing_zero_and_large_receipts_distinct(charge):
    case = copy.deepcopy(SUCCESS[0])
    if charge is None:
        case["response"]["metadata"].pop("fcu_charged")
    else:
        case["response"]["metadata"]["fcu_charged"] = charge
    with fixture_app(case) as (browser, calls):
        _, response, _ = quote_and_solve(browser, case)
        assert response.status_code == 200
        assert response.json()["charged_cu"] == (None if charge is None else str(charge))
        assert len(calls) == 2
