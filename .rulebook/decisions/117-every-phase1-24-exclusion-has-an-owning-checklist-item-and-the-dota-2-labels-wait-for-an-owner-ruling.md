# 117. Every phase1.24 exclusion has an owning checklist item, and the Dota 2 labels wait for an owner ruling

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.24_python-api-facade, phase1.14_compositor-core, phase5.2_parity-report-tiers, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle

## Context

The spec of phase1.24 requires each Tier 0 output outside the supported scope to be listed with its kind and its existing owner. Its report (`parity/reports/phase1/python-api-facade.md` §3) listed four whose owner had no checklist item, or which need an owner ruling. Items 3.1 and 4.1 could not close on them.

- **P20-A and P20-B** (decision 107): the fill-channel defaults and the dense sRGB decode. Decision 108 §4 assigns their fit to phase1.14_compositor-core, which is open, but phase1.14 has no item for them. Recording 1 s9 and s12 of `phase1-reload-resources` are refused for the same reason: the facade refuses s6's grey bitmap on BaseColor (P20-A).
- **`phase1-reload-resources` recording 2, s9 and s12.** After save and reopen, Painter reports reloads of bytes the project already holds (decision 110 §6). The phase0 stability report classifies this golden as unstable: r1 and r2 differ on the events of start, s9 and s12. Decision 032 makes r1 the exact target and publishes r2 residuals in `parity/exceptions.json`. phase1.21, which named the residual, is archived.
  - No open task names `reload_modified_resources_async`.
  - The MCP tasks cover resource import, list, search and replace, not reload, and their fixtures are MCP-only.
  - phase5.2_parity-report-tiers runs Tier 0 over the corpus of `docs/architecture/14-parity-testing.md` §3, which includes the API probes and event order, and publishes the exception register.
- **Dota 2's user-channel labels.** User0-User3 carry Painter's own text, which UzPainter does not ship (decision 116 §4). Whether it may is a licence and clean-room ruling.

The model panel (one round):
- **C1, P20-A/B to a new phase1.14 item.** AGREE ×3. Kimi: name the cross-task dependency in the item text.
- **C2, the recording 2 residual to phase5.2_parity-report-tiers**, after recording 1 is exact, settled by a recording or entered as a decision-032 r2 divergence, with no exact claim on r2. AGREE ×3.
- **C3, the labels as a pending owner question** in phase1.24's metadata, which agents do not decide. AGREE, AGREE, PARTLY. GPT also wanted a phase1.24 checklist item; item 3.1 already names the question, so none was added.

## Decision

1. **phase1.14_compositor-core item 2.9** owns P20-A and P20-B.
   - It records both recordings, then fits `DEFAULT_SOURCES`, `default_bitmap_space`, `available_bitmap_spaces` and the float32 sRGB decode exactly.
   - Acceptance: every P20-A and P20-B output equals its golden in both recordings. The P20-A refusals and the `export-ocio-encode-legacy` `readback/get_source/29/BaseColor` exclusion are removed, and their tests become exact comparisons. `phase1-reload-resources` recording 1 s9 and s12 are exact.
   - The item is blocked only by the recordings.
2. **phase5.2_parity-report-tiers item 2.10** owns the recording 2 residual of `phase1-reload-resources` (s9, s12).
   - It starts after item 1 makes recording 1 exact.
   - If a Painter recording settles the rule, the residual is explained and compared.
   - Otherwise it is entered in `parity/exceptions.json` as a decision-032 r2 divergence (`api_readback`, the events of s9 and s12).
   - No exact parity is claimed on recording 2.
3. **The Dota 2 labels** are owner question q1 in `.rulebook/tasks/phase1.24_python-api-facade/.metadata.json`, which agents do not decide. The options are:
   - (a) ship generic labels;
   - (b) ship Painter's label text, after the owner's licence review.
   phase1.24 item 3.1 stays open on that question alone.

## Alternatives Considered

- **phase1.24 owns the reload residual itself.** Rejected: the residual is an oracle instability, and decision 032's register is phase5.2_parity-report-tiers' deliverable. phase1.24 would also wait on phase1.14 item 2.9.
- **An MCP task owns the residual.** Rejected: no MCP tool reloads resources, and an MCP fixture does not replay the facade probe.
- **Decide the labels.** Rejected: shipping Painter's text is the owner's clean-room and licence ruling.

## Consequences

- The report §3 and phase1.24 items 3.1 and 4.1 cite these owner items.
- phase1.24 item 3.1 waits only for the owner's answer to q1. Item 1.1 still waits on its prerequisites.
- No test or code changes. The named exclusions keep their tests, which require the outputs to still differ.
