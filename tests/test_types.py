"""Tests for AuditRails types."""

import pytest

from auditrails.types import AuditEvent, Config


class TestAuditEvent:
    def test_to_payload_all_fields(self) -> None:
        event = AuditEvent(
            action="user.login",
            actor_id="user_123",
            resource="session/sess_456",
            metadata={"ip": "1.2.3.4"},
        )
        payload = event.to_payload()
        assert payload == {
            "action": "user.login",
            "actor_id": "user_123",
            "resource": "session/sess_456",
            "metadata": {"ip": "1.2.3.4"},
        }

    def test_to_payload_required_only(self) -> None:
        event = AuditEvent(action="user.login")
        payload = event.to_payload()
        assert payload == {"action": "user.login"}
        assert "actor_id" not in payload
        assert "resource" not in payload
        assert "metadata" not in payload


class TestConfig:
    def test_raises_on_empty_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key is required"):
            Config(api_key="")

    def test_defaults(self) -> None:
        config = Config(api_key="at_test_123")
        assert config.base_url == "https://api.auditrails.io"
        assert config.batch_size == 100
        assert config.flush_interval == 1.0
        assert config.max_retries == 3
        assert config.timeout == 10.0

    def test_effective_batch_size_capped(self) -> None:
        config = Config(api_key="at_test_123", batch_size=500)
        assert config.effective_batch_size == 100
