#include "render/kernel_bindings.h"

#include "vulkan_command_list.h"

#include <algorithm>

namespace uzp::render {

namespace {

template <class Handle>
uint32_t Slot(std::vector<Handle>& slots, Handle handle, uint32_t capacity, const char* what,
              std::string& overflow) {
    const auto found = std::find(slots.begin(), slots.end(), handle);
    if (found != slots.end()) return static_cast<uint32_t>(found - slots.begin());
    if (slots.size() >= capacity) {
        if (overflow.empty()) {
            overflow = std::string("a dispatch reads more than ") + std::to_string(capacity) + " " + what +
                       " (the vendored Vulkan layout's fixed slots, decision 313)";
        }
        return capacity - 1;
    }
    slots.push_back(handle);
    return static_cast<uint32_t>(slots.size() - 1);
}

}  // namespace

KernelBindings::KernelBindings(IDevice& device) : m_device(&device), m_backend(device.GetBackend()) {}

uint32_t KernelBindings::Texture(uz::RHITextureHandle texture) {
    if (m_backend == Backend::Dx12) return m_device->Rhi().GetTextureSRVIndex(texture);
    return Slot(m_textures, texture, kVulkanTextureSlots, "sampled textures", m_overflow);
}

uint32_t KernelBindings::Buffer(uz::RHIBufferHandle buffer) {
    if (m_backend == Backend::Dx12) return m_device->Rhi().GetBufferSRVIndex(buffer);
    return Slot(m_buffers, buffer, kVulkanBufferSlots, "structured buffers", m_overflow);
}

uint32_t KernelBindings::RwBuffer(uz::RHIBufferHandle buffer) {
    if (m_backend == Backend::Dx12) return m_device->Rhi().GetBufferUAVIndex(buffer);
    return Slot(m_buffers, buffer, kVulkanBufferSlots, "structured buffers", m_overflow);
}

uint32_t KernelBindings::Output(uz::RHITextureHandle texture) {
    if (m_output.IsValid() && !(m_output == texture) && m_overflow.empty()) {
        m_overflow = "a dispatch writes more than one texture";
    }
    m_output = texture;
    if (m_backend == Backend::Dx12) return m_device->Rhi().GetTextureUAVIndex(texture);
    return 0;  // u0
}

Result<void> KernelBindings::Validate() const {
    if (!m_overflow.empty()) return Fail(ErrorCode::RequestFailed, m_backend, m_overflow);
    return {};
}

void KernelBindings::Record(uz::IRHICommandList& cmd, std::span<const uint32_t> rootConstants) const {
    if (m_backend == Backend::Dx12) {
        cmd.SetRootConstants(kRootConstantsParam, rootConstants.data(), static_cast<uint32_t>(rootConstants.size()));
        return;
    }
    // Every IRHICommandList of a Vulkan device is the vendored VulkanCommandList.
    auto& vk = static_cast<uz::VulkanCommandList&>(cmd);
    for (size_t i = 0; i < m_textures.size(); ++i) vk.SetComputeSampledImage(static_cast<uint32_t>(i), m_textures[i]);
    for (size_t i = 0; i < m_buffers.size(); ++i) vk.SetComputeStorageBuffer(static_cast<uint32_t>(i), m_buffers[i]);
    if (m_output.IsValid()) vk.SetDescriptorTable(kUavTableParam, m_device->Rhi().GetTextureUAVIndex(m_output));
    // Push constants at 4-byte offsets 0, 4, ... (`SetDescriptorIndex` on Vulkan).
    for (size_t i = 0; i < rootConstants.size(); ++i) vk.SetDescriptorIndex(static_cast<uint32_t>(i), rootConstants[i]);
}

}  // namespace uzp::render
