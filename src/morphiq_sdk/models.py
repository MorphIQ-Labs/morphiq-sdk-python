"""API wire models for the reviewed HTTP contract; no pricing logic lives here.

Class names follow the contract's schema names (``OptionsPriceRequest``,
``ResponseMetadata``, ``Problem``) so each model can be checked against the
pinned OpenAPI document. Requests are closed: unknown fields and enum values
are rejected before sending. Responses are open: additive fields are retained,
and an enum value or variant this SDK does not know is kept as a plain string or
an ``Unrecognized*`` model instead of failing the whole response.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    FiniteFloat,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    Tag,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

ExerciseStyle = Literal["european", "american"]
OptionType = Literal["call", "put"]
PricingModel = Literal[
    "auto",
    "black_scholes_merton",
    "bjerksund_stensland_1993",
    "black_scholes_merton_qdfp",
    "black_scholes_merton_fd",
]
"""Model selectors accepted in requests (``model.id``)."""

ResolvedPricingModel = Literal[
    "black_scholes_merton",
    "bjerksund_stensland_1993",
    "black_scholes_merton_qdfp",
    "black_scholes_merton_fd",
]
"""Model ids the pinned contract can report; responses may carry newer ids."""

ResidualBasis = Literal["forward_normalised_price", "option_price"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    def to_wire(self) -> dict[str, Any]:
        """Revalidate current inputs and return the JSON body.

        Freezing a model does not freeze its lists, so in-place edits are
        validated again here. Absent optional members are omitted, never null.
        """
        # In-place edits may hold plain dicts; they are revalidated, not serialized as-is.
        validated = type(self).model_validate(self.model_dump(warnings=False))
        return validated.model_dump(mode="json", exclude_none=True)


class DividendEvent(_Request):
    """Cash per share at an ex-dividend time expressed in years from valuation."""

    ex_time_years: FiniteFloat
    cash_amount: FiniteFloat


class Option(_Request):
    """Contract terms: option type, exercise style, strike and time to expiry in years."""

    type: OptionType
    exercise_style: ExerciseStyle
    strike: FiniteFloat
    time_to_expiry_years: FiniteFloat


class Market(_Request):
    """The underlying's market. Rates and yield are continuously compounded decimals.

    ``dividends`` holds discrete cash dividends; only the cash-dividend model
    accepts a nonempty schedule. An empty schedule is omitted from the request.
    """

    spot: FiniteFloat
    risk_free_rate: FiniteFloat
    dividend_yield: FiniteFloat
    dividends: list[DividendEvent] = Field(default_factory=list, max_length=16)

    @model_serializer(mode="wrap")
    def _omit_empty_dividends(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict) and not data.get("dividends"):
            data.pop("dividends", None)
        return data


class ModelSelection(_Request):
    """Model selector; ``auto`` lets the service choose. ``version`` pins an algorithm."""

    id: PricingModel = "auto"
    version: str | None = None


class _ForwardOptionRequest(_Request):
    """Option, market, a supplied annual volatility (decimal) and the model selection.

    Numeric/model-domain validation belongs to the service. The SDK rejects
    malformed wire types and non-finite values without clamping or repricing.
    """

    option: Option
    market: Market
    volatility: FiniteFloat
    model: ModelSelection = Field(default_factory=ModelSelection)


class _InverseOptionRequest(_Request):
    """Option, market, a per-share market price and the model selection.

    Volatility is an output, not a request field. The service validates premiums
    and numerical domains without SDK-side clamping or local solving.
    """

    option: Option
    market: Market
    market_price: FiniteFloat
    model: ModelSelection = Field(default_factory=ModelSelection)


class OptionsPriceRequest(_ForwardOptionRequest):
    """``options.price``: price an option at a supplied volatility."""


class OptionsGreeksRequest(_ForwardOptionRequest):
    """``options.greeks``: price and all ten Greeks at a supplied volatility."""


class OptionsStandardGreeksRequest(_ForwardOptionRequest):
    """``options.standard_greeks``: price and delta, gamma, theta, vega and rho."""


class OptionsImpliedVolatilityRequest(_InverseOptionRequest):
    """``options.implied_volatility``: solve volatility from an option premium."""


class OptionsImpliedGreeksRequest(_InverseOptionRequest):
    """``options.implied_greeks``: solve IV from a premium, then price and all ten Greeks."""


OptionRequest = (
    OptionsPriceRequest
    | OptionsGreeksRequest
    | OptionsStandardGreeksRequest
    | OptionsImpliedVolatilityRequest
    | OptionsImpliedGreeksRequest
)
_ItemType = TypeVar("_ItemType", bound=_Request)


class _BatchRequest(_Request, Generic[_ItemType]):
    # This is the reviewed wire limit, not an account/plan limit.
    items: list[_ItemType] = Field(min_length=1, max_length=100)

    def to_wire(self) -> dict[str, Any]:
        validated = type(self).model_validate({"items": self.items})
        return {"items": [item.to_wire() for item in validated.items]}


class OptionsBatchPriceRequest(_BatchRequest[OptionsPriceRequest]):
    """``options.batch_price``: one explicit batch of pricing requests in caller order."""


class OptionsBatchGreeksRequest(_BatchRequest[OptionsGreeksRequest]):
    """``options.batch_greeks``: one explicit batch of price-and-Greeks requests."""


class OptionsBatchStandardGreeksRequest(_BatchRequest[OptionsStandardGreeksRequest]):
    """``options.batch_standard_greeks``: one ordered batch of standard-Greeks requests."""


class OptionsBatchImpliedVolatilityRequest(_BatchRequest[OptionsImpliedVolatilityRequest]):
    """``options.batch_implied_volatility``: one explicit batch of IV solves."""


class OptionsBatchImpliedGreeksRequest(_BatchRequest[OptionsImpliedGreeksRequest]):
    """``options.batch_implied_greeks``: one explicit batch of implied-Greeks requests."""


class SeriesIdentifyRegimeRequest(_Request):
    """``series.identify_regime``: comparable positive prices, oldest first.

    V1 requires 512 prices and consumes the latest 507. Supply split-adjusted
    closes without cash-dividend total-return adjustment. No sampling interval is
    assumed. The service validates timestamp/domain semantics and request byte
    limits; no cropping occurs here.
    """

    prices: list[Annotated[FiniteFloat, Field(gt=0)]] = Field(min_length=512)
    as_of: str | None = Field(default=None, max_length=64)


# Responses -----------------------------------------------------------------


class _Response(BaseModel):
    # Retain additive fields. A new resolved model name must not break decoding.
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)


def _variant(field: str, known: Iterable[str]) -> Discriminator:
    """Select a union member by ``field``; unknown values select ``unrecognized``.

    Response enums may gain values. An unknown variant is retained with its
    wire members instead of failing the whole response.
    """
    names = frozenset(known)

    def pick(value: Any) -> str:
        tag = value.get(field) if isinstance(value, dict) else getattr(value, field, None)
        return tag if isinstance(tag, str) and tag in names else "unrecognized"

    return Discriminator(pick)


class Unrecognized(_Response):
    """A response variant this SDK version does not know. All wire members are kept."""

    status: str


class SolveTrialContext(_Response):
    """Where a target solve refused a level."""

    phase: Literal["domain_check", "search"] | str
    coordinate: str
    coordinate_value: FiniteFloat
    evaluations: int = Field(ge=0)


class Problem(_Response):
    """RFC 9457 problem details. ``code`` is the stable machine-readable reason."""

    type: str
    title: str
    status: int = Field(ge=0)
    detail: str
    code: str
    field: str | None = None
    solve_trial: SolveTrialContext | None = None


class ContractIdentity(_Response):
    """The served HTTP contract: its version label and exact document digest."""

    version: str
    sha256: str


class EngineIdentity(_Response):
    name: str
    version: str
    revision: str


class RateCardIdentity(_Response):
    id: str
    version: str


class BillingMetadata(_Response):
    """Commercial CU evidence. A missing ``charged_cu`` means unreported, not zero."""

    quoted_cu: int | None = Field(default=None, ge=0)
    charged_cu: int | None = Field(default=None, ge=0)
    rate_card: RateCardIdentity | None = None


class BudgetMetadata(_Response):
    period: str | None = None
    resets_at: str | None = None
    remaining_estimate_cu: int | None = Field(default=None, ge=0)


class PolicyMetadata(_Response):
    plan: str
    revision: str


class ResponseMetadata(_Response):
    """Shared metadata on every response, success or error.

    ``billing``, ``budget`` and ``policy`` are present on metered responses and
    omitted otherwise. ``engines`` is absent when no numerical engine was selected.
    """

    request_id: str
    service_version: str
    contract: ContractIdentity
    engines: list[EngineIdentity] | None = None
    billing: BillingMetadata | None = None
    budget: BudgetMetadata | None = None
    policy: PolicyMetadata | None = None

    @property
    def charged_cu(self) -> int | None:
        """``billing.charged_cu``; ``None`` means the charge was not reported."""
        return self.billing.charged_cu if self.billing is not None else None


class ErrorResponse(Problem):
    """A non-success response: the problem details plus the shared metadata."""

    metadata: ResponseMetadata


class ModelIdentity(_Response):
    """The resolved model and its exact algorithm pin."""

    id: ResolvedPricingModel | str
    version: str


class StandardGreeks(_Response):
    """Unscaled derivatives; omitted quantities have typed unavailable reasons.

    Time derivatives are per year, volatility/rate derivatives per unit.
    A resolved zero stays 0.0; unavailable quantities are never filled with zero.
    Use model_dump(exclude_unset=True) to preserve the original wire presence.
    """

    delta: FiniteFloat | None = None
    gamma: FiniteFloat | None = None
    theta: FiniteFloat | None = None
    vega: FiniteFloat | None = None
    rho: FiniteFloat | None = None
    unavailable: dict[str, Problem] = Field(default_factory=dict)

    @field_validator("*", mode="before")
    @classmethod
    def reject_null_quantity(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name != "unavailable" and value is None:
            raise ValueError("Unavailable Greeks must be omitted, not null")
        return value

    @model_validator(mode="after")
    def require_availability_evidence(self) -> StandardGreeks:
        for name in type(self).model_fields:
            if name == "unavailable":
                continue
            present = getattr(self, name) is not None
            explained = name in self.unavailable
            if present == explained:
                raise ValueError(f"{name} must have either a value or an unavailable reason")
        return self


class Greeks(StandardGreeks):
    """All ten derivatives, retaining partial results and unavailable reasons."""

    vanna: FiniteFloat | None = None
    volga: FiniteFloat | None = None
    charm: FiniteFloat | None = None
    veta: FiniteFloat | None = None
    color: FiniteFloat | None = None


class PriceResult(_Response):
    price: FiniteFloat
    model: ModelIdentity


class StandardGreeksResult(_Response):
    price: FiniteFloat
    greeks: StandardGreeks
    model: ModelIdentity


class GreeksResult(_Response):
    price: FiniteFloat
    greeks: Greeks
    model: ModelIdentity


class ImpliedVolatilityResult(_Response):
    """Unmodified solver diagnostics. Volatility is a decimal fraction.

    Known residual bases are ``forward_normalised_price`` and ``option_price``;
    retain future basis names without interpreting or converting their values.
    ``used_fallback`` describes the algorithm, not solution quality.
    """

    implied_volatility: FiniteFloat
    iterations: int = Field(ge=0)
    used_fallback: bool
    residual: FiniteFloat
    residual_basis: ResidualBasis | str
    model: ModelIdentity


class ImpliedGreeksResult(GreeksResult):
    """Price and Greeks at the solved IV; the nested solve has no separate charge."""

    implied_volatility: ImpliedVolatilityResult | None = None


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


class OptionsPriceResponse(_EvidenceResponse):
    result: PriceResult
    metadata: ResponseMetadata


class OptionsStandardGreeksResponse(_EvidenceResponse):
    result: StandardGreeksResult
    metadata: ResponseMetadata


class OptionsGreeksResponse(_EvidenceResponse):
    result: GreeksResult
    metadata: ResponseMetadata


class OptionsImpliedVolatilityResponse(_EvidenceResponse):
    result: ImpliedVolatilityResult
    metadata: ResponseMetadata


class OptionsImpliedGreeksResponse(_EvidenceResponse):
    result: ImpliedGreeksResult
    metadata: ResponseMetadata


_ResultType = TypeVar("_ResultType", bound=_Response)


class BatchSuccess(_Response, Generic[_ResultType]):
    index: int = Field(ge=0)
    status: Literal["success"]
    result: _ResultType


class BatchFailure(_Response):
    index: int = Field(ge=0)
    status: Literal["error"]
    error: Problem


class BatchUnrecognized(Unrecognized):
    """A batch outcome status this SDK version does not know."""

    index: int = Field(ge=0)


class _BatchResponse(_EvidenceResponse, Generic[_ResultType]):
    metadata: ResponseMetadata
    results: list[
        Annotated[
            Annotated[BatchSuccess[_ResultType], Tag("success")]
            | Annotated[BatchFailure, Tag("error")]
            | Annotated[BatchUnrecognized, Tag("unrecognized")],
            _variant("status", ["success", "error"]),
        ]
    ]


class OptionsBatchPriceResponse(_BatchResponse[PriceResult]):
    """Ordered outcomes and one metadata/charge block for the entire batch."""


class OptionsBatchStandardGreeksResponse(_BatchResponse[StandardGreeksResult]):
    """Ordered standard-Greeks outcomes with batch-level charge evidence."""


class OptionsBatchGreeksResponse(_BatchResponse[GreeksResult]):
    """Ordered Greeks outcomes and batch-level charge evidence."""


class OptionsBatchImpliedVolatilityResponse(_BatchResponse[ImpliedVolatilityResult]):
    """Ordered IV outcomes and batch-level charge evidence."""


class OptionsBatchImpliedGreeksResponse(_BatchResponse[ImpliedGreeksResult]):
    """Ordered implied-Greeks outcomes and batch-level charge evidence."""


# Regime ---------------------------------------------------------------------

RegimeDecisionLabel = Literal["not_eligible", "supported", "unsupported", "unresolved"]
RegimeDirectionLabel = Literal["up", "down", "neutral"]
RegimeStateLabel = Literal["lower_vol", "higher_vol"]
RegimeVolatilityLabel = Literal["low", "high", "crisis"]
RegimeTarget = Literal[
    "reference_procedure_outcome",
    "selected_state_tendency",
    "filtered_scale_order_membership",
]
RegimeCrisisUnavailableReason = Literal["short_reference", "degenerate_reference"]
_HEAD_STATUSES = ["available", "not_applicable", "unavailable"]


class RegimeDecisionScore(_Response):
    label: RegimeDecisionLabel | str
    value: FiniteFloat = Field(ge=0, le=1)


class RegimeDirectionScore(_Response):
    label: RegimeDirectionLabel | str
    value: FiniteFloat = Field(ge=0, le=1)


class RegimeStateScore(_Response):
    label: RegimeStateLabel | str
    value: FiniteFloat = Field(ge=0, le=1)


# Score lists keep the contract's minimum; a label added later may lengthen them.
class RegimeDecisionPrediction(_Response):
    label: RegimeDecisionLabel | str
    scores: list[RegimeDecisionScore] = Field(min_length=4)
    selection: Literal["argmax"] | str


class RegimeDirectionPrediction(_Response):
    label: RegimeDirectionLabel | str
    scores: list[RegimeDirectionScore] = Field(min_length=3)
    selection: Literal["argmax"] | str


class RegimeStatePrediction(_Response):
    label: RegimeStateLabel | str
    scores: list[RegimeStateScore] = Field(min_length=2)
    selection: Literal["argmax"] | str


class RegimeBasis(_Response):
    target: RegimeTarget | str


_Prediction = TypeVar("_Prediction", bound=_Response)


class RegimeAvailable(_Response, Generic[_Prediction]):
    status: Literal["available"]
    basis: RegimeBasis
    prediction: _Prediction


class RegimeNotApplicable(_Response):
    """The head does not apply; ``prediction`` is omitted and ``reason_code`` says why."""

    status: Literal["not_applicable"]
    basis: RegimeBasis
    reason_code: Literal["predicted_not_eligible"] | str


class RegimeUnavailable(_Response):
    """No prediction is available; ``prediction`` is omitted and ``reason_code`` says why."""

    status: Literal["unavailable"]
    basis: RegimeBasis
    reason_code: Literal["prediction_unavailable"] | str


RegimeDecisionHead = Annotated[
    Annotated[RegimeAvailable[RegimeDecisionPrediction], Tag("available")]
    | Annotated[RegimeNotApplicable, Tag("not_applicable")]
    | Annotated[RegimeUnavailable, Tag("unavailable")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", _HEAD_STATUSES),
]
RegimeDirectionHead = Annotated[
    Annotated[RegimeAvailable[RegimeDirectionPrediction], Tag("available")]
    | Annotated[RegimeNotApplicable, Tag("not_applicable")]
    | Annotated[RegimeUnavailable, Tag("unavailable")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", _HEAD_STATUSES),
]
RegimeStateHead = Annotated[
    Annotated[RegimeAvailable[RegimeStatePrediction], Tag("available")]
    | Annotated[RegimeNotApplicable, Tag("not_applicable")]
    | Annotated[RegimeUnavailable, Tag("unavailable")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", _HEAD_STATUSES),
]


class RegimeScoreContract(_Response):
    kind: Literal["uncalibrated_softmax"] | str
    version: str
    sum_tolerance: FiniteFloat


class RegimeVolatilityBasis(_Response):
    target: Literal["current_volatility"] | str


class RegimeVolatilityPrediction(_Response):
    label: RegimeVolatilityLabel | str


class RegimeVolatilityAvailable(_Response):
    status: Literal["available"]
    basis: RegimeVolatilityBasis
    prediction: RegimeVolatilityPrediction


class RegimeVolatilityNotApplicable(_Response):
    status: Literal["not_applicable"]
    basis: RegimeVolatilityBasis
    reason_code: Literal["predicted_not_eligible"] | str


class RegimeVolatilityUnavailable(_Response):
    status: Literal["unavailable"]
    basis: RegimeVolatilityBasis
    reason_code: Literal["prediction_unavailable"] | str


RegimeVolatilityHead = Annotated[
    Annotated[RegimeVolatilityAvailable, Tag("available")]
    | Annotated[RegimeVolatilityNotApplicable, Tag("not_applicable")]
    | Annotated[RegimeVolatilityUnavailable, Tag("unavailable")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", _HEAD_STATUSES),
]


class RegimeCrisisActive(_Response):
    status: Literal["crisis"]
    score: FiniteFloat
    episode_start_price_index: int = Field(ge=0)


class RegimeNotCrisis(_Response):
    """No crisis; ``episode_start_price_index`` is omitted."""

    status: Literal["not_crisis"]
    score: FiniteFloat


class RegimeCrisisUnavailable(_Response):
    """No crisis score; ``score`` and ``episode_start_price_index`` are omitted."""

    status: Literal["unavailable"]
    reason_code: RegimeCrisisUnavailableReason | str


RegimeCrisis = Annotated[
    Annotated[RegimeCrisisActive, Tag("crisis")]
    | Annotated[RegimeNotCrisis, Tag("not_crisis")]
    | Annotated[RegimeCrisisUnavailable, Tag("unavailable")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", ["crisis", "not_crisis", "unavailable"]),
]


class RegimeCrisisScoreContract(_Response):
    """Unbounded linear readout; neither a probability nor a softmax score."""

    kind: Literal["linear_readout"] | str
    version: str
    theta_in: FiniteFloat
    theta_out: FiniteFloat


class RegimeCrisisProvenance(_Response):
    method: str
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    features: str


class RegimeVolatilityLabelProvenance(_Response):
    method: str
    model_id: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crisis_method: str
    crisis_parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegimeProvenance(_Response):
    model_id: str
    model_status: str
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing: str
    teacher_executed: bool
    volatility_label: RegimeVolatilityLabelProvenance
    crisis: RegimeCrisisProvenance


class RegimeConsumedPriceRange(_Response):
    start_index: int = Field(ge=0)
    end_index_exclusive: int = Field(ge=0)


class RegimeInput(_Response):
    """Window and return facts. ``as_of`` is present only when the request supplied it."""

    received_price_count: int = Field(ge=0)
    window_price_count: int = Field(ge=0)
    price_count: int = Field(ge=0)
    return_count: int = Field(ge=0)
    consumed_price_range: RegimeConsumedPriceRange
    observation_index: int = Field(ge=0)
    input_price_index: int = Field(ge=0)
    all_prices_consumed: bool
    return_type: Literal["log"] | str
    return_unit: Literal["fraction"] | str
    as_of: str | None = None


class RegimeTiming(_Response):
    """Server-side inference times in microseconds."""

    inference_us: int = Field(ge=0)
    crisis_us: int = Field(ge=0)


class RegimeEstimates(_Response):
    score_contract: RegimeScoreContract
    decision: RegimeDecisionHead
    direction: RegimeDirectionHead
    state: RegimeStateHead
    volatility: RegimeVolatilityHead
    crisis_score_contract: RegimeCrisisScoreContract
    crisis: RegimeCrisis


class RegimeResult(RegimeEstimates):
    """The estimates plus input facts, timing, provenance and the regime contract version."""

    response_contract_version: str
    provenance: RegimeProvenance
    input: RegimeInput
    timing: RegimeTiming


class SeriesIdentifyRegimeResponse(_EvidenceResponse):
    result: RegimeResult
    metadata: ResponseMetadata


# Rate card -----------------------------------------------------------------


class Rate(_Response):
    """One published rate; its presence does not establish entitlement or availability."""

    rate_class: str
    model: str
    billing_unit: str
    cu_per_unit: int = Field(ge=0)
    max_discrete_dividends: int = Field(ge=0)


class RateCard(_Response):
    schedule_id: str
    schedule_version: str
    record_version: int = Field(ge=0)
    policy_revision: str
    effective_from: str
    effective_until: str | None = None
    fixed_request_cu: int = Field(ge=0)
    minimum_charge_cu: int = Field(ge=0)
    rounding: str
    failure_charging: str
    rates: list[Rate]


class QuoteLine(_Response):
    rate_class: str
    model: str
    billing_unit: str
    quantity: int = Field(ge=0)
    cu_per_unit: int = Field(ge=0)
    variable_cu: int = Field(ge=0)


class Quote(_Response):
    total_cu: int = Field(ge=0)
    fixed_cu: int = Field(ge=0)
    variable_cu: int = Field(ge=0)
    minimum_charge_cu: int = Field(ge=0)
    lines: list[QuoteLine]


class QuotedModel(_Response):
    model: str
    quantity: int = Field(ge=0)


class RateCardGetResponse(_EvidenceResponse):
    """Your active rate card. Reading it executes nothing and charges no CUs."""

    schedule: RateCard
    metadata: ResponseMetadata


class RateCardQuoteResponse(_EvidenceResponse):
    """Exact conditional quote. No funds, execution capacity, or price are reserved."""

    quote: Quote
    resolved_models: list[QuotedModel]
    metadata: ResponseMetadata


# Model catalog --------------------------------------------------------------


class ModelConstraint(_Response):
    quantity: str
    description: str
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None


class ValidityInterval(_Response):
    kind: Literal["interval"]
    input: str
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None


class ValidityCondition(_Response):
    kind: Literal["condition"]
    name: str
    formula: str


class UnrecognizedValidityBound(_Response):
    """A validity bound kind this SDK version does not know. All wire members are kept."""

    kind: str


ValidityBound = Annotated[
    Annotated[ValidityInterval, Tag("interval")]
    | Annotated[ValidityCondition, Tag("condition")]
    | Annotated[UnrecognizedValidityBound, Tag("unrecognized")],
    _variant("kind", ["interval", "condition"]),
]


class ValidityTolerance(_Response):
    relative: FiniteFloat
    absolute: FiniteFloat
    absolute_unit: str


class QuantityValidity(_Response):
    """The engine's stated validity contract for one served quantity."""

    quantity: str
    status: Literal["validated", "not_stated", "not_offered"] | str
    criterion: Literal["strict", "approximation", "inverse_of_price"] | str | None = None
    tolerance: ValidityTolerance | None = None
    region: list[ValidityBound] | None = None
    outside: str | None = None


class ModelDescriptor(_Response):
    id: ResolvedPricingModel | str
    name: str
    version: str
    model_version: str
    underlying_model: str
    method: str
    exercise_styles: list[ExerciseStyle | str]
    dividend_support: list[str]
    operations: list[str]
    greeks: list[str]
    guidance: str
    constraints: list[ModelConstraint]
    validity: list[QuantityValidity]
    notes: str


class ModelsListResponse(_EvidenceResponse):
    """Public compiled capabilities; account entitlements and rates are separate."""

    models: list[ModelDescriptor]
    engines: list[EngineIdentity]
    greek_units: dict[str, str]
    validity_symbols: dict[str, str]
