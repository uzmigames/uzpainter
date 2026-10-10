## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.7_render-reference-captures

## 2. Implementation
- [ ] 2.1 Feasibility prototype transport from `07-preview-and-render-parity.md` §3.1–§3.2 sources: path tracing with NEE and MIS, environment importance sampling, Russian roulette, Owen-scrambled Sobol with a fixed seed, fixed per-pixel accumulation order
- [ ] 2.2 Prototype layered BSDF from the MDL specification and OpenPBR lobes (§3.3), with a provenance note per formula
- [ ] 2.3 Camera, environment and display transform of the analytic profile (§3.4: Legacy `Linear` tone mapping, IEC 61966-2-1)
- [ ] 2.4 Fit lobe variants and constants black-box against the admitted references; write `parity/semantics/iray.json` with public source and residual per entry
- [ ] 2.5 Record the transport evidence: residual change for spectral vs RGB, caustic paths and maximum path depth
- [ ] 2.6 Measure UzPainter's error at S (term c) from several seeds against the prototype's own k·S render
- [ ] 2.7 Write `parity/reports/phase0/iray-noise-floor.md`: terms (a), (b), (c) per fixture and region, mean signed Δ with standard error, 2×/4×/8× downsampled statistics, FLIP diagnostic
- [ ] 2.8 Record DXR Tier 1.1 and Vulkan ray-query support of the owner's GPU in the report

## 3. Tests
- [ ] 3.1 White-furnace check: the prototype conserves energy on the white-furnace fixture within its own Monte-Carlo error
- [ ] 3.2 Defect detection: a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation each produce a mean signed Δ outside the measured noise floor
- [ ] 3.3 Repeatability: two prototype runs with the same build, adapter, seed and sample count produce identical bytes, or the difference is reported
- [ ] 3.4 Guard run: no reference pixels, crops or difference maps are in the repository

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-FEAS-RENDER, noise floor): noise floor measured; first clean-room lobe fits published with residuals; ray-tracing probes on the owner's GPU recorded

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
