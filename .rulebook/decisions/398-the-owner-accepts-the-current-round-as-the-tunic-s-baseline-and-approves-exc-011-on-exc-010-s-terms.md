# 398. The owner accepts the current round as the Tunic's baseline and approves EXC-011 on EXC-010's terms

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase2.10_pilot-tunic-recovery, phase2.9_pilot-belt, phase3.1_export-island-padding

## Context

The Tunic v10 could not reach its Tier 1 comparison for two reasons.
- **Its inputs.** Part of the original inputs is lost (decisions 194, 215; `parity/reports/phase2/tunic-v10-input-inventory.md`). Today 8 masks and the Normal are originals; the other 9 masks, the AO and the low are substitutes of the current round. That round, `phase2/tier1/tunic-v10-current`, was recorded in Painter (record `3165bacb…`, decision 300 item 7) and rebuilt through the typed MCP tools (state and recipe passed, export refused, commit 31f271ce). Decision 300 item 8 makes it the Tunic's comparison basis only on the owner's own yes.
- **Its UV islands.** As on the Wand, production refuses the islanded export: the Normal on the islands (decision 245) and the `infinite` padding there (decision 259). The Wand passes under its own exception, EXC-010 (decision 395), which covers no other piece. Decision 396 §4 left each pilot to rely on an owner exception of its own, through the measure export, or to wait on `phase3.1_export-island-padding`.

**The owner's answers** (André, 2026-11-03, pt-BR, verbatim).

Question 1:

> "Tunic: parte das entradas originais se perdeu. Hoje 8 máscaras e o Normal são originais; 9 máscaras, o AO e o low são da rodada atual. Aceita a rodada atual como a nova base de comparação do Tunic (decisão 300 item 8)?"

He chose "Aceito a base nova (Recomendado)". The option read:

> "O Tunic passa a comparar com a rodada atual, que já foi capturada no Painter e reconstruída via MCP. Destrava a task 2.10."

Question 2:

> "Tunic e Sash têm ilhas UV como o Wand, então o padding e a borda do Normal também não batem exato. Aplico a mesma regra da EXC-010 (só padding + borda do Normal podem diferir, publicados por faixa; o resto exato) pra cada um?"

He chose "Sim, mesma regra (Recomendado)". The option read:

> "Uma exceção por peça (EXC-011 Tunic, EXC-012 Sash), mesmos termos do Wand."

These are his own yes to a changed baseline (decision 300 item 8) and to the terms below (decision 259 §6).

## Decision

1. **The changed baseline** (decision 300 item 8, phase2.10 item 2.8).
   - The Tunic's Tier 1 comparison basis is the current round, the admitted golden `phase2/tier1/tunic-v10-current` (record `3165bacb…`).
   - The migration golden `phase2/tier1/tunic-v10` is retained unchanged as the approved v10 reference. The two are `different` (698d1ac1, `parity/reports/phase2/tunic-v10-current-reference.md`; only Metallic is byte-identical). So no claim of approved-v10 parity is made: a Tunic result is reported against the current reference (decision 300 item 7, "What may be claimed").
   - The historic missing inputs stay missing and are listed by name and known hash in the inventory. The 9 masks, the AO and the low of the current round are named substitutes, never recovered originals.
   - The admitted manifest is not edited: its description, written before this answer, still says the baseline waits on the owner. This decision is the record of that yes.
2. **EXC-011 version 1** (`parity/exceptions.json`), EXC-010's terms for the Tunic.
   - **Tier and domain.** Tier 1, `asset_map` `tier1/pilot/tunic-v10-current`, golden `phase2/tier1/tunic-v10-current` only (`domain.goldens`). The migration golden has another domain (`tier1/pilot/tunic-v10`) and is not covered.
   - **Bound 1.** `max_abs_diff` 0 over `covered_interior`, on every map, the Normal included.
   - **Bound 2.** `max_abs_diff` 0 over `covered`, on every map but the Normal (`excepted_outputs: ["export/DefaultMaterial_Normal_Raw"]`, the golden record's output id).
   - So the only covered texels that may differ are the Normal's island-edge texels; the uncovered (padding) texels of all five maps may differ. A comparison without a coverage mask, with a mask of another size, or naming no output is held to both bounds. No numeric bound is put on the excepted texels (decision 223 §3).
   - **Basis** `owner_scope_split`, `approved_by: owner`, `approved_on: 2026-11-03`. Its defect test is `tests/parity/test_verdict.py::test_exc011_catches_injected_defects`, EXC-010's seven injected defects on the Tunic's golden and outputs.
   - Everything that differs is still published per map and per band (decision 395 §2).
3. **EXC-012 is reserved for the Sash** (`phase2.9_pilot-belt`). The owner's yes covers it, but it is not created here: its golden, outputs and evidence belong to the Sash's own run.
4. **What writes the Tunic's maps: the diagnostic measure export**, as for the Wand (decision 395 §4).
   - **Tier 1** (items 2.5, 3.1): the Wand's runner, whose native route already rebuilds this job (`tests/parity/tier1/wand_v1/runner.py`, `reopened_compared(..., diagnostic=True)`): two rebuilds through the adapter, each in its own processes, and the first one's save/reopen export. Each receipt must be marked `non_conformant` and name only decisions 245's and 259's refusals.
   - **Dump-and-rebuild** (items 2.4, 3.4): `tests/parity/tier1/tunic_recipe.py` with `diagnostic=True`. The typed sessions keep every state check and send no export; each project (the original, and the rebuilt one after its save and reopen) is exported by a separate `UzPainter.exe run --diagnostic-measure-export` process, its receipt checked the same way.
   - Both tests are in `tests/parity/tier1/test_mcp_round.py`, on one `zig build painter -Doptimize=ReleaseFast`. The production recipe test keeps its expectation (`pass` or `export_refused`).
   - **Production is unchanged.** `CheckIslandNormal` and `CheckPadding` still refuse on every asset, the Tunic included; a `non_conformant` export gets no Assets3D manifest (decision 286 §5).
5. **Supersedes in part, for the golden `phase2/tier1/tunic-v10-current` only**, exactly what decision 395 §5 superseded for the Wand: decision 259 §2 and §4, decision 245 §1 and decision 286 §2. Decision 255 §3 never applied to the Tunic. Everywhere else those decisions stand.
6. **Reporting and what stays open.**
   - A Tunic pass is reported as "pass under EXC-011, against the current reference", never as exact and never as approved-v10 parity. Its report lists EXC-011 version 1 in `exceptions_relied_on`.
   - EXC-011 is narrowed by new versions as `phase3.1_export-island-padding` makes parts exact, and withdrawn once the Tunic passes with no exception.
   - Acceptance 4.1 and the archive still wait on item 1.1: `phase2.9_pilot-belt` is not accepted (`phase2.8_mcp-server` and `phase2.2_recipe-and-diagnostics` are archived).

## Result: the Tunic's runs of 2026-11-03

The tests of dff5f1b0 (register and defect test: e46e6641), on `zig build painter -Doptimize=ReleaseFast` (`UzPainter.exe` SHA-256 `20982dff60ea…`, the Wand's build), DX12 for the Tier 1 runner and Vulkan for the typed round, as each route runs.

**No map was compared.** Every Tunic export is refused before writing, the diagnostic measure export included:

> `evaluator:unsupported_source: the height-to-normal scaling is recorded on square sets of 256, 512, 1024 and 2048 texels only (phase1.12_compositor-height-normal)`

The Tunic's set is 4096 px. The measure mode bypasses only decisions 245's and 259's refusals; this one is the height-to-normal stencil's own (`src/evaluator/height_to_normal.cpp`, `docs/architecture/04-layer-stack-and-compositing.md`: "Refused until recorded: other set sizes and shapes"). The z = 100 / W and 800 / W scalings were fitted on recordings at 256 to 2048 px (decisions 079, 080), and extending them to 4096 without a recording would be a guess. So EXC-011 has nothing to judge yet, and no task owns a 4096 recording: the coordinator has to assign one.

- **Tier 1** (`test_tunic_current_tier1_maps_equal_painter_under_exc011` and its save/reopen test): both rebuilds refused, so there is no save/reopen record. `parity/reports/phase2/tier1-tunic-v10.json` holds the refusal as its one structural item (`candidate_export_refused`, outcome `fail`, nothing relied on). The oracle is `stable`: all five maps are byte-identical in r1, r1-repeat and r2.
- **Dump-and-rebuild** (`test_tunic_current_recipe_rebuild_exports_identical_bytes_in_the_measure_mode`): every state check passed in all three typed sessions, `run_python` was listed in none, and the two recipe digests are equal. Both measure exports were refused by the same message.
- These three tests are expected failures naming that refusal (`HEIGHT_NORMAL_GAP` in `tests/parity/tier1/test_mcp_round.py`). Any other refusal, or a mix of refused and written exports, fails them. Once the scaling is recorded they must pass under EXC-011, or fail.
- **Two defects of the direct route, found and fixed on the way.** It had never run on real UzPainter.
  - The Tier 1 runner ran the sync even after a failed create, so the create's error was hidden (`runner.built`).
  - The native save after the sync called `save_as` onto the open project, which UzPainter's store refuses ("use save()"). It now saves that file with `save` (Full) (`NATIVE_SAVE_CODE`, `tests/adapters/assets3d/wand.py`).
  - The fixture also sets `OCIO` to Painter's substance configuration, which the manifest applies by environment variable and the native create checks by hash.

What this run establishes for phase2.10: items 2.1, 2.3, 2.4, 2.8, 3.2 and 3.3 hold. Items 2.5, 3.1, 3.4 and 3.5 wait on the 4096-px scaling. Item 1.1 waits on `phase2.9_pilot-belt` alone.

## Alternatives Considered

- **Extend EXC-010 to the Tunic** (a second golden in its domain). Rejected: the owner asked for one exception per piece, and EXC-010's domain is the Wand's.
- **Keep the migration golden as the basis.** Rejected by the owner's answer; its inputs cannot be rebuilt (decisions 194, 215, 300).
- **Create EXC-012 now.** Not taken: no Sash run has measured its golden yet.

## Consequences

- The Tunic's Tier 1 test passes only when every covered interior texel is equal on all five maps, every covered texel is equal on the four material maps and the two rebuilds are byte-identical. It is then a pass under EXC-011.
- `parity/reports/phase2/tier1-tunic-v10.json` is written by that run.
- Production export of the Tunic is still refused, so it has no conformant UzPainter delivery until `phase3.1_export-island-padding` is exact.
