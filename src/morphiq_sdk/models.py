"""API wire models for the reviewed HTTP contract; no pricing logic lives here."""

from typing import Annotated, Any, Generic, Literal, TypeVar

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
        """Validate current inputs, preserving omission and explicit null/empty values."""
        values = self.model_dump(exclude={"dividend_schedule"}, exclude_unset=True)
        # Freezing the model does not freeze lists or track their in-place edits.
        # Include nonempty schedules and revalidate edits before JSON serialization.
        if self.dividend_schedule or "dividend_schedule" in self.model_fields_set:
            values["dividend_schedule"] = self.dividend_schedule
        validated = type(self).model_validate(values)
        result = validated.model_dump(mode="json", exclude_unset=True)
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


class _EvidenceResponse(_Response):
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


class PriceResponse(_EvidenceResponse):
    result: PriceResult
    metadata: ResponseMetadata


class RegimeRequest(_Request):
    """Comparable positive prices, oldest first; no sampling interval is assumed.

    V1 requires 512 prices and consumes the latest 507. Supply split-adjusted
    closes without cash-dividend total-return adjustment. The service validates
    timestamp/domain semantics and request byte limits; no cropping occurs here.
    """

    prices: list[Annotated[FiniteFloat, Field(gt=0)]] = Field(min_length=512)
    as_of: str | None = Field(default=None, max_length=64)

    def to_wire(self) -> dict[str, Any]:
        # Revalidate mutable price lists without dropping explicit null timestamps.
        values = self.model_dump(exclude={"prices"}, exclude_unset=True)
        values["prices"] = self.prices
        validated = type(self).model_validate(values)
        return validated.model_dump(mode="json", exclude_unset=True)


RegimeDecisionLabel = Literal["not_eligible", "supported", "unsupported", "unresolved"]
RegimeDirectionLabel = Literal["UP", "DOWN", "NEUTRAL"]
RegimeStateLabel = Literal["LOWER_VOL", "HIGHER_VOL"]
_Label = TypeVar("_Label")
_Prediction = TypeVar("_Prediction")


class RegimeScore(_Response, Generic[_Label]):
    label: _Label
    value: FiniteFloat = Field(ge=0, le=1)


class RegimePrediction(_Response, Generic[_Label]):
    label: _Label
    scores: list[RegimeScore[_Label]]
    selection: Literal["argmax"]


class RegimeDecisionPrediction(RegimePrediction[RegimeDecisionLabel]):
    scores: list[RegimeScore[RegimeDecisionLabel]] = Field(min_length=4, max_length=4)


class RegimeDirectionPrediction(RegimePrediction[RegimeDirectionLabel]):
    scores: list[RegimeScore[RegimeDirectionLabel]] = Field(min_length=3, max_length=3)


class RegimeStatePrediction(RegimePrediction[RegimeStateLabel]):
    scores: list[RegimeScore[RegimeStateLabel]] = Field(min_length=2, max_length=2)


class RegimeBasis(_Response):
    target: Literal[
        "reference_procedure_outcome",
        "selected_state_tendency",
        "filtered_scale_order_membership",
    ]


class RegimeAvailable(_Response, Generic[_Prediction]):
    status: Literal["available"]
    basis: RegimeBasis
    prediction: _Prediction


class RegimeNotApplicable(_Response):
    status: Literal["not_applicable"]
    basis: RegimeBasis
    prediction: None
    reason_code: Literal["predicted_not_eligible"]


class RegimeUnavailable(_Response):
    status: Literal["unavailable"]
    basis: RegimeBasis
    prediction: None
    reason_code: Literal["prediction_unavailable"]


class RegimeScoreContract(_Response):
    kind: Literal["uncalibrated_softmax"]
    version: str
    sum_tolerance: FiniteFloat


class RegimeResult(_Response):
    score_contract: RegimeScoreContract
    decision: Annotated[
        RegimeAvailable[RegimeDecisionPrediction] | RegimeNotApplicable | RegimeUnavailable,
        Field(discriminator="status"),
    ]
    direction: Annotated[
        RegimeAvailable[RegimeDirectionPrediction] | RegimeNotApplicable | RegimeUnavailable,
        Field(discriminator="status"),
    ]
    state: Annotated[
        RegimeAvailable[RegimeStatePrediction] | RegimeNotApplicable | RegimeUnavailable,
        Field(discriminator="status"),
    ]


class RegimeProvenance(_Response):
    model_id: str
    model_status: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing: str
    teacher_executed: bool


class RegimeConsumedPriceRange(_Response):
    start_index: int = Field(ge=0)
    end_index_exclusive: int = Field(ge=0)


class RegimeMetadata(_CommercialMetadata):
    response_contract_version: str
    request_id: str
    api_version: str
    service_version: str
    engines: list[EngineIdentity]
    provenance: RegimeProvenance
    received_price_count: int = Field(ge=0)
    window_price_count: int = Field(ge=0)
    price_count: int = Field(ge=0)
    return_count: int = Field(ge=0)
    consumed_price_range: RegimeConsumedPriceRange
    observation_index: int = Field(ge=0)
    input_price_index: int = Field(ge=0)
    as_of: str | None
    return_type: Literal["log"]
    return_unit: Literal["fraction"]
    inference_time_us: int = Field(ge=0)
    all_prices_consumed: bool


class RegimeResponse(_EvidenceResponse):
    result: RegimeResult
    metadata: RegimeMetadata


class ErrorDetails(_Response):
    code: str
    message: str
    field: str | None = None


class ErrorEnvelope(_Response):
    error: ErrorDetails
    metadata: ResponseMetadata | ServiceErrorMetadata
