"""Errors without retained HTTP requests or credential-bearing trace messages."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from .models import ErrorResponse, ResponseMetadata, SolveTrialContext


class MorphIQError(Exception):
    """Base class for request/response failures from the SDK."""


class TransportError(MorphIQError):
    """No complete response was received. Execution and charges may be unknown."""


class RequestTimeout(TransportError):
    """A client timeout does not establish that the server did no work."""


class ResponseError(MorphIQError):
    """A successful HTTP status carried an invalid API response.

    Independently valid response metadata remains available even when the result
    is malformed. Missing metadata does not establish a zero charge.
    """

    def __init__(
        self,
        *,
        request_id: str | None,
        body: bytes,
        headers: dict[str, str],
        metadata: ResponseMetadata | None = None,
    ) -> None:
        self.metadata = metadata
        self.request_id = request_id or (metadata.request_id if metadata else None)
        self.body = body
        self.headers = headers
        super().__init__("The API returned an invalid API response; no retry was attempted.")


class APIError(MorphIQError):
    """Non-success HTTP response, including gateway and router failures.

    API failures are RFC 9457 problems: inspect ``code``, ``detail``, ``field``,
    ``request_id`` and ``metadata`` (with any ``metadata.billing`` charge), or the
    whole ``problem``. A gateway or router response that is not a MorphIQ
    problem leaves those as ``None``; ``headers`` and ``body`` are always kept.
    The known API key is redacted if a remote server reflects it in a response.
    Missing charge metadata is never interpreted as a zero charge.
    """

    def __init__(
        self,
        *,
        status_code: int,
        problem: ErrorResponse | None,
        request_id: str | None,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.status_code = status_code
        self.problem = problem
        self.code: str | None = problem.code if problem else None
        self.title: str | None = problem.title if problem else None
        self.detail: str = problem.detail if problem else "Non-standard API or gateway response"
        self.field: str | None = problem.field if problem else None
        self.solve_trial: SolveTrialContext | None = problem.solve_trial if problem else None
        self.metadata: ResponseMetadata | None = problem.metadata if problem else None
        self.request_id = self.metadata.request_id if self.metadata else request_id
        self.body = body
        self.headers = headers
        self.retry_after = headers.get("retry-after")
        code = f" ({self.code})" if self.code else ""
        support = f"; request_id={self.request_id}" if self.request_id else ""
        super().__init__(f"HTTP {status_code}{code}: {self.detail}{support}")


class RateLimitError(APIError):
    """HTTP 429, including gateway responses. No automatic wait, split or retry.

    ``retry_after`` retains the raw server header; ``retry_delay`` interprets
    delta-seconds or an HTTP date for callers choosing when to try again.
    Absence or an invalid value returns None, never an invented zero delay.
    """

    def retry_delay(self, *, now: datetime | None = None) -> float | None:
        value = self.retry_after
        if value is None:
            return None
        value = value.strip()
        try:
            if value.isascii() and value.isdigit():
                return float(int(value))
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            current = now if now is not None else datetime.now(UTC)
            if current.tzinfo is None:
                raise ValueError("now must include a timezone")
            return max(0.0, (retry_at - current).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
