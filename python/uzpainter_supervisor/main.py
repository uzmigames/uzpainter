"""`UzPainter.exe --mcp`: the command line and the MCP transports (src/supervisor/supervisor.h).

Both transports serve one tool registry (registry.py; task phase2.5, decisions 158 and 159):

- **stdio** (the default): the SDK's `stdio_server`. While it serves, stdout carries protocol
  frames only: the SDK points the process's file descriptor 1 at stderr, so stray output from any
  code in the process misses the wire. Logs go to stderr and to the ledger's `log` table.
- **Streamable HTTP** (`--mcp-http <host>:<port>`, transport_http.py): Origin, Host and bearer
  checks; a non-loopback bind needs `--allow-remote`. HTTP clients take the mutation lease
  explicitly with `lease_acquire {owner}`.

A console Ctrl+C or Ctrl+Break stops either transport through one shutdown: the worker ends (the OS
removes its project's lock sidecar with it), then the ledger closes, checkpointing its WAL.

`--roots` confines the structured tools' path arguments (roots.py). The registry checks every call
before admission (admission.py); a long tool (the worker lists it as `long`) takes `wait` too and
runs as a job (phase2.3): its progress reaches a client that waits as `notifications/progress` on
the request's progress token, with `{job_id, status, progress, message}` under
`_meta["uzpainter/job"]`. The resources and prompts (resources.py; phase2.6, decision 165) are
served over the same registry; `capture`'s image block is built by the native helper
`_uzpainter_image` of UzPainter.exe.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import secrets
import signal
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from . import transport_http
from . import worker as worker_module
from .admission import Admission
from .ledger import DEFAULT_PATH, Ledger, LogHandler, process_identity
from .registry import Client, Manifest, ManifestError, Registry, Thumbnail
from .resources import (
    JOB_TEMPLATE,
    JSON,
    PROMPTS,
    RESOURCE_NOT_FOUND,
    RESOURCES,
    ResourceError,
    Resources,
)
from .roots import Roots, RootsError

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FATAL = 4

JOB_META_KEY = "uzpainter/job"
MAX_HTTP_CLIENTS = 10_000  # the SDK's session limit
# The console stops the stdio transport handles; the HTTP transport takes the same through uvicorn.
CONSOLE_STOP_SIGNALS = (signal.SIGINT, signal.SIGBREAK)

log = logging.getLogger("uzpainter.supervisor")


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # never exits the process
        raise _UsageError(message)


def parse_args(argv: list[str], hooks_compiled: bool) -> argparse.Namespace:
    parser = _Parser(prog="UzPainter.exe --mcp", add_help=False)
    parser.add_argument("--gpu-backend", choices=("dx12", "vulkan"), default="dx12")
    parser.add_argument("--allow-python", action="store_true")
    parser.add_argument("--gpu-deadline-ms", type=int)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--crash-dir", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--test-faults", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--mcp-http")
    parser.add_argument("--token")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--roots")
    args = parser.parse_args(argv)
    if args.gpu_deadline_ms is not None and not 1 <= args.gpu_deadline_ms <= 86_400_000:
        raise _UsageError("--gpu-deadline-ms must be between 1 and 86400000")
    if args.test_faults and not hooks_compiled:
        raise _UsageError("--test-faults needs a Debug build (the fault hooks are not compiled in)")
    args.bind = None
    if args.mcp_http is None:
        if args.token is not None or args.allow_remote:
            raise _UsageError("--token and --allow-remote need --mcp-http")
    else:
        try:
            args.bind = transport_http.parse_bind(args.mcp_http, args.allow_remote)
        except transport_http.BindError as error:
            raise _UsageError(str(error)) from None
        if args.token is not None and (not args.token or any(c.isspace() for c in args.token)):
            raise _UsageError("--token must be a non-empty token without spaces")
    args.root_set = None
    if args.roots is not None:
        try:
            args.root_set = Roots.parse(args.roots)
        except RootsError as error:
            raise _UsageError(str(error)) from None
        args.output_root = _output_root(args.root_set, args.output_root)
    return args


def _output_root(roots: Roots, given: Path | None) -> Path:
    """With `--roots`: the worker's output root, the export root by default; it must lie inside
    a root, so the files it holds are never outside the roots."""
    if given is None:
        export = roots.roots.get("export")
        if export is None:
            raise _UsageError("--roots needs an export root, or an --output-root inside a root")
        return Path(export)
    resolved = Path(os.path.realpath(given))
    if not roots.contains(str(resolved)):
        raise _UsageError("--output-root must lie inside one of the --roots")
    return resolved


def main(argv: list[str], exe: str, build: str, protocol: str, hooks_compiled: bool) -> int:
    """Called by `UzPainter.exe --mcp` with the arguments after `--mcp`; the exit status."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="uzpainter supervisor: %(levelname)s %(message)s",
    )
    try:
        args = parse_args(argv, hooks_compiled)
    except _UsageError as error:
        print(f"UzPainter.exe --mcp: {error}", file=sys.stderr)
        return EXIT_USAGE
    base = Path(tempfile.gettempdir()) / f"uzpainter-{os.getpid()}"
    config = worker_module.WorkerConfig(
        exe=exe,
        gpu_backend=args.gpu_backend,
        allow_python=args.allow_python,
        gpu_deadline_ms=args.gpu_deadline_ms,
        output_root=(args.output_root or base / "outputs").resolve(),
        crash_root=(args.crash_dir or base / "crashes").resolve(),
        test_faults=args.test_faults,
        preview=args.preview,
        protocol=protocol,
    )
    log.info("build %s, backend %s, python %s", build, config.gpu_backend, config.allow_python)
    try:
        ledger = Ledger((args.ledger or DEFAULT_PATH).resolve())
    except (OSError, sqlite3.Error) as error:
        log.critical("fatal supervisor error: cannot open the ledger: %s", error)
        return EXIT_FATAL
    handler = LogHandler(ledger, process_identity(os.getpid()) or f"{os.getpid()}:0")
    logging.getLogger().addHandler(handler)
    try:
        try:
            manifest = Manifest.load(Path(exe).parent / "capabilities.json")
        except ManifestError as error:
            log.critical("fatal supervisor error: %s", error)
            return EXIT_FATAL
        return _run(_serve(config, build, protocol, ledger, manifest, args))
    finally:
        logging.getLogger().removeHandler(handler)
        ledger.close()


def _run(main: Coroutine[Any, Any, int]) -> int:
    """Runs `main` on a new event loop and returns its status as soon as it ends. Unlike
    `asyncio.run`, it neither cancels nor awaits the tasks still pending: after a console stop the
    stdio transport's stdin reader cannot finish (`_until_console_stop`), and the process ends
    right after without finalizing the interpreter (supervisor.cpp, main.cpp)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(main)


def _thumbnail() -> Thumbnail | None:
    """The native image helper of UzPainter.exe (`_uzpainter_image`, image_block.h)."""
    try:
        import _uzpainter_image  # type: ignore[import-not-found]
    except ImportError:
        return None
    preview: Thumbnail = _uzpainter_image.preview_png
    return preview


async def _serve(
    config: worker_module.WorkerConfig,
    build: str,
    protocol: str,
    ledger: Ledger,
    manifest: Manifest,
    args: argparse.Namespace,
) -> int:
    supervisor = worker_module.Supervisor(config)
    # The MCP SDK is imported on a thread while the worker starts and creates its GPU device: the
    # two take about half a second each and neither needs the other (decision 253).
    sdk = asyncio.ensure_future(asyncio.to_thread(_import_sdk, args.bind is None))
    try:
        await supervisor.start()
    except worker_module.FatalSupervisorError as error:
        sdk.cancel()
        log.critical("fatal supervisor error: %s", error)
        return EXIT_FATAL
    admission = Admission(supervisor, ledger)
    supervisor.on_job_event = admission.on_job_event
    supervisor.on_project_switch = admission.on_project_switch
    registry = Registry(
        supervisor,
        admission,
        manifest,
        roots=args.root_set,
        http=args.bind is not None,
        thumbnail=_thumbnail(),
        build=build,
        protocol=protocol,
    )
    try:
        await sdk
        if args.bind is None:
            await _run_stdio(registry, build)
        else:
            host, port = args.bind
            token = args.token
            if token is None:
                token = secrets.token_urlsafe(32)
                # Printed once for the operator; never logged, so never in the ledger.
                print(f"uzpainter supervisor: bearer token {token}", file=sys.stderr, flush=True)
            server = _server(registry, build, _http_clients())
            await transport_http.serve(server, host, port, token)
    finally:
        registry.close()
        admission.close()
        await supervisor.close()
    return EXIT_OK


def _import_sdk(stdio: bool) -> None:
    """Imports the SDK modules `_server` and, with `stdio`, `_run_stdio` use."""
    for name in ("mcp_types", "mcp.server.lowlevel", *(("mcp.server.stdio",) if stdio else ())):
        importlib.import_module(name)


def _http_clients() -> Any:
    """The client of each Streamable HTTP session, by its `Mcp-Session-Id`; a request without a
    session (stateless) is its own client and holds no owner."""
    clients: dict[str, Client] = {}

    def client_for(ctx: Any) -> Client:
        request = getattr(ctx, "request", None)
        headers = getattr(request, "headers", None)
        session_id = headers.get("mcp-session-id") if headers is not None else None
        if not isinstance(session_id, str):
            return Client("http")
        client = clients.get(session_id)
        if client is None:
            if len(clients) >= MAX_HTTP_CLIENTS:
                clients.pop(next(iter(clients)))
            client = clients[session_id] = Client("http")
        return client

    return client_for


async def _run_stdio(registry: Registry, build: str) -> None:
    from mcp.server.stdio import stdio_server

    client = Client("stdio")
    server = _server(registry, build, lambda ctx: client)

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    await _until_console_stop(serve())


async def _until_console_stop(serving: Coroutine[Any, Any, None]) -> None:
    """Serves until the session ends or the console sends Ctrl+C or Ctrl+Break, the stop the HTTP
    transport takes through uvicorn. Either way the caller's shutdown follows: the worker ends (the
    OS removes its project's lock sidecar with it) and the ledger closes, which checkpoints its
    WAL. After a stop the stdio task stays blocked on stdin, whose reader thread cannot be
    cancelled; `_run` returns without waiting for it and the process ends (supervisor.cpp)."""
    if threading.current_thread() is not threading.main_thread():
        await serving
        return
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()

    def stop(signum: int, frame: Any) -> None:
        loop.call_soon_threadsafe(stopped.set)

    previous = {sig: signal.signal(sig, stop) for sig in CONSOLE_STOP_SIGNALS}
    task = asyncio.ensure_future(serving)
    waiter = asyncio.ensure_future(stopped.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if task.done():
        task.result()
    else:
        log.info("console stop: ending the worker and closing the ledger")


def _server(registry: Registry, build: str, client_for: Any) -> Any:
    """The SDK's low-level `Server` over `registry`; `client_for(ctx)` names a request's client."""
    import mcp_types as types
    from mcp.server.lowlevel import Server

    async def list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    input_schema=tool["inputSchema"],
                    annotations=types.ToolAnnotations(read_only_hint=tool["readOnly"]),
                    _meta=tool["meta"],
                )
                for tool in await registry.list_tools()
            ]
        )

    resources = Resources(registry)

    async def list_resources(ctx: Any, params: Any) -> Any:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    uri=item.uri, name=item.name, description=item.description, mime_type=JSON
                )
                for item in RESOURCES
            ]
        )

    async def list_resource_templates(ctx: Any, params: Any) -> Any:
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    uri_template=JOB_TEMPLATE.uri,
                    name=JOB_TEMPLATE.name,
                    description=JOB_TEMPLATE.description,
                    mime_type=JSON,
                )
            ]
        )

    async def read_resource(ctx: Any, params: Any) -> Any:
        from mcp.shared.exceptions import MCPError

        uri = str(params.uri)
        try:
            document = await resources.read(uri, client_for(ctx))
        except ResourceError as error:
            raise MCPError(RESOURCE_NOT_FOUND, str(error), error.data) from None
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri, mime_type=JSON, text=json.dumps(document, sort_keys=True)
                )
            ]
        )

    async def list_prompts(ctx: Any, params: Any) -> Any:
        return types.ListPromptsResult(
            prompts=[
                types.Prompt(name=prompt.name, description=prompt.description, arguments=[])
                for prompt in PROMPTS
            ]
        )

    async def get_prompt(ctx: Any, params: Any) -> Any:
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_PARAMS

        try:
            prompt = Resources.prompt(params.name)
        except ResourceError as error:
            raise MCPError(INVALID_PARAMS, str(error), error.data) from None
        return types.GetPromptResult(
            description=prompt.description,
            messages=[
                types.PromptMessage(role="user", content=types.TextContent(text=prompt.text))
            ],
        )

    async def call_tool(ctx: Any, params: Any) -> Any:
        reply = await registry.call(
            params.name, dict(params.arguments or {}), client_for(ctx), progress_sender(ctx)
        )
        content: list[Any] = [types.TextContent(text=reply.summary)]
        content += [
            types.ImageContent(data=image["data"], mime_type=image["mimeType"])
            for image in reply.images
        ]
        return types.CallToolResult(
            content=content, structured_content=reply.body, is_error="error" in reply.body
        )

    def progress_sender(ctx: Any) -> Any:
        """Sends a waited job's events as `notifications/progress` on the request's token."""
        meta = (ctx.params or {}).get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        if isinstance(token, bool) or not isinstance(token, str | int):
            return None

        async def notify(event: dict[str, Any]) -> None:
            await ctx.session.send_notification(
                types.ProgressNotification(
                    params=types.ProgressNotificationParams(
                        progress_token=token,
                        progress=event["progress"],
                        total=1.0,
                        message=f"{event['status']}: {event['message']}",
                        meta={JOB_META_KEY: event},
                    )
                ),
                related_request_id=ctx.request_id,
            )

        return notify

    return Server(
        "uzpainter",
        version=build,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_resource_templates=list_resource_templates,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )
