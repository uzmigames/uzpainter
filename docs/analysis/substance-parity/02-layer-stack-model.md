# 02 — Substance 3D Painter layer-stack data model (as of 2026-10-10)

How Painter 12.1.0 structures a texturing document — Texture Sets, stacks, channels, layers, effects, masks, blending, sources, projections, geometry masks, smart assets, resources and UV tiles — as exposed to Python. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`. `PYDOC` = `PAINTER\resources\python-doc`. `PYSRC` = `PAINTER\resources\python\modules\substance_painter`. `TESTS` = `PAINTER\resources\python\modules\automated_tests` and `...\engine_tests` (Adobe's shipped test suites).
- Labels: **Fact** = stated in, or computed this session from, the cited source; **Hypothesis** = inferred, not confirmed; **Recommendation** = ours. "Not confirmed" marks gaps.
- Symbol signatures are listed exhaustively in `01-python-api-inventory.md`; this file explains the model and the rules.

## 1. Containment hierarchy

| Level | Python object | Key facts | Label | Source |
|---|---|---|---|---|
| Project | `substance_painter.project` (module-level state; one open project at a time) | `create`/`open` raise `ProjectError` if a project is already open. | Fact | `PYDOC\substance_painter\project.html` (`create`, `open` raises) |
| Texture Set | `textureset.TextureSet(material_id)` | One per material of the imported mesh (or per UV tile in the legacy `TextureSetPerUVTile` workflow). Has a resolution, one or more stacks, optional UV tiles, and a set of baked mesh-map slots (`MeshMapUsage`). Names must be unique; `original_name` keeps the import name. | Fact | `PYDOC\substance_painter\textureset\textureset.html`; `project.html` (`ProjectWorkflow`) |
| Stack | `textureset.Stack(stack_id)` | Normally one stack, "transparent to the user"; a Texture Set using material layering (custom layering shader) has several named stacks (e.g. `"Mask1"`); the stack name is empty when material layering is not used. Upstream contradiction: the `Stack.name()` paragraph says the reverse ("A stack name is empty if the Texture Set it belongs to uses material layering"); this row follows the class examples and `Stack.from_name` ("Leave empty if the Texture Set does not use material layering"). | Fact (examples, `from_name`); which text is right not confirmed | `PYDOC\substance_painter\textureset\stack.html` |
| Channel | `textureset.Channel(channel_id)` | A stack holds at most one channel per `ChannelType`; each channel has a `ChannelFormat`; user channels `User0`..`User31` can carry a label. `add_channel`/`remove_channel` are not available with material layering. | Fact | `PYDOC\substance_painter\textureset\channel.html`; `stack.html` |
| Layer stack | `layerstack.get_root_layer_nodes(stack)` | Root layers of one stack, ordered like the UI (top first). Requires an open project in edition state. | Fact | `PYDOC\substance_painter\layerstack\navigation.html`; `layerstack\index.html` |
| Layer | `layerstack.LayerNode` subclasses | Lives in the main hierarchy (root or inside a group). Has a content-effect stack and an optional mask stack. | Fact | `layerstack\navigation.html` (`LayerNode`) |
| Effect | `layerstack.*EffectNode` | Lives in a layer's content stack (`NodeStack.Content`) or mask stack (`NodeStack.Mask`). | Fact | `layerstack\edition.html` (`NodeStack`) |
| UV tile | `textureset.UVTile(u, v)` | Belongs to a Texture Set using the UV-tile workflow; can override its resolution (square, power of 2). | Fact | `PYDOC\substance_painter\textureset\uvtile.html` |

Every node has an integer internal uid (`Node.uid()`, "Get the object internal uid"), and `layerstack.get_node_by_uid(uid)` re-resolves it; calling a method with a uid that "no longer refers to existing data in the Layer Stack" raises `ValueError` (**Fact**, `layerstack\navigation.html` → `Node`, `Node.uid`). The docs do not promise that a uid survives project reload, node re-creation or undo/redo (**not confirmed**).

## 2. Node kinds

`layerstack.NodeType` has 12 members; each maps to one Python class (**Fact**, `PYSRC\layerstack.py` → `NodeType` docstring and class definitions).

| `NodeType` | Python class | Layer or effect | What it is (Adobe wording) | Insert with | Own API beyond `Node`/`LayerNode` |
|---|---|---|---|---|---|
| `PaintLayer` | `PaintLayerNode` | layer | "can be painted on with brushes and particles" | `insert_paint(pos)` | none; "Strokes are not accessible from the Python API" |
| `PaintEffect` | `PaintEffectNode` | effect | same, as an effect | `insert_paint(pos)` | none (strokes inaccessible) |
| `FillLayer` | `FillLayerNode` | layer | "takes a material or resources as input" | `insert_fill(pos)` | sources, active channels, projection, symmetry (mixins) |
| `FillEffect` | `FillEffectNode` | effect | same, as an effect | `insert_fill(pos)` | same as fill layer |
| `GeneratorEffect` | `GeneratorEffectNode` | effect | takes a Generator substance (`Usage.GENERATOR`) | `insert_generator_effect(pos, res=None)` | `get_source`/`set_source(res)`/`remove_source`, `active_channels` |
| `FilterEffect` | `FilterEffectNode` | effect | takes a Filter substance (`Usage.FILTER`) | `insert_filter_effect(pos, res=None)` | `get_source`/`set_source(res)`/`remove_source`, `active_channels` |
| `LevelsEffect` | `LevelsEffectNode` | effect | "adjust the color ranges of an image" | `insert_levels_effect(pos)` | `affected_channel`, `get/set_parameters(LevelsParams)` |
| `CompareMaskEffect` | `CompareMaskEffectNode` | effect (mask stack only) | compares two channels to produce a mask | `insert_compare_mask_effect(pos)` | `get/set_parameters(CompareMaskEffectParams)` |
| `ColorSelectionEffect` | `ColorSelectionEffectNode` | effect (mask stack only) | extracts colors from a bitmap (usually the ID map) into a mask | `insert_color_selection_effect(pos)` | `get/set_parameters(ColorSelectionEffectParams)` |
| `GroupLayer` | `GroupLayerNode` | layer | contains other layers | `insert_group(pos)` | `sub_layers()`, `is_collapsed()`/`set_collapsed()` |
| `InstanceLayer` | `InstanceLayerNode` | layer | synchronizes a layer across layers/Texture Sets; "Only the source layer can be modified" — this covers the synchronized content: the same page's example renames instances (`instance1.set_name`), and instances "still generate a mesh dependent result" | `instantiate(pos, layer)` | `instance_source()`; the source exposes `LayerNode.instances()` |
| `AnchorPointEffect` | `AnchorPointEffectNode` | effect | exposes an element of the stack for reuse elsewhere | `insert_anchor_point_effect(pos, name)` | none (referenced by `SourceReference`) |

Sources: `PYDOC\substance_painter\layerstack\layereffect\{paint,fill,generator,filter,levels,comparemask,colorselection,group,instance,anchorpoint}.html` (**Fact**). Smart materials and smart masks are not node types: `insert_smart_material` returns a `GroupLayerNode`; `insert_smart_mask` returns the list of inserted effect nodes (**Fact**, `layereffect\smartmaterial.html`, `smartmask.html`).

### 2.1 Common node API

| Capability | API | Rule | Label | Source |
|---|---|---|---|---|
| Name | `get_name`, `set_name` | names are not unique (MCP uses uids for that reason) | Fact (API); Fact (MCP note) | `navigation.html`; `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\README.md` ("Layer names are not unique in Painter") |
| Visibility | `is_visible`, `set_visible` | — | Fact | `navigation.html` |
| Hierarchy | `get_parent`, `get_next_sibling`, `get_previous_sibling`, `get_stack`, `get_texture_set`, `is_in_mask_stack` | parent is `None` for root layers | Fact | `navigation.html` |
| Delete | `delete_node(node)` | — | Fact | `edition.html` |
| Move/reorder existing node | none | No public move/reparent function exists in `layerstack.py`; only insert positions for new nodes. | Fact (absence) | `PYSRC\layerstack.py`; also `SubstancePainterMCP\docs\ROADMAP.md` → "Safety constraint: existing-layer movement" |
| Duplicate/copy node | none | No public duplicate/copy function in `layerstack.py`. | Fact (absence) | `PYSRC\layerstack.py` |
| Undo grouping | `with ScopedModification(name):` | groups many calls into one history entry and one recomputation; `set_selected_nodes`/`set_selection_type` raise `RuntimeError` inside it | Fact | `edition.html` (`ScopedModification`); `selection.html` |
| Selection | `get_selected_nodes(stack)`, `set_selected_nodes(nodes)`, `get_selection_type(layer)`, `set_selection_type(layer, SelectionType)` | `SelectionType`: `Content`, `Mask`, `GeometryMask`, `Properties` (instances only) | Fact | `PYDOC\substance_painter\layerstack\selection.html` |
| Layer color tag | not exposed | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] | not confirmed from public sources | — |

## 3. Insertion rules

`InsertPosition` is built with `from_textureset_stack(stack)` (top of a stack), `above_node(node)`, `below_node(node)` or `inside_node(node, NodeStack)` where `NodeStack` is `Substack` (inside a group), `Content` or `Mask`. The same `insert_fill`/`insert_paint` produce a layer or an effect depending on the position (**Fact**, `PYDOC\substance_painter\layerstack\edition.html`).

When the reference node is a layer (x = allowed), parsed from the HTML tables of `edition.html` (**Fact**):

| Node type | From Texture Set stack / above / below / inside group (`Substack`) | Inside layer `Content` | Inside layer `Mask` |
|---|---|---|---|
| Paint | x | x | x |
| Fill | x | x | x |
| Generator | | x | x |
| Filter | | x | x |
| Levels | | x | x |
| Compare Mask | | | x |
| Color Selection | | | x |
| Group | x | | |
| Anchor Point | | x | x |
| Smart Mask | | | x |
| Smart Material | x | | |
| Instance | x | | |

When the reference node is an effect: Paint, Fill, Generator, Filter, Levels and Anchor Point can go above/below an effect in a Content or a Mask stack; Compare Mask, Color Selection and Smart Mask only in a Mask stack; Group, Smart Material and Instance cannot be placed relative to an effect (**Fact**, same tables).

## 4. Masks

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Creation | `LayerNode.add_mask(MaskBackground)`; `MaskBackground.Black` = "Everything is discarded by default", `White` = "Everything is included by default". Raises if a mask already exists. | Fact | `navigation.html` (`add_mask`, `MaskBackground`) |
| State | `has_mask`, `remove_mask` (removes all mask effects), `get/set_mask_background`, `is_mask_enabled`, `enable_mask` | Fact | `navigation.html` |
| Content | Mask effects are inserted with `InsertPosition.inside_node(layer, NodeStack.Mask)` and read with `LayerNode.mask_effects()`; content effects with `content_effects()`. | Fact | `edition.html`; `navigation.html` |
| Mono-channel | Fill effects in a mask stack are mono-channel: `set_source(None, source)`; `get/set_material_source` not allowed; `source_mode` is `None`. | Fact | `layereffect\fill.html` (example comments) |
| Mask-only effects | Compare Mask, Color Selection and Smart Mask can only be inserted in a mask stack. | Fact | `layereffect\comparemask.html`, `colorselection.html`, `smartmask.html` |
| Geometry mask | separate from the paint mask; see §10 | Fact | `navigation.html` |

## 5. Blending and opacity

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Per-channel blending | Outside a mask stack, blend mode and opacity are per `ChannelType`: `get/set_blending_mode(mode, channel)`, `get/set_opacity(value 0.0–1.0, channel)`; passing no channel raises `ValueError`. | Fact | `navigation.html` (`Node.get_blending_mode` …) |
| Mask-stack blending | Inside a mask stack blending is mono-channel; the channel argument must be `None`. | Fact | same |
| Nodes without blending | `Node.has_blending()` tells whether a node carries blending; Adobe's example comment: "e.g.: Levels Effect does not". | Fact | `navigation.html`; `layereffect\paint.html` (example) |
| Blend modes | 32 members: `Normal, PassThrough, Disable, Replace, Multiply, Divide, InverseDivide, Darken, Lighten, LinearDodge, Subtract, InverseSubtract, Difference, Exclusion, SignedAddition, Overlay, Screen, LinearBurn, ColorBurn, ColorDodge, SoftLight, HardLight, VividLight, LinearLight, PinLight, Tint, Saturation, Color, Value, NormalMapCombine, NormalMapDetail, NormalMapInverseDetail`. Normal-map modes: Combine = "Whiteout Blending", Detail = "Reoriented Normal Mapping", InverseDetail = bottom layer reoriented to the top. Complete numerical blend formulas are not given in the shipped docs (**not confirmed**). | Fact | `PYSRC\layerstack.py` → `BlendingMode` docstring |
| Serialization | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] | — | — |

## 6. Channels and formats

### 6.1 Channel types (`textureset.ChannelType`)

| Group | Members | Label | Source |
|---|---|---|---|
| OpenPBR (default names since API 0.3.7 / Painter 12.1.0) | `BaseWeight, BaseColor, BaseMetalness, BaseDiffuseRoughness, SpecularWeight, SpecularColor, SpecularRoughness, SpecularRoughnessAnisotropy, TransmissionWeight, TransmissionColor, SubsurfaceWeight, SubsurfaceColor, SubsurfaceRadiusScale, CoatWeight, CoatColor, CoatRoughness, CoatRoughnessAnisotropy, CoatNormal, CoatTangent, FuzzWeight, FuzzColor, FuzzRoughness, EmissionColor, ThinFilmWeight, Opacity, Height, Displacement, Normal, Tangent, AO` | Fact | `PYSRC\textureset.py` → `ChannelType` docstring; `PYDOC\index.html` changelog 0.3.7 |
| User channels | `User0` … `User31` (labels via `Channel.label()` / `edit(format, label)`) | Fact | same; `textureset\channel.html` |
| Legacy / Adobe Standard Material (non-OpenPBR) | `Glossiness, Specular, Anisotropyangle, Transmissive, Reflection, Ior, Diffuse, Specularlevel, BlendingMask, CoatSpecularLevel` | Fact | same |
| Legacy aliases | `Metallic, Roughness, Emissive, SpecularEdgeColor, Anisotropylevel, Scattering, ScatteringColor, Translucency, AbsorptionColor, SheenOpacity, SheenRoughness, SheenColor, CoatOpacity` (aliases kept for backward compatibility) | Fact | same; changelog 0.3.7 ("keep legacy/Adobe Standard Material channel names as aliases") |
| Which alias maps to which OpenPBR name | e.g. `Metallic`→`BaseMetalness`, `Roughness`→`SpecularRoughness`, `Emissive`→`EmissionColor` | Hypothesis (pairing not stated in the docs) | not confirmed; validate by comparing `ChannelType.Metallic == ChannelType.BaseMetalness` inside Painter |
| Export map names | The export JSON `documentMap` names are the legacy lower-case identifiers (`basecolor, height, specular, opacity, emissive, displacement, glossiness, roughness, anisotropylevel, anisotropyangle, transmissive, scattering, reflection, ior, metallic, normal, ambientOcclusion, diffuse, specularlevel, blendingmask, user0`…`user7`). | Fact | `PYDOC\substance_painter\export.html` → "Full json_config dict possibilities" |

### 6.2 Channel formats (`textureset.ChannelFormat`)

| Format | Type | Dynamic range | Bits/component | Storage |
|---|---|---|---|---|
| `sRGB8` | Color | normalized fixed point | 8 | sRGB |
| `L8` | Grayscale | normalized fixed point | 8 | linear |
| `RGB8` | Color | normalized fixed point | 8 | linear |
| `L16` | Grayscale | normalized fixed point | 16 | linear |
| `RGB16` | Color | normalized fixed point | 16 | linear |
| `L16F` | Grayscale | HDR floating point | 16 | linear |
| `RGB16F` | Color | HDR floating point | 16 | linear |
| `L32F` | Grayscale | HDR floating point | 32 | linear |
| `RGB32F` | Color | HDR floating point | 32 | linear |

**Fact** — `PYSRC\textureset.py` → `ChannelFormat` docstring. `Channel.is_color()`, `is_floating()`, `bit_depth()` derive from the format (**Fact**, `textureset\channel.html`). Default channel set and default formats of a new project are not defined in the Python API (they come with the project template / shader): **not confirmed**; validate by creating a project from each `.spt` in `PAINTER\resources\starter_assets\templates\` and calling `Stack.all_channels()`.

### 6.3 Resolution

| Rule | Label | Source |
|---|---|---|
| Texture Set and UV-tile resolutions must be powers of 2 "within the range of accepted resolutions"; UV-tile resolutions must be square. The exact accepted range is not stated. | Fact (rule); range not confirmed | `PYSRC\textureset.py` → `Resolution` docstring; `textureset\uvtile.html` (`set_resolution` raises) |
| `TextureSet.get/set_resolution`, `set_resolutions(list, res)`, per-tile overrides `get/set/reset_uvtiles_resolution`, `UVTile.get/set/reset_resolution`. | Fact | `textureset\textureset.html`, `uvtile.html` |

## 7. Sources — how layer content is set

A *source* is what produces a texture inside a fill layer/effect or a procedural input: uniform color, bitmap, vector file, font/text, substance (`.sbsar`) or reference to an anchor point (**Fact**, `PYDOC\substance_painter\source\index.html`). Sources cannot be constructed directly; they are created by setter calls (**Fact**, same page).

### 7.1 Source modes on fills

| `source_mode` | Meaning | Calls | Label | Source |
|---|---|---|---|---|
| `SourceMode.Split` | one source per channel; a new fill layer starts in Split mode | `set_source(channel, src)`, `get_source(channel)`, `reset_source(channel)` | Fact | `source\index.html` (`SourceMode`); `layereffect\fill.html` (example: "The Fill layer is created with the SourceMode 'Split'") |
| `SourceMode.Material` | one source writes several channels; set automatically by `set_material_source` | `set_material_source(ResourceID or AnchorPointEffectNode)`, `get_material_source()`, `reset_material_source()` | Fact | same ("SourceMode is automatically updated to 'Material'") |
| `None` | mono-channel context (mask stack) | `set_source(None, src)` | Fact | `layereffect\fill.html` |
| Active channels | `active_channels` (set of `ChannelType`) — channels not listed are disabled | property on fills, generators, filters | Fact | `layereffect\fill.html`, `generator.html` |
| Presets | sets up the fill from a resource preset (`.sppr` files ship under `starter_assets\presets`) | `set_sources_from_preset(preset: ResourceID)` | Fact (API); file link Hypothesis | `layereffect\fill.html`; directory listing `PAINTER\resources\starter_assets\presets` (216 `.sppr` + 57 `.Sppr` files counted) |

### 7.2 Setter argument → source class

`set_source(channel, value)` produces a source class that depends on the value type (**Fact**, the public pages cited in the table; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\source.py.]):

| Value passed | Resulting source class | Notes | Source |
|---|---|---|---|
| `colormanagement.Color` | `SourceUniformColor` | `get_color`/`set_color`; a `Color` without color space is interpreted as sRGB on color-managed channels and Raw otherwise | `source\uniformcolor.html`; `PYDOC\substance_painter\colormanagement.html` |
| `resource.ResourceID` of an image | `SourceBitmap` | `resource_id`; `get/set/reset_color_space`; `list_available_color_spaces()` | `source\bitmap.html` |
| `ResourceID` of a vector file (`.ai`, `.svg`) | `SourceVectorial` | `SourceVectorialParams(artboard_id, scope, resolution, crop_area_mode, crop_area_value, fit_to_square)` | `source\vectorial.html` |
| `ResourceID` of a font | `SourceFont` | `SourceFontParams(text, auto_size, size, horizontal/vertical_alignment, color, background_color, background_opacity, line_spacing, character_spacing, offset, resolution)` | `source\font.html` |
| `ResourceID` of a substance (`.sbsar`) | `SourceSubstance` | parameters, presets, image inputs, outputs, resolution — §7.3 | `source\substance.html` |
| `AnchorPointEffectNode` | `SourceReference` | `anchor`, `channel_mapping` (multi-channel) or `referenced_channel` (single), `alpha_matte` (`KeepAlpha`, `ExtractAlpha`, `DefaultBackgroundColor`), `get/set_levels(LevelsParams)` | `source\reference.html` |

Cycles through anchor points are rejected with `ValueError` (**Fact**, changelog 0.3.1, `PYDOC\index.html`).

### 7.3 Substance (`.sbsar`) sources

| Capability | API | Rule | Label | Source |
|---|---|---|---|---|
| Read parameters | `get_parameters() -> Dict[str, PropertyValue]` | keys are the graph parameter identifiers | Fact | `source\substance.html` |
| Write parameters | `set_parameters(dict)` | batch; booleans must be passed as `int` (`True` raises "expected value of type <int32>") | Fact | same (Warning box) |
| Parameter metadata | `get_properties() -> Dict[str, Property]`; `Property.widget_type()`, `enum_values()`, `enum_value(label)`, `properties()`, `label()` | `properties()` returns a JSON object of the meta properties (e.g. ranges) | Fact | `PYDOC\substance_painter\properties.html` |
| Presets | `get_preset_list()`, `apply_preset(name)` | applying an unknown name does nothing | Fact | `source\substance.html` |
| Image inputs | `image_inputs` (ids); `get/set/reset/remove_source(identifier, …)` | inputs are themselves sources (bitmap, color, anchor) | Fact | same |
| Outputs | `image_outputs`; `output_mapping[ChannelType] = output_id`; `active_output`; `mask_output` | `output_mapping` and `mask_output` in multi-output (Material) context; `active_output` in single-output context | Fact | same |
| Resolution | `resolution: ResolutionOverride(mode, value, log2_offset)`; `ResolutionMode`: `Auto` (parent context, e.g. Texture Set resolution), `Asset`, `Custom`, `TextureSet`, `UVTile` (+ deprecated `Document`, `Manual`) | `value` power of 2 in [128, 4096]; `log2_offset` only in `Auto`; raises on a source used by a Filter effect. These bounds apply to substance source resolution overrides only, not to Texture Set, bake or export sizes. the relation between `Asset`/`Custom` and the deprecated `Document`/`Manual` is to be checked at run time ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\source.py.]) | Fact | `source\index.html` (`ResolutionOverride`, `ResolutionMode`); `source\substance.html` (`resolution`) |

### 7.4 Color management

| Item | Values | Label | Source |
|---|---|---|---|
| `GenericColorSpace` | `sRGB`, `Working`, `Raw` | Fact | `PYSRC\colormanagement.py` |
| `LegacyColorSpace` | `Linear`, `sRGB` | Fact | same |
| `DataColorSpace` | `Data`, `DataSigned` | Fact | same |
| `NormalColorSpace` | `NormalXYZRight` (OpenGL), `NormalXYZLeft` (DirectX) | Fact (names and OpenGL/Direct3D meaning) | same; `PYDOC\substance_painter\colormanagement.html` ("Normal map in OpenGL format" / "Normal map in Direct3D format"); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\test_project_create.py.] |
| OCIO / ACE | plain color-space strings of the active configuration are accepted; project mode chosen at creation from the `OCIO` or `PAINTER_ACE_CONFIG` environment variables (OCIO wins), else Legacy | Fact | `PYDOC\substance_painter\colormanagement.html` ("ColorSpace Enums"); `project.html` (`create`) |

## 8. Fill projections and symmetry

| `ProjectionMode` | Parameters dataclass | Fields | Label | Source |
|---|---|---|---|---|
| `Fill` | none (`get_projection_parameters()` returns `None`) | — ("match per UV Tile") | Fact | `layereffect\fill.html` |
| `UV` | `UVProjectionParams` | `filtering_mode`, `uv_wrapping_mode`, `uv_transformation` | Fact | same |
| `Triplanar` | `TriplanarProjectionParams` | `filtering_mode`, `shape_crop_mode`, `hardness`, `uv_transformation`, `projection_3d` | Fact | same |
| `Planar` | `PlanarProjectionParams` | `filtering_mode`, `uv_wrapping_mode`, `shape_crop_mode`, `depth_culling`, `backface_culling`, `backface_culling_angle` (45–135), `uv_transformation`, `projection_3d` | Fact | same |
| `Spherical` | `SphericalProjectionParams` | `filtering_mode`, `uv_wrapping_mode`, `shape_crop_mode`, `uv_transformation` (only `ScaleMode.Factors`), `projection_3d` | Fact | same |
| `Cylindrical` | `CylindricalProjectionParams` | `filtering_mode`, `uv_wrapping_mode`, `shape_crop_mode`, `angle`, `backface_culling`, `uv_transformation`, `projection_3d` | Fact | same |
| `Warp` | `WarpProjectionParams` | `filtering_mode`, `uv_wrapping_mode`, `shape_crop_mode`, `projection_depth`, `depth_culling`, `uv_transformation`, `projection_3d` (warp grid points are not exposed) | Fact (fields); grid absence Fact (no grid field) | same |
| `UVSetToUVSet` | `UVSetToUVSetProjectionParams` | `source_uv_set` (0 = no effect), `filtering_mode`, `uv_wrapping_mode`, `uv_transformation` | Fact | same |

Sub-structures (**Fact**, same page): `UVTransformationParams(scale_mode, scale, rotation, offset)` — `ScaleMode`: `Factors`, `MaterialPhysicalSize` (scale forced from the material's physical size), `CustomPhysicalSize` (scale in centimeters); offset unavailable for Triplanar. `Projection3DParams(offset, rotation, scale)`. `ProjectionCullingParams(enabled, hardness 0–1)`. Enums: `FilteringMode` (`BilinearHQ`, `BilinearSharp`, `Nearest`), `UVWrapMode` (`RepeatNone`, `RepeatHorizontally`, `RepeatVertically`, `Repeat`), `ShapeCropMode` (`CroppedToShape`, `ExtendsOutsideShape`).

Symmetry (**Fact**, same page): only for 3D projection modes (`is_3d_projection_mode()`); `MirrorSymmetryParams(axis, flip_u, flip_v, axis_position)`, `RadialSymmetryParams(+ count 2–16, angle_span −360..360)`; `axis_position` clamped to [−10, 10] per axis; `set_symmetry_parameters` does not enable symmetry — `set_symmetry_enabled(True)` does.

## 9. Effect parameters

| Effect | Parameters | Label | Source |
|---|---|---|---|
| Levels | `affected_channel: ChannelType`; `LevelsParamsMono(input_min, input_max, gamma, output_min, output_max, clamp)` for grayscale channels, `LevelsParamsRGB` (same fields as RGB tuples) for color channels | Fact | `layereffect\levels.html` |
| Compare Mask | `CompareMaskEffectParams(channel, left_operand, right_operand, operation, constant, tolerance, hardness)`; operands `LayersBelow`, `ThisLayer`, `ThisMask`, `Constant`; operations `LesserThan`, `WithinTolerance`, `GreaterThan`; values in [0, 1] | Fact | `layereffect\comparemask.html` |
| Color Selection | `ColorSelectionEffectParams(id_mask, output_value, hardness, tolerance, background_color, colors: List[Color])`; `id_mask` is a `Usage.TEXTURE` resource of the project ("Typically the ID Mask baked map"); background `Transparent`, `Black`, `White`, `Gray` | Fact | `layereffect\colorselection.html` |
| Generator / Filter | the substance's own parameters through `get_source()` (`SourceSubstance`) | Fact | `layereffect\generator.html`, `filter.html` |
| Anchor Point | name only | Fact | `layereffect\anchorpoint.html` |

## 10. Geometry masks

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Types | `GeometryMaskType.Mesh` (mesh names) or `UVTile` (only when the Texture Set uses UV tiles) | Fact | `navigation.html` |
| Unified API (0.3.7) | `LayerNode.get_geometry_mask()` / `set_geometry_mask(GeometryMaskMeshParams(inclusion_list, meshes) or GeometryMaskUVTilesParams(inclusion_list, uv_tiles))`; `inclusion_list=True` includes listed elements, `False` excludes them | Fact | `navigation.html`; changelog 0.3.7 |
| Element lists | `TextureSet.all_mesh_names()`, `UVTile.all_mesh_names()`, `TextureSet.all_uv_tiles()` | Fact | `textureset\textureset.html`, `uvtile.html` |
| Deprecated setters | `set_geometry_mask_type`, `set_geometry_mask_enabled_meshes`, `set_geometry_mask_enabled_uv_tiles` (deprecated 0.3.7) | Fact | `navigation.html` |
| Scope | Geometry masks are on layers (`LayerNode`), not on effects. | Fact (methods are defined on `LayerNode` only) | `PYSRC\layerstack.py` |

## 11. Smart materials and smart masks

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Definition | Smart material = preset of layers that "adapt to the 3D model"; smart mask = preset of a mask effect stack. | Fact | `layereffect\smartmaterial.html`, `smartmask.html` |
| Apply | `insert_smart_material(pos, res)` → `GroupLayerNode` (resource needs `Usage.SMART_MATERIAL`); `insert_smart_mask(pos, res)` → list of effects (needs `Usage.SMART_MASK`, mask stack only) | Fact | same |
| Create into shelf | `create_smart_material(group, name)`, `create_smart_mask(layer, name)` → `Resource` | Fact | same |
| Export to disk | `export_as_smart_material(group, name, path)`, `export_as_smart_mask(layer, name, path)` — file written to `path`, not added to a shelf; overwrites | Fact | same (0.3.6) |
| File format | `.spsm`/`.spmsk`/`.spt`/`.spp` start with the HDF5 signature `89 48 44 46 0D 0A 1A 0A`. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\starter_assets\smart-materials\Organic\Wax Candle.spsm.] | Fact (signature bytes) | `xxd` of `PAINTER\resources\starter_assets\smart-materials\Effect\Dirt.spsm`, `smart-masks\*.spmsk`, `templates\Unreal Engine.spt`; strings of `smart-materials\Organic\Wax Candle.spsm` |
| Shipped content | 121 smart materials in 10 folders (Effect 3, Fabric 19, Leather 14, Marble - granite 3, Metal 36, Organic 9, Plastic - rubber 26, Stone 2, Translucent 2, Wood 7), sizes 0.7–37.6 MB (median ≈5.5 MB); 66 smart masks | Fact (counted this session) | `PAINTER\resources\starter_assets\smart-materials\`, `smart-masks\` |
| Adaptation to the mesh | Smart materials rely on generators that read the Texture Set's baked mesh maps (see `03-baking.md` §6). | Fact (generator definition); per-material dependency list not confirmed | `layereffect\generator.html` |

## 12. Resources

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Identity | `ResourceID(context, name, version=None)`; URL form `resource://context/name?version=<hash>.<ext>` (e.g. `...?version=0123…567.image`); `from_url` rejects other schemes; an ID does not guarantee existence | Fact | `PYDOC\substance_painter\resource.html` (`ResourceID`, `from_url`) |
| Locations | `ResourceLocation`: `SESSION` (lost on restart), `PROJECT` ("embedded in the spp file"), `SHELF`; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\resource.py.] | Fact | `PYDOC\substance_painter\resource.html` (`ResourceLocation`) |
| Contexts observed | `starter_assets` (application shelf, per Adobe examples), project contexts; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] | Fact | `resource.html` examples |
| `Type` | `ABR_PACKAGE, BRUSH, EXPORT, FONT, IMAGE, PRESET, RESOURCE, SCRIPT, SHADER, SMART_MASK, SMART_MATERIAL, SUBSTANCE, SUBSTANCE_PACKAGE, VECTORIAL` | Fact | `resource.html` |
| `Usage` | `ALPHA, BASE_MATERIAL, BRUSH, COLOR_LUT, EMITTER, ENVIRONMENT, EXPORT, FILTER, FONT, GENERATOR, PARTICLE, PROCEDURAL, RECEIVER, SHADER, SMART_MASK, SMART_MATERIAL, TEXTURE ("A UV space map like bakes"), TOOL` | Fact | `resource.html` |
| Metadata | `Resource.gui_name`, `category`, `tags`, `usages`, `type`, `internal_properties()` (incl. substance preset details), `children()`/`parent()`, custom preview | Fact | `resource.html` |
| Search | `search(query)`; query examples `"s:starterassets u:substance n:Paper\ Grainy="`, `"u:smartmaterial"`, `"u:generator"`, `"u:filter"`, `"u:procedural"`, `"u:smartmask"`, `"u:basematerial"`; `StandardQuery` (named in `resource.html`; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\resource.py.]). Full grammar is referenced as "text query documentation" (not shipped) | Fact (examples); full grammar not confirmed | `layerstack\edition.html` example; `PYSRC\resource.py` (`StandardQuery`) |
| Import | `import_project_resource(path, usage, name, group)` (embedded in the `.spp`), `import_session_resource(...)`, `Shelf.import_resource(...)` (not for read-only shelves; the shipped Substance shelf is read-only) | Fact | `resource.html` → "Importing resources" |
| Shelves | `Shelves.all/exists/add/remove/refresh_all/user_shelf/application_shelf`; `Shelf.name/path/resources(query)/can_import_resources/is_crawling/refresh`; crawling emits `ShelfCrawlingStarted/Ended` | Fact | `resource.html` → "Resource crawling" |
| Project resources | `list_project_resources()`, `list_project_outdated_resources()`, `replace_project_resources({old: new}, allow_parameters_mismatch=False)` (atomic; same type required; fails on renamed/removed parameters unless allowed) | Fact | `resource.html` |
| Reload | Imported resources are copies; `reload_modified_resources_async(filter)` re-imports originals (filters: All, Project, ResourcesList, ResourcesUsedByProject, Session, ShelvesList); does not update document usages (use `replace_project_resources`) | Fact | `resource.html` → "Resource reloading" |
| Shelf configuration file | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\shelf.ini` holds UI state (`[General] version=1, icon-mode, panels-visibility, filter-by-path-filtered, favorites`, `[filters]`, `[tabs]`); shelf folder registrations are not in this file on this machine | Fact (file content) | `C:\Users\Bolado\Documents\Adobe\Adobe Substance 3D Painter\shelf.ini` |
| Starter assets (application shelf) | under `PAINTER\resources\starter_assets\`: alphas (423 `.sbsar`, 5 `.png`, 2 `.svg`), colorluts (16 `.exr`), effects (62 `.sbsar`), emitters (4 `.pkfx`), environments (32 `.exr`), export-presets (34 `.spexp`), fonts (27 `.ttf`, 3 `.otf`), generators (21 `.sbsar`), materials (107 `.sbsar`), postfx (25 `.png`), presets (216 `.sppr` + 57 `.Sppr`, 1 `.abr`, 1 `.txt`, 1 file without extension), procedurals (276 `.sbsar`), receivers (16 `.pkfx`), shaders (17 `.glsl` plus 1 `.js`, 4 `.qml`, 1 `.txt` in sub-folders), smart-masks (66 `.spmsk`), smart-materials (121 `.spsm`), templates (26 `.spt`), textures (81 `.png`, 66 `.sbsar`, 2 `.tga`) | Fact (counted this session) | directory listing |
| User shelf | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\assets\` with the same category folders, essentially empty on this machine | Fact | directory listing |

## 13. UV tiles (UDIM)

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Workflows | `ProjectWorkflow.Default` (no UDIM), `TextureSetPerUVTile` (legacy, one Texture Set per tile, no painting across tiles), `UVTile` (one Texture Set per material with several tiles sharing one stack) | Fact | `project.html` (`ProjectWorkflow`) |
| Tile identity | `UVTile(u, v)` with integer coordinates; Adobe's example comments map `uv_tile(0, 0)` → UDIM 1001 and `uv_tile(1, 0)` → 1002 | Fact | `layerstack\navigation.html` (geometry-mask example) |
| Tile metadata | `UVTile.name` (unique within the Texture Set), `description` | Fact | `textureset\uvtile.html` |
| Per-tile resolution | square power of 2; overrides via `TextureSet.set_uvtiles_resolution({tile: res})`, reset via `reset_uvtiles_resolution` | Fact | `textureset\textureset.html`, `uvtile.html` |
| Baking per tile | `BakingParameters.is/set_uv_tile_enabled`, `get/set_enabled_uv_tiles` | Fact | `baking.html` |
| Export per tile | `exportList[].filter.uvTiles` and `exportParameters[].filter.uvTiles` take `[[u, v], …]`; file names use `$udim` / `$uvTileName` | Fact | `export.html` → JSON configuration |
| Geometry mask per tile | `GeometryMaskUVTilesParams` | Fact | `navigation.html` |

## 14. Internal serialization names (cross-reference)

The `.spp` container stores the layer stack in Painter's own serialization. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\samples\MeetMat.spp; PAINTER\resources\samples\FrenchRestaurantTable.spp.] See `05-project-and-spp.md` §6.
