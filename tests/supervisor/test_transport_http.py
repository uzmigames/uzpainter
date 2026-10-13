"""The Streamable HTTP guard and bind rules (python/uzpainter_supervisor/transport_http.py; task
phase2.5_mcp-transport-registry items 2.3 and 3.2; decision 159).

Pure Python: the guard is driven as an ASGI app in front of a stand-in app that records what
reaches it. The same refusals through `UzPainter.exe --mcp --mcp-http` are in
test_supervisor_transports.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from python.uzpainter_supervisor.transport_http import BindError, Guard, is_loopback, parse_bind

TOKEN = "s3cret-token-for-tests"


def send_through(guard: Guard, headers: dict[str, str]) -> tuple[int, bool]:
    """The status `guard` answers a POST with `headers`, and whether the app behind it ran."""
    reached: list[bool] = []
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(message)

    guard.app = app
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(guard(scope, receive, send))
    return int(sent[0]["status"]), bool(reached)


def test_origin_host_and_bearer_are_checked_before_the_app() -> None:
    guard = Guard(lambda *a: None, TOKEN, check_host=True)  # type: ignore[arg-type]
    good = {"host": "127.0.0.1:7777", "authorization": f"Bearer {TOKEN}"}
    assert send_through(guard, good) == (200, True)
    for origin in ("http://localhost:3000", "http://127.0.0.1", "http://[::1]:8080"):
        assert send_through(guard, {**good, "origin": origin}) == (200, True), origin
    for origin in ("http://evil.example", "https://127.0.0.1", "null", "http://10.0.0.5:7777"):
        assert send_through(guard, {**good, "origin": origin}) == (403, False), origin
    for host in ("evil.example:7777", "10.0.0.5:7777", ""):
        assert send_through(guard, {**good, "host": host}) == (421, False), host
    for host in ("localhost:7777", "[::1]:7777", "127.0.0.2:7777"):
        assert send_through(guard, {**good, "host": host}) == (200, True), host
    for auth in (None, "Bearer", "Bearer wrong", f"Basic {TOKEN}", f"Bearer {TOKEN}x"):
        headers = dict(good)
        if auth is None:
            del headers["authorization"]
        else:
            headers["authorization"] = auth
        assert send_through(guard, headers) == (401, False), auth
    remote = Guard(lambda *a: None, TOKEN, check_host=False)  # type: ignore[arg-type]
    assert send_through(remote, {**good, "host": "10.0.0.5:7777"}) == (200, True)
    assert send_through(remote, {"host": "10.0.0.5:7777"}) == (401, False)


def test_bind_addresses() -> None:
    assert parse_bind("127.0.0.1:7777", False) == ("127.0.0.1", 7777)
    assert parse_bind("localhost:0", False) == ("localhost", 0)
    assert parse_bind("[::1]:7777", False) == ("::1", 7777)
    assert parse_bind("0.0.0.0:7777", True) == ("0.0.0.0", 7777)
    for text in ("0.0.0.0:7777", "192.168.1.4:7777", "[::]:7777"):
        with pytest.raises(BindError, match="--allow-remote"):
            parse_bind(text, False)
    for text in ("7777", "127.0.0.1", "127.0.0.1:x", "127.0.0.1:70000", "example.com:7777"):
        with pytest.raises(BindError):
            parse_bind(text, True)
    assert is_loopback("127.1.2.3") and is_loopback("[::1]") and not is_loopback("0.0.0.0")
