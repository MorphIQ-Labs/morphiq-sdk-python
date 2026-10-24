"""Opt-in comparison against the pinned native service, never routine production traffic."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from morphiq_sdk import APIError, AsyncMorphIQ, GreeksRequest, MorphIQ, PriceRequest

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
