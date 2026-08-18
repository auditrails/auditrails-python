"""Types and data classes for the AuditRails SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AuditEvent:
    """An audit event to log.

    Args:
        action: The action being logged (e.g. "user.login"). Required.
        actor_id: The ID of the actor performing the action.
        resource: The resource being acted upon (e.g. "document/doc-123").
        metadata: Additional key-value metadata. Max 10 keys, values max 1KB each.
    """

    action: str
    actor_id: Optional[str] = None
    resource: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        """Convert to API payload format."""
        payload: Dict[str, Any] = {"action": self.action}
        if self.actor_id is not None:
            payload["actor_id"] = self.actor_id
        if self.resource is not None:
            payload["resource"] = self.resource
        if self.metadata is not None:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class Config:
    """Configuration for the AuditRails client.

    Args:
        api_key: Your API key (starts with at_live_ or at_test_). Required.
        base_url: Base URL for the ingestion API.
        batch_size: Maximum events to buffer before flushing. Max 100.
        flush_interval: Auto-flush interval in seconds.
        max_retries: Retry attempts for failed requests (5xx).
        timeout: Request timeout in seconds.
    """

    api_key: str
    base_url: str = "https://api.auditrails.io"
    batch_size: int = 100
    flush_interval: float = 1.0
    max_retries: int = 3
    timeout: float = 10.0

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("AuditRails: api_key is required")

    @property
    def effective_batch_size(self) -> int:
        return min(self.batch_size, 100)


@dataclass(frozen=True)
class LogResponse:
    """Response from logging a single event."""

    log_id: str
    request_id: str


@dataclass(frozen=True)
class BatchResponse:
    """Response from logging a batch of events."""

    log_ids: list[str] = field(default_factory=list)
    request_id: str = ""
