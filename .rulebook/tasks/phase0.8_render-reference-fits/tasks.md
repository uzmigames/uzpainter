## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.7_render-reference-captures

## 2. Implementation
- [x] 2.1 Feasibility prototype transport from `07-preview-and-render-parity.md` §3.1–§3.2 sources, on the CPU and never shipped (`tools/parity/render_fits/`, decision 050): path tracing with NEE and MIS, environment importance sampling, Russian roulette, Owen-scrambled Sobol with a fixed seed, fixed per-pixel accumulation order; on the fixed pipeline's single convex meshes no light-carrying path has a second vertex, and the path loop is tested on a concave scene
- [x] 2.2 Prototype layered BSDF of the default `open-pbr` instance (decision 042) from the MDL specification, OpenPBR and the cited papers, with a provenance note per formula and the variants the fits choose between
- [x] 2.3 Camera of decision 046, the fixed pipeline's two environments by SHA-256, Painter's channel quantisation, the pixel filter and the display encoding of the fixed pipeline (OCIO Default - sRGB through Save Render 16-bit, fitted as binary16 then IEC 61966-2-1) in place of the analytic profile's Legacy `Linear` (decisions 038, 050)
- [x] 2.4 Fit lobe variants and constants black-box against the admitted references (chosen on one chessboard half of the pixels, residuals on the held-out half and on held-out goldens); write `parity/semantics/iray.json` with public source and residual per entry
- [x] 2.5 Record the transport evidence: the prototype's spectral-versus-RGB sensitivity on the saturated fixtures; caustic paths and maximum path depth, which the fixed pipeline's fixtures cannot discriminate, stated with the measured below-facet and depth differences
- [x] 2.6 Measure UzPainter's error at S (term c) on the feasibility prototype from two seeds against its own k·S render, with a measurement that phase3.6 reruns on `painter_iray`
- [x] 2.7 Write `parity/reports/phase0/iray-noise-floor.md`: terms (a), (b), (c) per fixture and region (per face where (a) is face-confined), mean signed Δ with standard error, the display-encoding bias, 2×/4×/8× downsampled statistics, FLIP diagnostic; the structure of the run-to-run difference and the capture request for its open part
- [x] 2.8 Record DXR Tier 1.1 and Vulkan ray-query support of the owner's GPU in the report (a fresh `selftest` run, cross-checked against `toolchain-probes.md`)

## 3. Tests
- [x] 3.1 White-furnace check: the prototype conserves energy on a white-furnace scene within its own Monte-Carlo error (an analytic test of UzPainter's own tracer, decision 046)
- [x] 3.2 Defect detection: a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation each produce a difference outside the measured noise floor (mean signed Δ beyond three combined standard errors, or the 8×-downsampled mean |Δ| beyond the fitted model's), or the miss is reported
- [x] 3.3 Repeatability: two prototype runs with the same build, CPU, seed and sample count produce identical bytes, or the difference is reported
- [x] 3.4 Guard run: no reference pixels, crops or difference maps are in the repository

## 4. Acceptance
- [x] 4.1 Acceptance (P0-FEAS-RENDER, noise floor): noise floor measured (Iray (a), (b); the prototype's (c)); first clean-room lobe fits published with residuals; ray-tracing probes on the owner's GPU recorded; the open items (cause of the face-confined run-to-run difference, the shipped tracer's (c)) listed with their owners (decision 050)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## Notes
- Scope change 2026-10-11 (decision 050, after decisions 038, 042 and 046): the analytic profile's Legacy colour management and its extra environments are replaced by the fixed pipeline; the prototype stays a CPU feasibility tool; term (c) is the prototype's, and phase3.6 item 2.3 measures the shipped tracer's. Items 2.1-2.8, 3.1-3.3 and 4.1 were reworded, none deleted.
