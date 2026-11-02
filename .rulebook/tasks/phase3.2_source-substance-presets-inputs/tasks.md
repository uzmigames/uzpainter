## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Add recorder operations for `apply_preset`, `SourceSubstance.get_source/set_source/reset_source/remove_source`, `output_mapping` and `mask_output` through the documented API, coordinated with the recorder owners (never during a pinned recording batch)
- [ ] 2.2 Author, record twice (same session, after save/reopen) and admit a Tier 0 probe on a starter asset chosen at record time that has presets, image inputs and several outputs
- [ ] 2.3 Extend the snapshot capture domain to preset and image-input signatures and multiple outputs (needs a decision); exact-signature serving only
- [ ] 2.4 Implement the moved methods in the native module and the facade from the recorded observations; unrecorded behaviour keeps refusing before mutation

## 3. Tests
- [ ] 3.1 Compared replay of both recordings, exact, with the decision 112 trace; only then promote the capability entries

## 4. Acceptance
- [ ] 4.1 Acceptance: the moved §7 methods equal both recordings and evaluate from project-private snapshots; no guessed behaviour

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
