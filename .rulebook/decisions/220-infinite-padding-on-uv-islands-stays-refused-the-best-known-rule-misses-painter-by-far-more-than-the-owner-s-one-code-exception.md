# 220. `infinite` padding on UV islands stays refused: the best-known rule misses Painter by far more than the owner's one-code exception

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` (`infinite` padding on UV-islanded sets) has stayed open through decisions 127, 129, 176, 184, 197, 206, 210, 211, 216 and 217. It is the last blocker of the Wand pilot.

**The owner's answer.** On 2026-10-13, in the coordinator session, the owner (André) was asked "O padding da Varinha não fecha exato depois de 8 tentativas … O que eu faço?". He chose the option "Exceção limitada (Recomendado)":
- approve a registered exception only for `infinite` padding;
- texels outside the islands and on seams may differ by at most ±1 code;
- texels inside the islands must stay exactly equal;
- the Wand unblocks now, and the hunt for the exact rule continues in parallel.

**What was not measured.** The "±1 code at 16 bits" was the coordinator's estimate. Under decisions 015 and 017, an exception needs its bound measured, with evidence, for its domain and metric. So this pass had one first job: measure the best-known rule against every recorded padding golden. The exception is registered only if the measured bound fits inside what the owner approved.

## Method

**The best-known rule.** It was assembled from the decisions above as a CPU prototype. The prototype is kept in private scratch (`pad220/`), as decision 090 §4 keeps the partial fit's reference implementation.
- **Coverage.** A texel is covered when its centre lies inside or on a UV triangle, the `geometry_mask.h` convention. The `vt` values are read as float32.
- **Border ring** (decisions 176 and 206). The ring texel takes the mean of its covered 8-neighbours, with weight 1 for a side neighbour and f/(1 − f) for a diagonal, f = 0.4142245.
  - On a straight edge one diagonal is weakened, so that the mean moves 24.875·2⁻¹⁵ texel along the edge.
  - The direction follows decision 206's fixed rule: +x on horizontal edges, −row on vertical edges.
  - The result is rounded to float32 and then through 1 − (1 − v), which puts it on the 2⁻²⁴ grid.
  - A mean of equal values returns that value. The constant seam goldens need this, because their constant ring equals the covered value exactly.
- **Seam ring** (decision 211). A ring texel whose nearest island edge is a seam takes up to four taps:
  - the candidates are its own covered 8-neighbours and the far island's texels in the two rows that bracket the unfolded point;
  - the four nearest by unfolded world distance are kept, weighted 1/d;
  - a tap at d = 0 is copied.
- **Seam corners and poles.** No identified rule exists for them (decision 211, 4(c) and 4(d)). Corner ring texels take the same four-tap mean over the far taps of every seam edge within 0.3 texel of the nearest one.
- **Gutter** (decision 197). A jump flood seeded by the covered and ring texels. The ring is taken with x wrap: wrap lowers the error on every golden with an island on the tile's left border and changes nothing on the others.

**What was compared.**
- **Source.** For each map, the covered texels of Painter's own r1 `infinite` OpenEXR 32f export are the raster.
- **Comparison.** The padded raster is compared on every uncovered texel:
  - with that OpenEXR 32f export, as an absolute float difference;
  - with every PNG 8 and PNG 16 file Painter exported of the map, in codes. Both sides go through the same encode: UNORM, Height as v·0.5 + 0.5, and sRGB for BaseColor.
- **Probes.** The P-ramp and P-tie probes were exported to OpenEXR 32f only. Their PNG 8 and PNG 16 figures are the hypothetical encode of the same rasters, marked *.
- **Covered texels.** The coverage mask equals Painter's: on every position-encoded probe, the texels holding their own position are exactly the covered ones, and on the cube and sphere the `infinite` and `passthrough` exports agree on every covered texel. No covered texel differs anywhere (column "Covered differing").

**The Wand.** The Wand's R9 golden (decision 180) was put through the same prototype.
- Its covered texels are read from Painter's PNG 16 files as UNORM operands. The mesh is the manifest's `wand-mesh` input, read by its hash from the private store.
- This is the measurement the Tier 1 runner would give. No DX12 run was made: UzPainter refuses the Wand's export before writing (`candidate_export_refused`), so a run only proves that refusal.

Everything ran on the CPU from the private store, without Painter and without a GPU. Only numbers are recorded here.

## Findings

### 1. The measured bound is far above one code at every bit depth

These are r1 `infinite` maps, measured on uncovered texels only. "Maps" counts the distinct texture-set maps.

| Golden | Maps | Padding texels | Covered differing | OpenEXR 32f max abs | PNG 16 max (codes) | PNG 16 texels > 1 code | PNG 16 mean | PNG 8 max (codes) | PNG 8 texels > 1 code |
|---|---|---|---|---|---|---|---|---|---|
| ramp-r1-p0-v2 | 1 | 917,504 | 0 | 0.146 | 9,593* | 231,756* | 117* | 38* | 109,150* |
| ramp-r1-p25-v2 | 1 | 917,504 | 0 | 0.309 | 20,263* | 231,756* | 690* | 78* | 109,150* |
| ramp-r1-p75-v2 | 1 | 917,504 | 0 | 0.353 | 23,157* | 231,755* | 772* | 90* | 205,302* |
| ramp-r2-p0-v2 | 1 | 966,656 | 0 | 0.5 | 32,743* | 378,961* | 1,810* | 127* | 277,782* |
| ramp-r2-p25-v2 | 1 | 966,656 | 0 | 0.402 | 26,342* | 377,456* | 1,800* | 102* | 277,782* |
| ramp-r2-p75-v2 | 1 | 966,656 | 0 | 0.1 | 6,566* | 305,062* | 462* | 25* | 109,901* |
| ramp-r15-p0-v2 | 1 | 835,584 | 0 | 0.405 | 26,569* | 288,896* | 404* | 103* | 160,510* |
| ramp-r15-p25-v2 | 1 | 835,584 | 0 | 0.363 | 23,764* | 354,319* | 3,200* | 93* | 167,973* |
| ramp-r15-p75-v2 | 1 | 835,584 | 0 | 0.413 | 27,033* | 308,465* | 409* | 105* | 66,883* |
| tie-512 | 1 | 249,856 | 0 | 2.98·10⁻⁶ | 1* | 0* | 0.025* | 0* | 0* |
| tie-2048-v2 | 1 | 3,997,696 | 0 | 7.15·10⁻⁷ | 1* | 0* | 0.0096* | 0* | 0* |
| tie-512-box16 | 1 | 249,856 | 0 | 0 | 0* | 0* | 0* | 0* | 0* |
| ramp-r1-p0-box17 | 1 | 917,504 | 0 | 0.146 | 9,593* | 231,756* | 117* | 38* | 109,150* |
| seam-ramp-1024 | 1 | 835,584 | 0 | 0.405 | 26,569* | 176,570* | 485* | 103* | 61,544* |
| export-padding (islands) | 7 | 260,498 | 0 | 0.355 | 23,265 | 38,583 | 20.7 | 90 | 2,553 |
| export-padding-bevelled-cube | 4 | 48,800 | 0 | 1.18 | 51,315 | 43,410 | 4,510 | not exported | not exported |
| export-padding-sphere | 4 | 16,384 | 0 | 0.594 | 44,111 | 14,018 | 561 | not exported | not exported |
| export-padding-seam-256 | 3 | 156,672 | 0 | 0.202 | 13,211 | 43,482 | 539 | not exported | not exported |
| export-padding-seam-1024 | 3 | 2,506,752 | 0 | 0.568 | 37,213 | 527,136 | 472 | not exported | not exported |
| export-padding-seam-field-256 | 2 | 104,448 | 0 | 0.246 | 8,068 | 37,414 | 415 | not exported | not exported |
| export-padding-seam-field-1024 | 2 | 1,671,168 | 0 | 0.427 | 26,673 | 494,439 | 335 | not exported | not exported |
| **Wand R9** (PNG 16, 2048) | 5 | 3,685,999 each | 0 | not exported | 59,150 (Metallic) | 482,652 to 3,685,999 per map | 2.5 to 6,398 per map | not exported | not exported |

The Wand per map, in 16-bit codes:

| Map | Max | Texels > 1 code |
|---|---|---|
| BaseColor | 42,573 | 3,685,997 |
| Roughness | 26,267 | 1,199,155 |
| Metallic | 59,150 | 868,021 |
| Height | 55 | 482,652 |
| Normal | 36,756 | 3,685,999 |

**Only the tie probes stay within ±1 code at 16 bits, and only with their fixed or near-fixed sign.** Every golden with a seam, an island corner other than a plain 90° corner, a rotated or narrowly spaced island, or a sphere pole exceeds the bound by 3 to 4 orders of magnitude. PNG 8 fails the same way: up to 90 codes on Painter's PNG 8 files of `export-padding`, and up to 127 on the probes' hypothetical encode.

### 2. Where the error comes from

Each uncovered texel was attributed to the ring texel its gutter copies, or to itself when it is a ring texel. In 16-bit codes:

| Ring class | Measured |
|---|---|
| Straight border edge (decision 206) | At most 1 code on the P-tie and P-ramp probes. Up to 16 codes on the seam and seam-field goldens, where these ring texels border a seam corner's wedge. 2,068 codes on Height and 23,265 on Normal_OpenGL of `export-padding`, whose islands sit 1 and 3 texels apart and one is turned 30°. |
| Other border texels (corners, turned edges) | 1,285 to 23,764 codes |
| Seam ring (decision 211) | 0 on ratio-1 r1-p0. 237 to 38,818 codes elsewhere. The 1/d weights are off by 10⁻³ (decision 211), and the tap choice is unknown on 208 texels. |
| Seam corners and sphere poles | 471 to 51,315 codes. No rule is identified (decision 211, 4(c) and 4(d)). |

A single wrong corner or seam ring value is copied by the jump flood into a wedge of the gutter. A rule error that is small on the ring therefore reaches hundreds of thousands of texels.

On the Wand, a closed mesh whose island borders are all seams, 3,326,676 of its 3,685,999 padding texels copy a seam-corner ring texel.

### 3. The open parts are not near-misses

The large errors come from parts with no identified rule: seam corners, sphere poles, turned edges and narrow gaps. Bounding them would need a rule. A bound measured today on a guessed rule would not hold for the next mesh: the Wand alone reaches 59,150 codes.

## Decision

1. **The owner's exception is not registered.** He approved ±1 code; the measured bound is up to 59,150 codes at 16 bits and up to 127 at 8 bits. Under decision 017 no exception may cover a divergence larger than its owner-approved bound.
   - `parity/exceptions.json` is unchanged, with no EXC-007.
   - The verdict tool is unchanged.
2. **The R-090 refusal stays.** `infinite` on islanded sets is refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case or test changes.
   - The best-known rule is not written into `padding.h`: a native copy that stays refused would be dead code. The prototype stays in private scratch.
3. **The Wand stays blocked on 2.7** (items 3.1 to 3.3 and 4.1). The Tier 1 DX12 run was not made, because it can only show the known refusal.
4. **For the owner** (owner-only: an exception's terms). These are the measured bounds an exception would have to cover:
   - **Exactly zero on covered texels.** The rule never touches a covered texel, and the coverage mask equals Painter's (Method). 0 covered texels differ on all 39 maps and on the Wand's 5.
   - **On padding texels, in the worst case:**
     - PNG 16: 59,150 codes (the Wand's Metallic);
     - PNG 8: 90 codes on Painter's PNG 8 files (`export-padding`), 127 on the hypothetical encode of the probes;
     - OpenEXR 32f: 1.18 absolute (Height, `export-padding-bevelled-cube`).
   - **Restricted to straight border edges on probes,** the bound is 1 code at 16 bits. Even that does not hold on the islands golden or the seam goldens.

   A "padding differs freely, interior exact" exception (any value outside the islands) would cover all of these. It is a different decision from the ±1 one the owner took, and needs his explicit approval.
5. **The exact hunt continues** (owner: `phase1.25_pilot-wand` item 2.7). In order of the texels they affect:
   - (a) seam corners;
   - (b) the seam weights and tap choice (decision 211, 4(a) and 4(b));
   - (c) turned and narrowly spaced border rings (`export-padding`);
   - (d) the sphere poles;
   - (e) the ring sign (decision 210, 4(a)).

   Decision 216's open question about A's left ring column is settled by measurement: the x-wrapped ring fits better on `export-padding-seam-ramp-1024` (0.405 against 0.799) and on every left-border golden.

## Consequences

- G1's P1-WAND gate and the Wand's five-map export stay blocked on 2.7, as decisions 127 to 217 recorded.
- The coordinator's ±1 estimate is replaced by measured bounds, per golden and per format.
- If the owner wants the Wand unblocked before the exact rule is found, the choice in Decision 4 is his: an exception for padding texels without a numeric bound, with interior exactness enforced by a coverage mask.
