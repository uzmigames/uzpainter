## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.6_render-reference-procedure

## 2. Implementation
- [x] 2.1 Author the fixture meshes (sphere, plane, bevelled cube) and constant-parameter materials on the default open-pbr shader (decision 042): base colour and metalness x roughness sweeps, the standard's `neutral_control` pair in place of the white furnace, spatially varying normal and height perturbations, emission and opacity as negative controls (decision 043)
- [x] 2.2 Use the fixed pipeline's environments with SHA-256 and provenance: Studio White Soft by resource URL (v2) and the standard's `ref_match` HDRI as a session resource named by SHA-256 (rotations 0 and 180); no other environment (decisions 038, 043)
- [x] 2.3 Write one settings sheet per fixture with the fixed pipeline's values (v2 or `ref_match`; OCIO, Default - sRGB, not Legacy `Linear`) and k = 4 from procedure `iray-capture/1` (decisions 038, 039, 043)
- [x] 2.4 Record each fixture twice in separate Painter sessions and once at k·S samples with the qualified procedure; admit the records to the store
- [x] 2.5 Write one golden-public manifest per fixture under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase0/iray-references/` (fixture, settings sheet, procedure version, `uncontrolled` settings, hashes of every private record) and the aggregate table in the report; the guard allows no multi-golden JSON (decision 043)
- [x] 2.6 Compute per fixture and region (interior, edge band, background) the run-to-run difference (a) and Iray's Monte-Carlo error at S (b) on the 16-bit display-referred renders; write `parity/reports/phase0/iray-references.md` (numbers only)
- [x] 2.7 Record the fixture content (meshes, material values, camera, `ref_match` subset) as a proposal to the owner for ratification in the report; the render settings are the owner's fixed pipeline (decision 038)

## 3. Tests
- [x] 3.1 Admission check: every reference has two session-separated recordings plus one k·S recording, each passing current-frame verification
- [x] 3.2 `uzpainter parity verify` (`python -m tools.parity.store verify`) passes for the `iray-references` manifests and the qualification sphere on the owner's machine
- [x] 3.3 Guard run: no reference image, readback or panel evidence is in the repository

## 4. Acceptance
- [x] 4.1 Acceptance (P0-FEAS-RENDER, references): references admitted under the fixed pipeline; Iray noise terms (a) and (b) measured; fixture content proposed to the owner for ratification

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Notes
- Scope change 2026-10-11 (decision 043, after decision 038): the analytic profile's Legacy colour management, extra environments, white furnace and aggregate JSON are replaced by the fixed pipeline; items 2.1-2.3, 2.5-2.7, 3.2 and 4.1 were reworded to that scope.
