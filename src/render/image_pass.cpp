#include "render/image_pass.h"

#include "render/capabilities.h"

#include <utility>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kImageCommonHlsl[] = {
#embed "shaders/image_common.hlsli"
};
#pragma clang diagnostic pop

}  // namespace

std::optional<ImagePassFormat> ImagePassFormatOf(uz::RHIFormat format) {
    using F = uz::RHIFormat;
    using E = TexelEncoding;
    switch (format) {
        case F::R8Unorm: return ImagePassFormat{1, E::Unorm8};
        case F::RG8Unorm: return ImagePassFormat{2, E::Unorm8};
        case F::RGBA8Unorm: return ImagePassFormat{4, E::Unorm8};
        case F::R16Unorm: return ImagePassFormat{1, E::Unorm16};
        case F::RG16Unorm: return ImagePassFormat{2, E::Unorm16};
        case F::RGBA16Unorm: return ImagePassFormat{4, E::Unorm16};
        case F::R16Float: return ImagePassFormat{1, E::Float16};
        case F::RG16Float: return ImagePassFormat{2, E::Float16};
        case F::RGBA16Float: return ImagePassFormat{4, E::Float16};
        case F::R32Float: return ImagePassFormat{1, E::Float32};
        case F::RG32Float: return ImagePassFormat{2, E::Float32};
        case F::RGBA32Float: return ImagePassFormat{4, E::Float32};
        default: return std::nullopt;
    }
}

namespace image_pass_detail {

KernelInclude CommonInclude() {
    return KernelInclude{"image_common.hlsli",
                         std::string(kImageCommonHlsl, sizeof(kImageCommonHlsl))};
}

KernelSource Kernel(std::string name, std::string_view hlsl, std::string entryPoint,
                    std::vector<KernelInclude> extra) {
    KernelSource source;
    source.name = std::move(name);
    source.hlsl.assign(hlsl);
    source.entryPoint = std::move(entryPoint);
    source.includes.push_back(CommonInclude());
    for (KernelInclude& include : extra) source.includes.push_back(std::move(include));
    return source;
}

Unexpected Invalid(const IDevice& device, std::string reason) {
    return Fail(ErrorCode::RequestFailed, device.GetBackend(), std::move(reason));
}

Result<uz::RHITextureDesc> RequireTexture(IDevice& device, uz::RHITextureHandle texture,
                                          uz::RHITextureUsage usage, std::string_view role) {
    const std::string name(role);
    const std::optional<uz::RHITextureDesc> desc = device.TextureDesc(texture);
    if (!desc) return Invalid(device, "the " + name + " texture is not a live texture");
    if (desc->is3D || desc->depthOrArraySize != 1) {
        return Invalid(device, "the " + name + " texture is not a single 2D texture");
    }
    if ((static_cast<uint32_t>(desc->usage) & static_cast<uint32_t>(usage)) !=
        static_cast<uint32_t>(usage)) {
        return Invalid(device, "the " + name + " texture lacks a usage the pass needs");
    }
    if (!ImagePassFormatOf(desc->format)) {
        return Invalid(device, "the " + name + " texture's format " +
                                   std::string(FormatName(desc->format)) +
                                   " is not an image-pass format");
    }
    if (desc->width == 0 || desc->height == 0 || desc->width > kMaxImagePassDimension ||
        desc->height > kMaxImagePassDimension) {
        return Invalid(device, "the " + name + " texture's size is outside 1..16384");
    }
    return *desc;
}

Scratch::~Scratch() {
    if (m_keep) return;
    for (const uz::RHITextureHandle texture : m_textures) m_device.DestroyTexture(texture);
    for (const uz::RHIBufferHandle buffer : m_buffers) m_device.DestroyBuffer(buffer);
}

Result<uz::RHITextureHandle> Scratch::Texture(const uz::RHITextureDesc& desc) {
    Result<uz::RHITextureHandle> texture = m_device.CreateTexture(desc);
    if (texture) m_textures.push_back(*texture);
    return texture;
}

Result<uz::RHIBufferHandle> Scratch::Buffer(const uz::RHIBufferDesc& desc) {
    Result<uz::RHIBufferHandle> buffer = m_device.CreateBuffer(desc);
    if (buffer) m_buffers.push_back(*buffer);
    return buffer;
}

void Scratch::Settle(const Result<void>& done) {
    if (!done && done.error().code == ErrorCode::Timeout) m_keep = true;
}

uz::RHIBarrierDesc Transition(uz::RHITextureHandle texture, uz::RHIResourceState before,
                              uz::RHIResourceState after) {
    return uz::RHIBarrierDesc{texture, uz::RHIBufferHandle::Invalid(), before, after};
}

uz::RHIBarrierDesc Transition(uz::RHIBufferHandle buffer, uz::RHIResourceState before,
                              uz::RHIResourceState after) {
    return uz::RHIBarrierDesc{uz::RHITextureHandle::Invalid(), buffer, before, after};
}

}  // namespace image_pass_detail

}  // namespace uzp::render
