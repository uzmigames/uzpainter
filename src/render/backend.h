#pragma once

// Backend-neutral interfaces of UzPainter's render layer (docs/architecture/13-engine-integration.md
// §4.1): the device and its queue, resources and compute kernels over the vendored RHI, the
// bounded wait result and the errors the layer reports (docs/architecture/02-runtime-topology.md
// §1, §5). DX12 implements them in device.cpp; Vulkan follows in Phase 3.
//
// Threading: an `IDevice` and its `IQueue` are used by the engine thread only (engine_thread.h);
// nothing here is synchronised.

#include "rhi.h"

#include <chrono>
#include <cstdint>
#include <expected>
#include <functional>
#include <optional>
#include <span>
#include <string>
#include <string_view>

namespace uzp::render {

/// The GPU backend of a process (`--gpu-backend dx12|vulkan`). There is no fallback from one
/// to the other.
enum class Backend : uint8_t { Dx12, Vulkan };

/// "dx12" or "vulkan", the spelling of `--gpu-backend` and of error reports.
[[nodiscard]] std::string_view BackendName(Backend backend);
[[nodiscard]] std::optional<Backend> ParseBackend(std::string_view name);

using Clock = std::chrono::steady_clock;
using Deadline = Clock::time_point;

/// Outcome of a bounded GPU wait.
enum class WaitStatus : uint8_t { Signaled, Timeout, DeviceLost };

/// "signaled", "timeout" or "device_lost".
[[nodiscard]] std::string_view WaitStatusName(WaitStatus status);

struct WaitResult {
    WaitStatus status = WaitStatus::Signaled;
    /// For `DeviceLost`, the backend's reason (DX12: the device-removed `HRESULT`); 0 otherwise.
    int32_t backendReason = 0;
};

/// Error kinds of the render layer; `ErrorCodeName` gives their report spelling.
enum class ErrorCode : uint8_t {
    GpuBackendUnavailable,   ///< No device of the requested backend; nothing was executed.
    DeviceRemoved,           ///< DX12 device removed / Vulkan device lost.
    Timeout,                 ///< A GPU wait passed its deadline.
    KernelCompileFailed,     ///< DXC rejected a kernel or could not be loaded.
    ResourceCreationFailed,  ///< A buffer, texture, pipeline or command list was not created.
    EngineStopped,           ///< The engine thread stopped before the request ran.
    RequestFailed,           ///< The request itself failed (invalid input, exception).
};

/// "gpu_backend_unavailable", "device_removed", "timeout", "kernel_compile_failed",
/// "resource_creation_failed", "engine_stopped" or "request_failed".
[[nodiscard]] std::string_view ErrorCodeName(ErrorCode code);

struct Error {
    ErrorCode code = ErrorCode::RequestFailed;
    /// The backend the error belongs to; empty for backend-free work (kernel compilation).
    std::optional<Backend> backend;
    std::string reason;

    /// `<code> {backend: <backend>, reason: <reason>}`, e.g.
    /// `device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED (0x887A0005)}`.
    [[nodiscard]] std::string Describe() const;
};

template <class T>
using Result = std::expected<T, Error>;

/// `std::unexpected<Error>`. Named through `std::expected` because Zig's libc++ also declares the
/// pre-C++17 function `std::unexpected()`, which makes the bare name ambiguous.
using Unexpected = std::expected<void, Error>::unexpected_type;

[[nodiscard]] Unexpected Fail(ErrorCode code, std::optional<Backend> backend, std::string reason);

/// Bytecode format of compiled kernels.
enum class KernelTarget : uint8_t { Dxil, Spirv };

/// "dxil" or "spirv".
[[nodiscard]] std::string_view KernelTargetName(KernelTarget target);

/// A compute kernel created on a device: its shader module and pipeline. Kernels bind through
/// the render core's root layout: root constants at parameter 0 (b0), the UAV table at
/// parameter 4 (u0).
struct ComputeKernel {
    uz::RHIShaderHandle shader = uz::RHIShaderHandle::Invalid();
    uz::RHIPipelineHandle pipeline = uz::RHIPipelineHandle::Invalid();
};

/// Root parameter indices of the render core's shared root layout used by compute kernels.
inline constexpr uint32_t kRootConstantsParam = 0;
inline constexpr uint32_t kUavTableParam = 4;

/// Records the commands of one submission.
using RecordFn = std::function<void(uz::IRHICommandList&)>;

/// The device's submission queue, with a monotonically increasing fence.
class IQueue {
public:
    virtual ~IQueue() = default;

    /// Records one command list with `record`, submits it and returns the fence value that is
    /// signalled when it has completed.
    virtual Result<uint64_t> Submit(const RecordFn& record) = 0;

    /// Waits until the fence reaches `value`, the deadline passes or the device is lost; never
    /// waits past `deadline`.
    [[nodiscard]] virtual WaitResult Wait(uint64_t value, Deadline deadline) = 0;

    /// The fence value of the last submission (0 before the first).
    [[nodiscard]] virtual uint64_t LastSubmitted() const = 0;
    /// The highest fence value the GPU has completed.
    [[nodiscard]] virtual uint64_t Completed() const = 0;
};

/// One GPU device of one backend.
class IDevice {
public:
    virtual ~IDevice() = default;

    [[nodiscard]] virtual Backend GetBackend() const = 0;
    [[nodiscard]] virtual const std::string& AdapterName() const = 0;
    /// The bytecode format this device consumes.
    [[nodiscard]] virtual KernelTarget NativeKernelTarget() const = 0;

    virtual IQueue& Queue() = 0;

    virtual Result<uz::RHIBufferHandle> CreateBuffer(const uz::RHIBufferDesc& desc) = 0;
    virtual void DestroyBuffer(uz::RHIBufferHandle buffer) = 0;
    virtual Result<uz::RHITextureHandle> CreateTexture(const uz::RHITextureDesc& desc) = 0;
    virtual void DestroyTexture(uz::RHITextureHandle texture) = 0;
    /// The creation description of a live texture; empty for an invalid or destroyed handle.
    [[nodiscard]] virtual std::optional<uz::RHITextureDesc> TextureDesc(
        uz::RHITextureHandle texture) const = 0;
    /// A compute kernel from bytecode of `NativeKernelTarget()`.
    virtual Result<ComputeKernel> CreateComputeKernel(std::span<const uint8_t> bytecode,
                                                      const std::string& name) = 0;
    virtual void DestroyComputeKernel(const ComputeKernel& kernel) = 0;

    /// The vendored RHI device, for recording commands and descriptor queries.
    virtual uz::IRHIDevice& Rhi() = 0;

    /// The host view of a `Readback` buffer whose copy has completed (its fence waited on); null
    /// when it cannot be mapped. Vulkan invalidates the allocation first (decision 310 §5).
    [[nodiscard]] virtual const void* MapReadback(uz::RHIBufferHandle buffer) { return Rhi().MapBuffer(buffer); }

    /// The most compute dispatches one submission may record. Unbounded on DX12; on Vulkan each
    /// dispatch takes a descriptor snapshot from a fixed pool (decision 313).
    [[nodiscard]] virtual uint32_t MaxDispatchesPerSubmission() const { return UINT32_MAX; }

    /// Empty while the device is alive; `device_removed {backend, reason}` once it is removed
    /// or lost.
    [[nodiscard]] virtual std::optional<Error> CheckRemoved() const = 0;

    /// The error a failed wait stands for: `timeout`, or `device_removed` with the backend's
    /// reason. Must not be called with a `Signaled` result.
    [[nodiscard]] virtual Error WaitFailure(const WaitResult& wait) const = 0;
};

}  // namespace uzp::render
