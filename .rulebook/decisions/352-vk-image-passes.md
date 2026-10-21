# 352. The image passes run on Vulkan in the fixed-slot model: one storage image per dispatch, `main` entry points, copies and remainders that do not depend on vendored or driver gaps

**Status**: accepted
**Date**: 2026-10-21
**Related Tasks**: phase3.1_vulkan-compute-parity

## Context

Items 2.5 and 3.2 port the UV raster, jump-flood dilation, resampling and mip generation to Vulkan with the same HLSL sources, byte-equal to DX12. The four kernels reached their resources through `ResourceDescriptorHeap`, which the vendored Vulkan backend lacks. Its one descriptor set has sampled images t0..t15, storage buffers 64..79 (UZP-MOD-013) and, through the root layout, the single storage image u0 (decision 313). `vulkan_backend.*` and the vendored code stay unchanged. Four further gaps showed on the RTX 4090 (driver 617.14):

1. The vendored backend creates every compute pipeline with entry point `main` (`vulkan_resources.cpp`), and SPIR-V keeps the HLSL function's name. Every kernel with another entry point failed at `vkCreateComputePipelines` (`VK_ERROR_UNKNOWN`).
2. The vendored Vulkan command list does not implement `CopyTextureRegion`. The RHI's default is a silent no-op, so the mip copies, dilation's initial colour copy and the resample identity copy did nothing.
3. Bilinear `Repeat` wrapped texel -1 of a 300-texel row to 195. That is (2^32 - 1) mod 300, an unsigned remainder. The SPIR-V is a signed `OpSRem` on int32; DX12 gives the signed remainder.
4. The sphere's bitangent differed in 23 320 bytes at 512 x 512. The plane and the cube, whose frames are axis-aligned, matched. In SPIR-V, `cross` is `GLSL.std.450 Cross`, an extended instruction that the `-Gis` NoContraction decorations do not reach. In DXIL it is separate multiplies and subtracts.

## Decision

1. **Fixed slots for the image passes.** On Vulkan, `image_pass_detail::ForDevice` compiles a kernel with `UZP_DST_FORMAT` of the image it writes, or `UZP_NO_STORAGE_IMAGE`, and with `UZP_RW_BUFFERS` when it writes structured buffers (`RwWord`, `RwStore`, `RwAdd`; the two-channel formats got DST codes). Root constants become push constants. Resources are named through `KernelBindings`, which gains `RwBuffer`: the UAV index on DX12, a slot on Vulkan. DX12 keeps its kernels and its dispatch sequence.
2. **One storage image per dispatch.** The UV raster is compiled per output buffer on Vulkan (`UZP_UV_OUTPUT`): ClearMain and CoverMain for the triangle ids and the mask, then ResolveMain for the six attribute buffers. The resolve reads the triangle ids as sampled image t0. Ten dispatches, from the same code as the DX12 three.
3. **Submissions.** Mip generation fills consecutive levels into further submissions when a level would exceed `MaxDispatchesPerSubmission`. A 512 x 512 alpha-coverage chain takes 65 dispatches. DX12 keeps one submission.
4. **Entry points.** On Vulkan a kernel whose entry point is not `main` gets the define `<entry>=main` and entry point `main` (`VulkanEntryPoint`).
5. **Copies.** `CopyMip`: `CopyTextureRegion` on DX12; on Vulkan, `CopyTexture` for mip 0 and a staging buffer (`CopyTextureToBuffer`, `CopyBufferToTexture`) for another mip.
6. **Remainders and cross products.** `Wrap` takes the floored remainder from non-negative operands only. The UV raster's bitangent uses `Cross`, separate IEEE products and differences. Both are integer or IEEE identities of the previous code, so DX12 results stay the same.
7. **Not lifted.** `render::CreateDevice(Vulkan)` still refuses every product path (decision 310). The tests use the native-test seam `EngineOptions::createDevice`, and none of this is parity evidence for a Painter-visible output.

## Consequences

- Evidence (tests/render/test_vulkan_image_passes.py):
  - The plane, sphere and bevelled cube rasterised at 512 x 512 and 300 x 200 match DX12 byte for byte in all eight buffers.
  - Dilation (six formats, distance 8 and unlimited), resampling (14 filter, wrap and colour cases, down and up) and mip chains (sRGB, linear, normal, alpha coverage) on those rasters match DX12 byte for byte, and DX12 matches the CPU reference.
  - Logs are in `tmp/scratch/vk-image-passes/` (untracked).
- The unsigned-remainder and fused-cross behaviours are driver findings, reported here and not waived. Other kernels that take a signed `%` of a negative value, or use `cross`, on Vulkan must avoid them the same way.
