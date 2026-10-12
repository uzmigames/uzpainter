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
| `png_writer.{h,cpp}` | (phase1.16) `EncodePng`: UzPainter's own PNG encoder over the vendored zlib, byte-identical to Painter's files. |
| `exr_writer.{h,cpp}`, `tinyexr_unit.cpp` | (phase1.16) `EncodeExr` / `DecodeExr` over the vendored tinyexr (one recorded local change), byte-identical to Painter's files; `tinyexr_unit.cpp` is the third-party translation unit of tinyexr's implementation. |
| `write.{h,cpp}` | (phase1.16) `EncodeExport`: every planned file checked, then evaluated, padded and encoded in memory; `WriteExport`: those bytes written under exportPath in Painter's flat layout (the parity writer). |
| `publish.{h,cpp}` | (phase1.17, decision 097) `PublishExport`: the encoded files, the plan and the receipt published as a new generation by an atomic pointer update; `PublicationLock`; `RecoverExport` (`export --recover`). |
| `fixed_names.{h,cpp}` | (phase1.17) `OpenPinnedDelivery` (the generation-pinning adapter), `CopyFixedNames` (the journalled fixed-name copy), `LockedFixedNames` (the reader under the publication lock), `RecoverFixedNames`. |
| `receipt.{h,cpp}`, `schema/receipt.schema.json` | (phase1.17) `BuildReceipt`, `ReadReceipt`, `ReadResourceHashes`: the receipt (ARC-11 header, per-file fields, normal tags, consumer gaps, the Assets3D v2 export block). |
| `cli.{h,cpp}` | (phase1.17) `UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...`. |
| `fault.{h,cpp}` | (phase1.17) Test-only fault hooks between every publication step, compiled into `uzp-export-tests.exe` only (`UZP_EXPORT_FAULT_HOOKS`). |

Both `uzp-export-tests.exe` and `UzPainter.exe` compile these sources (`build.zig`, `export_sources`). The Python bindings (`uzpainter.export.plan`, `substance_painter.export.list_project_textures`) are `phase1.19_pyapi-native-module` item 2.7.

## 2. Semantics (decisions 085 and 091)

Painter's documented semantics, with the Tier 0 recordings and the export probes of recording R-085 (decision 087) deciding what the documentation leaves open. Every probe behaves as Painter did (`test_dry_run_equals_painter_probes`). The dry run of every export step of every recorded golden of the current envelope lists exactly the files Painter wrote: 166 steps over 26 project templates (`test_dry_run_equals_painter_export`).

- **Errors.** An ill-formed configuration, or one invalid for the project, throws `core::ValueError` (Painter's documented `ValueError`). The message starts with the JSON path or the file, and lists the valid alternatives nearest first: `Mixed_AO` lists `AO_Mixed` first. A well-formed request for something this build does not do throws `core::NotYetSupported` naming its owner task. A request for behaviour no recording shows also throws it, naming recording R-091 (decision 091) or R-092 (decision 092). Every failure happens before any evaluation or write.
- **Keys.** Undocumented keys at the configuration's root and in a preset map are ignored, as Painter ignores them (probe P10). Elsewhere an undocumented key is not recorded and is refused. An integer `bitDepth` is a `ValueError` ("Expected a string value", probe P11). `srcPath` is accepted only empty (Painter's own `list_output_maps` emits `''`). `exportShaderParams: true` is a release gap (phase2.3).
- **Presets.** `defaultExportPreset` and `exportList[].exportPreset` name inline presets. A `resource://` shelf preset is `phase1.17_export-presets`.
- **Roots.** `rootPath` is `<set>` for a set whose only stack is unnamed, `<set>/<stack>` otherwise. Any other value is a `ValueError` listing the valid roots.
- **Filters.** An absent filter or member selects everything; a present empty list selects nothing. `dataPaths` entries match a root path or its texture set. `outputMaps` entries match the unexpanded `fileName` exactly. `uvTiles` selects a texture set of the Default workflow, the single tile [0, 0], when it lists [0, 0] (probe P4). Members combine with AND. A configuration may write no file (probe P8).
- **Parameters.** Start from the preset map's `parameters`, then apply every matching `exportParameters` rule in list order. Each defined field overrides. `fileFormat`, `bitDepth`, `dithering` and `paddingAlgorithm` must then be defined, and `dilationDistance` when the padding is `transparent`, `color` or `diffusion`. Otherwise the configuration is invalid, naming the map and the parameter. An absent `sizeLog2` is the set's size. A scalar `sizeLog2` sets the larger side and keeps the aspect; `[w, h]` sets both. `bitDepth` must suit the format: png 8 or 16, exr 16f or 32f. Formats: png and exr are written in Phase 1. TGA, BMP, JPEG and DDS belong to `phase3.2_unreal-ue56-packed-preset`. TIFF, PSD, WebP, J2K/JP2, PGM, JNG and sbsar are not in v1.
- **Dry run (decision 091).** The dry run lists exactly the files the export writes. Painter's own `list_project_textures` also names maps its export does not write or refuses; the plan keeps them in `skipped` with their kind: `absent` (sources absent), `not_written` (Painter lists it, writes nothing) or `export_error` (Painter lists it, its export raises `ValueError`). With an `export_error` and no file to write, the dry run (`ListProjectTextures`, `CheckExportable`) and the export raise `ValueError` before any write; with files to write as well it is not recorded and is refused.
- **Presence.** A `documentMap` whose channel the stack lacks makes its map absent: Painter writes no file for it. A legacy name reads its OpenPBR member when the stack lacks the legacy one: `roughness` → SpecularRoughness, `metallic` → BaseMetalness, `emissive` → EmissionColor, `anisotropylevel` → SpecularRoughnessAnisotropy, `scattering` → SubsurfaceRadiusScale (decision 085), `coatopacity` → CoatWeight, `sheencolor` → FuzzColor, `sheenroughness` → FuzzRoughness, `sheenopacity` → FuzzWeight, `translucency` → SubsurfaceWeight, `scatteringcolor` → SubsurfaceColor (probe P13, byte-equal to the paired channel's export). These six, `absorptioncolor` and `specularedgecolor` are an `export_error` when the stack has neither their channel nor their pairing. A map made only of `defaultMap white` is absent; one made only of `black` is `not_written` (probe P8). An unbound mesh map is an `export_error` (probe P12). An absent `documentMap` as the alpha of present R, G and B drops the alpha: the file is R+G+B (probe P7). Refused as not recorded (R-091): any other mix of present and absent sources, and black mixed with white.
- **Names** (probes P1-P3, P9). `$textureSet` is the set's name and `$sceneMaterial` its mesh material (`original_name`). `$mesh` is the imported mesh file's name without its extension, and `$project` the project file's name without its extension, `Untitled` while it was never saved (`PlanContext::projectPath`). Under legacy colour management `$colorSpace` is empty, and in the Default workflow `$udim` and `$uvTileName` are empty, also outside a group. A `( … )` holding no parenthesis and at least one wildcard is a group: dropped when its wildcards are empty, written without its parentheses otherwise. Every other parenthesis is a literal character: `$textureSet(_v2)` → `s0(_v2)`, `$textureSet((_$udim))` → `s0()`, `$textureSet(_$udim` → `s0(_`. `/` separates sub-folders. The extension is the format's. Within one exportList entry, a later map whose path equals an earlier one's gets `_1` before its extension. Refused before writing:
  - Windows-invalid components, `.` and `..` (`ValueError`);
  - unknown wildcards (`ValueError`, with the alternatives);
  - not recorded (R-091): a mesh or project file name with more than one dot, a renamed set's `$sceneMaterial`, a group with both empty and non-empty wildcards, a `)` after no literal `(`, a third equal path;
  - two entries' files with one path, and paths equal only ignoring case: Painter lists both, but the file a case-insensitive file system keeps depends on a write order not recorded. Both are named.
- **Channels.** The destination sets are L, L+A, R+G+B and R+G+B+A. `srcChannel` L, R, G or B of a one-component source reads its value. R, G or B of a three-component source reads that component. L of a three-component source reads the Rec. 601 luma of its linear components, `fma(0.114, b, fma(0.299, r, 0.587 g))` in float32 (probe P5; the luma of an sRGB8 channel's base value is refused at evaluation, the evaluator holding its export value). Any letter of a `defaultMap` reads its constant. A of any other source is recorded only at full and no coverage (probe P6) and is refused.
- **Normal sources.** `Normal_OpenGL` and `Normal_DirectX` need a Height and a Normal channel at plan time. Their other limits (set size, a bound Normal mesh map) belong to the evaluator, which refuses them with `unsupported_source` (`NotYetSupported`) when the export evaluates every file, before any write. `meshMap normal_base` is the geometry-only pass-through. Other mesh maps are refused until recording R-090 (decision 090).
- **Diagnostics** (decision 076, `08-export.md` §6). A `diagnosticMap` source resolves in the stacks that hold its node and is absent in the others. A node in no exported stack is invalid, and so is a channel the stack lacks. A `regionStats` source is a statistics file: the map's only channel (destination L), written as canonical JSON (`<name>.json`). Anywhere else it is invalid.
- **Plan hash.** The SHA-256 of the canonical JSON of the plan without its `hash` member (`core::json::WriteCanonical`): the same project and configuration give the same bytes.

## 3. Virtual maps (decisions 086 and 092)

`Normal_OpenGL` and `Normal_DirectX` are supported. Through the plan they equal every compared golden map of the height-amplitude sweep and the Sharp and Sobel plane-strength sweeps (`test_virtual_map_goldens_exact`). The other eleven documented maps are release gaps, refused before anything is written (`parity/semantics/virtual-maps.json` states each fit):

- `AO_Mixed`: the best model of recording R-086a misses r1 at 31 values, each a few ulps from a 2^-12 boundary; no correctly rounded float32 evaluation of the tested inputs reproduces them, and Painter's arithmetic there is not identified (recording R-092).
- `Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `f0`: fitted exactly on recording R-086b at PNG 16 and OpenEXR 32f. They read each channel's per-texel coverage, which the evaluator does not give, and fixed inputs where a channel has no layer, seen on one template only (recording R-092).
- `View_2D`: a shaded render of the 2D view, not an operator on the channels.

## 4. Processing and encoders (decisions 089 and 090)

Task `phase1.16_export-processing-encoders`. Local run report: `parity/reports/phase1/export-processing-encoders.md`. Published semantics: `parity/semantics/export-processing.json` (re-derived by `python tests/export/encoders_tier0.py`). Tests: `tests/export/test_export_encoders.py`.

- **Writers (decision 089).**
  - PNG: UzPainter's own encoder over zlib. Chunks IHDR, pHYs (2835 per metre), IDAT and IEND. Rows are filtered with None, Sub or Paeth by the minimum sum of min(b, 256 - b), ties to the earlier. One zlib stream (level 6, window bits 15, memory level 8, Z_FILTERED) is split into 8192-byte IDATs.
  - OpenEXR: tinyexr, single-part scanline, PIZ, FLOAT channels `Y`, `B G R` or `A B G R`, with OpenEXR's Huffman heap tie-break as its one local change.
  - Every distinct PNG (1027) and OpenEXR (267) file Painter exported in the current envelope, decoded and encoded again, is byte-identical. That covers grey, RGB and RGBA, PNG 8 and 16, and OpenEXR 32f.
- **Values.**
  - The evaluator's read-out of each channel (an sRGB8 User channel as its linear operand).
  - PNG 16: the UNORM write rule (`arith::WriteUnorm`).
  - OpenEXR 32f: the float unchanged.
  - Written end to end by `WriteExport`, the recorded export steps of the height-normal plane goldens give Painter's bytes: 148 of 148 files.
- **Padding.**
  - With complete UV coverage, `infinite` and `passthrough` change nothing.
  - With incomplete coverage, `passthrough` is no operation; Painter's own texels outside the islands are session state.
  - Refused with incomplete coverage: `infinite`, and `passthrough` of meshMap and virtualMap sources (recording R-090).
- **Refused before anything is written** (`NotYetSupported`):
  - naming R-090: PNG 8, OpenEXR 16f, the L+A layout, an sRGB8 channel in OpenEXR, dithering, resize, and the `color`, `transparent` and `diffusion` paddings;
  - naming decision 090, recorded but not fitted: sRGB8 material channels such as BaseColor (sRGB-encoded on export) and the RGB+A layout.
- **Order.** `WriteExport` checks every file's processing and padding, then evaluates, pads and encodes every file in memory, and only then writes. A refusal or an evaluation failure leaves nothing written. Two runs in two processes write identical bytes.


## 5. Publication and receipts (decision 097)

Task `phase1.17_export-publication-receipts`. Tests: `tests/export/test_export_publication.py` (CPU, every lane).

- **Generations.** `PublishExport` holds the publication lock (`exportPath/publication.lock`) while it works:
  1. It encodes every file in memory (`EncodeExport`).
  2. It claims `exportPath/generations/<NNNNNN>/`. The number comes after every existing generation, and the directory is created only if absent.
  3. It writes `files/<relativePath>`, `plan.json` and `receipt.json`. Each one is flushed and read back to check its size and SHA-256.
  4. It renames `current.json.uzp-staging` over `current.json`. The pointer is `{schema: uzpainter/export-current/1, generation, receipt, receipt_sha256}`.

  A failure before the rename removes the new generation and returns an `export:` failure. The previous generation stays selected. An encoder that throws is caught, so the host keeps running. A refusal (`ValueError`, `NotYetSupported`) happens before anything is written.
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
  - **Resources.** `resource_hashes` lists the resources the files read: bitmaps of the read channel DAGs, a diagnostic material's masks, the mesh maps read, and the texturing mesh.
  - **Identity.** `app_version` and `build` come from the caller (`PublishRequest::identity`).
  - **Colour space.** Every image file written today is `linear`.
  - **Consumer gaps.** A SpecularWeight map carries the consumer gap of `08-export.md` §4.
