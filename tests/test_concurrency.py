import asyncio
import copy
import json

import httpx
import pytest
from test_workflows import OPERATIONS

from morphiq_sdk import (
    APIError,
    AsyncMorphIQ,
    BatchPriceRequest,
    RateLimitError,
    RequestTimeout,
    ResponseError,
)


@pytest.mark.parametrize("operation", range(4))
def test_out_of_order_completions_keep_indices_and_exact_charges(operation, batch_cases):
    factory, request_type = OPERATIONS[operation]
    case = batch_cases[operation]
    requests = (
        request_type(**case["request"]).requests * 5 + request_type(**case["request"]).requests[:1]
    )

    async def run():
        entered = [asyncio.Event() for _ in range(6)]
        release = [asyncio.Event() for _ in range(6)]
        calls, completed = [], []
        active = peak = 0

        async def handle(request):
            nonlocal active, peak
            index = len(calls)
            body = json.loads(request.content)
            assert request.url.path == case["path"]
            assert body == {"requests": [r.to_wire() for r in requests[index * 3 : index * 3 + 3]]}
            calls.append(body)
            active += 1
            peak = max(peak, active)
            entered[index].set()
            try:
                await release[index].wait()
                response = copy.deepcopy(case["response"])
                response["results"] = response["results"][: len(body["requests"])]
                response["metadata"].update(request_id=f"chunk-{index}", fcu_charged=2**100 + index)
                completed.append(index)
                return httpx.Response(200, json=response)
            finally:
                active -= 1

        async with AsyncMorphIQ(
            api_key="concurrency-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = getattr(client, factory)(requests, chunk_size=3, max_concurrency=2)
            assert workflow.max_concurrency == 2 and not calls
            task = asyncio.create_task(workflow.run())
            await entered[1].wait()
            assert len(calls) == 2
            release[1].set()
            await entered[2].wait()
            assert workflow.attempts[1].finished and not workflow.attempts[0].finished
            release[2].set()
            await entered[3].wait()
            release[0].set()
            await entered[4].wait()
            release[4].set()
            await entered[5].wait()
            release[3].set()
            release[5].set()
            await task
            assert completed == [1, 2, 0, 4, 3, 5]
            assert peak == 2 and active == 0
            assert workflow.state == "completed" and not workflow.unattempted_ranges
            assert [a.start for a in workflow.attempts] == [0, 3, 6, 9, 12, 15]
            assert [a.request_id for a in workflow.attempts] == [f"chunk-{i}" for i in range(6)]
            assert [a.fcu_charged for a in workflow.attempts] == [2**100 + i for i in range(6)]
            assert workflow.total_fcu_charged == 6 * 2**100 + 15
            assert workflow.unknown_charge_count == 0
            assert [
                a.start + r.index for a in workflow.attempts for r in a.response.results
            ] == list(range(16))
            assert workflow.attempts[0].response.results[1].status == "error"
            with pytest.raises(RuntimeError):
                await workflow.run()
            assert len(calls) == 6

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["429", "gateway", "timeout", "invalid", "500", "cancel"])
def test_failure_stops_launches_drains_inflight_and_preserves_all_errors(failure, batch_cases):
    case = batch_cases[0]

    async def run():
        entered = [asyncio.Event() for _ in range(3)]
        release = [asyncio.Event() for _ in range(3)]
        returned = [asyncio.Event() for _ in range(3)]
        calls = []

        async def handle(request):
            index = len(calls)
            calls.append(request)
            assert index < 3, "A request started after the failure was observed"
            entered[index].set()
            await release[index].wait()
            response = copy.deepcopy(case["response"])
            response["metadata"].update(
                fcu_charged=2**100 if index == 0 else 7, request_id=f"chunk-{index}"
            )
            returned[index].set()
            if index == 1:
                if failure == "timeout":
                    raise httpx.ReadTimeout("synthetic")
                if failure == "cancel":
                    raise asyncio.CancelledError()
                if failure == "gateway":
                    return httpx.Response(429, text="busy", headers={"Retry-After": "30"})
                if failure == "invalid":
                    response["results"].reverse()
                    return httpx.Response(200, json=response)
            if index != 0:
                # A later in-flight failure must not replace the first observed error.
                response = {
                    "metadata": response["metadata"],
                    "error": {"code": "synthetic", "message": "synthetic failure"},
                }
                return httpx.Response(
                    429 if index == 1 and failure == "429" else 500,
                    json=response,
                    headers={"Retry-After": "30"},
                )
            return httpx.Response(200, json=response)

        async with AsyncMorphIQ(
            api_key="concurrency-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = client.price_workflow(
                BatchPriceRequest(**case["request"]).requests * 5, chunk_size=3, max_concurrency=3
            )
            task = asyncio.create_task(workflow.run())
            await entered[2].wait()
            release[1].set()
            await returned[1].wait()
            assert workflow.attempts[1].finished
            assert not task.done() and workflow.state == "running"
            release[0].set()
            await returned[0].wait()
            assert len(calls) == 3 and not task.done()
            release[2].set()
            expected = {
                "429": RateLimitError,
                "gateway": RateLimitError,
                "timeout": RequestTimeout,
                "invalid": ResponseError,
                "500": APIError,
                "cancel": asyncio.CancelledError,
            }[failure]
            with pytest.raises(expected) as raised:
                await task
            assert raised.value is workflow.attempts[1].error
            assert isinstance(workflow.attempts[2].error, APIError)
            assert workflow.attempts[0].response is not None
            assert workflow.unattempted_ranges == ((9, 12), (12, 15))
            unknown = failure in ("gateway", "timeout", "cancel")
            assert workflow.unknown_charge_count == int(unknown)
            assert workflow.reported_fcu_charged == 2**100 + (7 if unknown else 14)
            assert workflow.total_fcu_charged is None and workflow.state == "stopped"
            assert len(calls) == 3

    asyncio.run(run())


@pytest.mark.parametrize("limit", [1, 2, 10])
def test_bound_defaults_and_oversized_pool(limit, batch_cases):
    case = batch_cases[0]

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        active = peak = calls = 0

        async def handle(request):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            if active == min(limit, 3):
                entered.set()
            await release.wait()
            active -= 1
            return httpx.Response(200, json=case["response"])

        async with AsyncMorphIQ(
            api_key="concurrency-test", transport=httpx.MockTransport(handle)
        ) as client:
            kwargs = {} if limit == 1 else {"max_concurrency": limit}
            workflow = client.price_workflow(
                BatchPriceRequest(**case["request"]).requests * 3, chunk_size=3, **kwargs
            )
            task = asyncio.create_task(workflow.run())
            await entered.wait()
            assert calls == min(limit, 3)
            release.set()
            await task
            assert peak == min(limit, 3) and calls == 3
            assert workflow.max_concurrency == limit

    asyncio.run(run())


@pytest.mark.parametrize("during_failure", [False, True])
def test_repeated_caller_cancellation_joins_workers_and_keeps_known_charges(
    during_failure, batch_cases
):
    case = batch_cases[0]

    async def run():
        baseline = asyncio.all_tasks()
        entered, cleanup_started, cleanup_release, first_done = (asyncio.Event() for _ in range(4))
        calls, cancelled, cleaned = [], [], []

        async def handle(request):
            index = len(calls)
            calls.append(index)
            if index == 0:
                # Wait until three calls are in flight before returning a known receipt.
                await entered.wait()
                response = copy.deepcopy(case["response"])
                response["metadata"]["fcu_charged"] = 2**100
                first_done.set()
                if during_failure:
                    return httpx.Response(
                        429,
                        json={
                            "metadata": response["metadata"],
                            "error": {"code": "limited", "message": "synthetic"},
                        },
                    )
                return httpx.Response(200, json=response)
            if index == 2:
                entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.append(index)
                if len(cancelled) == (2 if during_failure else 3):
                    cleanup_started.set()
                await cleanup_release.wait()
                cleaned.append(index)
                raise

        async with AsyncMorphIQ(
            api_key="concurrency-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = client.price_workflow(
                BatchPriceRequest(**case["request"]).requests * 6, chunk_size=3, max_concurrency=3
            )
            task = asyncio.create_task(workflow.run())
            await first_done.wait()
            assert workflow.attempts[0].finished
            task.cancel()
            await cleanup_started.wait()
            task.cancel()  # Repeated cancellation must not leave background calls behind.
            await asyncio.sleep(0)
            assert not task.done()
            cleanup_release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sorted(cleaned) == sorted(cancelled)
            assert asyncio.all_tasks() == baseline
            assert workflow.reported_fcu_charged == 2**100
            assert workflow.unknown_charge_count == (2 if during_failure else 3)
            assert workflow.total_fcu_charged is None and workflow.state == "stopped"
            assert all(a.finished for a in workflow.attempts)
            assert len(calls) == (3 if during_failure else 4)
            assert workflow.unattempted_ranges[0][0] == len(calls) * 3

    asyncio.run(run())


@pytest.mark.parametrize("operation", range(4))
def test_concurrency_validation_and_empty_work(operation, batch_cases):
    factory, request_type = OPERATIONS[operation]

    async def run():
        async with AsyncMorphIQ(api_key="concurrency-test") as client:
            for invalid in (0, -1, True, 1.5, "2", None):
                with pytest.raises(ValueError, match="positive integer"):
                    getattr(client, factory)(
                        request_type(**batch_cases[operation]["request"]).requests,
                        chunk_size=3,
                        max_concurrency=invalid,
                    )
            workflow = getattr(client, factory)([], chunk_size=1, max_concurrency=10)
            await workflow.run()
            assert workflow.attempts == () and workflow.state == "completed"
            assert workflow.total_fcu_charged == 0

    asyncio.run(run())


def test_receipt_returned_during_cancellation_is_retained_without_new_submissions(batch_cases):
    case = batch_cases[0]

    async def run():
        entered = asyncio.Event()
        calls = []

        async def handle(request):
            index = len(calls)
            calls.append(index)
            if index == 2:
                entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                if index == 0:
                    body = copy.deepcopy(case["response"])
                    body["metadata"]["fcu_charged"] = 7
                    return httpx.Response(200, json=body)
                raise

        async with AsyncMorphIQ(
            api_key="concurrency-test", transport=httpx.MockTransport(handle)
        ) as client:
            workflow = client.price_workflow(
                BatchPriceRequest(**case["request"]).requests * 6, chunk_size=3, max_concurrency=3
            )
            task = asyncio.create_task(workflow.run())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == [0, 1, 2]
            assert workflow.attempts[0].response is not None
            assert workflow.reported_fcu_charged == 7
            assert workflow.unknown_charge_count == 2
            assert workflow.state == "stopped"

    asyncio.run(run())


def test_standalone_async_example_uses_explicit_concurrency(batch_cases, tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    case = batch_cases[4]
    both_started, third_started = threading.Event(), threading.Event()
    lock = threading.Lock()
    seen = []
    active = peak = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal active, peak
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            start = {80.0: 0, 90.0: 2, 100.0: 4}[body["requests"][0]["spot"]]
            assert body == {"requests": case["request"]["requests"][start : min(start + 2, 5)]}
            with lock:
                seen.append(start)
                active += 1
                peak = max(peak, active)
                if len(seen) >= 2:
                    both_started.set()
            try:
                assert both_started.wait(timeout=5)
                if start == 0:
                    assert third_started.wait(timeout=5)
                elif start == 4:
                    third_started.set()
                response = copy.deepcopy(case["response"])
                response["results"] = response["results"][start : min(start + 2, 5)]
                for index, item in enumerate(response["results"]):
                    item["index"] = index
                response["metadata"]["fcu_charged"] = {0: 2**100, 2: 7, 4: 11}[start]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            finally:
                with lock:
                    active -= 1

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = tmp_path / "chunked_price_async.py"
        shutil.copyfile(Path(__file__).parents[1] / "examples" / script.name, script)
        result = subprocess.run(
            [sys.executable, str(script), "--max-concurrency", "2"],
            cwd=tmp_path,
            env={
                **os.environ,
                "MORPHIQ_API_KEY": "concurrent-example-key",
                "MORPHIQ_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert sorted(seen) == [0, 2, 4] and peak >= 2
        assert "Maximum concurrent requests: 2" in result.stdout
        assert f"Whole-workflow CU: {2**100 + 18}" in result.stdout
        assert (
            result.stdout.index("Item 0:")
            < result.stdout.index("Item 2:")
            < result.stdout.index("Item 4:")
        )
        assert "concurrent-example-key" not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
