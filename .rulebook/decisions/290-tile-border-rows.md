# 290. The sphere's tile-border rows: decision 270's 1–8 ulp texels are a reversed tap order, a u-border seam edge opens no window, a clamped window base finds the bottom-row taps, and the 54 corner gutter texels were a ring artefact; three window selectors stay open

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine

## Context

After decision 288, `export-padding-sphere` and its probe `sphere-256` are left with 164 ring misses on rows 0, 1, 254 and 255: decision 270's open border-row item. Decision 270 had seen 32 two-tap texels on row 255 with the right weight code but 1 to 8 ulps off, and no chain form fixed them. Decision 285 left the sphere's 54 tile-corner gutter texels open, because they matched no seed.

**Method.**
- CPU only (numpy). No Painter, no GPU, no `src/` change. The scripts read oracle values, so they stay in private scratch (`pad290/`). Only counts are recorded here.
- **The kernel ("before")** is decision 288's (`h1+eq7+weld+skiptau+ownraw`). It reproduces decision 288's cached rows texel for texel: 2,176 ring texels, 1,978 exact (Height and 24-channel probe).
- **Painter's taps** come from decision 270's decode. On top of it:
  - Painter's level-0 fraction t is read straight off the one-hot slots, since a = 1 and b = 0 make the chain exact;
  - for 3–4-tap texels with shared slots, the tap sets were brute-forced over the covered texels in Painter's nonzero slots.
- **Holdout.** Every rule was scored per texel on decision 280's 16 probes, and on the `export-padding` and `export-padding-bevelled-cube` goldens.

## Findings

### 1. The 164 texels by class

The pole apex sits on the tile edge (v = 0 and v = 1), so the border rows are the apex rows. Pole segment i covers columns 8i to 8i + 8.

| Class | Texels | What Painter does |
|---|---|---|
| **E**: south (8i + 1, 255) | 32 | Our taps, in the reversed order (§2) |
| **D**: south (8i, 255), i ≥ 1 | 31 | Adds a third tap (8i − 8, 254), which lies outside our window's rows (§4) |
| **C**: south (8i + 1, 254) | 32 + 1 | Drops the far tap from the window across τ's vertical edge, at reach 1.5. It takes the own tap (8i, 253) as the fourth tap instead (§5) |
| **A**: north (8i + 8, 0) | 31 | Drops both taps of the window across τ's vertical edge, so 2 taps instead of 4 (§6) |
| **B**: north (8i + 7, 0), undecoded by decision 270 | 32 | Now decoded: our taps without that same window's tap, [(8i − 1, 1), (8i + 7, 1), (8i − 1, 2)] (§6) |
| Cross-border singletons: (0, 0), (0, 1), (255, 254), (255, 255) | 4 | Undecoded. Their own neighbours lie only across the x border |
| Other row-0 or row-255 tap sets | 1 | (247, 255) |

With decision 288's ring point q and the raw 3D distance, Painter's decoded weights are reproduced on every decoded miss. So q and the distances are right. Only the tap set and, on E, the order differ.

### 2. Decision 270's 1–8 ulps: the own tap is put first

**What Painter computes.** Painter's t on the 32 E texels is 0.5315249, 1 ulp below fl(2175/4092) = 0.53152496, which is code 384's value.

**No other formula explains it.**
- **The other 2-tap texels.** All 133–134 decoded 2-tap atlas texels and the 62 other 2-tap sphere texels take t on the exact rational grid.
- **Code-to-t formulas.** Twenty-one float32 formulas were tried, among them s = u/1023 then 1/4 + 3/4·s, fma and lerp forms, and the reciprocal. None fits every code, and code 449 takes two different values on different atlas texels.
- **3-tap chains.** No 3-tap chain over the two taps, in any order and with any codes, fits. Nor does one with (248, 254) as a third tap.

**What fits.** The chain [own, far] is exact on all 24 channels and on the Height:
- the own tap (8i, 254) goes first, with the smaller share (0.4687, code 298, t = fl(1917/4092));
- then the far tap (8i + 8, 254), whose share is larger.

The rational weights are the same either way. Only the float32 rounding of 1 − fl(1917/4092) differs from fl(2175/4092), and that gives the 1–8 ulps.

**The selector is open.** The order is not a distance order:
- **The gap is large.** The far tap is 12 % nearer (0.1198 against 0.1358) by raw distance, by unfolded distance and by decision 280's comparator.
- **Own-first is not general.** The 1,502 other mixed texels need the far tap first, as do the 61 atlas 2-tap texels.
- **The mirror texels disagree.** The north mirror texels (8i + 6, 0) are the same geometry mirrored in u and flipped in v, and they need the far tap first.
- **Other order keys.** Ordering far taps by the own-triangle extrapolation fails 1,471 texels.

### 3. A seam edge on the tile's u border opens no window (rule)

**What the decode shows.**
- **South.** No ring texel at x ≤ 8 takes a tap at x ≥ 248. Ring texels at x ≥ 248 do take taps at x ≤ 1 (for example (249, 255) and (248, 255)).
- **North.** It is the other way round: x ≤ 8 takes x ≥ 248, never the reverse.

**Where the seam is crossed.** In both poles, Painter crosses the u = 0 | 1 seam only from the side whose edge is a slanted spoke. It never crosses from the side whose seam edge lies on u = 0 or u = 1.

**The rule.** A seam edge whose two UV ends both lie on the tile's left or right border opens no window.

**Counts.**
- Sphere: +2 texels ((1, 254) and (255, 0)), none lost.
- The 16 holdout probes, `export-padding` and the cube: 0 texels change.

### 4. Class D: the window base clamped to the image finds the bottom-row taps, but is not adopted alone

**Why our window misses the tap.** For (8i, 255), the window across τ's vertical edge folds q to f = (8i − 7.27, 255.538). Decision 275's rows are then 255 to 257, so row 254 falls outside the window, and Painter takes a tap from row 254.

**The clamp.** Clamp f to [½, N − ½] before the window base, which is the same as clamping the base b = floor(f − ½) to the image, the way a clamp-to-edge bilinear footprint is clamped.

**What it gains.**
- With §3 it adds 42 texels: the 31 D texels, (247, 253..255), (248, 255), the seam column (250..255, 241..251) and (255, 0). It loses (8, 2).
- On the 16 holdout probes it changes 0 texels, and none on `export-padding` or the cube.

**Why it is not adopted alone.** The same clamp opens the reach-1.5 inside window (§5) at the 32 E texels. That adds (8i − 8, 254) there as a third tap, which Painter does not take. Their exported Height was right and becomes wrong.

**End to end (decision 288's check), before → with the clamp and §3:**

| Golden | Covered Normal | Ring Normal | Gutter Normal | Height export, ring | Height export, gutter (decision 285's clamped flood) |
|---|---|---|---|---|---|
| `export-padding-sphere` | 61,395 → 61,399 | 2,002 → 2,012 | 1,685 → 1,697 | 2,010 → 2,020 | 1,799 → **1,742** |

- `export-padding` stays exact (28,322 covered, 1,387 ring). The cube is unchanged (53,141).
- So the clamp stays identified, not adopted, until §5's selector is known.

### 5. Class C and E: inside windows at reach 1.5 are not used; the selector is open

An **inside window** is one whose edge has the ring texel on τ's side, so q folds to beyond J's hinge.

**What Painter uses.**

| Window | Painter takes its taps? |
|---|---|
| South vertical-edge inside windows at reach 0.5 (D) | Yes, 31 of 31 |
| South vertical-edge inside windows at reach 1.5 (C and E) | No, 62 of 62 |
| North slanted inside windows at reach 1.12 | Yes, 31 of 31 |

**Rejected: a cap on inside windows.** A cap below 1.5 (1.2 or 1.4) gives the sphere +32 with no loss. But on the holdout it loses:
- 8 texels each on `atlas-512`, `-1024` and `-2048`;
- 7 (with 1 gained) on `-1024-moved`;
- 69 on `sweep-centred`.

So it is not the rule.

**Also rejected:**
- reach measured in 3D, or at the fold point;
- the distance from f to J;
- the side of the fold.

None of them separates the used and the unused windows.

### 6. Classes A and B: the north row 0 drops the window across τ's vertical edge

**What Painter drops.** On row 0, Painter takes no tap from the window across τ's vertical edge, whose spoke runs to the apex on the top border:
- 31 beyond-side windows (A);
- 32 inside windows (B).

**Not a reach or gate effect.**
- The same kind of window is used on row 1 (400 of 400) and on the south border (D).
- The gate's normal dot product is 0.9998, so the gate never closes these windows.
- The reach is 0.5.

**Not explained either:** the f clamp, mirrored or clamped row reads, and a window clamped inside the image. The selector is open.

### 7. The sphere's 54 corner gutter texels (decision 285 (e)): closed, not a new rule

**The cause.** The 54 texels are the gutter beside the 24 ring texels whose covered neighbours lie only across the x tile border: (0, 0..11) and (255, 244..255). Decision 285 counted them with a ring that does not wrap in x.

**What holds.** The reference's ring wraps x (`(x + dx) % W`) and contains those 24 texels. With it, decision 285's clamped flood, given Painter's own ring values, matches Painter on all 1,920 sphere gutter texels.

**Painter's q at those 24 texels.** Painter extrapolates the actual centre through τ, across the tile, about 12 cm away. Re-placing the texel at x ± W next to τ loses 8 texels that are exact today. So the reference stays as it is.

## Decision

1. **Recorded, not implemented.** No `src/`, test, semantics entry, capability, conformance case or exception changes. Item 2.7 stays open, and decisions 245's, 259's and R-090's refusals are unchanged.
2. **Identified for the ring kernel's integration:**
   - **(a)** A seam edge whose two UV ends both lie on u = 0 or both on u = 1 opens no window (§3). It is neutral on the holdout.
   - **(b)** Decision 270's row-255 ulp texels are explained: Painter's chain there is [own, far] (§2). No arithmetic change is needed. Only the order selector is missing.
   - **(c)** Decision 285 (e) is closed (§7). The x-wrapped ring and the clamped flood are complete on the sphere's gutter.
3. **Identified, not adopted:** the window base clamped to the image (§4). It fixes class D and is holdout-neutral, but it must come with the rule that closes §5's inside windows.
4. **Rejected:**
   - a cap on inside-window reach (§5);
   - own-first or own-triangle-extrapolation tap orders (§2);
   - other code-to-t formulas (§2);
   - mirrored or clamped window reads (§6);
   - re-placing cross-border ring texels at x ± W (§7).
5. **Still open on the sphere:**
   - the E order selector (32);
   - the inside-window selector (C, 33);
   - the north row-0 vertical-edge window (A and B, 63);
   - the 4 cross-border singletons;
   - (247, 255);
   - decision 288's 13 self-fold texels and its 21 other texels.
6. **No new recording is requested.**

## Alternatives Considered

- **A different float32 code-to-t decode.** Rejected: no formula fits every observed code, while the reversed order fits exactly (§2).
- **Closing inside windows by reach.** Rejected: it loses texels on the atlas and the sweep (§5).
- **Adopting the f clamp now.** Deferred: it costs 57 exported-Height gutter texels at the E texels until §5 is known (§4).

## Consequences

- **The sphere's border misses** are now characterised as three window selectors and one order selector, all at the pole apexes on the tile edge.
- **Rule (a)** can go into the reference and `padding.cpp` with decision 288's rules.
- **These need no retesting:**
  - other float32 decodes of the fraction codes;
  - 3-tap chains with duplicate taps at the border;
  - a ring point re-placed across the x border;
  - flood addressing variants for the sphere's gutter.
