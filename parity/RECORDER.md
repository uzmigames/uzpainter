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
| `substance_painter.project.create` | `mesh` (input id); optional `normal_map_format`, `tangent_space_mode`, `project_workflow`, `default_texture_resolution`, `import_cameras`, `mesh_unit_scale` |
| `substance_painter.layerstack.insert_fill` | `position: "top"`, or `above_step` / `below_step` (the step that inserted the reference layer) |
| `substance_painter.layerstack.FillLayerNode.active_channels` | `node_step`, `channels` |
| `substance_painter.layerstack.FillLayerNode.set_source` | `node_step`, `channel`, and either `color` [r, g, b] with optional `color_space` (`sRGB`, `Working`, `Raw`) or `resource` (a `resource://` URL, `resource.ResourceID.from_url`); the readback records a uniform colour, or every `properties.Property` of a substance source (`value`, `widget_type`, `label`) |
| `substance_painter.layerstack.Node.set_blending_mode` | `node_step`, `blending_mode`, `channel` |
| `substance_painter.layerstack.Node.set_opacity` | `node_step`, `opacity`, `channel` |
| `substance_painter.textureset.set_resolutions` | `width`, `height` (all texture sets) |
| `substance_painter.display.Camera.<property>` | `value` (`projection_type`, `position`, `rotation`, `field_of_view`, `focal_length`, `focus_distance`, `aperture`, `orthographic_height`) |
| `substance_painter.display.set_environment_resource` | `environment` (input id, imported with `resource.import_project_resource`) |
| `substance_painter.display.set_tone_mapping` | `function` (`Linear`, `ACES`) |
| `substance_painter.export.export_project_textures` (capture) | `maps` (`<mapType>/<name>:<RGB|RGBA|L>`, e.g. `documentMap/basecolor:RGB`), `bit_depth`, `padding`; optional `file_format` (png), `dithering`, `dilation`, `size_log2` |

Enum arguments accept only the documented member names listed in `painter_side.py`.

## 3. Texture goldens (Tiers 0–2b)

`python -m tools.parity.recorder record <manifest.json>`

1. The state steps are applied once. Effective defaults are read as they appear (each new fill layer before it is edited, and the channel set `project.create` produced) and go into `key.effective_defaults`.
2. Recording `r1` (`same_session`): template capture (texture sets, stacks, channel formats), a readback of every property the sequence set (an exception Painter raises is recorded as `raised`), then each export.
3. The project is saved (Full) in the work directory, closed and reopened; layers are found again at their recorded place in the stack.
4. Recording `r2` (`after_save_reopen`): the same captures.

**Readiness and current output.** Before each export the recorder waits until the project is in edition state and not busy; `export_project_textures` computes what it writes. It then writes a fence file and exports into a new, empty directory. It accepts the export only if that directory holds exactly the files the call reported and each was written no earlier than the fence (same filesystem clock). Anything else, such as a stale, extra or missing file, refuses the whole golden and writes nothing.

**Storage format** is measured from the file: PNG IHDR and colour chunks, and the OpenEXR channel list. If the file states no encoding, the encoding comes from the source channel's documented storage (`textureset.ChannelFormat`: `sRGB8` is sRGB, the others are linear), and `export_settings.encoding_basis` says which applies.

## 4. Iray references (Tier 3)

`python -m tools.parity.recorder iray <manifest.json> --condition separate_session` (twice, restarting Painter in between), then `--condition k_times_samples --k <k>`. This implements `07-preview-and-render-parity.md` §2.2. The procedure must be qualified by `phase0.9_render-reference-capture` before any render golden is admitted.

- The recorder applies the documented settings (camera, environment, tone mapping), reads every documented render setting back into `key.render_state`, and switches to `ui.UIMode.Visualisation`.
- **Operator form.** The settings sheet is the manifest's `applied_settings` with `applied_by: operator_settings_sheet`, named `<panel>/<setting>`. It must include `Iray Settings/Min Sample` = `Max Sample` (S), `Max Time` (unit `s`, `min` or `h`), `Width` and `Height`. For each setting, the operator types the value the panel shows; any value that differs from the sheet (k·S for Min/Max Sample on the k run) refuses the reference. The operator also gives one PNG or JPEG image of each panel. Entries and images become private outputs (`operator_recorded_settings`, `settings_panel_evidence`).
- **Convergence.** Accepted only when the operator reports Status `Done`, Iterations equal to the sample count, and a Rendering time below Max Time.
- **Capture.** The recorder writes the fence, and the operator uses Save Render to save to the path it names. Current-frame verification: the file is the only one in a new directory, written after the fence, at the overridden resolution, and its silhouette matches the fixture's authored mask (input `silhouette`: 0 is background, full value is the object, anything else is a don't-care edge band). Every background pixel must hold one value and no object pixel may hold it. If the file states no encoding, the sheet must give it as setting `capture.encoding`.
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
