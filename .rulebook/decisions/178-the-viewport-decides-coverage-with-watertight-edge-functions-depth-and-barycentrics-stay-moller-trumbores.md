# 178. The viewport decides coverage with watertight edge functions; depth and barycentrics stay Möller-Trumbore's

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_preview-viewport-window, phase2.3_realtime-preview, phase2.2_preview-capture

## Context

Decision 163 found that perspective rays of the `painter_viewport` pass are not watertight. On the 20 × 20 plane seen from above at 64 × 64, five pixels on the two triangles' shared diagonal (row + column = 63) show the background.

The root cause is the hit test. The pass decided coverage with binary32 Möller-Trumbore: `u = dot(tv, pv) / det`, `v = dot(dir, qv) / det`, then `u < 0`, `v < 0` and `u + v > 1` reject. Each triangle computes its own `u` and `v` from its own edges and corner, with several roundings. Nothing ties the value one triangle computes for the shared edge to the value its neighbour computes. A ray through that edge can therefore come out at `u + v` just above 1 in one triangle and at a coordinate just below 0 in the other, and both reject it. The binning is not involved: each triangle's tiles are its projected bounds grown by one pixel. The orthographic rays of decision 163 happen to have no such hole on this fixture.

The viewport regression goldens (`tests/preview/viewport-goldens.json`) are UzPainter's own repeatability check, keyed by kernel, adapter and driver. They are never Painter parity evidence (decisions 018, 148).

## Decision

1. **Coverage.** The pass decides whether a triangle covers a ray with the watertight test of Woop, Benthin and Wald (2013).
   - Per ray: kz is the axis of the ray's largest component, kx and ky follow it cyclically, and the shear is `dir[kx] / dir[kz]`, `dir[ky] / dir[kz]`.
   - Per triangle: each corner relative to the ray origin is sheared to `x = r[kx] − shear_x · r[kz]`, `y = r[ky] − shear_y · r[kz]`. The three edge functions are the 2D cross products `x_i · y_j − y_i · x_j` of the sheared corners.
   - The triangle covers the ray when no edge function is negative or none is positive, because both faces are visible. A triangle whose three edge functions are zero is seen edge-on and covers nothing.
2. **Why this is watertight.** A corner shared by two triangles is sheared to the same binary32 values in both, since the shear depends only on the ray. Rounding is monotone, so `fl(fl(a·b) − fl(c·d))` either has the sign of the exact `a·b − c·d` of those values or is zero. A ray strictly inside a triangle of the sheared corners therefore never sees a negative and a positive edge function, and a ray on a shared edge sees zero there in both triangles. No ray through a shared edge or corner misses both sides. The edge functions are `precise` so the compiler cannot contract them into a fused multiply-add, which would break that argument. The kernels are also built with `-Gis`.
3. **Depth and shading unchanged.** For a covering triangle, the depth `t` and the barycentrics `u`, `v` are still Möller-Trumbore's, with the same `det == 0` and `t > 0` rejections. Only its range rejections on `u` and `v` are removed; the edge functions replace them. On the former cracks `u + v` may exceed 1 or a coordinate may be below 0 by rounding, and interpolating with those weights is harmless. Every pixel the old test already hit keeps its triangle, depth and barycentrics, so its colour is bit-identical. The nearest hit still wins, the lowest index on a tie, so a ray on the shared edge that both triangles now cover takes the nearer one.
4. **Goldens re-keyed with every image unchanged.** The kernel source changed, so its key did: `51810c8132b4cdc5` (CRLF checkout) and `115b8b6f3f2579a9` (LF `viewport.hlsl`, the variant the file already held). The new kernel renders the sphere, plane and bevelled-cube goldens at 256 × 256 with display and linear hashes equal to those under the previous kernels `3f173b7573f95bba` and `91bc3285269b6519`. A pixel-by-pixel comparison of both renders' display codes and linear binary16 values found 0 changed pixels in each of the three. The golden cameras do not put a pixel centre on a shared edge, so they had no crack to close. The old entries were removed.
5. **The crack scene.** `test_orthographic_capture_casts_parallel_rays` now requires the perspective view of the plane to be solid, rows and columns 14-49, as it already required of the orthographic views.
   - Under the previous kernel that check fails.
   - The test's eight captures were compared pixel by pixel, PNG display codes and OpenEXR linear values, under both kernels. Seven are identical. The perspective capture differs in exactly five pixels, (row, column) (16, 47), (20, 43), (32, 31), (33, 30) and (46, 17), all on the diagonal row + column = 63. Each showed the clear colour before and shows the plane now.

## Alternatives Considered

- **A tolerance on `u`, `v` (an epsilon).** Rejected: it hides the hole only for rays near enough to the edge, and it makes neighbours overlap by an arbitrary margin.
- **Woop's test for depth and barycentrics too.** Rejected for this fix: it would move the shading of most pixels by rounding, so a fix of five pixels would change thousands, and the goldens could no longer show that nothing else moved.
- **Woop's double-precision recomputation when an edge function is zero.** Not needed: a zero only adds coverage on an edge, which the nearest-hit rule resolves, and it would need 64-bit float support in the kernel.

## Consequences

- Perspective and orthographic coverage are watertight on every mesh whose triangles share corners.
- The regression goldens hold only the two new keys. Their image hashes are unchanged.
- Decision 163's note that the fix would change the perspective goldens did not hold: no golden image changed.
