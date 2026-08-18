"""Error types for the AuditRails SDK."""

from __future__ import annotations


class AuditRailsError(Exception):
    """Error raised when the AuditRails API returns an error response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        request_id: str = "",
        doc_url: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.doc_url = doc_url

    @property
    def retryable(self) -> bool:
        """Whether this error is retryable (5xx server errors)."""
        return self.status_code >= 500


class AuditRailsTimeoutError(Exception):
    """Error raised when a request times out."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"Request timed out after {timeout}s")
        self.timeout = timeout
