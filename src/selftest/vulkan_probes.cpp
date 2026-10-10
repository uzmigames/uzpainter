// Vulkan probes of `selftest`: availability and inline ray queries (probes.h). The system loader
// `vulkan-1.dll` (installed by the GPU driver, never shipped: 13-engine-integration.md §5) is
// loaded here and handed to volk; no Vulkan device is created (the Vulkan hardware selftest is
// part of the P3-VULKAN gate).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#include "probes.h"

#include <volk.h>

#include <windows.h>

#include <cstdio>
#include <memory>
#include <string>
#include <vector>

namespace uzp::selftest {

namespace {

std::string Hex(uint32_t value, int digits) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%0*X", digits, value);
    return buf;
}

/// The system's text for an error code, in US English when the system has it.
std::string SystemMessage(DWORD code) {
    constexpr DWORD kFlags =
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS;
    wchar_t* text = nullptr;
    DWORD length = FormatMessageW(kFlags, nullptr, code, MAKELANGID(LANG_ENGLISH, SUBLANG_ENGLISH_US),
                                  reinterpret_cast<wchar_t*>(&text), 0, nullptr);
    if (length == 0) {
        length = FormatMessageW(kFlags, nullptr, code, 0, reinterpret_cast<wchar_t*>(&text), 0,
                                nullptr);
    }
    std::string out;
    if (length && text) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, text, static_cast<int>(length), nullptr, 0,
                                             nullptr, nullptr);
        out.resize(static_cast<size_t>(size));
        WideCharToMultiByte(CP_UTF8, 0, text, static_cast<int>(length), out.data(), size, nullptr,
                            nullptr);
        while (!out.empty() && (out.back() == '\n' || out.back() == '\r' || out.back() == ' ' ||
                                out.back() == '.')) {
            out.pop_back();
        }
    }
    if (text) LocalFree(text);
    if (const size_t insert = out.find("%1"); insert != std::string::npos) {
        out.replace(insert, 2, "vulkan-1.dll");
    }
    return out;
}

std::string ModulePath(HMODULE module) {
    wchar_t path[MAX_PATH] = {};
    const DWORD length = GetModuleFileNameW(module, path, MAX_PATH);
    const int size = WideCharToMultiByte(CP_UTF8, 0, path, static_cast<int>(length), nullptr, 0,
                                         nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, path, static_cast<int>(length), out.data(), size, nullptr,
                        nullptr);
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

/// The driver version in the vendor's own encoding (NVIDIA 10.8.8.6 bits, Intel on Windows 18.14
/// bits, otherwise the Vulkan version encoding).
std::string DriverVersionName(uint32_t vendor, uint32_t version) {
    if (vendor == 0x10DE) {
        return std::to_string(version >> 22) + "." + std::to_string((version >> 14) & 0xFF) + "." +
               std::to_string((version >> 6) & 0xFF) + "." + std::to_string(version & 0x3F);
    }
    if (vendor == 0x8086) return std::to_string(version >> 14) + "." + std::to_string(version & 0x3FFF);
    return VulkanVersionName(version);
}

VulkanDeviceInfo Describe(VkPhysicalDevice physical) {
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical, &props);
    VulkanDeviceInfo info;
    info.name = props.deviceName;
    info.type = TypeName(props.deviceType);
    info.apiVersion = props.apiVersion;

    uint32_t count = 0;
    vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, nullptr);
    std::vector<VkExtensionProperties> extensions(count);
    vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, extensions.data());
    for (const VkExtensionProperties& extension : extensions) {
        info.extensions.emplace_back(extension.extensionName);
    }

    // Structures are chained only where the device's API version or an exposed extension makes
    // them valid.
    const bool api12 = props.apiVersion >= VK_API_VERSION_1_2;
    const bool api13 = props.apiVersion >= VK_API_VERSION_1_3;
    VkPhysicalDeviceIDProperties id{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES};
    VkPhysicalDeviceDriverProperties driver{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceProperties2 props2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    if (props.apiVersion >= VK_API_VERSION_1_1) {
        props2.pNext = &id;
        if (api12) id.pNext = &driver;
        vkGetPhysicalDeviceProperties2(physical, &props2);
    }

    VkPhysicalDeviceFeatures2 features2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    VkPhysicalDeviceVulkan12Features v12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceDynamicRenderingFeatures dynamicRendering{
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DYNAMIC_RENDERING_FEATURES};
    VkPhysicalDeviceSynchronization2Features sync2{
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES};
    VkPhysicalDeviceAccelerationStructureFeaturesKHR accel{
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ACCELERATION_STRUCTURE_FEATURES_KHR};
    VkPhysicalDeviceRayQueryFeaturesKHR rayQuery{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_QUERY_FEATURES_KHR};
    void** next = &features2.pNext;
    auto chain = [&next](bool valid, auto& structure) {
        if (!valid) return;
        *next = &structure;
        next = &structure.pNext;
    };
    chain(api12, v12);
    chain(api13 || info.HasExtension("VK_KHR_dynamic_rendering"), dynamicRendering);
    chain(api13 || info.HasExtension("VK_KHR_synchronization2"), sync2);
    chain(info.HasExtension("VK_KHR_acceleration_structure"), accel);
    chain(info.HasExtension("VK_KHR_ray_query"), rayQuery);
    if (props.apiVersion >= VK_API_VERSION_1_1) {
        vkGetPhysicalDeviceFeatures2(physical, &features2);
    } else {
        vkGetPhysicalDeviceFeatures(physical, &features2.features);
    }

    info.features = {
        {"timelineSemaphore", v12.timelineSemaphore == VK_TRUE},
        {"descriptorIndexing", v12.descriptorIndexing == VK_TRUE},
        {"bufferDeviceAddress", v12.bufferDeviceAddress == VK_TRUE},
        {"runtimeDescriptorArray", v12.runtimeDescriptorArray == VK_TRUE},
        {"descriptorBindingPartiallyBound", v12.descriptorBindingPartiallyBound == VK_TRUE},
        {"shaderSampledImageArrayNonUniformIndexing",
         v12.shaderSampledImageArrayNonUniformIndexing == VK_TRUE},
        {"descriptorBindingVariableDescriptorCount",
         v12.descriptorBindingVariableDescriptorCount == VK_TRUE},
        {"descriptorBindingSampledImageUpdateAfterBind",
         v12.descriptorBindingSampledImageUpdateAfterBind == VK_TRUE},
        {"descriptorBindingStorageImageUpdateAfterBind",
         v12.descriptorBindingStorageImageUpdateAfterBind == VK_TRUE},
        {"descriptorBindingUniformBufferUpdateAfterBind",
         v12.descriptorBindingUniformBufferUpdateAfterBind == VK_TRUE},
        {"dynamicRendering", dynamicRendering.dynamicRendering == VK_TRUE},
        {"synchronization2", sync2.synchronization2 == VK_TRUE},
        {"fillModeNonSolid", features2.features.fillModeNonSolid == VK_TRUE},
        {"samplerAnisotropy", features2.features.samplerAnisotropy == VK_TRUE},
        {"accelerationStructure", accel.accelerationStructure == VK_TRUE},
        {"rayQuery", rayQuery.rayQuery == VK_TRUE},
    };

    const std::string version = DriverVersionName(props.vendorID, props.driverVersion);
    info.driver = api12 ? std::string(driver.driverName) + " " + driver.driverInfo : version;
    std::string luid = "invalid";
    if (id.deviceLUIDValid) {
        luid.clear();
        for (int i = 7; i >= 0; --i) {
            char buf[4];
            std::snprintf(buf, sizeof(buf), "%02X", id.deviceLUID[i]);
            luid += buf;
        }
    }
    info.facts = {
        {"name", info.name},
        {"type", info.type},
        {"api_version", VulkanVersionName(props.apiVersion)},
        {"driver_version", version},
        {"driver_name", api12 ? driver.driverName : ""},
        {"driver_info", api12 ? driver.driverInfo : ""},
        {"vendor_id", Hex(props.vendorID, 4)},
        {"device_id", Hex(props.deviceID, 4)},
        {"luid", luid},
        {"extension_count", std::to_string(info.extensions.size())},
    };
    return info;
}

/// Loads the loader, creates a Vulkan 1.2 instance and describes every physical device. Every
/// Vulkan object and the loader are released before returning.
VulkanProbeState Gather() {
    VulkanProbeState state;
    VulkanLoaderInfo& loader = state.loader;
    HMODULE library = LoadLibraryW(L"vulkan-1.dll");
    if (!library) {
        const DWORD code = GetLastError();
        loader.error = "the Vulkan loader vulkan-1.dll could not be loaded: error " +
                       std::to_string(code) + " (" + SystemMessage(code) + ")";
        return state;
    }
    loader.path = ModulePath(library);
    auto getInstanceProcAddr = reinterpret_cast<PFN_vkGetInstanceProcAddr>(
        reinterpret_cast<void*>(GetProcAddress(library, "vkGetInstanceProcAddr")));
    if (!getInstanceProcAddr) {
        loader.error = "the Vulkan loader " + loader.path + " exports no vkGetInstanceProcAddr";
        FreeLibrary(library);
        return state;
    }
    loader.loaded = true;
    volkInitializeCustom(getInstanceProcAddr);
    loader.instanceVersion = volkGetInstanceVersion();

    if (loader.instanceVersion >= VK_API_VERSION_1_2) {
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
        app.pApplicationName = "UzPainter selftest";
        app.pEngineName = "UzPainter";
        app.apiVersion = VK_API_VERSION_1_2;
        VkInstanceCreateInfo create{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
        create.pApplicationInfo = &app;
        VkInstance instance = VK_NULL_HANDLE;
        const VkResult result = vkCreateInstance(&create, nullptr, &instance);
        if (result != VK_SUCCESS) {
            loader.instanceError = "vkCreateInstance (apiVersion 1.2) failed, VkResult " +
                                   std::to_string(static_cast<int>(result));
        } else {
            loader.instanceCreated = true;
            volkLoadInstanceOnly(instance);
            uint32_t count = 0;
            vkEnumeratePhysicalDevices(instance, &count, nullptr);
            std::vector<VkPhysicalDevice> physical(count);
            vkEnumeratePhysicalDevices(instance, &count, physical.data());
            physical.resize(count);
            for (VkPhysicalDevice device : physical) state.devices.push_back(Describe(device));
            vkDestroyInstance(instance, nullptr);
        }
    }
    volkFinalize();
    FreeLibrary(library);

    if (!state.devices.empty()) {
        const size_t selected = SelectedVulkanDevice(state.devices);
        for (size_t i = 0; i < state.devices.size(); ++i) {
            state.devices[i].facts.emplace_back("selected", i == selected ? "yes" : "no");
        }
    }
    return state;
}

}  // namespace

ProbeReport ProbeVulkanAvailability(SelftestContext& context) {
    context.vulkan = std::make_shared<VulkanProbeState>(Gather());
    return EvaluateVulkanAvailability(*context.vulkan);
}

ProbeReport ProbeVulkanRayQuery(SelftestContext& context) {
    if (!context.vulkan) {
        return NotCompleted("vulkan-ray-query", "vulkan",
                            "the vulkan-availability probe did not complete");
    }
    return EvaluateVulkanRayQuery(*context.vulkan);
}

}  // namespace uzp::selftest
