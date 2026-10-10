## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_baker-request-model, phase0.9_normal-convention-fixture

## 2. Implementation
- [ ] 2.1 Implement the `Normal` baker: high-poly normal at the hit, expressed in the texturing mesh's MikkTSpace frame under the project's `TangentSpace` mode
- [ ] 2.2 Encode per `NormalMapFormat` (OpenGL +Y / DirectX) with the convention settled by the normal-convention fixture
- [ ] 2.3 Add normal diagnostics to the comparison tool: angular max/mean, non-finite and unnormalised counts, low-Z texels reported without repair
- [ ] 2.4 Author the `Normal` Tier 2b manifests under `parity/manifests/` (fixture descriptions, settings, golden hashes)

## 3. Tests
- [ ] 3.1 Re-run the hemisphere normal-convention fixture through the native baker and compare with the Painter bake
- [ ] 3.2 Tier 2b on plane, sphere and bevelled cube with highs: hit/coverage first, then maps, exact against private goldens
- [ ] 3.3 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.4 Repeat 3.2 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Normal` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
