# Proposal: phase4.2_dxr-dx12-rt

## Why
The optional `GpuBaker` has a DX12 backend, `dx12_rt`: DXR Tier 1.1 with SM 6.5 `RayQuery` compute kernels, whose capability check the vendored copy extends from Tier 1.0 to Tier 1.1 (`docs/architecture/06-baking.md` §1; `docs/architecture/13-engine-integration.md` §2.3, §3.4). The DAG requires each backend to be qualified separately against the Embree outputs and the Painter goldens — same outputs, or a divergence approved through the exception register (`docs/dag.md` P4-DXR; decision 017, Q1). BAK-03 and BAK-07 (`docs/prd.md`) define the settings and the accounting the backend must honour; Tier 2b defines the corpus and the comparison order (hit/coverage evidence first, then maps; `docs/architecture/14-parity-testing.md` §3; `06-…` §7). GPU baker qualification runs on the owner's self-hosted GPU runner (`14-…` §7; decision 022, Q9). Child of P4-DXR (`phase4.3_dxr-baker`), implementing D5.

## What Changes
- **`dx12_rt` backend** on the `GpuBaker` seam: feature detection (`D3D12_FEATURE_D3D12_OPTIONS5` with `RaytracingTier ≥ D3D12_RAYTRACING_TIER_1_1`, SM 6.5 `RayQuery` under the SM 6.6 application baseline), BLAS/TLAS build through the vendored DXR primitives, DXIL ray-query kernels; no DXR pipeline state objects, shader tables or `DispatchRays`.
- **Qualification run** on the Tier 2b corpus (analytic plane, sphere, bevelled cube with highs; the wand and hat low/high/cage pairs; the ten usages): `dx12_rt` vs `embree` texel for texel, and vs the private Painter CPU-bake goldens; repeated across runs on the same build and GPU; manifests under `parity/manifests/tier2b/gpu-dx12-rt/`.
- **Qualification report** `parity/reports/phase4/` (numbers only): per usage and fixture, hit/coverage agreement then map equality, max/mean/p99 Δ and differing-texel counts; exception proposals for any divergence, which pass only once the owner approves them.
- **Capability-manifest status** for `dx12_rt`: `supported` only after qualification.

## Dependencies
- Parent DAG inputs: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing`.
- Previous child: `phase4.1_dxr-gpu-baker-core`.
- Parent: `phase4.3_dxr-baker`. Independent of `phase4.2_dxr-vulkan-rt`.

## Acceptance
Part of the optional P4-DXR gate. `dx12_rt` is qualified when, on the whole Tier 2b corpus, its outputs equal the Embree outputs and the Painter goldens, or every divergence is covered by an owner-approved exception; it is repeatable on one build and GPU; and a device without DXR Tier 1.1 receives an explicit capability error.

## Impact
- Affected specs: `baker` (DX12 GPU baker backend)
- Affected code: Baker component (`dx12_rt` backend, DXIL bake kernels, feature detection); `parity/manifests/tier2b/gpu-dx12-rt/`; `parity/reports/phase4/`; capability manifest
- Breaking change: NO
- User benefit: a qualified DX12 GPU bake path
