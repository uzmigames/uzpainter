# 255. A refused export is one structural failure, and the Wand Tier 1 test ends as an expected failure naming decision 245's refusal

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand

## Context

`test_wand_v1_maps_equal_painter_and_are_byte_stable` failed in the full gate with "6 more items" in `equality_to_painter.structural`. Reproduced on the CPU with the admitted golden `phase1/tier1/wand-v1` and two refused rebuilds (scratch `fix4/wand-tier1/cpu_compare.log`), the six items are:

| output_id | reason |
|---|---|
| `export` | `candidate_export_refused` |
| `11-Varinha-Madeira/11-Varinha-Madeira_v1r2_BaseColor` | `missing_from_candidate` |
| `11-Varinha-Madeira/11-Varinha-Madeira_v1r2_Height` | `missing_from_candidate` |
| `11-Varinha-Madeira/11-Varinha-Madeira_v1r2_Metallic` | `missing_from_candidate` |
| `11-Varinha-Madeira/11-Varinha-Madeira_v1r2_Normal` | `missing_from_candidate` |
| `11-Varinha-Madeira/11-Varinha-Madeira_v1r2_Roughness` | `missing_from_candidate` |

- The first is decision 245's refusal: the five-map export is refused whole, before writing, because its virtual Normal on the Wand's UV islands is not exact. That refusal is correct (decision 001).
- The other five are its consequence, not five defects. A refused run has no files, so the comparison's per-map loop marked every map of r1 as missing. Nothing in the exporter or the comparison is wrong apart from this double count.
- Decision 124 adopted the panel condition "list every missing map", and its synthetic test asserted the refusal plus every map. The report's `oracle_unavailable` branch already listed only the refusal.
- Decision 245's consequences say the Wand's Tier 1 run reports the export as refused, not as a failed comparison. The gate test instead failed on six structural items, and the failure kept sending agents to fix it.

## Panel

One round, `cx/gpt-6-astra`, `kimi/kimi-k3`, `xai/grok-4.5` (dossier and answers in scratch `fix4/wand-tier1/`).

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 A refused export lists only `{export, candidate_export_refused}`; outcome stays `fail`; no schema enum change | PARTLY: branch on the typed refusal, not on the file count; an export that finished empty still lists every map | AGREE: key on the refusal signal; record the narrowing of decision 124 | PARTLY: `fail` reads as a failed comparison; either `blocked` with no structural item, or `fail` documented |
| C2 The refusal message stays on the Python-side run, not in the public report | AGREE: branch on the typed status | PARTLY: report it in the test output | AGREE |
| C3 The test asserts the refusal report, then `pytest.xfail(<message>)` | PARTLY: only the known decision-245 refusal, both rebuilds refused, report asserted first; any other refusal fails | PARTLY: branch, then xfail | DISAGREE: the decided refusal should pass the test |
| C4 Other failures, and a refusal that wrote files, still stop the run | PARTLY: keep it proven | AGREE | AGREE |

## Decision

1. **A refused export is one structural failure** (`tools/parity/tier1/compare.py` `equality`). The run is classified as refused only by the runner's existing typed test: exit status 1, `NotYetSupported` on standard error and no file written (decision 124 §2). It then lists only `{export, candidate_export_refused}`, compares no map and keeps the outcome `fail`. The schema's rule that a structural difference fails in every tier is kept, so the outcome is not `blocked`; that is 2 of 3. A stale golden still reports `stale`.
   - `missing_from_candidate` names a map that a finished export left out, so decision 124's "list every missing map" now applies to exports that ran. An export that finished without writing anything still lists every map of r1.
2. **The refusal's message stays out of the public report.** `CandidateRun.refusal` holds it for the caller. The runner's `compared()` returns the report and both rebuilds; `run()` still returns the report alone, so Belt v5 is unchanged. `refusal(call)` moved from the recipe runner to the Tier 1 runner, which both use. The first DX12 run showed that it returned a raw JSON tail starting mid-word (`port: 11-Varinha-Madeira map ...`). The pinned `painter_layer_stack.py` raises with the client's reply cut to its last 3000 characters (`text[-3000:]`), and decision 245's message with its traceback is longer than that. The cut reply is not JSON, so `refusal` now reads the message from the traceback's last line (`NotYetSupported: <message>`), which the cut keeps. `test_tier1_compare.py::test_the_refusal_message_is_read_from_a_whole_or_cut_reply` covers a whole reply and a cut one.
3. **The Wand Tier 1 test** (`tests/parity/tier1/wand_v1/test_wand_v1.py`) does the following when a rebuild was refused:
   - It asserts that both rebuilds carry decision 245's refusal (`IslandNormalRefusal`'s "the Height outside the UV islands; decision 245").
   - It asserts that the report states exactly the one structural item, with no maps, and that repeatability is `not_measured`.
   - It then ends with `pytest.xfail` naming the refusal. This was GPT's and Kimi's position. Grok's plain pass was rejected, because the acceptance of item 3.1 is unmet and a pass would read as met.
   - Any other refusal, or one rebuild refused and one not, fails the test with the messages.
   - When item 2.7 lifts the refusal, the equality and repeatability assertions run unchanged. No marker needs removing.
4. **Evidence.**
   - `tests/parity/tier1/test_tier1_compare.py::test_a_refused_export_fails_naming_the_refusal_once` covers a refusal (one item, no maps, `not_measured`) and an export that finished empty (every map missing).
   - `::test_a_golden_of_another_envelope_is_stale` covers a refusal against a stale golden (`stale`).

## Alternatives Considered

- **A new outcome `refused`, or a refusal message in the report.** Rejected. The report schema is public, holds numbers and hashes only, and its outcome order is the contract's (decision 124). The reason code already names the refusal.
- **`blocked` with an empty `structural`.** Rejected. A refused export is missing content, and missing content fails in every tier.
- **A hard `pytest.fail(<message>)`.** Rejected. The gate would stay red for a decided refusal with a named owner.
- **`pytest.skip`, as the recipe gate does (decision 142).** Rejected. A skip would not check that the report states the refusal.

## Consequences

- On the owner's machine the Wand Tier 1 test reports `XFAIL` with decision 245's message, not a failure with six items. This was measured once on DX12 (ReleaseFast, 36 s; scratch `fix4/wand-tier1/pytest-wand-dx12.log`). Both rebuilds carried the decision-245 refusal of `11-Varinha-Madeira_v1r2_Normal`. Items 3.1 and 4.1 stay open under item 2.7.
- `parity/reports/phase1/tier1-wand-v1.json` is still decision 223's run. A local run with `UZP_TIER1_REPORT` set rewrites it as the refusal.
