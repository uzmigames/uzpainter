# 286. The diagnostic measure export: `UzPainter.exe run --diagnostic-measure-export` writes past decisions 245 and 259 on UV islands, marked non-conformant, so the Wand's real pipeline is scored end to end against its Tier 1 golden

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.23_pyapi-pipeline-adapter

## Context

Item 2.7 of `phase1.25_pilot-wand` measured the `infinite` padding by feeding Painter's own exported maps into `uzp-export-tests process`. That isolates the padding, but it never showed that UzPainter's own evaluated texels plus UzPainter's padding equal Painter's file. Production cannot show it either: `UzPainter.exe` refuses the Wand's five-map export before writing.
- Decision 245 refuses the combined virtual Normal on UV islands (`CheckIslandNormal`).
- Decision 259 refuses `infinite` padding on UV islands (`CheckPadding`).

The coordinator asked for an explicit diagnostic mode on the Tier 1 path. It must:
- export with `InexactPadding::measure`, and write the Normal by the current best path;
- mark its output as not conformant;
- never be the default, and be unreachable from production MCP or `run` calls without an explicit flag;
- leave the production refusals unchanged.

## Decision

1. **Reach: one command-line flag on `run`, and nothing else.**
   - `UzPainter.exe run <script> --diagnostic-measure-export` (before `--`; after `--` it is a script argument) sets a process flag once, before the script runs (`python/run.h` `DiagnosticMeasureExport`).
   - Each export job reads it when it is queued (`ExportJob`). No other verb parses it. The MCP worker process calls `ExportJob` too, but never runs `RunRunCommand`, so it always gets `false`. No Python call can set it.
   - Given twice, it is a usage error (exit status 2).
2. **The Tier 1 fixture reaches it through the adapter client.**
   - The pinned pipeline scripts must run byte-unchanged, and the adapter client (`adapters/assets3d/client.py`) is what starts `UzPainter.exe run`.
   - The client passes the flag only when `UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT` is exactly `1`. Any other non-empty value is a host error before UzPainter runs.
   - The Wand fixture sets it for the export call only (`Wand.export(diagnostic=True)`).
   - The Tier 1 runner's `measured()` is the only caller. `test_wand_v1.py` never uses it, and its report is never written as the Tier 1 report.
3. **What the mode exports** (`export/write.h` `DiagnosticMeasure`, `EncodeExport`):
   - Step 1 runs every production check. Only the `NotYetSupported` refusals of `CheckIslandNormal` and of `CheckPadding` are recorded per file (`EncodedFile::bypassed`) instead of thrown. Every other check still throws, and so does `CheckPadding` under `InexactPadding::measure`.
   - The coverage gets the mesh's triangles (`IslandTriangles`), which the measured ring needs.
   - Step 2 encodes with `InexactPadding::measure`.
4. **The Normal: the current best implemented path.**
   - The combined virtual Normal is written as `EvaluateFileOn` gives it (the height-to-normal stencil over the whole tile), then padded as its stored values by the measured kernel.
   - This is the best path implemented in `src/`. Its island-edge texels are known to differ (decision 245, decision 263: Painter's stencil reads its float32 padded Height). Its ring and gutter are known to differ wherever a mesh map is bound (decision 276).
   - Decision 287 records the Normal's padding rule (ring copy of the nearest covered 8-neighbour of the mesh-free normal, flood, then the mesh map combined per texel). It is not implemented. Its mesh-map combination is pinned only to within 1 code, so implementing it here would add an inexact path to measure an inexact path. It belongs to item 2.7's integration (decision 287 §5), not to this mode.
5. **Marking.**
   - The generation's receipt gets `non_conformant: {mode: "diagnostic-measure", decision: "286", bypassed: [{path, refusal}]}`. This is an optional property of `receipt.schema.json`; a conformant receipt never has it.
   - The receipt's manifest export block names the mode in `open_items` (`NON-CONFORMANT: ...`).
   - The job's result holds `non_conformant`, and the run's report holds `diagnostic`.
   - The adapter fails closed. An export whose receipt says `non_conformant` gets no Assets3D manifest (`manifest_unavailable`), whatever its paths and whatever the environment.
   - The Tier 1 runner checks that each diagnostic rebuild's receipt is marked, and that a conformant rebuild's is not.
6. **The production refusals are unchanged.** `CheckIslandNormal`, `CheckPadding` and their messages are untouched. `test_padding_on_islands` and `test_virtual_normal_on_islands` pass unchanged.

## Measurement: the Wand Tier 1, end to end

**What ran.** The tree is commit 193a8b9 (tree 96f9f8d) on main ba8dbff, with no local patch. Only this decision's text was added afterwards.
- The binary is `zig build painter -Doptimize=ReleaseFast -j4`, `UzPainter.exe` SHA-256 `e380147c...c4de55`.
- The call is `measured()`: two rebuilds of the pinned create, sync and export, each export under `--diagnostic-measure-export`, DX12 host (the export evaluates on the CPU).
- Both rebuilds' receipts were marked `non_conformant`. The two rebuilds are byte-identical (`repeatable`), and the oracle is `stable`.
- The comparison is against r1 of `phase1/tier1/wand-v1` in the private store. Classes use `tools.parity.coverage` (with decision 281's 1/256-texel snap): 508,307 covered texels (6,301 of them edge), 6,334 ring and 3,679,663 gutter. A texel counts as differing when any component differs.

| Map | Covered (interior) | of which edge | Ring | Gutter | Max codes covered / ring / gutter |
|---|---|---|---|---|---|
| BaseColor | **0** | 0 | 113 | 32,121 | 0 / 2,806 / 2,806 |
| Height | **0** | 0 | 23 | 12,588 | 0 / 8 / 8 |
| Metallic | **0** | 0 | 17 | 14,101 | 0 / 8,481 / 8,481 |
| Roughness | **0** | 0 | 23 | 7,768 | 0 / 1,542 / 1,542 |
| Normal | **1,071** | 1,071 | 6,334 (all) | 3,679,663 (all) | 537 / 34,343 / 37,135 |

- **The four material maps.** The interior is 0 on every one. UzPainter's own evaluation of the Wand equals Painter's on every covered texel, so every remaining difference is padding. The union of their misses is 130 ring texels (6,204 of 6,334 ring texels match all four) and 34,535 gutter texels.
- **The Normal.** Its 1,071 covered misses are all island-edge texels: none is an interior texel whose 8 neighbours are all covered. This is exactly decision 245's 1,071. Every one has its left or upper Sharp tap uncovered (1,071 of 1,071, out of 3,022 covered texels with such a tap). That is decision 263's root cause: Painter's stencil reads its own float32 `infinite`-padded Height at those taps, and UzPainter reads the whole-tile evaluated Height. Every ring and gutter texel differs, as decision 276 predicts for stored-value padding over a bound mesh map. Decision 287's rule, not implemented, is what closes them.
- So the interior is 0 wherever the interior does not read outside the islands. The only covered misses are decision 263's Height ring, still item 2.7's open ring.

## Model panel

The design was put to `cx/gpt-5.6-sol` and `kimi/kimi-k3` through 9router; `xai/grok-4.5`'s answer was lost to an encoding error in the client script.
- **C1 (reach).** GPT partly, Kimi agree. Both asked that the flag be read once and captured per job, which it is.
- **C2 (the Normal as the evaluator gives it).** GPT agree, Kimi partly. Kimi's point that a score mixes padding and evaluator errors is answered by the interior / ring / gutter split.
- **C3 (marking).** Both partly. Both warned that a free-text open item is easy to ignore. This led to the structured receipt field and the adapter's fail-closed manifest, adopted.
- **C4 (tests).** GPT agree, Kimi partly. Their extra cases are in the tests: a non-`1` value is an error, a conformant rebuild's receipt is checked unmarked, and the flag after `--` does nothing.

## Alternatives Considered

- **An environment variable read by `UzPainter.exe`.** Rejected. It would reach every process that inherits it, the MCP worker included. The variable that exists is read only by the adapter client, which turns it into the command-line flag.
- **A Python API argument (`export_project_textures(..., diagnostic=True)`).** Rejected. Any script or MCP `execute_python` call could pass it, and the pinned pipeline scripts cannot.
- **Feeding Painter's own files into `uzp-export-tests process`.** That is what was done until now. It does not test UzPainter's evaluated texels.
- **Implementing decision 287's Normal padding in this mode.** Rejected (Decision 4).

## Consequences

- The Wand's real pipeline can be scored against its golden at any time. Run `measured(painter, work)` in `tests/parity/tier1/wand_v1/runner.py`; it runs one GPU-class `UzPainter.exe` session at a time.
- The interior count is the evaluator's own parity on the Wand, apart from the padding.
- Lifting decisions 245 and 259 stays item 2.7's job. This mode never changes what production writes.
