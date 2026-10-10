// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-003. Original: UzEngine runtime/engine/rhi/rhi_fence.h at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

#pragma once

/// RHI fence interface for CPU-GPU synchronization.

#include <chrono>
#include <cstdint>

namespace uz {

// ─────────────────────────────────────────────────────────────────────────────
// Bounded fence wait
// ─────────────────────────────────────────────────────────────────────────────

/// Outcome of a bounded CPU wait on a fence (`IRHIFence::WaitCPU`).
enum class FenceWaitStatus : uint8_t {
    Signaled,    ///< The fence reached the value before the deadline.
    Timeout,     ///< The deadline passed and the device is still alive.
    DeviceLost,  ///< The device is lost or the wait itself failed; `backendReason` says why.
};

/// Result of `IRHIFence::WaitCPU`.
struct FenceWaitResult {
    FenceWaitStatus status = FenceWaitStatus::Signaled;
    /// The backend's reason when `status` is `DeviceLost`, 0 otherwise: on DX12 the
    /// device-removed reason (`ID3D12Device::GetDeviceRemovedReason`, an `HRESULT`), on
    /// Vulkan the `VkResult` of the wait (for example `VK_ERROR_DEVICE_LOST`).
    int32_t backendReason = 0;
};

/// Point in time after which `IRHIFence::WaitCPU` stops waiting.
using FenceDeadline = std::chrono::steady_clock::time_point;

// ─────────────────────────────────────────────────────────────────────────────
// IRHIFence — CPU/GPU synchronization primitive
// ─────────────────────────────────────────────────────────────────────────────

/// GPU fence for synchronizing CPU and GPU work.
///
/// Fences are monotonically increasing: each `Signal(value)` must use a value
/// greater than any previously signaled value. The fence starts at value 0.
///
/// # Thread Safety
/// All methods are thread-safe. Multiple CPU threads can poll `IsComplete()`
/// concurrently. Only one thread should call `WaitCPU()` at a time per fence.
///
/// # Lifetime
/// Created via `IRHIDevice::CreateFence()`, destroyed via `IRHIDevice::DestroyFence()`.
/// Must be destroyed before the device.
///
/// # Examples
/// ```cpp
/// auto* fence = device->CreateFence();
/// uint64_t fenceValue = 1;
///
/// cmdList->End();
/// cmdList->Execute();
/// fence->Signal(fenceValue);
/// FenceWaitResult r = fence->WaitCPU(fenceValue,
///     std::chrono::steady_clock::now() + std::chrono::seconds(10));
/// if (r.status == FenceWaitStatus::Signaled) {
///     // GPU work is now complete
/// }
///
/// device->DestroyFence(fence);
/// ```
class IRHIFence {
public:
    virtual ~IRHIFence() = default;

    /// Signals the fence to the given value from the GPU timeline.
    ///
    /// # Arguments
    /// * `value` — Monotonically increasing fence value. Must be greater
    ///   than any previously signaled value.
    virtual void Signal(uint64_t value) = 0;

    /// Blocks the calling CPU thread until the fence reaches the given value, the
    /// deadline passes or the device is lost, whichever comes first.
    ///
    /// Returns `Signaled` at once if the fence has already reached or passed `value`
    /// on a live device. Never waits past `deadline` (plus scheduling latency); a
    /// device loss the backend reports is returned as `DeviceLost`, never as
    /// `Signaled` or `Timeout`.
    ///
    /// # Arguments
    /// * `value` — The fence value to wait for.
    /// * `deadline` — Latest point in time to return by.
    ///
    /// # Returns
    /// `Signaled`, `Timeout`, or `DeviceLost` with the backend's reason.
    [[nodiscard]] virtual FenceWaitResult WaitCPU(uint64_t value, FenceDeadline deadline) = 0;

    /// Returns true if the fence has reached or passed the given value.
    ///
    /// # Arguments
    /// * `value` — The fence value to check against.
    ///
    /// # Returns
    /// `true` if `GetCompletedValue() >= value`, `false` otherwise.
    virtual bool IsComplete(uint64_t value) const = 0;

    /// Returns the highest value the fence has completed on the GPU.
    ///
    /// # Returns
    /// The most recently completed fence value, or 0 if no signal has occurred.
    virtual uint64_t GetCompletedValue() const = 0;
};

} // namespace uz
