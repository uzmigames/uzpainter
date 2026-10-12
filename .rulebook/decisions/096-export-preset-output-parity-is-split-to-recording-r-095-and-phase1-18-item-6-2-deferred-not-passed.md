# 96. Export preset output parity is split to recording R-095 and phase1.18 item 6.2: deferred, not passed

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.17_export-presets, phase1.18_export-engine

## Context

Task phase1.17 items 3.1 and 4.1 ask that each shipped preset pass an output-parity test on a UzmiGames fixture project against private records: every file equal on decoded pixels and naming. Decision 095 records what exists:

- **No record of the Painter presets.** The private store holds no export through `PBR Metallic Roughness` or `Blender (Principled BSDF)`. Their layouts are hypotheses, refused until recording R-095.
- **The five-map preset is partly covered.** The current envelope holds the five-map preset's Normal map. Its byte-identical comparison passes (`test_five_map_preset_normal_equals_painter_files`, 4 of 4 texture sets).
- **No five-map golden.** No golden fills all five maps.
- **BaseColor is refused in all three presets.** Its sRGB export encoding is recorded but not fitted (decision 090, R-090, `phase1.18_export-engine` item 6.1).

The speed rules of 2026-10-12 close tasks with scope splits when an item is blocked only by a recording and nothing claimed is untrue. Claim C4 of decision 095's panel round asked whether to split items 3.1 and 4.1 to R-095 and R-090 and archive the task:

| Panel member | Verdict |
|---|---|
| kimi/kimi-k3 | AGREE |
| xai/grok-4.5 | AGREE |
| cx/gpt-6-astra | DISAGREE. Archive only with an explicit amendment that marks the unmet items deferred, not passed, and assigns concrete follow-up acceptance tests. |

## Decision

1. **Items 3.1 and 4.1 of phase1.17 are checked as recorded scope splits.** They are deferred, not passed. Each preset's provenance record states `parity.status: "pending"`, with its pending recordings and owners.

   Done in phase1.17:
   - the provenance and alias checks;
   - the refusals;
   - the five-map preset's plan equality with the pipeline configuration;
   - its Normal map's byte equality with Painter.
2. **New item `phase1.18_export-engine` 6.2** owns the remainder, with these acceptance tests:
   - Record R-095 (`parity/reports/phase1/export-presets.md` §3).
   - Confirm or correct the two Painter-named presets from it, and set their layout to `confirmed`.
   - Add an output-parity test per preset in `tests/export/test_export_presets.py` against the R-095 goldens, comparing every file's name and decoded pixels.
   - Set each record's `privateRecords` and its `parity.status` to `exact` when it passes.
   - BaseColor's part follows item 6.1's fit from R-090.
3. **GPT's condition is adopted.** The split is written as deferred in the task checklist, the provenance records and the report. The follow-up tests are named.

## Alternatives Considered

- **Keeping phase1.17 open until R-095 and R-090 are recorded and fitted.** Rejected by the panel majority and the speed rules. Everything phase1.17 can do without Painter is done, and the refusals keep the unconfirmed behaviour out.

## Consequences

- phase1.17 is archived.
- phase1.18 cannot close until items 6.1 and 6.2 are done.
- R-095 joins R-090 on the Painter-owning agent's list.
