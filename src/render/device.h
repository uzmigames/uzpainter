#pragma once

// Device creation for the selected backend (docs/architecture/02-runtime-topology.md §1) and the
// DX12 implementation of the backend-neutral interfaces of backend.h over the vendored RHI.
//
// The requested backend is the only one ever tried: when no device of it can be created the
// caller gets `gpu_backend_unavailable {backend, reason}` and no other backend is attempted.

#include "render/backend.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

struct ID3D12Device;

namespace uz {
class DX12Device;
}

namespace uzp::render {

struct DeviceOptions {
    Backend backend = Backend::Dx12;
    /// Adapter index in DXGI's high-performance order (0 = the high-performance adapter).
    uint32_t adapterIndex = 0;
    /// D3D12 debug layer (development only).
    bool enableValidation = false;
};

/// The device of `options.backend`, or `gpu_backend_unavailable {backend, reason}`.
/// Only DX12 is implemented; a Vulkan request is reported unavailable, never served by DX12.
[[nodiscard]] Result<std::unique_ptr<IDevice>> CreateDevice(const DeviceOptions& options);

/// "DXGI_ERROR_DEVICE_REMOVED (0x887A0005)" for a device-removed reason; the hex value alone for
/// codes without a name.
[[nodiscard]] std::string DeviceRemovedReasonText(int32_t hresult);

class Dx12Queue;

/// The DX12 device: the vendored `uz::DX12Device` and its direct queue.
class Dx12Device final : public IDevice {
public:
    ~Dx12Device() override;
    Dx12Device(const Dx12Device&) = delete;
    Dx12Device& operator=(const Dx12Device&) = delete;

    Backend GetBackend() const override { return Backend::Dx12; }
    const std::string& AdapterName() const override { return m_adapterName; }
    KernelTarget NativeKernelTarget() const override { return KernelTarget::Dxil; }
    IQueue& Queue() override;

    Result<uz::RHIBufferHandle> CreateBuffer(const uz::RHIBufferDesc& desc) override;
    void DestroyBuffer(uz::RHIBufferHandle buffer) override;
    Result<uz::RHITextureHandle> CreateTexture(const uz::RHITextureDesc& desc) override;
    void DestroyTexture(uz::RHITextureHandle texture) override;
    std::optional<uz::RHITextureDesc> TextureDesc(uz::RHITextureHandle texture) const override;
    Result<ComputeKernel> CreateComputeKernel(std::span<const uint8_t> bytecode,
                                              const std::string& name) override;
    void DestroyComputeKernel(const ComputeKernel& kernel) override;

    uz::IRHIDevice& Rhi() override;
    std::optional<Error> CheckRemoved() const override;
    Error WaitFailure(const WaitResult& wait) const override;

    /// The vendored DX12 device (capability queries, DX12-only tests).
    [[nodiscard]] uz::DX12Device& Native() { return *m_native; }
    [[nodiscard]] ID3D12Device* D3D12() const;
    [[nodiscard]] uint32_t AdapterIndex() const { return m_adapterIndex; }

private:
    friend Result<std::unique_ptr<IDevice>> CreateDevice(const DeviceOptions& options);
    Dx12Device(std::unique_ptr<uz::IRHIDevice> rhi, uint32_t adapterIndex);

    std::unique_ptr<uz::IRHIDevice> m_rhi;
    uz::DX12Device* m_native = nullptr;
    std::unique_ptr<Dx12Queue> m_queue;
    std::string m_adapterName;
    uint32_t m_adapterIndex = 0;
};

/// The direct queue of a `Dx12Device`: one fence, one command list per in-flight submission
/// (command lists are reused once the fence shows them complete).
class Dx12Queue final : public IQueue {
public:
    Dx12Queue(uz::IRHIDevice& device, uz::IRHIFence* fence);
    ~Dx12Queue() override;
    Dx12Queue(const Dx12Queue&) = delete;
    Dx12Queue& operator=(const Dx12Queue&) = delete;

    Result<uint64_t> Submit(const RecordFn& record) override;
    WaitResult Wait(uint64_t value, Deadline deadline) override;
    uint64_t LastSubmitted() const override { return m_lastSubmitted; }
    uint64_t Completed() const override;

private:
    struct InFlight {
        uz::IRHICommandList* list;
        uint64_t value;
    };
    void Retire();

    uz::IRHIDevice& m_device;
    uz::IRHIFence* m_fence;
    uint64_t m_lastSubmitted = 0;
    std::vector<InFlight> m_inFlight;
    std::vector<uz::IRHICommandList*> m_free;
};

}  // namespace uzp::render
