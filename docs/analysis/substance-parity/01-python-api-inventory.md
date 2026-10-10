# 01 — Substance 3D Painter Python API inventory (as of 2026-10-10)

Module-by-module inventory of every public symbol of the Python API shipped with the Adobe Substance 3D Painter install on this machine. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`. Paths below are relative to `PAINTER` unless they start with a drive letter.
- Labels: **Fact** = stated in, or computed this session from, the cited source; **Hypothesis** = inferred, not confirmed; **Recommendation** = ours. "Not confirmed" marks gaps.
- Method used to build the tables (**Fact**): every `.py` file of the shipped package `resources\python\modules\substance_painter\` (and `resources\python\modules\substance_painter_plugins.py`) was parsed with Python's `ast` module (no import, no execution). Every public (non-underscore) module-level function, class, dataclass field, method, property and native enum was extracted; signatures are the source annotations verbatim. Enum members of native enums come from the shipped docstrings and match the HTML member lists; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\substance_painter\_utility.py.] The result was cross-checked against every symbol anchor in the shipped HTML docs (`resources\python-doc\**\*.html`): all documented symbols are present in the source. Differences: the HTML lists inherited members under the concrete classes (mixin members under `FillLayerNode`/`FillEffectNode`, `uid()` under nodes and sources, enum members of `ReloadMeshStatus`, fields of `ResourceID`); the source additionally contains symbols without their own HTML entry — the mixin classes (`FillParamsEditorMixin`, `ActiveChannelsMixin`, `SourceEditorMixin`), the iterator classes of `OutputMapping`/`ChannelMapping`, type aliases (`ColorColorSpace`, `ResourceColorSpace`, `GeometryMaskParams`, `AutoUnwrapUVTilesSettings`, `PropertyValue`, `ReloadResourcesFilter`, `Source`), the deprecated `usd_settings` properties and the `logging` severity constants (described in prose in the HTML).
- "Purpose" is the first sentence of the docstring (lightly cleaned). Deprecations are taken from the docstrings and from the API changelog in `resources\python-doc\index.html`.
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
| 3 | Paint strokes are not accessible from Python ("Strokes are not accessible from the Python API"). | Fact | `resources\python-doc\substance_painter\layerstack\layereffect\paint.html` (PaintLayerNode, PaintEffectNode) |
| 4 | Layer-stack editing requires an open project in edition state; the entry point is `layerstack.get_root_layer_nodes()`. | Fact | `resources\python-doc\substance_painter\layerstack\index.html` |
| 5 | Long operations are asynchronous and event-driven: `project.create/open` (finish with `event.ProjectEditionEntered`), `baking.bake_async` (finish with `event.BakingProcessEnded`), `project.reload_mesh` (callback), `resource.reload_modified_resources_async` (`event.ReloadResourcesEnded`), shelf crawling (`event.ShelfCrawlingEnded`). | Fact | `project.html` → Events; `baking.html`; `resource.html` → Resource crawling / Resource reloading |
| 6 | Remote scripting: the MCP bridge talks to Painter started with `--enable-remote-scripting`, which listens on `localhost:60041` and accepts `POST /run.json` with `{"python": <base64>}` or `{"js": <base64>}`. Not described in the shipped Python HTML docs. | Fact (bridge code); not confirmed in Adobe docs | `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\README.md` → "Start Painter with remote scripting"; `...\src\substance_painter_mcp\client.py` (`route = "/run.json"`) |
| 7 | Plugins: a plugin is a standard Python module on `substance_painter_plugins.path` (initialised from `SUBSTANCE_PAINTER_PLUGINS_PATH`, the install dir and the user resources dir); each plugin dir has `plugins/`, `startup/`, `modules/`; plugin modules expose `start_plugin()`/`close_plugin()`. | Fact | `resources\python-doc\plugins\substance_painter_plugins.html` (`path`) |
| 8 | Adobe's shipped test suites call private `_substance_painter.*` functions that are not part of the public API. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\engine_tests\; resources\python\modules\automated_tests\.] Independently of those tests, the Assets3D pipeline uses the private viewport capture `_substance_painter.display.save_viewport`. | Fact; stability not confirmed | test directories (paths only); `E:\UzmiGames\Assets3D\Docs\Pipeline\Licoes\operacao-projeto-captura-reais.md` |
| 9 | `layerstack.get_node_by_uid` is annotated as returning `List[...]` (public signature) but returns a single node. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\layerstack.py.] | Fact | `resources\python-doc\substance_painter\layerstack\navigation.html` (signature) |
| 10 | The shipped Adobe test suites (`resources\python\modules\automated_tests\`, `engine_tests\`) are the richest usage examples for baking, export, layer stack and project creation and are reused as sources in files 02–05. | Fact | directory listing |

## 4. Symbol tables

Each section lists every public symbol of one module. Kind values: `function`, `class`, `dataclass`, `enum` (Python `enum.Enum`), `enum (native)` (C++ enum exposed by the native module; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\_utility.py.]), `exception (native)`, `method`, `staticmethod`, `classmethod`, `constructor`, `property`, `property setter`, `type alias`, `attribute`, `note` (added rows that document inherited/dunder behaviour).

## `substance_painter.application`

Application-level version query, engine-computation toggle and application close. Source: `resources\python\modules\substance_painter\application.py`; HTML: `resources\python-doc\substance_painter\application.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `version_info` | function | `version_info() -> Tuple[int, int, int]` | Get the version_info of Substance 3D Painter. |
| `version` | function | `version() -> str` | Get the version of Substance 3D Painter. |
| `engine_computations_status` | function | `engine_computations_status() -> bool` | Check whether engine computations are enabled. |
| `enable_engine_computations` | function | `enable_engine_computations(enable: bool)` | Enable or disable engine computations. |
| `disable_engine_computations` | function | `disable_engine_computations()` | Context manager to disable engine computations. |
| `close` | function | `close()` | Close Susbtance 3D Painter. |

## `substance_painter.async_utils`

Cancellation handle returned by asynchronous calls (baking). Source: `resources\python\modules\substance_painter\async_utils.py`; HTML: `resources\python-doc\substance_painter\async_utils.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `StopSource` | dataclass | fields: stop_source: _substance_painter.async_utils.StopSource | An object that can be used to cancel an asynchronous computation. |
| `StopSource.request_stop` | method | `request_stop() -> bool` | Makes a top request. |
| `StopSource.stop_requested` | method | `stop_requested() -> bool` | Check if a stop request as been made. |

## `substance_painter.baking`

Per-Texture-Set baking configuration (dynamic `Property` bags), baker enablement, UV-tile selection, link groups, asynchronous bake launch. Source: `resources\python\modules\substance_painter\baking.py`; HTML: `resources\python-doc\substance_painter\baking.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `BakingStatus` | enum (native) | Members: `Success`, `Cancel`, `Fail` | Status code of the baking process. |
| `CurvatureMethod` | enum (native) | Members: `FromMesh`, `FromNormalMap` | Enumeration. |
| `BakingParameters` | dataclass | fields: material_id: int | Baking parameters for a given texture set. |
| `BakingParameters.from_texture_set` | staticmethod | `from_texture_set(texture_set: TextureSet) -> 'BakingParameters'` | Get the baking parameters for the given texture set object. |
| `BakingParameters.from_texture_set_name` | staticmethod | `from_texture_set_name(texture_set_name: str) -> 'BakingParameters'` | Get the baking parameters for the given texture set name. |
| `BakingParameters.texture_set` | method | `texture_set() -> TextureSet` | Get the associated texture set. |
| `BakingParameters.common` | method | `common() -> Dict[str, Property]` | Get the parameters common to all bakers, like baking resolution. |
| `BakingParameters.baker` | method | `baker(baked_map: MeshMapUsage) -> Dict[str, Property]` | Get the parameters specific to a given baked map. |
| `BakingParameters.set` | staticmethod | `set(property_values: Dict[Property, PropertyValue]) -> None` | Set property values in batch. |
| `BakingParameters.get_curvature_method` | method | `get_curvature_method() -> CurvatureMethod` | Get the curvature method used for baking |
| `BakingParameters.set_curvature_method` | method | `set_curvature_method(method: CurvatureMethod)` | Set the curvature method to use for baking |
| `BakingParameters.is_baker_enabled` | method | `is_baker_enabled(usage: MeshMapUsage) -> bool` | Whether some usage is enabled for baking. |
| `BakingParameters.set_baker_enabled` | method | `set_baker_enabled(usage: MeshMapUsage, enable: bool) -> None` | Enable or disable a usage for baking. |
| `BakingParameters.get_enabled_bakers` | method | `get_enabled_bakers() -> List[MeshMapUsage]` | Get all usages enabled for baking. |
| `BakingParameters.set_enabled_bakers` | method | `set_enabled_bakers(enabled_usages: List[MeshMapUsage]) -> None` | Set usages enabled for baking. |
| `BakingParameters.is_textureset_enabled` | method | `is_textureset_enabled() -> bool` | Whether this Texture Set is enabled for baking. |
| `BakingParameters.set_textureset_enabled` | method | `set_textureset_enabled(enable: bool) -> None` | Enable or disable this Texture Set for baking. |
| `BakingParameters.is_uv_tile_enabled` | method | `is_uv_tile_enabled(uv_tile: UVTile) -> bool` | Whether a UV Tile is enabled for baking. |
| `BakingParameters.set_uv_tile_enabled` | method | `set_uv_tile_enabled(uv_tile: UVTile, enable: bool) -> None` | Enable or disable an UV Tile for baking. |
| `BakingParameters.get_enabled_uv_tiles` | method | `get_enabled_uv_tiles() -> List[UVTile]` | Get all UV Tiles enabled for baking. |
| `BakingParameters.set_enabled_uv_tiles` | method | `set_enabled_uv_tiles(enabled_uv_tiles: List[UVTile]) -> None` | Set UV Tiles enabled for baking. |
| `set_linked_group` | function | `set_linked_group(group: List[TextureSet], reference: TextureSet, usage: MeshMapUsage) -> None` | Make a group of Texture Sets share the same baking parameters for the given 'usage'. |
| `set_linked_group_common_parameters` | function | `set_linked_group_common_parameters(group: List[TextureSet], reference: TextureSet) -> None` | Make a group of Texture Sets share the same baking common parameters. |
| `unlink_all` | function | `unlink_all(usage: MeshMapUsage) -> None` | Unlink all Texture Sets for a given usage. |
| `unlink_all_common_parameters` | function | `unlink_all_common_parameters() -> None` | Unlink all Texture Sets for common parameters. |
| `get_link_group` | function | `get_link_group(usage: MeshMapUsage) -> List[TextureSet]` | Get the list of Texture Sets that share baking parameters for a given usage. |
| `get_link_group_common_parameters` | function | `get_link_group_common_parameters() -> List[TextureSet]` | Get the list of Texture Sets that share common baking parameters. |
| `get_linked_texture_sets` | function | `get_linked_texture_sets(texture_set: TextureSet, usage: MeshMapUsage) -> List[TextureSet]` | Get the list of Texture Sets that share the same parameters as some Texture Set, for a given usage. |
| `get_linked_texture_sets_common_parameters` | function | `get_linked_texture_sets_common_parameters(texture_set: TextureSet) -> List[TextureSet]` | Get the list of Texture Sets that share the same parameters as some Texture Set, for common parameters. |
| `bake_async` | function | `bake_async(texture_set: TextureSet) -> StopSource` | Launch the baking process for a Texture Set, using the current baking configuration. |
| `bake_selected_textures_async` | function | `bake_selected_textures_async() -> StopSource` | Launch the baking process, using the current baking configuration. |

## `substance_painter.colormanagement`

Color value type with explicit color space; color-space enums used by sources. Source: `resources\python\modules\substance_painter\colormanagement.py`; HTML: `resources\python-doc\substance_painter\colormanagement.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `GenericColorSpace` | enum | Members: `sRGB`, `Working`, `Raw` | Generic color spaces valid with any color space engine used. |
| `LegacyColorSpace` | enum | Members: `Linear`, `sRGB` | Legacy color spaces. |
| `DataColorSpace` | enum | Members: `Data`, `DataSigned` | Data color spaces. |
| `NormalColorSpace` | enum | Members: `NormalXYZRight`, `NormalXYZLeft` | Normal color spaces. |
| `ColorColorSpace` | type alias | = Union[GenericColorSpace, str] |  |
| `ResourceColorSpace` | type alias | = Union[GenericColorSpace, LegacyColorSpace, DataColorSpace, NormalColorSpace, str] |  |
| `Color` | class | fields: value_raw: Tuple[float, float, float]; color_space: ColorColorSpace | Describe a color (with a color space). |
| `Color.__init__` | constructor | `__init__(r: float, g: float, b: float, color_space: ColorColorSpace = None)` | Color constructor |
| `Color.convert` | method | `convert(color_space: ColorColorSpace) -> Tuple[float, float, float]` | Get r,g,b values encoded in the given color space |
| `Color.value` | property | `value() -> Tuple[float, float, float]` | color value |
| `Color.sRGB` | property | `sRGB() -> Tuple[float, float, float]` | color value in sRGB space |
| `Color.sRGB` | property setter | `sRGB(value: Tuple[float, float, float]) -> None` | Setter of the property above. |
| `Color.working` | property | `working() -> Tuple[float, float, float]` | color value in working space |
| `Color.working` | property setter | `working(value: Tuple[float, float, float]) -> None` | Setter of the property above. |

## `substance_painter.display`

Viewport/display settings of the project: environment map, color LUT, tone mapping, camera. Source: `resources\python\modules\substance_painter\display.py`; HTML: `resources\python-doc\substance_painter\display.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ToneMappingFunction` | enum (native) | Members: `Linear`, `ACES` | Tone mapping function used in display. |
| `get_environment_resource` | function | `get_environment_resource() -> typing.Optional[substance_painter.resource.ResourceID]` | Get the environment map resource of the active project. |
| `set_environment_resource` | function | `set_environment_resource(new_env_map: substance_painter.resource.ResourceID) -> None` | Set the environment map resource of the active project. |
| `get_color_lut_resource` | function | `get_color_lut_resource() -> typing.Optional[substance_painter.resource.ResourceID]` | Get the color profile LUT resource of the active project. |
| `set_color_lut_resource` | function | `set_color_lut_resource(new_color_lut: substance_painter.resource.ResourceID) -> None` | Set the color profile LUT resource of the active project. |
| `get_tone_mapping` | function | `get_tone_mapping() -> ToneMappingFunction` | Get the tone mapping operator used to display the current project. |
| `set_tone_mapping` | function | `set_tone_mapping(new_tone_mapping: ToneMappingFunction) -> None` | Set the tone mapping operator to display the current project. |
| `CameraProjectionType` | enum (native) | Members: `Perspective`, `Orthographic` | Camera projection type. |
| `Camera` | dataclass | fields: _camera_id: int | Allows the manipulation of the properties of an existing Camera. |
| `Camera.get_default_camera` | staticmethod | `get_default_camera() -> Camera` | Get the default camera. |
| `Camera.position` | property | `position() -> List[float]` | The position (x,y,z) of the camera. |
| `Camera.position` | property setter | `position(position: List[float]) -> None` | Setter of the property above. |
| `Camera.rotation` | property | `rotation() -> List[float]` | The rotation (x,y,z) of the camera as Euler angles in degrees. |
| `Camera.rotation` | property setter | `rotation(rotation: List[float]) -> None` | Setter of the property above. |
| `Camera.field_of_view` | property | `field_of_view() -> float` | The field of view of the camera in degrees. |
| `Camera.field_of_view` | property setter | `field_of_view(fov: float) -> None` | Setter of the property above. |
| `Camera.focal_length` | property | `focal_length() -> float` | The focal length of the camera in mm. |
| `Camera.focal_length` | property setter | `focal_length(focal_length: float) -> None` | Setter of the property above. |
| `Camera.focus_distance` | property | `focus_distance() -> float` | The focus distance of the camera. |
| `Camera.focus_distance` | property setter | `focus_distance(focus_distance: float) -> None` | Setter of the property above. |
| `Camera.aperture` | property | `aperture() -> float` | The aperture of the camera. |
| `Camera.aperture` | property setter | `aperture(aperture: float) -> None` | Setter of the property above. |
| `Camera.orthographic_height` | property | `orthographic_height() -> float` | The orthographic height of the camera. |
| `Camera.orthographic_height` | property setter | `orthographic_height(orthographic_height: float) -> None` | Setter of the property above. |
| `Camera.projection_type` | property | `projection_type() -> CameraProjectionType` | The projection type (perspective or orthographic) of the camera. |
| `Camera.projection_type` | property setter | `projection_type(projection_type: CameraProjectionType) -> None` | Setter of the property above. |

## `substance_painter.event`

Event classes and the global dispatcher used to observe project, export, baking, shelf, texture and camera events. Source: `resources\python\modules\substance_painter\event.py`; HTML: `resources\python-doc\substance_painter\event.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `Event` | dataclass | — | Base event class. |
| `ProjectOpened` | dataclass | bases (Event) | Event triggered when an existing project has been opened. |
| `ProjectCreated` | dataclass | bases (Event) | Event triggered when a new project has been created. |
| `ProjectAboutToClose` | dataclass | bases (Event) | Event triggered just before closing the current project. |
| `ProjectClosed` | dataclass | bases (Event) | Event triggered just before closing the current project. |
| `ProjectAboutToSave` | dataclass | bases (Event) — fields: file_path: str | Event triggered just before saving the current project. |
| `ProjectSaved` | dataclass | bases (Event) | Event triggered once the current project is saved. |
| `ExportTexturesAboutToStart` | dataclass | bases (Event) — fields: textures: Dict[Tuple[str, str], List[str]] | Event triggered just before a textures export. |
| `ExportTexturesEnded` | dataclass | bases (Event) — fields: status: ExportStatus; message: str; textures: Dict[Tuple[str, str], List[str]] | Event triggered after textures export is finished. |
| `ShelfCrawlingStarted` | dataclass | bases (Event) — fields: shelf_name: str | Event triggered when a shelf starts reading the file system to discover new resources. |
| `ShelfCrawlingEnded` | dataclass | bases (Event) — fields: shelf_name: str | Event triggered when a shelf has finished discovering new resources and loading their thumbnails. |
| `ProjectEditionEntered` | dataclass | bases (Event) | Event triggered when the project is fully loaded and ready to work with. |
| `ProjectEditionLeft` | dataclass | bases (Event) | Event triggered when the current project can non longer be edited. |
| `BusyStatusChanged` | dataclass | bases (Event) — fields: busy: bool | Event triggered when Substance 3D Painter busy state changed. |
| `BakingProcessAboutToStart` | dataclass | bases (Event) — fields: stop_source: StopSource | Event triggered when a baking is about to start. |
| `BakingProcessProgress` | dataclass | bases (Event) — fields: progress: float | Event triggered when baking process progress changes. |
| `BakingProcessEnded` | dataclass | bases (Event) — fields: status: BakingStatus | Event triggered after baking is finished. |
| `LayerStacksModelDataChanged` | dataclass | bases (Event) | Event triggered whenever the status of the Layer Stacks changes. |
| `EngineComputationsStatusChanged` | dataclass | bases (Event) — fields: engine_computations_enabled: bool | Event triggered whenever the status of the engine computations changes. |
| `GraphicalUserInterfaceStarted` | dataclass | bases (Event) | Event triggered when the GUI has finished to initialize itself. |
| `TextureStateEventAction` | enum (native) | Members: `ADD`, `UPDATE`, `REMOVE` | The TextureStateEvent possible actions. |
| `TextureStateEvent` | dataclass | bases (Event) — fields: action: TextureStateEventAction; stack_id: int; tile_indices: Tuple[int, int]; channel_type: ChannelType; cache_key: int | Event triggered when a document texture is added, removed or updated. |
| `TextureStateEvent.cache_key_invalidation_throttling_period` | staticmethod | `cache_key_invalidation_throttling_period() -> datetime.timedelta` | Get the minimum duration between two texture update events (for a given texture). |
| `TextureStateEvent.set_cache_key_invalidation_throttling_period` | staticmethod | `set_cache_key_invalidation_throttling_period(period: datetime.timedelta) -> None` | Set the minimum duration between two texture update events (for a given texture). |
| `CameraPropertiesChanged` | dataclass | bases (Event) — fields: camera_id: int | Event triggered when the camera properties change. |
| `ReloadResourcesStarted` | dataclass | bases (Event) — fields: filter: ReloadResourcesFilter | Event triggered when a resource reload operation has started. |
| `ReloadedResourceResult` | dataclass | fields: old_resource_id: ResourceID; new_resource_id: ResourceID | Per resource result of a successful resource reload operation. |
| `ReloadedResourceError` | dataclass | fields: resource_id: ResourceID; error_msg: str | Per resource result of an unsuccessful resource reload operation. |
| `ReloadResourcesEnded` | dataclass | bases (Event) — fields: filter: ReloadResourcesFilter; reloaded_resources: List[ReloadedResourceResult]; resource_errors: List[ReloadedResourceError] | Event triggered when a resource reload operation has completed. |
| `Dispatcher` | class | — | The Event Dispatcher. |
| `Dispatcher.__init__` | constructor | `__init__()` |  |
| `Dispatcher.connect` | method | `connect(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Connect a callback to handle the given event type. |
| `Dispatcher.connect_strong` | method | `connect_strong(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Connect a callback to handle the given event type. |
| `Dispatcher.disconnect` | method | `disconnect(event_cls: Type[Event], callback: Callable[[Event], Any]) -> None` | Disconnect a previously connected callback. |
| `DISPATCHER` | attribute | = Dispatcher() | The event dispatcher instance that will be used by the application. |

## `substance_painter.exception`

Painter-specific exceptions (native objects). Source: `resources\python\modules\substance_painter\exception.py`; HTML: `resources\python-doc\substance_painter\exception.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ProjectError` | exception (native) | native object | Raised when an operation or function is incompatible with the current project, or when the current state of the project is invalid. |
| `ServiceNotFoundError` | exception (native) | native object | Raised when an operation or function relies on a service which could not be found. |
| `ResourceNotFoundError` | exception (native) | native object | Raised when a Substance 3D Painter resource could not be found. |

## `substance_painter.export`

Texture export driven by a JSON configuration, export-preset listing, mesh export. Source: `resources\python\modules\substance_painter\export.py`; HTML: `resources\python-doc\substance_painter\export.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ExportStatus` | enum (native) | Members: `Success`, `Cancelled`, `Warning`, `Error` | Status code of the export process. |
| `list_project_textures` | function | `list_project_textures(json_config: dict) -> Dict[Tuple[str, str], List[str]]` | Get list of textures that would be exported according to the given JSON configuration. |
| `TextureExportResult` | dataclass | fields: status: ExportStatus; message: str; textures: Dict[Tuple[str, str], List[str]] | Result of the export textures process |
| `export_project_textures` | function | `export_project_textures(json_config: dict) -> TextureExportResult` | Export document textures according to the given JSON configuration. |
| `get_default_export_path` | function | `get_default_export_path() -> str` | Get the application default export path used for exporting textures. |
| `PredefinedExportPreset` | dataclass | fields: name: str; url: str | An export preset (output template) controls the behavior of the export process. |
| `PredefinedExportPreset.list_output_maps` | method | `list_output_maps(stack: substance_painter.textureset.Stack) -> list` | Get the list of output maps based on the channels available on the given stack. |
| `list_predefined_export_presets` | function | `list_predefined_export_presets() -> List[PredefinedExportPreset]` | Get the list of predefined export presets (output templates). |
| `ResourceExportPreset` | dataclass | fields: resource_id: substance_painter.resource.ResourceID | An export preset (output template) controls the behavior of the export process. |
| `ResourceExportPreset.list_output_maps` | method | `list_output_maps() -> list` | Get the list of output maps for the given preset. |
| `list_resource_export_presets` | function | `list_resource_export_presets() -> List[ResourceExportPreset]` | Get the list of export presets (output templates). |
| `MeshExportOption` | enum (native) | Members: `BaseMesh`, `TriangulatedMesh`, `TessellationNormalsBaseMesh`, `TessellationRecomputeNormals` | Options available for the mesh export. |
| `scene_is_triangulated` | function | `scene_is_triangulated() -> bool` | Check if the scene has only triangles (polygons with only 3 sides). |
| `scene_has_tessellation` | function | `scene_has_tessellation() -> bool` | Check if the scene has displacement/tessellation enabled. |
| `MeshExportResult` | dataclass | fields: status: ExportStatus; message: str | Result of the export mesh process |
| `export_mesh` | function | `export_mesh(file_path: str, option: MeshExportOption) -> MeshExportResult` | Export the current mesh to the given file path. |

## `substance_painter.js`

Bridge to the legacy embedded JavaScript API (`alg.*`). Source: `resources\python\modules\substance_painter\js.py`; HTML: `resources\python-doc\substance_painter\js.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `evaluate` | function | `evaluate(js_code: str) -> str` | Evaluate a JavaScript expression. |

## `substance_painter.layerstack`

Layer stack navigation, insertion, deletion, selection, masks, blending, geometry masks, projections, symmetry, smart materials/masks. Source: `resources\python\modules\substance_painter\layerstack.py`; HTML: `resources\python-doc\substance_painter\layerstack\*.html and layerstack\layereffect\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `BlendingMode` | enum (native) | Members: `Normal`, `PassThrough`, `Disable`, `Replace`, `Multiply`, `Divide`, `InverseDivide`, `Darken`, `Lighten`, `LinearDodge`, `Subtract`, `InverseSubtract`, `Difference`, `Exclusion`, `SignedAddition`, `Overlay`, `Screen`, `LinearBurn`, `ColorBurn`, `ColorDodge`, `SoftLight`, `HardLight`, `VividLight`, `LinearLight`, `PinLight`, `Tint`, `Saturation`, `Color`, `Value`, `NormalMapCombine`, `NormalMapDetail`, `NormalMapInverseDetail` | Blending Modes allow to mix the result of a layer with the other layers below in different manners. |
| `NodeType` | enum (native) | Members: `PaintLayer`, `PaintEffect`, `FillLayer`, `FillEffect`, `GeneratorEffect`, `FilterEffect`, `LevelsEffect`, `CompareMaskEffect`, `ColorSelectionEffect`, `GroupLayer`, `InstanceLayer`, `AnchorPointEffect` | For more information about layers and effects, see :ref:`layerstack_layers_effects`. |
| `NodeStack` | enum | Members: `Substack`, `Content`, `Mask` | Indicate which node stack you want to insert in. |
| `MaskBackground` | enum (native) | Members: `Black`, `White` | Enumeration. |
| `ColorSelectionBackgroundColor` | enum (native) | Members: `Transparent`, `Black`, `White`, `Gray` | Enumeration. |
| `GeometryMaskType` | enum (native) | Members: `Mesh`, `UVTile` | Enumeration. |
| `GeometryMaskMeshParams` | dataclass | fields: inclusion_list: bool = True; meshes: List[str] = dataclasses.field(default_factory=list) | Geometry mask mesh names parameters. |
| `GeometryMaskUVTilesParams` | dataclass | fields: inclusion_list: bool = True; uv_tiles: List[UVTile] = dataclasses.field(default_factory=list) | Geometry mask UV Tiles parameters. |
| `GeometryMaskParams` | type alias | = Union[GeometryMaskMeshParams, GeometryMaskUVTilesParams] |  |
| `ProjectionMode` | enum (native) | Members: `Fill`, `UV`, `Triplanar`, `Planar`, `Spherical`, `Cylindrical`, `Warp`, `UVSetToUVSet` | See `Fill projections documentation`_ for a complete description of all Projection modes. |
| `is_3d_projection_mode` | function | `is_3d_projection_mode(projection_mode: ProjectionMode) -> bool` | Check if the projection mode is a 3D projection. |
| `FilteringMode` | enum (native) | Members: `BilinearHQ`, `BilinearSharp`, `Nearest` | Enumeration. |
| `UVWrapMode` | enum (native) | Members: `RepeatNone`, `RepeatHorizontally`, `RepeatVertically`, `Repeat` | Enumeration. |
| `ShapeCropMode` | enum (native) | Members: `CroppedToShape`, `ExtendsOutsideShape` | Enumeration. |
| `ScaleMode` | enum (native) | Members: `Factors`, `MaterialPhysicalSize`, `CustomPhysicalSize` | Enumeration. |
| `CompareMaskEffectOperand` | enum (native) | Members: `LayersBelow`, `ThisLayer`, `ThisMask`, `Constant` | See `Compare Mask effect documentation`_ for a complete description of the compare mask effect. |
| `CompareMaskEffectOperation` | enum (native) | Members: `LesserThan`, `WithinTolerance`, `GreaterThan` | Enumeration. |
| `SelectionType` | enum (native) | Members: `Content`, `Mask`, `GeometryMask`, `Properties` | Enumeration. |
| `SymmetryAxis` | enum (native) | Members: `X`, `Y`, `Z` | Enumeration. |
| `SymmetryMode` | enum (native) | Members: `Mirror`, `Radial` | Symmetry (Mirror or Radial) is only applied when a 3D projection mode is set on a Fill Layer. |
| `ScopedModification` | class | — | ScopedModification can be used to group many layerstack modification calls in a single undoable command. |
| `ScopedModification.__init__` | constructor | `__init__(name)` |  |
| `FillParamsEditorMixin` | class | — | A mixin allowing manipulation of this fill parameters. Docstring marks it `:meta private:` (`layerstack.py:518–523`): implementation helper, not supported public API; its members are public through `FillLayerNode`/`FillEffectNode`. |
| `FillParamsEditorMixin.get_projection_mode` | method | `get_projection_mode() -> ProjectionMode` | Get the current projection mode. |
| `FillParamsEditorMixin.set_projection_mode` | method | `set_projection_mode(projection_mode: ProjectionMode)` | Switch to a new projection mode. |
| `FillParamsEditorMixin.get_projection_parameters` | method | `get_projection_parameters() -> ProjectionParams \| None` | Get the current projection parameters. |
| `FillParamsEditorMixin.set_projection_parameters` | method | `set_projection_parameters(projection_parameters: ProjectionParams)` | Set projection parameters and update the current projection mode accordingly. |
| `FillParamsEditorMixin.is_symmetry_enabled` | method | `is_symmetry_enabled() -> bool` | Check if symmetry is enabled. |
| `FillParamsEditorMixin.set_symmetry_enabled` | method | `set_symmetry_enabled(enabled: bool)` | Set the symmetry enabled state. |
| `FillParamsEditorMixin.get_symmetry_parameters` | method | `get_symmetry_parameters() -> SymmetryParams` | Get the current symmetry parameters. |
| `FillParamsEditorMixin.set_symmetry_parameters` | method | `set_symmetry_parameters(symmetry_parameters: SymmetryParams)` | Set the symmetry parameters and update the current symmetry mode accordingly. |
| `Node` | class | bases (ReadOnlyUid) | Abstract class to manipulate common properties of a layer stack node. |
| `Node.get_type` | method | `get_type() -> NodeType` | Check the type of the node. |
| `Node.get_texture_set` | method | `get_texture_set() -> TextureSet` | Get the TextureSet this node belongs to. |
| `Node.is_visible` | method | `is_visible() -> bool` | Check whether this node is rendered. |
| `Node.set_visible` | method | `set_visible(visible: bool)` | Enable this node for rendering. |
| `Node.get_name` | method | `get_name() -> str` | Get the name assigned to this Node. |
| `Node.set_name` | method | `set_name(name: str)` | Change this node name. |
| `Node.is_in_mask_stack` | method | `is_in_mask_stack() -> bool` | Check whether this node is part of a mask stack. |
| `Node.has_blending` | method | `has_blending() -> bool` | Check whether this node supports blending information (blending mode + opacity). |
| `Node.get_blending_mode` | method | `get_blending_mode(channel: Optional[ChannelType] = None) -> BlendingMode` | Get the blending mode for a Node. |
| `Node.set_blending_mode` | method | `set_blending_mode(blending_mode: BlendingMode, channel: Optional[ChannelType] = None)` | Set the blending mode for a Node. |
| `Node.get_opacity` | method | `get_opacity(channel: Optional[ChannelType] = None) -> float` | Get the opacity for a Node. |
| `Node.set_opacity` | method | `set_opacity(opacity: float, channel: Optional[ChannelType] = None)` | Set the opacity for a node. |
| `Node.get_stack` | method | `get_stack() -> Stack` | Get the stack that contains this node. |
| `Node.get_parent` | method | `get_parent() -> Node` | Get the parent of this node. |
| `Node.get_next_sibling` | method | `get_next_sibling() -> Node` | Get the next sibling of this node. |
| `Node.get_previous_sibling` | method | `get_previous_sibling() -> Node` | Get the previous sibling of this node. |
| `LayerNode` | class | bases (Node) | A Node that is part of the main hierarchy. |
| `LayerNode.content_effects` | method | `content_effects() -> List[EffectNode]` | Query the content effects of this node, ordered like in the layer stack. |
| `LayerNode.mask_effects` | method | `mask_effects() -> List[EffectNode]` | Query the mask effects of this node, ordered like in the layer stack. |
| `LayerNode.instances` | method | `instances() -> List[LayerNode]` | Return the list of instances of this layer. |
| `LayerNode.get_geometry_mask_type` | method | `get_geometry_mask_type() -> GeometryMaskType` | Query the geometry mask type currently applied to this node. |
| `LayerNode.set_geometry_mask_type` | method | `set_geometry_mask_type(geometry_mask_type: GeometryMaskType)` | Set the geometry mask type to apply to this node. **Deprecated since 0.3.7 (use set_geometry_mask).** |
| `LayerNode.get_geometry_mask_enabled_meshes` | method | `get_geometry_mask_enabled_meshes() -> List[str]` | Get the list of enabled meshes for the geometry mask. |
| `LayerNode.set_geometry_mask_enabled_meshes` | method | `set_geometry_mask_enabled_meshes(mesh_names: List[str])` | Set the list of enabled meshes for the geometry mask. **Deprecated since 0.3.7 (use set_geometry_mask).** |
| `LayerNode.get_geometry_mask_enabled_uv_tiles` | method | `get_geometry_mask_enabled_uv_tiles() -> List[UVTile]` | Get the list of enabled UV Tiles for the geometry mask. |
| `LayerNode.set_geometry_mask_enabled_uv_tiles` | method | `set_geometry_mask_enabled_uv_tiles(uv_tiles: List[UVTile])` | Set the list of enabled UV Tiles for the geometry mask. **Deprecated since 0.3.7 (use set_geometry_mask).** |
| `LayerNode.get_geometry_mask` | method | `get_geometry_mask() -> GeometryMaskParams` | Get geometry mask current settings. |
| `LayerNode.set_geometry_mask` | method | `set_geometry_mask(params: GeometryMaskParams)` | Set geometry mask settings. |
| `LayerNode.has_mask` | method | `has_mask() -> bool` | Check whether this node has a mask. |
| `LayerNode.add_mask` | method | `add_mask(background: MaskBackground)` | Add a mask on this node with the specified background. |
| `LayerNode.remove_mask` | method | `remove_mask()` | Remove this node mask, including all its effects. |
| `LayerNode.get_mask_background` | method | `get_mask_background() -> MaskBackground` | Query the type of mask used by this node. |
| `LayerNode.set_mask_background` | method | `set_mask_background(background: MaskBackground)` | Set the mask background on this node. |
| `LayerNode.is_mask_enabled` | method | `is_mask_enabled() -> bool` | Query whether the mask is currently enabled. |
| `LayerNode.enable_mask` | method | `enable_mask(enabled: bool)` | Set whether the mask is currently enabled. |
| `GroupLayerNode` | class | bases (LayerNode) | A node allowing manipulation of a Group layer of the Layer Stack. |
| `GroupLayerNode.sub_layers` | method | `sub_layers() -> List[LayerNode]` | Query sub layers of this node. |
| `GroupLayerNode.is_collapsed` | method | `is_collapsed() -> bool` | Query if the group is in collapsed state. |
| `GroupLayerNode.set_collapsed` | method | `set_collapsed(collapsed: bool)` | Set the collapsed state of the group. |
| `PaintLayerNode` | class | bases (LayerNode) | A node allowing manipulation of a Paint layer. |
| `InstanceLayerNode` | class | bases (LayerNode) | A node allowing manipulation of an Instance layer. |
| `InstanceLayerNode.instance_source` | method | `instance_source() -> LayerNode` | Return the source layer of this instance. |
| `FillLayerNode` | class | bases (FillParamsEditorMixin, SourceEditorMixin, LayerNode) | A node allowing manipulation of a Fill layer. |
| `HierarchicalNode` | type alias | = Union[LayerNode, GroupLayerNode, PaintLayerNode, InstanceLayerNode, FillLayerNode] |  |
| `GeneratorEffectNode` | class | bases (ActiveChannelsMixin, Node) | A node allowing manipulation of a Generator effect. |
| `GeneratorEffectNode.get_source` | method | `get_source() -> SourceSubstance` | Get the source procedural of the generator, or None if no generator is set. |
| `GeneratorEffectNode.set_source` | method | `set_source(res: substance_painter.resource.ResourceID) -> SourceSubstance` | Create and assign a source from the given resource and return the created source. |
| `GeneratorEffectNode.remove_source` | method | `remove_source() -> None` | Remove the currently used source. |
| `PaintEffectNode` | class | bases (Node) | A node allowing manipulation of a Paint effect. |
| `FillEffectNode` | class | bases (FillParamsEditorMixin, SourceEditorMixin, Node) | A node allowing manipulation of a Fill effect. |
| `LevelsEffectNode` | class | bases (Node) | A node allowing manipulation of a Levels effect. |
| `LevelsEffectNode.affected_channel` | property | `affected_channel() -> ChannelType` | The channel affected by the current level effect. |
| `LevelsEffectNode.affected_channel` | property setter | `affected_channel(channel: ChannelType) -> None` | Setter of the property above. |
| `LevelsEffectNode.get_parameters` | method | `get_parameters() -> LevelsParams` | Get the current parameters of this levels effect. |
| `LevelsEffectNode.set_parameters` | method | `set_parameters(params: LevelsParams) -> None` | Set new parameters for this levels effect. |
| `CompareMaskEffectParams` | dataclass | fields: channel: ChannelType; left_operand: CompareMaskEffectOperand; right_operand: CompareMaskEffectOperand; operation: CompareMaskEffectOperation; constant: float; tolerance: float; hardness: float | A compare mask effect parameters. |
| `CompareMaskEffectNode` | class | bases (Node) | A node allowing manipulation of a Compare Mask effect. |
| `CompareMaskEffectNode.get_parameters` | method | `get_parameters() -> CompareMaskEffectParams` | Get the current parameters of this compare mask effect. |
| `CompareMaskEffectNode.set_parameters` | method | `set_parameters(params: CompareMaskEffectParams) -> None` | Set new parameters of this compare mask effect. |
| `FilterEffectNode` | class | bases (ActiveChannelsMixin, Node) | A node allowing manipulation of a Filter effect. |
| `FilterEffectNode.get_source` | method | `get_source() -> SourceSubstance` | Get the source procedural of the filter, or None if no filter is set. |
| `FilterEffectNode.set_source` | method | `set_source(res: substance_painter.resource.ResourceID) -> SourceSubstance` | Create and assign a source from the given resource and return the created source. |
| `FilterEffectNode.remove_source` | method | `remove_source() -> None` | Remove the currently used source. |
| `ColorSelectionEffectParams` | dataclass | fields: id_mask: Optional[substance_painter.resource.ResourceID]; output_value: float; hardness: float; tolerance: float; background_color: ColorSelectionBackgroundColor; colors: List[Color] | A color selection effect parameters. |
| `ColorSelectionEffectNode` | class | bases (Node) | A node allowing manipulation of a Color Selection effect. |
| `ColorSelectionEffectNode.get_parameters` | method | `get_parameters() -> ColorSelectionEffectParams` | Get the current parameters of this color selection effect. |
| `ColorSelectionEffectNode.set_parameters` | method | `set_parameters(params: ColorSelectionEffectParams) -> None` | Set new parameters of this compare mask effect. |
| `AnchorPointEffectNode` | class | bases (Node) | A node allowing manipulation of an Anchor Point effect. |
| `EffectNode` | type alias | = Union[GeneratorEffectNode, PaintEffectNode, FillEffectNode, LevelsEffectNode, CompareMaskEffectNode, FilterEffectNode, ColorSelectionEffectNode, AnchorPointEffectNode] |  |
| `get_root_layer_nodes` | function | `get_root_layer_nodes(stack: Stack) -> List[HierarchicalNode]` | Get the root layers of a stack, ordered like in the layer stack. |
| `get_node_by_uid` | function | `get_node_by_uid(node_id: int) -> List[Union[HierarchicalNode, EffectNode]]` | Get a node by its internal identifier. |
| `get_selected_nodes` | function | `get_selected_nodes(stack: Stack) -> List[Union[HierarchicalNode, EffectNode]]` | Get the selected nodes of a Stack, ordered like in the layer stack. |
| `set_selected_nodes` | function | `set_selected_nodes(nodes: List[EffectNode] \| List[LayerNode])` | Select the given nodes in the layer stack UI. |
| `get_selection_type` | function | `get_selection_type(layer: LayerNode) -> SelectionType` | Return which part of a layer is selected (content, mask, etc...). |
| `set_selection_type` | function | `set_selection_type(layer: LayerNode, layer_selection_type: SelectionType)` | Select which part of the layer you want to select. |
| `delete_node` | function | `delete_node(node: Node)` | Delete the given node. |
| `UVTransformationParams` | dataclass | fields: scale_mode: ScaleMode = None; scale: List[float] = None; rotation: float = None; offset: List[float] = None | UV projection transformation parameters. |
| `Projection3DParams` | dataclass | fields: offset: List[float] = None; rotation: List[float] = None; scale: List[float] = None | 3D projection transformation parameters. |
| `ProjectionCullingParams` | dataclass | fields: enabled: bool = None; hardness: float = None | Projection culling parameters. |
| `UVProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.UV <ProjectionMode>. |
| `TriplanarProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; shape_crop_mode: ShapeCropMode = None; hardness: float = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.Triplanar <ProjectionMode>. |
| `PlanarProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; depth_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); backface_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); backface_culling_angle: float = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.Planar <ProjectionMode>. |
| `WarpProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; projection_depth: float = None; depth_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.Warp <ProjectionMode>. |
| `SphericalProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.Spherical <ProjectionMode>. |
| `CylindricalProjectionParams` | dataclass | fields: filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; shape_crop_mode: ShapeCropMode = None; angle: float = None; backface_culling: ProjectionCullingParams = dataclasses.field(default_factory=ProjectionCullingParams); uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams); projection_3d: Projection3DParams = dataclasses.field(default_factory=Projection3DParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.Cylindrical <ProjectionMode>. Also declares private class metadata, which is not a dataclass field and not a constructor parameter ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\layerstack.py.]). |
| `UVSetToUVSetProjectionParams` | dataclass | fields: source_uv_set: int = None; filtering_mode: FilteringMode = None; uv_wrapping_mode: UVWrapMode = None; uv_transformation: UVTransformationParams = dataclasses.field(default_factory=UVTransformationParams) | Parameters that control the fill behaviour when the projection mode is ProjectionMode.UVSetToUVSet <ProjectionMode>. |
| `ProjectionParams` | type alias | = Union[UVProjectionParams, TriplanarProjectionParams, PlanarProjectionParams, WarpProjectionParams, SphericalProjectionParams, CylindricalProjectionParams, UVSetToUVSetProjectionParams] | Each Projection Mode has its own projection parameters. |
| `MirrorSymmetryParams` | dataclass | fields: axis: SymmetryAxis = None; flip_u: bool = None; flip_v: bool = None; axis_position: List[float] = None | Parameters that control the mirror symmetry behaviour. |
| `RadialSymmetryParams` | dataclass | fields: axis: SymmetryAxis = None; flip_u: bool = None; flip_v: bool = None; axis_position: List[float] = None; count: int = None; angle_span: float = None | Parameters that control the radial symmetry behaviour. |
| `SymmetryParams` | type alias | = Union[MirrorSymmetryParams, RadialSymmetryParams] | Each Symmetry Mode has its own symmetry parameters. |
| `InsertPosition` | dataclass | fields: node_id: int; node_stack: Optional[int] | InsertPosition is the object used by all the insert methods to express where you want the insertion to happen in the layer stack hierarchy. |
| `InsertPosition.from_textureset_stack` | staticmethod | `from_textureset_stack(stack: substance_painter.textureset.Stack) -> InsertPosition` | Generate an InsertPosition on the top of a stack. |
| `InsertPosition.above_node` | staticmethod | `above_node(node: Node) -> InsertPosition` | Generate an InsertPosition to insert above the given node. |
| `InsertPosition.below_node` | staticmethod | `below_node(node: Node) -> InsertPosition` | Generate an InsertPosition to insert below the given node. |
| `InsertPosition.inside_node` | staticmethod | `inside_node(node: Node, node_stack: NodeStack) -> InsertPosition` | Generate an InsertPosition to insert inside the given stack of a node. |
| `insert_fill` | function | `insert_fill(position: InsertPosition) -> Union[FillLayerNode, FillEffectNode]` | Insert a Fill effect or layer (depending on the insert position). |
| `insert_paint` | function | `insert_paint(position: InsertPosition) -> Union[PaintLayerNode, PaintEffectNode]` | Insert a Paint effect or layer (depending on the insert position). |
| `insert_group` | function | `insert_group(position: InsertPosition) -> GroupLayerNode` | Insert a group layer. |
| `instantiate` | function | `instantiate(position: InsertPosition, layer: LayerNode) -> InstanceLayerNode` | Instantiate the given layer. |
| `insert_levels_effect` | function | `insert_levels_effect(position: InsertPosition) -> LevelsEffectNode` | Insert a levels effect with default parameters. |
| `insert_compare_mask_effect` | function | `insert_compare_mask_effect(position: InsertPosition) -> CompareMaskEffectNode` | Insert a compare mask effect with default parameters. |
| `insert_filter_effect` | function | `insert_filter_effect(position: InsertPosition, filter_substance: Optional[substance_painter.resource.ResourceID] = None) -> FilterEffectNode` | Insert a filter effect, either empty or with the given filter resource. |
| `insert_generator_effect` | function | `insert_generator_effect(position: InsertPosition, generator_substance: Optional[substance_painter.resource.ResourceID] = None) -> GeneratorEffectNode` | Insert a Generator effect, either empty or with the given filter resource. |
| `insert_anchor_point_effect` | function | `insert_anchor_point_effect(position: InsertPosition, name: str) -> AnchorPointEffectNode` | Insert an anchor point effect. |
| `insert_color_selection_effect` | function | `insert_color_selection_effect(position: InsertPosition) -> ColorSelectionEffectNode` | Insert a color selection effect. |
| `insert_smart_material` | function | `insert_smart_material(position: InsertPosition, smart_material: substance_painter.resource.ResourceID) -> GroupLayerNode` | Insert a smart material at the given position. |
| `create_smart_material` | function | `create_smart_material(group: GroupLayerNode, name: str) -> substance_painter.resource.Resource` | Create a smart material with name `name` from the given `group`. |
| `export_as_smart_material` | function | `export_as_smart_material(group: GroupLayerNode, name: str, path: str)` | Export the given `group` as a smart material with name `name` in the given `path`. |
| `insert_smart_mask` | function | `insert_smart_mask(position: InsertPosition, smart_mask: substance_painter.resource.ResourceID) -> List[EffectNode]` | Insert a smart mask in a mask stack. |
| `create_smart_mask` | function | `create_smart_mask(layer: LayerNode, name: str) -> substance_painter.resource.Resource` | Create a smart mask with name `name` from the mask stack of the given `layer`. |
| `export_as_smart_mask` | function | `export_as_smart_mask(layer: LayerNode, name: str, path: str)` | Export the mask stack of the given `layer` as a smart mask with name `name` in the given `path`. |
| `Node.uid` (inherited from `_utility.ReadOnlyUid`) | method | `uid() -> int` | Internal identifier of the node (also present on every `source.Source*` class). |
| `FillLayerNode` / `FillEffectNode` (inherited) | note | all `FillParamsEditorMixin` and `source.SourceEditorMixin` members | The HTML docs list these inherited members under both classes (projection, symmetry, sources, `active_channels`, `source_mode`). |
| `GeneratorEffectNode` / `FilterEffectNode` (inherited) | note | `source.ActiveChannelsMixin.active_channels` | Active-channel set of the effect. |
| `ScopedModification.__enter__` / `__exit__` | context manager | `with ScopedModification(name): ...` | Groups calls into one undo entry and one recomputation. |

## `substance_painter.levels`

Levels parameter dataclasses used by the Levels effect and by anchor references. Source: `resources\python\modules\substance_painter\levels.py`; HTML: `resources\python-doc\substance_painter\layerstack\layereffect\levels.html (no standalone page)`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `LevelsParamsRGB` | dataclass | fields: input_min: Tuple[float, float, float] = (0.0, 0.0, 0.0); input_max: Tuple[float, float, float] = (1.0, 1.0, 1.0); gamma: Tuple[float, float, float] = (1.0, 1.0, 1.0); output_min: Tuple[float, float, float] = (0.0, 0.0, 0.0); output_max: Tuple[float, float, float] = (1.0, 1.0, 1.0); clamp: bool = False | A levels parameters, when in RGB color mode. |
| `LevelsParamsMono` | dataclass | fields: input_min: float = 0.0; input_max: float = 1.0; gamma: float = 1.0; output_min: float = 0.0; output_max: float = 1.0; clamp: bool = False | A levels parameters, when in Luminance or only one color mode. |
| `LevelsParams` | type alias | = Union[LevelsParamsMono, LevelsParamsRGB] | alias of LevelsParamsMono \| LevelsParamsRGB |

## `substance_painter.logging`

Messages to the Painter log/console. Source: `resources\python\modules\substance_painter\logging.py`; HTML: `resources\python-doc\substance_painter\logging.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `INFO`, `WARNING`, `ERROR`, `DBG_INFO`, `DBG_WARNING`, `DBG_ERROR` | attribute | severity constants (documented in prose in `logging.html`); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\logging.py.] |  || `log` | function | `log(severity, channel: str, message: str)` | Logs a message with level `severity` on the Substance 3D Painter logger. |
| `info` | function | `info(message: str)` | Logs a message with level `INFO` on the Substance 3D Painter logger. |
| `warning` | function | `warning(message: str)` | Logs a message with level `WARNING` on the Substance 3D Painter logger. |
| `error` | function | `error(message: str)` | Logs a message with level `ERROR` on the Substance 3D Painter logger. |

## `substance_painter.project`

Project create/open/save/close, settings dataclasses, mesh reload, busy state, metadata. Source: `resources\python\modules\substance_painter\project.py`; HTML: `resources\python-doc\substance_painter\project.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ProjectSaveMode` | enum (native) | Members: `Full`, `Incremental` | Save strategy enumeration. |
| `NormalMapFormat` | enum (native) | Members: `OpenGL`, `DirectX` | The normal map formats that can be used by a `Substance 3D Painter` project. |
| `TangentSpace` | enum (native) | Members: `PerVertex`, `PerFragment` | The options for computing tangent space in a project. |
| `ProjectWorkflow` | enum (native) | Members: `Default`, `TextureSetPerUVTile`, `UVTile` | The workflow used by a `Substance 3D Painter` project. |
| `AutoUnwrapUVIslandOrientation` | enum (native) | Members: `RotateFreely`, `AlignWith3DMesh`, `KeepOriginal` | The orientation of UV islands during the automatic unwrap process. |
| `AutoUnwrapUVTilesSettingsUVTilesCount` | dataclass | fields: uv_tile_count_max: int = 4 | Settings to specify the number of UV Tiles to generate during the automatic unwrap process. |
| `AutoUnwrapUVTilesSettingsTexelDensity` | dataclass | fields: texel_density: float = 1.0; reference_resolution: int = 1024 | Settings to control the texel density of UV Tiles during the automatic unwrap process. |
| `AutoUnwrapUVTilesSettings` | type alias | = Union[AutoUnwrapUVTilesSettingsUVTilesCount, AutoUnwrapUVTilesSettingsTexelDensity] |  |
| `AutoUnwrapSettings` | dataclass | fields: recompute_seams: bool = True; recompute_uv_islands: bool = True; recompute_packing: bool = True; margin_size: float = 2.0; island_orientation: AutoUnwrapUVIslandOrientation = dataclasses.field(default_factory=lambda: AutoUnwrapUVIslandOrientation.RotateFreely); uv_tiles_settings: AutoUnwrapUVTilesSettings = dataclasses.field(default_factory=AutoUnwrapUVTilesSettingsUVTilesCount); avoid_elongated_uv_islands: bool = False; create_fewer_seams: bool = True | Auto-unwrap settings for project creation and mesh reloading. |
| `UsdSettings` | dataclass | fields: scope_name: str = '/'; variants: dict = None; subdivision_level: int = 1; frame: int = 0 | Specific settings for USD files. |
| `GltfSettings` | dataclass | fields: invert_normal_maps: bool = None | Specific settings for GLTF files. |
| `Settings` | dataclass | fields: default_save_path: str = None; normal_map_format: NormalMapFormat = None; tangent_space_mode: TangentSpace = None; project_workflow: ProjectWorkflow = None; export_path: str = None; default_texture_resolution: int = None; import_cameras: bool = None; mesh_unit_scale: float = None; mesh_settings: Union[UsdSettings, GltfSettings] = None; auto_unwrap_settings: AutoUnwrapSettings = None | Project configuration options. |
| `Settings.usd_settings` | property | `usd_settings()` | :meta private: **Deprecated since 0.3.2 (use mesh_settings).** |
| `Settings.usd_settings` | property setter | `usd_settings(value)` | Setter of the property above. |
| `MeshReloadingSettings` | dataclass | fields: import_cameras: bool = True; preserve_strokes: bool = True; mesh_settings: UsdSettings = None; auto_unwrap_settings: AutoUnwrapSettings = None | Settings used when reloading a mesh. |
| `MeshReloadingSettings.usd_settings` | property | `usd_settings()` | :meta private: **Deprecated since 0.3.2 (use mesh_settings).** |
| `MeshReloadingSettings.usd_settings` | property setter | `usd_settings(value)` | Setter of the property above. |
| `name` | function | `name() -> Optional[str]` | Return the name of the current project. |
| `file_path` | function | `file_path() -> Optional[str]` | Return the file path of the current project. |
| `close` | function | `close() -> None` | Close the current project. |
| `open` | function | `open(project_file_path: str) -> None` | Open the project located at `project_file_path`. |
| `is_open` | function | `is_open() -> bool` | Check if a project is already opened. |
| `needs_saving` | function | `needs_saving() -> bool` | Check if the current project needs to be saved. |
| `is_in_edition_state` | function | `is_in_edition_state() -> bool` | Check if the current project is ready to work with. |
| `is_busy` | function | `is_busy() -> bool` | Check if Substance 3D Painter is currently busy. |
| `execute_when_not_busy` | function | `execute_when_not_busy(callback: Callable[[], None]) -> None` | Execute the given callback when Substance 3D Painter is not busy. |
| `save_as` | function | `save_as(project_file_path: str, mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Save the current project by writing it to the file path `project_file_path`. |
| `save` | function | `save(mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Save the current project by overwriting the previous save. |
| `save_as_copy` | function | `save_as_copy(backup_file_path: str, mode: ProjectSaveMode = ProjectSaveMode.Incremental) -> None` | Save a copy of the current project by writing it to the file path `backup_file_path`. |
| `save_as_template` | function | `save_as_template(template_file_path: str, texture_set_name: str) -> ProjectSaveMode` | Save a template based of the current Texture Set or the one specified. |
| `create` | function | `create(mesh_file_path: str, mesh_map_file_paths: List[str] = None, template_file_path: str = None, settings: Settings = Settings())` | Create a new project. |
| `last_imported_mesh_path` | function | `last_imported_mesh_path() -> str` | Return the path to the last imported mesh. |
| `last_saved_substance_painter_version` | function | `last_saved_substance_painter_version() -> Optional[Tuple[int, int, int]]` | Return the version of Substance 3D Painter used to last save the project, or None if the project is unsaved or was saved with version <= 8.2.0. |
| `ReloadMeshStatus` | enum | Members: `SUCCESS`, `ERROR` (values 0 and 2 per HTML doc) | Reload mesh status, used in mesh reload asynchronous callback. |
| `reload_mesh` | function | `reload_mesh(mesh_file_path: str, settings: MeshReloadingSettings, loading_status_cb: Callable[[ReloadMeshStatus], Any])` | Import a new mesh to the current project, using the given settings. |
| `BoundingBox` | dataclass | fields: dimensions: List[float]; center: List[float]; radius: float | Axis-aligned bounding box (AABB). |
| `get_scene_bounding_box` | function | `get_scene_bounding_box() -> BoundingBox` | Return the bounding box of the scene. |
| `get_uuid` | function | `get_uuid() -> uuid.UUID` | Return the UUID of the current project. |
| `Metadata` | class | — | Project metadata are arbitrary data that can be attached to a `Substance Painter` project. |
| `Metadata.__init__` | constructor | `__init__(context: str)` |  |
| `Metadata.list` | method | `list() -> list` | Return the list of project metadata keys. |
| `Metadata.get` | method | `get(key: str)` | Retrieve the project metadata under the given key. |
| `Metadata.set` | method | `set(key: str, value)` | Store project metadata under the given key. |
| `ProjectSaveMode` default | note | `ProjectSaveMode.Incremental` (HTML signatures; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\project.py.]) | Default mode of `save`, `save_as`, `save_as_copy`. |

## `substance_painter.properties`

Read-only wrapper over dynamic engine properties (used by baking and substance sources). Source: `resources\python\modules\substance_painter\properties.py`; HTML: `resources\python-doc\substance_painter\properties.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `PropertyValue` | type alias | = typing.Union[bool, int, typing.Tuple[int, int], typing.Tuple[int, int, int], typing.Tuple[int, int, int, int], float, typing.Tuple[float, float], typing.Tuple[float, float, float], Color, typing.Tuple[Color, float], typing.Tuple[float, float, float, float], str] |  |
| `Property` | dataclass | fields: handle: _substance_painter.data_tweak.PythonTweak | Read only access to a property data. |
| `Property.value` | method | `value() -> PropertyValue` | Get the current property value. |
| `Property.name` | method | `name() -> str` | Get the property name. |
| `Property.short_name` | method | `short_name() -> str` | Get the shortened property name. |
| `Property.label` | method | `label() -> str` | Get the property label. |
| `Property.widget_type` | method | `widget_type() -> str` | Get the widget type that should be used to edit the property. |
| `Property.enum_values` | method | `enum_values() -> typing.Dict[str, int]` | The possible enum values with corresponding text for 'Combobox' widget type. |
| `Property.enum_value` | method | `enum_value(enum_label: str) -> int` | Get the enum value for the given enum label for 'Combobox' widget type. |
| `Property.properties` | method | `properties() -> typing.Dict[str, typing.Any]` | Get a json object that describes all available meta properties of this property. |

## `substance_painter.resource`

Resources (URL-identified assets), shelves, search, import, project-resource listing/replacement, reload. Source: `resources\python\modules\substance_painter\resource.py`; HTML: `resources\python-doc\substance_painter\resource.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ResourceLocation` | enum | Members: `SESSION`, `PROJECT`, `SHELF` | Each resource has a location determined by where its data lives. |
| `ResourceID` | dataclass | fields: context: str; name: str; version: str = None | A `Substance 3D Painter` resource identifier. |
| `ResourceID.from_url` | classmethod | `from_url(url: str)` | Create a `ResourceID` object from its URL. |
| `ResourceID.from_project` | classmethod | `from_project(name: str, version: str = None)` | Create a `ResourceID` object for a resource located in the current project. |
| `ResourceID.from_session` | classmethod | `from_session(name: str, version: str = None)` | Create a `ResourceID` object for a resource located in the current session. |
| `ResourceID.url` | method | `url() -> str` | Get the URL form of this `ResourceID`. |
| `ResourceID.location` | method | `location() -> ResourceLocation` | Get the location of this `ResourceID`. |
| `Usage` | enum | Members: `ALPHA`, `BASE_MATERIAL`, `BRUSH`, `COLOR_LUT`, `EMITTER`, `ENVIRONMENT`, `EXPORT`, `FILTER`, `FONT`, `GENERATOR`, `PARTICLE`, `PROCEDURAL`, `RECEIVER`, `SHADER`, `SMART_MASK`, `SMART_MATERIAL`, `TEXTURE`, `TOOL` | Enumeration describing how a given resource is meant to be used. |
| `Type` | enum | Members: `ABR_PACKAGE`, `BRUSH`, `EXPORT`, `FONT`, `IMAGE`, `PRESET`, `RESOURCE`, `SCRIPT`, `SHADER`, `SMART_MASK`, `SMART_MATERIAL`, `SUBSTANCE`, `SUBSTANCE_PACKAGE`, `VECTORIAL` | Enumeration describing the type of a given resource. |
| `Resource` | dataclass | fields: handle: _substance_painter.resource.ResourceHandle | A `Substance 3D Painter` resource. |
| `Resource.identifier` | method | `identifier() -> ResourceID` | Get this resource identifier. |
| `Resource.location` | method | `location() -> ResourceLocation` | Get the location of this `Resource`. |
| `Resource.retrieve` | staticmethod | `retrieve(identifier: ResourceID)` | Retrieve a list of resources matching the given identifier. |
| `Resource.set_custom_preview` | method | `set_custom_preview(preview_image: str) -> None` | Replace the current preview of this resource with a custom image. |
| `Resource.category` | method | `category() -> str` | Get the category of this resource, ex: "wood" for a material. |
| `Resource.usages` | method | `usages() -> typing.List[Usage]` | Get the usages of this resource. |
| `Resource.gui_name` | method | `gui_name() -> str` | Get the GUI name of this resource. |
| `Resource.type` | method | `type() -> Type` | Get the type of this resource. |
| `Resource.tags` | method | `tags() -> typing.List[str]` | Get the tags of this resource. |
| `Resource.internal_properties` | method | `internal_properties() -> dict` | Get a dictionary of the resource internal properties. |
| `Resource.children` | method | `children() -> typing.List['Resource']` | Get child resources. |
| `Resource.parent` | method | `parent() -> typing.Optional['Resource']` | Get parent resource. |
| `Resource.reset_preview` | method | `reset_preview() -> None` | Remove any custom preview for this resource and resets to the default one. |
| `Resource.show_in_ui` | method | `show_in_ui() -> None` | Highlight this resource in the application shelf UI (Assets window). |
| `show_resources_in_ui` | function | `show_resources_in_ui(resources: typing.List[Resource]) -> None` | Highlight a list of resources in the application shelf UI (Assets window). |
| `import_project_resource` | function | `import_project_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None) -> Resource` | Import a resource into the current opened project. |
| `import_session_resource` | function | `import_session_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None) -> Resource` | Import a resource into the current session. |
| `StandardQuery` | class | fields: ALL_RESOURCES; PROJECT_RESOURCES; SESSION_RESOURCES; SHELVES_RESOURCES ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\resource.py.]) | Standard resource queries. |
| `search` | function | `search(query: str) -> typing.List[Resource]` | List Substance 3D Painter resources that match the given query. |
| `list_layer_stack_resources` | function | `list_layer_stack_resources() -> typing.List[ResourceID]` | List the resources referenced by the layer stacks and mesh maps of the current project. **Deprecated since 0.3.4 (use list_project_resources).** |
| `update_layer_stack_resource` | function | `update_layer_stack_resource(old_resource_id: ResourceID, new_resource: Resource) -> typing.List[ResourceID]` | Replace resources from the layer stacks and mesh maps in the current project. **Deprecated since 0.3.4 (use replace_project_resources).** |
| `list_project_resources` | function | `list_project_resources() -> typing.List[ResourceID]` | List the resources used in the current project. |
| `list_project_outdated_resources` | function | `list_project_outdated_resources() -> typing.Dict[ResourceID, ResourceID]` | List the resources used in the current project that are outdated. |
| `UpdateProjectStatus` | enum (native) | Members: `SUCCESS`, `ERROR` | Status of the replace_project_resources operation. |
| `UpdateProjectError` | dataclass | fields: old_resource_id: ResourceID; new_resource_id: ResourceID; details: typing.List[str] | Error that occurred during the replace_project_resources operation. |
| `UpdateProjectResult` | dataclass | fields: status: UpdateProjectStatus; errors: typing.List[UpdateProjectError] | Result of the replace_project_resources operation. |
| `replace_project_resources` | function | `replace_project_resources(ids: typing.Dict[ResourceID, ResourceID], allow_parameters_mismatch: bool = False) -> UpdateProjectResult` | Replace resources in the current project. |
| `Shelf` | dataclass | fields: _name: str | Class providing information on a given `Substance 3D Painter` shelf. |
| `Shelf.name` | method | `name() -> str` | Returns: The shelf name. |
| `Shelf.path` | method | `path() -> str` | Returns: The associated path |
| `Shelf.resources` | method | `resources(query: str = StandardQuery.ALL_RESOURCES) -> typing.List[Resource]` | Get resources contained in this shelf. |
| `Shelf.can_import_resources` | method | `can_import_resources() -> bool` | Check if resources can be imported into this shelf. |
| `Shelf.import_resource` | method | `import_resource(file_path: str, resource_usage: Usage, name: str = None, group: str = None, uuid: str = None) -> Resource` | Import a resource into this shelf. |
| `Shelf.is_crawling` | method | `is_crawling() -> bool` | Check if this shelf is currently discovering resources in folders. |
| `Shelf.refresh` | method | `refresh()` | Forces discovering of resources in shelf folders. |
| `Shelves` | class | — | Collection of static methods to manipulate shelves. |
| `Shelves.all` | staticmethod | `all() -> typing.List[Shelf]` | List all shelves. |
| `Shelves.exists` | staticmethod | `exists(name: str) -> bool` | Tell whether a shelf with the given name exists. |
| `Shelves.add` | staticmethod | `add(name: str, path: str) -> Shelf` | Add a new shelf. |
| `Shelves.remove` | staticmethod | `remove(name: str)` | Removes a shelf. |
| `Shelves.refresh_all` | staticmethod | `refresh_all()` | Forces discovering of resources in all shelves folders. |
| `Shelves.user_shelf` | staticmethod | `user_shelf() -> Shelf` | This is the shelf located in the user Documents folder where new resources are created by default. |
| `Shelves.application_shelf` | staticmethod | `application_shelf() -> Shelf` | This is the shelf containing the default content shipped with the application. |
| `AllResourcesFilter` | dataclass | — | Filter used to reload all modified resources known to Substance 3D Painter, which includes resources in all shelves, session-scoped resources, and project-scoped resources. |
| `ProjectFilter` | dataclass | — | Filter used to reload modified resources contained in the project context. |
| `ResourcesListFilter` | dataclass | fields: resources: typing.List[ResourceID] | Filter used to reload modified resources amongst a given list of resources. |
| `ResourcesUsedByProjectFilter` | dataclass | — | Filter used to reload modified resources currently in use by the project. |
| `SessionFilter` | dataclass | — | Filter used to reload modified resources contained in the session. |
| `ShelvesListFilter` | dataclass | fields: shelves: typing.List[Shelf] | Filter used to reload modified resources contained in designated shelves. |
| `ReloadResourcesFilter` | type alias | = typing.Union[AllResourcesFilter, ProjectFilter, ResourcesListFilter, ResourcesUsedByProjectFilter, SessionFilter, ShelvesListFilter] |  |
| `reload_modified_resources_async` | function | `reload_modified_resources_async(resource_filter: ReloadResourcesFilter) -> bool` | Triggers a reload of the modified resources found using the given filter. |
| `is_reload_modified_resources_running` | function | `is_reload_modified_resources_running() -> bool` | Check if a reload modified resources operation is currently running. |

## `substance_painter.source`

Sources that feed fill layers/effects and procedural inputs: uniform color, bitmap, font, vector, substance, anchor reference. Source: `resources\python\modules\substance_painter\source.py`; HTML: `resources\python-doc\substance_painter\source\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `SourceMode` | enum (native) | Members: `Split`, `Material` | When working with a fill layer or a fill effect in a multi-channel context, you can either have one source that write to all channels or several sources with each source writing to one channel. |
| `FontResolutionMode` | enum | Members: `Auto`, `Manual` | Members: **Deprecated since 0.3.4 (use ResolutionMode).** |
| `HorizontalAlignment` | enum (native) | Members: `Left`, `Center`, `Right` | Enumeration. |
| `VerticalAlignment` | enum (native) | Members: `Top`, `Middle`, `Bottom` | Enumeration. |
| `ResolutionMode` | enum | Members: `Auto`, `Asset`, `Custom`, `TextureSet`, `UVTile`, `Document`, `Manual` | Members: |
| `VectorialResolutionMode` | attribute | = ResolutionMode | Alias for ResolutionMode. **Deprecated since 0.3.4; alias of ResolutionMode.** |
| `CropAreaMode` | enum (native) | Members: `DocumentBounds`, `Manual` | Enumeration. |
| `AlphaMatte` | enum (native) | Members: `KeepAlpha`, `ExtractAlpha`, `DefaultBackgroundColor` | Enumeration. |
| `ResolutionOverride` | dataclass | fields: mode: ResolutionMode; value: Tuple[int, int]; log2_offset: int | Resolution override parameters. |
| `ActiveChannelsMixin` | class | — | Mixin providing active channels property. Docstring marks it `:meta private:` (`source.py:300–305`): implementation helper; `active_channels` is public through `FillLayerNode`, `FillEffectNode`, `GeneratorEffectNode`, `FilterEffectNode` only (not `PaintLayerNode`). |
| `ActiveChannelsMixin.active_channels` | property | `active_channels() -> Set[ChannelType]` | The set of active channels of the source. |
| `ActiveChannelsMixin.active_channels` | property setter | `active_channels(channels: Set[ChannelType]) -> None` | Setter of the property above. |
| `SourceEditorMixin` | class | bases (ActiveChannelsMixin) | Mixin providing all necessary functions to edit sources. Docstring marks it `:meta private:` (`source.py:324–329`): implementation helper; members public through `FillLayerNode`/`FillEffectNode`. |
| `SourceEditorMixin.source_mode` | property | `source_mode() -> SourceMode` | The current context in which the source is edited: |
| `SourceEditorMixin.get_source` | method | `get_source(channeltype: ChannelType \| None = None) -> Source` | Get the source for the given channel type. |
| `SourceEditorMixin.set_source` | method | `set_source(channeltype: ChannelType \| None, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | Set the source for the given channel type. |
| `SourceEditorMixin.reset_source` | method | `reset_source(channeltype: ChannelType \| None = None) -> None` | Reset the source at channel type. |
| `SourceEditorMixin.get_material_source` | method | `get_material_source() -> SourceSubstance \| SourceReference` | Get the source in material mode. |
| `SourceEditorMixin.set_material_source` | method | `set_material_source(source: ResourceID \| layerstack.AnchorPointEffectNode) -> SourceSubstance \| SourceReference` | Set the source in material mode. |
| `SourceEditorMixin.reset_material_source` | method | `reset_material_source() -> None` | Reset the source in material mode. |
| `SourceEditorMixin.set_sources_from_preset` | method | `set_sources_from_preset(preset: ResourceID) -> None` | Setup the fill with the given preset. |
| `SourceUniformColor` | class | bases (ReadOnlyUid) | A class that represents an uniform color source. |
| `SourceUniformColor.get_color` | method | `get_color() -> Color` | Get the uniform color of the source. |
| `SourceUniformColor.set_color` | method | `set_color(color: Color) -> None` | Set the uniform color of the source. |
| `SourceBitmap` | class | bases (ReadOnlyUid) | A class that represents a bitmap source. |
| `SourceBitmap.resource_id` | property | `resource_id() -> ResourceID` | The current bitmap used by the source. |
| `SourceBitmap.get_color_space` | method | `get_color_space() -> ResourceColorSpace` | Return the color space of the bitmap. |
| `SourceBitmap.set_color_space` | method | `set_color_space(color_space: ResourceColorSpace)` | Override the default color space of the bitmap. |
| `SourceBitmap.reset_color_space` | method | `reset_color_space()` | Remove any override color space and go back to the default one. |
| `SourceBitmap.list_available_color_spaces` | method | `list_available_color_spaces() -> List[ResourceColorSpace]` | Get the list of available color spaces for the bitmap. |
| `SourceFontParams` | dataclass | bases: private ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\source.py.]) — fields: text: str \| None; auto_size: bool; size: float \| None; horizontal_alignment: HorizontalAlignment; vertical_alignment: VerticalAlignment; color: Color; background_color: Color; background_opacity: float \| None; line_spacing: float; character_spacing: float; offset: Tuple[float, float]; resolution: ResolutionOverride | The source font parameters. |
| `SourceFont` | class | bases (ReadOnlyUid) | A class that represents a text source. |
| `SourceFont.resource_id` | property | `resource_id() -> ResourceID` | The current font resource of the source. |
| `SourceFont.get_parameters` | method | `get_parameters() -> SourceFontParams` | Get the source parameters. |
| `SourceFont.set_parameters` | method | `set_parameters(params: SourceFontParams) -> None` | Set the source parameters. |
| `SourceVectorialParams` | dataclass | bases: private (same redaction as `SourceFontParams`) — fields: artboard_id: str \| None; scope: str \| None; resolution: ResolutionOverride; crop_area_mode: CropAreaMode; crop_area_value: Tuple[float, float, float, float]; fit_to_square: bool = True | The source vectorial parameters. |
| `SourceVectorial` | class | bases (ReadOnlyUid) | A class that represents a vectorial source. |
| `SourceVectorial.resource_id` | property | `resource_id() -> ResourceID` | The current vectorial resource of the source. |
| `SourceVectorial.get_parameters` | method | `get_parameters() -> SourceVectorialParams` | Get the source parameters. |
| `SourceVectorial.set_parameters` | method | `set_parameters(params: SourceVectorialParams) -> None` | Set the source parameters. |
| `OutputMappingIterator` | class | — | This class implements the iterator interface for class OutputMapping. Docstring marks it `:meta private:` (`source.py:709–714`): implementation helper. |
| `OutputMappingIterator.__init__` | constructor | `__init__(uid)` |  |
| `OutputMapping` | class | bases (ReadOnlyUid) | This class gives access to the output mapping of a source procedural in a dict-like fashion. |
| `SourceSubstance` | class | bases (ReadOnlyUid) | A class that represents a procedural source. |
| `SourceSubstance.resource_id` | property | `resource_id() -> ResourceID` | The current substance resource of the source. |
| `SourceSubstance.output_mapping` | property | `output_mapping() -> OutputMapping` | The output mapping property in multiple output context. |
| `SourceSubstance.active_output` | property | `active_output() -> str` | The active output of the source in single output context. |
| `SourceSubstance.active_output` | property setter | `active_output(identifier: str) -> None` | Setter of the property above. |
| `SourceSubstance.mask_output` | property | `mask_output() -> str` | The mask output identifier of the source in multiple output context. |
| `SourceSubstance.mask_output` | property setter | `mask_output(identifier: str) -> None` | Setter of the property above. |
| `SourceSubstance.image_inputs` | property | `image_inputs() -> List[str]` | The list of image inputs identifier from the current graph. |
| `SourceSubstance.image_outputs` | property | `image_outputs() -> List[str]` | The list of image outputs identifier from the current graph. |
| `SourceSubstance.get_source` | method | `get_source(identifier: str) -> Source` | Get the source for the given input identifier. |
| `SourceSubstance.set_source` | method | `set_source(identifier: str, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | Set the source for the given input identifier. |
| `SourceSubstance.reset_source` | method | `reset_source(identifier: str) -> None` | Reset the source for the given input identifier. |
| `SourceSubstance.remove_source` | method | `remove_source(identifier: str) -> None` | Remove the source for the given input identifier. |
| `SourceSubstance.get_parameters` | method | `get_parameters() -> Dict[str, PropertyValue]` | Get source procedural parameters. |
| `SourceSubstance.set_parameters` | method | `set_parameters(property_values: Dict[str, PropertyValue]) -> None` | Set source procedural parameters. |
| `SourceSubstance.get_properties` | method | `get_properties() -> Dict[str, Property]` | Get source procedural properties. |
| `SourceSubstance.get_preset_list` | method | `get_preset_list() -> List[str]` | Get the list of all available presets for this source. |
| `SourceSubstance.apply_preset` | method | `apply_preset(name: str)` | Apply a preset given its name. |
| `SourceSubstance.resolution` | property | `resolution() -> ResolutionOverride` | The resolution parameters for this substance. |
| `SourceSubstance.resolution` | property setter | `resolution(value)` | Setter of the property above. |
| `ChannelMappingIterator` | class | — | This class implements the iterator interface for class ChannelMapping. Docstring marks it `:meta private:` (`source.py:983–988`): implementation helper. |
| `ChannelMappingIterator.__init__` | constructor | `__init__(uid)` |  |
| `ChannelMapping` | class | bases (ReadOnlyUid) | This class gives access to the active channels of a source reference in a dict-like fashion. |
| `SourceReference` | class | bases (ReadOnlyUid) | A class that represents an reference to an anchor point. |
| `SourceReference.channel_mapping` | property | `channel_mapping() -> ChannelMapping` | The channels mapping property. |
| `SourceReference.referenced_channel` | property | `referenced_channel() -> ChannelType` | The referenced channel of the source. |
| `SourceReference.referenced_channel` | property setter | `referenced_channel(channeltype: ChannelType) -> None` | Setter of the property above. |
| `SourceReference.anchor` | property | `anchor() -> layerstack.AnchorPointEffectNode` | The anchor used by this source. |
| `SourceReference.alpha_matte` | property | `alpha_matte() -> AlphaMatte` | The alpha matte used by this source. |
| `SourceReference.alpha_matte` | property setter | `alpha_matte(alpha_matte: AlphaMatte)` | Setter of the property above. |
| `SourceReference.get_levels` | method | `get_levels() -> LevelsParams` | Get the parameters used by the levels of this source. |
| `SourceReference.set_levels` | method | `set_levels(params: LevelsParams) -> None` | Set the parameters used by the levels of this source. |
| `Source` | type alias | = Union[SourceUniformColor, SourceBitmap, SourceVectorial, SourceSubstance, SourceReference, SourceFont] |  |
| `OutputMapping` / `ChannelMapping` (dunder API) | dict-like | `__getitem__(ChannelType)`, `__setitem__(ChannelType, str or ChannelType)`, `__len__`, `__contains__`, `__iter__` | Read/write output mapping (substance outputs to channels) and channel mapping (anchor channels to channels). |
| `SourceFontParams.resolution_mode` / `resolution_value`, `SourceVectorialParams.resolution_mode` / `resolution_value` | deprecated attributes | via a private base (same redaction as `SourceFontParams`) | **Deprecated since 0.3.4** (use `resolution: ResolutionOverride`). |

## `substance_painter.textureset`

Texture Sets, stacks, channels (types/formats), UV tiles, resolutions, mesh-map slots. Source: `resources\python\modules\substance_painter\textureset.py`; HTML: `resources\python-doc\substance_painter\textureset\*.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `ChannelFormat` | enum (native) | Members: `sRGB8`, `L8`, `RGB8`, `L16`, `RGB16`, `L16F`, `RGB16F`, `L32F`, `RGB32F` | The texture format of a channel. |
| `ChannelType` | enum (native) | Members: OpenPBR: `BaseWeight`, `BaseColor`, `BaseMetalness`, `BaseDiffuseRoughness`, `SpecularWeight`, `SpecularColor`, `SpecularRoughness`, `SpecularRoughnessAnisotropy`, `TransmissionWeight`, `TransmissionColor`, `SubsurfaceWeight`, `SubsurfaceColor`, `SubsurfaceRadiusScale`, `CoatWeight`, `CoatColor`, `CoatRoughness`, `CoatRoughnessAnisotropy`, `CoatNormal`, `CoatTangent`, `FuzzWeight`, `FuzzColor`, `FuzzRoughness`, `EmissionColor`, `ThinFilmWeight`, `Opacity`, `Height`, `Displacement`, `Normal`, `Tangent`, `AO`; User: `User0`..`User31`; Non-OpenPBR (legacy/ASM): `Glossiness`, `Specular`, `Anisotropyangle`, `Transmissive`, `Reflection`, `Ior`, `Diffuse`, `Specularlevel`, `BlendingMask`, `CoatSpecularLevel`; Legacy aliases: `Metallic`, `Roughness`, `Emissive`, `SpecularEdgeColor`, `Anisotropylevel`, `Scattering`, `ScatteringColor`, `Translucency`, `AbsorptionColor`, `SheenOpacity`, `SheenRoughness`, `SheenColor`, `CoatOpacity` | All possible types of channel in a document. |
| `MeshMapUsage` | enum (native) | Members: `AO`, `BentNormals`, `Curvature`, `Height`, `ID`, `Normal`, `Opacity`, `Position`, `Thickness`, `WorldSpaceNormal` | Enumeration. |
| `Resolution` | dataclass | fields: width: int = 1024; height: int = 1024 | Two dimensional resolution. |
| `Channel` | dataclass | fields: channel_id: int = None | A `Substance 3D Painter` channel. |
| `Channel.format` | method | `format() -> ChannelFormat` | Get the channel format. |
| `Channel.label` | method | `label() -> str` | Get the user label for User channels (`User0` to `User31`). |
| `Channel.is_color` | method | `is_color() -> bool` | Check if the channel is in color or grayscale format. |
| `Channel.is_floating` | method | `is_floating() -> bool` | Check if the channel is in floating point or normalized fixed point format. |
| `Channel.bit_depth` | method | `bit_depth() -> int` | Get the number of bits per component. |
| `Channel.type` | method | `type() -> ChannelType` | Get the channel type. |
| `Channel.edit` | method | `edit(channel_format: ChannelFormat, label: typing.Optional[str] = None) -> None` | Change the channel format and label. |
| `UVTile` | class | bases: private ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.]) | A UV Tile coordinates. |
| `UVTile.u` | attribute | `u: int` | "The U coordinate of the UV Tile" (class docstring); public field (HTML class signature below). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.] |
| `UVTile.v` | attribute | `v: int` | "The V coordinate of the UV Tile" (class docstring); public field (HTML class signature below). |
| `UVTile.__init__` | constructor | `__init__(u: int, v: int, _material_id: int)` | HTML signature `UVTile(u: int, v: int, _material_id: int)` (`textureset\uvtile.html`). `_material_id` is private, not an additional public field. |
| `UVTile.name` | property | `name() -> str` | The name of the UV Tile. |
| `UVTile.name` | property setter | `name(name: str) -> None` | Setter of the property above. |
| `UVTile.description` | property | `description() -> str` | The description of the UV Tile. |
| `UVTile.description` | property setter | `description(description: str) -> None` | Setter of the property above. |
| `UVTile.get_resolution` | method | `get_resolution() -> Resolution` | Get the UV Tile resolution. |
| `UVTile.set_resolution` | method | `set_resolution(new_resolution: Resolution)` | Set the resolution of the UV Tile. |
| `UVTile.reset_resolution` | method | `reset_resolution()` | Reset the resolution of the UV Tile to match the parent Texture Set. |
| `UVTile.all_mesh_names` | method | `all_mesh_names() -> typing.List[str]` | Get the list of meshes of the UV Tile. |
| `Stack` | dataclass | fields: stack_id: int = None | A `Substance 3D Painter` paintable stack. |
| `Stack.from_name` | staticmethod | `from_name(texture_set_name: str, stack_name: str = '')` | Get a stack from its name. |
| `Stack.name` | method | `name() -> str` | Get the stack name. |
| `Stack.material` | method | `material()` | Get the Texture Set this stack belongs to. |
| `Stack.all_channels` | method | `all_channels() -> typing.Dict[ChannelType, Channel]` | List all the channels of a stack. |
| `Stack.add_channel` | method | `add_channel(channel_type: ChannelType, channel_format: ChannelFormat, label: typing.Optional[str] = None) -> Channel` | Add a new channel to a stack. |
| `Stack.remove_channel` | method | `remove_channel(channel_type: ChannelType) -> None` | Remove a channel from a stack. |
| `Stack.edit_channel` | method | `edit_channel(channel_type: ChannelType, channel_format: ChannelFormat, label: typing.Optional[str] = None) -> None` | Change the texture format and label of a channel. |
| `Stack.has_channel` | method | `has_channel(channel_type: ChannelType) -> bool` | Check if a channel exists in a stack. |
| `Stack.get_channel` | method | `get_channel(channel_type: ChannelType) -> Channel` | Get an existing channel from its type. |
| `TextureSet` | class | bases: private (same redaction as `UVTile`) | A `Substance 3D Painter` Texture Set. |
| `TextureSet.material_id` | attribute | `material_id: int` | Integer id of the Texture Set; public field (HTML class signature below). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: resources\python\modules\substance_painter\textureset.py.] |
| `TextureSet.__init__` | constructor | `__init__(material_id: int)` | HTML signature `TextureSet(material_id: int)` (`textureset\textureset.html`). |
| `TextureSet.from_name` | staticmethod | `from_name(texture_set_name: str)` | Get the Texture Set from its name. |
| `TextureSet.original_name` | property | `original_name() -> str` | The original name of the Texture Set, as it was when it was imported. |
| `TextureSet.name` | property | `name() -> str` | The name of the Texture Set. |
| `TextureSet.name` | property setter | `name(name: str) -> None` | Setter of the property above. |
| `TextureSet.description` | property | `description() -> str` | The description of the Texture Set. |
| `TextureSet.description` | property setter | `description(description: str) -> None` | Setter of the property above. |
| `TextureSet.is_layered_material` | method | `is_layered_material() -> bool` | Query if this Texture Set uses material layering. |
| `TextureSet.all_stacks` | method | `all_stacks() -> typing.List[Stack]` | List all the stacks from this Texture Set. |
| `TextureSet.get_stack` | method | `get_stack(stack_name: str = '') -> Stack` | Get a stack of this Texture Set from its name. |
| `TextureSet.get_resolution` | method | `get_resolution() -> Resolution` | Get the Texture Set resolution. |
| `TextureSet.set_resolution` | method | `set_resolution(new_resolution: Resolution)` | Set the resolution of the Texture Set. |
| `TextureSet.has_uv_tiles` | method | `has_uv_tiles() -> bool` | Check if the Texture Set uses the UV Tiles workflow. |
| `TextureSet.uv_tile` | method | `uv_tile(u_coord: int, v_coord: int) -> UVTile` | Get the Texture Set UV Tile at (u, v) coordinates. |
| `TextureSet.all_uv_tiles` | method | `all_uv_tiles() -> typing.List[UVTile]` | Get the list of the Texture Set UV Tiles, ordered by U then V coordinates. |
| `TextureSet.get_uvtiles_resolution` | method | `get_uvtiles_resolution() -> typing.Dict[UVTile, Resolution]` | Get all UV Tiles that have a different resolution from the Texture Set, associated to their effective resolution. |
| `TextureSet.set_uvtiles_resolution` | method | `set_uvtiles_resolution(resolutions: typing.Dict[UVTile, Resolution])` | Set the resolution of the given UV Tiles to the associated resolution. |
| `TextureSet.reset_uvtiles_resolution` | method | `reset_uvtiles_resolution(uvtiles: typing.List[UVTile])` | Reset the resolution of the given UV Tiles to the parent Texture Set's resolution. |
| `TextureSet.all_mesh_names` | method | `all_mesh_names() -> typing.List[str]` | Get the list of meshes of the Texture Set. |
| `TextureSet.get_mesh_map_resource` | method | `get_mesh_map_resource(usage: MeshMapUsage) -> typing.Optional[substance_painter.resource.ResourceID]` | Query the Mesh map for the given usage of the Texture Set. |
| `TextureSet.set_mesh_map_resource` | method | `set_mesh_map_resource(usage: MeshMapUsage, new_mesh_map: typing.Optional[substance_painter.resource.ResourceID]) -> None` | Replace the Mesh map for the given usage of the Texture Set. |
| `set_resolutions` | function | `set_resolutions(texturesets: typing.List[TextureSet], new_resolution: Resolution)` | Set the same resolution to multiple Texture Sets. |
| `all_texture_sets` | function | `all_texture_sets() -> typing.List[TextureSet]` | List all the Texture Sets of the current project. |
| `get_active_stack` | function | `get_active_stack() -> Stack` | Get the currently paintable Texture Set stack. |
| `set_active_stack` | function | `set_active_stack(stack: Stack) -> None` | Set the Texture Set stack to be currently paintable. |

## `substance_painter.ui`

Qt (PySide6) UI integration: main window, docks, menus, toolbars, layouts, UI modes. Source: `resources\python\modules\substance_painter\ui.py`; HTML: `resources\python-doc\substance_painter\ui.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `UIMode` | enum (native) | Members: `Edition`, `Visualisation`, `Baking` | UI configurations enumeration. |
| `ApplicationMenu` | enum (native) | Members: `File`, `Edit`, `Mode`, `Window`, `Viewport`, `Help` | Standard application menus enumeration. |
| `show_main_window` | function | `show_main_window()` | Show Substance 3D Painter main window in the windowing system and give it the focus. |
| `get_main_window` | function | `get_main_window() -> PySide6.QtWidgets.QMainWindow` | Get access to Substance 3D Painter main window. |
| `get_layout` | function | `get_layout(mode: UIMode) -> bytes` | Get Substance 3D Painter layout state for the given UI mode. |
| `get_layout_mode` | function | `get_layout_mode(layout: bytes) -> UIMode` | Get the Substance 3D Painter UI layout mode of a given state. |
| `set_layout` | function | `set_layout(layout: bytes) -> UIMode` | Restore a Substance 3D Painter layout state obtained with get_layout. |
| `reset_layout` | function | `reset_layout(mode: UIMode)` | Reset Substance 3D Painter layout to default for a selected UI mode. |
| `add_dock_widget` | function | `add_dock_widget(widget: PySide6.QtWidgets.QWidget, ui_modes: int = UIMode.Edition) -> PySide6.QtWidgets.QDockWidget` | Add a widget as a QDockWidget to the main window. |
| `add_plugins_toolbar_widget` | function | `add_plugins_toolbar_widget(widget: PySide6.QtWidgets.QWidget)` | Add a widget to the plugins toolbar. |
| `add_menu` | function | `add_menu(menu: PySide6.QtWidgets.QMenu)` | Add the given menu to the application main window. |
| `add_toolbar` | function | `add_toolbar(title: str, object_name: str, ui_modes: int = UIMode.Edition) -> PySide6.QtWidgets.QToolBar` | Create and add a toolbar to the application main window. |
| `add_action` | function | `add_action(menu: ApplicationMenu, action: PySide6.QtGui.QAction)` | Add the given action to the given application menu. |
| `delete_ui_element` | function | `delete_ui_element(element: PySide6.QtWidgets.QWidget)` | Delete a UI element. |
| `get_current_mode` | function | `get_current_mode() -> UIMode` | Get the current UI mode. |
| `switch_to_mode` | function | `switch_to_mode(mode: UIMode) -> None` | Switch to some UI mode. |

## `substance_painter_plugins`

Plugin discovery/start/stop/reload (separate top-level module). Source: `resources\python\modules\substance_painter_plugins.py`; HTML: `resources\python-doc\plugins\substance_painter_plugins.html`.

| Symbol | Kind | Signature / fields / members | Purpose |
|---|---|---|---|
| `path` | attribute | = [] | list: A list of strings that specifies the search path for plugins. |
| `plugins` | attribute | = {} | dict: Currently started plugins. |
| `start_plugin` | function | `start_plugin(module)` | Start the given `Substance 3D Painter` plugin. |
| `close_plugin` | function | `close_plugin(module, gc_collect = True)` | Close the given `Substance 3D Painter` plugin. |
| `is_plugin_started` | function | `is_plugin_started(module)` | Check if the given plugin is currently started. |
| `reload_plugin` | function | `reload_plugin(module)` | Reload a plugin and start it. |
| `startup_module_names` | function | `startup_module_names()` | List the names of the available *startup* modules. |
| `plugin_module_names` | function | `plugin_module_names()` | List the names of the available *plugins* modules. |
| `load_startup_modules` | function | `load_startup_modules()` | Load all startup modules. |
| `close_all_plugins` | function | `close_all_plugins()` | Close all started plugins. |
| `update_sys_path` | function | `update_sys_path()` | Update `sys.path` according to :obj:`substance_painter_plugins.path` and `SUBSTANCE_PAINTER_PLUGINS_PATH` environment variable. |
