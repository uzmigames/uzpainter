// The Vulkan hardware slice of `selftest` (vulkan_slice.h): qualification and device, compute
// readback of the qualification kernels, and the 16-bit PNG of the Vulkan pattern.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "vulkan_slice.h"

#include "hardware_slice.h"

#include "render/vulkan_backend.h"
#include "render/vulkan_kernels.h"

#include "dx12_device.h"

#include <windows.h>

#include <chrono>
#include <cstdio>
#include <string>

namespace uzp::selftest {

namespace {

constexpr auto kGpuDeadline = std::chrono::seconds(10);
/// An odd width whose rows are not a multiple of the 256-byte pitch for any kernel's texel.
constexpr uint32_t kOddWidth = 1023;
constexpr uint32_t kOddHeight = 3;

/// The LUID of the DX12 slice's adapter in the Vulkan record's spelling; empty without it.
std::string Dx12Luid(const SelftestContext& context) {
    if (!context.device) return {};
    LUID luid{};
    static_cast<uz::DX12Device*>(context.device.get())->GetDevice()->GetAdapterLuid(&luid);
    char buf[24];
    std::snprintf(buf, sizeof(buf), "%08lX%08lX", static_cast<unsigned long>(luid.HighPart),
                  static_cast<unsigned long>(luid.LowPart));
    return buf;
}

std::string Join(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) out += (out.empty() ? "" : "; ") + item;
    return out;
}

}  // namespace

void RegisterVulkanSlice(Selftest& selftest) {
    // name, mandatory, needsGpu, hardwareSlice, dependsOn, run, vulkanHardwareSlice.
    selftest.Add({"vulkan-device", false, true, false, {}, RunVulkanDevice, true});
    selftest.Add({"vulkan-compute-readback", false, true, false, {"vulkan-device"}, RunVulkanComputeReadback, true});
    selftest.Add({"vulkan-png16", false, true, false, {"vulkan-compute-readback"}, RunVulkanPng16, true});
}

void TeardownVulkanSlice(SelftestContext& context) {
    if (!context.vulkanDevice) return;
    const render::VulkanTeardown teardown = context.vulkanDevice->Shutdown(render::Clock::now() + kGpuDeadline);
    if (teardown == render::VulkanTeardown::Abandoned) {
        // Its objects are kept on purpose (the destructor leaks them); the process ends after this.
        std::printf("selftest: the Vulkan device was abandoned at teardown (its work did not complete)\n");
    }
    context.vulkanDevice.reset();
}

// ── vulkan-device ────────────────────────────────────────────────────────────

StageOutcome RunVulkanDevice(SelftestContext& context) {
    const render::VulkanSurvey survey = render::SurveyVulkan();
    const render::VulkanQualification qualification = render::QualifyVulkan(survey, 0);
    Details details = {
        {"loader", survey.instance.loaderLoaded ? "loaded" : survey.instance.loaderError},
        {"loader_instance_version", render::VulkanVersionText(survey.instance.instanceVersion)},
        {"physical_devices", std::to_string(survey.devices.size())},
        {"adapter_index", "0"},
        {"selection", "vendored order (discrete, integrated, virtual, cpu, other), no fallback"},
    };
    const std::vector<size_t> order = render::VulkanVendoredOrder(survey.devices);
    for (size_t i = 0; i < order.size(); ++i) {
        const render::VulkanDeviceRecord& device = survey.devices[order[i]];
        details.emplace_back("candidate." + std::to_string(i), device.name + " (" + device.type + ", Vulkan " +
                                                                   render::VulkanVersionText(device.apiVersion) +
                                                                   ", driver " + device.driverVersionName + ")");
    }
    for (size_t i = 0; i < qualification.checks.size(); ++i) {
        const render::VulkanCheck& check = qualification.checks[i];
        details.emplace_back("check." + std::to_string(i), std::string(check.passed ? "passed" : "FAILED") + ": " +
                                                               check.criterion + ": required " + check.required +
                                                               ", found " + check.found);
    }
    if (qualification.device) {
        const render::VulkanDeviceRecord& device = survey.devices[*qualification.device];
        for (auto& [key, value] : device.Facts()) details.emplace_back("device." + key, value);
        details.emplace_back("queue_family", std::to_string(qualification.queueFamily.value_or(0)));
        const render::VulkanDescriptorModel descriptors = render::DeriveVulkanDescriptorModel(device);
        details.emplace_back("descriptors.per_dispatch",
                             std::to_string(descriptors.sampledImagesPerDispatch) + " sampled images, " +
                                 std::to_string(descriptors.samplersPerDispatch) + " samplers, " +
                                 std::to_string(descriptors.uniformBuffersPerDispatch) + " uniform buffers, " +
                                 std::to_string(descriptors.storageImagesPerDispatch) + " storage images");
        details.emplace_back("descriptors.sets_in_pool", std::to_string(descriptors.setsInPool) +
                                                             " (limited by " + descriptors.setsLimitedBy + ")");
        const render::VulkanVram vram = render::DeriveVulkanVram(device);
        details.emplace_back("vram.source", vram.fromMemoryBudget ? "VK_EXT_memory_budget" : "heap sizes");
        details.emplace_back("vram.budget_bytes", std::to_string(vram.budgetBytes));
        details.emplace_back("vram.usage_bytes", std::to_string(vram.usageBytes));
        details.emplace_back("admission.bytes", std::to_string(render::DeriveVulkanAdmissionBudget(
                                                                    vram, render::AdmissionPolicy{})
                                                                    .bytes));
        const std::string dx12 = Dx12Luid(context);
        details.emplace_back("same_adapter_as_dx12",
                             dx12.empty() ? "unknown (no DX12 device)" : (dx12 == device.luid ? "yes" : "no"));
    }
    details.emplace_back("qualification", qualification.Summary(survey));
    if (!qualification.qualified) {
        return StageOutcome::Fail("refused before any work: " + Join(qualification.Missing()), details);
    }
    render::Result<std::unique_ptr<render::VulkanDevice>> device =
        render::CreateQualifiedVulkanDevice(survey, qualification);
    if (!device) return StageOutcome::Fail(device.error().Describe(), details);
    context.vulkanDevice = std::move(*device);
    return StageOutcome::Pass(std::move(details));
}

// ── vulkan-compute-readback ──────────────────────────────────────────────────

StageOutcome RunVulkanComputeReadback(SelftestContext& context) {
    render::VulkanDevice& device = *context.vulkanDevice;
    const std::filesystem::path dxc = context.exeDir / "dxcompiler.dll";
    Details details = {{"width", std::to_string(kPatternWidth)},
                       {"height", std::to_string(kPatternHeight)},
                       {"odd_width", std::to_string(kOddWidth) + "x" + std::to_string(kOddHeight)},
                       {"deadline_ms", std::to_string(std::chrono::milliseconds(kGpuDeadline).count())}};
    std::vector<std::string> failures;
    for (const render::VulkanQualificationKernel& kernel : render::VulkanQualificationKernels()) {
        const std::string name = kernel.name;
        render::Result<std::vector<uint8_t>> spirv = render::CompileVulkanKernel(kernel, dxc);
        if (!spirv) return StageOutcome::Fail(spirv.error().Describe(), details);
        const render::SpirvFacts facts = render::InspectSpirv(*spirv);
        const bool formatOk = facts.imageFormats.size() == 1 && facts.imageFormats[0] == kernel.spirvImageFormat;
        details.emplace_back(name + ".spirv_bytes", std::to_string(spirv->size()));
        details.emplace_back(name + ".spirv_image_format",
                             facts.imageFormats.empty() ? "none" : std::to_string(facts.imageFormats[0]));
        details.emplace_back(name + ".no_contraction", std::to_string(facts.noContraction));
        if (!formatOk) failures.push_back(name + ": the SPIR-V image does not declare its format");
        if (kernel.ieeeStrict && facts.noContraction == 0) failures.push_back(name + ": not IEEE-strict");
        std::string capabilities;
        for (const uint32_t capability : facts.capabilities) {
            capabilities += (capabilities.empty() ? "" : " ") + std::to_string(capability);
        }
        details.emplace_back(name + ".spirv_capabilities", capabilities);
        if (!facts.UnqualifiedCapabilities().empty()) {
            failures.push_back(name + ": the SPIR-V declares a capability the qualification does not cover");
        }
        if (facts.HasCapability(render::kSpirvCapabilityStorageImageExtendedFormats) != kernel.extendedFormat) {
            failures.push_back(name + ": StorageImageExtendedFormats capability " +
                               (kernel.extendedFormat ? "missing" : "unexpected"));
        }

        render::Result<render::ComputeKernel> compiled = device.CreateComputeKernel(*spirv, name);
        if (!compiled) return StageOutcome::Fail(compiled.error().Describe(), details);
        for (const auto& [width, height] : {std::pair{kPatternWidth, kPatternHeight}, std::pair{kOddWidth, kOddHeight}}) {
            const std::string label = width == kPatternWidth ? name : name + ".odd";
            render::Result<render::KernelReadback> run =
                render::DispatchQualificationKernel(device, kernel, *compiled, width, height, kGpuDeadline);
            if (!run) {
                // The device keeps what the failed work may still use.
                return StageOutcome::Fail(label + ": " + run.error().Describe(), details);
            }
            details.emplace_back(label + ".row_pitch", std::to_string(run->rowPitch));
            details.emplace_back(label + ".mismatches", std::to_string(run->mismatches));
            if (run->mismatches != 0) {
                failures.push_back(label + ": " + std::to_string(run->mismatches) + " texels differ, first " +
                                   run->firstMismatch);
            }
            if (name == "pattern16" && width == kPatternWidth) {
                std::vector<uint16_t> pattern(run->values.begin(), run->values.end());
                details.emplace_back("pattern16.equals_cpu_pattern", pattern == ExpectedPattern() ? "yes" : "no");
                details.emplace_back("pattern16.equals_dx12_readback",
                                     context.readback.empty() ? "not run (no DX12 readback)"
                                                              : (pattern == context.readback ? "yes" : "no"));
                context.vulkanReadback = std::move(pattern);
            }
        }
        device.DestroyComputeKernel(*compiled);
    }
    if (!failures.empty()) return StageOutcome::Fail(Join(failures), details);
    return StageOutcome::Pass(std::move(details));
}

// ── vulkan-png16 ─────────────────────────────────────────────────────────────

StageOutcome RunVulkanPng16(SelftestContext& context) {
    return Png16RoundTrip(context.vulkanReadback, "vulkan-readback",
                          context.options.outDir / "selftest-vulkan-pattern16.png");
}

}  // namespace uzp::selftest
