# Proposal: phase1.2_docmodel-capability-manifest

## Why
UzPainter must never be silently a no-op: every Painter Python symbol and every UzPainter operation carries a status `supported`, `desktop-only-omitted` or `release-gap`, generated at build time and shipped as `capabilities.json` (ARC-03). Release gates and milestone names depend on this list (OWN-01; owner Q5: nothing is called a full replacement while a required gap is open). Requirements: OWN-01, ARC-03, CLR-03 (`docs/prd.md`). Implements the document part of D3 (decision 005) in `docs/architecture/03-project-model.md` and `docs/architecture/04-layer-stack-and-compositing.md` §1, the operation records of D1/ARC-02 (decision 003) in `docs/architecture/02-runtime-topology.md` §3 and `docs/architecture/09-project-file-format.md` §4, and the capability manifest of D2 (decision 004, amended by decision 019: brush strokes out of scope) in `docs/architecture/10-python-api.md` §3. Child of `phase1.3_document-model` (P1-DOCMODEL), whose DAG Outputs name the capability manifest generator.

## What Changes
- `tools/capabilities/painter-api-inventory.json`: the documented Painter symbol inventory, authored from Painter's public API documentation as admitted by the approved-source index (`docs/approved-sources.md`, P0-SOURCES); documented symbols only.
- `tools/capabilities/uzpainter-additions.json`: UzPainter-only operations and modules.
- `tools/capabilities/capabilities.schema.json` and the generator `tools/capabilities/generate_capabilities.py`, run as a `build.zig` step, emitting `capabilities.json` with one entry per qualified symbol and per operation context: `symbol`, `context`, `status`, `since`, `tier_evidence`, `notes`, `evidence`.
- Generation rules: `supported` requires a Tier 0 evidence reference; every `desktop-only-omitted` entry carries its per-symbol justification; the release gaps of `docs/architecture/10-python-api.md` §3 are present as `release-gap`; no brush-stroke symbol exists (owner Q5).

## Dependencies
- DAG input of the parent: `phase0.2_parity-contract` (Tier 0 evidence identifiers). The inventory's source admission comes from `phase0.1_approved-source-index` through P0-CONTRACT.
- Sibling prerequisite: `phase1.1_docmodel-types-manifest` (the `compat_profile` and version fields).
- Parent: `phase1.3_document-model`. Consumer: `phase1.22_pyapi-cli-capabilities` (populates statuses for the Phase 1 symbol set and prints the manifest).

## Acceptance
Part of the P1-DOCMODEL gate: the generator is deterministic and its output validates; the generation rules reject an unjustified status.

## Impact
- Affected specs: `document-model`
- Affected code: `tools/capabilities/`, `build.zig` (generation step), `tests/capabilities/`
- Breaking change: NO
- User benefit: Agents and gates read one machine-checked list of what is supported, omitted or still a gap.
