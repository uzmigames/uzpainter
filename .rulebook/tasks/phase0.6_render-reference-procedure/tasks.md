## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [ ] 2.1 Probe the colour LUT application point and the colour-management display/view transform; record answers and private evidence
- [ ] 2.2 Probe persistence and readback of Min/Max Sample, Max Time, Caustic Sampler, Firefly Filter and the resolution override
- [ ] 2.3 Probe a programmatic readiness check for convergence (Status, Iterations, Rendering time)
- [ ] 2.4 Probe the Viewer and MDL Settings, the display settings that change the Iray image, and the default-MDL material parameters
- [ ] 2.5 Probe the denoiser, seed repeatability (repeated renders bit-identical or not) and height as bump or displacement
- [ ] 2.6 Probe Save Render: output format, bit depth, whether the display transform is baked in, stale-frame behaviour; choose Save Render or the external 1:1 observation fallback
- [ ] 2.7 Mark every setting that cannot be fixed or read as `uncontrolled`
- [ ] 2.8 Define the settings sheet and operator form used by the recorder's Iray path
- [ ] 2.9 Write the versioned qualified procedure (`07-preview-and-render-parity.md` §2.2 steps 1–7) and the answers in `parity/reports/phase0/iray-capture-procedure.md`; the JavaScript API is used only if the approved-source index admits its documentation, and the Assets3D render adapter's undocumented UI path is not used

## 3. Tests
- [ ] 3.1 Qualification run: one analytic fixture captured end to end with the procedure; readiness gate refuses a capture before Status is Done and Iterations equals S
- [ ] 3.2 Current-frame verification: a capture made before the last settings change is rejected; a silhouette mismatch with the recorded camera is rejected
- [ ] 3.3 Every §2.1 row has an answer (`documented`, `confirmed by probe` or `uncontrolled`) with an evidence hash

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-FEAS-RENDER, procedure): every "not confirmed" row answered with evidence; capture procedure qualified

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
