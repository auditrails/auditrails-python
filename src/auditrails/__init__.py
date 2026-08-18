"""Official Python SDK for auditrails.io — tamper-proof audit logging as a service."""

from auditrails.client import AuditRails
from auditrails.async_client import AsyncAuditRails
from auditrails.types import AuditEvent, Config, LogResponse, BatchResponse
from auditrails.errors import AuditRailsError, AuditRailsTimeoutError

__all__ = [
    "AuditRails",
    "AsyncAuditRails",
    "AuditEvent",
    "Config",
    "LogResponse",
    "BatchResponse",
    "AuditRailsError",
    "AuditRailsTimeoutError",
]

__version__ = "1.0.0"
