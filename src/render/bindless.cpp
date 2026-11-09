// Bindless sampled textures on both backends (phase3.2_vulkan-ray-tracing item 2.4, decision 421).

#include "render/bindless.h"

#include "render/device.h"
#include "render/vulkan_backend.h"

#include "dx12_device.h"
#include "shader_compiler.h"
#include "vulkan_command_list.h"
#include "vulkan_device.h"

#include <algorithm>
#include <cstring>
#include <utility>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kBindlessGatherHlsl[] = {
#embed "shaders/bindless_gather.hlsl"
};
#pragma clang diagnostic pop

constexpr uint32_t kLookupsPerGroup = 64;
constexpr uint64_t kMaxLookups = uint64_t{65535} * kLookupsPerGroup;
constexpr uint32_t kLookupBytes = sizeof(TexelLookup);
constexpr uint32_t kGatheredBytes = sizeof(GatheredTexel);
static_assert(kLookupBytes == 16 && kGatheredBytes == 32);

std::string Join(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) out += (out.empty() ? "" : ", ") + item;
    return out;
}

Unexpected Invalid(Backend backend, const std::string& why) { return Fail(ErrorCode::RequestFailed, backend, why); }

uz::VulkanDevice& NativeVulkan(IDevice& device) { return static_cast<uz::VulkanDevice&>(device.Rhi()); }

void DestroyBuffers(IDevice& device, std::vector<uz::RHIBufferHandle>& buffers) {
    for (const uz::RHIBufferHandle buffer : buffers) device.DestroyBuffer(buffer);
    buffers.clear();
}

}  // namespace

BindlessSupport QueryBindlessTextures(IDevice& device) {
    BindlessSupport support;
    support.backend = device.GetBackend();
    if (support.backend == Backend::Vulkan) {
        uz::VulkanDevice& native = NativeVulkan(device);
        support.available = native.SupportsBindlessTextures();
        support.capacity = support.available ? uz::VulkanDevice::kBindlessTextureCapacity : 0;
        support.missing = native.BindlessMissing();
        if (!support.available && support.missing.empty()) support.missing.emplace_back("bindless texture set (device)");
        return support;
    }
    auto& dx12 = static_cast<Dx12Device&>(device);
    D3D12_FEATURE_DATA_SHADER_MODEL shaderModel{D3D_SHADER_MODEL_6_6};
    const bool sm66 =
        SUCCEEDED(dx12.D3D12()->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &shaderModel, sizeof(shaderModel))) &&
        shaderModel.HighestShaderModel >= D3D_SHADER_MODEL_6_6;
    if (!sm66) support.missing.emplace_back("Shader Model 6.6");
    support.available = sm66;
    support.capacity = sm66 ? uz::kMaxCbvSrvUavDescriptors : 0;
    return support;
}

Result<void> RequireBindlessTextures(IDevice& device) {
    const BindlessSupport support = QueryBindlessTextures(device);
    if (support.available) return {};
    return Fail(ErrorCode::GpuBackendUnavailable, support.backend,
                "bindless textures are unavailable on " + device.AdapterName() + ": missing " + Join(support.missing) +
                    "; nothing was dispatched and nothing falls back");
}

Result<uint32_t> BindlessTextureIndex(IDevice& device, uz::RHITextureHandle texture) {
    const Backend backend = device.GetBackend();
    if (Result<void> required = RequireBindlessTextures(device); !required) return Unexpected(required.error());
    const std::optional<uz::RHITextureDesc> desc = device.TextureDesc(texture);
    if (!desc) return Invalid(backend, "the texture is not a live texture");
    if (desc->is3D || desc->depthOrArraySize != 1) return Invalid(backend, "the texture is not a single 2D texture");
    if (!uz::HasFlag(desc->usage, uz::RHITextureUsage::ShaderResource)) {
        return Invalid(backend, "the texture was not created with ShaderResource usage");
    }
    const uint32_t index = backend == Backend::Vulkan ? NativeVulkan(device).GetTextureBindlessIndex(texture)
                                                      : device.Rhi().GetTextureSRVIndex(texture);
    if (index == UINT32_MAX) {
        return Invalid(backend, backend == Backend::Vulkan
                                    ? "the texture has no bindless slot (a depth format, or the set was full when "
                                      "it was created)"
                                    : "the texture has no SRV heap index");
    }
    return index;
}

std::string_view BindlessGatherHlsl() { return {kBindlessGatherHlsl, sizeof(kBindlessGatherHlsl)}; }

Result<std::vector<uint8_t>> CompileBindlessGatherKernel(KernelTarget target, const std::filesystem::path& dxcompiler) {
    uz::ShaderCompiler compiler;
    if (!compiler.Init(dxcompiler.string())) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt, "DXC failed to load from " + dxcompiler.string());
    }
    const std::string source(BindlessGatherHlsl());
    uz::ShaderCompileDesc desc;
    desc.source = source;
    desc.sourceName = "bindless_gather.hlsl";
    desc.stage = uz::ShaderStageCompile::Compute;
    desc.model = uz::ShaderModelCompile::SM6_6;
    desc.output = target == KernelTarget::Spirv ? uz::ShaderOutputFormat::SPIRV : uz::ShaderOutputFormat::DXIL;
    uz::ShaderCompileResult result = compiler.Compile(desc);
    if (!result.success || result.bytecode.empty()) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    "bindless_gather.hlsl to " + std::string(KernelTargetName(target)) + ": " +
                        (result.errors.empty() ? "no bytecode" : result.errors));
    }
    return std::move(result.bytecode);
}

Result<std::vector<GatheredTexel>> GatherTexels(IDevice& device, const ComputeKernel& kernel,
                                                std::span<const TexelLookup> lookups, Deadline deadline) {
    const Backend backend = device.GetBackend();
    if (Result<void> required = RequireBindlessTextures(device); !required) return Unexpected(required.error());
    if (lookups.empty()) return std::vector<GatheredTexel>{};
    if (lookups.size() > kMaxLookups) {
        return Invalid(backend, std::to_string(lookups.size()) + " lookups exceed the " + std::to_string(kMaxLookups) +
                                    " one dispatch reads");
    }
    const uint64_t lookupBytes = uint64_t{lookups.size()} * kLookupBytes;
    const uint64_t resultBytes = uint64_t{lookups.size()} * kGatheredBytes;

    std::vector<uz::RHIBufferHandle> buffers;
    const auto release = [&] { DestroyBuffers(device, buffers); };
    const auto create = [&](uint64_t bytes, uint32_t stride, uz::RHIBufferUsage usage, uz::RHIMemoryType memory,
                            const char* name) -> Result<uz::RHIBufferHandle> {
        uz::RHIBufferDesc desc;
        desc.sizeBytes = bytes;
        desc.stride = stride;
        desc.usage = usage;
        desc.memory = memory;
        desc.debugName = name;
        Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(desc);
        if (buffer) buffers.push_back(*buffer);
        return buffer;
    };
    Result<uz::RHIBufferHandle> lookupBuffer = create(lookupBytes, kLookupBytes, uz::RHIBufferUsage::StructuredBuffer,
                                                      uz::RHIMemoryType::Upload, "bindless_lookups");
    if (!lookupBuffer) {
        release();
        return Unexpected(lookupBuffer.error());
    }
    void* mapped = device.Rhi().MapBuffer(*lookupBuffer);
    if (!mapped) {
        release();
        return Fail(ErrorCode::ResourceCreationFailed, backend, "bindless_lookups is not mappable");
    }
    std::memcpy(mapped, lookups.data(), lookupBytes);
    device.Rhi().UnmapBuffer(*lookupBuffer);  // flushes non-coherent memory (UZP-MOD-013)
    Result<uz::RHIBufferHandle> results =
        create(resultBytes, kGatheredBytes,
               uz::RHIBufferUsage::UnorderedAccess | uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopySrc,
               uz::RHIMemoryType::Default, "bindless_results");
    if (!results) {
        release();
        return Unexpected(results.error());
    }
    Result<uz::RHIBufferHandle> readback =
        create(resultBytes, 0, uz::RHIBufferUsage::CopyDst, uz::RHIMemoryType::Readback, "bindless_readback");
    if (!readback) {
        release();
        return Unexpected(readback.error());
    }

    const auto count = static_cast<uint32_t>(lookups.size());
    Result<uint64_t> fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        using State = uz::RHIResourceState;
        const uz::RHIBarrierDesc toUav{uz::RHITextureHandle::Invalid(), *results, State::Common, State::UnorderedAccess};
        cmd.ResourceBarrier(&toUav, 1);
        cmd.SetPipeline(kernel.pipeline);
        if (backend == Backend::Vulkan) {
            auto& vk = static_cast<uz::VulkanCommandList&>(cmd);
            vk.SetComputeStorageBuffer(0, *lookupBuffer);
            vk.SetComputeStorageBuffer(1, *results);
            const uint32_t constants[4] = {count, 0, 1, 0};
            for (uint32_t i = 0; i < 4; ++i) vk.SetDescriptorIndex(i, constants[i]);  // push constants
        } else {
            const uint32_t constants[4] = {count, device.Rhi().GetBufferSRVIndex(*lookupBuffer),
                                           device.Rhi().GetBufferUAVIndex(*results), 0};
            cmd.SetRootConstants(kRootConstantsParam, constants, 4);
        }
        cmd.Dispatch((count + kLookupsPerGroup - 1) / kLookupsPerGroup, 1, 1);
        const uz::RHIBarrierDesc toCopy{uz::RHITextureHandle::Invalid(), *results, State::UnorderedAccess,
                                        State::CopySrc};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyBuffer(*results, 0, *readback, 0, resultBytes);
    });
    if (!fence) {
        release();
        return Unexpected(fence.error());
    }
    const WaitResult wait = device.Queue().Wait(*fence, deadline);
    if (wait.status != WaitStatus::Signaled) return Unexpected(device.WaitFailure(wait));  // the failed device keeps them
    const void* view = device.MapReadback(*readback);
    if (!view) {
        release();
        return Fail(ErrorCode::RequestFailed, backend, "the gather readback buffer is not host-visible");
    }
    std::vector<GatheredTexel> out(lookups.size());
    std::memcpy(out.data(), view, resultBytes);
    release();
    return out;
}

}  // namespace uzp::render
