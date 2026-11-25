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


# Scenario and book wire types, from the pinned API 0.10.0 contract.
# Input domains and account limits remain server-owned; no client repricing.


class UnrecognizedKind(_Response):
    """An unknown kind-tagged response, preserved without interpretation."""

    kind: str


class BookPosition(_Request):
    """One held option: signed quantity of contracts, each worth `multiplier`
    underlying units. Its market is the request's `markets[underlying]`; its
    volatility and model are its own. Net value is quantity × multiplier ×
    option price, in the request `currency`."""

    id: str = Field(pattern="^[A-Za-z0-9._:/-]{1,64}$")
    model: ModelSelection
    multiplier: FiniteFloat
    option: Option
    quantity: FiniteFloat
    underlying: str = Field(pattern="^[A-Za-z0-9._:/-]{1,64}$")
    volatility: FiniteFloat


class BookStrategy(_Request):
    """A named grouping of positions in one book. Strategies may overlap, so strategy
    totals are not additive; book totals always sum positions once."""

    id: str = Field(pattern="^[A-Za-z0-9._:/-]{1,64}$")
    position_ids: list[str] = Field(max_length=50)


class Book(_Request):
    """A book of positions and its optional strategies."""

    id: str = Field(pattern="^[A-Za-z0-9._:/-]{1,64}$")
    positions: list[BookPosition] = Field(max_length=50)
    strategies: list[BookStrategy] | None = Field(default=None, max_length=64)


class BookShockSpotRelative(_Request):
    """Multiply the underlying by 1 + relative; relative must exceed -1."""

    kind: Literal["spot_relative"]
    relative: FiniteFloat


class BookShockParallelVol(_Request):
    """Add an absolute shift to volatility."""

    kind: Literal["parallel_vol"]
    shift: FiniteFloat


class BookShockSkew(_Request):
    """Skew slope per unit of log-moneyness ln(K / F); positive raises
    higher-strike volatility."""

    kind: Literal["skew"]
    slope: FiniteFloat


class BookShockRate(_Request):
    """Add an absolute shift to the continuously compounded rate, per year."""

    kind: Literal["rate"]
    shift: FiniteFloat


class BookShockRollDown(_Request):
    """Move the valuation later by `years` (nonnegative) with spot held."""

    kind: Literal["roll_down"]
    years: FiniteFloat


class BookShockVolTerm(_Request):
    """Linear volatility ramp over remaining tenor, flat outside the anchors."""

    back_shift: FiniteFloat
    back_tenor: FiniteFloat
    front_shift: FiniteFloat
    front_tenor: FiniteFloat
    kind: Literal["vol_term"]


BookShock = Annotated[
    BookShockSpotRelative
    | BookShockParallelVol
    | BookShockSkew
    | BookShockRate
    | BookShockRollDown
    | BookShockVolTerm,
    Field(discriminator="kind"),
]


class BookScenarioDefinition(_Request):
    """A named, ordered scenario applied to every position of every book."""

    name: str | None = Field(default=None)
    shocks: list[BookShock] | None = Field(default=None, max_length=16)


class BooksRevalueRequest(_Request):
    """Reprice one or more books under one composed scenario (`books.revalue`,
    and the same body for `books.explain`). More than one book returns
    portfolio totals. Every position costs a base and a shocked price
    calculation at its model's price rate."""

    books: list[Book] = Field(max_length=50)
    currency: str = Field(pattern="^[A-Z]{3}$")
    markets: dict[str, Market]
    scenario: BookScenarioDefinition


class BooksSolveScenarioRequest(_Request):
    """Find every spot level at which a book's (or one strategy's) modeled P&L
    equals a target (`books.solve_scenario`), under an ordered non-spot scenario. P&L
    is horizon value minus `signed_reference_net_value`. Solved positions
    share one underlying, so its single market's spot is the solved axis.
    Roll-down may reach expiry (including engine roundoff tolerance) but not pass it."""

    book: Book
    coordinate_tolerance: FiniteFloat | None = Field(default=None)
    currency: str = Field(pattern="^[A-Z]{3}$")
    lower: FiniteFloat
    markets: dict[str, Market]
    pnl_tolerance: FiniteFloat | None = Field(default=None)
    scenario: BookScenarioDefinition
    signed_reference_net_value: FiniteFloat
    strategy_id: str | None = Field(default=None, pattern="^[A-Za-z0-9._:/-]{1,64}$")
    target_pnl: FiniteFloat | None = Field(default=None)
    upper: FiniteFloat


class ScenarioPosition(_Request):
    """Optional signed position scaling. P&L is relative to the base model value
    (`pnl_basis: base_model_value`), not trade entry cost. No currency
    conversion, fees or financing are applied."""

    multiplier: FiniteFloat
    quantity: FiniteFloat


class ScenarioPoint(_Request):
    """Changes applied independently to the base contract. Monetary values use the
    contract's quote currency; volatility is annualized decimal volatility."""

    elapsed_time_years: FiniteFloat | None = Field(default=None)
    spot: FiniteFloat | None = Field(default=None)
    spot_change: FiniteFloat | None = Field(default=None)
    volatility: FiniteFloat | None = Field(default=None)


class OptionsRevalueRequest(_Request):
    """Independently reprice one option at explicit points (`options.revalue`).
    Send a curve or a flattened grid in the desired order. Only explicit BSM
    and BS1993 are supported."""

    market: Market
    model: ModelSelection
    option: Option
    position: ScenarioPosition | None = Field(default=None)
    scenarios: list[ScenarioPoint] = Field(min_length=1, max_length=99)
    volatility: FiniteFloat


class OptionsSolveScenarioAssumptions(_Request):
    """Scenario assumptions a target solve holds fixed while it searches its
    coordinate."""

    elapsed_time_years: FiniteFloat | None = Field(default=None)
    volatility: FiniteFloat | None = Field(default=None)


ScenarioSolveCoordinate = Literal[
    "spot", "strike", "time_to_expiry", "elapsed_time", "rate", "dividend_yield", "volatility"
]


class ScenarioSolveTargetOptionPrice(_Request):
    """ScenarioSolveTargetOptionPrice"""

    kind: Literal["option_price"]
    value: FiniteFloat


class ScenarioSolveTargetPositionPnl(_Request):
    """ScenarioSolveTargetPositionPnl"""

    kind: Literal["position_pnl"]
    position: ScenarioPosition
    value: FiniteFloat


ScenarioSolveGreek = Literal[
    "delta", "gamma", "theta", "vega", "rho", "vanna", "volga", "charm", "veta", "color"
]


class ScenarioSolveTargetGreek(_Request):
    """One per-option Greek in the units the Greek endpoints publish (annual
    time units for theta, charm, veta and color). Not scaled by any position."""

    greek: ScenarioSolveGreek
    kind: Literal["greek"]
    value: FiniteFloat


ScenarioSolveTarget = Annotated[
    ScenarioSolveTargetOptionPrice | ScenarioSolveTargetPositionPnl | ScenarioSolveTargetGreek,
    Field(discriminator="kind"),
]


class OptionsSolveScenarioRequest(_Request):
    """Solve one input of one option for a target price, P&L or Greek
    (`options.solve_scenario`)."""

    coordinate: ScenarioSolveCoordinate | None = Field(default=None)
    coordinate_tolerance: FiniteFloat | None = Field(default=None)
    lower: FiniteFloat
    market: Market
    model: ModelSelection
    option: Option
    scenario: OptionsSolveScenarioAssumptions | None = Field(default=None)
    target: ScenarioSolveTarget
    upper: FiniteFloat
    value_tolerance: FiniteFloat | None = Field(default=None)
    volatility: FiniteFloat


class DividendEventEcho(_Response):
    """One discrete cash dividend."""

    cash_amount: FiniteFloat
    ex_time_years: FiniteFloat


class MarketEcho(_Response):
    """Market state of the underlying: one per underlying in a book."""

    dividend_yield: FiniteFloat
    dividends: list[DividendEventEcho] | None = Field(default=None, max_length=16)
    risk_free_rate: FiniteFloat
    spot: FiniteFloat


class ModelSelectionEcho(_Response):
    """Model selection for a request: a selector from `GET /v1/models`, or `auto`."""

    id: PricingModel | str
    version: str | None = Field(default=None)


class OptionEcho(_Response):
    """The option's contract terms (ADR 0011). Market state and the model are
    separate objects, so scenarios and books change one without restating the
    others."""

    exercise_style: ExerciseStyle | str
    strike: FiniteFloat
    time_to_expiry_years: FiniteFloat = Field(ge=0)
    type: OptionType | str


class OptionsPriceRequestEcho(_Response):
    """Price one option at a supplied volatility."""

    market: MarketEcho
    model: ModelSelectionEcho
    option: OptionEcho
    volatility: FiniteFloat = Field(ge=0)


class ScenarioItemBase(_Response):
    """ScenarioItemBase"""

    index: int = Field(ge=0)
    inputs: OptionsPriceRequestEcho


class ScenarioSuccess(ScenarioItemBase):
    """ScenarioSuccess"""

    pnl: FiniteFloat | None = Field(default=None)
    price_change: FiniteFloat
    result: PriceResult
    status: Literal["success"]


class ScenarioError(ScenarioItemBase):
    """ScenarioError"""

    error: Problem
    status: Literal["error"]


class ScenarioUnrecognized(ScenarioItemBase):
    status: str


ScenarioItem = Annotated[
    Annotated[ScenarioSuccess, Tag("success")]
    | Annotated[ScenarioError, Tag("error")]
    | Annotated[ScenarioUnrecognized, Tag("unrecognized")],
    _variant("status", ("success", "error")),
]


class BookPositionScenario(_Response):
    """One position's base and shocked valuation, in the request currency."""

    base_net_value: FiniteFloat
    base_unit_price: FiniteFloat
    contract: OptionsPriceRequestEcho
    id: str
    model: ModelIdentity
    multiplier: FiniteFloat
    pnl: FiniteFloat
    quantity: FiniteFloat
    shocked_net_value: FiniteFloat
    shocked_unit_price: FiniteFloat
    underlying: str


class ExpiryPnlBucket(_Response):
    """Positions sharing exactly the same base expiry (bitwise-equal years)."""

    base_net_value: FiniteFloat
    pnl: FiniteFloat
    shocked_net_value: FiniteFloat
    time_to_expiry_years: FiniteFloat


class StrikePnlBucket(_Response):
    """Positions sharing exactly the same strike (bitwise-equal)."""

    base_net_value: FiniteFloat
    pnl: FiniteFloat
    shocked_net_value: FiniteFloat
    strike: FiniteFloat


class ScenarioPnlAttribution(_Response):
    """P&L attribution. The expiry buckets and the strike buckets each partition
    the positions and reconcile to the enclosing P&L."""

    expiry_buckets: list[ExpiryPnlBucket]
    strike_buckets: list[StrikePnlBucket]


class BookStrategyScenario(_Response):
    """One strategy's member set; overlapping strategies are not additive."""

    base_net_value: FiniteFloat
    id: str
    pnl: FiniteFloat
    position_ids: list[str] = Field(max_length=50)
    shocked_net_value: FiniteFloat


class BookScenarioBook(_Response):
    """One book's base and shocked valuation, in the request currency."""

    attribution: ScenarioPnlAttribution | None = Field(default=None)
    base_net_value: FiniteFloat
    id: str
    pnl: FiniteFloat
    positions: list[BookPositionScenario]
    shocked_net_value: FiniteFloat
    strategies: list[BookStrategyScenario]


class BookSolvePosition(_Response):
    """One solved position and its base valuation, in the request currency."""

    base_net_value: FiniteFloat
    contract: OptionsPriceRequestEcho
    id: str
    model: ModelIdentity
    multiplier: FiniteFloat
    quantity: FiniteFloat
    underlying: str


PnlBasis = Literal["base_model_value", "signed_reference_net_value"]


class BookShockEchoSpotRelative(_Response):
    """Multiply the underlying by 1 + relative; relative must exceed -1."""

    kind: Literal["spot_relative"]
    relative: FiniteFloat


class BookShockEchoParallelVol(_Response):
    """Add an absolute shift to volatility."""

    kind: Literal["parallel_vol"]
    shift: FiniteFloat


class BookShockEchoSkew(_Response):
    """Skew slope per unit of log-moneyness ln(K / F); positive raises
    higher-strike volatility."""

    kind: Literal["skew"]
    slope: FiniteFloat


class BookShockEchoRate(_Response):
    """Add an absolute shift to the continuously compounded rate, per year."""

    kind: Literal["rate"]
    shift: FiniteFloat


class BookShockEchoRollDown(_Response):
    """Move the valuation later by `years` (nonnegative) with spot held."""

    kind: Literal["roll_down"]
    years: FiniteFloat


class BookShockEchoVolTerm(_Response):
    """Linear volatility ramp over remaining tenor, flat outside the anchors."""

    back_shift: FiniteFloat
    back_tenor: FiniteFloat
    front_shift: FiniteFloat
    front_tenor: FiniteFloat
    kind: Literal["vol_term"]


BookShockEcho = Annotated[
    Annotated[BookShockEchoSpotRelative, Tag("spot_relative")]
    | Annotated[BookShockEchoParallelVol, Tag("parallel_vol")]
    | Annotated[BookShockEchoSkew, Tag("skew")]
    | Annotated[BookShockEchoRate, Tag("rate")]
    | Annotated[BookShockEchoRollDown, Tag("roll_down")]
    | Annotated[BookShockEchoVolTerm, Tag("vol_term")]
    | Annotated[UnrecognizedKind, Tag("unrecognized")],
    _variant("kind", ("spot_relative", "parallel_vol", "skew", "rate", "roll_down", "vol_term")),
]


class BookScenarioDefinitionEcho(_Response):
    """A named, ordered scenario applied to every position of every book."""

    name: str | None = Field(default=None)
    shocks: list[BookShockEcho] | None = Field(default=None, max_length=16)


class BooksRevalueResult(_Response):
    """Book and portfolio scenario valuation. `:explain` returns exactly this result
    with `attribution` added at book and portfolio level, so one parser handles both."""

    attribution: ScenarioPnlAttribution | None = Field(default=None)
    base_net_value: FiniteFloat
    books: list[BookScenarioBook]
    currency: str
    pnl: FiniteFloat
    pnl_basis: PnlBasis | str
    price_evaluations: int = Field(ge=0)
    scenario: BookScenarioDefinitionEcho
    shocked_net_value: FiniteFloat


class BooksRevalueResponse(_EvidenceResponse):
    """BooksRevalueResponse"""

    metadata: ResponseMetadata
    result: BooksRevalueResult


class ScenarioSolveBoundaryPoint(_Response):
    """ScenarioSolveBoundaryPoint"""

    bracket_width: FiniteFloat
    coordinate: FiniteFloat
    crossing: bool
    kind: Literal["point"]
    refinements: int = Field(ge=0)
    value: FiniteFloat


class ScenarioSolveBoundaryInterval(_Response):
    """ScenarioSolveBoundaryInterval"""

    kind: Literal["interval"]
    lower: FiniteFloat
    upper: FiniteFloat
    value: FiniteFloat


ScenarioSolveBoundary = Annotated[
    Annotated[ScenarioSolveBoundaryPoint, Tag("point")]
    | Annotated[ScenarioSolveBoundaryInterval, Tag("interval")]
    | Annotated[UnrecognizedKind, Tag("unrecognized")],
    _variant("kind", ("point", "interval")),
]


ScenarioSolveCoordinateUnit = Literal["price", "years", "annual_rate", "annual_volatility"]


ScenarioSolveCoverageBasis = Literal["scan_resolution"]


class ScenarioSolveCoverageResolved(_Response):
    """Every candidate resolved at `basis`; smaller structures can be missed."""

    basis: ScenarioSolveCoverageBasis | str
    status: Literal["resolved"]


ScenarioSolveUnresolvedReason = Literal[
    "refinement_budget_exhausted",
    "bracket_collapsed_above_tolerance",
    "coordinate_tolerance_reached",
    "representative_out_of_band",
]


class ScenarioSolveUnresolvedCell(_Response):
    """ScenarioSolveUnresolvedCell"""

    best_abs_value_error: FiniteFloat
    best_coordinate: FiniteFloat
    lower: FiniteFloat
    reason: ScenarioSolveUnresolvedReason | str
    upper: FiniteFloat


class ScenarioSolveCoverageUnresolved(_Response):
    """At least one cell could not be resolved; see `cells`."""

    basis: ScenarioSolveCoverageBasis | str
    cells: list[ScenarioSolveUnresolvedCell]
    status: Literal["unresolved"]


ScenarioSolveCoverage = Annotated[
    Annotated[ScenarioSolveCoverageResolved, Tag("resolved")]
    | Annotated[ScenarioSolveCoverageUnresolved, Tag("unresolved")]
    | Annotated[Unrecognized, Tag("unrecognized")],
    _variant("status", ("resolved", "unresolved")),
]


ScenarioSolveOutcome = Literal["solutions_found", "no_solution_detected", "incomplete"]


class ScenarioSolveProfile(_Response):
    """Fixed bounded work profile, independent of user tolerances and target."""

    id: str
    max_price_evaluations: int = Field(ge=0)
    max_refinements: int = Field(ge=0)
    scan_intervals: int = Field(ge=0)


ScenarioSolveSign = Literal["above_target", "below_target", "at_target"]


class ScenarioSolveRegion(_Response):
    """ScenarioSolveRegion"""

    lower: FiniteFloat
    sign: ScenarioSolveSign | str
    upper: FiniteFloat


class BooksSolveScenarioResult(_Response):
    """Spot levels at which the solved positions' P&L meets the target, with the
    sign regions and coverage of the search."""

    book_id: str
    boundaries: list[ScenarioSolveBoundary]
    coordinate: ScenarioSolveCoordinate | str
    coordinate_tolerance: FiniteFloat
    coordinate_unit: ScenarioSolveCoordinateUnit | str
    coverage: ScenarioSolveCoverage
    currency: str
    evaluations: int = Field(ge=0)
    lower: FiniteFloat
    outcome: ScenarioSolveOutcome | str
    pnl_basis: PnlBasis | str
    pnl_tolerance: FiniteFloat
    positions: list[BookSolvePosition]
    price_evaluations: int = Field(ge=0)
    profile: ScenarioSolveProfile
    regions: list[ScenarioSolveRegion]
    scenario: BookScenarioDefinitionEcho
    signed_reference_net_value: FiniteFloat
    strategy_id: str | None = Field(default=None)
    target_pnl: FiniteFloat
    target_unit: str
    underlying: str
    upper: FiniteFloat


class BooksSolveScenarioResponse(_EvidenceResponse):
    """BooksSolveScenarioResponse"""

    metadata: ResponseMetadata
    result: BooksSolveScenarioResult


class ScenarioValuation(_Response):
    """One valuation and the full inputs it was computed from."""

    inputs: OptionsPriceRequestEcho
    result: PriceResult


class ScenarioPositionEcho(_Response):
    """Optional signed position scaling. P&L is relative to the base model value
    (`pnl_basis: base_model_value`), not trade entry cost. No currency
    conversion, fees or financing are applied."""

    multiplier: FiniteFloat
    quantity: FiniteFloat


class OptionsRevalueResult(_Response):
    """The base valuation and one revaluation per submitted scenario point."""

    base: ScenarioValuation
    pnl_basis: PnlBasis | str | None = Field(default=None)
    position: ScenarioPositionEcho | None = Field(default=None)
    scenarios: list[ScenarioItem]


class OptionsRevalueResponse(_EvidenceResponse):
    """OptionsRevalueResponse"""

    metadata: ResponseMetadata
    result: OptionsRevalueResult


class ScenarioSolveTargetEchoOptionPrice(_Response):
    """ScenarioSolveTargetEchoOptionPrice"""

    kind: Literal["option_price"]
    value: FiniteFloat


class ScenarioSolveTargetEchoPositionPnl(_Response):
    """ScenarioSolveTargetEchoPositionPnl"""

    kind: Literal["position_pnl"]
    position: ScenarioPositionEcho
    value: FiniteFloat


class ScenarioSolveTargetEchoGreek(_Response):
    """One per-option Greek in the units the Greek endpoints publish (annual
    time units for theta, charm, veta and color). Not scaled by any position."""

    greek: ScenarioSolveGreek | str
    kind: Literal["greek"]
    value: FiniteFloat


ScenarioSolveTargetEcho = Annotated[
    Annotated[ScenarioSolveTargetEchoOptionPrice, Tag("option_price")]
    | Annotated[ScenarioSolveTargetEchoPositionPnl, Tag("position_pnl")]
    | Annotated[ScenarioSolveTargetEchoGreek, Tag("greek")]
    | Annotated[UnrecognizedKind, Tag("unrecognized")],
    _variant("kind", ("option_price", "position_pnl", "greek")),
]


class OptionsSolveScenarioResult(_Response):
    """Where over the search range one option's target quantity meets the target,
    with the sign regions and coverage of the search."""

    base: ScenarioValuation
    boundaries: list[ScenarioSolveBoundary]
    coordinate: ScenarioSolveCoordinate | str
    coordinate_tolerance: FiniteFloat
    coordinate_unit: ScenarioSolveCoordinateUnit | str
    coverage: ScenarioSolveCoverage
    inputs: OptionsPriceRequestEcho
    lower: FiniteFloat
    model: ModelIdentity
    outcome: ScenarioSolveOutcome | str
    pnl_basis: PnlBasis | str | None = Field(default=None)
    price_evaluations: int = Field(ge=0)
    profile: ScenarioSolveProfile
    reference_net_value: FiniteFloat | None = Field(default=None)
    regions: list[ScenarioSolveRegion]
    target: ScenarioSolveTargetEcho
    target_unit: str
    upper: FiniteFloat
    value_tolerance: FiniteFloat


class OptionsSolveScenarioResponse(_EvidenceResponse):
    """OptionsSolveScenarioResponse"""

    metadata: ResponseMetadata
    result: OptionsSolveScenarioResult


class BooksExplainRequest(BooksRevalueRequest):
    """books.explain uses the same body as revalue, but requests attribution."""


class BooksExplainResponse(BooksRevalueResponse):
    """Book revaluation with expiry and strike P&L attribution."""
