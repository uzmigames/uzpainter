## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.4_path-tracer-transport, phase3.5_path-tracer-materials

## 2. Implementation
- [ ] 2.1 Write production-profile settings sheets for Wand v1, Belt v5 and Tunic v10 (environment by hash, display configuration, cameras) and author their fixture descriptions in `parity/manifests/`
- [ ] 2.2 Capture the production-project Iray references per `07-…` §2.2 (two session-separated captures plus one at k·S), storing blobs and panel evidence privately and hashes publicly
- [ ] 2.3 Implement the noise measurement of `07-…` §4 step 1 for every analytic and production fixture
- [ ] 2.4 Implement the comparison in the reference's own encoding with per-region statistics, mean signed Δ and standard error, 2×/4×/8× downsampled statistics and pinned FLIP (diagnostic only)
- [ ] 2.5 Produce the DXR-versus-Vulkan cross-backend report on the same fixtures
- [ ] 2.6 Draft exception proposals (domain, metrics, noise-floor-derived bounds, `uncontrolled` settings relied on) with decision drafts for the owner
- [ ] 2.7 Implement the defect-detection test: the proposed bounds MUST fail a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation
- [ ] 2.8 Write the Tier 3 report under `parity/reports/phase3/` (numbers only), marking every comparison without an approved entry `blocked` and failing structural differences outright

## 3. Tests
- [ ] 3.1 Capture qualification: every production reference passes the convergence check and current-frame verification (silhouette matches the recorded camera)
- [ ] 3.2 Comparison-tool tests on authored synthetic images: exact statistics for a known offset and known noise; display-referred 8-bit path applies the same transform and quantisation as the reference
- [ ] 3.3 Defect-detection test run against every proposed bound
- [ ] 3.4 Guard test: no reference pixel, difference map or crop appears in the repository; the public report carries numbers only

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 3 report produced with noise floor, per-region statistics and cross-backend report; exception proposals submitted; unapproved comparisons reported `blocked`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
