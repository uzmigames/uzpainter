# 03 — Substance 3D Painter baking (as of 2026-10-10)

What Painter 12.1.0 bakes, which parameters exist and how they are exposed to Python, the high-poly/cage workflow, the asynchronous bake lifecycle, and how baked mesh maps feed the layer stack. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`; `PYDOC` = `PAINTER\resources\python-doc`; `PYSRC` = `PAINTER\resources\python\modules\substance_painter`; `JSDOC` = `PAINTER\resources\javascript-doc`; `MODS` = `PAINTER\resources\python\modules`; `MCP` = `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP`.
- Labels: **Fact**, **Hypothesis**, **Recommendation**; "not confirmed" marks gaps.
- "Internal identifier" = the dotted parameter id stored in project files (e.g. `Detail.HipolyMesh`). "Python key" = the key of the dict returned by `BakingParameters.common()` / `baker()`.

## 1. Bakers (mesh maps)

`textureset.MeshMapUsage` has 10 members; each is one baker and one mesh-map slot of a Texture Set (**Fact**, `PYSRC\textureset.py` → `MeshMapUsage`; `PYDOC\substance_painter\baking.html`).

| `MeshMapUsage` | Internal baker id | "Mesh Maps" export / effect identifier | Effect-input usage | Baker-specific UI parameters (Adobe docs) |
|---|---|---|---|---|
| `Normal` | withheld (see note) | `normal_base` | `normalBase` | none listed beyond common |
| `WorldSpaceNormal` | withheld (see note) | `world_space_normals` | `normalWS` | none listed |
| `ID` | withheld (see note) | `id` | `id` | Color source (Vertex Color, Material Color, File ID, Mesh ID/Polygroup); Color generator (Random, Hue shift, Grayscale) |
| `AO` | withheld (see note) | `ambient_occlusion` | `ambientOcclusionBase` | Secondary rays, Min/Max occluder distance, Spread angle, Distribution, Ignore backface, Self occlusion, Ground plane, Ground plane offset |
| `Curvature` | withheld (see note) | `curvature` | `curvature` | Method, Secondary rays, Sampling radius, Self intersection, Auto tonemapping, Tonemapping min/max |
| `Position` | withheld (see note) | `position` | `position` | Mode (all axis / single axis), Axis, Normalization type, Normalization scale |
| `Thickness` | withheld (see note) | `thickness` | `thickness` | Secondary rays, Min/Max occluder distance, Spread angle, Distribution, Self occlusion, Normalization |
| `Height` | withheld (see note) | `height_base` (preset output) | `heightBase` | Normalization, Scaling divisor |
| `BentNormals` | withheld (see note) | `bent_normals_base` (preset output) | `bentNormalsBase` | Secondary rays, Min/Max occluder distance, Spread angle, Distribution, Ignore backface, Self occlusion |
| `Opacity` | withheld (see note) | `opacity_base` (preset output) | `opacityBase` | none listed |

Sources and labels:
- Internal baker ids: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.]
- Export identifiers: **Fact** — output file names of the shipped `Mesh Maps` export preset (`$textureSet_normal_base`, `_world_space_normals`, `_id`, `_position`, `_bent_normals_base`, `_ambient_occlusion`, `_curvature`, `_thickness`, `_height_base`, `_opacity_base`); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.]
- Effect-input usages/identifiers: **Fact** — Adobe, "Mesh Map" (custom effects): https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/content/creating-custom-effects/mesh-map ("the usage has the priority").
- Per-baker UI parameters: **Fact** — Adobe, "Mesh map settings": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/baking/mesh-map-settings.
- Curvature method: `baking.CurvatureMethod` = `FromMesh`, `FromNormalMap` (**Fact**, `PYSRC\baking.py`); the JS API marks `FromNormalMap` as deprecated (**Fact**, `JSDOC\alg.baking.html` → `curvatureMethod`). Since API 0.3.5 the "Curvature From Map" baker lost `PerVertex` (always per fragment) and `TonemappingMin`/`TonemappingMax` became `TonemappingBounds` (array of 2 floats) (**Fact**, `PYDOC\index.html` changelog 0.3.5).

## 2. How parameters are exposed to Python

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Entry point | `BakingParameters.from_texture_set(ts)` / `from_texture_set_name(name)` | Fact | `PYDOC\substance_painter\baking.html` |
| Common parameters | `common()` returns `{Property.short_name(): Property}`; high-poly/cage settings are among its keys (the documented example sets `common()['HipolyMesh']`) | Fact | `PYDOC\substance_painter\baking.html`; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\baking.py.] |
| Per-baker parameters | `baker(MeshMapUsage)` returns `{short_name: Property}` | Fact | `PYDOC\substance_painter\baking.html` |
| Writing | `BakingParameters.set({Property: value, ...})` (static, batch) | Fact | `baking.html` |
| Property introspection | `Property.value()`, `name()`, `short_name()`, `label()`, `widget_type()`, `enum_values()` (label→int for 'Combobox'), `enum_value(label)`, `properties()` (JSON of meta properties, e.g. ranges) | Fact | `PYDOC\substance_painter\properties.html` |
| Discovery | Parameter names are not listed in the docs; Adobe's own example prints `common().keys()` and `baker(MeshMapUsage.AO).keys()` to discover them | Fact | `baking.html` (`BakingParameters` example) |
| Value types | `PropertyValue` = bool, int, int tuples (2–4), float, float tuples (2–4), `Color`, `(Color, float)`, str | Fact | `PYSRC\properties.py` |
| Python-key naming | Observed keys equal the last component of the internal identifier: `OutputSize` (`Common.OutputSize`), `HipolyMesh`, `LowAsHigh`, `CageMode`, `CageMesh` (Adobe tests), `SubSampling`, `DilationWidth`, `OffsetMap` (MCP code/docs), `Distribution` (AO, Adobe test), `NbSecondary` (AO), `AutoMinMax` (Curvature) (MCP docs). | Fact for the listed keys; general rule Hypothesis | `MODS\automated_tests\test_baking.py`; `MODS\engine_tests\test_baking.py`; `MCP\src\substance_painter_mcp\operations.py` (`preflight_bake`: `common.get("SubSampling")`); `MCP\docs\PROCEDURAL_AND_BAKING.md` |
| JS equivalent | `alg.baking.textureSetBakingParameters(name)` returns `{materialParameters: {commonParameters: {Apply_Diffusion, Dilation_Width, Output_Size}, detailParameters: {Antialiasing, Average_Normals, …}}, definitions: {Ambient_occlusion: {enabled, parameters: {Attenuation: "Linear", Distribution: "Cosine", Ignore_Backface, Max_Occluder_Distance: 0.1, Min_Occluder_Distance: 0.00001, Relative_to_Bounding_Box, Secondary_Rays: 64, Self_Occlusion: "Always", Spread_Angle: 180}}, …}}` (labels with underscores) | Fact (example values from the doc) | `JSDOC\alg.baking.html` (`textureSetBakingParameters` example) |

## 3. Parameter catalogue

Internal identifiers below were read from project/template files saved by recent Painter versions (`PAINTER\resources\samples\FrenchRestaurantTable.spp`, `PAINTER\resources\starter_assets\templates\Unreal Engine.spt`) — **Fact** (strings present). Grouping by baker is a **Hypothesis** ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.]). UI labels are from Adobe's docs; the internal-id ↔ UI-label pairing is a **Hypothesis** unless a source is given. Values found in these files are stored specimen values (what one saved file contains), not Painter 12.1 initialization defaults, and JS-doc values are example inputs (**Fact** for the distinction; current defaults **not confirmed**).

### 3.1 Common and high-poly ("detail") parameters

| Internal identifier | Python key | Likely UI label | Type / values | Value seen (example or stored specimen; not a confirmed 12.1 default) | Label / source |
|---|---|---|---|---|---|
| `Common.OutputSize` | `OutputSize` | Output size | pair of log2 sizes, e.g. `(10, 10)` = 1024×1024; `(11, 11)` = 2048 | not confirmed | Fact for key and log2 encoding — `JSDOC\tutorial-baker_parameters.html` ("Output_Size … [10, 10] … 1024x1024"); `PYDOC\…\baking.html` example `(10,10)` |
| `Common.DilationWidth` | `DilationWidth` | Dilation width | int (pixels) | JS example `Dilation_Width: 32` | Fact (JS example); key Fact (MCP docs) |
| `Common.ApplyDiffusion` | `ApplyDiffusion` | Apply diffusion | bool | JS example `false` | Fact (JS example); key Hypothesis |
| `Detail.LowAsHigh` | `LowAsHigh` | Use low poly mesh as high poly mesh | bool | — | Fact (Adobe test) |
| `Detail.HipolyMesh` | `HipolyMesh` | High definition meshes | string: `file:///` URLs joined with a pipe character (Adobe builds them with `QUrl.fromLocalFile(...).toString()`) | — | Fact — community MCP bridge `MCP\src\substance_painter_mcp\operations.py` (pipe join); `baking.html` example (QUrl); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.] |
| `Detail.CageMode` | `CageMode` | Cage | enum: "Distance-based", "Automatic (experimental)", "Custom file"; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.] | — | Fact — release notes 11.0 (https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/old-versions/version-11-0); `MODS\engine_tests\test_baking.py`; labels also in `MCP\src\substance_painter_mcp\operations.py` (`cage_modes`) |
| `Detail.CageMesh` | `CageMesh` | Cage file | `file:///` URL string | — | Fact (Adobe test) |
| `Detail.MaxHeight` | not confirmed | Max frontal distance | float | not confirmed | Hypothesis (name pairing); UI meaning — Adobe Bakers "Common Parameters": https://experienceleague.adobe.com/en/docs/substance-3d/bakers/bakers-settings/common-parameters ("no effect when a Cage is used") |
| `Detail.MaxDepth` | not confirmed | Max rear distance | float | not confirmed | Hypothesis (same source) |
| `Detail.RelativeScale` | not confirmed | Relative to bounding box | bool | not confirmed | Hypothesis |
| `Detail.SmoothNormals` | not confirmed | Average normals | bool | JS example `Average_Normals: true` | Hypothesis |
| `Detail.IgnoreBackface` | not confirmed | Ignore backface | bool | not confirmed | Hypothesis |
| `Detail.FilterMethod` | not confirmed | Match (Always / By mesh name) | enum | not confirmed | Hypothesis |
| `Detail.LowpolySuffix` | not confirmed | Low poly mesh suffix | string | `_low` | Fact (value stored after the id in `layerstack-cube.spp` and `Unreal Engine.spt`); 12.1 default not confirmed |
| `Detail.HipolySuffix` | not confirmed | High poly mesh suffix | string | `_high` | Fact (stored, same files); default not confirmed |
| `Detail.BackfaceCullingSuffix` | not confirmed | (ignore-backface name suffix) | string | `_ignorebf` | Fact (stored, same files); default and UI label not confirmed |
| `Detail.SubSampling` | `SubSampling` | Antialiasing | enum; Adobe Bakers docs list None, Subsampling 2x2, 4x4, 8x8 | JS example `Antialiasing: "None"` | key Fact (MCP code); values Fact for Bakers docs, Hypothesis for Painter |
| `Detail.SkewFaceBehavior` | `SkewFaceBehavior` (per MCP docs) | skew-correction behaviour | not confirmed | — | Fact that it exists in 12.x files; MCP docs name it (`MCP\docs\RESOURCE_INGESTION.md`) |
| `Detail.OffsetMap` | `OffsetMap` | skew map ("grayscale skew-correction map", Resource widget) | Resource | — | Fact (string in 12.x files); semantics per `MCP\docs\RESOURCE_INGESTION.md` (third-party claim) |

UI "Skew correction" group also lists Paint skew correction, Edge protection, Edge distance, Edge contrast (**Fact**, Adobe "Mesh map settings" page); their internal ids are **not confirmed**. Painter 12.1 "Auto Rebake" and "Skew Painting" mode have no public Python method (**Fact** for absence in `PYSRC\baking.py`; the MCP author reached the same conclusion: `MCP\docs\PRODUCTION_BAKING.md`).

### 3.2 Per-baker parameters (internal ids)

| Baker (hypothesised) | Internal identifiers | Likely UI labels |
|---|---|---|
| ID | `Detail.Color.ColorSource`, `Detail.Color.ColorGenerator` | Color source, Color generator |
| AO | `Detail.SecondaryCommon.NbSecondary`, `.MinDistance`, `.MaxDistance`, `.MaxDistanceRelativeScale`, `.Spread`, `.Distribution`, `.IgnoreBackfaceSecondary`, `.FilterMethodSecondary`; `Detail.AO.Attenuation`, `Detail.AO.GroundPlane`, `Detail.AO.GroundOffset` | Secondary rays, Min/Max occluder distance, relative-to-bbox, Spread angle, Distribution, Ignore backface, Self occlusion, Attenuation, Ground plane, Ground plane offset |
| Curvature | `Detail.SecondaryCommon.NbSecondary`, `Detail.SecondaryCommon.SamplingRadius` (older files: `Detail.Curvature1.SamplingRadius`), `.MaxDistanceRelativeScale`, `.FilterMethodSecondary`, `Detail.Curvature1.AutoMinMax`, `Detail.Curvature1.TonemappingBounds` (older: `TonemappingMin`/`TonemappingMax`) | Secondary rays, Sampling radius, Self intersection, Auto tonemapping, Tonemapping min/max |
| Position | `Position.Mode`, `Position.Axis`, `Position.Normalization`, `Position.NormalizationScale` | Mode, Axis, Normalization type, Normalization scale |
| Thickness | `Detail.SecondaryCommon.*` (NbSecondary, MinDistance, MaxDistance, MaxDistanceRelativeScale, Spread, Distribution, FilterMethodSecondary), `Detail.Distance.MaximizeRange` | Secondary rays, Min/Max occluder distance, Spread angle, Distribution, Self occlusion, Normalization |
| Height | `Detail.Distance.MaximizeRange`, `Detail.Distance.Divisor` | Normalization, Scaling divisor |
| Bent normals | `Detail.SecondaryCommon.*` incl. `IgnoreBackfaceSecondary` | Secondary rays, Min/Max occluder distance, Spread angle, Distribution, Ignore backface, Self occlusion |
| Normal, World-space normal, Opacity | none identified besides common/detail ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.]; this does not prove the native bakers have no options in every version or context) | — |

Sources: strings in `FrenchRestaurantTable.spp`, `JadeToad.spp`, `Unreal Engine.spt`, `layerstack-cube.spp` (**Fact** for presence); grouping/labels **Hypothesis**; UI labels **Fact** for the Adobe "Mesh map settings" page. The JS example values for AO (`Secondary_Rays: 64`, `Spread_Angle: 180`, `Min_Occluder_Distance: 0.00001`, `Max_Occluder_Distance: 0.1`, `Distribution: "Cosine"`, `Attenuation: "Linear"`, `Self_Occlusion: "Always"`) are documented example values, not confirmed defaults (`JSDOC\alg.baking.html`).

### 3.3 Generic Bakers reference (not Painter-specific)

Adobe's Substance 3D Bakers "Common Parameters" page lists: Size (32…8192, non-square allowed, default 2048), Format, Anti-Aliasing (None, Subsampling 2x2/4x4/8x8), UV Set, Dilation (px), Apply Diffusion, Average Normals, High Definition Meshes, Use Low as High Definition, Set Distance With Cage, Cage File, Frontal Value (Max Frontal Distance), Rear Value (Max Rear Distance), Relative to Bounding Box, Match (Always, By Mesh Name), Match Suffixes, Use Skew Correction, Skew Map, Invert Skew Correction (**Fact** for that page: https://experienceleague.adobe.com/en/docs/substance-3d/bakers/bakers-settings/common-parameters). Whether every item maps 1:1 to a Painter 12.1 parameter is **not confirmed**.

**Recommendation**: before treating any value in §3 as a default, capture on a freshly created 12.1 project, per Texture Set and versioned separately from the specimen values: `common()` and `baker(usage)` for all ten `MeshMapUsage` (`Property.value()`, `widget_type()`, `enum_values()`, `properties()`), the curvature method, enabled bakers/UV tiles and the link groups, then bake a fixed fixture and keep the outputs as the reference.

## 4. High-poly workflow

| Step | API / rule | Label | Source |
|---|---|---|---|
| Choose sources | `HipolyMesh` = pipe-joined file URLs of one or more high-poly meshes; `LowAsHigh=True` bakes the low poly onto itself | Fact | community MCP bridge `MCP\src\substance_painter_mcp\operations.py` (pipe join); "Use low poly mesh as high poly mesh" (Adobe "Mesh map settings"); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\common\baking_scenario.py.] |
| Match by name | `FilterMethod` (Match: Always / By mesh name) with `LowpolySuffix` `_low`, `HipolySuffix` `_high` defaults | Fact (values stored in specimens, UI options); 12.1 defaults and key pairing Hypothesis | §3.1 |
| Ray distance | Distance-based cage: Max frontal / rear distance, optionally relative to bounding box | Fact (UI); key pairing Hypothesis | §3.1; Adobe Bakers page |
| Cage | `CageMode` = Distance-based / Automatic (experimental, since 11.0) / Custom file + `CageMesh` URL | Fact | release notes 11.0; `MODS\engine_tests\test_baking.py` |
| Antialiasing | `SubSampling` | Fact (key) | `MCP\…\operations.py` |
| Output size / dilation | `OutputSize` (log2 pair), `DilationWidth`, `ApplyDiffusion` | Fact | §3.1 |
| Output format of baked maps | not configurable through the Python baking API (no format parameter in `common()` keys seen); baked maps are stored as project resources | Hypothesis (absence of a format key in observed ids) | §3.1 strings; `resource.html` (baked AO example is a PROJECT resource) |
| Allowed high-poly file types | not documented in the Python docs; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.]; the MCP accepts FBX, Alembic, OBJ, DAE, PLY, glTF, GLB and USD family | Fact (MCP list); list not confirmed by Adobe | `MODS\engine_tests\test_baking.py`; `MCP\docs\PRODUCTION_BAKING.md` |

## 5. Scope, linking and execution

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Texture Set enable | `is/set_textureset_enabled` | Fact | `baking.html` |
| Baker enable | `is/set_baker_enabled(usage)`, `get/set_enabled_bakers(list)` | Fact | `baking.html` |
| UV-tile selection | `is/set_uv_tile_enabled(tile)`, `get/set_enabled_uv_tiles(list)`; `bake_async` honours the UV-tile selection since 0.2.9 | Fact | `baking.html`; changelog 0.2.9 |
| Curvature method | `get/set_curvature_method(CurvatureMethod)` | Fact | `baking.html` |
| Linking | Texture Sets can share common parameters (`set_linked_group_common_parameters(group, reference)`) and per-usage parameters (`set_linked_group(group, reference, usage)`); `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`. Common parameters are linked across all Texture Sets at project creation. | Fact (documented example comment); not verified as a runtime guarantee for every project | `baking.html` (example comment "True at project creation") |
| Launch | `bake_async(texture_set) -> StopSource`; `bake_selected_textures_async() -> StopSource` (all enabled Texture Sets) | Fact | `baking.html` |
| Cancel | `StopSource.request_stop()`, `stop_requested()` | Fact | `PYDOC\substance_painter\async_utils.html` |
| Events | `BakingProcessAboutToStart(stop_source)`, `BakingProcessProgress(progress: float)`, `BakingProcessEnded(status: BakingStatus)`; `BakingStatus` = `Success`, `Cancel`, `Fail` ("cause is detailed in the log") | Fact | `PYSRC\event.py`; `PYSRC\baking.py` |
| Per-baker error detail | not provided by the public event (global status only) | Fact (event fields); MCP author states the same | `PYSRC\event.py`; `MCP\docs\PRODUCTION_BAKING.md` ("Result manifests") |
| UI mode | `ui.UIMode.Baking`, `ui.switch_to_mode` exist but are not required to bake from Python ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.]) | Fact (enum); Hypothesis (not required) | `PYSRC\ui.py`; `MODS\engine_tests\test_baking.py` |
| Busy state | baking makes `project.is_busy()` true; saving is refused while busy | Fact | `project.html` (`is_busy`) |

## 6. Where baked maps go and how they are consumed

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Storage | Baked maps are resources embedded in the project (`ResourceLocation.PROJECT`), e.g. `ResourceID.from_project(name="ambient_occlusion")` | Fact | `PYSRC\resource.py` (`ResourceLocation` example) |
| Slot assignment | Each Texture Set has one slot per `MeshMapUsage`: `TextureSet.get_mesh_map_resource(usage) -> ResourceID or None`, `set_mesh_map_resource(usage, ResourceID or None)` | Fact | `PYDOC\substance_painter\textureset\textureset.html` |
| Import instead of bake | `project.create(mesh, mesh_map_file_paths=[...])` loads pre-baked maps (Adobe example names `DefaultMaterial_ambient_occlusion.png`, `DefaultMaterial_id.png`; a `.1001` file loads the whole UDIM sequence) | Fact (API and example); automatic slot detection from file names Hypothesis | `PYDOC\substance_painter\project.html` → "Creating a project" |
| Replace/update | `resource.list_project_resources` / `replace_project_resources` include mesh maps ("resources used by the layer stacks and mesh maps" in the older API) | Fact | `resource.html`; changelog 0.2.1 |
| Generators | "Generator substances generate a mask or a material based on the mesh topology using the additional maps setup in the TextureSet Settings." | Fact | `PYDOC\substance_painter\layerstack\layereffect\generator.html` |
| Binding rule | A substance graph input is auto-connected to a mesh map when its usage (preferred) or identifier matches the table in §1 | Fact | Adobe "Mesh Map": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/content/creating-custom-effects/mesh-map |
| Shipped generators | 21 `.sbsar` in `PAINTER\resources\starter_assets\generators\`: `3d_distance, 3d_linear_gradient, advanced_tri-planar, grayscale_conversion, inflate_shrinkwrap, light, mg_ambient_occlusion, mg_auto_stitcher, mg_curvature, mg_dirt, mg_dripping_rust, mg_fiber_glass_edge_wear, mg_mask_builder, mg_mask_editor, mg_metal_edge_wear, mg_position, mg_uv_border_distance, mg_world_space_normals, uv_checker, uv_random_color, uv_texel_density` | Fact (listing) | directory listing |
| Which mesh maps each generator / smart material reads | not confirmed (requires reading each `.sbsar` graph's inputs) | not confirmed | — |
| Color Selection effect | reads a `Usage.TEXTURE` project resource, "Typically the ID Mask baked map" | Fact | `layereffect\colorselection.html` |
| Shading and export | Converted export maps mix bakes with channels: "Normal OpenGL/DirectX" = baked normal combined with the Texture Set normal channel; "Mixed AO" = baked AO combined with the AO channel | Fact | Adobe "Output templates": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/export-window/output-templates |
| Project-level blending of additional maps | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] No Python accessor was found in the public API. | Fact (absence in the public API) | `PYDOC\substance_painter\textureset\textureset.html` |

## 7. Facts relevant to quality

| Statement | Label | Source |
|---|---|---|
| Adobe advises keeping mesh maps at least 16-bit to avoid artefacts and baking different maps at different resolutions to save space. | Fact | Adobe "Projects are really big": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/technical-support/workflow-issues/project-issues/projects-are-really-big |
| Baked mesh maps are one of the four kinds of data Adobe lists as stored inside the project (with the processed source mesh, materials and bitmaps used by layers/presets/strokes). | Fact | same page |
