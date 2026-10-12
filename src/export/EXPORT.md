# The export plan compiler (`src/export/`)

Task `phase1.15_export-plan-compiler` (child of `phase1.18_export-engine`, P1-EXPORT). Implements `docs/architecture/08-export.md` §1 (configuration), §2 (virtual maps) and §6 (diagnostic sources) under decisions 076, 085 and 086. Tests: `tests/export/` (`zig build export-tests`, `python -m pytest tests/export`). Local run report: `parity/reports/phase1/export-plan-compiler.md`. Published semantics: `parity/semantics/virtual-maps.json` (re-derived by `python tests/export/tier0.py`).

## 1. Shape

| File | Role |
|---|---|
| `config.{h,cpp}` | `ParseConfig`: Painter's `json_config` dictionary read verbatim (export.html, "Full json_config dict possibilities") into `ExportConfig`. Checks every project-independent identifier: keys, channel letters and destination sets, `srcMapType`, the documented `srcMapName`s of each type, decision 076's `diagnosticMap` grammar, file formats, bit depths, padding algorithms, `sizeLog2`, preset references. `Nearest` orders the valid alternatives of an unknown name. |
| `plan.{h,cpp}` | `CompilePlan`: the configuration against a project (texture sets, stacks, channels, bound mesh maps) into `ExportPlan`, every output file with its sources, parameters, size, name and format, the maps skipped and the plan hash; `PlanJson` (schema `uzpainter/export-plan/1`); `FilesByStack` / `ListProjectTextures`, the dry run in `list_project_textures`'s shape; `EvaluateFileOn`, a planned file's channels evaluated on a tile store. |
| `virtual_maps.{h,cpp}` | The documented virtual maps and their support (`Support`); `EvaluateVirtualMapOn` (the combined normals of `evaluator/height_to_normal.h`) and `EvaluateMeshMapOn` (the `normal_base` geometry-only pass-through). |

Both `uzp-export-tests.exe` and `UzPainter.exe` compile these sources (`build.zig`, `export_sources`). The Python bindings (`uzpainter.export.plan`, `substance_painter.export.list_project_textures`) are `phase1.19_pyapi-native-module` item 2.7.

## 2. Semantics (decision 085)

Painter's documented semantics, with the Tier 0 recordings deciding what the documentation leaves open. The dry run of every export step of every recorded golden of the current envelope lists exactly the files Painter wrote: 166 steps over 26 project templates (`test_dry_run_equals_painter_export`).

- **Errors.** An ill-formed configuration, or one invalid for the project, throws `core::ValueError` (Painter's documented `ValueError`). The message starts with the JSON path or the file, and lists the valid alternatives nearest first: `Mixed_AO` lists `AO_Mixed` first. A well-formed request for something this build does not do throws `core::NotYetSupported` naming its owner task. A request for behaviour no recording shows also throws it, naming recording R-085 or R-086. Every failure happens before any evaluation or write.
- **Keys.** Only the documented keys. An undocumented key is refused, not ignored. `srcPath` is accepted only empty (Painter's own `list_output_maps` emits `''`). `exportShaderParams: true` is a release gap (phase2.3).
- **Presets.** `defaultExportPreset` and `exportList[].exportPreset` name inline presets. A `resource://` shelf preset is `phase1.17_export-presets`.
- **Roots.** `rootPath` is `<set>` for a set whose only stack is unnamed, `<set>/<stack>` otherwise. Any other value is a `ValueError` listing the valid roots.
- **Filters.** An absent filter or member selects everything; a present empty list selects nothing. `dataPaths` entries match a root path or its texture set. `outputMaps` entries match the unexpanded `fileName` exactly. Members combine with AND. `uvTiles` on a project without UV tiles is not recorded.
- **Parameters.** Start from the preset map's `parameters`, then apply every matching `exportParameters` rule in list order. Each defined field overrides. `fileFormat`, `bitDepth`, `dithering` and `paddingAlgorithm` must then be defined, and `dilationDistance` when the padding is `transparent`, `color` or `diffusion`. Otherwise the configuration is invalid, naming the map and the parameter. An absent `sizeLog2` is the set's size. A scalar `sizeLog2` sets the larger side and keeps the aspect; `[w, h]` sets both. `bitDepth` must suit the format: png 8 or 16, exr 16f or 32f. Formats: png and exr are written in Phase 1. TGA, BMP, JPEG and DDS belong to `phase3.2_unreal-ue56-packed-preset`. TIFF, PSD, WebP, J2K/JP2, PGM, JNG and sbsar are not in v1.
- **Presence.** A `documentMap` whose channel the stack lacks makes its map absent: Painter writes no file for it, and the plan lists it in `skipped`. A legacy name reads its OpenPBR member when the stack lacks the legacy one (`roughness` → SpecularRoughness, `metallic` → BaseMetalness, `emissive` → EmissionColor, `anisotropylevel` → SpecularRoughnessAnisotropy, `scattering` → SubsurfaceRadiusScale). A map made only of `defaultMap white` is also absent. Unrecorded combinations are refused (R-085):
  - a present source mixed with an absent one;
  - `black` only;
  - an unbound mesh map;
  - the legacy aliases never observed.
- **Names.** `$textureSet` is the set's name. Under legacy colour management `$colorSpace` is empty, and in the Default workflow `$udim` and `$uvTileName` are empty. A `( … )` group is dropped when one of its wildcards is empty, and written without its parentheses otherwise. `/` separates sub-folders. The extension is the format's. Refused before writing:
  - Windows-invalid components, `.` and `..` (`ValueError`);
  - unknown wildcards (`ValueError`, with the alternatives);
  - `$mesh`, `$project`, `$sceneMaterial`, an empty wildcard outside a group, a group without a wildcard and nested groups (not recorded, R-085);
  - two files whose paths are equal ignoring case (Painter's collision behaviour is not recorded), naming both.
- **Channels.** The destination sets are L, L+A, R+G+B and R+G+B+A. `srcChannel` L, R, G or B of a one-component source reads its value. R, G or B of a three-component source reads that component. Any letter of a `defaultMap` reads its constant. L of a colour source (an undocumented mix) and A of any source are refused.
- **Normal sources.** `Normal_OpenGL` and `Normal_DirectX` need a Height and a Normal channel at plan time. Their other limits (set size, a bound Normal mesh map) belong to the evaluator, which refuses them with `unsupported_source` (`NotYetSupported`) when the export evaluates every file, before any write. `meshMap normal_base` is the geometry-only pass-through. Other mesh maps at native precision belong to `phase1.16`.
- **Diagnostics** (decision 076, `08-export.md` §6). A `diagnosticMap` source resolves in the stacks that hold its node and is absent in the others. A node in no exported stack is invalid, and so is a channel the stack lacks. A `regionStats` source is a statistics file: the map's only channel (destination L), written as canonical JSON (`<name>.json`). Anywhere else it is invalid.
- **Plan hash.** The SHA-256 of the canonical JSON of the plan without its `hash` member (`core::json::WriteCanonical`): the same project and configuration give the same bytes.

## 3. Virtual maps (decision 086)

`Normal_OpenGL` and `Normal_DirectX` are supported. Through the plan they equal every compared golden map of the height-amplitude sweep and the Sharp and Sobel plane-strength sweeps (`test_virtual_map_goldens_exact`). `AO_Mixed` and the ten converted maps (`Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `f0`, `View_2D`) are release gaps, refused before anything is written until recording R-086 and its fit:

- `AO_Mixed`'s published operator (`parity/semantics/ao-mixed.json`, calibrated) is not exact on the opacity-0.5 set, where Painter's two recordings also disagree with each other.
- The other ten maps have no golden.
