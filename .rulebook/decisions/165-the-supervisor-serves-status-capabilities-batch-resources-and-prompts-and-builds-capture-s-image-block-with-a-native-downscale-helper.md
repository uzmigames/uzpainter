# 165. The supervisor serves status, capabilities, batch, resources and prompts, and builds capture's image block with a native downscale helper

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.6_mcp-typed-tool-families, phase2.5_mcp-transport-registry, phase2.2_preview-capture, phase2.8_mcp-server

## Context

Besides the worker's typed tools (decision 164), 11 §2 lists `status`, `capabilities` and `batch {calls[], stop_on_error}`, eight resources and four prompts. It also says a capture returns "a downscaled PNG as an MCP image block built by the supervisor from the file" (02 §2).

phase2.5 attached the capture's PNG as it was, up to 4 MiB, and left the downscale to this task. The supervisor's embedded interpreter has no image library, but UzPainter.exe links spng (`evaluator::DecodeBitmap`, `exporter::EncodePng`).

The model panel's votes on C4-C6 (one round; decision 164 holds C1-C3 and C7):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C4 `status`, `capabilities`, `batch` in the supervisor; `batch` runs each call through the registry, not atomic, `not_executed` after a stop, no nesting, long calls with `wait` | AGREE | PARTLY | AGREE |
| C5 The supervisor downscales capture's PNG with a native helper (area average, long edge 512); a block that cannot be built leaves the capture succeeded with a warning | DISAGREE | AGREE | PARTLY |
| C6 Resources and prompts served by the supervisor; `project/manifest` through a pipe method; static UzmiGames prompts | AGREE | PARTLY | AGREE |

Refinements adopted:

- C4: a batch key gives every mutating call without its own key `<key>/<index>` and the revision current at its admission, so a retried batch returns the stored outcome of each committed call instead of running it again (Kimi). The batch's `status` tells `completed`, `completed_with_errors` and `stopped` apart (GPT). Interleaving between calls is bounded by the lease: another owner cannot mutate while this owner holds it (Kimi, Grok).
- C5: an image block that cannot be built is never silent. The result carries `image {built: false, reason}` beside the capture's receipt, and a warning (Kimi, Grok). The capture itself stays succeeded: its files and receipt are durable, and the block is a convenience copy of `files.png`, which the result names with its hash. GPT asked for an error; the majority kept the explicit field. The helper refuses a file over 512 MiB or a side over 16384 px before decoding, so a malformed PNG cannot exhaust the supervisor (Kimi).
- C6: every project resource names `project_uuid` and `revision`; with no project open, the read fails (Kimi).

## Decision

1. **Supervisor tools.**
   - `status`: the worker's and the supervisor's builds, the IPC protocol, the manifest's compat profile, the GPU backend and its status, the Python policy, the project (path, UUID, untitled), its committed revision, the running jobs and the lease.
   - `capabilities`: entry counts by status, and each worker tool's status with its gap operations and gap argument values (`Registry.capability_table`).
2. **`batch {calls: [{tool, arguments}], stop_on_error = true, idempotency_key?}`.**
   - Each call goes through `Registry.call` in order: every check, its own admission, job, transaction and receipt. A long call runs with `wait`.
   - A failed call stops the batch when `stop_on_error` is set; the calls after it are `not_executed`. A nested batch fails that call `invalid_arguments`.
   - Result: `{status, executed, failed, results: [{index, tool, status, summary, body}]}` and the committed revision after the batch.
   - A batch is not atomic. Atomic multi-edit work is `sync_stack`, or an insert with `params`.
3. **Capture's image block.**
   - The built-in module `_uzpainter_image` (`src/supervisor/image_block.{h,cpp}`) offers `preview_png(png, max_edge)`. It decodes 8- or 16-bit grey or RGB; alpha is not kept.
   - It averages k×k blocks, with the smallest whole k that brings the long edge to at most `max_edge` (k = 1 keeps the size). Each average is rounded to the nearest 8-bit code, half up, and written as an 8-bit PNG.
   - It refuses a file over 512 MiB or a side over 16384 px before decoding.
   - The registry calls it in the executor with `IMAGE_EDGE = 512` and records `image {built, mime_type, width, height, max_edge, sha256, source_sha256}`. A failure is `image {built: false, reason}` and a warning.
   - The block is a preview for an agent, never parity evidence: parity reads the receipt's PNG and OpenEXR.
   - It is the supervisor's helper, not a `uzpainter` API name, so the capability manifest does not list it.
4. **Resources** (`python/uzpainter_supervisor/resources.py`), all `application/json`:
   - `uzpainter://capabilities`: every manifest entry and the tool table;
   - `uzpainter://project/manifest`: the pipe method `worker/manifest`, which returns the committed revision's `ProjectToJson`;
   - `uzpainter://project/recipe`, `uzpainter://project/layers` and `uzpainter://project/resources`: the read tools `project_recipe`, `snapshot_layer_tree` and `resource_list`, read through the registry, so the roots scrub them;
   - `uzpainter://assets/parity`: no assets yet, with the status of `uzpainter.assets.search`;
   - `uzpainter://jobs/{job_id}`: a resource template, `job_status`;
   - `uzpainter://ledger`: the 50 newest jobs.

   An unknown URI, an unknown job, or no project open is MCP error -32002.
5. **Prompts.** Four UzmiGames-authored templates, each one user message with a JSON block:
   - `stack_json_template`: the stack JSON format of `stack_sync.h`;
   - `smart_json_template`: the `smart` configuration of `docs/analysis/assets3d-pipeline/04` §F;
   - `baking_preset_template`: the fields of `bake_configure`, marked as a release gap;
   - `export_config_template`: the documented `json_config` keys with a shipped preset.

## Alternatives Considered

- **Downscaling in pure Python** (zlib and the PNG filters). Rejected: about a second per megapixel in CPython, and a second decoder beside the one the evaluator already tests.
- **Making the worker write a preview file.** Rejected: 02 §2 makes the block the supervisor's, and the worker answers one call at a time.
- **An atomic batch.** Rejected: it contradicts per-call results and the per-call receipt contract. `sync_stack` and `params` cover atomic work.
- **Failing the capture when the block cannot be built** (GPT). Rejected: it would report as failed a capture whose files are durable. The explicit `image.built: false` keeps QG-03.

## Consequences

- MCP clients can read the project, its recipe and the gaps without calling tools.
- A downscaled block is the one image path. `IMAGE_LIMIT` (4 MiB) now bounds the block, which is always far smaller.
- `tests/supervisor/test_registry.py` covers the tools, the batch, the block and the resources in pure Python. `tests/supervisor/test_typed_tools.py` covers them through `UzPainter.exe --mcp`.
