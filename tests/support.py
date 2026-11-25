"""Synthetic wire builders shared by the unit tests; no network or numerical logic."""

from __future__ import annotations

import copy
from typing import Any

from morphiq_sdk import (
    OptionsBatchGreeksRequest,
    OptionsBatchGreeksResponse,
    OptionsBatchImpliedGreeksRequest,
    OptionsBatchImpliedGreeksResponse,
    OptionsBatchImpliedVolatilityRequest,
    OptionsBatchImpliedVolatilityResponse,
    OptionsBatchPriceRequest,
    OptionsBatchPriceResponse,
)

# Batch fixture order: price, greeks, implied volatility, implied Greeks.
BATCH_OPERATIONS = [
    ("batch_price", OptionsBatchPriceRequest, OptionsBatchPriceResponse, "price_workflow"),
    ("batch_greeks", OptionsBatchGreeksRequest, OptionsBatchGreeksResponse, "greeks_workflow"),
    (
        "batch_implied_volatility",
        OptionsBatchImpliedVolatilityRequest,
        OptionsBatchImpliedVolatilityResponse,
        "implied_volatility_workflow",
    ),
    (
        "batch_implied_greeks",
        OptionsBatchImpliedGreeksRequest,
        OptionsBatchImpliedGreeksResponse,
        "implied_greeks_workflow",
    ),
]


def problem(
    code: str,
    detail: str = "Synthetic failure",
    *,
    status: int = 422,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """An RFC 9457 problem body, with the shared metadata when given."""
    body: dict[str, Any] = {
        "type": f"https://developers.morphiqlabs.com/docs/errors#{code}",
        "title": code.replace("_", " ").capitalize(),
        "status": status,
        "detail": detail,
        "code": code,
        **extra,
    }
    if metadata is not None:
        body["metadata"] = metadata
    return body


def set_charge(
    metadata: dict[str, Any], charged: int | None, quoted: int | None = None
) -> dict[str, Any]:
    """Set ``billing`` in place; an unreported charge omits the member, never null."""
    billing = {
        key: value
        for key, value in {"quoted_cu": quoted, "charged_cu": charged}.items()
        if value is not None
    }
    if billing:
        metadata["billing"] = billing
    else:
        metadata.pop("billing", None)
    return metadata


def charged(metadata: dict[str, Any], value: int | None, quoted: int | None = None) -> dict:
    """A copy of ``metadata`` with the given billing evidence."""
    return set_charge(copy.deepcopy(metadata), value, quoted)
