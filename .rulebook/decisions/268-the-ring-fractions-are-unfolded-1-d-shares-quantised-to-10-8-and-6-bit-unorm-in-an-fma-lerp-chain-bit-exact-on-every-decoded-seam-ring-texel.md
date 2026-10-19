# 268. The ring fractions are unfolded 1/d shares quantised to 10-, 8- and 6-bit UNORM in an FMA lerp chain, bit-exact on every decoded seam-ring texel

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What earlier passes left on the seam ring** (ring texels whose island edge is a UV seam):
- the taps are about the 4 nearest of the own 8-neighbours plus a far strip (decision 262);
- the weights are close to 1/d but not 1/d. Two far taps at bit-equal distance get weights 1.0046 apart, and no float32 distance explains it (decisions 262, 265);
- decision 269 found that a corner ring texel is a float32 FMA lerp chain with fixed fractions, and that the fractions are not 1/d.

**This pass covers the seam ring only:** the atlas seam items (flat and folded), and the seam rings of the five kernel ramp probes. Straight non-seam edges belong to decision 267, and corners and poles to decision 269. Their texels were decoded too, only as checks.

**The data** are decision 266's probes, recorded on 2026-10-19 (commit c1f30c3): the r1 `infinite` exports (step 45) of `export-padding-kernel-atlas-{512,1024,2048,1024-moved}` and `export-padding-kernel-ramp-{r1-p0,r2-p0,r2-p25,r15-p0,r15-p25}`, all 8 User channels. They were read from the private store.

**How the taps were decoded:**
- **Coverage.** A covered texel is one where `infinite` equals the authored source on all 24 channels. On the atlas this matches the mesh's own rasterisation: 2,928 texels, item by item.
- **Search.** Candidates are each item's covered texels, ordered by distance in 3D (the atlas) or in the unfolded plane (the ramps). Each candidate's class must be one of the non-zero one-hot slots.
- **Choice.** The decoder takes the fewest taps that reproduce the 15 one-hot and code scalars to 2·10⁻⁷ with positive weights.
- **Code collisions.** The codes repeat every 255 columns and 390 rows, and that put a wrong tap on 6 ramp texels. Where two decodes fit equally, the one with the nearer taps is kept.

**Bit-exactness** means all 24 output channels equal Painter's float32 bits after decision 206's output rounding: float32, then the 2⁻²⁴ grid with ties to even.

Everything ran on the CPU, from the private store: no Painter, no GPU, no writes to Assets3D, within the 2-hour box. The scripts stay in private scratch (`pad268/`), because they read oracle values.

## Findings

### 1. The fractions are 1/d shares, quantised level by level to 10, 8 and 6 bits

Two observations led here.
- **The largest weight is always a multiple of 1/1364.** It equals round(1364·s), where s is that tap's exact 1/d share. This holds on all 424 multi-tap ring texels of `atlas-512`. Examples: 2397/4092 for side plus diagonal, and 1512/4092 = 0.36950147 for the r2-p0 far tap.
- **The other taps follow fixed grids.** Within the remaining taps, the next share is always (255 + 2k)/765 (272 of 272), and the one after it is always (63 + k)/126 (40 of 40).

Those three grids are the UNORM codes of a share that is known to be at least 1/n:

**The weight rule.**
1. Sort the taps by their exact 1/d share, largest first. n ≤ 4 taps.
2. Read d in the unfolded plane, in the ring texel's own texel units (finding 4).
3. Code levels ℓ = 1, 2, 3 have (k, L) = (4, 1023), (3, 255) and (2, 63): 10, 8 and 6 bits.
4. At level ℓ, let σ be tap ℓ's 1/d share among taps ℓ…n.
5. Quantise it: u = round((σ − 1/k)·k/(k − 1)·L), clamped to [0, L], and t_ℓ = 1/k + (k − 1)/k · u/L.
6. The last tap takes whatever weight remains.

The 10 + 8 + 6 = 24 bits look like a packed per-texel weight word. This is a reading of the arithmetic only, not a claim about how Painter is built.

**The rule explains every earlier "not 1/d" constant:**

| Earlier finding | Its value | This rule |
|---|---|---|
| Side + diagonal, decision 269 (0x3ED41506) | 0.41422290 | 1 − 799/1364 |
| Straight edge, decision 269 (0x3EFFAA54, 0x3ED41505) | 0.49934640, 0.41422287 | 1 − 383/765, then 565/1364 |
| The L, decision 269 (0x3ED37E28, 0x3EBD2F4C) | 0.41307187, 0.36950147 | 1 − 449/765, then 504/1364 |
| The straight-edge along shift, decisions 206 and 217 (about 25·2⁻¹⁵, read as 1/(1 + e) with e ≈ 1/384) | — | The two diagonals tie at σ = 1/2, which codes 383 against 382 (of 765). The shift is (1/765)·(799/1364) = 25.1·2⁻¹⁵ |
| The corner fraction f, decision 206 | 0.4142245 | The side-plus-diagonal share, 565/1364, seen through a 2-tap centroid |
| The r2-p25 B tied far taps, decision 265 | weights 1.0046 apart | One of the pair codes at level 2 and the other takes the rest |

**Which of two tied taps leads** is only the order of the sort. The shares are equal, so the order comes from rounding: this is decision 261's sign. This pass let the order be free, and did not test the comparator.

### 2. The value is a float32 FMA lerp chain from the inside out

Let v₁…vₙ be the taps in sorted order.
- **The innermost pair:** m = fma(fl(1 − t_{n−1}), v_n − v_{n−1}, v_{n−1}).
- **Each outer level,** for ℓ = n − 2 down to 1: m = fma(t_ℓ, v_ℓ − m, m).
- **Constants.** Each t_ℓ is the float32 nearest to the rational above, and fl(1 − t) is a float32 subtraction.
- **Output:** decision 206's rounding.
- **One tap at distance 0** (ratio-1 seams) is a copy.

This is decision 269's chain, with its fractions now generated rather than tabulated.

### 3. Exact counts

The counts take the decoded taps. Only the order of exactly tied shares is left free.

| Probe | Ring texels | Bit-exact, all 24 channels |
|---|---|---|
| `atlas-512`: all 29 flat items (rows, columns, pairs, gaps, blocks, diamond, the 8 flat seam items) | 655 | **655** |
| `atlas-1024` | 655 | **655** |
| `atlas-2048` | 655 | **655** |
| `atlas-1024-moved` | 655 | **655** |
| `atlas-512`: the 3 folded seam items, with d in the unfolded plane | 104 | **104** |
| `ramp-r1-p0` (both seam rings, corners included) | 516 | **516** |
| `ramp-r2-p0` | 388 | **388** |
| `ramp-r2-p25` | 388 | **387** (1 corner not decoded) |
| `ramp-r15-p0` | 644 | **644** |
| `ramp-r15-p25` | 644 | **644** |

**About the counts:**
- The seam items alone are 228 texels per atlas probe.
- The one-hot weights are identical at 512, 1024 and 2048, so the rule does not depend on resolution.
- On the moved atlas, 30 texels change. Each is a swapped tie or a corner tap set, never a fraction.
- The folded seams need the unfolded distance: d measured in 3D from the ring point extended in its own plane gives only 74 of 104.

### 4. Tap selection: the 4 nearest by unfolded distance, except the far window on r15-p25 B

The tap set was predicted from the ramp geometry (`seam-ramp-*.obj` affine maps, unfolded world x and z):
- **Candidates:** the own covered 8-neighbours, plus the far island's covered texels;
- **Taps:** the 4 nearest by unfolded distance;
- **Copy:** a far texel at distance 0 is copied.

Interior seam-ring texels:

| Probe, ring | Interior texels | Set exact, any far texel allowed | Set exact, far texels limited to decision 262's along-seam strip |
|---|---|---|---|
| r1-p0 A and B | 512 | 512 | 512 |
| r2-p0 A | 256 | 255 | 254 |
| r2-p0 B | 128 | 128 | 128 |
| r2-p25 A | 256 | 141 + 115 tied 4th slot | 141 + 115 tied |
| r2-p25 B | 128 | 128 | 128 |
| r15-p0 A | 384 | 384 | 384 |
| r15-p0 B | 256 | 256 | 256 |
| r15-p25 A | 384 | 279 + 105 tied 4th slot | 279 + 105 tied |
| r15-p25 B | 256 | 127 | 129 |

**What the misses are:**
- **"Tied 4th slot".** Two own diagonals tie for the last place, and Painter keeps one of them. This is decision 262's 361 + 20 rows, ordered by the sign.
- **r15-p25 B.** It is decision 262's 127 texels again. In alternate rows, Painter keeps a far texel 1.225 far texels along the seam from the far point and drops one at 1.275. No along-seam window, across-seam window or 2×2 far footprint separates the two halves.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open. `src/export/padding.h` keeps decision 223's coverage-only rule, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes.
2. **Identified, for the integration (decisions 267 and 269 use the same arithmetic):**
   - **The ring value** is the FMA lerp chain of finding 2 over at most 4 taps, then decision 206's output rounding.
   - **The fractions** are the taps' exact 1/d shares, sorted and quantised level by level to 10, 8 and 6 bits (finding 1). Seams measure d in the unfolded plane, folds included.
   - **The counts:** bit-exact on every decoded seam-ring texel of the 9 probes (finding 3), given the taps and the order of tied shares.
   - This resolves decision 269 open items (a) and (c), and decision 262/265 open item (a), the seam weight asymmetry.
3. **Rejected:** any kernel whose weights are a smooth function of distance. The deviations from 1/d are the UNORM quantisation and nothing else.
4. **Still open:**
   - **(a)** The order of exactly tied shares: decision 261's comparator, tested here on no texel. It decides which tied tap leads on 254 + 128 interior texels of r2-p0 (A, B), 127 + 128 of r2-p25, and the 220 tied 4th slots of finding 4.
   - **(b)** The far-tap window on r15-p25 B: 127 or 129 of 256 texels, depending on the rule.
   - **(c)** The rounding of u at an exact half. No such texel was seen.
   - **(d)** Seams of `sphere-256` and `bevelled-cube-256`, and seams that end at cube corners. None was decoded here.
5. **No new recording is requested.** The next step is offline: run decision 261's comparator over the tied shares of this pass's texels, and find the r15-p25 B window. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- The seam ring is exact once the taps and the tie order are known, and decisions 267 and 269 share the same generated fractions. Item 2.7 waits on the tie order and the r15-p25 B window. It no longer waits on the weights.
- **Later fits need only decode taps and order.** Any recorded ring texel can be predicted from its taps' unfolded distances, so further kernel-shape fitting is unneeded.
- These need no retesting: smooth kernels, query-point shifts, power laws and float32 distance rounding as weight sources (decisions 262, 265, 269).
