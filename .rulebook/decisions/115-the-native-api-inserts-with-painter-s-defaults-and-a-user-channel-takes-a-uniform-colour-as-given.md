# 115. The native API inserts with Painter's defaults, and a user channel takes a uniform colour as given

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.24_python-api-facade, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.22_pyapi-cli-capabilities, phase1.23_pyapi-pipeline-adapter, phase1.14_compositor-core, phase2.6_mcp-typed-tool-families, phase2.8_mcp-server

## Context

Task phase1.24 is the parent of P1-PYAPI. Its children handed it two questions: whether the native API should adopt Painter's insert defaults, and what evidence the 63 UzPainter-only `pending-evidence` symbols can get (decision 112). Integration found a third: how an sRGB uniform colour is stored.

Measured facts:

- **Insert defaults.**
  - Painter, in the Tier 0 api-probes: a new fill, fill effect or group in a content stack blends Height `LinearDodge`, Normal `NormalMapDetail`, and every other channel `Normal` at opacity 1.
  - A new fill holds BaseColor 0.8 and Height 0 in the working space, with no active channel. A content-stack levels effect is named "Levels - Base color" and affects BaseColor. A compare mask is "Compare mask".
  - Until now the native inserts gave `Normal` everywhere, no default source, and the names "Levels" and "Compare Mask". The facade re-applied Painter's values afterwards (decision 107 §5).
- **The native composite diverged from the script it mirrors.**
  - `layerstack.sync_stack` (LAY-07) built its fills and groups with `Normal` Height blending.
  - `painter_layer_stack.py sync`, in Painter or through the facade, gives `LinearDodge`: the script's inserted nodes get Painter's defaults.
  - The wand's stack has height layers (the iron dimples, -0.003), so the two Height maps differed.
- **Uniform colours.**
  - The native evaluator composites a stored uniform value as linear and ignores its colour-space tag.
  - The Tier 0 goldens `colour-ramps-srgb`, `-working` and `-raw` set 288 values, k/255 and (k + 0.5)/255, on RGB16 and sRGB8 user channels, as `Color(v, sRGB)`, `Working` and `Raw`. The evaluator, fed the raw values with the tag ignored, equals every texel of all three (0 of 18 874 368 values differ per golden). So Painter's Legacy mode composites `Color(v, sRGB)` as v.
  - Painter's readback `get_color().working` of `Color(0.8, …, sRGB)` is the decoded 0.6038274 (`fill-layer-readback`).
  - The facade decoded every sRGB-tagged colour before storing it (decision 107 §2), on every channel. No Tier 0 comparison had exported such a colour through the facade.
  - The native `sync_stack` stored the stack's `base` colours as given, tagged sRGB. The script through the facade stores them decoded: a second BaseColor divergence.
  - **Measured after the panel's second round:** the facade replay of the three ramp goldens (§3) shows that Painter's readback of `Color(v, sRGB)` on a user channel is v, not its decode, on RGB16 and sRGB8 user channels alike (384 readbacks of `colour-ramps-srgb` differed from the facade's decoded values). Painter therefore does not colour-manage a uniform colour on a user channel: it reads back and exports the value set. On BaseColor the decode is recorded (`fill-layer-readback`, `export-ocio-encode-legacy`). No golden compares an export of an sRGB colour on BaseColor (the 16-bit BaseColor export is R-090, and the `export-ocio-encode-legacy` maps are phase1.14's fit).
- **UzPainter-only symbols.** 63 entries have no Painter counterpart. A compared replay counts a symbol only when the compared outputs depend on it (decision 112).
  - Some can carry the outputs of a replay: `Transaction`, its result's `created` ids, name addressing, `Stack.uid`, `export.plan`, `export.start` and `Job.wait`.
  - The rest change no compared output: the error classes, `capabilities.*`, the dispatcher-thread helpers, `project.revert`, `Job.cancel` and `Job.progress`, the `render` and `diagnostics` modules, `UVTile.u/v` on single-tile projects.

The model panel, two rounds (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| A1 native inserts adopt Painter's recorded defaults | PARTLY: amend 107 §5; scope by node kind and stack; keep unrecorded sources absent | AGREE: "Levels - Base color" only for the recorded case | PARTLY: amend 107 §5 |
| A2 LAY-01 untouched; the reset quirk stays in the facade | AGREE | AGREE | AGREE |
| A3 the facade stops re-applying, in the same change | PARTLY: re-run the traced Tier 0 replays | AGREE: same commit | PARTLY: one change with the native test |
| A4 `sync_stack` builds the script's document | PARTLY: compare across height, groups, masks | AGREE | AGREE |
| C1 native replays through the UzPainter-only operations | PARTLY: promote only symbols the outputs depend on | PARTLY: build the symbol × probe matrix first | PARTLY: no `to_dict`, `status` or bare `last_result` |
| C2 the rest stay `pending-evidence`, a G5 question | PARTLY: classify each one | AGREE | AGREE |
| D1 the facade stores a colour as given and converts on read | PARTLY: user-channel evidence does not prove BaseColor | AGREE | AGREE |
| D2 amend decision 107 §2 here | PARTLY: confirm the 70/255 residual by replay | AGREE | AGREE |
| D3 verify with the full ramps through the facade | PARTLY: all 288 values, all three spaces | PARTLY: untagged has no golden | PARTLY: full ramps |

D1 was adopted on the premise that Painter composites every tagged colour as given. The full-ramp replay that D3 asked for refuted it for the readback, and it confirmed GPT's reservation: the user channels are not colour managed, while BaseColor is. The measurement decides §3, not the vote.

Rejected alternatives: keeping Normal-everywhere native defaults with the MCP re-applying them (all three), leaving the colour question to phase1.14 (all three), and amending decision 112 so that contract tests count as evidence (all three).

## Decision

1. **The native inserts give Painter's effective defaults** (amends decision 107 §5). The rules live in `src/python/stack_sync.{h,cpp}` (`ApplyDefaultBlending`, `ApplyDefaultSources`) and in `bind_layerstack.cpp` (`InsertDefaults`).
   - A new fill, fill effect or group in a content stack blends Height `LinearDodge` and Normal `NormalMapDetail` where the stack has the channel. Other channels keep `Normal` at opacity 1.
   - A new content fill holds BaseColor 0.8 and Height 0 as working-space uniform sources, with no active channel. A channel whose default is unrecorded gets no source (recording P20-A).
   - Where the stack has BaseColor, a content-stack levels effect affects BaseColor with RGB parameters, and is named "Levels - Base color" unless the call names it. A compare mask is named "Compare mask".
   - A node in a mask stack keeps the plain defaults.
   - LAY-01 is unchanged: assigning `active_channels` changes no source. Painter's reset on assignment stays a facade quirk.
   - The facade no longer re-applies any of this. It keeps `DEFAULT_SOURCES` for the reset quirk only.
2. **`sync_stack` builds the document `painter_layer_stack.py sync` builds.**
   - Every node it creates starts with the insert defaults of §1: the root group, the groups, and the fills. A group with `replace_height` blends Height `Normal`.
   - A fill's active channels are exactly the ones its layer names. The default Height source of a fill without a height stays, inactive.
   - A mask's bitmap is in the Data space, Painter's default for a bitmap bound in a mask.
   - `tests/adapters/assets3d` runs the native `sync_stack` on the wand's stack after the script's `sync`. It compares the two documents: tree, blending and opacity of every node on every channel, active channels, every source, projections and masks. They must be equal.
3. **A user channel takes a uniform colour as given** (amends decision 107 §2).
   - On a colour-managed channel the facade still stores the float32 working value, decoding an sRGB (or untagged) colour, as decision 107 records. Colour-managed now means an sRGB8 channel that is not a user channel (`nodes.decodes_colour`).
   - On any other channel, user channels included, the facade stores the value as given, whatever its space. Its readback `.working` is that value and its export composites it.
   - Proof: `test_pyapi_facade_tier0.py` replays the three colour-ramp goldens through the facade with the recorder's own code. It compares all 192 exported maps and all 216 readbacks of each recording, both recordings, exactly.
   - The BaseColor composite of an sRGB colour stays decision 107's rule, readback-proven only. Its export comparison belongs to the R-090 fit (phase1.25_pilot-wand item 2.6) and the `export-ocio-encode-legacy` fit (phase1.14_compositor-core, decision 108).
   - The native `sync_stack` stores the stack's colours as the facade stores the script's: `base` as its float32 working value on an sRGB8 BaseColor, the other values as given.
   - The native API itself keeps storing a colour as given (decision 105 §2).
4. **UzPainter-only evidence.**
   - The native `fill-layer-readback` replay reaches Painter's outputs through UzPainter's own operations. Its state steps are one `Transaction`; the result's `created` ids address the identity and name readbacks. The other readbacks find their nodes by name (`get_node_by_name`, `find_nodes_by_name`), and the stack is found again by `Stack.uid` after reopening.
   - Its Height map is exported through `export.plan`, `export.start` and `Job.wait`, then compared with Painter's on every texel.
   - The trace (decision 112) marks what these replays exercise. Those entries become `supported`.
   - Every other UzPainter-only symbol stays `pending-evidence`. Its note says why no Painter-compared replay can exercise it. Whether release G5 accepts such a symbol on its contract tests is a question for G5, not phase1.24 (a recorded scope split).

## Consequences

- Same inserts, same document: through MCP (phase2.6, phase2.8), the native API and a Painter script.
- When P20-A is recorded, the defaults of the other channels are added to `ApplyDefaultSources` and to the facade's reset table together.
- phase1.14's colour fits (decision 108) start from this rule: decode on BaseColor, as given on user channels.
