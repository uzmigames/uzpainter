// Test-only fault hooks of the worker (fault_hooks.h).

#if defined(UZP_WORKER_FAULT_HOOKS)

#include "supervisor/fault_hooks.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "render/device.h"

#include <windows.h>
#include <wrl/client.h>

#include <atomic>
#include <cstdlib>

namespace uzp::supervisor::fault {

namespace {

enum class GpuFault : int { none, remove_device, gpu_stall };

std::atomic<GpuFault> g_gpu{GpuFault::none};
std::atomic<bool> g_kill_before_reply{false};

render::Dx12Device* Dx12(render::EngineContext& context) { return dynamic_cast<render::Dx12Device*>(&context.Device()); }

}  // namespace

std::optional<Fault> Parse(std::string_view name) {
    if (name == "kill") return Fault::kill;
    if (name == "abort") return Fault::abort;
    if (name == "seh") return Fault::seh;
    if (name == "remove_device") return Fault::remove_device;
    if (name == "gpu_stall") return Fault::gpu_stall;
    if (name == "kill_before_reply") return Fault::kill_before_reply;
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
    }
}

bool GpuFaultArmed() { return g_gpu.load() != GpuFault::none; }

render::Result<void> InjectGpuFault(render::EngineContext& context) {
    const GpuFault fault = g_gpu.exchange(GpuFault::none);
    if (fault == GpuFault::none) return {};
    render::Dx12Device* device = Dx12(context);
    if (!device) {
        return render::Fail(render::ErrorCode::RequestFailed, context.Device().GetBackend(),
                            "the GPU fault hooks need a DX12 device");
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
