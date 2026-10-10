# Proposal: phase0.6_tier0-defaults-templates

## Why
UzPainter's bakers mirror Painter's dynamic `Property` model and must start from Painter's effective defaults, and every project template fixes a channel set and a storage format per channel; neither is fully stated in public documentation. `docs/architecture/06-baking.md` §2 requires the defaults to be captured in Phase 0 through the documented API (`Property.value()` for every key of `BakingParameters.common()` and `baker(usage)` on a fresh Painter 12.1.0 project), with enum integers taken from `enum_values()` and never guessed; `03-project-model.md` §2 requires the default channel sets and formats per template to be observed in Tier 0. Both captures are private oracle records (PRD CLR-05; `docs/licensing-and-clean-room.md` §1.6): the default table and template JSON UzPainter later ships are authored by UzmiGames and only checked against these captures. PRD BAK-02, BAK-03, PRJ-05, PRJ-06, ARC-13, CLR-05. Child of `phase0.8_tier0-goldens` (implements D5, D3, D13).

## What Changes
- Recorder instruction sequences (documented API only, run by `phase0.3_painter-oracle-recorder` on the owner's Painter 12.1.0):
  - **Baking defaults:** on a fresh project, for `BakingParameters.common()` and `baker(usage)` of each of the ten `MeshMapUsage` bakers (`Normal`, `WorldSpaceNormal`, `ID`, `AO`, `Curvature`, `Position`, `Thickness`, `Height`, `BentNormals`, `Opacity`), every key with `Property.value()`, `name`, `short_name`, `label`, `widget_type`, `enum_values`, `enum_value` and `properties()` (ranges and nested properties).
  - **Templates:** for each project template shipped with Painter 12.1.0 and selectable through the documented project-creation API, a project created on a UzmiGames synthetic mesh, and per texture-set stack the channel set and each channel's `ChannelFormat` read back through the documented `textureset` API, with the project settings applied.
- Each capture recorded at least twice (same session; after save/reopen; the defaults capture also on a second fresh project), shaped by `parity/schema/golden-private.json`, admitted into the private store by `uzpainter parity record`.
- Public manifest `parity/manifests/phase0/tier0-defaults-templates.json`: the instruction sequences, the template identifiers used, software identities (Painter build id) and the SHA-256 of each private capture — no captured value.
- Not in this task: the UzmiGames-authored `assets/defaults/baking.json` and template JSON (authored later from documented semantics, each entry with its provenance, and checked against these captures on the self-hosted runner).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Parent: `phase0.8_tier0-goldens` (P0-TIER0) closes only when this child passes.
- Successors: `phase0.7_tier0-stability-fits` (stability of the captures), `phase1.3_document-model` (template channel sets), `phase3.1_baker-request-model` (P3-BAKER parameter model and default table).

## Acceptance
The baking defaults of all ten bakers and the channel sets and formats of every shipped template are captured through the documented API, each recorded at least twice, stored privately with only hashes and instruction sequences in the public manifest; `uzpainter parity verify` passes. Contributes to the P0-TIER0 gate "each golden recorded ≥ 2×" (`docs/dag.md`) and G0 "Tier 0 goldens admitted (blobs private, hashes public)" (`docs/roadmap.md`).

## Impact
- Affected specs: tier0
- Affected code: recorder instruction sequences, `parity/manifests/phase0/tier0-defaults-templates.json`; private store contents
- Breaking change: NO
- User benefit: bakers and templates start from Painter's observed defaults instead of guesses, while no captured Adobe data is published
