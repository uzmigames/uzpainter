## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.6_tier0-semantics-goldens

## 2. Implementation
- [ ] 2.1 Recorder operator step for texture goldens: a settings sheet (`<panel>/<setting>`, `applied_by: operator_settings_sheet`), values set through Windows UI automation under decision 029, each verified (readback or panel screenshot) and recorded privately as `operator_recorded_settings` / `settings_panel_evidence`
- [ ] 2.2 Height→normal goldens for each project-setting method over the authored height ramps (plane, sphere, bevelled cube)
- [ ] 2.3 Height→normal strength sweep (default plus at least three values) for each method
- [ ] 2.4 Group `PassThrough` goldens set through the UI, with and without masks on the group and on a child (the `group-masks` stack)
- [ ] 2.5 Record every golden at least twice (same session; after save/reopen) at 16 bit or float; admit with `uzpainter parity record`; write the public manifests under `parity/manifests/tier0/semantics-ui/`

## 3. Tests
- [ ] 3.1 Manifest test: every manifest validates against `golden-public.json`, lists two recordings and names each UI-set setting in `applied_settings`
- [ ] 3.2 Store test: `uzpainter parity verify` passes for every manifest on the owner's machine
- [ ] 3.3 Guard test: no screenshot, readback or export is committed; the guard passes on the repository
- [ ] 3.4 Operator-step test (fake Painter): a UI value that differs from the sheet refuses the golden

## 4. Acceptance
- [ ] 4.1 Both height→normal methods with a strength sweep and the group `PassThrough` mode with masks are recorded ≥ 2×, every UI-set value verified; blobs private, hashes public; verify passes

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
