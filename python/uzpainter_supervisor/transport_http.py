"""Streamable HTTP mode: `UzPainter.exe --mcp --mcp-http <host>:<port> [--token <token>]
[--allow-remote]` (11-mcp-server.md §1, §4; task phase2.5_mcp-transport-registry, decision 159).

A resident supervisor serves the SDK's Streamable HTTP app at `http://<host>:<port>/mcp` on uvicorn,
in the supervisor's own event loop, over the same tool registry as stdio. `Guard` checks every HTTP
request before the SDK sees it:

- **Origin.** A request that carries an `Origin` header must come from an `http` origin on a
  loopback host (`localhost`, `127.0.0.0/8`, `[::1]`; any port): 403 otherwise. A client that is
  not a browser sends no Origin.
- **Host.** When the server is bound to a loopback address, the `Host` header must name a loopback
  host: 421 otherwise (DNS rebinding). With `--allow-remote` the Host check is off, the bearer
  token is the only guard, and the start-up says so on stderr.
- **Bearer.** `Authorization: Bearer <token>` on every request and method, compared in constant
  time: 401 otherwise. The token is `--token`'s, or one generated at start
  (`secrets.token_urlsafe(32)`) and printed once on stderr; it is never logged to the ledger.

A bind address that is not a loopback address is a usage error without `--allow-remote`. The
traffic is plain HTTP: a remote bind belongs on a trusted network.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import logging
import signal
import sys
import threading
import urllib.parse
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from typing import Any

log = logging.getLogger("uzpainter.supervisor")

MCP_PATH = "/mcp"

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]


class BindError(ValueError):
    """A malformed or refused `--mcp-http` address."""


def is_loopback(host: str) -> bool:
    """Whether `host` (a name or an IP literal, IPv6 with or without brackets) is loopback."""
    host = host.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_bind(text: str, allow_remote: bool) -> tuple[str, int]:
    """`<host>:<port>` (IPv6 as `[addr]:<port>`): the host and the port; `BindError`."""
    host, sep, port_text = text.rpartition(":")
    if not sep or not host or not port_text.isdigit():
        raise BindError("--mcp-http needs <host>:<port>, e.g. 127.0.0.1:7777")
    port = int(port_text)
    if not 0 <= port <= 65535:
        raise BindError("--mcp-http port must be between 0 and 65535")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.lower() != "localhost":
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise BindError("--mcp-http host must be an IP address or localhost") from None
    if not is_loopback(host) and not allow_remote:
        raise BindError(
            "--mcp-http binds only to a loopback address unless --allow-remote is given"
        )
    return host, port


def _host_name(value: str) -> str:
    """The host of a `Host` header value (without its port)."""
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class Guard:
    """The ASGI app that checks Origin, Host and the bearer token before `app`."""

    def __init__(self, app: App, token: str, check_host: bool) -> None:
        self.app = app
        self.token = token.encode("utf-8")
        self.check_host = check_host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        refusal = self._refusal(headers)
        if refusal is None:
            await self.app(scope, receive, send)
            return
        status, message, extra = refusal
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), *extra],
            }
        )
        await send({"type": "http.response.body", "body": message.encode("utf-8")})

    def _refusal(
        self, headers: dict[str, str]
    ) -> tuple[int, str, list[tuple[bytes, bytes]]] | None:
        origin = headers.get("origin")
        if origin is not None:
            parsed = urllib.parse.urlsplit(origin)
            if parsed.scheme != "http" or not parsed.hostname or not is_loopback(parsed.hostname):
                log.warning("refused an HTTP request with an invalid Origin")
                return 403, "Invalid Origin header", []
        if self.check_host and not is_loopback(_host_name(headers.get("host", ""))):
            log.warning("refused an HTTP request with an invalid Host")
            return 421, "Invalid Host header", []
        scheme, _, given = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            given.strip().encode("utf-8"), self.token
        ):
            return 401, "Missing or invalid bearer token", [(b"www-authenticate", b"Bearer")]
        return None


async def serve(server: Any, host: str, port: int, token: str) -> None:
    """Serves `server` (the SDK's low-level `Server`) on `http://<host>:<port>/mcp` until the
    process is asked to stop (Ctrl+C or Ctrl+Break)."""
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    # The guard owns Origin and Host; the SDK still checks the media types.
    app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host=host,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    loopback = is_loopback(host)
    config = uvicorn.Config(
        Guard(app, token, check_host=loopback),
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        lifespan="on",
    )
    http_server = _server_class()(config)
    if not loopback:
        print(
            "uzpainter supervisor: WARNING --allow-remote: the Host check is off and the bearer "
            "token is the only guard; the traffic is plain HTTP",
            file=sys.stderr,
            flush=True,
        )
    announce = asyncio.ensure_future(_announce(http_server, host))
    try:
        await http_server.serve()
    finally:
        announce.cancel()


def _server_class() -> Any:
    import uvicorn

    class Server(uvicorn.Server):  # type: ignore[misc]
        """uvicorn's server, whose stop signals end `serve()` and are not raised again after it
        (uvicorn re-raises them, which would end the process before the supervisor closes its
        worker and its ledger)."""

        @contextlib.contextmanager
        def capture_signals(self) -> Iterator[None]:
            if threading.current_thread() is not threading.main_thread():
                yield
                return
            handled = [signal.SIGINT, signal.SIGTERM, signal.SIGBREAK]
            previous = {sig: signal.signal(sig, self.handle_exit) for sig in handled}
            try:
                yield
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)

    return Server


async def _announce(http_server: Any, host: str) -> None:
    """Logs the address once uvicorn listens (its port when 0 was asked)."""
    while not http_server.started:
        await asyncio.sleep(0.05)
    port = http_server.servers[0].sockets[0].getsockname()[1]
    shown = f"[{host}]" if ":" in host else host
    log.info("mcp http listening on http://%s:%d%s", shown, port, MCP_PATH)
