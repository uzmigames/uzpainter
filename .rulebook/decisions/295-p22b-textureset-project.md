# 295. P22-B for the textureset, project, export, baking and source modules: eight requests exercise 80 pending symbols, and four take another evidence route

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.24_python-api-facade, phase3.5_embree-bakers, phase3.2_proc-material-families

## Context

Decision 189 §3 split P22-B by module into `phase1.24_python-api-facade` item 3.4. This decision covers one group: textureset, project, export, baking and source. Decisions 296 and 297 cover the other modules.

Measured on main 39d8d7b:

- The capability manifest (`tools/capabilities/painter-api-inventory.json`) has 93 `pending-evidence` Painter symbols in these modules: textureset 75, project 11, export 3, source 3 and baking 1.
- Nine of them are decision 188's (decision 189 §2): seven `MeshMapUsage` members, `SourceBitmap.reset_color_space` and `SourceUniformColor.set_color`.
- That leaves 84. Decision 189 counted 83: `ExportStatus.Error` was not in its count, and it is pending as well.

Facts that shaped the probes (A-PYDOC, Painter 12.1 python-doc; the recorder; the facade):

- `export_project_textures` is documented as follows: its result is never `Error`, and a failed export raises while `ExportTexturesEnded` receives `Error`. A user cancel returns `Cancelled`. `Warning` means "completed with warnings", and no trigger for it is documented. No documented call cancels an export.
- Every `substance_painter.baking` member is a release gap (`phase3.5_embree-bakers`). `SourceMode.Material` needs a material source, and `set_material_source` refuses with `UnsupportedProcedural` (`phase3.2_proc-material-families`).
- `project.get_uuid()` is new for every created project. `last_imported_mesh_path()` lies in the recorder's private run directory.
- Painter 12.1 documents `TextureSet.original_name` and `TextureSet.description` as properties, and `description` has a setter. The facade (`python/uzpainter_facade/textureset.py`) implements both as methods, with no setter.
- `ChannelType` has legacy alias members (`Metallic`, `Roughness`, `Emissive`, `SpecularEdgeColor`, `Anisotropylevel`, `Scattering`, `ScatteringColor`, `Translucency`, `AbsorptionColor`, `SheenOpacity`, `SheenRoughness`, `SheenColor`, `CoatOpacity`). A plane created without a template holds BaseColor, BaseMetalness, Height, Normal and SpecularRoughness.
- `Settings.tangent_space_mode`, `project_workflow` and `mesh_unit_scale` have no documented getter. `phase1-create-settings` made `Settings.normal_map_format` `supported` through the compared replay of a create that passes it.
- Step arguments are scalars or lists of scalars (`golden-public.json`), so a dict value cannot be authored directly.

**Model panel** (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

- C1, the baking module gets no probe, and its route is phase3.5: AGREE ×3. Kimi added that the module could aggregate to `release-gap`. That is not adopted: decision 112 §4 gives that status to refused calls, and importing the module is not refused.
- C2, `SourceMode.Material` goes to phase3.2: AGREE ×3.
- C3, an `Error` probe through an export path taken by a regular file: PARTLY ×3. The trigger is not documented, and Painter might refuse before `ExportTexturesEnded`. Adopted with a fallback (§3 below).
- C4, `Cancelled` gets no probe and stays open at G5: AGREE ×2, PARTLY (GPT: a controlled owner cancellation could be admitted later). Adopted with GPT's widening.
- C5, `Warning` is observed only: AGREE ×2, PARTLY (GPT: an observed Warning is a candidate, and it counts only through a matching replay). Adopted.
- C6, `get_uuid` is recorded as facts: AGREE, PARTLY ×2. Record what Painter gives instead of assuming a `uuid.UUID`, and check that UUIDs differ between projects (GPT). Adopted.
- C7, use the documented property forms and report the facade divergence: AGREE ×3.
- C8, each `ChannelType` member is passed to add/has/get: PARTLY ×3. Add canonical members before the aliases, and read every member back. Adopted.
- C9, the three `Settings` fields in two shared creates: DISAGREE ×2, PARTLY. A create's success does not show that a setting applied, and two creates confound three settings. Adopted: one request per setting, and an explicit amendment (§2 below).

## Decision

### 1. Vocabulary

The vocabulary uses explicit documented calls only. It lives in the `P295_*` block of `tools/parity/recorder/painter_probes.py`, which the host merges in `probes.py`.

- **Edits:**
  - `Stack.add_channel`, `Stack.edit_channel` and `Channel.edit` take `channel`, `format` and an optional `label`. The label is passed only when the step gives one.
  - `Stack.remove_channel`.
  - `TextureSet.set_resolution` (`width`, `height`).
  - The `TextureSet.description` setter (`value`).
  - `set_active_stack` (`texture_set`, `stack`).
  - `project.Metadata.set` (`context`, `key`, and `value` or `dict_keys` + `dict_values`).
- **Getters:**
  - `Stack.has_channel`.
  - `Stack.get_channel`. A channel is read as `type()`, `format()` and `label()`.
  - `TextureSet.from_name`, the `original_name` and `description` properties, and `is_layered_material`.
  - `get_active_stack`.
  - `Metadata.list` and `Metadata.get`.
  - `get_uuid`: whether it is a `uuid.UUID`, whether its text parses as one, its version, and whether it equals the run's first read.
  - `last_imported_mesh_path`, relative to the run.
- **Export:** an export probe with `export_path_blocked: true` has its `exportPath` taken by a regular file in the run's private directory.
- **Recorder:** `painter_side.py` resolves every `ChannelType` member the requests pass.
- **Fake:** the fake Painter models all of this (`extend_p295` in `fake_probe_painter.py`).
- **Tests:** `tests/parity/recorder/test_api_probes_p22b_d295.py`. Each request validates, loads, names its symbols and records `r1` and `r2`. Every pending symbol of the group is either requested or routed.

### 2. Requests and the symbols they exercise

The requests live in `requests/tier0/api-probes/` and are not recorded yet. All run on the plane at 256 px under Legacy, with readbacks in the same session and after save and reopen.

| Request | Pending symbols exercised |
|---|---|
| `p22b-textureset-channels` | `Stack.add_channel` / `has_channel` / `get_channel` (with `Channel.type`) of the 28 standard members: AO, BaseDiffuseRoughness, BaseWeight, BlendingMask, CoatRoughnessAnisotropy, CoatSpecularLevel, CoatTangent, Displacement, Ior, Reflection, SpecularColor, SpecularWeight, ThinFilmWeight, TransmissionColor and TransmissionWeight, then the aliases AbsorptionColor, Anisotropylevel, CoatOpacity, Emissive, Metallic, Roughness, Scattering, ScatteringColor, SheenColor, SheenOpacity, SheenRoughness, SpecularEdgeColor and Translucency; `Stack.edit_channel`, `Channel.edit`, `Stack.remove_channel`; `ChannelFormat.L32F`, `RGB32F` |
| `p22b-textureset-user-channels` | `ChannelType.User8` to `User31` (labelled and unlabelled), the same channel calls, `L32F`, `RGB32F` |
| `p22b-textureset-texture-set` | `TextureSet.set_resolution` with `Resolution.width` / `height`, `TextureSet.description` (set and get), `TextureSet.from_name`, `original_name`, `is_layered_material`, `set_active_stack` |
| `p22b-project-tangent-per-vertex` | `Settings.tangent_space_mode`, `TangentSpace`, `TangentSpace.PerVertex`, `Metadata.list` (with `Metadata.set` / `get` of bool, int, float, str, list and dict), `get_uuid`, `last_imported_mesh_path` |
| `p22b-project-tangent-per-fragment` | `TangentSpace.PerFragment`, `Settings.tangent_space_mode`, `get_uuid`, `last_imported_mesh_path` |
| `p22b-project-workflow-default` | `Settings.project_workflow`, `ProjectWorkflow`, `ProjectWorkflow.Default`, `get_uuid` |
| `p22b-project-mesh-unit-scale` | `Settings.mesh_unit_scale` (2.0), with the scene bounding box read |
| `p22b-export-error-status` | `ExportStatus.Error`, through the raised export and the `ExportTexturesEnded` status |

**Amendment to decision 112 (Recordings, P22-B): settings with no getter.** A `project.Settings` field with no documented getter is evidenced like `normal_map_format`: by the compared replay of a create that passes it, one setting per request. The set→get rule does not apply to it.

- `mesh_unit_scale` also records `get_scene_bounding_box`. It is compared once that call leaves its release gap.
- `ProjectWorkflow.Default` proves nothing about `UVTile` or `TextureSetPerUVTile`, which remain release gaps.

### 3. Other evidence routes (amendments to decision 112 §3)

No P22-B probe reaches these four. Their manifest entries stay `pending-evidence`, with these routes:

- **`substance_painter.baking`** (the module entry). It is settled by the first compared replay of a baking member, once `phase3.5_embree-bakers` implements one. Every member refuses today.
- **`SourceMode.Material`**. It is settled by `phase3.2_proc-material-families`'s compared replay of a fill holding a material source. A Painter-only recording would describe a state that UzPainter reaches only through a refused call.
- **`ExportStatus.Cancelled`**. No Tier 0 probe: only a user action cancels, and a timed UI cancel would be unsafe and nondeterministic. G5 lists it as an open item. A later decision may admit an owner-run controlled cancellation, or a documented scriptable cancel.
- **`ExportStatus.Warning`**. It is observed only, never triggered by a guess. An admitted Painter export record whose result or `ExportTexturesEnded` status is `Warning` is a candidate. It counts once that golden's replay reproduces it under the same preconditions. Until then it is open at G5.

**Fallback for `ExportStatus.Error`.** If `p22b-export-error-status` records Painter refusing before `ExportTexturesEnded`, or that event carrying another status, `Error` takes `Warning`'s observed-only route.

### 4. Notes for the replay owner (item 4.1 acceptance; not done here)

Editorial clarification: item 3.4 closes the vocabulary, fake tests, request authoring and evidence-route judgments of decision 189 section 3. Recording, admission and compared replay remain mandatory under item 4.1 and decision 112; this clarification promotes no capability.

- The facade's `TextureSet.original_name()` and `description()` are methods. Painter's are properties, and `description` has a setter. The replay of `p22b-textureset-texture-set` cannot match until the facade follows A-PYDOC.
- The replay must reproduce `export_path_blocked`: a regular file at the export path.
- The replay compares `get_uuid` facts, and must also check that two created projects give different UUIDs (C6). A constant UUID would otherwise pass.
- Alias members resolve as Painter records them (`get_channel`'s `type`). The recorded outcome of an add on an alias, a raise or a separate channel, is the behaviour to match.

## Alternatives Considered

- **One request for every symbol of the group.** Rejected. The channel steps alone take 160, and decision 180's time cap stopped a 645-step request. Separate requests also keep each setting unconfounded (C9).
- **Recording the UUID value.** Rejected. It differs on every run, so no replay could compare it.
- **Guessing a Warning trigger, or a timed UI cancel.** Rejected (C4, C5).
- **Classifying the baking module as `release-gap`.** Rejected (C1, Kimi). Decision 112 §4 classifies refused calls, and the module itself is not refused.

## Consequences

- These eight requests exercise 80 of the group's 84 symbols, and the other four take the routes in §3. Decision 188's requests hold the remaining nine of the 93. No manifest entry changes until a recording is admitted and replayed (decision 189 §2).
- `test_api_probes_phase1.py` now counts only the `phase1-*` requests, so P22-B requests can stage beside them.
- RECORDER.md §9 describes the vocabulary, and §11.4 the recording.

*Clean-room note (2026-10-19, decision 304): the `ChannelType` alias member names were marked as code for clean-room hygiene; no wording or reasoning changed.*
