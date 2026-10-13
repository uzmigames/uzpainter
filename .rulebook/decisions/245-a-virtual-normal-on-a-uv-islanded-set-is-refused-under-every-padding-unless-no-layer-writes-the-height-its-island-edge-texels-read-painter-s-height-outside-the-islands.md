# 245. A virtual normal on a UV-islanded set is refused under every padding unless no layer writes the Height: its island-edge texels read Painter's Height outside the islands

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase3.2_unreal-ue56-packed-preset

## Context

The practical end-to-end run (`parity/reports/phase2/practical-e2e.md`, B18) found that on a real mesh no export holding the Normal map could be produced. It ran on main `959b16a`, before decision 223. On main `170028e` the refusals of a file reading `virtualMap Normal_OpenGL` on a texture set whose UV islands do not cover the tile are:

| Padding | Check | Result on main |
|---|---|---|
| `passthrough` | `CheckPadding`: a meshMap or virtualMap source outside the islands | refused, "not recorded (R-090)" |
| `infinite` | none since decision 223 | **written** |
| `color`, `transparent`, `diffusion` | `CheckProcessing`: dilation not fitted | refused, every map |
| any `sizeLog2` other than the set's | `CheckProcessing`: resize partly fitted | refused, every map |

Decision 223's own Wand run had found the Normal's covered texels wrong at the island edge (1,071 texels, 2,499 values, max 537 codes). So since decision 223 the pipeline's `infinite` export writes a Normal map whose covered texels are known to differ from Painter's, with no refusal.

## Measurements

All of them are on the CPU, from the private store, with counts only (scratch `e2efix/b18-normal-export`). UzPainter's evaluated `Normal_OpenGL` (`uzp-export-tests files`, the 16-bit write rule, no padding) is compared with Painter's r1. The interior is the covered texels whose 8 neighbours are all covered. The edge is the covered texels with an uncovered 8-neighbour.

| Golden | Interior differing | Edge differing / edge texels | Painter r1 vs r2 on the edge |
|---|---|---|---|
| `export-padding` (islands, Height and Normal channel from bitmaps, no mesh map), all 46 PNG 16 steps | 0 / 26,870 | 445 / 1,452 in every step | 0 |
| `export-padding`, the 8 OpenEXR 32f steps | 0 | 451 / 1,452 | 0 |
| `height-normal-sphere` (Sharp) | 0 / 59,264 | 592 / 2,176 | 0 |
| `height-normal-bevelled-cube` (Sharp) | 0 / 51,040 | 1,154 / 2,296 | 0 |
| `height-normal-sobel-sphere` | 0 | 1,569 / 2,176 | 0 |
| `height-normal-sobel-bevelled-cube` | 0 | 2,296 / 2,296 | 0 |
| Wand v1 (decision 223) | 0 | 1,071 | 0 |

- **Painter's covered texels do not depend on the padding.** On `export-padding`, Painter's `Normal_OpenGL` covered texels are identical in all 46 PNG 16 steps: `passthrough`, `infinite`, and `color`, `transparent` and `diffusion` at dilations 0 to 64. The edge reads some Height outside the islands that is fixed before the export pads anything.
- **It is not the evaluated Height.** UzPainter evaluates layers over the whole tile, so its stencil reads the layers' values there. Even edge texels whose 3 x 3 evaluated Height is constant differ: 1 of 303 on `export-padding`, 405 of 750 on the cube. Painter's Height outside the islands is made from farther texels, and it is not identified.
- **Why the fits missed it.** The height-to-normal fits (decisions 064, 065) compare the sphere and the cube "on the UV coverage eroded by one texel". That is exactly the interior; the edge was never evidence.
- **`passthrough` outside the islands.** Painter's virtual normal there differs between r1 and r2 on 37,095 of 37,214 uncovered texels (`export-padding`, no mesh map), as document maps do (decision 032). No recording shows it with a bound mesh map or with a Height that has no layer.
- **No recording has an islanded mesh with an empty Height and a virtual normal.** None of the goldens above holds a Height of exactly 0 anywhere.

## Panel

The dossier (measurements and claims C1-C6) went to `cx/gpt-6-astra`, `kimi/kimi-k3` and `xai/grok-4.5` in one round.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The `infinite` admission with Height layers is a decision-001 bug; refuse before writing, even though it blocks the Wand's whole five-map export | AGREE | AGREE | AGREE |
| C2 Refuse under every padding, the edge being padding-independent | AGREE | PARTLY (wording; the conclusion stands) | AGREE |
| C3 Keep a Height with no layer admitted: a deduction from the fits, not a new fit | DISAGREE (not proven; refuse until recorded) | PARTLY (admit, marked as a deduction, tracked under 2.7, "contributes" defined structurally) | AGREE |
| C4 Decide it structurally, before evaluation | PARTLY | AGREE (define contribution precisely) | AGREE |
| C5 A uniform non-zero Height stays refused | AGREE | AGREE | AGREE |
| C6 No partial export: one refused map refuses the export | AGREE | AGREE | AGREE |

## Decision

1. **New refusal** (`src/export/padding.h` `CheckIslandNormal`, called by `EncodeExport` step 1 before `CheckPadding`).
   - Scope: a file reading `Normal_OpenGL` or `Normal_DirectX` on a texture set whose UV coverage is incomplete, under every padding.
   - It is refused with `NotYetSupported` before anything is evaluated or written. The message names the cause (the island-edge texels read Painter's Height outside the islands, which is not reproduced) and the owner (`phase1.25_pilot-wand` item 2.7, decision 245).
   - On the Wand, the pipeline's pinned five-map `infinite` export is refused as a whole, and nothing is written (C6). Before, it wrote four exact maps and a Normal that was wrong on 1,071 covered texels. Its four document maps export with `passthrough`, or without the Normal under `infinite` (EXC-007).
2. **Kept admitted: a Height with no layer** (C3, 2 of 3; Kimi's conditions taken).
   - The condition is structural (evaluator `FlatZeroHeight`): the stack has no Height channel, or the Height DAG's root list is empty (no visible layer has Height active) and the channel's base is 0. All 26 shipped templates have a Height base of 0.
   - A layer with Height active counts as writing the Height, even with a 0 source or a 0 mask. That case is refused.
   - The basis is a deduction, not a recording. The stencil then reads 0 on every texel. Painter's Height outside the islands is made from the covered texels or from the empty channel's base, and every mean, blend or copy of exact zeros is exactly 0. Interior texels, the mesh map and the Normal channel are per-texel fits.
   - The recording that settles it, owned by `phase1.25_pilot-wand` item 2.7: an islanded mesh (the Tier 0 sphere) with no Height layer, a Normal channel fill and a bound 16-bit Normal mesh map, exporting `Normal_OpenGL` at PNG 16 and OpenEXR 32f with `infinite` and `passthrough`, recorded r1 and r2.
3. **A uniform non-zero Height stays refused** (C5). Painter's mean of equal non-zero values is not shown to return the value bit for bit.
4. **`passthrough` of a meshMap or virtualMap outside the islands stays refused** (decision 090). Its message names what R-090 records and the owner, `phase1.25_pilot-wand` item 2.7. With Height layers, the island-edge refusal comes first.
5. **Dilation paddings and resize stay refused** (decision 103). Their messages gain their owner, `phase3.2_unreal-ue56-packed-preset`. The resize message also says what is not reproduced, virtual normals after a downscale among them.
6. **Evidence in the tests.**
   - `tests/export/test_export_encoders.py::test_virtual_normal_on_islands` (CPU, every lane): the refusals, and the written flat normal.
   - `::test_island_edge_normals_differ_from_painter` (Tier 0): interior 0 differing, edge differing with r1 = r2, and Painter's covered texels the same under every padding. When an exact Height outside the islands lifts this refusal, that test is the one to turn around.

## Alternatives Considered

- **Keep writing the Normal under `infinite`, and let the Tier 1 verdict fail.** Rejected: decision 001 refuses before writing anything not exact, and EXC-007 must not cover covered texels (decision 223).
- **Refuse every virtual normal on islanded sets, an empty Height included** (GPT). Rejected by majority. It would block the common case of a baked normal with no height painting, where nothing contradicts exactness. The deduction is recorded as such, with the recording that settles it.
- **Write the four exact maps and skip the Normal.** Rejected 3 of 3: an export with a refused map is refused whole.
- **Test the evaluated Height for zeros after evaluation.** Rejected: the refusal would come after the work, and the test would depend on values. The structural rule decides before evaluation.

## Consequences

- B18 is answered. No refusal on the Normal path refuses something exact by the existing fits. One missing refusal, a virtual normal with Height layers under `infinite`, is added. The Normal of a stack without Height layers exports under `infinite`.
- The Wand's Tier 1 run now reports the export as refused (`capability_gap` over MCP), not as a failed comparison. Item 2.7 owns both the Height outside the islands and the island padding. G1 still waits on it.
- `parity/semantics/export-processing.json` keeps `padding-islands` as a gap.
