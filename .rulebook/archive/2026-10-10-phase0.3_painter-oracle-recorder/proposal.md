# Proposal: phase0.3_painter-oracle-recorder

## Why
Black-box observation of Painter is the only permitted way to learn undocumented semantics (decision 002), and every golden must be recorded through Painter's documented Python API for state and a qualified, permitted capture procedure for pixels — never through the community MCP bridge or a private interface (PRD ARC-09, CLR-02, CLR-03, CLR-05, G-04; decisions 017, 018, 020, 022; `docs/architecture/14-parity-testing.md` §2; `docs/architecture/07-preview-and-render-parity.md` §2.2; `docs/dag.md` P0-RECORDER, implements D13 and CLR). Tier 0, the procedural and render feasibility studies, the normal fixture and every later migration (Q6: rebuild through the documented API, proven by output equality) depend on this recorder.

## What Changes
- `tools/parity/recorder/*.py`, UzmiGames recorder scripts written from `python-doc` only, driving Painter 12.1.0 started with `--enable-remote-scripting` on the owner's machine:
  - state through the documented API (project create/open with recorded settings, layer stack operations, `Property` readback, effective defaults);
  - pixels through the permitted capture procedure: texture exports via the documented `export_project_textures` at 16 bit (or float), and the Iray path of `07-…` §2.2 (apply and read back the documented settings, switch to Iray mode, settings sheet, convergence check, Save Render), with readiness and current-frame verification;
  - an operator-recorded form for render settings the API does not expose (Iray settings, Viewer and MDL settings), stored with an image of each settings panel as private evidence;
  - every golden recorded at least twice (same session; after save/reopen), records shaped by `parity/schema/golden-private.json` and their hashes written into a public manifest shaped by `parity/schema/golden-public.json`.
- Records are written to a private output directory outside the repository; admission into the content-addressed store is done by `uzpainter parity record` (`phase0.5_private-oracle-store`).
- One Tier 0 sample (authored fixture, instruction sequence, export, readback) recorded end to end as the acceptance run.

## Dependencies
- Prerequisites: `phase0.2_parity-contract` (P0-CONTRACT).
- Successors: `phase0.8_tier0-goldens` (P0-TIER0), `phase0.6_procedural-feasibility` (P0-FEAS-PROC), `phase0.9_render-reference-capture` (P0-FEAS-RENDER), `phase0.9_normal-convention-fixture` (P0-NORMAL).

## Acceptance
A Tier 0 sample recorded end to end; no bridge code path; no private interface (`docs/dag.md`, P0-RECORDER). The Iray capture procedure itself is qualified by `phase0.9_render-reference-capture` before any render golden is admitted (14 §2).

## Impact
- Affected specs: oracle-recorder
- Affected code: `tools/parity/recorder/` (Python scripts run inside Painter on the owner's machine) and its tests
- Breaking change: NO
- User benefit: every Painter observation is reproducible, documented-API-only and private by construction
