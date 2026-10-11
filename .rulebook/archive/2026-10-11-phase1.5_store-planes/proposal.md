# Proposal: phase1.5_store-planes

## Why
Child of `phase1.8_project-store` (P1-STORE in `docs/dag.md`), implementing D8 as specified in `docs/architecture/09-project-file-format.md` §1 ("Authoritative raster planes") and the paint-plane model of `docs/architecture/04-layer-stack-and-compositing.md` §1 (paint layers and paint effects hold one authoritative raster plane per active channel, `planes{channel → plane_id}`). Paint-layer content written by bitmap and projection operations (brush strokes are out of scope, owner Q5, decision 019) and frozen procedural snapshots embedded per project are authoritative state that cannot be re-derived, so the store must keep them losslessly, never alias two planes on the same channel and tile, never flatten them into a composite, and keep every retained revision's pixels reachable while writing only what an edit changed. Requirements: SAV-01, SAV-02, NFR-04, NFR-08, OWN-07 (`docs/prd.md`).

## What Changes
- `plane` rows with a persistent `plane_id`, referenced explicitly by the owning node, source or output in the manifest, keeping the plane's set, stack, channel, UV-tile identity (`tile_u`, `tile_v`), native format, size and chunk size; any number of planes may share a set/stack/channel/tile.
- Immutable `plane_version` rows with `chunk_root` = SHA-256 of the sorted `(chunk_x, chunk_y, sha256)` list; `plane_chunk` rows keyed by `(version_id, chunk_x, chunk_y)` whose coordinates index the evaluator's 1024×1024 tiles inside the plane (`04-…` §2), distinct from UV-tile coordinates; chunk pixels stored as zstd blobs in `blob`, addressed and deduplicated by SHA-256.
- Copy-on-write edits: a new version writes blobs only for the chunks it changed, copies the hash rows (no pixel data) of the unchanged ones and omits empty chunks, which read as the plane's empty value; a committed version is never modified.
- Manifest bindings: every retained manifest binds each raster plane to a `plane_version.version_id` and its chunk-root hash, written in the same commit transaction as the revision (through the commit path of `phase1.4_store-container-operations`).
- Read path that resolves the manifest's binding for the requested revision, never the greatest global chunk revision below it.
- Plane integrity rules, run on open and exported for `uzpainter inspect --verify`: foreign keys enforced (`PRAGMA foreign_keys = ON`); every plane binding in a retained manifest names an existing `plane_version` of that `plane_id` whose chunk rows hash to its `chunk_root`; every chunk hash exists in `blob`; every `plane` and `plane_version` row is reachable from a retained manifest or reported as collectable by `compact`; a chunk blob whose bytes do not match its SHA-256 is reported with the affected plane and owning node.
- Store-level plane write API used by the later bitmap and projection operations (paint layers, `phase4.2_remaining-nodes`) and frozen procedural snapshots (`phase3.3_procedural-families`); Phase 1 exercises it through test writers.
- Code: `src/store/planes.{h,cpp}` (plane rows, versions, chunk codec, binding resolution), `src/store/plane_integrity.{h,cpp}` (plane rules, called by `src/store/integrity.*` on open and by `inspect --verify`); tests in `tests/store/`.

## Dependencies
- Parent: `phase1.8_project-store` (integration and acceptance of P1-STORE).
- Prerequisite: `phase1.3_document-model` (the DAG input of P1-STORE: manifest types with `planes{channel → plane_id}` on paint layers and paint effects).
- Prerequisite (sibling): `phase1.4_store-container-operations` (SQLite container, `blob` table, the mutation commit transaction).
- Followed by the siblings `phase1.6_store-save-retention` (compaction and revert preserve plane bindings) and `phase1.7_store-inspect-census` (`inspect --verify`, `export-bundle` `planes/`, bytes per raster-plane edit).

## Acceptance
- The `09-project-file-format.md` §7 items owned by this child pass: two paint layers with separate planes on the same channel and tile are saved, reopened, edited and recovered, and neither aliases nor flattens the other; a raster-plane edit writes only the changed chunks; manifests and pixels are identical after recovery from an interrupted plane commit and after a corrupted chunk blob is detected.
- Reads of any retained revision return exactly the pixels bound by that revision's manifest.
- Every integrity rule of 09 §1 for planes is checked on open and reported with the affected plane and node.

## Impact
- Affected specs: `project-store` (raster planes, chunk versions, plane integrity)
- Affected code: `src/store/planes.*`, `src/store/plane_integrity.*`, `tests/store/`
- Breaking change: NO
- User benefit: paint and snapshot content survives save, reopen and edits losslessly, with storage cost proportional to what changed
