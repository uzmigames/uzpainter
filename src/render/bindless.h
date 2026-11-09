#pragma once

// Bindless sampled textures on both backends (phase3.2_vulkan-ray-tracing item 2.4;
// docs/architecture/13-engine-integration.md §2.3; decision 421).
//
// - DX12: a sampled texture's bindless name is its SRV index in the SM 6.6 descriptor heap
//   (`GetTextureSRVIndex`); a kernel reads it through `ResourceDescriptorHeap`.
// - Vulkan: the vendored device (UZP-MOD-007) keeps one bindless descriptor set, set 1, whose
//   binding 0 is an array of `uz::VulkanDevice::kBindlessTextureCapacity` sampled images
//   (descriptor indexing: partially bound, update-after-bind, update-unused-while-pending). A 2D
//   colour texture created with `ShaderResource` usage gets a slot there for its whole life, written
//   once at creation; the slot is its bindless name, and a kernel reads it through a runtime array
//   declared at `[[vk::binding(0, 1)]]`. The set is bound with every compute command list.
//
// Phase 1 kernels keep the fixed-slot model on Vulkan (`kernel_bindings.h`, decision 313): set 0
// is unchanged. Bindless names are for kernels that index many textures, the path tracer's
// material textures first. A device without the features or limits reports them missing and is
// refused before any work (`RequireBindlessTextures`); nothing falls back to the fixed slots.
//
// The texture a kernel reads must be in the `ShaderResource` state (Vulkan: the descriptor's
// layout is SHADER_READ_ONLY_OPTIMAL), as for the fixed slots. Threading: as for every `IDevice`,
// one thread.

#include "render/backend.h"

#include <array>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::render {

struct BindlessSupport {
    Backend backend = Backend::Dx12;
    bool available = false;
    /// How many textures may hold a bindless name at once (DX12: the heap's descriptors).
    uint32_t capacity = 0;
    std::vector<std::string> missing;  ///< What keeps bindless textures off, by name.
};

[[nodiscard]] BindlessSupport QueryBindlessTextures(IDevice& device);

/// Empty when the device gives sampled textures bindless names; otherwise
/// `gpu_backend_unavailable {backend, reason}` naming every missing item.
[[nodiscard]] Result<void> RequireBindlessTextures(IDevice& device);

/// The bindless name of a live 2D texture created with `ShaderResource` usage (Vulkan: a colour
/// format, one array layer); `request_failed` naming why otherwise.
[[nodiscard]] Result<uint32_t> BindlessTextureIndex(IDevice& device, uz::RHITextureHandle texture);

// ── Gather kernel (the qualification of the bindless path) ───────────────────

/// One lookup of the gather kernel (16 bytes, `Lookup` in shaders/bindless_gather.hlsl).
struct TexelLookup {
    uint32_t texture = 0;  ///< A bindless name (`BindlessTextureIndex`).
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t mip = 0;
};

/// One result (32 bytes, `Gathered` in shaders/bindless_gather.hlsl).
struct GatheredTexel {
    std::array<float, 4> value = {};
    uint32_t width = 0;   ///< The lookup's mip level size.
    uint32_t height = 0;
    uint32_t levels = 0;  ///< The texture's mip-level count.
    uint32_t pad = 0;
};

/// The gather kernel's HLSL (shaders/bindless_gather.hlsl).
[[nodiscard]] std::string_view BindlessGatherHlsl();

/// The gather kernel compiled by DXC for `target` (cs_6_6 DXIL or SPIR-V), or
/// `kernel_compile_failed`.
[[nodiscard]] Result<std::vector<uint8_t>> CompileBindlessGatherKernel(KernelTarget target,
                                                                       const std::filesystem::path& dxcompiler);

/// SPIR-V capabilities a bindless kernel declares: `RuntimeDescriptorArray` (the unsized array)
/// and `ShaderNonUniform` (the per-thread index); `InspectSpirv` (vulkan_kernels.h) lists them.
inline constexpr uint32_t kSpirvCapabilityShaderNonUniform = 5301;
inline constexpr uint32_t kSpirvCapabilityRuntimeDescriptorArray = 5302;

/// Runs `kernel` (from `CompileBindlessGatherKernel` for the device) over `lookups`, after
/// requiring bindless textures, and returns one result per lookup; at most 65535 x 64 lookups (one
/// dispatch), `request_failed` beyond. Every texture a lookup names must be live and in the
/// `ShaderResource` state. A failed wait returns the device's `WaitFailure` and leaves the buffers
/// to the failed device.
[[nodiscard]] Result<std::vector<GatheredTexel>> GatherTexels(IDevice& device, const ComputeKernel& kernel,
                                                              std::span<const TexelLookup> lookups,
                                                              Deadline deadline);

}  // namespace uzp::render
