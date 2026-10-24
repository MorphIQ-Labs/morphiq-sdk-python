"""Opt-in comparison against the pinned native service, never routine production traffic."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from morphiq_sdk import (
    AnalyticsRequest,
    APIError,
    AsyncMorphIQ,
    GreeksRequest,
    ImpliedVolatilityRequest,
    MorphIQ,
    PriceRequest,
)

ENDPOINT = os.environ.get("MORPHIQ_TEST_API_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ENDPOINT, reason="controlled API not set"),
]


def test_native_api_sync_async_and_validation(cases):
    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )

    async def run_async(request):
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.price(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        for case in cases:
            request = PriceRequest(**case["request"])
            sync = client.price(request)
            asynchronous = asyncio.run(run_async(request))
            raw = httpx.post(f"{ENDPOINT}/v1/price", json=request.to_wire()).json()
            assert sync.result.model_dump() == asynchronous.result.model_dump() == raw["result"]
            assert sync.result.price == pytest.approx(
                case["response"]["result"]["price"], abs=1e-12
            )
            assert sync.metadata.fcu_charged is None
        invalid = PriceRequest(**{**cases[0]["request"], "spot": -1})
        with pytest.raises(APIError) as raised:
            client.price(invalid)
        assert raised.value.status_code == 422
        assert raised.value.request_id


def test_native_greeks_sync_async_and_validation(greeks_cases):
    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )

    async def run_async(request):
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.greeks(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        for case in greeks_cases:
            request = GreeksRequest(**case["request"])
            sync = client.greeks(request)
            asynchronous = asyncio.run(run_async(request))
            raw = httpx.post(f"{ENDPOINT}/v1/greeks", json=request.to_wire()).json()
            assert sync.result.model_dump() == asynchronous.result.model_dump() == raw["result"]
            assert sync.result.model_dump() == case["response"]["result"]
            assert sync.metadata.fcu_charged is None
        request = GreeksRequest(**{**greeks_cases[0]["request"], "spot": -1})
        with pytest.raises(APIError) as error:
            client.greeks(request)
        assert error.value.status_code == 422 and error.value.request_id


def test_native_analytics_sync_async_and_validation(analytics_cases):
    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )

    async def run_async(request):
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.analytics(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        for case in analytics_cases:
            request = AnalyticsRequest(**case["request"])
            sync = client.analytics(request)
            asynchronous = asyncio.run(run_async(request))
            raw = httpx.post(f"{ENDPOINT}/v1/analytics", json=request.to_wire()).json()
            assert (
                sync.result.model_dump(exclude_unset=True)
                == asynchronous.result.model_dump(exclude_unset=True)
                == raw["result"]
            )
            assert sync.result.model_dump(exclude_unset=True) == case["response"]["result"]
            assert sync.metadata.fcu_charged is None
        request = AnalyticsRequest(**{**analytics_cases[0]["request"], "spot": -1})
        with pytest.raises(APIError) as error:
            client.analytics(request)
        assert error.value.status_code == 422 and error.value.request_id


def test_native_implied_volatility_sync_async_and_validation(iv_cases):
    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )

    async def run_async(request):
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.implied_volatility(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        for case in iv_cases:
            request = ImpliedVolatilityRequest(**case["request"])
            sync = client.implied_volatility(request)
            asynchronous = asyncio.run(run_async(request))
            raw = httpx.post(f"{ENDPOINT}/v1/implied-volatility", json=request.to_wire()).json()
            assert sync.result.model_dump() == asynchronous.result.model_dump() == raw["result"]
            assert sync.result.model_dump() == case["response"]["result"]
            assert sync.result.implied_volatility == pytest.approx(0.2, abs=1e-10)
            assert sync.result.residual_basis in ("forward_normalised_price", "option_price")
            assert sync.metadata.fcu_charged is None
        for premium, status in [(-1, 422), (1000, 500)]:
            request = ImpliedVolatilityRequest(
                **{**iv_cases[1]["request"], "market_price": premium}
            )
            with pytest.raises(APIError) as error:
                client.implied_volatility(request)
            assert error.value.status_code == status and error.value.request_id
            if premium == 1000:
                # The pinned service reports an unbracketable American solve as an engine error.
                assert error.value.code == "pricing_failed"


def test_native_regime_sync_async_and_wire_response(regime_cases):
    from morphiq_sdk import RegimeRequest

    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )
    request = RegimeRequest(**regime_cases[0]["request"])

    async def run_async():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.regime(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = client.regime(request)
    asynchronous = asyncio.run(run_async())
    native = httpx.post(f"{ENDPOINT}/v1/regime", json=request.to_wire())
    native.raise_for_status()
    raw = native.json()
    assert sync.result.model_dump(exclude_unset=True) == raw["result"]
    assert asynchronous.result.model_dump(exclude_unset=True) == raw["result"]
    for response in (sync, asynchronous):
        assert (
            response.metadata.provenance.model_dump(exclude_unset=True)
            == raw["metadata"]["provenance"]
        )
        assert (
            response.metadata.consumed_price_range.model_dump()
            == raw["metadata"]["consumed_price_range"]
        )


@pytest.mark.parametrize("index", range(4))
def test_native_batches_preserve_order_errors_and_metadata(batch_cases, index):
    from test_batch import OPERATIONS

    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )
    method, cls, _, _ = OPERATIONS[index]
    case = batch_cases[index]
    request = cls(**case["request"])

    async def run():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await getattr(client, method)(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = getattr(client, method)(request)
    asynchronous = asyncio.run(run())
    raw = httpx.post(f"{ENDPOINT}{case['path']}", json=request.to_wire()).json()
    assert [item.model_dump(exclude_unset=True) for item in sync.results] == raw["results"]
    assert [item.model_dump(exclude_unset=True) for item in asynchronous.results] == raw["results"]
    assert raw["results"] == case["response"]["results"]
    assert [item.status for item in sync.results] == ["success", "error", "success"]
    assert sync.metadata.fcu_charged is None


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("max_concurrency", [1, 2])
def test_native_workflows_keep_chunk_metadata_and_order(batch_cases, index, max_concurrency):
    from test_workflows import OPERATIONS

    provenance = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
    assert (
        hashlib.sha256(httpx.get(f"{ENDPOINT}/openapi.json").content).hexdigest()
        == provenance["sha256"]
    )
    factory, cls = OPERATIONS[index]
    case = batch_cases[index]
    requests = cls(**case["request"]).requests * 2

    async def run():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            workflow = getattr(client, factory)(
                requests, chunk_size=3, max_concurrency=max_concurrency
            )
            await workflow.run()
            return workflow

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = getattr(client, factory)(requests, chunk_size=3)
        sync.run()
    for workflow in (sync, asyncio.run(run())):
        assert workflow.state == "completed"
        assert len(workflow.attempts) == 2
        assert workflow.unknown_charge_count == 2
        assert workflow.total_fcu_charged is None
        assert workflow.reported_fcu_charged == 0
        assert [(a.start, a.stop) for a in workflow.attempts] == [(0, 3), (3, 6)]
        assert workflow.attempts[0].request_id != workflow.attempts[1].request_id
        for attempt in workflow.attempts:
            assert [item.model_dump(exclude_unset=True) for item in attempt.response.results] == (
                case["response"]["results"]
            )
