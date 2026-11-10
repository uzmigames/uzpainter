# Proposal: phase3.3_vulkan-backend-ray-tracing

## Why
The owner's platform decision (Q9, decision 022; PRD §17 constraints, OWN-08) makes Vulkan the second Windows GPU backend next to DX12, and VIS-06 and ARC-06 (`docs/prd.md`) require the clean-room path tracer on both DXR and Vulkan ray tracing. The vendored Vulkan backend covers compute, rasterisation and readback but has no acceleration structures or ray queries (`docs/architecture/13-engine-integration.md` §2.3), and the Vulkan hardware selftest was deferred to this node (`13-…` §4.2). This parent integration and acceptance task for DAG node P3-VULKAN implements D12 and D6 (`13-…` §2.3, §3.4, §4.1, §7; `docs/architecture/07-preview-and-render-parity.md` §3.5), split per the `docs/dag.md` task decomposition rule.

## What Changes
Integration of two mandatory children (DAG Outputs of P3-VULKAN):
- `phase3.1_vulkan-compute-parity`: the vendored Vulkan backend qualified for the compositor, export, readback and preview paths behind the backend-neutral interfaces of `src/render/`; backend selection by `--gpu-backend` with no silent fallback; Vulkan capability reporting; `selftest` Vulkan hardware slice.
- `phase3.2_vulkan-ray-tracing`: Vulkan ray tracing added by UzPainter (UZP-MOD-007): `VK_KHR_acceleration_structure` with `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`, inline ray queries in compute, no ray-tracing pipeline, behind the same abstraction as DXR; ray-cast fixtures compared with DXR.
- Parent-level outputs: the P3-VULKAN qualification report under `parity/reports/phase3/` (numbers and hashes only) and the regenerated capability manifest (`capabilities.json`) with backend and ray-query entries.

## Dependencies
- DAG inputs: `phase1.4_render-core-layer` (P1-CORE), `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Children (both mandatory): `phase3.1_vulkan-compute-parity`, then `phase3.2_vulkan-ray-tracing`.
- Downstream: `phase3.7_path-tracer` (P3-PATHTRACER) and the optional `phase4.3_dxr-baker` (P4-DXR).

## Acceptance
DAG gate of P3-VULKAN: `selftest` hardware slice green on Vulkan; the Tier 0 subset and the three pilot Tier 1 maps byte-equal on Vulkan and DX12; ray-cast fixtures compared with DXR and every difference reported; any divergence passes only as an owner-approved exception (decision 017; `parity/exceptions.json`). The parent closes only when both children are accepted.

## Impact
- Affected specs: vulkan
- Affected code: `src/render/` Vulkan backend, vendored Vulkan backend files (UZP-MOD-007), selftest, capability manifest, `parity/reports/phase3/`
- Breaking change: NO
- User benefit: every GPU feature, including the path tracer, can run on Vulkan with outputs proven equal to DX12 or every difference reported
