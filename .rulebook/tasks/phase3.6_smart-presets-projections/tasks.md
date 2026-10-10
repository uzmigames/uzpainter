## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_procedural-families

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.4_smart-projections accepted
- [ ] 2.2 phase3.4_smart-mask-recipes accepted
- [ ] 2.3 phase3.5_smart-material-recipes accepted

## 3. Integration
- [ ] 3.1 Run the full Tier 0 projection suite and the Tier 2a suite of every shipped smart-mask and smart-material recipe on the owner's machine from one build
- [ ] 3.2 Verify every shipped recipe carries an independently authored provenance record covering each family and resource it uses, and that no observed Adobe structure is present in the repository or the distribution
- [ ] 3.3 Publish the P3-SMART report under `parity/reports/phase3/` (numbers and hashes only; build hash; exceptions relied on listed)
- [ ] 3.4 Regenerate the capability manifest: projections, symmetry and shipped recipes `supported`; `Warp`, `UVSetToUVSet` and Painter smart presets without a private structure listed as gaps

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 0 projection goldens exact; every shipped recipe passes Tier 2a; every non-zero difference an owner-approved exception; all children accepted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
