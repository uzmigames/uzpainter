# 348. An empty paint layer is transparent; `project.create` makes Painter's "Layer 1"; the whole-bitmap operation stores a bitmap only as the plane's texels

**Status**: accepted
**Date**: 2026-10-21
**Related Tasks**: phase4.1_nodes-paint-layers, phase1.19_pyapi-native-module, phase1.20_pyapi-facade

## Context

Task `phase4.1_nodes-paint-layers` items 2.1, 2.2, 2.4 (empty planes), 2.8, 3.5 and 3.7 can be done offline: no new recording is needed for them. Decision 105 §4 left Painter's default paint layer "Layer 1" to this task. Until now the evaluator and the support check refused every paint layer (`support.cpp`, `dag.cpp`).

Measured facts, from the admitted goldens of the current envelope `painter-12.1.5_js-api.1.1.20` (scan script `tmp/scratch/paint-layers/scan_layer1.py`, log `scan_layer1.log`, private records read through the oracle store):

- 333 goldens have private records. 327 of them start with `project.create`; the 6 others are the three wand-v1 Tier 1 pipeline runs, `tunic-v10` (it opens a project), and the two lifecycle probes, which create the project at step 2.
- Five Tier 0 api-probes read "Layer 1" back. Four read the root layers: `fill-layer-readback`, `insert-positions`, `phase1-delete-node` and `phase1-reload-mesh`. In both recordings of each, the bottom root layer is `{"name": "Layer 1", "node_type": "PaintLayer", "visible": true, "has_mask": false, "Content": [], "Mask": []}`. In `phase1-layer-navigation`, `s30/get_next_sibling` of a top-level group is "Layer 1" in both recordings, and `s88/get_selected_nodes` is `["Layer 1"]` in the first one.
- No instruction sequence deletes or edits "Layer 1": every `delete_node` names a node a step inserted, and every recorded insertion is at `top`.
- The wand-v1 pipeline records "Layer 1" as the one root layer its sync hid.
- `insert_paint` at `top` gives a `PaintLayer` named "Paint" (`phase1-layer-stack-events` s14, both recordings, with `LayerStacksModelDataChanged`). Inside a content stack it gives a `PaintEffect` named "Paint" (`phase1-layer-node-kinds` s5). The native default name was "Layer".
- The native evaluator creates no "Layer 1" and matches many Tier 0 texture goldens exactly, all recorded over Painter's "Layer 1". On those configurations an empty paint layer at the bottom of the stack changes no channel. `fill-layer-readback`'s Height export is compared on every texel by `tests/python/test_pyapi_tier0.py`, now with "Layer 1" present natively.
- The plane store (phase1.5) holds a plane's texels in the channel's native format without coverage. Its `DecodePng` and `DecodeExr` read a bitmap as a plane format only when the layout matches exactly.

The hypothesis "every Tier 0 golden was recorded with an empty Layer 1" holds for the 327 goldens created by `project.create`, under the reading above. Only these five probes show it directly, all on the default template and a single texture set. For the templated goldens and for meshes with several texture sets, the layer is inferred from `project.create`, not read back.

## Decision

1. **Empty paint layers are transparent.** A paint layer with no plane bound and no content effect (`core::IsEmptyPaintLayer`) contributes nothing to any channel, whatever its mode, opacity, mask and visibility. The support check accepts it. The DAG skips it, as it skips a fill with no source on the channel. Texture state does not count it as content. This is the same precedent as a fill with no active channel. Still refused, before mutation and at evaluation:
   - a paint layer holding plane content (item 2.4, with the Tier 0 goldens of 2.5 and 3.2);
   - a content effect on a paint layer (item 3.4);
   - every paint effect (item 3.1: no golden records an empty paint effect's output).
2. **`project.create` makes "Layer 1".** `Session::Create` inserts an empty paint layer "Layer 1" in every stack it creates, at the bottom, in the creation revision. Every template and multi-set mesh gets it too. That part is inferred, not read back (see Context). The recording that settles it is a structure readback after `project.create` with a template and with a two-material mesh. The facade's selection after creation is that layer, as `s88` records.
3. **`insert_paint`.** A new paint layer is named "Paint". The facade's `insert_paint` emits `LayerStacksModelDataChanged`. The native and facade `insert_paint` of a layer are no longer refused.
4. **The whole-bitmap operation stores texels as they are.** `store::StageBitmap` (`ProjectStore::WriteBitmap`) writes a project resource into the plane of each addressed channel of a paint layer or content paint effect, in one transaction: a new plane on UV tile 1001 when the node holds none on the channel, then a new copy-on-write version. The resolution is the texture set's and the format the channel's. Every check runs before anything is staged. It raises `NotYetSupported` naming item 2.5 for:
   - a bitmap of another size (resampling is not recorded);
   - a bitmap whose layout does not hold the plane's texels as they are (no conversion is recorded);
   - a mask-stack paint effect (its plane format is not recorded);
   - a project outside the Default workflow (phase4.5_uv-tiles).

   Plane content stays unevaluated (1). The operation's public surface, the native `paint_set` and MCP tool, is item 2.7.

## Alternatives Considered

- **Keep "Layer 1" out (decision 105 §4).** Rejected now that an empty paint layer is evaluated. Every structure readback, sibling walk, selection and sync differed from Painter's.
- **Accept an empty paint layer only at the bottom with Painter's defaults.** Rejected. The layer contributes nothing anywhere, as a fill without a source does, and refusing a rename or a hide of "Layer 1" would refuse Painter's own recorded pipeline (the wand sync hides it).
- **Accept empty paint effects too.** Not done. No golden records the output of one, and their content and mask mixes would be inferred.
- **Convert or resample bitmaps in the whole-bitmap operation.** Rejected: no recording fixes the rule.

## Consequences

- Removed exclusions: "Layer 1" in `tests/python/test_pyapi_tier0.py` and `test_pyapi_facade_tier0.py`; `s30` and `s88` in `test_pyapi_observed_layer_tier0.py`; `s14` in `test_pyapi_observed_tier0.py`.
- Capability entries follow the trace (decision 112): `insert_paint`, `PaintLayerNode` (context `any`) and `NodeType.PaintLayer` move to what the compared replays exercise. The `bitmap-or-projection-content` gaps stay.
- Tests that assumed an empty new stack change with it. The Assets3D adapter's sync now hides "Layer 1", as Painter's wand-v1 run records. MCP tests no longer use a paint layer as their example of a native release gap.
- Items still open: 2.3 (excluded: projected bitmaps), 2.5, 2.6, 2.7, 3.1–3.4, 3.6, 3.8, 4.1.
