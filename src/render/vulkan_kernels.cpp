#include "render/vulkan_kernels.h"

#include "render/texture_readback.h"
#include "render/vulkan_backend.h"

#include "shader_compiler.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstring>

namespace uzp::render {

namespace {

// SPIR-V `ImageFormat` values (SPIR-V specification §3.11).
constexpr uint32_t kSpirvR32f = 3;
constexpr uint32_t kSpirvR16f = 9;
constexpr uint32_t kSpirvR32ui = 33;

constexpr const char* kPattern16 = R"(
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
};
[[vk::image_format("r16f")]] RWTexture2D<float> g_output : register(u0);

uint PatternValue(uint x, uint y) {
    uint v = (x * 0x9E37u + y * 0x7F4Au + 0x1234u) & 0xFFFFu;
    if (((v >> 10) & 0x1Fu) == 0x1Fu) v ^= 0x4000u;
    return v;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    g_output[id.xy] = f16tof32(PatternValue(id.x, id.y));
}
)";

constexpr const char* kHash32 = R"(
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
};
[[vk::image_format("r32ui")]] RWTexture2D<uint> g_output : register(u0);

uint Hash(uint x, uint y) {
    uint h = (x * 0x9E3779B1u) ^ ((y + 0x7F4A7C15u) * 0x85EBCA77u);
    h ^= h >> 15;
    h *= 0x2C1B3C6Du;
    h ^= h >> 12;
    h = (h << 7) | (h >> 25);
    return h + (x ^ y);
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    g_output[id.xy] = Hash(id.x, id.y);
}
)";

constexpr const char* kIeee32 = R"(
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
};
[[vk::image_format("r32f")]] RWTexture2D<float> g_output : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    float a = float(id.x) * 0.1f;
    float b = float(id.y) * 0.7f;
    float c = float(id.x ^ id.y) * 0.3f;
    g_output[id.xy] = (a + b) - c;
}
)";

uint32_t Pattern16(uint32_t x, uint32_t y) {
    uint32_t v = (x * 0x9E37u + y * 0x7F4Au + 0x1234u) & 0xFFFFu;
    if (((v >> 10) & 0x1Fu) == 0x1Fu) v ^= 0x4000u;
    return v;
}

uint32_t Hash32(uint32_t x, uint32_t y) {
    uint32_t h = (x * 0x9E3779B1u) ^ ((y + 0x7F4A7C15u) * 0x85EBCA77u);
    h ^= h >> 15;
    h *= 0x2C1B3C6Du;
    h ^= h >> 12;
    h = (h << 7) | (h >> 25);
    return h + (x ^ y);
}

uint32_t Ieee32(uint32_t x, uint32_t y) {
    // One rounded IEEE operation per statement; `volatile` keeps the compiler from contracting
    // or reassociating them.
    volatile float a = static_cast<float>(x) * 0.1f;
    volatile float b = static_cast<float>(y) * 0.7f;
    volatile float c = static_cast<float>(x ^ y) * 0.3f;
    volatile float sum = a + b;
    volatile float result = sum - c;
    return std::bit_cast<uint32_t>(static_cast<float>(result));
}

std::string Hex(uint32_t value, int digits) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%0*X", digits, value);
    return buf;
}

}  // namespace

const std::vector<VulkanQualificationKernel>& VulkanQualificationKernels() {
    static const std::vector<VulkanQualificationKernel> kernels = {
        {"pattern16", kPattern16, uz::RHIFormat::R16Float, 2, kSpirvR16f, true, false, Pattern16},
        {"hash32", kHash32, uz::RHIFormat::R32Uint, 4, kSpirvR32ui, false, false, Hash32},
        {"ieee32", kIeee32, uz::RHIFormat::R32Float, 4, kSpirvR32f, false, true, Ieee32},
    };
    return kernels;
}

Result<std::vector<uint8_t>> CompileVulkanKernel(const VulkanQualificationKernel& kernel,
                                                 const std::filesystem::path& dxcompiler) {
    uz::ShaderCompiler compiler;
    if (!compiler.Init(dxcompiler.string())) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt, "DXC failed to load from " + dxcompiler.string());
    }
    uz::ShaderCompileDesc desc;
    desc.source = kernel.source;
    desc.sourceName = std::string("vulkan_") + kernel.name + ".hlsl";
    desc.stage = uz::ShaderStageCompile::Compute;
    desc.model = uz::ShaderModelCompile::SM6_6;
    desc.output = uz::ShaderOutputFormat::SPIRV;
    desc.ieeeStrict = kernel.ieeeStrict;
    uz::ShaderCompileResult result = compiler.Compile(desc);
    uint32_t magic = 0;
    if (result.success && result.bytecode.size() >= 4) std::memcpy(&magic, result.bytecode.data(), 4);
    if (!result.success || magic != 0x07230203u) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    std::string("kernel ") + kernel.name + " to SPIR-V: " +
                        (result.errors.empty() ? "no SPIR-V module" : result.errors));
    }
    return std::move(result.bytecode);
}

bool SpirvFacts::HasCapability(uint32_t capability) const {
    return std::find(capabilities.begin(), capabilities.end(), capability) != capabilities.end();
}

std::vector<uint32_t> SpirvFacts::UnqualifiedCapabilities() const {
    std::vector<uint32_t> out;
    for (const uint32_t capability : capabilities) {
        if (capability != kSpirvCapabilityShader && capability != kSpirvCapabilityStorageImageExtendedFormats &&
            capability != kSpirvCapabilitySignedZeroInfNanPreserve) {
            out.push_back(capability);
        }
    }
    return out;
}

SpirvFacts InspectSpirv(const std::vector<uint8_t>& spirv) {
    SpirvFacts facts;
    std::vector<uint32_t> words(spirv.size() / 4);
    if (!words.empty()) std::memcpy(words.data(), spirv.data(), words.size() * 4);
    constexpr uint32_t kOpCapability = 17;
    constexpr uint32_t kOpDecorate = 71;
    constexpr uint32_t kOpTypeImage = 25;
    constexpr uint32_t kNoContraction = 42;
    constexpr uint32_t kBinding = 33;
    constexpr uint32_t kDescriptorSet = 34;
    for (size_t i = 5; i < words.size();) {
        const uint32_t length = words[i] >> 16;
        const uint32_t opcode = words[i] & 0xFFFF;
        if (length == 0 || i + length > words.size()) break;
        if (opcode == kOpCapability && length >= 2) facts.capabilities.push_back(words[i + 1]);
        if (opcode == kOpDecorate && length >= 3 && words[i + 2] == kNoContraction) ++facts.noContraction;
        if (opcode == kOpDecorate && length >= 4 && words[i + 2] == kDescriptorSet) facts.descriptorSets.push_back(words[i + 3]);
        if (opcode == kOpDecorate && length >= 4 && words[i + 2] == kBinding) facts.bindings.push_back(words[i + 3]);
        // OpTypeImage: result, sampled type, dim, depth, arrayed, MS, sampled, format.
        if (opcode == kOpTypeImage && length >= 9) facts.imageFormats.push_back(words[i + 8]);
        i += length;
    }
    return facts;
}

Result<KernelReadback> DispatchQualificationKernel(VulkanDevice& device, const VulkanQualificationKernel& kernel,
                                                   const ComputeKernel& compiled, uint32_t width, uint32_t height,
                                                   std::chrono::milliseconds deadline) {
    KernelReadback out;
    out.width = width;
    out.height = height;
    out.rowPitch = ReadbackRowPitch(uint64_t{width} * kernel.bytesPerTexel, kernel.bytesPerTexel);

    uz::RHITextureDesc textureDesc;
    textureDesc.width = width;
    textureDesc.height = height;
    textureDesc.format = kernel.format;
    textureDesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
    textureDesc.debugName = kernel.name;
    Result<uz::RHITextureHandle> texture = device.CreateTexture(textureDesc);
    if (!texture) return Unexpected(texture.error());
    const uint32_t uav = device.Rhi().GetTextureUAVIndex(*texture);
    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = out.rowPitch * height;
    bufferDesc.usage = uz::RHIBufferUsage::CopyDst;
    bufferDesc.memory = uz::RHIMemoryType::Readback;
    bufferDesc.debugName = "vulkan_qualification_readback";
    Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(bufferDesc);
    if (!buffer) {
        device.DestroyTexture(*texture);
        return Unexpected(buffer.error());
    }
    const auto release = [&] {
        device.DestroyBuffer(*buffer);
        device.DestroyTexture(*texture);
    };

    const uint32_t constants[2] = {width, height};
    const auto pitch = static_cast<uint32_t>(out.rowPitch);
    Result<uint64_t> fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toUav{*texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::Common,
                                       uz::RHIResourceState::UnorderedAccess};
        cmd.ResourceBarrier(&toUav, 1);
        cmd.SetPipeline(compiled.pipeline);
        cmd.SetRootConstants(kRootConstantsParam, constants, 2);
        cmd.SetDescriptorTable(kUavTableParam, uav);
        cmd.Dispatch((width + 7) / 8, (height + 7) / 8, 1);
        const uz::RHIBarrierDesc toCopy{*texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::UnorderedAccess,
                                        uz::RHIResourceState::CopySrc};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyTextureToBuffer(*texture, 0, *buffer, 0, pitch);
    });
    if (!fence) {
        // A refused command list never ran; after a partial submission the failed device's
        // Destroy* keep both objects (vulkan_backend.h).
        release();
        return Unexpected(fence.error());
    }
    out.fenceValue = *fence;
    const WaitResult wait = device.Queue().Wait(*fence, Clock::now() + deadline);
    if (wait.status != WaitStatus::Signaled) return Unexpected(device.WaitFailure(wait));

    const auto* mapped = static_cast<const unsigned char*>(device.MapReadback(*buffer));
    if (!mapped) {
        release();
        return Fail(ErrorCode::RequestFailed, Backend::Vulkan, "the readback buffer is not host-visible");
    }
    out.values.resize(static_cast<size_t>(width) * height);
    for (uint32_t y = 0; y < height; ++y) {
        const unsigned char* row = mapped + out.rowPitch * y;
        for (uint32_t x = 0; x < width; ++x) {
            uint32_t value = 0;
            std::memcpy(&value, row + static_cast<size_t>(x) * kernel.bytesPerTexel, kernel.bytesPerTexel);
            out.values[static_cast<size_t>(y) * width + x] = value;
            const uint32_t expected = kernel.expected(x, y);
            if (value != expected && out.mismatches++ == 0) {
                const int digits = static_cast<int>(kernel.bytesPerTexel * 2);
                out.firstMismatch = "(" + std::to_string(x) + ", " + std::to_string(y) + "): got " +
                                    Hex(value, digits) + ", expected " + Hex(expected, digits);
            }
        }
    }
    release();
    return out;
}

}  // namespace uzp::render
