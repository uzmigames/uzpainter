## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker

## 2. Implementation
- [ ] 2.1 Tool registry shared by both transports; handlers forward to the worker over the pipe inside an executor
- [ ] 2.2 stdio transport with protocol frames only on stdout and logs on stderr and in the ledger
- [ ] 2.3 Streamable HTTP transport (`--mcp-http 127.0.0.1:<port>`): Origin validation, bearer token (generated or `--token`), non-loopback binding refused without `--allow-remote`
- [ ] 2.4 Input schema validation (bounds, enums, object references) before admission; `structuredContent` + text summary results; image content blocks only for `capture`
- [ ] 2.5 Mutating-tool contract: key and precondition handling with the omission rule of `11-…` §4; result fields `revision`, `committed_revision`, `job_id`, `changed/created/hidden/imported/skipped`, `warnings`; structured error codes
- [ ] 2.6 Lease at the boundary: implicit for stdio, explicit `lease_acquire/lease_release/lease_status` in HTTP mode
- [ ] 2.7 Path roots: `--roots` parsing, canonicalisation (absolute, reparse points, `file:///`, relative), per-operation root check, no out-of-root path in any result
- [ ] 2.8 `run_python` registered only with `--allow-python`; `result`/stdout/stderr returned separately; lease, revision and per-call transaction rules applied
- [ ] 2.9 Capability-driven availability: tools of `release-gap` operations fail with a structured capability-gap error before mutation

## 3. Tests
- [ ] 3.1 stdio framing test: nothing but protocol frames on stdout under logging load
- [ ] 3.2 HTTP tests: bad Origin rejected, missing or wrong bearer rejected, non-loopback bind refused without `--allow-remote`, client reconnect keeps lease and job state
- [ ] 3.3 Schema tests: out-of-bound numbers, unknown enum members and dangling object references rejected before admission
- [ ] 3.4 Roots tests: absolute, relative, `file:///` and reparse-point paths outside the roots rejected; Windows path forms normalised
- [ ] 3.5 `run_python` absent from the tool list without `--allow-python`; with it, a script raising after two committed calls returns the last committed revision and partial changes
- [ ] 3.6 Omission rule: call without key and precondition gets both generated and returned; call with a key but without its precondition is rejected

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.8_mcp-server`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
