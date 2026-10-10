#pragma once

// Probe report model of `selftest` (phase0.7_toolchain-probes; docs/architecture/13-engine-integration.md
// §4.2): what a probe found, kept apart from whether the probe could run. Every probe states
//
//   completed  the probe ran to its end (false: `probe not completed`, with `error`)
//   qualified  the backend or feature it probes is usable as UzPainter needs it
//
// plus the supported items, the checks it executed with their results and an explicit reason for
// every unsupported item (the `missing` list a later `PathTracerUnavailable{backend, missing}`
// carries). The decisions here are pure functions of the capabilities a probe gathered, so the
// probe stages (dx12_probes.cpp, vulkan_probes.cpp) and the native tests
// (tests/native/selftest_probes_test.cpp) share them.

#include "harness.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace uzp::selftest {

struct ExecutedCheck {
    std::string check;
    bool passed = false;
    std::string detail;  ///< The observed value or the failure.
};

struct UnsupportedItem {
    std::string item;
    std::string reason;
};

/// One device a probe enumerated (Vulkan physical devices).
struct DeviceRecord {
    Details facts;
    std::vector<std::string> extensions;
    std::vector<std::pair<std::string, bool>> features;
};

struct ProbeReport {
    std::string probe;
    std::string backend;
    std::string adapter;
    std::string driver;
    bool completed = false;
    bool qualified = false;
    /// One word for people: `available`/`unavailable` (Vulkan availability),
    /// `supported`/`unsupported` (ray queries), `qualified`/`partially qualified`/`unsupported`
    /// (WARP), or `probe not completed`.
    std::string verdict;
    std::string error;  ///< Why the probe did not complete; empty when it completed.
    std::vector<std::string> supported;
    std::vector<ExecutedCheck> executedChecks;
    std::vector<UnsupportedItem> unsupported;
    Details facts;
    std::vector<DeviceRecord> devices;
    /// WARP only: the checks the hosted WARP lane may run (those that passed on WARP).
    bool hasHostedLane = false;
    std::vector<std::string> hostedLane;

    /// The report as a JSON object; `indent` prefixes every line after the first.
    std::string ToJson(const std::string& indent = "") const;
};

/// A probe that could not run to its end.
ProbeReport NotCompleted(std::string probe, std::string backend, std::string error);

/// The stage outcome of a probe: passed when the probe completed (qualified or not), failed
/// (`probe not completed`) otherwise. Probe stages are never mandatory, so neither fails `selftest`.
StageOutcome ProbeOutcome(const ProbeReport& report);

// ── DX12 inline ray queries ──────────────────────────────────────────────────

/// `D3D12_RAYTRACING_TIER` and `D3D_SHADER_MODEL` values (d3d12.h), as plain integers.
inline constexpr uint32_t kDxrTierNotSupported = 0;
inline constexpr uint32_t kDxrTier1_0 = 10;
inline constexpr uint32_t kDxrTier1_1 = 11;
inline constexpr uint32_t kShaderModel6_5 = 0x65;
inline constexpr uint32_t kShaderModel6_6 = 0x66;

std::string DxrTierName(uint32_t tier);         ///< "not supported", "Tier 1.0", "Tier 1.1", ...
std::string ShaderModelName(uint32_t model);    ///< "6.6"

/// Inline ray queries on DX12: DXR Tier 1.1 and highest shader model 6.6, decided by the vendored
/// `DX12SupportsInlineRayQuery` (UZP-MOD-004); each missing item is named.
ProbeReport EvaluateDx12RayQuery(uint32_t raytracingTier, uint32_t highestShaderModel,
                                 std::string adapter, std::string driver);

// ── Vulkan ───────────────────────────────────────────────────────────────────

struct VulkanLoaderInfo {
    bool loaded = false;           ///< `vulkan-1.dll` loaded and `vkGetInstanceProcAddr` found.
    std::string path;              ///< The loaded file.
    std::string error;             ///< Why it was not loaded.
    uint32_t instanceVersion = 0;  ///< `vkEnumerateInstanceVersion` (1.0 when absent).
    bool instanceCreated = false;  ///< A Vulkan 1.2 instance was created.
    std::string instanceError;     ///< Why not.
};

struct VulkanDeviceInfo {
    std::string name;
    std::string type;  ///< `discrete`, `integrated`, `virtual`, `cpu` or `other`.
    uint32_t apiVersion = 0;
    std::string driver;  ///< Driver name and version for people.
    Details facts;       ///< Every recorded property, in report order.
    std::vector<std::string> extensions;
    std::vector<std::pair<std::string, bool>> features;

    bool HasExtension(const std::string& name) const;
    bool Feature(const std::string& name) const;  ///< False when not recorded.
};

/// What the Vulkan availability probe gathered; the Vulkan ray-query probe reads it.
struct VulkanProbeState {
    VulkanLoaderInfo loader;
    std::vector<VulkanDeviceInfo> devices;  ///< In enumeration order.
};

std::string VulkanVersionName(uint32_t version);  ///< "1.3.280"

/// The device the vendored Vulkan backend selects for adapter index 0: the first of the highest
/// type priority (discrete, integrated, virtual, cpu, other), as `vulkan_device.cpp` sorts them.
size_t SelectedVulkanDevice(const std::vector<VulkanDeviceInfo>& devices);

/// The extensions and features the vendored Vulkan device enables at `vkCreateDevice`
/// (`vulkan_device.cpp`): a device without one of them cannot host the Vulkan backend.
const std::vector<std::string>& VulkanRequiredExtensions();
const std::vector<std::string>& VulkanRequiredFeatures();
/// The ray-query items of `07-preview-and-render-parity.md` §3.5.
const std::vector<std::string>& VulkanRayQueryExtensions();
const std::vector<std::string>& VulkanRayQueryFeatures();

/// Vulkan availability: loader, a Vulkan 1.2 instance, and a selected device with API 1.2 and the
/// vendored device's extensions and features. An absent or too-old loader is `unavailable` with
/// its reason; the probe still completed.
ProbeReport EvaluateVulkanAvailability(const VulkanProbeState& state);

/// Vulkan inline ray queries on the selected device, each missing item named.
ProbeReport EvaluateVulkanRayQuery(const VulkanProbeState& state);

// ── WARP ─────────────────────────────────────────────────────────────────────

enum class CheckStatus { Passed, Failed, NotRun };

struct WarpCheck {
    std::string check;
    CheckStatus status = CheckStatus::NotRun;
    std::string detail;  ///< Observed value, failure, or why it was not run.
};

/// Fills the WARP verdict from the attempted checks: executed checks with their results, an
/// unsupported item with its reason for every check that failed or was not run, the hosted
/// WARP lane (only the checks that passed), and qualified when every check passed.
void ConcludeWarp(ProbeReport& report, const std::vector<WarpCheck>& checks);

}  // namespace uzp::selftest
