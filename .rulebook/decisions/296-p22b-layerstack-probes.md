# 296. P22-B for layerstack, levels, properties and colormanagement: six requests exercise 76 pending symbols, `properties` is read by the recorded baking defaults, and three amendments to decision 112

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.24_python-api-facade

## Context

Decision 189 split P22-B, the pending-evidence Painter symbols that no request exercises, to `phase1.24_python-api-facade` item 3.4, by module. This decision covers four modules. Decision 295 covers textureset, project, export, baking and source. Decision 297 covers the other modules.

On main (39d8d7b), the capability manifest (`tools/capabilities/painter-api-inventory.json`) lists 86 pending-evidence symbols in these four modules that decision 188's requests do not reach:

- `layerstack`: 59. The manifest has 74 pending; decision 189 names the other 15 (`BlendingMode.Multiply`, `FilteringMode.Nearest`, `FillLayerNode.reset_source` and `set_symmetry_enabled`, `LayerNode.enable_mask`, `remove_mask` and `set_mask_background`, `LevelsEffectNode` with `affected_channel` and `set_parameters`, and five `NodeType` members).
- `levels`: 15.
- `properties`: 10.
- `colormanagement`: 2. Decision 189 counted 5. Three of them have become `supported` since then, so 2 remain: `Color.sRGB` and `Color.value`.

Facts that decide the routes:

- The Tier 0 facade replay (`tests/python/test_pyapi_facade_tier0.py`) runs `painter_probes.py` itself inside UzPainter. A request's calls are therefore replayed as written. `tests/python/capability_trace.py` counts a symbol when a call to it returns or raises something other than a UzPainter refusal, when an enum member is passed or returned, or when a public-class instance is returned.
- UzPainter refuses `insert_paint`, `instantiate`, `insert_filter_effect` and `insert_generator_effect` (all four are `release-gap`; the last two raise `UnsupportedProcedural`, phase3.3_procedural-families). As a result, no UzPainter node has the type `NodeType.PaintEffect`, `FilterEffect`, `GeneratorEffect` or `InstanceLayer`, and none has an `InstanceLayerNode.instance_source`.
- In the python-doc, `layerstack.EffectNode` is an alias of the effect node classes, not a class with members. Calling it does nothing, and an `isinstance` check is not a call the trace can attribute to it.
- No Phase 1 call returns a `properties.Property`. `SourceSubstance.get_properties` and every `BakingParameters` call are release gaps (`src/python/PYAPI.md`). The recorded golden `tier0/defaults-templates/baking-defaults` already reads every documented `Property` getter on every baking parameter: `value`, `name`, `short_name`, `label`, `widget_type`, `enum_values`, `properties`, and `enum_value` for every label (RECORDER.md §8).
- No symbol in these modules is unsafe or nondeterministic to call in a recording session. Selection, collapse and scoped modifications are layer-stack UI state that a probe sets and reads back in the same step sequence.

The model panel was not consulted. Each route follows the text of decisions 112 and 189, and the three amendments below only state where P22-B's own replay cannot provide the evidence.

## Decision

1. **Vocabulary** (`tools/parity/recorder/painter_probes.py`, block "P22-B layer stack, levels and colour"). Every call is written out explicitly; there is no `getattr` or `vars`. `documented_symbols.json` names the python-doc object of each new symbol, and `python -m tools.parity.recorder check` passes.
   - New edits:
     - `GroupLayerNode.set_collapsed` (`collapsed`)
     - `FillEffectNode.reset_source` and `set_symmetry_enabled`
     - `instantiate` (position, `layer_step`)
     - `insert_filter_effect` and `insert_generator_effect` (position, `search`: the first result of the documented `resource.search`, as `effect-order` finds its Blur filter)
     - `set_selected_nodes` (`node_steps`)
     - `set_selection_type` (`selection_type`)
     - `ScopedModification` (`name`, `new_name`, `opacity`, `channel`). The rename, the opacity edit, `set_selected_nodes`, `set_selection_type` and `get_name` run inside the scope, and each inner outcome is recorded.
     - `levels.LevelsParamsMono` and `levels.LevelsParamsRGB`: built with all six fields, set through `LevelsEffectNode.set_parameters`, and read back field by field together with their class.
     - `colormanagement.Color.sRGB` with `value`: either assigned on the colour of a uniform source and set back with `SourceUniformColor.set_color`, or assigned on a built colour, in which case its `sRGB`, `working`, `value_raw` and `color_space` are returned.
   - New readbacks:
     - `GroupLayerNode.is_collapsed`
     - `FillLayerNode` and `FillEffectNode` `is_symmetry_enabled` and `get_material_source`
     - `InstanceLayerNode.instance_source` and `LayerNode.instances`
     - `Node.get_parent`, `get_next_sibling`, `get_previous_sibling` and `get_texture_set` (by name)
     - `EffectNode` (`isinstance`)
     - `get_selected_nodes` (of the active stack) and `get_selection_type`
     - `Color.sRGB` and `Color.value`, either of a uniform source's colour or of a colour built from `color` and an optional `color_space`
   - The fake Painter (`tests/parity/recorder/fake_probe_painter.py`, `extend_layerstack_p22b`; `fake_painter.py`'s `BlendingMode` members) supports each call, under its own stated rules. `tests/parity/recorder/test_api_probes_p22b_layerstack.py` tests each behaviour, and checks that every pending symbol of the four modules is requested here, routed by §2, or covered by decision 188.
2. **Requests** (`parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/tier0/api-probes/`). All are Tier 0 observed probes on the plane in a Legacy session. Every edit is a `probe: true` step followed by its readback, in `r1` and after save and reopen in `r2`, and every enum member is passed where its owner call takes it. Each validates against `golden-public.json` and records `r1` and `r2` against the fake (`test_api_probes_phase1.py`). They are not recorded yet, so the manifest is unchanged and every symbol stays `pending-evidence` until its request is admitted and replayed (decision 112 §1).

   | Request | Steps | Symbols it exercises |
   |---|---|---|
   | `phase1-blending-modes-layer` | 82 | All 32 documented `BlendingMode` members, each set then read back on a fill's BaseColor. The NormalMap modes and Normal are also set on its Normal channel, and PassThrough and Normal on a group. Settles the 27 pending members: Color, ColorBurn, ColorDodge, Darken, Difference, Disable, Divide, Exclusion, HardLight, InverseDivide, InverseSubtract, Lighten, LinearBurn, LinearLight, NormalMapCombine, NormalMapInverseDetail, Overlay, PassThrough, PinLight, Replace, Saturation, SignedAddition, SoftLight, Subtract, Tint, Value, VividLight. |
   | `phase1-blending-modes-mask` | 72 | The same 32 members on a mask fill effect, with no channel (the mask-stack context). |
   | `phase1-layer-navigation` | 106 | `Node.get_parent`, `get_next_sibling`, `get_previous_sibling`, `get_texture_set`; `EffectNode`; `LayerNode.instances`; `GroupLayerNode.is_collapsed`, `set_collapsed`; `FillLayerNode.is_symmetry_enabled`, `get_material_source`; `FillEffectNode.is_symmetry_enabled`, `set_symmetry_enabled`, `get_material_source`, `reset_source`; `ProjectionMode.Fill`; `FilteringMode.BilinearSharp` (with BilinearHQ and Nearest); `get_selected_nodes`, `set_selected_nodes`, `get_selection_type`, `set_selection_type`; `SelectionType` and its four members; `ScopedModification`. |
   | `phase1-layer-node-kinds` | 24 | `NodeType.PaintEffect`, `FilterEffect`, `GeneratorEffect`, `InstanceLayer`; `InstanceLayerNode.instance_source`; `LayerNode.instances` after `instantiate`; `EffectNode`; `SelectionType.Properties` on an instance and on a fill. See §3 (c). |
   | `phase1-levels-params` | 28 | The `substance_painter.levels` module; `LevelsParamsRGB` and `LevelsParamsMono` with all six fields (`input_min`, `input_max`, `gamma`, `output_min`, `output_max`, `clamp`), on RGB and mono channels, on mismatched channels and in a mask; `LevelsEffectNode.get_parameters`. |
   | `phase1-color-srgb-value` | 31 | `Color.sRGB` (getter and setter) and `Color.value`, on BaseColor and Height source colours and on colours built with no colour space and with GenericColorSpace sRGB, Working and Raw. |

   The 76 symbols settled by these requests: the 59 of `layerstack`, the 15 of `levels` and the 2 of `colormanagement`.
3. **Amendments to decision 112.**
   - (a) **`properties` (10 symbols: the module, `Property` and its eight members) has another evidence route.** No P22-B request exercises it. These symbols are settled by the compared replay of the recorded `tier0/defaults-templates/baking-defaults`, once `BakingParameters` is implemented (phase3.5_embree-bakers), or by a procedural golden's replay through `SourceSubstance.get_properties` (phase3.3_procedural-families), whichever comes first. A Property request now would duplicate that recording, and its replay would be refused anyway.
   - (b) **`layerstack.EffectNode` is a documented alias.** It is settled by the exact compared readbacks `s47` to `s53/EffectNode` of `phase1-layer-navigation`, the `isinstance` checks on every node kind. The trace cannot attribute an `isinstance` check, so when that golden is admitted, its manifest entry cites the golden by hand. The conformance check then takes this one entry from the compared output instead of the trace (decision 112 §1 and §2 apply to every other symbol).
   - (c) **Pending symbols reachable only through release gaps** are `NodeType.PaintEffect`, `FilterEffect`, `GeneratorEffect` and `InstanceLayer`, and `InstanceLayerNode.instance_source`. `phase1-layer-node-kinds` records Painter's behaviour for them. UzPainter's replay refuses the calls that create their nodes, so the replay does not settle them. They stay `pending-evidence` until the release gaps of `insert_paint`, `instantiate`, `insert_filter_effect` and `insert_generator_effect` close and that golden's replay passes. Release G5 treats them as open, as decision 112 §3 already says.

## Alternatives Considered

- **A Property probe through `BakingParameters.common()`.** Rejected. It repeats the recorded baking defaults, and the UzPainter replay refuses it.
- **Routing the node kinds of §3 (c) to their release gaps with no request.** Rejected. The calls are safe and deterministic in Painter. Decision 188 already recorded `insert_paint` in P21-E the same way, and the recording is the oracle those gaps will need.
- **Extending the trace to count `isinstance` checks.** Rejected for this task. An `isinstance` check is a builtin call on an argument, and counting it would also count the recorder's own type tests.

## Consequences

- The next Painter batch records the six requests in a Legacy session: `python -m tools.parity.recorder.probes record "$req/tier0/api-probes/<stem>.json"` (RECORDER.md §11.4).
- On admission: delete the request, then add the replay to the traced Tier 0 tests. Update the manifest entries that the conformance test names, with §3 (b) for `EffectNode`. The node kinds of §3 (c) stay pending.
- The fake's rules are not Painter's (for example, its lack of `BlendingMode.PassThrough`). Only the recording gives Painter's behaviour.
