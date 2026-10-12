# 136. The diagnostic views read the committed revision through the export's entry points, refuse inferred bases per source, and the MCP tools publish export generations

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_recipe-diagnostic-views, phase2.2_recipe-and-diagnostics, phase2.6_mcp-typed-tool-families, phase2.5_mcp-transport-registry

## Context

Task `phase2.1_recipe-diagnostic-views` exposes the compositor diagnostics of phase1.13 (decisions 075 and 076) as `uzpainter.diagnostics` and as the worker's MCP Diagnostics tools (`11-mcp-server.md` §2). It also adds the layer-tree snapshot and its diff. The task names the functions but not how they read the project, what they return, how decision 126 applies to them, or what the MCP tools write.

Facts on main:

- The evaluator already computes `isolate`, `contribution`, `material_views` and `region_stats` (`src/evaluator/diagnostics.h`). The export already evaluates every `diagnosticMap` source through `EvaluateDiagnosticOn`, on the CPU evaluator (decision 111), and it refuses before writing any source that reads a channel whose template base is `inferred` (decision 126).
- The export of the Python API refuses to run inside an open native `Transaction`.
- Node uids are unique in a project (`uzp_core/types/ids.h`).
- The worker hosts the native `Session`. Its `evaluate_channel` tool writes payloads under `--output-root`. MCP roots arrive with phase2.5.
- The task's spec scenario says a "Roughness bleeding outside its material mask" is detected. Decision 075 already defines a leak: a texel inside the material's region where the full stack differs from the material's solo evaluation.

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1. The Python views read the committed revision on a CPU evaluator, with the export's inputs and entry points, and refuse inside a Transaction. Maps are float32 little-endian bytes. `region_stats` returns the export's statistics JSON | PARTLY: share the guard and the source resolution, not only the evaluator; compare to lossless exports | PARTLY: a wrong map string must raise; define the uid scope | PARTLY: lock the byte format against the OpenEXR decode |
| C2. Decision 126 is applied per source by one function shared with the export. `material_views` moves each refused channel view to `refused` and returns the others | PARTLY: refuse the view's `materialLeaks` too; partial results need a fixed schema | PARTLY: the MCP summary must carry the same `refused` | AGREE |
| C3. Snapshot records and a JSON-pointer diff by uid; objects recursed, arrays whole; revision reported, not compared | PARTLY: carry stack uids, reject a bad schema or a repeated uid, escape the pointers, define stack-level changes | PARTLY: pin the reorder behaviour in tests | PARTLY: inert state is diffed; give the schema a version |
| C4. `isolate_layer` and `material_views` publish an ordinary export generation (OpenEXR 32f, padding `passthrough`); `region_stats`, the snapshot and the diff return JSON; all are non-mutating and GPU-free | DISAGREE: publication is a file side effect; validate `path` against the output root; return the revision | PARTLY: return the evaluated revision; surface `refused` | PARTLY |
| C5. Item 1.1 stays open and the task is not archived | PARTLY | PARTLY | PARTLY |

Every PARTLY point is adopted below. GPT's DISAGREE on C4 concerns the side effect and the path, and both are adopted: publication goes only inside the output root, and every call reports its revision.

## Decision

1. **Reading.** A `DiagnosticRun` (`src/python/diagnostics.{h,cpp}`) reads the committed revision of the open project once. It refuses inside an open native Transaction (`RuntimeError`), as the export does. It evaluates on a CPU evaluator with the export's inputs: the project's template, its resources and the mesh re-derived from its stored bytes. It calls the entry points the export's `diagnosticMap` sources use, so every view equals the export of its source (item 3.6). The node of a call names its stack. A uid in no stack raises `ValueError`.
2. **Python API** (`uzpainter.diagnostics`, `bind_diagnostics.cpp`).
   - `isolate(node, map)` returns `{source, revision, node, was_visible, map}`.
   - `contribution(node, map)` returns `{source, isolated_source, revision, node, full, isolated, difference}`.
   - `material_views(material)` returns `{revision, material, mask_source, mask, inside, views, missing, refused}`. Each view is `{source, leaks_source, channel, values, leaks, leak_count, leak_texels, modal_id}`.
   - `region_stats(map, mask)` returns `{source, revision, stats}`. `stats` is the parsed canonical JSON that the export writes for `regionStats/<map>/<mask>`.
   - A map is `{width, height, components, values}`. `values` holds the float32 little-endian bytes, rows top first.
   - `map` is a `ChannelType` or a map name (decision 076). Any other value raises `ValueError` or `TypeError`. A node is a layerstack handle or its uid.
3. **Decision 126 per source.** `exporter::RequireIdentifiedBase` is the one guard, used both by `EvaluateFileOn` and by the views.
   - `isolate`, `contribution` and `region_stats` on such a channel raise `NotYetSupported`.
   - `material_views` takes each such view out, its values and its leaks together, and lists it in `refused` as `{view: reason}`. The mask, the ID view and views on observed bases are still returned. The MCP tool reports the same `refused` and exports none of the refused sources.
4. **Leaks.** The spec's "bleeding outside the material mask" is decision 075's leak, unchanged: another material shows inside the region, above it, or below it through partial opacity or mask. The seeded fixture puts an unmasked Roughness layer above the material.
5. **Layer-tree snapshot and diff** (`src/uzp_core/document/layer_tree.{h,cpp}`).
   - A snapshot is `uzpainter/layer-tree/1`: `{schema, revision, stacks, nodes}`.
   - `stacks` holds one `{texture_set, texture_set_name, stack, stack_name}` per stack.
   - `nodes` holds one record per layer, content effect and mask effect, in `ForEachNode` order: `{uid, node, kind, name, visible, texture_set, stack, parent, slot, index, params}`. `params` is the node's manifest object without its identity. Each list of nested nodes in it becomes a list of uids.
   - The diff is `uzpainter/layer-tree-diff/1`: `{before_revision, after_revision, stacks, added, removed, modified}`. Nodes are matched by uid and stacks by stack uid.
   - A change is `{path, before, after}`, with `path` a JSON pointer (RFC 6901 escaping). Objects are compared key by key. Arrays and scalars are compared whole.
   - A member present on one side only omits the other side's value. For example, a layer's first `set_opacity` on a channel creates its `blending/<channel>` entry.
   - Lists are sorted by uid, and changes by path. The revisions are reported, not compared.
   - A wrong schema, a missing or mistyped member, or a repeated uid raises `ValueError`.
   - Inert state such as `collapsed` and `preset_ref` is part of the tree, so the diff reports it.
6. **MCP Diagnostics tools** (`src/supervisor/worker.cpp`). All five are non-mutating and GPU-free, and each reports the revision it read.
   - `snapshot_layer_tree {}` and `diff_snapshots {before, after}` return the JSON above.
   - `isolate_layer {uid, channels, path}` and `material_views {mask, path}` publish an ordinary export generation through `PublishExport`, with its plan and receipt. Files are OpenEXR 32f with padding `passthrough`, one file `$textureSet_<kind>_<map or view>_<uid>.exr` per source, so each file holds the source's float32 values. `material_views` exports the mask and every returned view with its leaks. Its summary carries `inside`, `leak_count` and `modal_id` per view, `missing` and `refused`.
   - Generations never overwrite one another, and the publication lock orders concurrent calls (decision 097).
   - `path` must lie inside the worker's `--output-root`. A relative path is taken under it, and anything else is `invalid_arguments`. MCP roots widen this in phase2.5.
   - `region_stats {mask, map}` returns `{source, revision, stats}`.
   - Refusals keep the API's classes. A uid in no stack is `call_failed` with `details.type` `ValueError`.

## Consequences

- The diagnostics run on the CPU, like the export. No GPU code changes. The GPU equals the CPU on the diagnostics already (`diagnostics-gpu-vs-cpu`, decision 075 §6).
- Painter has no equivalent, so no Painter recording is needed.
- `uzpainter.diagnostics.{isolate, contribution, material_views, region_stats, snapshot_layer_tree, diff_snapshots}` move from release gap to `pending-evidence` (UzPainter-only; gate G5 decides on their contract tests).
- phase2.6 owns the final MCP contract of these tools (schemas, omission rule, registry). This decision fixes their behaviour.
