"""Typed production additions, with explicit legacy response compatibility."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from morphiq_sdk import RegimeResponse, models

SCHEMA = json.loads((Path(__file__).parents[1] / "contracts/openapi.json").read_text())


@pytest.mark.parametrize(
    "name",
    [
        "RegimeVolatilityBasis",
        "RegimeVolatilityPrediction",
        "RegimeCrisisScoreContract",
        "RegimeCrisisProvenance",
        "RegimeVolatilityLabelProvenance",
        "CostRate",
        "CostLine",
        "CostBreakdown",
        "CostSchedule",
    ],
)
def test_production_field_coverage(name):
    assert set(getattr(models, name).model_fields) == set(
        SCHEMA["components"]["schemas"][name]["properties"]
    )


@pytest.mark.parametrize(
    "crisis",
    [
        {"status": "crisis", "score": 2.75, "episode_start_price_index": 500},
        {"status": "not_crisis", "score": -3.5, "episode_start_price_index": None},
        {
            "status": "unavailable",
            "score": None,
            "episode_start_price_index": None,
            "reason_code": "short_reference",
        },
        {
            "status": "unavailable",
            "score": None,
            "episode_start_price_index": None,
            "reason_code": "degenerate_reference",
        },
    ],
)
@pytest.mark.parametrize(
    "volatility",
    [
        *[
            {"status": "available", "prediction": {"label": label}}
            for label in ["low", "high", "crisis"]
        ],
        {"status": "not_applicable", "prediction": None, "reason_code": "predicted_not_eligible"},
        {"status": "unavailable", "prediction": None, "reason_code": "prediction_unavailable"},
    ],
)
def test_regime_variants_preserve_wire_evidence(regime_cases, crisis, volatility):
    # Test wire variants independently; the client does not recompute the server's rule.
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"]["crisis"] = crisis
    payload["result"]["volatility"] = {**volatility, "basis": {"target": "current_volatility"}}
    Draft202012Validator(
        {
            "$ref": "#/components/schemas/RegimeResponse",
            "components": SCHEMA["components"],
        }
    ).validate(payload)
    parsed = RegimeResponse.model_validate(payload)
    assert parsed.model_dump(exclude_unset=True) == payload
    assert parsed.result.crisis.status == crisis["status"]
    assert parsed.result.volatility.status == volatility["status"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("crisis", {"status": "crisis", "score": 2, "episode_start_price_index": None}),
        (
            "crisis",
            {"status": "not_crisis", "score": float("inf"), "episode_start_price_index": None},
        ),
        (
            "crisis",
            {
                "status": "unavailable",
                "score": 0,
                "episode_start_price_index": None,
                "reason_code": "short_reference",
            },
        ),
        (
            "volatility",
            {
                "status": "available",
                "basis": {"target": "current_volatility"},
                "prediction": {"label": "LOWER_VOL"},
            },
        ),
    ],
)
def test_invalid_production_states_are_rejected(regime_cases, field, value):
    payload = copy.deepcopy(regime_cases[0]["response"])
    payload["result"][field] = value
    with pytest.raises(ValidationError):
        RegimeResponse.model_validate(payload)


def test_old_regime_response_remains_readable_without_inventing_results(regime_cases):
    payload = copy.deepcopy(regime_cases[0]["response"])
    for key in ["volatility", "crisis", "crisis_score_contract"]:
        del payload["result"][key]
    del payload["metadata"]["crisis_time_us"]
    for key in ["crisis", "volatility_label"]:
        del payload["metadata"]["provenance"][key]
    parsed = RegimeResponse.model_validate(payload)
    assert parsed.result.crisis is None
    assert parsed.result.volatility is None
    assert parsed.metadata.crisis_time_us is None
    assert parsed.model_dump(exclude_unset=True) == payload
