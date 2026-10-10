# Proposal: phase2.3_realtime-preview

## Why
P2-PREVIEW in `docs/dag.md`, implementing the preview part of D6 (`docs/architecture/07-preview-and-render-parity.md` §1, §5, §6, §7, §8; decision 018, owner Q2). The realtime viewport is the human preview and a fast check, not a parity target; captures must be window-independent for headless operation, and `painter_iray` stays an explicit unavailable capability until `phase3.7_path-tracer` passes. Requirements: VIS-01…05, RES-03, QG-01, NFR-01, ARC-06 (`docs/prd.md`). This parent is the integration and acceptance task; the work is split into three children.

## What Changes
- `painter_viewport` forward pass, preview window and viewport regression goldens: child `phase2.1_preview-viewport-window`.
- `capture` for preview and diagnostic modes with receipts, `painter_iray` unavailable: child `phase2.2_preview-capture`.
- Display presets, environments and cameras: child `phase2.1_preview-display-presets`.
- Settling evidence for `07-…` §8 Phase 2 in `parity/reports/phase2/preview-settling.json` (pass/fail, timings, build hash; no oracle data).

## Dependencies
- DAG input: `phase1.25_pilot-wand` (P1-WAND).
- Children (all mandatory): `phase2.1_preview-viewport-window`, `phase2.2_preview-capture`, `phase2.1_preview-display-presets`.
- Consumer: `phase2.11_gate-g2` (G2).

## Acceptance
DAG gate: captures window-independent; preview never pauses evaluation. `painter_iray` is reported as an explicit unavailable capability. G2 does not include render parity. The parent closes only when all three children pass.

## Impact
- Affected specs: `preview`
- Affected code: viewport pass, preview window, capture, display state
- Breaking change: NO
- User benefit: owner preview and agent captures without any effect on evaluation
