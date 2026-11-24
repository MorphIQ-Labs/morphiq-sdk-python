"""Grouped response metadata: contract, billing, budget and policy, never flat CU aliases."""

import copy

import pytest
from pydantic import ValidationError

import morphiq_sdk as sdk
from morphiq_sdk.models import BillingMetadata, BudgetMetadata, PolicyMetadata, ResponseMetadata
from morphiq_sdk.pandas import batch_to_frames
from morphiq_sdk.workflows import ChunkAttempt

BASE = {
    "request_id": "billing-fields",
    "service_version": "0.10.0",
    "contract": {"version": "0.1.0", "sha256": "a" * 64},
    "engines": [{"name": "morphiq-risk", "version": "0.46.1", "revision": "a" * 40}],
}
METERED = {
    "billing": {
        "quoted_cu": 100,
        "charged_cu": 100,
        "rate_card": {"id": "fcu-qdfp-v1", "version": "2026-11-20-scenario-solves"},
    },
    "budget": {
        "period": "2026-11",
        "resets_at": "2026-12-01T00:00:00Z",
        "remaining_estimate_cu": 9900,
    },
    "policy": {"plan": "developer", "revision": "b" * 64},
}


def test_metered_metadata_is_grouped_and_wire_faithful():
    wire = {**BASE, **METERED}
    parsed = ResponseMetadata.model_validate(wire)
    assert parsed.billing.quoted_cu == parsed.billing.charged_cu == parsed.charged_cu == 100
    assert parsed.billing.rate_card.id == "fcu-qdfp-v1"
    assert parsed.budget.remaining_estimate_cu == 9900
    assert parsed.policy.plan == "developer" and parsed.policy.revision == "b" * 64
    assert parsed.contract.version == "0.1.0"
    assert parsed.model_dump(exclude_unset=True) == wire


def test_unmetered_metadata_omits_groups_and_charge_stays_unreported():
    parsed = ResponseMetadata.model_validate(BASE)
    assert parsed.billing is None and parsed.budget is None and parsed.policy is None
    assert parsed.charged_cu is None
    assert parsed.model_dump(exclude_unset=True) == BASE
    # Billing present without a charge is still unreported, never zero.
    partial = ResponseMetadata.model_validate({**BASE, "billing": {"quoted_cu": 3}})
    assert partial.charged_cu is None and partial.billing.quoted_cu == 3


def test_engines_are_absent_when_no_engine_was_selected():
    wire = {key: value for key, value in BASE.items() if key != "engines"}
    parsed = ResponseMetadata.model_validate(wire)
    assert parsed.engines is None
    assert parsed.model_dump(exclude_unset=True) == wire


@pytest.mark.parametrize(
    "wire",
    [
        {k: v for k, v in BASE.items() if k != "contract"},
        {**BASE, "contract": {"version": "0.1.0"}},
        {**BASE, "billing": {"charged_cu": -1}},
        {**BASE, "billing": {"charged_cu": "7"}},
        {**BASE, "budget": {"remaining_estimate_cu": 1.5}},
        {**BASE, "policy": {"plan": "developer"}},
    ],
)
def test_invalid_metadata_is_rejected(wire):
    with pytest.raises(ValidationError):
        ResponseMetadata.model_validate(wire)


def test_retired_flat_fields_are_additive_extras_not_charges():
    # Retired flat names (fcu_charged, cu_remaining_estimate) carry no meaning now.
    wire = {**BASE, "fcu_charged": 5, "cu_charged": 5, "remaining_cu_instance_estimate": 4}
    parsed = ResponseMetadata.model_validate(wire)
    assert parsed.charged_cu is None
    assert parsed.model_dump(exclude_unset=True) == wire
    assert not hasattr(sdk, "ServiceErrorMetadata")


@pytest.mark.parametrize("model", [BillingMetadata, BudgetMetadata])
def test_every_group_member_is_optional(model):
    assert model.model_validate({}).model_dump(exclude_unset=True) == {}


def test_policy_reports_plan_and_revision_only():
    assert set(PolicyMetadata.model_fields) == {"plan", "revision"}


def _batch_response(batch_cases, billing=None):
    body = copy.deepcopy(batch_cases[0]["response"])
    body["metadata"].pop("billing", None)
    if billing is not None:
        body["metadata"]["billing"] = billing
    return sdk.OptionsBatchPriceResponse.model_validate(body)


def test_batch_frames_read_the_grouped_charge(batch_cases):
    frames = batch_to_frames(_batch_response(batch_cases, {"quoted_cu": 7, "charged_cu": 7}))
    assert frames.reported_charged_cu == frames.total_charged_cu == 7
    assert frames.requests.loc[0, "charged_cu"] == 7
    assert frames.requests.loc[0, "metadata"]["billing"]["quoted_cu"] == 7


def test_batch_frames_keep_a_missing_charge_unknown(batch_cases):
    frames = batch_to_frames(_batch_response(batch_cases))
    assert frames.unknown_charge_count == 1
    assert frames.total_charged_cu is None
    assert frames.requests.loc[0, "charged_cu"] is None


def test_chunk_attempt_holds_the_reported_charge():
    assert ChunkAttempt(start=0, stop=3, charged_cu=9).charged_cu == 9
    assert ChunkAttempt(start=0, stop=3).charged_cu is None
