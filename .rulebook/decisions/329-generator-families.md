# 329. The mesh-map generator families: eight HLSL families over mesh maps bound by usage, a loud failure for a missing or invalid map, no resampling, and domains declared uncertified

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.2_proc-generator-families

## Context

`phase3.2_proc-generator-families` items 2.2, 2.3, 2.4 and 2.7 and tests 3.2, 3.3 and 3.4 can be built without Painter. Items 2.1 (parameter discovery through the `Property` API), 2.5 (calibration against private oracles), 2.6 (aliases and Tier 2a manifests) and 3.1 (Tier 2a) need Painter recordings or goldens, and stay open. Facts at the start (main `d55af8b9`, rebased on `c477be55`):

- The seam, the HLSL host, the shared primitive library and the asset library exist (decisions 222, 303, 324, 327). No family is certified, and the shipped library holds no record.
- A texture set binds its mesh maps by usage (`TextureSet::mesh_maps`, `core::MeshMapUsage`). A binding names its image by SHA-256, its channel format and its colour space (`Raw` for imported and baked maps), and a mesh reload marks it `invalid` with an `invalid_report` (`mesh/reload.h`). The export's pass-through reads a mesh map the same way: the binding of the set, its decoded image through `evaluator::IResourceProvider`, and a loud failure for a missing binding or image (`export/virtual_maps.cpp`).
- The python-doc says generators bind mesh maps by usage automatically, and 05 §7 says a missing or invalid mesh map fails evaluation loudly.
- The filter task (decision 328, main `c477be55`) added the `IHlslFamily::JointRefusal` hook, which this task uses unchanged.

The coordinator's brief fixed the frame: kernels from published math only (decision 006), UzPainter names only, no alias before an asset is `exact` (decision 324), and every status stays not certified. No model panel ran. The forks below follow from those rules.

## Decision

Code: `src/procedural/generators.{h,cpp}`. Records: `assets/procedural/records/generator.*@1.json`. Tests: `tests/procedural/generators_test.cpp` (`uzp-proc-generator-tests`, `zig build proc-generator-tests`) and `tests/procedural/test_proc_generator_families.py`.

1. **Mesh maps bound by usage.**
   - A generator's image inputs are named by `core::MeshMapUsage` (`AO`, `Curvature`, `Position`, `WorldSpaceNormal`, `Thickness`). Its record's domain lists the ones it reads, and `GeneratorUsages` gives them.
   - `BindMeshMaps(set, usages, resources)` reads each from the texture set's binding: its hash, its spec (the set's square resolution, the binding format's sample type and channel count, its colour space) and its decoded image. A UNORM code is read as `float32(code / (2^n - 1))`, the operand of a stored UNORM code; a float sample keeps its bits.
   - It fails loudly (`request_failed`) and names the mesh map: no binding, a binding marked `invalid` (with its report), an image the resources do not hold, an image whose size, channels or sample type are not the binding's, or a texture set that is not square. Nothing is substituted, and no other map or default value stands in.
   - The request must not bind an input with a mesh-map name itself (`GeneratorRequest`): a generator reads its maps from the texture set only.
   - `SetGeneratorEffect` is the edit: the request, then the seam's admission (decision 324 §10), then one transaction on a generator effect. A refusal opens no transaction.
2. **No resampling.** Every mesh map has the output's resolution. The domain's JSON cannot say so, so each generator checks it after the domain check (`IHlslFamily::JointRefusal`), as `outside certified domain` naming the input's resolution and the output's.
3. **The families.** Every operation is a flushed single operation of the primitive library, with no division in a kernel (the host rounds `1 / (high - low)` once to float32) and no contraction. Every kernel has a CPU reference equal to it bit for bit. The shared shaping is Peachey's boxstep `clamp((v - low) / (high - low), 0, 1)` and smoothstep `3t^2 - 2t^3` (Ebert et al., ch. 2), where the clamp sends NaN and -0 to +0.
   - Curvature (`uzasset://generator/curvature@1`): the signed curvature `2c - 1`, negated for concave `mode`, shaped.
   - Position (`uzasset://generator/position@1`): the normalised position along `axis`, shaped.
   - World Space Normals (`uzasset://generator/world-normal@1`): the normal's component `2c - 1` along one of six signed axes, shaped.
   - Ambient Occlusion (`uzasset://generator/occlusion@1`): the occlusion `1 - ao`, shaped.
   - Dirt (`uzasset://generator/dirt@1`, after Miller 1994 and Hsu and Wong 1995): the cavity `clamp(1 - 2c)` and the occlusion `1 - ao`, weighted and clamped; a disk dilation of radius `spread`; then 3D fBm of Perlin 2002 noise over the position map (four octaves, lacunarity 2, gain 1/2, the request's seed), scaled by `noise_amount` and added, and boxstep from `low` to `high`.
   - Metal Edge Wear (`uzasset://generator/edge-wear@1`, after Paquette, Poulin and Drettakis 2001): the convex edges `clamp(2c - 1)` less `occlusion_protect x (1 - ao)`, clamped; then the same dilation, noise and boxstep as Dirt.
   - Mask Builder (`uzasset://generator/mask-builder@1`): one `source` (convex edges, cavities, occlusion, height or upward normal) boxstepped; a noise mask (the fBm mapped to [0, 1] and boxstepped from `noise_low` to `noise_high`) mixed in by `noise_amount`; then `grow` texels of disk dilation, or of erosion when negative.
   - Mask Editor (`uzasset://generator/mask-editor@1`): the weighted sum of the convex edges, cavities, occlusion, height, upward normal and thickness, boxstepped from `low` to `high`, optionally inverted. It reads five maps, so it runs in two passes (the host gives a pass at most four inputs).
   - The morphology clamps at the texture border. It works in UV space and crosses UV island borders.
4. **Domains declared before calibration, uncertified (item 2.7, first half).**
   - The eight records go in the shipped library with status `unavailable` and no corpus. The alias table stays empty, so `resource.search` refuses every Painter name as before, and `s:uzpainter` lists the eight assets.
   - Parameter names and ranges are UzPainter's own, with `low - high <= -2^-8` wherever a range has two ends. Item 2.1 has not discovered Painter's. When it does, the domains are revised before calibration starts.
   - Seeds: any 32-bit seed (`any_u32`). The four mesh-map generators read no noise, so their output does not depend on the seed.
   - Geometry: the classes of the certification meshes (`sphere`, `bevelled-cube`, `garment`) on one UV tile; each mesh map at 1024, 2048 or 4096, 8- or 16-bit, colour space `Raw`, one channel (AO, curvature, thickness) or three (position, world space normal).
   - Output: one float32 channel, `linear`, at 1024, 2048 or 4096.
   - The held-out reservation of item 2.7 comes from the recording batch, so 2.7 stays open.

## Alternatives Considered

- **Mesh maps in the reference's image inputs.** Rejected: the project stores only what the user chose (decision 324 §10), and the maps change with every bake or mesh reload.
- **Resampling a mesh map at another resolution.** Rejected: that is a substitution of unrecorded behaviour (05 §4, §6).
- **A default value for a missing map** (flat curvature, no occlusion). Rejected: 05 §7 requires a loud failure.
- **UV-space value noise for the breakup.** Not taken: noise over the position map has no seam across UV islands. Calibration may still change it.

## Consequences

- Items 2.1, 2.5, 2.6 and 3.1 remain, and so do the held-out half of 2.7 and 4.1.
- Any later change of operator, parameter or domain happens before calibration starts, or it starts a new held-out set (decision 222).
- The evaluator still refuses generator effects. Wiring them into the compositor waits on a certified family (phase3.3), because production may serve only `exact` assets.
