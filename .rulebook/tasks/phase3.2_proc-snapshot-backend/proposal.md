# Proposal: phase3.2_proc-snapshot-backend

## Why
MAT-03 and MAT-04 (`docs/prd.md`) require the procedurals of recorded and locked recipes to evaluate identically; during migration an existing approved state (Tunic v10, locked bracers) must be preserved even where no certified family exists yet. Shipping Painter-derived captures was rejected (decision 002), so snapshots are project-private data. This child of P3-PROC (`phase3.3_procedural-families`) implements `SnapshotBackend` of `docs/architecture/05-procedural-content.md` §4 (D4) and the snapshot storage of `docs/architecture/09-project-file-format.md`.

## What Changes
- `SnapshotBackend` behind `IProceduralBackend`: a snapshot is a raster the user's own Painter produced for the user's own project, with the full signature `{asset id, asset version, effective parameters incl. defaults, preset, seed, output id, resolution, channel format, colour space, image inputs by hash, project settings that affect evaluation}`.
- Served only on an exact signature match — no resampling, no parameter extrapolation; otherwise `unavailable`. A snapshot never makes an asset editable.
- Project-private storage: snapshot rasters as authoritative raster planes with `plane_id` embedded in that project's `.uzp`, signatures in the manifest (`09-project-file-format.md`); never shipped with UzPainter, never copied into another project.
- `uzpainter assets snapshot` command that records snapshots locally through Painter's documented export API on a machine with the owner's Painter licence.

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`.
- Parent: `phase3.3_procedural-families`.

## Acceptance
A snapshot recorded for a fixture project is served byte-equal to the Painter export for its exact signature; any single-field signature mismatch yields `unavailable`; snapshots stay inside their project (no cross-project copy, not shipped, rejected by the repository guard).

## Impact
- Affected specs: procedural
- Affected code: `SnapshotBackend`, `.uzp` plane and signature storage, `uzpainter assets snapshot`
- Breaking change: NO
- User benefit: approved procedural states preserved during migration without shipping Adobe-derived data
