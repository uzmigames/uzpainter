# 158. The MCP registry refuses a key without its precondition, gates release gaps, confines paths to roots and shapes every result

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.5_mcp-transport-registry, phase2.6_mcp-typed-tool-families, phase2.7_mcp-operation-matrix, phase2.2_supervisor-admission-ledger

## Context

phase2.5 puts one tool registry in front of admission (11-mcp-server.md §2, §4, §5). Four choices had real consequences:

- **The omission rule.** 11 §4 says a call may omit `expected_revision` only when it also omits `idempotency_key`, and the task's test 3.6 says a key without its precondition is rejected. Decision 138 (phase2.2) chose to forward such a call: the worker answers the key's stored outcome or `outcome_unknown`, and never runs it. One phase2.2 test replayed a key with no precondition through MCP and expected `outcome_unknown`.
- **Roots.** Existing tests open projects from temporary folders without roots. The worker writes evaluation payloads and diagnostic exports under `--output-root`. Results carry paths: receipts, export directories, the temporary store of an untitled project, and `supervisor_status`.
- **Capability gating.** The build ships `capabilities.json` with each symbol's status. Tools are defined in the worker (C++).
- **The result contract.** A transaction result has `created`, `hidden`, `imported`, `modified`, `removed` and `skipped`. A script's report lists its committed calls. 11 §2 names `changed/created/hidden/imported/skipped` and `warnings`.

The model panel was consulted in one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). This decision records C1, C2, C4 and C5; decision 159 records C3, C6 and C7.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Refuse a key without its precondition at the MCP boundary | AGREE | AGREE | AGREE |
| C2 Roots: allowlist with `--roots`, unconfined without; canonical paths; no echo; scrub results | PARTLY | PARTLY | PARTLY |
| C4 Capability gating from the shipped manifest before admission | PARTLY | AGREE | AGREE |
| C5 Result contract fields and a one-line summary | PARTLY | AGREE | PARTLY |

Refinements adopted:

- C2: scrub only the fields known to hold paths, not every string (Kimi); compare paths case-insensitively, as Windows does (Kimi); check the lexical path first, so another drive or UNC share is refused without a filesystem lookup (GPT); keep today's behaviour when `--roots` is absent (Kimi, Grok).
- C4: a declared operation missing from the manifest counts as a gap, failing closed; a malformed manifest is fatal at start (Kimi).
- C5: `changed` is modified ∪ removed only; only committed calls are gathered; `job_id`, `revision` and `committed_revision` are always present, null when they do not apply; the summary follows one template (Grok, Kimi).

Refinements not adopted:

- GPT's worker-side recheck against a reparse point created after the supervisor's check. The supervisor hands the worker the resolved path, and roots are policy for a local operator, not a sandbox.
- GPT's per-operation output containment beyond the output root. The output root is the export root, or a folder inside a root.

## Decision

1. **Order of checks.** Every refusal below comes before admission: no job row, and nothing is sent to the worker.
   1. The capability gate.
   2. Schema validation: JSON Schema 2020-12 for types, bounds, enums, required and unknown properties. The error names the argument and the rule, never the value.
   3. The key rule.
   4. Object references (`x-uzpainter-ref`: `node`, `texture_set`, `stack`), checked against the committed revision's layer tree.
   5. Roots.
   6. The HTTP owner (decision 159).
2. **The key rule (supersedes decision 138 item 4, third row, at the MCP boundary).**
   - A mutating call that carries `idempotency_key` without `expected_revision` fails `invalid_arguments` (`/expected_revision`, rule `dependentRequired`).
   - The worker's pipe still decides a key-only request for direct pipe clients: the stored outcome, or `outcome_unknown`.
   - Neither form ever creates a mutation. The phase2.2 test now expects the refusal.
3. **Roots.**
   - Without `--roots`, nothing is confined.
   - With `--roots`, the roots are an allowlist. A tool's schema names each path argument's root with `x-uzpainter-root`, or with `x-uzpainter-paths {member: root}` for an object or JSON text such as the export config's `exportPath`. A root kind that is not named refuses every path of that kind.
   - A path is canonicalised in this order: a `file:` URI becomes a path, a `\\?\` prefix is dropped and `/` becomes `\`; a relative path is taken under its root; the lexical form is checked; reparse points are resolved with `realpath` and the result is checked again.
   - The worker receives the canonical path. A refusal is `path_outside_roots {argument, root, reason}`, without the path.
   - The worker's output root defaults to the export root and must lie inside a root (a usage error otherwise).
   - Results replace any path-valued field (`path`, `directory`, `receipt`, `project`, `project_path`, `mesh_path`, `output_root`, `exportPath`, `ledger`, `crash_dir`, `minidump`) that lies outside the roots with `<outside the roots>`. A `run_python` result's own body is exempt; its receipt is not.
4. **Capability gating.**
   - A worker tool lists `capability: [{symbol, context}]`, the manifest operations it performs.
   - The supervisor loads `capabilities.json` beside `UzPainter.exe` at start. A missing or malformed manifest is a fatal start error (exit 4).
   - A call whose operation is `release-gap`, or is not in the manifest, fails `capability_gap {tool, operations}`.
   - The tool stays listed, with `_meta["uzpainter/capability"]`. It becomes callable when its manifest entry changes, with no MCP change.
   - Today's tools declare `project_open`, `project_close`, `project_save`, `export` and the three diagnostic exports. All of them are supported or pending evidence.
5. **The result contract.**
   - Every forwarded result has these fields at top level:
     - `revision`: the revision the call was admitted on;
     - `committed_revision`: the project's committed revision after the call;
     - `job_id`;
     - `changed`: modified ∪ removed;
     - `created`, `hidden`, `imported` and `skipped`, gathered over the committed transactions, including the calls a raising script committed;
     - `warnings`.
   - The worker's `result` or `error` and the `receipt` stay as they were.
   - The text content is one line: `<tool>: <status>[; revision a -> b][; <counts>][; job j]`, or `<tool>: error <code>: <message>`.
   - Image blocks are produced only for `capture` (phase2.6 fills its `image`).

## Alternatives Considered

- **Keep forwarding a key-only call (decision 138).** Rejected: it contradicts 11 §4 and the task's test 3.6.
- **Confine paths even without `--roots`.** Rejected: it would break today's local stdio use and its tests, and 11 §5 makes roots a launch option.
- **Scrub every string that looks like a path.** Rejected: it would mangle names and script output.
- **Keep the capability mapping in the supervisor.** Rejected: the worker defines the tools, so phase2.6 adds each mapping next to its tool.

## Consequences

- phase2.6's typed tools need only their schema annotations and their `capability` entries. Validation, references, roots, gating and the contract come from the registry.
- A client that retries keeps the key and the precondition its receipt names.
- The phase2.7 matrix can read each tool's operations from `tools/list`.
