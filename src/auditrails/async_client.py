"""Async AuditRails client using httpx."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from auditrails.errors import AuditRailsError, AuditRailsTimeoutError
from auditrails.types import AuditEvent, BatchResponse, Config, LogResponse

logger = logging.getLogger("auditrails")

_MAX_BATCH_SIZE = 100


class AsyncAuditRails:
    """Async AuditRails client using httpx.

    Buffers events in memory and flushes them in batches via an asyncio task.

    Requires the ``async`` extra::

        pip install auditrails[async]

    Example::

        from auditrails import AsyncAuditRails, AuditEvent, Config

        audit = AsyncAuditRails(Config(api_key="at_live_..."))
        await audit.start()

        audit.log(AuditEvent(action="user.login", actor_id="user_123"))

        await audit.close()  # flushes remaining events
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._buffer: List[AuditEvent] = []
        self._lock = asyncio.Lock()
        self._closed = False
        self._flush_task: Optional[asyncio.Task[None]] = None
        self._client: Any = None  # httpx.AsyncClient, lazy import

    async def start(self) -> None:
        """Start the background flush loop and HTTP client."""
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for AsyncAuditRails. "
                "Install with: pip install auditrails[async]"
            ) from None

        self._client = httpx.AsyncClient(timeout=self._config.timeout)
        self._flush_task = asyncio.create_task(self._flush_loop())

    def log(self, event: AuditEvent) -> None:
        """Buffer an audit event for batch sending.

        This method is synchronous and safe to call from async code.
        Never raises — errors are logged silently.
        """
        if self._closed:
            logger.warning("AuditRails: client is closed, ignoring event")
            return

        if not event.action:
            logger.error("AuditRails: action is required, ignoring event")
            return

        self._buffer.append(event)
        logger.debug("AuditRails: buffered event (%d/%d)", len(self._buffer), self._config.effective_batch_size)

    async def flush(self) -> None:
        """Immediately flush all buffered events to the API."""
        async with self._lock:
            if not self._buffer:
                return
            events = self._buffer[:]
            self._buffer.clear()

        await self._send_batch(events)

    async def log_direct(self, event: AuditEvent) -> LogResponse:
        """Send a single event directly and return the response.

        Raises:
            AuditRailsError: On API errors.
            RuntimeError: If the client is closed or not started.
        """
        if self._closed:
            raise RuntimeError("AuditRails: client is closed")
        if self._client is None:
            raise RuntimeError("AuditRails: client not started, call await audit.start() first")

        data = await self._request_with_retry("/v1/events", event.to_payload())
        return LogResponse(log_id=data["log_id"], request_id=data["request_id"])

    async def log_batch_direct(self, events: List[AuditEvent]) -> BatchResponse:
        """Send a batch of events directly and return the response.

        Raises:
            AuditRailsError: On API errors.
            ValueError: If events is empty or exceeds 100.
            RuntimeError: If the client is closed or not started.
        """
        if self._closed:
            raise RuntimeError("AuditRails: client is closed")
        if self._client is None:
            raise RuntimeError("AuditRails: client not started, call await audit.start() first")

        if not events:
            raise ValueError("AuditRails: events list is empty")

        if len(events) > _MAX_BATCH_SIZE:
            raise ValueError(f"AuditRails: batch size exceeds maximum of {_MAX_BATCH_SIZE}")

        data = await self._request_with_retry(
            "/v1/events/batch",
            {"events": [e.to_payload() for e in events]},
        )
        return BatchResponse(log_ids=data["log_ids"], request_id=data["request_id"])

    async def close(self) -> None:
        """Flush remaining events and shut down."""
        if self._closed:
            return

        self._closed = True

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        await self.flush()

        if self._client:
            await self._client.aclose()

    async def _flush_loop(self) -> None:
        """Background task that flushes events periodically."""
        while not self._closed:
            await asyncio.sleep(self._config.flush_interval)
            try:
                await self.flush()
            except Exception:
                pass

    async def _send_batch(self, events: List[AuditEvent]) -> None:
        """Send a batch of events, handling errors silently."""
        if not events:
            return

        try:
            if len(events) == 1:
                await self._request_with_retry("/v1/events", events[0].to_payload())
            else:
                await self._request_with_retry(
                    "/v1/events/batch",
                    {"events": [e.to_payload() for e in events]},
                )
            logger.info("AuditRails: flushed %d event(s)", len(events))
        except Exception as exc:
            logger.error("AuditRails: failed to flush %d event(s): %s", len(events), exc)

    async def _request_with_retry(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Make an HTTP request with exponential backoff retry on 5xx."""
        url = f"{self._base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(self._config.max_retries + 1):
            if attempt > 0:
                delay = min(0.2 * (2 ** (attempt - 1)), 10.0)
                await asyncio.sleep(delay)

            try:
                return await self._do_request(url, body)
            except AuditRailsError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
                logger.warning(
                    "AuditRails: request failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._config.max_retries + 1,
                    exc,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "AuditRails: request error (attempt %d/%d): %s",
                    attempt + 1,
                    self._config.max_retries + 1,
                    exc,
                )

        if isinstance(last_error, AuditRailsError):
            raise last_error
        raise RuntimeError(f"AuditRails: request failed: {last_error}") from last_error

    async def _do_request(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single HTTP POST request using httpx."""
        import httpx

        try:
            response = await self._client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "User-Agent": "auditrails-python/1.0.0",
                },
            )
        except httpx.TimeoutException as exc:
            raise AuditRailsTimeoutError(self._config.timeout) from exc

        if 200 <= response.status_code < 300:
            return response.json()  # type: ignore[no-any-return]

        try:
            error_data = response.json().get("error", {})
        except Exception:
            error_data = {}

        raise AuditRailsError(
            status_code=response.status_code,
            code=error_data.get("code", "unknown"),
            message=error_data.get("message", response.reason_phrase),
            request_id=error_data.get("request_id", ""),
            doc_url=error_data.get("doc_url", ""),
        )
