## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.6_tier0-semantics-goldens

## 2. Implementation
- [x] 2.1 Recorder operator step for texture goldens: a settings sheet (`<panel>/<setting>`, `applied_by: operator_settings_sheet`), values set through Windows UI automation under decision 029, each verified (readback or panel screenshot) and recorded privately as `operator_recorded_settings` / `settings_panel_evidence`
- [x] 2.2 Height→normal goldens for each project-setting method over the authored height ramps (plane, sphere, bevelled cube) (Painter 12.1.5: the method is a per-texture-set Texture Set Settings value, `Sharp` default and `Smooth (Sobel)`; decision 047)
- [x] 2.3 Height→normal strength sweep (default plus at least three values) for each method (Painter 12.1.5 has no strength setting; a height-amplitude sweep per method stands in for it: opacity 1, 0.75, 0.5, 0.25, 0.1 and x2, x3, x4; decision 047)
- [x] 2.4 Group `PassThrough` goldens set through the UI, with and without masks on the group and on a child (the `group-masks` stack)
- [x] 2.5 Record every golden at least twice (same session; after save/reopen) at 16 bit or float; admit with `uzpainter parity record`; write the public manifests under `parity/manifests/tier0/semantics-ui/` (under the current envelope's manifest root, decision 037)

## 3. Tests
- [x] 3.1 Manifest test: every manifest validates against `golden-public.json`, lists two recordings and names each UI-set setting in `applied_settings`
- [x] 3.2 Store test: `uzpainter parity verify` passes for every manifest on the owner's machine
- [x] 3.3 Guard test: no screenshot, readback or export is committed; the guard passes on the repository
- [x] 3.4 Operator-step test (fake Painter): a UI value that differs from the sheet refuses the golden

## 4. Acceptance
- [x] 4.1 Both height→normal methods with a strength sweep and the group `PassThrough` mode with masks are recorded ≥ 2×, every UI-set value verified; blobs private, hashes public; verify passes

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-11, owner's machine, Painter `12.1.5+js-api.1.1.20`, Assets3D Painter lock held by this task, Legacy colour management)

Report: `parity/reports/phase0/tier0-semantics-ui.md`. Decisions 047 (the UI cases) and 048 (the Phase 1 recording requests made in the same Painter session).

- 2.1: `tools/parity/recorder/texture_sheet.py` (sheet names `Texture Set Settings/Height to normal method (<texture set>)` and `Layers/Blending mode (step <n>, <channel>)`; applied before r1, re-read after the reopen; layer modes also read by `Node.get_blending_mode`; any mismatch refuses the golden). The UI side is in `painter_ui.py` (tabbed docks, per-channel blending menu, a click guard against covering windows); the painter side is `show_texture_set`/`show_node` (documented `textureset.set_active_stack`). `record --operator ui|console`; the envelope corpus dispatch (refresh, study, canary) uses the UI operator.
- 2.2-2.4: `tools/parity/tier0_semantics/current.py`: `height-normal-{sharp,sobel}-{sphere,bevelled-cube}`, `height-normal-{sharp,sobel}-plane-strength` (4x2 grid, 8 amplitudes), `group-passthrough-masks` (4x2 grid: Passthrough with none/group/child/both masks, and the same four in Normal).
- 2.5: 7 goldens under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0/semantics-ui/`, each run holding r1 `same_session` and r2 `after_save_reopen`, admitted with `python -m tools.parity.store record --run`. r1 = r2 on every map, except `plane-strength` s1 (opacity 0.75) and s4 (opacity 0.1) for both methods: save-reopen-unstable under decision 032 (r1 the exact target). Explicit Sharp is byte-identical to the default-method goldens. The Normal controls of `group-passthrough-masks` are byte-identical to `group-masks` s1/s3.
- 3.1-3.4: `tests/parity/test_tier0_semantics_ui.py` (30 passed with the store) and `tests/parity/recorder/test_texture_sheet.py` (9 passed). `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0` exit 0; whole-store `verify` exit 0; `python -m tools.parity.guard` 0 blocked.
- 4.1: the three cases are recorded twice and verified; blobs are private and hashes public. The stability report was regenerated for the current envelope (69 goldens, 59 stable).
- 5.1: `parity/RECORDER.md` §3 (operator step), `parity/TIER0-SEMANTICS.md` §1 and §4, `docs/architecture/04-layer-stack-and-compositing.md` §6 (method per texture set, no strength in 12.1.5).
