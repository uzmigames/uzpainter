"""`UzPainter.exe --mcp`: the command line and the stdio MCP server (src/supervisor/supervisor.h).

The MCP surface is the forwarding path of phase2.1 with the admission of phase2.2: the tools
are the worker's own (`tools/list` asks the worker) plus `supervisor_status` and `wait_idle`. A
mutating tool's schema takes its `idempotency_key` and `expected_revision` among the arguments
(`public_schema`); both may be omitted, and the supervisor then generates the key and resolves
the precondition. Every call goes through `admission.Admission`, which lifts them into the pipe
request. The tool registry with its schemas, HTTP mode, roots, resources and prompts come with
phase2.5-phase2.8.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import worker as worker_module
from .admission import Admission
from .ledger import DEFAULT_PATH, Ledger

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FATAL = 4

STATUS_TOOL = "supervisor_status"
WAIT_IDLE_TOOL = "wait_idle"
# The MCP arguments of a mutating tool carry its key and precondition (02 §2); the supervisor
# lifts them into the pipe request, so the worker's own schema does not list them. Both may be
# omitted together; a client that supplies its own key supplies its original precondition with
# it on every attempt (11-mcp-server.md §4).
MUTATION_PROPERTIES: dict[str, Any] = {
    "idempotency_key": {
        "type": "string",
        "minLength": 1,
        "description": "The mutation's idempotency key, kept for every retry of it; generated "
        "by the supervisor (and returned in the receipt) when omitted.",
    },
    "expected_revision": {
        "type": "integer",
        "description": "The revision the mutation is based on (its precondition), kept with "
        "the key on every retry; resolved by the supervisor when both are omitted.",
    },
}
WAIT_IDLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "timeout": {
            "type": "number",
            "minimum": 0,
            "description": "Seconds to wait before failing with `timeout`.",
        }
    },
    "required": ["timeout"],
    "additionalProperties": False,
}


def public_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """The MCP input schema of a worker tool; a mutating one takes its key and precondition too."""
    schema: dict[str, Any] = copy.deepcopy(tool["inputSchema"])
    if tool["mutating"]:
        schema.setdefault("properties", {}).update(copy.deepcopy(MUTATION_PROPERTIES))
    return schema


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
    args = parser.parse_args(argv)
    if args.gpu_deadline_ms is not None and not 1 <= args.gpu_deadline_ms <= 86_400_000:
        raise _UsageError("--gpu-deadline-ms must be between 1 and 86400000")
    if args.test_faults and not hooks_compiled:
        raise _UsageError("--test-faults needs a Debug build (the fault hooks are not compiled in)")
    return args


def main(argv: list[str], exe: str, build: str, protocol: str, hooks_compiled: bool) -> int:
    """Called by `UzPainter.exe --mcp` with the arguments after `--mcp`; the exit status."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="uzpainter supervisor: %(levelname)s %(message)s",
    )
    if any(arg in ("--mcp-http", "--roots") for arg in argv):
        print(
            "UzPainter.exe --mcp: --mcp-http and --roots are delivered by phase2.5 "
            "(task phase2.5_mcp-transport-registry)",
            file=sys.stderr,
        )
        return EXIT_USAGE
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
        protocol=protocol,
    )
    log.info("build %s, backend %s, python %s", build, config.gpu_backend, config.allow_python)
    try:
        ledger = Ledger((args.ledger or DEFAULT_PATH).resolve())
    except (OSError, sqlite3.Error) as error:
        log.critical("fatal supervisor error: cannot open the ledger: %s", error)
        return EXIT_FATAL
    try:
        return asyncio.run(_serve(config, build, ledger))
    finally:
        ledger.close()


async def _serve(config: worker_module.WorkerConfig, build: str, ledger: Ledger) -> int:
    supervisor = worker_module.Supervisor(config)
    try:
        await supervisor.start()
    except worker_module.FatalSupervisorError as error:
        log.critical("fatal supervisor error: %s", error)
        return EXIT_FATAL
    admission = Admission(supervisor, ledger)
    try:
        await _run_mcp(supervisor, admission, build)
    finally:
        admission.close()
        await supervisor.close()
    return EXIT_OK


async def _run_mcp(supervisor: worker_module.Supervisor, admission: Admission, build: str) -> None:
    import mcp_types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    mutating: dict[str, bool] = {}

    async def worker_tools() -> list[dict[str, Any]]:
        reply = await supervisor.request({"method": "tools/list"})
        if "error" in reply:  # the worker died while listing: ask the relaunched one
            reply = await supervisor.request({"method": "tools/list"})
        listed: list[dict[str, Any]] = reply.get("result", {}).get("tools", [])
        mutating.update({tool["name"]: bool(tool["mutating"]) for tool in listed})
        return listed

    async def list_tools(ctx: Any, params: Any) -> Any:
        tools = [
            types.Tool(
                name=STATUS_TOOL,
                description="The supervisor's worker: pid, backend, Python policy, project and "
                "every recovery with its cause, minidump and time; the ledger, the project's "
                "lease and the running calls.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(read_only_hint=True),
            ),
            types.Tool(
                name=WAIT_IDLE_TOOL,
                description="Waits until no mutating call runs; a timeout is an error.",
                input_schema=copy.deepcopy(WAIT_IDLE_SCHEMA),
                annotations=types.ToolAnnotations(read_only_hint=True),
            ),
        ]
        for tool in await worker_tools():
            tools.append(
                types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    input_schema=public_schema(tool),
                    annotations=types.ToolAnnotations(read_only_hint=not tool["mutating"]),
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: Any) -> Any:
        arguments = dict(params.arguments or {})
        if params.name == STATUS_TOOL:
            return _tool_result({"result": {**supervisor.status(), **admission.status()}})
        if params.name == WAIT_IDLE_TOOL:
            timeout = arguments.get("timeout")
            if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout < 0:
                return _tool_result(
                    {
                        "error": {
                            "code": "invalid_arguments",
                            "message": "wait_idle needs timeout (seconds, at least 0)",
                            "details": {},
                        }
                    }
                )
            return _tool_result(await admission.wait_idle(float(timeout)))
        if params.name not in mutating:
            await worker_tools()
        reply = await admission.call(params.name, arguments, mutating.get(params.name, False))
        return _tool_result(reply)

    def _tool_result(body: dict[str, Any]) -> Any:
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(body, sort_keys=True, ensure_ascii=False))],
            structured_content=body,
            is_error="error" in body,
        )

    server = Server("uzpainter", version=build, on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
