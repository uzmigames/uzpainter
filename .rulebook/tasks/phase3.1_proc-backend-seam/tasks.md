## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.6_procedural-feasibility, phase2.10_pilot-tunic-recovery

## 2. Implementation
- [ ] 2.1 Define `ProceduralRequest`, `IProceduralBackend` and `ParityStatus`; implement backend order Snapshot → Hlsl and `UnsupportedProcedural{asset, reason}` raised before any mutation; `HlslBackend.canEvaluate` checks the asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and refuses outside it with `reason: "outside certified domain"`, the field, the value and the certified range
- [ ] 2.2 Implement the `HlslBackend` host: family registration, generated HLSL compiled through the render core with `precise` arithmetic, content-hash kernel cache
- [ ] 2.3 Implement the shared primitive library (Perlin 1985/2002, simplex, Worley, fBm, morphological and blur operators) with a provenance note per primitive
- [ ] 2.4 Implement the asset library: `uzasset://<family>/<id>@<version>` pinned in the project, per-family provenance records, internal alias table for `resource.search`
- [ ] 2.5 Implement `uzpainter assets list --parity` and `.sbsar` import rejection (`reason: "no runtime"`)
- [ ] 2.6 Implement `SourceSubstance` facade semantics of `05-procedural-content.md` §7, including `ResolutionOverride` constraints and automatic mesh-map binding by usage with loud failure on a missing or invalid map
- [ ] 2.7 Implement the Tier 2a certification harness over the §6 matrix with private-store fetch, `oracle_unavailable` on a missing blob, and report output under `parity/reports/phase3/`; it keeps the calibration set and the held-out set apart (a held-out hash list committed before calibration, fitting tools that cannot read held-out blobs, both sets reported separately; decision 222)
  - Note (2026-10-19, permitted early slice under SUP-014; not acceptance): the harness core exists in `tools/parity/proc_cert/`, under decision 303. It has a hash-pinned `batch.json` with separate calibration and held-out roots; an audit-hook fence that refuses fitters and candidates any access to the store, the held-out root and the reports; `oracle_unavailable` for a missing blob; bit-exact per-case outcomes; a held-out set spent on the first candidate it is revealed to; and deterministic hash-only reports. Still open: the §6 matrix check, float (EXR) oracles, real batches under `parity/manifests/phase3/` and reports under `parity/reports/phase3/`, and an OS-isolated fitter worker (decision 303, risk 1).

## 3. Tests
- [ ] 3.1 Seam tests: no backend can serve → `UnsupportedProcedural` and the revision does not advance; no similar asset is substituted
- [ ] 3.2 Tier 0 API-probe goldens for `SourceSubstance` (set→get readback, booleans as int, `ResolutionOverride` errors, Filter-effect restriction) exact
- [ ] 3.3 Primitive-library tests against independently authored public expectations on the local CPU lane (decision 200); DX12 repeatability (identical bytes across runs)
- [ ] 3.4 Reopen test: a project pinning `uzasset://…@<version>` reproduces identical evaluation after save/reopen (RES-04)
- [ ] 3.5 Harness self-test: a seeded one-texel residual is reported with exact max/mean/p99 and affected-texel count and is never a pass; a held-out case with a residual fails the asset even when the calibration set is exact
  - Note (2026-10-19): `tests/parity/proc_cert/test_proc_cert_harness.py` runs this self-test on two synthetic families (authored formulas, not Painter assets). It covers a one-texel residual reported as max 1, sum 1, mean 1/256, p99 0, 1 affected texel of 256, never a pass, in either set; a memorising fitter that is exact on calibration and fails on held-out; missing blobs; eight held-out access attempts refused; the pin; independence; and spending. These are synthetic evidence only; the item stays open until real families run.
- [ ] 3.6 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted; a project snapshot with that exact signature is still served (decision 222)

## 4. Acceptance
- [ ] 4.1 Acceptance: seam, asset library, facade probes, harness and domain-refusal tests pass; no silent substitution or clamping path exists

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
