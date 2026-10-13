# 245. A virtual normal on a UV-islanded set is refused in every export and diagnostic: its island-edge texels read Painter's Height outside the islands

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase3.2_unreal-ue56-packed-preset, phase2.1_recipe-diagnostic-views

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

C3 passed 2 to 1 and was first adopted. The review withdrew it (§2 below): the panel cannot stand in for the evidence decision 001 requires.

## Decision

1. **New refusal** (`src/export/padding.h` `CheckIslandNormal`, called by `EncodeExport` step 1 before `CheckPadding`).
   - Scope: a file reading `Normal_OpenGL` or `Normal_DirectX`, or a diagnosticMap that isolates, compares or summarises one (`isolated/`, `contribution/`, `regionStats/` of either), on a texture set whose UV coverage is incomplete, under every padding. A `regionStats` file has no padding, but its statistics read the island-edge texels, so the export reads the coverage for it too, and its receipt lists the mesh.
   - It is refused with `NotYetSupported` before anything is evaluated or written. The message names the cause (the island-edge texels read Painter's Height outside the islands, which is not reproduced), the evidence (recording R-090), the empty-Height case and the owner (`phase1.25_pilot-wand` item 2.7, decision 245).
   - `uzpainter.diagnostics` and the worker's Diagnostics tools refuse the same views in memory before evaluating (`DiagnosticRun::RequireExact`, `exporter::IslandNormalRefusal`): `isolate`, `contribution` and `region_stats` of `Normal_OpenGL` or `Normal_DirectX` raise `NotYetSupported`. Each view equals the export of its source (decision 136), so it is refused where that export is. Without a texturing mesh there are no UV islands and nothing is refused.
   - On the Wand, the pipeline's pinned five-map `infinite` export is refused as a whole, and nothing is written (C6). Before, it wrote four exact maps and a Normal that was wrong on 1,071 covered texels. Its four document maps export with `passthrough`, or without the Normal under `infinite` (EXC-007).
2. **A Height with no layer is refused too** (C3 withdrawn after review).
   - First adopted by the panel's majority as a deduction: the stencil reads 0 everywhere, and Painter's Height outside the islands, made from the covered texels or the empty channel's base, would be 0 too.
   - The review found the deduction's premise contradicted by a recording. `parity/semantics/virtual-maps.json` (R-092, decision 092) records that Painter's other virtual maps read an empty channel as a constant that is not its base: L = 1.3, r = 0.5980393 and m = 0 where the channel has no layer. Painter's empty Height inside the virtual normal may likewise read a non-zero constant, or one that differs inside and outside the islands. A uniform non-zero Height is refused for that reason (C5), so the exemption contradicted C5.
   - No golden holds evidence for it: none has an island-edge texel whose Height window is 0, at radius 2, 4 or 8 (scratch `zero_windows.log`).
   - Decision 001 admits only what a recording shows exact. A majority vote is not that evidence, so GPT's position holds and the exemption (evaluator `FlatZeroHeight`) is removed.
   - The recording that would lift this case, owned by `phase1.25_pilot-wand` item 2.7: an islanded mesh (the Tier 0 sphere) with no Height layer, a Normal channel fill and a bound 16-bit Normal mesh map, exporting `Normal_OpenGL` at PNG 16 and OpenEXR 32f with `infinite` and `passthrough`, recorded r1 and r2.
3. **A uniform non-zero Height stays refused** (C5). Painter's mean of equal non-zero values is not shown to return the value bit for bit.
4. **`passthrough` of a meshMap or virtualMap outside the islands stays refused** (decision 090). Its message names what R-090 records and the owner, `phase1.25_pilot-wand` item 2.7. For a virtual normal, the island-edge refusal comes first.
5. **Dilation paddings and resize stay refused** (decision 103). Their messages gain their owner, `phase3.2_unreal-ue56-packed-preset`. The resize message also says what is not reproduced, virtual normals after a downscale among them.
6. **Evidence in the tests.**
   - `tests/export/test_export_encoders.py::test_virtual_normal_on_islands` (CPU, every lane): on the sphere, every virtualMap and diagnosticMap source of a virtual normal refused under `infinite` and `passthrough`, with and without a Height layer, nothing written; the pipeline's five-map export refused whole; on the grid (complete coverage) the same sources written.
   - `tests/python/test_pyapi_diagnostics.py::test_a_virtual_normal_on_uv_islands_is_refused_per_source` (CPU): `isolate`, `contribution` and `region_stats` of the virtual normals refused on the sphere, with and without a Height layer, the revision unchanged; returned on the plane.
   - `::test_island_edge_normals_differ_from_painter` (Tier 0): interior 0 differing, edge differing with r1 = r2, and Painter's covered texels the same under every padding. When an exact Height outside the islands lifts this refusal, that test is the one to turn around.

## Alternatives Considered

- **Keep writing the Normal under `infinite`, and let the Tier 1 verdict fail.** Rejected: decision 001 refuses before writing anything not exact, and EXC-007 must not cover covered texels (decision 223).
- **Admit a Height with no layer as a deduction** (C3, Grok and Kimi). Adopted first, then withdrawn after review (§2): R-092 shows Painter reading empty channels as non-base constants in its virtual maps, and no recording shows the case. It blocks the common case of a baked normal with no height painting until the recording in §2 is made.
- **Refuse the in-memory diagnostics only in the evaluator** (`EvaluateMapOn`). Rejected: the preview and the render captures evaluate the same virtual normal, and their parity is the render's (decision 038), not the export's. The guard follows decision 126's pattern: an exporter function the export and `uzpainter.diagnostics` both apply.
- **Write the four exact maps and skip the Normal.** Rejected 3 of 3: an export with a refused map is refused whole.
- **Test the evaluated Height for zeros after evaluation.** Rejected: the refusal would come after the work, and the test would depend on values. Since §2 no Height case is admitted, so the refusal reads only the coverage, before evaluation.

## Consequences

- B18 is answered. No refusal on the Normal path refuses something a recording shows exact. The missing refusals are added: a virtual normal on an islanded set under `infinite`, and the diagnostic views and diagnosticMap files of one. On an islanded set no Normal map exports, with Height layers or without, until item 2.7 gives the Height outside the islands or the recording in §2 is made. The e2e `bracal` stack (no Height layer, a bound Normal mesh map) is refused too.
- The Wand's Tier 1 run now reports the export as refused (`capability_gap` over MCP), not as a failed comparison. Item 2.7 owns both the Height outside the islands and the island padding. G1 still waits on it.
- `parity/semantics/export-processing.json` keeps `padding-islands` as a gap.
