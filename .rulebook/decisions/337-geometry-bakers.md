# 337. Geometry bakers on the CPU core: WorldSpaceNormal as the signed float32 high normal at the hit; Position as the hit point with Mode and Axis and only Normalization None (centimetres); ID as Mesh ID labels with no colour generator; every unrecorded parameter value refused before any work; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.4_baker-world-space-normal, phase3.4_baker-position, phase3.4_baker-id, phase3.5_embree-bakers

## Context

The coordinator asked for the offline items of three baker tasks on the Embree CPU core of decisions 302, 306 and 311 (the pattern of the native Normal baker, `06-baking.md` §3.2), CPU-only, with this rule: a parameter whose Painter semantics are unrecorded is refused with `NotYetSupported`, and nothing is claimed equal to Painter.

What is recorded about the three bakers:
- `assets/defaults/baking.json` (decision 323): the keys, labels, enum integers and defaults. WorldSpaceNormal has no keys. Position has `Mode` (All axis / One axis, default All axis), `Axis` (X / Y / Z, default X), `Normalization` (BBox / BSphere / None, default BSphere) and `NormalizationScale` (Per Material / Full Scene, default Full Scene). ID has `ColorSource` (Vertex color / Material color / File ID / Mesh ID / Polygroup / Submesh, default Material color) and `ColorGenerator` (Random / Hue shift / Grayscale, default Hue shift).
- No Tier 2b golden of any of the three exists, and no recorded output states a channel format, a value mapping, a normalisation formula or a palette.

No model panel ran: the coordinator fixed the rule, and each fork below applies it.

## Decision

### 1. The rule
- **Implemented** (UzPainter's own reading, `pending-evidence`): a value whose label names exactly one computation on data the bake mesh carries, with no constant or choice the label leaves open.
- **Refused before any work** (`NotYetSupported`, naming the owner task and this decision): a value whose computation needs a formula, a constant or an input that nothing recorded fixes.
- Both apply to a native `BakeRequest`; `RequestFromParameters` maps every label to the request, so a parameter-made request meets the same refusals.

### 2. Shared to all three
- They run on the shared primary hit of `embree_baker.cpp`: the same texel candidates, primary ray, name matching, `IgnoreBackface`, cage, hidden mask and classes. Combined with AO or Normal they share the hits and leave those maps' bytes alone.
- A non-hit texel holds zero and is told apart by the class map; nothing is filled.
- `SubSampling` above 1 and `DilationWidth` above 0 are refused: the resolve rule of these maps and their padding are not recorded (the Normal baker's bound, `06-baking.md` §3.2).
- The canonical bytes keep `UZPBAKE3`/`UZPBAKE4` for results without these maps. Each map present is appended as a tagged block after the distance record.
- Every map is written by one texel's own slot, so the bytes do not depend on the worker count (decision 302).

### 3. WorldSpaceNormal (phase3.4_baker-world-space-normal)
- The value is the high mesh's interpolated corner normal at the primary hit, normalised in double: the vector the AO and Normal paths already compute. `LowAsHigh` hits the low parts, so the low mesh's own normal is used.
- The frame is the meshes' scene frame (`mesh_inputs.h`: object transforms applied, normals through the inverse transpose).
- **Stored unencoded**: `BakeResult::world_normal`, float32 xyz, signed. Painter's channel format and value mapping (item 2.2) are established by the Tier 2b goldens, so no encoding is chosen here. The block tag is `WSN1`.
- **Settles it:** a WorldSpaceNormal golden (sphere and bevelled cube) for the encoding and the frame.

### 4. Position (phase3.4_baker-position)
- **The point.** The high surface point at the primary hit: Embree's barycentrics on the hit triangle, blended in double, in the meshes' scene frame. `LowAsHigh` gives the low surface point.
- **`Mode` and `Axis`.** All axis writes x, y and z; One axis writes the coordinate on `Axis`, one channel. The labels name these choices, so they are implemented.
- **`Normalization` None.** The coordinate in centimetres: the mesh-unit value times the request's `scale_to_internal`, the project's unit rule (`12-mesh-import.md` §3, decision 311). No bounds apply, so `NormalizationScale` has no effect, and the record says so.
- **`Normalization` BBox and BSphere: refused** before any work. Nothing recorded says which bounds they use (the texture set's or the whole scene's, the low or the high meshes), nor whether a box maps each axis on its own or keeps proportions, nor which sphere bounds the mesh. BSphere is Painter's default, so a Position bake with Painter's defaults is refused, as an AO bake with Painter's default `Attenuation` is (decision 323).
- **The map.** `BakeResult::position`, float32 and unclamped, one or three channels per texel. The block tag is `POS1`.
- **The record.** `PositionNormalizationRecord` holds the four settings, the channel count, the unit scale and whether bounds applied. `PositionNormalizationJson` gives it as the binding's `baked.effective_normalization` (Painter's labels, `unit: centimetre`, `bounds: null`). Publishing the binding and the receipt belongs to `phase3.3_baker-evidence-publication`; nothing writes them yet.
- **The parameter model.** Position's values are now stored per texture set (`StoresBakerValues`), saved in `bake_settings.per_baker.Position` and loaded like AO's. They form no link group: a Position link group stays `NotYetSupported`, naming this task. `RequestFromParameters` maps all four labels, and the baker refuses the values above.
- `baking_project.cpp`: an AO link group compares only its members' AO values, so a member's own Position values no longer read as a conflict; saving keeps every stored baker's values.
- **Settles it:** a Position golden for each `Normalization` and `NormalizationScale` on a non-cubic mesh with highs.

### 5. ID (phase3.4_baker-id)
- **The label.** `ColorSource` Mesh ID / Polygroup: a hit texel's label is the index of the high mesh it hit, plus one, in request order (`HighMeshes` gives one mesh per object, in object order). `LowAsHigh` labels by low part. Zero means no hit. The bake mesh carries no polygroups, so a mesh is one group.
- **The map.** `BakeResult::id_labels`, uint16 per texel, and `id_label_meshes`, the mesh names in label order. The block tag is `IDM1`. These are what the exact label-equality diagnostic of item 2.3 compares; that diagnostic belongs to the comparison tool and is not written here.
- **No colour map.** Every `ColorGenerator` is refused before any work: the colour Painter gives a label under Random, Hue shift or Grayscale (its hue spacing, saturation, value, grey levels and random sequence) is not recorded, and the task says it is established black-box against the goldens. The request's generator is optional: absent, the bake produces the label map only, an evidence request no parameter makes. `RequestFromParameters` always sets one, so a parameter-made ID bake is refused until a golden settles the palette.
- **Refused sources.** Vertex color, Material color and File ID need inputs the bake mesh does not carry (vertex colours, the material's colour, an ID file and its mapping); Submesh is not described by anything recorded. Each is `NotYetSupported`. Material color is Painter's default.
- **The parameter model.** ID's values are stored per texture set like Position's, saved in `bake_settings.per_baker.ID`, with no link group.
- **Settles it:** an ID golden for each generator on the bevelled cube split into named meshes; for the other sources, the bake-mesh inputs and a golden each.

## Alternatives Considered

- **Encoding WorldSpaceNormal like the Normal map, `n * 0.5 + 0.5` in RGB16.** Not taken. It would be a channel format and a value mapping nobody recorded, and item 2.2 says the goldens establish them. The signed floats lose nothing, so any encoding the goldens settle can be applied to them.
- **Implementing BBox and BSphere with a reading of our own** (each axis mapped to the box, the sphere around the box). Rejected under the rule: the bounds and the mapping are choices nothing recorded fixes.
- **Palettes of our own for the three generators** (evenly spaced hues, grey levels, a hashed colour). Rejected under the rule: hue spacing, saturation, grey levels and the random sequence are choices the labels leave open, and the task says the palette is established against the goldens.
- **Averaging sub-samples or dilating like AO.** Rejected: the resolve rule and padding of these maps are not recorded, and an average of normals is a choice of its own.

## Consequences

- New: `src/bake/world_normal_baker.{h,cpp}` (in the `bake-feasibility-tests` step) and `tests/bake/world_normal_bake_cases.h`.
- Changed: `bake_request.*` (the `world_normal` map and its `WSN1` block), `embree_baker.*` (the usage, its validation and its texel write), `tests/bake/bake_feasibility_test.cpp` and `test_bake_feasibility.py` (six native cases and the `world_normal` cross-process fixture), `06-baking.md` §3.3.
- Position: new `src/bake/position_baker.{h,cpp}` and `tests/bake/position_bake_cases.h` (seven native cases, the `position` cross-process fixture); changed `baking_parameters.*` (Position values stored, saved, loaded and mapped), `baking_project.cpp` (an AO group compares only AO values; saving keeps every stored baker) and `tests/bake/baking_project_test.cpp` (the round trip carries a Position value).
- ID: new `src/bake/id_baker.{h,cpp}` and `tests/bake/id_bake_cases.h` (seven native cases, the `id` cross-process fixture); `baking_parameters.*` store, save, load and map ID's values.
- The bytes of every AO and Normal result are unchanged: the block exists only when the map does.
- No Python or MCP symbol is added. `BakingParameters.set` through Python and MCP `bake_configure` now store Position and ID values, where they refused them before. Parity stays `pending-evidence`; every Tier 2b item stays open.
