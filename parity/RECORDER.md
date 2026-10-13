# Painter oracle recorder

Work package P0-RECORDER (`docs/dag.md`), task `phase0.3_painter-oracle-recorder`. Code: `tools/parity/recorder/`; tests: `tests/parity/recorder/`. It records Painter goldens as defined by `CONTRACT.md` §6 and `docs/architecture/14-parity-testing.md` §2, through Painter's **documented** Python API only (approved source A-PYDOC). It never uses the community MCP bridge or a private interface, and it never reads Painter's shipped sources.

## 1. How it talks to Painter

- Painter runs on the owner's machine, started with `--enable-remote-scripting` (by the operator, or by the recorder's launcher, §10). Its documented remote control (Python API guide *Remote control / headless*) accepts `POST http://localhost:60041/run.json` with `{"python": <base64 source>}` and answers with the JSON value of an expression.
- The recorder sends `painter_side.py` once into a private namespace, then calls one operation per request. Painter loads projects asynchronously, so the host polls readiness (`project.is_in_edition_state()`, `project.is_busy()`) between requests.
- Software identity: `application.version()` and `version_info()` expose no finer build number, so `build_id` is `<version>+js-api.<alg.version.api>` (documented JavaScript API version through the documented `js.evaluate`), e.g. `12.1.0+js-api.1.1.20`. A golden's manifest must name this build or the recorder refuses (goldens are immutable per build).
- Build guard (decision 037): the running build must be the build of the current envelope or of the candidate envelope being recorded (`parity/envelopes/registry.json`). An unseen build refuses the command and starts the envelope refresh (§10); no other path passes the guard.
- Environment record (decision 034 (a)): every run carries the environment of its session: Painter build, GPU model and driver version (Windows CIM `Win32_VideoController` `Name`, `DriverVersion`; every adapter, sorted, joined with ` | `), OS build (`<major>.<minor>.<build>.<UBR>` from the registry), the SHA-256 of the colour configuration (the documented `OCIO` / `PAINTER_ACE_CONFIG` selection the painter side already reads, plus the SHA-256 of each file it names), the recorder version (`uzp-recorder/1+src.<digest of the recorder sources>`), and for Iray references the operator id. A field that cannot be read is `unknown`. Nothing new is asked of Painter: no symbol was added to `documented_symbols.json`.
- Session id: a random id kept in Painter's Python globals. It survives reconnects and changes when Painter restarts, which is how separate sessions are told apart.
- Safety: the recorder refuses to start when a project is already open. It creates a throwaway project from inputs copied into its work directory, saves only there, and closes the project when it finishes or fails.

## 2. Jobs

A job is the golden's public manifest (`golden-public.json`) with `private_records` empty, e.g. `parity/manifests/tier0/recorder-sample/blend-multiply-plane.json`. Input hashes are checked before Painter is touched. Steps must be numbered 1..n, start with `project.create`, and put every state step before the captures. Only this vocabulary is replayed (every name is a documented symbol):

| Call | Arguments |
|---|---|
| `substance_painter.project.create` | `mesh` (input id); optional `normal_map_format`, `tangent_space_mode`, `project_workflow`, `default_texture_resolution`, `import_cameras`, `mesh_unit_scale`, `template` (a shipped template's identifier, §8) |
| `substance_painter.layerstack.insert_fill` | `position: "top"` (optional `texture_set`: that set's stack, else the active stack), or `above_step` / `below_step` (the step that inserted the reference node), or `inside_step` with `stack` (`Substack`, `Content`, `Mask`; `InsertPosition.inside_node`): a fill layer, or a fill effect in a content or mask stack |
| `substance_painter.layerstack.insert_group`, `.insert_levels_effect` | the insert positions of `insert_fill` |
| `substance_painter.layerstack.insert_filter_effect` | the insert positions, and `filter_search` (a documented `resource.search` query; the first result is used and its URL recorded) |
| `substance_painter.layerstack.FillEffectNode.set_source` | as `FillLayerNode.set_source`; `channel: null` in a mask stack |
| `substance_painter.layerstack.FillEffectNode.active_channels`, `FilterEffectNode.active_channels` | `node_step`, `channels` |
| `substance_painter.layerstack.LevelsEffectNode.affected_channel` | `node_step`, `channel` |
| `substance_painter.layerstack.LevelsEffectNode.set_parameters` | `node_step` and any of `input_min`, `input_max`, `gamma`, `output_min`, `output_max` (a number, used for R, G and B on a colour channel, or [r, g, b]), `clamp` |
| `substance_painter.layerstack.FillLayerNode.set_projection_parameters` | `node_step`, `filtering_mode` (`BilinearHQ`, `BilinearSharp`, `Nearest`), `uv_wrapping_mode`, `scale_mode` (`Factors`), `scale`, `rotation`, `offset` (`UVProjectionParams`) |
| `substance_painter.textureset.Stack.add_channel`, `.edit_channel` | `channel`, `format` (a `ChannelFormat` member); optional `texture_set`, else every texture set |
| `substance_painter.layerstack.FillLayerNode.active_channels` | `node_step`, `channels` |
| `substance_painter.layerstack.FillLayerNode.set_source` | `node_step`, `channel`, and either `color` [r, g, b] with optional `color_space` (`sRGB`, `Working`, `Raw`) or `resource` (a `resource://` URL, `resource.ResourceID.from_url`) or `resource_step`, an imported bitmap, with optional `color_space` (`sRGB`, `Working`, `Raw`, `LegacyColorSpace.Linear`, `LegacyColorSpace.sRGB`; set by the documented `SourceBitmap.set_color_space`, decisions 087 and 156); the readback records a uniform colour, a bitmap's colour space, or every `properties.Property` of a substance source (`value`, `widget_type`, `label`) |
| `substance_painter.source.SourceBitmap.set_color_space` (attempted, decision 156) | `node_step` (an `insert_fill` step), `channel` (`null` for a fill effect in a mask stack), `color_space` (as for `set_source`); a state step whose refusal is the observation: the record's effective defaults hold `set_color_space.<step>` as `applied: true`, or `applied: false` with what Painter raised, and the golden is still recorded |
| `substance_painter.layerstack.Node.set_blending_mode` | `node_step`, `blending_mode`, `channel` |
| `substance_painter.layerstack.Node.set_opacity` | `node_step`, `opacity`, `channel` |
| `substance_painter.textureset.set_resolutions` | `width`, `height` (may differ, e.g. 256 × 128); optional `texture_set`: only that set (`TextureSet.from_name`), else every texture set. Each set's resolution is in the template capture of both recordings |
| `substance_painter.display.Camera.<property>` | `value` (`projection_type`, `position`, `rotation`, `field_of_view`, `focal_length`, `focus_distance`, `aperture`, `orthographic_height`) |
| `substance_painter.display.set_environment_resource` | `environment` (input id, imported with `resource.import_project_resource`) |
| `substance_painter.display.set_tone_mapping` | `function` (`Linear`, `ACES`) |
| `substance_painter.resource.import_project_resource` | `input` (input id), `usage` (`TEXTURE`, `GENERATOR`, `SMART_MATERIAL`); the imported resource is kept for later steps and its URL recorded |
| `substance_painter.textureset.TextureSet.set_mesh_map_resource` | `usage` (a `MeshMapUsage` member), `resource_step` (the import step); optional `texture_set`, else every texture set; readback `get_mesh_map_resource` |
| `substance_painter.layerstack.LayerNode.add_mask` | `node_step`, `background` (`Black`, `White`) |
| `substance_painter.layerstack.insert_generator_effect`, `.insert_smart_material` | the insert positions of `insert_fill`, and either `resource` (a `resource://` URL) or `resource_name` + `resource_usage` (optional `resource_context`): exactly one `resource.search` result with that GUI or identifier name and usage, its URL recorded. Readbacks: the generator's `get_source` (every `Property` described, presets, image inputs and outputs); the smart material's structure (`GroupLayerNode.sub_layers` walk with names, types, sources and effects), private like every readback |
| `substance_painter.source.SourceSubstance.set_parameters` | `node_step` (a generator effect, or a fill with `channel`), `parameter`, `value` (booleans as 0/1, lists as tuples); readback: the generator's `get_source` |
| `substance_painter.baking.BakingParameters.set` | `parameter` (a key of `BakingParameters.common()`, or of `baker(usage)` when `usage`, a `MeshMapUsage` member name, is given) and exactly one of `value` (a list is passed as a tuple), `enum_label` (converted with `Property.enum_value`) or `input` (input id with a path, passed as its `file:///` URL; `HipolyMesh` accepts only `input`); optional `texture_set`, else every texture set; readback `Property.value()` |
| `substance_painter.baking.BakingParameters.set_enabled_bakers` | `usages` (`MeshMapUsage` member names); optional `texture_set`; readback `get_enabled_bakers` |
| `substance_painter.baking.bake_async` | optional `texture_set`, else every texture set in turn; readback `get_mesh_map_resource` of every usage enabled at bake time |
| `substance_painter.export.export_project_textures` (capture) | `maps` (`<mapType>/<name>:<RGB|RGBA|L>`, e.g. `documentMap/basecolor:RGB`, `meshMap/normal_base:RGB`), `bit_depth`, `padding`; optional `file_format` (png), `dithering`, `dilation`, `size_log2`. A map name holding a `/` (`1/ior`) is written as `_over_` (`$textureSet_1_over_ior`), so Painter writes no sub-folder |
| `substance_painter.export.list_project_textures` (export probe, decision 087) | `config`: the input id of an authored `recipe_json` input holding a documented `json_config` without `exportPath` |
| `substance_painter.export.list_predefined_export_presets` (capture) | none; records each preset's `name` and `url` |
| `substance_painter.export.list_resource_export_presets` (capture) | none; records each preset's `resource_id` (`url`, `context`, `name`, `version`) |
| `substance_painter.export.PredefinedExportPreset.list_output_maps` (capture) | `texture_set` (its stack is passed); optional `preset` (a name): that preset only, else every preset Painter lists; recorded by preset name with its `url` and `output_maps` (or what that preset's call raised) |
| `substance_painter.export.ResourceExportPreset.list_output_maps` (capture) | `preset` (a `resource://` URL; `ResourceExportPreset(ResourceID.from_url(preset))`, no stack) |
| `substance_painter.source.SourceBitmap.list_available_color_spaces` (capture) | `node_step` (an `insert_fill` step), `channel` (`null` for a fill effect in a mask stack); records the available colour spaces and `get_color_space()`, each as `{class, name}` (`GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`, `NormalColorSpace` or `str`) |
| `substance_painter.layerstack.FillLayerNode.get_projection_parameters` (capture, decision 156) | `node_step` (an `insert_fill` step); records the fill's UV projection as Painter holds it, e.g. its default filtering when no step set it |
| `substance_painter.baking.BakingParameters.common` (capture, §8) | none |
| `substance_painter.baking.BakingParameters.baker` (capture, §8) | `usage` (a `textureset.MeshMapUsage` member name) |
| `substance_painter.baking.BakingParameters.get_curvature_method`, `.get_enabled_bakers`, `.is_textureset_enabled` (captures, §8) | none |

Enum arguments accept only the documented member names listed in `painter_side.py`.

## 3. Texture goldens (Tiers 0–2b)

`python -m tools.parity.recorder record <manifest.json>`

1. The state steps are applied once. Effective defaults are read as they appear (each new fill layer before it is edited, and the channel set `project.create` produced) and go into `key.effective_defaults`.
2. Recording `r1` (`same_session`): template capture (texture sets, stacks, channel formats), a readback of every property the sequence set (an exception Painter raises is recorded as `raised`), then each export.
3. The project is saved (Full) in the work directory as `golden.spp`, or under the file stem the manifest names in the setting `project.file_name` (`applied_by: recorder_api`, e.g. `golden.dotted` for a project name holding dots, decision 093), closed and reopened; layers are found again at their recorded place in the stack.
4. Recording `r2` (`after_save_reopen`): the same captures.

**Readiness and current output.** Before each export the recorder waits until the project is in edition state and not busy; `export_project_textures` computes what it writes. It then writes a fence file and exports into a new, empty directory. It accepts the export only if that directory holds exactly the files the call reported and each was written no earlier than the fence (same filesystem clock). Anything else, such as a stale, extra or missing file, refuses the whole golden and writes nothing.

**Output ids.** An exported map's output id is `<texture set>[/<stack>]/<map>`, with `/` in the map name written `_over_`. A map that two export steps of the golden name (a second export in one session measures Painter's run-to-run noise) is keyed by step: `<texture set>[/<stack>]/<map>/step<n>`. Every other id is unchanged, so no earlier record id changes (decision 087).

**Export probes (decision 087).** A probe's configuration is an authored `recipe_json` input (hash-checked like every input). The recorder gives it a fresh `exportPath` per probe and recording and calls `list_project_textures`, recording the returned files relative to that directory (a path outside it as `../...`, never read) or the raised error (`probe/s<n>/list`). When the dry run succeeds it writes a fence, calls `export_project_textures` and records the status, message and files, or the raised error, together with the directory content and its difference from the reported files (`probe/s<n>/export`); every file present becomes a blob (`probe/s<n>/<file>`). A difference is an observation, not a refusal; a file older than the fence, or a link, still refuses the golden.

**Captures (recordings R5-R7, decision 100).** The export-preset captures and the bitmap colour-space capture are read, like export probes, after the state steps in both recordings, in step order with the export steps and probes. Each is a private `api_readback`, `presets/s<n>` or `color-spaces/s<n>`. What Painter raises (an unknown preset, an invalid stack, a source that is not a bitmap) is recorded as `raised` and does not refuse the golden. Malformed arguments refuse the golden before Painter is touched. A texture golden may consist of captures and probes alone.

**Storage format** is measured from the file: PNG IHDR and colour chunks, and the OpenEXR channel list. If the file states no encoding, the encoding comes from the source channel's documented storage (`textureset.ChannelFormat`: `sRGB8` is sRGB, the others are linear), and `export_settings.encoding_basis` says which applies. A `meshMap` export that states no encoding is linear with basis `baked_mesh_map`: a baked mesh map stores data, not colour. A converted virtual map (Diffuse, Specular, Glossiness, Glossiness2, Unity4Diff, Unity4Gloss, reflection, 1/ior, f0, View_2D) and an export probe's file derive from no single channel: when the file states no encoding the record says `undetermined` (basis `converted_virtual_map` or `export_probe`) and makes no colour-space claim (decision 087).

**Operator step (UI-set values; decisions 029, 047; `texture_sheet.py`).** Some Tier 0 cases depend on values that only Painter's UI can set. Their manifest names each value in `applied_settings` with `applied_by: operator_settings_sheet`, one entry per target:

- `Texture Set Settings/Height to normal method (<texture set>)`, valued `Sharp` or `Smooth (Sobel)`;
- `Layers/Blending mode (step <n>, <channel>)`, the node inserted by step n, in one channel (e.g. `Passthrough`, which the documented API cannot set: the python-doc's `BlendingMode.PassThrough` does not exist at runtime);
- `Texture Set List/Name (<texture set>)`, the texture set imported under that name, renamed to the value (letters, digits, `_`) with a double click on its row's name in the Texture Set List: the documented API cannot rename a texture set (decision 093). The name is also read through the documented `TextureSet.name` and `original_name` (a string at runtime in 12.1.5), before `r1` and after the reopen.

`record --operator ui` (or `console`) applies them after the state steps and before `r1`. The recorder makes the target visible through the documented `textureset.set_active_stack` and asks the operator to set the value and enter what the widget then shows. A layer's mode is also read through `Node.get_blending_mode`. Any value other than the sheet's refuses the golden before anything is written. After the reopen the operator reads the values again and changes nothing. Both recordings carry the entries (`operator_recorded_settings`) and one panel image per target (`settings_panel_evidence`), all private. A golden with sheet entries is refused without `--operator`. The envelope refresh, stability study and canary record such goldens with the UI operator. The UI operator (`painter_ui.py`) brings a tabbed dock forward by UI Automation tab selection, which only navigates. It sets values with real clicks, and before each click it checks that the point belongs to Painter's own window or to the menu Painter opened. Painter must be visible on screen. Texture goldens run with Legacy colour management (no `OCIO`), like the corpus. A manifest that names `OCIO` in `applied_settings` (`applied_by: environment_variable`, the configuration's path under Painter's directory) is refused unless the session runs that configuration; the read-back of the qualification sphere's template-default material was the first such golden (decision 068). Conversely, a manifest that names no `OCIO` is recorded only in a Legacy session (no `OCIO`, no `PAINTER_ACE_CONFIG`); any other session is refused with a request to restart Painter without them (decision 099).

**Baking jobs** (`phase0.9_normal-convention-fixture`). Bake steps are state steps, applied once before `r1`; a `BakingParameters.set` or `set_enabled_bakers` step after the last `bake_async` is refused. Each `set` step sets one parameter with one documented `BakingParameters.set` call per texture set. The high-poly mesh is an input of the manifest (`parameter: "HipolyMesh"`, `input: <input id>`): the recorder stages it and passes `file:///` followed by the staged file's POSIX path, the form of the documented `QUrl.fromLocalFile(...).toString()` example. A path holding a character that a URL would percent-encode, such as a space, refuses the golden. For `bake_async`, `painter_side.py` connects a handler for `event.BakingProcessEnded` to the documented dispatcher, launches the bake and returns. The host then polls the `baking_state` operation (which launches the next texture set when one ends) for up to 1800 s, and waits for readiness. A status other than `Success`, or no end in time, refuses the golden. The handler is disconnected when the bake ends or the project closes. `key.effective_defaults.bakes` records, per bake step, the status of each texture set and the bakers enabled at bake time. Painter's bake backend cannot be read or fixed through the documented API, so `key.bake_backend` stays `null` and the public manifest lists it in `uncontrolled_settings`.

## 4. Iray references (Tier 3)

`python -m tools.parity.recorder iray <manifest.json> --condition separate_session --operator-id <id>` (twice, restarting Painter in between), then `--condition k_times_samples --k 4 --operator-id <id>`. The staged references of one golden must share one envelope; a reference staged under another envelope refuses the assembly. This implements `07-preview-and-render-parity.md` §2.2 as procedure `iray-capture/1`. The procedure, its answers to 07 §2.1 and its qualification status are in `parity/reports/phase0/iray-capture-procedure.md`; no render golden is admitted before it is qualified.

- The sheet must name the procedure and the pixel route: settings `capture.procedure` = `iray-capture/1` and `capture.route` = `save_render` (`applied_by: recorder_api`). A camera rotation other than zero also needs `capture.camera_rotation_order`, the Euler order the probe confirmed (`ZYX`).
- **Fixed pipeline (decision 038).** References use the Assets3D render comparison standard. Start Painter with `OCIO` naming its `resources\ocio\substance\config.ocio`, in a fresh session per reference. The sheet adds:
  - `capture.bits_per_channel` (16);
  - `capture.background_srgb8` (`89,89,89`), the background the render must show in 8-bit codes;
  - `capture.display_transform` (`Default - sRGB`), which adds an image of the viewport's display-transform selector to the panel evidence.
- **UI operator (decision 029).** `--operator ui` lets `tools/parity/recorder/painter_ui.py` operate the panels by Windows UI automation instead of a person at the console. It reads each widget back after commit and drives the Save Render dialog. Painter must be visible on screen while it runs. The default is `--operator console`.
- The recorder applies the documented settings (camera, environment, tone mapping). It reads every documented render setting back into `key.render_state`, together with `project.get_scene_bounding_box()`, and switches to `ui.UIMode.Visualisation`.
- **Operator form.** The settings sheet is the manifest's `applied_settings` with `applied_by: operator_settings_sheet`, named `<panel>/<setting>`. It must include `Iray Settings/Min Sample` = `Max Sample` (S), `Max Time` (unit `s`, `min` or `h`), `Width` and `Height`. For each setting, the operator types the value the panel shows; any value that differs from the sheet (k·S for Min/Max Sample on the k run) refuses the reference. The operator also gives one PNG or JPEG image of each panel. Entries and images become private outputs (`operator_recorded_settings`, `settings_panel_evidence`).
- **Convergence.** Accepted only when the operator reports Status `Done`, Iterations equal to the sample count, and a Rendering time below Max Time.
- **Capture.** The recorder writes the fence, and the operator uses Save Render to save to the path it names. Current-frame verification: the file is the only one in a new directory, written after the fence, at the overridden resolution (square), and its silhouette matches the job's mesh projected from the read-back camera (`tools/parity/render_procedure/projection.py`; Perspective only, a 2-pixel don't-care band around the outline). The scene bounding box must equal the mesh file's. Every background pixel must hold one value and no object pixel may hold it. If the file states no encoding, the sheet must give it as setting `capture.encoding`.
- **Probe.** `python -m tools.parity.recorder iray-probe --ref-match-hdri <exr> [--operator ui]` runs the probe session of the procedure report §3. Its evidence goes to `UZP_ORACLE_WORK\iray-probe\<run>\probe.json`; `iray-probe-analyse <dir>` re-runs the analysis without Painter.
- **Series (decision 046).** `python -m tools.parity.recorder iray <manifests or directories> --condition <c> --launch --operator ui --operator-id <id> [--session-file <file>]` records one reference per manifest, each in a Painter process it starts and stops itself (`OCIO` must be set in the shell that runs it). A golden whose staging already holds the condition (two separate sessions, or the k·S reference) or whose manifest already names private records is skipped, so a series can be re-run after an interruption; a refused reference is reported and the series goes on (exit status 2).
- **Stability probe (decision 062).** `--condition same_session` records two S renders of one project in one Painter session: after the first Save Render the recorder nudges the camera's field of view by 1 degree and puts it back through the documented API (Iray restarts, as in the procedure probe's same-session repeat), requires the read-back render state to equal the first, waits for Done and saves again. The recordings are `s-<session>-1` and `s-<session>-2`. The stability goldens of decision 052's capture request (`phase0/iray-stability/`, `references.STABILITY_FIXTURES`) hold two S renders and no k·S render, so they are never assembled into a golden record; `python -m tools.parity.render_procedure stability-admit` puts their blobs into the private store under their manifests, and `python -m tools.parity.render_fits probe --work <dir>` measures them.
- **Session environment.** A `set_environment_resource` step with `session_environment` (a SHA-256) and `file_name` imports a file as a session resource (`resource.import_session_resource`), the `ref_match` preset's procedure. The file is not a repository input: the recorder is given it with `--session-file`, checks its hash, stages it under `file_name` and lists it in `key.resource_hashes` as `session:<sha256>`.
- **OCIO guard.** A sheet that names `capture.display_transform` is refused unless Painter's colour management is `ocio`: a Legacy project shows the same 89,89,89 background, so the canary alone would not catch it.
- References are staged in the work directory. When two `separate_session` references (from different Painter processes) and one `k_times_samples` reference have identical keys, the record is written. Different keys refuse assembly, because the oracle is unstable.

## 5. Output: private inbox, public hashes

Records go to `UZP_ORACLE_INBOX` (default `%LOCALAPPDATA%\UzPainter\oracle-inbox`). Working files (staged inputs, throwaway `.spp`, exports, renders) go to `UZP_ORACLE_WORK` (default `%LOCALAPPDATA%\UzPainter\oracle-work`). The recorder refuses either directory if it lies inside the repository. One run per golden:

```
<inbox>/<golden_id with / as __>/<UTC stamp>-<session>/record.json     private record (golden-private.json, record_problems clean)
                                                      /blobs/<sha256>  every blob the record names, and the environment record
                                                      /manifest.json   public manifest with private_records filled
                                                      /READY           written last
```

`private_records` lists `golden-record` (the record file), `<recording>-<output>` for each blob and `oracle-environment` (kind `oracle_environment_record`: the canonical JSON of the record's `environment`, the public hash of the envelope), by SHA-256 and size. The study, the canary and a second envelope under one build put a prefix in front of every record id (§10), so no store entry is ever written twice. The private store CLI (`phase0.3_oracle-store-cli`, `python -m tools.parity.store record <repository manifest> --run <run>`) admits a READY run and merges those hashes into the repository manifest. Nothing recorded enters the repository.

## 6. Provenance check

`python -m tools.parity.recorder check [--python-doc <objects.inv>]`. This is also `tests/parity/recorder/test_provenance.py`. Over `tools/parity/recorder/*.py` it checks:

- nothing imports or names the MCP bridge;
- no attribute starting with an underscore is accessed;
- every `substance_painter` symbol used is in `documented_symbols.json`, which names the python-doc object that documents each one, and the list matches Painter 12.1.0's python-doc inventory where that is installed;
- in `painter_side.py`, every attribute read is a documented member or a builtin-type method, and there is no dynamic attribute access.

## 7. Acceptance run (2026-10-10, owner's machine)

The recorder ran `record parity/manifests/tier0/recorder-sample/blend-multiply-plane.json` on Painter 12.1.0 (`12.1.0+js-api.1.1.20`, Legacy colour management, embedded Python 3.13.9). It ran twice, in two separate Painter sessions, and the second run used the final code. Each run wrote one inbox run with two recordings, `same_session` and `after_save_reopen`:

- each record validates against `golden-private.json` (no `record_problems`), and each manifest against `golden-public.json`;
- each manifest lists the record's SHA-256 and the 16-bit PNG BaseColor export of both recordings;
- all four exports are byte-identical.

Painter was driven only through the documented remote control, under the shared Painter lock, on throwaway projects. The substance-source `Property` readback is covered by the unit tests only: the sample uses uniform-colour fills.

## 8. Baking defaults and project templates (Tier 0)

Task `phase0.6_tier0-defaults-templates`; code: `tools/parity/recorder/defaults.py`; tests: `tests/parity/recorder/test_defaults_templates.py`; jobs: `parity/manifests/tier0/defaults-templates/`. Both captures are private oracle records (`effective_default_capture`, `template_capture` outputs). The public manifests carry the instruction sequence, the template identifiers, the Painter build id and the record hash. The default table and template JSON UzPainter ships are written separately by UzmiGames, and each entry names its provenance (`06-baking.md` §2, `03-project-model.md` §2).

**Baking defaults:** `python -m tools.parity.recorder record-defaults <manifest.json>`. The job creates one project from the mesh only, so every project setting keeps Painter's default. It must then capture `common()` and `baker(usage)` for all ten `MeshMapUsage` bakers. On every texture set, each key of the returned dict is described with every documented `properties.Property` getter: `value`, `name`, `short_name`, `label`, `widget_type`, `enum_values` and `properties`, plus `enum_value(label)` for each label `enum_values()` returns. A getter that raises is recorded under `raised`. The optional captures `get_curvature_method`, `get_enabled_bakers` and `is_textureset_enabled` record the remaining baking state. The recorder refuses a capture in which a key is not fully described or an enum label has no `enum_value` read. A baker that exposes no keys, and an enumeration with no labels, are recorded as Painter reports them. There are three recordings: `r1` on a fresh project, `r2` after save and reopen, and `r3` on a second fresh project in the same session. All three must report the same keys.

**Templates:** `python -m tools.parity.recorder list-templates` prints the shipped templates, and `record-templates <manifest.json>` records them. A shipped template is a `.spt` file of the documented application shelf (`resource.Shelves.application_shelf().path()`), identified by its shelf-relative POSIX path. The recorder lists file names only and never reads, hashes or copies a template. Painter opens each one through `project.create(template_file_path=...)` (coordinator ruling, 2026-10-10). The job is one `project.create` step per template, with `mesh` and `template` only, so the template's own settings apply. It must name exactly the shipped templates. Each recording starts with the shipped list (`templates/shipped`) and then gives, per template, the texture sets, stacks, channels and `ChannelFormat` (§3 template capture): `r1` as created, `r2` after save and reopen. If the documented API refuses a template, the refusal is recorded twice as `accepted: false` together with the exception.

**First recording (2026-10-10, owner's machine, Painter `12.1.0+js-api.1.1.20`, under the shared Painter lock).** One Painter session recorded both goldens. The baking defaults have three recordings, and `r2` and `r3` are identical to `r1`. The application shelf ships 26 templates. Painter accepted all 26, and the `r2` captures are identical to `r1`. Both runs were admitted with `python -m tools.parity.store record --run`, and `python -m tools.parity.store verify parity/manifests/tier0/defaults-templates` and the whole-store `verify` both exit 0.

## 9. Tier 0 API probes

Task `phase0.6_tier0-api-probes`. Code: `tools/parity/recorder/probes.py` (host) and `painter_probes.py` (inside Painter); tests: `tests/parity/recorder/test_api_probes.py` with the fake `fake_probe_painter.py`. Manifests: `parity/manifests/tier0/api-probes/<probe>.json`, one golden per probe, golden id `tier0/api-probes/<probe>`; a capability-manifest `tier_evidence` cites one as `T0-api-probes/<probe>.json` (`docs/architecture/10-python-api.md` §3). Authored inputs: the plane mesh and the 16×16 PNGs in `parity/fixtures/api-probes/`.

`python -m tools.parity.recorder.probes record <manifest.json>`

`painter_probes.py` is executed into a copy of `painter_side.py`'s namespace: it reuses its helpers and registers its operations in the same `OPERATIONS` table, and its own names never replace `painter_side.py`'s.

**Instruction sequence.** `project.create`, then state steps, then probe steps, then optional `export_project_textures` captures (§3).

- *State steps* (`insert_fill`, `insert_group`, `insert_levels_effect`, `insert_compare_mask_effect`, `insert_color_selection_effect`, `Node.set_name`, `set_visible`, `set_blending_mode`, `set_opacity`, `FillLayerNode.active_channels` with `channels`, `set_source`, `set_projection_mode`, `set_projection_parameters` (UV), `SourceBitmap.set_color_space`, `LayerNode.add_mask`, `enable_mask`, `LevelsEffectNode.affected_channel` with `channel`, `set_parameters`, `resource.import_project_resource`, `textureset.set_resolutions`, `TextureSet.set_mesh_map_resource`) run once. Positions are `position: "top"`, `above_step`, `below_step`, or `inside_step` with `node_stack`. A `channel` of `null` is passed as `None`.
- *Probe steps* are the readbacks (getters, and `active_channels`/`affected_channel` without a value) and every edit marked `probe: true`. They run again in every recording. An edit is marked as a probe when its outcome, usually a documented error, is the thing being observed.
- Each outcome is recorded as an `api_readback`: the value the call returned (enums by name, colours in working space, nodes by type and name, parameter dataclasses field by field), or `raised` with the exception class name and message. A step that raises does not stop the recording.

**Recordings.** `r1` (`same_session`) holds the outcomes of the state steps, then the probes and exports. The project is then saved (Full), closed and reopened. Each inserted node is found again by its place in the tree (root index, then `Substack`/`Content`/`Mask` index). `r2` (`after_save_reopen`) repeats the probes and exports. Every probe call resolves its node freshly through `layerstack.get_node_by_uid`. In each recording, `identity/s<step>` records whether the node kept the uid it had in `r1`, and whether that uid resolves to the node. The golden key holds the effective defaults of every inserted node, read before any step edits it.

**Lifecycle probe** (`lifecycle-events`, first step `event.Dispatcher.connect`). The procedure is fixed. The listed project events are connected, then two cycles run, each of create → save_as → close (`same_session`) followed by open → save → close (`after_save_reopen`). That gives four recordings. Each phase records the events dispatched during it, with `is_open()`, `is_in_edition_state()` and `is_busy()` read inside each callback. It also records the distinct readiness states polled until the phase completed, plus three settle polls. The callbacks are disconnected at the end.

| Probe | Observes |
|---|---|
| `fill-layer-readback` | Set→get of name, visibility, active channels, uniform and bitmap sources, bitmap colour space, per-channel blending and opacity, group blending, UV projection; BaseColor and Height exports |
| `mask-stack` | Mask-stack `None` rules for source, blending and opacity; channel arguments on the mask fill and `None` on the content layer; mask properties; a second `add_mask`; a mask levels effect; BaseColor export |
| `set-source-none-multichannel` | `set_source(None, …)` and `get_source(None)` on a fill layer and a content fill effect; `set_source` on an inactive channel |
| `active-channel-reset`, `active-channel-reset-superset`, `active-channel-order-control` | `active_channels` assigned again (same set, larger set) after `set_source`, against the channels-first control; source readback and BaseColor/Height exports |
| `insert-positions` | Every insertion the documented table forbids, repeated in each recording; two undocumented cases applied once; resulting structure |
| `textureset-project-readback` | Resolution, Normal/AO mesh-map resources, a resource reused for a second usage, `needs_saving`, file name, project name |
| `lifecycle-events` | Event order and readiness transitions of create/open, save and close |

Admission: `python -m tools.parity.store record parity/manifests/tier0/api-probes/<probe>.json --run <run>`, then `python -m tools.parity.store verify parity/manifests/tier0/api-probes`. `test_api_probes.py` checks that every manifest is admitted and that every probe output appears in at least two recordings of the stored record. Where there is no store, it skips that check and says why.

**First recording (2026-10-10, owner's machine, Painter `12.1.0+js-api.1.1.20`, under the shared Painter lock).** All nine probes were recorded in one Painter session and admitted with `python -m tools.parity.store record --run`. `python -m tools.parity.store verify parity/manifests/tier0/api-probes` and the whole-store `verify` both exit 0. Readbacks are equal across the recordings, except values that depend on the condition: the resource context of the reopened project instance, and the file path, project name and mesh-map resource context after a save. The `mask-stack` BaseColor export differs between `same_session` and `after_save_reopen` (4608 of 196608 values). Two runs reproduced the same pair of hashes. Its stability classification belongs to `phase0.7_tier0-stability-fits`.

**Observed probe goldens (R10, `requests/tier0/api-probes/phase1-*`; tests `test_api_probes_phase1.py`).** A probe golden whose step 2 is `event.Dispatcher.connect` is *observed*. Its new edit calls, applied once or with `probe: true` in both recordings, are:
`layerstack.delete_node` (`node_step`), `resource.update_layer_stack_resource` (`resource_step`, `new_resource_step`), `project.save_as` / `save_as_copy` (`work_file`, `mode`), `project.save` (`mode`), `project.reload_mesh` (`mesh` or `work_file`), `project.execute_when_not_busy`, `resource.reload_modified_resources_async` (`filter`, `resource_steps`, optional `rewrite_input` + `with_input`), `application.enable_engine_computations` (`enable`), `application.disable_engine_computations` (a `set_source` inside the context), and `export_project_textures` with `probe: true`. Its new getters are `Node.uid`, `get_node_by_uid`, `all_texture_sets`, `project.is_busy`, `engine_computations_status` and `is_reload_modified_resources_running`.

After every later step the recorder records:

- `s<n>/events`: the events dispatched since the previous step, each with the readiness state and `during_step` when it was dispatched inside the call;
- `s<n>/states`: `probe_state` polls (is_open, in_edition, busy, engine_computations), taken until the step's asynchronous calls have answered and then three more times.

Asynchronous calls are `reload_mesh` and `execute_when_not_busy`, whose callbacks are logged as events, and `reload_modified_resources_async`, which is pending while `is_reload_modified_resources_running()`. A call still pending after 600 s is recorded as `s<n>/pending`; the recording is not refused. `wait: false` folds a step's events into the next step's record.

Other rules:

- The host resolves `work_file` to a file in the recording's private `work-files` directory and lists those file names after every save step (`s<n>/files`).
- The host overwrites the staged input `rewrite_input` with `with_input` just before a resource reload.
- An `export_project_textures` with `probe: true` records Painter's result or error, then the files present once the step settled, with their SHA-256.
- Painter is never blocked in a loop: handlers connect through `event.DISPATCHER` and the host polls. At the end, `probe_finish` re-enables engine computations a probe disabled and disconnects the events.
- No documented getter reads the project's normal map format back.

**Host behaviour probes (decisions 095, 109, 110, 132).** Observed probes may also use:

- `project.create` arguments `mesh_maps` (input ids, passed as `mesh_map_file_paths`; an input's staged file keeps its id as stem, e.g. `uzp_plane_ambient_occlusion`) and `default_save_path` / `export_path` (plain folder names the host makes in the recording's work directory, passed in `project.Settings`).
- Edits: `insert_paint`, `insert_anchor_point_effect` (`name`), `LayerNode.remove_mask`, `set_mask_background`, `FillLayerNode.reset_source`, `set_symmetry_enabled`, `SourceUniformColor.set_color`, `SourceBitmap.reset_color_space`, `display.set_environment_resource` (`resource_step`, an import with usage `ENVIRONMENT`), `set_color_lut_resource` (`resource_step`, or none for `None`), `set_tone_mapping` (`function`), `display.Camera.<property>` with `value`, `resource.Shelves.add` (`name`, `folder`, `inputs`: the host makes the folder in the work directory with copies of the inputs), `Shelf.refresh` (`name`), and `project.close` / `project.open` (no argument: the file the close left; before a close the host keeps the inserted nodes' places, and after the open settled it finds them again, `s<n>/rebind`).
- Getters: `display.Camera.get_default_camera` (all eight properties), each `display.Camera.<property>`, `get_environment_resource`, `get_color_lut_resource`, `get_tone_mapping`, `project.get_scene_bounding_box`, `export.get_default_export_path`, `TextureStateEvent.cache_key_invalidation_throttling_period` (milliseconds), `Shelves.all`, `application_shelf`, `user_shelf`, `exists` (`name`), `Shelf.is_crawling` (`name`), `resource.search` (`query`; each result's identifier, GUI name and usages).
- `export_project_textures` with `probe: true` and `default_export_path: true`: the configuration has no `exportPath`; the result says where each file went (relative to the run's private directory, else as Painter gave it) and `s<n>/files` hashes those under the run.
- A shelf crawl is pending while `Shelf.is_crawling()` is true, and once a probe added a shelf every state poll carries `shelves_crawling`; an open is pending until the project is in edition and not busy. The events `ShelfCrawlingStarted` / `Ended` (with `shelf_name_argument`) and `CameraPropertiesChanged` can be connected. Shelves a probe added are removed after the project is closed (`Shelves.remove` needs no open project).
- A lifecycle probe whose step 1 has `timing: true` runs `create` and `open` with the step marker set to the phase (events dispatched inside the call carry `during_step`) while a second Python thread polls `is_busy()` and `is_in_edition_state()` about every millisecond until `ProjectEditionEntered`; `<phase>/thread_polls` records each change of state with its time and the poll count.
- A probe manifest that names `OCIO` is recorded only in a session started with that configuration, and one that names none only under Legacy, as for texture goldens.

## 9a. Pipeline-script goldens (Tier 1, decision 099)

Code: `tools/parity/recorder/script_run.py` (host) and `painter_scripts.py` (inside Painter, loaded like `painter_probes.py`); tests: `tests/parity/recorder/test_script_run.py`.

`python -m tools.parity.recorder record-script <manifest.json> --assets-root <Assets3D> [--launch]` records a golden whose instruction sequence uses the `uzmigames_pipeline_scripts` interface.

- **What a step is.** Each step runs one UzmiGames pipeline script (`uzmigames.pipeline.run_script`), byte-unchanged and pinned by SHA-256. It runs through the recorder's own remote control (`POST /run.json`), never through the community MCP bridge.
- **Inputs.** They live in the Assets3D repository and are named only by `assets3d_path` and SHA-256.
- **Checks before Painter is touched.** Every input is hash-checked under `--assets-root`. The job is refused on any missing file, any mismatch, or any step it does not know (create, `sync`, export, in that order).
- **Session.** Painter must run under the OCIO configuration the manifest names, with no project open.

**Adaptations.** There are two, and only these:

1. **Repointed arguments.** The inputs are copied into the private work directory. Each Painter-side script runs in a fresh namespace whose `open` maps exactly its one hard-coded arguments path to a copy of the arguments. In that copy:
   - `mesh`, `normal` and `ao` name the staged copies;
   - `dst` names a project in the work directory;
   - `out` names a fresh export directory;
   - every other key is unchanged.
2. **Transport swap for `sync`.** The layer-stack `sync` command runs host-side from its pinned bytes, with `__file__` set to its real path. Only its `execute(code)` is replaced by the recorder's remote control, under the same contract, so the code it sends to Painter is its own.

**Recordings.**
- `r1` (same session): create, sync, export.
- `r1-repeat` (same session): export again.
- `r2`: close, reopen the saved work project, export again.

Each export is verified like a texture export: fence, fresh empty directory, and exactly the files the script reports. Each script's `result` is recorded as a private readback under `uzmigames.pipeline.run_script`.

**Admission and regeneration.**
- Admit with `python -m tools.parity.store record <manifests/…/wand-v1.json> --run <run>`.
- Regenerate the requested manifest with `python -m tools.parity.recorder.script_run manifest --assets-root <Assets3D> --out <path>`.
- The Belt v5 request (`phase2/tier1/belt-v5`, phase2.9, decision 192) is written by the same command with `--pilot belt`. It pins the committed waist-v5 scripts and `stack-belt.json`, the round folder's arguments files, the mesh (with the material library its `mtllib` names), normal and AO those name, and the stack's bitmaps in `paint/masks-belt/`. A missing file refuses the command, which prints every missing path as JSON. Add `--store` to put every pinned input in the private store, so the request outlives Assets3D `_tmp` (decision 144). The round folder `_tmp/claude/cintura-v5/` was removed on 2026-10-12 and the owner must restore it before the request exists.

The scripts' own Painter calls are pinned, not checked symbol by symbol. `delete_node`, which the sync code uses, is probed by R10.

**Comparison (phase1.25, decision 124).** `tests/parity/tier1/wand_v1/runner.py` rebuilds the golden's job twice in UzPainter through the Assets3D adapter, with the same pins and the same staged inputs. `tools/parity/tier1/compare.py` then compares both rebuilds with the admitted golden. Run it as `python -m pytest tests/parity/tier1/wand_v1`; set `UZP_TIER1_REPORT=parity/reports/phase1/tier1-wand-v1.json` to write the report.

Belt v5 (phase2.9, decision 192) uses the same runner and comparison: `python -m pytest tests/parity/tier1/belt_v5` with `UZP_TIER1_REPORT=parity/reports/phase2/tier1-belt-v5.json`. The same file runs the Python-disabled MCP round (`UZP_MCP_ROUND_REPORT=parity/reports/phase2/belt-v5-mcp-round.json`). Until the request exists, `tests/parity/tier1/test_mcp_round.py` runs the round on the Wand v1 inputs as a stand-in for the tool only.

The report (`comparison-report.json`) keeps three results apart: oracle stability, UzPainter repeatability and equality to Painter. Structural differences fail and are listed: a refused export, a map on one side only, a differing storage format or shape. A golden that is not admitted, or one whose record or blobs are missing, is `oracle_unavailable`.

## 10. Oracle envelope: rolling refresh, stability study, canary

Task `phase0.9_oracle-envelope`, decisions 034 (envelope, study, canary) and 037 (rolling oracle). Code: `tools/parity/envelope/` and `tools/parity/recorder/{environment,launcher}.py`; tests: `tests/parity/test_oracle_envelope.py` (fake Painter only); report: `parity/reports/phase0/oracle-envelope.md` (generated, numbers and hashes only).

**Registry.** `parity/envelopes/registry.json` names the current envelope (the acceptance oracle: gates and verdicts use only it), the candidate being recorded, every promoted envelope as history (`current` or `superseded`, never deleted) and every quarantined candidate. The 12.1.0 corpus keeps `parity/manifests` as its manifest root; a promoted envelope's manifests live under `parity/envelopes/<dir>/manifests/` with the same relative paths. `<dir>` is the envelope id with every character outside letters, digits and `. _ ~ -` replaced by `_` (`painter-12.1.5+js-api.1.1.20` -> `painter-12.1.5_js-api.1.1.20`; `registry.envelope_directory`); every work, inbox, quarantine and drift-report path named after an envelope uses it, so a bake's staged mesh under it has a file URL that needs no percent-encoding. The registry, records and reports keep the id itself. The store already keeps one corpus per Painter build. `python -m tools.parity.envelope status` prints the registry; `tools.parity.envelope.registry.current_envelope()` is the accessor for other tools.

**Prerequisites** (owner's machine): Painter installed (default `C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe`, else set `UZP_PAINTER_EXE` or pass `--painter-exe`); no Painter running when `--launch` is used (the launcher refuses to start when the endpoint already answers and only ever stops the process it started); the Assets3D Painter lock held; the private store initialised (`python -m tools.parity.store init`), `UZP_ORACLE_INBOX` and `UZP_ORACLE_WORK` outside the repository (defaults under `%LOCALAPPDATA%\UzPainter`); Python with `numpy` and the OpenEXR binding (float exports are decoded for the diffs).

**Launcher.** Starts `<exe> --enable-remote-scripting`, waits up to 600 s until `http://localhost:60041/run.json` executes `1`, and stops by closing the project through the documented API (`project.close`), then ending the process it started (`terminate`, then `kill`): the documented API has no call that quits Painter.

### 10.1 Detection and refresh (decision 037)

`python -m tools.parity.recorder refresh --launch` (or without `--launch` against a running Painter). The local parity gate checks with `python -m tools.parity.envelope check` (exit 0 current, 3 refresh needed, 4 the build of a superseded envelope, 2 Painter unreachable) and refreshes with the same `refresh` command. Every recording command also reads the build first and starts the refresh on an unseen build (exit status 3).

1. Detection reads the running build and environment. Current build and envelope (or an environment the canary proved equivalent): nothing to do. Current build, other environment: the canary runs; exact equality records the environment as equivalent in the registry, any difference starts the refresh. Unseen build: the refresh starts. A superseded envelope's build is refused.
2. The candidate is entered in the registry (its build becomes recordable; the previous envelope stays current) with a ledger `<work>/envelopes/<dir>/candidate.json`; runs go to `<inbox>/envelopes/<dir>/`.
3. The ten canary goldens are recorded first and their drift is published (`oracle-envelope-drift-canary-<dir>.json`); then every other Tier 0-2b golden of the current envelope, always in full, each by its own recorder command under the candidate build. Record ids get the prefix `env-<n>-` only when the build already has an envelope.
4. Verification: before every call that is not a readiness poll the session checks the Painter build and session id; before every golden and at the end it re-reads the host environment (a field that differs or reads `unknown` is read again, three reads over 30 s: only a consistent other value is a change, a field that never reads back is unverifiable, and the abort names each field's expected and observed values); every run is checked for the candidate's build and envelope hash. A change, or an identity that cannot be read, aborts the candidate: the throwaway project is closed if it is still the recorder's process, the partial outputs move to `<work>/quarantine/<dir>/`, the registry records the reason, and detection restarts against the new build (with `--launch`, Painter is restarted; at most 3 restarts).
5. A golden the recorder refuses leaves the candidate incomplete: the previous envelope stays current and the next `refresh` resumes from the ledger.
6. Promotion when every golden is recorded, every run is consistent and schema-valid, the corpus drift report (`oracle-envelope-drift-corpus-<dir>.json`: unchanged / changed per golden, divergence candidates, fits to re-check, whether a new evaluator profile is needed, stale Tier 3 references) is published, and the store is available: each run is admitted with the store's `record --run` into the candidate's manifest, then the registry is replaced in one atomic write (the commit point). The previous envelope, its manifests, records and fits stay as history.

### 10.2 Stability study (decision 034 (b), (c))

`python -m tools.parity.recorder stability-study [<manifest or dir>...] --launch --admit` (default: the current envelope's `tier0/` manifests; manifests of another build are refused). Each golden is recorded by its own command three times: runs `a` and `b` in one Painter process (`a.r1`, `b.r1` same session; `a.r2`, `b.r2` after save and reopen), then run `c` in a freshly started process (`c.r1`, plus `c.r2`). Runs go to `<inbox>/stability-study/<study id>/` with record ids prefixed `study-<study id>-<run>-`; the ledger is `<work>/stability-study/<study id>/study.json`, and `--resume <that directory>` continues an interrupted study. `--admit` admits every run with the store's `record --run` into study manifests in the study directory, never into a golden's own manifest.

Analysis (`python -m tools.parity.envelope study-analyse <study dir>` re-runs it without Painter): per pair, exported maps are compared by hash, then decoded at native depth (max, mean, p99 |Δ|, differing values and texels); readbacks as JSON after replacing the per-project resource counter and the run directory. Classification: `stable`, `save-reopen-unstable` (decision 032), `fresh-process-unstable`, `save-reopen-and-fresh-process-unstable`, `same-session-unstable` (r1 does not repeat in one process; covered by neither 032 nor 034), `incomplete`. For a fresh-process-unstable golden r1 stays the exact target; its register entry is prepared in `parity/reports/phase0/oracle-envelope-register-drafts.json` without the owner's approval fields and never written to `parity/exceptions.json`.

### 10.3 Canary (decision 034 (d))

`python -m tools.parity.recorder canary --launch`. The fixed subset (`tools/parity/envelope/canary.py`): `tier0/semantics/blend-basic`, `blend-component`, `quantisation-thirds`, `colour-ramps-srgb`, `height-normal-sphere`, `resample-uv`, `levels-clamp`, `phase0/normal-convention/hemisphere/per-fragment` (a bake), `tier0/api-probes/fill-layer-readback` and `tier0/defaults-templates/baking-defaults` (API readbacks). On an unseen build or another environment the command runs the refresh of §10.1, whose first goldens are the canary. On the current envelope it re-records the subset (record ids `canary-<stamp>-`, never merged into a manifest) and diffs it exactly; a difference under the same envelope means the oracle does not reproduce itself and exits 4, replacing nothing.

### 10.4 Back-fill

`python -m tools.parity.envelope backfill parity/manifests [--known gpu_model=... --known driver_version=... --known os_build=...] [--dry-run]` writes an environment record with `basis: backfilled` for every golden recorded before the record existed, and appends only its `oracle-environment` reference to the manifest. The Painter build comes from the manifest, the colour-configuration hash from the record's colour-management readback when it names no configuration file; everything else is `unknown` unless stated with `--known`. Outputs are never touched.

## 11. Requested goldens and the Phase 1 recording runbook (decisions 099, 100)

**Requested goldens.** A golden prepared before the Painter session that records it is a *request*: a public manifest under the current envelope's `parity/envelopes/<envelope>/requests/`, with the same relative path it will have under `manifests/` and `private_records` empty (the guard allows nothing else there). The recorder records from the request path. `python -m tools.parity.store record <the same path under manifests/> --run <run>` then creates the admitted manifest from the run, and the request file is deleted. The Tier 0 requests are generated by `tools/parity/tier0_semantics/recording_requests.py` (`python -m tools.parity.tier0_semantics write`); on admission a golden moves from `requested_goldens` to `current.api_goldens`. Requests are never under `manifests/`, so the gate, the refresh, the canary and the store verify never see an unrecorded golden.

**Phase 1 batch (decision 100).** Two Painter sessions, Legacy first. The coordinator agent that owns Painter holds the Assets3D Painter lock, drives Painter through the recorder (and the UI operator where a manifest needs one; none of this batch does), and admits each run. Every Tier 0 golden records `r1` and `r2`; most repeat each export step in the session. In PowerShell from the repository root:

```powershell
$req = "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests"
$man = "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests"
$exe = "C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
```

### 11.1 Session L (Legacy colour management)

1. Close Painter. In a shell with **no** `OCIO` and no `PAINTER_ACE_CONFIG` (`Remove-Item Env:OCIO, Env:PAINTER_ACE_CONFIG -ErrorAction SilentlyContinue`), start `& $exe --enable-remote-scripting` and wait until no project is open.
2. `python -m tools.parity.envelope check` must exit 0. Exit 3 means an unseen build: run `python -m tools.parity.recorder refresh` first, and regenerate the requests under the new envelope before recording.
3. Tier 0 export goldens, in this order (largest first, so a refusal shows early):

   ```powershell
   $legacy = "export-bit-depth", "export-padding", "export-padding-bevelled-cube",
     "export-padding-sphere", "export-padding-seam-256", "export-padding-seam-field-256",
     "export-padding-seam-1024", "export-padding-seam-field-1024", "export-alpha-layouts",
     "export-resize", "export-dither", "export-presets-legacy", "export-ocio-encode-legacy"
   foreach ($g in $legacy) {
     python -m tools.parity.recorder record "$req/tier0/semantics/$g.json"
   }
   ```

   Each command prints `recorded: <run directory>`. A refused golden writes nothing; the command says why. Note the refusal and go on with the next golden.
4. R10 API probes (Legacy): record each probe, the engine-computations probe last. Its export request with engine computations disabled may never return; if Painter hangs, stop it and restart. The other goldens are already safe, and the hang is itself the observation to report:

   ```powershell
   $probes = "phase1-delete-node", "phase1-resource-update", "phase1-save-modes",
     "phase1-create-settings", "phase1-reload-mesh", "phase1-reload-resources",
     "phase1-execute-when-not-busy", "phase1-engine-computations"
   foreach ($g in $probes) {
     python -m tools.parity.recorder.probes record "$req/tier0/api-probes/$g.json"
   }
   ```
5. Admit each run: `python -m tools.parity.store record "$man/<family>/<name>.json" --run <run directory>`. Then `python -m tools.parity.store verify $man/tier0`.

### 11.2 Session O (OCIO)

1. Close Painter. Set `$env:OCIO = "C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"` and start `& $exe --enable-remote-scripting` from that shell. The recorder refuses an OCIO golden in a Legacy session and a Legacy golden in an OCIO session.
2. `python -m tools.parity.recorder record "$req/tier0/semantics/export-ocio-encode.json"`, then `export-presets-ocio.json`.
3. R9, the Wand v1 Tier 1 golden, last (the longest): with the Assets3D lock held (the recorder only reads Assets3D):

   ```powershell
   python -m tools.parity.recorder record-script "$req/phase1/tier1/wand-v1.json" --assets-root E:\UzmiGames\Assets3D
   ```

   It records `r1` (create, sync, export), `r1-repeat` (export again in the same session) and `r2` (reopen the saved work project, export again). Admit it to `$man/phase1/tier1/wand-v1.json`.
4. Admit as in 11.1 step 5.

### 11.4 Later requests (decisions 095, 107, 109, 110, 132, 169, 174; requests by decisions 156, 157, 168, 180)

Legacy session as in 11.1 steps 1, 2 and 5. The throttling probe (P21-C) goes first, in the fresh session, before any script can set the period:

```powershell
python -m tools.parity.recorder.probes record "$req/tier0/api-probes/phase1-texture-throttling.json"
# Decision 174 item 6 (sRGB bitmap minification), decision 169 (L8 material channels) and
# decision 084 item 5 (held-out axis-aligned minification, never to be used by a fit).
foreach ($g in "srgb-bitmap-minification", "export-l8-material", "resample-uv-heldout-128px",
  "resample-uv-heldout-32px") {
  python -m tools.parity.recorder record "$req/tier0/semantics/$g.json"
}
# P20-B in four parts of 80 colours (decision 180: the single 645-step request did not fit a
# window; each part takes about 9 minutes), P20-A, then the host behaviour probes.
$probes = @(foreach ($n in 1..4) { "phase1-srgb-uniform-decode-part$n" })
$probes += "phase1-fill-channel-defaults", "phase1-create-mesh-maps", "phase1-create-default-paths",
  "phase1-shelves", "phase1-layer-stack-events", "phase1-close-without-saving",
  "phase1-create-open-timing", "phase1-default-camera-plane", "phase1-default-camera-sphere",
  "phase1-default-camera-bevelled-cube", "phase1-camera-coupling", "phase1-export-preset-search"
foreach ($g in $probes) {
  python -m tools.parity.recorder.probes record "$req/tier0/api-probes/$g.json"
}
```

Then an OCIO session (Session O, as in 11.2 step 1) for R-132-D and P20-B's OCIO twin (decision 190), four parts of about 9 minutes each:

```powershell
$ocio = @("phase1-display-ocio") + @(foreach ($n in 1..4) { "phase1-srgb-uniform-decode-ocio-part$n" })
foreach ($g in $ocio) {
  python -m tools.parity.recorder.probes record "$req/tier0/api-probes/$g.json"
}
```

Decision 160 admitted the template bases, `export-padding-tie-512` and the void first P-ramp and P-tie 2048 records; the `-v2` names re-author the void ones with the ramp files `uv-ramp-n1024.exr` and `uv-ramp-n2048.exr` (decision 166); decision 167 admitted all eleven, and decision 172 admitted the 21 `export-template-base-*` requests of decision 168. Decision 180 recorded Session O (11.2, R9 included), `export-presets-legacy` (no crash), `phase1-mesh-map-update`, `phase1-restored-values`, `phase1-save-as-existing` and `phase1-engine-computations` (no hang); `phase1-srgb-uniform-decode` (645 steps, about 35 minutes) was stopped at the time cap, and its four parts replace it. With `export-presets-legacy` and `-ocio` admitted, R-095 is recorded except P7, which `phase1-export-preset-search` records. Decision 198 recorded the four `phase1-srgb-uniform-decode-ocio` parts and `phase1-display-ocio` (Session O), `srgb-bitmap-minification`, `export-l8-material`, both `resample-uv-heldout` goldens, `phase1-fill-channel-defaults`, P21-A, B, D, F and G, R-132-A and `phase1-export-preset-search` (R-095 is complete). Still open: the four Legacy P20-B parts, `phase1-texture-throttling` (fresh session first), `phase1-layer-stack-events` and `phase1-camera-coupling`. `srgb-bitmap-variants-v2` s4 and s5 attempt `set_color_space(sRGB)` (decisions 156 and 167): a refusal there is recorded (`set_color_space.<step>` in the effective defaults), not a refused golden. A P-ramp or P-tie record whose `passthrough` User0 differs from the ramp on a covered texel, or whose template capture shows User0 other than RGB32F, is void (decision 129); report it.

### 11.3 After the sessions

- For each admitted Tier 0 golden, add its name to `recording_requests.ADMITTED` (the generator then plans its manifest under `manifests/`) and delete its request file. `python -m tools.parity.tier0_semantics check` must pass.
- Admitted probe and Tier 1 manifests move the same way: delete the request file once the store has written the manifest under `manifests/`.
- Keep a refused golden's request and record the refusal and its cause in the batch report. A state step Painter refuses (for example an `add_channel` of a channel the default project already has) refuses the whole golden; fix the request under a new name. A recorded golden is immutable.
- Run `python -m pytest tests/parity/test_tier0_gate.py tests/parity/test_tier0_semantics_ui.py tests/parity/test_recording_requests.py tests/parity/recorder/test_api_probes.py`.
- Regenerate `parity/reports/phase0/tier0-stability.md` as earlier batches did.
- Commit the manifests (hashes only) with a decision that records the batch.
