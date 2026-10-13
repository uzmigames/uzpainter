# 240. Every path stores a uniform colour through one native decode, and OCIO bitmaps the evaluator refuses are refused before mutation

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.6_mcp-typed-tool-families, phase1.15_compositor-colour-fits, phase1.24_python-api-facade

## Context

The practical end-to-end run (`parity/reports/phase2/practical-e2e.md`) found two bugs in how a colour reaches the document.

**B1 (High).** The same instruction gave different textures through MCP and through the facade.
- MCP `source_set {kind: uniform_color, color: [0.5, 0.35, 0.2], color_space: "sRGB"}` stored the values as given with the tag `sRGB`. The evaluator takes every stored uniform value as linear whatever its tag (`src/evaluator/sources.h`). The BaseColor therefore exported double-encoded: (48360, 41122, 31840) instead of (32893, 22895, 13128).
- The facade's `set_source(ch, Color(0.5, 0.35, 0.2))` decodes sRGB to the working space before storing it. So does the native `sync_stack`.
- Under OCIO, MCP accepted components that the facade refuses. 0.35 is not in Painter's measured table (decision 202).
- Decision 105 §2 made the native setters "raw": a colour is kept as given. Decision 212 §2 extended that to MCP `source_set` and named `sync_stack` the only native decode.
- There were three decodes:
  - the facade's Python formula and dict;
  - `sync_stack`'s C++ copy;
  - none in `set_source`, `set_color` and `source_set`.
- `sync_stack`'s copy had drifted. It still divided by 1.055f (decision 107's rule), which misses Painter on 62 of P20-B's 448 components. Decision 214 replaced that rule in the facade only. 40 of the 256 codes c / 255 differ, among them 70, 98 and 133.

**B5 (Low).** Under OCIO, `source_set` of a bitmap the evaluator refuses committed with no warning. Examples are an 8-bit colour bitmap that is not the set's size, and an 8-bit grey mask source. Every later export, capture and diagnostic then failed.
- The pre-mutation support check (`evaluator/support.h`) is a document check. It refused the colour space and channel part of the OCIO rule (decision 190).
- The image's kind and its 1:1 sampling were checked only at evaluation (`evaluate.cpp` `CheckOcioBitmap`).
- Both need only the PNG header.

### Model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5; 2026-10-13, one round)

The dossier is in the session scratchpad. The claims and votes:

- **C1. Decode at the setter, not in the evaluator by tag.** Store (working, `Working`), identical records for the facade and MCP, refusals before mutation, evaluator untouched.
  - AGREE ×3.
  - GPT: an evaluator decode by tag would also reinterpret the sRGB-tagged records saved earlier.
- **C2. A colour without a space over MCP and the native API follows Painter's rule:** sRGB on a decoding channel, Raw elsewhere. MCP's capability is Painter's `set_source`. The break is documented.
  - AGREE ×3.
- **C3. The facade keeps its profile view and calls the one C++ decode through a private native helper.** This keeps the Session O replays working. They run on a Legacy native project whose `get_color_management` reports OCIO.
  - AGREE ×1 (Grok), PARTLY ×2.
  - GPT: two authorities still pick the channel and the profile; test real Legacy and OCIO projects through every path.
  - Kimi: move the channel predicate into C++ too.
- **C4. No migration of documents saved earlier.**
  - AGREE ×3.
  - Kimi would also warn on open.
- **C5. Option (a) for B5:**
  - an image-aware support check over a header reader, for committed and staged bytes;
  - one predicate shared with the evaluation;
  - a `set_resolution` that breaks 1:1 refused too;
  - Legacy image checks stay at evaluation.
  - AGREE ×2 (GPT, Grok), PARTLY ×1. Kimi: Painter allows the resize, so keep it at evaluation.

## Decision

1. **One decode, in native code.**
   - `python::WorkingColour(rgb, space, decodes, ocio)` (`src/python/edits.h`) is the rule:
     - no space is sRGB on a decoding channel and Raw elsewhere;
     - a channel that does not decode takes the value as given, once the space is checked;
     - sRGB decodes by `evaluator::PainterLegacySrgbDecode` (decision 214's formula) or reads `evaluator::PainterOcioSrgbDecode` (the table generated from `ocio_srgb.py`, decision 212);
     - Working, Linear (Legacy only) and Raw are taken as given.
   - Its refusals are the facade's, word for word, each before any change:
     - under OCIO, an unrecorded component, an sRGB colour on a channel that does not decode it, and any other space raise `NotYetSupported`;
     - in Legacy, any other space raises `ValueError`;
     - an unpinned configuration raises `NotYetSupported` (`OcioColourProfile`).
   - `DecodesColour` decides which channels decode: an sRGB8 channel that is not a user channel (decision 115).
2. **Every native path uses it.** `FillLayerNode.set_source(Color)`, `SourceUniformColor.set_color`, MCP `source_set` and `sync_stack`'s `base` store `StoredUniformColour`: Painter's working value, tagged `Working`. This is the record the facade stores.
   - This amends decision 105 §2 for uniform colours. The native API no longer keeps a colour's raw value and tag.
   - It also replaces decision 212 §2's "native setters and the MCP `source_set` store colours as given".
   - `sync_stack`'s own decode is deleted. It now equals Painter on the 62 components it missed.
   - MCP `color_space` empty or omitted means no space. The schema describes the rule.
3. **The facade calls the same function.** It uses `uzpainter.colormanagement._working_value`, private, so it is neither public API nor capability evidence.
   - It passes its own profile view and channel predicate. The Session O replays need them: their native project is Legacy.
   - Its Python formula and its dict of the table are deleted.
   - The channel predicate stays in Python, as C3's two PARTLY votes noted. Moving it native would change the native symbols every Tier 0 replay exercises, and so the committed trace (decision 112).
   - Instead, `test_every_path_stores_a_uniform_colour_as_painter` runs real Legacy and OCIO projects through the facade and the native setter, on every channel kind. It requires the same stored value or the same refusal.
4. **No migration.** A document saved earlier with an sRGB-tagged uniform colour, stored as given, keeps evaluating as stored. The tag never changed the evaluation, and rewriting stored values would silently change outputs. Re-setting the colour stores Painter's value.
5. **B5: option (a).**
   - `evaluator::OcioBitmapRecorded` holds the image's kind and 1:1 sampling (`sources.h`). The evaluation's `CheckOcioBitmap` and the support check both call it.
   - `BitmapShapeOf` reads the shape from the PNG header, as `DecodeBitmap` would give it.
   - The session passes the support check a reader over the store's bytes, committed or staged for the running transaction (`ProjectStore::ReadResource`). Shapes are cached by content hash.
   - `RequireSupported` refuses an OCIO bitmap the evaluation would refuse:
     - in every node a request creates or modifies (bind, projection change, rebind);
     - in every node of a texture set whose resolution or channels the request changes, when the use was recorded before.
   - Majority (2 of 3) over Kimi's PARTLY on resizing: UzPainter refuses a release gap before mutation as policy (decisions 081, 082), not as Painter parity.
   - `rebuild_from_recipe` checks with the bytes it holds.
   - Legacy's image rules stay at evaluation, as before:
     - minification outside the texture unit's measured domain;
     - the L8 material rule (decision 208);
     - the grey-texture rule (decision 218).

## Alternatives Considered

- **Decoding by tag in the evaluator.** Rejected (C1). Records would differ between the facade and MCP. The CPU and GPU kernels would change. Saved documents would be reinterpreted.
- **Native setters deciding the profile alone, with the replays moved to real OCIO projects.** Rejected for now. Their exports would meet the OCIO bitmap refusals, and the committed capability trace would change.
- **A warning instead of a refusal for B5 (option c), or no change (d).** Rejected. The project would be left unexportable while the call reports success.

## Consequences

### Positive
- The same instruction gives the same texture through MCP, the native API, `run` and `sync_stack`. One function holds the decode and its refusals.
- MCP can no longer store OCIO colours nobody measured.
- Under OCIO, a project can no longer be put into a state that no export can evaluate through a bind, a projection change or a resize.

### Negative
- A native or MCP client that relied on raw storage now gets Painter's value. A colour sent without a space is now decoded on BaseColor. Such a client must send `Working` or `Raw` to store values unchanged.
- A native `get_color` reads back the working value tagged `Working`, not the value and tag given.
- Under OCIO, `set_resolution` and `set_channels` are refused while they would break a bound bitmap's recorded use.
