## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.1_vulkan-compute-parity accepted
- [ ] 2.2 phase3.2_vulkan-ray-tracing accepted

## 3. Integration
- [ ] 3.1 Run `selftest` on the owner's machine with both backends: DX12 slice, Vulkan hardware slice and Vulkan ray-query slice green; availability probes reported separately
- [ ] 3.2 Run the Tier 0 subset and the Wand v1, Belt v5 and Tunic v10 Tier 1 exports on DX12 and Vulkan from the same build; confirm byte equality of every decoded map
- [ ] 3.3 Run the ray-cast fixtures on DXR and Vulkan from the same build; collect every per-ray difference
- [ ] 3.4 Propose an exception entry for each remaining divergence (domain backend pair, metric, bound, evidence, defect-detection test); none counts until the owner approves it
- [ ] 3.5 Publish the P3-VULKAN qualification report under `parity/reports/phase3/` (numbers and hashes only; build hash, adapter, driver; exceptions relied on listed)
- [ ] 3.6 Regenerate the capability manifest with the Vulkan backend and Vulkan ray-query entries `supported` or listed as release gaps

## 4. Acceptance
- [ ] 4.1 Acceptance: Vulkan selftest hardware slice green; Tier 0 subset and pilot Tier 1 maps byte-equal on Vulkan and DX12; ray-cast fixtures compared with DXR with every difference reported; every divergence an owner-approved exception; both children accepted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
