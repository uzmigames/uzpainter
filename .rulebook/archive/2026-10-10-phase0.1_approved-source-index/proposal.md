# Proposal: phase0.1_approved-source-index

## Why
The clean-room policy (decision 002; `docs/licensing-and-clean-room.md` §1–§2) lets implementers use only public specifications and literature, public Adobe documentation, UzmiGames files and black-box observation. Historical analyses under `docs/analysis/` are restricted context until an itemised provenance audit clears an exact revision, and the record of the sanitisation pass is not a clearance. Today no index says which sources are approved, so no package can prove its provenance (PRD CLR-01, CLR-02, CLR-04, LIC-03; `docs/dag.md` P0-SOURCES, implements CLR and Astra finding F04 as named in `dag.md`). Owner Q2 (decision 018) added NVIDIA's MDL specification and the BSD-3 MDL SDK as allowed sources for the path tracer; `docs/architecture/07-preview-and-render-parity.md` §2.1 and §3.1 and `04-layer-stack-and-compositing.md` defer to this index for what may be read.

## What Changes
- `docs/approved-sources.md`, the approved-source index, with one entry per source: identifier (title/edition, URL or path), category, exact revision or hash where the source is a file, licence where code may enter the build, cleared scope (what it may be used for) and the reviewer.
  - Public specifications and papers: the list of `docs/licensing-and-clean-room.md` §2 and `07-…` §3.1 (OpenPBR, glTF 2.0 PBR appendix, IEC 61966-2-1, MikkTSpace, OCIO/OpenEXR, Kajiya 1986, Veach 1997, PBR 4th ed., Burley 2020, the BRDF papers), NVIDIA's MDL specification and the open-source MDL SDK (BSD-3-Clause), NVIDIA FLIP (`NVlabs/flip`).
  - Public Adobe documentation: `PAINTER\resources\python-doc\**\*.html` pages and the public help pages the architecture cites (*Iray Renderer*, *Iray Settings*, *Viewer and MDL Settings*, mesh-map settings, output templates); an explicit admitted/not-admitted entry for `PAINTER\resources\javascript-doc\` (`07-…` §2.1).
  - UzmiGames files: the Assets3D pipeline files the architecture cites (for example `A3D\Docs\Pipeline\Render\Render-Comparison-Standard.json`) and UzEngine sources (read-only; code enters only through `docs/architecture/13-engine-integration.md` §3), each with path and revision/hash.
  - Historical analyses: the exact revision hash of each `docs/analysis/` file cleared by an itemised provenance audit, its provenance and its cleared scope.
- Quarantine list in the same file: the off-limits sources of `docs/licensing-and-clean-room.md` §2 (shader library, shader docs embedding it, shipped MDL files, shipped `.py` sources, Adobe binary formats, Iray internals) and every historical analysis or revision not cleared.
- Citation audit of `docs/architecture/*.md` (and `docs/prd.md`, `docs/roadmap.md`, `docs/dag.md`): every cited source resolves to an approved entry; a citation of uncleared material is marked historical context or replaced.

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, archived).
- Successors: `phase0.2_parity-contract` (P0-CONTRACT) and gate `phase0.10_gate-g0` (G0).

## Acceptance
Index published; every architecture doc cites only approved sources (`docs/dag.md`, P0-SOURCES). Contributes to G0: "approved-source index published" (`docs/roadmap.md`).

## Impact
- Affected specs: clean-room
- Affected code: none (documentation and review record)
- Breaking change: NO
- User benefit: every later task cites an approved source; a reviewer can reject any change whose provenance is not in the index (CLR-02)
