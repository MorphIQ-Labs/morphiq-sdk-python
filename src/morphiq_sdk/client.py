"""Shared JSON API behavior for synchronous and asynchronous HTTPX clients."""

from __future__ import annotations

import json
import os
from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from .errors import APIError, RateLimitError, RequestTimeout, ResponseError, TransportError
from .models import (
    AnalyticsRequest,
    AnalyticsResponse,
    BatchAnalyticsRequest,
    BatchAnalyticsResponse,
    BatchGreeksRequest,
    BatchGreeksResponse,
    BatchImpliedVolatilityRequest,
    BatchImpliedVolatilityResponse,
    BatchPriceRequest,
    BatchPriceResponse,
    ErrorEnvelope,
    GreeksRequest,
    GreeksResponse,
    ImpliedVolatilityRequest,
    ImpliedVolatilityResponse,
    PriceRequest,
    PriceResponse,
    RegimeRequest,
    RegimeResponse,
    ResponseMetadata,
    _BatchResponse,
)

_ResponseType = TypeVar(
    "_ResponseType",
    BatchPriceResponse,
    BatchGreeksResponse,
    BatchImpliedVolatilityResponse,
    BatchAnalyticsResponse,
    PriceResponse,
    RegimeResponse,
    GreeksResponse,
    ImpliedVolatilityResponse,
    AnalyticsResponse,
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
        if not key and not allow_unauthenticated:
            raise ValueError(
                "Pass api_key or set MORPHIQ_API_KEY. Only a controlled open development "
                "service should use allow_unauthenticated=True."
            )
        self._key = key

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
                envelope = ErrorEnvelope.model_validate_json(body)
            except ValidationError:
                envelope = None
            error_type = RateLimitError if response.status_code == 429 else APIError
            raise error_type(
                status_code=response.status_code,
                envelope=envelope,
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
            except (ValueError, UnicodeDecodeError):
                pass
            raise ResponseError(
                request_id=request_id, body=body, headers=headers, metadata=metadata
            ) from None
        result._raw_body = body
        result._headers = headers
        return result


class MorphIQ:
    """Synchronous API client. No retries or redirects are performed.

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

    def price(self, request: PriceRequest) -> PriceResponse:
        """Price one option; preserve server model selection and charge evidence."""
        return self._post("v1/price", request.to_wire(), PriceResponse)

    def regime(self, request: RegimeRequest) -> RegimeResponse:
        """Identify regime heads; preserve scores, applicability and provenance."""
        return self._post("v1/regime", request.to_wire(), RegimeResponse)

    def greeks(self, request: GreeksRequest) -> GreeksResponse:
        """Return the option price and all ten Greeks, preserving the API's units."""
        return self._post("v1/greeks", request.to_wire(), GreeksResponse)

    def implied_volatility(self, request: ImpliedVolatilityRequest) -> ImpliedVolatilityResponse:
        """Solve IV from an option premium; preserve residual basis and charge evidence."""
        return self._post("v1/implied-volatility", request.to_wire(), ImpliedVolatilityResponse)

    def analytics(self, request: AnalyticsRequest) -> AnalyticsResponse:
        """Return combined analytics and one server-reported commercial charge."""
        return self._post("v1/analytics", request.to_wire(), AnalyticsResponse)

    def price_batch(self, request: BatchPriceRequest) -> BatchPriceResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = self._post("v1/price:batch", payload, BatchPriceResponse)
        return _check_batch(response, len(payload["requests"]))

    def greeks_batch(self, request: BatchGreeksRequest) -> BatchGreeksResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = self._post("v1/greeks:batch", payload, BatchGreeksResponse)
        return _check_batch(response, len(payload["requests"]))

    def implied_volatility_batch(
        self, request: BatchImpliedVolatilityRequest
    ) -> BatchImpliedVolatilityResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = self._post(
            "v1/implied-volatility:batch", payload, BatchImpliedVolatilityResponse
        )
        return _check_batch(response, len(payload["requests"]))

    def analytics_batch(self, request: BatchAnalyticsRequest) -> BatchAnalyticsResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = self._post("v1/analytics:batch", payload, BatchAnalyticsResponse)
        return _check_batch(response, len(payload["requests"]))

    def _post(
        self, path: str, payload: dict[str, Any], model: type[_ResponseType]
    ) -> _ResponseType:
        try:
            response = self._http.post(path, json=payload)
        except httpx.TimeoutException:
            raise RequestTimeout(
                "The request timed out; execution and CU charges may be unknown. "
                "No retry was attempted."
            ) from None
        except httpx.RequestError:
            raise TransportError(
                "The request failed before a complete response was received. "
                "Execution and CU charges may be unknown; no retry was attempted."
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
    """Async equivalent of MorphIQ; use async with and await client.price(...)."""

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

    async def price(self, request: PriceRequest) -> PriceResponse:
        """Price one option; preserve server model selection and charge evidence."""
        return await self._post("v1/price", request.to_wire(), PriceResponse)

    async def regime(self, request: RegimeRequest) -> RegimeResponse:
        """Identify regime heads; preserve scores, applicability and provenance."""
        return await self._post("v1/regime", request.to_wire(), RegimeResponse)

    async def greeks(self, request: GreeksRequest) -> GreeksResponse:
        """Return the option price and all ten Greeks, preserving the API's units."""
        return await self._post("v1/greeks", request.to_wire(), GreeksResponse)

    async def implied_volatility(
        self, request: ImpliedVolatilityRequest
    ) -> ImpliedVolatilityResponse:
        """Solve IV from an option premium; preserve residual basis and charge evidence."""
        return await self._post(
            "v1/implied-volatility", request.to_wire(), ImpliedVolatilityResponse
        )

    async def analytics(self, request: AnalyticsRequest) -> AnalyticsResponse:
        """Return combined analytics and one server-reported commercial charge."""
        return await self._post("v1/analytics", request.to_wire(), AnalyticsResponse)

    async def price_batch(self, request: BatchPriceRequest) -> BatchPriceResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = await self._post("v1/price:batch", payload, BatchPriceResponse)
        return _check_batch(response, len(payload["requests"]))

    async def greeks_batch(self, request: BatchGreeksRequest) -> BatchGreeksResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = await self._post("v1/greeks:batch", payload, BatchGreeksResponse)
        return _check_batch(response, len(payload["requests"]))

    async def implied_volatility_batch(
        self, request: BatchImpliedVolatilityRequest
    ) -> BatchImpliedVolatilityResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = await self._post(
            "v1/implied-volatility:batch", payload, BatchImpliedVolatilityResponse
        )
        return _check_batch(response, len(payload["requests"]))

    async def analytics_batch(self, request: BatchAnalyticsRequest) -> BatchAnalyticsResponse:
        """Submit one batch; preserve ordered outcomes and count its charge once."""
        payload = request.to_wire()
        response = await self._post("v1/analytics:batch", payload, BatchAnalyticsResponse)
        return _check_batch(response, len(payload["requests"]))

    async def _post(
        self, path: str, payload: dict[str, Any], model: type[_ResponseType]
    ) -> _ResponseType:
        try:
            response = await self._http.post(path, json=payload)
        except httpx.TimeoutException:
            raise RequestTimeout(
                "The request timed out; execution and CU charges may be unknown. "
                "No retry was attempted."
            ) from None
        except httpx.RequestError:
            raise TransportError(
                "The request failed before a complete response was received. "
                "Execution and CU charges may be unknown; no retry was attempted."
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
