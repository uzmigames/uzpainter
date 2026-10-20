# 334. The material family: four multi-output HLSL families written once for both lanes, outputs reached through output_mapping, a physical size per record under the project unit rule, and domains declared uncertified

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.2_proc-material-families

## Context

`phase3.2_proc-material-families` items 2.2, 2.3 and 2.4, the domain half of 2.6, tests 3.3 and 3.4, and the half of test 3.2 that needs no golden can be built without Painter. Items 2.1 (parameter discovery through the `Property` API), 2.5 (calibration and Tier 2a manifests), 3.1 (Tier 2a), the held-out half of 2.6 and the oracle half of 3.2 need Painter recordings or goldens, and stay open. Facts at the start (main `99ad2db9`):

- The seam, the HLSL host, the primitive library and the asset library exist (decisions 222, 303, 324, 327). The filter, generator and grunge families are declared uncertified (decisions 328, 329, 331). No family is certified.
- `ProceduralRequest::outputId` carries `SourceSubstance.active_output` (decision 327). `ProceduralRef::output_mapping` maps channel names to asset outputs, and a fill's `SourceMode.Material` holds one `material_source`. The domain's JSON (`tools/parity/proc_cert/batch.py` `Domain`) has no member for outputs.
- The evaluator refuses `MaterialPhysicalSize` naming this task and `CustomPhysicalSize` naming `phase3.4_smart-projections`. The python-doc gives `CustomPhysicalSize`'s scale in centimetres (A-PYDOC). The mesh import report records the effective units (`units {source, from, requested_mesh_unit_scale, scale_to_internal}`, 12 §3) and the certificate's texel density per set.
- The grunge family's periodic noise helpers are private to `grunges.cpp`, and that file is not to be changed.

The coordinator's brief fixed the frame: kernels from published texture-synthesis math only (decision 006), UzPainter names only, no alias, every status `unavailable`, and no change to `tools/parity`, the facade files, `src/export`, `src/bake` or `src/render`. No model panel ran. The forks below follow from those rules.

## Decision

Code: `src/procedural/materials.{h,cpp}` and `src/procedural/shaders/proc_materials.hlsli`; the record members in `src/procedural/asset_library.{h,cpp}` and their listing in `src/procedural/cli.cpp`. Records: `assets/procedural/records/material.*@1.json`. Tests: `tests/procedural/materials_test.cpp` (`uzp-proc-material-tests`, `zig build proc-material-tests`) and `tests/procedural/test_proc_material_families.py`.

1. **Four assets, six outputs each.**
   - `uzasset://material/{felt, burlap, leather-grain, leather-pattern}@1`, usage BASE_MATERIAL, with UzPainter names ("UzPainter Felt", ...).
   - Outputs: `basecolor` (RGB, sRGB-encoded), `normal` (RGB, tangent space, n x 0.5 + 0.5, green = +v), `roughness`, `metallic` (0: dielectrics), `height` and `ambient_occlusion` (mono, linear). Assumption: Painter's output names and usages are not discovered (2.1), so these are UzPainter's.
   - Every output comes from two per-texel fields, a height and a tone, on periodic lattices: the texture wraps bit for bit, and `tiling` is a whole number of repeats from 1 to 32.
   - Felt: straight fibre segments after Kallmes and Corte 1960 over fBm clouds. Burlap: a plain weave after Peachey with a gap, per-yarn thickness and twist ridges after Irawan and Marschner 2012, and an fBm fuzz. Leather grain: domed Worley cells with grooves at their borders and pores. Leather pattern: creases at coarse Worley borders, Musgrave's ridged fBm wrinkles and a fine cell grain.
   - The normal is Blinn's perturbed normal from central differences, with a gain of `normal_intensity` x R / 256 so it does not depend on the resolution, normalised by Lomont's inverse square root and four Newton steps. The occlusion is 1 - ao_intensity x Clamp01(4 (mean - height)), the mean R / 512 texels away (Luft, Colditz and Deussen 2006). Both read neighbours, so they run in two passes: the fields over the whole texture, then the output.
2. **Outputs in the record, checked by a joint rule.**
   - A record may carry `outputs` [{`id`, `channel`, `channels`, `colour_space`}] and `physical_size_cm` [width, height]. The load refuses an unknown member, a channel that is not a `ChannelType`, channels or a colour space outside the domain's output rule, a repeated id or channel, and a size that is not two finite positive values. `assets list --parity` prints both beside the domain.
   - The domain stays the harness's JSON. Each family's `JointRefusal` refuses a request with no output id, an id the record lacks, or a spec whose channels or colour space are not that output's, as `outside certified domain` with the field (`output.id`, `output.channels`, `output.colour_space`).
3. **`output_mapping` reaches every output.** `MaterialRequests(ref, context, library)` gives one request per mapped channel, with the output's channels and colour space. An empty mapping, a key that is not a channel and an unknown output are refused. `DefaultOutputMapping` maps each output to the channel its record names. `SetMaterialSource` admits every channel through the seam, then sets the fill's material source in one transaction. A refusal opens no transaction.
4. **One kernel text for both lanes.** `proc_materials.hlsli` is written in a subset of HLSL that is also C++: only the primitive library's flushed operations on floats, dyadic float literals, exact comparisons, integer hashing, no vector arithmetic, no arrays. The HLSL host compiles it after its wrapper (`#embed`, through `EmbedInputs`). `materials.cpp` includes the same text in a prelude that defines the HLSL vocabulary over `primitives.h`, as the CPU reference. A host-computed parameter block holds every division and the fibre directions' sines and cosines (IEEE double, then float32). The CPU lane computes the fields only where a two-pass output reads them, each at its wrapped position, which is what the second kernel pass reads.
   - The grunge family's periodic helpers are private to `grunges.cpp`, so the material text has its own periodic Perlin noise, fBm and Worley search. Moving one shared set into the primitive library is deferred (decision 331 deferred it too). It changes no output.
5. **Physical size (item 2.4).** `EvaluatePhysicalScale(transformation, record, mesh, set)`:
   - Size: the record's `physical_size_cm` for `MaterialPhysicalSize`, the transformation's `scale` in centimetres for `CustomPhysicalSize`. `Factors`, an invalid custom size and an asset without a physical size are refused.
   - Units: the import report's `units` give the centimetres per file unit (`scale_to_internal`) and whether they follow the file unit or `mesh_unit_scale`. A 3D projection repeats the texture `cm per file unit / size` times per file unit.
   - UV: one UV unit spans `sqrt(W H) / p50` centimetres, p50 being the certificate's surface-weighted median density of the set. The texture repeats `cm per UV / size` times per UV unit. Assumption: Painter's rule is undiscovered. This one is UzPainter's, to be replaced if the oracle half of 3.2 shows another.
   - `PhysicalScale::ToJson` is the receipt: mode, size and its origin, the units, and both scales.
   - The evaluator keeps refusing both modes. A material source is not served until a material is `exact` (phase3.3), and the 3D projections belong to `phase3.4_smart-projections`.
6. **Domains declared before calibration, uncertified (the domain half of 2.6).**
   - UzPainter's own parameters: `tiling` {1, ..., 32}; `color_r`, `color_g`, `color_b`, `color_variation`, `roughness`, `roughness_variation`, `ao_intensity` in [0, 1]; `normal_intensity` in [0, 4]; and per material `fibre_density`, `fibre_alignment` (felt), `gap` in [0, 0.4], `irregularity`, `fuzz` (burlap), `irregularity`, `groove_width`, `pore_amount` (leather grain), `crease_depth`, `wrinkles`, `grain_amount` (leather pattern).
   - Any 32-bit seed. No image input. The certification mesh classes on one UV tile. Output float32 at 1024, 2048 or 4096, linear or sRGB, one or three channels, tied to each output by the joint rule.
   - Every status is `unavailable` with no corpus. The alias table stays empty.
   - Item 2.1 revises names, ranges and defaults before calibration starts. The held-out reservation comes from the recording batch, so 2.6 stays open.
7. **Not wired into the evaluator.** As for the other families, the material family is compiled into its test executable only.

## Alternatives Considered

- **Outputs in the domain JSON.** Rejected: the harness's `Domain` is shared with `tools/parity`, which this task does not change, and the per-output channel rule needs a joint check anyway.
- **One asset per output.** Rejected: Painter's materials are one source with several outputs (`image_outputs`, `output_mapping`), and the snapshot signature already carries the output id.
- **A hand-written HLSL mirror of a C++ reference**, as the grunges do. Rejected: one text compiled twice cannot drift, and it keeps one body to review.
- **Calling the grunge helpers.** Not possible without changing `grunges.cpp`, which the brief forbids.
- **The mesh's bounding box for the UV span.** Not taken: it ignores how the UVs are laid out. The certificate's density is stored, uses the effective units and is per set.

## Consequences

- Items 2.1, 2.5 and 3.1, the held-out half of 2.6 and the oracle half of 3.2 remain. 4.1 waits on them.
- Any later change of operator, parameter, output or domain happens before calibration starts, or it starts a new held-out set (decision 222).
- The certification harness has no output id in its case signature yet. Material batches will need one case list per output, or a harness change owned by `tools/parity`.
