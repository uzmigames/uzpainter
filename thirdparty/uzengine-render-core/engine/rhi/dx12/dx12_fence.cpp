// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-003. Original: UzEngine runtime/engine/rhi/dx12/dx12_fence.cpp at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

/// DX12 Fence Implementation
///
/// CPU-GPU synchronization via ID3D12Fence + Win32 event.
/// Supports Signal (GPU increments), WaitCPU (block until reached, the deadline or device
/// removal), and status queries.
/// Single event per fence; shared across multiple Signal/Wait pairs.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "dx12_fence.h"
#include "dx12_guids.h"

// IID_PPV_ARGS(&m_fence) needs __uuidof(ID3D12Fence). On Clang/MinGW that
// resolves through __mingw_uuidof<T>, whose primary template is declared but
// never defined — without the __CRT_UUID_DECL entries this compiles and then
// fails at link with "undefined symbol: __mingw_uuidof<ID3D12Fence>()".
#include "dx12_guids.h"

#include "log.h"
#include "profiler.h"

#include <windows.h>

#include <chrono>

namespace uz {

namespace {

/// Device-removed reason of the device that owns `fence`: `S_OK` while the device is
/// alive, a failure code (for example `DXGI_ERROR_DEVICE_REMOVED`) once it is removed.
HRESULT DeviceRemovedReason(ID3D12Fence* fence) {
    ComPtr<ID3D12Device> device;
    if (FAILED(fence->GetDevice(IID_PPV_ARGS(&device))) || !device) {
        return S_OK;
    }
    return device->GetDeviceRemovedReason();
}

} // namespace

/// Cleanup: closes Win32 event if allocated.
DX12Fence::~DX12Fence() {
    if (m_event) {
        CloseHandle(m_event);
        m_event = nullptr;
    }
}

bool DX12Fence::Init(ID3D12Device* device, ID3D12CommandQueue* queue) {
    UZ_PROFILE_FUNCTION();
    if (!queue) {
        UZ_LOG(RHI, Error, "DX12Fence::Init — null command queue");
        return false;
    }

    HRESULT hr = device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&m_fence));
    if (FAILED(hr)) {
        UZ_LOG(RHI, Error, "Failed to create ID3D12Fence, hr=0x{:08X}", static_cast<uint32_t>(hr));
        return false;
    }

    m_queue = queue;

    m_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!m_event) {
        UZ_LOG(RHI, Error, "Failed to create Win32 event for fence");
        m_fence.Reset();
        return false;
    }

    UZ_LOG(RHI, Trace, "DX12Fence created");
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// IRHIFence implementation
// ─────────────────────────────────────────────────────────────────────────────

void DX12Fence::Signal(uint64_t value) {
    HRESULT hr = m_queue->Signal(m_fence.Get(), value);
    if (FAILED(hr)) {
        UZ_LOG(RHI, Error, "DX12Fence::Signal({}) failed, hr=0x{:08X}", value, static_cast<uint32_t>(hr));
    }
}

FenceWaitResult DX12Fence::WaitCPU(uint64_t value, FenceDeadline deadline) {
    UZ_PROFILE_FUNCTION();
    // Removal is checked before the completed value: a removed device reports UINT64_MAX,
    // which would otherwise read as "signaled" for every value.
    auto settled = [this, value](FenceWaitResult& out) {
        const HRESULT removed = DeviceRemovedReason(m_fence.Get());
        if (FAILED(removed)) {
            UZ_LOG(RHI, Error, "DX12Fence::WaitCPU: device removed while waiting for value {}, reason 0x{:08X}",
                   value, static_cast<uint32_t>(removed));
            out = {FenceWaitStatus::DeviceLost, static_cast<int32_t>(removed)};
            return true;
        }
        if (m_fence->GetCompletedValue() >= value) {
            out = {FenceWaitStatus::Signaled, 0};
            return true;
        }
        return false;
    };

    FenceWaitResult result;
    if (settled(result)) {
        return result;
    }

    // Without the event (registration or wait failed) the wait polls; it is bounded by the
    // deadline either way.
    HRESULT hr = m_fence->SetEventOnCompletion(value, m_event);
    bool useEvent = SUCCEEDED(hr);
    if (!useEvent) {
        UZ_LOG(RHI, Error, "DX12Fence::SetEventOnCompletion({}) failed, hr=0x{:08X}; polling until the deadline",
               value, static_cast<uint32_t>(hr));
    }

    for (;;) {
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline) {
            if (settled(result)) {
                return result;
            }
            UZ_LOG(RHI, Warning, "DX12Fence::WaitCPU: deadline passed waiting for value {} (completed {})",
                   value, m_fence->GetCompletedValue());
            return {FenceWaitStatus::Timeout, 0};
        }
        if (useEvent) {
            // Rounded up so the wait never ends before the deadline; kept below INFINITE.
            const long long remaining =
                std::chrono::ceil<std::chrono::milliseconds>(deadline - now).count();
            const long long maxWait = static_cast<long long>(INFINITE) - 1;
            const DWORD waitMs = static_cast<DWORD>(remaining < maxWait ? remaining : maxWait);
            if (WaitForSingleObject(m_event, waitMs) == WAIT_FAILED) {
                UZ_LOG(RHI, Error, "DX12Fence::WaitCPU: WaitForSingleObject failed (Win32 error {}); polling until the deadline",
                       static_cast<uint32_t>(GetLastError()));
                useEvent = false;
            }
        } else {
            Sleep(1);
        }
        // The auto-reset event may also be set by an earlier registration for another value,
        // so removal, completion and the deadline are re-checked after every wake-up.
        if (settled(result)) {
            return result;
        }
    }
}

bool DX12Fence::IsComplete(uint64_t value) const {
    return m_fence->GetCompletedValue() >= value;
}

uint64_t DX12Fence::GetCompletedValue() const {
    return m_fence->GetCompletedValue();
}

} // namespace uz
