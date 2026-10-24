"""Explicit sequential batch execution; no retries, numerical work or data dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any, Generic, Literal, TypeVar

from .errors import APIError, ResponseError
from .models import (
    ResponseMetadata,
    ServiceErrorMetadata,
    _BatchRequest,
    _BatchResponse,
    _OptionRequest,
)

_RequestT = TypeVar("_RequestT", bound=_BatchRequest[Any])
_ResponseT = TypeVar("_ResponseT", bound=_BatchResponse[Any])


@dataclass(frozen=True)
class ChunkAttempt(Generic[_ResponseT]):
    """One HTTP attempt covering original input indices [start, stop).

    Response indices remain local to this chunk. Add ``start`` for the original
    input index. Charge and request ID are captured once, independently of later
    edits to the response. An unfinished attempt has unknown execution/charge.
    """

    start: int
    stop: int
    response: _ResponseT | None = None
    error: BaseException | None = None
    finished: bool = False
    fcu_charged: int | None = None
    request_id: str | None = None


class _Workflow(Generic[_RequestT, _ResponseT]):
    def __init__(self, chunks: Sequence[_RequestT]) -> None:
        self._state_lock = Lock()
        self._chunks = tuple(chunks)
        self._ranges: tuple[tuple[int, int], ...] = tuple(self._make_ranges(chunks))
        self._attempts: list[ChunkAttempt[_ResponseT]] = []
        self._state: Literal["ready", "running", "completed", "stopped"] = "ready"

    @staticmethod
    def _make_ranges(chunks: Sequence[_RequestT]) -> list[tuple[int, int]]:
        ranges = []
        start = 0
        for chunk in chunks:
            stop = start + len(chunk.requests)
            ranges.append((start, stop))
            start = stop
        return ranges

    @property
    def state(self) -> Literal["ready", "running", "completed", "stopped"]:
        return self._state

    @property
    def planned_chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def attempts(self) -> tuple[ChunkAttempt[_ResponseT], ...]:
        """In submission order, including a failed or currently in-flight attempt."""
        return tuple(self._attempts)

    @property
    def unattempted_ranges(self) -> tuple[tuple[int, int], ...]:
        """Original input ranges never submitted; excludes the failed/in-flight chunk."""
        return self._ranges[len(self._attempts) :]

    @property
    def reported_fcu_charged(self) -> int:
        """Exact integer subtotal of reported commercial charges, once per attempt."""
        return sum(a.fcu_charged for a in self._attempts if a.fcu_charged is not None)

    @property
    def unknown_charge_count(self) -> int:
        """Attempts without a reported charge; a reported zero is known."""
        return sum(a.fcu_charged is None for a in self._attempts)

    @property
    def total_fcu_charged(self) -> int | None:
        """Whole-workflow total only when completed and every attempt reports a charge."""
        if self._state != "completed" or self.unknown_charge_count:
            return None
        return self.reported_fcu_charged

    def _begin(self) -> None:
        with self._state_lock:
            if self._state != "ready":
                raise RuntimeError("A batch workflow can run only once; no requests were replayed.")
            self._state = "running"

    def _start_attempt(self, index: int) -> None:
        start, stop = self._ranges[index]
        self._attempts.append(ChunkAttempt(start=start, stop=stop))

    def _finish_attempt(
        self, *, response: _ResponseT | None = None, error: BaseException | None = None
    ) -> None:
        attempt = self._attempts[-1]
        metadata: ResponseMetadata | ServiceErrorMetadata | None = (
            response.metadata if response is not None else None
        )
        request_id = metadata.request_id if metadata else None
        if isinstance(error, (APIError, ResponseError)):
            metadata = error.metadata
            request_id = error.request_id
        self._attempts[-1] = ChunkAttempt(
            start=attempt.start,
            stop=attempt.stop,
            response=response,
            error=error,
            finished=True,
            fcu_charged=metadata.fcu_charged if metadata else None,
            request_id=request_id,
        )


class BatchWorkflow(_Workflow[_RequestT, _ResponseT]):
    """Prepared synchronous workflow. Use a client's ``*_workflow`` factory.

    Construction makes no HTTP requests. ``run()`` sends chunks sequentially,
    retains each outcome and propagates the original exception on failure.
    An item-level error in an accepted response does not stop later chunks.
    The client must remain open until execution finishes. Instances are single-use.
    """

    def __init__(
        self, chunks: Sequence[_RequestT], operation: Callable[[_RequestT], _ResponseT]
    ) -> None:
        super().__init__(chunks)
        self._operation = operation

    def run(self) -> None:
        self._begin()
        try:
            for index, chunk in enumerate(self._chunks):
                self._start_attempt(index)
                try:
                    response = self._operation(chunk)
                except BaseException as error:
                    # Includes interruption: it does not establish a zero charge.
                    self._finish_attempt(error=error)
                    raise
                self._finish_attempt(response=response)
            self._state = "completed"
        finally:
            if self._state == "running":
                self._state = "stopped"


class AsyncBatchWorkflow(_Workflow[_RequestT, _ResponseT]):
    """Async equivalent; sequential awaits, with cancellation retained and propagated."""

    def __init__(
        self, chunks: Sequence[_RequestT], operation: Callable[[_RequestT], Awaitable[_ResponseT]]
    ) -> None:
        super().__init__(chunks)
        self._operation = operation

    async def run(self) -> None:
        self._begin()
        try:
            for index, chunk in enumerate(self._chunks):
                self._start_attempt(index)
                try:
                    response = await self._operation(chunk)
                except BaseException as error:
                    self._finish_attempt(error=error)
                    raise
                self._finish_attempt(response=response)
            self._state = "completed"
        finally:
            if self._state == "running":
                self._state = "stopped"


def _prepare_chunks(
    requests: Sequence[_OptionRequest], batch_type: type[_RequestT], chunk_size: int
) -> tuple[_RequestT, ...]:
    # Validate size using the reviewed envelope, not a customer plan assumption.
    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer within the batch wire limit.")
    limit = batch_type.model_fields["requests"].metadata
    maximum = next(rule.max_length for rule in limit if hasattr(rule, "max_length"))
    if chunk_size > maximum:
        raise ValueError(f"chunk_size exceeds the reviewed batch wire limit of {maximum}.")
    # Validate and snapshot every chunk before any network activity. Deeply mutable
    # input schedules cannot change the prepared work after this point.
    return tuple(
        batch_type.model_validate(
            batch_type(requests=list(requests[start : start + chunk_size])).to_wire()
        )
        for start in range(0, len(requests), chunk_size)
    )
