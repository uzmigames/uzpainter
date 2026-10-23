#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/capabilities.h"

#include "render/device.h"
#include "render/vulkan_backend.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "dx12_resource_creation.h"
#include "rhi_config.h"

#include <windows.h>

#include <algorithm>
#include <cstdio>
#include <utility>

namespace uzp::render {

namespace {

using Microsoft::WRL::ComPtr;

struct NamedFormat {
    uz::RHIFormat format;
    const char* name;
};

/// Every texel format of the vendored RHI.
constexpr NamedFormat kFormats[] = {
    {uz::RHIFormat::R8Unorm, "R8Unorm"},
    {uz::RHIFormat::RG8Unorm, "RG8Unorm"},
    {uz::RHIFormat::RGBA8Unorm, "RGBA8Unorm"},
    {uz::RHIFormat::RGBA8Srgb, "RGBA8Srgb"},
    {uz::RHIFormat::BGRA8Unorm, "BGRA8Unorm"},
    {uz::RHIFormat::BGRA8Srgb, "BGRA8Srgb"},
    {uz::RHIFormat::R16Float, "R16Float"},
    {uz::RHIFormat::RG16Float, "RG16Float"},
    {uz::RHIFormat::RGBA16Float, "RGBA16Float"},
    {uz::RHIFormat::R32Float, "R32Float"},
    {uz::RHIFormat::RG32Float, "RG32Float"},
    {uz::RHIFormat::RGB32Float, "RGB32Float"},
    {uz::RHIFormat::RGBA32Float, "RGBA32Float"},
    {uz::RHIFormat::R32Uint, "R32Uint"},
    {uz::RHIFormat::RG32Uint, "RG32Uint"},
    {uz::RHIFormat::RGBA32Uint, "RGBA32Uint"},
    {uz::RHIFormat::BC1Unorm, "BC1Unorm"},
    {uz::RHIFormat::BC1Srgb, "BC1Srgb"},
    {uz::RHIFormat::BC3Unorm, "BC3Unorm"},
    {uz::RHIFormat::BC3Srgb, "BC3Srgb"},
    {uz::RHIFormat::BC4Unorm, "BC4Unorm"},
    {uz::RHIFormat::BC5Unorm, "BC5Unorm"},
    {uz::RHIFormat::BC7Unorm, "BC7Unorm"},
    {uz::RHIFormat::BC7Srgb, "BC7Srgb"},
    {uz::RHIFormat::D16Unorm, "D16Unorm"},
    {uz::RHIFormat::D32Float, "D32Float"},
    {uz::RHIFormat::D24UnormS8Uint, "D24UnormS8Uint"},
    {uz::RHIFormat::D32FloatS8Uint, "D32FloatS8Uint"},
    {uz::RHIFormat::R16Unorm, "R16Unorm"},
    {uz::RHIFormat::RG16Unorm, "RG16Unorm"},
    {uz::RHIFormat::RGBA16Unorm, "RGBA16Unorm"},
};

std::string Utf8(const wchar_t* wide) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string out(static_cast<size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide, -1, out.data(), size, nullptr, nullptr);
    return out;
}

std::string JsonString(std::string_view text) {
    std::string out = "\"";
    for (const unsigned char c : text) {
        if (c == '"' || c == '\\') {
            out += '\\';
            out += static_cast<char>(c);
        } else if (c < 0x20) {
            char buf[8];
            std::snprintf(buf, sizeof(buf), "\\u%04x", c);
            out += buf;
        } else {
            out += static_cast<char>(c);
        }
    }
    return out + "\"";
}

const char* JsonBool(bool value) { return value ? "true" : "false"; }

std::string Hex(uint32_t value, int digits) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%0*X", digits, value);
    return buf;
}

FormatCapability QueryFormat(ID3D12Device* device, const NamedFormat& named) {
    FormatCapability format;
    format.format = named.format;
    format.name = named.name;
    D3D12_FEATURE_DATA_FORMAT_SUPPORT support{};
    support.Format = uz::ToDxgiFormat(named.format);
    if (support.Format == DXGI_FORMAT_UNKNOWN ||
        FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &support,
                                           sizeof(support)))) {
        return format;
    }
    const auto has1 = [&](D3D12_FORMAT_SUPPORT1 flag) { return (support.Support1 & flag) != 0; };
    const auto has2 = [&](D3D12_FORMAT_SUPPORT2 flag) { return (support.Support2 & flag) != 0; };
    format.texture2D = has1(D3D12_FORMAT_SUPPORT1_TEXTURE2D);
    format.shaderResource = format.texture2D && has1(D3D12_FORMAT_SUPPORT1_SHADER_LOAD);
    format.sample = format.texture2D && has1(D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE);
    format.renderTarget = format.texture2D && has1(D3D12_FORMAT_SUPPORT1_RENDER_TARGET);
    format.depthStencil = format.texture2D && has1(D3D12_FORMAT_SUPPORT1_DEPTH_STENCIL);
    format.unorderedAccess = format.texture2D &&
                             has1(D3D12_FORMAT_SUPPORT1_TYPED_UNORDERED_ACCESS_VIEW) &&
                             has2(D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE);
    format.unorderedAccessLoad = format.unorderedAccess && has2(D3D12_FORMAT_SUPPORT2_UAV_TYPED_LOAD);
    return format;
}

Result<CapabilityReport> QueryDx12(Dx12Device& device, const AdmissionPolicy& policy) {
    uz::DX12Device& native = device.Native();
    ID3D12Device* d3d12 = device.D3D12();
    CapabilityReport report;
    report.backend = Backend::Dx12;
    report.featureLevel = native.GetFeatureLevel();
    report.shaderModel = uz::ShaderModelToString(native.GetShaderModel());
    report.rayTracing = native.SupportsRayTracing();
    report.rayQuery = native.SupportsInlineRayQuery();

    // The adapter of the device, by LUID. DirectX-Headers declare struct-returning methods in
    // their out-parameter form for non-MSVC compilers.
    LUID luid{};
    d3d12->GetAdapterLuid(&luid);
    ComPtr<IDXGIAdapter3> adapter;
    HRESULT hr = native.GetFactory()->EnumAdapterByLuid(luid, IID_PPV_ARGS(&adapter));
    if (FAILED(hr)) {
        return Fail(ErrorCode::GpuBackendUnavailable, Backend::Dx12,
                    "the device's DXGI adapter was not found, hr=" +
                        Hex(static_cast<uint32_t>(hr), 8));
    }
    DXGI_ADAPTER_DESC1 desc{};
    adapter->GetDesc1(&desc);
    report.adapter = Utf8(desc.Description);
    LARGE_INTEGER driver{};
    if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &driver))) {
        const uint64_t version = static_cast<uint64_t>(driver.QuadPart);
        report.driver = std::to_string(version >> 48) + "." + std::to_string((version >> 32) & 0xFFFF) + "." +
                        std::to_string((version >> 16) & 0xFFFF) + "." + std::to_string(version & 0xFFFF);
    }
    report.vendorId = desc.VendorId;
    report.deviceId = desc.DeviceId;
    report.softwareAdapter = (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0;
    report.vram.dedicatedVideoMemoryBytes = desc.DedicatedVideoMemory;
    report.vram.sharedSystemMemoryBytes = desc.SharedSystemMemory;

    DXGI_QUERY_VIDEO_MEMORY_INFO memory{};
    hr = adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &memory);
    if (FAILED(hr)) {
        return Fail(ErrorCode::GpuBackendUnavailable, Backend::Dx12,
                    "the DXGI video memory budget query failed, hr=" +
                        Hex(static_cast<uint32_t>(hr), 8));
    }
    report.vram.budgetBytes = memory.Budget;
    report.vram.usageBytes = memory.CurrentUsage;

    // The heap sizes the vendored device creates (dx12_device.h).
    report.descriptors.shaderResources = uz::kMaxCbvSrvUavDescriptors;
    report.descriptors.samplers = uz::kMaxSamplerDescriptors;
    report.descriptors.renderTargets = uz::kMaxRtvDescriptors;
    report.descriptors.depthStencils = uz::kMaxDsvDescriptors;
    D3D12_FEATURE_DATA_D3D12_OPTIONS options{};
    if (SUCCEEDED(d3d12->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS, &options,
                                             sizeof(options)))) {
        report.descriptors.resourceBindingTier = static_cast<uint32_t>(options.ResourceBindingTier);
    }

    for (const NamedFormat& named : kFormats) report.formats.push_back(QueryFormat(d3d12, named));

    report.policy = policy;
    report.admission = DeriveAdmissionBudget(report.vram, report.descriptors, policy);
    return report;
}

}  // namespace

std::vector<std::string_view> FormatCapability::Usages() const {
    std::vector<std::string_view> usages;
    if (texture2D) usages.push_back("copy");
    if (shaderResource) usages.push_back("shader_resource");
    if (sample) usages.push_back("sample");
    if (renderTarget) usages.push_back("render_target");
    if (depthStencil) usages.push_back("depth_stencil");
    if (unorderedAccess) usages.push_back("unordered_access");
    if (unorderedAccessLoad) usages.push_back("unordered_access_load");
    return usages;
}

uint64_t AdmissionBudget::MaxLiveTiles(uint64_t bytesPerTile) const {
    if (bytesPerTile == 0) return 0;
    return std::min(bytes / bytesPerTile, maxTilesByDescriptors);
}

AdmissionBudget DeriveAdmissionBudget(const VramReport& vram,
                                      const DescriptorCapacities& descriptors,
                                      const AdmissionPolicy& policy) {
    AdmissionBudget budget;
    const uint64_t free = vram.budgetBytes > vram.usageBytes ? vram.budgetBytes - vram.usageBytes : 0;
    const uint64_t usable = free > policy.reserveBytes ? free - policy.reserveBytes : 0;
    const uint64_t percent = std::min<uint64_t>(policy.budgetPercent, 100);
    // usable / 100 * percent + remainder term: exact, and cannot overflow 64 bits.
    budget.bytes = usable / 100 * percent + usable % 100 * percent / 100;
    if (policy.descriptorsPerTile > 0 && descriptors.shaderResources > policy.reservedDescriptors) {
        budget.maxTilesByDescriptors =
            (descriptors.shaderResources - policy.reservedDescriptors) / policy.descriptorsPerTile;
    }
    return budget;
}

std::string_view FormatName(uz::RHIFormat format) {
    for (const NamedFormat& named : kFormats) {
        if (named.format == format) return named.name;
    }
    return "Unknown";
}

const FormatCapability* CapabilityReport::Find(uz::RHIFormat format) const {
    for (const FormatCapability& entry : formats) {
        if (entry.format == format) return &entry;
    }
    return nullptr;
}

std::string CapabilityReport::ToJson() const {
    std::string json = "{";
    json += "\"backend\":" + JsonString(BackendName(backend));
    json += ",\"adapter\":" + JsonString(adapter);
    json += ",\"driver\":" + JsonString(driver);
    json += ",\"vendor_id\":" + JsonString(Hex(vendorId, 4));
    json += ",\"device_id\":" + JsonString(Hex(deviceId, 4));
    json += std::string(",\"software_adapter\":") + JsonBool(softwareAdapter);
    json += ",\"feature_level\":" + JsonString(featureLevel);
    json += ",\"shader_model\":" + JsonString(shaderModel);
    json += std::string(",\"ray_tracing\":") + JsonBool(rayTracing);
    json += std::string(",\"ray_query\":") + JsonBool(rayQuery);
    json += ",\"formats\":[";
    for (size_t i = 0; i < formats.size(); ++i) {
        if (i > 0) json += ",";
        json += "{\"format\":" + JsonString(formats[i].name) + ",\"usages\":[";
        const std::vector<std::string_view> usages = formats[i].Usages();
        for (size_t u = 0; u < usages.size(); ++u) {
            if (u > 0) json += ",";
            json += JsonString(usages[u]);
        }
        json += "]}";
    }
    json += "]";
    json += ",\"descriptors\":{\"shader_resources\":" + std::to_string(descriptors.shaderResources) +
            ",\"samplers\":" + std::to_string(descriptors.samplers) +
            ",\"render_targets\":" + std::to_string(descriptors.renderTargets) +
            ",\"depth_stencils\":" + std::to_string(descriptors.depthStencils) +
            ",\"resource_binding_tier\":" + std::to_string(descriptors.resourceBindingTier) + "}";
    json += ",\"vram\":{\"budget_bytes\":" + std::to_string(vram.budgetBytes) +
            ",\"usage_bytes\":" + std::to_string(vram.usageBytes) +
            ",\"dedicated_video_memory_bytes\":" + std::to_string(vram.dedicatedVideoMemoryBytes) +
            ",\"shared_system_memory_bytes\":" + std::to_string(vram.sharedSystemMemoryBytes) + "}";
    json += ",\"admission_policy\":{\"budget_percent\":" + std::to_string(policy.budgetPercent) +
            ",\"reserve_bytes\":" + std::to_string(policy.reserveBytes) +
            ",\"reserved_descriptors\":" + std::to_string(policy.reservedDescriptors) +
            ",\"descriptors_per_tile\":" + std::to_string(policy.descriptorsPerTile) + "}";
    json += ",\"admission\":{\"bytes\":" + std::to_string(admission.bytes) +
            ",\"max_tiles_by_descriptors\":" + std::to_string(admission.maxTilesByDescriptors) +
            "}";
    return json + "}";
}

Result<CapabilityReport> QueryCapabilities(IDevice& device, const AdmissionPolicy& policy) {
    if (device.GetBackend() == Backend::Vulkan) {
        // The record the qualified device was created on (render/vulkan_qualification.h).
        return VulkanCapabilityReport(static_cast<VulkanDevice&>(device).Record(), policy);
    }
    return QueryDx12(static_cast<Dx12Device&>(device), policy);
}

}  // namespace uzp::render
