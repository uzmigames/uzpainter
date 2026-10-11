# 64. The virtual normal maps reorient the height normal onto the flat base, then the Normal channel onto the result, from the pre-write Height read-out

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.12_compositor-height-normal

## Context

Decision 047 recorded Painter 12.1.5's two height-to-normal methods (`Sharp`, the default, and `Smooth (Sobel)`, per texture set, no strength setting) on the sphere, the bevelled cube and an amplitude sweep on a 4x2 plane grid (opacity 1, 0.75, 0.5, 0.25, 0.1; 2, 3, 4 copies in LinearDodge). The phase0.7 fit of the default method (backward differences, (-k dx, k dy, 1) with k = 2.56, one normalisation) left tens of texels per set one code off, attributed to GPU rounding. Measured in this task (counts of differing values over the sweep, `parity/semantics/height-to-normal.json`):

- The stencil reads the Height read-out **before** its L16F write: at opacity 0.75 and 0.1 the value q x half(opacity) is off the half grid, and only the unquantised float32 value reproduces the maps (the stored half, exported as Height, differs on 54 248 values at 0.75). Copies in LinearDodge read the per-layer-quantised accumulator (the stack's own rule).
- Sharp: v = (h(-1,0) - h(0,0), h(0,0) - h(0,-1), 0.390625). Sobel: v = (L - R, B - T, 3.125) with (1, 2, 1)-weighted columns and rows. Wrap-around at the texture borders.
- Combination: H = normalise(v); A = normalise(reoriented(F, H)) with F = (0, 0, 1); n = normalise(reoriented(A, decode(C))) with C the Normal channel; Normal_DirectX negates n.y before the encoding. With the fitted normal-map helpers of decision 053 (hardware rsqrt) this is exact on every r1 map of both methods, the older default-method goldens and every map of `blend-normal-channel`. One normalisation leaves 657 values off, reoriented(H, F) alone 359, the Normal channel as the first base 180-192 per set.
- An empty Normal channel exports float32(127/255) yet acts as exactly flat.
- The Normal channel stores an imported 16-bit normal map with its green inverted (blend-modes.json, recorded in an OpenGL project).
- After save and reopen (r2), opacity 0.75 and 0.1 differ from r1 for both methods; neither the reopened Height nor one opacity explains r2.

The model panel ruled on 2026-10-11 under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| Pre-write read-out for Height and Normal | PARTLY x3: proven for Height; for Normal unpinned (no partial coverage recorded). Keep one rule, mark the Normal side unobserved. |
| Stencils, fixed z, no strength; Sobel order unpinned | AGREE x1, PARTLY x2: pin one summation order as the implemented convention; constants recorded at 256 px only. |
| F is the mesh normal map slot | PARTLY x3: by elimination only (F flat makes the first step invisible); ship F flat, block a bound mesh map until recorded. |
| Empty channel flat via composite over (0.5, 0.5, 1) | AGREE x1, PARTLY x2: provisional rule, partial coverage to be recorded. |
| Green inversion of Normal imports; refuse DirectX | AGREE x2, PARTLY x1: recorded for 16-bit in OpenGL only; refuse DirectX. |
| r2 of 0.75 / 0.1 is not a target | AGREE x2, PARTLY x1: call it a save-and-reopen divergence, not recorder instability. |

## Decision

1. The virtual maps read the Height read-out before the channel's write rule, and the Normal channel's read-out composited over the flat colour (0.5, 0.5, 1) (one rule for the empty and the fully covered channel; partial coverage is a recorded hypothesis).
2. Sharp and Sobel are the stencils above with z = 0.390625 and 3.125 at 256 texels; the Sobel sums are (a + 2b) + c in float32, the implemented convention (the goldens do not separate orders). There is no strength parameter.
3. The combination is H, then reoriented onto the flat F, then the Normal channel reoriented onto the result, normalised with the recording GPU's rsqrt, encoded fma(n, 1/2, 1/2); DirectX negates n.y first.
4. Not recorded, refused with `evaluator:unsupported_source` until recorded: set resolutions other than 256, a bound Normal mesh map in the combined maps, a non-empty Normal channel or a Normal-channel bitmap in a DirectX project. 8-bit Normal imports invert green by analogy (listed).
5. r1 is the exact target of the plane-strength goldens; their r2 residuals are published as a save-and-reopen divergence and covered by a decision-032 exception entry.

## Alternatives Considered

- Model the empty channel as a special case and read the channel over its template base otherwise (rejected: two rules where one covers every recorded case; both stay open on partial coverage).
- Implement the decoded mesh normal map as F now (rejected by the panel: no recording places it).
- Scale z with the resolution (a UV-space gradient) (rejected: not recorded; refusal is explicit).

## Consequences

`src/evaluator/height_to_normal.{h,cpp}`, the float32 read-out (`EvaluateFloat32Readout`, a raw blend) and the `UZP_VNORMAL` kernel implement the model on CPU and GPU bit for bit. The published fit replaces the phase0.7 default-method fit. The recording requests are in `parity/reports/phase1/compositor-height-normal.md` §5.
