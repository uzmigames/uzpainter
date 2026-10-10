# Native MCP Server Options

Research compiled 2026-10-09. Corrected 2026-10-10 after the Astra technical review (`docs/analysis/reviews/technology-options-astra-review.md`); per-finding verdicts are in `05-review-response.md`. Web sources were retrieved 2026-10-10.

## MCP Specification and Transports

**Current Version**: **Fact** Specification 2026-07-28 (the specification landing page references `schema/2026-07-28/schema.ts`; retrieved 2026-10-10). [Source](https://modelcontextprotocol.io/specification). Prior versions: 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05. Older revisions (with `initialize` and sessions) belong only in an explicit compatibility path.

**Transports Available** (2026-07-28):
1. **stdio**: The client launches the MCP server as a subprocess; the server reads JSON-RPC from stdin and writes JSON-RPC to stdout, one message per line; messages "MUST NOT contain embedded newlines" (escaped `\n` inside JSON strings is fine); stdout carries only MCP messages; the server MAY log UTF-8 to stderr. All messages share one channel (no per-request streams). Cancellation is `notifications/cancelled`; the client shuts down by closing the server's stdin. The draft's "Clients **SHOULD** support stdio whenever possible" is not in the 2026-07-28 transport pages and is withdrawn. [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)

2. **Streamable HTTP**: The server "operates as an independent process that can handle multiple client connections"; every client message is an HTTP POST to one MCP endpoint (e.g., `/mcp`); the reply is a JSON object or a request-scoped SSE stream. Revision 2026-07-28 removed protocol-level sessions (`Mcp-Session-Id`), the GET stream and SSE resumability; closing the response stream cancels the request. Servers MUST validate `Origin`, SHOULD bind to 127.0.0.1 when running locally, and SHOULD authenticate. It is not restricted to remote servers. [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

3. **Custom Transports**: MAY be implemented; they MUST preserve the JSON-RPC format, the message patterns and the per-request metadata model; custom transports over a byte stream (Unix socket, TCP, named pipe) SHOULD reuse the stdio framing. Not standardized; an ordinary MCP host will not speak them without a bridge. [Source](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)

**Core Utilities and 2026-07-28 changes** (**Fact**, [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)):
- **Stateless requests**: the `initialize` handshake is removed; every request carries its protocol version and client capabilities in `_meta`; servers MUST implement `server/discover`; all results carry `resultType`.
- **Servers MUST NOT initiate JSON-RPC requests**: server-to-client input (elicitation, sampling, roots) is returned as an `InputRequiredResult` (`resultType: "input_required"`), and the client retries the original request with `inputResponses` (Multi Round-Trip Requests). [Patterns](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns)
- **Elicitation**: added in 2025-06-18 ([changelog](https://modelcontextprotocol.io/specification/2025-06-18/changelog)); in 2026-07-28 it is delivered inside `InputRequiredResult`, not as a server request. [Source](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
- **Progress Tracking**: `notifications/progress` already existed in 2024-11-05; in 2026-07-28 it flows on the response stream of the related request. [2024-11-05 progress](https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/progress)
- **Cancellation**: `notifications/cancelled` already existed in 2024-11-05; in 2026-07-28 it is used on stdio, while Streamable HTTP cancels by closing the response stream. [2024-11-05 cancellation](https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/cancellation)
- **Change notifications**: `subscriptions/listen` replaces the HTTP GET stream and `resources/subscribe`.
- **Tasks Extension** (opt-in, `io.modelcontextprotocol/tasks`): moved out of core into an official extension in 2026-07-28. Asynchronous job execution with durability; returns `CreateTaskResult` instead of blocking. Supports polling (`tasks/get`), input pauses (`input_required`), mid-flight input (`tasks/update`), and cancellation (`tasks/cancel`). See [Tasks Extension](https://modelcontextprotocol.io/extensions/tasks/overview). [Source](https://github.com/modelcontextprotocol/ext-tasks)

## Official SDKs

| SDK | Language | Maturity | Platforms | Key Features | License | Source |
|-----|----------|----------|-----------|--------------|---------|--------|
| **Official Python SDK** | Python 3.10+ | Tier 1 in the official SDK directory; v2 is the current stable line (v1.x in maintenance) | Windows, macOS, Linux | High-level `MCPServer` (v2 rename of the v1 `FastMCP` class) with `@mcp.tool()`, `@mcp.resource("uri")`, `@mcp.prompt()`; low-level `Server` with `on_*` handler parameters; schemas derived from type hints; stdio + Streamable HTTP; speaks 2026-07-28 and 2025-11-25. **Fact:** the migration guide states "This SDK does not implement the [Tasks] extension yet." | **Fact**: MIT; package authors "Model Context Protocol a Series of LF Projects, LLC." [Source](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/pyproject.toml) | [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk); [v1→v2 migration](https://py.sdk.modelcontextprotocol.io/migration/) |
| **Official TypeScript SDK** | TypeScript/JavaScript | Tier 1; v2 packages `@modelcontextprotocol/server` and `@modelcontextprotocol/client` | Node.js, Bun, Deno | Server + client libraries; stdio + Streamable HTTP. | **Fact**: Apache-2.0 for new contributions, existing code MIT (mixed; not interchangeable). [Source](https://github.com/modelcontextprotocol/typescript-sdk) | [MCP TypeScript SDK GitHub](https://github.com/modelcontextprotocol/typescript-sdk) |
| **Community C++ SDK (Gopher Security)** | C++ | Community (not in the official SDK directory). The vendor calls it "Production-ready"; maturity, Windows build, tests and conformance were not independently evaluated. | Windows, macOS, Linux (vendor claim) | README lists stdio, HTTP+SSE, HTTPS+SSE, WebSocket and TCP transports; C API (`libgopher_mcp_c`) with bindings for Python, TypeScript/Node, Go, Rust, Java, C#, Ruby; states support for 2025-06-18, 2025-11-25 and 2026-07-28 (Tasks support not confirmed). | **Fact**: Apache-2.0. [Source](https://github.com/GopherSecurity/gopher-mcp) | [Gopher MCP C++ SDK GitHub](https://github.com/GopherSecurity/gopher-mcp) |
| **FastMCP (standalone Python framework)** | Python | Separately versioned project; "FastMCP created the high-level Python API incorporated into the official MCP Python SDK in 2024" | Windows, macOS, Linux | High-level decorators; schemas from Python type hints. Its docs track `main` and "may describe features that have not reached a stable release." Choose either this framework or the official SDK's release API, not a mix. | **Fact**: Apache-2.0. [Source](https://raw.githubusercontent.com/jlowin/fastmcp/main/LICENSE) | [FastMCP docs](https://gofastmcp.com/getting-started/welcome) |

**No Official C++ SDK** (official SDK directory, retrieved 2026-10-10): Tier 1 TypeScript, Python, C#, Go, Rust, Ruby; Tier 2 Java; Tier 3 Swift, PHP, Kotlin. Official SDKs live under the `modelcontextprotocol` organization (LF Projects), not only "from Anthropic". Community C++ implementations exist but require external maintenance. [SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk)

## Tool/Resource/Prompt Declaration (JSON Schema)

**Fact**: A tool's `inputSchema` MUST be a valid JSON Schema object (2020-12 by default). `outputSchema` is optional; when present, servers MUST return conforming `structuredContent` and SHOULD also return the serialized JSON as text. Servers MUST validate all tool inputs. Output schemas and structured tool output were added in 2025-06-18, not 2026-07-28. [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

### Tool Definition (example):
```json
{
  "name": "bake_normal_map",
  "description": "Bake a normal map from the geometry mesh",
  "inputSchema": {
    "type": "object",
    "properties": {
      "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096], "description": "Output resolution" },
      "strength": { "type": "number", "minimum": 0, "maximum": 1, "description": "Normal map strength" },
      "project_revision": { "type": "string", "description": "Revision the bake applies to; stale revisions are rejected" }
    },
    "required": ["resolution", "project_revision"],
    "additionalProperties": false
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "artifact_uri": { "type": "string", "description": "Resource URI the client can read" },
      "sha256": { "type": "string" },
      "timings_ms": { "type": "integer" }
    },
    "required": ["artifact_uri", "sha256"]
  }
}
```

Bounds belong in the schema **and** in native validation (cross-field constraints, object references, project revisions). A local file path is not an image a remote client can observe: return `image` content (base64 + `mimeType`) or a `resource_link` the client can read, with hash and channel/color metadata. The Python SDK derives schemas from type hints; bounds still need explicit validation.

### Resource Definition:
```json
{
  "uri": "uzpainter://project/layers",
  "name": "layers",
  "mimeType": "application/json",
  "description": "Current layer tree and metadata"
}
```
Resources are read by the client. They are not static: clients can subscribe through `subscriptions/listen` (`resourceSubscriptions`) to receive `notifications/resources/updated`. Typically return project state, documentation, schemas.

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

**MCP 2026-07-28 Spec**: **Tasks Extension** (opt-in) for long-running operations. Core protocol supports:
- **Elicitation**: via `InputRequiredResult` and a client retry (not a server-initiated request).
- **Progress Tracking**: `notifications/progress` on the request's response stream.
- **Cancellation**: `notifications/cancelled` on stdio; closing the response stream on Streamable HTTP (cooperative). Transport-request cancellation is distinct from cancelling a durable job.

**Tasks Extension** (when both sides support it):
- **Capability Negotiation**: Client declares `io.modelcontextprotocol/tasks` in per-request capabilities (`_meta`); server advertises the same in `server/discover`. A server must never return a task to a client that did not declare support.
- **Job Creation**: Tool returns `CreateTaskResult` — a flat result with `resultType: "task"` and required `taskId`, `status`, `createdAt`, `lastUpdatedAt`, `ttlMs` (number or null); `statusMessage` and `pollIntervalMs` are optional. **Fact:** the task "must be durably created before sending the response". [Schema](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/schema/2026-07-28/schema.ts)
- **Polling Loop**: Client calls `tasks/get(taskId)` (reply `resultType: "complete"`) until status reaches terminal (`completed`, `failed`, `cancelled`), honoring `pollIntervalMs`.
- **Mid-Flight Input**: If status is `input_required`, server provides `inputRequests` (e.g., user confirmation); client responds via `tasks/update(taskId, inputResponses)`.
- **Completion**: Terminal status includes `result` (if `completed`) or `error` (if `failed`).
- **Cancellation**: Client sends `tasks/cancel(taskId)` anytime; server acknowledges but cancellation is cooperative. [Source](https://modelcontextprotocol.io/extensions/tasks/overview)
- A protocol task handle does not implement persistence or a bake scheduler; that remains a native job layer (see topology table).

**Job-Handle Pattern** (core MCP, no extension):
- Tool `bake_normal_map` returns `{ job_id: "abc123", status: "started" }` immediately.
- Client polls via separate tool `get_bake_status(job_id)`.
- Completion indicated by `{ job_id, status: "done", result: { artifact_uri, ... } }`.
- **Correction:** this is a valid fallback, not a deprecated mistake — the 2026-07-28 tools spec recommends explicit server-minted handles for cross-call state ("Stateful Tools"). Use it for hosts or SDKs without Tasks support; add idempotency keys/revision preconditions so an AI retry does not duplicate a bake.

**Progress Visibility** (Tasks Extension):
- Server sends `status: "working"` with optional `statusMessage: "45% complete"` on each poll.
- Avoids `input_required` pause unless user approval needed.
- **Notifications** (optional): Server can push status updates via `notifications/tasks` (client opts in via `subscriptions/listen`), eliminating polling overhead. [Source](https://modelcontextprotocol.io/extensions/tasks/overview)

**Support not confirmed**: Tasks support "varies by client". The community-maintained extension support matrix (retrieved 2026-10-10) has no Tasks column, so Claude/Claude Code Tasks support is **unconfirmed**; the official Python SDK v2 does not implement Tasks. Keep the job-handle pattern as the fallback. [Client matrix](https://modelcontextprotocol.io/extensions/client-matrix)

## Embedding MCP in UzPainter (C++ App)

**Fact (process topology):** with stdio, the AI host launches the server process and owns its single stdin/stdout pair; one pipe pair is not a shared multi-client endpoint. A Python process that UzPainter launches itself cannot also be reached by an external AI host over that pipe, and a `.pyd` loaded in a separate worker cannot access ordinary C++ objects in the renderer process. "Embed CPython" and "launch bundled Python" are different designs. The choice of state owner is **forwarded to architecture**.

**Integration topology options** (added 2026-10-10):

| Option | What It Is | Pros | Cons | License | Source |
|---|---|---|---|---|---|
| **Native C++ MCP endpoint in `UzPainter.exe`** | The AI host launches `UzPainter.exe --mcp`; a C++ endpoint reads the inherited stdin and writes stdout, dispatching to the native command/job system; optional embedded CPython stays an API/plugin subsystem. | Direct state access; one process whose lifecycle the AI host owns; no extra interpreter process. | No official C++ SDK — conformance and maintenance of the protocol code are UzPainter's (or a community SDK's); stdout reserved for MCP (renderer logs to stderr); long bakes must stay off the protocol reader. | Own code (+ JSON library license). | [stdio binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio); [SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk) |
| **Embedded CPython + official Python SDK in `UzPainter.exe`** | Same single process, but the MCP endpoint is the Python SDK running in the embedded interpreter and calling the `uzpainter` native module. | Tier 1 SDK handles protocol details; schemas from type hints. | Python SDK v2 lacks Tasks; SDK dependencies must be vendored into the private runtime; protocol event loop must not be blocked by synchronous bakes; GIL only matters for Python code paths (see 01). | MIT (SDK) + PSF (CPython). | [Python SDK](https://github.com/modelcontextprotocol/python-sdk); [Windows embedding](https://docs.python.org/3.13/using/windows.html#the-embeddable-package) |
| **AI-launched bridge + resident UzPainter** | A small bridge process (built with an official SDK, e.g., C#, Go, Rust, Python or TypeScript) is launched by the AI host over stdio and talks to an already-running UzPainter over a separately defined named-pipe/socket command API. | Uses an official SDK; UzPainter can run independently of the AI session. | Two protocols (MCP + internal command API) and an extra runtime or FFI boundary; internal API needs its own versioning and auth. | Per SDK (Python MIT; TypeScript Apache-2.0/MIT; others not verified here). | [SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk); [custom transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) |
| **Loopback Streamable HTTP in resident UzPainter** | UzPainter hosts an MCP endpoint on 127.0.0.1 for a persistent application or multiple clients. | Multiple clients; app lifecycle independent of any one AI host; no sessions to manage in 2026-07-28. | MUST validate `Origin`; SHOULD bind to localhost and authenticate; HTTP stack in the app. | Depends on implementation. | [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) |
| **Native job/state layer + handle-based tools** | Native job IDs, project-revision inputs, progress, cancellation, result publication and persistence, mapped to the Tasks extension when negotiated and to job-handle tools otherwise. | One execution model for Python and MCP; crash/reconnect recovery; idempotent retries. | Persistence and coordination work; commits must be serialized or revision-checked so cancellation never publishes half-written state. | Own code. | [Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview); [Stateful Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) |

### Option A: In-Process MCP Server
- **How**: the AI host launches `UzPainter.exe`; the MCP endpoint (native C++ or the Python SDK in embedded CPython, see table) runs in the renderer process.
- **Pros**: No subprocess overhead; direct access to project state; tight control.
- **Cons**: Native faults take down the whole process. **Correction:** the GIL does not block C++ threads that do not hold it, and a Python exception is not by itself an app crash (see 01). Long native work must stay off the protocol reader/event loop; shared state mutations must be serialized or versioned.
- **Tools Definition**: Python decorators (`@mcp.tool()` on `MCPServer`) generate JSON Schema from type hints; a C++ endpoint writes schemas explicitly.

### Option B: Subprocess MCP Server (draft recommendation — not viable as drafted)
- **How (draft)**: Embed CPython + MCP Python SDK → launch MCP server as subprocess at app startup (stdio transport) → C++ core communicates via JSON-RPC on pipes.
- **Correction**: here UzPainter is the server's only client; the external AI cannot attach to that pipe, and the Python worker cannot reach the renderer's C++ objects. It is viable only as an internal worker behind one of the topologies above.
- **Pros (corrected)**: Worker faults are isolated from the renderer; standard protocol on the internal pipe.
- **Cons (corrected)**: IPC copy/serialization cost (the draft's "~1–10 ms per request" is **unconfirmed**); the worker can still suffer GIL contention, native races and an event loop blocked by synchronous calls; UzPainter would need a real MCP client implementation.
- **Typical Implementation** (corrected pseudocode):
  ```cpp
  // Pseudocode: UzPainter acting as an MCP *client* of a server it launched
  subprocess* server = launch_python_mcp_server("python -m uzpainter.mcp");
  // One JSON-RPC message per line on server.stdin / server.stdout
  send_json_rpc(server, { jsonrpc: "2.0", id: 1, method: "tools/call",
                          params: { name: "bake", arguments: {...},
                                    _meta: { "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                             "io.modelcontextprotocol/clientCapabilities": {...} } } });
  receive_json_rpc(server); // response may be a final result, an InputRequiredResult, or a CreateTaskResult
  ```

**For UzPainter Bake Jobs** (Tasks Extension, when negotiated):
- Tool `bake_normal_map(resolution, strength, project_revision)` called with `io.modelcontextprotocol/tasks` in the request's client capabilities.
- Server durably creates the job, then returns `CreateTaskResult { resultType: "task", taskId: "bake-xyz", status: "working", createdAt: <ISO 8601>, lastUpdatedAt: <ISO 8601>, ttlMs: <number or null>, pollIntervalMs: 500 }`.
- The AI client (not the C++ app) polls `tasks/get("bake-xyz")`, honoring `pollIntervalMs`.
- Server reports status: `{ taskId, status: "working", statusMessage: "45% complete (normal map)", ... }`.
- On completion: `{ resultType: "complete", taskId, status: "completed", result: { structuredContent: { artifact_uri: "...", sha256: "...", timings_ms: ... }, ... } }`.
- No progress-bar UI is required for an AI-only product (as the review states the acceptance premise); expose status to the client instead.

## MCP + AI Use Cases

**Standard Flow**:
1. AI client (e.g., Claude) reaches the MCP server (stdio or HTTP); with 2026-07-28 there is no `initialize`, and the client may call `server/discover` first (recommended as a probe on stdio).
2. AI queries available tools: `{ method: "tools/list" }` → server responds with all tool schemas.
3. AI decides to call a tool: `{ method: "tools/call", params: { name: "adjust_layer_opacity", arguments: { layer_id, opacity: 0.8 } } }` (every request also carries `_meta` protocol version and capabilities).
4. Server executes, returns a result (`resultType: "complete"`), an `InputRequiredResult`, or a task handle.
5. AI uses result to inform next step (e.g., "The layer is now 80% transparent; now I'll export.").

**Example for UzPainter**:
- AI observes project via `resources` (list layers, fetch layer metadata) and an `inspect_project` tool/resource (see 03).
- AI calls tools to manipulate state (adjust opacity, add layer, export).
- AI can also request prompts (e.g., "refine_textures") to guide its own generation.

## Trade-Off Summary

**Choice: open — process topology and state owner forwarded to architecture** (the draft's "Python SDK + Subprocess (stdio) MCP Server" does not give the external AI a path to the live renderer).

**Corrected considerations**:
- **Spec Compliance**: the official Python SDK is Tier 1 and LF-hosted (MIT) and speaks 2026-07-28, but does not implement the Tasks extension; pin an actual release.
- **Simplicity**: Python type hints generate JSON Schema; bounds and cross-field rules still need explicit validation.
- **Process Isolation**: a worker protects the renderer only from faults inside the worker; it adds IPC and state-copy costs.
- **Debuggability**: any MCP client (e.g., MCP Inspector, Claude Desktop) can connect to a stdio server it launches itself.
- **Licensing**: Python SDK MIT; TypeScript SDK Apache-2.0 (new contributions) + MIT (existing code); Gopher Apache-2.0.

**Implementation Sketch** (official Python SDK v2; pin the exact release before use):
1. Embed CPython and vendor the Python MCP SDK into the private runtime (see 01).
2. Write Python module `uzpainter/mcp_server.py`:
   ```python
   from mcp.server import MCPServer
   import uzpainter  # native module exposed by the UzPainter host (in-process embedding)

   mcp = MCPServer("uzpainter")

   @mcp.tool()
   def bake_normal_map(resolution: int, strength: float, project_revision: str) -> dict:
       """Bake a normal map; returns an artifact reference and hash."""
       return uzpainter.bake_normal(resolution, strength, project_revision)

   @mcp.resource("uzpainter://project/layers")
   def layers() -> str:
       """Current layer tree as JSON."""
       return uzpainter.layers_json()
   ```
3. Start the transport per the pinned release's documentation. The README (retrieved 2026-10-10) shows `uv run mcp dev server.py` (Inspector) and `uv run mcp run server.py --transport streamable-http` (HTTP); the in-code stdio entry point was not verified in this pass.
4. The AI host launches the process that hosts this server. If UzPainter itself ever has to act as an MCP client, it needs a real client implementation; otherwise use a separate internal command API.

**Alternative (if Python unavailable or team expertise limited)**:
- Native C++ endpoint (own code or the Gopher C++ SDK after evaluating its Windows build, dependencies, tests and protocol generation).
- Upside: single-language stack, direct state access.
- Downside: protocol conformance work. The draft's "larger binary" claim is **unconfirmed** (no evaluated binary).

**Re-evaluated (previously "Not Recommended")**:
- In-process embedding: not rejected — see Option A corrections.
- Streamable HTTP for a local tool: valid when a persistent application or multiple clients justify it; requires `Origin` validation, localhost binding and authentication. Session management no longer exists in 2026-07-28. Use stdio when the AI host should own one process lifecycle.

## Sources
Retrieved 2026-10-10 unless noted.
- [MCP Specification (landing, 2026-07-28)](https://modelcontextprotocol.io/specification)
- [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [MCP 2026-07-28: Transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports); [stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio); [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP 2026-07-28: Message patterns](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns); [Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
- [MCP 2026-07-28: Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP 2025-06-18 changelog](https://modelcontextprotocol.io/specification/2025-06-18/changelog); [2024-11-05 progress](https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/progress); [2024-11-05 cancellation](https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/cancellation)
- [MCP Tasks Extension](https://modelcontextprotocol.io/extensions/tasks/overview); [Tasks schema 2026-07-28](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/schema/2026-07-28/schema.ts); [MCP ext-tasks Repository](https://github.com/modelcontextprotocol/ext-tasks); [Extension client matrix](https://modelcontextprotocol.io/extensions/client-matrix)
- [Official SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk)
- [Python MCP SDK GitHub](https://github.com/modelcontextprotocol/python-sdk); [pyproject.toml](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/pyproject.toml); [v1→v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/)
- [TypeScript MCP SDK GitHub](https://github.com/modelcontextprotocol/typescript-sdk)
- [Gopher MCP C++ SDK GitHub](https://github.com/GopherSecurity/gopher-mcp)
- [FastMCP docs](https://gofastmcp.com/getting-started/welcome); [FastMCP LICENSE](https://raw.githubusercontent.com/jlowin/fastmcp/main/LICENSE)
- Superseded (2026-10-09 draft): [MCP Architecture Explained (third-party blog)](https://getknit.dev/blog/mcp-architecture-deep-dive-tools-resources-and-prompts-explained)
