# auditrails

Official Python SDK for [auditrails.io](https://auditrails.io) — tamper-proof audit logging as a service.

## Install

```bash
pip install auditrails
```

Requires Python 3.9+. Zero dependencies (uses stdlib `urllib`).

For async support:

```bash
pip install auditrails[async]
```

## Quick Start

```python
from auditrails import AuditRails, AuditEvent, Config

audit = AuditRails(Config(api_key="at_live_..."))

# Fire-and-forget (buffered, flushed in background thread)
audit.log(AuditEvent(
    action=Actions.AUTH_LOGIN,   # typed compliance action constant
    actor_id="user_123",
    resource="session/sess_456",
    metadata={"ip": "1.2.3.4"},
))

# Before process exit:
audit.close()
```

That's it. Your first audit event in under 2 minutes.

### Compliance Action Constants

The SDK includes `Actions` class with typed constants for all 42 compliance actions:

```python
from auditrails.actions import Actions

audit.log(AuditEvent(action=Actions.AUTH_LOGIN, actor_id="user_1"))
audit.log(AuditEvent(action=Actions.CONSENT_GIVEN, actor_id="user_1"))
audit.log(AuditEvent(action=Actions.PHI_ACCESSED, actor_id="user_1", resource="patient/123"))
```

Raw strings are still accepted for backward compatibility.

## API

### `AuditRails(config)`

| Config Option | Type | Default | Description |
|---------------|------|---------|-------------|
| `api_key` | `str` | **required** | Your API key (`at_live_...` or `at_test_...`) |
| `base_url` | `str` | `https://api.auditrails.io` | Ingestion API URL |
| `batch_size` | `int` | `100` | Max events per batch (max 100) |
| `flush_interval` | `float` | `1.0` | Auto-flush interval in seconds |
| `max_retries` | `int` | `3` | Retry attempts for 5xx errors |
| `timeout` | `float` | `10.0` | Request timeout in seconds |

### `audit.log(event)`

Buffer an event for batch sending. **Never raises** — errors are logged silently.

```python
audit.log(AuditEvent(
    action="document.created",    # required
    actor_id="user_123",          # who did it
    resource="document/doc-456",  # what was affected
    metadata={"key": "value"},    # extra context (max 10 keys)
))
```

### `audit.log_direct(event) -> LogResponse`

Send a single event immediately. Raises `AuditRailsError` on API errors.

```python
response = audit.log_direct(AuditEvent(action="user.deleted", actor_id="admin_1"))
print(response.log_id)      # "01HX..."
print(response.request_id)  # "req_01HX..."
```

### `audit.log_batch_direct(events) -> BatchResponse`

Send a batch of events immediately. Raises on error.

### `audit.flush()`

Flush all buffered events immediately.

### `audit.close()`

Flush remaining events and shut down. After `close()`, `log()` calls are silently ignored.

## Async Client

For asyncio applications, use `AsyncAuditRails` (requires `httpx`):

```python
from auditrails import AsyncAuditRails, AuditEvent, Config

audit = AsyncAuditRails(Config(api_key="at_live_..."))
await audit.start()

audit.log(AuditEvent(action="user.login", actor_id="user_123"))

response = await audit.log_direct(AuditEvent(action="user.deleted"))

await audit.close()
```

## Error Handling

The SDK **never crashes your application**:

- `log()` never raises — errors go to `logging.getLogger("auditrails")`
- `log_direct()` and `log_batch_direct()` raise `AuditRailsError` on API errors
- 5xx errors are retried with exponential backoff
- 4xx errors fail immediately (no retry)

```python
from auditrails import AuditRailsError

try:
    audit.log_direct(AuditEvent(action="test"))
except AuditRailsError as e:
    print(e.code)         # "validation/missing_action"
    print(e.status_code)  # 422
    print(e.request_id)   # "req_..."
    print(e.doc_url)      # link to docs
```

## Type Safety

The SDK is fully typed and ships with `py.typed` for mypy compatibility.

## License

MIT
