# Proposal: phase1.9_compositor-resample-gaps

## Why
Two Tier 0 `resample-uv` differences remain after `phase1.8_compositor-sources-projection` and were split out by the coordinator's answer to its q1 (2026-10-11): nothing here is accepted as a pass until both match Painter exactly or the owner approves an exception-register entry (decision 017; `docs/architecture/14-parity-testing.md` §5). (a) `BilinearHQ`/`BilinearSharp` with `Repeat`: one value of 1 376 256 per set is one code off (s0 and s1, User2 at scale 1.37 × 2.11, texel (175, 18), green, both recordings) — the exact weighted sum of float32 texels lies 2^-34.7 above a float32 midpoint and Painter rounds it down (`parity/semantics/uv-sampling.json`, `uv-bilinear-repeat`). (b) Bilinear minification (User6, field A at scale 3.3, s0, s1, s3): Painter applies a wider prefilter that `phase0.7_tier0-stability-fits` could not fit (`resampling.json`, `uv-sampling.json` `uv-bilinear-minification`); the evaluator refuses it with `evaluator:unsupported_source`.

## What Changes
- Fit the bilinear rounding that reproduces the near-tie without moving any other `resample-uv` value (candidate models: the texture unit's internal fixed-point filter precision, weight-sum ordering on the GPU), from public sources (X-D3D12 filtering precision) and the Tier 0 golden; or, failing that, an exception proposal with its evidence.
- Fit Painter's minification prefilter for `BilinearHQ` and `BilinearSharp` (mip chain, footprint, seam behaviour) on `resample-uv` User6; record new goldens if the existing one does not determine it (a new manifest under `parity/manifests/tier0/semantics/`).
- Implement both in `src/evaluator/projection_uv.{h,cpp}` and `shaders/evaluator_project.hlsl` (CPU reference = GPU kernel bit for bit), lift the `CheckSampling` refusal, update `parity/semantics/uv-sampling.json` through `tests/evaluator/sources_fits.py`.

## Dependencies
- `phase1.8_compositor-sources-projection` (the projection evaluator and its fits).
- Not a prerequisite of `phase1.14_compositor-core`: the pilot stacks (Wand v1, Belt v5, Tunic v10) use bitmap fills at scale 1 with `BilinearHQ`, which `phase1.8` reproduces exactly (1:1 copy); neither difference is exercised by them. It becomes a prerequisite of any later gate whose content scales bitmaps (minification, or non-unit scales on the bilinear filters).

## Acceptance
`resample-uv` s0, s1 and s3 (every user channel, User6 included) exact on CPU and GPU in a local DX12 run (decision 028), or an owner-approved exception-register entry for what remains.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/projection_uv.*`, `src/evaluator/shaders/evaluator_project.hlsl`, `tests/evaluator/`, `parity/semantics/uv-sampling.json`
- Breaking change: NO
- User benefit: scaled bitmap fills (tiling, minified textures) match Painter exactly.
