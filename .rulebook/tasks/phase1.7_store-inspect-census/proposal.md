# Proposal: phase1.7_store-inspect-census

## Why
Tools and agents need to read a project without opening it (no GPU, no lock), humans and archive tools need a file bundle, and the owner's Q11 budget (10 % of the matched `.spp`) can only be ratified with a census produced by the store's own instrumentation. Requirements: OWN-07, NFR-04, SAV-01, INT-22 (`docs/prd.md`). Implements D8 (decision 010) and owner answer Q11 (decision 024: self-contained portable file, 10 % candidate budget measured by the census, retention of current and previous checkpoints plus the last 50 mutation revisions) in `docs/architecture/09-project-file-format.md`, the durability contract of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §3, §5 and §6 (operation record committed atomically with its revision; autosave by commit), and owner answer Q6 (decision 020: no `.spp` reader). Child of `phase1.8_project-store` (P1-STORE), covering `docs/architecture/09-project-file-format.md` §3 and §6.

## What Changes
- `src/store/inspect.{h,cpp}` and the CLI verb `uzpainter inspect <file.uzp> [--revision N] [--verify]`: prints format and app versions, profiles, project settings, texture sets/channels, layer tree with bindings, resource table (name, hash, bytes, usage), mesh maps with provenance, checkpoints, sizes (file, blobs, cache, external dependencies, listed separately) without a GPU and without taking the project lock; `--verify` runs every integrity rule of `09-…` §1, calling the plane integrity checker of `phase1.5_store-planes` for plane bindings and chunks. The recipe digest field is reported as unavailable until `phase2.2_recipe-and-diagnostics` adds `dump_recipe` (never silently omitted).
- `src/store/bundle.{h,cpp}` and `uzpainter export-bundle <file.uzp> <dir|zip>`: writes `manifest.json`, `res/<sha256>.<ext>`, `meshmaps/`, `planes/` (PNG/EXR at native precision); `project.open` accepts a bundle directory (re-import).
- `src/store/census.{h,cpp}`: instrumentation of first save, repeated one-parameter edits, raster-plane edit, reopen time, bytes written per edit, compaction time, retained-history size, project bytes vs external dependency bytes; report `parity/reports/phase1/store-census.json` (numbers only) on the dependency content of tunic v10, hat v8 and the body versions, with the ratio to the matched compacted `.spp` stated wherever that file size is available; the full-content census is completed by `phase4.1_coverage-body-v6b`.

## Dependencies
- DAG input of the parent: `phase1.3_document-model`.
- Sibling prerequisites: `phase1.4_store-container-operations`, `phase1.5_store-planes`, `phase1.6_store-save-retention` (compaction and retention are measured).
- Parent: `phase1.8_project-store`. Later: `phase2.2_recipe-and-diagnostics` adds the recipe digest to `inspect`; `phase4.1_coverage-body-v6b` completes the size census.

## Acceptance
The `docs/architecture/09-project-file-format.md` §7 instrumentation items owned by this child run on tunic, hat and body content and produce the census numbers; `inspect` and `export-bundle` pass their tests.

## Impact
- Affected specs: `project-store`
- Affected code: `src/store/inspect.*`, `src/store/bundle.*`, `src/store/census.*`, CLI verbs `inspect` and `export-bundle`, `tests/store/`, `parity/reports/phase1/store-census.json`
- Breaking change: NO
- User benefit: Projects can be inspected and archived without a GPU, and the owner gets measured numbers to ratify the size budget.
