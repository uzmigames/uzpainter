# 367. Three coordinated fronts with a native lock and a model panel

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase1.25_pilot-wand, phase3.2_vulkan-ray-tracing

## Context

On 2026-11-02 the owner asked to resume implementation with several agents in parallel, using the 9router models (`cx/gpt-6-astra`, `cx/gpt-6.1-sol`, `xai/grok-4.6`, `kimi/kimi-k3`) to decide by consensus, without questions to the owner. Painter is busy with another session, so no oracle recording can run now. Agents share one checkout and decision 041 allows one `zig build` at a time with no native edit during it.

## Decision

Panel result: all four agree on fronts and on front C; all four say "partly" on lock scope and ask for a stricter one.

1. **Front A, Wand padding** (`phase1.25_pilot-wand` item 2.7, critical path to G1): re-measure the Wand after decision 366 first, then 2-hour hypothesis cycles, each checked against the Wand and all 29 kernel probes with zero new misses. A cycle that does not shrink the residual ends with a characterization that separates "hypothesis wrong" from "implementation wrong" and with the next discriminating Painter probe request.
2. **Front B, Vulkan ray query** (`phase3.2_vulkan-ray-tracing`): start with the smallest capability-gated BLAS/TLAS ray-query selftest, checked against CPU-computed known answers, not only against DX12.
3. **Front C, Painter recording batch**: a Python compiler and offline validator over the committed recorder requests that emits one prioritized, resumable batch (Wand discriminating probes first), so the next Painter slot records everything pending.
4. **Native lock.** `python -m tools.native_lock` holds `tmp/scratch/native-build.lock` from an agent's first C++, header, shader or `build.zig` edit until its build and tests end. Front A goes first when both wait. Analysis and Python work stay outside the lock.
5. **Commits.** Each front commits only its own exact paths (`git commit --only -- <paths>`), never `git add -A` or another front's files; the coordinator reconciles.
6. **External models** produce hypotheses and review frozen diffs. Tests, not reviewer approval, are the evidence.

Decision numbers reserved: front A 368-371, front B 372-375, front C 376-379.

## Consequences

Native throughput stays serial; the parallelism is in analysis, Python tooling and review. Parity exceptions remain the owner's alone (2026-10-18), so the panel never waives a residual.
