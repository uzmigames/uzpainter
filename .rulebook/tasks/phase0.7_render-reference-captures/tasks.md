## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.6_render-reference-procedure

## 2. Implementation
- [ ] 2.1 Author the analytic fixture meshes (sphere, plane, bevelled cube) and constant-parameter materials: base colour, metallic and roughness sweeps, white furnace, single-channel perturbations (normal, height, emissive, opacity)
- [ ] 2.2 Author or select the environments (constant colour, single bright patch, Poly Haven CC0 HDRI) with SHA-256 and provenance
- [ ] 2.3 Write one settings sheet per fixture with the proposed `07-preview-and-render-parity.md` §2.3 profile values and fix k for the k·S reference
- [ ] 2.4 Record each fixture twice in separate Painter sessions and once at k·S samples with the qualified procedure; admit the records to the store
- [ ] 2.5 Write `parity/manifests/phase0/iray-references.json`: fixtures, settings sheets, procedure version, `uncontrolled` settings, hashes of every private record
- [ ] 2.6 Compute per fixture and material region the run-to-run difference (a) and Iray's Monte-Carlo error at S (b); write `parity/reports/phase0/iray-references.md` (numbers only)
- [ ] 2.7 Record the analytic fixture values as a proposal to the owner for ratification in the report

## 3. Tests
- [ ] 3.1 Admission check: every reference has two session-separated recordings plus one k·S recording, each passing current-frame verification
- [ ] 3.2 `uzpainter parity verify` passes for `iray-references.json` on the owner's machine
- [ ] 3.3 Guard run: no reference image, readback or panel evidence is in the repository

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-FEAS-RENDER, references): references admitted; Iray noise terms (a) and (b) measured; fixture values proposed to the owner for ratification

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
