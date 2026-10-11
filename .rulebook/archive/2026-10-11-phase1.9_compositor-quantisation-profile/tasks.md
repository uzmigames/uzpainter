## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.3_document-model, phase1.5_compositor-tile-dag, phase1.8_compositor-sources-projection

## 2. Implementation
- [x] 2.1 Run the Tier 0 quantisation experiment against the private goldens and select the model that reproduces them exactly (isolated root, `painter-12.1-isolated-linear`: exact against r1 on every UNORM/sRGB8/16-bit float map; both goldens unstable: r1 the exact target under decision 032, r2 comparisons covered by register entries `EXC-001` and `EXC-002` of `parity/exceptions.json`; 32-bit float within 2^-24, a divergence tracked by `phase1.10_compositor-float32-residual`)
- [x] 2.2 Implement the selected quantisation points and precision rules in the kernel generator
- [x] 2.3 Implement the profile registry: id `painter-12.1-<profile-id>` stamped into projects and goldens; evaluation dispatches on the project's profile
- [x] 2.4 Publish `parity/semantics/quantisation-profile.json` (model, public source, residual)

## 3. Tests
- [x] 3.1 Tier 0 quantisation goldens (three 1/3-opacity fills) exact for each channel format used by the templates (against r1; `test_compositor_quantisation_profile.py`)
- [x] 3.2 Tier 0 sRGB8 blend-space goldens exact
- [x] 3.3 Profile pinning: a project stamped with profile A evaluates with A after a synthetic profile B is registered

## 4. Acceptance
- [x] 4.1 Tier 0 sets of this child exact in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence); unit tests green (`parity/reports/phase1/compositor-quantisation-profile.md`: exact against r1; r2 comparisons covered by `EXC-001` and `EXC-002`, decision 032)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
