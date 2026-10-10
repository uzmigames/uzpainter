# Proposal: phase1.6_mesh-reload

## Why
When the low-poly mesh changes, the project must keep its stacks and resources, match texture sets by material identity, report which texels changed, and invalidate dependent mesh maps, geometry masks, procedural caches and receipts — never attaching silently to renamed, split or merged materials (PRJ-08, BAK-06). Implements D11 (decision 013) under owner answer Q8 (decision 021: zero dependency on UzEngine; UzPainter neither vendors nor calls UzEngine's cook path) in `docs/architecture/12-mesh-import.md`, with the normal convention and per-fragment frame settled by P0-NORMAL. Child of `phase1.7_mesh-loader` (P1-MESH), covering `docs/architecture/12-mesh-import.md` §7 and `docs/architecture/03-project-model.md` §4. `docs/dag.md` gives P1-MESH no P1-CORE input, so the pixel-domain metrics of this task are computed by the mesh module without the GPU UV raster pass of `phase1.3_core-uv-raster` and run on the hosted CPU lane.

## What Changes
- `src/mesh/reload.{h,cpp}`: native `project.reload_mesh(path, settings)` as one document transaction: parse and certify the new mesh; match texture sets by material identity (renamed, split or merged materials are an explicit error carrying a mapping proposal, never a silent attach); keep stacks and resources; compare corner hashes per set and classify texels unchanged / moved / new / replaced; mark mesh-map bindings, geometry masks, procedural caches and downstream receipts `invalid` (kept, flagged, never deleted); return `{sets: added, removed, renamed}` and the per-set region classes. Failure leaves the old mesh.
- The facade's `reload_mesh(path, settings, cb)` callback delivery is provided by `phase1.21_pyapi-dispatcher-lifecycle`.

## Dependencies
- DAG inputs of the parent: `phase1.3_document-model` (transactions, mesh-map binding `invalid` state).
- Sibling prerequisites: `phase1.4_mesh-importers`, `phase1.5_mesh-tangents-certificate`.
- Parent: `phase1.7_mesh-loader`. Consumer: `phase1.21_pyapi-dispatcher-lifecycle` (facade callback).

## Acceptance
The `docs/architecture/12-mesh-import.md` §9 reload/rename/split fixtures pass: bindings are preserved where material identity matches and deliberately rejected with a mapping proposal where it does not.

## Impact
- Affected specs: `mesh`
- Affected code: `src/mesh/reload.*`, `tests/mesh/`
- Breaking change: NO
- User benefit: A mesh fix never costs the painted stack, and every map that the change invalidated is flagged instead of silently reused.
