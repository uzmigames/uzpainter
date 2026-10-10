## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.3_document-model, phase1.5_compositor-tile-dag, phase1.8_compositor-sources-projection

## 2. Implementation
- [ ] 2.1 Run the Tier 0 quantisation experiment against the private goldens and select the model that reproduces them exactly
- [ ] 2.2 Implement the selected quantisation points and precision rules in the kernel generator
- [ ] 2.3 Implement the profile registry: id `painter-12.1-<profile-id>` stamped into projects and goldens; evaluation dispatches on the project's profile
- [ ] 2.4 Publish `parity/semantics/quantisation-profile.json` (model, public source, residual)

## 3. Tests
- [ ] 3.1 Tier 0 quantisation goldens (three 1/3-opacity fills) exact for each channel format used by the templates
- [ ] 3.2 Tier 0 sRGB8 blend-space goldens exact
- [ ] 3.3 Profile pinning: a project stamped with profile A evaluates with A after a synthetic profile B is registered

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact on the self-hosted GPU runner (DX12); unit tests green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
