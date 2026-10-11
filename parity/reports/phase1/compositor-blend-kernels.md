# `phase1.10_compositor-blend-kernels`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §3). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. It gives numbers and hashes only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `95b2cea` with this task's working-tree changes (`src/evaluator/`, `tests/evaluator/`, `build.zig`, `parity/semantics/blend-kernels.json`).

**Result: all 24 separable modes equal the Tier 0 blend sweeps exactly, on every format and against both recordings, on the CPU and on the GPU.** These are Normal, Replace, Disable, Multiply, Divide, InverseDivide, Darken, Lighten, LinearDodge, Subtract, InverseSubtract, Difference, Exclusion, SignedAddition, Screen, LinearBurn, Overlay, ColorBurn, ColorDodge, SoftLight, HardLight, VividLight, LinearLight and PinLight.

Seven modes are implemented but not exact, and they stay release gaps:

- **The three normal-map modes** (NormalMapCombine, NormalMapDetail, NormalMapInverseDetail) are exact at opacity 1 on every format and on the Normal channel. They are not exact below opacity 1.
- **The four component modes** (Tint, Saturation, Color, Value) are exact on grey channels only.

PassThrough is a group placement and no golden records it. No exception is proposed. The GPU equals the CPU bit for bit for every mode.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build painter` and `zig build evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on `src/evaluator/` and `tests/evaluator/` |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`, Painter build `12.1.0+js-api.1.1.20`. Comparisons go through `tools.parity.fit` (`Golden.map`). Recordings: `r1` (same session) and `r2` (after save and reopen). The blend sweeps are stable (r1 = r2, `tier0-stability.md`) |
| Profile | `painter-12.1-isolated-linear` (phase1.9). Root isolated, read-out over the base |

## What made the separable modes exact

At the start of the task, the evaluator (phase1.9) already reproduced 18 of the 24 separable modes exactly. Each of the other six differed by one code (or one half or float32 step) on a few to 1 970 values per map, and the sRGB8 maps differed by up to 2 codes after export. Two root causes, both identified by bisection on the goldens:

1. **Hardware reciprocal and square root.** Painter divides through the GPU's float32 reciprocal and takes the GPU's float32 square root. These results are faithful (within one ulp) but not correctly rounded.
   - The reciprocal differs from the correctly rounded result on 1 108 522 of the 2^23 mantissas.
   - The square root differs on 2 829 803 of the 2^24 values of [1, 4).
   - `uzp-evaluator-tests fp-hardware` measures `1/x`, `sqrt` and `rsqrt` on every float32 of the reduced domain, and on the 4090 they match the correctly rounded value to within −2..+1 ulp (`rsqrt` has 8 entries at −2).
   - The deltas are stored as zlib-compressed 2-bit tables in `src/evaluator/tables/`: `hw-rcp.zlib` 151 347 bytes, `hw-sqrt.zlib` 180 000 bytes, `hw-rsqrt.zlib` 324 410 bytes. They are embedded with `#embed`, and the CPU and every GPU read the same tables, so neither uses its own instruction.
   - With the tables, Divide, InverseDivide, ColorBurn, ColorDodge and VividLight (reciprocal) and SoftLight (square root) become exact. Under `rsqrt(a)·a` instead, SoftLight still leaves 96 RGB16 values off.
2. **ColorBurn's opacity mix is a fused multiply-add,** `v = fma(a, 1 − α, r·α)`. The mix that every other mode uses, `a(1 − α) + rα`, leaves 18 149 RGB32F values off by 2^-24 at opacity 0.25. With the fused mix they are exact. Applying the same fused mix to the other modes breaks every one of them, so this is per mode.

### Explicit fused multiply-adds (coordinator's design note)

Contraction stays off (`-ffp-contract=off`, `-Gis`). Every fused multiply-add is written as an explicit `Fma` in both `arith.cpp` and the HLSL, and only where the goldens require it. Each listed form is exact, and the unfused alternative was measured to be wrong:

- **Exclusion:** `fma(−2(a − ½), b − ½, ½)`.
- **Screen:** `fma(−(1 − a), 1 − b, 1)`.
- **HardLight (upper branch) and Overlay:** `fma(−2(1 − a), 1 − b, 1)`.
- **SoftLight:** both branches.
- **ColorBurn:** both the kernel (`fma(a − 1, rcp(b), 1)`) and the mix (above).
- **Normal-map modes:** the dot products `fma(z, z', fma(x, x', y·y'))` (normalisation) and `fma(z, z', fma(y, y', x·x'))` (reoriented mapping), `r.xy = fma(t.xy, d, −(u.xy·t.z))`, and the encode `fma(n, ½, ½)`.

The two normalisation dot orders were selected among all 6 × 6 orders: 0 differing values on RGB16 and RGB16F, against at least 11 for every other order. The reoriented-mapping z component is `t.z·(d − u.z)`, not fused, which took Detail and InverseDetail from 19 differing values to 0.

## Tier 0 comparisons

`parity/semantics/blend-kernels.json` publishes the residuals per texture set and channel against r1 and r2 (`tests/evaluator/blend_fits.py`; `test_published_fit_reproduces` requires the file byte for byte). The table gives the r1 statistics; r2 is identical because the goldens are stable.

| Modes | Maps | Result |
|---|---|---|
| 24 separable modes (`blend-basic`, `blend-additive`, `blend-contrast`) | 8 channels each: RGB16 α 1 and 0.5, sRGB8 α 1 and 0.5, RGB8, RGB16F, L16 (grey), RGB32F α 0.25 | **exact**: 0 differing values on every map, r1 and r2, CPU and GPU |
| NormalMapCombine, NormalMapDetail, NormalMapInverseDetail (`blend-component` s4–s6) | user channels at opacity 1 (RGB16, sRGB8, RGB8, RGB16F, L16), sRGB8 at 0.5 (Combine) | exact |
| the same | Normal channel (`blend-normal-channel` s1–s3, RGB16F, OpenEXR) | exact. The fields are imported with the OpenGL green convention (r, 1 − g, b) applied to the fixture bytes, the import rule `blend-modes.json` records; phase1.12 owns that import |
| the same | RGB16 at 0.5 | release gap: 202 / 257 / 176 of 196 608 values off by 1 code |
| the same | sRGB8 at 0.5 (Detail, InverseDetail) | release gap: 40 values off by 2 sRGB codes (16-bit export 511) |
| the same | RGB32F at 0.25 | release gap: 72 042 / 72 463 / 47 693 values off by at most 1.8e-7 |
| Tint, Saturation, Color, Value (`blend-component` s0–s3) | L16 (grey: keep A, Value takes B) | exact |
| the same | colour channels | release gap: up to 32 634 / 53 100 / 46 657 / 23 312 of 196 608 RGB16 values differ; max 129 / 14 879 / 172 / 14 011 codes |

The normal-map residual below opacity 1 is the rotation of the upper normal toward (0, 0, 1). Painter's float32 evaluation of that slerp, with its own trigonometric functions, is not identified. The evaluator uses a deterministic float32 series that is equal on CPU and GPU.

The component modes follow the phase0.7 HSV fit (hexcone with ε = 2^-12, value doubled, divisions through the hardware reciprocal). The residual concentrates where the hue source is nearly grey, the hue offset that `blend-modes.json` already records as an open item. Several variants change nothing:

- half-precision inputs, operations or outputs;
- other epsilons (1e-10, 1e-4, 1e-3);
- correctly rounded division.

### Per-channel modes (3.2)

No Tier 0 golden records different modes on the channels of one layer. The sweeps share their inputs and per-channel opacities, so the test composes a layer from them:

- Multiply on RGB16, Divide on sRGB8 (as on BaseColor), ColorBurn on RGB8, Screen on RGB16F and SoftLight on L16 (as on Roughness), each at its channel's opacity.
- Each channel is compared with the sweep recorded in its mode.
- Every channel is exact against r1 and r2 on both backends.

## Unit tests and kernels

| Case | Result |
|---|---|
| `arith`, `order` (CPU) | passed. Every documented mode but PassThrough has a kernel (31 of 32), and Tint now evaluates |
| `fp-hardware` (DX12) | the embedded rcp, sqrt and rsqrt tables equal the GPU on all 8 388 608, 16 777 216 and 16 777 216 entries of their domains. `hw::Rcp/Sqrt/Rsqrt` equal the GPU on 32 edge values and 1 048 544 hashed bit patterns over every exponent: subnormals count as signed zero, and a reciprocal below 2^-126 is ±0 |
| `kernel-sweep` (DX12) | every mode × 9 channel formats × coverage on and off × opacity 1 and 0.7: GPU = CPU on 149 422 080 samples (1 080 combinations) |
| `gpu-vs-cpu` (DX12) | random stacks over every mode and format: identical bytes (2 490 368 samples) |
| Earlier phase1.5, phase1.8 and phase1.9 goldens | unchanged: `blend-order` stays exact with the hardware reciprocal in Divide |

## Quality gate

| Step | Command | Result |
|---|---|---|
| Type-check | `python -m mypy` | no issues (184 files) |
| Lint | `python -m ruff check .`, `python -m ruff format --check .` | clean |
| Build | `zig build painter`, `zig build evaluator-tests` | exit 0, no warnings |
| Tests | `python -m pytest tests/evaluator`, `python -m pytest tests/parity` | 235 passed (evaluator, with the store and the DX12 adapter: nothing skipped); 625 passed (parity) |
| Guard | `python -m tools.parity.guard` | 0 blocked |

## Decisions and open items

- **The tables are measurements of the recording GPU, not of Painter.** They make the evaluator reproduce Painter as recorded on an RTX 4090. If a later golden is recorded on another GPU, a new table set and a new profile id are needed.
- **Kernel corrections and the profile id.** The kernel corrections change the output of Divide, InverseDivide, ColorBurn, ColorDodge, VividLight and SoftLight within the registered profile `painter-12.1-isolated-linear`, by one code where they differed before. No project has shipped with that profile, and the blend kernels were provisional until this task. No new profile id was introduced (an assumption for the coordinator).
- **Release gaps (q1, option 1).** The component modes on colour channels, the normal-map modes below opacity 1 and PassThrough stay `release-gap` in `tools/capabilities/painter-api-inventory.json`, and each entry's note names the gap. They move to the follow-up task `phase1.11_compositor-blend-gaps`. That task is not a prerequisite of `phase1.14_compositor-core`: the Wand v1 stacks use only `Normal`, `LinearDodge` (Height) and default-mode groups. No exception is approved.
- **Transient kernel-cache failures.** Two GPU evaluations failed once in a work folder about 200 characters deep, with "include could not be written". They passed on a rerun, so this was not reproduced as a code fault.
