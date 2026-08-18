"""Tests for AuditRails error types."""

from auditrails.errors import AuditRailsError, AuditRailsTimeoutError


class TestAuditRailsError:
    def test_captures_details(self) -> None:
        err = AuditRailsError(
            status_code=422,
            code="validation/missing_action",
            message="The 'action' field is required.",
            request_id="req_123",
            doc_url="https://docs.auditrails.io/errors/validation/missing_action",
        )
        assert err.status_code == 422
        assert err.code == "validation/missing_action"
        assert str(err) == "The 'action' field is required."
        assert err.request_id == "req_123"
        assert err.doc_url == "https://docs.auditrails.io/errors/validation/missing_action"

    def test_retryable_for_5xx(self) -> None:
        err = AuditRailsError(500, "event/write_failed", "Internal error")
        assert err.retryable is True

    def test_not_retryable_for_4xx(self) -> None:
        err = AuditRailsError(429, "rate/limit_exceeded", "Rate limit exceeded")
        assert err.retryable is False

    def test_is_exception(self) -> None:
        err = AuditRailsError(400, "test", "test")
        assert isinstance(err, Exception)


class TestAuditRailsTimeoutError:
    def test_includes_timeout(self) -> None:
        err = AuditRailsTimeoutError(10.0)
        assert "10.0s" in str(err)
        assert err.timeout == 10.0
