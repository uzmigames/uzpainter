# 08 — Export

Implements D7 (`05-resolution.md`) and owner answers Q10 (decision 023: UE 5.6 with PNG/TGA by default and optional DDS BC7/BC5; UzEngine `.uzmat` + compressed `.uztexture`; SpecularWeight reported as a consumer gap) and Q8 (decision 021: UzEngine formats are written by UzPainter's own code, with no engine link). Requirements: EXP-01…10, INT-11, INT-13, INT-21, QG-03 (`docs/prd.md`). Painter facts: the public `export` API documentation and Adobe's public output-template help pages (`docs/analysis/substance-parity/04-export.md` is quarantined, historical context only); engine facts: `docs/analysis/uzengine-renderer/04-material-and-texture-standard.md`, `10-review-response.md`.

## 1. Configuration

`export.export_project_textures(json_config)` and `list_project_textures(json_config)` accept Painter's dictionary verbatim: `exportPath`, `exportShaderParams`, `defaultExportPreset` (name or `resource://` URL), `exportPresets[].{name, maps[].{fileName, channels[].{destChannel, srcChannel, srcMapType, srcMapName}, parameters}}`, `exportList[].{rootPath ("<set>" or "<set>/<stack>"), filter.{outputMaps, uvTiles}, exportPreset}`, `exportParameters[].{filter.{dataPaths, outputMaps, uvTiles}, parameters.{fileFormat, bitDepth, dithering, sizeLog2 (int or [w,h]), paddingAlgorithm, dilationDistance}}`, wildcards `$project $mesh $textureSet $sceneMaterial $colorSpace $udim $uvTileName` with `( … )` optional groups; `srcMapType ∈ {documentMap, meshMap, virtualMap, defaultMap}` with the documented names; `{}` matches all and `{"dataPaths": []}` matches nothing; resolution order = preset parameters, then `exportParameters` rules in list order; every parameter must be defined after resolution or the config is invalid.

The configuration is **compiled into a typed export plan** before any GPU work: every output file with its resolved sources, parameters, size, naming and target format. Unknown identifiers (e.g. the pipeline's `Mixed_AO`, which crashed Painter — the documented name is `AO_Mixed`) are rejected here with the valid alternatives. `list_project_textures` returns the plan; the MCP `export` tool exposes it as the dry run.

Implemented in `src/export/` (`phase1.15_export-plan-compiler`, decision 085; `src/export/EXPORT.md`). The rules the documentation leaves open were decided by the Tier 0 recordings: the dry run of every recorded export step lists exactly the files Painter wrote (`parity/reports/phase1/export-plan-compiler.md`). A `documentMap` the stack lacks makes its map absent (no file), as does a map made only of `defaultMap white`. Legacy names read their OpenPBR member when the stack lacks the legacy one. Every case no recording covers fails with `NotYetSupported` before anything is written, naming recording R-085. The evaluator's own limits stay with it: the export evaluates every planned file before it writes any. The Python surface (`uzpainter.export.plan`, `list_project_textures`) is `phase1.19_pyapi-native-module` item 2.7.

## 2. Virtual maps

`Normal_OpenGL`, `Normal_DirectX` (mesh normal ⊕ channel normal ⊕ height-derived normal, `04-layer-stack-and-compositing.md` §6, tagged `combined`), `AO_Mixed`, `Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `f0`, `View_2D` — definitions from Adobe's public output-template documentation (the `export.html` API page and the help pages), operators fitted and confirmed in Tier 0 against private oracles. A geometry-only normal pass-through is exported through `meshMap normal_base` (EXP-01).

Supported today (decisions 086, 092, `parity/semantics/virtual-maps.json`): `Normal_OpenGL` and `Normal_DirectX`, exact through the plan. On a texture set whose UV islands do not cover the tile, their island-edge texels read the Height outside the islands, where Painter's Height is not reproduced. There they are refused before writing, under every padding, a Height without layers included, and so is every diagnosticMap that isolates, compares or summarises one (decision 245). `AO_Mixed` and the ten converted maps are release gaps, refused before writing. `AO_Mixed`'s best model misses r1 at 31 values of recording R-086a; its exact fit is `phase3.2_unreal-ue56-packed-preset` item 2.10 (decision 131). Nine converted maps are fitted exactly but wait on per-texel channel coverage from the evaluator; `View_2D` has no operator (decision 092).

## 3. Formats and processing

| Step | Rule |
|---|---|
| Padding | `passthrough`, `color`, `transparent`, `diffusion`, `infinite` + `dilationDistance`; implemented as compute passes over the coverage mask; behaviour fitted to Painter in Tier 0 |
| Resize | `sizeLog2` scalar keeps aspect; `[w,h]` does not; filter fitted in Tier 0 |
| Dithering | Explicit per map; algorithm fitted in Tier 0 (Painter's export dithering is not documented) |
| Bit depth / colour | `8`, `16`, `16f`, `32f` as the format allows; colour-managed channels encoded sRGB, data channels linear; the project's colour configuration decides `$colorSpace` |
| PNG | 8/16-bit through UzPainter's own encoder over the vendored zlib (decision 089: it writes Painter's bytes; libpng is not vendored, spng stays the decoder; UzEngine's 8-bit-only PNG file encoder is not used, `13-engine-integration.md` §2.4); fixed filter choice, zlib level and strategy for byte determinism |
| EXR | 16f/32f via tinyexr (PIZ, Painter's bytes with OpenEXR's Huffman tie-break as the one recorded local change, decision 089) |
| TGA/BMP/JPEG | stb / libjpeg-turbo (8-bit) |
| DDS | Own header writer + etcpak BC1/BC3/BC4/BC5/BC7 (CPU, deterministic, behind an encoder adapter; bc7enc_rdo is the replacement candidate) |
| Not in v1 | TIFF, PSD, WebP, J2K/JP2, PGM, JNG, `sbsar` — listed as release gaps in the capability manifest; requesting them raises before writing anything |

Implemented in `src/export/` (`phase1.16_export-processing-encoders` and `phase1.18_export-engine`, decisions 089, 090 and 103; `src/export/EXPORT.md` §4).

- **Exact in the recorded domain.**
  - Painter's PNG and OpenEXR files re-encode byte for byte (8-bit grey PNGs choose among all five row filters with zlib's default strategy, every other layout among None, Sub and Paeth with Z_FILTERED).
  - PNG 8 and 16 (UNORM write rule; Height written as v * 0.5 + 0.5; an sRGB8 BaseColor, Specular or Emissive as the GPU sRGB encode of its linear value, decision 126, and an L8 one the same but its G, which holds the linear write, decision 204), OpenEXR 16f (half rounded toward zero) and 32f; L+A and RGB+A, an alpha of 1 everywhere dropped; dithering at PNG 16 (no change); the AO, Curvature and Position mesh maps passed through.
  - The recorded PNG 16 and OpenEXR 32f exports, written end to end, equal Painter's files where the UV islands cover the tile.
  - `passthrough` on islanded sets writes the evaluated values.
- **Not exact, refused before writing** (decision 259; owner `phase1.25_pilot-wand` item 2.7): `infinite` on islanded sets. Decision 223 wrote it under exception EXC-007, which let the padding texels differ from Painter's. The owner withdrew that exception ("every texel identical"), so the export refuses it again, naming R-090, until the rule is exact. Decision 223's coverage-only rule (`src/export/padding.h`) is kept for measurement only. A virtual normal is refused there first, as under every padding (decision 245).
- **Recorded but not fitted, refused before writing** (decision 103; owner `phase3.2_unreal-ue56-packed-preset`): dithering at PNG 8 and in OpenEXR, resize (partly fitted), and the `color`, `transparent` and `diffusion` paddings. Also refused: a file depending on a template base inferred from its PNG export only (none ships since decision 169), an sRGB8 channel other than User, BaseColor, Specular and Emissive (decision 126), and a PNG of an L8 BaseColor, Specular or Emissive under OCIO or outside the RGB and L files of the one channel (decision 204).

## 4. Presets

Shipped as UzmiGames-authored JSON presets in `assets/export-presets/`, written in the export-configuration form documented in `export.html`.

**Provenance — no decoded Adobe preset data.** Each preset is defined from Painter's documented export behaviour (the `export.html` API page and Adobe's public output-template help pages) and confirmed against observed outputs: the files Painter writes for that preset on a UzmiGames fixture project, and what the documented `ResourceExportPreset.list_output_maps()` / `PredefinedExportPreset.list_output_maps(stack)` return there. Those observations are private oracle records (`14-parity-testing.md` §6). The shipped JSON is written by hand from the documented semantics and the observed behaviour, never generated by serialising a readback; renaming or reformatting a readback does not qualify it for publication. Adobe's binary `.spexp` files are neither parsed nor shipped (`docs/licensing-and-clean-room.md`), and the historical decoding in `04-export.md` §7 is historical context, not a source. Every shipped preset has a provenance record `assets/export-presets/<preset>.provenance.json` — `{preset, version, author, date, public sources (page and section), observed-output fixtures (SHA-256 of the private records), packing decisions with their source, parity status}` — and passes output-parity tests against the private oracle before it ships.

Presets, by the Painter name they answer to (resolved through the compatibility alias table, so `defaultExportPreset` keeps working): `PBR Metallic Roughness`, `Blender (Principled BSDF)` (the pipeline's preset), `Unreal Engine (Packed)`, `Mesh Maps`, `glTF PBR Metal Roughness`. UzmiGames' own pipeline presets, whose provenance is the pipeline script: the Assets3D inline five-map preset (`A3D\Pipeline\retopology\staff-v10\painter_export.py`) and its hat v8 variant that adds SpecularWeight (`hat-v6\painter_export_v8.py`). The UzEngine preset below. Further presets are added on the same evidence and provenance rule.

Implemented in `src/export/preset_aliases.{h,cpp}` and `assets/export-presets/` (`phase1.17_export-presets`, decision 095; `src/export/EXPORT.md` §5):

- `assets3d-inline-five-map` is the pipeline's inline preset. It writes BaseColor sRGB-encoded (decision 126).
- `pbr-metallic-roughness` and `blender-principled-bsdf` answer to their Painter names and `resource://starter_assets/` URLs through the alias table. They are refused until recording R-095 confirms their layouts.
- `gltf-pbr-metal-roughness` answers to `glTF PBR Metal Roughness` and `export-preset-generator://gltf`. R-314 confirms the four-map layout and PNG8 defaults (normal dithering enabled, other maps disabled); padding must be supplied explicitly. SpecularWeight is a supplemental UzPainter map with authored PNG8/no-dithering defaults and a consumer-gap receipt (decision 023), with no Painter counterpart. Pipeline parameters override these defaults. Full texture parity remains pending on AO_Mixed, padding, dithering and pilot acceptance (`phase3.1_unreal-gltf-pbr-preset`, decision 314); the texture preset does not generate glTF/GLB scenes.
- Full output parity moved from `phase1.18_export-engine` item 6.2 to `phase3.3_unreal-gltf-presets` item 3.5 (decision 103).

### Unreal Engine (Packed)

`$mesh_$textureSet_BaseColor` RGB=basecolor A=opacity; `_OcclusionRoughnessMetallic` R=`AO_Mixed` G=roughness B=metallic (linear); `_Normal` = `Normal_DirectX`; `_Emissive`. This layout is stated as behaviour and ships only once the preset's provenance record confirms it. Target UE 5.6 (owner Q10): default encoding PNG/TGA 8-bit; optional DDS BC7 (BaseColor, ORM, Emissive) and BC5 (Normal). UE 5.6 documents DDS 2D import; BC pass-through through cooking is not documented (`technology-options/05-review-response.md` finding 13), so "already compressed" means compact interchange until the Unreal consumer fixture (§5.1) proves otherwise. SpecularWeight is exported as a separate `_SpecularWeight` map when the channel exists and reported in the receipt as a **consumer gap**: the stated mapping `Specular = 0.5 × SpecularWeight` (hat v8 report) belongs to the consumer's material and is not executed by the export.

Implemented in `assets/export-presets/unreal-engine-packed{,-dds}.json` and `src/export/` (decision 322; `src/export/EXPORT.md` §5). Both presets are refused until recording R-322 confirms the layout. The DDS variant is the separate preset `unreal-engine-packed-dds`: PNG 16 maps with DDS companions. The native TGA8 writer accepts explicitly quantized L/LA/RGB/RGBA bytes through pinned stb; Painter export configuration stays refused until R-322 establishes its TGA processing and files.

### UzEngine preset

Target UzEngine (owner Q10): `.uzmat` plus compressed `.uztexture`. Both formats are written by UzPainter's own code from the format definition (`13-engine-integration.md` §2); no UzEngine library is linked or called (owner Q8).

| Output | Source | File | `.uztexture` | Colour | Binding |
|---|---|---|---|---|---|
| `<set>_albedo` | basecolor RGB + opacity A | PNG8 | BC7 sRGB | sRGB | `albedo`; opacity in alpha because the bindless fixed-PBR path reads `.a` and the SM5 path never reads albedo alpha as opacity (`10-review-response.md` §7) — the SM5 route is reported unsupported for opacity |
| `<set>_normal` | virtual normal in the convention proven by the Phase 0 fixture | PNG8/16 | BC5 | linear | `normal`; negative-Z texels are detected and the export fails or routes to an RGB format (information would be lost by Z reconstruction) |
| `<set>_orm` | `AO_Mixed`, roughness, metallic | PNG8 | BC7 | linear | `orm` (R=AO, G=roughness, B=metallic; `gbuffer_ps.hlsl` fixed-PBR path) |
| `<set>_emissive` | emissive | PNG8 | BC7 sRGB | sRGB | `emissive` |
| `<set>_height` | height | PNG16 + sidecar | BC4 | linear | heightmap slot; explicit format metadata (the cooker's default rule would make it BC7 sRGB) |
| `<set>_specularweight` | SpecularWeight | PNG8/16 | BC4 | linear | no engine slot: exported and reported as a **consumer gap** in the receipt |
| `<set>.uzmat` | — | JSON | — | — | `TextureSample → PBROutput` pins 0..6; inline scene material block also written |

`.uztexture` companions are written by UzPainter's own `.uztexture` writer, with etcpak BC encoding and full mip chains generated in UzPainter: sRGB-aware filtering for colour, renormalised normals, alpha-coverage-preserving for masked albedo. Canonical 16-bit/float maps are always written beside the cooked derivatives (EXP-10). The preset is validated by the external UzEngine consumer fixture (§5.1: UzEngine's own executable loads the `.uzmat` and `.uztexture` files in a test scene, `07-preview-and-render-parity.md` §1); UzPainter links no UzEngine code for it.

## 5. Determinism and verification

- Export reads a revision snapshot. The receipt records `{revision, generation, evaluator_profile, plan hash, per file: path, bytes, sha256, format, bit depth, colour space, size, preset, channel mapping, normal tag (geometry_only|combined + relief round), consumer gaps}`. It also records the manifest export block (INT-21) in the form of Assets3D's `manifest-schema-v2.json` `$defs/export`: `sources`, `outputs`, `moment`, `preset`, `maps`, `comparison`, `evidence`, `open_items`. That block replaces schema v1's `exportacao` (`fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias`), which Assets3D retired (decision 097).
- **Generational publication (EXP-06).** Every file and the receipt are written into a new generation directory under `exportPath`, flushed and verified against the plan (size and SHA-256 per file), then published by one atomic durable update of the delivery pointer (`current.json`: written to a temporary file, flushed, renamed over the old pointer). A failure at any step leaves the previously published generation selected; incomplete generations stay unreferenced and are listed and removable by `UzPainter.exe export --recover`.
- **Fixed file names.** Every supported consumer reads one complete published generation. A fixed-name consumer (Unreal import, the Assets3D scripts of §5.1) runs through a delivery adapter that pins that generation, or under a coordinated publication lock that completes recovery before consumption and excludes writers for the entire read; fixed-name copies are journalled (`{generation, files[], copied[]}`) so that this recovery can roll them forward. Staging filenames are not advertised as a committed delivery. A raw fixed-name directory updated by separate copies is not an atomic delivery and cannot satisfy EXP-06.
- Fault tests interrupt between every step (each file, the receipt, the pointer, each fixed-name copy) and verify that a consumer reading the pointer sees either the old or the new complete generation, and that recovery completes or discards the interrupted one. After interrupting each fixed-name copy, the test immediately invokes each supported fixed-name consumer through its prescribed adapter: it must consume one complete generation or fail before consumption; deferred recovery on a later export is insufficient.
- Implemented in `src/export/` (`phase1.17_export-publication-receipts`, decision 097; `src/export/EXPORT.md` §6).
  - **Layout.** The pointer is `exportPath/current.json`. Each generation is `exportPath/generations/<NNNNNN>/` with `files/`, `plan.json` and `receipt.json`. The lock is `exportPath/publication.lock`.
  - **Recovery.** `UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...` runs the recovery described above.
  - **End to end.** `UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>` exports a saved project's current revision and publishes it (`phase1.18_export-engine`, decision 104; `src/export/EXPORT.md` §7).
  - **Fixed-name routes.** The pinning adapter hands over the generation's `files/` directory. The alternative is a journalled fixed-name copy read under the lock.
  - **Receipt.** The receipt's ARC-11 `app_version` and `build` come from the caller.
  - **Paths.** The paths of the manifest block are relative to the generation. The pipeline adapter (`phase1.23_pyapi-pipeline-adapter`) rebases them under the Assets3D root.
- Same build + same project + same config ⇒ identical bytes (EXP-05 MUST); cross-machine identity is measured and reported (SHOULD).
- Dry run (`list_project_textures`) and result list the exact files; nothing is reported written that was not (QG-03).

### 5.1 Consumer matrix (INT-11)

Each consumer's script code runs **unchanged** on the UzPainter delivery; the script version is pinned by SHA-256 in the fixture. Its host adapter and invocation requirements (the generation-pinning delivery adapter or the publication lock of §5) are part of the consumer fixture. Paths are relative to `A3D\` (`E:\UzmiGames\Assets3D`); facts from `docs/analysis/assets3d-pipeline/05-export-and-consumers.md`.

| # | Consumer | Script or tool | Fixture | Expected bindings |
|---|---|---|---|---|
| 1 | Staff delivery | `Pipeline\retopology\staff-v10\deliver.py` | staff v10, five-map pipeline preset | BaseColor PNG16 sRGB; Roughness, Metallic PNG16 Non-Color; Normal PNG16 Non-Color, OpenGL, `combined`, through a Normal Map node on `UVMap`; Height exported, not wired; GLB with tangents and FBX with relative texture paths built |
| 2 | Hat delivery | `Pipeline\retopology\hat-v6\deliver_v8.py` | hat v8 (pipeline preset + SpecularWeight + 16-bit AO) | Row 1 plus AO 16-bit in the glTF occlusion slot; SpecularWeight loaded, but its Blender link is commented out in the script: reported as a consumer gap, not compensated by UzPainter |
| 3 | Specular augmentation | `Pipeline\retopology\hat-v6\glb_add_specular.py` | GLB of row 2 | SpecularWeight (8-bit, weight in RGB and A as delivered today) → `KHR_materials_specular` |
| 4 | PBR review render | `Pipeline\render\render_pbr_asset.py` | wand v1, staff v10 | Maps reloaded with BaseColor sRGB and the others Non-Color; geometry/UV hash checks pass |
| 5 | Piece paint renders | `paintrender.py` of `wand11-v1`, `waist-v5`, `staff-v10`; `hat-v6\paintrender_v8.py` | wand v1, belt v5, staff v10, hat v8 | Rows 1–2 bindings under `ref_match`; hat v8 wires Specular IOR Level = 0.5 × SpecularWeight |
| 6 | Render standard | `Pipeline\render\blender_render_standard.py` (`apply(…, preset='ref_match')`, `base_color_diagnostic()`) | used by rows 4–5 | BaseColor diagnostic identical to that of the Painter delivery |
| 7 | Review panel | `Pipeline\panel\` (three.js 0.170) on the Blender-built GLB | GLBs of rows 1–3 | BaseColor sRGB, metallic-roughness texture packed by Blender's glTF exporter, normal, occlusion and `KHR_materials_specular` when present |
| 8 | Unreal Engine 5.6 | External import fixture (`07-preview-and-render-parity.md` §1) | wand v1, hat v8 | `Unreal Engine (Packed)` files: BaseColor sRGB, ORM linear, Normal as DirectX normal map, Emissive sRGB; PNG/TGA default and the DDS BC7/BC5 variant both import; SpecularWeight gap reported |
| 9 | UzEngine | External fixture: UzEngine's own executable loads the `.uzmat` and `.uztexture` files in a test scene | wand v1, hat v8 | Bindings of the UzEngine preset table; decoded `.uztexture` compared with the canonical maps under the lossy-derivative contract (`14-parity-testing.md` §4) |

Pass condition: rows 1–7 also run on the Painter delivery of the same project, and bindings (file, channel, colour space, bit depth, metadata) and outputs must be identical under the tier rules of `14-parity-testing.md`; rows 8–9 pass on their expected bindings. A change needed in a consumer script is Assets3D work: it is reported, never compensated inside UzPainter's export.

## 6. Diagnostics through the same engine

Any channel, mesh map, mask, isolated layer, difference map or unlit BaseColor is an export with the appropriate `srcMapType`/diagnostic source (EXP-04, LAY-09, LAY-14, INT-13); curvature and other mesh maps export at native precision with their recorded normalisation.

The diagnostic sources (decision 076, `src/evaluator/diagnostics.h`) use `srcMapType` `diagnosticMap`. This is a UzPainter extension; Painter's own values keep their meaning. The `srcMapName` values are:

- `isolated/<map>/<node>`: the map with the node hidden;
- `contribution/<map>/<node>`: full − isolated, a signed float map;
- `materialMask/<material>`: the effective mask;
- `materialView/<view>/<material>`: the view inside the region, 0 outside;
- `materialLeaks/<view>/<material>`: 1 at a leak, else 0;
- `regionStats/<map>/<material>`: statistics, written as canonical JSON, never as an image.

`<map>` is a channel name, `Normal_OpenGL` or `Normal_DirectX`. `<view>` is `ID`, `BaseColor`, `Height`, `Normal`, `Roughness` or `Metallic`. Uids are in decimal. Raster sources are float32 values, written with the file's write rule. A name that does not parse is an invalid config, and so is a statistics source in an image channel slot.
