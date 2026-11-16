"""The SDK prefers the ``cu_*`` wire names and falls back to deprecated ``fcu_*`` names."""

import copy

import pytest

import morphiq_sdk as sdk
from morphiq_sdk.models import (
    CostBreakdown,
    CostLine,
    CostRate,
    CostSchedule,
    ResponseMetadata,
    ServiceErrorMetadata,
)
from morphiq_sdk.pandas import batch_to_frames
from morphiq_sdk.workflows import ChunkAttempt

BASE = {
    "request_id": "cu-fields",
    "api_version": "v1",
    "engine_version": "0.45.0",
    "engines": [{"name": "morphiq-risk", "version": "0.45.0", "revision": "a" * 40}],
}
COMMERCIAL = {
    "quoted": 1,
    "charged": 1,
    "schedule_id": "fcu-qdfp-v1",
    "schedule_version": "2026-11-12-regime-rate",
}


def metadata(*, cu=False, fcu=False, **extra):
    wire = dict(BASE)
    for key, value in COMMERCIAL.items():
        if cu:
            wire[f"cu_{key}"] = value
        if fcu:
            wire[f"fcu_{key}"] = value
    wire.update(extra)
    return wire


@pytest.mark.parametrize("names", [{"cu": True}, {"fcu": True}, {"cu": True, "fcu": True}])
def test_metadata_populates_both_names_and_keeps_the_wire_payload(names):
    wire = metadata(**names)
    parsed = ResponseMetadata.model_validate(wire)
    assert (parsed.cu_quoted, parsed.cu_charged) == (1, 1)
    assert (parsed.fcu_quoted, parsed.fcu_charged) == (1, 1)
    assert parsed.cu_schedule_id == parsed.fcu_schedule_id == "fcu-qdfp-v1"
    assert parsed.cu_schedule_version == parsed.fcu_schedule_version == "2026-11-12-regime-rate"
    # Names the server did not send are not reported as sent.
    assert parsed.model_dump(exclude_unset=True) == wire


@pytest.mark.parametrize(
    ("sent", "other"),
    [
        ("remaining_cu_instance_estimate", "remaining_fcu_instance_estimate"),
        ("remaining_fcu_instance_estimate", "remaining_cu_instance_estimate"),
    ],
)
def test_remaining_instance_estimate_mirrors_in_both_directions(sent, other):
    parsed = ResponseMetadata.model_validate(metadata(**{sent: 41}))
    assert getattr(parsed, sent) == getattr(parsed, other) == 41


def test_unreported_charge_stays_unreported_not_zero():
    parsed = ResponseMetadata.model_validate(metadata())
    assert parsed.cu_charged is None and parsed.fcu_charged is None
    assert parsed.model_dump(exclude_unset=True) == metadata()


def test_a_value_the_server_sent_is_never_overridden():
    wire = metadata(cu=True, fcu=True)
    wire["cu_charged"] = 5
    parsed = ResponseMetadata.model_validate(wire)
    assert (parsed.cu_charged, parsed.fcu_charged) == (5, 1)


@pytest.mark.parametrize("current,legacy", [(None, 3), (3, None), (None, None)])
def test_explicit_null_charge_is_preserved(current, legacy):
    wire = {**metadata(), "service_version": "0.7.0", "cu_charged": current, "fcu_charged": legacy}
    parsed = ServiceErrorMetadata.model_validate(wire)
    assert parsed.cu_charged == current
    assert parsed.fcu_charged == legacy
    assert parsed.model_dump(exclude_unset=True) == wire


COST_TYPES = {
    CostRate: {"cu_per_unit": 2},
    CostLine: {"cu_per_unit": 2, "variable_cu": 4},
    CostBreakdown: {"total_cu": 5, "fixed_cu": 1, "variable_cu": 4, "minimum_charge_cu": 0},
    CostSchedule: {"fixed_request_cu": 1, "minimum_charge_cu": 0},
}
REQUIRED_OTHER = {
    CostRate: {
        "operation": "price",
        "model": "m/1",
        "billing_unit": "contract",
        "max_discrete_dividends": 0,
    },
    CostLine: {"operation": "price", "model": "m/1", "billing_unit": "contract", "quantity": 2},
    CostBreakdown: {"lines": []},
    CostSchedule: {
        "schedule_id": "s",
        "schedule_version": "1",
        "record_version": 1,
        "policy_revision": "a" * 64,
        "effective_from": "2026-11-12T00:00:00Z",
        "effective_until": None,
        "rounding": "none",
        "failure_charging": "commit_at_execution_start",
        "rates": [],
    },
}


@pytest.mark.parametrize("cls", list(COST_TYPES))
@pytest.mark.parametrize("names", ["cu", "fcu", "both"])
def test_cost_types_accept_either_name_and_expose_both(cls, names):
    cu = COST_TYPES[cls]
    fcu = {key.replace("cu", "fcu"): value for key, value in cu.items()}
    wire = {
        **REQUIRED_OTHER[cls],
        **(cu if names != "fcu" else {}),
        **(fcu if names != "cu" else {}),
    }
    parsed = cls.model_validate(wire)
    for name, value in cu.items():
        assert getattr(parsed, name) == value
        assert getattr(parsed, name.replace("cu", "fcu")) == value
    assert parsed.model_dump(exclude_unset=True) == wire


def test_cost_type_without_either_name_is_still_rejected():
    with pytest.raises(ValueError, match="per_unit"):
        CostRate.model_validate(REQUIRED_OTHER[CostRate])


def _batch_response(batch_cases, **commercial):
    body = copy.deepcopy(batch_cases[0]["response"])
    for key in ("fcu_charged", "cu_charged", "fcu_quoted", "cu_quoted"):
        body["metadata"].pop(key, None)
    body["metadata"].update(commercial)
    return sdk.BatchPriceResponse.model_validate(body)


@pytest.mark.parametrize("sent", ["cu_charged", "fcu_charged"])
def test_batch_frames_read_the_charge_from_either_name(batch_cases, sent):
    frames = batch_to_frames(_batch_response(batch_cases, **{sent: 7}))
    assert frames.reported_cu_charged == frames.reported_fcu_charged == 7
    assert frames.total_cu_charged == frames.total_fcu_charged == 7
    assert frames.requests.loc[0, "cu_charged"] == frames.requests.loc[0, "fcu_charged"] == 7


def test_batch_frames_keep_a_missing_charge_unknown(batch_cases):
    frames = batch_to_frames(_batch_response(batch_cases))
    assert frames.unknown_charge_count == 1
    assert frames.total_cu_charged is None and frames.total_fcu_charged is None
    assert frames.requests.loc[0, "cu_charged"] is None


def test_chunk_attempt_cu_charged_aliases_the_stored_charge():
    attempt = ChunkAttempt(start=0, stop=3, fcu_charged=9)
    assert attempt.cu_charged == attempt.fcu_charged == 9
    assert ChunkAttempt(start=0, stop=3).cu_charged is None
