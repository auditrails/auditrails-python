"""Tests for the synchronous AuditRails client."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from auditrails.client import AuditRails
from auditrails.errors import AuditRailsError
from auditrails.types import AuditEvent, Config


class MockHandler(BaseHTTPRequestHandler):
    """HTTP handler that records requests and returns configured responses."""

    responses: List[Tuple[int, Dict[str, Any]]] = []
    requests: List[Tuple[str, Dict[str, Any]]] = []
    call_index: int = 0

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        MockHandler.requests.append((self.path, body))

        if MockHandler.call_index < len(MockHandler.responses):
            status, response_body = MockHandler.responses[MockHandler.call_index]
            MockHandler.call_index += 1
        else:
            status, response_body = 500, {"error": {"code": "test/no_response", "message": "No mock response"}}

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response_body).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress server logs


@pytest.fixture()
def mock_server():
    """Start a mock HTTP server and return (url, handler_class)."""
    MockHandler.responses = []
    MockHandler.requests = []
    MockHandler.call_index = 0

    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", MockHandler

    server.shutdown()


def make_client(base_url: str, **kwargs: Any) -> AuditRails:
    config = Config(
        api_key="at_test_abc123",
        base_url=base_url,
        flush_interval=60.0,  # disable auto-flush for tests
        max_retries=kwargs.pop("max_retries", 0),
        batch_size=kwargs.pop("batch_size", 100),
        **kwargs,
    )
    return AuditRails(config)


class TestLog:
    def test_buffers_and_flushes_single_event(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_id": "log_1", "request_id": "req_1"})]

        client = make_client(url)
        client.log(AuditEvent(action="user.login", actor_id="user_123"))
        client.flush()

        assert len(handler.requests) == 1
        path, body = handler.requests[0]
        assert path == "/v1/events"
        assert body["action"] == "user.login"
        assert body["actor_id"] == "user_123"
        client.close()

    def test_flushes_as_batch_for_multiple_events(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_ids": ["a", "b"], "request_id": "req_1"})]

        client = make_client(url)
        client.log(AuditEvent(action="user.login"))
        client.log(AuditEvent(action="user.logout"))
        client.flush()

        assert len(handler.requests) == 1
        path, body = handler.requests[0]
        assert path == "/v1/events/batch"
        assert len(body["events"]) == 2
        assert body["events"][0]["action"] == "user.login"
        assert body["events"][1]["action"] == "user.logout"
        client.close()

    def test_ignores_empty_action(self, mock_server: Any) -> None:
        url, handler = mock_server
        client = make_client(url)
        client.log(AuditEvent(action=""))
        client.flush()
        assert len(handler.requests) == 0
        client.close()

    def test_ignores_events_after_close(self, mock_server: Any) -> None:
        url, handler = mock_server
        client = make_client(url)
        client.close()
        client.log(AuditEvent(action="test"))
        assert len(handler.requests) == 0

    def test_auto_flushes_at_batch_size(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_ids": ["a", "b"], "request_id": "req_1"})]

        client = make_client(url, batch_size=2)
        client.log(AuditEvent(action="event.one"))
        client.log(AuditEvent(action="event.two"))

        # Wait for background flush
        time.sleep(0.2)
        assert len(handler.requests) == 1
        client.close()

    def test_includes_metadata_and_resource(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_id": "test", "request_id": "req_test"})]

        client = make_client(url)
        client.log(AuditEvent(
            action="document.created",
            actor_id="user_1",
            resource="document/doc-123",
            metadata={"key": "value"},
        ))
        client.flush()

        _, body = handler.requests[0]
        assert body["resource"] == "document/doc-123"
        assert body["metadata"] == {"key": "value"}
        client.close()


class TestLogDirect:
    def test_sends_single_event(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_id": "log_abc", "request_id": "req_xyz"})]

        client = make_client(url)
        result = client.log_direct(AuditEvent(action="user.login", actor_id="u1"))

        assert result.log_id == "log_abc"
        assert result.request_id == "req_xyz"
        client.close()

    def test_throws_on_api_error(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(422, {
            "error": {
                "code": "validation/missing_action",
                "message": "The 'action' field is required.",
                "request_id": "req_1",
                "doc_url": "",
            },
        })]

        client = make_client(url)
        with pytest.raises(AuditRailsError) as exc_info:
            client.log_direct(AuditEvent(action="test"))
        assert exc_info.value.status_code == 422
        client.close()

    def test_throws_when_closed(self, mock_server: Any) -> None:
        url, _ = mock_server
        client = make_client(url)
        client.close()
        with pytest.raises(RuntimeError, match="client is closed"):
            client.log_direct(AuditEvent(action="test"))


class TestLogBatchDirect:
    def test_sends_batch(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_ids": ["a", "b"], "request_id": "req_1"})]

        client = make_client(url)
        result = client.log_batch_direct([
            AuditEvent(action="user.login"),
            AuditEvent(action="user.logout"),
        ])

        assert result.log_ids == ["a", "b"]
        assert result.request_id == "req_1"
        client.close()

    def test_rejects_empty_list(self, mock_server: Any) -> None:
        url, _ = mock_server
        client = make_client(url)
        with pytest.raises(ValueError, match="events list is empty"):
            client.log_batch_direct([])
        client.close()

    def test_rejects_oversized_batch(self, mock_server: Any) -> None:
        url, _ = mock_server
        client = make_client(url)
        events = [AuditEvent(action=f"event.{i}") for i in range(101)]
        with pytest.raises(ValueError, match="batch size exceeds"):
            client.log_batch_direct(events)
        client.close()


class TestRetry:
    def test_retries_on_5xx(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [
            (500, {"error": {"code": "event/write_failed", "message": "err"}}),
            (202, {"log_id": "ok", "request_id": "req_ok"}),
        ]

        client = make_client(url, max_retries=1)
        result = client.log_direct(AuditEvent(action="test"))
        assert result.log_id == "ok"
        assert len(handler.requests) == 2
        client.close()

    def test_no_retry_on_4xx(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(422, {
            "error": {"code": "validation/missing_action", "message": "err", "request_id": "", "doc_url": ""},
        })]

        client = make_client(url, max_retries=3)
        with pytest.raises(AuditRailsError):
            client.log_direct(AuditEvent(action="test"))
        assert len(handler.requests) == 1
        client.close()

    def test_exhausts_retries(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [
            (500, {"error": {"code": "event/write_failed", "message": "err"}}),
            (500, {"error": {"code": "event/write_failed", "message": "err"}}),
        ]

        client = make_client(url, max_retries=1)
        with pytest.raises(AuditRailsError):
            client.log_direct(AuditEvent(action="test"))
        assert len(handler.requests) == 2
        client.close()


class TestErrorIsolation:
    def test_flush_does_not_throw_on_error(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [
            (500, {"error": {"code": "event/write_failed", "message": "err"}}),
        ]

        client = make_client(url, max_retries=0)
        client.log(AuditEvent(action="test"))
        # Should not raise
        client.flush()
        client.close()


class TestClose:
    def test_flushes_remaining_events(self, mock_server: Any) -> None:
        url, handler = mock_server
        handler.responses = [(202, {"log_id": "test", "request_id": "req_test"})]

        client = make_client(url)
        client.log(AuditEvent(action="final.event"))
        client.close()

        assert len(handler.requests) == 1

    def test_is_idempotent(self, mock_server: Any) -> None:
        url, _ = mock_server
        client = make_client(url)
        client.close()
        client.close()  # Should not raise
