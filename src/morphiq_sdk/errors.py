"""Errors without retained HTTP requests or credential-bearing trace messages."""

from .models import ErrorEnvelope, ResponseMetadata, ServiceErrorMetadata


class MorphIQError(Exception):
    """Base class for request/response failures from the SDK."""


class TransportError(MorphIQError):
    """No complete response was received. Execution and charges may be unknown."""


class RequestTimeout(TransportError):
    """A client timeout does not establish that the server did no work."""


class ResponseError(MorphIQError):
    """A successful HTTP status carried an invalid API response.

    Independently valid pricing metadata remains available even when the result
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

    Inspect ``code``, ``request_id``, ``metadata``, ``headers`` and ``body``.
    The known API key is redacted if a remote server reflects it in a response.
    Missing charge metadata is never interpreted as a zero charge.
    """

    def __init__(
        self,
        *,
        status_code: int,
        envelope: ErrorEnvelope | None,
        request_id: str | None,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.status_code = status_code
        self.code = envelope.error.code if envelope else None
        self.message = (
            envelope.error.message if envelope else "Non-standard API or gateway response"
        )
        self.field = envelope.error.field if envelope else None
        self.metadata: ResponseMetadata | ServiceErrorMetadata | None = (
            envelope.metadata if envelope else None
        )
        self.request_id = self.metadata.request_id if self.metadata else request_id
        self.body = body
        self.headers = headers
        self.retry_after = headers.get("retry-after")
        detail = f" ({self.code})" if self.code else ""
        support = f"; request_id={self.request_id}" if self.request_id else ""
        super().__init__(f"HTTP {status_code}{detail}: {self.message}{support}")
