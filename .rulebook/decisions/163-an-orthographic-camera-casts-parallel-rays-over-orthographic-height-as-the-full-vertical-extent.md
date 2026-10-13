# 163. An orthographic camera casts parallel rays over `orthographic_height` as the full vertical extent

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.3_realtime-preview, phase2.2_preview-capture, phase2.1_preview-display-presets, phase3.4_path-tracer-transport

## Context

Decision 148 left an orthographic camera in a `painter_viewport` capture as a release gap owned by phase2.3_realtime-preview, because the pass cast perspective rays only (`NotYetSupported`). The Assets3D render standard frames its reference renders with an orthographic camera.

Painter's documented camera has `orthographic_height` ("the orthographic height of the camera"). How Painter maps it to the frame has not been recorded. The viewport is a preview, never parity evidence (decision 018), and `field_of_view` is already taken as the vertical angle by UzPainter's convention (decision 148).

The pass bins triangles on the CPU by their projected screen bounds into 16 × 16 tiles. Each pixel casts one ray against its tile and keeps the nearest hit with t > 0. Its regression goldens are keyed by the kernel source's hash, the adapter and the driver.

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| B1. Parallel rays; `orthographic_height` is the full vertical extent, the width is that times the aspect; a recorded convention | AGREE: test portrait and landscape | PARTLY: Blender's `ortho_scale` is the larger side under automatic sensor fit, so non-square conversions differ | PARTLY: the same Blender point |
| B2. Only hits in front of the eye plane; no near or far plane; the lens fields do not apply | AGREE: show that the lens fields leave the pixels unchanged | AGREE | AGREE |
| B3. Affine binning; triangles crossing the eye plane keep their bounds; triangles wholly behind are dropped | AGREE | AGREE | AGREE |
| B4. Perspective unchanged: digest keys only for orthographic captures; goldens re-keyed with the same image hashes | PARTLY: compare against the preserved old hashes | AGREE | AGREE |
| B5. No Painter recording | AGREE: geometric tests for framing, aspect, eye-plane crossing | AGREE | AGREE |

## Decision

1. **Projection.** An `Orthographic` camera record renders with parallel rays.
   - Every pixel's ray starts at its point on the plane through the camera's position, at `right·sx + up·sy`, and runs along the forward axis.
   - `orthographic_height` is the view's full vertical extent in scene units. The width is that height times the aspect.
   - This is UzPainter's convention, like the vertical field of view, and not a measured Painter fact. Square captures are the same under any reading of it.
2. **Visibility.** Only hits in front of that plane count (t > 0), as for perspective rays. No near or far plane is added, since Painter's are unrecorded. `field_of_view` and `focal_length` stay in the receipt's camera record but do not change an orthographic image.
3. **Binning.** The orthographic projection is affine, so a triangle crossing the camera's plane keeps its projected bounds. A triangle wholly behind it is dropped.
4. **Perspective unchanged.**
   - The frame buffer gains one word (projection). The receipt's resolved pose gains `projection` and `orthographic_height` for orthographic captures only, so perspective render-state digests are unchanged.
   - The regression goldens are re-keyed for the new kernel source: `3f173b7573f95bba` (CRLF checkout) and `91bc3285269b6519` (LF). Their sphere, plane and bevelled-cube images have the same display and linear hashes as under the previous kernel, so the perspective images are byte-identical.
5. **Blender conversion.** It is unchanged: `ortho_scale = orthographic_height`, as `angle = field_of_view`. Under Blender's automatic sensor fit, both name the larger side. A non-square Blender camera therefore frames differently from UzPainter's vertical convention, for both projections. The conversion carries no image size, and this is recorded, not corrected.
6. **Tests.** `test_orthographic_capture_casts_parallel_rays` renders the 20 × 20 plane fixture from above at `orthographic_height` 40. The plane covers exactly the pixels whose centres lie on it:
   - square: rows and columns 16-47;
   - landscape 96 × 64: rows 16-47, columns 32-63;
   - portrait 64 × 96: rows 24-71, columns 8-55.
   The test also checks that:
   - other lens fields give the same bytes;
   - a camera ten times farther gives the same coverage;
   - a camera under the plane sees only the background;
   - a camera tilted 45° on the plane sees the half in front, rows 21-31;
   - the perspective camera at the same place frames rows 14-49 by its vertical field of view. Only its bounds are compared, see Consequences.
7. **No recording.** None is requested: the viewport is never parity evidence. An orthographic parity render belongs to the path tracer (phase3.4 item 2.5).

## Alternatives Considered

- **`orthographic_height` as the larger side (Blender's automatic fit).** Rejected: the name says height, and it keeps one convention with the vertical field of view.
- **Converting `ortho_scale` with the aspect.** Rejected: a camera record carries no image size. Square captures, the standard's 1200 × 1200, are unaffected.

## Consequences

- `uzpainter.render.capture` renders orthographic cameras. The capability note no longer lists the gap.
- phase2.2's headless test no longer expects the orthographic refusal.
- Found while testing, and present before this decision (the perspective images are byte-identical): perspective rays are not watertight. On the plane seen from above, five pixels on the two triangles' shared diagonal (row + column = 63 at 64 × 64) show the background, because a ray along the shared edge misses both triangles in the binary32 Möller-Trumbore test. The orthographic images have no such hole. The fix changes the perspective goldens, so it needs an owner (the viewport pass of phase2.1_preview-viewport-window is merged); it is not made here.
