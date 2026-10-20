#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_WIN32_KHR
#include "render/vulkan_backend.h"

#include <volk.h>

#define VMA_STATIC_VULKAN_FUNCTIONS 0
#define VMA_DYNAMIC_VULKAN_FUNCTIONS 1
// VMA's header leaves some pointers without a nullability specifier (a warning, an error here).
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wnullability-completeness"
#include <vk_mem_alloc.h>
#pragma clang diagnostic pop

#include "log.h"
#include "rhi_backend.h"
#include "vulkan_command_list.h"
#include "vulkan_device.h"
#include "vulkan_fence.h"
#include "vulkan_resources.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <utility>
#include <vector>

namespace uzp::render {

namespace {

/// A Vulkan structure with its `sType` set and every other member zero.
template <class T>
T Vk(VkStructureType type) {
    T structure{};
    structure.sType = type;
    return structure;
}

std::string HexBytes(const uint8_t* bytes, size_t count) {
    std::string out;
    for (size_t i = 0; i < count; ++i) {
        char buf[4];
        std::snprintf(buf, sizeof(buf), "%02X", bytes[i]);
        out += buf;
    }
    return out;
}

const char* TypeName(VkPhysicalDeviceType type) {
    switch (type) {
        case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:   return "discrete";
        case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated";
        case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU:    return "virtual";
        case VK_PHYSICAL_DEVICE_TYPE_CPU:            return "cpu";
        default:                                     return "other";
    }
}

std::string Bool(VkBool32 value) { return value == VK_TRUE ? "true" : "false"; }

std::string Independence(VkShaderFloatControlsIndependence value) {
    switch (value) {
        case VK_SHADER_FLOAT_CONTROLS_INDEPENDENCE_32_BIT_ONLY: return "32_bit_only";
        case VK_SHADER_FLOAT_CONTROLS_INDEPENDENCE_ALL:         return "all";
        case VK_SHADER_FLOAT_CONTROLS_INDEPENDENCE_NONE:        return "none";
        default:                                                return std::to_string(value);
    }
}

VulkanDeviceRecord Describe(VkPhysicalDevice physical, uint32_t index) {
    VulkanDeviceRecord record;
    record.enumerationIndex = index;

    uint32_t count = 0;
    vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, nullptr);
    std::vector<VkExtensionProperties> extensions(count);
    vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, extensions.data());
    extensions.resize(count);
    for (const VkExtensionProperties& extension : extensions) {
        record.extensions.emplace_back(extension.extensionName);
    }

    VkPhysicalDeviceProperties core{};
    vkGetPhysicalDeviceProperties(physical, &core);
    // Structures are chained only where the device's API version or an exposed extension makes
    // them valid.
    const bool api12 = core.apiVersion >= VK_API_VERSION_1_2;
    const bool api13 = core.apiVersion >= VK_API_VERSION_1_3;
    auto p11 = Vk<VkPhysicalDeviceVulkan11Properties>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_PROPERTIES);
    auto p12 = Vk<VkPhysicalDeviceVulkan12Properties>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_PROPERTIES);
    auto props = Vk<VkPhysicalDeviceProperties2>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2);
    if (api12) {
        props.pNext = &p11;
        p11.pNext = &p12;
        vkGetPhysicalDeviceProperties2(physical, &props);
    } else {
        props.properties = core;
    }
    const VkPhysicalDeviceProperties& p = props.properties;
    const VkPhysicalDeviceLimits& l = p.limits;
    record.name = p.deviceName;
    record.type = TypeName(p.deviceType);
    record.vendorId = p.vendorID;
    record.deviceId = p.deviceID;
    record.apiVersion = p.apiVersion;
    record.driverVersion = p.driverVersion;
    record.driverVersionName = VulkanDriverVersionName(p.vendorID, p.driverVersion);
    record.pipelineCacheUuid = HexBytes(p.pipelineCacheUUID, VK_UUID_SIZE);
    if (api12) {
        record.driverId = static_cast<uint32_t>(p12.driverID);
        record.driverName = p12.driverName;
        record.driverInfo = p12.driverInfo;
        const VkConformanceVersion& c = p12.conformanceVersion;
        record.conformanceVersion = std::to_string(c.major) + "." + std::to_string(c.minor) + "." +
                                    std::to_string(c.subminor) + "." + std::to_string(c.patch);
        record.deviceUuid = HexBytes(p11.deviceUUID, VK_UUID_SIZE);
        record.driverUuid = HexBytes(p11.driverUUID, VK_UUID_SIZE);
        if (p11.deviceLUIDValid) {
            // Little-endian bytes, printed as the 64-bit LUID (DXGI's LowPart/HighPart order).
            uint8_t reversed[VK_LUID_SIZE];
            for (size_t i = 0; i < VK_LUID_SIZE; ++i) reversed[i] = p11.deviceLUID[VK_LUID_SIZE - 1 - i];
            record.luid = HexBytes(reversed, VK_LUID_SIZE);
        }
    }

    record.limits = {
        {"maxImageDimension2D", l.maxImageDimension2D},
        {"maxPushConstantsSize", l.maxPushConstantsSize},
        {"maxBoundDescriptorSets", l.maxBoundDescriptorSets},
        {"maxPerStageDescriptorSamplers", l.maxPerStageDescriptorSamplers},
        {"maxPerStageDescriptorUniformBuffers", l.maxPerStageDescriptorUniformBuffers},
        {"maxPerStageDescriptorSampledImages", l.maxPerStageDescriptorSampledImages},
        {"maxPerStageDescriptorStorageImages", l.maxPerStageDescriptorStorageImages},
        {"maxPerStageResources", l.maxPerStageResources},
        {"maxComputeSharedMemorySize", l.maxComputeSharedMemorySize},
        {"maxComputeWorkGroupCount.x", l.maxComputeWorkGroupCount[0]},
        {"maxComputeWorkGroupCount.y", l.maxComputeWorkGroupCount[1]},
        {"maxComputeWorkGroupCount.z", l.maxComputeWorkGroupCount[2]},
        {"maxComputeWorkGroupInvocations", l.maxComputeWorkGroupInvocations},
        {"maxComputeWorkGroupSize.x", l.maxComputeWorkGroupSize[0]},
        {"maxComputeWorkGroupSize.y", l.maxComputeWorkGroupSize[1]},
        {"maxComputeWorkGroupSize.z", l.maxComputeWorkGroupSize[2]},
        {"maxUniformBufferRange", l.maxUniformBufferRange},
        {"maxStorageBufferRange", l.maxStorageBufferRange},
        {"minUniformBufferOffsetAlignment", l.minUniformBufferOffsetAlignment},
        {"minMemoryMapAlignment", l.minMemoryMapAlignment},
        {"nonCoherentAtomSize", l.nonCoherentAtomSize},
        {"optimalBufferCopyOffsetAlignment", l.optimalBufferCopyOffsetAlignment},
        {"optimalBufferCopyRowPitchAlignment", l.optimalBufferCopyRowPitchAlignment},
    };
    if (api12) {
        const std::pair<const char*, uint64_t> v12Limits[] = {
            {"maxUpdateAfterBindDescriptorsInAllPools", p12.maxUpdateAfterBindDescriptorsInAllPools},
            {"maxPerStageDescriptorUpdateAfterBindSamplers", p12.maxPerStageDescriptorUpdateAfterBindSamplers},
            {"maxPerStageDescriptorUpdateAfterBindUniformBuffers",
             p12.maxPerStageDescriptorUpdateAfterBindUniformBuffers},
            {"maxPerStageDescriptorUpdateAfterBindSampledImages",
             p12.maxPerStageDescriptorUpdateAfterBindSampledImages},
            {"maxPerStageDescriptorUpdateAfterBindStorageImages",
             p12.maxPerStageDescriptorUpdateAfterBindStorageImages},
            {"maxPerStageDescriptorUpdateAfterBindStorageBuffers",
             p12.maxPerStageDescriptorUpdateAfterBindStorageBuffers},
            {"maxPerStageUpdateAfterBindResources", p12.maxPerStageUpdateAfterBindResources},
            {"maxDescriptorSetUpdateAfterBindSamplers", p12.maxDescriptorSetUpdateAfterBindSamplers},
            {"maxDescriptorSetUpdateAfterBindUniformBuffers", p12.maxDescriptorSetUpdateAfterBindUniformBuffers},
            {"maxDescriptorSetUpdateAfterBindSampledImages", p12.maxDescriptorSetUpdateAfterBindSampledImages},
            {"maxDescriptorSetUpdateAfterBindStorageBuffers", p12.maxDescriptorSetUpdateAfterBindStorageBuffers},
            {"maxDescriptorSetUpdateAfterBindStorageImages", p12.maxDescriptorSetUpdateAfterBindStorageImages},
        };
        for (const auto& [name, value] : v12Limits) record.limits.emplace_back(name, value);
    }
    char period[32];
    std::snprintf(period, sizeof(period), "%.9g", static_cast<double>(l.timestampPeriod));
    record.properties = {
        {"timestampPeriod", period},
        {"timestampComputeAndGraphics", Bool(l.timestampComputeAndGraphics)},
    };
    if (api12) {
        const std::pair<const char*, std::string> floatControls[] = {
            {"denormBehaviorIndependence", Independence(p12.denormBehaviorIndependence)},
            {"roundingModeIndependence", Independence(p12.roundingModeIndependence)},
            {"shaderDenormPreserveFloat32", Bool(p12.shaderDenormPreserveFloat32)},
            {"shaderDenormFlushToZeroFloat32", Bool(p12.shaderDenormFlushToZeroFloat32)},
            {"shaderRoundingModeRTEFloat32", Bool(p12.shaderRoundingModeRTEFloat32)},
            {"shaderSignedZeroInfNanPreserveFloat32", Bool(p12.shaderSignedZeroInfNanPreserveFloat32)},
        };
        for (const auto& [name, value] : floatControls) record.properties.emplace_back(name, value);
    }

    auto features = Vk<VkPhysicalDeviceFeatures2>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2);
    auto v12 = Vk<VkPhysicalDeviceVulkan12Features>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES);
    auto dynamicRendering = Vk<VkPhysicalDeviceDynamicRenderingFeatures>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DYNAMIC_RENDERING_FEATURES);
    auto sync2 = Vk<VkPhysicalDeviceSynchronization2Features>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES);
    void** next = &features.pNext;
    auto chain = [&next](bool valid, auto& structure) {
        if (!valid) return;
        *next = &structure;
        next = &structure.pNext;
    };
    chain(api12, v12);
    chain(api13 || record.HasExtension("VK_KHR_dynamic_rendering"), dynamicRendering);
    chain(api13 || record.HasExtension("VK_KHR_synchronization2"), sync2);
    if (p.apiVersion >= VK_API_VERSION_1_1) {
        vkGetPhysicalDeviceFeatures2(physical, &features);
    } else {
        vkGetPhysicalDeviceFeatures(physical, &features.features);
    }
    const VkPhysicalDeviceFeatures& f = features.features;
    record.features = {
        {"timelineSemaphore", v12.timelineSemaphore == VK_TRUE},
        {"descriptorIndexing", v12.descriptorIndexing == VK_TRUE},
        {"bufferDeviceAddress", v12.bufferDeviceAddress == VK_TRUE},
        {"runtimeDescriptorArray", v12.runtimeDescriptorArray == VK_TRUE},
        {"descriptorBindingPartiallyBound", v12.descriptorBindingPartiallyBound == VK_TRUE},
        {"shaderSampledImageArrayNonUniformIndexing", v12.shaderSampledImageArrayNonUniformIndexing == VK_TRUE},
        {"descriptorBindingVariableDescriptorCount", v12.descriptorBindingVariableDescriptorCount == VK_TRUE},
        {"descriptorBindingSampledImageUpdateAfterBind",
         v12.descriptorBindingSampledImageUpdateAfterBind == VK_TRUE},
        {"descriptorBindingStorageImageUpdateAfterBind",
         v12.descriptorBindingStorageImageUpdateAfterBind == VK_TRUE},
        {"descriptorBindingUniformBufferUpdateAfterBind",
         v12.descriptorBindingUniformBufferUpdateAfterBind == VK_TRUE},
        {"dynamicRendering", dynamicRendering.dynamicRendering == VK_TRUE},
        {"synchronization2", sync2.synchronization2 == VK_TRUE},
        {"fillModeNonSolid", f.fillModeNonSolid == VK_TRUE},
        {"samplerAnisotropy", f.samplerAnisotropy == VK_TRUE},
        {"shaderStorageImageExtendedFormats", f.shaderStorageImageExtendedFormats == VK_TRUE},
        // Recorded, not required.
        {"shaderStorageImageReadWithoutFormat", f.shaderStorageImageReadWithoutFormat == VK_TRUE},
        {"shaderStorageImageWriteWithoutFormat", f.shaderStorageImageWriteWithoutFormat == VK_TRUE},
        {"shaderInt16", f.shaderInt16 == VK_TRUE},
        {"shaderInt64", f.shaderInt64 == VK_TRUE},
        {"shaderFloat64", f.shaderFloat64 == VK_TRUE},
        {"robustBufferAccess", f.robustBufferAccess == VK_TRUE},
        {"shaderFloat16", v12.shaderFloat16 == VK_TRUE},
        {"vulkanMemoryModel", v12.vulkanMemoryModel == VK_TRUE},
    };

    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, nullptr);
    std::vector<VkQueueFamilyProperties> families(count);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, families.data());
    families.resize(count);
    for (const VkQueueFamilyProperties& family : families) {
        record.queueFamilies.push_back({family.queueFlags, family.queueCount, family.timestampValidBits});
    }

    record.memoryBudget = record.HasExtension(VK_EXT_MEMORY_BUDGET_EXTENSION_NAME);
    auto budget = Vk<VkPhysicalDeviceMemoryBudgetPropertiesEXT>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_BUDGET_PROPERTIES_EXT);
    auto memory = Vk<VkPhysicalDeviceMemoryProperties2>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PROPERTIES_2);
    if (p.apiVersion >= VK_API_VERSION_1_1) {
        if (record.memoryBudget) memory.pNext = &budget;
        vkGetPhysicalDeviceMemoryProperties2(physical, &memory);
    } else {
        record.memoryBudget = false;
        vkGetPhysicalDeviceMemoryProperties(physical, &memory.memoryProperties);
    }
    const VkPhysicalDeviceMemoryProperties& m = memory.memoryProperties;
    for (uint32_t i = 0; i < m.memoryHeapCount; ++i) {
        record.heaps.push_back({m.memoryHeaps[i].size, m.memoryHeaps[i].flags,
                                record.memoryBudget ? budget.heapBudget[i] : 0,
                                record.memoryBudget ? budget.heapUsage[i] : 0});
    }
    for (uint32_t i = 0; i < m.memoryTypeCount; ++i) {
        record.memoryTypes.push_back({m.memoryTypes[i].propertyFlags, m.memoryTypes[i].heapIndex});
    }

    for (const auto& [format, name] : VulkanRecordedFormats()) {
        VkFormatProperties properties{};
        vkGetPhysicalDeviceFormatProperties(physical, static_cast<VkFormat>(format), &properties);
        record.formats.push_back({name, format, properties.optimalTilingFeatures,
                                  properties.linearTilingFeatures, properties.bufferFeatures});
    }
    return record;
}

/// The device UUID of the physical device a vendored device runs on.
std::string PhysicalDeviceUuid(VkPhysicalDevice physical) {
    auto id = Vk<VkPhysicalDeviceIDProperties>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES);
    auto props = Vk<VkPhysicalDeviceProperties2>(VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2);
    props.pNext = &id;
    vkGetPhysicalDeviceProperties2(physical, &props);
    return HexBytes(id.deviceUUID, VK_UUID_SIZE);
}

/// The device-level entry points `VulkanRequiredEntryPoints` names, as volk loaded them.
std::vector<std::pair<std::string_view, const void*>> VolkEntryPoints() {
    return {
        {"vkQueueSubmit", reinterpret_cast<const void*>(vkQueueSubmit)},
        {"vkWaitSemaphores", reinterpret_cast<const void*>(vkWaitSemaphores)},
        {"vkSignalSemaphore", reinterpret_cast<const void*>(vkSignalSemaphore)},
        {"vkGetSemaphoreCounterValue", reinterpret_cast<const void*>(vkGetSemaphoreCounterValue)},
        {"vkCmdPipelineBarrier2KHR", reinterpret_cast<const void*>(vkCmdPipelineBarrier2KHR)},
        {"vkCmdBeginRenderingKHR", reinterpret_cast<const void*>(vkCmdBeginRenderingKHR)},
        {"vkCmdEndRenderingKHR", reinterpret_cast<const void*>(vkCmdEndRenderingKHR)},
        {"vkCmdDispatch", reinterpret_cast<const void*>(vkCmdDispatch)},
        {"vkCmdCopyImageToBuffer", reinterpret_cast<const void*>(vkCmdCopyImageToBuffer)},
    };
}

Unexpected VulkanUnavailable(std::string reason) {
    return Fail(ErrorCode::GpuBackendUnavailable, Backend::Vulkan, std::move(reason));
}

}  // namespace

std::string_view VulkanTeardownName(VulkanTeardown teardown) {
    switch (teardown) {
        case VulkanTeardown::Live:      return "live";
        case VulkanTeardown::Destroyed: return "destroyed";
        case VulkanTeardown::Abandoned: return "abandoned";
    }
    return "unknown";
}

// ── Survey ───────────────────────────────────────────────────────────────────

VulkanSurvey SurveyVulkan() {
    VulkanSurvey survey;
    VulkanInstanceRecord& instance = survey.instance;
    const VkResult loaded = volkInitialize();
    if (loaded != VK_SUCCESS) {
        instance.loaderError = "the Vulkan loader vulkan-1.dll could not be loaded (volkInitialize: " +
                               VkResultText(loaded) + ")";
        return survey;
    }
    instance.loaderLoaded = true;
    instance.instanceVersion = volkGetInstanceVersion();

    uint32_t count = 0;
    vkEnumerateInstanceExtensionProperties(nullptr, &count, nullptr);
    std::vector<VkExtensionProperties> extensions(count);
    vkEnumerateInstanceExtensionProperties(nullptr, &count, extensions.data());
    extensions.resize(count);
    for (const VkExtensionProperties& extension : extensions) {
        instance.instanceExtensions.emplace_back(extension.extensionName);
    }
    if (instance.instanceVersion < VK_API_VERSION_1_2) {
        instance.instanceError = "not attempted: the loader offers Vulkan " +
                                 VulkanVersionText(instance.instanceVersion) + " only";
        return survey;
    }

    auto app = Vk<VkApplicationInfo>(VK_STRUCTURE_TYPE_APPLICATION_INFO);
    app.pApplicationName = "UzPainter Vulkan qualification";
    app.pEngineName = "UzPainter";
    app.apiVersion = VK_API_VERSION_1_2;
    auto create = Vk<VkInstanceCreateInfo>(VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO);
    create.pApplicationInfo = &app;
    VkInstance handle = VK_NULL_HANDLE;
    const VkResult created = vkCreateInstance(&create, nullptr, &handle);
    if (created != VK_SUCCESS) {
        instance.instanceError = "vkCreateInstance (apiVersion 1.2) failed: " + VkResultText(created);
        return survey;
    }
    instance.instanceCreated = true;
    volkLoadInstanceOnly(handle);
    vkEnumeratePhysicalDevices(handle, &count, nullptr);
    std::vector<VkPhysicalDevice> physical(count);
    vkEnumeratePhysicalDevices(handle, &count, physical.data());
    physical.resize(count);
    for (uint32_t i = 0; i < physical.size(); ++i) survey.devices.push_back(Describe(physical[i], i));
    vkDestroyInstance(handle, nullptr);
    return survey;
}

// ── Queue ────────────────────────────────────────────────────────────────────

/// The vendored device's graphics queue: one timeline fence (UZP-MOD-003), one command list per
/// in-flight submission, and a pre-recorded host-visibility barrier submitted after each one.
class VulkanQueue final : public IQueue {
public:
    VulkanQueue(uz::VulkanDevice& device, uz::IRHIFence* fence) : m_device(device), m_fence(fence) {}

    ~VulkanQueue() override {
        if (m_abandoned) return;
        for (const InFlight& entry : m_inFlight) m_device.DestroyCommandList(entry.list);
        for (uz::IRHICommandList* list : m_free) m_device.DestroyCommandList(list);
        if (m_barrierPool != VK_NULL_HANDLE) vkDestroyCommandPool(m_device.GetVkDevice(), m_barrierPool, nullptr);
        m_device.DestroyFence(m_fence);
    }

    /// Records the host-visibility barrier; false (with the reason) when it cannot.
    bool Init(std::string& reason) {
        auto poolInfo = Vk<VkCommandPoolCreateInfo>(VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO);
        poolInfo.queueFamilyIndex = m_device.GetGraphicsQueueFamily();
        VkResult result = vkCreateCommandPool(m_device.GetVkDevice(), &poolInfo, nullptr, &m_barrierPool);
        if (result != VK_SUCCESS) {
            reason = "vkCreateCommandPool failed: " + VkResultText(result);
            return false;
        }
        auto allocate = Vk<VkCommandBufferAllocateInfo>(VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO);
        allocate.commandPool = m_barrierPool;
        allocate.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        allocate.commandBufferCount = 1;
        result = vkAllocateCommandBuffers(m_device.GetVkDevice(), &allocate, &m_hostBarrier);
        if (result != VK_SUCCESS) {
            reason = "vkAllocateCommandBuffers failed: " + VkResultText(result);
            return false;
        }
        auto begin = Vk<VkCommandBufferBeginInfo>(VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO);
        begin.flags = VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT;
        vkBeginCommandBuffer(m_hostBarrier, &begin);
        auto barrier = Vk<VkMemoryBarrier2>(VK_STRUCTURE_TYPE_MEMORY_BARRIER_2);
        barrier.srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
        barrier.srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT;
        barrier.dstStageMask = VK_PIPELINE_STAGE_2_HOST_BIT;
        barrier.dstAccessMask = VK_ACCESS_2_HOST_READ_BIT;
        auto dependency = Vk<VkDependencyInfo>(VK_STRUCTURE_TYPE_DEPENDENCY_INFO);
        dependency.memoryBarrierCount = 1;
        dependency.pMemoryBarriers = &barrier;
        vkCmdPipelineBarrier2KHR(m_hostBarrier, &dependency);
        result = vkEndCommandBuffer(m_hostBarrier);
        if (result != VK_SUCCESS) {
            reason = "vkEndCommandBuffer failed: " + VkResultText(result);
            return false;
        }
        return true;
    }

    Result<uint64_t> Submit(const RecordFn& record) override {
        if (m_lostReason) return Unexpected(Lost());
        if (m_refused) {
            return Fail(ErrorCode::RequestFailed, Backend::Vulkan,
                        "the queue refused the fence signal of value " + std::to_string(m_refused->value) +
                            " (" + VkResultText(m_refused->result) + "); no later submission is accepted");
        }
        if (m_partial) {
            return Fail(ErrorCode::RequestFailed, Backend::Vulkan,
                        "a submission was refused after its command list reached the GPU (" +
                            VkResultText(*m_partial) + "); no later submission is accepted");
        }
        Retire();
        uz::IRHICommandList* list = nullptr;
        if (!m_free.empty()) {
            list = m_free.back();
            m_free.pop_back();
        } else {
            list = m_device.CreateCommandList(uz::RHIQueueType::Graphics);
            if (!list) return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan, "command list not created");
        }
        list->Begin();
        record(*list);
        list->End();
        // UZP-MOD-013: a draw or dispatch whose descriptor snapshot was not allocated would read
        // the list's shared working set, so the list is not submitted at all.
        if (const uint32_t missing = static_cast<uz::VulkanCommandList*>(list)->DescriptorSetFailures()) {
            m_free.push_back(list);
            return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                        std::to_string(missing) +
                            " dispatch(es) of the command list got no descriptor snapshot from the vendored "
                            "pool (decision 313); nothing was submitted");
        }
        list->Execute();
        // UZP-MOD-011: a refused command buffer never runs, so the list is free again at once.
        const VkResult executed = static_cast<uz::VulkanCommandList*>(list)->LastSubmitResult();
        if (executed != VK_SUCCESS) {
            m_free.push_back(list);
            return Refused("the command list", executed);
        }

        auto barrier = Vk<VkSubmitInfo>(VK_STRUCTURE_TYPE_SUBMIT_INFO);
        barrier.commandBufferCount = 1;
        barrier.pCommandBuffers = &m_hostBarrier;
        auto stallInfo = Vk<VkTimelineSemaphoreSubmitInfo>(VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO);
        const uint64_t stallValue = 1;
        const VkPipelineStageFlags stallStage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
        const VkSemaphore stall = std::exchange(m_stall, VK_NULL_HANDLE);
        if (stall != VK_NULL_HANDLE) {
            stallInfo.waitSemaphoreValueCount = 1;
            stallInfo.pWaitSemaphoreValues = &stallValue;
            barrier.pNext = &stallInfo;
            barrier.waitSemaphoreCount = 1;
            barrier.pWaitSemaphores = &stall;
            barrier.pWaitDstStageMask = &stallStage;
        }
        const VkResult barrierResult = vkQueueSubmit(m_device.GetGraphicsQueue(), 1, &barrier, VK_NULL_HANDLE);

        // The list is on the GPU: its fence value is signalled whatever the barrier did, so it
        // can be retired.
        ++m_lastSubmitted;
        m_fence->Signal(m_lastSubmitted);
        m_inFlight.push_back({list, m_lastSubmitted});
        const VkResult signalled = static_cast<uz::VulkanFence*>(m_fence)->LastSignalResult();
        if (signalled != VK_SUCCESS) {
            m_refused = RefusedSignal{m_lastSubmitted, signalled};
            if (signalled == VK_ERROR_DEVICE_LOST) m_lostReason = signalled;
            return Partial("the fence signal", signalled);
        }
        if (barrierResult != VK_SUCCESS) {
            m_partial = barrierResult;
            if (barrierResult == VK_ERROR_DEVICE_LOST) m_lostReason = barrierResult;
            return Partial("the host-visibility barrier", barrierResult);
        }
        return m_lastSubmitted;
    }

    WaitResult Wait(uint64_t value, Deadline deadline) override {
        if (m_lostReason) return {WaitStatus::DeviceLost, *m_lostReason};
        if (m_refused && value >= m_refused->value) return {WaitStatus::DeviceLost, m_refused->result};
        const uz::FenceWaitResult wait = m_fence->WaitCPU(value, deadline);
        switch (wait.status) {
            case uz::FenceWaitStatus::Signaled: return {WaitStatus::Signaled, 0};
            case uz::FenceWaitStatus::Timeout:  return {WaitStatus::Timeout, 0};
            case uz::FenceWaitStatus::DeviceLost: break;
        }
        if (wait.backendReason == VK_ERROR_DEVICE_LOST) m_lostReason = wait.backendReason;
        return {WaitStatus::DeviceLost, wait.backendReason};
    }

    uint64_t LastSubmitted() const override { return m_lastSubmitted; }
    uint64_t Completed() const override { return m_fence->GetCompletedValue(); }

    [[nodiscard]] std::optional<int32_t> LostReason() const { return m_lostReason; }
    /// A device loss, a refused fence signal, or a refused submission after the command list was
    /// accepted: the device keeps every resource from then on (`VulkanDevice::Usable`).
    [[nodiscard]] bool Failed() const {
        return m_lostReason.has_value() || m_refused.has_value() || m_partial.has_value();
    }
    [[nodiscard]] std::optional<int32_t> PartialReason() const {
        if (m_partial) return m_partial;
        if (m_refused) return m_refused->result;
        return std::nullopt;
    }

    /// Keeps every object of the queue alive and stops using it.
    void Abandon() { m_abandoned = true; }

    void ArmStall(VkSemaphore semaphore) { m_stall = semaphore; }

private:
    struct InFlight {
        uz::IRHICommandList* list;
        uint64_t value;
    };
    struct RefusedSignal {
        uint64_t value;
        int32_t result;
    };

    void Retire() {
        const uint64_t completed = Completed();
        std::erase_if(m_inFlight, [&](const InFlight& entry) {
            if (entry.value > completed) return false;
            m_free.push_back(entry.list);
            return true;
        });
    }

    Error Lost() const {
        return Error{ErrorCode::DeviceRemoved, Backend::Vulkan, VkResultText(*m_lostReason)};
    }

    /// A refusal after the command list was accepted: its work is on the GPU and may still use
    /// every resource it names, so the queue is failed for good (nothing is freed again).
    Unexpected Partial(const char* what, VkResult result) {
        if (result == VK_ERROR_DEVICE_LOST) return Unexpected(Lost());
        return Fail(ErrorCode::RequestFailed, Backend::Vulkan,
                    std::string("vkQueueSubmit refused ") + what + " (" + VkResultText(result) +
                        ") after the command list was submitted: its work may still run, so the device "
                        "is failed and keeps every resource until the process ends");
    }

    /// A refusal of the command list itself: nothing of it reached the GPU.
    Unexpected Refused(const char* what, VkResult result) {
        if (result == VK_ERROR_DEVICE_LOST) {
            m_lostReason = result;
            return Unexpected(Lost());
        }
        return Fail(ErrorCode::RequestFailed, Backend::Vulkan,
                    std::string("vkQueueSubmit refused ") + what + ": " + VkResultText(result));
    }

    uz::VulkanDevice& m_device;
    uz::IRHIFence* m_fence;
    VkCommandPool m_barrierPool = VK_NULL_HANDLE;
    VkCommandBuffer m_hostBarrier = VK_NULL_HANDLE;
    VkSemaphore m_stall = VK_NULL_HANDLE;
    uint64_t m_lastSubmitted = 0;
    std::vector<InFlight> m_inFlight;
    std::vector<uz::IRHICommandList*> m_free;
    std::optional<int32_t> m_lostReason;
    std::optional<RefusedSignal> m_refused;
    std::optional<int32_t> m_partial;
    bool m_abandoned = false;
};

// ── Device ───────────────────────────────────────────────────────────────────

Result<std::unique_ptr<VulkanDevice>> CreateQualifiedVulkanDevice(const VulkanSurvey& survey,
                                                                 const VulkanQualification& qualification,
                                                                 const VulkanDeviceOptions& options) {
    if (!qualification.qualified || !qualification.device || *qualification.device >= survey.devices.size() ||
        !qualification.queueFamily) {
        return VulkanUnavailable("refused before any work: " + qualification.Summary(survey));
    }
    const VulkanDeviceRecord& record = survey.devices[*qualification.device];
    uz::RHIDeviceDesc desc;
    desc.backend = uz::RHIBackend::Vulkan;
    desc.adapterIndex = qualification.adapterIndex;
    desc.enableValidation = options.enableValidation;
    std::unique_ptr<uz::IRHIDevice> rhi = uz::CreateRHIDevice(desc);
    if (!rhi) {
        return VulkanUnavailable("the vendored Vulkan device was not created on the qualified device '" +
                                 record.name + "' (the render core log has the cause)");
    }
    auto* native = static_cast<uz::VulkanDevice*>(rhi.get());
    // The instance asks for Vulkan 1.2: the backend records through the device-level entry points
    // of 1.2 and of the extensions it enables, which volk loaded for this device.
    const std::vector<std::string> missing = MissingVulkanEntryPoints([](std::string_view name) {
        for (const auto& [entry, pointer] : VolkEntryPoints()) {
            if (entry == name) return pointer != nullptr;
        }
        return false;
    });
    if (!missing.empty()) {
        std::string names;
        for (const std::string& name : missing) names += (names.empty() ? "" : ", ") + name;
        return VulkanUnavailable("the device '" + record.name + "' does not resolve the entry points " + names +
                                 "; nothing was submitted");
    }
    const std::string uuid = PhysicalDeviceUuid(native->GetVkPhysicalDevice());
    if (uuid != record.deviceUuid || native->GetGraphicsQueueFamily() != *qualification.queueFamily) {
        return VulkanUnavailable("the vendored backend took device " + uuid + " queue family " +
                                 std::to_string(native->GetGraphicsQueueFamily()) + ", not the judged '" +
                                 record.name + "' (" + record.deviceUuid + ") queue family " +
                                 std::to_string(*qualification.queueFamily));
    }
    std::unique_ptr<VulkanDevice> device(new VulkanDevice(std::move(rhi), record, qualification, options));
    if (!device->m_queue) {
        return VulkanUnavailable("the Vulkan device '" + record.name + "' could not create its queue fence");
    }
    std::string reason;
    if (!device->m_queue->Init(reason)) {
        return VulkanUnavailable("the Vulkan device '" + record.name + "' could not record its host barrier: " +
                                 reason);
    }
    return device;
}

VulkanDevice::VulkanDevice(std::unique_ptr<uz::IRHIDevice> rhi, VulkanDeviceRecord record,
                           VulkanQualification qualification, const VulkanDeviceOptions& options)
    : m_rhi(std::move(rhi)),
      m_native(static_cast<uz::VulkanDevice*>(m_rhi.get())),
      m_record(std::move(record)),
      m_qualification(std::move(qualification)),
      m_options(options) {
    if (uz::IRHIFence* fence = m_rhi->CreateFence()) m_queue = std::make_unique<VulkanQueue>(*m_native, fence);
}

VulkanDevice::~VulkanDevice() {
    if (Shutdown(Clock::now() + m_options.teardownDeadline) == VulkanTeardown::Abandoned) {
        // Kept on purpose: the GPU may still use every object of an abandoned device.
        static_cast<void>(m_queue.release());
        static_cast<void>(m_rhi.release());
    }
}

VulkanTeardown VulkanDevice::Shutdown(Deadline deadline) {
    if (m_teardown != VulkanTeardown::Live) return m_teardown;
    // Without a queue nothing was ever submitted.
    bool complete = !m_queue || !m_queue->Failed();
    if (complete && m_queue) {
        complete = m_queue->Wait(m_queue->LastSubmitted(), deadline).status == WaitStatus::Signaled;
    }
    if (!complete) {
        // Nothing is destroyed or waited on again: the GPU may still use every object. The
        // destructor leaks them.
        if (m_queue) m_queue->Abandon();
        m_teardown = VulkanTeardown::Abandoned;
        UZ_LOG(RHI, Error, "Vulkan device '{}' abandoned at teardown: its work did not complete", m_record.name);
        return m_teardown;
    }
    // Every submission has completed; the vendored destructor's vkDeviceWaitIdle (no timeout)
    // runs after that, not bounded by `deadline`.
    m_queue.reset();
    m_rhi.reset();
    m_teardown = VulkanTeardown::Destroyed;
    return m_teardown;
}

bool VulkanDevice::Usable() const { return m_teardown == VulkanTeardown::Live && m_queue && !m_queue->Failed(); }

IQueue& VulkanDevice::Queue() { return *m_queue; }

uz::IRHIDevice& VulkanDevice::Rhi() { return *m_rhi; }

Result<uz::RHIBufferHandle> VulkanDevice::CreateBuffer(const uz::RHIBufferDesc& desc) {
    if (!Usable()) return Unexpected(*CheckRemoved());
    const uz::RHIBufferHandle buffer = m_rhi->CreateBuffer(desc);
    if (!buffer.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                    "buffer of " + std::to_string(desc.sizeBytes) + " bytes not created");
    }
    return buffer;
}

void VulkanDevice::DestroyBuffer(uz::RHIBufferHandle buffer) {
    // A failed device may still use its objects: they stay until the process ends.
    if (Usable() && buffer.IsValid()) m_rhi->DestroyBuffer(buffer);
}

Result<uz::RHITextureHandle> VulkanDevice::CreateTexture(const uz::RHITextureDesc& desc) {
    if (!Usable()) return Unexpected(*CheckRemoved());
    const uz::RHITextureHandle texture = m_rhi->CreateTexture(desc);
    if (!texture.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                    "texture " + std::to_string(desc.width) + "x" + std::to_string(desc.height) + " not created");
    }
    return texture;
}

void VulkanDevice::DestroyTexture(uz::RHITextureHandle texture) {
    if (Usable() && texture.IsValid()) m_rhi->DestroyTexture(texture);
}

std::optional<uz::RHITextureDesc> VulkanDevice::TextureDesc(uz::RHITextureHandle texture) const {
    if (m_teardown != VulkanTeardown::Live) return std::nullopt;
    const uz::VulkanTexture* entry = m_native->GetTexturePool().Get(texture.index, texture.generation);
    if (!entry || entry->image == VK_NULL_HANDLE) return std::nullopt;
    return entry->desc;
}

Result<ComputeKernel> VulkanDevice::CreateComputeKernel(std::span<const uint8_t> bytecode, const std::string& name) {
    if (!Usable()) return Unexpected(*CheckRemoved());
    uz::RHIShaderDesc shaderDesc;
    shaderDesc.bytecode = bytecode.data();
    shaderDesc.bytecodeSize = bytecode.size();
    shaderDesc.stage = uz::RHIShaderStage::Compute;
    shaderDesc.debugName = name.c_str();
    ComputeKernel kernel;
    kernel.shader = m_rhi->CreateShader(shaderDesc);
    if (!kernel.shader.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                    "shader module of kernel '" + name + "' not created");
    }
    uz::RHIComputePipelineDesc pipelineDesc;
    pipelineDesc.computeShader = kernel.shader;
    pipelineDesc.debugName = name.c_str();
    kernel.pipeline = m_rhi->CreateComputePipeline(pipelineDesc);
    if (!kernel.pipeline.IsValid()) {
        m_rhi->DestroyShader(kernel.shader);
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                    "compute pipeline of kernel '" + name + "' not created");
    }
    return kernel;
}

void VulkanDevice::DestroyComputeKernel(const ComputeKernel& kernel) {
    if (!Usable()) return;
    if (kernel.pipeline.IsValid()) m_rhi->DestroyPipeline(kernel.pipeline);
    if (kernel.shader.IsValid()) m_rhi->DestroyShader(kernel.shader);
}

std::optional<Error> VulkanDevice::CheckRemoved() const {
    if (m_teardown == VulkanTeardown::Abandoned) {
        return Error{ErrorCode::DeviceRemoved, Backend::Vulkan, "the device was abandoned at teardown"};
    }
    if (m_teardown == VulkanTeardown::Destroyed) {
        return Error{ErrorCode::DeviceRemoved, Backend::Vulkan, "the device was destroyed"};
    }
    if (const std::optional<int32_t> lost = m_queue ? m_queue->LostReason() : std::nullopt) {
        return Error{ErrorCode::DeviceRemoved, Backend::Vulkan, VkResultText(*lost)};
    }
    if (const std::optional<int32_t> partial = m_queue ? m_queue->PartialReason() : std::nullopt) {
        return Error{ErrorCode::RequestFailed, Backend::Vulkan,
                     "a submission was refused after its command list reached the GPU (" +
                         VkResultText(*partial) + "); the device keeps every resource"};
    }
    return std::nullopt;
}

Error VulkanDevice::WaitFailure(const WaitResult& wait) const {
    if (wait.status == WaitStatus::Timeout) {
        return Error{ErrorCode::Timeout, Backend::Vulkan,
                     "the GPU did not complete the submitted work before the deadline"};
    }
    if (wait.backendReason == VK_ERROR_DEVICE_LOST) {
        return Error{ErrorCode::DeviceRemoved, Backend::Vulkan, VkResultText(wait.backendReason)};
    }
    return Error{ErrorCode::RequestFailed, Backend::Vulkan,
                 "the fence wait failed: " + VkResultText(wait.backendReason)};
}

uint32_t VulkanDevice::MaxDispatchesPerSubmission() const {
    const uint32_t sets = DeriveVulkanDescriptorModel(m_record).setsInPool / 2;
    return sets > uz::kVulkanFrameCount ? sets - uz::kVulkanFrameCount : 1;
}

const void* VulkanDevice::MapReadback(uz::RHIBufferHandle buffer) {
    if (!Usable()) return nullptr;
    uz::VulkanBuffer* entry = m_native->GetBufferPool().Get(buffer.index, buffer.generation);
    if (!entry || entry->buffer == VK_NULL_HANDLE || !entry->mappedPtr) return nullptr;
    if (vmaInvalidateAllocation(m_native->GetAllocator(), entry->allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
        return nullptr;
    }
    return entry->mappedPtr;
}

Result<std::function<void()>> VulkanDevice::InjectQueueStall() {
    if (!Usable()) return Unexpected(*CheckRemoved());
    auto timeline = Vk<VkSemaphoreTypeCreateInfo>(VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO);
    timeline.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    auto create = Vk<VkSemaphoreCreateInfo>(VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO);
    create.pNext = &timeline;
    VkSemaphore semaphore = VK_NULL_HANDLE;
    const VkResult result = vkCreateSemaphore(m_native->GetVkDevice(), &create, nullptr, &semaphore);
    if (result != VK_SUCCESS) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Vulkan,
                    "stall semaphore not created: " + VkResultText(result));
    }
    // The semaphore is never destroyed, so the release stays valid on an abandoned device.
    m_queue->ArmStall(semaphore);
    const VkDevice device = m_native->GetVkDevice();
    const PFN_vkSignalSemaphore signal = vkSignalSemaphore;
    return std::function<void()>([device, semaphore, signal] {
        auto info = Vk<VkSemaphoreSignalInfo>(VK_STRUCTURE_TYPE_SEMAPHORE_SIGNAL_INFO);
        info.semaphore = semaphore;
        info.value = 1;
        signal(device, &info);
    });
}

}  // namespace uzp::render
