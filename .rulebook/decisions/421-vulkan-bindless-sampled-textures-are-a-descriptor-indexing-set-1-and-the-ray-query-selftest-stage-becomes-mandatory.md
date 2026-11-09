# 421. Vulkan bindless sampled textures are a descriptor-indexing set 1, a live device without VK_KHR_ray_query is made by hiding the extension, and the ray-query selftest stage becomes mandatory

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.2_vulkan-ray-tracing, phase3.3_vulkan-backend-ray-tracing, phase3.7_path-tracer

## Context

`phase3.2_vulkan-ray-tracing` had four open items after decisions 372 and 373:

- 2.4: descriptor-indexing bindless on Vulkan for sampled textures, keeping the Phase 1 kernels on the fixed-slot subset (`13-engine-integration.md` §2.3). The path tracer's material textures need it: a dispatch reads more textures than the 16 fixed slots, by an index that varies per thread. DX12 already names a texture by its SRV index in the SM 6.6 descriptor heap.
- 2.13: Vulkan ray-query entries in the capability manifest.
- 3.2: a device without `VK_KHR_ray_query` reports unavailable with the missing list and dispatches nothing. Only fabricated capability records covered it; the owner's RTX 4090 exposes the extension.
- 4.1: acceptance, with the selftest's `vulkan-ray-query-trace` stage left non-mandatory by decision 310 §9 for this phase to settle.

## Decision

1. **Bindless set (UZP-MOD-007, vendored Vulkan device).** When the device has `descriptorIndexing`, `runtimeDescriptorArray`, `descriptorBindingPartiallyBound`, `shaderSampledImageArrayNonUniformIndexing`, `descriptorBindingSampledImageUpdateAfterBind` and `descriptorBindingUpdateUnusedWhilePending`, and the update-after-bind limits hold for set 0 plus the set's capacity, the device creates one descriptor set for its life:
   - set 1, binding 0;
   - 65,536 `SAMPLED_IMAGE` descriptors in the compute stage;
   - partially bound, update-after-bind and update-unused-while-pending;
   - in a pool of its own.

   The pipeline layout gains it as set 1, and `Begin` binds it for compute. Set 0, where the Phase 1 kernels keep their fixed slots (decision 313), is unchanged. `vkCreateDevice` also enables `descriptorBindingUpdateUnusedWhilePending` when supported. Without a feature or limit the set is not created and `BindlessMissing()` names every missing item; nothing falls back to the fixed slots.
2. **Names.** A single 2D colour texture with `ShaderResource` usage gets a slot when it is created. Its view is written once there, in `SHADER_READ_ONLY_OPTIMAL`. The slot is the texture's bindless name for its life. `DestroyTexture` releases the slot, and slots are reused oldest first. `render::BindlessTextureIndex` (`src/render/bindless.h`) gives that slot on Vulkan and the SRV heap index on DX12. `RequireBindlessTextures` refuses before any work with `gpu_backend_unavailable` naming every missing item. A kernel reads `ResourceDescriptorHeap[NonUniformResourceIndex(i)]` on DX12 and `[[vk::binding(0, 1)]] Texture2D<float4> t[]` indexed with `NonUniformResourceIndex` on Vulkan, in one HLSL file (`shaders/bindless_gather.hlsl`).
3. **Evidence for 2.4.** `uzp-render-tests bindless-textures` runs on both backends:
   - 40 RGBA32F textures of two mips, more than the 16 fixed slots, get 40 distinct names;
   - 160 shuffled lookups read each texel, mip size and level count bit for bit against the CPU values, twice byte-identical;
   - a destroyed texture has no name, its Vulkan slot goes to the next texture, and that texture reads its own texels;
   - a texture without `ShaderResource` usage has no name;
   - the SPIR-V declares `RuntimeDescriptorArray` and `ShaderNonUniform` and puts the array in set 1;
   - DX12 and Vulkan give byte-identical results.
4. **A live device without `VK_KHR_ray_query` (3.2).** No such device is on the machine, and the loader offers no portable way to hide one device extension. `uz::VulkanDevice::HideDeviceExtensionsForNextInit` is a test hook: the next `Init` treats the named optional extensions as not exposed. `render::VulkanDeviceOptions::hiddenDeviceExtensions` sets it, and product paths never do. `uzp-render-tests vulkan-ray-query-hidden` uses it to create a real device without `VK_KHR_ray_query`:
   - the query and the capability report name exactly that extension;
   - acceleration structures stay on;
   - `RequireInlineRayQuery`, `BuildRayScene` and `CastRays` fail as unavailable, naming the backend and the extension;
   - the queue's last submission is unchanged, so nothing was dispatched and nothing fell back.
5. **Capability manifest (2.13).** No public symbol depends on Vulkan ray queries before the path tracer. The entry is `uzpainter.render.capture` in context `mode:painter_iray:backend:vulkan`, a release gap. Its notes cite the qualified prerequisite: the selftest stage and `parity/reports/phase3/ray-cast.json`. A gap has no Tier 0 evidence, and Painter has no ray-query API to record one. The capability conformance test proves the refusal through the same call as the `mode:painter_iray` entry, which is refused before the process's backend is consulted.
6. **Selftest.** As decision 310 §9 did for the compute stages at phase3.1's acceptance, `vulkan-ray-query-trace` becomes mandatory at this phase's acceptance. A Vulkan device without inline ray queries now fails `selftest`. It still skips under `--no-gpu`/`UZP_NO_GPU=1`. The PRD's Vulkan backend (Q9, decision 022) includes the ray-query extensions for the path tracer.

## Alternatives Considered

- **Make `ResourceDescriptorHeap` itself work in SPIR-V (DXC `-fvk-bind-resource-heap`).** Rejected for now: it needs a new vendored shader-compiler option, and it aliases every resource type at one binding. The explicit set-1 array keeps one descriptor type and the same HLSL file, with a `__spirv__` branch, as `ray_cast.hlsl` already has.
- **A binding of set 0 holding the array.** Rejected: each dispatch copies set 0 into a snapshot (decision 310 §7), so a 65,536-entry binding would be copied per dispatch.
- **Variable descriptor count.** Not needed: the capacity is fixed, and partially bound covers unwritten slots.
- **Leave 3.2 on fabricated records.** Rejected: the item asks that no work be dispatched, which only a live device shows.

## Consequences

- Phase 1 kernels and their results are unchanged. The fixed-slot Vulkan suites (`test_vulkan_qualification.py`, `test_vulkan_image_passes.py`) and the selftest are re-run on the new layout.
- No validation layer is installed on the owner's machine, so the bindless descriptor use is checked by its results, not by validation.
- The path tracer (`phase3.7_path-tracer`) names its material textures through `render::BindlessTextureIndex`.
