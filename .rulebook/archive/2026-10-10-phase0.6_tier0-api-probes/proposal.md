# Proposal: phase0.6_tier0-api-probes

## Why
The `substance_painter` facade must reproduce Painter's observable behaviour that changes output, and a symbol may be marked `supported` in the capability manifest only with Tier 0 evidence: set→get readback through a freshly resolved handle, persistence after save/reopen, and a golden comparison for output-affecting symbols (`docs/architecture/10-python-api.md` §0, §3–§4; PRD ARC-03, ARC-13, LAY-01, QG-03, CLR-03). Several rules are undocumented and can be learned only by observing Painter through its documented API (decision 002): the active-channel reset, mask-stack `None` requirements, `EditionContextException` on `set_source(None, …)` for multichannel fills, insertion-position errors and event order (`14-parity-testing.md` §3 Tier 0 row). Child of `phase0.8_tier0-goldens` (`docs/dag.md` P0-TIER0, implements D9 and D13).

## What Changes
- UzmiGames-written probe instruction sequences (public, in `parity/manifests/phase0/tier0-api-probes.json`) and their private readback goldens, recorded twice (same session; after save/reopen) through the recorder:
  - set→get readback through a freshly resolved handle and after save/reopen, for the layer, mask, effect, texture-set and project properties the Phase 1 facade subset uses;
  - mask-stack contexts: channel and source mode `None` rules (ValueError otherwise);
  - `active_channels` assigned after `set_source` resetting the fill's sources to the channel default, with the exported output;
  - `set_source(None, …)` on a multichannel fill raising `EditionContextException`;
  - `insert_*` position rules and the errors they raise;
  - event order of the lifecycle (`ProjectOpened`/`ProjectCreated` → `ProjectEditionEntered`; `ProjectAboutToSave` → `ProjectSaved`; `ProjectAboutToClose` → `ProjectClosed`) and `is_busy()`/`is_in_edition_state()` transitions.
- Probe ids usable as `tier_evidence` references in the capability manifest (for example `T0-api-probes/mask-blend.json`, 10 §3).
- Blobs in the private store; hashes in the public manifest.

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Parent: `phase0.8_tier0-goldens` (P0-TIER0). Sibling that depends on this task: `phase0.7_tier0-stability-fits`.

## Acceptance
Each API-probe golden recorded ≥ 2× and admitted (blobs private, hashes public) (`docs/dag.md`, P0-TIER0).

## Impact
- Affected specs: tier0
- Affected code: probe sequences under `parity/manifests/phase0/`; private store contents
- Breaking change: NO
- User benefit: the facade's quirks and readback rules are reproduced from evidence, and the capability manifest can cite it
