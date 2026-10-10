# The compositor's tile DAG (`src/evaluator/`)

Task `phase1.5_compositor-tile-dag` (child of `phase1.14_compositor-core`, P1-COMPOSITOR). Implements `docs/architecture/04-layer-stack-and-compositing.md` §2 (steps 1–3, 6, 7), §4 (the storage rules the kernels share) and §7 (DAG, cache, admission, generated kernels), and the project templates of `03-project-model.md` §2. Tests: `tests/evaluator/` (`zig build evaluator-tests`, `python -m pytest tests/evaluator`). Local run report: `parity/reports/phase1/compositor-tile-dag.md`.

## 1. Shape

| File | Role |
|---|---|
| `arith.{h,cpp}` | The scalar rules every backend shares: UNORM operand tables (`float32(code / M)`), the sRGB8 operand (IEC decode on 8 significant bits) and store (decode thresholds compared in double), the UNORM write rule (truncate to n + 4 fractional bits, nearest, ties down), the 16-bit float store toward zero, the 32-bit float store `base + (v - base)`, the separable blend kernels of `parity/semantics/blend-modes.json` and the per-texel composite. |
| `formats.h` | `TileFormat` (encoding, 1 or 3 channels, sRGB flag, coverage plane), its GPU format and byte cost; the 1024-texel tile grid. |
| `templates.{h,cpp}` | `TemplateLibrary`: `assets/templates/*.json` (§3). |
| `hash.{h,cpp}` | SHA-256 `HashWriter` for subtree hashes. |
| `dag.{h,cpp}` | `BuildDag`: the per-(set, stack, channel) evaluation DAG from a snapshot, with the subtree hash of every node output (§2). |
| `admission.{h,cpp}` | `AdmissionLimits` from the render layer's budget, `CheckTextureSet` (refusal at creation), `TileCache` (LRU under the limits, pins). |
| `tile_store.h` | `ITileStore`: allocate, upload, blend, flush, read. |
| `cpu_store.{h,cpp}` | The CPU store: the reference, and the path without a GPU. |
| `kernelgen.{h,cpp}`, `shaders/evaluator_blend.hlsl` | One generated kernel per (blend mode, tile format), compiled through the render layer's kernel cache; parameter blocks in an arena buffer. |
| `gpu_store.{h,cpp}` | The GPU store on the engine thread: textures, batched dispatches, `TextureReadback`. |
| `evaluate.{h,cpp}` | Running a DAG tile by tile on a store under the cache. |
| `evaluator.{h,cpp}` | `Evaluator` (engine thread, GPU) and `CpuEvaluator`; `EvaluateOn` is their shared body. |
| `error.{h,cpp}` | Evaluator failures as `render::Error` with the reason `evaluator:<kind>[ node=<uid>]: <detail>`. |

Everything runs on revision snapshots (`core::Snapshot`); the GPU path submits one engine request per channel evaluation and keeps the cache across requests.

## 2. Semantics implemented (and their evidence)

- **Base value, bottom-up order.** `acc := base(channel)` from the template; root layers are walked bottom-up; each contributing layer blends with its per-channel mode and opacity; the result is written to the channel format after every layer (profile `painter-12.1-layerq-linear`, provisional, `parity/semantics/evaluator-profile.json`). Evidence: `blend-order` RGB16 maps exact on both recordings (`tests/evaluator/test_compositor_tile_dag.py::test_evaluation_order_equals_the_golden`).
- **An empty channel is its base constant**, not a stored code: Painter's empty channels export values no channel code produces (the BaseColor of the shipped templates, `float32(127/255)` on an RGB16F Normal). The evaluator returns the constant; an exporter writes it with the float write rule of the export depth (16-bit PNG: the UNORM write rule; OpenEXR: the float32). Evidence: every `base-values-*` golden exact.
- **Groups.** A group composites its visible children from a transparent start into an isolated intermediate (coverage in a fourth plane, quantised to the channel format after each child; the 32-bit float store re-composites over 0 inside a group and over the channel base on the stack), then blends that intermediate with its own mode and opacity. Painter's default group mode behaves exactly so: in `group-masks` the default-mode group (s0) and the `Normal` group (s1) are identical texel for texel, and both are reproduced exactly on RGB16 and RGB32F. `PassThrough` (documented, not settable through Painter 12.1.0's API, `phase0.7_tier0-semantics-ui-cases`) composites the children directly into the stack with their opacities scaled by the group's: a hypothesis until recorded. `Disable` skips the node for that channel.
- **Isolated composite.** W3C Compositing and Blending Level 1 §5.1 with straight colours: an opaque backdrop gives the fitted mix `a (1 - alpha) + r alpha` (`Replace`: `a + (r - a) alpha`), a transparent backdrop passes the source through, a partly covered backdrop uses the general formula (not yet exercised by a golden; masks are `phase1.11`).
- **Instances** evaluate their source layer in their own position; **invisible** layers are skipped; an **empty mask** is its background (White 1, Black 0); a disabled mask is 1.
- **Sources.** Uniform colours are stored like a channel value and read back (`blend-modes.json` `uniform_operand`; a grey channel takes the mean of the three components). Bitmaps are copied at 1:1: codes of the channel's depth as they are, 16-bit codes onto 32-bit float channels as `float32(code / 65535)`. Every other conversion (16-bit bitmaps onto sRGB8, 8-bit or float channels, UV transforms, filters) is `phase1.8_compositor-sources-projection` and fails with `evaluator:unsupported_source`.
- **Kernels.** The 23 separable modes of `blend-modes.json` (Normal, Replace, Disable, Multiply … PinLight) with the fit's float32 operation order: fused multiply-add as the float32 rounding of the exact `x y + z` (exact product in double, one addition), correctly rounded reciprocal and square root (the hardware result corrected with exact double residuals on the GPU), IEEE minNum/maxNum where the fit uses numpy `fmin/fmax`, NaN propagation where it uses `minimum/maximum`. Exactness against the Tier 0 sweeps is `phase1.10`'s acceptance; this task's acceptance is GPU = CPU bit for bit (`gpu-vs-cpu`, `kernel-sweep`). Tint, Saturation, Color, Value and the normal-map modes fail with `evaluator:unsupported_blend_mode`.
- **Cache.** Node outputs are tiles keyed by `(node, kind, subtree hash, tile)`: `Content` for a layer's bitmap tile, `Prefix` for the accumulator of a layer list after a layer (chained hashes from the list start, which includes profile, channel, format and base). A list is evaluated from its highest cached prefix upward, so an edit re-evaluates only the layers above it; untouched channels and tiles are served whole. Subtree hashes cover only evaluation-relevant fields (names and UI state do not invalidate).
- **Admission.** Limits come from `render::AdmissionBudget` (13 §6). `CheckTextureSet` admits a set when its final tiles plus a three-tile working set fit; `TileCache::Allocate` evicts least recently used unpinned tiles and fails explicitly (`tile_budget_exceeded`) when pinned tiles leave no room; the evaluator flushes queued GPU work and releases finished inputs before failing.

## 3. Templates (`assets/templates/`)

One JSON per shipped Painter 12.1.0 template (26), `default.json` for the project created with no template, and `channel-defaults.json` for channels added afterwards. Schema `uzpainter/template/1`: `id`, `name`, `kind` (`project` | `channel-defaults`), `painter_template` (the shelf path the template reproduces), `provenance` (channel set: the `project-templates` capture; base values: the `base-values-<template>` golden; record hashes), `channels[]` with `type` (`ChannelType`), `format` (`ChannelFormat`, project templates only), `base` (three float32 components) and `base_provenance`:

- `observed`: the private golden, its record hash, the map and the 16-bit export codes the base reproduces (the base is the nearest float32 to `code / 65535`, checked to write back to the code);
- `fitted`: a published fit (`height-to-normal.json` flat normal, `ao-mixed.json` white AO);
- `unobserved`: no document map exports the channel (coat, fuzz, subsurface weight/colour, tangent); authored by analogy and listed as such in the local run report. A channel type absent from both a template and the defaults fails evaluation with `missing_base_value`.

Authored by UzmiGames; never generated from a capture (the goldens are compared with the files in the local run, `test_template_channel_sets_equal_the_capture`, `test_base_values_equal_the_empty_project_exports`). `TemplateLibrary::DefaultDirectory()` is `assets/templates` beside the executable (installed by `zig build painter` and `evaluator-tests`).

## 4. Out of this profile (explicit failures, capability gaps)

Paint layers, content and mask effects, geometry masks, `Material` source mode, procedural/vector/font/reference sources, 3D projections and symmetry, UV transforms other than the identity, non-separable and normal-map blend modes, masks with partial coverage (the general composite is implemented but unverified). Each fails before any work with `evaluator:unsupported_*` naming the node and the task that owns it.
