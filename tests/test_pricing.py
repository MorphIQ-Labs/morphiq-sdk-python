import asyncio
import copy
import json
import os
import subprocess
import sys
import traceback

import httpx
import pytest
from pydantic import ValidationError
from support import charged, problem

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    DividendEvent,
    Market,
    ModelSelection,
    MorphIQ,
    Option,
    OptionsPriceRequest,
    RequestTimeout,
    ResponseError,
    TransportError,
)


def european_call():
    return OptionsPriceRequest(
        option=Option(
            type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0
        ),
        market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
        volatility=0.20,
    )


def american_put():
    return OptionsPriceRequest(
        option=Option(
            type="put", exercise_style="american", strike=105.0, time_to_expiry_years=0.5
        ),
        market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.01),
        volatility=0.20,
    )


def invoke(mode, transport, request=None, **kwargs):
    settings = {"base_url": "https://api.example.test/prefix", "api_key": "test-only-key"}
    settings.update(kwargs)
    request = request or european_call()
    if mode == "sync":
        with MorphIQ(transport=transport, **settings) as client:
            return client.options.price(request)

    async def run():
        async with AsyncMorphIQ(transport=transport, **settings) as client:
            return await client.options.price(request)

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", [0, 1])
def test_wire_request_and_native_response(mode, index, cases):
    case = cases[index]
    received = []

    def handle(request):
        received.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.example.test/prefix/v1/options:price"
        assert request.headers["Authorization"] == "Bearer test-only-key"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == case["request"]
        assert request.extensions["timeout"] == {
            "connect": 2.0,
            "read": 8.0,
            "write": 3.0,
            "pool": 1.0,
        }
        return httpx.Response(200, json=case["response"], headers={"x-request-id": "header-id"})

    response = invoke(
        mode,
        httpx.MockTransport(handle),
        OptionsPriceRequest.model_validate(case["request"]),
        timeout=httpx.Timeout(connect=2, read=8, write=3, pool=1),
    )
    assert len(received) == 1
    assert response.model_dump(exclude_unset=True) == case["response"]
    assert json.loads(response.raw_body) == case["response"]
    assert response.headers["x-request-id"] == "header-id"
    assert response.metadata.billing is None
    assert response.metadata.charged_cu is None
    assert response.result.model.id == case["response"]["result"]["model"]["id"]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status,code,charge",
    [
        (401, "unauthenticated", 0),
        (402, "insufficient_funds", 0),
        (403, "forbidden", 0),
        (422, "invalid_request", 0),
        (429, "concurrency_limited", 0),
        (503, "rollout_unavailable", 0),
        (500, "pricing_failed", 7),
        (504, "compute_deadline_exceeded", 7),
    ],
)
def test_failures_preserve_evidence_and_never_retry(mode, status, code, charge, cases):
    metadata = charged(cases[0]["response"]["metadata"], charge)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            json=problem(code, "failure", status=status, metadata=metadata, field="market.spot"),
            headers={
                "Retry-After": "1",
                "x-request-id": metadata["request_id"],
                "Content-Type": "application/problem+json",
            },
        )

    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(handle))
    error = raised.value
    assert len(calls) == 1
    assert error.status_code == status and error.code == code
    assert error.detail == "failure" and error.field == "market.spot"
    assert error.problem.status == status and error.title
    assert error.metadata.charged_cu == charge
    assert error.metadata.billing.charged_cu == charge
    assert error.request_id == metadata["request_id"]
    assert error.retry_after == "1"
    assert json.loads(error.body)["metadata"] == metadata


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_router_metadata_and_forward_compatible_results(mode, cases):
    body = copy.deepcopy(cases[0]["response"])
    body["result"]["model"]["id"] = "future_engine_model"
    body["result"]["new_diagnostic"] = {"available": True}
    body["metadata"]["billing"] = {"charged_cu": 0, "future_billing": "x"}
    body["metadata"]["budget"] = {"remaining_estimate_cu": 9900}
    body["future_field"] = [1, 2]
    response = invoke(mode, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    assert response.model_dump(exclude_unset=True) == body
    assert response.metadata.charged_cu == 0
    assert response.result.model.id == "future_engine_model"
    assert response.metadata.budget.remaining_estimate_cu == 9900
    assert response.metadata.budget.period is None

    router = problem(
        "not_found",
        "unknown route",
        status=404,
        metadata={
            "request_id": "router-id",
            "service_version": "test",
            "contract": {"version": "0.1.0", "sha256": "a" * 64},
        },
    )
    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(lambda _: httpx.Response(404, json=router)))
    assert raised.value.request_id == "router-id"
    assert raised.value.code == "not_found"
    assert raised.value.metadata.engines is None
    assert raised.value.metadata.charged_cu is None


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [302, 502])
def test_gateway_errors_and_redirects_are_not_replayed(mode, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="<html>gateway</html>",
            headers={"x-request-id": "edge-id", "Location": "https://elsewhere.example.test"},
        )

    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(handle))
    assert len(calls) == 1
    assert raised.value.body == b"<html>gateway</html>"
    assert raised.value.request_id == "edge-id"
    assert raised.value.metadata is None


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "body", [b"not JSON", b"{}", b'{"result":{"price":null}}', b'{"metadata":null}']
)
def test_invalid_success_is_not_silently_accepted(mode, body):
    with pytest.raises(ResponseError) as raised:
        invoke(
            mode,
            httpx.MockTransport(
                lambda _: httpx.Response(200, content=body, headers={"x-request-id": "bad-id"})
            ),
        )
    assert raised.value.request_id == "bad-id"
    assert raised.value.body == body


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "failure,expected",
    [
        (httpx.ReadTimeout, RequestTimeout),
        (httpx.ConnectError, TransportError),
    ],
)
def test_transport_failures_hide_secrets_and_do_not_retry(mode, failure, expected):
    calls = []

    def handle(request):
        calls.append(request)
        raise failure("test-only-key reflected by transport", request=request)

    with pytest.raises(expected) as raised:
        invoke(mode, httpx.MockTransport(handle))
    assert len(calls) == 1
    assert "test-only-key" not in "".join(traceback.format_exception(raised.value))
    assert "unknown" in str(raised.value)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_reflected_credentials_are_redacted(mode, cases):
    payload = problem(
        "bad_key",
        "reflected test-only-key",
        status=401,
        metadata=cases[0]["response"]["metadata"],
    )
    with pytest.raises(APIError) as raised:
        invoke(
            mode,
            httpx.MockTransport(
                lambda _: httpx.Response(401, json=payload, headers={"x-debug": "test-only-key"})
            ),
        )
    assert "test-only-key" not in str(raised.value)
    assert b"test-only-key" not in raised.value.body
    assert "test-only-key" not in repr(raised.value.headers)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "environment_url,explicit_url,expected_url",
    [
        (None, None, "https://api.morphiqlabs.com/v1/options:price"),
        ("", None, "https://api.morphiqlabs.com/v1/options:price"),
        (
            "https://env.example.test/prefix",
            None,
            "https://env.example.test/prefix/v1/options:price",
        ),
        (
            "https://env.example.test",
            "https://explicit.example.test/local",
            "https://explicit.example.test/local/v1/options:price",
        ),
    ],
)
def test_default_api_url_and_overrides(mode, environment_url, explicit_url, expected_url, cases):
    environment = {
        name: value for name, value in os.environ.items() if name != "MORPHIQ_API_BASE_URL"
    }
    if environment_url is not None:
        environment["MORPHIQ_API_BASE_URL"] = environment_url
    program = """
import asyncio
import json
import sys

import httpx

from morphiq_sdk import AsyncMorphIQ, MorphIQ, OptionsPriceRequest

config = json.loads(sys.argv[1])
received = []

def handle(request):
    received.append(request)
    assert str(request.url) == config["expected_url"]
    assert request.headers["Authorization"] == "Bearer test-only-key"
    return httpx.Response(200, json=config["case"]["response"])

settings = {
    "base_url": config["explicit_url"],
    "api_key": "test-only-key",
    "transport": httpx.MockTransport(handle),
}
request = OptionsPriceRequest.model_validate(config["case"]["request"])

async def run_async():
    async with AsyncMorphIQ(**settings) as client:
        await client.options.price(request)

if config["mode"] == "async":
    asyncio.run(run_async())
else:
    with MorphIQ(**settings) as client:
        client.options.price(request)
assert len(received) == 1
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            json.dumps(
                {
                    "mode": mode,
                    "explicit_url": explicit_url,
                    "expected_url": expected_url,
                    "case": cases[0],
                }
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )


def test_environment_configuration_and_representations(monkeypatch):
    monkeypatch.setenv("MORPHIQ_API_KEY", "environment-test-key")
    monkeypatch.setenv("MORPHIQ_API_BASE_URL", "https://api.example.test")
    with MorphIQ() as client:
        assert "environment-test-key" not in repr(client)
    with MorphIQ(api_key="explicit-key") as client:
        assert "explicit-key" not in repr(client)
    monkeypatch.delenv("MORPHIQ_API_KEY")
    with pytest.raises(ValueError, match="MORPHIQ_API_KEY"):
        with MorphIQ() as client:
            client.rate_card.get()
    with MorphIQ(allow_unauthenticated=True):
        pass


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_json_escaped_credentials_are_redacted(mode, cases):
    payload = problem(
        "bad_key", "test-only-key", status=401, metadata=cases[0]["response"]["metadata"]
    )
    encoded = json.dumps(payload).replace("test-only-key", r"\u0074est-only-key").encode()
    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(lambda _: httpx.Response(401, content=encoded)))
    assert "test-only-key" not in str(raised.value)
    assert json.loads(raised.value.body)["detail"] == "[REDACTED]"
    assert raised.value.detail == "[REDACTED]"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "ftp://example.test",
        "https://user:secret@example.test",
        "https://example.test?key=secret",
        "https://example.test/#secret",
    ],
)
def test_bad_endpoint_configuration_never_echoes_input(url):
    with pytest.raises(ValueError) as raised:
        MorphIQ(base_url=url, api_key="test-key")
    assert "secret" not in str(raised.value)


def test_request_shape_omission_validation_and_no_numeric_policy():
    request = european_call()
    wire = request.to_wire()
    assert wire == {
        "option": {
            "type": "call",
            "exercise_style": "european",
            "strike": 100.0,
            "time_to_expiry_years": 1.0,
        },
        "market": {"spot": 100.0, "risk_free_rate": 0.05, "dividend_yield": 0.0},
        "volatility": 0.2,
        "model": {"id": "auto"},
    }
    # Absent optional members are omitted, never sent as null.
    pinned = OptionsPriceRequest(
        option=request.option,
        market=request.market,
        volatility=0.2,
        model=ModelSelection(id="black_scholes_merton", version="black_scholes_merton/1"),
    )
    assert pinned.to_wire()["model"] == {
        "id": "black_scholes_merton",
        "version": "black_scholes_merton/1",
    }
    assert "version" not in OptionsPriceRequest.model_validate(wire).to_wire()["model"]
    for path, value in (
        (("volatility",), float("nan")),
        (("market", "spot"), True),
        (("market", "spot"), "100"),
        (("option", "exercise_style"), "unknown"),
        (("option", "type"), "straddle"),
        (("market", "dividends"), None),
        (("unknown",), 1),
        (("option", "unknown"), 1),
        (("model", "id"), "bjerksund_stensland_2002"),
        (("model", "id"), "qd_fixed_point"),
        (("model", "id"), "cash_dividend_american"),
    ):
        changed = copy.deepcopy(wire)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(ValidationError):
            OptionsPriceRequest.model_validate(changed)
    # Model-domain checks remain with the service; do not clamp or substitute.
    negative = copy.deepcopy(wire)
    negative["market"]["spot"] = -1.0
    assert OptionsPriceRequest.model_validate(negative).to_wire()["market"]["spot"] == -1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("initial", [None, [], [{"ex_time_years": 0.1, "cash_amount": 1.0}]])
def test_edited_dividends_are_sent_in_order(mode, initial, cases):
    values = american_put().to_wire()
    if initial is not None:
        values["market"]["dividends"] = initial
    request = OptionsPriceRequest.model_validate(values)
    request.market.dividends.append(DividendEvent(ex_time_years=0.25, cash_amount=2.0))
    received = []

    def handle(wire_request):
        received.append(json.loads(wire_request.content))
        return httpx.Response(200, json=cases[1]["response"])

    invoke(mode, httpx.MockTransport(handle), request)
    assert len(received) == 1
    assert received[0]["market"]["dividends"] == [
        *(initial or []),
        {"ex_time_years": 0.25, "cash_amount": 2.0},
    ]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "events",
    [
        [DividendEvent(ex_time_years=0.25, cash_amount=2.0)] * 17,
        [{"ex_time_years": 0.25, "cash_amount": float("nan")}],
        [{"ex_time_years": True, "cash_amount": 2.0}],
    ],
)
def test_invalid_dividend_edits_fail_before_transport(mode, events):
    request = american_put()
    request.market.dividends.extend(events)
    received = []

    def handle(wire_request):
        received.append(wire_request)
        return httpx.Response(200, json={})

    with pytest.raises(ValidationError):
        invoke(mode, httpx.MockTransport(handle), request)
    assert received == []


def test_empty_dividends_are_omitted():
    request = american_put()
    request.market.dividends.append(DividendEvent(ex_time_years=0.25, cash_amount=2.0))
    request.market.dividends.clear()
    assert "dividends" not in request.to_wire()["market"]
    explicit = Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0, dividends=[])
    assert "dividends" not in explicit.to_wire()


def test_async_cancellation_closes_transport_without_retry():
    async def run():
        started = asyncio.Event()

        class BlockingTransport(httpx.AsyncBaseTransport):
            calls = 0
            closed = False

            async def handle_async_request(self, request):
                self.calls += 1
                started.set()
                await asyncio.Future()

            async def aclose(self):
                self.closed = True

        transport = BlockingTransport()
        async with AsyncMorphIQ(
            base_url="https://api.example.test", api_key="test-key", transport=transport
        ) as client:
            task = asyncio.create_task(client.options.price(american_put()))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert transport.calls == 1
        assert transport.closed

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_grouped_metadata_is_typed_and_wire_faithful(mode, cases):
    body = copy.deepcopy(cases[0]["response"])
    body["metadata"].update(
        billing={
            "quoted_cu": 50,
            "charged_cu": 50,
            "rate_card": {"id": "fcu-qdfp-v1", "version": "2026-11-20-scenario-solves"},
        },
        budget={
            "period": "2026-11",
            "resets_at": "2026-12-01T00:00:00Z",
            "remaining_estimate_cu": 0,
        },
        policy={"plan": "developer", "revision": "a" * 64},
    )
    result = invoke(mode, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    metadata = result.metadata
    assert metadata.billing.quoted_cu == metadata.billing.charged_cu == metadata.charged_cu == 50
    assert metadata.billing.rate_card.version == "2026-11-20-scenario-solves"
    assert metadata.budget.remaining_estimate_cu == 0
    assert metadata.policy.plan == "developer"
    assert metadata.contract.sha256 == body["metadata"]["contract"]["sha256"]
    assert result.model_dump(exclude_unset=True) == body
