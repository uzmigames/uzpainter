# 417. The owner includes the virtual Normal's island edge: EXC-014 lets its covered island-edge texels differ in production, everything else exact

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase4.1_export-island-padding-exact, phase3.1_assets3d-cutover, phase3.1_unreal-gltf-pbr-preset
**Supersedes in part**: decision 245 §1 (the production refusal of a combined virtual normal on UV-islanded sets, for the scope of §3 below) and decision 414 §3 (`CheckIslandNormal` unchanged)

## Context

Decision 414 lifted the production refusal of `infinite` padding on UV-islanded sets under EXC-013 (every covered texel exact, the padding outside the coverage free), and kept `CheckIslandNormal` (decision 245): a file that reads a combined virtual normal over incomplete coverage stayed refused in production "until the owner decides separately". A five-map pilot export holds such a Normal, so it stayed refused as a whole (decision 091).

The Normal's covered island-edge texels read the Height outside the islands through the height-to-normal stencil (decisions 245, 263). The diagnostic measure export computes them by Painter's recorded rule (decision 308: the stencil reads the measured `infinite` padding of the Height, decisions 263 and 288 (a)). Under that rule the covered values that still differ from Painter are on the island edge only: Wand v1 42, Sash v5 880, Tunic v10 25,393 (Tier 1 runs under EXC-010, EXC-012 and EXC-011 v3; decision 410's table). Every covered interior texel of the Normal, and every covered texel of every other map, is exact on the three pilots.

**The owner's answer** (André, 2026-11-09, relayed by the coordinator session). Asked whether production should also release the Normal's island edge, he chose **"Incluir a borda"** (include the edge). The terms relayed with that choice:
- only the Normal texels on the island edge whose value derives from the Height padding outside the islands may differ;
- the Normal's interior and every other map stay exact: bound 0 on every covered texel outside that band.

This is his own yes to the terms below (decision 259 §6).

## Decision

1. **A new id, EXC-014 version 1** (`parity/exceptions.json`), not EXC-013 version 2. EXC-007 stays withdrawn; EXC-008 to EXC-013 are taken; ids are never reused.
   - Why a new id. Only the highest version of an id is in force (CONTRACT.md §5), so an EXC-013 version 2 would replace version 1's bound for every padded file. It would then have to hold two bounds on two kinds of file (every covered texel exact on the material maps, the interior only on the Normal) in one entry. The register can only name excepted outputs by recorded output id (`excepted_outputs`, decision 395), and a production export has no golden to name them from. A second entry with its own receipt listing keeps both mechanical: EXC-013 v1 stays unchanged on every padded file, and EXC-014 is relied on only by the files the receipt names under it. The two also close separately: EXC-013 when the padding is exact (item 2.1 of `phase4.1_export-island-padding-exact`), EXC-014 when the Height outside the islands is (item 2.2).
   - **Tier and domain.** Tier 1, domain kind `production_export` (decision 414), selector `export/islanded-virtual-normal-edge`. A comparison is in the domain only when the candidate's export receipt names EXC-014 in `exceptions_relied_on` for the compared file (`Comparison.candidate_exceptions`). The export names it only for the files of §3.
   - **The band** (the pilots' definition, EXC-010, EXC-011 v3, EXC-012; decisions 245, 395): the covered texels with at least one uncovered texel among their eight neighbours, x wrapping, rows not wrapping (`tools.parity.coverage.distance_bands`; the covered texels outside `covered_interior` in `tools/parity/verdict.py`). It holds every covered texel whose height-to-normal taps read an uncovered Height texel (Sharp's left and upper taps, decisions 064, 065 and 263; a Sobel 3 x 3). It is the band within which decision 263 found every differing Normal texel.
   - **Bound.** `max_abs_diff` 0 over `covered_interior`: every covered texel outside the band is exactly equal. The band and the uncovered (padding) texels may differ, with no numeric bound (decision 223 §3). A file the receipt does not name under EXC-014 is held to EXC-013 v1, every covered texel exact.
   - **Fail-closed.** A comparison without a coverage mask, with a mask of another size, or with no covered interior texel is not covered. A shape mismatch is structural and fails in every tier.
   - **Basis** `owner_scope_split`, `approved_by: owner`, `approved_on: 2026-11-09`. Defect test: `tests/parity/test_verdict.py::test_exc014_catches_injected_defects`. Each of these fails: one covered interior value on the Normal, one covered interior value or one island-edge value on another map, a uniform offset, a structural difference, a missing or mis-sized mask, and a Normal edge difference whose receipt does not name EXC-014.
2. **Reporting.** A pass relying on it is "pass under EXC-014" (with EXC-013 for the other padded files), never exact. EXC-010, EXC-011 v3 and EXC-012 are unchanged; they keep scoring the measure export's Tier 1 evidence.
3. **`CheckIslandNormal` is lifted in production for exactly this scope** (`src/export/guards.cpp` `IslandNormalFileRefusal`, `src/export/padding.h` `IslandNormalLifted`). A file is written when all of these hold:
   - every channel of it reads a combined virtual normal map (virtualMap `Normal_OpenGL` or `Normal_DirectX`), so no other map shares the band;
   - its padding is `infinite` over incomplete coverage with a covered texel (`PadsIslands`), and it is not resized (decision 349's refusal stays).

   Its Normal is computed by decision 308's rule, the measure export's: the stencil reads the measured `infinite` padding of the Height outside the islands, so the band's values derive from that padding as the owner's terms say. The file is written under EXC-013 and EXC-014. Everything else stays refused, with decision 245's message:
   - a file that mixes a combined virtual normal with another source;
   - every diagnosticMap that isolates, compares or summarises one (`isolated/`, `contribution/`, `regionStats/`; a statistics file reads the band in aggregate);
   - `passthrough` and the dilation paddings;
   - `uzpainter.diagnostics`' in-memory views (`IslandNormalRefusal`).
4. **Decision 245 §2 stays: a Height with no layer is refused** (`IslandNormalHeightRefusal`). A stack with no Height channel, or none of whose layers contributes to it (its Height DAG has no root layer), is refused before anything is written, in the export and in the preflight. No recording shows what Painter's empty Height reads (R-092). Its recording is authored but not recorded (`parity/reports/phase1/normal-empty-height-freeze.md`). The diagnostic measure export records this refusal as bypassed, as it does for decision 245's. Decision 245 §3's uniform non-zero Height is in scope: its interior stencil reads equal taps, and the padding it differs on (Painter's mean of equal values) is outside the islands, so it reaches the band only.
5. **Receipt.** Each file of §3 sets `EncodedFile::islandNormal`. The export receipt's `exceptions_relied_on` gains {exception_id `EXC-014`, version 1, decision `417`, paths} next to EXC-013's entry, and the manifest export block names it in `open_items` (`kIslandNormalNote`). The generation is conformant (no `non_conformant`), so Assets3D manifest blocks are written for it with both exceptions named.
6. **Tier 1 on production exports.** The Tier 1 runners (`tests/parity/tier1/wand_v1/runner.py`, `tools/parity/tier1/compare.py`) read each production rebuild's receipt and pass, per compared file, the exception ids its `exceptions_relied_on` names for that file as `candidate_exceptions`. The measure export's comparisons pass none: a non-conformant generation is outside a production domain.

## Alternatives Considered

- **EXC-013 version 2.** Rejected (§1): one entry cannot hold two different covered bounds on files the register cannot name, and the two parts close in different items.
- **Lift for every file that reads the combined normal, a packed one included.** Rejected: the band would then except the other channels of a packed file on the island edge, against "every other map stays exact".
- **Lift the diagnosticMap sources and the statistics files too.** Rejected: the owner released the Normal map's edge. A statistics file summarises the band with the interior, so no per-texel bound applies to it.
- **Admit a Height with no layer as the same band.** Rejected: no recording shows it (decision 245 §2), and its own task is in flight.

## Consequences

- Production exports a five-map pilot export on UV islands under `infinite`, provided its Height has a layer. Its receipt relies on EXC-013 for every padded file and on EXC-014 for the Normal.
- `phase4.1_export-island-padding-exact` keeps items 2.1 and 2.2 and the narrowing and withdrawal of EXC-010 to EXC-014. Its lift of `CheckIslandNormal` is done under EXC-014.
- `phase3.1_assets3d-cutover` item 3.1 has conformant five-map pilot exports to validate under EXC-013 and EXC-014. Its draft amendment names both and stays unsigned.
