## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.7_mesh-loader, phase1.10_compositor-blend-kernels, phase1.11_compositor-mask-effects
  - All four archived on main (phase1.11 on 2026-10-11 after its 3.3 scope split, decision 069, and 3.4 under the coverage-weights profile); merged here at main `7be83f4`.

## 2. Implementation
- [x] 2.1 Implement the signed Height channel in its template storage format
  - L16F, signed bitmap range (phase1.8) and the pre-write float32 read-out (`EvaluateFloat32Readout`); Height exports exact over the whole amplitude sweep incl. LinearDodge copies.
- [x] 2.2 Fit both height→normal methods (footprint, scaling, edge handling, strength) to the Tier 0 ramps and implement the kernel
  - Sharp and Sobel stencils, wrap-around, no strength setting (decision 047; amplitude sweep exact); CPU + `UZP_VNORMAL` kernel bit for bit (decision 064).
- [x] 2.3 Fit and implement the normal-combination operator and the OpenGL/DirectX conversion
  - reoriented(F, H) then reoriented(·, Normal channel), DirectX negates y; exact on `blend-normal-channel`. F is the bound Normal mesh map (decoded, y negated in the DirectX convention; decision 079); the channel's normal comes from its root list (colour, coverage) with the GPU's Vulkan acos.
- [x] 2.4 Expose `Normal_OpenGL`/`Normal_DirectX` sources tagged `combined` with the relief round and the geometry-only pass-through tagged `geometry_only`
  - `Evaluator::EvaluateNormal` / `CpuEvaluator::EvaluateNormal`, `NormalTag`/`ReliefRound` (decision 065).
- [x] 2.5 Publish `parity/semantics/height-to-normal.json`
  - Republished against 12.1.5 with the decision-077 recordings (`python -m tools.parity.fit check --fit normal` reproduces): 10 exact, 3 calibrated (r2 divergences: EXC-003, EXC-004, EXC-005), 1 gap.

## 3. Tests
- [x] 3.1 Tier 0 height goldens (`SignedAddition`, `LinearDodge` on Height) exact
  - LinearDodge exact (sweep s5-s7, plane-amplitudes s3); SignedAddition exact on all 24 maps of `height-signed-addition`, both recordings, CPU and GPU (decision 079, no code change).
- [x] 3.2 Tier 0 height→normal goldens for both methods across the strength sweep exact
  - Every r1 map, CPU and GPU; r2 where stable (decision 032 / EXC-003 for s1, s4).
- [x] 3.3 Tier 0 normal-blend goldens (mesh normal ⊕ channel normal ⊕ height normal, both conventions) exact
  - `height-normal-mesh-map` (OpenGL, both methods) and `-directx`, `height-normal-channel-coverage`, `normal-channel-import` and `-directx` (8 and 16 bits): every r1 map exact on CPU and GPU, r2 where stable (EXC-004 for coverage s2). Recorded combinations only; the unrecorded ones are refused and published as the gap `height-normal-unrecorded-inputs` (decision 079).
- [x] 3.4 Tagging test: a combined normal carries `combined` and its relief round; the geometry-only pass-through carries `geometry_only` (EXP-09)
  - `uzp-evaluator-tests height-normal`.

## 4. Acceptance
- [x] 4.1 Tier 0 sets of this child exact in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence); unit tests green
  - `parity/reports/phase1/compositor-height-normal.md` (closing run): every golden of the child exact on r1, CPU and DX12 identical; the resolution goldens (512-2048 px) lift the 256-only refusal; r2 divergences bounded by EXC-003/004/005 (decisions 032, 080).

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - `src/evaluator/EVALUATOR.md`, 04 §6 as built, 03 data model, report `parity/reports/phase1/compositor-height-normal.md` (closing run, decisions 079, 080).
- [x] 5.2 Write tests covering the new behavior
  - `tests/evaluator/test_compositor_height_normal.py` (incl. `test_recorded_inputs_exact`), native cases `height-normal`, `height-normal-gpu-vs-cpu`, `tests/parity/fit/test_normal.py`, `tests/parity/test_verdict.py` (EXC-004, EXC-005).
- [x] 5.3 Run tests and confirm they pass
  - After merging main `7be83f4`: `tests/evaluator`, `tests/parity/fit`, `tests/parity/test_verdict.py`, `tests/uzp_core`, `tests/sources`: 517 passed (29 min, CPU and DX12); `tests/store`: green before the merge.

## Report (2026-10-11)
- Done: 2.1-2.5, 3.2, 3.4, 5.1, 5.2 (decisions 064, 065; `parity/reports/phase1/compositor-height-normal.md`). Every r1 map of both methods exact on CPU and GPU; `blend-normal-channel` exact.
- Open on recordings (exact specs in the report §5): (i) a Normal mesh map with Height and the Normal channel, OpenGL and DirectX projects, both methods (closes 3.3); (ii) SignedAddition on Height (closes 3.1); (iii) Normal-channel partial coverage with Height; (iv) 8- and 16-bit Normal imports in OpenGL and DirectX projects; (v) the amplitude goldens at 512, 1024, 2048 px (lifts the 256-only refusal). 4.1 waits on (i) and (ii).

## Report (2026-10-11, closing run)
- Done: 3.1, 3.3, 4.1 on the recordings of decision 077 (decisions 079, 080). Every r1 map of the ten goldens exact on CPU and DX12, bit for bit; r2 where stable.
- New model: the mesh map is F (decoded, y negated in DirectX); the Normal channel's normal from its root list (colour X, coverage a: decode(X rcp(a)) turned by a with the GPU's Vulkan acos); the channel's read-out over (0.5, 0.5, 1); convention-independent Normal storage, a DirectX export inverts green again; z = 100 / W, 800 / W; Height bitmaps filtered as signed values.
- Lifted only within the evidence (panel): square sets of 256-2048 px, 16-bit mesh maps at the set size in the project's convention, a DirectX Normal channel of one bitmap fill at opacity 1. The rest stays refused (gap `height-normal-unrecorded-inputs`).
- Owner review: EXC-004 and EXC-005 (`parity/exceptions.json`) were entered under decision 032's standing approval.
