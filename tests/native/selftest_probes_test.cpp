// Native tests of the `selftest` probe decisions (src/selftest/probe_report.h) on capability
// sources the test fabricates: a DX12 adapter with DXR Tier 1.0 or SM 6.5, a Vulkan loader that
// is absent or too old, a Vulkan device without VK_KHR_ray_query, a WARP run with a failing check.
// Built by `zig build probe-tests` and driven by tests/toolchain/test_probes.py.
//
// Usage: uzp-probe-tests <case>
// Prints the probe report of the case as JSON (the object `selftest` writes into its `probes`
// array) and exits 0; exit code 2 on an unknown case.

#include "selftest/probe_report.h"

#include <cstdio>
#include <functional>
#include <map>
#include <string>

namespace {

using namespace uzp::selftest;

constexpr uint32_t Version(uint32_t major, uint32_t minor, uint32_t patch) {
    return (major << 22) | (minor << 12) | patch;
}

/// A device exposing everything the vendored Vulkan device and the ray-query path need.
VulkanDeviceInfo FullDevice(std::string name, std::string type) {
    VulkanDeviceInfo device;
    device.name = std::move(name);
    device.type = std::move(type);
    device.apiVersion = Version(1, 3, 280);
    device.driver = "Fabricated driver 1.0";
    device.facts = {{"name", device.name}, {"type", device.type}};
    device.extensions = VulkanRequiredExtensions();
    device.extensions.push_back("VK_EXT_memory_budget");
    for (const std::string& name : VulkanRayQueryExtensions()) device.extensions.push_back(name);
    for (const std::string& name : VulkanRequiredFeatures()) device.features.emplace_back(name, true);
    for (const std::string& name : VulkanRayQueryFeatures()) device.features.emplace_back(name, true);
    return device;
}

VulkanProbeState LoadedState(std::vector<VulkanDeviceInfo> devices) {
    VulkanProbeState state;
    state.loader.loaded = true;
    state.loader.path = "C:\\Windows\\System32\\vulkan-1.dll";
    state.loader.instanceVersion = Version(1, 4, 304);
    state.loader.instanceCreated = true;
    state.devices = std::move(devices);
    return state;
}

VulkanProbeState LoaderAbsent() {
    VulkanProbeState state;
    state.loader.error =
        "the Vulkan loader vulkan-1.dll could not be loaded: error 126 (The specified module "
        "could not be found)";
    return state;
}

VulkanProbeState LoaderTooOld() {
    VulkanProbeState state;
    state.loader.loaded = true;
    state.loader.path = "C:\\Windows\\System32\\vulkan-1.dll";
    state.loader.instanceVersion = Version(1, 1, 0);
    return state;
}

VulkanProbeState WithoutRayQuery() {
    VulkanDeviceInfo device = FullDevice("Fabricated GPU", "discrete");
    std::erase(device.extensions, std::string("VK_KHR_ray_query"));
    for (auto& [name, enabled] : device.features) {
        if (name == "rayQuery") enabled = false;
    }
    return LoadedState({device});
}

ProbeReport Warp(std::vector<WarpCheck> checks) {
    ProbeReport report;
    report.probe = "warp";
    report.backend = "dx12-warp";
    report.adapter = "Microsoft Basic Render Driver";
    report.completed = true;
    ConcludeWarp(report, checks);
    return report;
}

const std::map<std::string, std::function<ProbeReport()>>& Cases() {
    static const std::map<std::string, std::function<ProbeReport()>> cases = {
        {"dx12-tier-1-0",
         [] { return EvaluateDx12RayQuery(kDxrTier1_0, kShaderModel6_6, "Fabricated GPU", "1.0"); }},
        {"dx12-sm-6-5",
         [] { return EvaluateDx12RayQuery(kDxrTier1_1, kShaderModel6_5, "Fabricated GPU", "1.0"); }},
        {"dx12-no-dxr",
         [] {
             return EvaluateDx12RayQuery(kDxrTierNotSupported, kShaderModel6_5, "Fabricated GPU",
                                         "1.0");
         }},
        {"dx12-tier-1-1-sm-6-6",
         [] { return EvaluateDx12RayQuery(kDxrTier1_1, kShaderModel6_6, "Fabricated GPU", "1.0"); }},
        {"vulkan-availability-loader-absent", [] { return EvaluateVulkanAvailability(LoaderAbsent()); }},
        {"vulkan-ray-query-loader-absent", [] { return EvaluateVulkanRayQuery(LoaderAbsent()); }},
        {"vulkan-availability-loader-too-old",
         [] { return EvaluateVulkanAvailability(LoaderTooOld()); }},
        {"vulkan-availability-no-ray-query",
         [] { return EvaluateVulkanAvailability(WithoutRayQuery()); }},
        {"vulkan-ray-query-no-ray-query", [] { return EvaluateVulkanRayQuery(WithoutRayQuery()); }},
        {"vulkan-ray-query-full",
         [] { return EvaluateVulkanRayQuery(LoadedState({FullDevice("Fabricated GPU", "discrete")})); }},
        {"vulkan-availability-no-budget",
         [] {
             VulkanDeviceInfo device = FullDevice("Fabricated GPU", "discrete");
             std::erase(device.extensions, std::string("VK_EXT_memory_budget"));
             return EvaluateVulkanAvailability(LoadedState({device}));
         }},
        {"vulkan-availability-selects-discrete",
         [] {
             VulkanDeviceInfo integrated = FullDevice("Fabricated iGPU", "integrated");
             integrated.apiVersion = Version(1, 1, 0);
             return EvaluateVulkanAvailability(
                 LoadedState({integrated, FullDevice("Fabricated dGPU", "discrete")}));
         }},
        {"warp-failing-check",
         [] {
             return Warp({{"dx12-device", CheckStatus::Passed, "Microsoft Basic Render Driver"},
                          {"shader-compile", CheckStatus::Passed, "cs_6_6 DXIL"},
                          {"compute-readback", CheckStatus::Failed, "17 read-back values differ"},
                          {"png16", CheckStatus::NotRun,
                           "needs check compute-readback, which did not pass"}});
         }},
        {"warp-all-pass",
         [] {
             return Warp({{"dx12-device", CheckStatus::Passed, "WARP"},
                          {"shader-compile", CheckStatus::Passed, "cs_6_6 DXIL"},
                          {"compute-readback", CheckStatus::Passed, "0 mismatches"},
                          {"png16", CheckStatus::Passed, "decoded back equal"}});
         }},
        {"warp-no-adapter",
         [] {
             return Warp({{"dx12-device", CheckStatus::Failed, "DXGI enumerates no WARP adapter"},
                          {"shader-compile", CheckStatus::NotRun, "needs check dx12-device"},
                          {"compute-readback", CheckStatus::NotRun, "needs check shader-compile"},
                          {"png16", CheckStatus::NotRun, "needs check compute-readback"}});
         }},
        {"not-completed",
         [] { return NotCompleted("vulkan-ray-query", "vulkan", "exception: fabricated"); }},
    };
    return cases;
}

}  // namespace

int main(int argc, char** argv) {
    const auto& cases = Cases();
    if (argc != 2 || cases.find(argv[1]) == cases.end()) {
        std::fprintf(stderr, "usage: uzp-probe-tests <case>\ncases:\n");
        for (const auto& [name, run] : cases) std::fprintf(stderr, "  %s\n", name.c_str());
        return 2;
    }
    const ProbeReport report = cases.at(argv[1])();
    std::printf("%s\n", report.ToJson().c_str());
    return 0;
}
