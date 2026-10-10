# Painter oracle recorder

Work package P0-RECORDER (`docs/dag.md`), task `phase0.3_painter-oracle-recorder`. Code: `tools/parity/recorder/`; tests: `tests/parity/recorder/`. It records Painter goldens as defined by `CONTRACT.md` §6 and `docs/architecture/14-parity-testing.md` §2, through Painter's **documented** Python API only (approved source A-PYDOC). It never uses the community MCP bridge or a private interface, and it never reads Painter's shipped sources.

## 1. How it talks to Painter

- Painter 12.1.0 runs on the owner's machine, started with `--enable-remote-scripting`. Its documented remote control (Python API guide *Remote control / headless*) accepts `POST http://localhost:60041/run.json` with `{"python": <base64 source>}` and answers with the JSON value of an expression.
- The recorder sends `painter_side.py` once into a private namespace, then calls one operation per request. Painter loads projects asynchronously, so the host polls readiness (`project.is_in_edition_state()`, `project.is_busy()`) between requests.
- Software identity: `application.version()` and `version_info()` must be 12.1.0. They expose no finer build number, so `build_id` is `<version>+js-api.<alg.version.api>` (documented JavaScript API version through the documented `js.evaluate`); today `12.1.0+js-api.1.1.20`. A golden's manifest must name this build or the recorder refuses (goldens are immutable per build).
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
| `substance_painter.layerstack.FillLayerNode.set_source` | `node_step`, `channel`, and either `color` [r, g, b] with optional `color_space` (`sRGB`, `Working`, `Raw`) or `resource` (a `resource://` URL, `resource.ResourceID.from_url`); the readback records a uniform colour, or every `properties.Property` of a substance source (`value`, `widget_type`, `label`) |
| `substance_painter.layerstack.Node.set_blending_mode` | `node_step`, `blending_mode`, `channel` |
| `substance_painter.layerstack.Node.set_opacity` | `node_step`, `opacity`, `channel` |
| `substance_painter.textureset.set_resolutions` | `width`, `height` (all texture sets) |
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
| `substance_painter.export.export_project_textures` (capture) | `maps` (`<mapType>/<name>:<RGB|RGBA|L>`, e.g. `documentMap/basecolor:RGB`, `meshMap/normal_base:RGB`), `bit_depth`, `padding`; optional `file_format` (png), `dithering`, `dilation`, `size_log2` |
| `substance_painter.baking.BakingParameters.common` (capture, §8) | none |
| `substance_painter.baking.BakingParameters.baker` (capture, §8) | `usage` (a `textureset.MeshMapUsage` member name) |
| `substance_painter.baking.BakingParameters.get_curvature_method`, `.get_enabled_bakers`, `.is_textureset_enabled` (captures, §8) | none |

Enum arguments accept only the documented member names listed in `painter_side.py`.

## 3. Texture goldens (Tiers 0–2b)

`python -m tools.parity.recorder record <manifest.json>`

1. The state steps are applied once. Effective defaults are read as they appear (each new fill layer before it is edited, and the channel set `project.create` produced) and go into `key.effective_defaults`.
2. Recording `r1` (`same_session`): template capture (texture sets, stacks, channel formats), a readback of every property the sequence set (an exception Painter raises is recorded as `raised`), then each export.
3. The project is saved (Full) in the work directory, closed and reopened; layers are found again at their recorded place in the stack.
4. Recording `r2` (`after_save_reopen`): the same captures.

**Readiness and current output.** Before each export the recorder waits until the project is in edition state and not busy; `export_project_textures` computes what it writes. It then writes a fence file and exports into a new, empty directory. It accepts the export only if that directory holds exactly the files the call reported and each was written no earlier than the fence (same filesystem clock). Anything else, such as a stale, extra or missing file, refuses the whole golden and writes nothing.

**Storage format** is measured from the file: PNG IHDR and colour chunks, and the OpenEXR channel list. If the file states no encoding, the encoding comes from the source channel's documented storage (`textureset.ChannelFormat`: `sRGB8` is sRGB, the others are linear), and `export_settings.encoding_basis` says which applies. A `meshMap` export that states no encoding is linear with basis `baked_mesh_map`: a baked mesh map stores data, not colour.

**Baking jobs** (`phase0.9_normal-convention-fixture`). Bake steps are state steps, applied once before `r1`; a `BakingParameters.set` or `set_enabled_bakers` step after the last `bake_async` is refused. Each `set` step sets one parameter with one documented `BakingParameters.set` call per texture set. The high-poly mesh is an input of the manifest (`parameter: "HipolyMesh"`, `input: <input id>`): the recorder stages it and passes `file:///` followed by the staged file's POSIX path, the form of the documented `QUrl.fromLocalFile(...).toString()` example. A path holding a character that a URL would percent-encode, such as a space, refuses the golden. For `bake_async`, `painter_side.py` connects a handler for `event.BakingProcessEnded` to the documented dispatcher, launches the bake and returns. The host then polls the `baking_state` operation (which launches the next texture set when one ends) for up to 1800 s, and waits for readiness. A status other than `Success`, or no end in time, refuses the golden. The handler is disconnected when the bake ends or the project closes. `key.effective_defaults.bakes` records, per bake step, the status of each texture set and the bakers enabled at bake time. Painter's bake backend cannot be read or fixed through the documented API, so `key.bake_backend` stays `null` and the public manifest lists it in `uncontrolled_settings`.

## 4. Iray references (Tier 3)

`python -m tools.parity.recorder iray <manifest.json> --condition separate_session` (twice, restarting Painter in between), then `--condition k_times_samples --k 4`. This implements `07-preview-and-render-parity.md` §2.2 as procedure `iray-capture/1`. The procedure, its answers to 07 §2.1 and its qualification status are in `parity/reports/phase0/iray-capture-procedure.md`; no render golden is admitted before it is qualified.

- The sheet must name the procedure and the pixel route: settings `capture.procedure` = `iray-capture/1` and `capture.route` = `save_render` (`applied_by: recorder_api`). A camera rotation other than zero also needs `capture.camera_rotation_order`, the Euler order the probe confirmed.
- The recorder applies the documented settings (camera, environment, tone mapping). It reads every documented render setting back into `key.render_state`, together with `project.get_scene_bounding_box()`, and switches to `ui.UIMode.Visualisation`.
- **Operator form.** The settings sheet is the manifest's `applied_settings` with `applied_by: operator_settings_sheet`, named `<panel>/<setting>`. It must include `Iray Settings/Min Sample` = `Max Sample` (S), `Max Time` (unit `s`, `min` or `h`), `Width` and `Height`. For each setting, the operator types the value the panel shows; any value that differs from the sheet (k·S for Min/Max Sample on the k run) refuses the reference. The operator also gives one PNG or JPEG image of each panel. Entries and images become private outputs (`operator_recorded_settings`, `settings_panel_evidence`).
- **Convergence.** Accepted only when the operator reports Status `Done`, Iterations equal to the sample count, and a Rendering time below Max Time.
- **Capture.** The recorder writes the fence, and the operator uses Save Render to save to the path it names. Current-frame verification: the file is the only one in a new directory, written after the fence, at the overridden resolution (square), and its silhouette matches the job's mesh projected from the read-back camera (`tools/parity/render_procedure/projection.py`; Perspective only, a 2-pixel don't-care band around the outline). The scene bounding box must equal the mesh file's. Every background pixel must hold one value and no object pixel may hold it. If the file states no encoding, the sheet must give it as setting `capture.encoding`.
- **Probe.** `python -m tools.parity.recorder iray-probe` runs the operator-assisted probe session of the procedure report §3. Its evidence goes to `UZP_ORACLE_WORK\iray-probe\<run>\probe.json`; `iray-probe-analyse <dir>` re-runs the analysis without Painter.
- References are staged in the work directory. When two `separate_session` references (from different Painter processes) and one `k_times_samples` reference have identical keys, the record is written. Different keys refuse assembly, because the oracle is unstable.

## 5. Output: private inbox, public hashes

Records go to `UZP_ORACLE_INBOX` (default `%LOCALAPPDATA%\UzPainter\oracle-inbox`). Working files (staged inputs, throwaway `.spp`, exports, renders) go to `UZP_ORACLE_WORK` (default `%LOCALAPPDATA%\UzPainter\oracle-work`). The recorder refuses either directory if it lies inside the repository. One run per golden:

```
<inbox>/<golden_id with / as __>/<UTC stamp>-<session>/record.json     private record (golden-private.json, record_problems clean)
                                                      /blobs/<sha256>  every blob the record names
                                                      /manifest.json   public manifest with private_records filled
                                                      /READY           written last
```

`private_records` lists `golden-record` (the record file) and `<recording>-<output>` for each blob, by SHA-256 and size. The private store CLI (`phase0.3_oracle-store-cli`, `python -m tools.parity.store record <repository manifest> --run <run>`) admits a READY run and merges those hashes into the repository manifest. Nothing recorded enters the repository.

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
