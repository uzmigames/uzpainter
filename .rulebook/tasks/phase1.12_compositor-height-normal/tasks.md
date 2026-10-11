## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.7_mesh-loader, phase1.10_compositor-blend-kernels, phase1.11_compositor-mask-effects
  - All four archived on main (phase1.11 on 2026-10-11 after its 3.3 scope split, decision 069, and 3.4 under the coverage-weights profile); merged here at main `7be83f4`.

## 2. Implementation
- [x] 2.1 Implement the signed Height channel in its template storage format
  - L16F, signed bitmap range (phase1.8) and the pre-write float32 read-out (`EvaluateFloat32Readout`); Height exports exact over the whole amplitude sweep incl. LinearDodge copies.
- [x] 2.2 Fit both height→normal methods (footprint, scaling, edge handling, strength) to the Tier 0 ramps and implement the kernel
  - Sharp and Sobel stencils, wrap-around, no strength setting (decision 047; amplitude sweep exact); CPU + `UZP_VNORMAL` kernel bit for bit (decision 064).
- [x] 2.3 Fit and implement the normal-combination operator and the OpenGL/DirectX conversion
  - reoriented(flat, H) then reoriented(·, Normal channel), DirectX negates y; exact on `blend-normal-channel`. The mesh-normal-map slot is refused until recorded (3.3).
- [x] 2.4 Expose `Normal_OpenGL`/`Normal_DirectX` sources tagged `combined` with the relief round and the geometry-only pass-through tagged `geometry_only`
  - `Evaluator::EvaluateNormal` / `CpuEvaluator::EvaluateNormal`, `NormalTag`/`ReliefRound` (decision 065).
- [x] 2.5 Publish `parity/semantics/height-to-normal.json`
  - Republished against 12.1.5 (`python -m tools.parity.fit check --fit normal` reproduces); EXC-003 for the plane-strength r2 divergence.

## 3. Tests
- [ ] 3.1 Tier 0 height goldens (`SignedAddition`, `LinearDodge` on Height) exact
  - LinearDodge exact (sweep s5-s7, plane-amplitudes s3). Open: no golden records SignedAddition on Height; recording request in `parity/reports/phase1/compositor-height-normal.md` §5 (ii).
- [x] 3.2 Tier 0 height→normal goldens for both methods across the strength sweep exact
  - Every r1 map, CPU and GPU; r2 where stable (decision 032 / EXC-003 for s1, s4).
- [ ] 3.3 Tier 0 normal-blend goldens (mesh normal ⊕ channel normal ⊕ height normal, both conventions) exact
  - Channel normal ⊕ flat height exact (`blend-normal-channel`); height ⊕ empty channel exact in both conventions. Open: no golden binds a Normal mesh map or combines a non-empty Normal channel with Height; recording request §5 (i), (iii), (iv).
- [x] 3.4 Tagging test: a combined normal carries `combined` and its relief round; the geometry-only pass-through carries `geometry_only` (EXP-09)
  - `uzp-evaluator-tests height-normal`.

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence); unit tests green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - `src/evaluator/EVALUATOR.md`, 04 §6 as built, 03 data model, report `parity/reports/phase1/compositor-height-normal.md`.
- [x] 5.2 Write tests covering the new behavior
  - `tests/evaluator/test_compositor_height_normal.py`, native cases `height-normal`, `height-normal-gpu-vs-cpu`, `tests/parity/fit/test_normal.py`.
- [x] 5.3 Run tests and confirm they pass
  - After merging main `7be83f4`: `tests/evaluator`, `tests/parity/fit`, `tests/parity/test_verdict.py`, `tests/uzp_core`, `tests/sources`: 517 passed (29 min, CPU and DX12); `tests/store`: green before the merge.

## Report (2026-10-11)
- Done: 2.1-2.5, 3.2, 3.4, 5.1, 5.2 (decisions 064, 065; `parity/reports/phase1/compositor-height-normal.md`). Every r1 map of both methods exact on CPU and GPU; `blend-normal-channel` exact.
- Open on recordings (exact specs in the report §5): (i) a Normal mesh map with Height and the Normal channel, OpenGL and DirectX projects, both methods (closes 3.3); (ii) SignedAddition on Height (closes 3.1); (iii) Normal-channel partial coverage with Height; (iv) 8- and 16-bit Normal imports in OpenGL and DirectX projects; (v) the amplitude goldens at 512, 1024, 2048 px (lifts the 256-only refusal). 4.1 waits on (i) and (ii).
