"""Shared JSON API behavior for synchronous and asynchronous HTTPX clients.

Operations are grouped by the contract's collections, so each method spells the
operation's canonical id: ``client.options.price`` is ``options.price``
(``POST /v1/options:price``), ``client.series.identify_regime`` is
``series.identify_regime``, ``client.models.list`` is ``models.list`` and
``client.rate_card.quote`` is ``rate_card.quote``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import ValidationError

from .errors import APIError, RateLimitError, RequestTimeout, ResponseError, TransportError
from .models import (
    BooksExplainRequest,
    BooksExplainResponse,
    BooksRevalueRequest,
    BooksRevalueResponse,
    BooksSolveScenarioRequest,
    BooksSolveScenarioResponse,
    ErrorResponse,
    ModelsListResponse,
    OptionsBatchGreeksRequest,
    OptionsBatchGreeksResponse,
    OptionsBatchImpliedGreeksRequest,
    OptionsBatchImpliedGreeksResponse,
    OptionsBatchImpliedVolatilityRequest,
    OptionsBatchImpliedVolatilityResponse,
    OptionsBatchPriceRequest,
    OptionsBatchPriceResponse,
    OptionsBatchStandardGreeksRequest,
    OptionsBatchStandardGreeksResponse,
    OptionsGreeksRequest,
    OptionsGreeksResponse,
    OptionsImpliedGreeksRequest,
    OptionsImpliedGreeksResponse,
    OptionsImpliedVolatilityRequest,
    OptionsImpliedVolatilityResponse,
    OptionsPriceRequest,
    OptionsPriceResponse,
    OptionsRevalueRequest,
    OptionsRevalueResponse,
    OptionsSolveScenarioRequest,
    OptionsSolveScenarioResponse,
    OptionsStandardGreeksRequest,
    OptionsStandardGreeksResponse,
    RateCardGetResponse,
    RateCardQuoteResponse,
    ResponseMetadata,
    SeriesIdentifyRegimeRequest,
    SeriesIdentifyRegimeResponse,
    _BatchRequest,
    _BatchResponse,
)
from .workflows import AsyncBatchWorkflow, BatchWorkflow, _prepare_chunks

_ResponseType = TypeVar(
    "_ResponseType",
    OptionsRevalueResponse,
    OptionsSolveScenarioResponse,
    BooksRevalueResponse,
    BooksExplainResponse,
    BooksSolveScenarioResponse,
    OptionsPriceResponse,
    OptionsGreeksResponse,
    OptionsStandardGreeksResponse,
    OptionsImpliedVolatilityResponse,
    OptionsImpliedGreeksResponse,
    OptionsBatchPriceResponse,
    OptionsBatchGreeksResponse,
    OptionsBatchStandardGreeksResponse,
    OptionsBatchImpliedVolatilityResponse,
    OptionsBatchImpliedGreeksResponse,
    SeriesIdentifyRegimeResponse,
    ModelsListResponse,
    RateCardGetResponse,
    RateCardQuoteResponse,
)
_BatchResponseType = TypeVar("_BatchResponseType", bound=_BatchResponse[Any])


def _check_batch(response: _BatchResponseType, expected: int) -> _BatchResponseType:
    # Never silently sort, drop or misassociate outcomes with submitted options.
    if [item.index for item in response.results] != list(range(expected)):
        raise ResponseError(
            request_id=response.metadata.request_id,
            body=response.raw_body,
            headers=response.headers,
            metadata=response.metadata,
        )
    return response


def _redact_body(body: bytes, key: str) -> bytes:
    """Handle both literal and JSON-escaped reflections without rewriting clean bodies."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body.replace(key.encode(), b"[REDACTED]")
    changed = False

    def visit(value: Any) -> Any:
        nonlocal changed
        if isinstance(value, str):
            if key in value:
                changed = True
                return value.replace(key, "[REDACTED]")
        elif isinstance(value, list):
            return [visit(item) for item in value]
        elif isinstance(value, dict):
            return {visit(name): visit(item) for name, item in value.items()}
        return value

    sanitized = visit(payload)
    return json.dumps(sanitized).encode() if changed else body


QuoteInput = (
    OptionsRevalueRequest
    | OptionsSolveScenarioRequest
    | BooksRevalueRequest
    | BooksExplainRequest
    | BooksSolveScenarioRequest
    | OptionsPriceRequest
    | OptionsBatchPriceRequest
    | OptionsImpliedVolatilityRequest
    | OptionsBatchImpliedVolatilityRequest
    | OptionsGreeksRequest
    | OptionsBatchGreeksRequest
    | OptionsStandardGreeksRequest
    | OptionsBatchStandardGreeksRequest
    | OptionsImpliedGreeksRequest
    | OptionsBatchImpliedGreeksRequest
    | SeriesIdentifyRegimeRequest
)
# Canonical operation ids, as the quote endpoint and model catalog spell them.
_OPERATION_IDS: dict[type[Any], str] = {
    BooksSolveScenarioRequest: "books.solve_scenario",
    BooksExplainRequest: "books.explain",
    BooksRevalueRequest: "books.revalue",
    OptionsSolveScenarioRequest: "options.solve_scenario",
    OptionsRevalueRequest: "options.revalue",
    OptionsPriceRequest: "options.price",
    OptionsBatchPriceRequest: "options.batch_price",
    OptionsImpliedVolatilityRequest: "options.implied_volatility",
    OptionsBatchImpliedVolatilityRequest: "options.batch_implied_volatility",
    OptionsGreeksRequest: "options.greeks",
    OptionsBatchGreeksRequest: "options.batch_greeks",
    OptionsStandardGreeksRequest: "options.standard_greeks",
    OptionsBatchStandardGreeksRequest: "options.batch_standard_greeks",
    OptionsImpliedGreeksRequest: "options.implied_greeks",
    OptionsBatchImpliedGreeksRequest: "options.batch_implied_greeks",
    SeriesIdentifyRegimeRequest: "series.identify_regime",
}


def operation_id(request: QuoteInput) -> str:
    """The canonical operation id (for example ``options.price``) a request executes."""
    operation = _OPERATION_IDS.get(type(request))
    if operation is None:
        raise TypeError("quote expects a supported MorphIQ request model")
    return operation


def _quote_payload(request: QuoteInput) -> dict[str, Any]:
    return {"operation": operation_id(request), "request": request.to_wire()}


def _cost_headers(max_cu: int | None) -> dict[str, str]:
    if max_cu is None:
        return {}
    if type(max_cu) is not int or not 0 <= max_cu <= 2**64 - 1:
        raise ValueError("max_cu must be an unsigned 64-bit integer")
    return {"X-MorphIQ-Max-CU": str(max_cu)}


def _transport_message(failure: str, billable: bool) -> str:
    evidence = (
        "Execution and CU charges may be unknown"
        if billable
        else "This utility request performs no calculation or CU charge"
    )
    return f"The request {failure}. {evidence}; no retry was attempted."


def _rate_card_params(rate_class: str | None, model: str | None) -> dict[str, str]:
    values = {"rate_class": rate_class, "model": model}
    return {key: value for key, value in values.items() if value is not None}


class _Configuration:
    def __init__(
        self, *, base_url: str | None, api_key: str | None, allow_unauthenticated: bool
    ) -> None:
        endpoint = (
            base_url
            if base_url is not None
            else os.environ.get("MORPHIQ_API_BASE_URL") or "https://api.morphiqlabs.com"
        )
        try:
            url = httpx.URL(endpoint)
        except httpx.InvalidURL:
            raise ValueError("base_url must be an absolute HTTP(S) URL.") from None
        if (
            url.scheme not in ("http", "https")
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "base_url must be an HTTP(S) URL without credentials, query or fragment."
            )
        self.url = str(url).rstrip("/") + "/"
        key = api_key if api_key is not None else os.environ.get("MORPHIQ_API_KEY")
        if key is not None and (not key or not key.isascii() or any(c.isspace() for c in key)):
            raise ValueError("API key must be a non-empty ASCII token without whitespace.")
        self._key = key
        self._allow_unauthenticated = allow_unauthenticated

    def require_auth(self) -> None:
        if not self._key and not self._allow_unauthenticated:
            raise ValueError(
                "Pass api_key or set MORPHIQ_API_KEY for authenticated operations. "
                "models.list() is public. Only a controlled open development "
                "service should use allow_unauthenticated=True."
            )

    def headers(self) -> dict[str, str]:
        result = {"Accept": "application/json", "User-Agent": "morphiq-sdk-python"}
        if self._key:
            result["Authorization"] = f"Bearer {self._key}"
        return result

    def decode(self, response: httpx.Response, model: type[_ResponseType]) -> _ResponseType:
        # Retain response evidence, never the request or its Authorization header.
        body = response.content
        headers = dict(response.headers)
        if self._key:
            body = _redact_body(body, self._key)
            headers = {
                key: value.replace(self._key, "[REDACTED]") for key, value in headers.items()
            }
        request_id = headers.get("x-request-id")
        if response.status_code != 200:
            try:
                problem = ErrorResponse.model_validate_json(body)
            except ValidationError:
                problem = None
            error_type = RateLimitError if response.status_code == 429 else APIError
            raise error_type(
                status_code=response.status_code,
                problem=problem,
                request_id=request_id,
                body=body,
                headers=headers,
            )
        try:
            result = model.model_validate_json(body)
        except ValidationError:
            # A malformed numerical result does not erase valid billing evidence.
            metadata = None
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    metadata = ResponseMetadata.model_validate(payload.get("metadata"))
            except (ValueError, UnicodeDecodeError, ValidationError):
                pass
            raise ResponseError(
                request_id=request_id, body=body, headers=headers, metadata=metadata
            ) from None
        result._raw_body = body
        result._headers = headers
        return result


class _Sender(Protocol):
    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        model: type[_ResponseType],
        *,
        params: dict[str, str] | None = None,
        max_cu: int | None = None,
        billable: bool = True,
        public: bool = False,
    ) -> _ResponseType: ...


class _AsyncSender(Protocol):
    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        model: type[_ResponseType],
        *,
        params: dict[str, str] | None = None,
        max_cu: int | None = None,
        billable: bool = True,
        public: bool = False,
    ) -> _ResponseType: ...


def _batch_size(request: _BatchRequest[Any]) -> int:
    return len(request.items)


class OptionsMethods:
    """The ``options`` collection: single-option operations, batches and workflows."""

    def __init__(self, client: _Sender) -> None:
        self._client = client

    def _post(
        self, method: str, payload: dict[str, Any], model: type[_ResponseType], max_cu: int | None
    ) -> _ResponseType:
        return self._client._request("POST", f"v1/options:{method}", payload, model, max_cu=max_cu)

    def price(
        self, request: OptionsPriceRequest, *, max_cu: int | None = None
    ) -> OptionsPriceResponse:
        """``options.price``: price one option at a supplied volatility."""
        return self._post("price", request.to_wire(), OptionsPriceResponse, max_cu)

    def implied_volatility(
        self, request: OptionsImpliedVolatilityRequest, *, max_cu: int | None = None
    ) -> OptionsImpliedVolatilityResponse:
        """``options.implied_volatility``: solve IV from an option premium."""
        return self._post(
            "implied-volatility", request.to_wire(), OptionsImpliedVolatilityResponse, max_cu
        )

    def greeks(
        self, request: OptionsGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsGreeksResponse:
        """``options.greeks``: the option price and all ten Greeks at a supplied volatility."""
        return self._post("greeks", request.to_wire(), OptionsGreeksResponse, max_cu)

    def standard_greeks(
        self, request: OptionsStandardGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsStandardGreeksResponse:
        """``options.standard_greeks``: the price and delta, gamma, theta, vega and rho."""
        return self._post(
            "standard-greeks", request.to_wire(), OptionsStandardGreeksResponse, max_cu
        )

    def implied_greeks(
        self, request: OptionsImpliedGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsImpliedGreeksResponse:
        """``options.implied_greeks``: IV from a premium, then price and all ten Greeks."""
        return self._post("implied-greeks", request.to_wire(), OptionsImpliedGreeksResponse, max_cu)

    def batch_price(
        self, request: OptionsBatchPriceRequest, *, max_cu: int | None = None
    ) -> OptionsBatchPriceResponse:
        """``options.batch_price``: one batch; ordered outcomes and one charge."""
        response = self._post("batch-price", request.to_wire(), OptionsBatchPriceResponse, max_cu)
        return _check_batch(response, _batch_size(request))

    def batch_implied_volatility(
        self, request: OptionsBatchImpliedVolatilityRequest, *, max_cu: int | None = None
    ) -> OptionsBatchImpliedVolatilityResponse:
        """``options.batch_implied_volatility``: one batch; ordered outcomes and one charge."""
        response = self._post(
            "batch-implied-volatility",
            request.to_wire(),
            OptionsBatchImpliedVolatilityResponse,
            max_cu,
        )
        return _check_batch(response, _batch_size(request))

    def batch_greeks(
        self, request: OptionsBatchGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchGreeksResponse:
        """``options.batch_greeks``: one batch; ordered outcomes and one charge."""
        response = self._post("batch-greeks", request.to_wire(), OptionsBatchGreeksResponse, max_cu)
        return _check_batch(response, _batch_size(request))

    def batch_standard_greeks(
        self, request: OptionsBatchStandardGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchStandardGreeksResponse:
        """``options.batch_standard_greeks``: one batch; ordered outcomes and one charge."""
        response = self._post(
            "batch-standard-greeks", request.to_wire(), OptionsBatchStandardGreeksResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    def batch_implied_greeks(
        self, request: OptionsBatchImpliedGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchImpliedGreeksResponse:
        """``options.batch_implied_greeks``: one batch; ordered outcomes and one charge."""
        response = self._post(
            "batch-implied-greeks", request.to_wire(), OptionsBatchImpliedGreeksResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    def price_workflow(
        self, requests: Sequence[OptionsPriceRequest], *, chunk_size: int
    ) -> BatchWorkflow[OptionsBatchPriceRequest, OptionsBatchPriceResponse]:
        """Prepare explicit sequential ``batch_price`` chunks without sending; call run() once."""
        return BatchWorkflow(
            _prepare_chunks(requests, OptionsBatchPriceRequest, chunk_size), self.batch_price
        )

    def implied_volatility_workflow(
        self, requests: Sequence[OptionsImpliedVolatilityRequest], *, chunk_size: int
    ) -> BatchWorkflow[OptionsBatchImpliedVolatilityRequest, OptionsBatchImpliedVolatilityResponse]:
        """Prepare explicit sequential chunks without sending requests; call run() once."""
        return BatchWorkflow(
            _prepare_chunks(requests, OptionsBatchImpliedVolatilityRequest, chunk_size),
            self.batch_implied_volatility,
        )

    def greeks_workflow(
        self, requests: Sequence[OptionsGreeksRequest], *, chunk_size: int
    ) -> BatchWorkflow[OptionsBatchGreeksRequest, OptionsBatchGreeksResponse]:
        """Prepare explicit sequential chunks without sending requests; call run() once."""
        return BatchWorkflow(
            _prepare_chunks(requests, OptionsBatchGreeksRequest, chunk_size), self.batch_greeks
        )

    def standard_greeks_workflow(
        self, requests: Sequence[OptionsStandardGreeksRequest], *, chunk_size: int
    ) -> BatchWorkflow[OptionsBatchStandardGreeksRequest, OptionsBatchStandardGreeksResponse]:
        """Prepare explicit sequential chunks without sending requests; call run() once."""
        return BatchWorkflow(
            _prepare_chunks(requests, OptionsBatchStandardGreeksRequest, chunk_size),
            self.batch_standard_greeks,
        )

    def implied_greeks_workflow(
        self, requests: Sequence[OptionsImpliedGreeksRequest], *, chunk_size: int
    ) -> BatchWorkflow[OptionsBatchImpliedGreeksRequest, OptionsBatchImpliedGreeksResponse]:
        """Prepare explicit sequential chunks without sending requests; call run() once."""
        return BatchWorkflow(
            _prepare_chunks(requests, OptionsBatchImpliedGreeksRequest, chunk_size),
            self.batch_implied_greeks,
        )

    def revalue(
        self, request: OptionsRevalueRequest, *, max_cu: int | None = None
    ) -> OptionsRevalueResponse:
        """Execute options.revalue once, preserving results and billing evidence."""
        response = self._post("revalue", request.to_wire(), OptionsRevalueResponse, max_cu)
        if [item.index for item in response.result.scenarios] != list(
            range(len(request.scenarios))
        ):
            raise ResponseError(
                request_id=response.metadata.request_id,
                body=response.raw_body,
                headers=response.headers,
                metadata=response.metadata,
            )
        return response

    def solve_scenario(
        self, request: OptionsSolveScenarioRequest, *, max_cu: int | None = None
    ) -> OptionsSolveScenarioResponse:
        """Execute options.solve_scenario once, preserving results and billing evidence."""
        response = self._post(
            "solve-scenario", request.to_wire(), OptionsSolveScenarioResponse, max_cu
        )
        return response


class BooksMethods:
    """Book revaluation, attribution and scenario solving."""

    def __init__(self, client: _Sender) -> None:
        self._client = client

    def revalue(
        self, request: BooksRevalueRequest, *, max_cu: int | None = None
    ) -> BooksRevalueResponse:
        """Execute books.revalue once, preserving results and billing evidence."""
        return self._client._request(
            "POST", "v1/books:revalue", request.to_wire(), BooksRevalueResponse, max_cu=max_cu
        )

    def explain(
        self, request: BooksExplainRequest, *, max_cu: int | None = None
    ) -> BooksExplainResponse:
        """Execute books.explain once, preserving results and billing evidence."""
        return self._client._request(
            "POST", "v1/books:explain", request.to_wire(), BooksExplainResponse, max_cu=max_cu
        )

    def solve_scenario(
        self, request: BooksSolveScenarioRequest, *, max_cu: int | None = None
    ) -> BooksSolveScenarioResponse:
        """Execute books.solve_scenario once, preserving results and billing evidence."""
        return self._client._request(
            "POST",
            "v1/books:solve-scenario",
            request.to_wire(),
            BooksSolveScenarioResponse,
            max_cu=max_cu,
        )


class SeriesMethods:
    """The ``series`` collection: price-series analysis."""

    def __init__(self, client: _Sender) -> None:
        self._client = client

    def identify_regime(
        self, request: SeriesIdentifyRegimeRequest, *, max_cu: int | None = None
    ) -> SeriesIdentifyRegimeResponse:
        """``series.identify_regime``: regime heads, input facts, timing and provenance."""
        return self._client._request(
            "POST",
            "v1/series:identify-regime",
            request.to_wire(),
            SeriesIdentifyRegimeResponse,
            max_cu=max_cu,
        )


class ModelsMethods:
    """The ``models`` collection: the public compiled model catalog."""

    def __init__(self, client: _Sender) -> None:
        self._client = client

    def list(self) -> ModelsListResponse:
        """``models.list``: compiled models without a key, execution, or CU charge."""
        return self._client._request(
            "GET", "v1/models", None, ModelsListResponse, billable=False, public=True
        )


class RateCardMethods:
    """The ``rate_card`` singleton: your active rate card and exact quotes."""

    def __init__(self, client: _Sender) -> None:
        self._client = client

    def get(
        self, *, rate_class: str | None = None, model: str | None = None
    ) -> RateCardGetResponse:
        """``rate_card.get``: your active rate card, optionally filtered; charges no CUs."""
        return self._client._request(
            "GET",
            "v1/rate-card",
            None,
            RateCardGetResponse,
            params=_rate_card_params(rate_class, model),
            billable=False,
        )

    def quote(self, request: QuoteInput) -> RateCardQuoteResponse:
        """``rate_card.quote``: quote the typed request you will execute, without running it."""
        return self._client._request(
            "POST",
            "v1/rate-card:quote",
            _quote_payload(request),
            RateCardQuoteResponse,
            billable=False,
        )


class AsyncOptionsMethods:
    """Async ``options`` collection; methods match OptionsMethods."""

    def __init__(self, client: _AsyncSender) -> None:
        self._client = client

    async def _post(
        self, method: str, payload: dict[str, Any], model: type[_ResponseType], max_cu: int | None
    ) -> _ResponseType:
        return await self._client._request(
            "POST", f"v1/options:{method}", payload, model, max_cu=max_cu
        )

    async def price(
        self, request: OptionsPriceRequest, *, max_cu: int | None = None
    ) -> OptionsPriceResponse:
        """``options.price``: price one option at a supplied volatility."""
        return await self._post("price", request.to_wire(), OptionsPriceResponse, max_cu)

    async def implied_volatility(
        self, request: OptionsImpliedVolatilityRequest, *, max_cu: int | None = None
    ) -> OptionsImpliedVolatilityResponse:
        """``options.implied_volatility``: solve IV from an option premium."""
        return await self._post(
            "implied-volatility", request.to_wire(), OptionsImpliedVolatilityResponse, max_cu
        )

    async def greeks(
        self, request: OptionsGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsGreeksResponse:
        """``options.greeks``: the option price and all ten Greeks at a supplied volatility."""
        return await self._post("greeks", request.to_wire(), OptionsGreeksResponse, max_cu)

    async def standard_greeks(
        self, request: OptionsStandardGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsStandardGreeksResponse:
        """``options.standard_greeks``: the price and delta, gamma, theta, vega and rho."""
        return await self._post(
            "standard-greeks", request.to_wire(), OptionsStandardGreeksResponse, max_cu
        )

    async def implied_greeks(
        self, request: OptionsImpliedGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsImpliedGreeksResponse:
        """``options.implied_greeks``: IV from a premium, then price and all ten Greeks."""
        return await self._post(
            "implied-greeks", request.to_wire(), OptionsImpliedGreeksResponse, max_cu
        )

    async def batch_price(
        self, request: OptionsBatchPriceRequest, *, max_cu: int | None = None
    ) -> OptionsBatchPriceResponse:
        """``options.batch_price``: one batch; ordered outcomes and one charge."""
        response = await self._post(
            "batch-price", request.to_wire(), OptionsBatchPriceResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    async def batch_implied_volatility(
        self, request: OptionsBatchImpliedVolatilityRequest, *, max_cu: int | None = None
    ) -> OptionsBatchImpliedVolatilityResponse:
        """``options.batch_implied_volatility``: one batch; ordered outcomes and one charge."""
        response = await self._post(
            "batch-implied-volatility",
            request.to_wire(),
            OptionsBatchImpliedVolatilityResponse,
            max_cu,
        )
        return _check_batch(response, _batch_size(request))

    async def batch_greeks(
        self, request: OptionsBatchGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchGreeksResponse:
        """``options.batch_greeks``: one batch; ordered outcomes and one charge."""
        response = await self._post(
            "batch-greeks", request.to_wire(), OptionsBatchGreeksResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    async def batch_standard_greeks(
        self, request: OptionsBatchStandardGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchStandardGreeksResponse:
        """``options.batch_standard_greeks``: one batch; ordered outcomes and one charge."""
        response = await self._post(
            "batch-standard-greeks", request.to_wire(), OptionsBatchStandardGreeksResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    async def batch_implied_greeks(
        self, request: OptionsBatchImpliedGreeksRequest, *, max_cu: int | None = None
    ) -> OptionsBatchImpliedGreeksResponse:
        """``options.batch_implied_greeks``: one batch; ordered outcomes and one charge."""
        response = await self._post(
            "batch-implied-greeks", request.to_wire(), OptionsBatchImpliedGreeksResponse, max_cu
        )
        return _check_batch(response, _batch_size(request))

    def price_workflow(
        self,
        requests: Sequence[OptionsPriceRequest],
        *,
        chunk_size: int,
        max_concurrency: int = 1,
    ) -> AsyncBatchWorkflow[OptionsBatchPriceRequest, OptionsBatchPriceResponse]:
        """Prepare chunks without HTTP; max_concurrency explicitly bounds async execution."""
        return AsyncBatchWorkflow(
            _prepare_chunks(requests, OptionsBatchPriceRequest, chunk_size),
            self.batch_price,
            max_concurrency=max_concurrency,
        )

    def implied_volatility_workflow(
        self,
        requests: Sequence[OptionsImpliedVolatilityRequest],
        *,
        chunk_size: int,
        max_concurrency: int = 1,
    ) -> AsyncBatchWorkflow[
        OptionsBatchImpliedVolatilityRequest, OptionsBatchImpliedVolatilityResponse
    ]:
        """Prepare chunks without HTTP; max_concurrency explicitly bounds async execution."""
        return AsyncBatchWorkflow(
            _prepare_chunks(requests, OptionsBatchImpliedVolatilityRequest, chunk_size),
            self.batch_implied_volatility,
            max_concurrency=max_concurrency,
        )

    def greeks_workflow(
        self,
        requests: Sequence[OptionsGreeksRequest],
        *,
        chunk_size: int,
        max_concurrency: int = 1,
    ) -> AsyncBatchWorkflow[OptionsBatchGreeksRequest, OptionsBatchGreeksResponse]:
        """Prepare chunks without HTTP; max_concurrency explicitly bounds async execution."""
        return AsyncBatchWorkflow(
            _prepare_chunks(requests, OptionsBatchGreeksRequest, chunk_size),
            self.batch_greeks,
            max_concurrency=max_concurrency,
        )

    def standard_greeks_workflow(
        self,
        requests: Sequence[OptionsStandardGreeksRequest],
        *,
        chunk_size: int,
        max_concurrency: int = 1,
    ) -> AsyncBatchWorkflow[OptionsBatchStandardGreeksRequest, OptionsBatchStandardGreeksResponse]:
        """Prepare chunks without HTTP; max_concurrency explicitly bounds async execution."""
        return AsyncBatchWorkflow(
            _prepare_chunks(requests, OptionsBatchStandardGreeksRequest, chunk_size),
            self.batch_standard_greeks,
            max_concurrency=max_concurrency,
        )

    def implied_greeks_workflow(
        self,
        requests: Sequence[OptionsImpliedGreeksRequest],
        *,
        chunk_size: int,
        max_concurrency: int = 1,
    ) -> AsyncBatchWorkflow[OptionsBatchImpliedGreeksRequest, OptionsBatchImpliedGreeksResponse]:
        """Prepare chunks without HTTP; max_concurrency explicitly bounds async execution."""
        return AsyncBatchWorkflow(
            _prepare_chunks(requests, OptionsBatchImpliedGreeksRequest, chunk_size),
            self.batch_implied_greeks,
            max_concurrency=max_concurrency,
        )

    async def revalue(
        self, request: OptionsRevalueRequest, *, max_cu: int | None = None
    ) -> OptionsRevalueResponse:
        """Execute options.revalue once, preserving results and billing evidence."""
        response = await self._post("revalue", request.to_wire(), OptionsRevalueResponse, max_cu)
        if [item.index for item in response.result.scenarios] != list(
            range(len(request.scenarios))
        ):
            raise ResponseError(
                request_id=response.metadata.request_id,
                body=response.raw_body,
                headers=response.headers,
                metadata=response.metadata,
            )
        return response

    async def solve_scenario(
        self, request: OptionsSolveScenarioRequest, *, max_cu: int | None = None
    ) -> OptionsSolveScenarioResponse:
        """Execute options.solve_scenario once, preserving results and billing evidence."""
        response = await self._post(
            "solve-scenario", request.to_wire(), OptionsSolveScenarioResponse, max_cu
        )
        return response


class AsyncBooksMethods:
    """Book revaluation, attribution and scenario solving."""

    def __init__(self, client: _AsyncSender) -> None:
        self._client = client

    async def revalue(
        self, request: BooksRevalueRequest, *, max_cu: int | None = None
    ) -> BooksRevalueResponse:
        """Execute books.revalue once, preserving results and billing evidence."""
        return await self._client._request(
            "POST", "v1/books:revalue", request.to_wire(), BooksRevalueResponse, max_cu=max_cu
        )

    async def explain(
        self, request: BooksExplainRequest, *, max_cu: int | None = None
    ) -> BooksExplainResponse:
        """Execute books.explain once, preserving results and billing evidence."""
        return await self._client._request(
            "POST", "v1/books:explain", request.to_wire(), BooksExplainResponse, max_cu=max_cu
        )

    async def solve_scenario(
        self, request: BooksSolveScenarioRequest, *, max_cu: int | None = None
    ) -> BooksSolveScenarioResponse:
        """Execute books.solve_scenario once, preserving results and billing evidence."""
        return await self._client._request(
            "POST",
            "v1/books:solve-scenario",
            request.to_wire(),
            BooksSolveScenarioResponse,
            max_cu=max_cu,
        )


class AsyncSeriesMethods:
    """Async ``series`` collection."""

    def __init__(self, client: _AsyncSender) -> None:
        self._client = client

    async def identify_regime(
        self, request: SeriesIdentifyRegimeRequest, *, max_cu: int | None = None
    ) -> SeriesIdentifyRegimeResponse:
        """``series.identify_regime``: regime heads, input facts, timing and provenance."""
        return await self._client._request(
            "POST",
            "v1/series:identify-regime",
            request.to_wire(),
            SeriesIdentifyRegimeResponse,
            max_cu=max_cu,
        )


class AsyncModelsMethods:
    """Async ``models`` collection."""

    def __init__(self, client: _AsyncSender) -> None:
        self._client = client

    async def list(self) -> ModelsListResponse:
        """``models.list``: compiled models without a key, execution, or CU charge."""
        return await self._client._request(
            "GET", "v1/models", None, ModelsListResponse, billable=False, public=True
        )


class AsyncRateCardMethods:
    """Async ``rate_card`` singleton."""

    def __init__(self, client: _AsyncSender) -> None:
        self._client = client

    async def get(
        self, *, rate_class: str | None = None, model: str | None = None
    ) -> RateCardGetResponse:
        """``rate_card.get``: your active rate card, optionally filtered; charges no CUs."""
        return await self._client._request(
            "GET",
            "v1/rate-card",
            None,
            RateCardGetResponse,
            params=_rate_card_params(rate_class, model),
            billable=False,
        )

    async def quote(self, request: QuoteInput) -> RateCardQuoteResponse:
        """``rate_card.quote``: quote the typed request you will execute, without running it."""
        return await self._client._request(
            "POST",
            "v1/rate-card:quote",
            _quote_payload(request),
            RateCardQuoteResponse,
            billable=False,
        )


class MorphIQ:
    """Synchronous API client. No retries or redirects are performed.

    Operations are grouped by collection: ``client.options``, ``client.books``, ``client.series``,
    ``client.models`` and ``client.rate_card``.
    The API URL defaults to https://api.morphiqlabs.com; override it with
    ``base_url`` or MORPHIQ_API_BASE_URL. ``api_key`` falls back to MORPHIQ_API_KEY.
    A numeric timeout applies to connect/read/write/pool waits;
    pass ``httpx.Timeout`` to tune them separately. Use a context manager or close().
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | httpx.Timeout = 30.0,
        allow_unauthenticated: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = _Configuration(
            base_url=base_url, api_key=api_key, allow_unauthenticated=allow_unauthenticated
        )
        self._http = httpx.Client(
            base_url=self._config.url,
            headers=self._config.headers(),
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self.options = OptionsMethods(self)
        self.books = BooksMethods(self)
        self.series = SeriesMethods(self)
        self.models = ModelsMethods(self)
        self.rate_card = RateCardMethods(self)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        model: type[_ResponseType],
        *,
        params: dict[str, str] | None = None,
        max_cu: int | None = None,
        billable: bool = True,
        public: bool = False,
    ) -> _ResponseType:
        if not public:
            self._config.require_auth()
        headers = _cost_headers(max_cu)
        try:
            request = self._http.build_request(
                method, path, json=payload, params=params, headers=headers
            )
            if public:
                request.headers.pop("Authorization", None)
            response = self._http.send(request)
        except httpx.TimeoutException:
            raise RequestTimeout(_transport_message("timed out", billable)) from None
        except httpx.RequestError:
            raise TransportError(
                _transport_message("failed before a complete response", billable)
            ) from None
        return self._config.decode(response, model)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MorphIQ:
        self._http.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AsyncMorphIQ:
    """Async equivalent of MorphIQ; use async with and ``await client.options.price(...)``."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | httpx.Timeout = 30.0,
        allow_unauthenticated: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = _Configuration(
            base_url=base_url, api_key=api_key, allow_unauthenticated=allow_unauthenticated
        )
        self._http = httpx.AsyncClient(
            base_url=self._config.url,
            headers=self._config.headers(),
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self.options = AsyncOptionsMethods(self)
        self.books = AsyncBooksMethods(self)
        self.series = AsyncSeriesMethods(self)
        self.models = AsyncModelsMethods(self)
        self.rate_card = AsyncRateCardMethods(self)

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        model: type[_ResponseType],
        *,
        params: dict[str, str] | None = None,
        max_cu: int | None = None,
        billable: bool = True,
        public: bool = False,
    ) -> _ResponseType:
        if not public:
            self._config.require_auth()
        headers = _cost_headers(max_cu)
        try:
            request = self._http.build_request(
                method, path, json=payload, params=params, headers=headers
            )
            if public:
                request.headers.pop("Authorization", None)
            response = await self._http.send(request)
        except httpx.TimeoutException:
            raise RequestTimeout(_transport_message("timed out", billable)) from None
        except httpx.RequestError:
            raise TransportError(
                _transport_message("failed before a complete response", billable)
            ) from None
        return self._config.decode(response, model)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncMorphIQ:
        await self._http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
