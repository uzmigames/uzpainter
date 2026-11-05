# 401. The owner widens EXC-011 to the island edge of every Tunic map; the 3-texel coverage near-tie goes to phase3.1

**Status**: accepted
**Date**: 2026-11-05
**Related Tasks**: phase2.10_pilot-tunic-recovery, phase3.1_export-island-padding

## Context

The Tunic's Tier 1 ran for real for the first time on 2026-11-03 (d2a71c25, task notes §13; `parity/reports/phase2/tier1-tunic-v10.json`). Under EXC-011 version 1 (decision 398, EXC-010's terms) it failed.
- Every covered interior texel was exact on all five maps, and Metallic was exact everywhere.
- 17 values on 3 covered island-edge texels differed: BaseColor 5 (max 1,042), Height (`Displacement_Raw`) 9 (max 192), Roughness 3 (max 771).
- Version 1 excepts the covered (edge) bound only on the Normal, so those 17 values failed it.

**Diagnosis** (2026-11-05, the coordinator's diagnosis run; its one-shot scripts were not kept, and the texel coordinates stay private). The 3 texels are a coverage near-tie at 4096 px.
- Under decision 281's coverage rule (each UV vertex snapped to 1/256 texel before the edge test), each texel centre lies inside its triangle by only 0.00004, 0.0016 and 0.0007 texel.
- In each case an endpoint of the deciding edge lies within 1/64 texel of a rounding tie of that snap.
- Painter counts these texels outside the island and UzPainter counts them inside, so UzPainter writes the island's value where Painter writes padding.
- A float32 clip-space hypothesis (the edge test done on float32 clip-space positions instead of the snapped texel-space ones) was tested and failed: it does not reproduce Painter's choice on the 3 texels. No rule that does is identified.

**The owner's answer** (André, 2026-11-05, pt-BR, verbatim).

Question:

> "Tunic: só 3 texels na borda das ilhas UV não batem (BaseColor, Height e Roughness, 17 valores no total). É um empate de arredondamento: o Painter considera o texel fora da ilha e o UzPainter considera dentro. Todo o interior dos 5 mapas bate exato. Como fecho o Tunic?"

He chose "Ampliar a EXC-011 (Recomendado)". The option read:

> "Nova versão da exceção do Tunic: a borda das ilhas pode diferir em todos os mapas (hoje só no Normal), publicada por faixa; o interior continua exato. Fecha e arquiva o Tunic agora. A regra exata do empate vai pra task de padding exato (fase 3)."

This is his own yes to the widened terms below (decision 259 §6).

## Decision

1. **EXC-011 version 2** (`parity/exceptions.json`), superseding version 1, which stays in the register as history.
   - **Tier and domain.** Unchanged: Tier 1, `asset_map` `tier1/pilot/tunic-v10-current`, golden `phase2/tier1/tunic-v10-current` only.
   - **Bound 1.** Unchanged and unexcepted: `max_abs_diff` 0 over `covered_interior`, on every map, the Normal included.
   - **Bound 2.** `max_abs_diff` 0 over `covered`, with `excepted_outputs` listing every map's recorded output (the golden record's ids): `export/DefaultMaterial_BaseColor_sRGB`, `export/DefaultMaterial_Displacement_Raw`, `export/DefaultMaterial_Metallic_Raw`, `export/DefaultMaterial_Normal_Raw` and `export/DefaultMaterial_Roughness_Raw`.
   - So the covered texels that may differ are the island-edge texels (covered, with an uncovered 8-neighbour) of all five maps; the padding stays free. A comparison without a coverage mask, with a mask of another size, naming no output or naming an output not listed is held to both bounds. No numeric bound is put on the excepted texels (decision 223 §3).
   - **Basis** `owner_scope_split`, `approved_by: owner`, `approved_on: 2026-11-05`. Its defect test is `tests/parity/test_verdict.py::test_exc011_v2_catches_injected_defects`.
   - Everything that differs is still published per map and per band (decision 395 §2).
2. **Reporting.** A Tunic pass is reported as "pass under EXC-011 v2, against the current reference", never as exact and never as approved-v10 parity. Its report lists EXC-011 version 2 in `exceptions_relied_on`. Decision 398 §5's partial supersessions still apply to this golden only.
3. **The exact rule goes to `phase3.1_export-island-padding`.** That task owns the coverage near-tie rule at the island edge, and narrows EXC-011 version 2 by a new version as it makes the edge exact, back to the Normal only and then to nothing (decision 398 §6).
4. **The Tunic closes on this.** Once its Tier 1 node passes under version 2, items 3.1, 4.1 and 5.3 of `phase2.10_pilot-tunic-recovery` are checked and the task is archived on the affected tests (CLAUDE.md's test-time override of 2026-10-12).

## Alternatives Considered

- **Find the exact tie rule first.** Not taken: the float32 clip-space hypothesis failed, and the owner sent the exact rule to phase3.1, where the padding's own coverage work lives.
- **Except only the 3 texels.** Not offered: a per-texel list would be fitted to this golden's coordinates and say nothing about the rule.

## Consequences

- The Tunic's Tier 1 test passes when every covered interior texel is equal on all five maps and the two rebuilds are byte-identical; the island edge and the padding of every map are published per band.
- The Wand (EXC-010) and the Sash (EXC-012) are unchanged; neither had such edge values.
- Production export of the Tunic is still refused, so it has no conformant UzPainter delivery until `phase3.1_export-island-padding` is exact.
