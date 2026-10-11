## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Children
- [x] 2.1 Child accepted: phase0.6_render-reference-procedure (every "not confirmed" row answered for the fixed pipeline of decision 038; capture procedure `iray-capture/1` qualified)
- [x] 2.2 Child accepted: phase0.7_render-reference-captures (references admitted under the fixed pipeline, decision 046; Iray noise terms (a) and (b); fixture content proposed)
- [x] 2.3 Child accepted: phase0.8_render-reference-fits (lobe fits, the prototype's noise term (c), noise-floor report, GPU probes; decisions 050-052)

## 3. Integration checks
- [x] 3.1 Every admitted reference names the qualified procedure version, its settings sheet hash and every `uncontrolled` setting
- [x] 3.2 The noise-floor report covers every analytic fixture with an admitted reference
- [x] 3.3 The analytic fixture values are presented to the owner for ratification as a proposal (recorded in the render report and the gate record of P3-PATHTRACER entry, decision 033); ratification itself is not required to close this task
- [x] 3.4 Decision 052's capture request (18 references, procedure `iray-capture/1`, S = 256, no k*S) recorded and analysed; decision 052 amended with the verdict on the face-confined run-to-run hypothesis (decision 062)
- [x] 3.5 Reproducibility probe (decision 033): one trivial Iray scene captured repeatedly, with pixel equality, per-setting observability and the measured variance published (decision 062)

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-FEAS-RENDER, entry gate of P3-PATHTRACER, decision 033): procedure qualified; references admitted; noise floor measured; fixture values proposed to the owner for ratification; reproducibility probe published; gate record written

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Notes
- Scope change 2026-10-11 (decisions 033, 038, 046, 050): this parent no longer joins G0 and is the sole entry gate of P3-PATHTRACER; its acceptance adds the reproducibility probe (item 3.5); the children were re-scoped to the fixed Assets3D render pipeline. Items 2.1-2.3, 3.3 and 4.1 were reworded to that scope, none deleted; items 3.4 and 3.5 were added for decision 052's capture request and decision 033's probe.
- Evidence 2026-10-11 (Painter `12.1.5+js-api.1.1.20`, Assets3D Painter lock held by this task and released): gate record `parity/reports/phase0/gate-p3-pathtracer-entry.md`; capture request and reproducibility probe in `parity/reports/phase0/iray-noise-floor.md` §9 (decision 062); decision 052 amended.
- Item 3.2 closed 2026-10-11 (decision 068): the template-default material of an OCIO project read back in one Painter session (`phase0/template-default-material/ocio-sphere`, r1 = r2, private record `f6ac6f70...`; `iray-references.md` §5.1), then `python -m tools.parity.render_fits qualification` measured the sphere's (c) (`iray-noise-floor.md` §3).
- Open (decisions 063, 068): item 4.1 waits only for the owner's signature of `parity/reports/phase0/gate-p3-pathtracer-entry.md` (evidence complete, clause by clause). The task is archived after the signature.
