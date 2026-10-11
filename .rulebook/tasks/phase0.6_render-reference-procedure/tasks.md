## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [x] 2.1 Pin the colour LUT (none, colour profile off) and confirm the colour-management display transform of the fixed pipeline (OCIO, Default - sRGB; decision 038); record answers and private evidence
- [x] 2.2 Apply and read back the pinned Min/Max Sample, Max Time, Caustic Sampler, Firefly Filter and resolution override values of the fixed pipeline; every capture re-applies them, persistence is not relied on (decision 038)
- [x] 2.3 Probe a programmatic readiness check for convergence (Status, Iterations, Rendering time)
- [x] 2.4 Apply and read back the pinned Viewer/environment and display settings of the fixed pipeline, and pin the default-MDL material parameters to Painter's defaults (decision 038)
- [x] 2.5 Probe the denoiser, seed repeatability (repeated renders bit-identical or not) and height as bump or displacement under the fixed pipeline
- [x] 2.6 Probe Save Render under the fixed pipeline: output format, bit depth, whether the display transform is baked in, stale-frame behaviour; choose Save Render or the external 1:1 observation fallback (decision 039)
- [x] 2.7 Mark every setting that cannot be fixed or read as `uncontrolled`
- [x] 2.8 Define the settings sheet and operator form used by the recorder's Iray path
- [x] 2.9 Write the versioned qualified procedure (`07-preview-and-render-parity.md` §2.2 steps 1–7) and the answers in `parity/reports/phase0/iray-capture-procedure.md`; the JavaScript API is used only if the approved-source index admits its documentation, and the Assets3D render adapter's undocumented UI path is not used

## 3. Tests
- [x] 3.1 Qualification run: one analytic fixture captured end to end with the procedure; readiness gate refuses a capture before Status is Done and Iterations equals S
- [x] 3.2 Current-frame verification: a capture made before the last settings change is rejected; a silhouette mismatch with the recorded camera is rejected
- [x] 3.3 Every §2.1 row has an answer (`documented`, `confirmed by probe`, `uncontrolled` or `not required` for the fixed pipeline, decision 038) with an evidence hash

## 4. Acceptance
- [x] 4.1 Acceptance (P0-FEAS-RENDER, procedure): every "not confirmed" row answered with evidence; capture procedure qualified

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Notes
- Scope change 2026-10-11 (owner, decision 038): the procedure covers only the fixed Assets3D render pipeline; items 2.1, 2.2, 2.4, 2.5, 2.6 and 3.3 were reworded to that scope. Decision 039: Save Render is the pixel route; panels are operated by out-of-process UI automation (decision 029).
- Probe `20261011T094244968281Z-3051381f1470` (`probe.json` `78a155f58093c815507ca82f511e5adfcc2dadbd4e3cb573de18e325ea82bbb3`) on Painter 12.1.5: 13 rows settled, `random_seed` uncontrolled; both presets apply and verify. Qualification reference staged `s-2e84a21a97c3` (render `63f1394ada0966781e3252c1b935b4de26d7f5789d9e0db144c58d5adab74121`); live readiness refusals recorded. Details: `parity/reports/phase0/iray-capture-procedure.md`.
