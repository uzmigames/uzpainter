## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker

## 2. Implementation
- [x] 2.1 Tool registry shared by both transports; handlers forward to the worker over the pipe inside an executor
- [x] 2.2 stdio transport with protocol frames only on stdout and logs on stderr and in the ledger
- [x] 2.3 Streamable HTTP transport (`--mcp-http 127.0.0.1:<port>`): Origin validation, bearer token (generated or `--token`), non-loopback binding refused without `--allow-remote`
- [x] 2.4 Input schema validation (bounds, enums, object references) before admission; `structuredContent` + text summary results; image content blocks only for `capture`
- [x] 2.5 Mutating-tool contract: key and precondition handling with the omission rule of `11-…` §4; result fields `revision`, `committed_revision`, `job_id`, `changed/created/hidden/imported/skipped`, `warnings`; structured error codes
- [x] 2.6 Lease at the boundary: implicit for stdio, explicit `lease_acquire/lease_release/lease_status` in HTTP mode
- [x] 2.7 Path roots: `--roots` parsing, canonicalisation (absolute, reparse points, `file:///`, relative), per-operation root check, no out-of-root path in any result
- [x] 2.8 `run_python` registered only with `--allow-python`; `result`/stdout/stderr returned separately; lease, revision and per-call transaction rules applied
- [x] 2.9 Capability-driven availability: tools of `release-gap` operations fail with a structured capability-gap error before mutation

## 3. Tests
- [x] 3.1 stdio framing test: nothing but protocol frames on stdout under logging load
- [x] 3.2 HTTP tests: bad Origin rejected, missing or wrong bearer rejected, non-loopback bind refused without `--allow-remote`, client reconnect keeps lease and job state
- [x] 3.3 Schema tests: out-of-bound numbers, unknown enum members and dangling object references rejected before admission
- [x] 3.4 Roots tests: absolute, relative, `file:///` and reparse-point paths outside the roots rejected; Windows path forms normalised
- [x] 3.5 `run_python` absent from the tool list without `--allow-python`; with it, a script raising after two committed calls returns the last committed revision and partial changes
- [x] 3.6 Omission rule: call without key and precondition gets both generated and returned; call with a key but without its precondition is rejected

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.8_mcp-server`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- Recordings: none. The MCP layer is UzPainter's own control plane, and it reproduces no Painter behaviour.
- 1.1: left open on purpose. phase2.4_supervisor-worker is merged on main but not accepted: its 4.1 waits on the Vulkan device cases (decision 121), the hosted CPU lane and G1. This task builds on its code on main.
- Decisions:
  - 158: the registry's order of checks; a key without its precondition refused at the MCP boundary (supersedes decision 138 item 4, third row, for MCP); roots; capability gating; the result contract.
  - 159: the HTTP guard and transport, the owner-bound lease, ledger logs and the executor.
  - Panel: one round (GPT-6 Astra, Kimi K3, Grok 4.5). C1 AGREE ×3. C2 PARTLY ×3, refined. C3, C4, C6 and C7 AGREE ×2 and PARTLY ×1. C5 AGREE ×1 and PARTLY ×2.
- 2.1:
  - `python/uzpainter_supervisor/registry.py` serves both transports through one SDK low-level `Server` (`main._server`).
  - Handlers are coroutines over the overlapped pipe client. The one blocking step, root canonicalisation, runs in `asyncio.to_thread` (decision 159).
- 2.2:
  - The SDK's `stdio_server` diverts file descriptor 1 to stderr while it serves.
  - Logs go to stderr and to the ledger's new `log` table (version 2, newest 10 000 rows). Every call is logged.
- 2.3:
  - `transport_http.py` serves the SDK's Streamable HTTP app on uvicorn behind its own guard: Origin, Host and bearer.
  - The token is generated (printed once on stderr, never logged) or given by `--token`.
  - A non-loopback bind is a usage error without `--allow-remote`.
  - Ctrl+Break stops the server with exit 0. The worker now starts in its own process group, so the signal never reaches it.
- 2.4:
  - JSON Schema 2020-12 validation. An error names the argument and the rule, never the value.
  - `x-uzpainter-ref` references (`node`, `texture_set`, `stack`) are checked against the committed layer tree.
  - The text content is a one-line summary. Image blocks are produced only for `capture`, whose `image` field phase2.6 fills.
  - The worker's schemas gained the annotations, `uniqueItems` on `isolate_layer.channels`, and `run_python`'s `code | path`. `display_set.color_lut` admits a SHA-256 string, so a LUT stays an `UnsupportedInUzPainter` refusal (decision 038) rather than a malformed argument.
- 2.5:
  - Every forwarded reply carries `revision`, `committed_revision`, `job_id`, `changed` (modified ∪ removed), `created`, `hidden`, `imported`, `skipped` and `warnings` (`admission.contract`). The ledger keeps the reply as answered, so `job_result` matches it after a restart.
  - The structured errors are those of phase2.2-2.4, plus `capability_gap`, `path_outside_roots` and `lease_required`.
- 2.6: the lease tools are listed in HTTP mode only. Owners are bound per `Mcp-Session-Id`, and a reconnecting client names its owner again.
- 2.7:
  - `roots.py`. With `--roots`, the output root defaults to the export root and must lie inside a root.
  - Path fields outside the roots are replaced with `<outside the roots>`. A `run_python` result's own body is exempt.
  - Without `--roots`, nothing changes.
- 2.8: `run_python` is listed by the worker only with `--allow-python`. Without the flag, a call is answered `python_disabled` at the worker's boundary. `path` runs a script file through `RunScript`. The report's `result`, `stdout` and `stderr` are separate fields.
- 2.9:
  - Worker tools declare `capability: [{symbol, context}]`. Today `project_open`, `project_close`, `project_save`, `export`, `isolate_layer`, `material_views` and `region_stats` declare theirs, and all are supported or pending evidence in the shipped manifest.
  - The supervisor loads `capabilities.json` beside the exe at start; missing or malformed is fatal.
  - A `release-gap` or unlisted operation fails `capability_gap` before admission. A manifest change makes the tool callable (test_registry.py).
- 3.1-3.6, 5.3: local runs on 2026-10-12, worktree `wt/p2-mcp-transport`, Vulkan workers (no GPU device):
  - New and changed tests: `test_supervisor_transports.py`, `test_registry.py`, `test_roots.py`, `test_transport_http.py`, and the 3 changed MCP tests. First run: 21 passed and 3 failed, all three test-side (exit 1). The 3 failed node ids plus `test_registry.py` then passed: 12 passed, exit 0.
  - `UZP_NO_GPU=1 python -m pytest tests/supervisor` without the tests above: 76 passed, 4 skipped, 2 failed (exit 1, 104 s). Fixed: `job_result` after a restart now returns the contract fields the reply carried, and `display_set`'s `color_lut` schema now admits a SHA-256 string. Re-run of the two failed tests with everything the fixes touch (`test_admission.py`, `test_registry.py`, `test_supervisor_jobs.py`, and the display test): 22 passed, exit 0.
  - ruff, `ruff format --check` and mypy (strict) are clean on `python/uzpainter_supervisor` and `tests/supervisor`. `zig build painter` (Debug, `-Werror`) succeeds.
- 4.1: the evidence is attached to `phase2.8_mcp-server` (its §6 notes).
