// Test-only fault hooks of the worker (fault_hooks.h).

#if defined(UZP_WORKER_FAULT_HOOKS)

#include "supervisor/fault_hooks.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "render/device.h"
#include "render/vulkan_backend.h"
#include "store/fault.h"

#include <windows.h>
#include <wrl/client.h>

#include <atomic>
#include <charconv>
#include <fstream>
#include <cstdlib>

namespace uzp::supervisor::fault {

namespace {

enum class GpuFault : int { none, remove_device, gpu_stall };

std::atomic<GpuFault> g_gpu{GpuFault::none};
std::atomic<bool> g_kill_before_reply{false};
std::atomic<store::fault::Fault> g_save_fault{store::fault::Fault::none};

render::Dx12Device* Dx12(render::EngineContext& context) { return dynamic_cast<render::Dx12Device*>(&context.Device()); }

}  // namespace

void ConfigureVulkanHeapFixture(render::EngineOptions& options) {
    const char* value = std::getenv("UZP_TEST_VULKAN_HEAP_BYTES");
    if (!value || options.device.backend != render::Backend::Vulkan || options.createDevice) return;
    const std::string text(value);
    const auto deviceOptions = options.device;
    options.createDevice = [text, deviceOptions]() -> render::Result<std::unique_ptr<render::IDevice>> {
        uint64_t bytes = 0;
        const auto parsed = std::from_chars(text.data(), text.data() + text.size(), bytes);
        if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || bytes == 0) {
            return render::Fail(render::ErrorCode::GpuBackendUnavailable, render::Backend::Vulkan,
                                "UZP_TEST_VULKAN_HEAP_BYTES must be a positive byte count");
        }
        auto survey = render::SurveyVulkan();
        for (auto& record : survey.devices) {
            record.memoryBudget = false;
            std::erase(record.extensions, std::string("VK_EXT_memory_budget"));
            bool assigned = false;
            for (auto& heap : record.heaps) {
                heap.budgetBytes = heap.usageBytes = 0;
                // VK_MEMORY_HEAP_DEVICE_LOCAL_BIT is 0x1 in the recorded Vulkan flags.
                if ((heap.flags & 0x1u) != 0) {
                    heap.sizeBytes = assigned ? 0 : bytes;
                    assigned = true;
                }
            }
        }
        const auto qualified = render::QualifyVulkan(survey, deviceOptions.adapterIndex);
        render::VulkanDeviceOptions native;
        native.enableValidation = deviceOptions.enableValidation;
        auto device = render::CreateQualifiedVulkanDevice(survey, qualified, native);
        if (!device) return render::Unexpected(device.error());
        return std::unique_ptr<render::IDevice>(std::move(*device));
    };
}

std::optional<Fault> Parse(std::string_view name) {
    if (name == "kill") return Fault::kill;
    if (name == "abort") return Fault::abort;
    if (name == "seh") return Fault::seh;
    if (name == "remove_device") return Fault::remove_device;
    if (name == "gpu_stall") return Fault::gpu_stall;
    if (name == "kill_before_reply") return Fault::kill_before_reply;
    if (name == "kill_during_save") return Fault::kill_during_save;
    if (name == "kill_during_compaction") return Fault::kill_during_compaction;
    return std::nullopt;
}

void KillNow() {
    TerminateProcess(GetCurrentProcess(), kKillExitCode);
    std::_Exit(static_cast<int>(kKillExitCode));
}

void Trigger(Fault fault) {
    switch (fault) {
        case Fault::kill:
            KillNow();
        case Fault::abort:
            std::abort();
        case Fault::seh: {
            volatile int* target = nullptr;
            *target = 1;  // EXCEPTION_ACCESS_VIOLATION, reported by the crash handler
            break;
        }
        case Fault::remove_device:
            g_gpu = GpuFault::remove_device;
            break;
        case Fault::gpu_stall:
            g_gpu = GpuFault::gpu_stall;
            break;
        case Fault::kill_before_reply:
            g_kill_before_reply = true;
            break;
        case Fault::kill_during_save:
            g_save_fault = store::fault::Fault::kill_during_commit;
            break;
        case Fault::kill_during_compaction:
            g_save_fault = store::fault::Fault::kill_during_vacuum;
            break;
    }
}

bool GpuFaultArmed() { return g_gpu.load() != GpuFault::none; }

render::Result<void> InjectGpuFault(render::EngineContext& context) {
    const GpuFault fault = g_gpu.exchange(GpuFault::none);
    if (fault == GpuFault::none) return {};
    if (auto* vulkan = dynamic_cast<render::VulkanDevice*>(&context.Device())) {
        if (fault == GpuFault::remove_device) {
            vulkan->InjectDeviceLoss();
        } else {
            // Leave the semaphore unsignalled: timeout makes the worker exit, keeping GPU
            // resources alive until then. Dropping the callback does not signal it.
            const auto release = vulkan->InjectQueueStall();
            if (!release) return render::Unexpected(release.error());
        }
        return context.SubmitAndWait([](uz::IRHICommandList&) {});
    }
    render::Dx12Device* device = Dx12(context);
    if (!device) {
        return render::Fail(render::ErrorCode::RequestFailed, context.Device().GetBackend(),
                            "the GPU fault hooks need a DX12 or Vulkan device");
    }
    if (fault == GpuFault::remove_device) {
        Microsoft::WRL::ComPtr<ID3D12Device5> device5;
        if (FAILED(device->D3D12()->QueryInterface(IID_PPV_ARGS(&device5)))) {
            return render::Fail(render::ErrorCode::RequestFailed, render::Backend::Dx12,
                                "ID3D12Device5 is not available for RemoveDevice");
        }
        device5->RemoveDevice();
    } else {
        // A GPU-side wait on a fence nothing signals: every later submission on the direct queue
        // stays pending, so the request's deadline wait returns `timeout`. The fence is never
        // released; the worker exits after the timeout.
        ID3D12Fence* never = nullptr;
        if (FAILED(device->D3D12()->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&never)))) {
            return render::Fail(render::ErrorCode::RequestFailed, render::Backend::Dx12, "CreateFence failed");
        }
        device->Native().GetDirectQueue()->Wait(never, 1);
    }
    // The empty submission that observes the fault: `device_removed` or `timeout`.
    return context.SubmitAndWait([](uz::IRHICommandList&) {});
}

bool TakeKillBeforeReply() { return g_kill_before_reply.exchange(false); }

SaveFaultScope::SaveFaultScope() {
    const store::fault::Fault fault = g_save_fault.exchange(store::fault::Fault::none);
    if (fault != store::fault::Fault::none) store::fault::Arm(fault);
}

SaveFaultScope::~SaveFaultScope() { store::fault::Arm(store::fault::Fault::none); }

void MaybeKillOnOpen() {
    const char* path = std::getenv("UZP_TEST_KILL_ON_OPEN");
    if (!path || !*path) return;
    long count = 0;
    {
        std::ifstream in(path);
        if (!(in >> count) || count <= 0) return;
    }
    {
        std::ofstream out(path, std::ios::trunc);
        out << (count - 1);
    }
    KillNow();
}

core::json::Object OverrideHandshake(core::json::Object handshake) {
    const char* text = std::getenv("UZP_TEST_HANDSHAKE");
    if (!text || !*text) return handshake;
    const core::json::Value value = core::json::Parse(text);
    if (!value.IsObject()) return handshake;
    for (const auto& [key, field] : std::get<core::json::Object>(value.data)) handshake[key] = field;
    return handshake;
}

}  // namespace uzp::supervisor::fault

#endif
