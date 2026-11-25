import hashlib
import json
import re
import typing
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from morphiq_sdk import client as client_module
from morphiq_sdk import models

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())
SCHEMAS = SCHEMA["components"]["schemas"]
PROVENANCE = json.loads((ROOT / "contracts/provenance.json").read_text())


def _properties(name):
    schema = SCHEMAS[name]
    if "properties" in schema:
        return schema["properties"]
    properties = {}
    for part in schema.get("allOf", []):
        if "$ref" in part:
            properties.update(_properties(part["$ref"].rsplit("/", 1)[1]))
        properties.update(part.get("properties", {}))
    return properties


def _model_named(name):
    candidate = getattr(models, name, None)
    return candidate if isinstance(candidate, type) and issubclass(candidate, BaseModel) else None


def test_snapshot_digest_version_and_operations():
    artifact = (ROOT / "contracts/openapi.json").read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == PROVENANCE["sha256"]
    assert SCHEMA["info"]["version"] == PROVENANCE["contract_version"]
    served = {
        f"{method.upper()} {path}"
        for path, operations in SCHEMA["paths"].items()
        if path.startswith("/v1/")
        for method in operations
    }
    covered = set(PROVENANCE["covered_operations"])
    # Every served operation is either covered or explicitly listed as not covered.
    assert covered | set(PROVENANCE["uncovered_operations"]) == served
    assert not covered & set(PROVENANCE["uncovered_operations"])


def test_every_covered_object_schema_has_a_matching_model():
    checked = []
    for name, schema in SCHEMAS.items():
        if "enum" in schema or "oneOf" in schema:
            continue
        # Batch items are BatchSuccess/BatchFailure; the health body is not an SDK type.
        if name in ("StatusResponse", "ScenarioItem") or re.fullmatch(r"OptionsBatch\w+Item", name):
            continue
        model = _model_named(name)
        assert model is not None, f"no SDK model for schema {name}"
        assert set(model.model_fields) == set(_properties(name)), name
        checked.append(name)
    assert len(checked) > 50


def test_canonical_operation_ids_match_the_quote_contract():
    quotable = {
        variant["properties"]["operation"]["enum"][0]
        for variant in SCHEMAS["RateCardQuoteRequest"]["oneOf"]
    }
    assert set(client_module._OPERATION_IDS.values()) == quotable
    for operation in client_module._OPERATION_IDS.values():
        collection, method = operation.split(".")
        path = f"/v1/{collection.replace('_', '-')}:{method.replace('_', '-')}"
        assert f"POST {path}" in PROVENANCE["covered_operations"], operation


@pytest.mark.parametrize(
    "alias,schema",
    [
        (models.PricingModel, "PricingModel"),
        (models.ResolvedPricingModel, "ResolvedPricingModel"),
        (models.ExerciseStyle, "ExerciseStyle"),
        (models.OptionType, "OptionType"),
        (models.ResidualBasis, "ResidualBasis"),
        (models.RegimeDecisionLabel, "RegimeDecisionLabel"),
        (models.RegimeDirectionLabel, "RegimeDirectionLabel"),
        (models.RegimeStateLabel, "RegimeStateLabel"),
        (models.RegimeVolatilityLabel, "RegimeVolatilityLabel"),
        (models.RegimeTarget, "RegimeTarget"),
        (models.RegimeCrisisUnavailableReason, "RegimeCrisisUnavailableReason"),
    ],
)
def test_known_enum_values_match_contract(alias, schema):
    assert set(typing.get_args(alias)) == set(SCHEMAS[schema]["enum"])


def _validate(name, value):
    Draft202012Validator({"$ref": f"#/components/schemas/{name}", **SCHEMA}).validate(value)


@pytest.mark.parametrize(
    "fixture,request_model,response_schema",
    [
        ("pricing", models.OptionsPriceRequest, "OptionsPriceResponse"),
        ("greeks", models.OptionsGreeksRequest, "OptionsGreeksResponse"),
        ("standard_greeks", models.OptionsStandardGreeksRequest, "OptionsStandardGreeksResponse"),
        (
            "implied_volatility",
            models.OptionsImpliedVolatilityRequest,
            "OptionsImpliedVolatilityResponse",
        ),
        ("implied_greeks", models.OptionsImpliedGreeksRequest, "OptionsImpliedGreeksResponse"),
        ("regime", models.SeriesIdentifyRegimeRequest, "SeriesIdentifyRegimeResponse"),
    ],
)
def test_native_fixtures_and_serialized_requests_match_contract(
    fixture, request_model, response_schema
):
    cases = json.loads((ROOT / f"tests/fixtures/{fixture}.json").read_text())["cases"]
    for case in cases:
        wire = request_model.model_validate(case["request"]).to_wire()
        assert wire == case["request"]
        _validate(request_model.__name__, wire)
        _validate(response_schema, case["response"])
        parsed = getattr(models, response_schema).model_validate(case["response"])
        assert parsed.model_dump(exclude_unset=True) == case["response"]


def test_batch_fixtures_match_contract(batch_cases):
    names = {
        "/v1/options:batch-price": "OptionsBatchPrice",
        "/v1/options:batch-greeks": "OptionsBatchGreeks",
        "/v1/options:batch-implied-volatility": "OptionsBatchImpliedVolatility",
        "/v1/options:batch-implied-greeks": "OptionsBatchImpliedGreeks",
    }
    for case in batch_cases:
        name = names[case["path"]]
        request = getattr(models, f"{name}Request").model_validate(case["request"])
        assert request.to_wire() == case["request"]
        # Some items deliberately break the request schema to record per-item problems.
        _validate(f"{name}Response", case["response"])
        parsed = getattr(models, f"{name}Response").model_validate(case["response"])
        assert parsed.model_dump(exclude_unset=True) == case["response"]


def test_model_catalog_fixture_matches_contract():
    catalog = json.loads((ROOT / "tests/fixtures/models.json").read_text())
    _validate("ModelsListResponse", catalog)
    parsed = models.ModelsListResponse.model_validate(catalog)
    assert parsed.model_dump(exclude_unset=True) == catalog
