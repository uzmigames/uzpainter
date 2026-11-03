# Proposal: phase3.1_height-magnification-fit

## Why
Decision 400 admits the height-to-normal scale z = 100 / W at 4096 px (Sharp), because Painter's own 4096 px Height gives its virtual normals exactly with it. The same recording, `tier0/semantics/height-normal-resolution-4096`, shows that Painter's bilinear magnification of a bitmap on the Height channel is NOT what the evaluator does at 4096: the 256 px height ramps magnified 16 times leave 48,126 of the 16,777,216 Height texels off (0.29 %, up to 2^-10; 38,847 by one binary16 step). At 512, 1024 and 2048 px the same model is exact (decisions 077, 079). So the evaluator refuses a bilinear Height magnification on a set wider or taller than 2048 texels (`CheckSampling`, `src/evaluator/projection_uv.cpp`), naming this task.

No pilot needs it now: the Tunic's Height is uniform colours under 4096 px masks at 1:1 (decision 400 §4). A Height bitmap magnified onto a 4096 px set (a tiling texture, a low-resolution height map) stays refused until this task fits it.

## What Changes
- Find Painter's rule for magnifying the signed heights at 4096 px from the recorded golden (and, if one recording cannot separate the candidates, a new request: other factors at 4096, the same factors on smaller sets, 8- and 16-bit bitmaps), under decision 001.
- Implement it in the CPU reference (`projection_uv.cpp` `ProjectTexel`, `BilinearFilter`) and the GPU kernel (`shaders/evaluator_project.hlsl`) operation for operation, and mirror it in `tools/parity/fit/normal.py` `magnified`.
- Lift the refusal only for what is exact; keep the rest refused with this task as the owner.

## Dependencies
- Inputs from earlier phases: `phase1.8_compositor-sources-projection` and `phase1.12_compositor-height-normal` (archived), the admitted golden of decision 400.
- No same-phase prerequisite, so level 1 (`docs/dag.md`, Task decomposition rule).
- Gate: joined by `phase3.8_gate-g3` item 4.4 (every Phase 3 task archived).

## Acceptance
`height-normal-resolution-4096`: the Height channel and both virtual normal maps of s0-s3 equal r1 on every texel, and r2 wherever r2 equals r1, on DX12 and the CPU reference; every magnification still unrecorded stays refused.

## Impact
- Affected specs: compositor
- Affected code: `src/evaluator/projection_uv.*`, `src/evaluator/shaders/evaluator_project.hlsl`, `tools/parity/fit/normal.py`, `tests/evaluator/test_compositor_height_normal.py`
- Breaking change: NO
- User benefit: low-resolution and tiled height bitmaps on 4096 px sets export as Painter writes them
