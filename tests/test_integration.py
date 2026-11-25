"""Opt-in comparison against the pinned native service, never routine production traffic."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchFailure,
    BatchSuccess,
    MorphIQ,
    OptionsBatchGreeksRequest,
    OptionsBatchImpliedGreeksRequest,
    OptionsBatchImpliedVolatilityRequest,
    OptionsBatchPriceRequest,
    OptionsBatchStandardGreeksRequest,
    OptionsGreeksRequest,
    OptionsImpliedGreeksRequest,
    OptionsImpliedVolatilityRequest,
    OptionsPriceRequest,
    OptionsStandardGreeksRequest,
    SeriesIdentifyRegimeRequest,
)

ENDPOINT = os.environ.get("MORPHIQ_TEST_API_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ENDPOINT, reason="controlled API not set"),
]
PROVENANCE = json.loads((Path(__file__).parents[1] / "contracts/provenance.json").read_text())
SINGLE = [
    ("price", OptionsPriceRequest, "pricing"),
    ("greeks", OptionsGreeksRequest, "greeks"),
    ("standard_greeks", OptionsStandardGreeksRequest, "standard_greeks"),
    ("implied_volatility", OptionsImpliedVolatilityRequest, "implied_volatility"),
    ("implied_greeks", OptionsImpliedGreeksRequest, "implied_greeks"),
]
BATCH = {
    "/v1/options:batch-price": ("batch_price", "price_workflow", OptionsBatchPriceRequest),
    "/v1/options:batch-greeks": ("batch_greeks", "greeks_workflow", OptionsBatchGreeksRequest),
    "/v1/options:batch-implied-volatility": (
        "batch_implied_volatility",
        "implied_volatility_workflow",
        OptionsBatchImpliedVolatilityRequest,
    ),
    "/v1/options:batch-implied-greeks": (
        "batch_implied_greeks",
        "implied_greeks_workflow",
        OptionsBatchImpliedGreeksRequest,
    ),
}


def _fixture(name):
    path = Path(__file__).parent / f"fixtures/{name}.json"
    return json.loads(path.read_text())["cases"]


@pytest.fixture(scope="module", autouse=True)
def served_contract_is_the_pin():
    served = httpx.get(f"{ENDPOINT}/openapi.json").content
    assert hashlib.sha256(served).hexdigest() == PROVENANCE["sha256"]


@pytest.mark.parametrize("method,model,fixture", SINGLE)
def test_native_option_operations_sync_async_and_validation(method, model, fixture):
    async def run_async(request):
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await getattr(client.options, method)(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        call = getattr(client.options, method)
        for case in _fixture(fixture):
            request = model.model_validate(case["request"])
            sync = call(request)
            asynchronous = asyncio.run(run_async(request))
            raw = httpx.post(f"{ENDPOINT}{case['path']}", json=request.to_wire()).json()
            assert (
                sync.result.model_dump(exclude_unset=True)
                == asynchronous.result.model_dump(exclude_unset=True)
                == raw["result"]
                == case["response"]["result"]
            )
            assert sync.metadata.contract.sha256 == PROVENANCE["sha256"]
            assert sync.metadata.engines and sync.metadata.billing is None
            assert sync.metadata.charged_cu is None
        invalid = model.model_validate(
            {**case["request"], "market": {**case["request"]["market"], "spot": -1.0}}
        )
        with pytest.raises(APIError) as error:
            call(invalid)
        assert error.value.status_code == 422 and error.value.request_id
        assert error.value.code == "invalid_field" and error.value.field == "market.spot"
        assert error.value.problem is not None and error.value.metadata is not None


def test_native_implied_volatility_refusals_are_problems():
    case = _fixture("implied_volatility")[1]
    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        for premium in (-1.0, 1000.0):
            request = OptionsImpliedVolatilityRequest.model_validate(
                {**case["request"], "market_price": premium}
            )
            with pytest.raises(APIError) as error:
                client.options.implied_volatility(request)
            assert error.value.status_code == 422 and error.value.request_id
            assert error.value.code and error.value.detail and error.value.title


def test_native_regime_sync_async_and_wire_response(regime_cases):
    request = SeriesIdentifyRegimeRequest.model_validate(regime_cases[0]["request"])

    async def run_async():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await client.series.identify_regime(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = client.series.identify_regime(request)
    asynchronous = asyncio.run(run_async())
    native = httpx.post(f"{ENDPOINT}/v1/series:identify-regime", json=request.to_wire())
    native.raise_for_status()
    raw = native.json()
    # Timing differs per request; every other member is deterministic.
    for response in (sync, asynchronous):
        result = response.result.model_dump(exclude_unset=True)
        assert set(result["timing"]) == set(raw["result"]["timing"])
        result.pop("timing")
        assert result == {k: v for k, v in raw["result"].items() if k != "timing"}
        assert response.metadata.contract.sha256 == PROVENANCE["sha256"]
        assert (
            response.result.input.consumed_price_range.model_dump()
            == (raw["result"]["input"]["consumed_price_range"])
        )
        assert "as_of" not in response.result.input.model_fields_set
    dated = SeriesIdentifyRegimeRequest(prices=request.prices, as_of="2026-11-20T21:00:00Z")
    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        assert client.series.identify_regime(dated).result.input.as_of == "2026-11-20T21:00:00Z"


@pytest.mark.parametrize("index", range(4))
def test_native_batches_preserve_order_errors_and_metadata(batch_cases, index):
    case = batch_cases[index]
    method, _, model = BATCH[case["path"]]
    request = model.model_validate(case["request"])

    async def run():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            return await getattr(client.options, method)(request)

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = getattr(client.options, method)(request)
    asynchronous = asyncio.run(run())
    raw = httpx.post(f"{ENDPOINT}{case['path']}", json=request.to_wire()).json()
    assert [item.model_dump(exclude_unset=True) for item in sync.results] == raw["results"]
    assert [item.model_dump(exclude_unset=True) for item in asynchronous.results] == raw["results"]
    assert raw["results"] == case["response"]["results"]
    expected = [BatchSuccess, BatchFailure, BatchSuccess] if index < 2 else [BatchSuccess] * 3
    assert all(isinstance(item, kind) for item, kind in zip(sync.results, expected, strict=True))
    assert sync.metadata.charged_cu is None


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("max_concurrency", [1, 2])
def test_native_workflows_keep_chunk_metadata_and_order(batch_cases, index, max_concurrency):
    case = batch_cases[index]
    _, factory, model = BATCH[case["path"]]
    requests = model.model_validate(case["request"]).items * 2

    async def run():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            workflow = getattr(client.options, factory)(
                requests, chunk_size=3, max_concurrency=max_concurrency
            )
            await workflow.run()
            return workflow

    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        sync = getattr(client.options, factory)(requests, chunk_size=3)
        sync.run()
    for workflow in (sync, asyncio.run(run())):
        assert workflow.state == "completed"
        assert len(workflow.attempts) == 2
        assert workflow.unknown_charge_count == 2
        assert workflow.total_charged_cu is None
        assert workflow.reported_charged_cu == 0
        assert [(a.start, a.stop) for a in workflow.attempts] == [(0, 3), (3, 6)]
        assert workflow.attempts[0].request_id != workflow.attempts[1].request_id
        for attempt in workflow.attempts:
            assert [item.model_dump(exclude_unset=True) for item in attempt.response.results] == (
                case["response"]["results"]
            )


def test_native_catalog_standard_greeks_and_model_support(cases, standard_greeks_cases):
    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        catalog = client.models.list()
        assert catalog.model_dump(exclude_unset=True) == httpx.get(f"{ENDPOINT}/v1/models").json()
        for descriptor in catalog.models:
            assert "options.price" in descriptor.operations
        request = OptionsStandardGreeksRequest.model_validate(standard_greeks_cases[0]["request"])
        response = client.options.standard_greeks(request)
        batch = client.options.batch_standard_greeks(
            OptionsBatchStandardGreeksRequest(items=[request] * 100)
        )
        assert len(batch.results) == 100
        assert all(
            item.result.model_dump(exclude_unset=True)
            == response.result.model_dump(exclude_unset=True)
            for item in batch.results
        )
        workflow = client.options.standard_greeks_workflow([request] * 3, chunk_size=2)
        workflow.run()
        assert [(a.start, a.stop) for a in workflow.attempts] == [(0, 2), (2, 3)]
        american = cases[1]["request"]
        for selector in ["black_scholes_merton_qdfp", "black_scholes_merton_fd"]:
            values = {**american, "model": {"id": selector}}
            price = client.options.price(OptionsPriceRequest.model_validate(values))
            assert price.result.model.id == selector
            assert price.result.model.version == next(
                d.model_version for d in catalog.models if d.id == selector
            )
            inverse = {k: v for k, v in values.items() if k != "volatility"}
            iv = client.options.implied_volatility(
                OptionsImpliedVolatilityRequest.model_validate(
                    {**inverse, "market_price": price.result.price}
                )
            )
            assert iv.result.implied_volatility == pytest.approx(0.2, abs=1e-6)
            for method, model, body in [
                ("greeks", OptionsGreeksRequest, values),
                ("standard_greeks", OptionsStandardGreeksRequest, values),
                (
                    "implied_greeks",
                    OptionsImpliedGreeksRequest,
                    {**inverse, "market_price": price.result.price},
                ),
            ]:
                with pytest.raises(APIError) as error:
                    getattr(client.options, method)(model.model_validate(body))
                assert error.value.status_code == 422
                assert error.value.code == "unsupported_operation"
            with pytest.raises(APIError) as error:
                client.options.batch_price(
                    OptionsBatchPriceRequest(items=[OptionsPriceRequest.model_validate(values)])
                )
            assert error.value.status_code == 422 and error.value.field == "items[0]"

    async def run():
        async with AsyncMorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
            assert (await client.models.list()).model_dump() == catalog.model_dump()
            assert (
                await client.options.standard_greeks(request)
            ).result.model_dump() == response.result.model_dump()
            workflow = client.options.standard_greeks_workflow(
                [request] * 3, chunk_size=2, max_concurrency=2
            )
            await workflow.run()
            assert workflow.state == "completed" and len(workflow.attempts) == 2

    asyncio.run(run())


def test_native_service_refuses_retired_selectors(cases):
    # The SDK refuses these locally; the served contract refuses them as well.
    for selector in ["bjerksund_stensland_2002", "qd_fixed_point", "cash_dividend_american"]:
        body = {**cases[1]["request"], "model": {"id": selector}}
        response = httpx.post(f"{ENDPOINT}/v1/options:price", json=body)
        assert response.status_code == 422
        problem = response.json()
        assert problem["code"] == "invalid_request" and problem["field"] == "model.id"


def test_native_rate_card_and_quote_when_policy_is_published(cases):
    with MorphIQ(base_url=ENDPOINT, allow_unauthenticated=True) as client:
        try:
            card = client.rate_card.get()
        except APIError as error:
            if error.code == "policy_unavailable":
                pytest.skip("this service has no signed policy publication (open admission)")
            raise
        assert card.schedule.rates
        request = OptionsPriceRequest.model_validate(cases[0]["request"])
        quote = client.rate_card.quote(request)
        assert quote.quote.total_cu >= 0
        assert quote.metadata.billing is not None
