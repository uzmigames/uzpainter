## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.10_pilot-tunic-recovery

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.1_baker-request-model accepted
- [ ] 2.2 phase3.2_baker-normal accepted
- [ ] 2.3 phase3.3_baker-evidence-publication accepted
- [ ] 2.4 phase3.4_baker-ao accepted
- [ ] 2.5 phase3.4_baker-world-space-normal accepted
- [ ] 2.6 phase3.4_baker-id accepted
- [ ] 2.7 phase3.4_baker-curvature accepted
- [ ] 2.8 phase3.4_baker-position accepted
- [ ] 2.9 phase3.4_baker-thickness accepted
- [ ] 2.10 phase3.4_baker-height accepted
- [ ] 2.11 phase3.4_baker-bent-normals accepted
- [ ] 2.12 phase3.4_baker-opacity accepted

## 3. Integration
- [ ] 3.1 Run the full Tier 2b suite for all ten usages on the owner's machine (analytic fixtures plane, sphere, bevelled cube with highs; wand and hat low/high/cage pairs), repeated across thread counts and ISAs, hit/coverage evidence compared first, then maps
- [ ] 3.2 Publish the Tier 2b report under `parity/reports/phase3/` (numbers and hashes only; Painter CPU backend and UzPainter build hash recorded; exceptions relied on listed)
- [ ] 3.3 Run the MCP native-bake cancellation fixture: `bake_start` on a synthetic project, `job_cancel` while running, terminal state `cancelled`, receipt states stopped before or after commit, no partial authoritative bake bound
- [ ] 3.4 Regenerate the capability manifest with each baker usage `supported` or listed as a release gap (including the `Automatic` cage mode until established)

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 2b published; MCP cancellation during a native bake passes; every mandatory child accepted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
