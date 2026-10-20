# 323. Closing the baker request model: the Automatic cage, ApplyDiffusion and the relative box size as manifest release gaps owned by phase3.5_embree-bakers; the BakingParameters/Property model from the authored, capture-checked table assets/defaults/baking.json (meta properties and out-of-range values refused); the MCP Baking parameter tools; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.1_baker-request-model, phase3.5_embree-bakers

## Context

Decisions 302, 306 and 311 built the CPU baker's request model in three permitted slices. Each slice left items 2.5, 2.7, 2.8, 2.9 and 2.11 open. The coordinator asked for those items to be closed, under one rule: behaviour without a Painter golden is refused before any mutation, with a `NotYetSupported` (or a capability error) naming its owner task or decision; everything else is `pending-evidence` and never claimed exact.

## Decision

### 1. Cages (item 2.5)
- **What is implemented** (decisions 306 and 311):
  - a custom cage given in memory or read from a mesh file, paired with the low mesh by vertex index;
  - the distance-based cage, with frontal (`MaxHeight`) and rear (`MaxDepth`) distances, absolute in centimetres or relative to the project mesh's bounding box.
- **What stays refused:**
  - the size of the bounding box a relative distance is a fraction of (its diagonal or its largest extent): `NotYetSupported` unless the request names the metric;
  - `CageMode` Automatic: a `CapabilityError` before any work.

  Both refusals now name their owner, `phase3.5_embree-bakers`. Its item 3.1 is the Tier 2b suite, whose recordings settle them.
- **The manifest.** The Automatic cage is a release gap of the capability manifest: `substance_painter.baking.bake_async` in the context `cage-mode:automatic`.
  - The entry is seeded in `RELEASE_GAPS`, and `10-python-api.md` §3 lists it.
  - Its context is the bake, not `BakingParameters.set`. Storing the value is ordinary parameter storage; baking with it is the behaviour nobody has recorded.
  - It leaves the list only together with §3, when Tier 2b establishes the cage (`phase3.5_embree-bakers` item 3.4 regenerates the manifest).

### 2. Dilation and units (item 2.7)
- **What is implemented** (decisions 306 and 311):
  - `DilationWidth`: serial Jacobi passes into `Uncovered` texels only. It writes the baked map; `ao_raw` is kept unchanged, and the used-surface texels without a hit are never written.
  - Units: absolute distances are centimetres over the mesh's required `scale_to_internal`. The scale, the relative flags, the box size and the effective mesh-unit distances are recorded with the map (`DistanceRecord`, `UZPBAKE3`).
- **What stays refused.** `ApplyDiffusion` on: `NotYetSupported` before any work, now owned by `phase3.5_embree-bakers`. One fixture baked with diffusion on and off settles it.
- **The manifest.** Two release gaps are added beside the Automatic cage, each refused by the CPU baker before any work:
  - `bake_async` @ `apply-diffusion`;
  - `bake_async` @ `relative-to-bounding-box`.

  Painter's own default for both relative flags is on. So until the box size is recorded, a bake with Painter's default distances is a release gap. The manifest says so rather than hiding it.

### 3. The parameter model from the observation (item 2.8)
- **The source.** The Phase 0 capture exists: `tier0/defaults-templates/baking-defaults`, recorded on Painter 12.1.0 and again on 12.1.5. It reads every `Property` getter of `common()` and the ten bakers, on a fresh project, after save and reopen, and on a second fresh project.
  - On 12.1.5 the three recordings are equal (record `53d9cfc9...`).
  - 12.1.0 differs only in `SkewFaceBehavior`'s labels.
- **The reading of the no-copy rule** (the coordinator, 2026-10-20). Painter's pixels, raw records and outputs never enter the repository. API metadata (names, labels, widget types, enum integers, ranges, defaults) is observed behaviour that the clean room reproduces: `docs/licensing-and-clean-room.md` §2 admits "property names/labels discovered through `Property` introspection". This follows the precedent of `assets/templates/*.json`.
- **The model.** `src/bake/baking_parameters.*` builds every `PropertySpec` from the authored table `assets/defaults/baking.json`, embedded through `EmbedInputs` (`src/bake/baking_catalog.cpp`). Decision 306's hand-made specs from the public pages are replaced.
  - **The keys.** `common()` has 19 keys; `baker(usage)` has the observed keys of every usage (none for Normal, WorldSpaceNormal and Opacity). Maps are ordered by short name, which is Painter's `keys()` order.
  - **What a `Property` answers.** `name()`, `label()`, `widget_type()`, `enum_values()` and `enum_value()` answer from the table.
  - **Enum values.** Values are stored by label; integers come only from `enum_values()`.
  - **Value types.** They follow the type of Painter's `value()`: `Bool`, `Int`, `Float`, `IntPair`, `FloatPair`, `Enum` and `String`. A `Float` key accepts an integer.
- **What stays refused:**
  - `Property.properties()`: the meta properties carry Painter's descriptive text (descriptions, status tips). The clean room does not copy Adobe prose beyond the short labels the API returns.
  - Out-of-range values. `set()` refuses a value outside a key's `min`/`max` (`minPow2`/`maxPow2` for `OutputSize`) with `NotYetSupported`, since how Painter treats one (clamp or refuse) is not recorded.
  - Other bakers' values. Storing a value for a baker other than AO stays with its owner task (decision 311); those values are readable.
- **Corrections to decision 306's public-page reading.** The observed labels replace it:
  - `CageMode` is labelled "Cage type", with the options "Distance-based", "Automatic (experimental)" and "Custom file";
  - `SubSampling` has the options "None" and "Subsampling 2x2", "4x4", "8x8";
  - `LowAsHigh` is labelled "Use Low Poly Mesh as High Poly Mesh".
- **`RequestFromParameters`.** It now reads `MaxHeight`, `MaxDepth`, `RelativeScale`, `NbSecondary`, `MinDistance` and `MaxDistance` from the parameters.
  - **Refused with `NotYetSupported`,** naming their owner: a value the baker does not implement. That is `OffsetMap` given, `Attenuation` other than None (Painter's default is Linear), `Spread` other than 180, `IgnoreBackfaceSecondary` other than Never, `FilterMethodSecondary` other than Always, and `GroundPlane` on.
  - **Not read.** `SmoothNormals` and `SkewFaceBehavior`: the baker's ray-direction reading of decision 302 applies, pending evidence. They are listed in `keys_not_read`.

### 4. The authored defaults and their local check (item 2.9)
- **The table.** `assets/defaults/baking.json` is authored by UzmiGames, entry by entry, from the observation; no script generates it from the record.
  - Each entry's `provenance` names the record's SHA-256 and its output.
  - A default is the fresh project's `value()`. Where Painter states no `defaultValue` (`OutputSize`, `TonemappingBounds`), the default is null with a note, and `value()` refuses until a value is set.
  - The texture set's baking state is recorded too: the curvature method, the enabled bakers and the enabled flag.
- **The check.** `tools/bake/bake_defaults.py` resolves the cited record in the private store, read only. Its problems name the key and the cited hash, never a value. It compares every entry's fields, the key order, every recording's agreement and the state. `--model` also compares the native model's dump with the table.

### 5. The MCP Baking parameter tools (item 2.11)
- **Where they run.** The worker serves them in `src/supervisor/typed_tools.cpp`, with the families' registration pattern.
  - `UzPainter.exe` compiles the parameter model (`bake_request`, `baking_parameters`, `baking_project`, the embedded table), but not Embree or the CPU baker.
  - Each change is one transaction: `bake::EditBakingSession` inside the call's admitted mutation.
- **The tools:**
  - `bake_inspect` (read): the values the texture set bakes with (null where nothing is established), its explicit `bake_settings`, its link groups, the fresh texture set's baking state and, with `properties`, every key's metadata;
  - `bake_configure`: `common` and `per_baker` values, typed per key, with an enum taking its label or its integer;
  - `bake_set_mesh_inputs`: `HipolyMesh` as `file:///` URLs joined by `|`, and `CageMesh`. Each file must exist; no URL encoding is applied;
  - `bake_capture_preset` (read): the explicit values as a `uzpainter/bake-preset/1` file inside the output root;
  - `bake_apply_preset`: replaces the explicit values of the named sets (all, by default) with a preset's, checked like `LoadBakeSettings`.
- **Errors.**
  - A wrong type, an unknown key, an unknown label and a malformed preset are `invalid_arguments`.
  - A model `NotYetSupported` is `capability_gap`: out of range, another baker's value.
  - `enabled`, `bakers`, `uv_tiles` and `curvature_method` are gated values (`x-uzpainter-capability`). Each declares its `BakingParameters.set_*` symbol, a release gap, so the supervisor refuses them before admission, and the worker refuses them for a direct pipe client.
- **No operation of their own.** The tools declare none: the `substance_painter.baking` Python symbols they used to cite stay release gaps until the parameter API is bound to Python. Their matrix rows are `available`, with the Python-disabled fixture `test_bake_parameter_tools_with_python_disabled`. Every result is labelled `pending-evidence`.
- **What stays a gap.** `bake_start` remains a gap tool (`phase3.5_embree-bakers`).

## Alternatives Considered

- **Refusing `set({CageMode: Automatic})`.** Rejected. The value and its enum label are API metadata; only the bake behaviour is unknown.
- **Reproducing `properties()` without its text fields.** Rejected. A dictionary missing Painter's keys is a silent difference; the call is refused instead.
- **Clamping out-of-range values.** Rejected. It is unrecorded, so it would be a guess.
- **Generating the table from the record.** Rejected by `06-baking.md` §2: the table is authored and then checked.
- **Keeping the Python symbols as the tools' operations.** Rejected. They would keep the tools gapped while the native model serves them; the matrix row would misreport the tool.
- **Leaving the owners at `phase3.1_baker-request-model`.** Rejected. Once this task closes, a refusal must name the task that still owns the missing evidence.

## Consequences

- Changed: `tools/capabilities/painter-api-inventory.json`, `generate_capabilities.py` (`RELEASE_GAPS`), `tests/capabilities/test_capabilities.py`, `docs/architecture/10-python-api.md` §3, `tools/capabilities/README.md`, and the refusal messages in `src/bake/embree_baker.cpp` and `bake_request.cpp`.
- Item 2.7 adds the `apply-diffusion` and `relative-to-bounding-box` entries to the inventory.
- Items 2.8 and 2.9 add:
  - `assets/defaults/baking.json`;
  - `src/bake/baking_catalog.{h,cpp}` (with two `EmbedInputs` lines and a source list in `build.zig`);
  - `tools/bake/bake_defaults.py`;
  - `tests/bake/test_bake_defaults.py`;
  - the `catalog` case of `uzp-baking-project-tests`.

  They rewrite `src/bake/baking_parameters.*` and its native cases.
- Item 2.11 changes:
  - `src/supervisor/typed_tools.{h,cpp}` (with `ToolContext::output_path`) and `worker.cpp`;
  - `build.zig` (`bake_parameter_sources` in `UzPainter.exe`);
  - `tools/capabilities/mcp-tools.json` (regenerated from a live worker) and `operation-matrix.json`;
  - the baking prompt;
  - `src/supervisor/SUPERVISOR.md`;
  - the supervisor and capability tests.
- The bytes of every bake are unchanged. Parity stays `pending-evidence`.
