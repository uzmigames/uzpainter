# 04 — UzEngine Material and Texture Standard (the UzPainter "UzEngine export preset")

Scope: exactly what a UzEngine material consumes — texture slots, channel packing, colour space, normal-map convention, on-disk/runtime formats, block compression, mip policy, and the JSON that references them. Paths relative to `E:\UzmiGames\UzEngine\`.

**Baseline** (added after the Astra review, see `10-review-response.md`): line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27); the working tree is mid-merge with `9220973`, and `scene_loader.cpp` line numbers shift by +77 there. Source reading only; no material, cook or render was executed.

## 1. Three material descriptions coexist — pick the right target

| Representation | Where | Loaded by | Status |
|---|---|---|---|
| **Fixed-PBR `Material` asset** (C++ struct with named texture slots + scalars) | `runtime/engine/renderer/material/material_asset.h`, base `material_interface.h` | Scene JSON `material` component (`engine/ecs/loaders/scene_loader.cpp` lines 757-852), decal component, Lua `uz.scene.set_material` | **Fact** — the path the GBuffer shader actually samples (`shaders/runtime/gbuffer/gbuffer_ps.hlsl` "Fixed PBR path") |
| **Node-graph `.uzmat`** (JSON `expressions[]` with `PBROutput` id 1) | `runtime/engine/material/material_graph.h`, defaults `engine/material/defaults/default_lit.uzmat` | `MaterialManager::LoadMaterial`, compiled by `HlslMaterialTranslator` and injected into `gbuffer_ps.hlsl` under `UZ_MATERIAL_GRAPH`; the scene loader also *flattens* a `.uzmat`'s `TextureSample` paths into the fixed `Material` slots (`scene_loader.cpp` lines 536-600, 740-775) | **Fact** — implemented ("Phase 1.5+ GPU integration", `docs/engine/12-rendering/16-material-system.md`) |
| **`.uzmaterial` JSON Schema** (`shader`, `render_state`, `textures{slot:{asset,sampler,uv_channel,tiling,offset}}`, `parameters`, `defines`, `shader_graph{nodes,connections}`) | `runtime/schemas/uzmaterial.schema.json` | **No loader for the schema's shape.** A different, minimal `.uzmaterial` reader exists in the scene loader: a `material` component with an `"asset"` field reads `textures.{base_color_map, normal_map, metallic_roughness_map, roughness_map, metallic_map, ao_map}` and `properties.{roughness, metallic, normal_strength}` (`scene_loader.cpp` lines 659-704). It routes `metallic_roughness_map` to the **ORM** slot with `useORM = true`, so that map's R channel is read as AO. The graph shape (`nodes/connections` vs `expressions/inputs`) differs from `.uzmat` | **Fact** — schema and the scene-loader subset both exist; **Hypothesis** — the full schema is aspirational/stale |

**Recommendation** — UzPainter's "UzEngine preset" should emit (a) texture files + `.uztexture` companions and (b) a `.uzmat` graph **or** inline scene `material` component fields, never the `uzmaterial.schema.json` shape.

## 2. Texture slots the renderer understands

**Fact** — Slot list enumerated by `SceneRenderer` when loading a material: `"Albedo", "Normal", "Roughness", "Metallic", "Ao", "Emissive", "ORM", "Thickness", "Opacity", "DetailAlbedo", "DetailNormal", "ClearCoatNormal", "Tangent", "Heightmap"` (`engine/renderer/scene/scene_texture_assets.cpp` lines 231-235). `Material` fields in `material_asset.h` lines 287-300, 410-429: `albedoPath, normalPath, roughnessPath, metallicPath, aoPath, emissivePath, opacityPath, ormPath (+useORM), thicknessPath, clearCoatNormalPath`; `heightmapSrvIndex` and POM parameters live in `PerObjectCB` (`gbuffer_ps.hlsl` lines 43-66). The inline scene `material` component sets only `albedo, normal, roughness, metallic, ao, emissive, orm` paths (§3); no inline key assigns `opacityPath`, `thicknessPath` or a heightmap (`scene_loader.cpp` lines 756-856).

### 2.1 Channel semantics as sampled by `gbuffer_ps.hlsl` (fixed-PBR path)

| Slot | Channels read | Shader evidence (`shaders/runtime/gbuffer/gbuffer_ps.hlsl`) | Colour space default | Fallback when unbound |
|---|---|---|---|---|
| Albedo / BaseColor | `.rgb` × `baseColorTint`; `.a` kept as `albedoAlpha` for alpha test | lines 139-154, 275-286 | **sRGB** | 1×1 white; shader uses tint only |
| Normal | `.rg` → `xy = rg*2-1`, `xy *= normalIntensity`, **`z = sqrt(1-dot(xy,xy))` reconstructed** (blue channel ignored → BC5-compatible) | lines 209-236 | linear | flat normal (128,128,255) placeholder |
| Roughness | `.r` × `roughnessMultiplier`; if no texture → `roughnessMultiplier` used directly | lines 170-176 | linear | none (multiplier) |
| Metallic | `.r` × `metallicMultiplier`; if no texture → multiplier | lines 177-183 | linear | none (multiplier) |
| AO | `.r`, then `ao = lerp(1, ao, aoIntensity)` | lines 184-187, 198 | linear | 1.0 |
| **ORM** (packed) | `materialFlags & 0x4` → one texture: **`ao = .r`, `roughness = .g`, `metallic = .b`** (overrides the three separates) | lines 165-169, 190-193 | linear | — |
| Emissive | `.rgb` × `emissiveColor` × `emissiveIntensity` | lines 248-258 | **sRGB** (`DefaultSlotIsSRGB`) | black (no emission) |
| Opacity | Masked only. SM6.6 bindless path: **`.a` of the opacity texture** when `opacitySrvIndex > 0`, else albedo alpha. SM5 path: always `.a` of the opacity texture at `t6`, albedo alpha not consulted. Graph path: the graph's Opacity output. Result compared with `alphaClipThreshold` | lines 272-294 | linear | albedo alpha (bindless path only) |
| Heightmap | `heightmapSrvIndex`, `displacementScale`, `pomMin/MaxLayers`, `pomFadeStart/End`, `pomSelfShadow` in `PerObjectCB` (POM implemented in `shaders/runtime/material/pom.hlsli`) | lines 60-65 | linear | black = no displacement (decision 009) |
| Thickness / ClearCoatNormal / Detail* / Tangent | loaded as slots; sampling locations not read in this analysis | `scene_texture_assets.cpp` 231-235 | linear | — |

**Fact** — Normal map Z reconstruction means the engine never needs the blue channel: BC5 (RG) is the intended cooked format (`uzcook.cpp` lines 219-224; `docs/runtime/asset-loading.md`).

**Fact (inconsistency to design around)** — The shader reads opacity from the **alpha** channel of the opacity texture, but `uzcook` compresses files named `opacity/alpha/mask` to **BC4 (single R channel)** (`runtime/tools/uzcook.cpp` lines 276-281). A BC4 opacity map therefore reads as alpha = 1. The fixed masked path above is the only consumer checked; forward/translucent paths were not read. A standalone opacity texture also has no inline scene-component key (§3). **Recommendation:** export opacity in the base-colour alpha channel (BC7 RGBA), the only route through the inline loader that this analysis found. That route works on the SM6.6 bindless path only; the SM5 path reads the opacity texture's alpha and ignores base-colour alpha (lines 287-289), and what it samples when no opacity texture is bound was not traced.

### 2.2 GBuffer layout the preview writes (for completeness)

**Fact** — `gbuffer_ps.hlsl` lines 304-310: RT0 `albedo.rgb + ao`, RT1 `OctEncode(N).xy + metallic + roughness`, RT2 `positionWS + customW`, RT3 `emissive.rgb + packed(specular, shadingModelID)`. Specular AA (Kaplanyan) is applied to roughness (lines 220-229).

## 3. Scalar parameters and flags (what the preset must also write)

**Fact** — `material_asset.h` lines 321-471 and the scene-loader JSON keys (`scene_loader.cpp` lines 756-856). Rows marked **not an inline key** are `Material` fields that this loader block does not read from the scene `material` component:

| JSON key (scene `material` component) | Field | Default |
|---|---|---|
| `albedo`, `normal`, `roughness`, `metallic`, `ao`, `emissive`, `orm` | texture paths (VFS-relative); a `.uzmat` graph path wins over the inline key for the first six (lines 760-769) | "" |
| `baseColorR/G/B` | `baseColorTint*` | 1,1,1 |
| `roughnessMultiplier`, `metallicMultiplier`, `normalIntensity`, `aoIntensity` | — | 1.0 |
| `specular` | F0 = 0.08 × specular | 0.5 (F0 0.04) |
| `transmission`, `ior`, `thicknessScale` | glass | 0, 1.5, 0.5 |
| `emissiveColorR/G/B`, `emissiveIntensity` | — | 0 |
| `shadingModel` string (`Unlit`, `Subsurface`, `ClearCoat`, `Cloth`, `ThinTranslucent` parsed; otherwise `DefaultLit`) | `EShadingModel` (10 values, `renderer/material/material_types.h`) | DefaultLit |
| `blendMode` string | `EBlendMode` Opaque/Masked/Translucent/Additive/Modulate; auto-detected from transmission (`scene_loader.cpp` line 790 comment) | Opaque |
| `twoSided`, `alphaTest`, `alphaClipThreshold` — **not inline keys** | flags; taken from `.uzmat` metadata (`twoSided`, `alphaClipThreshold`) or forced for Masked (`alphaTest = true`, threshold 0.3333) | false, false, 0.3333 |
| `uvScaleX/Y`, `uvOffsetX/Y` — **not inline keys** | UV transform | 1,1,0,0 |
| `envMultiplier`, `clearCoat`, `clearCoatRoughness`, `sheenColor*`, `sheenRoughness`, `subsurfaceColor*`, `subsurfaceRadius` — **not inline keys** | extended models | see header |

**Fact (defect)** — When a `.uzmat` graph routes ORM, the loader sets `ormPath` and `useORM` and clears the separate roughness/metallic/AO paths (lines 770-777), then unconditionally overwrites `ormPath` with `ReadString(comp, "orm")` (line 848), which returns an empty string when the inline key is absent (`ReadString`, lines 199-205); `useORM` stays true. **Hypothesis:** a graph-only ORM binding is lost in this path (visible effect not executed).

**Fact** — Fallback colour convention: `.rulebook/decisions/009-fallback-texture-color-convention-for-pbr-materials.md` states "all fallback textures are WHITE … exceptions: normal = flat blue, displacement = black"; `material_asset.h` comments say metallic/emissive fallback is black. In code, `SceneRenderer::LoadTexture` binds only two placeholders — white or flat-normal (`scene_texture_assets.cpp` lines 124-136) — and the shader bypasses sampling when the slot index is 0 and uses the multiplier instead (`gbuffer_ps.hlsl` lines 170-183). **Recommendation:** always export a texture for every channel UzPainter authored and set multipliers to 1.0.

## 4. Colour-space rules

**Fact** — `MaterialInterface::DefaultSlotIsSRGB(slotName)` (`renderer/material/material_interface.h` lines 200-210): sRGB for `Albedo`, `BaseColor`, `Diffuse`, `Emissive`, `ScatterColor`, `SubsurfaceColor`, `FuzzColor`, `ClothColor`, `DetailAlbedo`; **everything else linear** (normal, roughness, metallic, AO, ORM, opacity, thickness, heightmap, mask, tangent, clearcoat). Applied at texture load (`scene_sync.cpp` line 180; `scene_texture_assets.cpp` line 241). Two mechanisms override the slot default: a cooked `.uztexture` companion is probed first (`scene_texture_assets.cpp` lines 158-196) and its GPU format comes from the file's own sRGB flag, not from the slot request (`texture_loader_ring.cpp` lines 70-72); and the scene texture cache is keyed by path only (`scene_texture_assets.cpp` lines 108-143), so the first slot that loads a path fixes its interpretation for later slots. **Hypothesis:** reusing one file as both colour and data can therefore be decoded with the wrong transfer function (not executed).

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
| Mip data | tightly packed, mip 0 first; the cooker writes full chains down to 1×1, the format itself allows a partial chain; BC size `ceil(w/4)*ceil(h/4)*{8|16}` |
| Dimensions | 2D only (no array/cube/3D/float fields) |
| Writer/reader | `WriteUzTexture(header, mips)`, `ReadUzTexture(bytes)` |
| Runtime discovery | `foo.png` → probe `foo.uztexture` first (`docs/runtime/asset-loading.md`; `scene_texture_assets.cpp` lines 150-163); upload via `TextureLoader::LoadUzTexViaRing` |

**Fact** — Not representable in `.uztexture` v1: BC6H, 16-bit UNORM, float formats, cubemaps/arrays, no-mip textures with `mipCount` > chain length. HDR emissive therefore has to stay LDR (BC7 sRGB) or be shipped as EXR/KTX2 through the raw path.

**Fact** — Validation actually enforced: `ReadUzTexture` (`uztexture_format.cpp` lines 60-110) checks header size, magic, version, that the mip descriptor table fits, and `offset + size ≤ file size` per mip. It does **not** enforce the rules the header documents (`uztexture_format.h` lines 50-59, 163-179, 202-207): dimension limits, `1 ≤ mipCount ≤ floor(log2(max(w,h)))+1`, per-mip width/height/byte size, zero flags/reserved bits. The ring loader parses the header again (`texture_loader_ring.cpp` lines 45-110), casts `mipCount` to `uint16` (line 84) and silently `break`s when a mip blob lies outside the file (line 110). The `offset + size` additions are not overflow-guarded. These readers are not an integrity boundary for untrusted or generated files.

### 5.3 Compression and mip policy of the cooker

**Fact** — `engine/asset/importers/texture_importer.cpp` (importer version 2): accepted inputs are `.png`, `.jpg`, `.jpeg`, `.tga` only (line 215); decode via spng (PNG) or stb_image forced RGBA8 (lines 254-271, 27) → full mip chain to 1×1 by 2×2 box filter (`BoxFilterDownsample`, lines 39-53, 360-371) → per-mip etcpak compression `CompressBc1/Bc3/Bc4/Bc5/Bc7` with 4×4 padding (lines 107-181); BC7 uses `bc7enc_compress_block_params_init` defaults (lines 178-181). No Kaiser filter, no sRGB-aware averaging, no alpha-coverage preservation, no max-size clamp (the "Planned" design in `docs/engine/08-resource-system/07-texture-pipeline.md` describes those but the code does not implement them). 16-bit PNG input is decoded as `SPNG_FMT_RGBA8` (lines 260-262), so the cooked path does not preserve 16-bit source precision (**Fact**); the box filter averages the stored bytes directly (lines 54-80), i.e. sRGB-encoded values for colour maps.

**Fact** — `uzcook` CLI: `uzcook --source <dir> --output <dir> [--pak <name>] [--textures-only] [--no-compress] [--verbose]` (`runtime/tools/uzcook.cpp` lines 8-18, 62-100). Companion `.uztexture` written next to the source, gitignored, incremental via `.uzimport` xxHash64 sidecars.

**Fact** — Filename-driven format selection (`uzcook.cpp` `SelectTextureFormat`, lines 162-287), checked in this order:

| Filename contains | Format | sRGB |
|---|---|---|
| `basecolor`, `albedo`, `diffuse`, `_col_`, `_col.` | BC7 | yes |
| `_orm`, `orm_` | BC7 | no |
| `normal`, `_nrm`, `_norm` | BC5 | no |
| `emissive`, `emission` | BC7 | yes |
| `metallicroughness`, `metallic_roughness`, `metalroughness`, `roughnessmetallic`, `roughness_metallic` (glTF packed, G=rough, B=metal) | BC7 | no |
| `roughness`, `_rough` | BC4 | no |
| `metallic`, `metalness`, `_metal` | BC4 | no |
| `ambientocclusion`, `occlusion`, `_ao` | BC4 | no |
| `opacity`, `alpha`, `_mask` | BC4 | no (see §2.1 inconsistency) |
| anything else, including `height`, `thickness` and `specular`/`specularweight` (no rule matches them; lines 285-288) | BC7 | yes |

## 6. Normal map and tangent-space convention

| Aspect | Finding | Evidence | Tag |
|---|---|---|---|
| Space | Tangent space; `B = cross(N, T) * tangent.w`; `N = normalize(mul(normalTS, TBN))` with `TBN = float3x3(T, B, N)` | `gbuffer_ps.hlsl` lines 209-236 | **Fact** |
| Channels | `xy` from RG, Z reconstructed; blue ignored; `normalIntensity` scales xy | same | **Fact** |
| Tangent generation (cooked importers) | MikkTSpace via `ComputeMikkTSpaceTangents`; the wrapper's comment claims compatibility with Blender/Substance/xNormal bakes (a comment, not evidence). FBX: MikkTSpace is the default of CVar `r.Mesh.TangentMode` (0 = MikkTSpace, 1 = Lengyel, 2 = Import). glTF: computed, then discarded, because the cooked record is the 32-byte `VertexPosNormUV` (`05-…` §1). The wrapper writes one tangent per vertex index, so per-corner frames survive only when the input has one vertex per corner, as the FBX cooker builds | `fbx_importer.cpp` lines 32, 1446-1447, 1574-1584; `mesh_importer.cpp` line 558; `engine/asset/mesh/mikktspace_tangents.h`, `mikktspace_tangents.cpp` lines 63-73 | **Fact** |
| Tangent generation (standalone tools) | Lengyel UV-edge accumulation + Gram-Schmidt — **not** MikkTSpace despite `uzmesh --help` text claiming "MikkTSpace tangent generation" | `renderer/mesh/mesh_tangents.cpp`; `uzmesh.cpp` lines 1091, 1285; `uzfbx.cpp` 208; `uzgltf.cpp` 203 | **Fact** |
| UV origin | Top-left (DirectX convention) per the `VertexPosNormUV` doc; the FBX importers flip V (`1 - v`); glTF UVs copied unchanged (glTF is also top-left) | `uzmesh_format.h`; `uzfbx.cpp` lines 150-153; `fbx_importer.cpp` line 1478 | **Fact** |
| Green channel orientation (OpenGL +Y vs DirectX -Y) | What the code shows: green is the coefficient of `B = cross(N, T) * tangent.w` with no sign flip, Z reconstructed; `tangent.w` comes from MikkTSpace (FBX cook) or from the Lengyel sign `sign(dot(cross(N, T), B))` (standalone tools); the FBX importers flip V while the glTF importers keep `TEXCOORD_0` unchanged; the glTF cook stores no tangents. No engine code, doc or test states the expected convention. Which way green points in UV space therefore depends on the import path (V flip, axis remap, winding flip, tangent generator). The DamagedHelmet sample rendering (CHANGELOG v0.6.0) does not establish it. | `gbuffer_ps.hlsl` lines 209-236; `mesh_tangents.cpp` lines 149-158; `fbx_importer.cpp` line 1478; `uzfbx.cpp` lines 150-153; repository grep for normal-map/green-channel convention terms (no match) | **Not confirmed.** **Recommendation:** calibrate per import path with controlled reference surfaces (known hemisphere/bevel normal maps in both conventions, mirrored and non-mirrored UVs) before freezing the preset. |
| Handedness/winding | Left-handed, Z-up, X-forward, centimetres; CCW front faces (`frontCounterClockwise = true`) | `renderer/mesh/mesh.h` header comment; `rhi_types.h` line 557; `uzfbx.cpp` lines 85-90 | **Fact** |

## 7. `.uzmat` graph essentials (for emitting a material file)

**Fact** — `docs/engine/12-rendering/16-material-system.md` + `engine/material/defaults/default_lit.uzmat`:

- JSON: `{ "version":1, "name", "domain":"Surface", "shadingModel":"DefaultLit", "expressions":[ { "id", "type", "pos", "inputs":[{"pin"|"dstPin", "srcExpr", "srcPin"}], "scalarParams", "stringParams" } ] }`; node id 1 must be `PBROutput`.
- `PBROutput` pins: 0 BaseColor (Float3), 1 Metallic, 2 Roughness, 3 Normal (tangent space), 4 Emissive, 5 Opacity, 6 AO (`scene_loader.cpp` lines 568-576).
- `TextureSample` / `TextureParameter`: `stringParams.texturePath` resolved relative to the `.uzmat` directory (`material_manager.cpp` lines 277-294, 315-321); outputs `RGBA, R, G, B, A` (+ aliases `RGB/XYZ/XY` since v0.9.4); generated HLSL samples `Texture2D<float4> … = ResourceDescriptorHeap[getTexIndex(slot)]; …Sample(linearSampler, uv)` (`hlsl_material_translator.cpp` lines 404-411); texture SRV indices occupy `materialParams[0..3]`, user params `[4..15]` (`gbuffer_ps.hlsl` lines 76-94).
- Expression families: constants, 20 math ops, `TexCoord(uvIndex)` (the translator ignores `uvIndex` and always emits `uv`, `hlsl_material_translator.cpp` lines 420-422), world/object position, vertex normal/colour, camera vector, screen position, time, `CheckerPattern`, `NoisePerlin`, `GradientLinear/Radial`, `TriPlanarMapping`, `Fresnel`, `Panner`, `ComponentMask`, `Append`, `Scalar/Vector/TextureParameter` (37 types; ids 0/100/200/300/400/500/600/700 blocks in `material_expression.h`).
- Scene loader maps a graph's `TextureSample` → `PBROutput` routing into the fixed slots, including ORM detection (`uzmatHasOrm`, `scene_loader.cpp` lines 764-775).

## 8. Recommended UzPainter → UzEngine export preset (derived from the facts above)

| UzPainter channel | File to write | `.uztexture` format | Colour space | Channel packing | Material binding |
|---|---|---|---|---|---|
| Base colour (+ opacity if masked) | `<name>_albedo.png` | BC7 | sRGB | RGB = colour, A = opacity (consumed as mask on the SM6.6 bindless path only, §2.1) | `albedo` / `TextureSample.RGB → BaseColor` |
| Normal | `<name>_normal.png` | BC5 | linear | RG = XY (green convention **not confirmed**, §6), B written as reconstructed Z for other consumers | `normal` |
| AO / Roughness / Metallic | `<name>_orm.png` | BC7 (linear) | linear | **R = AO, G = Roughness, B = Metallic** (same order as Unreal "ORM" and glTF G/B) | `orm` (sets `useORM`) |
| or separate maps | `_roughness`, `_metallic`, `_ao` | BC4 each | linear | R | `roughness`, `metallic`, `ao` |
| Emissive | `<name>_emissive.png` | BC7 | sRGB | RGB LDR; HDR intensity via `emissiveIntensity` | `emissive` + `emissiveColor/Intensity` |
| Height | `<name>_height.png` | BC4 written directly with `WriteUzTexture` (`uzcook` would cook `_height` as BC7 sRGB, §5.3); BC4 is 8-bit and not equivalent to 16-bit authored height | linear | R | heightmap slot (POM) — **no inline scene key** (`heightmapSrvIndex` exists in CB); binding route **not confirmed** |
| Opacity standalone | avoid BC4; use RGBA with alpha | BC7/RGBA8 | linear | A | **not an inline scene key** (`Material.opacityPath` exists but the inline loader does not set it); use base-colour alpha unless another consumer is verified |
| Thickness | `<name>_thickness.png` | BC4 written directly with `WriteUzTexture` (`uzcook` would cook it as BC7 sRGB) | linear | R | **not an inline scene key**; binding route **not confirmed** |

Plus: write PNG sources (8-bit via `PngCodec::EncodeFile`; 16-bit height via `PngCodec::EncodeMemory` + file write, only if the engine's cooker is bypassed, because the cooker decodes to RGBA8) and generate `.uztexture` companions directly with `TextureImporter`/`WriteUzTexture` + etcpak (same code `uzcook` uses), and emit either a scene `material` component block or a `.uzmat` graph. Write full mip chains to match the cooker's policy; the readers do **not** validate `mipCount` against the chain length (§5.2), so the exporter must. **Recommendation:** keep canonical authored/baked channel data at full precision independently of these lossy runtime derivatives, and require an end-to-end write → load example through the chosen consumer for every key and channel before accepting this preset.
