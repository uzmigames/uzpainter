"""UzPainter's supervisor (docs/architecture/02-runtime-topology.md §1, §2, §5; task
phase2.1_supervisor-ipc-worker; src/supervisor/SUPERVISOR.md).

`UzPainter.exe --mcp` starts the embedded interpreter and calls `main.main`: the supervisor serves
the stdio MCP session through the pinned MCP SDK, launches the worker (`UzPainter.exe --worker`),
checks its handshake and forwards `tools/call` over the private pipe, relaunching the worker
after every fault. It never creates a GPU device, opens a project or runs user Python.

- `ipc`: the pipe protocol's frames, the handshake check and the worker's exit codes (standard
  library only, so the repository's tests import it directly).
- `worker`: the worker process and its pipe, fault detection and relaunch.
- `main`: the command line and the MCP server.
"""
