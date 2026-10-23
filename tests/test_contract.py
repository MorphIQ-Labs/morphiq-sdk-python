import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from morphiq_sdk.models import (
    DividendEvent,
    EngineIdentity,
    ErrorDetails,
    PolicyMetadata,
    PriceRequest,
    PriceResponse,
    PriceResult,
    ResponseMetadata,
    ServiceErrorMetadata,
)

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_digest_version_and_route():
    artifact = (ROOT / "contracts/openapi.json").read_bytes()
    provenance = json.loads((ROOT / "contracts/provenance.json").read_text())
    assert hashlib.sha256(artifact).hexdigest() == provenance["sha256"]
    schema = json.loads(artifact)
    assert schema["info"]["version"] == provenance["contract_version"]
    operation = schema["paths"]["/v1/price"]["post"]
    assert operation["operationId"] == "priceOption"
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PriceRequest"
    )


def test_models_cover_pricing_wire_fields():
    schemas = json.loads((ROOT / "contracts/openapi.json").read_text())["components"]["schemas"]
    for model, name in [
        (PriceRequest, "PriceRequest"),
        (PriceResult, "PriceResult"),
        (PriceResponse, "PriceResponse"),
        (ResponseMetadata, "ResponseMetadata"),
        (ServiceErrorMetadata, "ServiceErrorMetadata"),
        (DividendEvent, "DividendEvent"),
        (EngineIdentity, "EngineIdentity"),
        (PolicyMetadata, "PolicyResponseMetadata"),
        (ErrorDetails, "ErrorBody"),
    ]:
        assert set(model.model_fields) == set(schemas[name]["properties"])


def test_native_fixtures_and_serialized_requests_match_contract(cases):
    schema = json.loads((ROOT / "contracts/openapi.json").read_text())
    for case in cases:
        for name, value in [
            ("PriceRequest", PriceRequest(**case["request"]).to_wire()),
            ("PriceResponse", case["response"]),
        ]:
            Draft202012Validator(
                {"$ref": f"#/components/schemas/{name}", "components": schema["components"]}
            ).validate(value)
