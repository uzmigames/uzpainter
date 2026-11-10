# Snapshots inside mask stacks, 2026-11-10 (phase3.3_procedural-families item 2.15)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, two Painter sessions under the Assets3D Painter lock (seq 2376 to 2377). The requests were committed before the sessions (`f4072e7b`, `daf48bf1`; code `tools/parity/tier0_semantics/snapshot_in_mask.py`). Each golden was recorded twice (r1; r2 after save and reopen) with `python -m tools.parity.recorder.launch_record`, admitted, verified, and its inbox run deleted. Numbers below come from `python -m tools.parity.fit.snapshot_in_mask`. Every map is a private oracle in the owner's store; no Painter value is published.

**Outcome: not exact. Item 2.15 stays open.** The support check still refuses a generator effect and a snapshot mask source before mutation. The capability entry `SourceSubstance` `compositor:snapshot-in-mask` stays a release gap. Two separate facts block exact serving. Each needs a choice that is not this item's to make.

## 1. Recordings

Both goldens use the destination of the 2.13/2.14 captures (store record `grunge-snapshots-project`): the authored plane at 256 px, OpenGL, with the fixtures `grey-a`, `half-steps-grey`, `field-a` and `field-b` bound as its AO, Curvature, Position and World Space Normal mesh maps. Each case is a white Raw fill on its own L32F User channel, over a black Raw base fill, under a mask, so the channel holds the mask value. Every grunge and generator uses exactly a parameter set the capture holds.

- `tier0/semantics/snapshot-in-mask`: the recipes' modes and opacities. Cases:
  - `rock` Normal 1;
  - `dirt-a` (seed 1) Normal 0.31;
  - `dirt-a` (seed 1), then `rock` Multiply;
  - `dirt-a` (seed 2), then `dirt-large` LinearDodge 0.14;
  - Mask Builder - Legacy Normal 0.91;
  - Metal Edge Wear, then `rock` Multiply;
  - Dirt, then the bitmap `grey-a` Subtract 0.9;
  - Dirt (seed 2) Normal 0.5 over a White mask.
- `tier0/semantics/snapshot-in-mask-sources` (the separating recording, made in a fresh Painter session): each of those eight sources alone at Normal 1 in a black mask.

## 2. Results

**Stability.** In both goldens, r1 equals r2 on every texel. A fresh session does not always reproduce the 2.13/2.14 capture:

| Source | Texels that differ from the capture (of 65 536) | Largest difference (16-bit codes) |
|---|---|---|
| `grunge/rock`, `grunge/dirt-large` | 0 | 0 |
| `grunge/dirt-a` seed 1, seed 2 | 5, 4 | 1, 1 |
| Dirt (default seed) | 8 | 20 |
| Dirt (seed 2), Metal Edge Wear | 0 | 0 |
| Mask Builder - Legacy | 10 | 23 |

The texels that differ are not the same in every session. In the first golden's session, Dirt (seed 2) differs from the capture at 4 texels by 22 codes. In the fresh session it equals the capture on every texel. The Dirt and Mask Builder texels repeat every 64 or 128 rows.

**16-bit codes.** Every value in every export, snapshot captures included, is within 0.01 code of a 16-bit code k. Each code always gives the same float32, G(k): 58 701 codes were seen and no code gave two values. Below code 32 768, G(k) is often not the correctly rounded float32(k / 65535): 255 of 256 codes below 256, 3 670 of 3 840 in 256..4095, 9 728 of 12 288 in 4096..16383 and 8 070 of 16 125 in 16384..32767. From 32 768 up, G(k) is the correctly rounded value on all 26 192 codes seen. This is the 16-bit conversion that decision 423 §3 found on the AO generator.

**Mask arithmetic.** A code-level model matches every texel except those the instability above can explain:
- the mask starts at its background code;
- each effect reads the mask and its source as float32(k / 65535) of their 16-bit codes (the snapshot's own float is not used);
- r = kernel(mode, m, b) is clamped to [0, 1];
- the effect mix is applied, then the result is stored at 16 bits by the UNORM write rule;
- the channel holds G of the final code.

Mismatching texels per case, with the effect mix as `fma(r - m, alpha, m)` and as the evaluator's `m + (r - m) alpha`:

| Case | fma | evaluator's mix | With the evaluator's read float32(k / 65535) in place of G |
|---|---|---|---|
| `rock` Normal 1 | 0 | 0 | 10 204 |
| `dirt-a` Normal 0.31 | 2 | 2 | 43 783 |
| `dirt-a`, `rock` Multiply | 4 | 4 | 40 089 |
| `dirt-a`, `dirt-large` LinearDodge 0.14 | 4 | 22 | 43 665 |
| Mask Builder Normal 0.91 | 10 | 10 | 470 |
| Metal Edge Wear, `rock` Multiply | 0 | 0 | 6 574 |
| Dirt, `grey-a` Subtract 0.9 | 8 | 20 | 23 888 |
| Dirt (seed 2) Normal 0.5 over White | 4 | 4 | 4 |

The texels that remain under `fma` match the instability above: the fresh session's differing texels of the same source (Mask Builder: 8 of its 10; `dirt-a`: 15307, 19302, 6491 and 9976), or texels of the same periodic pattern.

## 3. What this separates

- **Fact:** inside a mask, Painter reads a procedural source as its 16-bit code, and the mask is the recorded 16-bit mask (masks-levels.json `mask-precision`). Nothing new is needed there, except the mix's rounding below.
- **Fact:** `fma(r - m, alpha, m)` leaves 30 fewer mismatching texels than the evaluator's two-rounding mix, on LinearDodge 0.14 and Subtract 0.9. **Hypothesis:** Painter's mask effect mix is one fused multiply-add. To confirm it, the existing mask goldens would need to be replayed with that mix before anything changes. At opacity 0.5 the two forms are equal.
- **Blocker 1, the 16-bit read (decision 423 §3):** the mask reaches the channel as G(k), not as float32(k / 65535). On an L32F channel the evaluator's read differs on up to 43 783 of 65 536 texels. Exact composites need G for every code below 32 768. That means either a UzmiGames measurement of the recording GPU's 16-bit texture conversion, or a 65 536-entry table, which decision 423 rejects because it ships Painter outputs. That choice is the owner's. No tried closed form reproduces G: rounding to 24 fractional bits still misses 5 398 of the codes seen.
- **Blocker 2, cross-session instability (new):** Painter does not reproduce its own seeded grunges and generators across sessions on a few texels, by up to 23 codes. A snapshot is byte-equal to the Painter session that captured it, but no snapshot predicts every texel of another session. Exact parity against an independent Painter recording of a seeded source therefore needs a comparison rule this item cannot set. Options include a same-session reference, or an exception that only the owner may approve. `grunge/rock`, `grunge/dirt-large`, Dirt (seed 2) and Metal Edge Wear were stable here.

No decision record, exception, tolerance or capability change was made.
