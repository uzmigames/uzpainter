## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Children
- [ ] 2.1 Child accepted: phase0.6_tier0-semantics-goldens (`04-layer-stack-and-compositing.md` §9 goldens)
- [ ] 2.2 Child accepted: phase0.6_tier0-defaults-templates (baking defaults, template channel sets and formats)
- [ ] 2.3 Child accepted: phase0.6_tier0-api-probes (API readback and quirk probes)
- [ ] 2.4 Child accepted: phase0.7_tier0-stability-fits (oracle-stability report, first `parity/semantics/*.json` fits)

## 3. Integration checks
- [ ] 3.1 Every Tier 0 manifest in `parity/manifests/` lists two recordings per golden and `uzpainter parity verify` passes for all of them on the owner's machine
- [ ] 3.2 The guard passes on the repository: no Tier 0 blob, readback or capture is committed, only hashes

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-TIER0): each golden recorded ≥ 2×; stability classified; fits published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
