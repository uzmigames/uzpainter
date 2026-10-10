# Proposal: phase5.1_performance-budgets

## Why
P5-PERF in `docs/dag.md`, implementing D12 as specified in `docs/architecture/13-engine-integration.md` §6 (capacity and budgets), with the memory admission of `docs/architecture/04-layer-stack-and-compositing.md` §7 and the set-creation check of `docs/architecture/03-project-model.md` (decisions 021 and 022). Speed targets are set only after outputs are equal and are measured on a fixed corpus (NFR-05); the scale workloads of NFR-03 (three 4096² sets in one project, 30–45-layer stacks, more than twenty 4K 16-bit masks, up to seven delivered maps per set) must each be supported and measured separately; per-set resolutions 2048/4096 (8192 SHOULD) are admitted or refused explicitly against the VRAM budget (PRJ-03). The `docs/dag.md` gate rule requires performance tuning to finish before the release build is frozen, because `phase5.2_packaging` and `phase5.4_parity-report` both refer to that frozen build and any later change reopens them.

## What Changes
- Measurement harness for timing and memory on the certified corpus (wand v1, belt v5, tunic v10, bracer r9, hat v8, body v6b) on DX12 and on Vulkan, run locally on the owner's machine (decision 028; the local run report is the evidence): per operation (project open, stack evaluation, export, native bake, capture) wall time, peak VRAM, peak RAM, tiles admitted and evicted, and bytes written; every record carries hardware, driver, backend, build hash and resource hashes (`docs/architecture/14-parity-testing.md` §8).
- The NFR-03 workloads measured one at a time on the fixtures NFR-03 names: body v6b (three 4096² sets), bracer 21 and hat v8 (layer count), hat v6 (more than twenty 4K 16-bit masks), hat v8 (seven delivered maps per set).
- Admission policy tuned from the measurements: the tile admission budget derived at startup from the VRAM budget query (DXGI memory budget on DX12; `VK_EXT_memory_budget`, else heap sizes, on Vulkan), LRU eviction in dependency order, explicit refusal of texture-set creation above the budget, and the peak-RAM estimate made before high-poly ingestion (13 §6, 04 §7). Tuned constants are recorded with the evidence that produced them.
- Published budget report `parity/reports/phase5/budgets.json` (numbers and hashes only, no oracle bytes) naming the build hash it was measured on; the release build is frozen only after this report is accepted.

## Dependencies
- Prerequisite: `phase4.6_gate-g4` (G4, the DAG input of P5-PERF: hat v8 and body v6b Tier 1 equal, so budgets are measured on equal outputs).
- Followed by `phase5.2_packaging` and `phase5.4_parity-report` (both take P5-PERF as input and use the frozen build that follows it); joined by `phase5.6_gate-g5`.

## Acceptance
- Budgets published: the budget report exists in `parity/reports/phase5/` with timing and memory per fixture, operation and backend, each NFR-03 workload measured separately, and the tuned admission constants.
- The admission policy is tuned before the release build is frozen; the report names the build hash that `phase5.2_packaging` and `phase5.4_parity-report` then use.

## Impact
- Affected specs: `budgets` (measurement, admission policy, publication)
- Affected code: measurement harness and CLI entry, VRAM/RAM budget queries, tile admission and eviction, texture-set creation check, high-poly ingestion RAM estimate
- Breaking change: NO
- User benefit: known, published speed and memory limits; oversize requests refused up front instead of failing mid-evaluation
