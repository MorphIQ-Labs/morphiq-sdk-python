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

from examples._shared import american_put, european_call
from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    DividendEvent,
    MorphIQ,
    PriceRequest,
    RequestTimeout,
    ResponseError,
    TransportError,
)


def invoke(mode, transport, request=None, **kwargs):
    settings = {"base_url": "https://api.example.test/prefix", "api_key": "test-only-key"}
    settings.update(kwargs)
    request = request or european_call()
    if mode == "sync":
        with MorphIQ(transport=transport, **settings) as client:
            return client.price(request)

    async def run():
        async with AsyncMorphIQ(transport=transport, **settings) as client:
            return await client.price(request)

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("index", [0, 1])
def test_wire_request_and_native_response(mode, index, cases):
    case = cases[index]
    received = []

    def handle(request):
        received.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.example.test/prefix/v1/price"
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
        PriceRequest(**case["request"]),
        timeout=httpx.Timeout(connect=2, read=8, write=3, pool=1),
    )
    assert len(received) == 1
    assert response.model_dump(exclude_unset=True) == case["response"]
    assert json.loads(response.raw_body) == case["response"]
    assert response.headers["x-request-id"] == "header-id"
    assert response.metadata.fcu_charged is None


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status,code,charged",
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
def test_failures_preserve_evidence_and_never_retry(mode, status, code, charged, cases):
    metadata = {**cases[0]["response"]["metadata"], "fcu_charged": charged}
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"metadata": metadata, "error": {"code": code, "message": "failure"}},
            headers={"Retry-After": "1", "x-request-id": metadata["request_id"]},
        )

    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(handle))
    error = raised.value
    assert len(calls) == 1
    assert error.status_code == status and error.code == code
    assert error.metadata.fcu_charged == charged
    assert error.request_id == metadata["request_id"]
    assert error.retry_after == "1"
    assert json.loads(error.body)["metadata"] == metadata


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_router_metadata_and_forward_compatible_results(mode, cases):
    body = copy.deepcopy(cases[0]["response"])
    body["result"]["pricing_model"] = "future_engine_model"
    body["result"]["new_diagnostic"] = {"available": True}
    body["metadata"]["fcu_charged"] = 0
    body["metadata"]["budget_period"] = None
    body["future_field"] = [1, 2]
    response = invoke(mode, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    assert response.model_dump(exclude_unset=True) == body
    assert response.metadata.fcu_charged == 0

    router = {
        "metadata": {"request_id": "router-id", "api_version": "v1", "service_version": "test"},
        "error": {"code": "not_found", "message": "unknown route"},
    }
    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(lambda _: httpx.Response(404, json=router)))
    assert raised.value.request_id == "router-id"
    assert raised.value.code == "not_found"
    assert raised.value.metadata.fcu_charged is None


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
@pytest.mark.parametrize("body", [b"not JSON", b"{}", b'{"result":{"price":null}}'])
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
    payload = {
        "metadata": cases[0]["response"]["metadata"],
        "error": {"code": "bad_key", "message": "reflected test-only-key"},
    }
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
        (None, None, "https://api.morphiqlabs.com/v1/price"),
        ("", None, "https://api.morphiqlabs.com/v1/price"),
        ("https://env.example.test/prefix", None, "https://env.example.test/prefix/v1/price"),
        (
            "https://env.example.test",
            "https://explicit.example.test/local",
            "https://explicit.example.test/local/v1/price",
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

from morphiq_sdk import AsyncMorphIQ, MorphIQ, PriceRequest

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
request = PriceRequest(**config["case"]["request"])

async def run_async():
    async with AsyncMorphIQ(**settings) as client:
        await client.price(request)

if config["mode"] == "async":
    asyncio.run(run_async())
else:
    with MorphIQ(**settings) as client:
        client.price(request)
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
        MorphIQ()
    with MorphIQ(allow_unauthenticated=True):
        pass


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_json_escaped_credentials_are_redacted(mode, cases):
    payload = {
        "metadata": cases[0]["response"]["metadata"],
        "error": {"code": "bad_key", "message": "test-only-key"},
    }
    encoded = json.dumps(payload).replace("test-only-key", r"\u0074est-only-key").encode()
    with pytest.raises(APIError) as raised:
        invoke(mode, httpx.MockTransport(lambda _: httpx.Response(401, content=encoded)))
    assert "test-only-key" not in str(raised.value)
    assert json.loads(raised.value.body)["error"]["message"] == "[REDACTED]"


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


def test_request_omission_validation_and_no_numeric_policy():
    request = european_call()
    assert request.to_wire()["pricing_model"] == "auto"
    assert "model_version" not in request.to_wire()
    assert "dividend_schedule" not in request.to_wire()
    explicit = PriceRequest(**{**request.to_wire(), "model_version": None, "dividend_schedule": []})
    assert explicit.to_wire()["model_version"] is None
    assert explicit.to_wire()["dividend_schedule"] == []
    for patch in (
        {"volatility": float("nan")},
        {"spot": True},
        {"spot": "100"},
        {"exercise_style": "unknown"},
        {"dividend_schedule": None},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            PriceRequest(**{**request.to_wire(), **patch})
    # Model-domain checks remain with the service; do not clamp or substitute.
    assert PriceRequest(**{**request.to_wire(), "spot": -1}).spot == -1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("initial", [None, [], [{"ex_time_years": 0.1, "cash_amount": 1.0}]])
def test_edited_dividend_schedule_is_sent_in_order(mode, initial, cases):
    values = american_put().to_wire()
    if initial is not None:
        values["dividend_schedule"] = initial
    request = PriceRequest(**values)
    request.dividend_schedule.append(DividendEvent(ex_time_years=0.25, cash_amount=2.0))
    received = []

    def handle(wire_request):
        received.append(json.loads(wire_request.content))
        return httpx.Response(200, json=cases[1]["response"])

    invoke(mode, httpx.MockTransport(handle), request)
    assert len(received) == 1
    assert received[0]["dividend_schedule"] == [
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
    request.dividend_schedule.extend(events)
    received = []

    def handle(wire_request):
        received.append(wire_request)
        return httpx.Response(200, json={})

    with pytest.raises(ValidationError):
        invoke(mode, httpx.MockTransport(handle), request)
    assert received == []


def test_cleared_explicit_dividend_schedule_remains_explicit():
    request = PriceRequest(
        **american_put().to_wire(),
        dividend_schedule=[DividendEvent(ex_time_years=0.25, cash_amount=2.0)],
    )
    request.dividend_schedule.clear()
    assert request.to_wire()["dividend_schedule"] == []


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
            task = asyncio.create_task(client.price(american_put()))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert transport.calls == 1
        assert transport.closed

    asyncio.run(run())
