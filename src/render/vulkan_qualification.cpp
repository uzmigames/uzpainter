#include "render/vulkan_qualification.h"

#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>

#include <algorithm>
#include <cstdio>
#include <limits>

namespace uzp::render {

namespace {

std::string Hex(uint64_t value, int digits) {
    char buf[24];
    std::snprintf(buf, sizeof(buf), "0x%0*llX", digits, static_cast<unsigned long long>(value));
    return buf;
}

int TypePriority(const std::string& type) {
    if (type == "discrete") return 4;
    if (type == "integrated") return 3;
    if (type == "virtual") return 2;
    if (type == "cpu") return 1;
    return 0;
}

std::string QueueFlagsText(uint32_t flags) {
    std::string text;
    const std::pair<uint32_t, const char*> names[] = {
        {VK_QUEUE_GRAPHICS_BIT, "graphics"},     {VK_QUEUE_COMPUTE_BIT, "compute"},
        {VK_QUEUE_TRANSFER_BIT, "transfer"},     {VK_QUEUE_SPARSE_BINDING_BIT, "sparse"},
        {VK_QUEUE_PROTECTED_BIT, "protected"},   {VK_QUEUE_VIDEO_DECODE_BIT_KHR, "video_decode"},
        {VK_QUEUE_VIDEO_ENCODE_BIT_KHR, "video_encode"},
    };
    for (const auto& [bit, name] : names) {
        if ((flags & bit) == 0) continue;
        if (!text.empty()) text += "|";
        text += name;
    }
    return text.empty() ? "none" : text;
}

/// The vendored descriptor pool (`uz::VulkanDevice::CreateDescriptorPool`) and the bindings of
/// one set of its layout (`CreateDescriptorSetLayout`), per descriptor type.
struct PoolType {
    const char* type;
    uint32_t poolCount;
    uint32_t perSet;
};
constexpr PoolType kVendoredPool[] = {
    {"sampled_image", 16384, 16},
    {"storage_image", 4096, 16},
    {"storage_buffer", 4096, 16},  // UZP-MOD-013: bindings 64..79
    {"uniform_buffer", 4096, 16},
    {"sampler", 2048, 16},
    {"combined_image_sampler", 8192, 0},
};
constexpr uint32_t kVendoredPoolMaxSets = 32768;
constexpr uint64_t kVendoredPoolDescriptors = 16384 + 4096 + 4096 + 4096 + 2048 + 8192;

}  // namespace

// ── Record ───────────────────────────────────────────────────────────────────

bool VulkanDeviceRecord::HasExtension(std::string_view extension) const {
    return std::find(extensions.begin(), extensions.end(), extension) != extensions.end();
}

std::optional<bool> VulkanDeviceRecord::Feature(std::string_view feature) const {
    for (const auto& [key, value] : features) {
        if (key == feature) return value;
    }
    return std::nullopt;
}

std::optional<uint64_t> VulkanDeviceRecord::Limit(std::string_view limit) const {
    for (const auto& [key, value] : limits) {
        if (key == limit) return value;
    }
    return std::nullopt;
}

const VulkanFormatRecord* VulkanDeviceRecord::Format(uint32_t format) const {
    for (const VulkanFormatRecord& record : formats) {
        if (record.vkFormat == format) return &record;
    }
    return nullptr;
}

std::vector<std::pair<std::string, std::string>> VulkanDeviceRecord::Facts() const {
    std::vector<std::pair<std::string, std::string>> facts = {
        {"name", name},
        {"type", type},
        {"enumeration_index", std::to_string(enumerationIndex)},
        {"vendor_id", Hex(vendorId, 4)},
        {"device_id", Hex(deviceId, 4)},
        {"api_version", VulkanVersionText(apiVersion)},
        {"driver_version", driverVersionName},
        {"driver_version_raw", Hex(driverVersion, 8)},
        {"driver_id", std::to_string(driverId)},
        {"driver_name", driverName},
        {"driver_info", driverInfo},
        {"conformance_version", conformanceVersion},
        {"device_uuid", deviceUuid},
        {"driver_uuid", driverUuid},
        {"pipeline_cache_uuid", pipelineCacheUuid},
        {"luid", luid.empty() ? "invalid" : luid},
        {"memory_budget_extension", memoryBudget ? "yes" : "no"},
        {"extension_count", std::to_string(extensions.size())},
    };
    std::string joined;
    for (const std::string& extension : extensions) joined += (joined.empty() ? "" : " ") + extension;
    facts.emplace_back("extensions", joined);
    for (const auto& [key, value] : features) facts.emplace_back("feature." + key, value ? "true" : "false");
    for (const auto& [key, value] : limits) facts.emplace_back("limit." + key, std::to_string(value));
    for (const auto& [key, value] : properties) facts.emplace_back("property." + key, value);
    for (size_t i = 0; i < queueFamilies.size(); ++i) {
        const VulkanQueueFamilyRecord& family = queueFamilies[i];
        facts.emplace_back("queue_family." + std::to_string(i),
                           QueueFlagsText(family.flags) + " x" + std::to_string(family.queueCount) +
                               ", timestamp bits " + std::to_string(family.timestampValidBits));
    }
    for (size_t i = 0; i < heaps.size(); ++i) {
        const VulkanMemoryHeapRecord& heap = heaps[i];
        std::string text = std::to_string(heap.sizeBytes) + " bytes, flags " + Hex(heap.flags, 2);
        if (memoryBudget) {
            text += ", budget " + std::to_string(heap.budgetBytes) + ", usage " +
                    std::to_string(heap.usageBytes);
        }
        facts.emplace_back("heap." + std::to_string(i), text);
    }
    for (size_t i = 0; i < memoryTypes.size(); ++i) {
        facts.emplace_back("memory_type." + std::to_string(i),
                           "flags " + Hex(memoryTypes[i].propertyFlags, 2) + ", heap " +
                               std::to_string(memoryTypes[i].heapIndex));
    }
    for (const VulkanFormatRecord& format : formats) {
        facts.emplace_back("format." + format.name,
                           "optimal " + Hex(format.optimalTilingFeatures, 8) + ", linear " +
                               Hex(format.linearTilingFeatures, 8) + ", buffer " +
                               Hex(format.bufferFeatures, 8));
    }
    return facts;
}

std::string VulkanVersionText(uint32_t version) {
    return std::to_string(VK_API_VERSION_MAJOR(version)) + "." +
           std::to_string(VK_API_VERSION_MINOR(version)) + "." +
           std::to_string(VK_API_VERSION_PATCH(version));
}

std::string VulkanDriverVersionName(uint32_t vendorId, uint32_t version) {
    if (vendorId == 0x10DE) {
        return std::to_string(version >> 22) + "." + std::to_string((version >> 14) & 0xFF) + "." +
               std::to_string((version >> 6) & 0xFF) + "." + std::to_string(version & 0x3F);
    }
    if (vendorId == 0x8086) return std::to_string(version >> 14) + "." + std::to_string(version & 0x3FFF);
    return VulkanVersionText(version);
}

std::string VkResultText(int32_t result) {
    const char* name = nullptr;
    switch (result) {
        case VK_SUCCESS: name = "VK_SUCCESS"; break;
        case VK_TIMEOUT: name = "VK_TIMEOUT"; break;
        case VK_ERROR_OUT_OF_HOST_MEMORY: name = "VK_ERROR_OUT_OF_HOST_MEMORY"; break;
        case VK_ERROR_OUT_OF_DEVICE_MEMORY: name = "VK_ERROR_OUT_OF_DEVICE_MEMORY"; break;
        case VK_ERROR_INITIALIZATION_FAILED: name = "VK_ERROR_INITIALIZATION_FAILED"; break;
        case VK_ERROR_DEVICE_LOST: name = "VK_ERROR_DEVICE_LOST"; break;
        case VK_ERROR_LAYER_NOT_PRESENT: name = "VK_ERROR_LAYER_NOT_PRESENT"; break;
        case VK_ERROR_EXTENSION_NOT_PRESENT: name = "VK_ERROR_EXTENSION_NOT_PRESENT"; break;
        case VK_ERROR_FEATURE_NOT_PRESENT: name = "VK_ERROR_FEATURE_NOT_PRESENT"; break;
        case VK_ERROR_INCOMPATIBLE_DRIVER: name = "VK_ERROR_INCOMPATIBLE_DRIVER"; break;
        case VK_ERROR_TOO_MANY_OBJECTS: name = "VK_ERROR_TOO_MANY_OBJECTS"; break;
        case VK_ERROR_OUT_OF_POOL_MEMORY: name = "VK_ERROR_OUT_OF_POOL_MEMORY"; break;
        default: break;
    }
    const std::string number = "(" + std::to_string(result) + ")";
    return name ? std::string(name) + " " + number : number;
}

// ── Criteria ─────────────────────────────────────────────────────────────────

const std::vector<std::string>& VulkanRequiredInstanceExtensions() {
    static const std::vector<std::string> names = {"VK_KHR_surface", "VK_KHR_win32_surface"};
    return names;
}

const std::vector<std::string>& VulkanRequiredDeviceExtensions() {
    static const std::vector<std::string> names = {
        "VK_KHR_swapchain",
        "VK_KHR_dynamic_rendering",
        "VK_KHR_synchronization2",
        "VK_KHR_timeline_semaphore",
    };
    return names;
}

const std::vector<std::string>& VulkanRequiredFeatures() {
    static const std::vector<std::string> names = {
        "timelineSemaphore",
        "descriptorIndexing",
        "bufferDeviceAddress",
        "runtimeDescriptorArray",
        "descriptorBindingPartiallyBound",
        "shaderSampledImageArrayNonUniformIndexing",
        "descriptorBindingVariableDescriptorCount",
        "descriptorBindingSampledImageUpdateAfterBind",
        "descriptorBindingStorageImageUpdateAfterBind",
        "descriptorBindingUniformBufferUpdateAfterBind",
        "dynamicRendering",
        "synchronization2",
        "fillModeNonSolid",
        "samplerAnisotropy",
        // Enabled when supported (UZP-MOD-012); the R16_SFLOAT kernel's storage image needs it.
        "shaderStorageImageExtendedFormats",
        // Enabled when supported (UZP-MOD-013); the compositor kernels compute in double and
        // 64-bit integers (SPIR-V Float64, Int64; decision 313).
        "shaderFloat64",
        "shaderInt64",
    };
    return names;
}

const std::vector<std::string>& VulkanRequiredEntryPoints() {
    static const std::vector<std::string> names = {
        "vkQueueSubmit",          "vkWaitSemaphores",       "vkSignalSemaphore",
        "vkGetSemaphoreCounterValue", "vkCmdPipelineBarrier2KHR", "vkCmdBeginRenderingKHR",
        "vkCmdEndRenderingKHR",   "vkCmdDispatch",          "vkCmdCopyImageToBuffer",
    };
    return names;
}

std::vector<std::string> MissingVulkanEntryPoints(const std::function<bool(std::string_view)>& resolves) {
    std::vector<std::string> missing;
    for (const std::string& name : VulkanRequiredEntryPoints()) {
        if (!resolves(name)) missing.push_back(name);
    }
    return missing;
}

const std::vector<VulkanLimitRequirement>& VulkanRequiredLimits() {
    static const std::vector<VulkanLimitRequirement> limits = {
        {"maxPushConstantsSize", 128, "the vendored pipeline layout has 128 bytes of push constants"},
        {"maxBoundDescriptorSets", 1, "the vendored pipeline layout binds descriptor set 0"},
        {"maxPerStageDescriptorUpdateAfterBindSampledImages", 16,
         "16 update-after-bind sampled-image bindings in one stage"},
        {"maxPerStageDescriptorUpdateAfterBindSamplers", 16,
         "16 update-after-bind sampler bindings in one stage"},
        {"maxPerStageDescriptorUpdateAfterBindUniformBuffers", 16,
         "16 update-after-bind uniform-buffer bindings in one stage"},
        {"maxPerStageDescriptorUpdateAfterBindStorageImages", 16,
         "16 update-after-bind storage-image bindings in one stage"},
        {"maxPerStageDescriptorUpdateAfterBindStorageBuffers", 16,
         "16 storage-buffer bindings in one stage (UZP-MOD-013)"},
        {"maxPerStageUpdateAfterBindResources", 64,
         "64 resources (sampled images, uniform buffers, storage images, storage buffers) visible to the compute stage"},
        {"maxDescriptorSetUpdateAfterBindSampledImages", 16, "16 sampled images in the set"},
        {"maxDescriptorSetUpdateAfterBindSamplers", 16, "16 samplers in the set"},
        {"maxDescriptorSetUpdateAfterBindUniformBuffers", 16, "16 uniform buffers in the set"},
        {"maxDescriptorSetUpdateAfterBindStorageImages", 16, "16 storage images in the set"},
        {"maxDescriptorSetUpdateAfterBindStorageBuffers", 16, "16 storage buffers in the set (UZP-MOD-013)"},
        {"maxStorageBufferRange", 0xFFFFFFFFull,
         "a compositor kernel reads a structured buffer of up to 4 GiB through one binding (decision 313)"},
        {"maxUpdateAfterBindDescriptorsInAllPools", kVendoredPoolDescriptors,
         "the vendored update-after-bind descriptor pool holds 38912 descriptors"},
        {"maxComputeWorkGroupSize.x", 8, "the qualification kernels run 8x8x1 work groups"},
        {"maxComputeWorkGroupSize.y", 8, "the qualification kernels run 8x8x1 work groups"},
        {"maxComputeWorkGroupInvocations", 64, "the qualification and compositor kernels run 64 invocations a group"},
    };
    return limits;
}

const std::vector<VulkanFormatRequirement>& VulkanRequiredFormats() {
    constexpr uint32_t kStorageCopy = VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT | VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;
    // A compositor tile is sampled, written as a storage image, uploaded and read back (decision 313).
    constexpr uint32_t kTile = kStorageCopy | VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
    static const std::vector<VulkanFormatRequirement> formats = {
        {"R16_SFLOAT", VK_FORMAT_R16_SFLOAT, kTile, "the 16-bit pattern kernel writes it; L16F compositor tiles"},
        {"R32_UINT", VK_FORMAT_R32_UINT, kStorageCopy, "the 32-bit integer kernel writes it"},
        {"R32_SFLOAT", VK_FORMAT_R32_SFLOAT, kTile, "the IEEE-strict float kernel writes it; L32F compositor tiles"},
        {"R8_UNORM", VK_FORMAT_R8_UNORM, kTile, "L8 compositor tiles"},
        {"R16_UNORM", VK_FORMAT_R16_UNORM, kTile, "L16 compositor tiles"},
        {"R8G8B8A8_UNORM", VK_FORMAT_R8G8B8A8_UNORM, kTile, "RGB8 and sRGB8 compositor tiles"},
        {"R16G16B16A16_UNORM", VK_FORMAT_R16G16B16A16_UNORM, kTile, "RGB16 compositor tiles"},
        {"R16G16B16A16_SFLOAT", VK_FORMAT_R16G16B16A16_SFLOAT, kTile, "RGB16F compositor tiles"},
        {"R32G32B32A32_SFLOAT", VK_FORMAT_R32G32B32A32_SFLOAT, kTile, "RGB32F compositor tiles"},
    };
    return formats;
}

const std::vector<std::pair<uint32_t, const char*>>& VulkanRecordedFormats() {
    static const std::vector<std::pair<uint32_t, const char*>> formats = {
        {VK_FORMAT_R16_SFLOAT, "R16_SFLOAT"},
        {VK_FORMAT_R32_UINT, "R32_UINT"},
        {VK_FORMAT_R32_SFLOAT, "R32_SFLOAT"},
        {VK_FORMAT_R8_UNORM, "R8_UNORM"},
        {VK_FORMAT_R16_UNORM, "R16_UNORM"},
        {VK_FORMAT_R8G8B8A8_UNORM, "R8G8B8A8_UNORM"},
        {VK_FORMAT_R16G16B16A16_UNORM, "R16G16B16A16_UNORM"},
        {VK_FORMAT_R16G16B16A16_SFLOAT, "R16G16B16A16_SFLOAT"},
        {VK_FORMAT_R32G32B32_SFLOAT, "R32G32B32_SFLOAT"},
        {VK_FORMAT_R32G32B32A32_SFLOAT, "R32G32B32A32_SFLOAT"},
    };
    return formats;
}

// ── Selection and qualification ──────────────────────────────────────────────

std::vector<size_t> VulkanVendoredOrder(const std::vector<VulkanDeviceRecord>& devices) {
    std::vector<size_t> order(devices.size());
    for (size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        return TypePriority(devices[a].type) > TypePriority(devices[b].type);
    });
    return order;
}

std::optional<uint32_t> VulkanVendoredQueueFamily(const VulkanDeviceRecord& device) {
    for (size_t i = 0; i < device.queueFamilies.size(); ++i) {
        if (device.queueFamilies[i].flags & VK_QUEUE_GRAPHICS_BIT) return static_cast<uint32_t>(i);
    }
    return std::nullopt;
}

std::vector<std::string> VulkanQualification::Missing() const {
    std::vector<std::string> missing;
    for (const VulkanCheck& check : checks) {
        if (!check.passed) {
            missing.push_back(check.criterion + ": required " + check.required + ", found " + check.found);
        }
    }
    return missing;
}

std::string VulkanQualification::Summary(const VulkanSurvey& survey) const {
    const std::string name =
        device ? "device " + std::to_string(adapterIndex) + " '" + survey.devices[*device].name + "'"
               : "adapter index " + std::to_string(adapterIndex);
    if (qualified) return "qualified: " + name;
    std::string text = "not qualified: " + name + ": ";
    const std::vector<std::string> missing = Missing();
    for (size_t i = 0; i < missing.size(); ++i) text += (i ? "; " : "") + missing[i];
    return text;
}

VulkanQualification QualifyVulkan(const VulkanSurvey& survey, uint32_t adapterIndex) {
    VulkanQualification q;
    q.adapterIndex = adapterIndex;
    auto check = [&q](std::string criterion, std::string required, std::string found, bool passed) {
        q.checks.push_back({std::move(criterion), std::move(required), std::move(found), passed});
        return passed;
    };
    auto allPassed = [&q] {
        return std::all_of(q.checks.begin(), q.checks.end(), [](const VulkanCheck& c) { return c.passed; });
    };

    // Instance: the vendored instance asks for Vulkan 1.2 and these extensions; a loader that
    // offers less is refused here, before the vendored backend would fall back to it.
    const VulkanInstanceRecord& instance = survey.instance;
    if (!check("Vulkan loader (vulkan-1.dll)", "loaded",
               instance.loaderLoaded ? "loaded" : instance.loaderError, instance.loaderLoaded)) {
        return q;
    }
    check("loader instance version", ">= 1.2.0", VulkanVersionText(instance.instanceVersion),
          instance.instanceVersion >= VK_API_VERSION_1_2);
    for (const std::string& name : VulkanRequiredInstanceExtensions()) {
        const bool present = std::find(instance.instanceExtensions.begin(), instance.instanceExtensions.end(),
                                       name) != instance.instanceExtensions.end();
        check("instance extension " + name, "exposed", present ? "exposed" : "absent", present);
    }
    check("Vulkan 1.2 instance", "created", instance.instanceCreated ? "created" : instance.instanceError,
          instance.instanceCreated);
    const std::vector<size_t> order = VulkanVendoredOrder(survey.devices);
    check("physical device at adapter index " + std::to_string(adapterIndex),
          "present in the vendored order", std::to_string(order.size()) + " device(s)",
          adapterIndex < order.size());
    if (!allPassed()) return q;

    q.device = order[adapterIndex];
    const VulkanDeviceRecord& device = survey.devices[*q.device];
    check("device type", "discrete or integrated GPU", device.type,
          device.type == "discrete" || device.type == "integrated");
    check("device API version", ">= 1.2.0", VulkanVersionText(device.apiVersion),
          device.apiVersion >= VK_API_VERSION_1_2);
    for (const std::string& name : VulkanRequiredDeviceExtensions()) {
        const bool present = device.HasExtension(name);
        check("device extension " + name, "exposed", present ? "exposed" : "absent", present);
    }
    for (const std::string& name : VulkanRequiredFeatures()) {
        const std::optional<bool> value = device.Feature(name);
        check("feature " + name, "true", value ? (*value ? "true" : "false") : "not queried",
              value.value_or(false));
    }
    q.queueFamily = VulkanVendoredQueueFamily(device);
    {
        const uint32_t flags = q.queueFamily ? device.queueFamilies[*q.queueFamily].flags : 0;
        const std::string found = q.queueFamily ? "family " + std::to_string(*q.queueFamily) + ": " +
                                                      QueueFlagsText(flags)
                                                : "no graphics family";
        check("queue family", "the first graphics family also has compute", found,
              q.queueFamily.has_value() && (flags & VK_QUEUE_COMPUTE_BIT) != 0);
    }
    for (const VulkanLimitRequirement& limit : VulkanRequiredLimits()) {
        const std::optional<uint64_t> value = device.Limit(limit.limit);
        check(std::string("limit ") + limit.limit + " (" + limit.why + ")",
              ">= " + std::to_string(limit.minimum), value ? std::to_string(*value) : "not queried",
              value.has_value() && *value >= limit.minimum);
    }
    {
        // IEEE-strict SPIR-V (UZP-MOD-008) declares SignedZeroInfNanPreserve for 32-bit floats.
        std::string found = "not queried";
        for (const auto& [key, value] : device.properties) {
            if (key == "shaderSignedZeroInfNanPreserveFloat32") found = value;
        }
        check("float controls shaderSignedZeroInfNanPreserveFloat32 (IEEE-strict kernels)", "true", found,
              found == "true");
    }
    const auto hasMemoryType = [&device](uint32_t flags) {
        return std::any_of(device.memoryTypes.begin(), device.memoryTypes.end(),
                           [flags](const VulkanMemoryTypeRecord& t) { return (t.propertyFlags & flags) == flags; });
    };
    check("memory type HOST_VISIBLE (readback buffers)", "present",
          hasMemoryType(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) ? "present" : "absent",
          hasMemoryType(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT));
    check("memory type DEVICE_LOCAL (images)", "present",
          hasMemoryType(VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) ? "present" : "absent",
          hasMemoryType(VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT));
    for (const VulkanFormatRequirement& format : VulkanRequiredFormats()) {
        const VulkanFormatRecord* record = device.Format(format.vkFormat);
        const uint32_t found = record ? record->optimalTilingFeatures : 0;
        check(std::string("format ") + format.name + " (" + format.why + ")",
              "optimal tiling features " + Hex(format.optimalTilingFeatures, 8),
              record ? Hex(found, 8) : "not queried",
              (found & format.optimalTilingFeatures) == format.optimalTilingFeatures);
    }
    q.qualified = allPassed();
    return q;
}

// ── Descriptors and admission ────────────────────────────────────────────────

VulkanDescriptorModel DeriveVulkanDescriptorModel(const VulkanDeviceRecord& device) {
    const auto perDispatch = [&device](const char* perStage, const char* perSet) {
        const uint64_t limit = std::min(device.Limit(perStage).value_or(0), device.Limit(perSet).value_or(0));
        return static_cast<uint32_t>(std::min<uint64_t>(16, limit));
    };
    VulkanDescriptorModel model;
    model.sampledImagesPerDispatch = perDispatch("maxPerStageDescriptorUpdateAfterBindSampledImages",
                                                 "maxDescriptorSetUpdateAfterBindSampledImages");
    model.samplersPerDispatch = perDispatch("maxPerStageDescriptorUpdateAfterBindSamplers",
                                            "maxDescriptorSetUpdateAfterBindSamplers");
    model.uniformBuffersPerDispatch = perDispatch("maxPerStageDescriptorUpdateAfterBindUniformBuffers",
                                                  "maxDescriptorSetUpdateAfterBindUniformBuffers");
    model.storageImagesPerDispatch = perDispatch("maxPerStageDescriptorUpdateAfterBindStorageImages",
                                                 "maxDescriptorSetUpdateAfterBindStorageImages");
    // The pool counts every binding of a set, the immutable samplers included.
    model.setsInPool = kVendoredPoolMaxSets;
    model.setsLimitedBy = "maxSets";
    for (const PoolType& type : kVendoredPool) {
        if (type.perSet == 0) continue;
        const uint32_t sets = type.poolCount / type.perSet;
        if (sets < model.setsInPool) {
            model.setsInPool = sets;
            model.setsLimitedBy = type.type;
        }
    }
    return model;
}

VulkanVram DeriveVulkanVram(const VulkanDeviceRecord& device) {
    VulkanVram vram;
    vram.fromMemoryBudget = device.memoryBudget;
    for (const VulkanMemoryHeapRecord& heap : device.heaps) {
        if ((heap.flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) == 0) continue;
        vram.deviceLocalHeapBytes += heap.sizeBytes;
        vram.budgetBytes += device.memoryBudget ? heap.budgetBytes : heap.sizeBytes;
        vram.usageBytes += device.memoryBudget ? heap.usageBytes : 0;
    }
    return vram;
}

AdmissionBudget DeriveVulkanAdmissionBudget(const VulkanVram& vram, const AdmissionPolicy& policy) {
    VramReport report;
    report.budgetBytes = vram.budgetBytes;
    report.usageBytes = vram.usageBytes;
    AdmissionBudget budget = DeriveAdmissionBudget(report, DescriptorCapacities{}, policy);
    budget.maxTilesByDescriptors = std::numeric_limits<uint64_t>::max();
    return budget;
}

CapabilityReport VulkanCapabilityReport(const VulkanDeviceRecord& device, const AdmissionPolicy& policy) {
    CapabilityReport report;
    report.backend = Backend::Vulkan;
    report.adapter = device.name;
    report.vendorId = device.vendorId;
    report.deviceId = device.deviceId;
    report.softwareAdapter = device.type == "cpu";
    report.featureLevel = "vulkan " + VulkanVersionText(device.apiVersion);
    report.shaderModel = "spirv";

    // The recorded formats in the vendored RHI's terms.
    const std::pair<uint32_t, uz::RHIFormat> rhi[] = {
        {VK_FORMAT_R16_SFLOAT, uz::RHIFormat::R16Float},
        {VK_FORMAT_R32_UINT, uz::RHIFormat::R32Uint},
        {VK_FORMAT_R32_SFLOAT, uz::RHIFormat::R32Float},
        {VK_FORMAT_R8_UNORM, uz::RHIFormat::R8Unorm},
        {VK_FORMAT_R16_UNORM, uz::RHIFormat::R16Unorm},
        {VK_FORMAT_R8G8B8A8_UNORM, uz::RHIFormat::RGBA8Unorm},
        {VK_FORMAT_R16G16B16A16_UNORM, uz::RHIFormat::RGBA16Unorm},
        {VK_FORMAT_R16G16B16A16_SFLOAT, uz::RHIFormat::RGBA16Float},
        {VK_FORMAT_R32G32B32_SFLOAT, uz::RHIFormat::RGB32Float},
        {VK_FORMAT_R32G32B32A32_SFLOAT, uz::RHIFormat::RGBA32Float},
    };
    for (const auto& [vkFormat, format] : rhi) {
        const VulkanFormatRecord* record = device.Format(vkFormat);
        if (record == nullptr) continue;
        const uint32_t features = record->optimalTilingFeatures;
        const auto has = [features](uint32_t bit) { return (features & bit) != 0; };
        FormatCapability capability;
        capability.format = format;
        capability.name = std::string(FormatName(format));
        capability.texture2D = features != 0;
        capability.shaderResource = has(VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT);
        capability.sample = has(VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);
        capability.renderTarget = has(VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT);
        capability.depthStencil = has(VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT);
        // A storage image declaring its format both loads and stores (decision 313).
        capability.unorderedAccess = has(VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT);
        capability.unorderedAccessLoad = capability.unorderedAccess;
        report.formats.push_back(std::move(capability));
    }

    const VulkanDescriptorModel descriptors = DeriveVulkanDescriptorModel(device);
    report.descriptors.shaderResources = descriptors.sampledImagesPerDispatch +
                                         descriptors.uniformBuffersPerDispatch +
                                         descriptors.storageImagesPerDispatch;
    report.descriptors.samplers = descriptors.samplersPerDispatch;

    const VulkanVram vram = DeriveVulkanVram(device);
    report.vram.budgetBytes = vram.budgetBytes;
    report.vram.usageBytes = vram.usageBytes;
    report.vram.dedicatedVideoMemoryBytes = vram.deviceLocalHeapBytes;
    for (const VulkanMemoryHeapRecord& heap : device.heaps) {
        if ((heap.flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) == 0) report.vram.sharedSystemMemoryBytes += heap.sizeBytes;
    }
    report.policy = policy;
    report.admission = DeriveVulkanAdmissionBudget(vram, policy);
    return report;
}

}  // namespace uzp::render
