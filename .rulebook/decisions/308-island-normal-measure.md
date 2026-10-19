# 308. The diagnostic measure export computes the Normal on UV islands by Painter's recorded rule: the Wand's Normal goes from 1,071 covered, 6,334 ring and 3,679,663 gutter misses to 49, 78 and 51,515; production refusals unchanged

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.12_compositor-height-normal

## Context

Decision 286 added `UzPainter.exe run --diagnostic-measure-export`. On the Wand, that mode wrote the combined Normal as the evaluator gives it over the whole tile, then padded its stored values. Against Painter's r1:
- the four material maps had interior 0;
- the Normal had 1,071 covered misses, all at island-edge texels whose left or upper Sharp tap is uncovered (decision 263's cause);
- every Normal ring and gutter texel differed (decision 276).

The coordinator asked for the measure path, and only the measure path, to compute the Normal as decisions 263, 276, 285, 287 and 288 record it. The supervisor's review (SUP-029) asked for the model to be proved on UzPainter's own float32 Height first, and for the misses and their controls to be compared separately.

## Decision

1. **Where.** `VirtualMapRequest::islandNormal` (`src/export/virtual_maps.h`). `EncodeExport` sets it per file only under `DiagnosticMeasure`. With it, and with incomplete coverage, `Normal_OpenGL` and `Normal_DirectX` are computed in four steps.
   1. **The Height the stencil reads** (decisions 263, 288 (a); `PadIslandHeight`). Covered texels keep the float32 read-out. Uncovered texels get the measured ring kernel over the Height's stored operands, without decision 206's 1 − (1 − m), then the clamped flood (decision 285). The evaluator takes it through `VirtualNormalRequest::heightPadding`. That request field is never persisted, and the tile cache keys it by the padded content.
   2. **Covered texels.** The combined normal of that Height, from the evaluator's own op.
   3. **The mesh-free normal** (decision 276). It is the same evaluation with `VirtualNormalRequest::withoutMesh`, padded by `PadIslandNormal`:
      - each ring texel copies its nearest covered 8-neighbour without wrap-around, ties in decision 197's offset order (decision 287);
      - a ring texel whose covered neighbours all lie across the x border keeps the flat height normal combined with the Normal channel there (decision 287 §4);
      - every other uncovered texel copies its seed in decision 197's flood with clamped reads (decision 285).
   4. **Uncovered texels.**
      - Without a mesh map, they are that padded normal (decision 287 §5).
      - With one, each is `MeshOnPaddedNormal`: normalise(reoriented(decode(F), decode(M))). Here F is the mesh map's operands at the texel, and M is the padded mesh-free normal encoded in OpenGL, then decoded.
2. **Decision 276 items 4 (b) and (c) stay open.** The chosen form is the encoded M combined under F, with F outside. Decision 293 lists this form as the one decision 276 §2 implies. Every uncovered texel of such a file is counted as undecided: `EncodedFile::undecided`, and the receipt's optional `non_conformant.undecided: [{path, texels, rule}]` (schema updated). Decision 293's recording decides them.
3. **Unchanged.**
   - Production never sets `islandNormal`.
   - `CheckIslandNormal` (decision 245) and `CheckPadding` (decision 259) still refuse, and the diagnostic mode still records both as bypassed.
   - A diagnosticMap of a virtual normal keeps decision 286's whole-tile path.
4. **A measurement hook.** In this path only, `UZP_DIAGNOSTIC_NORMAL_DUMP` writes the float32 Height before and after step 1.

## Measurement: the Wand, real pipeline

**The run.** The Tier 1 runner's `measured()` with `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT=1`: two rebuilds, DX12 host, CPU export. The binary is `zig build painter -Doptimize=ReleaseFast -j4`. Both receipts were marked `non_conformant`, and the rebuilds were repeatable. Classes are those of decision 286.

| Normal | Before (decision 286) | After |
|---|---|---|
| Covered (all edge) | 1,071 | **49** |
| Ring | 6,334 | **78** (6,300 within 1 code) |
| Gutter | 3,679,663 | **51,515** (3,659,463 within 1 code) |

BaseColor, Height, Metallic and Roughness are unchanged: interior 0, ring 113 / 23 / 17 / 23. The ring texels exact on all four material maps are **6,204 / 6,334**. That is the real-pipeline (final-material) count. The measure-path isolated-kernel count, 5,917 / 6,334, comes from Painter's own inputs (decision 292 and later). It is not re-measured here, and the two numbers measure different things.

**SUP-029's checks**, private scratch `E:/tmp/uzp-scratch/normal-wire/` (`analyse.py`, `extra.py`):
1. **The model.** `tools/parity/fit/normal.py` was run on UzPainter's own float32 Height read-out (dumped, not decoded from the PNG 16) with the mesh map. It reproduces decision 286's exported Normal on every covered texel: 0 of 508,307 differ. On the padded Height, it reproduces the new export on every covered texel, also 0 differing.
2. **Only uncovered taps are replaced.** The padded Height equals the read-out bit for bit on every covered texel.
3. **The two groups**, by which Sharp tap is uncovered:

| Group | Left only | Up only | Both | Total |
|---|---|---|---|---|
| Decision 286's misses: texels | 500 | 473 | 98 | 1,071 |
| still differing after | 32 (max 168 codes) | 9 (max 55) | 8 (max 11) | **49** |
| Controls (eligible, already matching): texels | 1,824 | 88 | 39 | 1,951 |
| differing after | 0 | 0 | 0 | **0** |

- No covered miss is outside the 3,022 eligible texels, before or after.
- **The 49 left.** Of the 49, 9 read an uncovered tap where the Height PNG 16 also misses (the Height ring's 23 misses). The other 40 read ring values whose half is Painter's but whose float32 value is not pinned. That is decision 283's float recording.
- **The 34 ring texels off by more than 1 code** all lie next to one of the 49. They copy them.

This is a diagnostic measurement, not production acceptance. The 1-code ring and gutter spread is decision 276 item 4 (b). Exact operands need decision 283's recording.

## Alternatives Considered

- **Compute the whole normal on the CPU in the export.** Rejected. The Normal channel's coverage cannot be read back from a store tile (`ITileStore::Read` drops alpha). The evaluator's own op keeps the covered texels on the path the evaluator's tests cover.
- **Pad the Height's float32 read-out instead of its stored operands.** Not taken. The Height export's ring, the measure path's kernel, pads the stored operands, and the coordinator named that ring. The Wand's covered result (49) does not separate the two.

## Consequences

- The measure path's Normal now fails only where the Height ring fails (decision 263's single blocker) and within 1 code where the mesh-map form is open (decision 276 item 4 (b)).
- Tests: `tests/export/test_island_normal.py` (CPU, through the new `uzp-export-tests export-diagnostic`) checks each rule against `tools/parity/fit/normal.py` and `tests/export/padding_reference.py` (`padding(..., rounded=False)`, `island_normal`).
