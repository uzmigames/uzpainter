# 164. Typed tools are native single-transaction handlers over the API's shared edits, gated per argument value, with the gap families registered

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.6_mcp-typed-tool-families, phase2.5_mcp-transport-registry, phase2.7_mcp-operation-matrix, phase2.8_mcp-server

## Context

phase2.6 delivers the typed tool families of `docs/architecture/11-mcp-server.md` §2, so every operation available in the build is reachable with Python disabled (owner Q12; INT-02, ARC-14). Facts at the start:

- The `uzpainter` API implements each operation as a pybind lambda calling `Session::Mutate(tool, args, edit)` with a fresh key; the edit bodies were file-local in `bind_*.cpp`.
- A typed mutation must be one transaction submitted with its client's key and original precondition (`Session::Submit`, decision 138), so its operation row answers a retry.
- The registry (decision 158) gates a tool by the operations it declares. Some tools are available or not depending on an argument: `layer_insert {kind: paint}` needs paint layers (a release gap), `kind: fill` does not.
- 11 §4 says `project_create` and `project_save_as` write their record into the new file's first transaction. `save_as` commits no revision.
- 11 §2 lists `sync_stack {stack_json, masks_dir, state?, resource_prefix, resource_group, keep_visible, texture_set}` with the `painter_layer_stack.py sync` semantics, and `mask_set {uid, background?, enabled?, blending?}`.

The model panel was consulted in one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). This decision records C1, C2, C3 and C7; decision 165 records C4, C5 and C6.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Native handlers over shared edits, uid and name addressing, `params` in the same transaction | PARTLY | PARTLY | AGREE |
| C2 Per-argument-value capability gating; gap families registered and refused on both sides | PARTLY | PARTLY | AGREE |
| C3 `project_create` writes its row in the new project's first transaction; `project_save_as` stays a lifecycle call | DISAGREE | PARTLY | PARTLY |
| C7 `set_rename`, `project_close {discard}`, `project_inspect {path}` | PARTLY | AGREE | AGREE |

Refinements adopted:

- C1: a named insert that finds its node applies its `params` to that node (an upsert), so repeating the same call is a no-op and a call with other params changes only them (GPT). `params` has a schema, validated before admission (Kimi). The name scope is the list the position names, so a parent group scopes it (Kimi).
- C2: the per-value gate runs after schema validation, so an unknown value is `invalid_arguments`, not a gap (Kimi). A value the map does not list is a gap: it fails closed (Kimi, GPT). The worker also turns a release gap its native code meets (`NotYetSupported` and its kin) into `capability_gap`, so a direct pipe client gets the same answer (GPT).
- C3: `project_save_as` is a long tool: it gets a ledger job and is refused `busy` while another job runs (Kimi, Grok). The doc's line is corrected.
- C7: a rename to another set's name fails before mutation; the same name is a no-op (GPT, Kimi). `project_inspect {path}` follows the project root (GPT).

Not adopted: a separate durable record for `project_save_as` (GPT). It commits no revision, so there is no transaction for a row, and a repeat writes the same revision to the same file.

## Decision

1. **Native handlers.**
   - The typed tools live in `src/supervisor/typed_tools.cpp`. The worker registers them beside its own (`ToolDefinition`, `src/supervisor/tools.h`).
   - Each mutating tool is one transaction through `SubmitAdmitted`: the client's key and original precondition.
   - The edits the API and the tools share moved into `src/python/edits.{h,cpp}`: channel checks, fills, sources, blending, LAY-06 insertion with Painter's insert defaults, levels, bitmaps, texture sets and channels, mesh-map binding, resource import and replacement, and the mesh reload. Both callers run the same code.
2. **Arguments.**
   - Setters address nodes by `uid` (`x-uzpainter-ref: node`).
   - Stack-level calls take `texture_set` and `stack` names, the active stack when omitted.
   - Inserts take `above`, `below` or `inside` (at most one), or the top of the stack. A `name` gives LAY-06: the node of that name and kind in the target list is returned (`created: false`, `no_op`); several give `ambiguous_name {candidates}` before mutation. `params` are the setter's fields, applied in the same transaction, to a found node too.
   - Colours are stored as given (the native API's rule, `bind_color.cpp`).
   - Resources are named by URL or by name.
3. **Per-value capabilities.**
   - A schema property may carry `x-uzpainter-capability {<value>: [ops], "*": [ops]}`. After schema validation, the registry adds the operations of the given value (`*`: of any value) to the tool's own.
   - A release gap among them fails `capability_gap {tool, operations: [{..., argument, value}]}`. An unlisted value is a gap.
   - `tools/list` carries each value's status under `_meta["uzpainter/capability"].values`.
   - The gated values: the insert kinds, the projection modes, the source kinds, `source_mode: Material`, the project workflows, the resource usages and any geometry mask.
4. **Gap families.**
   - These are registered with their schemas and declare release-gap operations: `resource_search`, `assets_search`, `layer_instantiate`, `procedural_set`, `anchor_list`, `smart_material_insert`, `smart_mask_insert`, `smart_export`, `apply_smart` and the six baking tools.
   - Their worker handlers refuse with `capability_gap` naming the owner task.
   - Two absent names become `uzpainter-additions.json` release gaps: `uzpainter.assets.search` and `uzpainter.layerstack.set_procedural`.
5. **Project lifecycle.**
   - `project_create` is long and mutating, with commit point `revision`. `Session::Create` takes the admitted request (`CreateCall`), so its operation row is in the new project's first transaction. A lost-acknowledgement retry finds the new project open and returns the stored outcome. Its mesh maps are imported and bound in that transaction.
   - `project_save_as` is long and non-mutating, with no commit point.
   - `project_revert` submits the admitted request (`Session::RevertRequest`).
   - `project_close {discard}` refuses an untitled project without `discard: true`, because closing deletes it. A saved project loses nothing: every commit is durable.
   - `project_inspect {path}` is the store's read-only inspection report.
6. **`sync_stack`.**
   - `resource_prefix` and `resource_group` name the imported images `<prefix><name>` in that group (`SyncOptions`). Without them, the result is unchanged.
   - There is no `state`. The script's state file maps SHA-1 to session-scoped resource URLs. UzPainter's resource URLs carry their content hash and survive sessions (RES-02), so nothing needs that cache. A call that names `state` fails schema validation; it is never silently ignored.
7. **`mask_set`** adds or removes a layer's mask (`present`) and sets its `background` and `enabled`. It sets no mask blending: no documented Painter operation sets one. The model keeps the field for round-trip.

## Alternatives Considered

- **Typed tools as shipped Python over the facade.** Rejected: each facade call is its own transaction with its own key, so a multi-call tool could not carry one operation row (decision 138). The proposal names native operations.
- **Duplicating the edit bodies in the worker.** Rejected: two copies of the same rule drift.
- **Gating only whole tools.** Rejected: `layer_insert` would be all available or all gap, and a paint insert would fail inside the worker as `call_failed` instead of `capability_gap` before admission.
- **A `state` file written for compatibility.** Rejected: it would be a cache of nothing.

## Consequences

- `phase2.7_mcp-operation-matrix` maps requirements to these tools. A family becomes callable when its manifest entry changes, with no MCP change.
- The bindings call `edits.h`, so API and MCP behaviour stay identical by construction.
- `tests/supervisor/test_typed_tools.py` drives every family through `UzPainter.exe --mcp` with Python disabled. `tests/supervisor/test_registry.py` covers the value gate in pure Python.
