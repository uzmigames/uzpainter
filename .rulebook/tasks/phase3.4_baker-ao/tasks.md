## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [ ] 2.1 Implement the `AO` baker: secondary rays over the hemisphere per `Spread`/`Distribution`/`NbSecondary`, distance window `MinDistance`/`MaxDistance`/`MaxDistanceRelativeScale`, `IgnoreBackfaceSecondary`, `FilterMethodSecondary`
- [ ] 2.2 Implement `Attenuation`, `GroundPlane` and `GroundOffset`
- [ ] 2.3 Report AO misses from hit evidence, separated from real holes, hidden surfaces and low AO, in the receipt
- [ ] 2.4 Implement the optional wider second pass applied only to missed texels, off by default, recorded in the receipt
- [ ] 2.5 Author the `AO` Tier 2b manifests under `parity/manifests/` with the Painter CPU backend recorded

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs (with and without `GroundPlane`): hit/coverage first, then maps, exact against private goldens
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes
- [ ] 3.4 Miss-evidence test on the buried-face fixture: misses counted apart from hidden and low-AO texels; the second pass changes only missed texels

## 4. Acceptance
- [ ] 4.1 Acceptance: `AO` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Recording requests (2026-11-02, decision 384)
- Item 3.1's Painter recordings are requested: `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/tier2b/bakes/ao-<scene>-{no-ground-plane,ground-plane}.json` (6). Not yet recorded; 3.2 and the buried-face golden of 3.4 have no request.
