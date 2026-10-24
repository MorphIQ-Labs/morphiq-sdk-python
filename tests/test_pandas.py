import asyncio
import copy
import subprocess
import sys

import httpx
import pandas as pd
import pytest

from morphiq_sdk import (
    AsyncMorphIQ,
    BatchAnalyticsResponse,
    BatchGreeksResponse,
    BatchImpliedVolatilityResponse,
    BatchPriceRequest,
    BatchPriceResponse,
    MorphIQ,
    RateLimitError,
    RequestTimeout,
    ResponseError,
)
from morphiq_sdk.pandas import batch_to_frames, workflow_to_frames

RESPONSE_TYPES = [
    BatchPriceResponse,
    BatchGreeksResponse,
    BatchImpliedVolatilityResponse,
    BatchAnalyticsResponse,
]


@pytest.mark.parametrize("operation", range(4))
@pytest.mark.parametrize("charge", [None, 0, 2**53 + 1, 2**100])
def test_batch_tables_preserve_lossless_rows_and_one_exact_charge(operation, charge, batch_cases):
    body = copy.deepcopy(batch_cases[operation]["response"])
    body["metadata"].update(fcu_charged=charge, fcu_quoted=999999)
    body["future_root"] = {"version": 2**100}
    # Future keys, even dotted names, must survive without colliding with typed columns.
    body["results"][0]["result"].update({"future": {"value": 2**100}, "greeks.delta": 123})
    response = RESPONSE_TYPES[operation].model_validate(body)
    frames = batch_to_frames(response, identifiers=[2**100, None, 2**100])
    records = frames.results.to_dict(orient="records")
    assert [r["outcome"] for r in records] == body["results"]
    assert [r["identifier"] for r in records] == [2**100, None, 2**100]
    assert [r["status"] for r in records] == ["success", "error", "success"]
    assert [r["index"] for r in records] == [0, 1, 2]
    assert [r["item_index"] for r in records] == [0, 1, 2]
    assert [r["request_index"] for r in records] == [0, 0, 0]
    assert not any("fcu" in name or "units_charged" in name for name in frames.results.columns)
    receipt = frames.requests.to_dict(orient="records")[0]
    assert receipt["metadata"] == body["metadata"]
    assert receipt["fcu_charged"] == charge
    assert receipt["start"] == 0 and receipt["stop"] == 3
    assert frames.reported_fcu_charged == (0 if charge is None else charge)
    assert frames.unknown_charge_count == (1 if charge is None else 0)
    assert frames.total_fcu_charged == charge
    # Reconstruct the original batch using the lossless payload and receipt columns.
    restored = RESPONSE_TYPES[operation].model_validate(
        {
            **receipt["response_extras"],
            "metadata": receipt["metadata"],
            "results": [r["outcome"] for r in records],
        }
    )
    assert restored.model_dump(exclude_unset=True) == body
    if operation != 2:
        assert frames.results["result.price"].dtype == pd.Float64Dtype()
        assert frames.results.loc[0, "result.price"] == body["results"][0]["result"]["price"]
        assert pd.isna(frames.results.loc[1, "result.price"])
    # Nested view edits never mutate the original evidence.
    receipt["metadata"]["engines"].clear()
    records[0]["outcome"]["result"]["future"]["value"] = 0
    assert response.metadata.engines
    assert response.results[0].result.model_extra["future"]["value"] == 2**100


def test_integer_and_boolean_diagnostics_and_float_units_are_unchanged(batch_cases):
    body = copy.deepcopy(batch_cases[2]["response"])
    body["results"][0]["result"].update(iterations=2**100, used_fallback=False, residual=-0.0)
    frames = batch_to_frames(BatchImpliedVolatilityResponse.model_validate(body))
    assert frames.results["result.iterations"].dtype == object
    assert frames.results.loc[0, "result.iterations"] == 2**100
    assert frames.results["result.used_fallback"].dtype == pd.BooleanDtype()
    assert not frames.results.loc[0, "result.used_fallback"]
    assert pd.isna(frames.results.loc[1, "result.used_fallback"])
    assert frames.results.loc[0, "result.residual"].hex() == (-0.0).hex()
    assert (
        frames.results.loc[0, "result.implied_volatility"]
        == (body["results"][0]["result"]["implied_volatility"])
    )
    for case, cls in [
        (batch_cases[1], BatchGreeksResponse),
        (batch_cases[3], BatchAnalyticsResponse),
    ]:
        result = cls.model_validate(case["response"])
        frame = batch_to_frames(result).results
        for name, value in result.results[0].result.greeks.model_dump().items():
            assert frame.loc[0, f"result.greeks.{name}"] == value


@pytest.mark.parametrize("values", [["a"], "abc", [1, 2.0, 3], [1, True, 3]])
def test_identifier_validation_does_not_infer_or_coerce(values, batch_cases):
    response = BatchPriceResponse.model_validate(batch_cases[0]["response"])
    with pytest.raises((TypeError, ValueError)):
        batch_to_frames(response, identifiers=values)


def test_reordered_response_is_rejected(batch_cases):
    response = BatchPriceResponse.model_validate(batch_cases[0]["response"])
    response.results.reverse()
    with pytest.raises(ValueError, match="indices"):
        batch_to_frames(response)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", [None, "429", "timeout", "invalid", "interrupt"])
def test_workflow_tables_preserve_all_inputs_partial_progress_and_charges(
    mode, failure, batch_cases
):
    case = batch_cases[0]
    requests = BatchPriceRequest(**case["request"]).requests * 3
    calls = []

    def handle(request):
        calls.append(request)
        body = copy.deepcopy(case["response"])
        body["metadata"]["fcu_charged"] = 2**100 if len(calls) == 1 else None
        if len(calls) == 2 and failure:
            if failure == "429":
                body["metadata"]["fcu_charged"] = 7
                return httpx.Response(
                    429,
                    json={
                        "metadata": body["metadata"],
                        "error": {"code": "limited", "message": "synthetic"},
                    },
                    headers={"Retry-After": "30"},
                )
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic")
            if failure == "interrupt":
                raise KeyboardInterrupt()
            body["results"].pop()
            body["metadata"]["fcu_charged"] = 11
        return httpx.Response(200, json=body)

    def check(workflow):
        frames = workflow_to_frames(workflow, identifiers=[f"contract-{i}" for i in range(9)])
        assert frames.results["index"].tolist() == list(range(9))
        assert frames.results["identifier"].tolist() == [f"contract-{i}" for i in range(9)]
        assert frames.results["status"].tolist()[:3] == ["success", "error", "success"]
        assert len(frames.results) == 9 and len(frames.requests) == (2 if failure else 3)
        assert frames.reported_fcu_charged == workflow.reported_fcu_charged
        assert frames.unknown_charge_count == workflow.unknown_charge_count
        assert frames.total_fcu_charged == workflow.total_fcu_charged
        if failure:
            expected = "interrupted" if failure == "interrupt" else "request_error"
            assert frames.results["status"].tolist()[3:] == [expected] * 3 + ["unattempted"] * 3
            assert frames.results["request_index"].tolist() == [0] * 3 + [1] * 3 + [None] * 3
            assert frames.requests.loc[1, "status"] == expected
            assert (
                frames.requests.loc[1, "error"]["type"] == type(workflow.attempts[1].error).__name__
            )
            if failure == "429":
                assert frames.requests.loc[1, "error"]["retry_after"] == "30"
                assert frames.requests.loc[1, "fcu_charged"] == 7
        else:
            assert frames.results["status"].tolist() == ["success", "error", "success"] * 3
        # Editing a view does not alter the captured summary or workflow evidence.
        frames.requests.loc[0, "fcu_charged"] = 0
        assert frames.reported_fcu_charged >= 2**100
        assert workflow.reported_fcu_charged >= 2**100

    errors = (RateLimitError, RequestTimeout, ResponseError, KeyboardInterrupt)
    if mode == "sync":
        with MorphIQ(api_key="frame-test", transport=httpx.MockTransport(handle)) as client:
            workflow = client.price_workflow(requests, chunk_size=3)
            try:
                workflow.run()
            except errors:
                assert failure
            check(workflow)
    else:

        async def run():
            async with AsyncMorphIQ(
                api_key="frame-test", transport=httpx.MockTransport(handle)
            ) as client:
                workflow = client.price_workflow(requests, chunk_size=3)
                try:
                    await workflow.run()
                except errors:
                    assert failure
                check(workflow)

        asyncio.run(run())
    assert len(calls) == (2 if failure else 3)  # Conversion sends nothing.


def test_ready_and_empty_workflows_have_stable_columns_without_fake_receipts(batch_cases):
    with MorphIQ(api_key="frame-test") as client:
        workflow = client.price_workflow(
            BatchPriceRequest(**batch_cases[0]["request"]).requests, chunk_size=2
        )
        frames = workflow_to_frames(workflow)
        assert frames.results["status"].tolist() == ["unattempted"] * 3
        assert frames.requests.empty
        assert "fcu_charged" in frames.requests.columns
        assert frames.reported_fcu_charged == frames.unknown_charge_count == 0
        assert frames.total_fcu_charged is None
        with pytest.raises(ValueError):
            workflow_to_frames(workflow, identifiers=["only-one"])
        empty = client.price_workflow([], chunk_size=2)
        empty.run()
        frames = workflow_to_frames(empty)
        assert frames.results.empty and frames.requests.empty
        assert frames.total_fcu_charged == 0
        assert frames.results.columns.tolist() == [
            "index",
            "identifier",
            "request_index",
            "item_index",
            "status",
            "outcome",
        ]


def test_running_async_workflow_rejected_cancelled_workflow_is_convertible(batch_cases):
    async def run():
        entered = asyncio.Event()

        async def handle(request):
            entered.set()
            await asyncio.Future()

        async with AsyncMorphIQ(
            api_key="frame-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = client.price_workflow(
                BatchPriceRequest(**batch_cases[0]["request"]).requests, chunk_size=2
            )
            task = asyncio.create_task(workflow.run())
            await entered.wait()
            with pytest.raises(ValueError, match="complete or stop"):
                workflow_to_frames(workflow)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            frames = workflow_to_frames(workflow)
            assert frames.results["status"].tolist() == [
                "interrupted",
                "interrupted",
                "unattempted",
            ]
            assert frames.unknown_charge_count == 1
            assert frames.requests.loc[0, "error"] == {"type": "CancelledError"}

    asyncio.run(run())


def test_core_and_adapter_import_do_not_load_pandas():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import morphiq_sdk; import morphiq_sdk.pandas; "
            "assert 'pandas' not in sys.modules; assert 'yfinance' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not result.stdout and not result.stderr


def test_absent_and_null_fields_remain_distinct_in_lossless_payloads(analytics_cases):
    case = analytics_cases[0]
    absent = copy.deepcopy(case["response"]["result"])
    absent.pop("implied_volatility", None)
    explicit_null = {**absent, "implied_volatility": None}
    metadata = copy.deepcopy(case["response"]["metadata"])
    metadata.pop("fcu_charged", None)
    response = BatchAnalyticsResponse.model_validate(
        {
            "metadata": metadata,
            "results": [
                {"index": 0, "status": "success", "result": absent},
                {"index": 1, "status": "success", "result": explicit_null},
            ],
        }
    )
    frames = batch_to_frames(response)
    outcomes = frames.results["outcome"].tolist()
    assert "implied_volatility" not in outcomes[0]["result"]
    assert outcomes[1]["result"]["implied_volatility"] is None
    assert frames.requests.loc[0, "fcu_charged"] is None
    assert "fcu_charged" not in frames.requests.loc[0, "metadata"]
    assert frames.unknown_charge_count == 1 and frames.total_fcu_charged is None
