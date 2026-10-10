## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Children
- [ ] 2.1 Child accepted: phase0.6_render-reference-procedure (every "not confirmed" row answered; capture procedure qualified)
- [ ] 2.2 Child accepted: phase0.7_render-reference-captures (references admitted; Iray noise terms; fixture values proposed)
- [ ] 2.3 Child accepted: phase0.8_render-reference-fits (lobe fits, UzPainter noise term, noise-floor report, GPU probes)

## 3. Integration checks
- [ ] 3.1 Every admitted reference names the qualified procedure version, its settings sheet hash and every `uncontrolled` setting
- [ ] 3.2 The noise-floor report covers every analytic fixture with an admitted reference
- [ ] 3.3 The analytic fixture values are presented to the owner for ratification as a proposal (recorded in the render report and the G0 record); ratification itself is not required to close this task

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-FEAS-RENDER): procedure qualified; references admitted; noise floor measured; fixture values proposed to the owner for ratification

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
