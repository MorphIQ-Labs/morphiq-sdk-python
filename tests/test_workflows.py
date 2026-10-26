import asyncio
import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchAnalyticsRequest,
    BatchGreeksRequest,
    BatchImpliedVolatilityRequest,
    BatchPriceRequest,
    MorphIQ,
    RateLimitError,
    RequestTimeout,
    ResponseError,
)

OPERATIONS = [
    ("price_workflow", BatchPriceRequest),
    ("greeks_workflow", BatchGreeksRequest),
    ("implied_volatility_workflow", BatchImpliedVolatilityRequest),
    ("analytics_workflow", BatchAnalyticsRequest),
]


def execute(mode, handler, factory, requests, check, chunk_size=3):
    if mode == "sync":
        with MorphIQ(api_key="workflow-test", transport=httpx.MockTransport(handler)) as client:
            workflow = getattr(client, factory)(requests, chunk_size=chunk_size)
            check(workflow, workflow.run)
    else:

        async def run():
            async with AsyncMorphIQ(
                api_key="workflow-test", transport=httpx.MockTransport(handler)
            ) as client:
                workflow = getattr(client, factory)(requests, chunk_size=chunk_size)
                # Test expectations run synchronously, but all HTTP calls are awaited.
                return workflow, await check(workflow, workflow.run)

        asyncio.run(run())


def checks_for(mode, before, after, error=None):
    if mode == "sync":

        def check(workflow, run):
            before(workflow)
            if error:
                with pytest.raises(error) as raised:
                    run()
                assert workflow.attempts[-1].error is raised.value
            else:
                run()
            after(workflow)
            with pytest.raises(RuntimeError, match="only once"):
                run()

        return check

    async def check(workflow, run):
        before(workflow)
        if error:
            with pytest.raises(error) as raised:
                await run()
            assert workflow.attempts[-1].error is raised.value
        else:
            await run()
        after(workflow)
        with pytest.raises(RuntimeError, match="only once"):
            await run()

    return check


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("operation", range(4))
def test_sequential_chunks_keep_outcomes_indices_wire_and_exact_charge(
    mode, operation, batch_cases
):
    factory, request_type = OPERATIONS[operation]
    case = batch_cases[operation]
    requests = (
        request_type(**case["request"]).requests * 2 + request_type(**case["request"]).requests[:1]
    )
    calls = []
    charges = [2**53 + 1, 0, 9]

    def handle(request):
        body = json.loads(request.content)
        assert request.url.path == case["path"]
        start = len(calls) * 3
        assert body == {"requests": [r.to_wire() for r in requests[start : start + 3]]}
        response = copy.deepcopy(case["response"])
        response["results"] = response["results"][: len(body["requests"])]
        response["metadata"]["fcu_charged"] = charges[len(calls)]
        response["metadata"]["fcu_quoted"] = 99999
        calls.append(body)
        return httpx.Response(200, json=response)

    def before(workflow):
        assert not calls and workflow.state == "ready"
        assert workflow.planned_chunk_count == 3
        assert workflow.unattempted_ranges == ((0, 3), (3, 6), (6, 7))
        assert workflow.total_fcu_charged is None

    def after(workflow):
        assert len(calls) == 3 and workflow.state == "completed"
        assert workflow.unattempted_ranges == ()
        assert workflow.reported_fcu_charged == 2**53 + 10
        assert workflow.total_fcu_charged == 2**53 + 10
        assert workflow.unknown_charge_count == 0
        outcomes = [
            (attempt.start + item.index, item.status)
            for attempt in workflow.attempts
            for item in attempt.response.results
        ]
        assert outcomes == [
            (0, "success"),
            (1, "error"),
            (2, "success"),
            (3, "success"),
            (4, "error"),
            (5, "success"),
            (6, "success"),
        ]
        for attempt in workflow.attempts:
            assert attempt.finished and attempt.error is None
            assert (
                json.loads(attempt.response.raw_body)["metadata"]["fcu_charged"]
                == attempt.fcu_charged
            )
        # Accounting is captured once, not recomputed from mutable response models.
        workflow.attempts[0].response.metadata.fcu_charged = 0
        assert workflow.total_fcu_charged == 2**53 + 10

    execute(mode, handle, factory, requests, checks_for(mode, before, after))


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("failure", ["429", "gateway", "api", "timeout", "malformed", "interrupt"])
def test_stop_retains_progress_failed_charge_and_never_replays(mode, failure, batch_cases):
    case = batch_cases[0]
    requests = BatchPriceRequest(**case["request"]).requests * 3
    calls = []
    failure_charge = {"429": 0, "api": 7, "malformed": 11}.get(failure)
    expected = {
        "429": RateLimitError,
        "gateway": RateLimitError,
        "api": APIError,
        "timeout": RequestTimeout,
        "malformed": ResponseError,
        "interrupt": KeyboardInterrupt,
    }[failure]

    def handle(request):
        calls.append(request)
        response = copy.deepcopy(case["response"])
        response["metadata"]["fcu_charged"] = 3 if len(calls) == 1 else failure_charge
        if len(calls) == 2:
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic")
            if failure == "interrupt":
                raise KeyboardInterrupt()
            if failure == "gateway":
                return httpx.Response(429, text="busy", headers={"Retry-After": "30"})
            if failure == "malformed":
                response["results"].reverse()
            else:
                response = {
                    "metadata": response["metadata"],
                    "error": {"code": "synthetic", "message": "synthetic failure"},
                }
                return httpx.Response(
                    429 if failure == "429" else 500, json=response, headers={"Retry-After": "30"}
                )
        return httpx.Response(200, json=response)

    def after(workflow):
        assert len(calls) == 2 and workflow.state == "stopped"
        assert len(workflow.attempts) == 2
        assert workflow.attempts[0].response is not None
        failed = workflow.attempts[1]
        assert failed.response is None and failed.finished
        assert (failed.start, failed.stop) == (3, 6)
        assert failed.fcu_charged == failure_charge
        assert workflow.unattempted_ranges == ((6, 9),)
        assert workflow.reported_fcu_charged == 3 + (failure_charge or 0)
        assert workflow.unknown_charge_count == (1 if failure_charge is None else 0)
        assert workflow.total_fcu_charged is None
        if failure in ("429", "gateway"):
            assert failed.error.retry_delay() == 30

    execute(
        mode, handle, "price_workflow", requests, checks_for(mode, lambda w: None, after, expected)
    )


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_missing_charge_is_not_zero(mode, batch_cases):
    case = batch_cases[0]
    requests = BatchPriceRequest(**case["request"]).requests * 2
    calls = []

    def handle(request):
        response = copy.deepcopy(case["response"])
        response["metadata"]["fcu_charged"] = None if not calls else 5
        calls.append(request)
        return httpx.Response(200, json=response)

    def after(workflow):
        assert workflow.state == "completed"
        assert workflow.reported_fcu_charged == 5
        assert workflow.unknown_charge_count == 1
        assert workflow.total_fcu_charged is None

    execute(mode, handle, "price_workflow", requests, checks_for(mode, lambda w: None, after))


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_empty_workflow_has_zero_requests_and_zero_cost(mode):
    def handle(request):
        pytest.fail("empty workflow must not send HTTP")

    def after(workflow):
        assert workflow.state == "completed" and not workflow.attempts
        assert workflow.total_fcu_charged == 0
        assert workflow.planned_chunk_count == 0

    execute(mode, handle, "price_workflow", [], checks_for(mode, lambda w: None, after))


@pytest.mark.parametrize("operation", range(4))
def test_validate_entire_plan_before_network_and_snapshot_inputs(operation, batch_cases):
    factory, request_type = OPERATIONS[operation]
    requests = request_type(**batch_cases[operation]["request"]).requests
    with MorphIQ(api_key="workflow-test") as client:
        for size in [0, -1, True, 1.5, 101]:
            with pytest.raises(ValueError):
                getattr(client, factory)(requests, chunk_size=size)
        assert getattr(client, factory)(requests, chunk_size=100).planned_chunk_count == 1
        # Invalid later chunk fails preparation; no earlier request has been made.
        requests[-1].dividend_schedule.append({"ex_time_years": float("nan"), "cash_amount": 1})
        with pytest.raises(ValidationError):
            getattr(client, factory)(requests, chunk_size=1)


def test_input_changes_do_not_change_prepared_requests(batch_cases):
    case = batch_cases[0]
    requests = BatchPriceRequest(**case["request"]).requests
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=case["response"])

    with MorphIQ(api_key="workflow-test", transport=httpx.MockTransport(handle)) as client:
        workflow = client.price_workflow(requests, chunk_size=3)
        requests[0].dividend_schedule.append({"ex_time_years": 0.5, "cash_amount": 1.0})
        requests.clear()
        workflow.run()
    assert calls == [case["request"]]


def test_async_cancellation_retains_inflight_unknown_and_prevents_concurrent_run(batch_cases):
    case = batch_cases[0]

    async def run():
        entered = asyncio.Event()
        calls = []

        async def handle(request):
            calls.append(request)
            if len(calls) == 1:
                response = copy.deepcopy(case["response"])
                response["metadata"]["fcu_charged"] = 5
                return httpx.Response(200, json=response)
            entered.set()
            await asyncio.Future()

        async with AsyncMorphIQ(
            api_key="workflow-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = client.price_workflow(
                BatchPriceRequest(**case["request"]).requests * 3, chunk_size=3
            )
            task = asyncio.create_task(workflow.run())
            await entered.wait()
            assert workflow.state == "running"
            assert not workflow.attempts[1].finished
            assert workflow.unknown_charge_count == 1
            assert workflow.unattempted_ranges == ((6, 9),)
            with pytest.raises(RuntimeError):
                await workflow.run()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert workflow.state == "stopped"
            assert workflow.attempts[1].finished
            assert isinstance(workflow.attempts[1].error, asyncio.CancelledError)
            assert workflow.reported_fcu_charged == 5
            assert workflow.total_fcu_charged is None
            assert len(calls) == 2
            with pytest.raises(RuntimeError):
                await workflow.run()

    asyncio.run(run())


@pytest.mark.parametrize("module", ["chunked_price", "chunked_price_async", "tabular_price"])
@pytest.mark.parametrize("failure", [None, "429", "malformed"])
def test_standalone_workflow_examples_report_partial_results_and_charges(
    module, failure, batch_cases, tmp_path
):
    import os
    import shutil
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    case = batch_cases[4]
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            start = len(received) * 2
            received.append(body)
            assert self.path == case["path"]
            assert body == {"requests": case["request"]["requests"][start : min(start + 2, 5)]}
            response = copy.deepcopy(case["response"])
            response["results"] = response["results"][start : min(start + 2, 5)]
            for index, item in enumerate(response["results"]):
                item["index"] = index
            response["metadata"]["fcu_charged"] = 2**53 + 1 if start == 0 else 7
            status = 200
            if failure and start == 2:
                if failure == "429":
                    status = 429
                    response = {
                        "metadata": response["metadata"],
                        "error": {"code": "limited", "message": "synthetic"},
                    }
                else:
                    response["results"] = []
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "30")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = tmp_path / f"{module}.py"
        shutil.copyfile(Path(__file__).parents[1] / "examples" / script.name, script)
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={
                **os.environ,
                "MORPHIQ_API_KEY": "example-workflow-key",
                "MORPHIQ_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            },
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=20,
        )
        assert result.returncode == (1 if failure else 0), result.stderr
        assert len(received) == (2 if failure else 3)
        assert "example-workflow-key" not in result.stdout + result.stderr
        if module == "tabular_price":
            assert "spot-80" in result.stdout and "spot-100" in result.stdout
            assert "request_index" in result.stdout
        else:
            assert "Item 0: spot=80.0" in result.stdout
            assert "Item 1: spot=85.0" in result.stdout
        assert f"Reported CU subtotal: {2**53 + (8 if failure else 15)}" in result.stdout
        assert "Attempts with unknown CU: 0" in result.stdout
        if failure:
            if module == "tabular_price":
                assert "unattempted" in result.stdout and "request_error" in result.stdout
            else:
                assert "Unattempted input ranges: ((4, 5),)" in result.stdout
            assert "Whole-workflow CU: unknown or incomplete" in result.stdout
        else:
            if module != "tabular_price":
                assert "Item 4: spot=100.0" in result.stdout
            assert f"Whole-workflow CU: {2**53 + 15}" in result.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_sync_concurrent_run_does_not_duplicate_submission(batch_cases):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    case = batch_cases[0]
    calls = []

    def handle(request):
        calls.append(request)
        entered.set()
        assert release.wait(timeout=5)
        return httpx.Response(200, json=case["response"])

    with MorphIQ(api_key="workflow-test", transport=httpx.MockTransport(handle)) as client:
        workflow = client.price_workflow(
            BatchPriceRequest(**case["request"]).requests, chunk_size=3
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(workflow.run)
            try:
                assert entered.wait(timeout=5)
                with pytest.raises(RuntimeError):
                    workflow.run()
            finally:
                release.set()
            future.result(timeout=5)
        assert len(calls) == 1 and workflow.state == "completed"
