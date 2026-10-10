# 04 — UzEngine Material and Texture Standard (the UzPainter "UzEngine export preset")

Scope: exactly what a UzEngine material consumes — texture slots, channel packing, colour space, normal-map convention, on-disk/runtime formats, block compression, mip policy, and the JSON that references them. Paths relative to `E:\UzmiGames\UzEngine\`.

## 1. Three material descriptions coexist — pick the right target

| Representation | Where | Loaded by | Status |
|---|---|---|---|
| **Fixed-PBR `Material` asset** (C++ struct with named texture slots + scalars) | `runtime/engine/renderer/material/material_asset.h`, base `material_interface.h` | Scene JSON `material` component (`engine/ecs/loaders/scene_loader.cpp` lines 757-852), decal component, Lua `uz.scene.set_material` | **Fact** — the path the GBuffer shader actually samples (`shaders/runtime/gbuffer/gbuffer_ps.hlsl` "Fixed PBR path") |
| **Node-graph `.uzmat`** (JSON `expressions[]` with `PBROutput` id 1) | `runtime/engine/material/material_graph.h`, defaults `engine/material/defaults/default_lit.uzmat` | `MaterialManager::LoadMaterial`, compiled by `HlslMaterialTranslator` and injected into `gbuffer_ps.hlsl` under `UZ_MATERIAL_GRAPH`; the scene loader also *flattens* a `.uzmat`'s `TextureSample` paths into the fixed `Material` slots (`scene_loader.cpp` lines 536-600, 740-775) | **Fact** — implemented ("Phase 1.5+ GPU integration", `docs/engine/12-rendering/16-material-system.md`) |
| **`.uzmaterial` JSON Schema** (`shader`, `render_state`, `textures{slot:{asset,sampler,uv_channel,tiling,offset}}`, `parameters`, `defines`, `shader_graph{nodes,connections}`) | `runtime/schemas/uzmaterial.schema.json` | **No loader found** for this shape; the extension differs (`.uzmaterial` vs `.uzmat`) and the graph shape differs (`nodes/connections` vs `expressions/inputs`) | **Fact** — schema exists; **Hypothesis** — it is aspirational/stale |

**Recommendation** — UzPainter's "UzEngine preset" should emit (a) texture files + `.uztexture` companions and (b) a `.uzmat` graph **or** inline scene `material` component fields, never the `uzmaterial.schema.json` shape.

## 2. Texture slots the renderer understands

**Fact** — Slot list enumerated by `SceneRenderer` when loading a material: `"Albedo", "Normal", "Roughness", "Metallic", "Ao", "Emissive", "ORM", "Thickness", "Opacity", "DetailAlbedo", "DetailNormal", "ClearCoatNormal", "Tangent", "Heightmap"` (`engine/renderer/scene/scene_texture_assets.cpp` lines 231-235). `Material` fields in `material_asset.h` lines 287-300, 410-429: `albedoPath, normalPath, roughnessPath, metallicPath, aoPath, emissivePath, opacityPath, ormPath (+useORM), thicknessPath, clearCoatNormalPath`; `heightmapSrvIndex` and POM parameters live in `PerObjectCB` (`gbuffer_ps.hlsl` lines 43-66).

### 2.1 Channel semantics as sampled by `gbuffer_ps.hlsl` (fixed-PBR path)

| Slot | Channels read | Shader evidence (`shaders/runtime/gbuffer/gbuffer_ps.hlsl`) | Colour space default | Fallback when unbound |
|---|---|---|---|---|
| Albedo / BaseColor | `.rgb` × `baseColorTint`; `.a` kept as `albedoAlpha` for alpha test | lines 139-154, 275-286 | **sRGB** | 1×1 white; shader uses tint only |
| Normal | `.rg` → `xy = rg*2-1`, `xy *= normalIntensity`, **`z = sqrt(1-dot(xy,xy))` reconstructed** (blue channel ignored → BC5-compatible) | lines 200-214 | linear | flat normal (128,128,255) placeholder |
| Roughness | `.r` × `roughnessMultiplier`; if no texture → `roughnessMultiplier` used directly | lines 170-176 | linear | none (multiplier) |
| Metallic | `.r` × `metallicMultiplier`; if no texture → multiplier | lines 177-183 | linear | none (multiplier) |
| AO | `.r`, then `ao = lerp(1, ao, aoIntensity)` | lines 184-187, 198 | linear | 1.0 |
| **ORM** (packed) | `materialFlags & 0x4` → one texture: **`ao = .r`, `roughness = .g`, `metallic = .b`** (overrides the three separates) | lines 165-169, 190-193 | linear | — |
| Emissive | `.rgb` × `emissiveColor` × `emissiveIntensity` | lines 248-258 | **sRGB** (`DefaultSlotIsSRGB`) | black (no emission) |
| Opacity | **`.a` of the opacity texture** when `opacitySrvIndex > 0`, else albedo alpha; compared with `alphaClipThreshold` when blend mode is Masked | lines 262-281 | linear | albedo alpha |
| Heightmap | `heightmapSrvIndex`, `displacementScale`, `pomMin/MaxLayers`, `pomFadeStart/End`, `pomSelfShadow` in `PerObjectCB` (POM implemented in `shaders/runtime/material/pom.hlsli`) | lines 60-65 | linear | black = no displacement (decision 009) |
| Thickness / ClearCoatNormal / Detail* / Tangent | loaded as slots; sampling locations not read in this analysis | `scene_texture_assets.cpp` 231-235 | linear | — |

**Fact** — Normal map Z reconstruction means the engine never needs the blue channel: BC5 (RG) is the intended cooked format (`uzcook.cpp` lines 219-224; `docs/runtime/asset-loading.md`).

**Fact (inconsistency to design around)** — The shader reads opacity from the **alpha** channel of the opacity texture, but `uzcook` compresses files named `opacity/alpha/mask` to **BC4 (single R channel)** (`runtime/tools/uzcook.cpp` lines 276-281). A BC4 opacity map therefore reads as alpha = 1. **Recommendation:** export opacity in the base-colour alpha channel (BC7 RGBA) or keep an RGBA8/BC7 opacity texture whose alpha carries the mask.

### 2.2 GBuffer layout the preview writes (for completeness)

**Fact** — `gbuffer_ps.hlsl` lines 304-310: RT0 `albedo.rgb + ao`, RT1 `OctEncode(N).xy + metallic + roughness`, RT2 `positionWS + customW`, RT3 `emissive.rgb + packed(specular, shadingModelID)`. Specular AA (Kaplanyan) is applied to roughness (lines 220-229).

## 3. Scalar parameters and flags (what the preset must also write)

**Fact** — `material_asset.h` lines 321-471 and the scene-loader JSON keys (`scene_loader.cpp` lines 764-852):

| JSON key (scene `material` component) | Field | Default |
|---|---|---|
| `albedo`, `normal`, `roughness`, `metallic`, `ao`, `emissive`, `orm` | texture paths (VFS-relative) | "" |
| `baseColorR/G/B` | `baseColorTint*` | 1,1,1 |
| `roughnessMultiplier`, `metallicMultiplier`, `normalIntensity`, `aoIntensity` | — | 1.0 |
| `specular` | F0 = 0.08 × specular | 0.5 (F0 0.04) |
| `transmission`, `ior`, `thicknessScale` | glass | 0, 1.5, 0.5 |
| `emissiveColorR/G/B`, `emissiveIntensity` | — | 0 |
| shading model string (`DefaultLit`, `Subsurface`, `ClearCoat`, `Cloth`, `ThinTranslucent`, …) | `EShadingModel` (10 values, `renderer/material/material_types.h`) | DefaultLit |
| blend mode | `EBlendMode` Opaque/Masked/Translucent/Additive/Modulate; auto-detected from transmission (`scene_loader.cpp` line 790 comment) | Opaque |
| `twoSided`, `alphaTest`, `alphaClipThreshold` | flags | false, false, 0.3333 |
| `uvScaleX/Y`, `uvOffsetX/Y` | UV transform | 1,1,0,0 |
| `envMultiplier`, `clearCoat`, `clearCoatRoughness`, `sheenColor*`, `sheenRoughness`, `subsurfaceColor*`, `subsurfaceRadius` | extended models | see header |

**Fact** — Fallback colour convention: `.rulebook/decisions/009-fallback-texture-color-convention-for-pbr-materials.md` states "all fallback textures are WHITE … exceptions: normal = flat blue, displacement = black"; `material_asset.h` comments say metallic/emissive fallback is black. In code, `SceneRenderer::LoadTexture` binds only two placeholders — white or flat-normal (`scene_texture_assets.cpp` lines 124-136) — and the shader bypasses sampling when the slot index is 0 and uses the multiplier instead (`gbuffer_ps.hlsl` lines 170-183). **Recommendation:** always export a texture for every channel UzPainter authored and set multipliers to 1.0.

## 4. Colour-space rules

**Fact** — `MaterialInterface::DefaultSlotIsSRGB(slotName)` (`renderer/material/material_interface.h` lines 200-210): sRGB for `Albedo`, `BaseColor`, `Diffuse`, `Emissive`, `ScatterColor`, `SubsurfaceColor`, `FuzzColor`, `ClothColor`, `DetailAlbedo`; **everything else linear** (normal, roughness, metallic, AO, ORM, opacity, thickness, heightmap, mask, tangent, clearcoat). Applied at texture load (`scene_sync.cpp` line 180; `scene_texture_assets.cpp` line 241).

**Fact** — Per-slot override field `srgbOverrides` with the documented JSON form `"textures": { "Albedo": { "srgb": true } }` exists on `Material` (`material_asset.h` lines 73-91), but no call site of `SetTextureSlotSRGB` was found in `engine/` (grep over `.cpp/.h`). **Hypothesis:** the override is not yet parsed from any file; rely on slot-name defaults.

**Fact** — Cooked `.uztexture` carries its own sRGB bit (`kUzTextureFlag_sRGB = 0x1`, `engine/asset/formats/uztexture_format.h`), mapped by `TextureFormatToRHI(fmt, isSRGB)` to `RGBA8Srgb/BC1Srgb/BC3Srgb/BC7Srgb`; BC4/BC5 are always linear.

## 5. On-disk formats

### 5.1 Source image formats accepted at runtime

**Fact** — PNG via spng (SIMD) and `PngCodec` (libpng, 8/16-bit, sRGB chunk), JPEG via libjpeg-turbo, TGA/BMP/PSD/GIF/HDR via stb_image, EXR via tinyexr → RGBA16F, KTX2 (UASTC HDR/LDR, ETC1S, Zstd supercompression) via basis_universal transcoder → RGBA16F, with Three.js CubeUV PMREM atlas detection (`runtime/thirdparty/README.md`; `renderer/upload/texture_loader_hdr.cpp`; `texture_loader_ktx2.cpp`; `texture_loader.h` `TextureLoadResult.isPMREM`).

### 5.2 Cooked runtime format `.uztexture` (v1)

**Fact** — `engine/asset/formats/uztexture_format.h`:

| Field | Value |
|---|---|
| Magic | `0x5A585455` ("UZTX" LE) |
| Version | 1 |
| Header | 64 bytes: `magic, version, width, height, mipCount, format, flags, reserved[9]` |
| `format` enum | `0 Uncompressed_RGBA8`, `1 BC1`, `2 BC3`, `3 BC5`, `4 BC7`, `5 BC4` |
| `flags` | bit 0 = sRGB; bit 1 reserved (cubemap); others 0 |
| Mip table | `mipCount × 24 bytes {offset u64, size u64, width u32, height u32}` |
| Mip data | tightly packed, mip 0 first, down to 1×1; BC size `ceil(w/4)*ceil(h/4)*{8|16}` |
| Dimensions | 2D only (no array/cube/3D/float fields) |
| Writer/reader | `WriteUzTexture(header, mips)`, `ReadUzTexture(bytes)` |
| Runtime discovery | `foo.png` → probe `foo.uztexture` first (`docs/runtime/asset-loading.md`; `scene_texture_assets.cpp` lines 150-163); upload via `TextureLoader::LoadUzTexViaRing` |

**Fact** — Not representable in `.uztexture` v1: BC6H, 16-bit UNORM, float formats, cubemaps/arrays, no-mip textures with `mipCount` > chain length. HDR emissive therefore has to stay LDR (BC7 sRGB) or be shipped as EXR/KTX2 through the raw path.

### 5.3 Compression and mip policy of the cooker

**Fact** — `engine/asset/importers/texture_importer.cpp` (importer version 2): decode via spng (PNG) or stb_image forced RGBA8 (lines 254-271, 27) → full mip chain to 1×1 by 2×2 box filter (`BoxFilterDownsample`, lines 39-53, 360-371) → per-mip etcpak compression `CompressBc1/Bc3/Bc4/Bc5/Bc7` with 4×4 padding (lines 107-181); BC7 uses `bc7enc_compress_block_params_init` defaults (lines 178-181). No Kaiser filter, no sRGB-aware averaging, no alpha-coverage preservation, no max-size clamp (the "Planned" design in `docs/engine/08-resource-system/07-texture-pipeline.md` describes those but the code does not implement them). 16-bit PNG input is decoded as `SPNG_FMT_RGBA8` (**Hypothesis:** truncated to 8-bit).

**Fact** — `uzcook` CLI: `uzcook --source <dir> --output <dir> [--pak <name>] [--textures-only] [--no-compress] [--verbose]` (`runtime/tools/uzcook.cpp` lines 8-18, 62-100). Companion `.uztexture` written next to the source, gitignored, incremental via `.uzimport` xxHash64 sidecars.

**Fact** — Filename-driven format selection (`uzcook.cpp` `SelectTextureFormat`, lines 162-287), checked in this order:

| Filename contains | Format | sRGB |
|---|---|---|
| `albedo`, `basecolor`, `diffuse`, `col` | BC7 | yes |
| `orm` | BC7 | no |
| `normal`, `nrm`, `norm` | BC5 | no |
| `emissive`, `emission` | BC7 | yes |
| `metallicroughness`, `metallic_roughness`, `metalroughness`, `roughnessmetallic`, `roughness_metallic` (glTF packed, G=rough, B=metal) | BC7 | no |
| `roughness`, `rough` | BC4 | no |
| `metallic`, `metal`, `metalness` | BC4 | no |
| `ao`, `ambientocclusion`, `occlusion` | BC4 | no |
| `opacity`, `alpha`, `mask` | BC4 | no (see §2.1 inconsistency) |
| anything else | BC7 | yes |

## 6. Normal map and tangent-space convention

| Aspect | Finding | Evidence | Tag |
|---|---|---|---|
| Space | Tangent space; `B = cross(N, T) * tangent.w`; `N = normalize(mul(normalTS, TBN))` with `TBN = float3x3(T, B, N)` | `gbuffer_ps.hlsl` lines 200-214 | **Fact** |
| Channels | `xy` from RG, Z reconstructed; blue ignored; `normalIntensity` scales xy | same | **Fact** |
| Tangent generation (cooked importers) | MikkTSpace (`ComputeMikkTSpaceTangents`) in `fbx_importer.cpp` line 1579 and glTF `mesh_importer.cpp` line 558; wrapper `engine/asset/mesh/mikktspace_tangents.h` ("compatible with normal maps baked in Blender, Substance, xNormal") | **Fact** |
| Tangent generation (standalone tools) | Lengyel UV-edge accumulation + Gram-Schmidt (`renderer/mesh/mesh_tangents.cpp`) in `uzmesh.cpp` line 1091, `uzfbx.cpp` 208, `uzgltf.cpp` 203 — **not** MikkTSpace despite `uzmesh --help` text claiming "MikkTSpace tangent generation" (line 1285) | **Fact** |
| UV origin | Top-left (DirectX convention) per `VertexPosNormUV` doc (`uzmesh_format.h`); FBX importer flips V (`1 - v`, `uzfbx.cpp` lines 150-153); glTF UVs copied unchanged (glTF is also top-left) | **Fact** |
| Green channel orientation (OpenGL +Y vs DirectX -Y) | **Not confirmed by code.** No flip of `.g` anywhere in the shader. The CHANGELOG v0.6.0 records the DamagedHelmet glTF sample rendering through the glTF path; glTF mandates OpenGL-style +Y normal maps with MikkTSpace tangents. | **Hypothesis:** the engine expects **OpenGL (+Y) tangent-space normal maps** for MikkTSpace-imported meshes. **Recommendation:** validate with a one-off calibration render (known hemisphere normal map, both conventions, compare lit result) before freezing the preset. |
| Handedness/winding | Left-handed, Z-up, X-forward, centimetres; CCW front faces (`frontCounterClockwise = true`) | `renderer/mesh/mesh.h` header comment; `rhi_types.h` line 557; `uzfbx.cpp` lines 85-90 | **Fact** |

## 7. `.uzmat` graph essentials (for emitting a material file)

**Fact** — `docs/engine/12-rendering/16-material-system.md` + `engine/material/defaults/default_lit.uzmat`:

- JSON: `{ "version":1, "name", "domain":"Surface", "shadingModel":"DefaultLit", "expressions":[ { "id", "type", "pos", "inputs":[{"pin"|"dstPin", "srcExpr", "srcPin"}], "scalarParams", "stringParams" } ] }`; node id 1 must be `PBROutput`.
- `PBROutput` pins: 0 BaseColor (Float3), 1 Metallic, 2 Roughness, 3 Normal (tangent space), 4 Emissive, 5 Opacity, 6 AO (`scene_loader.cpp` lines 568-576).
- `TextureSample` / `TextureParameter`: `stringParams.texturePath` resolved relative to the `.uzmat` directory (`material_manager.cpp` lines 277-294, 315-321); outputs `RGBA, R, G, B, A` (+ aliases `RGB/XYZ/XY` since v0.9.4); generated HLSL samples `Texture2D<float4> … = ResourceDescriptorHeap[getTexIndex(slot)]; …Sample(linearSampler, uv)` (`hlsl_material_translator.cpp` lines 404-411); texture SRV indices occupy `materialParams[0..3]`, user params `[4..15]` (`gbuffer_ps.hlsl` lines 76-94).
- Expression families: constants, 20 math ops, `TexCoord(uvIndex)`, world/object position, vertex normal/colour, camera vector, screen position, time, `CheckerPattern`, `NoisePerlin`, `GradientLinear/Radial`, `TriPlanarMapping`, `Fresnel`, `Panner`, `ComponentMask`, `Append`, `Scalar/Vector/TextureParameter` (37 types; ids 0/100/200/300/400/500/600/700 blocks in `material_expression.h`).
- Scene loader maps a graph's `TextureSample` → `PBROutput` routing into the fixed slots, including ORM detection (`uzmatHasOrm`, `scene_loader.cpp` lines 764-775).

## 8. Recommended UzPainter → UzEngine export preset (derived from the facts above)

| UzPainter channel | File to write | `.uztexture` format | Colour space | Channel packing | Material binding |
|---|---|---|---|---|---|
| Base colour (+ opacity if masked) | `<name>_albedo.png` | BC7 | sRGB | RGB = colour, A = opacity | `albedo` / `TextureSample.RGB → BaseColor` |
| Normal | `<name>_normal.png` | BC5 | linear | RG = XY (+Y convention to be confirmed), B written as reconstructed Z for other consumers | `normal` |
| AO / Roughness / Metallic | `<name>_orm.png` | BC7 (linear) | linear | **R = AO, G = Roughness, B = Metallic** (same order as Unreal "ORM" and glTF G/B) | `orm` (sets `useORM`) |
| or separate maps | `_roughness`, `_metallic`, `_ao` | BC4 each | linear | R | `roughness`, `metallic`, `ao` |
| Emissive | `<name>_emissive.png` | BC7 | sRGB | RGB LDR; HDR intensity via `emissiveIntensity` | `emissive` + `emissiveColor/Intensity` |
| Height | `<name>_height.png` | BC4 | linear | R | heightmap slot (POM) — binding key in JSON **not confirmed** (`heightmapSrvIndex` exists in CB; loader key not located) |
| Opacity standalone | avoid BC4; use RGBA with alpha | BC7/RGBA8 | linear | A | `opacity` |
| Thickness | `<name>_thickness.png` | BC4 | linear | R | `thickness` |

Plus: write PNG sources (8-bit; 16-bit height via `PngCodec` if the engine's cooker is bypassed) and generate `.uztexture` companions directly with `TextureImporter`/`WriteUzTexture` + etcpak (same code `uzcook` uses), and emit either a scene `material` component block or a `.uzmat` graph. Mip chains must be complete (importer always builds full chains; the loader validates `mipCount ≤ floor(log2(max(w,h)))+1`).
