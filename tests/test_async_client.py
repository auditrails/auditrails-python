"""Tests for the async AuditRails client."""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Dict, List, Tuple

import pytest

from auditrails.async_client import AsyncAuditRails
from auditrails.errors import AuditRailsError
from auditrails.types import AuditEvent, Config


class AsyncMockHandler(BaseHTTPRequestHandler):
    """HTTP handler for async client tests."""

    responses: List[Tuple[int, Dict[str, Any]]] = []
    requests: List[Tuple[str, Dict[str, Any]]] = []
    call_index: int = 0

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        AsyncMockHandler.requests.append((self.path, body))

        if AsyncMockHandler.call_index < len(AsyncMockHandler.responses):
            status, response_body = AsyncMockHandler.responses[AsyncMockHandler.call_index]
            AsyncMockHandler.call_index += 1
        else:
            status, response_body = 500, {"error": {"code": "test/no_response", "message": "No mock"}}

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response_body).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture()
def async_mock_server():
    AsyncMockHandler.responses = []
    AsyncMockHandler.requests = []
    AsyncMockHandler.call_index = 0

    server = HTTPServer(("127.0.0.1", 0), AsyncMockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", AsyncMockHandler

    server.shutdown()


async def make_async_client(base_url: str, **kwargs: Any) -> AsyncAuditRails:
    config = Config(
        api_key="at_test_abc123",
        base_url=base_url,
        flush_interval=60.0,
        max_retries=kwargs.pop("max_retries", 0),
        batch_size=kwargs.pop("batch_size", 100),
        **kwargs,
    )
    client = AsyncAuditRails(config)
    await client.start()
    return client


@pytest.mark.asyncio
class TestAsyncLogDirect:
    async def test_sends_single_event(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [(202, {"log_id": "log_abc", "request_id": "req_xyz"})]

        client = await make_async_client(url)
        result = await client.log_direct(AuditEvent(action="user.login", actor_id="u1"))

        assert result.log_id == "log_abc"
        assert result.request_id == "req_xyz"
        await client.close()

    async def test_throws_on_api_error(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [(422, {
            "error": {
                "code": "validation/missing_action",
                "message": "err",
                "request_id": "",
                "doc_url": "",
            },
        })]

        client = await make_async_client(url)
        with pytest.raises(AuditRailsError) as exc_info:
            await client.log_direct(AuditEvent(action="test"))
        assert exc_info.value.status_code == 422
        await client.close()

    async def test_throws_when_closed(self, async_mock_server: Any) -> None:
        url, _ = async_mock_server
        client = await make_async_client(url)
        await client.close()
        with pytest.raises(RuntimeError, match="client is closed"):
            await client.log_direct(AuditEvent(action="test"))


@pytest.mark.asyncio
class TestAsyncFlush:
    async def test_buffers_and_flushes(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [(202, {"log_id": "a", "request_id": "req_a"})]

        client = await make_async_client(url)
        client.log(AuditEvent(action="user.login"))
        await client.flush()

        assert len(handler.requests) == 1
        _, body = handler.requests[0]
        assert body["action"] == "user.login"
        await client.close()

    async def test_close_flushes_remaining(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [(202, {"log_id": "test", "request_id": "req_test"})]

        client = await make_async_client(url)
        client.log(AuditEvent(action="final.event"))
        await client.close()

        assert len(handler.requests) == 1


@pytest.mark.asyncio
class TestAsyncRetry:
    async def test_retries_on_5xx(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [
            (500, {"error": {"code": "event/write_failed", "message": "err"}}),
            (202, {"log_id": "ok", "request_id": "req_ok"}),
        ]

        client = await make_async_client(url, max_retries=1)
        result = await client.log_direct(AuditEvent(action="test"))
        assert result.log_id == "ok"
        assert len(handler.requests) == 2
        await client.close()

    async def test_no_retry_on_4xx(self, async_mock_server: Any) -> None:
        url, handler = async_mock_server
        handler.responses = [(422, {
            "error": {"code": "validation/missing_action", "message": "err", "request_id": "", "doc_url": ""},
        })]

        client = await make_async_client(url, max_retries=3)
        with pytest.raises(AuditRailsError):
            await client.log_direct(AuditEvent(action="test"))
        assert len(handler.requests) == 1
        await client.close()
