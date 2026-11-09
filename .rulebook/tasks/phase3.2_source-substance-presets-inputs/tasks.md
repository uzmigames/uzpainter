## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam
  - Note: archived 2026-11-08 (2c7d178b).

## 2. Implementation
- [x] 2.1 Add recorder operations for `apply_preset`, `SourceSubstance.get_source/set_source/reset_source/remove_source`, `output_mapping` and `mask_output` through the documented API, coordinated with the recorder owners (never during a pinned recording batch)
  - Note: decision 412 item 2. `painter_probes.py` gains `set_material_source`, `apply_preset`, the image-input `get_source`/`set_source`/`reset_source`/`remove_source`, `output_mapping` and `mask_output` (choices by index in Painter's lists); no pinned batch was running. Transport tests: `tests/parity/recorder/test_source_substance_presets.py`.
- [x] 2.2 Author, record twice (same session, after save/reopen) and admit a Tier 0 probe on a starter asset chosen at record time that has presets, image inputs and several outputs
  - Note: decision 412 item 1. The survey (`tools/parity/recorder/substance_survey.py`) chose `inflate_shrinkwrap` (3 presets, 1 input, 2 outputs). `source-substance-presets-inputs` (93 steps, golden `64efeda399b2`) and `source-substance-input-anchor` (13 steps, golden `27c8faa1fdc7`) were recorded r1/r2 and admitted on 2026-11-08; inbox runs deleted.
- [ ] 2.3 Extend the snapshot capture domain to preset and image-input signatures and multiple outputs (needs a decision); exact-signature serving only
  - Note: the decision is 412 item 3 (output per snapshot, `preset` in the signature reached by Painter's own apply_preset, inputs by bitmap hash and colour space or working colour; anchors outside). Native implementation and the capture of this asset are not done.
- [ ] 2.4 Implement the moved methods in the native module and the facade from the recorded observations; unrecorded behaviour keeps refusing before mutation

## 3. Tests
- [ ] 3.1 Compared replay of both recordings, exact, with the decision 112 trace; only then promote the capability entries

## 4. Acceptance
- [ ] 4.1 Acceptance: the moved §7 methods equal both recordings and evaluate from project-private snapshots; no guessed behaviour

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
