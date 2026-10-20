# 311. CPU baker slice 3: the Embree pin in build.zig, distances in centimetres over the mesh's unit scale, distances relative to a named bounding-box size, mesh-file inputs with the cage paired by vertex index, link groups and bake_settings as one transaction, and the parameter-to-request mapping; ApplyDiffusion stays refused; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_baker-request-model, phase3.4_baker-ao, phase3.5_embree-bakers

## Context

A third permitted slice of `phase3.1_baker-request-model` (SUP-014), after decisions 302 and 306, and not its acceptance. The coordinator asked for the next open code items: the mapping from parameters to `BakeRequest`, relative (bounding-box) distances and units, `ApplyDiffusion`, cage files and linked groups. Decision 302's contract holds: equal bytes at 1, 4 and N threads, miss classes kept, refusals explicit.

Admitted sources for Painter facts:
- Adobe's mesh-map settings page (A-HELP-BAKING): "Apply Diffusion: Enable this box to apply diffusion to the edges of generated information"; a custom cage file "must have the same number of vertices as the base mesh"; "Relative to Bounding Box: ... other settings that refer to distance are based on the bounding box of the project mesh", where a distance of 1 is the size of the bounding box.
- Painter's public Python API page `baking.html`: the link-group functions, their wording ("share the same baking parameters", the reference's parameters "applied to the whole group", `unlink_all` leaves "all Texture Sets [with] their own copy"), and the example comment that common parameters are shared "at project creation".
- `docs/architecture/12-mesh-import.md` §3: Painter's unit is the centimetre, and the mesh stores `scale_to_internal` (centimetres per file unit).

**Panel** (2026-10-19, `cx/gpt-5.6-sol`, `kimi/kimi-k3`, `xai/grok-4.5`):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 relative distances, diagonal size | disagree | partly | partly |
| C2 units over `scale_to_internal` | partly | agree | agree |
| C3 `ApplyDiffusion` as a pull-push fill | disagree | partly | partly |
| C4 cage files, pairing by object and triangle | disagree | partly | disagree |
| C5 link groups | partly | partly | agree |
| C6 `bake_settings` persistence | agree | agree | agree |
| C7 parameters to request | partly | agree | agree |
| C8 the pin in build.zig | disagree | agree | agree |

What the panel changed:
- C1: which size "the size of the bounding box" means is pending (all three). The request names the metric; nothing guesses it.
- C2: no default unit scale (GPT): a request without `scale_to_internal` is refused.
- C3: refuse `ApplyDiffusion` until a recording settles it (GPT and Grok; Kimi read the wording as an edge band, not a fill). It stays `NotYetSupported`.
- C4: no topology rule stricter than the page's "same number of vertices" (all three). The cage pairs with the low mesh by vertex index (Grok), and only on identity transforms.
- C5: regrouping, a reference outside the group and a group of one are refused (GPT and Kimi): the API does not say what they do.
- C7: the keys taken from the request are listed (Kimi).
- C8: GPT asked for the artifact to be pinned too. It is: `thirdparty/embree/MANIFEST.json` holds the DLLs' SHA-256, and the device is checked at run time.

## Decision

### 1. The Embree pin (item 2.1)
- `build.zig` `bake_flags` pins the package: `UZP_EMBREE_PINNED_VERSION=40401`, `UZP_EMBREE_PINNED_ISA="avx2"`, `UZP_EMBREE_PINNED_TASKING=1` (TBB). It also compiles `src/bake/` and its tests with `-fno-fast-math -ffp-contract=off`.
- `embree_baker.h` refuses to compile without them. A device whose tasking system is not TBB is unqualified, like a wrong version or ISA.
- The bytes are unchanged: the default target is baseline x86-64, which has no FMA to contract.

### 2. Units (item 2.7)
- `BakeRequest::scale_to_internal` is the mesh's `units.scale_to_internal`. It is required: 0, not finite or not positive is a `ValueError`.
- Absolute distances (`max_height`, `max_depth`, AO `min_distance`, `max_distance`) are centimetres. Each becomes `float(double(d) / scale_to_internal)` mesh units before any work.
- `BakeResult::distances` records the scale, the relative flags, the box size and metric, and the effective mesh-unit distances. The canonical bytes become `UZPBAKE3`, with the record after the counts.

### 3. Relative distances (item 2.5)
- `DetailSettings::relative_to_bounding_box` (`RelativeScale`) and `AoSettings::relative_to_bounding_box` (`MaxDistanceRelativeScale`) make a group's distances fractions of the box size: `float(double(d) * size)`.
- The box is the project mesh's (every texture set's parts), given by the request (`project_bounds`; `SceneBounds` computes it from a texturing mesh). A relative request without it is a `ValueError`. It is never computed from one texture set.
- The size metric is the request's `box_size_metric`, `Diagonal` or `LargestExtent`. Without it, a relative request raises `NotYetSupported`. The parameter model never sets it.
- **Settles it:** a Painter recording with a relative distance on a non-cubic mesh.

### 4. Mesh files and the cage file (item 2.5; `src/bake/mesh_inputs.*`)
- `ReadBakeMeshFile` reads OBJ, FBX or glTF with UzPainter's raw loaders, without the import's UV-tile check, tangents or unit conversion.
- A bake mesh has one vertex per triangle corner, nothing welded. Positions are in the file's scene space; normals go through the inverse transpose. A mirroring or singular transform is `NotYetSupported`.
  - `LowParts(mesh, material)`: one part per object with triangles of the material, named after the object.
  - `HighMeshes(mesh)`: one mesh per object.
- `CageParts(cage, low, material)` follows the page's one rule, the same vertex count (otherwise `ValueError`). The cage point of a low corner is the cage file's position with that corner's position index.
- Both files must have identity object transforms (otherwise `NotYetSupported`): which transform carries a vertex shared between objects is not established.
- `CageMode::CustomFile` without one cage per low part is now a `ValueError`; it was `NotYetSupported` while no file could be read.
- **Settles it:** a Painter recording with a custom cage file.

### 5. `ApplyDiffusion` (item 2.7)
Still refused with `NotYetSupported`, by the panel's majority. The wording supports more than one reading (a fill of the empty texture, or a band at the island edges), and either would be a guess. **Settles it:** one fixture baked with diffusion on and off.

### 6. Link groups (item 2.10)
`BakingSession(texture_sets)` holds every set's parameters.
- **One copy per group.** A group shares one copy of its keys, called a slot: the common group the common and detail keys, AO's group the AO keys. Other usages raise `NotYetSupported` naming their owner task.
- **At creation.** With two or more sets, every set starts in the common group, as the documented example states.
- **`set_linked_group(group, reference, usage)` and `set_linked_group_common_parameters`** copy the reference's slot to every member. Refusals:
  - an unknown or repeated set: `ValueError`;
  - a reference outside the group, fewer than two sets, or another group already linked for those keys: `NotYetSupported`.
  - Linking the same group again re-applies the reference.
- **`unlink_all*`** give every member its own copy of the current values.
- **Queries.** `get_link_group*` return the group, or empty when there is none. `get_linked_texture_sets*` return the group, or the set alone. Lists are in texture set order.
- **One transaction.** `BakingParameters::set` checks the whole batch before writing. A key named twice through linked members is a `ValueError` (it is one parameter). `revision()` advances once per accepted change and never on a refusal.

### 7. `bake_settings` (item 2.10)
- `ToBakeSettings` writes only the values that were set, never a default. It uses Painter short names: common keys in `common`, detail keys in `detail`, AO keys in `per_baker.AO`.
- JSON types: bool, integer, `[a, b]`, the option label for an enum, string.
- `LoadBakeSettings` checks everything like `set()`, then replaces the set's slots. It refuses the whole load for:
  - an unknown key or a key in the wrong group;
  - a wrong type, a pending type or an unknown option;
  - another baker with values.
- Loading a linked set loads its group.
- Link groups have no manifest field yet and are not persisted.

### 8. Parameters to a request (item 2.8)
`RequestFromParameters(parameters, base)` writes every key of known type into its request field.
- **Values.** Each such key must have a value (set, or documented), otherwise `NotYetSupported` (item 2.9).
- **Labels to request values:**
  - `CageMode`: Distance based / Automatic (experimental) / Custom file;
  - `SubSampling`: None / 2×2 / 4×4 / 8×8 as 1 / 2 / 4 / 8;
  - `FilterMethod`;
  - `Distribution`: only `Cosine` is documented.
- **Pending keys** keep `base`'s fields and are listed in `keys_from_request`: `MaxHeight`, `MaxDepth`, `RelativeScale`, `NbSecondary`, `MinDistance`, `MaxDistance`.
- **Mesh inputs.** `HipolyMesh` and `CageMesh` belong to the mesh-input step; `base` carries the meshes.
- **Refusals.** `GroundPlane` on raises `NotYetSupported` (`phase3.4_baker-ao`), and a log2 size outside [0, 31] is a `ValueError`.

### 9. Scope
- AO stays the only usage, `pending-evidence`, owned by `phase3.4_baker-ao`.
- No Python or MCP symbol is exposed: `uzpainter.baking` stays gapped and the capability manifest is unchanged.

## Alternatives Considered

- **A default unit scale of 1:** rejected (GPT). A request that forgets the unit is refused, not assumed to be in centimetres.
- **The diagonal as the box size:** not chosen without evidence. Both metrics are implemented, and the request must name one.
- **Pull-push diffusion, or a diffusion limited to an edge band:** both are guesses until recorded.
- **Pairing the cage by object and triangle:** rejected, since it is stricter than Painter's documented rule.
- **Replacing an existing group on `set_linked_group`:** not established, so refused.

## Consequences

**Files.**
- New: `src/bake/mesh_inputs.{h,cpp}`.
- Changed: `bake_request.*`, `embree_baker.*`, `baking_parameters.*`, `build.zig` (`bake_flags`; the bake tests link `uzp_mesh`) and `tests/bake/*`.

**Tests.** `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 39 passed. That is 33 native cases and the cross-process tests, with seven new native cases: `units`, `relative_distances`, `cage_file`, `cage_file_threads_in_process`, `linked_groups`, `bake_settings` and `parameters_to_request`. The cross-process `cage_file` fixture has the same bytes at 1, 4 and 32 threads, SHA-256 `c65e3519188b54cf3d8b5ac379622cdb8f6f44ebd8e3741b429371ed3acb284c` (one build and machine; not a golden).

**Still open:**
- `ApplyDiffusion`;
- the box-size metric and the cage pairing, against evidence;
- persisting the link groups;
- Tier 0 metadata and defaults (items 2.8, 2.9, 3.1, 3.2);
- the MCP tools (2.11);
- Tier 2b evidence.
