# 395. The owner approves EXC-010: the Wand v1 padding and its Normal's island-edge texels may differ, everything else stays exact

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine

## Context

Phases 1 and 2 waited on the Wand (gate G1). Its Tier 1 comparison cannot pass texel for texel in two places:
- the padding texels outside the UV islands, on all five maps (`infinite` padding, `phase1.25_pilot-wand` item 2.7, still not exact after decisions 261 to 368);
- the Normal's island-edge texels: covered texels with an uncovered 8-neighbour, whose height-to-normal stencil reads Painter's padded Height outside the islands (decisions 223 Result, 245, 263, 308). On the whole-tile path there are 1,071 of them.

Every other covered texel matches on all five maps (decisions 286, 308, 366).

Decision 259 had withdrawn EXC-007 on the owner's own "Não, tudo idêntico" (2026-10-18). Its §6 says that only the owner's own yes to an exception's terms counts.

**The owner's answers** (André, 2026-11-03, pt-BR, verbatim).

Question 1:

> "As fases 1–2 travaram porque o Wand não bate pixel a pixel em dois lugares: os texels de padding fora das ilhas UV (o EXC-007 já cobre esses no Wand v1, decisão 223) e 1.071 texels da borda das ilhas do Normal (os outros 4 mapas e o interior das ilhas batem exato). Como você quer destravar?"

He chose "Aprovar exceção (Recomendado)". The option read:

> "Nova exceção cobrindo os 1.071 texels de borda do Normal do Wand v1, publicados por faixa no relatório; todo o resto continua exato."

**Correction.** Question 1 was wrong: it said EXC-007 still covered the padding. It does not. Decision 259 withdrew it, so his first answer approved the Normal's edge only. He was asked again.

Question 2:

> "Pra fechar o Wand agora, a exceção precisa cobrir também o padding (os texels FORA das ilhas UV, nos 5 mapas), que você tinha recusado em 18/10 ('tudo idêntico'). Dentro das ilhas fica tudo idêntico, menos os 1.071 texels de borda do Normal que você já aprovou. O que você quer?"

He chose "Incluir o padding (Recomendado)". The option read:

> "Exceção única pro Wand v1: padding fora das ilhas + borda do Normal podem diferir, publicados por faixa; o resto continua exato."

These are his own yes to the terms below (decision 259 §6).

## Decision

1. **EXC-010 version 1** (`parity/exceptions.json`). EXC-007 stays withdrawn and its id is not reused; EXC-008 and EXC-009 are taken.
   - **Tier and domain.** Tier 1, `asset_map` `tier1/pilot/wand-v1`, golden `phase1/tier1/wand-v1` only (`domain.goldens`). The float twins `wand-v1-float` and `wand-v1-normal-float` have another domain and are not covered.
   - **Bound 1.** `max_abs_diff` 0 over `covered_interior`, on every map, the Normal included: every covered texel whose eight neighbours are all covered (x wrapping) is exactly equal.
   - **Bound 2.** `max_abs_diff` 0 over `covered`, on every map but the Normal (`excepted_outputs: ["export/11-Varinha-Madeira_v1r2_Normal"]`, the golden record's output id).
   - So the only covered texels that may differ are the Normal's island-edge texels: covered, with an uncovered 8-neighbour (decision 223's Result; x wrapping, as the ring and `runner.texel_classes` do). The uncovered (padding) texels of all five maps may differ.
   - **Fail-closed.** A comparison without a coverage mask, with a mask of another size, or naming no output is held to both bounds. A coverage mask with no interior texel at all is covered by nothing.
   - **No numeric bound on the excepted texels.** Decision 223 §3's reasoning holds: a bound measured on a guessed rule would not carry. The class is excepted, not a count; 1,071 is its whole-tile count.
   - **Basis** `owner_scope_split`, `approved_by: owner`, `approved_on: 2026-11-03`.
2. **Everything that differs is still measured and published**, per map and per band (decision 223 §2).
   - Each map's `padding` block keeps the covered, uncovered and 1/2/4/8-texel band statistics.
   - It gains `edge_texels` and `edge`: the island-edge texels' statistics (`tools/parity/tier1/compare.py`, `parity/schema/comparison-report.json`; optional, so older reports stay valid).
3. **Verdict and register** (`tools/parity/verdict.py`, `parity/schema/exceptions.json`, `tools/parity/schemas.py`).
   - The bound scope `covered_interior` and the bound property `excepted_outputs` are new. Both are admitted only in an owner scope split, which must keep one max |delta| 0 bound with no exception.
   - `register_problems` refuses an entry that excepts outputs without listing its goldens.
   - The Tier 1 comparison now names the golden and the recorded output of each map (`Comparison.golden_id`, `output_id`).
   - Defect detection: `tests/parity/test_verdict.py::test_exc010_catches_injected_defects`. One code on one covered interior texel fails on any map, the Normal included. An island-edge difference fails on any other map, and on the Normal when no output is named. A uniform offset and a missing or mis-sized mask fail.
4. **What writes the Wand's five maps: the diagnostic measure export, not a production lift.**
   - Decision 286's mode records each production refusal it bypasses in its receipt (`non_conformant.bypassed`), pads with `InexactPadding::measure` and computes the Normal on the islands by decision 308's recorded rule. It is reachable only through `UzPainter.exe run --diagnostic-measure-export`, which the adapter client passes only for `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT=1`.
   - The Wand's Tier 1 test (`test_wand_v1.py`) now runs its rebuilds and its save/reopen export in that mode. It checks each receipt is marked `non_conformant` and that every bypassed refusal is decision 245's or decision 259's.
   - **Production is unchanged.** `CheckIslandNormal` and `CheckPadding` still refuse before writing on every asset, the Wand included.
   - Why no production lift: the export cannot tell which golden its project belongs to, so any lift there would reach every islanded asset. Belt, Tunic and every other asset stay refused, with nothing written, and EXC-010 covers none of them. The refusal tests (`tests/export/test_export_encoders.py::test_virtual_normal_on_islands`, `tests/python/test_pyapi_diagnostics.py`) keep their expectations.
   - The adapter keeps failing closed: a `non_conformant` export gets no Assets3D manifest (decision 286 §5). The Wand's Tier 1 pass is parity evidence under EXC-010, not a production delivery.
5. **Supersedes in part, for the golden `phase1/tier1/wand-v1` only:**
   - **Decision 259 §2.** A padding difference on the Wand passes under EXC-010. It fails only without the entry, or outside its terms.
   - **Decision 259 §4.** Its scope is unchanged in production; only the Wand's Tier 1 evidence is written past it, by the measure mode.
   - **Decision 245 §1**, for the Wand's Tier 1 evidence only. The refusal stays in production.
   - **Decision 286 §2**, which said the measure mode's report is never the Tier 1 report. For the Wand, under EXC-010, it is.
   - **Decision 255 §3.** The Wand's Tier 1 test no longer ends as an expected failure. Any refusal now fails it.
   - Everywhere else those decisions stand: decision 259 §6, decision 245 §2-§5 and the production refusals.
6. **Reporting and what stays open.**
   - A Wand pass is reported as "pass under EXC-010", never as exact. Its report lists EXC-010 version 1 in `exceptions_relied_on`, and G1's gate record lists it as relied on.
   - Item 2.7 stays open for the exact rule. EXC-010 is narrowed by a new version as parts become exact: the padding first, then the Normal's edge, which follows the Height's ring (decision 308).
   - Items 3.1 to 3.3 can be checked on the run's evidence; 4.1 and the archive wait on the coordinator's full gate.

## Result: the Wand's Tier 1 run under EXC-010

The run: DX12 run of 2026-11-03, `test_wand_v1.py` on the tree of `e50844ee`, `zig build painter -Doptimize=ReleaseFast` (`UzPainter.exe` SHA-256 `20982dff60ea…`), every export the diagnostic measure export (decision 286), both rebuilds' receipts and the reopen export's marked `non_conformant` with only decisions 245's and 259's refusals bypassed. It took 232 s.

**Verdict: pass under EXC-010** (`parity/reports/phase1/tier1-wand-v1.json`). The oracle is `stable`, the two rebuilds are `repeatable`, there is no structural item, and the save/reopen export equals the first one byte for byte.

Counts are of differing values (components), as the report gives them. There are 508,307 covered texels, 6,301 of them on the island edge, and 3,685,997 uncovered ones.

| Map | Covered interior | Covered island edge: values differing / max | Padding: values differing / max / mean | Within 1 / 2 / 4 / 8 texels of coverage |
|---|---|---|---|---|
| BaseColor | 0 | 0 | 34,374 / 2,806 / 0.907 | 147 / 291 / 589 / 1,215 |
| Roughness | 0 | 0 | 7,667 / 1,542 / 0.950 | 20 / 44 / 100 / 240 |
| Metallic | 0 | 0 | 14,103 / 8,481 / 1.737 | 15 / 31 / 82 / 253 |
| Height | 0 | 0 | 12,295 / 8 / 0.008 | 17 / 38 / 91 / 240 |
| Normal | 0 | **42 / 168** | 4,673 / 169 / 0.005 | 51 / 103 / 208 / 447 |

- Every covered interior texel is equal on all five maps. Every covered texel is equal on the four material maps.
- The Normal's only covered differences are 42 values on island-edge texels: the class EXC-010 excepts. On the whole-tile path there were 1,071 such texels (decision 223); decision 308's island rule leaves these.
- `phase1.25_pilot-wand` items 3.1 to 3.3 are checked on this run. Item 2.7 and acceptance 4.1 stay open.

## Alternatives Considered

- **Reuse EXC-007 (a version 3).** Rejected. A withdrawn id is never reused (decision 259 §1), and EXC-007 never covered covered texels.
- **Lift the production refusals for the Wand.** Rejected. The export has no way to know an asset's golden, so the lift would write inexact Normals and padding silently for every islanded asset (decision 001). The measure mode already writes, marks and records what it bypasses.
- **Name the excepted maps positively** (a bound that applies only to the four non-Normal maps). Rejected: a map added later would be held to the interior bound only. Excepting the one Normal output keeps every other output under both bounds.
- **A ceiling of 1,071 texels on the Normal's edge.** Not taken. The owner's terms except the edge class, published per band. A count from one path would not hold on the next.

## Consequences

- The Wand's Tier 1 test passes only when every covered interior texel is equal on all five maps, every covered texel is equal on the four material maps, and the two rebuilds are byte-identical. It is then a pass under EXC-010.
- `parity/reports/phase1/tier1-wand-v1.json` is rewritten by that run.
- Production export of islanded sets is still refused, so the Wand has no conformant UzPainter delivery until item 2.7 is exact.
