"""Typed sync/async clients for the MorphIQ Labs API."""

from importlib.metadata import version

from .client import AsyncMorphIQ, MorphIQ
from .errors import APIError, MorphIQError, RequestTimeout, ResponseError, TransportError
from .market_data import PriceAdjustment, PriceBar, PriceHistory, PriceInterval, PriceProvider
from .models import (
    AnalyticsRequest,
    AnalyticsResponse,
    AnalyticsResult,
    DividendEvent,
    Greeks,
    GreeksRequest,
    GreeksResponse,
    GreeksResult,
    ImpliedVolatilityRequest,
    ImpliedVolatilityResponse,
    ImpliedVolatilityResult,
    PriceRequest,
    PriceResponse,
    RegimeRequest,
    RegimeResponse,
)

__version__ = version("morphiq-sdk")

__all__ = [
    "APIError",
    "AnalyticsRequest",
    "AnalyticsResponse",
    "AnalyticsResult",
    "AsyncMorphIQ",
    "DividendEvent",
    "Greeks",
    "GreeksRequest",
    "GreeksResponse",
    "GreeksResult",
    "ImpliedVolatilityRequest",
    "ImpliedVolatilityResponse",
    "ImpliedVolatilityResult",
    "MorphIQ",
    "MorphIQError",
    "PriceAdjustment",
    "PriceBar",
    "PriceHistory",
    "PriceInterval",
    "PriceProvider",
    "PriceRequest",
    "PriceResponse",
    "RegimeRequest",
    "RegimeResponse",
    "RequestTimeout",
    "ResponseError",
    "TransportError",
    "__version__",
]
