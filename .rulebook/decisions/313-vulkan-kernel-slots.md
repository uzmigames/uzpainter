# 313. The compositor kernels compile to SPIR-V in the fixed-slot model of the vendored Vulkan layout: slots instead of heap indices, storage-buffer bindings added (UZP-MOD-013), push constants for the root constants, bounded dispatches per submission; product paths still refuse Vulkan

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.1_vulkan-compute-parity, phase1.4_render-core-layer, phase1.14_compositor-core

## Context

phase3.1 item 2.3 runs the generated compositor kernels (`src/evaluator/kernelgen.h`: blend, Levels, virtual normal, UV projection) as SPIR-V through the shared kernel cache, within the fixed-slot descriptor subset (`13-engine-integration.md` §2.3). The cache key already includes the target (`KernelKey`). Decision 310 qualified a device for three test kernels only. The compositor kernels did not fit the vendored Vulkan backend:

- They reach every resource through the SM 6.6 descriptor heap (`ResourceDescriptorHeap[index]`), with the indices in a parameter arena. The vendored backend has no heap: one descriptor set of 64 fixed bindings (16 sampled images, 16 samplers, 16 uniform buffers, 16 storage images).
- They read structured buffers (the parameter arena, the operand tables, the 192 MiB function tables, bitmap codes). The layout has no storage-buffer binding.
- Their storage images were untyped (`RWTexture2D<float4>` from the heap), which needs `shaderStorageImageWriteWithoutFormat`; the device does not enable it.
- They compute in `double` and 64-bit integers; the device enabled neither `shaderFloat64` nor `shaderInt64`.
- The vendored `SetRootConstants` keeps **one** scratch uniform buffer per root parameter per command list and overwrites it on each call, so every dispatch of a list reads the last values written. A flush records hundreds of dispatches in one list, each with its own block index.
- Each dispatch takes a descriptor snapshot from a pool that holds 128 at once (decision 310 §7). A failed allocation silently binds the shared working set.

## Decision

1. **Fixed slots on Vulkan, heap indices on DX12.** A kernel that defines `UZP_DST_FORMAT` compiles to SPIR-V with `UZP_FIXED_SLOTS` (`src/render/shaders/image_common.hlsli`): sampled images t0..t15, structured buffers at bindings 64..79, one storage image u0 declaring the destination tile's format. `LoadTexel`, `BufferWord`, `BufferFloat` and `StoreTexel` take a slot there and a heap index on DXIL, where the code is the same descriptor-heap access as before. `render::KernelBindings` (`src/render/kernel_bindings.h`) names each resource of a dispatch (heap index on DX12, slot on Vulkan) and records the slots before the dispatch. Every compositor kernel uses it (`GpuTileStore`).
2. **Root constants are push constants on Vulkan**, recorded with each dispatch (`SetDescriptorIndex`), never the vendored per-list scratch buffer.
3. **UZP-MOD-013** (vendored): 16 compute storage-buffer bindings at 64..79 (partially bound, not update-after-bind); `SetComputeSampledImage` and `SetComputeStorageBuffer`; snapshot failures counted (`DescriptorSetFailures`); `shaderFloat64` and `shaderInt64` enabled when supported; `UnmapBuffer` flushes host writes.
4. **Bounded submissions.** `IDevice::MaxDispatchesPerSubmission` is unbounded on DX12 and 61 on Vulkan (half the 128 snapshots, less the list's 3 working sets), so a flush is split into several submissions in queue order. The Vulkan queue refuses, before submitting it, a list with a failed snapshot (`resource_creation_failed`).
5. **Criteria** (decision 310 §3, extended to what these kernels use): `shaderFloat64`, `shaderInt64`; 16 update-after-bind storage buffers per stage and per set; 64 update-after-bind resources per stage; `maxStorageBufferRange` 4 GiB − 1; optimal-tiling `SAMPLED|STORAGE|TRANSFER_SRC|TRANSFER_DST` for the eight tile formats (R8, R16, R16F, R32F, RGBA8, RGBA16, RGBA16F, RGBA32F).
6. **Readback.** `TextureReadback` maps through `IDevice::MapReadback` (Vulkan invalidates first, decision 310 §5) and refuses `RGB32Float` on Vulkan by name (`ReadbackRefusal`; the RTX 4090 has no optimal tiling for it, decision 310 §8).
7. **Reach is unchanged.** `render::CreateDevice(Vulkan)` still refuses every product path. `EngineOptions::createDevice` is a test seam: only native tests set it, to run an engine on a qualified Vulkan device. No Painter-visible output runs on Vulkan and nothing here is parity evidence.

## Alternatives Considered

- **Descriptor-indexing bindless on Vulkan** (DXC's `ResourceDescriptorHeap` mapping): rejected for Phase 1 kernels by `13-…` §2.3, which keeps them in the fixed-slot subset; bindless is written for the path tracer.
- **Buffers packed into textures:** rejected; it changes the DX12 data layout and every kernel's indexing.
- **Fixing the vendored `SetRootConstants`:** not needed; push constants are the Vulkan mechanism and the pipeline layout already has 128 bytes of them.

## Consequences

- No model panel was run: the coordinator closed the session for task closure and the GPU window (00:10Z) before one could run.
- Evidence on the RTX 4090, all through pytest:
  - **DX12:** `kernel-sweep`, `masks-gpu-vs-cpu`, `height-normal-gpu-vs-cpu` and `projection-gpu-vs-cpu` still give GPU = CPU over the changed DXIL source.
  - **SPIR-V:** `vulkan-kernel-spirv` (no GPU) checks all 589 compositor kernels in the fixed-slot model.
  - **Vulkan blend:** `vulkan-kernel-sweep` covers every blend mode x channel format, with and without coverage, at opacities 1 and 0.7. It equals the CPU and DX12 bit for bit.
  - **Subnormals:** on 240 more combinations with subnormal float32 operands, Vulkan equals DX12 bit for bit. Both differ from the CPU reference on 172 of them: the GPU flushes subnormal float32 operands on DX12 and Vulkan alike, where the CPU keeps them.
    - That is a GPU-versus-CPU divergence of the DX12 product path. It is not Vulkan-specific, so no kernel is refused on Vulkan for it.
    - It is reported to the owner as a parity finding and not waived. The sweep prints it as a `KNOWN` line, and the DX12 sweep has no subnormal operands yet.
- **Reach on Vulkan is the blend kernels only.** The Levels, virtual normal, UV projection and raw-blend kernels compile to SPIR-V, but `GpuTileStore` refuses them on Vulkan by name (`unsupported_node`, NotYetSupported; tested by `vulkan-refusals`) until their sweeps run. Those cases evaluate through the engine's capability query, which phase3.1 item 2.6 wires.
- The blend sweep uses constant masks and no effect, coverage-weight or fused-read-out flags. Those runtime paths of the same kernels are compared on DX12 only.
- Open risk: each live command list keeps 3 working sets from the 128-set pool. Many concurrent readbacks reduce what a dispatch submission can get; the refusal makes that explicit, never silent.
