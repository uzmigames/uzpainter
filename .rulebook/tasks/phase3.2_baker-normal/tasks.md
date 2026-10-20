## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_baker-request-model, phase0.9_normal-convention-fixture

## 2. Implementation
- [ ] 2.1 Implement the `Normal` baker: high-poly normal at the hit, expressed in the texturing mesh's MikkTSpace frame under the project's `TangentSpace` mode
- [x] 2.2 Encode per `NormalMapFormat` (OpenGL +Y / DirectX) with the convention settled by the normal-convention fixture - native RGB16 encoding and validation in section 7
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

## 7. Native Normal calculation and encoding (2026-10-20)
- Item 2.2: the native Embree baker shares its primary hit with AO, interpolates the high mesh's authored normal, and applies the existing inverse MikkTSpace frame. PerVertex is the default; PerFragment is explicit. OpenGL uses the Phase 0 prototype's float32 quantization order; DirectX complements the encoded green code, including 32768 to 32767. Negative Z is preserved. Non-hit texels remain zero with separate class evidence; singular/non-finite frames fail the job without publishing a result.
- `LowParts` computes MikkTSpace on complete objects before selecting a material and retains tangents per triangle corner. Caller rounding/FTZ/DAZ state cannot change generated tangents and is restored. Native complete-object inputs generate missing tangents before the job. Normal-only requests ignore AO settings, cast no secondary rays and leave AO maps empty. Combined requests retain the AO maps. AO-only canonical bytes keep `UZPBAKE3`; Normal uses `UZPBAKE4` with usage/mode/format metadata.
- Explicit native boundary: SubSampling 1, DilationWidth 0, identity transforms on imported low objects. Other values are refused before starting a job. Item 2.1 remains open until the outstanding domains are established; no Python/MCP baking defaults, metadata or capabilities are promoted. Both native usages remain `pending-evidence` with individual owner tasks.
- CPU validation on Debug, ReleaseSafe, ReleaseFast and ReleaseSmall: `tests/bake/test_bake_feasibility.py` passed 52 tests on each build (11.78, 4.80, 5.83 and 4.54 s respectively); `tests/mesh/test_mesh_import.py::test_native_cases` passed on each build (18 native cases). New cases cover analytic planes, distinct tangent modes, mirrored UVs, DirectX codes, negative Z, interpolated high normals, misses/hidden/back faces/cages, singular-frame failure, AO isolation, invalid inputs, retained material/corner frames and caller FP state. Four authored scenes, including Normal, produce identical canonical bytes across separate processes at 1, 4 and all hardware threads, capped by tile count.
- Evidence: `tmp/scratch/native-normal/evidence.json` indexes all eight runs and their JUnit files, source hashes and executable SHA-256. Debug baker executable SHA-256: `2dea53511b2be627217893915f8d6c4563523b264f89733e53295faa768dd748`. All run identities remained stable. Compilation uses warnings as errors; Ruff check/format, mypy, source citation/revision audit and Rulebook validation passed. Documentation: `docs/architecture/06-baking.md` section 3.2 and this task's spec.
- No Painter session or GPU was used. The Phase 0 residual of up to one RGB16 code is calibrated evidence, not Tier 2b equality. Prerequisites, item 2.1, private fixtures/tests, task-wide tails and acceptance remain open.
