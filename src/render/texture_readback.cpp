#include "render/texture_readback.h"

#include "render/capabilities.h"

#include <algorithm>
#include <cstring>
#include <string>

namespace uzp::render {

std::optional<TexelLayout> ReadbackLayout(uz::RHIFormat format) {
    using F = uz::RHIFormat;
    switch (format) {
        case F::R8Unorm:     return TexelLayout{1, 1};
        case F::RG8Unorm:    return TexelLayout{2, 1};
        case F::RGBA8Unorm:
        case F::RGBA8Srgb:
        case F::BGRA8Unorm:
        case F::BGRA8Srgb:   return TexelLayout{4, 1};
        case F::R16Unorm:
        case F::R16Float:    return TexelLayout{1, 2};
        case F::RG16Unorm:
        case F::RG16Float:   return TexelLayout{2, 2};
        case F::RGBA16Unorm:
        case F::RGBA16Float: return TexelLayout{4, 2};
        case F::R32Float:
        case F::R32Uint:     return TexelLayout{1, 4};
        case F::RG32Float:
        case F::RG32Uint:    return TexelLayout{2, 4};
        case F::RGB32Float:  return TexelLayout{3, 4};
        case F::RGBA32Float:
        case F::RGBA32Uint:  return TexelLayout{4, 4};
        default:             return std::nullopt;
    }
}

std::optional<std::string> ReadbackRefusal(Backend backend, uz::RHIFormat format) {
    if (backend == Backend::Vulkan && format == uz::RHIFormat::RGB32Float) {
        return std::string(
            "RGB32Float (VK_FORMAT_R32G32B32_SFLOAT) is not read back on Vulkan: the qualified RTX 4090 "
            "has no optimal-tiling support for it (decision 310 §8)");
    }
    return std::nullopt;
}

TextureReadback::TextureReadback(EngineContext& context)
    : m_context(context), m_device(context.Device()) {}

TextureReadback::~TextureReadback() { static_cast<void>(Drain()); }

Result<ReadbackId> TextureReadback::Request(const ReadbackDesc& desc) {
    const Backend backend = m_device.GetBackend();
    const auto fail = [&](std::string reason) {
        return Fail(ErrorCode::RequestFailed, backend, "readback: " + std::move(reason));
    };

    // A removed device copies nothing: fail before anything is allocated.
    if (std::optional<Error> removed = m_device.CheckRemoved()) return Unexpected(*removed);
    const std::optional<uz::RHITextureDesc> texture = m_device.TextureDesc(desc.texture);
    if (!texture) return fail("the texture handle is invalid or the texture was destroyed");
    const std::string name = texture->debugName ? std::string(" '") + texture->debugName + "'"
                                                : std::string();
    const std::optional<TexelLayout> layout = ReadbackLayout(texture->format);
    if (!layout) {
        return fail("texture" + name + " has format " + std::string(FormatName(texture->format)) +
                    ", which is not read back (block-compressed and depth formats are not)");
    }
    if (const std::optional<std::string> refused = ReadbackRefusal(backend, texture->format)) {
        return fail("texture" + name + ": " + *refused);
    }
    if (!uz::HasFlag(texture->usage, uz::RHITextureUsage::CopySrc)) {
        return fail("texture" + name + " was not created with CopySrc usage");
    }
    const uint32_t mipLevels = std::max<uint32_t>(1, texture->mipLevels);
    if (desc.mipLevel >= mipLevels) {
        return fail("mip level " + std::to_string(desc.mipLevel) + " of texture" + name +
                    " with " + std::to_string(mipLevels) + " mip levels");
    }
    const uint32_t slices =
        texture->is3D ? std::max<uint32_t>(1, uint32_t{texture->depthOrArraySize} >> desc.mipLevel)
                      : std::max<uint32_t>(1, texture->depthOrArraySize);
    if (desc.arraySlice >= slices) {
        return fail("slice " + std::to_string(desc.arraySlice) + " of texture" + name + " with " +
                    std::to_string(slices) + " slices at mip " + std::to_string(desc.mipLevel));
    }
    const uint32_t channels = desc.channels == 0 ? layout->channels : desc.channels;
    if (channels > layout->channels) {
        return fail(std::to_string(channels) + " channels requested from texture" + name +
                    " of format " + std::string(FormatName(texture->format)) + ", which has " +
                    std::to_string(layout->channels));
    }

    Pending pending;
    pending.id = m_nextId;
    pending.format = texture->format;
    pending.layout = *layout;
    pending.channels = channels;
    pending.width = std::max(1u, texture->width >> desc.mipLevel);
    pending.height = std::max(1u, texture->height >> desc.mipLevel);
    pending.rowPitch =
        ReadbackRowPitch(uint64_t{pending.width} * layout->BytesPerTexel(), layout->BytesPerTexel());

    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = pending.rowPitch * pending.height;
    bufferDesc.usage = uz::RHIBufferUsage::CopyDst;
    bufferDesc.memory = uz::RHIMemoryType::Readback;
    bufferDesc.debugName = "uzp_texture_readback";
    Result<uz::RHIBufferHandle> staging = m_device.CreateBuffer(bufferDesc);
    if (!staging) return Unexpected(std::move(staging.error()));
    pending.staging = *staging;

    const uz::RHITextureHandle source = desc.texture;
    const uz::RHIResourceState state = desc.state;
    const uint32_t mip = desc.mipLevel;
    const uint32_t slice = desc.arraySlice;
    const auto pitch = static_cast<uint32_t>(pending.rowPitch);
    Result<uint64_t> fence = m_context.Submit([&](uz::IRHICommandList& cmd) {
        const bool transition = state != uz::RHIResourceState::CopySrc;
        if (transition) {
            const uz::RHIBarrierDesc toCopy{source, uz::RHIBufferHandle::Invalid(), state,
                                            uz::RHIResourceState::CopySrc};
            cmd.ResourceBarrier(&toCopy, 1);
        }
        cmd.CopyTextureToBuffer(source, mip, pending.staging, 0, pitch, slice);
        if (transition) {
            const uz::RHIBarrierDesc back{source, uz::RHIBufferHandle::Invalid(),
                                          uz::RHIResourceState::CopySrc, state};
            cmd.ResourceBarrier(&back, 1);
        }
    });
    if (!fence) {
        // Either nothing reached the GPU and the buffer can go at once, or the submission failed
        // after its command list was accepted: that device is then failed and its DestroyBuffer
        // keeps the buffer (vulkan_backend.h).
        m_device.DestroyBuffer(pending.staging);
        return Unexpected(std::move(fence.error()));
    }
    pending.fence = *fence;
    m_pending.push_back(pending);
    return m_nextId++;
}

Result<ReadbackImage> TextureReadback::Complete(ReadbackId id) {
    const auto found = std::find_if(m_pending.begin(), m_pending.end(),
                                    [id](const Pending& p) { return p.id == id; });
    if (found == m_pending.end()) {
        return Fail(ErrorCode::RequestFailed, m_device.GetBackend(),
                    "readback: request " + std::to_string(id) +
                        " is not outstanding (never requested, completed or drained)");
    }
    const Pending pending = *found;
    m_pending.erase(found);
    return Finish(pending);
}

std::vector<ReadbackOutcome> TextureReadback::Drain() {
    std::vector<ReadbackOutcome> outcomes;
    outcomes.reserve(m_pending.size());
    while (!m_pending.empty()) {
        const Pending pending = m_pending.front();
        m_pending.pop_front();
        outcomes.push_back({pending.id, Finish(pending)});
    }
    ReleaseHeldBack();
    return outcomes;
}

Result<ReadbackImage> TextureReadback::Finish(const Pending& pending) {
    Result<void> waited = m_context.Wait(pending.fence);
    if (!waited) {
        if (waited.error().code == ErrorCode::Timeout) {
            // The GPU may still write the buffer: it is released only once the copy completed.
            m_heldBack.emplace_back(pending.fence, pending.staging);
        } else {
            // A removed device executes nothing any more.
            m_device.DestroyBuffer(pending.staging);
        }
        return Unexpected(std::move(waited.error()));
    }

    uz::IRHIDevice& rhi = m_device.Rhi();
    const auto* mapped = static_cast<const std::byte*>(m_device.MapReadback(pending.staging));
    if (!mapped) {
        m_device.DestroyBuffer(pending.staging);
        return Fail(ErrorCode::RequestFailed, m_device.GetBackend(),
                    "readback: the staging buffer of request " + std::to_string(pending.id) +
                        " could not be mapped");
    }
    ReadbackImage image;
    image.format = pending.format;
    image.width = pending.width;
    image.height = pending.height;
    image.channels = pending.channels;
    image.bytesPerChannel = pending.layout.bytesPerChannel;
    image.texels.resize(image.RowBytes() * image.height);
    const size_t sourceTexel = pending.layout.BytesPerTexel();
    const size_t texel = image.TexelBytes();
    for (uint32_t y = 0; y < pending.height; ++y) {
        const std::byte* row = mapped + pending.rowPitch * y;
        std::byte* out = image.texels.data() + image.RowBytes() * y;
        if (texel == sourceTexel) {
            std::memcpy(out, row, image.RowBytes());
            continue;
        }
        for (uint32_t x = 0; x < pending.width; ++x) {
            std::memcpy(out + texel * x, row + sourceTexel * x, texel);
        }
    }
    rhi.UnmapBuffer(pending.staging);
    m_device.DestroyBuffer(pending.staging);
    return image;
}

void TextureReadback::ReleaseHeldBack() {
    if (m_heldBack.empty()) return;
    const bool removed = m_device.CheckRemoved().has_value();
    const uint64_t completed = m_device.Queue().Completed();
    std::erase_if(m_heldBack, [&](const std::pair<uint64_t, uz::RHIBufferHandle>& held) {
        if (!removed && completed < held.first) return false;
        m_device.DestroyBuffer(held.second);
        return true;
    });
}

}  // namespace uzp::render
