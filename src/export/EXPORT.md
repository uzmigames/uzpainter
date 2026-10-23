# The export plan compiler (`src/export/`)

Task `phase1.15_export-plan-compiler` (child of `phase1.18_export-engine`, P1-EXPORT). Implements `docs/architecture/08-export.md` §1 (configuration), §2 (virtual maps) and §6 (diagnostic sources) under decisions 076, 085, 086 and 091. Tests: `tests/export/` (`zig build export-tests`, `python -m pytest tests/export`). Local run report: `parity/reports/phase1/export-plan-compiler.md`. Published semantics: `parity/semantics/virtual-maps.json` (re-derived by `python tests/export/tier0.py`).

## 1. Shape

| File | Role |
|---|---|
| `config.{h,cpp}` | `ParseConfig`: Painter's `json_config` dictionary read verbatim (export.html, "Full json_config dict possibilities") into `ExportConfig`. Checks every project-independent identifier: keys, channel letters and destination sets, `srcMapType`, the documented `srcMapName`s of each type, decision 076's `diagnosticMap` grammar, file formats, bit depths, padding algorithms, `sizeLog2`, preset references. `Nearest` orders the valid alternatives of an unknown name. |
| `plan.{h,cpp}` | `CompilePlan`: the configuration against a project (texture sets, stacks, channels, bound mesh maps) into `ExportPlan`, every output file with its sources, parameters, size, name and format, the maps skipped and the plan hash; `PlanJson` (schema `uzpainter/export-plan/1`); `FilesByStack` / `ListProjectTextures`, the dry run in `list_project_textures`'s shape; `EvaluateFileOn`, a planned file's channels evaluated on a tile store. |
| `virtual_maps.{h,cpp}` | The documented virtual maps and their support (`Support`); `EvaluateVirtualMapOn` (the combined normals of `evaluator/height_to_normal.h`) and `EvaluateMeshMapOn` (the `normal_base` geometry-only pass-through). |
| `encode.{h,cpp}` | (phase1.16, decisions 089 and 090) `CheckProcessing`: the processing a planned file asks for, refused with `NotYetSupported` outside the recorded domain (§4); `EncodeFile`: a padded raster to the PNG or OpenEXR bytes (or the statistics JSON). |
| `padding.{h,cpp}` | (phase1.16) `CheckPadding` / `ApplyPadding` over the texture set's texel-centre UV coverage (§4). |
| `guards.{h,cpp}` | (SUP-035, decision 091) The export's static refusals as pure checks (`ProcessingRefusal`, `IslandNormalFileRefusal`, `PaddingRefusal`), which `CheckProcessing`, `CheckIslandNormal` and `CheckPadding` throw; `PreflightExport` / `PreflightJson`, the MCP dry run's per-file `blocked`, `needs_evaluation` or `no_known_blocker` over them. |
| `png_writer.{h,cpp}` | (phase1.16) `EncodePng`: UzPainter's own PNG encoder over the vendored zlib, byte-identical to Painter's files. |
| `exr_writer.{h,cpp}`, `tinyexr_unit.cpp` | (phase1.16) `EncodeExr` / `DecodeExr` over the vendored tinyexr (one recorded local change), byte-identical to Painter's files; `tinyexr_unit.cpp` is the third-party translation unit of tinyexr's implementation. |
| `write.{h,cpp}` | (phase1.16) `EncodeExport`: every planned file checked, then evaluated, padded and encoded in memory; `WriteExport`: those bytes written under exportPath in Painter's flat layout (the parity writer). |
| `preset_aliases.{h,cpp}` | (phase1.17, decision 095) The shipped presets of `assets/export-presets/` and the compatibility alias table: `ShippedPresetId` (a shipped id, a Painter preset name, or its `resource://starter_assets/` URL), `LoadShippedPreset` (the preset and its provenance record), `DefaultPresetDirectory` (`assets/export-presets` beside the executable) (§5). |
| `publish.{h,cpp}` | (phase1.17, decision 097) `PublishExport`: the encoded files, the plan and the receipt published as a new generation by an atomic pointer update; `PublicationLock`; `RecoverExport` (`export --recover`). |
| `fixed_names.{h,cpp}` | (phase1.17) `OpenPinnedDelivery` (the generation-pinning adapter), `CopyFixedNames` (the journalled fixed-name copy), `LockedFixedNames` (the reader under the publication lock), `RecoverFixedNames`. |
| `receipt.{h,cpp}`, `schema/receipt.schema.json` | (phase1.17) `BuildReceipt`, `ReadReceipt`, `ReadResourceHashes`: the receipt (ARC-11 header, per-file fields, normal tags, consumer gaps, the Assets3D v2 export block). |
| `project_export.{h,cpp}` | (phase1.18, decision 104) `ExportProject`: a `.uzp` project's current revision exported end to end with a `json_config` and published (§7). |
| `cli.{h,cpp}` | (phase1.17, phase1.18) `UzPainter.exe export <file.uzp> --config <config.json> --app-version <v> --build <id>` and `export --recover <exportPath> [--fixed-names <dir>]...`. |
| `fault.{h,cpp}` | (phase1.17) Test-only fault hooks between every publication step, compiled into `uzp-export-tests.exe` only (`UZP_EXPORT_FAULT_HOOKS`). |
| `bc_encoder.{h,cpp}`, `mips.{h,cpp}`, `uztexture_writer.{h,cpp}` | (phase3.1_uze-uztexture-writer, decisions 315 and 316) The UzEngine texture path, compiled into `uzp_texture.lib`, which every binary compiling these export sources links (decision 316): `EncodeBc`, the BC1/BC3/BC4/BC5/BC7 (and sRGB) encoder adapter over etcpak 2.1, whose bytes do not depend on the thread count; `GenerateMipChain`, full 16-bit power-of-two chains per map class (linear, sRGB-aware colour, renormalised normals, alpha-coverage-preserving masked colour); `WriteUzTextureFile` / `CookUzTexture`, the `.uztexture` writer over the vendored format definition, with the negative-Z guard for BC5 normals. Tests: `tests/export/texture_test.cpp` (`zig build uzp-texture-tests`, `tests/export/test_uze_texture.py`), with the test-only bcdec decoder and `.uztexture` reader of `tests/export/uze_texture_check.h`. |

Both `uzp-export-tests.exe` and `UzPainter.exe` compile these sources (`build.zig`, `export_sources`). The Python bindings (`uzpainter.export.plan`, `substance_painter.export.list_project_textures`) are `phase1.19_pyapi-native-module` item 2.7.

## 2. Semantics (decisions 085 and 091)

Painter's documented semantics, with the Tier 0 recordings and the export probes of recording R-085 (decision 087) deciding what the documentation leaves open. Every probe behaves as Painter did (`test_dry_run_equals_painter_probes`). The dry run of every export step of every recorded golden of the current envelope lists exactly the files Painter wrote: 166 steps over 26 project templates (`test_dry_run_equals_painter_export`).

- **Errors.** An ill-formed configuration, or one invalid for the project, throws `core::ValueError` (Painter's documented `ValueError`). The message starts with the JSON path or the file, and lists the valid alternatives nearest first: `Mixed_AO` lists `AO_Mixed` first. A well-formed request for something this build does not do throws `core::NotYetSupported` naming its owner task. A request for behaviour no recording shows also throws it, naming recording R-091 (decision 091) or R-092 (decision 092). Every failure happens before any evaluation or write.
- **Keys.** Undocumented keys at the configuration's root and in a preset map are ignored, as Painter ignores them (probe P10). Elsewhere an undocumented key is not recorded and is refused. An integer `bitDepth` is a `ValueError` ("Expected a string value", probe P11). `srcPath` is accepted only empty (Painter's own `list_output_maps` emits `''`). `exportShaderParams: true` is a release gap (phase2.3).
- **Presets.** `defaultExportPreset` and `exportList[].exportPreset` name an inline preset, else a shipped preset (§5, decision 095). A shelf or predefined preset UzPainter does not ship is `NotYetSupported`.
- **Roots.** `rootPath` is `<set>` for a set whose only stack is unnamed, `<set>/<stack>` otherwise. Any other value is a `ValueError` listing the valid roots.
- **Filters.** An absent filter or member selects everything; a present empty list selects nothing. `dataPaths` entries match a root path or its texture set. `outputMaps` entries match the unexpanded `fileName` exactly. `uvTiles` selects a texture set of the Default workflow, the single tile [0, 0], when it lists [0, 0] (probe P4). Members combine with AND. A configuration may write no file (probe P8).
- **Parameters.** Start from the preset map's `parameters`, then apply every matching `exportParameters` rule in list order. Each defined field overrides. `fileFormat`, `bitDepth`, `dithering` and `paddingAlgorithm` must then be defined, and `dilationDistance` when the padding is `transparent`, `color` or `diffusion`. Otherwise the configuration is invalid, naming the map and the parameter. An absent `sizeLog2` is the set's size. A scalar `sizeLog2` sets the larger side and keeps the aspect; `[w, h]` sets both. `bitDepth` must suit the format: png 8 or 16, exr 16f or 32f. Formats: png and exr are written in Phase 1. TGA, BMP, JPEG and DDS belong to `phase3.2_unreal-ue56-packed-preset`. TIFF, PSD, WebP, J2K/JP2, PGM, JNG and sbsar are not in v1.
- **Dry run (decision 091).** The dry run lists exactly the files the export writes. Painter's own `list_project_textures` also names maps its export does not write or refuses; the plan keeps them in `skipped` with their kind: `absent` (sources absent), `not_written` (Painter lists it, writes nothing) or `export_error` (Painter lists it, its export raises `ValueError`). With an `export_error` and no file to write, the dry run (`ListProjectTextures`, `CheckExportable`) and the export raise `ValueError` before any write; with files to write as well it is not recorded and is refused.
- **Presence.** A `documentMap` whose channel the stack lacks makes its map absent: Painter writes no file for it. A legacy name reads its OpenPBR member when the stack lacks the legacy one: `roughness` → SpecularRoughness, `metallic` → BaseMetalness, `emissive` → EmissionColor, `anisotropylevel` → SpecularRoughnessAnisotropy, `scattering` → SubsurfaceRadiusScale (decision 085), `coatopacity` → CoatWeight, `sheencolor` → FuzzColor, `sheenroughness` → FuzzRoughness, `sheenopacity` → FuzzWeight, `translucency` → SubsurfaceWeight, `scatteringcolor` → SubsurfaceColor (probe P13, byte-equal to the paired channel's export). These six, `absorptioncolor` and `specularedgecolor` are an `export_error` when the stack has neither their channel nor their pairing. A map made only of `defaultMap white` is absent; one made only of `black` is `not_written` (probe P8). An unbound mesh map is an `export_error` (probe P12). An absent `documentMap` as the alpha of present R, G and B drops the alpha: the file is R+G+B (probe P7). Refused as not recorded (R-091): any other mix of present and absent sources, and black mixed with white.
- **Names** (probes P1-P3, P9). `$textureSet` is the set's name and `$sceneMaterial` its mesh material (`original_name`). `$mesh` is the imported mesh file's name without its extension, and `$project` the project file's name without its extension, `Untitled` while it was never saved (`PlanContext::projectPath`). Under legacy colour management `$colorSpace` is empty. Under OCIO with Painter's substance config (decision 190) it is `sRGB` for a PNG of an sRGB8 BaseColor and `Raw` for a PNG whose every channel reads a document channel that is not sRGB8; any other file naming it is refused as not recorded (`export-ocio-encode`). In the Default workflow `$udim` and `$uvTileName` are empty, also outside a group. A `( … )` holding no parenthesis and at least one wildcard is a group: dropped when its wildcards are empty, written without its parentheses otherwise. Every other parenthesis is a literal character: `$textureSet(_v2)` → `s0(_v2)`, `$textureSet((_$udim))` → `s0()`, `$textureSet(_$udim` → `s0(_`. `/` separates sub-folders. The extension is the format's. Within one exportList entry, a later map whose path equals an earlier one's gets `_1` before its extension. Refused before writing:
  - Windows-invalid components, `.` and `..` (`ValueError`);
  - unknown wildcards (`ValueError`, with the alternatives);
  - not recorded (R-091): a mesh or project file name with more than one dot, a renamed set's `$sceneMaterial`, a group with both empty and non-empty wildcards, a `)` after no literal `(`, a third equal path;
  - two entries' files with one path, and paths equal only ignoring case: Painter lists both, but the file a case-insensitive file system keeps depends on a write order not recorded. Both are named.
- **Channels.** The destination sets are L, L+A, R+G+B and R+G+B+A. `srcChannel` L, R, G or B of a one-component source reads its value. R, G or B of a three-component source reads that component. L of a three-component source reads the Rec. 601 luma of its linear components, `fma(0.114, b, fma(0.299, r, 0.587 g))` in float32 (probe P5; an sRGB8 channel's base value is linear, decision 126). Any letter of a `defaultMap` reads its constant. A of any other source is recorded only at full and no coverage (probe P6) and is refused.
- **Normal sources.** `Normal_OpenGL` and `Normal_DirectX` need a Height and a Normal channel at plan time. Their other limits (set size, a bound Normal mesh map) belong to the evaluator, which refuses them with `unsupported_source` (`NotYetSupported`) when the export evaluates every file, before any write. `meshMap normal_base` is the geometry-only pass-through. `ambient_occlusion`, `curvature` (L) and `position` (RGB) pass their bound 8- or 16-bit image through at the set's resolution, each code as its UNORM operand (recording R-090 P7, decision 103). The other mesh maps (`id`, `world_space_normals`, `thickness`) are refused (`NotYetSupported`, no recording).
- **Diagnostics** (decision 076, `08-export.md` §6). A `diagnosticMap` source resolves in the stacks that hold its node and is absent in the others. A node in no exported stack is invalid, and so is a channel the stack lacks. A `regionStats` source is a statistics file: the map's only channel (destination L), written as canonical JSON (`<name>.json`). Anywhere else it is invalid.
- **Plan hash.** The SHA-256 of the canonical JSON of the plan without its `hash` member (`core::json::WriteCanonical`): the same project and configuration give the same bytes.

## 3. Virtual maps (decisions 086 and 092)

`Normal_OpenGL` and `Normal_DirectX` are supported. Through the plan they equal every compared golden map of the height-amplitude sweep and the Sharp and Sobel plane-strength sweeps (`test_virtual_map_goldens_exact`). The other eleven documented maps are release gaps, refused before anything is written (`parity/semantics/virtual-maps.json` states each fit):

- `AO_Mixed`: the best model of recording R-086a misses r1 at 31 values, each a few ulps from a 2^-12 boundary; no correctly rounded float32 evaluation of the tested inputs reproduces them, and Painter's arithmetic there is not identified (recording R-092).
- `Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `f0`: fitted exactly on recording R-086b at PNG 16 and OpenEXR 32f. They read each channel's per-texel coverage, which the evaluator does not give, and fixed inputs where a channel has no layer, seen on one template only (recording R-092).
- `View_2D`: a shaded render of the 2D view, not an operator on the channels.

## 4. Processing and encoders (decisions 089, 090 and 103)

Tasks `phase1.16_export-processing-encoders` and `phase1.18_export-engine` item 6.1. Local run reports: `parity/reports/phase1/export-processing-encoders.md`, `parity/reports/phase1/export-engine.md`. Published semantics: `parity/semantics/export-processing.json` (re-derived by `python tests/export/encoders_tier0.py`). Tests: `tests/export/test_export_encoders.py`.

- **Writers (decisions 089 and 103).**
  - PNG: UzPainter's own encoder over zlib. Chunks IHDR, pHYs (2835 per metre), IDAT and IEND. Each row takes the filter whose bytes have the minimum sum of min(b, 256 - b), ties to the earlier, from all five filters for 8-bit grey and from None, Sub and Paeth for every other layout. One zlib stream (level 6, window bits 15, memory level 8; Z_DEFAULT_STRATEGY for 8-bit grey, Z_FILTERED otherwise) is split into 8192-byte IDATs. Layouts: grey, RGB and RGBA at 8 or 16 bits, grey and alpha at 16 bits.
  - OpenEXR: tinyexr, single-part scanline, PIZ, FLOAT (32f) or HALF (16f) channels `Y`, `A Y`, `B G R` or `A B G R`, with OpenEXR's Huffman heap tie-break as its one local change.
  - Every distinct PNG (1826) and OpenEXR (823) file Painter exported in the current envelope, decoded and encoded again, is byte-identical.
- **Values.**
  - The evaluator's read-out of each channel (an sRGB8 channel as its linear operand, in every format; the template constants of the sRGB8 BaseColor and Specular are linear, decision 126).
  - PNG 8 and 16: the UNORM write rule at the file's depth (`arith::WriteUnorm`). A Height channel is written as v * 0.5 + 0.5. An sRGB8 BaseColor, Specular or Emissive (and its luma) is written as the sRGB encode of its linear value, `x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), -0.055)` with the recording GPU's log2 and exp2 (decisions 091 and 126): 258 of 258 values of `export-bit-depth` and 134 of 134 PNG files of four goldens re-encoded from Painter's own OpenEXR 32f files; written end to end, 120 of 120 of `export-bit-depth`'s material files. Its OpenEXR files hold the linear value. An L8 BaseColor, Specular or Emissive is written the same way through srcChannel R, B and L, and as its linear value through G (`SrgbEncodedRead`, decision 204): an RGB file holds (sRGB, linear, sRGB), an L file the sRGB encode, at PNG 8 and 16 (Dota 2's empty L8 Specular, `float32(10/255)`, is (14330, 2570, 14330) at PNG 16). `export-l8-material`'s 96 PNG files re-encoded from Painter's own OpenEXR 32f files (183 codes, r1 and r2) and, written end to end, the 72 files of its uniform colour and empty sets and Dota 2's two PNG 16 files are byte-identical.
  - Under OCIO with Painter's substance config (decision 190) each value is written as under Legacy but for the PNG 16 of an sRGB-encoded channel: each linear value is written as Painter's recorded code (`OcioSrgbPng16Code`, a measured table of the 256 sRGB8 operands and the empty BaseColor 0.8, `export-ocio-encode`). Any other value of such a channel in a PNG (8 or 16), a luma for example, fails with `unsupported_source` before anything is written.
    - The table differs from the Legacy encode by one code on 73 of the 256 operands and on 0.8 (59396 against 59397), and Painter's own files differ in the same places (`export-ocio-encode` against `export-ocio-encode-legacy`, s3 and s7, r1 and r2). So where a Legacy and an OCIO project store the same values, their PNG 8 and OpenEXR files are the same and their PNG 16 files differ by one code there. This was confirmed for B17 of `parity/reports/phase2/practical-e2e.md` and is pinned by `tests/export/test_export_encoders.py::test_painter_ocio_png16_differs_from_legacy_on_74_values` and `::test_ocio_png16_differs_from_legacy_where_painter_does`. They store the same values for every recorded source but one (`src/evaluator/sources.h`): an 8-bit colour bitmap in Raw on an sRGB8 channel stores the image codes 176, 245, 247 and 254 one sRGB8 code lower under OCIO (decision 190 fact 3, `OcioRawDecoded`). So `export-ocio-encode` s4's BaseColor differs from its Legacy twin's in PNG 16, PNG 8 and OpenEXR 32f, in Painter's files and in UzPainter's (`test_srgb8_bitmap_equals_painter_files` and `test_ocio_encode_equals_painter_files` are exact on both twins' s4).
  - OpenEXR 32f: the float unchanged. OpenEXR 16f: the half rounded toward zero (`arith::HalfTowardZero`).
  - L+A and RGB+A: written as such; an alpha of exactly 1 at every texel is dropped (the file is L or RGB, and the receipt says so).
  - Dithering: no change at PNG 16.
  - Painter's own OpenEXR 32f file of each map of `export-bit-depth`, `export-alpha-layouts` and `export-dither`, encoded with the processing of its other files, gives those files byte for byte: 384 of 384 bit-depth cases (PNG 8, PNG 16, OpenEXR 16f), 4 of 4 alpha layouts, 20 of 20 dithered PNG 16 (`test_processing_reproduces_painter_files`).
  - Written end to end by `WriteExport`, the recorded export steps of the height-normal plane goldens give Painter's bytes: 148 of 148 files.
- **Padding.**
  - With complete UV coverage, `infinite` and `passthrough` change nothing.
  - With incomplete coverage, `passthrough` is no operation; Painter's own texels outside the islands are session state.
  - With incomplete coverage, `infinite` is refused before writing, naming R-090 (decision 259). The owner withdrew exception EXC-007 (decision 223), which had let the padding texels differ from Painter's. The coverage-only rule of `padding.h` is applied only when the exact hunt measures it (`InexactPadding::measure`, `uzp-export-tests process`), never by the export.
  - Diagnostic seam discovery (decision 339) uses one-texel-wide strips with straight endpoints and a top-left fill rule at their borders. Collinear seams of an island that share a UV end and border one far island form a run, and a strip writes its run's ID. The last strip drawn owns each sample, including uncovered samples. A ring texel discovers every seam of a run owning a sample of its 3x3 neighborhood, before visibility and border gates, within the common 1.78 cap; the old corner brackets remain diagnostics. On the CPU reference over the 27 kernel probes, differing ring coordinates fall from 5,312 to 4,691 (corner 426 to 217, window 230 to 152, atlas-512 102 to 41, sphere 196 to 103, cube 346 to 342), with no new coordinate. Decision 340's own-order comparator (fused UV determinant; tau keeps the split one) lowers that to 4,615 (corner 174, window 132), and the compiled export runner equals the reference on every probe. Decision 342 keeps a far tap's own chart rigid: on a face path into tau's frame, a far tap skips the hinges whose two triangles are both in its chart, while the seam hinge and tau's chart keep decision 282's gate. That lowers the total to 3,444 (hinge-far 395, hinge-single 677, hinge-vary 953, corner 137, cube 336) with no new coordinate, compiled equal to the reference on every probe. Decision 356 draws every island's seam strips into one map in mesh order (the last seam drawn owns each sample; an island discovers a seam of its own only when that seam's run owns a sample of the 3x3) and lets the far window take tau's own island too (an own neighbour stays an own tap; any other texel of tau's island in the window is a far tap at its frame distance). That lowers the total to 2,951 (tie-sweep seams 36/2/1, atlases 30/32/31/65), compiled equal to the reference on every probe; the only new coordinates are 9 hinge-vary texels, all flagged `window-side` (decision 291 (b)). Remaining differences keep decisions 245/259 in force.
  - Refused with incomplete coverage: `passthrough` of meshMap and virtualMap sources, the alpha layouts, and under every padding and in statistics files a `Normal_OpenGL` or `Normal_DirectX`, or a diagnosticMap that isolates, compares or summarises one (`CheckIslandNormal`, decision 245). Its island-edge texels read the Height outside the islands, where Painter's Height is not reproduced. A Height without layers is refused too: no recording shows what Painter's empty Height reads outside the islands. `uzpainter.diagnostics` refuses the same views in memory.
- **Refused before anything is written** (`NotYetSupported`, recorded by R-090 but not fitted, decision 103):
  - dithering at PNG 8 (deterministic, not a threshold matrix) and in OpenEXR (no recording compares it with off);
  - resize (a sizeLog2 other than the set's size): partly fitted, `parity/semantics/export-processing.json` `resize`;
  - the `color`, `transparent` and `diffusion` paddings;
  - an sRGB8 channel other than a User channel, BaseColor, Specular and Emissive (EmissionColor, Diffuse, CoatColor, ...): not recorded (decision 126);
  - a PNG of an L8 BaseColor, Specular or Emissive under OCIO, or in any file other than the RGB file whose R, G and B (or the L file whose L) read those letters of the one L8 channel: not recorded (decision 204). Its OpenEXR files are exact;
  - any file whose values depend on a channel whose template base is `inferred` (none ships since decision 169: OpenEXR 32f shows every shipped template's base), whatever the format and through documentMap or diagnosticMap sources: `unsupported_source` at evaluation (decision 126). The guard is `RequireIdentifiedBase` (`plan.h`); `uzpainter.diagnostics` applies the same function to every view it returns (decision 136).

  Their owners: `phase1.25_pilot-wand` item 2.7 (padding on islands and the Height outside them: decisions 127, 223 and 245), the export encoder owner (the L8 material channel's PNG outside the recorded files, decision 204) and `phase3.2_unreal-ue56-packed-preset` (dithering, resize, dilation paddings).
- **Order.** `WriteExport` checks every file's processing and padding, then evaluates, pads and encodes every file in memory, and only then writes. A refusal or an evaluation failure leaves nothing written. Two runs in two processes write identical bytes.

## 5. Shipped presets (decision 095)

Task `phase1.17_export-presets`. Local run report: `parity/reports/phase1/export-presets.md`. Tests: `tests/export/test_export_presets.py`.

- **Files.** `assets/export-presets/<id>.json` is one `exportPresets[]` entry (`{name, maps}`) whose `name` is its UzPainter id. Its provenance record `<id>.provenance.json` follows `src/export/preset-provenance.schema.json` (`uzpainter/export-preset-provenance/1`): sources (page, section, facts, SHA-256 of UzmiGames files), private records (SHA-256 only), one packing entry per map with its source and status, parity (layout, status, pending recordings with their owners, tests). Both are installed beside `UzPainter.exe` and `uzp-export-tests.exe` (`bin/assets/export-presets/`).
- **Shipped.**
  - `assets3d-inline-five-map`: the Assets3D pipeline's inline preset (`painter_export.py`), named `$textureSet_<map>`; layout `pipeline`. It plans, file for file, what the pipeline's inline configuration plans.
  - `pbr-metallic-roughness` and `blender-principled-bsdf`: written from public sources and UzmiGames' own observations; layout `unconfirmed`.
  - `gltf-pbr-metal-roughness` (phase3.1_unreal-gltf-pbr-preset, decision 314): written from the glTF 2.0 specification; layout `unconfirmed` until recording R-314. Maps: BaseColor (RGB, A from opacity), MetallicRoughness (R white, G roughness, B metallic), Normal (`Normal_OpenGL`), Occlusion (`AO_Mixed`, refused until it is fitted, decision 131), Emissive and SpecularWeight (a consumer gap in the receipt, decision 023), each `fileFormat: png`.
  - `unreal-engine-packed` and its DDS variant `unreal-engine-packed-dds` (phase3.2_unreal-ue56-packed-preset, decision 322): layout `unconfirmed` until recording R-322 (below).
- **Resolution.** A reference that names an inline preset is that preset. The id `uzengine` names the UzEngine preset (below), which no Painter name aliases. Otherwise `ShippedPresetId` reads it as a shipped id, a Painter name of the alias table (`PBR Metallic Roughness`, `Blender (Principled BSDF)`, `glTF PBR Metal Roughness`, `Unreal Engine (Packed)`), or `resource://starter_assets/<Painter name>` with no query or a recorded `?version=` (an unrecorded query: `NotYetSupported`, naming the alias's recording: R-095, R-314 for the glTF preset, R-322 for the Unreal preset). The shipped preset joins `exportPresets` under its id, and the reference becomes that id. Painter names are aliases only (CLR-06). An inline preset named like the shipped id a reference resolves to is a `ValueError`. Any other `resource://` or `export-preset-generator://` reference is `NotYetSupported`.
- **Refusals.**
  - A preset whose layout is `unconfirmed` is refused (`NotYetSupported`) before anything is planned, naming its pending recordings (R-095; R-314 for the glTF preset; R-322 for the two Unreal presets).
  - The five-map preset writes BaseColor sRGB-encoded (decision 126); on a template whose BaseColor base is inferred the export is refused before writing.
- **Parity.** The five-map preset's Normal map, written on the recorded plane goldens, is byte-identical to Painter's `Normal_OpenGL` PNG 16 files. Every preset's full output parity waits on a comparison with recording R-095, which decisions 180 and 198 admitted (`export-presets-legacy`, `export-presets-ocio`, `phase1-export-preset-search`) and no test compares yet: a scope split to `phase3.3_unreal-gltf-presets` (decision 103).

### UzEngine preset (phase3.2_uze-uzmat-preset)

`assets/export-presets/uzengine.json` is the table of `08-export.md` §4, in the configuration form, plus a preset-level `uzengine` block. Only a shipped preset may carry that block. In an inline preset the key stays undocumented and is refused. Its provenance record has layout `consumer`: UzmiGames defined it from the UzEngine format definition (U-UZE-RUNTIME a703c95), and no Painter preset answers to it.

- **Maps.**
  - `$textureSet_albedo`: RGB from basecolor, A from opacity, PNG 8.
  - `$textureSet_normal`: `Normal_DirectX`, PNG 16. Phase 0 (`parity/reports/phase0/normal-convention.md` §8) found that UzEngine reads green as -v for meshes uzmesh cooks from OBJ. No gbuffer, uzmesh, tangent or material file differs between f4dcfc46 and a703c95. Other import paths are not calibrated.
  - `$textureSet_orm`: `AO_Mixed`, roughness, metallic, PNG 8.
  - `$textureSet_emissive`: PNG 8.
  - `$textureSet_height`: PNG 16.
  - `$textureSet_specularweight`: PNG 16.
  - Canonical companions: `canonical/$textureSet_{albedo,orm,emissive}`, PNG 16 copies of the three PNG 8 maps. The normal, height and SpecularWeight maps are their own canonical files (the table's "PNG8/16" resolved to 16).
  - Padding and dithering come from `exportParameters`.
- **Targets** (EXP-10: stated, never inferred from a name).

  | Map | Format | Colour | Mips | Binding |
  |---|---|---|---|---|
  | albedo | BC7 | sRGB | masked colour | `albedo` |
  | normal | BC5 | linear | normal | `normal`; negative-Z policy `fail` |
  | orm | BC7 | linear | linear | `orm` |
  | emissive | BC7 | sRGB | colour | `emissive` |
  | height | BC4 | linear | linear | `heightmap` |
  | specularweight | BC4 | linear | linear | none |

  - The `.uzmat` is `$textureSet.uzmat` at the delivery root. It binds the albedo, normal, ORM and emissive derivatives, and the height derivative as a reported gap.
- **Plan.** `CompilePlan` attaches each target to its delivered file (`PlannedFile::uztexture`: `<stem>.uztexture` beside it, cooked from `canonical`) and adds `ExportPlan::materials`. The dry run lists each derivative after its file and the `.uzmat` after its stack's last file. `PlanJson` states each derivative's format, sRGB flag, mip class, binding and canonical file. Refused before anything is written:
  - a filter that keeps a delivered map and drops its canonical map (`ValueError`, EXP-10);
  - a canonical file that is not a PNG 16 at power-of-two sides;
  - a layout the format cannot hold (BC4 needs L, BC5 an RGB normal source);
  - a colour channel whose stored encoding differs from the declared colour space (`NotYetSupported`, `phase3.4_uzengine-preset`). The check reads the encoder's own flags, luma included. Nothing is converted.
  - a UzEngine output whose path equals any other output's, across every stack, compared as Windows compares file names (`SameDeliveryPath`, `ValueError`). A derivative requested after compilation (`RequestUzTextureNormal`) goes through the same check, and the plan stays as it was when it fails. Two Painter-form files keep Painter's rule (R-091).

  When one of its four textures is not written, the `.uzmat` is skipped (`absent`, with the reason).
- **Cook** (`EncodeExport`). Each derivative is cooked from its canonical file's PNG 16 samples as written: L as R = G = B, a missing alpha as 65535. The samples are already encoded, so the colour and masked-colour mips decode the sRGB codes once to average them and encode them back; no second transfer is applied. The `.uzmat` is written after cooking (`WriteUzMaterial`). Its blend is `Masked` when the albedo derivative holds an alpha and `Opaque` otherwise. That is an authored UzPainter rule, not an engine fact: an alpha channel alone does not tell a cutout from a translucent surface. So it claims no engine Opacity parity, and the receipt records it as a `blend` consumer gap.
- **Publication.** Each derivative is written right after its file, and the `.uzmat` after its stack's last file. Test fault points: `kill_after_uztexture:<file>` and `kill_after_uzmat:<material>`.
- **Receipt.**
  - A derivative's `uztexture` is {source (its canonical file), delivery, binding or null, format, srgb, mips, encoder, negative_z (normal maps only)}.
  - The `.uzmat` entry (format `uzmat`) has `uzmat` {albedo, normal, orm, emissive, height, blend, two_sided, inline_material} and the writer's gaps.
  - Consumer gaps: `Opacity` on an albedo derivative with alpha (SM5 never reads albedo alpha), `Height` on the height derivative (no pin or inline key), `SpecularWeight`, and the `.uzmat`'s `opacity`, `height` and `blend` (the authored blend rule above).
- **Status.** Every plan that writes `$textureSet_orm` is refused until `AO_Mixed` is fitted (decision 131, `phase3.2_unreal-ue56-packed-preset` item 2.10, provenance pending R-131). So the full shipped preset is not yet exportable. On wand v1 its normal is also refused by the island rule (decision 245).
- **Tests.** `tests/export/test_uze_preset.py`, CPU only. It covers the shipped preset with its ORM maps filtered out and a test-only variant whose ORM R reads `ambientOcclusion`. Neither is shipped-preset or wand v1 acceptance. The normal's convention is checked against `Normal_OpenGL` through the PNG route: red and blue are equal and green is mirrored. A published `<set>_specularweight` needs a SpecularWeight base value, and no template or channel default records one (`missing_base_value`, decision 097). So its gap is checked through the receipt builder only.
- **Height sidecar.** The table's "sidecar" is read as the BC4 `.uztexture` companion: the engine probes a cooked companion before its file-name rule, and the companion's header states the format. The receipt also records that format. No engine sidecar format exists in the approved source.

### Unreal Engine (Packed) preset (phase3.2_unreal-ue56-packed-preset, decision 322)

`assets/export-presets/unreal-engine-packed.json` is `08-export.md` §4's layout in the configuration form, written by hand from that section, decision 023 and the UE 5.6 texture documentation (X-CONSUMERS). It answers to `Unreal Engine (Packed)` through the alias table. Its provenance record has layout `unconfirmed`, pending recording R-322 (item 2.1), so every reference to it is refused before anything is planned.

- **Maps**, named `$mesh_$textureSet_<map>`, each PNG 8:
  - `BaseColor`: RGB from basecolor, A from opacity;
  - `OcclusionRoughnessMetallic`: R `AO_Mixed`, G roughness, B metallic. Refused until AO_Mixed is fitted (decision 131, item 2.10);
  - `Normal`: `Normal_DirectX`;
  - `Emissive`;
  - `SpecularWeight`: absent when the stack has no SpecularWeight channel. The receipt reports it as a consumer gap, and the mapping `Specular = 0.5 x SpecularWeight` is not applied.

  Padding and dithering come from `exportParameters`.
- **TGA.** Refused before writing (`NotYetSupported`, naming item 2.5 and R-322): stb is not vendored, and Painter's TGA files are not recorded.
- **DDS variant.** `unreal-engine-packed-dds` has the same maps at PNG 16 and a preset-level `dds` block. No Painter name answers to it, and it shares the default preset's `unconfirmed` layout and R-322.
  - Targets: BaseColor and Emissive `BC7_SRGB` with colour mips, ORM `BC7` with linear mips, Normal `BC5` with normal mips; SpecularWeight has none.
  - Only a shipped preset may carry `dds`; an inline preset's `dds` key is refused as undocumented. `LoadShippedPreset` checks every target against the preset's maps, and BC5 must go with normal mips and BC7_SRGB with colour mips.
  - `CompilePlan` attaches each target to its PNG 16 file through `RequestDds` (`docs/DDS.md`), with that function's checks. The dry run lists each `.dds` right after its PNG 16.
- **Receipt.** Every DDS derivative carries a `cook` consumer gap: UE 5.6 documents DDS 2D import, not BC pass-through through cooking, so whether the engine re-encodes the file is recorded by the consumer fixture (item 3.3).
- **Tests.** `tests/export/test_unreal_preset.py`, CPU only. It covers the shipped presets' content, provenance and refusal. It also covers a test-only copy whose provenance says `confirmed` and whose ORM R reads `ambientOcclusion`: the dry run, DDS publication with receipts, the SpecularWeight gap and the target checks. The copy is not the shipped preset, and none of this is Painter-parity or UE 5.6 evidence.

### glTF consumer fixture

`tools/consumers/gltf.py` assembles an external glTF 2.0 asset from one published
generation. Build its CPU consumer with `zig build gltf-consumer`, then run
`python -m tools.consumers.gltf --request <request.json>`. The consumer uses vendored
fastgltf 0.9.1 and `fastgltf::validate`; its recorded identity and archive hash are in
`parity/manifests/consumers/gltf/wand-v1.json`. This is structural validation and actual
geometry/PNG loading, not the Khronos validator or a renderer.

The request is a JSON object with these fields; paths resolve from the caller's working
directory:

| Field | Contract |
| --- | --- |
| `export_root` | Publication directory containing `current.json`. |
| `mesh_obj` | Authored, triangulated OBJ with position, normal and UV at every corner. |
| `mesh_material` | Optional OBJ material selection; otherwise exactly one material must contain faces. |
| `bindings` | Exactly `baseColor`, `metallicRoughness`, `normal`, `occlusion`, `emissive`, each naming a PNG relative to the generation's `files/`. |
| `references` | `roughness` and `metallic`, each `{path, sha256}` naming an independent single-channel PNG with the packed texture's dimensions and native bit depth. |
| `output_dir` | New fixture directory; an existing directory is refused. |
| `consumer_exe` | Built `uzp-gltf-consumer.exe`. |
| `manifest_path` | Recorded consumer manifest above. |

The runner reads `current.json` once, verifies its receipt and every published file's
path, size and SHA-256, then retains those bytes. It copies selected PNGs unchanged,
converts the OBJ to indexed glTF geometry (normalizing normals and inverting V), and
sets material multipliers to one. The loader checks geometry, all five texture slots,
decoded PNG metadata and material factors. PNG input is limited to non-interlaced
8/16-bit grey, grey-alpha, RGB or RGBA; decompression is bounded by its declared size.
Metallic-roughness G/B must equal the independent references at every texel. Swapping
channels fails even when the altered texture and receipt have consistent hashes.

Success writes `asset.gltf`, `mesh.bin`, five PNGs and `report.json`; the report pins
the generation, receipt, source mesh, asset, manifest and consumer executable. Errors
return nonzero with a JSON error. `tests/export/test_gltf_consumer.py` exercises an
authored publication and corrupt inputs. The manifest stays `pending-real-fixture`:
this tooling does not satisfy Wand acceptance, R-314, or Painter export parity.

### UzEngine material writer

`WriteUzMaterial` (`uzmat_writer.{h,cpp}`) emits a version-1 `.uzmat` graph and the
matching JSON value for a scene's `components.material`. It writes bytes in memory;
the preset and publication integration remain `phase3.2_uze-uzmat-preset` work.
Its format source is approved `U-UZE-RUNTIME`, commit
`a703c95ada45002a774db9d9cf82b3b7964d09d6`: `material_expression.cpp`,
`material_graph.cpp`, `hlsl_material_translator.cpp` and `ecs/loaders/scene_loader.cpp`.
No UzEngine implementation is linked or executed.

The request explicitly supplies the material name/path and albedo, normal, ORM and
emissive `.uztexture` paths, with optional height, blend mode and two-sidedness.
Pins 0..6 bind albedo RGB, ORM B, ORM G, normal RGB, emissive RGB, albedo A and ORM R.
Samples are named `Albedo`, `Normal`, `ORM`, `Emissive` because the pinned graph
translator uses those names for texture colour space. Normal stays encoded; the
shader decodes it downstream. Multipliers are one. The inline block includes `orm`
and all four emissive colour/intensity values because the pinned scene loader
otherwise overwrites graph ORM and multiplies emission by zero.

The `.uzmat` must sit at the delivery root, mounted as the consumer's VFS root.
All texture references use that same root in both documents; nested texture paths
are allowed. The writer rejects traversal, invalid UTF-8, reserved Windows device
names and case-insensitive path matches between sRGB and linear texture slots. It never infers a binding
or format from a filename. File existence, format metadata, generation ownership
and actual engine loading belong to the publication and external consumer fixture.

Height has no pin among 0..6 and no verified inline binding in this source revision.
An optional height path is reported in `gaps`, without inventing an engine key.
Non-opaque modes also report the SM5 opacity gap. The pinned shader reconstructs
positive normal Z from XY: RGB file preservation alone does not establish that this
consumer renders negative-Z normals correctly. These consumer limits do not accept
the complete UzEngine preset or its fixture. CPU tests: `zig build uzp-material-tests`
and `tests/export/test_uzmat_writer.py`.

## 6. Publication and receipts (decision 097)

Task `phase1.17_export-publication-receipts`. Tests: `tests/export/test_export_publication.py` (CPU, every lane).

- **Generations.** `PublishExport` holds the publication lock (`exportPath/publication.lock`) while it works:
  1. It encodes every file in memory (`EncodeExport`).
  2. It claims `exportPath/generations/<NNNNNN>/`. The number comes after every existing generation, and the directory is created only if absent.
  3. It writes `files/<relativePath>`, `plan.json` and `receipt.json`. Each one is flushed and read back to check its size and SHA-256.
  4. It renames `current.json.uzp-staging` over `current.json`. The pointer is `{schema: uzpainter/export-current/1, generation, receipt, receipt_sha256}`.

  A failure before the rename removes the new generation and returns an `export:` failure. The previous generation stays selected. An encoder that throws is caught, so the host keeps running. A refusal (`ValueError`, `NotYetSupported`) happens before anything is written.
  Before evaluation or any filesystem change, it resolves the tile store's execution identity. An unavailable GPU identity fails the request without evaluating tiles, creating an output directory, or changing an existing generation.
- **Completeness.** A generation is complete when:
  - its receipt reads as a receipt of that generation;
  - `plan.json` hashes to the receipt's plan hash;
  - every listed file has its recorded size and SHA-256.

  Complete generations are never changed or removed.
- **Recovery.** `export --recover` publishes the newest complete generation newer than the selected one. It removes every other incomplete generation and any staging pointer. A damaged selected generation is reported (exit 1) and left in place. A pointer that does not read fails the recovery before anything changes.
- **Fixed names.** A consumer reads one complete generation by either route:
  - **`OpenPinnedDelivery`:** the selected generation's `files/` directory, verified against its receipt.
  - **`LockedFixedNames`:** a fixed-name copy (`CopyFixedNames`), read under the publication lock.

  The copy is journalled in its directory (`fixed-names.journal.json`: `{generation, files, copied, obsolete}`). Each file is staged as `<name>.uzp-staging`, then renamed and recorded. Names the new generation lacks are removed last. The locked reader first rolls an interrupted copy forward from the journal's generation, then verifies every fixed name, and holds the lock until it is done. If that generation does not verify, the reader fails before consuming anything. A copy into `exportPath` itself gives Painter's flat layout beside the publication. It refuses `current.json`, `generations`, `publication.lock` and the journal as fixed names. Staging names never appear in a receipt, a journal or the pointer.
- **Receipt** (`uzpainter/export-receipt/1`, `schema/receipt.schema.json`).
  - **Header.** The ARC-11 header (`revision`, `evaluator_profile`, `compat_profile`, `app_version`, `resource_hashes`), plus `build`, `generation`, `moment`, `plan` and `plan_hash`.
  - **`files[]`.** Each entry has `path`, `key`, `root_path`, `preset`, `bytes`, `sha256`, `format`, `bit_depth`, `colour_space`, `size`, `layout`, `channels` and `normal`. `normal` is `{role: combined, relief: {revision, height_hash, method}}`, `{role: geometry_only, relief: null}` or null. Each entry also has `consumer_gaps`.
  - **`skipped[]`.** The maps the plan does not write, with their kind and reason.
  - **`manifest_export`.** The Assets3D block in the form of `manifest-schema-v2.json` `$defs/export`, replacing v1's `exportacao`. `manifest_files` holds the `files` entries its keys name. Their paths are relative to the generation; the pipeline adapter rebases them. The block is null when the export writes no file.
  - **Resources.** `resource_hashes` lists the resources the files read: bitmaps of the read channel DAGs, a diagnostic material's masks, the mesh maps read, and the texturing mesh (its file and the files it reads beside it, such as a glTF's buffers).
  - **Identity.** `app_version` and `build` come from the caller (`PublishRequest::identity`).
  - **Execution.** `backend`, `adapter` and `driver` come from the tile store that evaluated the export. CPU receipts use `backend: cpu` with null adapter and driver. GPU receipts identify the active device and refuse missing or unknown identities. DX12 resolves the device's adapter by LUID; Vulkan uses its physical-device record. Historical receipts without all three fields remain readable; new receipts always contain the complete trio. Capture receipts use the same capability identity.
  - **Colour space.** `colour_space` states what the file stores: `sRGB` when every colour channel (all but A) is written sRGB-encoded, `linear` when none is, and `mixed` otherwise. For example, an L8 BaseColor's RGB file holds sRGB, linear, sRGB (decision 204). Each image channel also states its `transfer`. Only a PNG writes sRGB-encoded values (decision 126), and the luma of an sRGB8 colour channel is one of them. Until phase3.2_uze-uzmat-preset every receipt said `linear`, so the files that change are exactly the sRGB-encoded PNGs (`test_receipt_colour_space_follows_the_written_encoding`).
  - **Consumer gaps.** A SpecularWeight map carries the consumer gap of `08-export.md` §4.
- **`.uztexture` normal derivative** (phase3.1_uze-uztexture-writer items 2.7 and 3.5, decision 316).
  - **Request.** `RequestUzTextureNormal(plan, relativePath, policy)` sets the plan field `PlannedFile::uztexture`. The policy is `fail` (the default) or `rgb`. The plan hash covers the field.
  - **Bound.** The file must be an RGB PNG 16 of one normal source, with power-of-two sides. That file is the canonical 16-bit companion. The derivative is `<stem>.uztexture` beside it.
  - **Preset exposure.** The UzEngine preset sets the field for its six maps, each cooked from its canonical file (§5, UzEngine preset).
  - **Cook.** `EncodeExport` cooks the derivative from the PNG's samples as written, after padding.
  - **Guard.** It finds the texels with B <= 32767 (Z < 0).
    - `fail`: an `export:` failure naming the count and the first texel, returned before any generation is claimed.
    - `rgb`: the map is stored as RGBA8, which keeps Z's sign.
    - No negative texel: the map is stored as BC5.
  - **Publication.** The derivative is published right after its file. The receipt lists it as a `uztexture` file with `uztexture.format` and `uztexture.negative_z` {policy, texels, first, routed}. A routed map carries a Normal consumer gap.

## 7. The end-to-end export (decision 104)

Task `phase1.18_export-engine`. Tests: `tests/export/test_export_engine.py`.

This command uses the CPU store. Python exports through `UzPainter.exe run` use the selected GPU after plan and source preflight (decision 357, `src/python/PYAPI.md`): DX12 by default, or explicit `--gpu-backend dx12|vulkan`, without CPU fallback after a GPU failure. Its Debug unavailable-device fixture explicitly selects CPU export. Every route records the tile store's actual execution identity in the receipt.

`UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>` (`ExportProject`):

1. The project file is opened through the project store, its lock taken and its current revision read. A file whose integrity report finds corrupt content or a missing dependency is refused (`ValueError`).
2. The configuration is compiled against that revision, with the file's path as `$project`; `CheckExportable` runs as for the dry run.
3. The evaluator runs on the CPU store (bounded by the machine's physical memory) with the templates beside the executable, reading the project's resources from the file and the texturing mesh re-derived from its stored bytes (`mesh::RederiveMesh`). A resource the file cannot give is `evaluator:missing_resource`.
4. `PublishExport` publishes the files, the plan and the receipt as a new generation; the receipt carries the given version and build (ARC-11).

A refusal prints `ValueError: ...` or `NotYetSupported: ...` and writes nothing (exit 1); a failure prints its reason with the previous generation still selected (exit 1); a usage error exits 2. Two processes exporting the same file with the same configuration into one exportPath publish generations whose files and plans are byte-identical and whose receipts differ only in `generation` and `moment`.
