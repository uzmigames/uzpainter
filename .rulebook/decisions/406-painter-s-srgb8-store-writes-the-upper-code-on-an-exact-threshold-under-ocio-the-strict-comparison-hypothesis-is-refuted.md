# 406. Painter's sRGB8 store writes the upper code on an exact threshold under OCIO; the strict-comparison hypothesis is refuted

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.2_unreal-ue56-packed-preset, phase1.26_gate-g1

## Context

R-322 (gate G1 record §9.1, `test_r322_tga_capture_diagnostic`). The admitted OCIO decode-stage control `ocio16-bitmap-srgb-basecolor-rgb32f` (decision 405) shows the float32 each 16-bit code of field-a decodes to under OCIO. Measured against the sRGB8 control `ocio16-bitmap-srgb-basecolor` (PNG8, r1): exactly three decoded values equal an sRGB8 threshold t_k of the native store (`arith.cpp` `kSrgb8ThresholdBits`), at the 16-bit codes 2429, 6548 and 14017 (t_10, t_26, t_55), and Painter stored k - 1 for each, where `arith::Srgb8Store` (the number of thresholds at or below v) gives k. Under "strict comparison" (the number of thresholds below v) the sRGB8 control has 0 misses of 65,536; under the native rule, those 3. The hypothesis was fitted on the same three points it explains, so no native change was made before a confirming recording.

## Decision

1. **Probe.** `tier0/api-probes/ocio-srgb8-threshold-ties` (`tools/parity/tier0_semantics/srgb8_threshold_ties.py`, request and authored input `parity/fixtures/tier0-semantics/bitmaps/srgb8-thresholds.exr` committed): an OpenEXR float bitmap set to `GenericColorSpace.Raw` (a data space: no OCIO conversion, read back typed as `GenericColorSpace.Raw` in r1 and r2), projected 1:1 on BaseColor sRGB8 of the 256 px plane, exported PNG8 passthrough, r1 and r2, OCIO session. Column x holds t_x (all 255 thresholds) with, in rows 0-127, the binary16 values just below and above, and in rows 128-255 the float32 values just below and above.
2. **Recording (2026-11-08, Painter 12.2.0, OCIO, under the Assets3D Painter lock, `envelope check --request` exit 0 under decision 405).** Admitted (4 private records); r1 and r2 exports are byte-identical. A first attempt without a colour-space setter read back `sRGB` (the bitmap was decoded through the configuration's sRGB LUT, so its values did not reach the store unchanged); that run was discarded before admission and the request was re-authored with the explicit Raw setter.
3. **Result** (`python -m tools.parity.tier0_semantics.srgb8_threshold_ties analyse`, counts only), the same in r1 and r2:
   - native rule (`>=`): 0 misses of 196,608 samples, including all 65,280 samples exactly on a threshold (255 distinct thresholds: 48,128 on the 188 binary16-exact ones, 17,152 on the 67 others) and every binary16 and float32 neighbour;
   - strict rule (`>`): 65,280 misses, every exact-threshold sample; 0 on the neighbours.
   So on a value exactly on t_k Painter stores k under OCIO, and the float32 neighbours show it keeps the float bitmap at float32 precision. **The strict-comparison hypothesis is refuted.** No native code changes; `Srgb8Store` and the thresholds stay as they are.
4. **What remains open (hypothesis, not adopted).** The three ties of the RGB16 path are not a store-comparison effect. The value that reaches the sRGB8 store from a 16-bit sRGB bitmap under OCIO must lie below the float32 the RGB32F channel exports at those three codes (for example a decode evaluated differently for the two channel formats). Settling it needs its own probe; it stays with `phase3.2_unreal-ue56-packed-preset` item 2.5.

## Alternatives Considered

- **Implementing strict comparison scoped to OCIO on the three-point fit.** Rejected: unconfirmed, and now contradicted on 255 thresholds.
- **A float bitmap in its default space.** Tried and discarded: Painter assigned `sRGB`, so the stored values were LUT-decoded, not the authored thresholds.

## Consequences

- `test_r322_tga_capture_diagnostic` stays red on this ground: the OCIO RGB16 bitmap route remains unsupported (decision 190) and its decode-to-store value at the ties is not identified.
- Tests: `tests/parity/recorder/test_srgb8_threshold_ties.py` (request, authored field, verdict).
