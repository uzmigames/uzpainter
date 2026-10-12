# 129. `infinite` padding on UV islands stays refused: the seam ring is not identified, and a jump flood seeded by the recorded ring is only an exploratory propagation candidate

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for an exact fit of `infinite` padding on UV-islanded sets. Decision 127 left three unknowns:
- the rule for the across-seam position, and its quantisation;
- the order of the passes;
- the sphere's pole wedges.

This record is a partial, factual one. The mechanism stays undetermined. The work was time-boxed (about 2 hours, plus one bounded correction pass after two Codex audits). It used only admitted goldens and private-store blobs, on the CPU, without Painter. Only numbers are given here.

**Comparison level.** A map matches only if every channel of every texel matches exactly:
- OpenEXR 32f: the uint32 bit patterns of the float32 values. The loader's float64 arrays were checked to round-trip to float32 exactly first.
- PNG: the integer codes.
- There is no tolerance.

Codex's independent receipt (`scripts/tmp/codex-audit/padding-checkpoint-receipt.json`) agrees with the arrays used here. It gives these RGB16 endpoint codes on seam User0:
- A = (13107, 26214, 39321);
- B = (58981, 32767, 6553), which decodes to (0.8999923468, 0.4999923706, 0.0999923721).

**Artifacts.** All are under `tier0/semantics/`.

- **Seam goldens.**
  - `export-padding-seam-256` and `-1024`: User0 and User1 (RGB16) and Height (L16F), steps 29-32. Steps 29-30 are PNG 16 and steps 31-32 OpenEXR 32f.
  - `export-padding-seam-field-256` and `-1024`: User0 (RGB16) and Height (L16F), steps 15-18. Steps 15-16 are PNG 16 and steps 17-18 OpenEXR 32f.
  - Within a golden, r1 equals r2, and both steps of each format are identical.
- **Control.** The constant golden's User1 (field A) steps 29/30/31/32 equal the field golden's User0 steps 15/16/17/18 bit for bit, at 256 and at 1024, in r1 and in r2.
- **Fixture differences.** The constant and field goldens differ in more than their values:
  - layers: the constant golden has a second fill masked by the side mask;
  - channels and step count: 32 steps against 18.
- **The 1024 pairs.** Each 256/1024 pair differs only in its identity and resolution fields. The bitmaps and the side mask stay 256×256, so the 1024 maps resample them. The island offsets (0.1, 0.6) change the sub-texel phase, so pixel i at 256 is not the same sample as pixel 4i at 1024.
- **Other meshes.** Every `infinite` map at 256 of `export-padding-bevelled-cube` (32 maps), `-sphere` (32) and `export-padding` (islands, 84): r1 and r2, PNG 16, PNG 8 and OpenEXR 32f, every channel.

## Findings

### 1. Building the ring: not identified

- **Compatible observations.** Two observations are compatible with ring weights that depend on geometry, not on data. The evidence is limited to these two fixtures, so this is not a proven rule.
  - In the seam field golden, A's ring texel equals a lerp between B's ring row and B's last row.
  - The weight is the same as in the constant golden (row 135: 0.50798 per channel).
- **B's ring** holds A's field resampled (alternating 0.3714/0.3720), not A's last-column value (0.37255).
  - This fits a pass order in which B's ring exists before A's ring samples it.
  - It does not prove that order: simultaneous or multipass behaviour is still possible.
- **Rejected: affine unfold with mip-0 bilinear.** This is a numerical rejection.
  - At 256, A's ring centre (0.5 A texels beyond A's edge, ratio s_B/s_A = 0.25/0.375) maps to B row 102.067. That predicts a weight of 0.4333 on B's last row. Observed, per channel: 0.50798, 0.32404 and 0.31085, period 3.
  - At 1024 it maps to B row 409.267, between rows 408.5 and 409.5, both covered B texels, so it predicts exactly B. Observed: 0.67092, then 0.76117, 0.78657, 0.80756, period 3.
- **Rejected: mip 1.** It predicts a constant 0.867 at 1024.
- **Inconclusive.** A two-parameter bilinear solve on the field puts the sample rows at 101.99/102.17/102.19 (256) and 409.69-409.74 (1024). Its x is ill-conditioned because the field varies slowly along the edge.
- **Correction to checkpoint 1.** The 1024 vectors near weights 0.375 and 0.125 lie on covered columns 0-1 of island A and on their gutter copies; the nominal 0.125 occurs only on covered column 1.
  - That is compatible with the 256 side mask being resampled across the wrap. It is a hypothesis, not a proven cause.
  - These vectors do not argue against any propagation model.
- **Membership.** Every gutter vector exists among the covered and ring texels, with or without wrap (Codex receipt). That proves only that the source values are available. It does not decide a propagation order.

### 2. Propagating the recorded ring: an exploratory candidate

This is **conditional on the oracle ring.** The values copied into the gutter are the golden's own ring values, and no ring value or covered value is predicted.

- **The seed set** is the 8-neighbour ring only (Normal maps included). The covered texels are not seeds; they are restored from the golden afterwards.
- **The ring** is the uncovered texels 8-adjacent to a covered texel (centre inside or on a UV triangle). It is taken with x wrap, so an island on the left border has ring texels in column N-1.
- **Code.** After the audit, the fill code (`jfa2.py`) was corrected:
  - only valid, in-domain, finite candidates update;
  - the "no seed" sentinel is explicit;
  - every final coordinate is checked to be a member of the seed set, and no texel stays unfilled.
- **Valid counts** are only those from the corrected runs (`reval.log`, `copybfs.log`, `tieprobe2.log`). Every count from before the correction is unsupported and is not used.

**Fit.** The fit set was only `export-padding-seam-256` User0 step31 r1.
- The candidate is a jump flood (steps N/2 … 1, 9 neighbours, no wrap in propagation). The 144 orderings searched are 6 x-orders × 6 y-orders × 2 nesting orders × 2 tie updates (strict or `<=`).
- Twelve orderings give 0 under the corrected code, six with x outer and six with y outer:
  - ('y',(-1,0,1),(1,-1,0),≤)
  - ('y',(1,0,-1),(0,-1,1),<)
  - ('x',(0,-1,1),(1,0,-1),≤)
  - ('x',(0,-1,1),(0,1,-1),≤)
  - ('x',(0,-1,1),(1,-1,0),≤)
  - ('y',(0,-1,1),(1,-1,0),≤)
  - ('y',(0,1,-1),(0,-1,1),<)
  - ('y',(-1,1,0),(1,-1,0),≤)
  - ('x',(1,-1,0),(-1,0,1),<)
  - ('x',(1,-1,0),(0,-1,1),<)
  - ('y',(1,-1,0),(0,-1,1),<)
  - ('x',(1,-1,0),(-1,1,0),<)
- All twelve give identical residual counts on every map below. `reval` compares counts only, not the maps of source coordinates.

**Residuals of the twelve orderings** (corrected run; texels missed per map, all channels):

| Set | Maps | Role | Texels missed per map |
|---|---|---|---|
| seam-256: every channel, step and recording, plus seam-field-256 | 40 | Same geometry as the fit, so the index map is not independent | 0 |
| bevelled cube | 32 | Not used for any choice | 0 |
| sphere | 32 | Not used for any choice | 3 each: (4,2), (8,1), (9,1) by the pole; Painter's value there is another seed's |
| islands | 84 | Fitting evidence: it decided "no wrap in propagation" | 6 each (Height 5); every one an exact distance tie |
| seam-1024 and seam-field-1024 | 40 | Fitting evidence: inspected before | 7 each, at (0..3, 48..50); Painter's value comes from a slightly farther seed (squared distance 288369 against 287912) |

The cube and the sphere are the only sets independent of the choices made. They share the seed-construction rule with the fit.

**Decision 090's copy order**, re-run with the corrected seeds (the same wrapped ring) and the same comparison:
- with x wrap: 2320 misses on seam-256, 0 on the cube and 35 on the sphere;
- without wrap: 316 on seam-256, 0 on the cube and 35 on the sphere.

This tests only decision 090's order (right, left, up, down, then the diagonals). Other copy orders, and copy dilation in general, stay live hypotheses.

**Unsupported counts.** The exact-Euclidean and separable-transform counts from before the correction (8833, 165, 57; 37-57) are not revalidated and support nothing.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090). Item 2.7 stays unchecked. No production code, semantics entry, capability or conformance case changes. Decision 090's description of propagation is not replaced: no mechanism is identified.
2. **Recorded as an exploratory, conditional candidate only.** Given the oracle ring (the 8-neighbour ring taken with x wrap):
   - a jump flood without wrap in propagation, under any of the twelve orderings, leaves 0 texels on 72 maps (40 seam-256, 32 cube);
   - it leaves 3 per map on the sphere, 5-6 on the islands and 7 on seam-1024.
   - Whether Painter uses a jump flood, a copy dilation or something else is not determined.
3. **Open.** Each of these blocks 2.7 on its own:
   - **(a)** Building the ring: the across-seam sample position and its quantisation for both islands, and the order or simultaneity of the two rings' writes.
   - **(b)** The propagation rule. The residuals of the candidate above (3, 6 and 7 texels) must reach zero, and the rule must be validated on data that took no part in choosing it.
   - **(c)** The pole texels on the sphere.

   Fitting (a) alone does not close 2.7.
4. **Future probes.** These are a specification for the owner's Painter session, not authorisation to use Painter. They are **exploratory**: they discriminate the hypotheses named below, but no promise is made that they settle the rule. Owner: `phase1.25_pilot-wand` item 2.7.

   **P-ramp: discriminating ring models.**

   *Meshes.* Each is two 10 cm quads sharing the 3D edge x = 10 cm. The vertices, faces and vertex order are those of `seam.obj`, and only the `vt` lines change. The seam is A's right edge u = A.u1 and B's bottom edge v = B.v0. B is turned 90 degrees as in `seam.obj`.

   | Mesh | A UV box (u0, u1, v0, v1) | B UV box (u0, u1, v0, v1) |
   |---|---|---|
   | ratio 1 (B/A scale 1) | (0.125, 0.375, 0.125, 0.375) | (0.5625, 0.8125, 0.625, 0.875) |
   | ratio 2 (B/A 0.5) | (0.125, 0.375, 0.125, 0.375) | (0.5625, 0.6875, 0.625, 0.75) |
   | ratio 1.5 (B/A 0.667) | (0.0625, 0.4375, 0.1, 0.475) | (0.55, 0.8, 0.6, 0.85) |

   - The ratio-1.5 mesh is `seam.obj` with A moved off the tile border. It is the border and mask-wrap control.
   - Each mesh is recorded at phase 0, and with every UV shifted by +0.25/1024 and by +0.75/1024. These are the fractional-phase controls.
   - The OBJ text is fixed by the generator `probe_gen.py` in private scratch: `vt` printed `%.9f`, LF line endings. Its SHA-256s:

   | Mesh | Phase 0 | +0.25 | +0.75 |
   |---|---|---|---|
   | ratio 1 | be463fa73ab3ddba7e6d536d1b9e366b9b987dd42494a53a7535af830b33c95e | a9300f4531619c51d931054b0634da0a6d38ba3d1577767b988cad5c4d504074 | e68e4c014bf51b2016ba5f5c0daf12afa509a866fac5073ba218d18f3256832f |
   | ratio 2 | 50376d51b0dbcdecbb9aa4e77051dcf9d3763669d7553209e002afa6f2a0b100 | d2dee8be1567e62c2ff8c674a7d636f985779c3827b5f6c61e3ce8734bf53c9d | b8b4a1ab1574c874d33db00128c0d33d9405afc222c067e22b080a540ea69d87 |
   | ratio 1.5 | ca9b86387b8bd14ba15766c37c4c4037f20c85f5c689125496e728569137bc62 | ebf2bc7a92ece0d4e17f263c4579d7f1145a0364cb28f55224fe27e13acf8c59 | 821c625e8e3cb90401b22116e719742a11aee234222db426d3b6ed24504b7553 |

   *Project.* The document resolution is 1024. `Stack.add_channel(User0, format=RGB32F)` sets the stored format explicitly, and the recorder reads it back and records it before any export. The record is refused if it is not 32F.

   *Layers.* One fill layer with only User0 active, no mask, Normal blending at opacity 1. Its source is a 1024×1024 OpenEXR float32 bitmap with UV projection and tiling 1, filtering left at the default and recorded:
   - R(x, y) = (x + 0.5)/1024
   - G(x, y) = (y + 0.5)/1024
   - B = 0.5
   - x is the column, y the row, rows top first.

   *Exports.*
   - `documentMap/user0:RGB`, OpenEXR 32f, padding `infinite`, done twice, in r1 and r2.
   - The same with `passthrough`. This is the covered-texel readback: every covered texel must equal the bitmap bit for bit, or the probe is void.

   *Target texels* at 1024:

   | Mesh, phase | A ring column | A ring rows | B ring row | B ring columns |
   |---|---|---|---|---|
   | ratio 1 and ratio 2, phase 0 and +0.25 | 384 | 640-895 | 384 | 576-831 (ratio 1), 576-703 (ratio 2) |
   | ratio 1 and ratio 2, +0.75 | 385 | 639-894 | 383 | 577-832 (ratio 1), 577-704 (ratio 2) |
   | ratio 1.5, phase 0 | 448 | 538-921 | 410 | 563-818 |
   | ratio 1.5, +0.25 | 448 | 537-920 | 409 | 563-818 |
   | ratio 1.5, +0.75 | 449 | 537-920 | 409 | 564-819 |

   *Rival predictions* for the weight on B's ring row in A's ring texel, under an affine unfold with mip-0 bilinear sampling of the final B texture:

   | Phase | ratio 1 | ratio 2 | ratio 1.5 |
   |---|---|---|---|
   | 0 | 0 | 0.25 | 0 |
   | +0.25 | 0 | 0.125 | 0 |
   | +0.75 | 0 | 0.375 | 0 |

   - That model is constant along the edge.
   - The behaviour seen at 1024 on `seam.obj` predicts the ratio-1.5 phase-0 mesh reproduces the 1024 values (ring-row weights about 0.19-0.33, period 3), if the border and mask wrap play no part.
   - Under direct sampling, R and G of A's ring invert to the sample coordinate. Under mixtures, footprints or quantisation they give only an effective coordinate, or none that is unique.

   **P-tie: discriminating propagation rules.**
   - Mesh: three separate axis-aligned 10 cm quads, each its own UV island. The UV squares have side 0.125, with lower-left corners at (0.1875, 0.1875), (0.6875, 0.1875) and (0.4375, 0.6875).
   - Before any capture, an explicit P-tie OBJ and its SHA-256 must be fixed. Neither is fixed yet.
   - The same channel and layer as P-ramp, at document resolution N = 512 and N = 2048, exported as OpenEXR 32f with `infinite`, twice, r1 and r2.
   - For each tested N, the source is an N×N OpenEXR float32 bitmap: R(x, y) = (x + 0.5)/N, G(x, y) = (y + 0.5)/N, B = 0.5.
   - The `passthrough` covered-texel control is compared bit for bit against that same N×N bitmap.
   - Prediction at 512 from the corrected code: the twelve candidate orderings agree with each other seed for seed, and differ from an exact Euclidean transform at 363 texels.
   - This probe tells "this jump flood" from "exact Euclidean". It does not tell the twelve orderings apart.

## Consequences

- 2.7 stays open, and so do G1's P1-WAND gate (items 3.1 and 4.1) and the wand's five-map export. Their other prerequisites stay as recorded elsewhere: item 2.6, the goldens, and decision 126's follow-ups.
- Recording P-ramp and P-tie is necessary but not sufficient. Open items 3(a), 3(b) and 3(c) each need an exact fit, validated on both recordings, on every native depth and on data not used to choose the rule.
- The analysis scripts and logs stay in private scratch: `geom.py`, `jfa2.py`, `objcov.py`, `reval.py`, `reval.log`, `copybfs.py`, `copybfs.log`, `tieprobe.py`, `tieprobe2.log`, `probe_gen.py`.
