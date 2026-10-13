# 156. The sRGB bitmap variants request runs on a 3x3 grid, and the recorder records an attempted `set_color_space` and the Legacy bitmap spaces

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand

## Context

Decision 145 §3 specifies one Tier 0 recording, `tier0/semantics/srgb-bitmap-variants`, which settles every sRGB bitmap use that stays refused. The request had to be authored so that the next Painter session only runs it. Writing it out showed four gaps between the specification and what can be recorded:

- **Nine sets on an eight-set grid.** The decision names sets s0 to s8 (nine) on the 4x2 grid, which has eight.
- **Two bitmaps on one channel.** s1 to s3 put field A and `srgb8-ramp` on BaseColor in the same set. A second fill at opacity 1 in Normal hides the first.
- **A refusal that must be kept.** s5 attempts `set_color_space(sRGB)` on a mask fill effect's grey source and keeps Painter's refusal if it refuses. The recorder applies a state step once and refuses the whole golden when Painter raises (decision 100).
- **Spaces the recorder cannot set.** s6 to s8 set the Legacy Linear and Legacy sRGB spaces. The recorder sets a bitmap's space only from `GenericColorSpace` (`sRGB`, `Working`, `Raw`).

The model panel was not consulted. Each gap has one reading that keeps the decision's intent, and none changes what is observed.

## Decision

1. **The grid.** The golden runs on an authored 3x3 plane grid, `grid3x3.obj`, generated like the other grids (`fixtures.grid(3, 3)`). Its nine sets are s0 to s8 as decision 145 numbers them. Everything else stays as specified: Legacy, 256 px, PNG 16, PNG 8 and OpenEXR 32f.
2. **s1 to s3.** One fill per set:
   - field A (16-bit) on BaseColor;
   - the 8-bit `srgb8-ramp` on Emissive, added as sRGB8 (an sRGB8 material channel whose empty base is observed, decision 126).

   Both are set to sRGB, and the decision's UV projection applies to the fill. The wrap is Repeat, so the fill covers every texel and no template base shows through.
3. **s4.** The L channels User2 (L8) and User4 (L16) take grey A, and the colour channels take field A. Decision 048 makes an L channel take the grey fixture. Every source is set to sRGB.
4. **An attempted `set_color_space` (recorder vocabulary).**
   - The state call `substance_painter.source.SourceBitmap.set_color_space` takes `node_step` (an `insert_fill` step), `channel` (null for a mask fill effect) and `color_space`.
   - What Painter raises is caught inside Painter. The record's effective defaults hold `set_color_space.<step>` as `applied: true`, or as `applied: false` with the exception's type and message. The golden is still recorded.
   - s5 uses it. The mask covers a uniform BaseColor (0.2, 0.5, 0.8), sRGB.
5. **Legacy bitmap spaces (recorder vocabulary).** A bitmap's `color_space` may be `LegacyColorSpace.Linear` or `LegacyColorSpace.sRGB`. A qualified name keeps a bare `sRGB` the generic member. Any consumer that does not know the qualified tag refuses it as unrecorded (`BitmapColourSpaceOf`), so nothing reads it as the fitted sRGB. Uniform colours keep the generic spaces only.
6. **A projection capture (recorder vocabulary).** `FillLayerNode.get_projection_parameters` is a texture-job capture taking `node_step` (an `insert_fill` step). It records a fill's projection without setting it first. Decision 129's padding probes need it to record the default filtering.
7. **Captures.** Every bitmap of the golden, the mask source included, gets `list_available_color_spaces` with `get_color_space`. Every export step is done twice, as in decision 100.

## Alternatives Considered

- **Use the 6x4 grid (24 sets).** Rejected. Fifteen empty sets add files without adding observations.
- **Put the two s1 to s3 bitmaps in two sets each.** Rejected. It needs six sets for three samplings and still does not fit one grid.
- **Record s5 as an API probe (`probe: true`).** Rejected. The texture exports and colour-space captures of the other sets would then need a second golden.

## Consequences

### Positive
- `srgb-bitmap-variants` is committed and recordable without code changes in the Painter session (Session L of `parity/RECORDER.md` §11).
- The recorder vocabulary gains the three calls above, with fake-Painter tests (`tests/parity/recorder/test_texture_captures.py`).

### Negative
- The fit owner (phase1.15 item 2.2) reads s1 to s3's 8-bit bitmap from Emissive, not BaseColor. Both are sRGB8 material channels with the same decode and encode (decisions 126 and 145).
