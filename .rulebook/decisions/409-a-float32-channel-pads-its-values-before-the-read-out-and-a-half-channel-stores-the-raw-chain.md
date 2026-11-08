# 409. A 32-bit float channel pads its values before the read-out, and a 16-bit float channel stores the raw chain

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.1_export-island-padding
**Refines**: decisions 206 (where its 1 - (1 - m) step lives), 274 (the operands of a float channel) and 288 (a)

## Context

`export-padding`'s User1 (L32F, filled from the 8-bit bitmap `grey-a`) was the last map of that golden whose `infinite` OpenEXR 32f ring differed from the reference: 83 of 1,387 ring texels (task notes 2026-11-05). The kernel probe `export-padding-kernel-islands-256` (admitted 2026-11-08) showed the reference's taps and fractions are Painter's on that mesh (0 of 1,387 ring texels differ), so the misses came from the values.

Black-box readings of Painter's r1 and r2 files (`tools/parity/fit/padding_goldens.py`, counts only):

- Every User1 covered value is float32(1 + float32(float32(k / 255) - 1)) for the 8-bit code k at that texel (230 of 230 distinct values): the read-out of a 32-bit float channel over the white base (`arith::Float32Readout`, "1 + (v - 1)"), which equals 1 - (1 - v). Only 103 of them equal float32(k / 255) itself.
- Every ring value is a fixed point of that read-out (1,387 of 1,387).
- The chain (decision 268) over the covered texels' **exported** values, then 1 - (1 - m): 83 ring texels differ. Over float32(k / 255), the values **before** the read-out, then 1 - (1 - m): 0 differ, and the gutter, the covered texels and every other map stay exact, r1 and r2.
- Rejected on the exported values: no 1 - (1 - m) (320 misses), the chain on 1 - v (207), five other lerp formulations at each level (82 to 458), one exact rounding of the real chain (59 and more), the step at every level (73), and values float32(k) float32(1/255) (283).

So decision 206's 1 - (1 - m) is the float32 channel's read-out, applied once to the padded value; the chain runs on the channel's values before it. Commit 0afd4d7d had found the companion half rule on the same goldens: a 16-bit float channel (the Height) stores the half toward zero of the chain **without** that step (one Height ring texel each on `export-padding`, the cube and the sphere), which a channel without a float32 read-out implies.

## Decision

1. **A 32-bit float documentMap channel** (L32F, RGB32F) is padded on its values before the read-out. `evaluator::EvaluateBeforeReadoutOn` gives them: per tile, the isolated root composited over a zero base (`EvaluateFloat32Readout`), which is the root's value where the stack covers the texel fully; the read-out base for an empty stack. `EvaluateFileOn` carries them as `FileRaster::operands` when the file's padding is `infinite`; a profile whose root is not isolated keeps the values, as before. The ring keeps decision 206's 1 - (1 - m), which is that read-out over the white base.
2. **A 16-bit float documentMap channel** (L16F, RGB16F) keeps the ring's raw chain: `ApplyPadding` takes one raw-chain flag per channel (`encode.cpp` `RawChains`), and the filled texel is stored as the half toward zero of it (decision 274).
3. **Every other channel** is unchanged.
4. **The scorer** (`padding_goldens.py`) mirrors both: the half store reads the raw chain; a float32 store's operand of a covered value is the 8-bit decode float32(k / 255) whose read-out is that value, or the value itself when none is (the listed goldens fill their float channels from 8-bit bitmaps).

This is the measured padding only: `CheckPadding` (decision 259) still refuses `infinite` on islands in production, and no exception changes here.

## Scores after this decision

- `padding_goldens.py` on the listed goldens: `export-padding` is exact on every texel of every `infinite` OpenEXR 32f map, r1 and r2, User1 included. The cube and the sphere keep their kernel-class ring misses (decision 368's open classes); the seam goldens stay exact.
- Natively, end to end (`tests/export/test_export_padding_tier0.py`): `export-padding`'s `uzp_islands` rebuilt from its manifest and written by the diagnostic measure export at its `infinite` OpenEXR 32f steps; BaseColor, SpecularRoughness, Height, User0 and User1 equal Painter's r1 and r2 files on every texel. The Opacity channel is left out (its bitmap's colour space and its base on Opacity are not recorded), and the virtual Normal's covered island edge is item 2.2's.

## Not covered

- A covered texel that the stack covers only partly (coverage below 1 before the read-out): its operand is the root's premultiplied value, and Painter's operand there is not recorded.
- A 32-bit float channel over a base other than white: the read-out over another base would not be 1 - (1 - m); the ring keeps decision 206's step there, unrecorded.
