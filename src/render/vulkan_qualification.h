#pragma once

// Qualification of a Vulkan device for UzPainter's Vulkan compute backend
// (phase3.1_vulkan-compute-parity items 2.1, 2.6 and 2.8; decision 310).
//
// The capability record (`VulkanSurvey`) is what the loader, a pre-check instance and every
// physical device report: identity, driver and API versions, extensions, features, limits, queue
// families, memory and formats. `SurveyVulkan` (vulkan_backend.h) gathers it before any logical
// device exists; everything here is a pure function of it, so the native tests judge fabricated
// records without a GPU.
//
// The criteria are what the vendored backend (`uz::VulkanDevice`) needs at `vkCreateInstance` and
// `vkCreateDevice` and what the qualification kernels use, each a named check with the required
// and the found value. A device is judged at the requested adapter index of the vendored order
// only (no fallback to another device, decision 310 §2); the first unmet criterion's name is what
// a refusal reports.
//
// A qualified device is a device the compute slice may run on. It is not evidence that any
// Painter-visible output is equal on Vulkan: that is phase3.1's pilot comparison.

#include "render/capabilities.h"

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace uzp::render {

/// What the loader and the pre-check instance report.
struct VulkanInstanceRecord {
    bool loaderLoaded = false;
    std::string loaderError;          ///< Why `vulkan-1.dll` was not loaded.
    uint32_t instanceVersion = 0;     ///< `vkEnumerateInstanceVersion` (1.0 when absent).
    std::vector<std::string> instanceExtensions;
    bool instanceCreated = false;     ///< A Vulkan 1.2 instance was created.
    std::string instanceError;
};

struct VulkanQueueFamilyRecord {
    uint32_t flags = 0;               ///< `VkQueueFlags`.
    uint32_t queueCount = 0;
    uint32_t timestampValidBits = 0;
};

struct VulkanMemoryHeapRecord {
    uint64_t sizeBytes = 0;
    uint32_t flags = 0;               ///< `VkMemoryHeapFlags`.
    uint64_t budgetBytes = 0;         ///< `VK_EXT_memory_budget`; 0 without it.
    uint64_t usageBytes = 0;
};

struct VulkanMemoryTypeRecord {
    uint32_t propertyFlags = 0;       ///< `VkMemoryPropertyFlags`.
    uint32_t heapIndex = 0;
};

struct VulkanFormatRecord {
    std::string name;                 ///< The `VkFormat` enumerator without `VK_FORMAT_`.
    uint32_t vkFormat = 0;
    uint32_t optimalTilingFeatures = 0;
    uint32_t linearTilingFeatures = 0;
    uint32_t bufferFeatures = 0;
};

/// The capability record of one physical device.
struct VulkanDeviceRecord {
    uint32_t enumerationIndex = 0;    ///< Position in `vkEnumeratePhysicalDevices`.
    std::string name;
    std::string type;                 ///< `discrete`, `integrated`, `virtual`, `cpu` or `other`.
    uint32_t vendorId = 0;
    uint32_t deviceId = 0;
    uint32_t apiVersion = 0;
    uint32_t driverVersion = 0;       ///< Raw `VkPhysicalDeviceProperties::driverVersion`.
    std::string driverVersionName;    ///< In the vendor's encoding (`VulkanDriverVersionName`).
    uint32_t driverId = 0;            ///< `VkDriverId`; 0 below Vulkan 1.2.
    std::string driverName;
    std::string driverInfo;
    std::string conformanceVersion;
    std::string deviceUuid;           ///< Hex, 32 digits.
    std::string driverUuid;
    std::string pipelineCacheUuid;
    std::string luid;                 ///< Hex, 16 digits; empty when the LUID is not valid.
    std::vector<std::string> extensions;
    std::vector<std::pair<std::string, bool>> features;
    std::vector<std::pair<std::string, uint64_t>> limits;
    std::vector<std::pair<std::string, std::string>> properties;  ///< Non-integer properties.
    std::vector<VulkanQueueFamilyRecord> queueFamilies;
    std::vector<VulkanMemoryHeapRecord> heaps;
    std::vector<VulkanMemoryTypeRecord> memoryTypes;
    bool memoryBudget = false;        ///< `VK_EXT_memory_budget` exposed (and enabled by the backend).
    std::vector<VulkanFormatRecord> formats;

    [[nodiscard]] bool HasExtension(std::string_view name) const;
    [[nodiscard]] std::optional<bool> Feature(std::string_view name) const;
    [[nodiscard]] std::optional<uint64_t> Limit(std::string_view name) const;
    [[nodiscard]] const VulkanFormatRecord* Format(uint32_t vkFormat) const;
    /// The record as ordered key/value facts (`feature.<name>`, `limit.<name>`, `queue_family.<i>`,
    /// `heap.<i>`, `memory_type.<i>`, `format.<name>`, ...), the report form.
    [[nodiscard]] std::vector<std::pair<std::string, std::string>> Facts() const;
};

/// What `SurveyVulkan` found: the instance, then every physical device in enumeration order.
struct VulkanSurvey {
    VulkanInstanceRecord instance;
    std::vector<VulkanDeviceRecord> devices;
};

/// "1.3.280" for a `VK_MAKE_API_VERSION` value.
[[nodiscard]] std::string VulkanVersionText(uint32_t version);
/// The driver version in its vendor's encoding: NVIDIA 10.8.8.6 bits, Intel on Windows 18.14 bits,
/// otherwise the Vulkan version encoding.
[[nodiscard]] std::string VulkanDriverVersionName(uint32_t vendorId, uint32_t driverVersion);
/// "VK_ERROR_DEVICE_LOST (-4)" for a `VkResult`; the number alone for codes without a name here.
[[nodiscard]] std::string VkResultText(int32_t result);

// ── Criteria ─────────────────────────────────────────────────────────────────

/// The instance extensions the vendored backend enables at `vkCreateInstance`.
[[nodiscard]] const std::vector<std::string>& VulkanRequiredInstanceExtensions();
/// The device extensions and features the vendored backend enables at `vkCreateDevice`.
[[nodiscard]] const std::vector<std::string>& VulkanRequiredDeviceExtensions();
[[nodiscard]] const std::vector<std::string>& VulkanRequiredFeatures();

/// The device-level entry points the backend calls, by the names it calls them: Vulkan 1.2 core
/// and the `VK_KHR_synchronization2` / `VK_KHR_dynamic_rendering` names (the instance asks for
/// Vulkan 1.2, so the core 1.3 names need not resolve, UZP-MOD-012).
[[nodiscard]] const std::vector<std::string>& VulkanRequiredEntryPoints();
/// The required entry points `resolves` does not resolve, in order. Checked on the created device,
/// before anything is submitted (feature bits alone do not prove an entry point exists).
[[nodiscard]] std::vector<std::string> MissingVulkanEntryPoints(
    const std::function<bool(std::string_view)>& resolves);

struct VulkanLimitRequirement {
    const char* limit;
    uint64_t minimum;
    const char* why;
};
/// The limits the vendored descriptor set layout, its descriptor pool, its pipeline layout and the
/// qualification kernels need.
[[nodiscard]] const std::vector<VulkanLimitRequirement>& VulkanRequiredLimits();

struct VulkanFormatRequirement {
    const char* name;
    uint32_t vkFormat;
    uint32_t optimalTilingFeatures;   ///< `VkFormatFeatureFlags` every one of which is needed.
    const char* why;
};
/// The formats the qualification kernels write as storage images and copy to a buffer, and the
/// compositor's tile formats (sampled, stored, uploaded and read back; decision 313).
[[nodiscard]] const std::vector<VulkanFormatRequirement>& VulkanRequiredFormats();

/// The formats the capability record lists (the required ones, then the compositor's channel
/// formats and RGB32F, recorded but not required).
[[nodiscard]] const std::vector<std::pair<uint32_t, const char*>>& VulkanRecordedFormats();

// ── Selection and qualification ──────────────────────────────────────────────

/// Indices into `devices` in the vendored backend's order: discrete, integrated, virtual, cpu,
/// other, enumeration order kept within a type (`uz::VulkanDevice::SelectPhysicalDevice`).
[[nodiscard]] std::vector<size_t> VulkanVendoredOrder(const std::vector<VulkanDeviceRecord>& devices);

/// The queue family the vendored backend creates its one queue on: the first family with
/// `VK_QUEUE_GRAPHICS_BIT`; empty when none has it.
[[nodiscard]] std::optional<uint32_t> VulkanVendoredQueueFamily(const VulkanDeviceRecord& device);

struct VulkanCheck {
    std::string criterion;
    std::string required;
    std::string found;
    bool passed = false;
};

struct VulkanQualification {
    bool qualified = false;
    uint32_t adapterIndex = 0;                 ///< The requested index in the vendored order.
    std::optional<size_t> device;              ///< Index into `VulkanSurvey::devices` judged.
    std::optional<uint32_t> queueFamily;       ///< The queue family the device will use.
    std::vector<VulkanCheck> checks;           ///< Every check made, in order.

    /// "<criterion>: required <required>, found <found>" for every failed check.
    [[nodiscard]] std::vector<std::string> Missing() const;
    /// One line: "qualified: <device>" or "not qualified: <device>: <missing>; ...".
    [[nodiscard]] std::string Summary(const VulkanSurvey& survey) const;
};

/// Judges the device at `adapterIndex` of the vendored order. Instance criteria first; when one
/// fails no device is judged.
[[nodiscard]] VulkanQualification QualifyVulkan(const VulkanSurvey& survey, uint32_t adapterIndex);

// ── Descriptors and admission ────────────────────────────────────────────────

/// The descriptor model of the vendored backend in Vulkan's own terms. No descriptor lives with a
/// texture: every dispatch binds one snapshot of a 64-binding descriptor set (16 sampled images,
/// 16 samplers, 16 uniform buffers, 16 storage images, all update-after-bind) allocated from one
/// device-wide pool and freed when its command list's frame is reset. So descriptors bound what
/// one dispatch binds and how many snapshots can be outstanding at once, not how many tiles are
/// alive.
struct VulkanDescriptorModel {
    uint32_t sampledImagesPerDispatch = 0;  ///< min(16, the device's update-after-bind limits).
    uint32_t samplersPerDispatch = 0;
    uint32_t uniformBuffersPerDispatch = 0;
    uint32_t storageImagesPerDispatch = 0;
    /// Descriptor sets the vendored pool holds at once: the smallest of `maxSets` and each
    /// descriptor type's pool count divided by the bindings of that type in one set.
    uint32_t setsInPool = 0;
    std::string setsLimitedBy;              ///< The descriptor type (or `maxSets`) that bounds it.
};

[[nodiscard]] VulkanDescriptorModel DeriveVulkanDescriptorModel(const VulkanDeviceRecord& device);

/// The VRAM a Vulkan device reports: with `VK_EXT_memory_budget` the device-local heaps' budget
/// and usage, otherwise their sizes with usage unknown (counted as 0) — the conservative
/// fallback of `13-engine-integration.md` §6 is then the admission policy's reserve and share.
struct VulkanVram {
    bool fromMemoryBudget = false;
    uint64_t budgetBytes = 0;
    uint64_t usageBytes = 0;
    uint64_t deviceLocalHeapBytes = 0;
};

[[nodiscard]] VulkanVram DeriveVulkanVram(const VulkanDeviceRecord& device);

/// The admission budget on a Vulkan device: the bytes of `DeriveAdmissionBudget` over
/// `DeriveVulkanVram`, and no descriptor bound on live tiles (`maxTilesByDescriptors` is
/// `UINT64_MAX`), since a live tile holds no descriptor (`VulkanDescriptorModel`).
[[nodiscard]] AdmissionBudget DeriveVulkanAdmissionBudget(const VulkanVram& vram,
                                                          const AdmissionPolicy& policy);

}  // namespace uzp::render
