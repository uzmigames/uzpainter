# 01 — Substance 3D Painter Python API inventory (as of 2026-10-10)

Module-by-module inventory of every public symbol of the Python API shipped with the Adobe Substance 3D Painter install on this machine. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`. Paths below are relative to `PAINTER` unless they start with a drive letter.
- Labels: **Fact** = stated in, or computed this session from, the cited source; **Hypothesis** = inferred, not confirmed; **Recommendation** = ours. "Not confirmed" marks gaps.
- Method used to build the tables (**Fact**): every `.py` file of the shipped package `resources\python\modules\substance_painter\` (and `resources\python\modules\substance_painter_plugins.py`) was parsed with Python's `ast` module (no import, no execution). Every public (non-underscore) module-level function, class, dataclass field, method, property and native enum was extracted; signatures are the source annotations verbatim. Enum members of native enums come from the shipped docstrings and match the HTML member lists; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\_utility.py.] The result was cross-checked against every symbol anchor in the shipped HTML docs (`resources\python-doc\**\*.html`): all documented symbols are present in the source. Differences: the HTML lists inherited members under the concrete classes (mixin members under `FillLayerNode`/`FillEffectNode`, `uid()` under nodes and sources, enum members of `ReloadMeshStatus`, fields of `ResourceID`); the source additionally contains symbols without their own HTML entry — the mixin classes (`FillParamsEditorMixin`, `ActiveChannelsMixin`, `SourceEditorMixin`), the iterator classes of `OutputMapping`/`ChannelMapping`, type aliases (`ColorColorSpace`, `ResourceColorSpace`, `GeometryMaskParams`, `AutoUnwrapUVTilesSettings`, `PropertyValue`, `ReloadResourcesFilter`, `Source`), the deprecated `usd_settings` properties and the `logging` severity constants (described in prose in the HTML).
- "Purpose" is a one-line description in UzmiGames' own words (sanitisation of 2026-10-19, `phase5.5_clean-history` item 2.1; it replaced the first docstring sentence that earlier revisions carried); no cell reproduces the documentation text, which `python -m tools.sources.doc_overlap` checks against the local python-doc and javascript-doc pages (decision 304). Module, symbol, signature, parameter and enum-member names are kept as documented. Deprecations are taken from the docstrings and from the API changelog in `resources\python-doc\index.html`.
- Corrections after the technical review (`docs\analysis\reviews\substance-parity-astra-review.md`; responses in `08-review-response.md`) (**Fact**, source lines cited in the rows): the extraction read only fields declared directly on each class, so three public fields inherited from private frozen dataclass bases (`UVTile.u`, `UVTile.v`, `TextureSet.material_id`) and the two inherited constructors were missing — now added to the `textureset` table; a private class attribute of `CylindricalProjectionParams` was listed as a dataclass field — now marked as private class metadata; five non-underscore helper classes carry `:meta private:` in their docstrings (`layerstack.FillParamsEditorMixin`, `source.ActiveChannelsMixin`, `source.SourceEditorMixin`, `source.OutputMappingIterator`, `source.ChannelMappingIterator`) — now marked as implementation helpers, not supported public API (their members stay public through the concrete classes that inherit them). No documented top-level function, class or enum is missing.

## 1. Versions

| Item | Value | Label | Source |
|---|---|---|---|
| Painter application | 12.1.0 (file and product version of the executable) | Fact | `PAINTER\Adobe Substance 3D Painter.exe` version resource (read with PowerShell `VersionInfo`) |
| Python API version string | `0.3.5` (`__version_info__ = (0, 3, 5)`) | Fact | `resources\python\modules\substance_painter\_version.py`; HTML title "Substance 3D Painter Python API 0.3.5 Documentation" in `resources\python-doc\index.html` |
| API changelog top entry | `0.3.7 (Substance 3D painter 12.1.0)`; `0.3.6 (12.0.2)`; `0.3.5 (11.1.0)` | Fact | `resources\python-doc\index.html` → Changelog |
| Version-string mismatch | `_version.py` declares 0.3.5 (static source; that a running 12.1 build reports 0.3.5 is the MCP author's second-hand observation on 12.1.1, not observed here) while the 0.3.6/0.3.7 symbols (e.g. `project.AutoUnwrapUVTilesSettings`, `layerstack.GeometryMaskMeshParams`, `layerstack.export_as_smart_material`) are present in the shipped source. Feature detection must use `hasattr`, not the version string. | Fact (presence) | `substance_painter\_version.py`; `substance_painter\project.py` line 211+; `substance_painter\layerstack.py` lines 204, 2326; also observed by the MCP author: `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\README.md` → "Compatibility" ("Runtime reported 0.3.5 in the validated build") |
| Embedded Python | CPython 3.13.9 (`python313.dll`; SDK `python.exe` version 3.13.9; `NEWS.txt` top entry "Python 3.13.9 final") | Fact | `PAINTER\python313.dll`; `resources\pythonsdk\python.exe` version resource; `resources\pythonsdk\NEWS.txt` |
| Qt binding | PySide6 / shiboken6 built for CPython 3.13 (`pyside6.cp313-win_amd64.dll`); `ui` functions are typed with `PySide6.QtWidgets` | Fact | `PAINTER\pyside6.cp313-win_amd64.dll`; `resources\python\modules\substance_painter\ui.py` |
| Stale bytecode | `substance_painter\__pycache__\*.cpython-310.pyc` files exist next to the 3.13 sources | Fact (observation only) | `resources\python\modules\substance_painter\__pycache__\` |
| Native backing module | Every public module wraps a private compiled module `_substance_painter.<module>` (e.g. `_substance_painter.textureset.ChannelType`) | Fact | imports at the top of each `substance_painter\*.py` |
| Python version history | API 0.0.1 used Python 3.7.6; 0.2.5 (Painter 8.1.0) moved to 3.9.9; no later Python-version entry in the changelog | Fact | `resources\python-doc\index.html` → Changelog |

## 2. Module map

`substance_painter/__init__.py` imports: `application, async_utils, baking, colormanagement, display, event, exception, export, js, layerstack, levels, logging, project, properties, resource, source, textureset, ui` (**Fact**, `resources\python\modules\substance_painter\__init__.py`). `levels` is imported but has no standalone HTML page; its classes are documented on the Levels-effect page (**Fact**). Plugins are managed by the separate top-level module `substance_painter_plugins` (**Fact**).

| Module | Functions | Classes/dataclasses | Enums (native + Python) | Methods/properties/ctors | Other (aliases, constants) |
|---|---|---|---|---|---|
| application | 6 | 0 | 0 | 0 | 0 |
| async_utils | 0 | 1 | 0 | 2 | 0 |
| baking | 10 | 1 | 2 | 18 | 0 |
| colormanagement | 0 | 1 | 4 | 7 | 2 |
| display | 6 | 1 | 2 | 17 | 0 |
| event | 0 | 27 | 1 | 6 | 1 |
| exception | 0 | 0 | 3 (exceptions) | 0 | 0 |
| export | 8 | 4 | 2 | 2 | 0 |
| js | 1 | 0 | 0 | 0 | 0 |
| layerstack | 24 | 33 | 16 | 65 | 5 |
| levels | 0 | 2 | 0 | 0 | 1 |
| logging | 4 | 0 | 0 | 0 | 6 |
| project | 19 | 9 | 6 | 8 | 1 |
| properties | 0 | 1 | 0 | 8 | 1 |
| resource | 11 | 13 | 4 | 33 | 1 |
| source | 0 | 15 | 7 | 52 | 2 |
| textureset | 4 | 5 | 3 | 46 | 0 |
| ui | 14 | 0 | 2 | 0 | 0 |
| substance_painter_plugins | 9 | 0 | 0 | 0 | 2 |

Counts are rows of the AST extraction (property getter and setter counted separately) — **Fact**, computed this session; `textureset` includes the two inherited constructors added after review (inherited fields are not counted in these columns).

## 3. Cross-cutting facts

| # | Statement | Label | Source |
|---|---|---|---|
| 1 | There is no public Python module for shaders/shader parameters, brushes/painting strokes, particles, the history/undo stack (other than `layerstack.ScopedModification` grouping), viewport capture, Iray rendering, or "Clean" (remove unused resources). | Fact (absence in the module list and sources) | `substance_painter\__init__.py`; module sources |
| 2 | The legacy JavaScript API is reachable from Python through `js.evaluate()` and covers, among others, shader instances/parameters (`alg.shaders.parameters`, `setParameters`, `updateShaderInstance`), map export helpers (`alg.mapexport.save`, `saveChannelMap`, `saveMeshMap`, `saveConvertedMap`), `alg.project.saveAndClose`, `alg.subprocess`, `alg.fileIO`. | Fact | `resources\javascript-doc\alg.*.html` (function anchors); `resources\python-doc\substance_painter\js.html` |
| 3 | Paint strokes cannot be read or written through Python; the paint-node page says so explicitly. | Fact | `resources\python-doc\substance_painter\layerstack\layereffect\paint.html` (PaintLayerNode, PaintEffectNode) |
| 4 | Layer-stack editing requires an open project in edition state; the entry point is `layerstack.get_root_layer_nodes()`. | Fact | `resources\python-doc\substance_painter\layerstack\index.html` |
| 5 | Long operations are asynchronous and event-driven: `project.create/open` (finish with `event.ProjectEditionEntered`), `baking.bake_async` (finish with `event.BakingProcessEnded`), `project.reload_mesh` (callback), `resource.reload_modified_resources_async` (`event.ReloadResourcesEnded`), shelf crawling (`event.ShelfCrawlingEnded`). | Fact | `project.html` → Events; `baking.html`; `resource.html` → Resource crawling / Resource reloading |
| 6 | Remote scripting: the MCP bridge talks to Painter started with `--enable-remote-scripting`, which listens on `localhost:60041` and accepts `POST /run.json` with `{"python": <base64>}` or `{"js": <base64>}`. Not described in the shipped Python HTML docs. | Fact (bridge code); not confirmed in Adobe docs | `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\README.md` → "Start Painter with remote scripting"; `...\src\substance_painter_mcp\client.py` (`route = "/run.json"`) |
| 7 | Plugins: each plugin is an ordinary Python module found on `substance_painter_plugins.path` (initialised from `SUBSTANCE_PAINTER_PLUGINS_PATH`, the install dir and the user resources dir); each plugin dir has `plugins/`, `startup/`, `modules/`; plugin modules expose `start_plugin()`/`close_plugin()`. | Fact | `resources\python-doc\plugins\substance_painter_plugins.html` (`path`) |
| 8 | Adobe's shipped test suites call private `_substance_painter.*` functions that are not part of the public API. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\engine_tests\; resources\python\modules\automated_tests\.] Independently of those tests, the Assets3D pipeline uses the private viewport capture `_substance_painter.display.save_viewport`. | Fact; stability not confirmed | test directories (paths only); `E:\UzmiGames\Assets3D\Docs\Lessons\operation-actual-project-and-capture.md` |
| 9 | `layerstack.get_node_by_uid` is annotated as returning `List[...]` (public signature) but returns a single node. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\layerstack.py.] | Fact | `resources\python-doc\substance_painter\layerstack\navigation.html` (signature) |
| 10 | The shipped Adobe test suites (`resources\python\modules\automated_tests\`, `engine_tests\`) are the richest usage examples for baking, export, layer stack and project creation and are reused as sources in files 02–05. | Fact | directory listing |

## 4. Symbol tables

Each section lists every public symbol of one module. Kind values: `function`, `class`, `dataclass`, `enum` (Python `enum.Enum`), `enum (native)` (C++ enum exposed by the native module; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\_utility.py.]), `exception (native)`, `method`, `staticmethod`, `classmethod`, `constructor`, `property`, `property setter`, `type alias`, `attribute`, `note` (added rows that document inherited/dunder behaviour).

## `substance_painter.application`

Application-level version query, engine-computation toggle and application close. Source: `resources\python\modules\substance_painter\application.py`; HTML: `resources\python-doc\substance_painter\application.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `version_info` | function | `version_info() -> Tuple[int, int, int]` | Painter's version as three integers (major, minor, patch). |
| `version` | function | `version() -> str` | Painter's version, as text. |
| `engine_computations_status` | function | `engine_computations_status() -> bool` | True while the engine is allowed to compute. |
| `enable_engine_computations` | function | `enable_engine_computations(enable: bool)` | Turns engine computation on or off according to `enable`. |
| `disable_engine_computations` | function | `disable_engine_computations()` | Context manager that pauses engine computation for the duration of a `with` block. |
| `close` | function | `close()` | Quits the Painter application. |

## `substance_painter.async_utils`

Cancellation handle returned by asynchronous calls (baking). Source: `resources\python\modules\substance_painter\async_utils.py`; HTML: `resources\python-doc\substance_painter\async_utils.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `StopSource` | dataclass | fields: stop_source: _substance_painter.async_utils.StopSource | Handle through which a running asynchronous job (a bake, for instance) can be cancelled. |
| `StopSource.request_stop` | method | `request_stop() -> bool` | Asks the associated job to stop; returns a boolean. |
| `StopSource.stop_requested` | method | `stop_requested() -> bool` | True once a stop has been asked for. |

## `substance_painter.baking`

Per-Texture-Set baking configuration (dynamic `Property` bags), baker enablement, UV-tile selection, link groups, asynchronous bake launch. Source: `resources\python\modules\substance_painter\baking.py`; HTML: `resources\python-doc\substance_painter\baking.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `BakingStatus` | enum (native) | Members: `Success`, `Cancel`, `Fail` | Outcome of a bake: success, cancellation or failure. |
| `CurvatureMethod` | enum (native) | Members: `FromMesh`, `FromNormalMap` | Input of the curvature baker: the mesh geometry or a normal map. |
| `BakingParameters` | dataclass | fields: material_id: int | Bake configuration attached to one Texture Set. |
| `BakingParameters.from_texture_set` | staticmethod | `from_texture_set(texture_set: TextureSet) -> 'BakingParameters'` | Looks up the bake configuration of a Texture Set object. |
| `BakingParameters.from_texture_set_name` | staticmethod | `from_texture_set_name(texture_set_name: str) -> 'BakingParameters'` | Looks up the bake configuration of the Texture Set with this name. |
| `BakingParameters.texture_set` | method | `texture_set() -> TextureSet` | The Texture Set this configuration belongs to. |
| `BakingParameters.common` | method | `common() -> Dict[str, Property]` | Settings shared by every baker (output resolution among them), as a name-to-`Property` mapping. |
| `BakingParameters.baker` | method | `baker(baked_map: MeshMapUsage) -> Dict[str, Property]` | Settings of the baker that produces one mesh map, as a name-to-`Property` mapping. |
| `BakingParameters.set` | staticmethod | `set(property_values: Dict[Property, PropertyValue]) -> None` | Writes several property values in one call. |
| `BakingParameters.get_curvature_method` | method | `get_curvature_method() -> CurvatureMethod` | Reads which curvature method the bake uses. |
| `BakingParameters.set_curvature_method` | method | `set_curvature_method(method: CurvatureMethod)` | Chooses the curvature method of the bake. |
| `BakingParameters.is_baker_enabled` | method | `is_baker_enabled(usage: MeshMapUsage) -> bool` | True when the mesh map of this usage is part of the bake. |
| `BakingParameters.set_baker_enabled` | method | `set_baker_enabled(usage: MeshMapUsage, enable: bool) -> None` | Adds one mesh-map usage to the bake or drops it. |
| `BakingParameters.get_enabled_bakers` | method | `get_enabled_bakers() -> List[MeshMapUsage]` | Every mesh-map usage currently selected for baking. |
| `BakingParameters.set_enabled_bakers` | method | `set_enabled_bakers(enabled_usages: List[MeshMapUsage]) -> None` | Replaces the selection of mesh-map usages to bake. |
| `BakingParameters.is_textureset_enabled` | method | `is_textureset_enabled() -> bool` | True when this Texture Set takes part in the bake. |
| `BakingParameters.set_textureset_enabled` | method | `set_textureset_enabled(enable: bool) -> None` | Includes this Texture Set in the bake or leaves it out. |
| `BakingParameters.is_uv_tile_enabled` | method | `is_uv_tile_enabled(uv_tile: UVTile) -> bool` | True when one UV Tile takes part in the bake. |
| `BakingParameters.set_uv_tile_enabled` | method | `set_uv_tile_enabled(uv_tile: UVTile, enable: bool) -> None` | Includes one UV Tile in the bake or leaves it out. |
| `BakingParameters.get_enabled_uv_tiles` | method | `get_enabled_uv_tiles() -> List[UVTile]` | Every UV Tile currently selected for baking. |
| `BakingParameters.set_enabled_uv_tiles` | method | `set_enabled_uv_tiles(enabled_uv_tiles: List[UVTile]) -> None` | Replaces the selection of UV Tiles to bake. |
| `set_linked_group` | function | `set_linked_group(group: List[TextureSet], reference: TextureSet, usage: MeshMapUsage) -> None` | Links several Texture Sets so that, for one mesh-map usage, they follow the reference set's settings. |
| `set_linked_group_common_parameters` | function | `set_linked_group_common_parameters(group: List[TextureSet], reference: TextureSet) -> None` | Links several Texture Sets so that they follow the reference set's shared (all-baker) settings. |
| `unlink_all` | function | `unlink_all(usage: MeshMapUsage) -> None` | Removes every link between Texture Sets for one mesh-map usage. |
| `unlink_all_common_parameters` | function | `unlink_all_common_parameters() -> None` | Removes every link between Texture Sets on the shared settings. |
| `get_link_group` | function | `get_link_group(usage: MeshMapUsage) -> List[TextureSet]` | Texture Sets linked together for one mesh-map usage. |
| `get_link_group_common_parameters` | function | `get_link_group_common_parameters() -> List[TextureSet]` | Texture Sets linked together on the shared settings. |
| `get_linked_texture_sets` | function | `get_linked_texture_sets(texture_set: TextureSet, usage: MeshMapUsage) -> List[TextureSet]` | Texture Sets linked to a given one for one mesh-map usage. |
| `get_linked_texture_sets_common_parameters` | function | `get_linked_texture_sets_common_parameters(texture_set: TextureSet) -> List[TextureSet]` | Texture Sets linked to a given one on the shared settings. |
| `bake_async` | function | `bake_async(texture_set: TextureSet) -> StopSource` | Starts baking one Texture Set with its current configuration; returns a cancellation handle. |
| `bake_selected_textures_async` | function | `bake_selected_textures_async() -> StopSource` | Starts a bake of the current selection with the current configuration; returns a cancellation handle. |

## `substance_painter.colormanagement`

Color value type with explicit color space; color-space enums used by sources. Source: `resources\python\modules\substance_painter\colormanagement.py`; HTML: `resources\python-doc\substance_painter\colormanagement.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `GenericColorSpace` | enum | Members: `sRGB`, `Working`, `Raw` | Colour spaces that stay valid whichever colour-management engine is active. |
| `LegacyColorSpace` | enum | Members: `Linear`, `sRGB` | Colour spaces of the legacy colour management. |
| `DataColorSpace` | enum | Members: `Data`, `DataSigned` | Colour spaces for non-colour data, unsigned or signed. |
| `NormalColorSpace` | enum | Members: `NormalXYZRight`, `NormalXYZLeft` | Colour spaces for normal maps, by handedness (right or left). |
| `ColorColorSpace` | type alias | = Union[GenericColorSpace, str] |  |
| `ResourceColorSpace` | type alias | = Union[GenericColorSpace, LegacyColorSpace, DataColorSpace, NormalColorSpace, str] |  |
| `Color` | class | fields: value_raw: Tuple[float, float, float]; color_space: ColorColorSpace | A colour value tagged with the colour space it is expressed in. |
| `Color.__init__` | constructor | `__init__(r: float, g: float, b: float, color_space: ColorColorSpace = None)` | Builds a colour from three components and an optional colour space. |
| `Color.convert` | method | `convert(color_space: ColorColorSpace) -> Tuple[float, float, float]` | Returns the three components re-expressed in another colour space. |
| `Color.value` | property | `value() -> Tuple[float, float, float]` | The stored components, in the colour's own space. |
| `Color.sRGB` | property | `sRGB() -> Tuple[float, float, float]` | The components expressed in sRGB. |
| `Color.sRGB` | property setter | `sRGB(value: Tuple[float, float, float]) -> None` | Setter of the property above. |
| `Color.working` | property | `working() -> Tuple[float, float, float]` | The components expressed in the working colour space. |
| `Color.working` | property setter | `working(value: Tuple[float, float, float]) -> None` | Setter of the property above. |

## `substance_painter.display`

Viewport/display settings of the project: environment map, color LUT, tone mapping, camera. Source: `resources\python\modules\substance_painter\display.py`; HTML: `resources\python-doc\substance_painter\display.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ToneMappingFunction` | enum (native) | Members: `Linear`, `ACES` | Tone-mapping operator applied to the display. |
| `get_environment_resource` | function | `get_environment_resource() -> typing.Optional[substance_painter.resource.ResourceID]` | Resource used as the active project's environment map, if any. |
| `set_environment_resource` | function | `set_environment_resource(new_env_map: substance_painter.resource.ResourceID) -> None` | Replaces the active project's environment-map resource. |
| `get_color_lut_resource` | function | `get_color_lut_resource() -> typing.Optional[substance_painter.resource.ResourceID]` | Resource used as the active project's colour-profile LUT, if any. |
| `set_color_lut_resource` | function | `set_color_lut_resource(new_color_lut: substance_painter.resource.ResourceID) -> None` | Replaces the active project's colour-profile LUT resource. |
| `get_tone_mapping` | function | `get_tone_mapping() -> ToneMappingFunction` | Tone-mapping operator the open project is displayed with. |
| `set_tone_mapping` | function | `set_tone_mapping(new_tone_mapping: ToneMappingFunction) -> None` | Chooses the tone-mapping operator of the open project's display. |
| `CameraProjectionType` | enum (native) | Members: `Perspective`, `Orthographic` | Perspective or orthographic camera. |
| `Camera` | dataclass | fields: _camera_id: int | Handle to an existing camera, through which its properties are read and written. |
| `Camera.get_default_camera` | staticmethod | `get_default_camera() -> Camera` | Returns the project's default camera. |
| `Camera.position` | property | `position() -> List[float]` | Camera location as x, y, z. |
| `Camera.position` | property setter | `position(position: List[float]) -> None` | Setter of the property above. |
| `Camera.rotation` | property | `rotation() -> List[float]` | Camera orientation as x, y, z Euler angles, in degrees. |
| `Camera.rotation` | property setter | `rotation(rotation: List[float]) -> None` | Setter of the property above. |
| `Camera.field_of_view` | property | `field_of_view() -> float` | Camera angle of view, in degrees. |
| `Camera.field_of_view` | property setter | `field_of_view(fov: float) -> None` | Setter of the property above. |
| `Camera.focal_length` | property | `focal_length() -> float` | Camera focal length, in millimetres. |
| `Camera.focal_length` | property setter | `focal_length(focal_length: float) -> None` | Setter of the property above. |
| `Camera.focus_distance` | property | `focus_distance() -> float` | Distance at which the camera is in focus. |
| `Camera.focus_distance` | property setter | `focus_distance(focus_distance: float) -> None` | Setter of the property above. |
| `Camera.aperture` | property | `aperture() -> float` | Camera aperture value. |
| `Camera.aperture` | property setter | `aperture(aperture: float) -> None` | Setter of the property above. |
| `Camera.orthographic_height` | property | `orthographic_height() -> float` | Height of the view volume when the camera is orthographic. |
| `Camera.orthographic_height` | property setter | `orthographic_height(orthographic_height: float) -> None` | Setter of the property above. |
| `Camera.projection_type` | property | `projection_type() -> CameraProjectionType` | Whether the camera projects in perspective or orthographically. |
| `Camera.projection_type` | property setter | `projection_type(projection_type: CameraProjectionType) -> None` | Setter of the property above. |

## `substance_painter.event`

Event classes and the global dispatcher used to observe project, export, baking, shelf, texture and camera events. Source: `resources\python\modules\substance_painter\event.py`; HTML: `resources\python-doc\substance_painter\event.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `Event` | dataclass | — | Common base of every event class. |
| `ProjectOpened` | dataclass | bases (Event) | Sent after an existing project file has been opened. |
| `ProjectCreated` | dataclass | bases (Event) | Sent once a new project exists. |
| `ProjectAboutToClose` | dataclass | bases (Event) | Sent right before the open project closes. |
| `ProjectClosed` | dataclass | bases (Event) | Sent when the open project closes (the documentation describes it with the same words as `ProjectAboutToClose`). |
| `ProjectAboutToSave` | dataclass | bases (Event) — fields: file_path: str | Sent right before the open project is written; carries the target `file_path`. |
| `ProjectSaved` | dataclass | bases (Event) | Sent after the open project has been written. |
| `ExportTexturesAboutToStart` | dataclass | bases (Event) — fields: textures: Dict[Tuple[str, str], List[str]] | Sent right before a texture export begins; lists the files to be written. |
| `ExportTexturesEnded` | dataclass | bases (Event) — fields: status: ExportStatus; message: str; textures: Dict[Tuple[str, str], List[str]] | Sent after a texture export completes, with its status, message and written files. |
| `ShelfCrawlingStarted` | dataclass | bases (Event) — fields: shelf_name: str | Sent when a shelf begins scanning its folders for new resources. |
| `ShelfCrawlingEnded` | dataclass | bases (Event) — fields: shelf_name: str | Sent once a shelf's resource scan is over and its thumbnails are loaded. |
| `ProjectEditionEntered` | dataclass | bases (Event) | Sent once the project has finished loading and can be edited. |
| `ProjectEditionLeft` | dataclass | bases (Event) | Sent when the project stops being editable. |
| `BusyStatusChanged` | dataclass | bases (Event) — fields: busy: bool | Sent when Painter enters or leaves its busy state. |
| `BakingProcessAboutToStart` | dataclass | bases (Event) — fields: stop_source: StopSource | Sent right before a bake begins; carries its cancellation handle. |
| `BakingProcessProgress` | dataclass | bases (Event) — fields: progress: float | Sent as a bake advances; carries the progress value. |
| `BakingProcessEnded` | dataclass | bases (Event) — fields: status: BakingStatus | Sent after a bake finishes, with its status. |
| `LayerStacksModelDataChanged` | dataclass | bases (Event) | Sent whenever layer-stack state changes. |
| `EngineComputationsStatusChanged` | dataclass | bases (Event) — fields: engine_computations_enabled: bool | Sent when engine computation is switched on or off. |
| `GraphicalUserInterfaceStarted` | dataclass | bases (Event) | Sent once the user interface has finished starting up. |
| `TextureStateEventAction` | enum (native) | Members: `ADD`, `UPDATE`, `REMOVE` | What happened to a texture: added, updated or removed. |
| `TextureStateEvent` | dataclass | bases (Event) — fields: action: TextureStateEventAction; stack_id: int; tile_indices: Tuple[int, int]; channel_type: ChannelType; cache_key: int | Sent when a texture of the document appears, changes or disappears. |
| `TextureStateEvent.cache_key_invalidation_throttling_period` | staticmethod | `cache_key_invalidation_throttling_period() -> datetime.timedelta` | Shortest interval between two update events for one texture. |
| `TextureStateEvent.set_cache_key_invalidation_throttling_period` | staticmethod | `set_cache_key_invalidation_throttling_period(period: datetime.timedelta) -> None` | Changes the shortest interval between two update events for one texture. |
| `CameraPropertiesChanged` | dataclass | bases (Event) — fields: camera_id: int | Sent when a camera's properties change. |
| `ReloadResourcesStarted` | dataclass | bases (Event) — fields: filter: ReloadResourcesFilter | Sent when a resource reload begins. |
| `ReloadedResourceResult` | dataclass | fields: old_resource_id: ResourceID; new_resource_id: ResourceID | Outcome for one resource that reloaded successfully (old and new identifiers). |
| `ReloadedResourceError` | dataclass | fields: resource_id: ResourceID; error_msg: str | Outcome for one resource that failed to reload (identifier and error text). |
| `ReloadResourcesEnded` | dataclass | bases (Event) — fields: filter: ReloadResourcesFilter; reloaded_resources: List[ReloadedResourceResult]; resource_errors: List[ReloadedResourceError] | Sent when a resource reload completes, with per-resource results and errors. |
| `Dispatcher` | class | — | Routes events to the callbacks registered for their type. |
| `Dispatcher.__init__` | constructor | `__init__()` |  |
| `Dispatcher.connect` | method | `connect(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Registers a callback for an event type. |
| `Dispatcher.connect_strong` | method | `connect_strong(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Variant of `connect` that registers a callback for an event type. |
| `Dispatcher.disconnect` | method | `disconnect(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Unregisters a callback added earlier. |
| `DISPATCHER` | attribute | = Dispatcher() | The application's single dispatcher instance. |

## `substance_painter.exception`

Painter-specific exceptions (native objects). Source: `resources\python\modules\substance_painter\exception.py`; HTML: `resources\python-doc\substance_painter\exception.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ProjectError` | exception (native) | native object | Raised when a call does not fit the open project, or the project is in an invalid state. |
| `ServiceNotFoundError` | exception (native) | native object | Raised when a call depends on a service that is missing. |
| `ResourceNotFoundError` | exception (native) | native object | Raised when a requested Painter resource does not exist. |

## `substance_painter.export`

Texture export driven by a JSON configuration, export-preset listing, mesh export. Source: `resources\python\modules\substance_painter\export.py`; HTML: `resources\python-doc\substance_painter\export.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ExportStatus` | enum (native) | Members: `Success`, `Cancelled`, `Warning`, `Error` | Outcome of an export: success, cancelled, warning or error. |
| `list_project_textures` | function | `list_project_textures(json_config: dict) -> Dict[Tuple[str, str], List[str]]` | Lists, without writing anything, the files an export with this JSON configuration would produce. |
| `TextureExportResult` | dataclass | fields: status: ExportStatus; message: str; textures: Dict[Tuple[str, str], List[str]] | What a texture export returns: status, message and written files. |
| `export_project_textures` | function | `export_project_textures(json_config: dict) -> TextureExportResult` | Writes the document's textures as the JSON configuration describes. |
| `get_default_export_path` | function | `get_default_export_path() -> str` | Folder the application exports textures to by default. |
| `PredefinedExportPreset` | dataclass | fields: name: str; url: str | A built-in export preset (output template); a preset governs how an export behaves. |
| `PredefinedExportPreset.list_output_maps` | method | `list_output_maps(stack: substance_painter.textureset.Stack) -> list` | Output maps this preset would produce from the channels of a stack. |
| `list_predefined_export_presets` | function | `list_predefined_export_presets() -> List[PredefinedExportPreset]` | All built-in export presets (output templates). |
| `ResourceExportPreset` | dataclass | fields: resource_id: substance_painter.resource.ResourceID | An export preset (output template) stored as a resource. |
| `ResourceExportPreset.list_output_maps` | method | `list_output_maps() -> list` | Output maps defined by this preset. |
| `list_resource_export_presets` | function | `list_resource_export_presets() -> List[ResourceExportPreset]` | All export presets (output templates) available as resources. |
| `MeshExportOption` | enum (native) | Members: `BaseMesh`, `TriangulatedMesh`, `TessellationNormalsBaseMesh`, `TessellationRecomputeNormals` | Choice of mesh geometry a mesh export writes. |
| `scene_is_triangulated` | function | `scene_is_triangulated() -> bool` | True when every polygon of the scene is a triangle. |
| `scene_has_tessellation` | function | `scene_has_tessellation() -> bool` | True when displacement or tessellation is on for the scene. |
| `MeshExportResult` | dataclass | fields: status: ExportStatus; message: str | What a mesh export returns: status and message. |
| `export_mesh` | function | `export_mesh(file_path: str, option: MeshExportOption) -> MeshExportResult` | Writes the current mesh to a file. |

## `substance_painter.js`

Bridge to the legacy embedded JavaScript API (`alg.*`). Source: `resources\python\modules\substance_painter\js.py`; HTML: `resources\python-doc\substance_painter\js.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `evaluate` | function | `evaluate(js_code: str) -> str` | Runs JavaScript code in Painter and returns the result as a string. |

## `substance_painter.layerstack`

Layer stack navigation, insertion, deletion, selection, masks, blending, geometry masks, projections, symmetry, smart materials/masks. Source: `resources\python\modules\substance_painter\layerstack.py`; HTML: `resources\python-doc\substance_painter\layerstack\*.html and layerstack\layereffect\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `BlendingMode` | enum (native) | Members: `Normal`, `PassThrough`, `Disable`, `Replace`, `Multiply`, `Divide`, `InverseDivide`, `Darken`, `Lighten`, `LinearDodge`, `Subtract`, `InverseSubtract`, `Difference`, `Exclusion`, `SignedAddition`, `Overlay`, `Screen`, `LinearBurn`, `ColorBurn`, `ColorDodge`, `SoftLight`, `HardLight`, `VividLight`, `LinearLight`, `PinLight`, `Tint`, `Saturation`, `Color`, `Value`, `NormalMapCombine`, `NormalMapDetail`, `NormalMapInverseDetail` | How a layer's result combines with the layers beneath it. |
| `NodeType` | enum (native) | Members: `PaintLayer`, `PaintEffect`, `FillLayer`, `FillEffect`, `GeneratorEffect`, `FilterEffect`, `LevelsEffect`, `CompareMaskEffect`, `ColorSelectionEffect`, `GroupLayer`, `InstanceLayer`, `AnchorPointEffect` | Kind of a layer-stack node (a layer type or an effect type); the documentation has a page on each. |
| `NodeStack` | enum | Members: `Substack`, `Content`, `Mask` | Which stack of a node an insertion targets: sub-stack, content or mask. |
| `MaskBackground` | enum (native) | Members: `Black`, `White` | Initial fill of a new mask: black or white. |
| `ColorSelectionBackgroundColor` | enum (native) | Members: `Transparent`, `Black`, `White`, `Gray` | Background colour choice of the colour-selection effect. |
| `GeometryMaskType` | enum (native) | Members: `Mesh`, `UVTile` | What a geometry mask filters by: mesh or UV Tile. |
| `GeometryMaskMeshParams` | dataclass | fields: inclusion_list: bool = True; meshes: List[str] = dataclasses.field(default_factory=list) | Geometry-mask settings that select meshes by name. |
| `GeometryMaskUVTilesParams` | dataclass | fields: inclusion_list: bool = True; uv_tiles: List[UVTile] = dataclasses.field(default_factory=list) | Geometry-mask settings that select UV Tiles. |
| `GeometryMaskParams` | type alias | = Union[GeometryMaskMeshParams, GeometryMaskUVTilesParams] |  |
| `ProjectionMode` | enum (native) | Members: `Fill`, `UV`, `Triplanar`, `Planar`, `Spherical`, `Cylindrical`, `Warp`, `UVSetToUVSet` | Fill projection mode; the fill-projection documentation describes each mode. |
| `is_3d_projection_mode` | function | `is_3d_projection_mode(projection_mode: ProjectionMode) -> bool` | True for projection modes that work in 3D space. |
| `FilteringMode` | enum (native) | Members: `BilinearHQ`, `BilinearSharp`, `Nearest` | Texture sampling filter of a fill projection. |
| `UVWrapMode` | enum (native) | Members: `RepeatNone`, `RepeatHorizontally`, `RepeatVertically`, `Repeat` | Tiling of a projected texture: none, horizontal, vertical or both. |
| `ShapeCropMode` | enum (native) | Members: `CroppedToShape`, `ExtendsOutsideShape` | Whether a projection stays inside the shape or extends past it. |
| `ScaleMode` | enum (native) | Members: `Factors`, `MaterialPhysicalSize`, `CustomPhysicalSize` | How projection scale is expressed: factors, the material's physical size or a custom physical size. |
| `CompareMaskEffectOperand` | enum (native) | Members: `LayersBelow`, `ThisLayer`, `ThisMask`, `Constant` | Value a compare-mask operand reads; the compare-mask documentation describes the effect. |
| `CompareMaskEffectOperation` | enum (native) | Members: `LesserThan`, `WithinTolerance`, `GreaterThan` | Comparison applied by the compare-mask effect. |
| `SelectionType` | enum (native) | Members: `Content`, `Mask`, `GeometryMask`, `Properties` | Which layer part a selection designates (`Content`, `Mask`, `GeometryMask`, `Properties`). |
| `SymmetryAxis` | enum (native) | Members: `X`, `Y`, `Z` | Axis of a fill symmetry. |
| `SymmetryMode` | enum (native) | Members: `Mirror`, `Radial` | Kind of symmetry (mirror or radial); it takes effect only on a Fill Layer with a 3D projection. |
| `ScopedModification` | class | — | Context manager that gathers many layer-stack edits into one undo step. |
| `ScopedModification.__init__` | constructor | `__init__(name)` |  |
| `FillParamsEditorMixin` | class | — | Helper base that carries the projection and symmetry settings of a fill. Docstring marks it `:meta private:` (`layerstack.py:518–523`): implementation helper, not supported public API; its members are public through `FillLayerNode`/`FillEffectNode`. |
| `FillParamsEditorMixin.get_projection_mode` | method | `get_projection_mode() -> ProjectionMode` | Reads the fill's projection mode. |
| `FillParamsEditorMixin.set_projection_mode` | method | `set_projection_mode(projection_mode: ProjectionMode)` | Changes the fill's projection mode. |
| `FillParamsEditorMixin.get_projection_parameters` | method | `get_projection_parameters() -> ProjectionParams \| None` | Reads the parameters of the fill's current projection. |
| `FillParamsEditorMixin.set_projection_parameters` | method | `set_projection_parameters(projection_parameters: ProjectionParams)` | Writes projection parameters; the projection mode follows the parameter type. |
| `FillParamsEditorMixin.is_symmetry_enabled` | method | `is_symmetry_enabled() -> bool` | True when symmetry is on for the fill. |
| `FillParamsEditorMixin.set_symmetry_enabled` | method | `set_symmetry_enabled(enabled: bool)` | Turns the fill's symmetry on or off. |
| `FillParamsEditorMixin.get_symmetry_parameters` | method | `get_symmetry_parameters() -> SymmetryParams` | Reads the fill's symmetry parameters. |
| `FillParamsEditorMixin.set_symmetry_parameters` | method | `set_symmetry_parameters(symmetry_parameters: SymmetryParams)` | Writes symmetry parameters; the symmetry mode follows the parameter type. |
| `Node` | class | bases (ReadOnlyUid) | Base class for the properties every layer-stack node has. |
| `Node.get_type` | method | `get_type() -> NodeType` | Kind of this node. |
| `Node.get_texture_set` | method | `get_texture_set() -> TextureSet` | Texture Set that owns this node. |
| `Node.is_visible` | method | `is_visible() -> bool` | True when this node contributes to the render. |
| `Node.set_visible` | method | `set_visible(visible: bool)` | Shows or hides this node. |
| `Node.get_name` | method | `get_name() -> str` | Display name of this node. |
| `Node.set_name` | method | `set_name(name: str)` | Renames this node. |
| `Node.is_in_mask_stack` | method | `is_in_mask_stack() -> bool` | True when this node sits inside a mask stack. |
| `Node.has_blending` | method | `has_blending() -> bool` | True when this node carries blending settings (mode and opacity). |
| `Node.get_blending_mode` | method | `get_blending_mode(channel: Optional[ChannelType] = None) -> BlendingMode` | Blending mode of the node, optionally for one channel. |
| `Node.set_blending_mode` | method | `set_blending_mode(blending_mode: BlendingMode, channel: Optional[ChannelType] = None)` | Changes the node's blending mode, optionally for one channel. |
| `Node.get_opacity` | method | `get_opacity(channel: Optional[ChannelType] = None) -> float` | Opacity of the node, optionally for one channel. |
| `Node.set_opacity` | method | `set_opacity(opacity: float, channel: Optional[ChannelType] = None)` | Changes the node's opacity, optionally for one channel. |
| `Node.get_stack` | method | `get_stack() -> Stack` | Stack in which this node lives. |
| `Node.get_parent` | method | `get_parent() -> Node` | Node directly above this one in the hierarchy. |
| `Node.get_next_sibling` | method | `get_next_sibling() -> Node` | Following node at the same level. |
| `Node.get_previous_sibling` | method | `get_previous_sibling() -> Node` | Preceding node at the same level. |
| `LayerNode` | class | bases (Node) | A node of the main layer hierarchy (not an effect). |
| `LayerNode.content_effects` | method | `content_effects() -> List[EffectNode]` | Effects of the node's content, in layer-stack order. |
| `LayerNode.mask_effects` | method | `mask_effects() -> List[EffectNode]` | Effects of the node's mask, in layer-stack order. |
| `LayerNode.instances` | method | `instances() -> List[LayerNode]` | Instance layers created from this layer. |
| `LayerNode.get_geometry_mask_type` | method | `get_geometry_mask_type() -> GeometryMaskType` | Kind of geometry mask on this node. |
| `LayerNode.set_geometry_mask_type` | method | `set_geometry_mask_type(geometry_mask_type: GeometryMaskType)` | Changes the kind of geometry mask on this node. **Deprecated in 0.3.7**; `set_geometry_mask` replaces it. |
| `LayerNode.get_geometry_mask_enabled_meshes` | method | `get_geometry_mask_enabled_meshes() -> List[str]` | Meshes the geometry mask lets through. |
| `LayerNode.set_geometry_mask_enabled_meshes` | method | `set_geometry_mask_enabled_meshes(mesh_names: List[str])` | Chooses the meshes the geometry mask lets through. **Deprecated in 0.3.7**; `set_geometry_mask` replaces it. |
| `LayerNode.get_geometry_mask_enabled_uv_tiles` | method | `get_geometry_mask_enabled_uv_tiles() -> List[UVTile]` | UV Tiles the geometry mask lets through. |
| `LayerNode.set_geometry_mask_enabled_uv_tiles` | method | `set_geometry_mask_enabled_uv_tiles(uv_tiles: List[UVTile])` | Chooses the UV Tiles the geometry mask lets through. **Deprecated in 0.3.7**; `set_geometry_mask` replaces it. |
| `LayerNode.get_geometry_mask` | method | `get_geometry_mask() -> GeometryMaskParams` | Reads the node's geometry-mask settings. |
| `LayerNode.set_geometry_mask` | method | `set_geometry_mask(params: GeometryMaskParams)` | Writes the node's geometry-mask settings. |
| `LayerNode.has_mask` | method | `has_mask() -> bool` | True when the node has a mask. |
| `LayerNode.add_mask` | method | `add_mask(background: MaskBackground)` | Gives the node a mask, starting black or white. |
| `LayerNode.remove_mask` | method | `remove_mask()` | Deletes the node's mask together with its effects. |
| `LayerNode.get_mask_background` | method | `get_mask_background() -> MaskBackground` | Black or white background of the node's mask. |
| `LayerNode.set_mask_background` | method | `set_mask_background(background: MaskBackground)` | Changes the background of the node's mask. |
| `LayerNode.is_mask_enabled` | method | `is_mask_enabled() -> bool` | True when the node's mask is active. |
| `LayerNode.enable_mask` | method | `enable_mask(enabled: bool)` | Activates or deactivates the node's mask. |
| `GroupLayerNode` | class | bases (LayerNode) | Handle to a group layer. |
| `GroupLayerNode.sub_layers` | method | `sub_layers() -> List[LayerNode]` | Layers inside this group. |
| `GroupLayerNode.is_collapsed` | method | `is_collapsed() -> bool` | True when the group is folded in the layer stack. |
| `GroupLayerNode.set_collapsed` | method | `set_collapsed(collapsed: bool)` | Folds or unfolds the group. |
| `PaintLayerNode` | class | bases (LayerNode) | Handle to a paint layer. |
| `InstanceLayerNode` | class | bases (LayerNode) | Handle to an instance layer. |
| `InstanceLayerNode.instance_source` | method | `instance_source() -> LayerNode` | Layer this instance reproduces. |
| `FillLayerNode` | class | bases (FillParamsEditorMixin, SourceEditorMixin, LayerNode) | Handle to a fill layer. |
| `HierarchicalNode` | type alias | = Union[LayerNode, GroupLayerNode, PaintLayerNode, InstanceLayerNode, FillLayerNode] |  |
| `GeneratorEffectNode` | class | bases (ActiveChannelsMixin, Node) | Handle to a generator effect. |
| `GeneratorEffectNode.get_source` | method | `get_source() -> SourceSubstance` | Procedural source of the generator; None when no generator is assigned. |
| `GeneratorEffectNode.set_source` | method | `set_source(res: substance_painter.resource.ResourceID) -> SourceSubstance` | Builds a source from a resource, assigns it and returns it. |
| `GeneratorEffectNode.remove_source` | method | `remove_source() -> None` | Clears the current source. |
| `PaintEffectNode` | class | bases (Node) | Handle to a paint effect. |
| `FillEffectNode` | class | bases (FillParamsEditorMixin, SourceEditorMixin, Node) | Handle to a fill effect. |
| `LevelsEffectNode` | class | bases (Node) | Handle to a levels effect. |
| `LevelsEffectNode.affected_channel` | property | `affected_channel() -> ChannelType` | Channel this levels effect adjusts. |
| `LevelsEffectNode.affected_channel` | property setter | `affected_channel(channel: ChannelType) -> None` | Setter of the property above. |
| `LevelsEffectNode.get_parameters` | method | `get_parameters() -> LevelsParams` | Reads the levels settings of this effect. |
| `LevelsEffectNode.set_parameters` | method | `set_parameters(params: LevelsParams) -> None` | Writes the levels settings of this effect. |
| `CompareMaskEffectParams` | dataclass | fields: channel: ChannelType; left_operand: CompareMaskEffectOperand; right_operand: CompareMaskEffectOperand; operation: CompareMaskEffectOperation; constant: float; tolerance: float; hardness: float | Settings of a compare-mask effect. |
| `CompareMaskEffectNode` | class | bases (Node) | Handle to a compare-mask effect. |
| `CompareMaskEffectNode.get_parameters` | method | `get_parameters() -> CompareMaskEffectParams` | Current compare-mask settings of this effect. |
| `CompareMaskEffectNode.set_parameters` | method | `set_parameters(params: CompareMaskEffectParams) -> None` | Applies new compare-mask settings to the effect. |
| `FilterEffectNode` | class | bases (ActiveChannelsMixin, Node) | Handle to a filter effect. |
| `FilterEffectNode.get_source` | method | `get_source() -> SourceSubstance` | Procedural source of the filter; None when no filter is assigned. |
| `FilterEffectNode.set_source` | method | `set_source(res: substance_painter.resource.ResourceID) -> SourceSubstance` | Builds a source from a resource, assigns it and returns it. |
| `FilterEffectNode.remove_source` | method | `remove_source() -> None` | Clears the current source. |
| `ColorSelectionEffectParams` | dataclass | fields: id_mask: Optional[substance_painter.resource.ResourceID]; output_value: float; hardness: float; tolerance: float; background_color: ColorSelectionBackgroundColor; colors: List[Color] | Settings of a colour-selection effect. |
| `ColorSelectionEffectNode` | class | bases (Node) | Handle to a colour-selection effect. |
| `ColorSelectionEffectNode.get_parameters` | method | `get_parameters() -> ColorSelectionEffectParams` | Reads the settings of this colour-selection effect. |
| `ColorSelectionEffectNode.set_parameters` | method | `set_parameters(params: ColorSelectionEffectParams) -> None` | Writes the settings of this colour-selection effect (the documentation's wording names the compare-mask effect here). |
| `AnchorPointEffectNode` | class | bases (Node) | Handle to an anchor-point effect. |
| `EffectNode` | type alias | = Union[GeneratorEffectNode, PaintEffectNode, FillEffectNode, LevelsEffectNode, CompareMaskEffectNode, FilterEffectNode, ColorSelectionEffectNode, AnchorPointEffectNode] |  |
| `get_root_layer_nodes` | function | `get_root_layer_nodes(stack: Stack) -> List[HierarchicalNode]` | Top-level layers of a stack, in layer-stack order. |
| `get_node_by_uid` | function | `get_node_by_uid(node_id: int) -> List[Union[HierarchicalNode, EffectNode]]` | Looks a node up by its internal identifier. |
| `get_selected_nodes` | function | `get_selected_nodes(stack: Stack) -> List[Union[HierarchicalNode, EffectNode]]` | Nodes selected in a stack, in layer-stack order. |
| `set_selected_nodes` | function | `set_selected_nodes(nodes: List[EffectNode] \| List[LayerNode])` | Makes these nodes the layer-stack selection in the UI. |
| `get_selection_type` | function | `get_selection_type(layer: LayerNode) -> SelectionType` | Which part of a layer (content, mask and so on) is selected. |
| `set_selection_type` | function | `set_selection_type(layer: LayerNode, layer_selection_type: SelectionType)` | Picks the selected part of a layer. |
| `delete_node` | function | `delete_node(node: Node)` | Removes a node from the layer stack. |
| `UVTransformationParams` | dataclass | fields: scale_mode: ScaleMode = None; scale: List[float] = None; rotation: float = None; offset: List[float] = None | Scale, rotation and offset of a UV projection. |
| `Projection3DParams` | dataclass | fields: offset: List[float] = None; rotation: List[float] = None; scale: List[float] = None | Offset, rotation and scale of a 3D projection. |
| `ProjectionCullingParams` | dataclass | fields: enabled: bool = None; hardness: float = None | On/off switch and hardness of projection culling. |
| `UVProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams) | Fill settings used with `ProjectionMode.UV`. |
| `TriplanarProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; shape_crop_mode: ShapeCropMode = None; hardness: float = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Fill settings used with `ProjectionMode.Triplanar`. |
| `PlanarProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; depth_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); backface_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); backface_culling_angle: float = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Fill settings used with `ProjectionMode.Planar`. |
| `WarpProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; projection_depth: float = None; depth_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Fill settings used with `ProjectionMode.Warp`. |
| `SphericalProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Fill settings used with `ProjectionMode.Spherical`. |
| `CylindricalProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; angle: float = None; backface_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Fill settings used with `ProjectionMode.Cylindrical`. Also declares private class metadata, which is not a dataclass field and not a constructor parameter ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\layerstack.py.]). |
| `UVSetToUVSetProjectionParams` | dataclass | fields: source_uv_set: int = None; filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams) | Fill settings used with `ProjectionMode.UVSetToUVSet`. |
| `ProjectionParams` | type alias | = Union[UVProjectionParams, TriplanarProjectionParams, PlanarProjectionParams, WarpProjectionParams, SphericalProjectionParams, CylindricalProjectionParams, UVSetToUVSetProjectionParams] | Union of the per-mode projection parameter classes; each mode has its own class. |
| `MirrorSymmetryParams` | dataclass | fields: axis: SymmetryAxis = None; flip_u: bool = None; flip_v: bool = None; axis_position: List[float] = None | Mirror-symmetry settings. |
| `RadialSymmetryParams` | dataclass | fields: axis: SymmetryAxis = None; flip_u: bool = None; flip_v: bool = None; axis_position: List[float] = None; count: int = None; angle_span: float = None | Radial-symmetry settings. |
| `SymmetryParams` | type alias | = Union[MirrorSymmetryParams, RadialSymmetryParams] | Union of the per-mode symmetry parameter classes. |
| `InsertPosition` | dataclass | fields: node_id: int; node_stack: Optional[int] | Target location in the layer-stack hierarchy, taken by every insert function. |
| `InsertPosition.from_textureset_stack` | staticmethod | `from_textureset_stack(stack: substance_painter.textureset.Stack) -> InsertPosition` | Position at the top of a stack. |
| `InsertPosition.above_node` | staticmethod | `above_node(node: Node) -> InsertPosition` | Position directly above a node. |
| `InsertPosition.below_node` | staticmethod | `below_node(node: Node) -> InsertPosition` | Position directly below a node. |
| `InsertPosition.inside_node` | staticmethod | `inside_node(node: Node, node_stack: NodeStack) -> InsertPosition` | Position inside one of a node's stacks (sub-stack, content or mask). |
| `insert_fill` | function | `insert_fill(position: InsertPosition) -> Union[FillLayerNode, FillEffectNode]` | Adds a fill: a layer or an effect, depending on the position. |
| `insert_paint` | function | `insert_paint(position: InsertPosition) -> Union[PaintLayerNode, PaintEffectNode]` | Adds a paint layer or a paint effect, depending on the position. |
| `insert_group` | function | `insert_group(position: InsertPosition) -> GroupLayerNode` | Adds a group layer. |
| `instantiate` | function | `instantiate(position: InsertPosition, layer: LayerNode) -> InstanceLayerNode` | Adds an instance of an existing layer. |
| `insert_levels_effect` | function | `insert_levels_effect(position: InsertPosition) -> LevelsEffectNode` | Adds a levels effect with its default settings. |
| `insert_compare_mask_effect` | function | `insert_compare_mask_effect(position: InsertPosition) -> CompareMaskEffectNode` | Adds a compare-mask effect with its default settings. |
| `insert_filter_effect` | function | `insert_filter_effect(position: InsertPosition, filter_substance: Optional[substance_painter.resource.ResourceID] = None) -> FilterEffectNode` | Adds a filter effect, empty or bound to a filter resource. |
| `insert_generator_effect` | function | `insert_generator_effect(position: InsertPosition, generator_substance: Optional[substance_painter.resource.ResourceID] = None) -> GeneratorEffectNode` | Adds a generator effect, empty or bound to a resource. |
| `insert_anchor_point_effect` | function | `insert_anchor_point_effect(position: InsertPosition, name: str) -> AnchorPointEffectNode` | Adds a named anchor-point effect. |
| `insert_color_selection_effect` | function | `insert_color_selection_effect(position: InsertPosition) -> ColorSelectionEffectNode` | Adds a colour-selection effect. |
| `insert_smart_material` | function | `insert_smart_material(position: InsertPosition, smart_material: substance_painter.resource.ResourceID) -> GroupLayerNode` | Adds a smart material at a position. |
| `create_smart_material` | function | `create_smart_material(group: GroupLayerNode, name: str) -> substance_painter.resource.Resource` | Makes a smart-material resource called `name` out of a group. |
| `export_as_smart_material` | function | `export_as_smart_material(group: GroupLayerNode, name: str, path: str)` | Writes a group to `path` as a smart material called `name`. |
| `insert_smart_mask` | function | `insert_smart_mask(position: InsertPosition, smart_mask: substance_painter.resource.ResourceID) -> List[EffectNode]` | Adds a smart mask to a mask stack. |
| `create_smart_mask` | function | `create_smart_mask(layer: LayerNode, name: str) -> substance_painter.resource.Resource` | Makes a smart-mask resource called `name` out of a layer's mask stack. |
| `export_as_smart_mask` | function | `export_as_smart_mask(layer: LayerNode, name: str, path: str)` | Writes a layer's mask stack to `path` as a smart mask called `name`. |
| `Node.uid` (inherited from `_utility.ReadOnlyUid`) | method | `uid() -> int` | Internal identifier of the node (also present on every `source.Source*` class). |
| `FillLayerNode` / `FillEffectNode` (inherited) | note | all `FillParamsEditorMixin` and `source.SourceEditorMixin` members | The HTML docs list these inherited members under both classes (projection, symmetry, sources, `active_channels`, `source_mode`). |
| `GeneratorEffectNode` / `FilterEffectNode` (inherited) | note | `source.ActiveChannelsMixin.active_channels` | Active-channel set of the effect. |
| `ScopedModification.__enter__` / `__exit__` | context manager | `with ScopedModification(name): ...` | Groups calls into one undo entry and one recomputation. |

## `substance_painter.levels`

Levels parameter dataclasses used by the Levels effect and by anchor references. Source: `resources\python\modules\substance_painter\levels.py`; HTML: `resources\python-doc\substance_painter\layerstack\layereffect\levels.html (no standalone page)`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `LevelsParamsRGB` | dataclass | fields: input_min: Tuple[float, float, float] = (0.0, 0.0, 0.0); input_max: Tuple[float, float, float] = (1.0, 1.0, 1.0); gamma: Tuple[float, float, float] = (1.0, 1.0, 1.0); output_min: Tuple[float, float, float] = (0.0, 0.0, 0.0); output_max: Tuple[float, float, float] = (1.0, 1.0, 1.0); clamp: bool = False | Levels settings for RGB mode, one value per colour component. |
| `LevelsParamsMono` | dataclass | fields: input_min: float = 0.0; input_max: float = 1.0; gamma: float = 1.0; output_min: float = 0.0; output_max: float = 1.0; clamp: bool = False | Levels settings for luminance or single-channel mode. |
| `LevelsParams` | type alias | = Union[LevelsParamsMono, LevelsParamsRGB] | Union of the mono and RGB levels settings. |

## `substance_painter.logging`

Messages to the Painter log/console. Source: `resources\python\modules\substance_painter\logging.py`; HTML: `resources\python-doc\substance_painter\logging.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `INFO`, `WARNING`, `ERROR`, `DBG_INFO`, `DBG_WARNING`, `DBG_ERROR` | attribute | severity constants (documented in prose in `logging.html`); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\logging.py.] |  |
| `log` | function | `log(severity, channel: str, message: str)` | Writes `message` to Painter's log on a named channel, at the given severity. |
| `info` | function | `info(message: str)` | Writes `message` to Painter's log at `INFO` severity. |
| `warning` | function | `warning(message: str)` | Writes `message` to Painter's log at `WARNING` severity. |
| `error` | function | `error(message: str)` | Writes `message` to Painter's log at `ERROR` severity. |

## `substance_painter.project`

Project create/open/save/close, settings dataclasses, mesh reload, busy state, metadata. Source: `resources\python\modules\substance_painter\project.py`; HTML: `resources\python-doc\substance_painter\project.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ProjectSaveMode` | enum (native) | Members: `Full`, `Incremental` | How a save is written: full or incremental. |
| `NormalMapFormat` | enum (native) | Members: `OpenGL`, `DirectX` | Normal-map convention of a project: OpenGL or DirectX. |
| `TangentSpace` | enum (native) | Members: `PerVertex`, `PerFragment` | How a project computes its tangent frame: per vertex or per fragment. |
| `ProjectWorkflow` | enum (native) | Members: `Default`, `TextureSetPerUVTile`, `UVTile` | Texture Set and UV Tile workflow of a project. |
| `AutoUnwrapUVIslandOrientation` | enum (native) | Members: `RotateFreely`, `AlignWith3DMesh`, `KeepOriginal` | Island orientation rule of the automatic unwrap. |
| `AutoUnwrapUVTilesSettingsUVTilesCount` | dataclass | fields: uv_tile_count_max: int = 4 | Automatic-unwrap setting that caps how many UV Tiles are produced. |
| `AutoUnwrapUVTilesSettingsTexelDensity` | dataclass | fields: texel_density: float = 1.0; reference_resolution: int = 1024 | Automatic-unwrap setting that targets a texel density for UV Tiles. |
| `AutoUnwrapUVTilesSettings` | type alias | = Union[AutoUnwrapUVTilesSettingsUVTilesCount, AutoUnwrapUVTilesSettingsTexelDensity] |  |
| `AutoUnwrapSettings` | dataclass | fields: recompute_seams: bool = True; recompute_uv_islands: bool = True; recompute_packing: bool = True; margin_size: float = 2.0; island_orientation: AutoUnwrapUVIslandOrientation = dataclasses.field(default_factory=lambda: AutoUnwrapUVIslandOrientation.RotateFreely); uv_tiles_settings: AutoUnwrapUVTilesSettings = dataclasses.field(default_factory=AutoUnwrapUVTilesSettingsUVTilesCount); avoid_elongated_uv_islands: bool = False; create_fewer_seams: bool = True | Automatic-unwrap options used when a project is created or its mesh is reloaded. |
| `UsdSettings` | dataclass | fields: scope_name: str = '/'; variants: dict = None; subdivision_level: int = 1; frame: int = 0 | Import options for USD meshes. |
| `GltfSettings` | dataclass | fields: invert_normal_maps: bool = None | Import options for glTF meshes. |
| `Settings` | dataclass | fields: default_save_path: str = None; normal_map_format: NormalMapFormat = None; tangent_space_mode: TangentSpace = None; project_workflow: ProjectWorkflow = None; export_path: str = None; default_texture_resolution: int = None; import_cameras: bool = None; mesh_unit_scale: float = None; mesh_settings: Union[UsdSettings, GltfSettings] = None; auto_unwrap_settings: AutoUnwrapSettings = None | Options of a new project. |
| `Settings.usd_settings` | property | `usd_settings()` | Hidden from the documentation. **Deprecated since 0.3.2 (use mesh_settings).** |
| `Settings.usd_settings` | property setter | `usd_settings(value)` | Setter of the property above. |
| `MeshReloadingSettings` | dataclass | fields: import_cameras: bool = True; preserve_strokes: bool = True; mesh_settings: UsdSettings = None; auto_unwrap_settings: AutoUnwrapSettings = None | Options of a mesh reload. |
| `MeshReloadingSettings.usd_settings` | property | `usd_settings()` | Hidden from the documentation. **Deprecated since 0.3.2 (use mesh_settings).** |
| `MeshReloadingSettings.usd_settings` | property setter | `usd_settings(value)` | Setter of the property above. |
| `name` | function | `name() -> Optional[str]` | Name of the open project, or None. |
| `file_path` | function | `file_path() -> Optional[str]` | File path of the open project, or None. |
| `close` | function | `close() -> None` | Closes the open project. |
| `open` | function | `open(project_file_path: str) -> None` | Opens the project file at `project_file_path`. |
| `is_open` | function | `is_open() -> bool` | True when a project is open. |
| `needs_saving` | function | `needs_saving() -> bool` | True when the open project has unsaved changes. |
| `is_in_edition_state` | function | `is_in_edition_state() -> bool` | True when the open project is loaded and editable. |
| `is_busy` | function | `is_busy() -> bool` | True while Painter is busy. |
| `execute_when_not_busy` | function | `execute_when_not_busy(callback: Callable[[], None]) -> None` | Defers a callback until Painter is no longer busy. |
| `save_as` | function | `save_as(project_file_path: str, mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Writes the open project to the new path `project_file_path`. |
| `save` | function | `save(mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Writes the open project over its last saved file. |
| `save_as_copy` | function | `save_as_copy(backup_file_path: str, mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Writes a copy of the open project to `backup_file_path`. |
| `save_as_template` | function | `save_as_template(template_file_path: str, texture_set_name: str) -> ProjectSaveMode` | Saves a template built from the named Texture Set (by default the current one). |
| `create` | function | `create(mesh_file_path: str, mesh_map_file_paths: List[str] = None, template_file_path: str = None, settings: Settings = Settings())` | Starts a new project from a mesh, with optional mesh maps, template and settings. |
| `last_imported_mesh_path` | function | `last_imported_mesh_path() -> str` | Path of the mesh imported most recently. |
| `last_saved_substance_painter_version` | function | `last_saved_substance_painter_version() -> Optional[Tuple[int, int, int]]` | Painter version that last saved the project; None for an unsaved project or one last saved by 8.2.0 or earlier. |
| `ReloadMeshStatus` | enum | Members: `SUCCESS`, `ERROR` (values 0 and 2 per HTML doc) | Result passed to the mesh-reload callback. |
| `reload_mesh` | function | `reload_mesh(mesh_file_path: str, settings: MeshReloadingSettings, loading_status_cb: Callable[[ReloadMeshStatus], Any])` | Replaces the project's mesh with a new file, using the given reload settings. |
| `BoundingBox` | dataclass | fields: dimensions: List[float]; center: List[float]; radius: float | Axis-aligned box (dimensions, centre, radius). |
| `get_scene_bounding_box` | function | `get_scene_bounding_box() -> BoundingBox` | Axis-aligned box that encloses the scene. |
| `get_uuid` | function | `get_uuid() -> uuid.UUID` | UUID of the open project. |
| `Metadata` | class | — | Arbitrary user data stored in a project under keys. |
| `Metadata.__init__` | constructor | `__init__(context: str)` |  |
| `Metadata.list` | method | `list() -> list` | Keys under which project metadata is stored. |
| `Metadata.get` | method | `get(key: str)` | Reads the project metadata stored under a key. |
| `Metadata.set` | method | `set(key: str, value)` | Stores project metadata under a key. |
| `ProjectSaveMode` default | note | `ProjectSaveMode.Incremental` (HTML signatures; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\project.py.]) | Default mode of `save`, `save_as`, `save_as_copy`. |

## `substance_painter.properties`

Read-only wrapper over dynamic engine properties (used by baking and substance sources). Source: `resources\python\modules\substance_painter\properties.py`; HTML: `resources\python-doc\substance_painter\properties.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `PropertyValue` | type alias | = typing.Union[bool, int, typing.Tuple[int, int], typing.Tuple[int, int, int], typing.Tuple[int, int, int, int], float, typing.Tuple[float, float], typing.Tuple[float, float, float], Color, typing.Tuple[Color, float], typing.Tuple[float, float, float, float], str] |  |
| `Property` | dataclass | fields: handle: _substance_painter.data_tweak.PythonTweak | Read-only view of one engine property. |
| `Property.value` | method | `value() -> PropertyValue` | Current value of the property. |
| `Property.name` | method | `name() -> str` | Full name of the property. |
| `Property.short_name` | method | `short_name() -> str` | Abbreviated name of the property. |
| `Property.label` | method | `label() -> str` | Label shown for the property. |
| `Property.widget_type` | method | `widget_type() -> str` | Kind of UI widget meant for editing the property. |
| `Property.enum_values` | method | `enum_values() -> typing.Dict[str, int]` | For a combo-box property, the mapping of option text to integer value. |
| `Property.enum_value` | method | `enum_value(enum_label: str) -> int` | For a combo-box property, the integer value of one option label. |
| `Property.properties` | method | `properties() -> typing.Dict[str, typing.Any]` | All metadata of the property, as a JSON-style object. |

## `substance_painter.resource`

Resources (URL-identified assets), shelves, search, import, project-resource listing/replacement, reload. Source: `resources\python\modules\substance_painter\resource.py`; HTML: `resources\python-doc\substance_painter\resource.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ResourceLocation` | enum | Members: `SESSION`, `PROJECT`, `SHELF` | Where a resource's data is held: session, project or shelf. |
| `ResourceID` | dataclass | fields: context: str; name: str; version: str = None | Identifier of a Painter resource (context, name and optional version). |
| `ResourceID.from_url` | classmethod | `from_url(url: str)` | Builds a `ResourceID` from its URL form. |
| `ResourceID.from_project` | classmethod | `from_project(name: str, version: str = None)` | Builds a `ResourceID` for a resource stored in the open project. |
| `ResourceID.from_session` | classmethod | `from_session(name: str, version: str = None)` | Builds a `ResourceID` for a resource stored in the session. |
| `ResourceID.url` | method | `url() -> str` | URL form of the identifier. |
| `ResourceID.location` | method | `location() -> ResourceLocation` | Where the identified resource lives. |
| `Usage` | enum | Members: `ALPHA`, `BASE_MATERIAL`, `BRUSH`, `COLOR_LUT`, `EMITTER`, `ENVIRONMENT`, `EXPORT`, `FILTER`, `FONT`, `GENERATOR`, `PARTICLE`, `PROCEDURAL`, `RECEIVER`, `SHADER`, `SMART_MASK`, `SMART_MATERIAL`, `TEXTURE`, `TOOL` | Intended role of a resource. |
| `Type` | enum | Members: `ABR_PACKAGE`, `BRUSH`, `EXPORT`, `FONT`, `IMAGE`, `PRESET`, `RESOURCE`, `SCRIPT`, `SHADER`, `SMART_MASK`, `SMART_MATERIAL`, `SUBSTANCE`, `SUBSTANCE_PACKAGE`, `VECTORIAL` | Kind of a resource. |
| `Resource` | dataclass | fields: handle: _substance_painter.resource.ResourceHandle | Handle to a Painter resource. |
| `Resource.identifier` | method | `identifier() -> ResourceID` | Identifier of this resource. |
| `Resource.location` | method | `location() -> ResourceLocation` | Where this resource lives. |
| `Resource.retrieve` | staticmethod | `retrieve(identifier: ResourceID)` | Resources that match an identifier, as a list. |
| `Resource.set_custom_preview` | method | `set_custom_preview(preview_image: str) -> None` | Uses an image file as this resource's thumbnail. |
| `Resource.category` | method | `category() -> str` | Category of the resource (for a material, for example "wood"). |
| `Resource.usages` | method | `usages() -> typing.List[Usage]` | Roles this resource can play. |
| `Resource.gui_name` | method | `gui_name() -> str` | Name the UI shows for this resource. |
| `Resource.type` | method | `type() -> Type` | Kind of this resource. |
| `Resource.tags` | method | `tags() -> typing.List[str]` | Tags attached to this resource. |
| `Resource.internal_properties` | method | `internal_properties() -> dict` | Internal properties of the resource, as a dictionary. |
| `Resource.children` | method | `children() -> typing.List['Resource']` | Resources nested under this one. |
| `Resource.parent` | method | `parent() -> typing.Optional['Resource']` | Resource this one is nested under, if any. |
| `Resource.reset_preview` | method | `reset_preview() -> None` | Drops a custom thumbnail and goes back to the default one. |
| `Resource.show_in_ui` | method | `show_in_ui() -> None` | Highlights this resource in the Assets window. |
| `show_resources_in_ui` | function | `show_resources_in_ui(resources: typing.List[Resource]) -> None` | Highlights several resources in the Assets window. |
| `import_project_resource` | function | `import_project_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None) -> Resource` | Imports a file as a resource of the open project. |
| `import_session_resource` | function | `import_session_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None) -> Resource` | Imports a file as a resource of the session. |
| `StandardQuery` | class | fields: ALL_RESOURCES; PROJECT_RESOURCES; SESSION_RESOURCES; SHELVES_RESOURCES ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\resource.py.]) | Predefined search queries. |
| `search` | function | `search(query: str) -> typing.List[Resource]` | Painter resources that match a query string. |
| `list_layer_stack_resources` | function | `list_layer_stack_resources() -> typing.List[ResourceID]` | Resources referred to by the project's layer stacks or mesh maps. **Deprecated in 0.3.4**; `list_project_resources` replaces it. |
| `update_layer_stack_resource` | function | `update_layer_stack_resource(old_resource_id: ResourceID, new_resource: Resource) -> typing.List[ResourceID]` | Swaps one resource for another wherever the project's layer stacks or mesh maps use it. **Deprecated in 0.3.4**; `replace_project_resources` replaces it. |
| `list_project_resources` | function | `list_project_resources() -> typing.List[ResourceID]` | Resources the open project uses. |
| `list_project_outdated_resources` | function | `list_project_outdated_resources() -> typing.Dict[ResourceID, ResourceID]` | Resources the open project uses that are out of date, returned as a mapping. |
| `UpdateProjectStatus` | enum (native) | Members: `SUCCESS`, `ERROR` | Outcome of `replace_project_resources`. |
| `UpdateProjectError` | dataclass | fields: old_resource_id: ResourceID; new_resource_id: ResourceID; details: typing.List[str] | One failure reported by `replace_project_resources`. |
| `UpdateProjectResult` | dataclass | fields: status: UpdateProjectStatus; errors: typing.List[UpdateProjectError] | What `replace_project_resources` returns: status and failures. |
| `replace_project_resources` | function | `replace_project_resources(ids: typing.Dict[ResourceID, ResourceID], allow_parameters_mismatch: bool = False) -> UpdateProjectResult` | Swaps resources of the open project according to an old-to-new mapping. |
| `Shelf` | dataclass | fields: _name: str | Information about one Painter shelf. |
| `Shelf.name` | method | `name() -> str` | The shelf's name. |
| `Shelf.path` | method | `path() -> str` | Folder the shelf is bound to. |
| `Shelf.resources` | method | `resources(query: str = StandardQuery.ALL_RESOURCES) -> typing.List[Resource]` | Resources held by this shelf, optionally narrowed by a query. |
| `Shelf.can_import_resources` | method | `can_import_resources() -> bool` | True when this shelf accepts imported resources. |
| `Shelf.import_resource` | method | `import_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None, uuid: str = None) -> Resource` | Imports a file as a resource of this shelf. |
| `Shelf.is_crawling` | method | `is_crawling() -> bool` | True while the shelf is scanning its folders for resources. |
| `Shelf.refresh` | method | `refresh()` | Makes the shelf rescan its folders. |
| `Shelves` | class | — | Static helpers that manage shelves. |
| `Shelves.all` | staticmethod | `all() -> typing.List[Shelf]` | Every shelf. |
| `Shelves.exists` | staticmethod | `exists(name: str) -> bool` | True when a shelf of that name exists. |
| `Shelves.add` | staticmethod | `add(name: str, path: str) -> Shelf` | Creates a shelf bound to a folder. |
| `Shelves.remove` | staticmethod | `remove(name: str)` | Deletes a shelf. |
| `Shelves.refresh_all` | staticmethod | `refresh_all()` | Makes every shelf rescan its folders. |
| `Shelves.user_shelf` | staticmethod | `user_shelf() -> Shelf` | Shelf in the user's Documents folder, where new resources go by default. |
| `Shelves.application_shelf` | staticmethod | `application_shelf() -> Shelf` | Shelf that holds the content installed with the application. |
| `AllResourcesFilter` | dataclass | — | Reload filter covering every modified resource Painter knows: all shelves, session and project. |
| `ProjectFilter` | dataclass | — | Reload filter covering modified resources stored in the project. |
| `ResourcesListFilter` | dataclass | fields: resources: typing.List[ResourceID] | Reload filter covering modified resources from an explicit list. |
| `ResourcesUsedByProjectFilter` | dataclass | — | Reload filter covering modified resources the project currently uses. |
| `SessionFilter` | dataclass | — | Reload filter covering modified resources stored in the session. |
| `ShelvesListFilter` | dataclass | fields: shelves: typing.List[Shelf] | Reload filter covering modified resources of the named shelves. |
| `ReloadResourcesFilter` | type alias | = typing.Union[AllResourcesFilter, ProjectFilter, ResourcesListFilter, ResourcesUsedByProjectFilter, SessionFilter, ShelvesListFilter] |  |
| `reload_modified_resources_async` | function | `reload_modified_resources_async(resource_filter: ReloadResourcesFilter) -> bool` | Starts reloading the modified resources a filter selects. |
| `is_reload_modified_resources_running` | function | `is_reload_modified_resources_running() -> bool` | True while a reload of modified resources is in progress. |

## `substance_painter.source`

Sources that feed fill layers/effects and procedural inputs: uniform color, bitmap, font, vector, substance, anchor reference. Source: `resources\python\modules\substance_painter\source.py`; HTML: `resources\python-doc\substance_painter\source\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `SourceMode` | enum (native) | Members: `Split`, `Material` | Whether a fill in a multi-channel context uses one source for all channels (material) or one source per channel (split). |
| `FontResolutionMode` | enum | Members: `Auto`, `Manual` | Resolution mode for font sources. **Deprecated in 0.3.4**; `ResolutionMode` replaces it. |
| `HorizontalAlignment` | enum (native) | Members: `Left`, `Center`, `Right` | Horizontal text alignment. |
| `VerticalAlignment` | enum (native) | Members: `Top`, `Middle`, `Bottom` | Vertical text alignment. |
| `ResolutionMode` | enum | Members: `Auto`, `Asset`, `Custom`, `TextureSet`, `UVTile`, `Document`, `Manual` | How a source's resolution is chosen. |
| `VectorialResolutionMode` | attribute | = ResolutionMode | Older name of `ResolutionMode`. **Deprecated since 0.3.4** (alias of `ResolutionMode`). |
| `CropAreaMode` | enum (native) | Members: `DocumentBounds`, `Manual` | How the crop area of a vector source is set: document bounds or manual. |
| `AlphaMatte` | enum (native) | Members: `KeepAlpha`, `ExtractAlpha`, `DefaultBackgroundColor` | How an anchor reference treats alpha: keep it, extract it or use the default background colour. |
| `ResolutionOverride` | dataclass | fields: mode: ResolutionMode; value: Tuple[int, int]; log2_offset: int | Settings that override a source's resolution. |
| `ActiveChannelsMixin` | class | — | Helper base that carries the active-channel set. Docstring marks it `:meta private:` (`source.py:300–305`): implementation helper; `active_channels` is public through `FillLayerNode`, `FillEffectNode`, `GeneratorEffectNode`, `FilterEffectNode` only (not `PaintLayerNode`). |
| `ActiveChannelsMixin.active_channels` | property | `active_channels() -> Set[ChannelType]` | Channels the source currently writes to. |
| `ActiveChannelsMixin.active_channels` | property setter | `active_channels(channels: Set[ChannelType]) -> None` | Setter of the property above. |
| `SourceEditorMixin` | class | bases (ActiveChannelsMixin) | Helper base that carries the source-editing functions. Docstring marks it `:meta private:` (`source.py:324–329`): implementation helper; members public through `FillLayerNode`/`FillEffectNode`. |
| `SourceEditorMixin.source_mode` | property | `source_mode() -> SourceMode` | Context the source is edited in (split or material). |
| `SourceEditorMixin.get_source` | method | `get_source(channeltype: ChannelType \| None = None) -> Source` | Source feeding a channel type. |
| `SourceEditorMixin.set_source` | method | `set_source(channeltype: ChannelType \| None, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | Assigns the source of a channel type (a resource, a colour or an anchor point). |
| `SourceEditorMixin.reset_source` | method | `reset_source(channeltype: ChannelType \| None = None) -> None` | Restores the default source of a channel type. |
| `SourceEditorMixin.get_material_source` | method | `get_material_source() -> SourceSubstance \| SourceReference` | Source used in material mode. |
| `SourceEditorMixin.set_material_source` | method | `set_material_source(source: ResourceID \| layerstack.AnchorPointEffectNode) -> SourceSubstance \| SourceReference` | Assigns the source used in material mode. |
| `SourceEditorMixin.reset_material_source` | method | `reset_material_source() -> None` | Restores the default material-mode source. |
| `SourceEditorMixin.set_sources_from_preset` | method | `set_sources_from_preset(preset: ResourceID) -> None` | Configures the fill from a preset. |
| `SourceUniformColor` | class | bases (ReadOnlyUid) | Uniform-colour source. |
| `SourceUniformColor.get_color` | method | `get_color() -> Color` | Colour of the source. |
| `SourceUniformColor.set_color` | method | `set_color(color: Color) -> None` | Changes the colour of the source. |
| `SourceBitmap` | class | bases (ReadOnlyUid) | Bitmap (image) source. |
| `SourceBitmap.resource_id` | property | `resource_id() -> ResourceID` | Image resource the source uses. |
| `SourceBitmap.get_color_space` | method | `get_color_space() -> ResourceColorSpace` | Colour space the bitmap is read in. |
| `SourceBitmap.set_color_space` | method | `set_color_space(color_space: ResourceColorSpace)` | Overrides the bitmap's default colour space. |
| `SourceBitmap.reset_color_space` | method | `reset_color_space()` | Drops a colour-space override and returns to the default. |
| `SourceBitmap.list_available_color_spaces` | method | `list_available_color_spaces() -> List[ResourceColorSpace]` | Colour spaces the bitmap can be read in. |
| `SourceFontParams` | dataclass | bases: private ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\source.py.]) — fields: text: str \| None; auto_size: bool; size: float \| None; horizontal_alignment: HorizontalAlignment; vertical_alignment: VerticalAlignment; color: Color; background_color: Color; background_opacity: float \| None; line_spacing: float; character_spacing: float; offset: Tuple[float, float]; resolution: ResolutionOverride | Settings of a text source. |
| `SourceFont` | class | bases (ReadOnlyUid) | Text (font) source. |
| `SourceFont.resource_id` | property | `resource_id() -> ResourceID` | Font resource the source uses. |
| `SourceFont.get_parameters` | method | `get_parameters() -> SourceFontParams` | Reads the source settings. |
| `SourceFont.set_parameters` | method | `set_parameters(params: SourceFontParams) -> None` | Writes the source settings. |
| `SourceVectorialParams` | dataclass | bases: private (same redaction as `SourceFontParams`) — fields: artboard_id: str \| None; scope: str \| None; resolution: ResolutionOverride; crop_area_mode: CropAreaMode; crop_area_value: Tuple[float, float, float, float]; fit_to_square: bool = True | Settings of a vector source. |
| `SourceVectorial` | class | bases (ReadOnlyUid) | Vector-graphics source. |
| `SourceVectorial.resource_id` | property | `resource_id() -> ResourceID` | Vector resource the source uses. |
| `SourceVectorial.get_parameters` | method | `get_parameters() -> SourceVectorialParams` | Reads the source settings. |
| `SourceVectorial.set_parameters` | method | `set_parameters(params: SourceVectorialParams) -> None` | Writes the source settings. |
| `OutputMappingIterator` | class | — | Iterator over an `OutputMapping`. Docstring marks it `:meta private:` (`source.py:709–714`): implementation helper. |
| `OutputMappingIterator.__init__` | constructor | `__init__(uid)` |  |
| `OutputMapping` | class | bases (ReadOnlyUid) | Dictionary-style access to how a procedural source's outputs map to channels. |
| `SourceSubstance` | class | bases (ReadOnlyUid) | Procedural (Substance) source. |
| `SourceSubstance.resource_id` | property | `resource_id() -> ResourceID` | Procedural resource the source uses. |
| `SourceSubstance.output_mapping` | property | `output_mapping() -> OutputMapping` | Output-to-channel mapping when the source drives several outputs. |
| `SourceSubstance.active_output` | property | `active_output() -> str` | Output used when the source drives a single output. |
| `SourceSubstance.active_output` | property setter | `active_output(identifier: str) -> None` | Setter of the property above. |
| `SourceSubstance.mask_output` | property | `mask_output() -> str` | Identifier of the output used as mask when the source drives several outputs. |
| `SourceSubstance.mask_output` | property setter | `mask_output(identifier: str) -> None` | Setter of the property above. |
| `SourceSubstance.image_inputs` | property | `image_inputs() -> List[str]` | Identifiers of the graph's image inputs. |
| `SourceSubstance.image_outputs` | property | `image_outputs() -> List[str]` | Identifiers of the graph's image outputs. |
| `SourceSubstance.get_source` | method | `get_source(identifier: str) -> Source` | Source plugged into an image input. |
| `SourceSubstance.set_source` | method | `set_source(identifier: str, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | Plugs a source (a resource, a colour or an anchor point) into an image input. |
| `SourceSubstance.reset_source` | method | `reset_source(identifier: str) -> None` | Restores the default source of an image input. |
| `SourceSubstance.remove_source` | method | `remove_source(identifier: str) -> None` | Unplugs the source of an image input. |
| `SourceSubstance.get_parameters` | method | `get_parameters() -> Dict[str, PropertyValue]` | Reads the procedural's parameter values. |
| `SourceSubstance.set_parameters` | method | `set_parameters(property_values: Dict[str, PropertyValue]) -> None` | Writes procedural parameter values. |
| `SourceSubstance.get_properties` | method | `get_properties() -> Dict[str, Property]` | The procedural's parameters as `Property` objects. |
| `SourceSubstance.get_preset_list` | method | `get_preset_list() -> List[str]` | Names of the presets available for this source. |
| `SourceSubstance.apply_preset` | method | `apply_preset(name: str)` | Applies a preset by name. |
| `SourceSubstance.resolution` | property | `resolution() -> ResolutionOverride` | Resolution settings of this procedural. |
| `SourceSubstance.resolution` | property setter | `resolution(value)` | Setter of the property above. |
| `ChannelMappingIterator` | class | — | Iterator over a `ChannelMapping`. Docstring marks it `:meta private:` (`source.py:983–988`): implementation helper. |
| `ChannelMappingIterator.__init__` | constructor | `__init__(uid)` |  |
| `ChannelMapping` | class | bases (ReadOnlyUid) | Dict-like view of which channels an anchor reference makes active. |
| `SourceReference` | class | bases (ReadOnlyUid) | Source that reads an anchor point. |
| `SourceReference.channel_mapping` | property | `channel_mapping() -> ChannelMapping` | Channel mapping of the reference. |
| `SourceReference.referenced_channel` | property | `referenced_channel() -> ChannelType` | Anchor channel the source reads. |
| `SourceReference.referenced_channel` | property setter | `referenced_channel(channeltype: ChannelType) -> None` | Setter of the property above. |
| `SourceReference.anchor` | property | `anchor() -> layerstack.AnchorPointEffectNode` | Anchor point the source reads. |
| `SourceReference.alpha_matte` | property | `alpha_matte() -> AlphaMatte` | Alpha handling of the source. |
| `SourceReference.alpha_matte` | property setter | `alpha_matte(alpha_matte: AlphaMatte)` | Setter of the property above. |
| `SourceReference.get_levels` | method | `get_levels() -> LevelsParams` | Reads the levels applied by this source. |
| `SourceReference.set_levels` | method | `set_levels(params: LevelsParams) -> None` | Writes the levels applied by this source. |
| `Source` | type alias | = Union[SourceUniformColor, SourceBitmap, SourceVectorial, SourceSubstance, SourceReference, SourceFont] |  |
| `OutputMapping` / `ChannelMapping` (dunder API) | dict-like | `__getitem__(ChannelType)`, `__setitem__(ChannelType, str or ChannelType)`, `__len__`, `__contains__`, `__iter__` | Read/write output mapping (substance outputs to channels) and channel mapping (anchor channels to channels). |
| `SourceFontParams.resolution_mode` / `resolution_value`, `SourceVectorialParams.resolution_mode` / `resolution_value` | deprecated attributes | via a private base (same redaction as `SourceFontParams`) | **Deprecated since 0.3.4**; replaced by `resolution: ResolutionOverride`. |

## `substance_painter.textureset`

Texture Sets, stacks, channels (types/formats), UV tiles, resolutions, mesh-map slots. Source: `resources\python\modules\substance_painter\textureset.py`; HTML: `resources\python-doc\substance_painter\textureset\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ChannelFormat` | enum (native) | Members: `sRGB8`, `L8`, `RGB8`, `L16`, `RGB16`, `L16F`, `RGB16F`, `L32F`, `RGB32F` | Storage format of a channel. |
| `ChannelType` | enum (native) | Members: OpenPBR: `BaseWeight`, `BaseColor`, `BaseMetalness`, `BaseDiffuseRoughness`, `SpecularWeight`, `SpecularColor`, `SpecularRoughness`, `SpecularRoughnessAnisotropy`, `TransmissionWeight`, `TransmissionColor`, `SubsurfaceWeight`, `SubsurfaceColor`, `SubsurfaceRadiusScale`, `CoatWeight`, `CoatColor`, `CoatRoughness`, `CoatRoughnessAnisotropy`, `CoatNormal`, `CoatTangent`, `FuzzWeight`, `FuzzColor`, `FuzzRoughness`, `EmissionColor`, `ThinFilmWeight`, `Opacity`, `Height`, `Displacement`, `Normal`, `Tangent`, `AO`; User: `User0`..`User31`; Non-OpenPBR (legacy/ASM): `Glossiness`, `Specular`, `Anisotropyangle`, `Transmissive`, `Reflection`, `Ior`, `Diffuse`, `Specularlevel`, `BlendingMask`, `CoatSpecularLevel`; Legacy aliases: `Metallic`, `Roughness`, `Emissive`, `SpecularEdgeColor`, `Anisotropylevel`, `Scattering`, `ScatteringColor`, `Translucency`, `AbsorptionColor`, `SheenOpacity`, `SheenRoughness`, `SheenColor`, `CoatOpacity` | Every channel kind a document can hold. |
| `MeshMapUsage` | enum (native) | Members: `AO`, `BentNormals`, `Curvature`, `Height`, `ID`, `Normal`, `Opacity`, `Position`, `Thickness`, `WorldSpaceNormal` | Kind of mesh map (baked map slot). |
| `Resolution` | dataclass | fields: width: int = 1024; height: int = 1024 | Width and height pair. |
| `Channel` | dataclass | fields: channel_id: int = None | Handle to a Painter channel. |
| `Channel.format` | method | `format() -> ChannelFormat` | Storage format of the channel. |
| `Channel.label` | method | `label() -> str` | User-given label of a User channel (`User0` to `User31`). |
| `Channel.is_color` | method | `is_color() -> bool` | True for colour channels, False for greyscale. |
| `Channel.is_floating` | method | `is_floating() -> bool` | True for floating-point storage, False for normalised fixed point. |
| `Channel.bit_depth` | method | `bit_depth() -> int` | Number of bits in each component. |
| `Channel.type` | method | `type() -> ChannelType` | Kind of the channel. |
| `Channel.edit` | method | `edit(channel_format: ChannelFormat, label: typing.Optional[str] = None) -> None` | Changes the channel's format and label. |
| `UVTile` | class | bases: private ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.]) | Integer coordinates of a UV Tile. |
| `UVTile.u` | attribute | `u: int` | U index of the tile; public field (HTML class signature below). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.] |
| `UVTile.v` | attribute | `v: int` | V index of the tile; public field (HTML class signature below). |
| `UVTile.__init__` | constructor | `__init__(u: int, v: int, _material_id: int)` | HTML signature `UVTile(u: int, v: int, _material_id: int)` (`textureset\uvtile.html`). `_material_id` is private, not an additional public field. |
| `UVTile.name` | property | `name() -> str` | Display name of the UV Tile. |
| `UVTile.name` | property setter | `name(name: str) -> None` | Setter of the property above. |
| `UVTile.description` | property | `description() -> str` | Free-text description of the UV Tile. |
| `UVTile.description` | property setter | `description(description: str) -> None` | Setter of the property above. |
| `UVTile.get_resolution` | method | `get_resolution() -> Resolution` | The UV Tile's resolution. |
| `UVTile.set_resolution` | method | `set_resolution(new_resolution: Resolution)` | Gives the UV Tile a new resolution. |
| `UVTile.reset_resolution` | method | `reset_resolution()` | Makes the UV Tile follow its Texture Set's resolution again. |
| `UVTile.all_mesh_names` | method | `all_mesh_names() -> typing.List[str]` | Meshes that fall in the UV Tile. |
| `Stack` | dataclass | fields: stack_id: int = None | Handle to a paintable stack. |
| `Stack.from_name` | staticmethod | `from_name(texture_set_name: str, stack_name: str = '')` | Looks a stack up by Texture Set name and stack name. |
| `Stack.name` | method | `name() -> str` | The stack's name. |
| `Stack.material` | method | `material()` | Texture Set that owns this stack. |
| `Stack.all_channels` | method | `all_channels() -> typing.Dict[ChannelType, Channel]` | Every channel of the stack, by type. |
| `Stack.add_channel` | method | `add_channel(channel_type: ChannelType, channel_format: ChannelFormat, label: typing.Optional[str] = None) -> Channel` | Creates a channel in the stack. |
| `Stack.remove_channel` | method | `remove_channel(channel_type: ChannelType) -> None` | Deletes a channel from the stack. |
| `Stack.edit_channel` | method | `edit_channel(channel_type: ChannelType, channel_format: ChannelFormat, label: typing.Optional[str] = None) -> None` | Changes the format and label of one of the stack's channels. |
| `Stack.has_channel` | method | `has_channel(channel_type: ChannelType) -> bool` | True when a channel of that type exists in the stack. |
| `Stack.get_channel` | method | `get_channel(channel_type: ChannelType) -> Channel` | Existing channel of the stack, by type. |
| `TextureSet` | class | bases: private (same redaction as `UVTile`) | Handle to a Painter Texture Set. |
| `TextureSet.material_id` | attribute | `material_id: int` | Integer id of the Texture Set; public field (HTML class signature below). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.] |
| `TextureSet.__init__` | constructor | `__init__(material_id: int)` | HTML signature `TextureSet(material_id: int)` (`textureset\textureset.html`). |
| `TextureSet.from_name` | staticmethod | `from_name(texture_set_name: str)` | Looks a Texture Set up by name. |
| `TextureSet.original_name` | property | `original_name() -> str` | Name the Texture Set had at import. |
| `TextureSet.name` | property | `name() -> str` | Current name of the Texture Set. |
| `TextureSet.name` | property setter | `name(name: str) -> None` | Setter of the property above. |
| `TextureSet.description` | property | `description() -> str` | Free-text description of the Texture Set. |
| `TextureSet.description` | property setter | `description(description: str) -> None` | Setter of the property above. |
| `TextureSet.is_layered_material` | method | `is_layered_material() -> bool` | True when material layering is on for the Texture Set. |
| `TextureSet.all_stacks` | method | `all_stacks() -> typing.List[Stack]` | Every stack of the Texture Set. |
| `TextureSet.get_stack` | method | `get_stack(stack_name: str = '') -> Stack` | Looks one of the set's stacks up by name. |
| `TextureSet.get_resolution` | method | `get_resolution() -> Resolution` | The Texture Set's resolution. |
| `TextureSet.set_resolution` | method | `set_resolution(new_resolution: Resolution)` | Gives the Texture Set a new resolution. |
| `TextureSet.has_uv_tiles` | method | `has_uv_tiles() -> bool` | True when the Texture Set follows the UV Tile workflow. |
| `TextureSet.uv_tile` | method | `uv_tile(u_coord: int, v_coord: int) -> UVTile` | UV Tile at coordinates (u, v). |
| `TextureSet.all_uv_tiles` | method | `all_uv_tiles() -> typing.List[UVTile]` | Every UV Tile of the set, sorted by U and then V. |
| `TextureSet.get_uvtiles_resolution` | method | `get_uvtiles_resolution() -> typing.Dict[UVTile, Resolution]` | UV Tiles whose resolution differs from the Texture Set's, each with the resolution it actually uses. |
| `TextureSet.set_uvtiles_resolution` | method | `set_uvtiles_resolution(resolutions: typing.Dict[UVTile, Resolution])` | Gives each listed UV Tile its own resolution. |
| `TextureSet.reset_uvtiles_resolution` | method | `reset_uvtiles_resolution(uvtiles: typing.List[UVTile])` | Makes the listed UV Tiles follow the Texture Set resolution again. |
| `TextureSet.all_mesh_names` | method | `all_mesh_names() -> typing.List[str]` | Meshes that belong to the Texture Set. |
| `TextureSet.get_mesh_map_resource` | method | `get_mesh_map_resource(usage: MeshMapUsage) -> typing.Optional[substance_painter.resource.ResourceID]` | Resource used as the mesh map of a usage, if any. |
| `TextureSet.set_mesh_map_resource` | method | `set_mesh_map_resource(usage: MeshMapUsage, new_mesh_map: typing.Optional[substance_painter.resource.ResourceID]) -> None` | Replaces (or clears) the mesh map of a usage. |
| `set_resolutions` | function | `set_resolutions(texturesets: typing.List[TextureSet], new_resolution: Resolution)` | Gives several Texture Sets one resolution. |
| `all_texture_sets` | function | `all_texture_sets() -> typing.List[TextureSet]` | Every Texture Set of the open project. |
| `get_active_stack` | function | `get_active_stack() -> Stack` | Stack currently open for painting. |
| `set_active_stack` | function | `set_active_stack(stack: Stack) -> None` | Makes a stack the one open for painting. |

## `substance_painter.ui`

Qt (PySide6) UI integration: main window, docks, menus, toolbars, layouts, UI modes. Source: `resources\python\modules\substance_painter\ui.py`; HTML: `resources\python-doc\substance_painter\ui.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `UIMode` | enum (native) | Members: `Edition`, `Visualisation`, `Baking` | UI configuration (edit, visualisation, baking). |
| `ApplicationMenu` | enum (native) | Members: `File`, `Edit`, `Mode`, `Window`, `Viewport`, `Help` | Built-in menus of the application. |
| `show_main_window` | function | `show_main_window()` | Brings Painter's main window up and focuses it. |
| `get_main_window` | function | `get_main_window() -> PySide6.QtWidgets.QMainWindow` | Painter's main window as a Qt object. |
| `get_layout` | function | `get_layout(mode: UIMode) -> bytes` | Serialised dock layout of a UI mode. |
| `get_layout_mode` | function | `get_layout_mode(layout: bytes) -> UIMode` | UI mode a serialised layout belongs to. |
| `set_layout` | function | `set_layout(layout: bytes) -> UIMode` | Restores a layout saved with `get_layout`. |
| `reset_layout` | function | `reset_layout(mode: UIMode)` | Restores the default layout of a UI mode. |
| `add_dock_widget` | function | `add_dock_widget(widget: PySide6.QtWidgets.QWidget, ui_modes: int = UIMode.Edition) -> PySide6.QtWidgets.QDockWidget` | Docks a Qt widget into the main window. |
| `add_plugins_toolbar_widget` | function | `add_plugins_toolbar_widget(widget: PySide6.QtWidgets.QWidget)` | Places a Qt widget on the plugins toolbar. |
| `add_menu` | function | `add_menu(menu: PySide6.QtWidgets.QMenu)` | Adds a Qt menu to the main window. |
| `add_toolbar` | function | `add_toolbar(title: str, object_name: str, ui_modes: int = UIMode.Edition) -> PySide6.QtWidgets.QToolBar` | Creates a toolbar in the main window and returns it. |
| `add_action` | function | `add_action(menu: ApplicationMenu, action: PySide6.QtGui.QAction)` | Appends a Qt action to one of the application menus. |
| `delete_ui_element` | function | `delete_ui_element(element: PySide6.QtWidgets.QWidget)` | Removes a UI element. |
| `get_current_mode` | function | `get_current_mode() -> UIMode` | Active UI mode. |
| `switch_to_mode` | function | `switch_to_mode(mode: UIMode) -> None` | Changes the active UI mode. |

## `substance_painter_plugins`

Plugin discovery/start/stop/reload (separate top-level module). Source: `resources\python\modules\substance_painter_plugins.py`; HTML: `resources\python-doc\plugins\substance_painter_plugins.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `path` | attribute | = [] | Folders searched for plugins (list of strings). |
| `plugins` | attribute | = {} | Plugins currently running (dict). |
| `start_plugin` | function | `start_plugin(module)` | Starts a plugin module. |
| `close_plugin` | function | `close_plugin(module, gc_collect = True)` | Stops a plugin module. |
| `is_plugin_started` | function | `is_plugin_started(module)` | True when the plugin is running. |
| `reload_plugin` | function | `reload_plugin(module)` | Reloads a plugin module and starts it again. |
| `startup_module_names` | function | `startup_module_names()` | Names of the startup modules that can be loaded. |
| `plugin_module_names` | function | `plugin_module_names()` | Names of the available plugin modules. |
| `load_startup_modules` | function | `load_startup_modules()` | Loads every startup module. |
| `close_all_plugins` | function | `close_all_plugins()` | Stops every running plugin. |
| `update_sys_path` | function | `update_sys_path()` | Brings `sys.path` in line with `substance_painter_plugins.path` and the `SUBSTANCE_PAINTER_PLUGINS_PATH` variable. |
