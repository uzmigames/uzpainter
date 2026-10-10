## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4

## 2. Implementation
- [ ] 2.1 Measurement harness: per-operation wall time, peak VRAM, peak RAM, tiles admitted/evicted and bytes written, each record tagged with hardware, driver, backend, build hash and resource hashes
- [ ] 2.2 Corpus runs on DX12 and Vulkan locally on the owner's machine (decision 028; local run report as evidence) for wand v1, belt v5, tunic v10, bracer r9, hat v8 and body v6b, only on fixtures whose Tier 1 outputs are equal
- [ ] 2.3 NFR-03 workloads measured separately: body v6b three 4096² sets; bracer 21 and hat v8 layer stacks; hat v6 masks (more than twenty 4K 16-bit); hat v8 seven delivered maps per set
- [ ] 2.4 VRAM budget query per backend (DXGI memory budget on DX12; `VK_EXT_memory_budget`, else heap sizes, on Vulkan) and the derived tile admission budget tuned from the measurements
- [ ] 2.5 Texture-set creation above the budget refused with an explicit error at creation time (2048, 4096 and 8192 per-set resolutions)
- [ ] 2.6 Peak-RAM estimate before high-poly ingestion compared with the measured peak; estimate constants tuned
- [ ] 2.7 Budget report `parity/reports/phase5/budgets.json` (numbers and hashes only) with the tuned constants, the evidence behind each and the build hash measured

## 3. Tests
- [ ] 3.1 VRAM admission test: a texture set whose resolution exceeds the budget is refused explicitly before any GPU allocation; sets within the budget are created
- [ ] 3.2 Body v6b: the three 4096² sets evaluate and export in sequence within the tuned budget on both backends
- [ ] 3.3 Repeatability under eviction: hat v8 exports with the default budget and with a lowered budget that forces LRU eviction are byte-identical
- [ ] 3.4 Budget report validates against its schema on the hosted CPU lane and contains no file whose hash is in the private store index (repository guard)

## 4. Acceptance
- [ ] 4.1 Budgets published in `parity/reports/phase5/` and accepted; admission tuning complete before the release build is frozen; frozen build hash handed to `phase5.2_packaging` and `phase5.4_parity-report`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
