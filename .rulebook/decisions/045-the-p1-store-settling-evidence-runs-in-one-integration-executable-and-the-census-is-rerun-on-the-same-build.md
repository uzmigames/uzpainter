# 45. The P1-STORE settling evidence runs in one integration executable, and the census is rerun on the same build

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.8_project-store

## Context

`phase1.8_project-store` is the parent of P1-STORE. Its items 3.1-3.5 ask for the settling evidence of `docs/architecture/09-project-file-format.md` §7 "end to end on one store build". Item 3.6 asks for the census on tunic v10, hat v8 and body content. The four children are implemented. Their native suites already cover each §7 fault on its own, in three executables that each compile the same store sources with the test-only fault hooks. `phase1.7_store-inspect-census` produced `parity/reports/phase1/store-census.json` with `UzPainter.exe store-census`. That command reads only the `.spp` file sizes and never opens Painter. Children `phase1.6` and `phase1.7` wait only on the hosted CPU lane, which needs the owner's push.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 One new integration executable (`uzp-store-settle-tests`) holds items 3.1-3.5; the child suites stay | AGREE x1, PARTLY x2: the wording does not force a new executable; it is justified because a chained multi-fault lifecycle on one file cannot be run in the child executables |
| C2 The cases are integration scenarios on richer content, with recovery checked as whole-history equality | AGREE x1, PARTLY x2: newly committed states need expected pixels computed independently; report that 3.2 and 3.3 deepen child scenarios rather than add new ones |
| C3 Item 3.1 is one continuous lifecycle; corruption is applied to copies | PARTLY x3: compare against a snapshot after each step so a failure can be located; check what compaction removes, not only what it keeps; copies must not change the file's layout |
| C4 Item 3.6 is met by rerunning the census CLI on the same build; the full-content census stays in phase4.1 | AGREE x2, PARTLY x1: record the build identity and the `not_measured` content; do not present `.spp` size as a measurement of its content |
| C5 Item 4.1 and children 2.3/2.4 stay unchecked until the hosted run; the parent is not archived | AGREE x2, PARTLY x1: say it is a policy hold |

Overall: GPT and Grok PARTLY (approve with constraints), Kimi AGREE.

## Decision

1. `tests/store/settle_test.cpp` builds one executable, `zig build uzp-store-settle-tests`, with one case per parent item 3.1-3.5, driven by `tests/store/test_store_settle.py`. The child suites are unchanged.
2. Every case works on the same content: a resource bound to a fill layer and two 2048×2048 sRGB8 paint planes on one channel and tile. Recovery is whole-file equality: per revision the manifest bytes, the pixel and resource digests, and the checkpoint and operation rows.
   - After each fault step the file is compared with the snapshot taken before that step.
   - Strokes committed after a recovery are compared with pixels computed independently (`Stroke(Synthetic(seed), …)`).
   - Compaction is checked for what it keeps (retained states equal), for what it removes (collapsed revisions; full reachability of planes, versions and blobs) and for the bytes it saves.
3. Corruption is applied to byte copies (`std::filesystem::copy_file`) of the closed project, so the layout is the original's.
4. Item 3.6 reruns `UzPainter.exe store-census` with `src/store/census_inputs.json` on the build that ran items 3.1-3.5. Its numbers and `not_measured` lists go into `parity/reports/phase1/project-store.md`. `store-census.json` stays phase1.7's report, because the repository guard allows one census report per phase. No Painter is involved.
5. Items 2.3, 2.4 and 4.1 stay unchecked, as a policy hold, until the hosted CPU lane shows children `phase1.6` and `phase1.7` (and the new settle tests) green. The parent is not archived.

## Consequences

- The §7 evidence for G1 comes from one executable built from one commit, and it is reproducible with `python -m pytest tests/store/test_store_settle.py`.
- The report says that items 3.2 and 3.3 deepen scenarios the children already have: richer content and whole-file equality.
