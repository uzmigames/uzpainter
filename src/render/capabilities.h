#pragma once

// Capability query of the active backend and the tile admission budget derived from it
// (docs/architecture/13-engine-integration.md §6, 04-layer-stack-and-compositing.md §7): formats
// and their usages, ray-query support, descriptor capacities and the VRAM budget (DX12: the DXGI
// memory-budget query; Vulkan: the qualified device's capability record, `VulkanCapabilityReport`
// in vulkan_qualification.h). Run on the engine thread at startup (engine_thread.h).

#include "render/backend.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::render {

/// What one texel format supports as a 2D texture.
struct FormatCapability {
    uz::RHIFormat format = uz::RHIFormat::Unknown;
    std::string name;                   ///< The `uz::RHIFormat` enumerator, e.g. "RGBA16Float".
    bool texture2D = false;             ///< Usable as a 2D texture (and so as a copy source/target).
    bool shaderResource = false;        ///< Loadable in shaders.
    bool sample = false;                ///< Sampleable with a filter.
    bool renderTarget = false;
    bool depthStencil = false;
    bool unorderedAccess = false;       ///< Typed UAV with typed stores.
    bool unorderedAccessLoad = false;   ///< Typed UAV loads.

    /// The supported usages by name: "copy", "shader_resource", "sample", "render_target",
    /// "depth_stencil", "unordered_access", "unordered_access_load".
    [[nodiscard]] std::vector<std::string_view> Usages() const;
};

/// Descriptor capacities of the device's heaps.
struct DescriptorCapacities {
    uint32_t shaderResources = 0;  ///< CBV/SRV/UAV descriptors (shader-visible heap).
    uint32_t samplers = 0;
    uint32_t renderTargets = 0;
    uint32_t depthStencils = 0;
    uint32_t resourceBindingTier = 0;  ///< D3D12 resource binding tier (1-3).
};

struct VramReport {
    uint64_t budgetBytes = 0;   ///< OS-assigned budget of local video memory for this process.
    uint64_t usageBytes = 0;    ///< This process's current usage of it.
    uint64_t dedicatedVideoMemoryBytes = 0;
    uint64_t sharedSystemMemoryBytes = 0;
};

/// How the admission budget is derived; the defaults are conservative until the budgets are
/// measured on the corpus (P5-PERF).
struct AdmissionPolicy {
    uint32_t budgetPercent = 50;              ///< Share of the free budget given to live tiles.
    uint64_t reserveBytes = 512ull << 20;     ///< Free budget kept for everything else first.
    uint32_t reservedDescriptors = 4096;      ///< CBV/SRV/UAV descriptors kept for passes.
    uint32_t descriptorsPerTile = 2;          ///< A live tile's SRV and UAV.
};

/// Bound on the evaluator's live tiles: live tiles x bytes per tile <= `bytes`, and at most
/// `maxTilesByDescriptors` live tiles.
struct AdmissionBudget {
    uint64_t bytes = 0;
    uint64_t maxTilesByDescriptors = 0;

    /// How many tiles of `bytesPerTile` may be live at once (0 when `bytesPerTile` is 0).
    [[nodiscard]] uint64_t MaxLiveTiles(uint64_t bytesPerTile) const;
};

[[nodiscard]] AdmissionBudget DeriveAdmissionBudget(const VramReport& vram,
                                                    const DescriptorCapacities& descriptors,
                                                    const AdmissionPolicy& policy);

struct CapabilityReport {
    Backend backend = Backend::Dx12;
    std::string adapter;
    uint32_t vendorId = 0;
    uint32_t deviceId = 0;
    bool softwareAdapter = false;
    std::string featureLevel;
    std::string shaderModel;
    bool rayTracing = false;  ///< Acceleration structures (DXR Tier 1.0+).
    bool rayQuery = false;    ///< Inline ray queries (DXR Tier 1.1 and SM 6.6, UZP-MOD-004).
    std::vector<FormatCapability> formats;
    DescriptorCapacities descriptors;
    VramReport vram;
    AdmissionPolicy policy;
    AdmissionBudget admission;

    [[nodiscard]] const FormatCapability* Find(uz::RHIFormat format) const;
    /// The report as one JSON object (the local run report of the tests).
    [[nodiscard]] std::string ToJson() const;
};

/// The `uz::RHIFormat` enumerator's name, e.g. "RGBA16Unorm"; "Unknown" for `Unknown`.
[[nodiscard]] std::string_view FormatName(uz::RHIFormat format);

/// Queries the device's capabilities and derives the admission budget with `policy`.
[[nodiscard]] Result<CapabilityReport> QueryCapabilities(IDevice& device,
                                                         const AdmissionPolicy& policy);

}  // namespace uzp::render
