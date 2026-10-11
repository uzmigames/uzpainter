# 04 — Layer stack and compositing semantics

Implements D3 (`05-resolution.md`). Requirements: G-02, LAY-01…14, MAT-01, MAT-05, EXP-09, NFR-02, NFR-03, ARC-04, CLR-01…03 (`docs/prd.md`). Painter facts come from its public API documentation (`PAINTER\resources\python-doc\substance_painter\layerstack\*.html`, `textureset\*.html`, `source\*.html`) and from black-box observation of its outputs. The earlier summary in `docs/analysis/substance-parity/02-layer-stack-model.md` (sanitised, `docs/analysis/clean-room-redactions.md`) is quarantined in the approved-source index, `docs/approved-sources.md`, and is historical context only. Adobe's shipped shader library and `.py` sources are off-limits (`docs/licensing-and-clean-room.md`). Owner answers applied: Q1 (decision 017: exact equality, divergence only through an owner-approved exception), Q5 (decision 019: brush strokes out of scope), Q8 (decision 021: vendored render core, no UzEngine dependency).

## 1. Data model

```
Layer (uid, kind ∈ {fill, paint, group, instance}, name, visible,
       blending{channel → {mode, opacity}}           // per channel outside mask stacks
       content_effects[], mask? {background: Black|White, enabled, blending{mode, opacity} (mono), effects[]},
       geometry_mask {type: Mesh|UVTile, inclusion_list, items[]},
       fill? {source_mode: Split|Material, sources{channel → Source}, material_source?, active_channels: set,
              projection {mode, params}, symmetry {enabled, params}},
       paint? {planes{channel → plane_id}},
       children[] (group), instance_source (instance), collapsed (inert state))
Effect (uid, kind ∈ {fill, paint, generator, filter, levels, compare_mask, color_selection, anchor}, name, visible,
        blending (per channel in content stacks, mono in mask stacks), active_channels (fill/generator/filter),
        params: LevelsParams | CompareMaskParams | ColorSelectionParams | anchor name,
        source: Source (fill, with projection/symmetry) | ProceduralRef (generator/filter: asset, params, preset, image_inputs, output_mapping, resolution_override)
                | planes{channel → plane_id} (paint))
Source ∈ { uniform_color {rgb, color_space}, bitmap {sha256, color_space}, vector {sha256, params}, font {sha256, params},
           procedural {asset@version, params, preset, image_inputs, output_mapping, mask_output, resolution_override},
           reference {anchor uid, channel_mapping | referenced_channel, alpha_matte, levels} }
```

All twelve documented `NodeType`s and the insertion rules the public `layerstack` API documentation states (first collected in `02-layer-stack-model.md` §3, historical context) are enforced (compare mask, colour selection and smart masks only in mask stacks; groups, smart materials and instances only in the hierarchy). Mask stacks are mono-channel: `set_source(None, …)`, blending with `channel=None`; a channel argument there raises `ValueError` as the documentation states. Smart materials expand to editable groups; smart masks expand to effect lists; both keep a `preset_ref {asset@version}` for provenance only.

Paint layers and paint effects hold one authoritative raster plane per active channel (`plane_id`, `09-project-file-format.md` §1). Their content is written only by typed bitmap operations: a whole bitmap in UV space at the plane's resolution, or a bitmap projected with the modes of §5. Brush strokes are out of scope (owner Q5: Painter's Python API exposes no strokes); UzPainter has no stroke engine, and LAY-12 covers paint layers as receivers of bitmaps and projections.

Per-node resource bindings store the content hash and an optional alias (`LAY-13`): the tunic's C07 binds `Source_v10_M_piping`, F03 binds `Source_v9_M_piping`, both named `M_piping` historically (`A3D\...\18-Tunica\report.json → painting_v10.source_recovery`).

## 2. Evaluation order

For each stack, each channel, each tile (1024×1024 texels; a set resolution ≤ 1024 is one tile):

1. `acc := default(channel)` — the stack's base value for the channel, measured per template in Tier 0 by exporting an empty project (`LAY-10`).
2. For each root layer bottom-up: `acc := Blend(mode_c, acc, L_c, opacity_c × M)` where `L_c` is the layer's value for channel `c` after its content effects and `M` the evaluated mask (1 where absent; the geometry mask multiplies; a disabled mask counts as 1).
3. Group: children composite into `tmp` from a transparent start, then `acc := Blend(group.mode_c, acc, tmp, group.opacity_c × M)`; `PassThrough` composites children directly into `acc`; `Disable` skips the node for that channel.
4. Content effects run in list order on the layer's own content: a fill effect blends its source over the content with its own per-channel mode/opacity; filter and generator effects compute from the current content plus mesh maps and blend with their mode/opacity; levels remaps the affected channel; anchor publishes the current content under its name.
5. Mask stacks: `m := background (0|1)`; effects in order, mono-channel, each with its own mode/opacity; the result is `M`.
6. Instance layers evaluate the source layer's subtree in the instance's position.
7. Anchor references form a dependency graph that must be acyclic (`ValueError` on cycles, as documented).

Painter's API lists root layers top-first (`get_root_layer_nodes`); storage keeps that order, evaluation walks it in reverse. Tier 0 confirms the order with asymmetric blends; every rule above that is not documented is a hypothesis until its Tier 0 golden passes.

## 3. Blend modes

All 32 documented `BlendingMode` members are implemented as kernels: `Normal, PassThrough, Disable, Replace, Multiply, Divide, InverseDivide, Darken, Lighten, LinearDodge, Subtract, InverseSubtract, Difference, Exclusion, SignedAddition, Overlay, Screen, LinearBurn, ColorBurn, ColorDodge, SoftLight, HardLight, VividLight, LinearLight, PinLight, Tint, Saturation, Color, Value, NormalMapCombine, NormalMapDetail, NormalMapInverseDetail`.

Formula sources, in order of authority:
1. **Black-box derivation from Painter (Tier 0):** for every mode, two uniform fills at a sweep of values and opacities, exported at 16 bit through the documented export API; the fitted formula, its clamping and the colour space it operates in (encoded sRGB or linear) are recorded in `parity/semantics/blend-modes.json` and become the kernel source of truth.
2. **Public candidate definitions:** the separable and non-separable modes of W3C Compositing and Blending Level 1 and the PDF 1.7 reference; for the normal-map modes, "whiteout" blending and reoriented normal mapping as published by Barré-Brisebois and Hill, *Blending in Detail* (2012) — Painter's public API documentation names these two techniques for `NormalMapCombine` and `NormalMapDetail`/`InverseDetail` (`PAINTER\resources\python-doc\substance_painter\layerstack\navigation.html`, `BlendingMode`).

Acceptance for every kernel is equality of native decoded values with the Tier 0/1 goldens at the channel's storage precision (Q1); there is no preset tolerance. A mode whose fit does not reproduce the goldens exactly is a release gap in the capability manifest until it does; a remaining difference passes only through an owner-approved, versioned exception with evidence (`14-parity-testing.md` §5), and a listed gap does not count as accepted.

## 4. Precision and quantisation profile

- Intermediates are fp32 (or integer where the storage format is integer and the operation is exactly representable). FP16 is never a substitute for `L16/RGB16` storage.
- Each channel's accumulator is quantised to its `ChannelFormat` at the points Painter quantises. Whether that happens per layer or only at the end, and whether sRGB8 channels blend in encoded or linear space, is decided by the Tier 0 experiment (a stack of three 1/3-opacity fills; compare exact vs per-layer-quantised models). The result is the **evaluator profile** (`evaluator_profile = "painter-12.1-<profile-id>"`), stored in every project and golden; changing it later requires a new profile id and a migration that keeps the old evaluator available for old projects.
- Colour transfer functions follow IEC 61966-2-1 (sRGB piecewise encode/decode). Painter may use an approximation; Tier 0 ramps fit any deviation and the fitted function is recorded. Hardware sRGB formats are not used for compositing; conversions are explicit in the kernels. No fast-math.
- Sampling: bitmap sources at 1:1 texel resolution are copied exactly; the `BilinearHQ`, `BilinearSharp` and `Nearest` filters and the four wrap modes of the documented `UVProjectionParams` are implemented in-kernel (manual filtering) with filter kernels fitted to Tier 0 resampling goldens.

## 5. Projections and symmetry

`Fill` (UV, match per tile), `UV` (filter, wrap, transform {scale_mode, scale, rotation, offset}), `Triplanar` (hardness, 3D transform, normal-weighted blend), `Planar`, `Spherical`, `Cylindrical` (culling, crop, 3D transform), `Warp` and `UVSetToUVSet` (release gaps until their goldens exist); mirror and radial symmetry for 3D projections — all as documented in `layerstack\layereffect\fill.html`. Physical-size scale modes (`MaterialPhysicalSize`, `CustomPhysicalSize`) use the unit rule of `12-mesh-import.md` §3. The semantics of `projection_3d.scale` are fitted from Tier 0 goldens, not assumed to be metres (PRJ-07).

## 6. Height, normal and the virtual maps

- Height is a signed channel (storage format per template, measured in Tier 0); `SignedAddition` and `LinearDodge` semantics come from Tier 0.
- Height→normal is a finite-difference gradient of the height channel. Painter 12.1.5 exposes the method per texture set in Texture Set Settings (`Sharp`, the default, and `Smooth (Sobel)`) and has no strength setting (decision 047, measured; older public help placed a strength in the shader settings). Both methods are fitted from Tier 0 height ramps (kernel footprint, scaling with the height amplitude, edge handling) and recorded in `parity/semantics/height-to-normal.json`.
- Virtual exports `Normal_OpenGL`/`Normal_DirectX` combine the mesh normal map, the channel normal and the height-derived normal with the fitted normal-blend operator, converted to the requested convention; every exported normal is tagged `geometry_only` or `combined` with the relief round (EXP-09). `AO_Mixed` combines the baked AO with the AO channel; the operator (multiply, minimum or other) is fitted in Tier 0. The definitions of the other virtual maps (`Diffuse`, `Specular`, `Glossiness`, `f0`, `1/ior`, …) come from Adobe's public output-template documentation and are confirmed in Tier 0.

## 7. Evaluator architecture

- A DAG keyed by `(stack, channel, tile)`; node outputs cached by `(node uid, subtree hash, evaluator_profile, tile)`; invalidation by subtree hash on every revision.
- Memory admission: live tiles × bytes/texel × channels is bounded by a VRAM budget computed at startup (`13-engine-integration.md` §6); tiles are evaluated in dependency order and evicted LRU; the body's three 4K sets fit in sequence.
- Kernels are generated HLSL compiled through the vendored render core's shader pipeline (DXC to DXIL and SPIR-V; `13-engine-integration.md` §2) and cached by content hash; one kernel per (node kind, blend mode, channel format). Dilation (jump-flood), resampling and height→normal are UzPainter compute passes on the vendored RHI. Arithmetic is marked `precise` (no contraction, no fast-math), and each kernel's outputs must be byte-identical on DX12 and Vulkan over the Tier 0 corpus (Q1).
- Dilation and padding happen at export and preview, not inside the stack (`08-export.md`), matching where Painter's documented export parameters apply them.
- **As built (`phase1.5_compositor-tile-dag`, `src/evaluator/`, reference `src/evaluator/EVALUATOR.md`):** `BuildDag` turns one (texture set, stack, channel) of a revision snapshot into a layer-list DAG with a SHA-256 subtree hash per node output; `TileCache` keys tiles by (node, kind, hash, tile) and serves a list from its highest cached prefix, so an edit re-evaluates only the layers above it; `CheckTextureSet` admits a set at creation from the render layer's budget and `TileCache::Allocate` evicts least recently used tiles under it. One generated kernel per (blend mode, tile format) runs on the engine thread (`GpuTileStore`); `CpuTileStore` is the bit-exact reference and the path without a GPU. Observed and honoured: the stack is evaluated bottom-up from the template base value with every layer written to the channel format (`blend-order` RGB16 exact); an empty channel is its base constant (every `base-values-*` golden exact; `assets/templates/`); a group composites its children from a transparent start into an isolated intermediate, quantised per child, then blends at its opacity, and Painter's default group mode is that `Normal` composite (`group-masks` s0 = s1, RGB16 and RGB32F exact); `PassThrough` stays a hypothesis until `phase0.7_tier0-semantics-ui-cases`.

## 8. Diagnostics (LAY-09, LAY-14, EXP-04)

`isolate(layer)` evaluates with one node hidden and restores visibility atomically; `contribution(layer)` returns the difference map; `material_views(mask)` returns per-channel values under a material mask for ID/BaseColor/Height/Normal/Roughness/Metallic leak checks. All diagnostics are exports of the general engine, not separate code paths.

## 9. What Tier 0 must settle before the kernels are frozen

Blend formulas and spaces; quantisation points; stack base values; mask precision (8 vs 16 bit); group `Normal`/`PassThrough` semantics with masks; content-effect order; levels clamp behaviour; the `BilinearHQ` kernel; height→normal methods and strength scaling; the `AO_Mixed` operator; API readback rules (set→get, mask `None`, insertion errors). Each has a golden set recorded through Painter's documented API (`14-parity-testing.md` §2) and stored privately (`14-…` §6); only the fitted formula, its public source and its residual are published under `parity/semantics/`.
