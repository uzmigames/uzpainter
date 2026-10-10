# Proposal: phase3.3_baker-evidence-publication

## Why
BAK-04 (AO miss evidence in receipts), BAK-05 (bakes as jobs with ids and unambiguous terminal status), BAK-06 (provenance on every mesh map), BAK-07 (surface accounting and lineage; RAW kept; conservation checked on an analytic fixture) and ARC-11 (`docs/prd.md`) need evidence that never alters the compatible map, a tested receipt contract and all-or-nothing publication. The P3-BAKER gate also requires MCP cancellation during a native bake. This child of P3-BAKER (`phase3.5_embree-bakers`) implements `docs/architecture/06-baking.md` §4 and §6 (D5) and the cancellation item of `docs/architecture/11-mcp-server.md` §3.

## What Changes
- Evidence maps per bake and usage: `raw`, `hit` (straight / cage), `coverage` (texel centre, conservative used surface), `miss`, `extension`; per-class counts and per-part Z<0 statistics; stored under `cache/` and regenerable.
- `BakeReceipt` exactly as `06-baking.md` §4 (`job_id`, `texture_set`, `input_revision`, `status`, `settings_hash`, `tools`, `inputs`, `usages[]` with `coverage`, `used_surface`, `fallback_texels`, `padding_texels`, `changed_used_texels`, `surface_modified`, `fidelity_evidence`, `parts[]`, `effective_normalization`) plus `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}` (`03-project-model.md`).
- Conservation rule: the seven used-surface classes are disjoint and sum to `coverage.conservative_texels`; `fallback_texels` only when the request enables a fallback; UzPainter never repairs on its own.
- Atomic publication per `(texture set, input revision)`: all enabled usages bound with `baked {baker_version, backend, settings_hash, high_meshes[], cage, mesh_hashes, effective_normalization}` provenance and the receipt stored with them, or the job fails/cancels with no partial authoritative bake.
- Job model: `bake_async(texture_set) → StopSource`, `bake_selected_textures_async()`, native `Job` (id, progress, `cancel()`, terminal `Success | Cancel | Fail`, per-baker error detail); events `BakingProcessAboutToStart`, `BakingProcessProgress`, `BakingProcessEnded` on the Python dispatcher thread; `project.is_busy()` true while running; cancellation acknowledged immediately, receipt states stopped before or after publication.
- MCP `bake_start {sets[], wait?}` over the job ledger with `job_cancel`/`job_status`/`job_result`.

## Dependencies
- Prerequisites: `phase3.1_baker-request-model`, `phase3.2_baker-normal` (the first usage published end to end).
- Parent: `phase3.5_embree-bakers`. Unblocks `phase3.4_baker-ao`, `phase3.4_baker-world-space-normal`, `phase3.4_baker-id`, `phase3.4_baker-curvature`, `phase3.4_baker-position`, `phase3.4_baker-thickness`, `phase3.4_baker-height`, `phase3.4_baker-bent-normals`, `phase3.4_baker-opacity`.

## Acceptance
Receipt accounting asserts exact per-class counts and the conservation identity on the analytic fixtures (plane, sphere, bevelled cube with highs, a part with a buried face); publication is all-or-nothing under cancellation and failure injection; MCP cancellation during a native bake passes (P3-BAKER gate item).

## Impact
- Affected specs: baker
- Affected code: bake evidence and receipt writer, publication into project bindings, bake job model, facade events, MCP `bake_start`
- Breaking change: NO
- User benefit: auditable bakes that never half-publish and can be cancelled safely
