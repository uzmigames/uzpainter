# 202. The facade reads Painter's measured OCIO decode of an sRGB uniform colour and opens OCIO projects with Painter's substance config

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand

## Context

Item 2.6 of `phase1.15_compositor-colour-fits` (decision 190) asks the Python facade to work under OCIO with Painter's substance config (SHA-256 `15059d4b…`, decision 134). Two things were missing:
- Painter's working value of a uniform colour set in sRGB;
- the eleven-space bitmap listing.

Then the facade's OCIO refusal (`colour.require_supported_configuration`) could be lifted where exact.

Decision 198 admitted P20-B's OCIO twin, `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part1..4`. It sets 320 colours in sRGB on BaseColor and reads each back through `get_source(...).get_color().working`: the greys c/255 for c = 0..255, then 64 random colours. r1 = r2 on every readback.

Measured (counts and numbers only):

1. **The data.** There are 448 distinct float32 input components, and each has exactly one working value.
   - The facade's Legacy float32 rule (decision 107) matches 10 of the 448.
   - Painter's value differs from the exact IEC 61966-2-1 decode by a pseudo-random error of about ±5·10⁻⁷ (standard deviation 2.4·10⁻⁷). The error is uniform over [0, 1] and is also present on the linear segment, where it reaches 3.4·10⁻⁴ relative (c = 1: 3.0342268e-4 against 3.0352699e-4).
   - Neighbouring inputs (Δ ≤ 2·10⁻⁴) have close errors, so the error is a function of the input, not noise.
   - On the linear segment, the readback of the integer codes c = 2-8 and 10 is exactly c · 3.0313077·10⁻⁴ plus an integer multiple of 10⁻⁶. c = 1 and c = 9 do not follow it.
2. **Rejected models**, each missing most of the points:
   - the exact and float32 sRGB decodes;
   - OpenColorIO 2.4.2's `ExponentWithLinearTransform`, exact and fast-power (decision 190);
   - regular 1D LUTs with linear interpolation: 2 to 70 000 nodes, the domains [0, 1], [-0.125, 1.125], [0, 1.25], [0, 1.5], [0, 2] and [0, 4], and node values exact, float32, binary16 or rounded to 10⁻⁴…10⁻⁸;
   - half-domain LUTs with exact, binary16 or float32 nodes;
   - a binary16-quantised input.

   The exactness hunt stopped at its two-hour cap.
3. **Separability.** `export-ocio-encode` was recorded in another project and session (decision 180). Its readbacks of (0.2, 0.5, 0.8) and (75, 70, 65)/255 in sRGB have five components equal to grey codes: 51/255, 204/255, 75/255, 70/255 and 65/255. All five equal the grey readbacks bit for bit. The decode is per component and does not depend on the session.
4. **The listing.** On BaseColor, `list_available_color_spaces` returns `GenericColorSpace` Raw, Working and sRGB, then the strings `Linear`, `sRGB`, `Rec709`, `Rec2020`, `ACES - ACEScg`, `Display P3`, `ACES sRGB` and `False Color` (s43-s45). A mask's mono source lists Raw, Data and DataSigned (s27).
   - Under Legacy, Linear and sRGB are `LegacyColorSpace` members (decision 107).
   - A colour image on BaseColor defaults to sRGB, and a mask source to Data.
5. **The Legacy fit, for comparison.** Decision 107's float32 rule matches 6 of the 7 Legacy components recorded so far. Their OCIO values differ from the Legacy ones, for example 70/255: 0.0612461679 against 0.0612460561. So item 2.1 still needs the Legacy twins `phase1-srgb-uniform-decode-part1..4`.
6. **The Wand.** Its pipeline (`painter_layer_stack.py`) sets every BaseColor as integer 0-255 RGB divided by 255, which lies inside the measured domain.
   - Its masks are 16-bit grey bitmaps at 1:1, and T_base is an 8-bit colour bitmap at 1:1. Decision 190 admits both under OCIO.
   - `project.create` makes a Legacy project (decision 134: it takes no colour-management settings). Painter takes OCIO from its environment at start-up.

Model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-13, one round):
- C1, admit a measured per-component table and refuse every other component: AGREE x2, PARTLY x1. GPT: key it on the float32 bits and check every component before any change.
- C2, lift the refusal only for Painter's config hash and the recorded domain: AGREE x2, PARTLY x1. GPT: the listings are metadata, not a claim about bitmap transforms.
- C3, the 193 non-c/255 recorded points belong in the table: AGREE x3.
- C4, OCIO project creation and the Wand's UV padding are separate items: AGREE x2, PARTLY x1. Kimi: state that the table cannot reach the Wand until an OCIO project can be created.

## Decision

1. **The profile.** `colour.require_supported_configuration` admits OCIO when the project's `config_hash` is Painter's substance config (`PAINTER_OCIO_CONFIG_SHA256`, the evaluator's `kPainterOcioConfigSha256`). It still refuses any other mode or hash before anything is evaluated. `project.open` and `export.export_project_textures` accept such a project. `colour.active_profile()` gives the open project's profile, and Legacy when no project is open.
2. **The sRGB decode under OCIO** is Painter's measured value, by float32 bits of each component (`python/uzpainter_facade/ocio_srgb.py`):
   - `CODES`, for the 256 components float32(c/255);
   - `RECORDED`, for the 193 other recorded components: 0.5 and part 4's 192 random components.

   Every component is checked before any change. An unrecorded component raises `NotYetSupported`, naming the readback that would settle it. This is the decision-190 pattern: the 8-bit authoring domain is covered by measurement because no formula was found.
3. **What else is admitted under OCIO.**
   - Raw and Working, and a colour without a space on a channel that does not decode, are taken as given. The recorded cases are Raw on BaseColor, and Raw and no space on SpecularRoughness, BaseMetalness and Height. Working is the identity by definition.
   - The BaseColor listing of fact 4 (`OCIO_COLOUR_SPACES` after the generic three), the mask listing, and the defaults sRGB (a colour image on BaseColor) and Data (a mask source).
4. **What stays refused under OCIO**, with `NotYetSupported` before any change (release gap `compositor:ocio-unrecorded`):
   - an sRGB uniform colour on a channel that does not decode it;
   - another colour space for a uniform colour;
   - the encode of a working value (`Color.sRGB`, `value` and `convert` to anything but Raw or Working);
   - the listings and defaults of every channel but BaseColor;
   - a fill's reset default source (`DEFAULT_SOURCES` are Legacy recordings);
   - any component outside the table.

   Bitmap evaluation stays as decision 190 admits it.
5. **Evidence.** These tests replay the goldens with the recorder's own Painter-side code through the facade in a project that declares Painter's OCIO configuration. Every readback equals Painter's on both recordings.
   - `test_facade_ocio_uniform_decode_equals_painter[part1..4]`: 160 readbacks per recording and part, events aside.
   - `test_colour_rule_readbacks_equal_painter[export-ocio-encode]`: every readback and colour-space capture, with no exclusion.

   These replays compare readbacks only, because the native project stays Legacy there (fact 6). The OCIO evaluation and export are decision 190's `test_ocio_encode_equals_painter_files`. `test_pyapi_facade.py` checks the refusals of item 4.
   - The five replays join the Tier 0 trace (`tools/capabilities/tier0-trace.json`), and the `tier_evidence` of every symbol they exercise cites them (decision 112). Two `pending-evidence` additions become `supported` this way, by the trace rule that setup counts:
     - `uzpainter.layerstack.FillLayerNode.reset_source`, from the OCIO reset of a fill's channels;
     - `uzpainter.project.revert`, from the close of the reopened, modified project. No compared output follows that close, so the owner may prefer to keep it pending at gate G5.
6. **The Wand pilot (phase1.25) stays blocked**, on two items outside this colour fit:
   - **No creation path yields an OCIO project.** The table is reachable only by opening a project that declares OCIO. The Wand's `painter_create.py` therefore builds a Legacy project. The open choice is how UzPainter learns the configuration that Painter takes from its `OCIO` environment variable. One option is a hash of the named file, checked against `kPainterOcioConfigSha256`; another is an explicit UzPainter setting. That choice belongs to a decision with the owner of project creation (phase1.24/phase1.25), not to item 2.6.
   - **Infinite padding on UV islands** (phase1.25 item 2.7) stays refused at export, so even an OCIO Wand project would end in `candidate_export_refused`.

## Alternatives Considered

- **An analytic decode.** Not found within the cap (fact 2). The linear-segment structure (fact 1) rules out every regular-grid LUT tried.
- **Only the 256 codes c/255.** Rejected (panel C3). The 193 other points are Painter observations with r1 = r2, and they make `export-ocio-encode` s0/s1 and P20-B part 4 replay exactly.
- **Keeping the facade's Legacy rule under OCIO.** Rejected: it differs on 438 of 448 components.

## Consequences

### Positive
- An OCIO project with Painter's substance config opens through the facade, and its sRGB uniform colours in the 8-bit domain read back Painter's working value bit for bit. Every colour the Wand's pipeline authors falls in that domain.

### Negative
- The decode is a measured table: an sRGB component outside the 449 recorded inputs is refused under OCIO.
- The Wand pilot still needs an OCIO creation path and the UV padding fit.
