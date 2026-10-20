#pragma once

// How a compute dispatch names the resources it reads and writes, on either backend (decision 313;
// docs/architecture/13-engine-integration.md §2.3).
//
// - DX12: kernels reach resources through the SM 6.6 descriptor heap, so a resource's name is
//   its heap index (`GetTextureSRVIndex`, `GetBufferSRVIndex`, `GetTextureUAVIndex`) and nothing
//   is bound per dispatch; the root constants are root parameter 0 (b0).
// - Vulkan: the vendored backend has one descriptor set of fixed bindings and no heap. A
//   resource's name is its slot in this dispatch: sampled images t0..t15, structured buffers at
//   bindings 64..79 (UZP-MOD-013) and the one storage image u0; `Record` writes the slots before
//   the dispatch, whose descriptor snapshot then holds them. The root constants are push
//   constants, recorded with the dispatch: the vendored b0 emulation keeps one buffer per root
//   parameter per command list, so every dispatch of a list would read the last values written.
//
// Kernels that take their names this way are the ones whose SPIR-V is compiled in the fixed-slot
// model (`UZP_FIXED_SLOTS` in shaders/image_common.hlsli). One `KernelBindings` describes one
// dispatch; it is filled when the dispatch is queued and recorded when it is.

#include "render/backend.h"

#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace uzp::render {

/// Slots of each class on Vulkan: the vendored layout's 16 bindings per class.
inline constexpr uint32_t kVulkanTextureSlots = 16;
inline constexpr uint32_t kVulkanBufferSlots = 16;

class KernelBindings {
public:
    explicit KernelBindings(IDevice& device);

    /// The name of `texture` read as a sampled image (`LoadTexel`). The same texture keeps one
    /// name within a dispatch.
    uint32_t Texture(uz::RHITextureHandle texture);
    /// The name of `buffer` read as a structured buffer of uints (`BufferWord`).
    uint32_t Buffer(uz::RHIBufferHandle buffer);
    /// The name of the texture the dispatch writes (`StoreTexel`); one per dispatch.
    uint32_t Output(uz::RHITextureHandle texture);

    /// Empty when every resource has a name; `request_failed` naming the class that ran out of
    /// slots (Vulkan) or a second output otherwise. Checked before anything is recorded.
    [[nodiscard]] Result<void> Validate() const;

    /// Records the bindings (Vulkan: the slots; DX12: nothing) and the dispatch's root
    /// constants, after `SetPipeline` and before `Dispatch`.
    void Record(uz::IRHICommandList& cmd, std::span<const uint32_t> rootConstants) const;

private:
    IDevice* m_device = nullptr;
    Backend m_backend = Backend::Dx12;
    std::vector<uz::RHITextureHandle> m_textures;
    std::vector<uz::RHIBufferHandle> m_buffers;
    uz::RHITextureHandle m_output = uz::RHITextureHandle::Invalid();
    std::string m_overflow;
};

}  // namespace uzp::render
