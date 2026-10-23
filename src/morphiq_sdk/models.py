"""Pricing wire models for the reviewed HTTP contract; no pricing logic lives here."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, PrivateAttr

ExerciseStyle = Literal["european", "american"]
OptionType = Literal["call", "put"]
PricingModel = Literal[
    "auto", "black_scholes_merton", "bjerksund_stensland_2002", "bjerksund_stensland_1993"
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class DividendEvent(_Request):
    """Cash per share at an ex-dividend time expressed in years from valuation."""

    ex_time_years: FiniteFloat
    cash_amount: FiniteFloat


class PriceRequest(_Request):
    """Option inputs. Rates, yield and volatility are decimals; time is in years.

    Numeric/model-domain validation belongs to the service. The SDK rejects
    malformed wire types and non-finite values without clamping or repricing.
    """

    exercise_style: ExerciseStyle
    option_type: OptionType
    spot: FiniteFloat
    strike: FiniteFloat
    time_to_expiry_years: FiniteFloat
    risk_free_rate: FiniteFloat
    dividend_yield: FiniteFloat
    volatility: FiniteFloat
    pricing_model: PricingModel = "auto"
    model_version: str | None = None
    dividend_schedule: list[DividendEvent] = Field(default_factory=list, max_length=16)

    def to_wire(self) -> dict[str, Any]:
        """Preserve optional-field omission and explicit null/empty values."""
        result = self.model_dump(mode="json", exclude_unset=True)
        # This required wire field has a convenience default in Python.
        result["pricing_model"] = self.pricing_model
        return result


class _Response(BaseModel):
    # Retain additive fields. A new resolved model name must not break decoding.
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)


class EngineIdentity(_Response):
    name: str
    version: str
    revision: str


class PolicyMetadata(_Response):
    snapshot_id: str
    revision: str
    plan: str
    records: list[str]


class _CommercialMetadata(_Response):
    fcu_quoted: int | None = Field(default=None, ge=0)
    fcu_charged: int | None = Field(default=None, ge=0)
    fcu_schedule_id: str | None = None
    fcu_schedule_version: str | None = None
    policy: PolicyMetadata | None = None
    remaining_fcu_instance_estimate: int | None = Field(default=None, ge=0)
    budget_period: str | None = None
    budget_reset_at: str | None = None


class ResponseMetadata(_CommercialMetadata):
    """Server provenance and optional commercial CU evidence.

    ``units_charged`` is an internal compute weight, not a commercial CU charge.
    Missing ``fcu_charged`` means unreported, not zero.
    """

    request_id: str
    api_version: str
    engine_version: str
    engines: list[EngineIdentity]
    units_charged: int = Field(ge=0)
    compute_schedule_version: str


class ServiceErrorMetadata(_CommercialMetadata):
    request_id: str
    api_version: str
    service_version: str


class PriceResult(_Response):
    price: FiniteFloat
    exercise_style: ExerciseStyle
    option_type: OptionType
    pricing_model: str
    model_version: str


class PriceResponse(_Response):
    result: PriceResult
    metadata: ResponseMetadata
    _raw_body: bytes = PrivateAttr(default=b"")
    _headers: dict[str, str] = PrivateAttr(default_factory=dict)

    @property
    def raw_body(self) -> bytes:
        """JSON response bytes, with any reflected API key redacted."""
        return self._raw_body

    @property
    def headers(self) -> dict[str, str]:
        """HTTP response headers without retaining a credential-bearing request."""
        return self._headers.copy()


class ErrorDetails(_Response):
    code: str
    message: str
    field: str | None = None


class ErrorEnvelope(_Response):
    error: ErrorDetails
    metadata: ResponseMetadata | ServiceErrorMetadata
