// Probe report model and the pure probe decisions (probe_report.h).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "probe_report.h"

#include "json_text.h"

#include "dx12_device.h"

#include <algorithm>
#include <sstream>

namespace uzp::selftest {

// ── Report ───────────────────────────────────────────────────────────────────

namespace {

std::string Bool(bool value) { return value ? "true" : "false"; }

std::string StringArray(const std::vector<std::string>& items) {
    std::string out = "[";
    for (size_t i = 0; i < items.size(); ++i) out += (i ? ", " : "") + JsonString(items[i]);
    return out + "]";
}

std::string DetailsObject(const Details& details, const std::string& indent) {
    if (details.empty()) return "{}";
    std::string out = "{";
    for (size_t i = 0; i < details.size(); ++i) {
        out += std::string(i ? "," : "") + "\n" + indent + "  " + JsonString(details[i].first) +
               ": " + JsonString(details[i].second);
    }
    return out + "\n" + indent + "}";
}

}  // namespace

std::string ProbeReport::ToJson(const std::string& indent) const {
    const std::string in = indent + "  ";
    std::ostringstream out;
    out << "{\n";
    out << in << "\"probe\": " << JsonString(probe) << ",\n";
    out << in << "\"backend\": " << JsonString(backend) << ",\n";
    out << in << "\"adapter\": " << JsonString(adapter) << ",\n";
    out << in << "\"driver\": " << JsonString(driver) << ",\n";
    out << in << "\"completed\": " << Bool(completed) << ",\n";
    out << in << "\"qualified\": " << Bool(qualified) << ",\n";
    out << in << "\"verdict\": " << JsonString(verdict) << ",\n";
    out << in << "\"error\": " << JsonString(error) << ",\n";
    out << in << "\"supported\": " << StringArray(supported) << ",\n";
    out << in << "\"executed_checks\": [";
    for (size_t i = 0; i < executedChecks.size(); ++i) {
        const ExecutedCheck& c = executedChecks[i];
        out << (i ? "," : "") << "\n" << in << "  {\"check\": " << JsonString(c.check)
            << ", \"result\": " << JsonString(c.passed ? "passed" : "failed")
            << ", \"detail\": " << JsonString(c.detail) << "}";
    }
    out << (executedChecks.empty() ? "]" : "\n" + in + "]") << ",\n";
    out << in << "\"unsupported\": [";
    for (size_t i = 0; i < unsupported.size(); ++i) {
        out << (i ? "," : "") << "\n" << in << "  {\"item\": " << JsonString(unsupported[i].item)
            << ", \"reason\": " << JsonString(unsupported[i].reason) << "}";
    }
    out << (unsupported.empty() ? "]" : "\n" + in + "]") << ",\n";
    if (hasHostedLane) out << in << "\"hosted_warp_lane\": " << StringArray(hostedLane) << ",\n";
    out << in << "\"devices\": [";
    for (size_t i = 0; i < devices.size(); ++i) {
        const DeviceRecord& d = devices[i];
        const std::string din = in + "  ";
        out << (i ? "," : "") << "\n" << din << "{\n";
        out << din << "  \"facts\": " << DetailsObject(d.facts, din + "  ") << ",\n";
        out << din << "  \"features\": {";
        for (size_t f = 0; f < d.features.size(); ++f) {
            out << (f ? ", " : "") << JsonString(d.features[f].first) << ": "
                << Bool(d.features[f].second);
        }
        out << "},\n";
        out << din << "  \"extensions\": " << StringArray(d.extensions) << "\n";
        out << din << "}";
    }
    out << (devices.empty() ? "]" : "\n" + in + "]") << ",\n";
    out << in << "\"facts\": " << DetailsObject(facts, in) << "\n";
    out << indent << "}";
    return out.str();
}

ProbeReport NotCompleted(std::string probe, std::string backend, std::string error) {
    ProbeReport report;
    report.probe = std::move(probe);
    report.backend = std::move(backend);
    report.completed = false;
    report.qualified = false;
    report.verdict = "probe not completed";
    report.error = std::move(error);
    return report;
}

StageOutcome ProbeOutcome(const ProbeReport& report) {
    std::string missing;
    for (const UnsupportedItem& item : report.unsupported) {
        missing += (missing.empty() ? "" : "; ") + item.item + ": " + item.reason;
    }
    Details details = {{"completed", report.completed ? "yes" : "no"},
                       {"qualified", report.qualified ? "yes" : "no"},
                       {"verdict", report.verdict}};
    if (!report.adapter.empty()) details.emplace_back("adapter", report.adapter);
    if (!report.driver.empty()) details.emplace_back("driver", report.driver);
    if (!missing.empty()) details.emplace_back("unsupported", missing);
    if (report.hasHostedLane) {
        std::string lane;
        for (const std::string& check : report.hostedLane) lane += (lane.empty() ? "" : ", ") + check;
        details.emplace_back("hosted_warp_lane", lane.empty() ? "none" : lane);
    }
    if (!report.completed) {
        return {StageStatus::Failed, "probe not completed: " + report.error, std::move(details)};
    }
    return {StageStatus::Passed, {}, std::move(details)};
}

// ── DX12 inline ray queries ──────────────────────────────────────────────────

std::string DxrTierName(uint32_t tier) {
    if (tier == kDxrTierNotSupported) return "not supported";
    return "Tier " + std::to_string(tier / 10) + "." + std::to_string(tier % 10);
}

std::string ShaderModelName(uint32_t model) {
    return std::to_string(model >> 4) + "." + std::to_string(model & 0xF);
}

ProbeReport EvaluateDx12RayQuery(uint32_t raytracingTier, uint32_t highestShaderModel,
                                 std::string adapter, std::string driver) {
    ProbeReport report;
    report.probe = "dx12-ray-query";
    report.backend = "dx12";
    report.adapter = std::move(adapter);
    report.driver = std::move(driver);
    report.facts = {{"raytracing_tier", DxrTierName(raytracingTier)},
                    {"highest_shader_model", ShaderModelName(highestShaderModel)}};

    const bool tierOk = raytracingTier >= kDxrTier1_1;
    const bool modelOk = highestShaderModel >= kShaderModel6_6;
    report.executedChecks.push_back(
        {"D3D12_FEATURE_D3D12_OPTIONS5 RaytracingTier >= Tier 1.1", tierOk, DxrTierName(raytracingTier)});
    report.executedChecks.push_back({"D3D12_FEATURE_SHADER_MODEL HighestShaderModel >= 6.6", modelOk,
                                     ShaderModelName(highestShaderModel)});
    if (tierOk) {
        report.supported.push_back("DXR " + DxrTierName(raytracingTier));
    } else {
        report.unsupported.push_back(
            {"DXR Tier 1.1", "the device reports DXR " + DxrTierName(raytracingTier) +
                                 "; inline ray queries (RayQuery) need Tier 1.1"});
    }
    if (modelOk) {
        report.supported.push_back("Shader Model " + ShaderModelName(highestShaderModel));
    } else {
        report.unsupported.push_back(
            {"Shader Model 6.6", "the device reports highest shader model " +
                                     ShaderModelName(highestShaderModel) +
                                     "; UzPainter's kernels target SM 6.6"});
    }

    const bool vendored = uz::DX12SupportsInlineRayQuery(
        static_cast<D3D12_RAYTRACING_TIER>(raytracingTier),
        static_cast<D3D_SHADER_MODEL>(highestShaderModel));
    report.executedChecks.push_back(
        {"DX12SupportsInlineRayQuery (UZP-MOD-004)", vendored, vendored ? "true" : "false"});
    if (vendored != report.unsupported.empty()) {
        return NotCompleted(report.probe, report.backend,
                            "the vendored DX12SupportsInlineRayQuery decided " +
                                std::string(vendored ? "true" : "false") +
                                " against the probe's own reading of the tier and shader model");
    }
    report.completed = true;
    report.qualified = vendored;
    report.verdict = vendored ? "supported" : "unsupported";
    return report;
}

// ── Vulkan ───────────────────────────────────────────────────────────────────

bool VulkanDeviceInfo::HasExtension(const std::string& name) const {
    return std::find(extensions.begin(), extensions.end(), name) != extensions.end();
}

bool VulkanDeviceInfo::Feature(const std::string& name) const {
    for (const auto& [feature, enabled] : features) {
        if (feature == name) return enabled;
    }
    return false;
}

std::string VulkanVersionName(uint32_t version) {
    // VK_API_VERSION_MAJOR / MINOR / PATCH.
    return std::to_string((version >> 22) & 0x7Fu) + "." + std::to_string((version >> 12) & 0x3FFu) +
           "." + std::to_string(version & 0xFFFu);
}

namespace {

constexpr uint32_t kVulkan1_2 = (1u << 22) | (2u << 12);

int TypePriority(const std::string& type) {
    if (type == "discrete") return 4;
    if (type == "integrated") return 3;
    if (type == "virtual") return 2;
    if (type == "cpu") return 1;
    return 0;
}

/// Why Vulkan as a whole is unavailable before any device is looked at; empty when a device exists.
UnsupportedItem VulkanUnavailableReason(const VulkanProbeState& state) {
    const VulkanLoaderInfo& loader = state.loader;
    if (!loader.loaded) return {"Vulkan loader (vulkan-1.dll)", loader.error};
    if (loader.instanceVersion < kVulkan1_2) {
        return {"Vulkan 1.2 instance", "the loader " + loader.path + " supports Vulkan " +
                                           VulkanVersionName(loader.instanceVersion) +
                                           " only; Vulkan 1.2 is needed (loader too old)"};
    }
    if (!loader.instanceCreated) return {"Vulkan 1.2 instance", loader.instanceError};
    if (state.devices.empty()) {
        return {"Vulkan physical device", "the Vulkan 1.2 instance enumerates no physical device"};
    }
    return {};
}

}  // namespace

size_t SelectedVulkanDevice(const std::vector<VulkanDeviceInfo>& devices) {
    size_t best = 0;
    for (size_t i = 1; i < devices.size(); ++i) {
        if (TypePriority(devices[i].type) > TypePriority(devices[best].type)) best = i;
    }
    return best;
}

const std::vector<std::string>& VulkanRequiredExtensions() {
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
    };
    return names;
}

const std::vector<std::string>& VulkanRayQueryExtensions() {
    static const std::vector<std::string> names = {
        "VK_KHR_acceleration_structure",
        "VK_KHR_deferred_host_operations",
        "VK_KHR_ray_query",
    };
    return names;
}

const std::vector<std::string>& VulkanRayQueryFeatures() {
    static const std::vector<std::string> names = {"accelerationStructure", "rayQuery"};
    return names;
}

ProbeReport EvaluateVulkanAvailability(const VulkanProbeState& state) {
    ProbeReport report;
    report.probe = "vulkan-availability";
    report.backend = "vulkan";
    report.completed = true;
    const VulkanLoaderInfo& loader = state.loader;
    report.facts = {{"loader", loader.loaded ? loader.path : "not loaded"},
                    {"loader_instance_version",
                     loader.loaded ? VulkanVersionName(loader.instanceVersion) : "none"},
                    {"instance_api_version_requested", "1.2"},
                    {"physical_devices", std::to_string(state.devices.size())}};
    for (const VulkanDeviceInfo& device : state.devices) {
        report.devices.push_back({device.facts, device.extensions, device.features});
    }

    const UnsupportedItem unavailable = VulkanUnavailableReason(state);
    report.executedChecks.push_back({"load vulkan-1.dll through volk", loader.loaded,
                                     loader.loaded ? loader.path : loader.error});
    if (loader.loaded) {
        report.executedChecks.push_back({"loader instance version >= 1.2",
                                         loader.instanceVersion >= kVulkan1_2,
                                         VulkanVersionName(loader.instanceVersion)});
    }
    if (loader.loaded && loader.instanceVersion >= kVulkan1_2) {
        report.executedChecks.push_back({"vkCreateInstance (apiVersion 1.2)", loader.instanceCreated,
                                         loader.instanceCreated ? "created" : loader.instanceError});
    }
    if (loader.instanceCreated) {
        report.executedChecks.push_back({"vkEnumeratePhysicalDevices", !state.devices.empty(),
                                         std::to_string(state.devices.size()) + " device(s)"});
    }
    if (!unavailable.item.empty()) {
        report.unsupported.push_back(unavailable);
        report.verdict = "unavailable";
        return report;
    }

    report.supported.push_back("Vulkan loader " + VulkanVersionName(loader.instanceVersion));
    report.supported.push_back("Vulkan 1.2 instance");
    const size_t selected = SelectedVulkanDevice(state.devices);
    const VulkanDeviceInfo& device = state.devices[selected];
    report.adapter = device.name;
    report.driver = device.driver;
    report.facts.emplace_back("selected_device", std::to_string(selected) + " (" + device.name + ")");

    const bool apiOk = device.apiVersion >= kVulkan1_2;
    report.executedChecks.push_back({"device apiVersion >= 1.2", apiOk, VulkanVersionName(device.apiVersion)});
    if (apiOk) {
        report.supported.push_back("device Vulkan " + VulkanVersionName(device.apiVersion));
    } else {
        report.unsupported.push_back({"device Vulkan 1.2", "the device reports Vulkan " +
                                                               VulkanVersionName(device.apiVersion)});
    }
    for (const std::string& name : VulkanRequiredExtensions()) {
        const bool present = device.HasExtension(name);
        report.executedChecks.push_back({"extension " + name, present, present ? "exposed" : "absent"});
        if (present) {
            report.supported.push_back(name);
        } else {
            report.unsupported.push_back({name, "not exposed by the device; the vendored Vulkan "
                                                "device enables it at vkCreateDevice"});
        }
    }
    for (const std::string& name : VulkanRequiredFeatures()) {
        const bool present = device.Feature(name);
        report.executedChecks.push_back({"feature " + name, present, present ? "true" : "false"});
        if (present) {
            report.supported.push_back(name);
        } else {
            report.unsupported.push_back({name, "feature not supported by the device; the vendored "
                                                "Vulkan device enables it at vkCreateDevice"});
        }
    }
    const bool budget = device.HasExtension("VK_EXT_memory_budget");
    report.executedChecks.push_back(
        {"extension VK_EXT_memory_budget (optional)", budget, budget ? "exposed" : "absent"});
    if (budget) {
        report.supported.push_back("VK_EXT_memory_budget");
    } else {
        report.unsupported.push_back({"VK_EXT_memory_budget (optional)",
                                      "not exposed; the VRAM budget falls back to heap sizes "
                                      "(13-engine-integration.md §6)"});
    }

    // The optional extension does not decide availability.
    report.qualified = std::none_of(report.unsupported.begin(), report.unsupported.end(),
                                    [](const UnsupportedItem& item) {
                                        return item.item != "VK_EXT_memory_budget (optional)";
                                    });
    report.verdict = report.qualified ? "available" : "unavailable";
    return report;
}

ProbeReport EvaluateVulkanRayQuery(const VulkanProbeState& state) {
    ProbeReport report;
    report.probe = "vulkan-ray-query";
    report.backend = "vulkan";
    report.completed = true;
    const UnsupportedItem unavailable = VulkanUnavailableReason(state);
    if (!unavailable.item.empty()) {
        report.unsupported.push_back({"Vulkan", "Vulkan unavailable: " + unavailable.item + ": " +
                                                    unavailable.reason});
        report.verdict = "unsupported";
        return report;
    }
    const VulkanDeviceInfo& device = state.devices[SelectedVulkanDevice(state.devices)];
    report.adapter = device.name;
    report.driver = device.driver;
    for (const std::string& name : VulkanRayQueryExtensions()) {
        const bool present = device.HasExtension(name);
        report.executedChecks.push_back({"extension " + name, present, present ? "exposed" : "absent"});
        if (present) {
            report.supported.push_back(name);
        } else {
            report.unsupported.push_back({name, "not exposed by the device"});
        }
    }
    const std::pair<const char*, const char*> owners[] = {
        {"accelerationStructure", "VK_KHR_acceleration_structure"},
        {"rayQuery", "VK_KHR_ray_query"},
    };
    for (const auto& [feature, extension] : owners) {
        const bool present = device.Feature(feature);
        report.executedChecks.push_back(
            {std::string("feature ") + feature, present, present ? "true" : "false"});
        if (present) {
            report.supported.push_back(feature);
        } else if (!device.HasExtension(extension)) {
            report.unsupported.push_back(
                {feature, std::string("cannot be queried: ") + extension + " is not exposed"});
        } else {
            report.unsupported.push_back({feature, "feature not supported by the device"});
        }
    }
    report.qualified = report.unsupported.empty();
    report.verdict = report.qualified ? "supported" : "unsupported";
    return report;
}

// ── WARP ─────────────────────────────────────────────────────────────────────

void ConcludeWarp(ProbeReport& report, const std::vector<WarpCheck>& checks) {
    report.hasHostedLane = true;
    report.hostedLane.clear();
    bool all = !checks.empty();
    for (const WarpCheck& check : checks) {
        switch (check.status) {
            case CheckStatus::Passed:
                report.executedChecks.push_back({check.check, true, check.detail});
                report.hostedLane.push_back(check.check);
                break;
            case CheckStatus::Failed:
                report.executedChecks.push_back({check.check, false, check.detail});
                report.unsupported.push_back({check.check, "failed on WARP: " + check.detail});
                all = false;
                break;
            case CheckStatus::NotRun:
                report.unsupported.push_back({check.check, "not run on WARP: " + check.detail});
                all = false;
                break;
        }
    }
    report.qualified = all;
    report.verdict = all                         ? "qualified"
                     : report.hostedLane.empty() ? "unsupported"
                                                 : "partially qualified";
}

}  // namespace uzp::selftest
