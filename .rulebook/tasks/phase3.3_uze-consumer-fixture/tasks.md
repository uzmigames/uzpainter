## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.2_uze-uzmat-preset`; private oracle store from `phase0.5_private-oracle-store` available on the owner's machine for local runs (decision 028)

## 2. Implementation
- [ ] 2.1 Fixture manifest `parity/manifests/consumers/uzengine/wand-v1.json`: executable identity and hash, test scene, qualified mesh route, pinned generation, expected bindings
- [ ] 2.2 Runner, run locally on the owner's machine (decision 028), invoking UzEngine's own executable as an external process through the generation-pinning delivery adapter
- [ ] 2.3 Load-and-render check reading the engine's load report and verifying each slot binding of the UzEngine preset table
- [ ] 2.4 Normal convention check against the convention settled by `phase0.9_normal-convention-fixture`
- [ ] 2.5 Lossy-derivative comparison of decoded `.uztexture` levels against canonical maps (`14-parity-testing.md` §4)
- [ ] 2.6 Gap report in `parity/reports/phase3/` (SpecularWeight, SM5 opacity route, rejected bindings, mesh route used)
- [ ] 2.7 Explicit failure when the UzEngine executable or its scene is unavailable; never reported as a pass

## 3. Tests
- [ ] 3.1 Consumer-matrix row 9 (`08-export.md` §5.1) on wand v1: loads, renders, bindings as expected
- [ ] 3.2 Defect detection: a `.uzmat` with the ORM texture on the albedo pin is rejected by the binding check
- [ ] 3.3 Defect detection: an albedo `.uztexture` written with linear instead of sRGB metadata is flagged
- [ ] 3.4 Missing-executable case fails the fixture with an explicit unavailable status
- [ ] 3.5 Build check: no include path, library path or build step of UzPainter refers to a UzEngine checkout

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: row 9 passes on wand v1; lossy-derivative numbers and gap report published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
