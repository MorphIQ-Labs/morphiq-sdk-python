"""Optional, in-memory tabular views of batch responses and workflows.

Install ``morphiq-sdk[pandas]``. Importing the core SDK or this module does not
import pandas; conversion does. No data download, API call or file write occurs.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .errors import APIError, MorphIQError, ResponseError
from .models import (
    BatchAnalyticsResponse,
    BatchGreeksResponse,
    BatchImpliedVolatilityResponse,
    BatchPriceResponse,
)
from .workflows import AsyncBatchWorkflow, BatchWorkflow, ChunkAttempt

if TYPE_CHECKING:
    import pandas as pd

_BatchResponse = (
    BatchPriceResponse
    | BatchGreeksResponse
    | BatchImpliedVolatilityResponse
    | BatchAnalyticsResponse
)
_Identifier = str | int | None
_ITEM_COLUMNS = ["index", "identifier", "request_index", "item_index", "status", "outcome"]
_REQUEST_COLUMNS = [
    "request_index",
    "start",
    "stop",
    "status",
    "request_id",
    "fcu_charged",
    "metadata",
    "response_extras",
    "error",
]

__all__ = ["BatchFrames", "batch_to_frames", "workflow_to_frames"]


@dataclass(frozen=True)
class BatchFrames:
    """Independent tables and cost summary captured at conversion time.

    ``results`` has one row per original input; ``requests`` has one row per HTTP
    attempt. Editing either table does not change SDK evidence or this summary.
    Result units are unchanged. Missing commercial charges are never zero-filled.
    """

    results: pd.DataFrame
    requests: pd.DataFrame
    state: str
    reported_fcu_charged: int
    unknown_charge_count: int
    total_fcu_charged: int | None


def _pandas() -> Any:
    try:
        import pandas
    except ImportError:
        raise ImportError(
            "DataFrame conversion requires pandas; install 'morphiq-sdk[pandas]' "
            "or, from a checkout, pip install -e '.[pandas]'."
        ) from None
    return pandas


def _identifiers(values: Sequence[_Identifier] | None, count: int) -> list[_Identifier]:
    if values is None:
        return [None] * count
    if isinstance(values, (str, bytes)) or len(values) != count:
        raise ValueError("identifiers must contain exactly one entry per original input.")
    result = list(values)
    if any(value is not None and type(value) not in (str, int) for value in result):
        raise TypeError("Each identifier must be a string, Python integer or None.")
    return result


def _fields(model: BaseModel, prefix: str) -> dict[str, Any]:
    # Flatten known typed fields only. Full outcome dictionaries below retain
    # additive fields, even names with dots that would collide when flattened.
    result: dict[str, Any] = {}
    for name in type(model).model_fields:
        if name not in model.model_fields_set:
            continue
        value = getattr(model, name)
        key = f"{prefix}.{name}"
        if isinstance(value, BaseModel):
            result.update(_fields(value, key))
        else:
            result[key] = deepcopy(value)
    return result


def _error(error: BaseException | None) -> dict[str, Any] | None:
    if error is None:
        return None
    result: dict[str, Any] = {"type": type(error).__name__}
    if isinstance(error, MorphIQError):
        result["message"] = str(error)
    if isinstance(error, APIError):
        result.update(
            status_code=error.status_code,
            code=error.code,
            field=error.field,
            retry_after=error.retry_after,
        )
    return result


def _attempt_rows(
    attempt: ChunkAttempt[Any],
    request_index: int,
    identifiers: list[_Identifier],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response, error = attempt.response, attempt.error
    metadata = response.metadata if response is not None else None
    if isinstance(error, (APIError, ResponseError)):
        metadata = error.metadata
    if response is not None:
        status = "completed"
        expected = list(range(attempt.stop - attempt.start))
        if [item.index for item in response.results] != expected:
            raise ValueError("Response indices must match the chunk's original input order.")
    elif not attempt.finished or (error is not None and not isinstance(error, Exception)):
        status = "interrupted"
    else:
        status = "request_error"
    receipt = {
        "request_index": request_index,
        "start": attempt.start,
        "stop": attempt.stop,
        "status": status,
        "request_id": attempt.request_id,
        "fcu_charged": attempt.fcu_charged,
        "metadata": metadata.model_dump(exclude_unset=True) if metadata else None,
        "response_extras": (
            response.model_dump(exclude={"metadata", "results"}, exclude_unset=True)
            if response is not None
            else None
        ),
        "error": _error(error),
    }
    rows = []
    for local_index, index in enumerate(range(attempt.start, attempt.stop)):
        row: dict[str, Any] = {
            "index": index,
            "identifier": identifiers[index],
            "request_index": request_index,
            "item_index": local_index,
            "status": status,
            "outcome": None,
        }
        if response is not None:
            item = response.results[local_index]
            row.update(status=item.status, outcome=item.model_dump(exclude_unset=True))
            if item.status == "success":
                row.update(_fields(item.result, "result"))
            else:
                row.update(_fields(item.error, "error"))
        rows.append(row)
    return rows, receipt


def _frames(
    rows: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    state: str,
) -> BatchFrames:
    pd = _pandas()
    columns = list(dict.fromkeys(_ITEM_COLUMNS + [name for row in rows for name in row]))
    # Build object columns directly, avoiding pandas' intermediate int->float
    # inference when an integer column also contains None (CU, IDs, iterations).
    results = pd.DataFrame(
        {name: pd.Series([row.get(name) for row in rows], dtype=object) for name in columns}
    )
    for name in columns:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None]
        if name.startswith("result.") and present:
            if all(type(value) is float for value in present):
                results[name] = pd.Series(values, dtype="Float64")
            elif all(type(value) is bool for value in present):
                results[name] = pd.Series(values, dtype="boolean")
    requests = pd.DataFrame(
        {
            name: pd.Series([receipt[name] for receipt in receipts], dtype=object)
            for name in _REQUEST_COLUMNS
        }
    )
    known = sum(
        receipt["fcu_charged"] for receipt in receipts if receipt["fcu_charged"] is not None
    )
    unknown = sum(receipt["fcu_charged"] is None for receipt in receipts)
    return BatchFrames(
        results=results,
        requests=requests,
        state=state,
        reported_fcu_charged=known,
        unknown_charge_count=unknown,
        total_fcu_charged=known if state == "completed" and not unknown else None,
    )


def batch_to_frames(
    response: _BatchResponse,
    *,
    identifiers: Sequence[_Identifier] | None = None,
) -> BatchFrames:
    """Convert one accepted batch, including item errors and one charge receipt.

    Identifiers are local labels, never sent to the API. Preserve duplicates and
    nulls in input order; their length must match the entire original batch.
    """
    labels = _identifiers(identifiers, len(response.results))
    attempt = ChunkAttempt(
        start=0,
        stop=len(response.results),
        response=response,
        finished=True,
        fcu_charged=response.metadata.fcu_charged,
        request_id=response.metadata.request_id,
    )
    rows, receipt = _attempt_rows(attempt, 0, labels)
    return _frames(rows, [receipt], "completed")


def workflow_to_frames(
    workflow: BatchWorkflow[Any, Any] | AsyncBatchWorkflow[Any, Any],
    *,
    identifiers: Sequence[_Identifier] | None = None,
) -> BatchFrames:
    """Snapshot a ready, completed or stopped workflow; reject active execution.

    Include placeholders for failed/interrupted requests and unattempted inputs.
    Only attempted requests get charge-table rows. Conversion never executes or
    resumes work. Identifiers must cover all original inputs, not just successes.
    """
    state = workflow.state
    if state == "running":
        raise ValueError("Wait for the workflow to complete or stop before converting it.")
    attempts, pending = workflow.attempts, workflow.unattempted_ranges
    if workflow.state != state:
        raise ValueError("Workflow changed during conversion; wait until it stops.")
    count = pending[-1][1] if pending else (attempts[-1].stop if attempts else 0)
    labels = _identifiers(identifiers, count)
    rows, receipts = [], []
    for request_index, attempt in enumerate(attempts):
        chunk_rows, receipt = _attempt_rows(attempt, request_index, labels)
        rows.extend(chunk_rows)
        receipts.append(receipt)
    for start, stop in pending:
        rows.extend(
            {
                "index": index,
                "identifier": labels[index],
                "request_index": None,
                "item_index": index - start,
                "status": "unattempted",
                "outcome": None,
            }
            for index in range(start, stop)
        )
    return _frames(rows, receipts, state)
