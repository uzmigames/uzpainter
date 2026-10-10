## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [ ] 2.1 Implement the `Thickness` baker: inward secondary rays per `NbSecondary`, distances, `Spread`, `Distribution`
- [ ] 2.2 Implement `MaximizeRange`; record the effective range in the binding and the receipt
- [ ] 2.3 Author the `Thickness` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs (with and without `MaximizeRange`): hit/coverage first, then maps, exact
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Thickness` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
