"""`UzPainter.exe --mcp`: the command line and the stdio MCP server (src/supervisor/supervisor.h).

The MCP surface of this task is the forwarding path only (phase2.1): the tools are the worker's
own (`tools/list` asks the worker) plus `supervisor_status`. A mutating tool's schema requires
its `idempotency_key` and `expected_revision` among the arguments (`public_schema`); the
supervisor lifts them into the pipe request. The tool registry with its schemas, the omission
rule for the key and the precondition, HTTP mode, roots, resources and prompts come with
phase2.5-phase2.8.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import worker as worker_module

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FATAL = 4

STATUS_TOOL = "supervisor_status"
LIFTED = ("idempotency_key", "expected_revision")
# The MCP arguments of a mutating tool carry its key and precondition (02 §2); the supervisor
# lifts them into the pipe request, so the worker's own schema does not list them.
MUTATION_PROPERTIES: dict[str, Any] = {
    "idempotency_key": {
        "type": "string",
        "minLength": 1,
        "description": "The mutation's idempotency key, kept for every retry of it.",
    },
    "expected_revision": {
        "type": "integer",
        "description": "The revision the mutation is based on (its precondition).",
    },
}


def public_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """The MCP input schema of a worker tool: a mutating tool also requires `LIFTED`."""
    schema: dict[str, Any] = copy.deepcopy(tool["inputSchema"])
    if tool["mutating"]:
        schema.setdefault("properties", {}).update(copy.deepcopy(MUTATION_PROPERTIES))
        schema["required"] = [*schema.get("required", []), *LIFTED]
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
    parser.add_argument("--test-faults", action="store_true")
    parser.add_argument("--preview", action="store_true")
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
        preview=args.preview,
        protocol=protocol,
    )
    log.info("build %s, backend %s, python %s", build, config.gpu_backend, config.allow_python)
    return asyncio.run(_serve(config, build))


async def _serve(config: worker_module.WorkerConfig, build: str) -> int:
    supervisor = worker_module.Supervisor(config)
    try:
        await supervisor.start()
    except worker_module.FatalSupervisorError as error:
        log.critical("fatal supervisor error: %s", error)
        return EXIT_FATAL
    try:
        await _run_mcp(supervisor, build)
    finally:
        await supervisor.close()
    return EXIT_OK


async def _run_mcp(supervisor: worker_module.Supervisor, build: str) -> None:
    import mcp_types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    async def list_tools(ctx: Any, params: Any) -> Any:
        reply = await supervisor.request({"method": "tools/list"})
        if "error" in reply:  # the worker died while listing: ask the relaunched one
            reply = await supervisor.request({"method": "tools/list"})
        tools = [
            types.Tool(
                name=STATUS_TOOL,
                description="The supervisor's worker: pid, backend, Python policy, project and "
                "every recovery with its cause, minidump and time.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(read_only_hint=True),
            )
        ]
        for tool in reply.get("result", {}).get("tools", []):
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
            return _tool_result({"result": supervisor.status()})
        frame: dict[str, Any] = {"method": "tools/call", "name": params.name}
        for key in LIFTED:
            if key in arguments:
                frame[key] = arguments.pop(key)
        frame["arguments"] = arguments
        reply = await supervisor.request(frame)
        reply.pop("id", None)
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
