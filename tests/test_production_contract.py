"""Regime variants: omitted members, open response enums and unrecognized variants."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import SeriesIdentifyRegimeResponse, Unrecognized, models

SCHEMA = json.loads((Path(__file__).parents[1] / "contracts/openapi.json").read_text())


def _validate(payload):
    Draft202012Validator(
        {"$ref": "#/components/schemas/SeriesIdentifyRegimeResponse", **SCHEMA}
    ).validate(payload)


@pytest.mark.parametrize(
    "crisis",
    [
        {"status": "crisis", "score": 2.75, "episode_start_price_index": 500},
        {"status": "not_crisis", "score": -3.5},
        {"status": "unavailable", "reason_code": "short_reference"},
        {"status": "unavailable", "reason_code": "degenerate_reference"},
    ],
)
@pytest.mark.parametrize(
    "volatility",
    [
        *[
            {"status": "available", "prediction": {"label": label}}
            for label in ["low", "high", "crisis"]
        ],
        {"status": "not_applicable", "reason_code": "predicted_not_eligible"},
        {"status": "unavailable", "reason_code": "prediction_unavailable"},
    ],
)
def test_regime_variants_preserve_wire_evidence(regime_cases, crisis, volatility):
    # Test wire variants independently; the client does not recompute the server's rule.
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"]["crisis"] = crisis
    payload["result"]["volatility"] = {**volatility, "basis": {"target": "current_volatility"}}
    _validate(payload)
    parsed = SeriesIdentifyRegimeResponse.model_validate(payload)
    assert parsed.model_dump(exclude_unset=True) == payload
    assert parsed.result.crisis.status == crisis["status"]
    assert parsed.result.volatility.status == volatility["status"]
    # Members a status cannot have are omitted, never reported as null.
    dumped = parsed.result.crisis.model_dump()
    assert ("score" in dumped) == (crisis["status"] != "unavailable")
    assert ("episode_start_price_index" in dumped) == (crisis["status"] == "crisis")


@pytest.mark.parametrize(
    "field,value",
    [
        ("crisis", {"status": "crisis", "score": 2}),
        ("crisis", {"status": "not_crisis", "score": float("inf")}),
        ("crisis", {"status": "not_crisis"}),
        ("crisis", {"status": "unavailable"}),
        ("volatility", {"status": "available", "basis": {"target": "current_volatility"}}),
        (
            "volatility",
            {"status": "not_applicable", "basis": {"target": "current_volatility"}},
        ),
    ],
)
def test_incomplete_known_variants_are_rejected(regime_cases, field, value):
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"][field] = value
    with pytest.raises(ValidationError):
        SeriesIdentifyRegimeResponse.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("crisis", {"status": "recovering", "score": 1.0, "since": 400}),
        ("volatility", {"status": "deferred", "basis": {"target": "current_volatility"}}),
    ],
)
def test_unrecognized_variants_are_retained(regime_cases, field, value):
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"][field] = value
    parsed = SeriesIdentifyRegimeResponse.model_validate(payload)
    variant = getattr(parsed.result, field)
    assert isinstance(variant, Unrecognized)
    assert variant.status == value["status"]
    assert parsed.model_dump(exclude_unset=True) == payload


@pytest.mark.parametrize(
    "path,value",
    [
        (("volatility", "prediction", "label"), "extreme"),
        (("volatility", "basis", "target"), "future_volatility"),
        (("crisis_score_contract", "kind"), "future_readout"),
        (("score_contract", "kind"), "calibrated_softmax"),
        (("decision", "prediction", "selection"), "threshold"),
        (("input", "return_type"), "simple"),
        (("input", "return_unit"), "percent"),
    ],
)
def test_unknown_response_enum_values_are_retained(regime_cases, path, value):
    payload = copy.deepcopy(regime_cases[0]["response"])
    target = payload["result"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    parsed = SeriesIdentifyRegimeResponse.model_validate(payload)
    assert parsed.model_dump(exclude_unset=True) == payload
    current = parsed.result
    for key in path:
        current = getattr(current, key)
    assert current == value


def test_unknown_crisis_reason_is_retained(regime_cases):
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"]["crisis"] = {"status": "unavailable", "reason_code": "future_reason"}
    parsed = SeriesIdentifyRegimeResponse.model_validate(payload)
    assert parsed.result.crisis.reason_code == "future_reason"


def test_crisis_score_contract_and_provenance_are_typed(regime_cases):
    result = SeriesIdentifyRegimeResponse.model_validate(regime_cases[0]["response"]).result
    assert isinstance(result.crisis_score_contract, models.RegimeCrisisScoreContract)
    assert isinstance(result.provenance.crisis, models.RegimeCrisisProvenance)
    assert isinstance(result.provenance.volatility_label, models.RegimeVolatilityLabelProvenance)
    bad = copy.deepcopy(regime_cases[0]["response"])
    bad["result"]["provenance"]["model_sha256"] = "not-a-digest"
    with pytest.raises(ValidationError):
        SeriesIdentifyRegimeResponse.model_validate(bad)
