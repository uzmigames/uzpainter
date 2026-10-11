# `phase1.5_compositor-tile-dag` — acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR, `docs/dag.md`; `docs/architecture/04-layer-stack-and-compositing.md` §2, §4, §7; `03-project-model.md` §2). Decision 028: the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence for the G1 gate record. Numbers and hashes only; every recorded Painter output stays in the private store. Run on 2026-10-10 on the tree of commit `6fb4a16` with this task's working-tree changes (`src/evaluator/`, `tests/evaluator/`, `assets/templates/`, `build.zig`).

**Result: every Tier 0 set owned by this child is exact on both backends; unit tests green.** 104 of 104 tests of `tests/evaluator/` pass; the kernels equal the CPU reference bit for bit over 114 556 928 swept samples.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090 (DXGI budget 24 505 221 120 bytes, dedicated 25 310 527 488), Windows 11 Pro 10.0.26200 |
| Backend | DX12 (`--gpu-backend dx12`, the default); kernels `cs_6_6 -Gis` through the render layer's kernel cache (DXC beside the executable), doubles used for the fused multiply-add and the residual corrections of `Rcp`/`Sqrt` |
| Admission budget in force | 11 957 792 768 bytes, 497 952 live tiles (`render::AdmissionBudget` of the capability report) |
| Build | Zig 0.15.2, Debug; `zig build painter evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on `src/evaluator/` and `tests/evaluator/` |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store` (735 hashes), Painter build `12.1.0+js-api.1.1.20`; comparisons through `tools.parity.fit` (`Golden.map`, native decoded values), both recordings `r1` and `r2` |

## Tier 0 comparisons (task items 3.1–3.4, 4.1)

| Item | Goldens | Compared | Result |
|---|---|---|---|
| 3.1 base values (LAY-10) | the 27 `tier0/semantics/base-values-*` goldens (26 shipped templates and the no-template project) | every exported map of every golden (147 maps), both recordings, on the CPU and on the GPU: the base constant of the empty channel exported with the 16-bit write rule (PNG 16) or as float32 (OpenEXR 32f) | exact (0 differing values) |
| 3.2 template channel sets | `tier0/defaults-templates/project-templates` (26 captures) and the no-template project of `base-values-default` | channel set and `ChannelFormat` of every authored template against the capture read back through the documented `textureset` API | equal for all 27 |
| 3.3 evaluation order | `tier0/semantics/blend-order` s0–s3 (ABC, BAC, ACB, CBA) | `User0` (RGB16), 4 maps × 2 recordings × 2 backends | exact (0 differing values of 196 608 per map) |
| 3.4 groups without masks | `tier0/semantics/group-masks` s0 (default mode) and s1 (`Normal`), opacity 0.75 | `User0` (RGB16) and `User2` (RGB32F), 4 maps × 2 recordings × 2 backends | exact (0 differing values of 196 608 per map) |

Not compared here, by scope: the sRGB8 channels of `blend-order` (`User1`) and `group-masks` (`User1`) depend on the import of a 16-bit bitmap into sRGB8 storage, the colour-transfer rule of `phase1.8_compositor-sources-projection` (their published fit is calibrated, not exact: `blend-modes.json` `blend-evaluation-order`); s2 and s3 of `group-masks` carry masks (`phase1.11_compositor-mask-effects`). `PassThrough` groups cannot be recorded through the documented API (`phase0.7_tier0-semantics-ui-cases`); the implemented placement (children directly into the stack, opacities scaled by the group's) is a hypothesis and is covered by unit tests only.

Findings fixed in this run, each a model error found by a golden and corrected at the root: (a) the `1 + (v - 1)` re-composition of 32-bit float channels is a read-out step, not a per-layer store (`group-masks` RGB32F: 12 693 texels 1 ulp off when applied per layer, exact once applied at read-out, as the blend fits read their backdrop raw); (b) Painter's default group mode is the isolated `Normal` composite (s0 = s1 texel for texel on every channel), not a pass-through; (c) an empty channel exports its base constant through the 16-bit write rule whatever the channel format (the Dota 2 `Specular` L8 base exports 14330, off the 8-bit lattice).

## Unit tests and kernels (task items 3.5, 3.6, 2.5)

| Item | Case | Evidence |
|---|---|---|
| 3.5 cache and invalidation | `cache` (CPU, 2048 × 1024 set, two L16 channels, ten layers over a bitmap) | first evaluation 2 tiles × 10 blends per channel, bitmap uploaded once per tile; same revision again: 2 cache hits, 0 blends; after one layer's opacity changes on `User0` in a committed revision: per tile the five prefixes above miss, the prefix below the edit hits, 5 blends run, nothing uploaded; `User1` served whole from the cache; the partial result equals a fresh evaluation bit for bit; no eviction under a wide budget (54 live tiles) |
| 3.6 admission | `admission` (counting store) | three 4096² sets (sRGB8, L8, L8, RGB16F, L16F) under a budget of one set's live tiles (268 435 456 bytes) plus the working set (25 165 824 bytes): every channel evaluates, 649 LRU evictions, store and cache peak within the budget; an 8192² set and a descriptor-starved budget are refused at creation with `texture_set_over_budget` |
| 2.5 kernels = reference | `gpu-vs-cpu`, `kernel-sweep` | random stacks over the 9 channel formats (bitmaps, uniform fills, isolated and pass-through groups, 2 490 368 samples) and dense sweeps of the 23 separable modes × 9 formats × with/without coverage × 2 opacities (828 combinations, 114 556 928 samples): GPU equals CPU bit for bit (NaN matches NaN, CONTRACT §3.1) |
| order, templates, arithmetic | `order`, `templates`, `arith` | bottom-up asymmetric blends on RGB16, L16, RGB32F; visibility, `Disable` per channel, empty masks, empty stack, groups, instances, 1:1 bitmaps, explicit `unsupported_*` failures; 27 templates load, 221 channel entries, base values resolve through template then defaults |

`python -m pytest tests/evaluator`: 104 passed, 0 skipped (295.9 s). Repository gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy` (173 files), `python -m tools.parity.guard` (2278 files, 0 blocked), `python -m tools.sources.check`, `python -m tools.vendoring.vendor_check` (97 files, build paths checked) all pass.

## Templates: unobserved base values (release gaps)

17 of the 221 channel entries have no observation (no document map exports them from an empty project) and are authored by analogy, marked `unobserved`: `CoatColor`, `CoatNormal`, `CoatRoughness`, `CoatWeight` (ASM coated, OpenPBR coat), `FuzzColor`, `FuzzRoughness`, `FuzzWeight` (ASM sheen, OpenPBR fuzz), `SubsurfaceColor`, `SubsurfaceWeight` (OpenPBR subsurface), `Tangent` (OpenPBR anisotropy). A channel type outside a template and the channel defaults fails evaluation explicitly (`missing_base_value`).

## Reproduce

```
zig build evaluator-tests
python -m pytest tests/evaluator
```
