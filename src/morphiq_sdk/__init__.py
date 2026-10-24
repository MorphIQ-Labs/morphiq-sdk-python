"""Typed synchronous and asynchronous pricing and regime identification for the MorphIQ Labs API."""

from importlib.metadata import version

from .client import AsyncMorphIQ, MorphIQ
from .errors import APIError, MorphIQError, RequestTimeout, ResponseError, TransportError
from .market_data import PriceAdjustment, PriceBar, PriceHistory, PriceInterval, PriceProvider
from .models import DividendEvent, PriceRequest, PriceResponse, RegimeRequest, RegimeResponse

__version__ = version("morphiq-sdk")

__all__ = [
    "APIError",
    "AsyncMorphIQ",
    "DividendEvent",
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
