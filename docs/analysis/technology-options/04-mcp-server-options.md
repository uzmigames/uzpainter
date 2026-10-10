# Native MCP Server Options

Research compiled 2026-10-09.

## MCP Specification and Transports

**Current Version**: **Fact** Specification 2026-07-28 (latest as of 2026-10-09). [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic). Prior versions: 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05.

**Transports Available** (2026-07-28):
1. **stdio** (default, recommended): Client launches MCP server as subprocess; server reads/writes JSON-RPC 2.0 on stdin/stdout, messages delimited by newlines. No embedded newlines in messages. Errors/logs sent to stderr (client may ignore). **Fact**: Clients **SHOULD** support stdio whenever possible. [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)

2. **Streamable HTTP** (remote servers): Server hosts single HTTP endpoint (e.g., `/mcp`); client POSTs JSON-RPC requests, server responds via HTTP (single response) or Server-Sent Events (SSE) stream for request-scoped streaming. **Note**: SSE is integrated into Streamable HTTP transport (not a separate transport as in 2024-11-05). [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)

3. **Custom Transports**: Pluggable; must preserve JSON-RPC message format and lifecycle. Not standardized; used for WebSocket, gRPC, or proprietary protocols.

**New Core Utilities** (2026-07-28 spec update):
- **Elicitation**: Server-initiated requests for additional user information (e.g., confirmation, approval gates) passed via tool results or mid-flight. [Source](https://modelcontextprotocol.io/specification/2026-07-28/)
- **Progress Tracking**: Formal progress reporting mechanism for long-running operations.
- **Cancellation**: Standardized cancellation semantics via `notifications/cancelled`.
- **Tasks Extension** (opt-in): Asynchronous job execution with durability; returns `CreateTaskResult` instead of blocking. Supports polling (`tasks/get`), input pauses (`input_required`), mid-flight input (`tasks/update`), and cancellation (`tasks/cancel`). See [Tasks Extension](https://modelcontextprotocol.io/extensions/tasks/overview). [Source](https://github.com/modelcontextprotocol/ext-tasks)

## Official SDKs

| SDK | Language | Maturity | Platforms | Key Features | License | Source |
|-----|----------|----------|-----------|--------------|---------|--------|
| **Official Python SDK** | Python 3.8+ | Production (Anthropic) | Windows, macOS, Linux | Decorators (`@server.tool()`, `@server.resource()`); async/await; stdio + Streamable HTTP transports; FastMCP high-level API (v2024+). | **Fact**: MIT/Apache 2.0 (Anthropic). [Source](https://github.com/modelcontextprotocol/python-sdk) | [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk) |
| **Official TypeScript SDK** | TypeScript/JavaScript | Production (Anthropic) | Node.js, Bun, Deno | Server + client libraries; decorators/classes; optional middleware (Express, Fastify, Hono); stdio + Streamable HTTP. | **Fact**: MIT/Apache 2.0 (Anthropic). [Source](https://github.com/modelcontextprotocol/typescript-sdk) | [MCP TypeScript SDK GitHub](https://github.com/modelcontextprotocol/typescript-sdk) |
| **Community C++ SDK (Gopher Security)** | C++ (modern, 17+) | Mature (2024); enterprise-grade | Windows, macOS, Linux | Stdio, HTTP+SSE, Streamable HTTP, WebSocket, TCP transports; FFI bindings for Python, TypeScript, Go, Rust, Java, C#; no dependency on Python. | **Fact**: Commercial (Gopher Security) with open-source options available. [Source](https://github.com/GopherSecurity/gopher-mcp) | [Gopher MCP C++ SDK GitHub](https://github.com/GopherSecurity/gopher-mcp) |
| **FastMCP (Python framework)** | Python | Growth (2024); officially integrated into SDK | Windows, macOS, Linux | High-level decorators; auto-schema from Python type hints (Pydantic, Zod compatibility); built into official Python SDK. | **Fact**: Apache 2.0. [Source](https://gofastmcp.com/) | [FastMCP Official](https://gofastmcp.com/) |

**No Official C++ Implementation from Anthropic** (as of 2026-10-09). Community implementations exist (Gopher, experimental), but require external maintenance.

## Tool/Resource/Prompt Declaration (JSON Schema)

**Fact**: All tools in MCP use **JSON Schema** for input validation. Output schemas are first-class (2026-07-28 spec).

### Tool Definition (required fields):
```json
{
  "name": "bake_normal_map",
  "description": "Bake a normal map from the geometry mesh",
  "inputSchema": {
    "type": "object",
    "properties": {
      "resolution": { "type": "integer", "description": "Output resolution (512-4096)" },
      "strength": { "type": "number", "description": "Normal map strength (0-1)" }
    },
    "required": ["resolution"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "image_url": { "type": "string", "description": "Data URI or file path" },
      "timings_ms": { "type": "integer" }
    }
  }
}
```

**Fact** (2025-06-18 spec update): Output schemas are now first-class; FastMCP auto-generates from Python type hints (e.g., Pydantic models, TypeScript types).

### Resource Definition:
```json
{
  "uri": "uzpainter://project/layers",
  "name": "layers",
  "mimeType": "application/json",
  "description": "Current layer tree and metadata"
}
```
Resources are passive (read-only, client-requested, server-controlled). Typically return project state, documentation, schemas.

### Prompt Definition:
```json
{
  "name": "refine_textures",
  "description": "Instruction template for refining texture quality",
  "arguments": [
    { "name": "layer_id", "description": "UUID of target layer", "required": true }
  ]
}
```
Prompts are pre-built instruction templates; client invokes by name + arguments.

## Long-Running Jobs (Bakes, Exports)

**MCP 2026-07-28 Spec**: Formal **Tasks Extension** (opt-in) for long-running operations. Core protocol supports:
- **Elicitation**: Server requests additional user input mid-operation (e.g., confirmation).
- **Progress Tracking**: Status reporting mechanism.
- **Cancellation**: `notifications/cancelled` signal (cooperative, not guaranteed).

**Tasks Extension** (recommended pattern for UzPainter):
- **Capability Negotiation**: Client declares `io.modelcontextprotocol/tasks` in per-request capabilities; server advertises same in `server/discover`.
- **Job Creation**: Tool returns `CreateTaskResult` with `taskId`, initial status (`working`), TTL, and suggested polling interval.
- **Polling Loop**: Client calls `tasks/get(taskId)` until status reaches terminal (`completed`, `failed`, `cancelled`).
- **Mid-Flight Input**: If status is `input_required`, server provides `inputRequests` (e.g., user confirmation); client responds via `tasks/update(taskId, inputResponses)`.
- **Completion**: Terminal status includes `result` (if `completed`) or `error` (if `failed`).
- **Cancellation**: Client sends `tasks/cancel(taskId)` anytime; server acknowledges but cancellation is cooperative. [Source](https://modelcontextprotocol.io/extensions/tasks/overview)

**Legacy Pattern** (core MCP, no extension):
- Tool `bake_normal_map` returns `{ job_id: "abc123", status: "started" }` immediately.
- Client polls via separate tool `get_bake_status(job_id)` on 1-5s interval.
- Completion indicated by `{ job_id, status: "done", result: { image_url, ... } }`.
- (Not recommended; Tasks Extension replaces this pattern in modern MCP 2026-07-28.)

**Progress Visibility** (Tasks Extension):
- Server sends `status: "working"` with optional `statusMessage: "45% complete"` on each poll.
- Avoids `input_required` pause unless user approval needed.
- **Notifications** (optional): Server can push status updates via `notifications/tasks` (client opts in via `subscriptions/listen`), eliminating polling overhead. [Source](https://modelcontextprotocol.io/extensions/tasks/overview)

**Note not confirmed**: Tasks Extension support varies by MCP client. Older clients may not recognize `CreateTaskResult`; fallback to legacy `job_id` pattern for compatibility.

## Embedding MCP in UzPainter (C++ App)

**Two Architectures**:

### Option A: In-Process Python MCP Server
- **How**: Embed CPython (via pybind11) → load Python MCP SDK → register tools/resources in Python → expose via embedded Python.
- **Pros**: No subprocess overhead; shared memory for project state; tight control.
- **Cons**: Python GIL blocks C++ threads (unless Python 3.13 free-threaded); Python error crashes app.
- **Tools Definition**: Python decorators (`@server.tool()`) → auto-converted to MCP JSON Schema.

### Option B: Subprocess MCP Server (Recommended)
- **How**: Embed CPython + MCP Python SDK → launch MCP server as subprocess at app startup (stdio transport) → C++ core communicates via JSON-RPC on pipes.
- **Pros**: Process isolation (Python crash ≠ app crash); standard MCP protocol; any LLM client can connect (local debugging, remote agents); GIL not a concern (Python runs single-threaded in subprocess).
- **Cons**: IPC latency (~1-10ms per request); subprocess management overhead.
- **Typical Implementation**:
  ```cpp
  // Pseudocode
  subprocess* server = launch_python_mcp_server("python -m uzpainter.mcp");
  // Read/write JSON-RPC on server.stdin / server.stdout
  send_json_rpc(server, { method: "tools/call", params: { name: "bake", args: {...} } });
  receive_json_rpc(server); // blocks until response or timeout
  ```

**For UzPainter Bake Jobs** (Tasks Extension):
- Tool `bake_normal_map(resolution, strength, geometry_id)` called with `io.modelcontextprotocol/tasks` capability.
- Python server returns `CreateTaskResult { taskId: "bake-xyz", status: "working", pollIntervalMs: 500 }` immediately (no blocking).
- C++ app polls `tasks/get("bake-xyz")` on 500ms interval in background thread.
- Server streams status updates: `{ taskId, status: "working", statusMessage: "45% complete (normal map)" }`.
- On completion: `{ taskId, status: "completed", result: { image_url: "...", timings_ms: 1250 } }`.
- C++ UI updates progress bar in real-time; bake result consumed when terminal status reached.

## MCP + AI Use Cases

**Standard Flow**:
1. AI client (e.g., Claude) connects to MCP server (stdio or HTTP).
2. AI queries available tools: `{ method: "tools/list" }` → server responds with all tool schemas.
3. AI decides to call a tool: `{ method: "tools/call", params: { name: "adjust_layer_opacity", arguments: { layer_id, opacity: 0.8 } } }`.
4. Server executes, returns result.
5. AI uses result to inform next step (e.g., "The layer is now 80% transparent; now I'll export.").

**Example for UzPainter**:
- AI observes project via `resources` (list layers, fetch layer metadata).
- AI calls tools to manipulate state (adjust opacity, add layer, export).
- AI can also request prompts (e.g., "refine_textures") to guide its own generation.

## Trade-Off Summary

**Choice: Python SDK + Subprocess (stdio) MCP Server**

**Why**:
- **Spec Compliance**: Official SDK, Anthropic-maintained, production-grade.
- **Simplicity**: Python decorators handle JSON Schema generation; no manual schema writing.
- **Process Isolation**: Safer than in-process embedding; Python errors don't crash renderer.
- **Debuggability**: Standard MCP protocol; can connect any MCP client for testing (e.g., Claude desktop client with custom server config).
- **Licensing**: MIT/Apache 2.0 (permissive).

**Implementation Sketch**:
1. Embed CPython + Python MCP SDK in UzPainter bundle.
2. Write Python module `uzpainter/mcp_server.py`:
   ```python
   from mcp.server import Server
   from mcp.types import Tool, TextContent
   
   server = Server("uzpainter")
   
   @server.tool()
   async def bake_normal_map(resolution: int, strength: float) -> str:
       # Call C++ baker via pybind11
       result = cpp_baker.bake_normal(resolution, strength)
       return json.dumps(result)
   
   @server.resource()
   async def layers() -> str:
       # Fetch project layers
       return json.dumps(project.layers())
   ```
3. At app startup, spawn subprocess: `subprocess.Popen(["python", "-m", "uzpainter.mcp_server"], stdin=PIPE, stdout=PIPE)`.
4. C++ core reads/writes JSON-RPC; no manual protocol parsing.

**Alternative (if Python unavailable or team expertise limited)**:
- Use Gopher C++ SDK; write MCP server in C++; same stdio/HTTP transports.
- Upside: single-language stack.
- Downside: larger binary, less ecosystem integration with LLM tools.

**Not Recommended**:
- In-process Python embedding: GIL complexity, crash risk.
- HTTP Streamable HTTP for local-only tool: added complexity (HTTP stack, session management); stdio is simpler.

## Sources
- [MCP Specification 2026-07-28 (Latest)](https://modelcontextprotocol.io/specification/2026-07-28/)
- [MCP Specification 2026-07-28: Transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
- [MCP Specification 2026-07-28: Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP Tasks Extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP ext-tasks Repository](https://github.com/modelcontextprotocol/ext-tasks)
- [Python MCP SDK GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [TypeScript MCP SDK GitHub](https://github.com/modelcontextprotocol/typescript-sdk)
- [Gopher MCP C++ SDK GitHub](https://github.com/GopherSecurity/gopher-mcp)
- [FastMCP Official](https://gofastmcp.com/)
- [MCP Architecture Explained](https://getknit.dev/blog/mcp-architecture-deep-dive-tools-resources-and-prompts-explained)
