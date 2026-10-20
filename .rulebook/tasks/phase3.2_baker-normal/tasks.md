## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_baker-request-model, phase0.9_normal-convention-fixture

## 2. Implementation
- [ ] 2.1 Implement the `Normal` baker: high-poly normal at the hit, expressed in the texturing mesh's MikkTSpace frame under the project's `TangentSpace` mode
- [ ] 2.2 Encode per `NormalMapFormat` (OpenGL +Y / DirectX) with the convention settled by the normal-convention fixture
- [x] 2.3 Add normal diagnostics to the comparison tool: angular max/mean, non-finite and unnormalised counts, low-Z texels reported without repair
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

## 6. Comparison diagnostic slice (2026-10-20)
- Item 2.3 only: `tools/parity/tier1/compare.py` retains the existing angular max/mean and non-finite/unnormalised counts and adds `normal.negative_z_count` for wholly finite candidate vectors with decoded Z < 0 over the whole map. Integer samples use n = 2c/max - 1; float samples remain unchanged. Zero and non-finite vectors do not count as negative Z. No repair is performed, and the new count is excluded from exception metrics.
- `parity/schema/comparison-report.json` accepts the nonnegative integer count while preserving historical reports without it. New normal reports always emit it. The architecture's comparison diagnostics and this task's existing spec document the contract.
- CPU validation: `tests/parity/tier1/test_tier1_compare.py`, `tests/parity/test_schemas.py` and `tests/parity/test_guard.py`: 216 passed in 57.82 s. New cases cover PNG 8/16 midpoint signs, float 16/32 zero/non-finite vectors, preserved samples and encoded bytes, unchanged equality outcomes, report field emission and schema compatibility. Ruff check/format and mypy passed for both changed Python files. JUnit evidence: `tmp/scratch/negative-z/results.xml`.
- No Painter session, GPU, native bake or private parity claim. Prerequisites, normal baker implementation, Tier 2b fixtures, parent acceptance and task-wide tails remain open.
