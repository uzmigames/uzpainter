## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_preview-display-presets
- [ ] 1.3 Child accepted: phase2.1_preview-viewport-window
- [ ] 1.4 Child accepted: phase2.2_preview-capture

## 2. Implementation
- [ ] 2.1 Integration scenario on the wand v1 project: worker with an attached preview window running evaluation, export and captures in all Phase 2 modes
- [ ] 2.2 Settling report writer for `parity/reports/phase2/preview-settling.json`

## 3. Tests
- [ ] 3.1 Captures in a local run on the owner's machine (decision 028) without any window or desktop focus, in `painter_viewport`, `base_color`, `channel:<name>` and `mask:<uid>` modes
- [ ] 3.2 Preview window open, minimised and stalled while the wand v1 export runs: export bytes and timing unaffected by the preview, no evaluation wait on the preview thread
- [ ] 3.3 `painter_iray` reported as an explicit unavailable capability in `uzpainter://capabilities` and by `capture`

## 4. Acceptance
- [ ] 4.1 DAG gate met: captures window-independent and preview never pauses evaluation; report written to `parity/reports/phase2/preview-settling.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (child results)
- phase2.1_preview-viewport-window (2026-10-12, owner machine, RTX 4090 driver 32.0.16.1714): `tests/preview` all green (display, environment, hand-over, unsupported configuration, regression goldens of sphere/plane/bevelled cube, stalled preview, window lifecycle, standalone `--preview`); details in that task's notes.
