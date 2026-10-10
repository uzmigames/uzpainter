# Proposal: phase3.1_vulkan-compute-parity

## Why
The owner made Vulkan the second Windows GPU backend (Q9, decision 022; PRD §17 constraints, OWN-08, NFR-01) and requires texture outputs to be identical on both backends: Tiers 0–2 on Vulkan must equal DX12 byte for byte (`docs/architecture/14-parity-testing.md` §3; G-04). Phase 1 qualified the render-core layer on DX12 only, behind backend-neutral interfaces (`phase1.4_render-core-layer`), and the Vulkan hardware selftest was deferred to P3-VULKAN (`docs/architecture/13-engine-integration.md` §4.2). This child of P3-VULKAN (`phase3.3_vulkan-backend-ray-tracing`) qualifies the vendored Vulkan backend for the compositor, export, readback and preview paths, implementing D12 (`13-…` §2.3, §4.1, §6, §7) and the backend rules of D1 (`docs/architecture/02-runtime-topology.md` §1).

## What Changes
- Vulkan implementations of the backend-neutral render interfaces in `src/render/` (`backend.h`): device/queue wrapper with deadline waits returning `signaled|timeout|device_lost` (UZP-MOD-003 on Vulkan), SPIR-V kernels through the shared kernel cache, `TextureReadback` (per-request ownership, aligned pitch, fence-linked map, drain), UV raster pass, dilation, resampling and mip generation, all within the fixed-slot descriptor subset (`13-…` §2.3).
- Capability query on Vulkan: formats, usages, VRAM budget through `VK_EXT_memory_budget` when present and conservatively from heap sizes otherwise, descriptor capacities; tile admission budget derived from it (`13-…` §6); `VK_ERROR_DEVICE_LOST` reported as `device_removed {backend, reason}`.
- Compositor kernels, the export engine and the `painter_viewport` preview/capture path running on Vulkan through `--gpu-backend vulkan`; capture and export receipts record the backend.
- `UzPainter.exe selftest` Vulkan hardware slice (device, compute, SPIR-V kernel, readback, PNG16) qualified, reported separately from the Phase 0 availability probe.
- Cross-backend comparison under `parity/reports/phase3/` (numbers and hashes only): the Tier 0 subset implemented by the compositor and export engine, and every exported map of the three pilots (Wand v1, Belt v5, Tunic v10), DX12 vs Vulkan.
- Capability manifest (`capabilities.json`, `docs/architecture/10-python-api.md` §3) entries for the Vulkan backend with their tier evidence.

## Dependencies
- Prerequisites: `phase1.4_render-core-layer` (backend-neutral interfaces, DX12 qualification), `phase2.10_pilot-tunic-recovery` (pilot Tier 1 goldens and the qualified compositor/export/preview paths).
- Parent: `phase3.3_vulkan-backend-ray-tracing`. Unblocks `phase3.2_vulkan-ray-tracing`.

## Acceptance
`selftest` hardware slice green on Vulkan; the Tier 0 subset and the three pilot Tier 1 maps byte-equal on Vulkan and DX12; readback drain tests and compositor kernels identical on both backends (`13-…` §7); any divergence passes only as an owner-approved exception in `parity/exceptions.json` (`docs/dag.md` P3-VULKAN).

## Impact
- Affected specs: vulkan
- Affected code: `src/render/` Vulkan backend implementations, capability query, selftest Vulkan slice, `tests/render/`, cross-backend comparison reports
- Breaking change: NO
- User benefit: the same project produces the same texture bytes on DX12 and Vulkan, so either backend can be selected
