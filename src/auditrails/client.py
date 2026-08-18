"""Synchronous AuditRails client with background thread for batching."""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from auditrails.errors import AuditRailsError, AuditRailsTimeoutError
from auditrails.types import AuditEvent, BatchResponse, Config, LogResponse

logger = logging.getLogger("auditrails")

_MAX_BATCH_SIZE = 100


class AuditRails:
    """AuditRails Python SDK client.

    Buffers events in memory and flushes them in batches via a background
    thread. Events are flushed every ``flush_interval`` seconds or when
    the buffer reaches ``batch_size``.

    Example::

        from auditrails import AuditRails, AuditEvent, Config

        audit = AuditRails(Config(api_key="at_live_..."))
        audit.log(AuditEvent(action="user.login", actor_id="user_123"))
        # Events flush automatically in the background
        # Call audit.close() before process exit

    Uses only stdlib (``urllib.request``). Zero external dependencies.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._buffer: List[AuditEvent] = []
        self._lock = threading.Lock()
        self._closed = False

        # Start background flush thread
        self._flush_event = threading.Event()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

        atexit.register(self.close)

    def log(self, event: AuditEvent) -> None:
        """Buffer an audit event for batch sending.

        Never raises — errors are logged silently.
        """
        if self._closed:
            logger.warning("AuditRails: client is closed, ignoring event")
            return

        if not event.action:
            logger.error("AuditRails: action is required, ignoring event")
            return

        with self._lock:
            self._buffer.append(event)
            buffer_len = len(self._buffer)

        logger.debug("AuditRails: buffered event (%d/%d)", buffer_len, self._config.effective_batch_size)

        if buffer_len >= self._config.effective_batch_size:
            self._flush_event.set()

    def flush(self) -> None:
        """Immediately flush all buffered events to the API."""
        with self._lock:
            if not self._buffer:
                return
            events = self._buffer[:]
            self._buffer.clear()

        self._send_batch(events)

    def log_direct(self, event: AuditEvent) -> LogResponse:
        """Send a single event directly and return the response.

        Unlike ``log()``, this blocks until the API responds and may raise.

        Raises:
            AuditRailsError: On API errors.
            RuntimeError: If the client is closed.
        """
        if self._closed:
            raise RuntimeError("AuditRails: client is closed")

        data = self._request_with_retry("/v1/events", event.to_payload())
        return LogResponse(log_id=data["log_id"], request_id=data["request_id"])

    def log_batch_direct(self, events: List[AuditEvent]) -> BatchResponse:
        """Send a batch of events directly and return the response.

        Raises:
            AuditRailsError: On API errors.
            ValueError: If events is empty or exceeds 100.
            RuntimeError: If the client is closed.
        """
        if self._closed:
            raise RuntimeError("AuditRails: client is closed")

        if not events:
            raise ValueError("AuditRails: events list is empty")

        if len(events) > _MAX_BATCH_SIZE:
            raise ValueError(f"AuditRails: batch size exceeds maximum of {_MAX_BATCH_SIZE}")

        data = self._request_with_retry(
            "/v1/events/batch",
            {"events": [e.to_payload() for e in events]},
        )
        return BatchResponse(log_ids=data["log_ids"], request_id=data["request_id"])

    def close(self) -> None:
        """Flush remaining events and shut down.

        After calling ``close()``, ``log()`` calls are silently ignored.
        """
        if self._closed:
            return

        self._closed = True
        self._flush_event.set()
        self._thread.join(timeout=5.0)
        self.flush()

    def _flush_loop(self) -> None:
        """Background thread that flushes events periodically."""
        while not self._closed:
            self._flush_event.wait(timeout=self._config.flush_interval)
            self._flush_event.clear()
            try:
                self.flush()
            except Exception:
                pass  # flush() already handles errors internally

    def _send_batch(self, events: List[AuditEvent]) -> None:
        """Send a batch of events, handling errors silently."""
        if not events:
            return

        try:
            if len(events) == 1:
                self._request_with_retry("/v1/events", events[0].to_payload())
            else:
                self._request_with_retry(
                    "/v1/events/batch",
                    {"events": [e.to_payload() for e in events]},
                )
            logger.info("AuditRails: flushed %d event(s)", len(events))
        except Exception as exc:
            logger.error("AuditRails: failed to flush %d event(s): %s", len(events), exc)
            # Events are dropped — SDK never crashes the host application

    def _request_with_retry(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Make an HTTP request with exponential backoff retry on 5xx."""
        url = f"{self._base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(self._config.max_retries + 1):
            if attempt > 0:
                delay = min(0.2 * (2 ** (attempt - 1)), 10.0)
                time.sleep(delay)

            try:
                return self._do_request(url, body)
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
            except AuditRailsTimeoutError as exc:
                last_error = exc
                logger.warning(
                    "AuditRails: request timeout (attempt %d/%d): %s",
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

    def _do_request(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single HTTP POST request using urllib."""
        data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
                "User-Agent": "auditrails-python/1.0.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                error_data = error_body.get("error", {})
            except Exception:
                error_data = {}

            raise AuditRailsError(
                status_code=exc.code,
                code=error_data.get("code", "unknown"),
                message=error_data.get("message", exc.reason),
                request_id=error_data.get("request_id", ""),
                doc_url=error_data.get("doc_url", ""),
            ) from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason):
                raise AuditRailsTimeoutError(self._config.timeout) from exc
            raise
