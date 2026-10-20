// Native tests of the Vulkan device qualification (phase3.1_vulkan-compute-parity items 2.1, 2.2,
// 2.6, 2.8, 3.1 and 3.4 in part; decision 310): src/render/vulkan_qualification.h,
// vulkan_backend.h and vulkan_kernels.h. Driven by tests/render/test_vulkan_qualification.py.
//
//   vulkan-qualify  no GPU: the criteria on fabricated capability records (each unmet criterion
//                   named, no fallback to another device), the entry-point check, the refusal of
//                   an unqualified device before anything is loaded, the descriptor model, the
//                   VRAM and admission derivation
//   vulkan-device   this machine's survey, qualification and device; the qualification kernels'
//                   SPIR-V and their readback bit for bit at the slice size and at odd widths;
//                   teardown after a completed drain
//   vulkan-faults   a wait past its deadline; a refused command list; a partial submission (host
//                   barrier refused after the command list) that keeps its staging buffer; a
//                   refused fence signal; an injected device loss; a stalled queue abandoned at a
//                   bounded teardown; a new device after the abandoned one
//   vulkan-readback TextureReadback on an engine over the qualified device (items 2.4, 3.1): every
//                   supported format read back bit-identical at odd widths and a lower mip; 64
//                   requests in flight drained in order with no staging allocation left, also by
//                   the destructor; device loss and a stalled queue under pending readbacks
//
// Faults are injected through volk's function table (as tests/native/vendor_modifications_test.cpp
// does), after the device is created and restored right after. Exit code 77 when the machine has
// no Vulkan physical device.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_WIN32_KHR
#include <volk.h>

#include "render/engine_thread.h"
#include "render/texture_readback.h"
#include "render/vulkan_backend.h"
#include "render/vulkan_kernels.h"
#include "render/vulkan_qualification.h"

#include "paths.h"
#include "vulkan_device.h"
#include "vulkan_resources.h"

#define VMA_STATIC_VULKAN_FUNCTIONS 0
#define VMA_DYNAMIC_VULKAN_FUNCTIONS 1
// VMA's header leaves some pointers without a nullability specifier (a warning, an error here).
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wnullability-completeness"
#include <vk_mem_alloc.h>
#pragma clang diagnostic pop

#include <windows.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <future>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using namespace uzp::render;
namespace fs = std::filesystem;
using Ms = std::chrono::milliseconds;

constexpr int kExitSkip = 77;
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

template <class T>
std::string Describe(const Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

bool Contains(const std::string& text, std::string_view part) { return text.find(part) != std::string::npos; }

std::string Joined(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) out += (out.empty() ? "" : " | ") + item;
    return out;
}

// ── Fabricated records ───────────────────────────────────────────────────────

VulkanDeviceRecord GoodRecord(std::string name = "Fabricated dGPU", std::string type = "discrete") {
    VulkanDeviceRecord r;
    r.name = std::move(name);
    r.type = std::move(type);
    r.vendorId = 0x10DE;
    r.apiVersion = VK_API_VERSION_1_3;
    r.driverVersion = (617u << 22) | (14u << 14);
    r.deviceUuid = "00112233445566778899AABBCCDDEEFF";
    r.extensions = VulkanRequiredDeviceExtensions();
    for (const std::string& feature : VulkanRequiredFeatures()) r.features.emplace_back(feature, true);
    for (const VulkanLimitRequirement& limit : VulkanRequiredLimits()) r.limits.emplace_back(limit.limit, limit.minimum);
    r.queueFamilies = {{VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT | VK_QUEUE_TRANSFER_BIT, 16, 64}};
    r.heaps = {{24ull << 30, VK_MEMORY_HEAP_DEVICE_LOCAL_BIT, 0, 0}, {32ull << 30, 0, 0, 0}};
    r.memoryTypes = {{VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0},
                     {VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, 1}};
    for (const VulkanFormatRequirement& format : VulkanRequiredFormats()) {
        r.formats.push_back({format.name, format.vkFormat, format.optimalTilingFeatures, 0, 0});
    }
    r.properties = {{"shaderSignedZeroInfNanPreserveFloat32", "true"}};
    return r;
}

VulkanSurvey GoodSurvey() {
    VulkanSurvey s;
    s.instance.loaderLoaded = true;
    s.instance.instanceVersion = VK_API_VERSION_1_3;
    s.instance.instanceExtensions = VulkanRequiredInstanceExtensions();
    s.instance.instanceCreated = true;
    s.devices = {GoodRecord()};
    return s;
}

void SetFeature(VulkanDeviceRecord& r, std::string_view name, bool value) {
    for (auto& [key, v] : r.features) {
        if (key == name) v = value;
    }
}

void SetLimit(VulkanDeviceRecord& r, std::string_view name, uint64_t value) {
    for (auto& [key, v] : r.limits) {
        if (key == name) v = value;
    }
}

/// Checks that the survey is refused and that the first unmet criterion starts with `criterion`.
void ExpectRefused(const VulkanSurvey& survey, uint32_t adapter, std::string_view criterion, const std::string& name) {
    const VulkanQualification q = QualifyVulkan(survey, adapter);
    const std::vector<std::string> missing = q.Missing();
    Check(!q.qualified && !missing.empty() && missing.front().starts_with(criterion), name, Joined(missing));
}

int RunQualify() {
    {
        const VulkanSurvey s = GoodSurvey();
        const VulkanQualification q = QualifyVulkan(s, 0);
        Check(q.qualified && q.device == 0u && q.queueFamily == 0u && q.Missing().empty(),
              "a device meeting every criterion qualifies on the first graphics queue family", Joined(q.Missing()));
        Check(q.Summary(s) == "qualified: device 0 'Fabricated dGPU'", "the summary names the device", q.Summary(s));
    }
    {
        VulkanSurvey s;
        s.instance.loaderError = "the Vulkan loader vulkan-1.dll could not be loaded";
        const VulkanQualification q = QualifyVulkan(s, 0);
        Check(!q.qualified && !q.device && q.checks.size() == 1 &&
                  q.Missing().front().starts_with("Vulkan loader (vulkan-1.dll): required loaded"),
              "no loader: refused, no device judged", Joined(q.Missing()));
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.instance.instanceVersion = VK_API_VERSION_1_1;
        ExpectRefused(s, 0, "loader instance version: required >= 1.2.0, found 1.1.0",
                      "a Vulkan 1.1 loader is refused before any device is judged");
        Check(!QualifyVulkan(s, 0).device, "a refused instance judges no device");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.instance.instanceExtensions = {"VK_KHR_surface"};
        ExpectRefused(s, 0, "instance extension VK_KHR_win32_surface", "a missing instance extension is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].apiVersion = VK_API_VERSION_1_1;
        ExpectRefused(s, 0, "device API version: required >= 1.2.0, found 1.1.0", "a Vulkan 1.1 device is refused");
    }
    {
        VulkanSurvey s = GoodSurvey();
        SetFeature(s.devices[0], "timelineSemaphore", false);
        ExpectRefused(s, 0, "feature timelineSemaphore: required true, found false",
                      "a missing required feature bit is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        SetFeature(s.devices[0], "shaderStorageImageExtendedFormats", false);
        ExpectRefused(s, 0, "feature shaderStorageImageExtendedFormats",
                      "shaderStorageImageExtendedFormats (the R16f storage image) is required");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].features.erase(s.devices[0].features.begin());
        ExpectRefused(s, 0, "feature timelineSemaphore: required true, found not queried",
                      "an unqueried feature is not taken as present");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].extensions.pop_back();
        ExpectRefused(s, 0, "device extension VK_KHR_timeline_semaphore", "a missing device extension is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].type = "cpu";
        ExpectRefused(s, 0, "device type: required discrete or integrated GPU, found cpu",
                      "a CPU device is refused as a hardware device");
    }
    {
        VulkanSurvey s = GoodSurvey();
        SetLimit(s.devices[0], "maxPerStageDescriptorUpdateAfterBindStorageImages", 8);
        ExpectRefused(s, 0, "limit maxPerStageDescriptorUpdateAfterBindStorageImages",
                      "an update-after-bind limit below the vendored layout is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        SetLimit(s.devices[0], "maxUpdateAfterBindDescriptorsInAllPools", 1000);
        ExpectRefused(s, 0, "limit maxUpdateAfterBindDescriptorsInAllPools",
                      "a pool smaller than the vendored descriptor pool is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].formats[0].optimalTilingFeatures = VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;
        ExpectRefused(s, 0, "format R16_SFLOAT", "a format without storage-image support is named");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].queueFamilies = {{VK_QUEUE_GRAPHICS_BIT, 1, 0}, {VK_QUEUE_COMPUTE_BIT, 1, 0}};
        ExpectRefused(s, 0, "queue family: required the first graphics family also has compute",
                      "a graphics family without compute is refused (no other family is picked)");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].properties = {{"shaderSignedZeroInfNanPreserveFloat32", "false"}};
        ExpectRefused(s, 0, "float controls shaderSignedZeroInfNanPreserveFloat32",
                      "a device without signed-zero/Inf/NaN preservation is refused for IEEE-strict kernels");
    }
    {
        VulkanSurvey s = GoodSurvey();
        s.devices[0].memoryTypes = {{VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0}};
        ExpectRefused(s, 0, "memory type HOST_VISIBLE", "a device without host-visible memory is refused");
    }
    ExpectRefused(GoodSurvey(), 1, "physical device at adapter index 1", "an adapter index past the devices is refused");
    {
        // Enumeration order: integrated first; the vendored order puts the discrete device first.
        VulkanSurvey s = GoodSurvey();
        s.devices = {GoodRecord("Fabricated iGPU", "integrated"), GoodRecord("Fabricated dGPU", "discrete")};
        const std::vector<size_t> order = VulkanVendoredOrder(s.devices);
        Check(order == std::vector<size_t>{1, 0}, "the vendored order puts discrete before integrated");
        const VulkanQualification q = QualifyVulkan(s, 0);
        Check(q.qualified && q.device == 1u, "adapter index 0 judges the discrete device");
        SetFeature(s.devices[1], "synchronization2", false);
        const VulkanQualification refused = QualifyVulkan(s, 0);
        Check(!refused.qualified && refused.device == 1u,
              "an unqualified discrete device is refused, not replaced by the qualified integrated one",
              Joined(refused.Missing()));
    }

    // Entry points: feature bits do not prove an entry point resolves.
    {
        const auto all = [](std::string_view) { return true; };
        Check(MissingVulkanEntryPoints(all).empty(), "every entry point resolving: none missing");
        const auto noKhrBarrier = [](std::string_view name) { return name != "vkCmdPipelineBarrier2KHR"; };
        Check(MissingVulkanEntryPoints(noKhrBarrier) == std::vector<std::string>{"vkCmdPipelineBarrier2KHR"},
              "a missing entry point is named");
        const std::vector<std::string>& required = VulkanRequiredEntryPoints();
        bool noCore13 = true;
        for (const std::string& name : required) {
            noCore13 = noCore13 && name != "vkCmdPipelineBarrier2" && name != "vkCmdBeginRendering" &&
                       name != "vkCmdEndRendering";
        }
        Check(noCore13, "the backend names the KHR entry points, not the core 1.3 ones");
    }

    // The deterministic unavailable-device fixture: an unqualified record is refused before
    // anything is created or loaded.
    {
        VulkanSurvey s = GoodSurvey();
        SetFeature(s.devices[0], "timelineSemaphore", false);
        const VulkanQualification q = QualifyVulkan(s, 0);
        Result<std::unique_ptr<VulkanDevice>> device = CreateQualifiedVulkanDevice(s, q);
        Check(!device && device.error().code == ErrorCode::GpuBackendUnavailable &&
                  device.error().backend == Backend::Vulkan &&
                  device.error().reason.starts_with("refused before any work: not qualified: device 0 "
                                                    "'Fabricated dGPU': feature timelineSemaphore"),
              "an unqualified device is refused before any work, naming the criterion", Describe(device));
        Check(GetModuleHandleW(L"vulkan-1.dll") == nullptr, "the refusal loaded no Vulkan loader");
    }

    // Descriptors in Vulkan terms.
    {
        VulkanDeviceRecord r = GoodRecord();
        const VulkanDescriptorModel model = DeriveVulkanDescriptorModel(r);
        Check(model.sampledImagesPerDispatch == 16 && model.samplersPerDispatch == 16 &&
                  model.uniformBuffersPerDispatch == 16 && model.storageImagesPerDispatch == 16,
              "one dispatch binds 16 of each descriptor type");
        Check(model.setsInPool == 128 && model.setsLimitedBy == "sampler",
              "the vendored pool holds 128 set snapshots at once, bounded by its 2048 samplers",
              std::to_string(model.setsInPool) + " by " + model.setsLimitedBy);
        SetLimit(r, "maxDescriptorSetUpdateAfterBindStorageImages", 8);
        Check(DeriveVulkanDescriptorModel(r).storageImagesPerDispatch == 8,
              "a lower device limit bounds the bindings of one dispatch");
    }
    // VRAM and admission.
    {
        VulkanDeviceRecord r = GoodRecord();
        VulkanVram vram = DeriveVulkanVram(r);
        Check(!vram.fromMemoryBudget && vram.budgetBytes == (24ull << 30) && vram.usageBytes == 0,
              "without VK_EXT_memory_budget the budget is the device-local heap size, usage unknown");
        r.memoryBudget = true;
        r.heaps[0].budgetBytes = 20ull << 30;
        r.heaps[0].usageBytes = 2ull << 30;
        vram = DeriveVulkanVram(r);
        Check(vram.fromMemoryBudget && vram.budgetBytes == (20ull << 30) && vram.usageBytes == (2ull << 30),
              "with VK_EXT_memory_budget the device-local heaps' budget and usage");
        const AdmissionBudget admission = DeriveVulkanAdmissionBudget(vram, AdmissionPolicy{});
        const uint64_t usable = (18ull << 30) - (512ull << 20);
        Check(admission.bytes == usable / 2 && admission.maxTilesByDescriptors == std::numeric_limits<uint64_t>::max(),
              "admission = (budget - usage - reserve) x 50 %, no descriptor bound on live tiles",
              std::to_string(admission.bytes));
    }
    // The capability report the engine thread's startup query returns on Vulkan.
    {
        VulkanDeviceRecord r = GoodRecord();
        r.memoryBudget = true;
        r.heaps[0].budgetBytes = 20ull << 30;
        r.heaps[0].usageBytes = 2ull << 30;
        r.formats.push_back({"R32G32B32_SFLOAT", VK_FORMAT_R32G32B32_SFLOAT, 0, 0, 0});
        const CapabilityReport report = VulkanCapabilityReport(r, AdmissionPolicy{});
        const AdmissionBudget expected = DeriveVulkanAdmissionBudget(DeriveVulkanVram(r), AdmissionPolicy{});
        Check(report.backend == Backend::Vulkan && report.adapter == "Fabricated dGPU" &&
                  report.admission.bytes == expected.bytes &&
                  report.admission.maxTilesByDescriptors == expected.maxTilesByDescriptors &&
                  report.vram.budgetBytes == (20ull << 30) && report.vram.usageBytes == (2ull << 30) &&
                  report.vram.dedicatedVideoMemoryBytes == (24ull << 30) &&
                  report.vram.sharedSystemMemoryBytes == (32ull << 30),
              "the Vulkan capability report carries the record's identity, VRAM and admission budget",
              report.ToJson());
        const FormatCapability* tile = report.Find(uz::RHIFormat::RGBA32Float);
        const FormatCapability* rgb = report.Find(uz::RHIFormat::RGB32Float);
        Check(tile != nullptr && tile->texture2D && tile->shaderResource && tile->unorderedAccess &&
                  tile->unorderedAccessLoad && rgb != nullptr && !rgb->texture2D && rgb->Usages().empty(),
              "the report's format usages come from the optimal-tiling features (none for RGB32F without any)",
              report.ToJson());
        Check(report.descriptors.shaderResources == 48 && report.descriptors.samplers == 16,
              "the report's descriptors are what one dispatch binds");
    }
    // Report forms.
    {
        const VulkanDeviceRecord r = GoodRecord();
        bool feature = false;
        bool limit = false;
        for (const auto& [key, value] : r.Facts()) {
            feature = feature || (key == "feature.timelineSemaphore" && value == "true");
            limit = limit || (key == "limit.maxPushConstantsSize" && value == "128");
        }
        Check(feature && limit, "the record's facts list its features and limits by name");
        Check(VulkanDriverVersionName(0x10DE, r.driverVersion) == "617.14.0.0", "NVIDIA driver versions decode");
        Check(VkResultText(VK_ERROR_DEVICE_LOST) == "VK_ERROR_DEVICE_LOST (-4)", "VkResult names");
    }
    return Finish();
}

// ── Hardware ─────────────────────────────────────────────────────────────────

fs::path DxcPath() { return fs::path(uz::GetExeDir()) / "dxcompiler.dll"; }

/// A new qualified device at adapter index 0, or the error.
Result<std::unique_ptr<VulkanDevice>> NewDevice(const VulkanDeviceOptions& options = {}) {
    const VulkanSurvey survey = SurveyVulkan();
    const VulkanQualification q = QualifyVulkan(survey, 0);
    return CreateQualifiedVulkanDevice(survey, q, options);
}

bool NoVulkanDevice() {
    const VulkanSurvey survey = SurveyVulkan();
    if (survey.devices.empty()) {
        Info("no Vulkan physical device: " + survey.instance.loaderError + survey.instance.instanceError);
        return true;
    }
    return false;
}

const VulkanQualificationKernel& Kernel(std::string_view name) {
    for (const VulkanQualificationKernel& kernel : VulkanQualificationKernels()) {
        if (kernel.name == name) return kernel;
    }
    return VulkanQualificationKernels().front();
}

int RunDevice() {
    const VulkanSurvey survey = SurveyVulkan();
    if (survey.devices.empty()) {
        Info("no Vulkan physical device: " + survey.instance.loaderError + survey.instance.instanceError);
        return kExitSkip;
    }
    for (const VulkanDeviceRecord& record : survey.devices) {
        Info("device " + std::to_string(record.enumerationIndex) + ": " + record.name + " (" + record.type +
             "), Vulkan " + VulkanVersionText(record.apiVersion) + ", driver " + record.driverVersionName + " " +
             record.driverName + " " + record.driverInfo);
    }
    const VulkanQualification q = QualifyVulkan(survey, 0);
    Check(q.qualified, "this machine's device at adapter index 0 qualifies", q.Summary(survey));
    if (!q.qualified) return Finish();
    const VulkanDeviceRecord& record = survey.devices[*q.device];
    Check(!record.deviceUuid.empty() && !record.driverName.empty() && record.Limit("maxPushConstantsSize") &&
              record.Feature("timelineSemaphore") == true,
          "the record holds the UUID, the driver, the limits and the features");

    Result<std::unique_ptr<VulkanDevice>> created = CreateQualifiedVulkanDevice(survey, q);
    Check(created.has_value(), "the qualified device is created on the judged device and queue family",
          Describe(created));
    if (!created) return Finish();
    VulkanDevice& device = **created;
    Check(device.GetBackend() == Backend::Vulkan && device.NativeKernelTarget() == KernelTarget::Spirv &&
              device.AdapterName() == record.name && !device.CheckRemoved(),
          "the device reports Vulkan, SPIR-V and its adapter");

    struct Size {
        uint32_t width, height;
    };
    const Size sizes[] = {{100, 64}, {1, 1}, {3, 5}, {1023, 3}, {4097, 2}};
    for (const VulkanQualificationKernel& kernel : VulkanQualificationKernels()) {
        const std::string name = kernel.name;
        Result<std::vector<uint8_t>> spirv = CompileVulkanKernel(kernel, DxcPath());
        Check(spirv.has_value(), name + ": compiles to SPIR-V", Describe(spirv));
        if (!spirv) continue;
        const SpirvFacts facts = InspectSpirv(*spirv);
        Check(facts.imageFormats == std::vector<uint32_t>{kernel.spirvImageFormat},
              name + ": the SPIR-V storage image declares its format");
        Check(!facts.HasCapability(kSpirvCapabilityStorageImageReadWithoutFormat) &&
                  !facts.HasCapability(kSpirvCapabilityStorageImageWriteWithoutFormat),
              name + ": the SPIR-V needs no ...WithoutFormat capability");
        Check(facts.UnqualifiedCapabilities().empty(),
              name + ": every SPIR-V capability is one the qualification covers");
        Check(facts.HasCapability(kSpirvCapabilitySignedZeroInfNanPreserve) == kernel.ieeeStrict,
              name + ": SignedZeroInfNanPreserve is declared exactly for the IEEE-strict kernel");
        Check(facts.HasCapability(kSpirvCapabilityStorageImageExtendedFormats) == kernel.extendedFormat,
              name + ": StorageImageExtendedFormats is declared exactly when the format needs it");
        if (kernel.ieeeStrict) Check(facts.noContraction > 0, name + ": the SPIR-V arithmetic is NoContraction");
        Result<ComputeKernel> compiled = device.CreateComputeKernel(*spirv, name);
        Check(compiled.has_value(), name + ": compute pipeline created", Describe(compiled));
        if (!compiled) continue;
        bool exact = true;
        bool pitches = true;
        for (const Size& size : sizes) {
            Result<KernelReadback> run = DispatchQualificationKernel(device, kernel, *compiled, size.width,
                                                                    size.height, Ms(10000));
            const std::string what = name + " " + std::to_string(size.width) + "x" + std::to_string(size.height);
            if (!run) {
                exact = false;
                Check(false, what + ": dispatched and read back", run.error().Describe());
                continue;
            }
            pitches = pitches && run->rowPitch == ReadbackRowPitch(uint64_t{size.width} * kernel.bytesPerTexel,
                                                                    kernel.bytesPerTexel);
            if (run->mismatches != 0) {
                exact = false;
                Check(false, what + ": bit-exact", std::to_string(run->mismatches) + " differ, first " +
                                                       run->firstMismatch);
            }
        }
        Check(exact, name + ": every read-back texel equals the CPU reference bit for bit, odd widths included");
        Check(pitches, name + ": rows are read at the texel-aware pitch");
        device.DestroyComputeKernel(*compiled);
    }
    const auto start = std::chrono::steady_clock::now();
    const VulkanTeardown teardown = device.Shutdown(Clock::now() + Ms(10000));
    Check(teardown == VulkanTeardown::Destroyed, "after its work completed the device is destroyed",
          std::string(VulkanTeardownName(teardown)));
    Info("teardown took " +
         std::to_string(std::chrono::duration_cast<Ms>(std::chrono::steady_clock::now() - start).count()) + " ms");
    Check(device.CheckRemoved().has_value() && !device.CreateTexture({}).has_value(),
          "a destroyed device creates nothing");
    return Finish();
}

// ── Faults ───────────────────────────────────────────────────────────────────

PFN_vkQueueSubmit g_realSubmit = nullptr;
int g_submitCall = 0;
int g_refusedCall = 0;

/// Refuses the `g_refusedCall`-th `vkQueueSubmit` since the injection and passes the others on.
/// A submission is three calls: the command list, the host barrier, the fence signal.
VKAPI_ATTR VkResult VKAPI_CALL CountingSubmit(VkQueue queue, uint32_t count, const VkSubmitInfo* submits, VkFence fence) {
    if (++g_submitCall == g_refusedCall) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
    return g_realSubmit(queue, count, submits, fence);
}

VKAPI_ATTR VkResult VKAPI_CALL LostWaitSemaphores(VkDevice, const VkSemaphoreWaitInfo*, uint64_t) {
    return VK_ERROR_DEVICE_LOST;
}

struct Injected {
    explicit Injected(int refused) {
        g_realSubmit = vkQueueSubmit;
        g_submitCall = 0;
        g_refusedCall = refused;
        vkQueueSubmit = &CountingSubmit;
    }
    ~Injected() { vkQueueSubmit = g_realSubmit; }
};

/// The objects of one hash32 dispatch the test keeps its own handles to.
struct Dispatch {
    uz::RHITextureHandle texture;
    uz::RHIBufferHandle buffer;
    Result<uint64_t> fence;
};

Dispatch Submit(VulkanDevice& device, const ComputeKernel& kernel) {
    uz::RHITextureDesc textureDesc;
    textureDesc.width = 64;
    textureDesc.height = 64;
    textureDesc.format = uz::RHIFormat::R32Uint;
    textureDesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = 256 * 64;
    bufferDesc.usage = uz::RHIBufferUsage::CopyDst;
    bufferDesc.memory = uz::RHIMemoryType::Readback;
    Dispatch d{*device.CreateTexture(textureDesc), *device.CreateBuffer(bufferDesc), {}};
    const uint32_t uav = device.Rhi().GetTextureUAVIndex(d.texture);
    const uint32_t constants[2] = {64, 64};
    d.fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toUav{d.texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::Common,
                                       uz::RHIResourceState::UnorderedAccess};
        cmd.ResourceBarrier(&toUav, 1);
        cmd.SetPipeline(kernel.pipeline);
        cmd.SetRootConstants(kRootConstantsParam, constants, 2);
        cmd.SetDescriptorTable(kUavTableParam, uav);
        cmd.Dispatch(8, 8, 1);
        const uz::RHIBarrierDesc toCopy{d.texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::UnorderedAccess,
                                        uz::RHIResourceState::CopySrc};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyTextureToBuffer(d.texture, 0, d.buffer, 0, 256);
    });
    return d;
}

bool BufferAlive(VulkanDevice& device, uz::RHIBufferHandle buffer) {
    auto& native = static_cast<uz::VulkanDevice&>(device.Rhi());
    const uz::VulkanBuffer* entry = native.GetBufferPool().Get(buffer.index, buffer.generation);
    return entry && entry->buffer != VK_NULL_HANDLE;
}

int64_t ElapsedMs(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration_cast<Ms>(std::chrono::steady_clock::now() - start).count();
}

int RunFaults() {
    if (NoVulkanDevice()) return kExitSkip;
    Result<std::vector<uint8_t>> spirv = CompileVulkanKernel(Kernel("hash32"), DxcPath());
    Check(spirv.has_value(), "hash32 compiles to SPIR-V", Describe(spirv));
    if (!spirv) return Finish();
    const auto kernelOn = [&](VulkanDevice& device) { return *device.CreateComputeKernel(*spirv, "hash32"); };

    // A wait past its deadline: `timeout` at the deadline, and the device stays usable.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        Check(device.has_value(), "timeout: device", Describe(device));
        if (!device) return Finish();
        IQueue& queue = (*device)->Queue();
        const auto start = std::chrono::steady_clock::now();
        const WaitResult wait = queue.Wait(queue.LastSubmitted() + 1, Clock::now() + Ms(500));
        const int64_t elapsed = ElapsedMs(start);
        Info("never-signalled wait: " + std::string(WaitStatusName(wait.status)) + " after " + std::to_string(elapsed) + " ms");
        Check(wait.status == WaitStatus::Timeout, "a wait for a value never submitted returns timeout");
        Check(elapsed >= 500 && elapsed < 900, "the timeout returns at the 500 ms deadline, not later",
              std::to_string(elapsed) + " ms");
        Check((*device)->WaitFailure(wait).code == ErrorCode::Timeout, "the failure is reported as timeout");
        const ComputeKernel kernel = kernelOn(**device);
        Result<KernelReadback> run = DispatchQualificationKernel(**device, Kernel("hash32"), kernel, 64, 64, Ms(10000));
        Check(run && run->mismatches == 0, "after a timeout the device still runs a kernel exactly", Describe(run));
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Destroyed,
              "timeout: the device is destroyed after its work completed");
    }

    // A refused command list: an error at once, nothing reached the GPU, the queue goes on.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        const uint64_t before = (*device)->Queue().LastSubmitted();
        const auto start = std::chrono::steady_clock::now();
        Dispatch d{};
        {
            Injected inject(1);
            d = Submit(**device, kernel);
        }
        Check(!d.fence && d.fence.error().code == ErrorCode::RequestFailed &&
                  Contains(d.fence.error().reason, "refused the command list"),
              "a refused command list fails Submit with request_failed", Describe(d.fence));
        Check(ElapsedMs(start) < 1000 && (*device)->Queue().LastSubmitted() == before,
              "the refusal is immediate and consumes no fence value");
        Check(!(*device)->CheckRemoved(), "a refused command list leaves the device usable");
        Result<KernelReadback> run = DispatchQualificationKernel(**device, Kernel("hash32"), kernel, 64, 64, Ms(10000));
        Check(run && run->mismatches == 0, "the next submission runs exactly", Describe(run));
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Destroyed,
              "refused command list: the device is destroyed after its work completed");
    }

    // A partial submission: the command list was accepted, the host barrier refused, the fence
    // signal accepted. The work may still run, so nothing it names is freed.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        Dispatch d{};
        {
            Injected inject(2);
            d = Submit(**device, kernel);
        }
        Check(g_submitCall == 3, "the command list, the barrier and the fence signal were each submitted",
              std::to_string(g_submitCall) + " calls");
        Check(!d.fence && Contains(d.fence.error().reason, "after the command list was submitted"),
              "the refused barrier fails Submit, stating the command list was submitted", Describe(d.fence));
        // As texture_readback.cpp does after a failed Submit.
        (*device)->DestroyBuffer(d.buffer);
        (*device)->DestroyTexture(d.texture);
        Check(BufferAlive(**device, d.buffer), "the staging buffer is not destroyed while its copy may be in flight");
        Check((*device)->CheckRemoved().has_value(), "the device reports itself failed");
        Check(!(*device)->Queue().Submit([](uz::IRHICommandList&) {}).has_value(),
              "a failed device accepts no further submission");
        const auto start = std::chrono::steady_clock::now();
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Abandoned && ElapsedMs(start) < 1000,
              "the failed device is abandoned at once, never waited on");
    }

    // A refused fence signal: the value can never be reached, so its wait fails at once.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        Dispatch d{};
        {
            Injected inject(3);
            d = Submit(**device, kernel);
        }
        Check(!d.fence && Contains(d.fence.error().reason, "refused the fence signal"),
              "a refused fence signal fails Submit", Describe(d.fence));
        IQueue& queue = (*device)->Queue();
        const auto start = std::chrono::steady_clock::now();
        const WaitResult wait = queue.Wait(queue.LastSubmitted(), Clock::now() + Ms(5000));
        Check(wait.status == WaitStatus::DeviceLost && wait.backendReason == VK_ERROR_OUT_OF_DEVICE_MEMORY &&
                  ElapsedMs(start) < 1000,
              "the wait on the refused value fails at once with its VkResult, not by a timeout");
        Check((*device)->WaitFailure(wait).code == ErrorCode::RequestFailed,
              "the failure is request_failed, not device_removed");
        (*device)->DestroyBuffer(d.buffer);
        Check(BufferAlive(**device, d.buffer), "the refused signal's buffer is kept");
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Abandoned,
              "the device with a refused signal is abandoned");
    }

    // Device loss injected into the timeline wait.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        const PFN_vkWaitSemaphores real = vkWaitSemaphores;
        vkWaitSemaphores = &LostWaitSemaphores;
        Result<KernelReadback> run = DispatchQualificationKernel(**device, Kernel("hash32"), kernel, 64, 64, Ms(5000));
        vkWaitSemaphores = real;
        Check(!run && run.error().Describe() == "device_removed {backend: vulkan, reason: VK_ERROR_DEVICE_LOST (-4)}",
              "VK_ERROR_DEVICE_LOST is reported as device_removed {backend: vulkan, reason}", Describe(run));
        const std::optional<Error> removed = (*device)->CheckRemoved();
        Check(removed && removed->code == ErrorCode::DeviceRemoved, "the device stays removed");
        Result<uint64_t> next = (*device)->Queue().Submit([](uz::IRHICommandList&) {});
        Check(!next && next.error().code == ErrorCode::DeviceRemoved, "a lost device accepts no submission",
              Describe(next));
        const auto start = std::chrono::steady_clock::now();
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Abandoned && ElapsedMs(start) < 1000,
              "the lost device is abandoned at once");
    }

    // A stalled queue: the wait times out at its deadline and teardown abandons the device within
    // its own deadline, without vkDeviceWaitIdle.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        Result<std::function<void()>> release = (*device)->InjectQueueStall();
        Check(release.has_value(), "the stall is armed", Describe(release));
        if (!release) return Finish();
        Dispatch d = Submit(**device, kernel);
        Check(d.fence.has_value(), "the stalled submission is accepted", Describe(d.fence));
        auto start = std::chrono::steady_clock::now();
        const WaitResult wait = (*device)->Queue().Wait(d.fence.value_or(1), Clock::now() + Ms(500));
        int64_t elapsed = ElapsedMs(start);
        Check(wait.status == WaitStatus::Timeout && elapsed >= 500 && elapsed < 900,
              "the stalled wait returns timeout at its 500 ms deadline", std::to_string(elapsed) + " ms");
        start = std::chrono::steady_clock::now();
        const VulkanTeardown teardown = (*device)->Shutdown(Clock::now() + Ms(500));
        elapsed = ElapsedMs(start);
        Info("stalled teardown: " + std::string(VulkanTeardownName(teardown)) + " after " + std::to_string(elapsed) + " ms");
        Check(teardown == VulkanTeardown::Abandoned && elapsed >= 500 && elapsed < 900,
              "teardown of the stalled device ends at its 500 ms deadline, abandoned", std::to_string(elapsed) + " ms");
        (*device)->DestroyBuffer(d.buffer);
        Check(BufferAlive(**device, d.buffer), "the abandoned device's staging buffer is not freed");
        // The GPU may now finish the abandoned work; its objects stay allocated.
        (*release)();
    }

    // Recovery: a new device after the abandoned ones runs the kernels exactly.
    {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        Check(device.has_value(), "a new device is created after abandoned ones", Describe(device));
        if (!device) return Finish();
        const ComputeKernel kernel = kernelOn(**device);
        Result<KernelReadback> run = DispatchQualificationKernel(**device, Kernel("hash32"), kernel, 1023, 3, Ms(10000));
        Check(run && run->mismatches == 0, "the new device runs the kernel bit for bit", Describe(run));
        Check((*device)->Shutdown(Clock::now() + Ms(10000)) == VulkanTeardown::Destroyed,
              "the new device is destroyed after its work completed");
    }
    return Finish();
}

// ── Readback (items 2.4, 3.1) ────────────────────────────────────────────────

/// An engine on the qualified Vulkan device of adapter index 0, through the native-test seam
/// (`EngineOptions::createDevice`, decision 313; product paths still refuse Vulkan).
EngineOptions VulkanEngineOptions(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    options.device.backend = Backend::Vulkan;
    options.createDevice = []() -> Result<std::unique_ptr<IDevice>> {
        Result<std::unique_ptr<VulkanDevice>> device = NewDevice();
        if (!device) return Unexpected(device.error());
        return std::unique_ptr<IDevice>(std::move(*device));
    };
    return options;
}

template <class T>
Result<T> Get(std::future<Result<T>>& future) {
    return future.get();
}

/// Live VMA allocations of the device (textures and buffers).
uint64_t LiveAllocations(IDevice& device) {
    VmaTotalStatistics stats{};
    vmaCalculateStatistics(static_cast<uz::VulkanDevice&>(device.Rhi()).GetAllocator(), &stats);
    return stats.total.statistics.allocationCount;
}

/// Deterministic bytes (xorshift64*), as `render_core_test.cpp`'s readback cases use.
std::vector<std::byte> PatternBytes(size_t count, uint64_t seed) {
    std::vector<std::byte> bytes(count);
    uint64_t state = seed * 0x9E3779B97F4A7C15ull + 1;
    for (std::byte& b : bytes) {
        state ^= state >> 12;
        state ^= state << 25;
        state ^= state >> 27;
        b = static_cast<std::byte>((state * 0x2545F4914F6CDD1Dull) >> 56);
    }
    return bytes;
}

std::string Compare(const Result<ReadbackImage>& image, const std::vector<std::byte>& expected, uint32_t width,
                    uint32_t height) {
    if (!image) return image.error().Describe();
    if (image->width != width || image->height != height) {
        return "size " + std::to_string(image->width) + "x" + std::to_string(image->height);
    }
    if (image->texels.size() != expected.size()) {
        return std::to_string(image->texels.size()) + " bytes, expected " + std::to_string(expected.size());
    }
    const size_t row = image->RowBytes();
    for (size_t i = 0; i < expected.size(); ++i) {
        if (image->texels[i] != expected[i]) {
            return "first difference in row " + std::to_string(i / row) + " at byte " + std::to_string(i % row);
        }
    }
    return {};
}

/// A texture filled with pattern bytes through a tightly packed upload (`bufferRowLength` = the
/// width, independent of `TextureReadback`'s pitch); destroyed by its owner.
struct Filled {
    uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    TexelLayout layout;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<std::byte> texels;
};

Result<Filled> MakeFilled(EngineContext& context, uz::RHIFormat format, uint32_t width, uint32_t height,
                          uint64_t seed, uint16_t mips = 1, uint32_t mip = 0) {
    IDevice& device = context.Device();
    Filled filled;
    filled.layout = ReadbackLayout(format).value_or(TexelLayout{});
    filled.width = std::max(1u, width >> mip);
    filled.height = std::max(1u, height >> mip);
    const size_t rowBytes = size_t{filled.width} * filled.layout.BytesPerTexel();
    filled.texels = PatternBytes(rowBytes * filled.height, seed);
    uz::RHITextureDesc desc;
    desc.width = width;
    desc.height = height;
    desc.mipLevels = mips;
    desc.format = format;
    desc.usage = uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::CopySrc | uz::RHITextureUsage::CopyDst;
    desc.debugName = "vulkan_readback_test";
    Result<uz::RHITextureHandle> texture = device.CreateTexture(desc);
    if (!texture) return Unexpected(texture.error());
    filled.texture = *texture;
    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = filled.texels.size();
    bufferDesc.usage = uz::RHIBufferUsage::CopySrc;
    bufferDesc.memory = uz::RHIMemoryType::Upload;
    bufferDesc.debugName = "vulkan_readback_test_upload";
    Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(bufferDesc);
    if (!buffer) {
        device.DestroyTexture(filled.texture);
        return Unexpected(buffer.error());
    }
    auto* mapped = static_cast<std::byte*>(device.Rhi().MapBuffer(*buffer));
    if (mapped) {
        std::memcpy(mapped, filled.texels.data(), filled.texels.size());
        device.Rhi().UnmapBuffer(*buffer);
    }
    const uz::RHIBufferHandle source = *buffer;
    Result<void> done = mapped ? context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toCopy{filled.texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::Common,
                                        uz::RHIResourceState::CopyDst};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyBufferToTexture(source, 0, static_cast<uint32_t>(rowBytes), filled.texture, mip, 0);
        const uz::RHIBarrierDesc back{filled.texture, uz::RHIBufferHandle::Invalid(), uz::RHIResourceState::CopyDst,
                                      uz::RHIResourceState::Common};
        cmd.ResourceBarrier(&back, 1);
    })
                               : Result<void>(Fail(ErrorCode::RequestFailed, Backend::Vulkan, "upload buffer not mapped"));
    device.DestroyBuffer(source);
    if (!done) {
        device.DestroyTexture(filled.texture);
        return Unexpected(done.error());
    }
    return filled;
}

/// The formats `TextureReadback` reads (`ReadbackLayout`), as in `render_core_test.cpp`.
constexpr uz::RHIFormat kReadableFormats[] = {
    uz::RHIFormat::R8Unorm,     uz::RHIFormat::RG8Unorm,    uz::RHIFormat::RGBA8Unorm,
    uz::RHIFormat::RGBA8Srgb,   uz::RHIFormat::BGRA8Unorm,  uz::RHIFormat::BGRA8Srgb,
    uz::RHIFormat::R16Unorm,    uz::RHIFormat::RG16Unorm,   uz::RHIFormat::RGBA16Unorm,
    uz::RHIFormat::R16Float,    uz::RHIFormat::RG16Float,   uz::RHIFormat::RGBA16Float,
    uz::RHIFormat::R32Float,    uz::RHIFormat::RG32Float,   uz::RHIFormat::RGB32Float,
    uz::RHIFormat::RGBA32Float, uz::RHIFormat::R32Uint,     uz::RHIFormat::RG32Uint,
    uz::RHIFormat::RGBA32Uint,
};

std::string Name(uz::RHIFormat format) { return std::string(FormatName(format)); }

int RunReadback(const fs::path& dir) {
    if (NoVulkanDevice()) return kExitSkip;
    auto snapshot = std::make_shared<const int>(0);

    // Pitch and exactness: every readable format the device supports as a 2D texture, at widths
    // whose rows are not multiples of 256 bytes, and a lower mip level.
    {
        Engine engine(VulkanEngineOptions(dir));
        Check(!engine.DeviceError(), "the engine runs on the qualified Vulkan device",
              engine.DeviceError() ? engine.DeviceError()->Describe() : "");
        if (engine.DeviceError()) return Finish();
        const Result<CapabilityReport> report = engine.Capabilities();
        std::vector<uz::RHIFormat> formats;
        for (const uz::RHIFormat format : kReadableFormats) {
            const FormatCapability* capability = report ? report->Find(format) : nullptr;
            if (capability && capability->texture2D) {
                formats.push_back(format);
            } else {
                Info(Name(format) + " is not a 2D texture format on this device; not tested");
            }
        }
        const bool rgb32 = std::find(formats.begin(), formats.end(), uz::RHIFormat::RGB32Float) != formats.end();
        Check(rgb32 || ReadbackRefusal(Backend::Vulkan, uz::RHIFormat::RGB32Float).has_value(),
              "RGB32F, which this device cannot create, is refused by name on Vulkan");
        auto future = engine.Submit(snapshot, [&](EngineContext& context, const int&) -> Result<void> {
            IDevice& device = context.Device();
            constexpr uint32_t kWidths[] = {1, 3, 1023, 4097};
            bool rows = true;
            bool pitches = true;
            uint64_t seed = 1;
            for (const uz::RHIFormat format : formats) {
                for (const uint32_t width : kWidths) {
                    const std::string what = Name(format) + ", width " + std::to_string(width);
                    Result<Filled> filled = MakeFilled(context, format, width, 5, seed++);
                    if (!filled) {
                        rows = false;
                        Check(false, what + ": uploaded", filled.error().Describe());
                        continue;
                    }
                    const uint32_t texel = filled->layout.BytesPerTexel();
                    const uint64_t pitch = ReadbackRowPitch(uint64_t{width} * texel, texel);
                    pitches = pitches && pitch % kReadbackPitchAlignment == 0 && pitch % texel == 0 &&
                              pitch >= uint64_t{width} * texel;
                    TextureReadback readback(context);
                    Result<ReadbackId> id = readback.Request({filled->texture});
                    Result<ReadbackImage> image =
                        id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
                    const std::string diff = Compare(image, filled->texels, width, 5);
                    if (!diff.empty()) Check(false, what + ": every row reads back unshifted", diff);
                    rows = rows && diff.empty();
                    device.DestroyTexture(filled->texture);
                }
            }
            Check(pitches, "the pitch is a multiple of 256 bytes and of the texel size for every format and width");
            Check(rows, "every supported format reads back bit-identical at widths 1, 3, 1023 and 4097 (" +
                            std::to_string(formats.size()) + " formats)");
            Result<Filled> mipped = MakeFilled(context, uz::RHIFormat::RGBA16Unorm, 64, 40, 7, 3, 2);
            if (!mipped) return Unexpected(mipped.error());
            TextureReadback readback(context);
            ReadbackDesc desc{mipped->texture};
            desc.mipLevel = 2;
            Result<ReadbackId> id = readback.Request(desc);
            Result<ReadbackImage> image = id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
            const std::string diff = Compare(image, mipped->texels, 16, 10);
            Check(diff.empty(), "mip level 2 (16x10) reads back bit-identical", diff);
            device.DestroyTexture(mipped->texture);
            return {};
        });
        Result<void> result = Get(future);
        Check(result.has_value(), "the pitch request ran", Describe(result));
    }

    // Drain: 64 requests in flight, each with its own staging buffer, drained in submission
    // order; the destructor drains; nothing stays allocated.
    {
        Engine engine(VulkanEngineOptions(dir));
        if (engine.DeviceError()) return Finish();
        constexpr size_t kRequests = 64;
        auto future = engine.Submit(snapshot, [&](EngineContext& context, const int&) -> Result<void> {
            IDevice& device = context.Device();
            const uz::RHIFormat formats[] = {uz::RHIFormat::R16Unorm, uz::RHIFormat::RGBA16Unorm,
                                             uz::RHIFormat::R8Unorm,  uz::RHIFormat::RGBA8Unorm,
                                             uz::RHIFormat::R16Float, uz::RHIFormat::RGBA16Float,
                                             uz::RHIFormat::R32Float, uz::RHIFormat::RGBA32Float};
            const uint32_t widths[] = {1, 3, 255, 1023, 64, 513, 4097, 17};
            std::vector<Filled> textures;
            for (size_t i = 0; i < std::size(formats); ++i) {
                Result<Filled> filled = MakeFilled(context, formats[i], widths[i], 9, 1000 + i);
                if (!filled) return Unexpected(filled.error());
                textures.push_back(std::move(*filled));
            }
            const uint64_t baseline = LiveAllocations(device);
            {
                TextureReadback readback(context);
                std::vector<ReadbackId> ids;
                std::vector<size_t> sources;
                for (size_t i = 0; i < kRequests; ++i) {
                    const size_t source = (i * 5) % textures.size();
                    Result<ReadbackId> id = readback.Request({textures[source].texture});
                    if (!id) return Unexpected(id.error());
                    ids.push_back(*id);
                    sources.push_back(source);
                }
                Check(readback.Outstanding() == kRequests && readback.StagingBuffers() == kRequests,
                      "64 readback requests are outstanding, each with its own staging buffer",
                      std::to_string(readback.StagingBuffers()) + " staging buffers");
                Check(LiveAllocations(device) == baseline + kRequests,
                      "the device holds one staging allocation per outstanding request",
                      std::to_string(LiveAllocations(device) - baseline) + " allocations");
                const std::vector<ReadbackOutcome> outcomes = readback.Drain();
                bool order = outcomes.size() == kRequests;
                bool exact = order;
                std::string first;
                for (size_t i = 0; order && i < outcomes.size(); ++i) {
                    order = outcomes[i].id == ids[i];
                    const Filled& source = textures[sources[i]];
                    const std::string diff = Compare(outcomes[i].image, source.texels, source.width, source.height);
                    if (!diff.empty() && first.empty()) first = "request " + std::to_string(i) + ": " + diff;
                    exact = exact && diff.empty();
                }
                Check(order, "the drain reports every request in submission order",
                      std::to_string(outcomes.size()) + " outcomes");
                Check(exact, "every drained request returns its texture's texels", first);
                Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 0 &&
                          LiveAllocations(device) == baseline,
                      "after the drain no staging buffer remains allocated on the device",
                      std::to_string(LiveAllocations(device)) + " allocations, baseline " + std::to_string(baseline));
                for (size_t i = 0; i < 17; ++i) {
                    if (!readback.Request({textures[i % textures.size()].texture})) {
                        return Fail(ErrorCode::RequestFailed, Backend::Vulkan, "request before destruction");
                    }
                }
            }
            Check(LiveAllocations(device) == baseline,
                  "destroying a TextureReadback with 17 requests in flight drains it and releases their staging buffers",
                  std::to_string(LiveAllocations(device)) + " allocations, baseline " + std::to_string(baseline));
            for (const Filled& filled : textures) device.DestroyTexture(filled.texture);
            return {};
        });
        Result<void> result = Get(future);
        Check(result.has_value(), "the drain request ran", Describe(result));
    }

    // Device loss under pending readbacks: device_removed, no texels, the drain fails the other
    // request, a later request fails, and the readback holds no staging buffer.
    {
        Engine engine(VulkanEngineOptions(dir));
        if (engine.DeviceError()) return Finish();
        auto future = engine.Submit(snapshot, [&](EngineContext& context, const int&) -> Result<void> {
            Result<Filled> filled = MakeFilled(context, uz::RHIFormat::R16Unorm, 1023, 5, 77);
            if (!filled) return Unexpected(filled.error());
            TextureReadback readback(context);
            Result<ReadbackId> first = readback.Request({filled->texture});
            Result<ReadbackImage> before =
                first ? readback.Complete(*first) : Result<ReadbackImage>(Unexpected(first.error()));
            Check(Compare(before, filled->texels, 1023, 5).empty(), "a readback succeeds before the loss",
                  Describe(before));
            Result<ReadbackId> pending = readback.Request({filled->texture});
            Result<ReadbackId> pending2 = readback.Request({filled->texture});
            Check(pending && pending2 && readback.Outstanding() == 2, "two readbacks are pending when the device is lost");
            const PFN_vkWaitSemaphores real = vkWaitSemaphores;
            vkWaitSemaphores = &LostWaitSemaphores;
            Result<ReadbackImage> after =
                pending ? readback.Complete(*pending) : Result<ReadbackImage>(Unexpected(pending.error()));
            const std::vector<ReadbackOutcome> drained = readback.Drain();
            vkWaitSemaphores = real;
            Check(!after && after.error().Describe() == "device_removed {backend: vulkan, reason: VK_ERROR_DEVICE_LOST (-4)}",
                  "the pending readback fails with device_removed {backend: vulkan, reason}", Describe(after));
            Check(drained.size() == 1 && pending2 && drained[0].id == *pending2 && !drained[0].image &&
                      drained[0].image.error().code == ErrorCode::DeviceRemoved,
                  "the drain fails the other pending readback with device_removed");
            Result<ReadbackId> later = readback.Request({filled->texture});
            Check(!later && later.error().code == ErrorCode::DeviceRemoved,
                  "a readback requested after the loss fails with device_removed", Describe(later));
            Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 0,
                  "the failed readbacks hold no staging buffer (the lost device keeps their memory, abandoned)");
            context.Device().DestroyTexture(filled->texture);
            return {};
        });
        Result<void> result = Get(future);
        Check(result.has_value(), "the loss request ran", Describe(result));
        bool ran = false;
        auto next = engine.Submit(snapshot, [&](EngineContext&, const int&) -> Result<void> {
            ran = true;
            return {};
        });
        Result<void> later = Get(next);
        Check(!later && later.error().code == ErrorCode::DeviceRemoved && !ran,
              "later requests fail with device_removed without running", Describe(later));
        engine.Stop();
    }

    // A readback behind a stalled queue: timeout and no texels; its staging buffer is held while
    // the GPU may still write it and released by the drain once the copy completed.
    {
        EngineOptions options = VulkanEngineOptions(dir);
        options.requestDeadline = Ms{300};
        Engine engine(options);
        if (engine.DeviceError()) return Finish();
        auto future = engine.Submit(snapshot, [&](EngineContext& context, const int&) -> Result<void> {
            auto& device = static_cast<VulkanDevice&>(context.Device());
            Result<Filled> filled = MakeFilled(context, uz::RHIFormat::RGBA16Unorm, 300, 4, 91);
            if (!filled) return Unexpected(filled.error());
            Result<std::function<void()>> release = device.InjectQueueStall();
            if (!release) return Unexpected(release.error());
            TextureReadback readback(context);
            Result<ReadbackId> id = readback.Request({filled->texture});
            Result<ReadbackImage> image = id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
            Check(!image && image.error().code == ErrorCode::Timeout,
                  "a readback behind a stalled queue fails with timeout and no texels", Describe(image));
            Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 1,
                  "its staging buffer is held while the GPU may still write it");
            (*release)();
            const auto until = Clock::now() + std::chrono::seconds(10);
            while (device.Queue().Completed() < device.Queue().LastSubmitted() && Clock::now() < until) {
                std::this_thread::sleep_for(Ms{5});
            }
            static_cast<void>(readback.Drain());
            Check(readback.StagingBuffers() == 0, "once the copy has completed the drain releases the held staging buffer");
            device.DestroyTexture(filled->texture);
            return {};
        });
        Result<void> result = Get(future);
        Check(result.has_value(), "the timeout request ran", Describe(result));
        engine.Stop();
    }
    return Finish();
}

}  // namespace

int RunVulkanCase(std::string_view mode, const fs::path& dir) {
    if (mode == "vulkan-qualify") return RunQualify();
    if (mode == "vulkan-device") return RunDevice();
    if (mode == "vulkan-faults") return RunFaults();
    if (mode == "vulkan-readback") return RunReadback(dir);
    return -1;
}
