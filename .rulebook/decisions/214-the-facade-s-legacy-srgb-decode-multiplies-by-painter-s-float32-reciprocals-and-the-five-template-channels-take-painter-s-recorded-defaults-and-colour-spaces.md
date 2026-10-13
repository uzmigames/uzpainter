# 214. The facade's Legacy sRGB decode multiplies by Painter's float32 reciprocals, and the five template channels take Painter's recorded defaults and colour spaces

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.24_python-api-facade

## Context

Item 2.1 of `phase1.15_compositor-colour-fits` (decisions 107, 108 §4, 117 and 130) fits the facade's colour tables to the recordings decision 107 named:

- **P20-A**, `tier0/api-probes/phase1-fill-channel-defaults` (admitted by decision 198);
- **P20-B in Legacy**, `phase1-srgb-uniform-decode-part1..4` (admitted by decision 205).

It also closes the residuals decision 117 assigned to it:

- the 70/255 exclusion of `export-ocio-encode-legacy`;
- `phase1-reload-resources` recording 1, s9 and s12.

Decision 202 fitted P20-B's OCIO twin with a measured table because no formula reproduced it. The brief for this item was to do the same in Legacy if the decode there is not a formula either.

Measured (counts and numbers only):

1. **P20-B Legacy.** There are 448 distinct float32 input components: the 256 greys c/255 and 192 random components. Each has one working value across both recordings, both conditions, and the `set_source` and `get_source` readbacks.
   - Decision 107's rule, `((x + 0.055f) / 1.055f) ^ 2.4f` with `x / 12.92f` on the linear segment, matches 386 of the 448. Each miss is 1 to 5 float32 ulp high.
   - On every miss, a power base one float32 ulp below the rule's base gives Painter's value. The rule's base is `f32(f32(x + 0.055f) / 1.055f)`.
   - Multiplying by the float32 quotient `1.0f / 1.055f` (0.94786733…, one ulp above the correctly rounded 1/1.055) gives the base on all 429 components of the curved segment. On the linear segment, `x * (1.0f / 12.92f)` gives all 19 components; division misses one of them.
   - Rejected along the way (best counts out of 448): the recording GPU's `exp2(2.4 log2 b)` from the `hw-lg2`/`hw-ex2` tables (at most 99 of the 429 curved components); log/exp in float32 (211); the double-precision decode (130); affine and fused-multiply-add bases (184 or fewer).
   - The Legacy and OCIO decodes agree on 10 of the 448 components (decision 202 fact 5). They are different decodes.
2. **P20-A** (both recordings; the readbacks equal in both, resource contexts aside):
   - **Default sources** after the active-channel assignment, in the working space: BaseColor 0.8, BaseMetalness 0, Height 0, Normal (0.5, 0.5, 1) and SpecularRoughness float32(0.3).
   - **Default bitmap spaces.** BaseColor takes sRGB for the 8-bit colour checker and the 8-bit grey bitmap alike. BaseMetalness and SpecularRoughness take Data, Height DataSigned and Normal NormalXYZLeft. A mask's mono source takes Data for both images.
   - **Listings.** BaseColor lists `[Raw, Working, sRGB, Linear, sRGB]`. BaseMetalness, SpecularRoughness, Height and a mask list `[Raw, Data, DataSigned]`. Normal lists `[Raw, NormalXYZRight, NormalXYZLeft]`. The template's formats are sRGB8, L8, L16F, RGB16F and L8.
   - **The five exported maps** do not equal the facade's. The stack binds the colour checker on the L8, L16F and RGB16F channels and as a mask source, and the grey bitmap on Normal.
     - On L8, the evaluator's values follow the checker's red component: 41 and 23 of 255 where the cell colours give R(1 − R).
     - Painter's values are the codes 59 and 63. The component mean of each colour, as value and as mask, gives 59.3 and 63.5. That is suggestive but not a fitted rule.
     - The evaluator refuses a grey bitmap on Normal (`evaluator:unsupported_source`).

No model panel was consulted. The decode is an exact formula on every recorded component, the defaults and listings are read directly, and the export split follows the time box of the speed rules.

## Decision

1. **The Legacy sRGB decode** (`colour.srgb_to_linear`) is computed in float32 with x = f32(v):
   - x ≤ 0.04045f: `x * (1.0f / 12.92f)`;
   - otherwise: `f32(f32(x + 0.055f) * (1.0f / 1.055f)) ^ 2.4f`.

   Each reciprocal is the float32 quotient of 1 by the float32 constant. The power of the float32 operands is rounded once to float32.
   - This is a formula, not a table. It equals Painter on all 448 P20-B components, both recordings, so no Legacy data file exists beside `ocio_srgb.py`, and no native Legacy table is needed. The native evaluator receives the stored working value.
   - The export tests' mirror of the facade's decode (`tests/export/encoders_tier0.py` `srgb_to_working`) uses the same formula.
   - The 0.04045 threshold is the documented one. P20-B has no component between 0.0368 and 0.0431, so a threshold inside that interval is not distinguished by the data.
   - The encode (`linear_to_srgb`) is unrecorded and stays as it was.
2. **`DEFAULT_SOURCES`** holds P20-A's five defaults. Any other channel's default is still unrecorded: reading it, or exporting a fill that has it active, raises `NotYetSupported` naming a P20-A-like probe on a template with that channel.
   - The native insert's own default sources (`stack_sync.cpp` `ApplyDefaultSources`, BaseColor and Height, decision 115) are not changed. P20-A records the defaults after an active-channel assignment, which goes through the facade. It does not record a fresh fill's inactive channels.
3. **Bitmap spaces.**
   - `default_bitmap_space` gives a grey bitmap on BaseColor sRGB in Legacy. Under OCIO that case is unrecorded and raises `NotYetSupported` before any change.
   - `available_bitmap_spaces` lists the data spaces for BaseMetalness, SpecularRoughness and Height, and the normal spaces for Normal, when the channel is not sRGB8.
   - Every other unrecorded channel still raises.
4. **Tests.**
   - `test_facade_legacy_uniform_decode_equals_painter[part1..4]` compares every readback and the BaseColor map exactly, both recordings. Each part has 165 and 163 outputs (160 colour readbacks), events aside.
   - `test_facade_fill_channel_defaults_equal_painter` compares P20-A's 73 + 49 readbacks and the five inserted nodes' effective defaults exactly, events aside. The five exported maps (10 files) are excluded and named to item 2.9.
   - The `readback/get_source/29/BaseColor` exclusion of `export-ocio-encode-legacy` is removed: every readback is exact.
   - `phase1-reload-resources` recording 1, s9 and s12, are compared again (`test_pyapi_lifecycle_tier0.py`). Recording 2 stays with phase5.2_parity-report-tiers item 2.10 (decision 117 §2).
   - The five new replays join the Tier 0 trace, and the `tier_evidence` of every symbol they exercise cites them (decision 112).
   - Four pending-evidence symbols become `supported` with P20-A as their evidence: `NormalColorSpace` and its two members (`get_color_space` and the Normal listing return them), and `uzpainter.layerstack.InsertPosition.above_node`.
   - `facade/mask-stack` and `facade/phase1-resource-update` are re-recorded too. Since decision 207 binds a bitmap in its default space in one native call, they no longer exercise `uzpainter.source.SourceBitmap.set_color_space`. That trace drift reached main with 86052ed.
   - `facade-events/phase1-reload-resources` is re-recorded: s6's grey bitmap now binds, so the replay exercises `set_source` and the bitmap's colour-space symbols. `uzpainter.NotYetSupported` and `uzpainter.exception.NotYetSupported` had that refusal as their only Tier 0 evidence. They return to `pending-evidence`, owned by gate G5 like the other UzPainter-only errors.
   - **An excluded exported map's export call is no longer evidence.** Before, `compare` dropped only the map's output id, so the symbols of its export call still counted. P20-A's refused Normal export would otherwise have made `ExportStatus.Error` `supported`.
     - `facade/mask-stack` and `facade/phase1-srgb-uniform-decode-ocio-part1..4` therefore lose the export symbols of their excluded BaseColor maps.
     - Every one of those symbols keeps other Tier 0 evidence. No `supported` entry is left without evidence.
5. **Scope split** (the decision-069 pattern): P20-A's exported maps go to the new **phase1.15 item 2.9**. Its scope is Painter's rule for a colour bitmap on a mono channel (L8, L16F) and as a mask source, for a colour bitmap on Normal and Height (RGB16F, DataSigned), and for a grey bitmap on Normal.
   - P20-A already records all of these at PNG 16. It needs no Painter recording, only a fit in the evaluator (CPU and GPU) and its support check.
   - **Finding for that item:** today the evaluator does not refuse a colour bitmap on an L8 channel or as a mask source. It evaluates the red component, which is not Painter's value. Item 2.9 either fits the rule or adds the refusal.

## Alternatives Considered

- **A measured Legacy table, as under OCIO.** Rejected: an exact formula exists, and a table would refuse every component outside the 448.
- **Keeping decision 107's division and listing the 62 misses.** Rejected: the one-ulp base offset fully explains them.
- **Changing the native insert defaults to all five channels.** Rejected for this item: it would claim a fresh fill's inactive-channel defaults, which P20-A does not record.
- **Holding item 2.1 open on the P20-A maps.** Rejected by the speed rules. The maps are evaluator fits with recordings in hand, and the facade's claims in item 2.1 (decode, defaults, spaces) are exact.

## Consequences

- Every Legacy sRGB uniform colour reads back Painter's working value bit for bit: all 448 recorded components, and decision 107's residual.
- A fill's active-channel reset gives Painter's defaults on all five default-template channels. Exporting such a fill no longer raises for BaseMetalness, Normal and SpecularRoughness.
- A grey bitmap on BaseColor binds in sRGB. `phase1-reload-resources` s6 is no longer refused.
- Item 2.9 owns P20-A's maps, and the evaluator's unrefused colour-on-mono path.
