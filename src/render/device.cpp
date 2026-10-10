#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/device.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "rhi_backend.h"

#include <windows.h>

#include <cstdio>
#include <utility>

namespace uzp::render {

namespace {

using Microsoft::WRL::ComPtr;

std::string Utf8(const wchar_t* wide) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string out(static_cast<size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide, -1, out.data(), size, nullptr, nullptr);
    return out;
}

std::string Hex32(uint32_t value) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%08X", value);
    return buf;
}

Unexpected Dx12Unavailable(std::string reason) {
    return Fail(ErrorCode::GpuBackendUnavailable, Backend::Dx12, std::move(reason));
}

}  // namespace

std::string DeviceRemovedReasonText(int32_t hresult) {
    const auto code = static_cast<uint32_t>(hresult);
    const char* name = nullptr;
    switch (code) {
        case 0x887A0001u: name = "DXGI_ERROR_INVALID_CALL"; break;
        case 0x887A0005u: name = "DXGI_ERROR_DEVICE_REMOVED"; break;
        case 0x887A0006u: name = "DXGI_ERROR_DEVICE_HUNG"; break;
        case 0x887A0007u: name = "DXGI_ERROR_DEVICE_RESET"; break;
        case 0x887A0020u: name = "DXGI_ERROR_DRIVER_INTERNAL_ERROR"; break;
        case 0x8007000Eu: name = "E_OUTOFMEMORY"; break;
        default: break;
    }
    return name ? std::string(name) + " (" + Hex32(code) + ")" : Hex32(code);
}

// ── Device creation ──────────────────────────────────────────────────────────

Result<std::unique_ptr<IDevice>> CreateDevice(const DeviceOptions& options) {
    if (options.backend == Backend::Vulkan) {
        return Fail(ErrorCode::GpuBackendUnavailable, Backend::Vulkan,
                    "this build's render layer implements DX12 only; Vulkan devices are not "
                    "available and DX12 is not used in their place");
    }

    // The adapter is looked up first, so a missing one is reported by index rather than as a
    // failed device creation.
    ComPtr<IDXGIFactory6> factory;
    HRESULT hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    if (FAILED(hr)) {
        return Dx12Unavailable("CreateDXGIFactory2 failed, hr=" + Hex32(static_cast<uint32_t>(hr)));
    }
    ComPtr<IDXGIAdapter1> adapter;
    hr = factory->EnumAdapterByGpuPreference(options.adapterIndex,
                                             DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                             IID_PPV_ARGS(&adapter));
    if (FAILED(hr)) {
        uint32_t count = 0;
        for (ComPtr<IDXGIAdapter1> probe;
             SUCCEEDED(factory->EnumAdapterByGpuPreference(
                 count, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&probe)));
             probe.Reset()) {
            ++count;
        }
        return Dx12Unavailable("no DXGI adapter at index " + std::to_string(options.adapterIndex) +
                               " (" + std::to_string(count) + " adapters present)");
    }
    DXGI_ADAPTER_DESC1 adapterDesc{};
    adapter->GetDesc1(&adapterDesc);
    const std::string adapterName = Utf8(adapterDesc.Description);

    uz::RHIDeviceDesc desc;
    desc.backend = uz::RHIBackend::DX12;
    desc.adapterIndex = options.adapterIndex;
    desc.enableValidation = options.enableValidation;
    std::unique_ptr<uz::IRHIDevice> rhi = uz::CreateRHIDevice(desc);
    if (!rhi) {
        return Dx12Unavailable("DX12 device creation failed on adapter " +
                               std::to_string(options.adapterIndex) + " '" + adapterName +
                               "' (the render core log has the cause)");
    }
    std::unique_ptr<Dx12Device> device(new Dx12Device(std::move(rhi), options.adapterIndex));
    if (!device->m_queue) {
        return Dx12Unavailable("the DX12 device on adapter '" + adapterName +
                               "' could not create its queue fence");
    }
    return std::unique_ptr<IDevice>(std::move(device));
}

// ── Dx12Device ───────────────────────────────────────────────────────────────

Dx12Device::Dx12Device(std::unique_ptr<uz::IRHIDevice> rhi, uint32_t adapterIndex)
    : m_rhi(std::move(rhi)),
      m_native(static_cast<uz::DX12Device*>(m_rhi.get())),
      m_adapterName(m_rhi->GetAdapterName()),
      m_adapterIndex(adapterIndex) {
    if (uz::IRHIFence* fence = m_rhi->CreateFence()) {
        m_queue = std::make_unique<Dx12Queue>(*m_rhi, fence);
    }
}

Dx12Device::~Dx12Device() {
    m_queue.reset();
    m_rhi.reset();
}

IQueue& Dx12Device::Queue() { return *m_queue; }

uz::IRHIDevice& Dx12Device::Rhi() { return *m_rhi; }

ID3D12Device* Dx12Device::D3D12() const { return m_native->GetDevice(); }

Result<uz::RHIBufferHandle> Dx12Device::CreateBuffer(const uz::RHIBufferDesc& desc) {
    const uz::RHIBufferHandle buffer = m_rhi->CreateBuffer(desc);
    if (!buffer.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12,
                    "buffer of " + std::to_string(desc.sizeBytes) + " bytes not created");
    }
    return buffer;
}

void Dx12Device::DestroyBuffer(uz::RHIBufferHandle buffer) {
    if (buffer.IsValid()) m_rhi->DestroyBuffer(buffer);
}

Result<uz::RHITextureHandle> Dx12Device::CreateTexture(const uz::RHITextureDesc& desc) {
    const uz::RHITextureHandle texture = m_rhi->CreateTexture(desc);
    if (!texture.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12,
                    "texture " + std::to_string(desc.width) + "x" + std::to_string(desc.height) +
                        " not created");
    }
    return texture;
}

void Dx12Device::DestroyTexture(uz::RHITextureHandle texture) {
    if (texture.IsValid()) m_rhi->DestroyTexture(texture);
}

Result<ComputeKernel> Dx12Device::CreateComputeKernel(std::span<const uint8_t> bytecode,
                                                      const std::string& name) {
    uz::RHIShaderDesc shaderDesc;
    shaderDesc.bytecode = bytecode.data();
    shaderDesc.bytecodeSize = bytecode.size();
    shaderDesc.stage = uz::RHIShaderStage::Compute;
    shaderDesc.debugName = name.c_str();
    ComputeKernel kernel;
    kernel.shader = m_rhi->CreateShader(shaderDesc);
    if (!kernel.shader.IsValid()) {
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12,
                    "shader module of kernel '" + name + "' not created");
    }
    uz::RHIComputePipelineDesc pipelineDesc;
    pipelineDesc.computeShader = kernel.shader;
    pipelineDesc.debugName = name.c_str();
    kernel.pipeline = m_rhi->CreateComputePipeline(pipelineDesc);
    if (!kernel.pipeline.IsValid()) {
        m_rhi->DestroyShader(kernel.shader);
        return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12,
                    "compute pipeline of kernel '" + name + "' not created");
    }
    return kernel;
}

void Dx12Device::DestroyComputeKernel(const ComputeKernel& kernel) {
    if (kernel.pipeline.IsValid()) m_rhi->DestroyPipeline(kernel.pipeline);
    if (kernel.shader.IsValid()) m_rhi->DestroyShader(kernel.shader);
}

std::optional<Error> Dx12Device::CheckRemoved() const {
    const HRESULT reason = D3D12()->GetDeviceRemovedReason();
    if (reason == S_OK) return std::nullopt;
    return Error{ErrorCode::DeviceRemoved, Backend::Dx12,
                 DeviceRemovedReasonText(static_cast<int32_t>(reason))};
}

Error Dx12Device::WaitFailure(const WaitResult& wait) const {
    if (wait.status == WaitStatus::Timeout) {
        return Error{ErrorCode::Timeout, Backend::Dx12,
                     "the GPU did not complete the submitted work before the deadline"};
    }
    if (wait.backendReason != 0) {
        return Error{ErrorCode::DeviceRemoved, Backend::Dx12,
                     DeviceRemovedReasonText(wait.backendReason)};
    }
    // The fence wait itself failed while the device reports no removal reason.
    return Error{ErrorCode::DeviceRemoved, Backend::Dx12,
                 "the fence wait failed without a device-removed reason"};
}

// ── Dx12Queue ────────────────────────────────────────────────────────────────

Dx12Queue::Dx12Queue(uz::IRHIDevice& device, uz::IRHIFence* fence)
    : m_device(device), m_fence(fence) {}

Dx12Queue::~Dx12Queue() {
    for (const InFlight& entry : m_inFlight) m_device.DestroyCommandList(entry.list);
    for (uz::IRHICommandList* list : m_free) m_device.DestroyCommandList(list);
    m_device.DestroyFence(m_fence);
}

uint64_t Dx12Queue::Completed() const { return m_fence->GetCompletedValue(); }

void Dx12Queue::Retire() {
    const uint64_t completed = Completed();
    std::erase_if(m_inFlight, [&](const InFlight& entry) {
        if (entry.value > completed) return false;
        m_free.push_back(entry.list);
        return true;
    });
}

Result<uint64_t> Dx12Queue::Submit(const RecordFn& record) {
    Retire();
    uz::IRHICommandList* list = nullptr;
    if (!m_free.empty()) {
        list = m_free.back();
        m_free.pop_back();
    } else {
        list = m_device.CreateCommandList(uz::RHIQueueType::Graphics);
        if (!list) {
            return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12,
                        "command list not created");
        }
    }
    list->Begin();
    record(*list);
    list->End();
    list->Execute();
    ++m_lastSubmitted;
    m_fence->Signal(m_lastSubmitted);
    m_inFlight.push_back({list, m_lastSubmitted});
    return m_lastSubmitted;
}

WaitResult Dx12Queue::Wait(uint64_t value, Deadline deadline) {
    const uz::FenceWaitResult wait = m_fence->WaitCPU(value, deadline);
    switch (wait.status) {
        case uz::FenceWaitStatus::Signaled:   return {WaitStatus::Signaled, 0};
        case uz::FenceWaitStatus::Timeout:    return {WaitStatus::Timeout, 0};
        case uz::FenceWaitStatus::DeviceLost: return {WaitStatus::DeviceLost, wait.backendReason};
    }
    return {WaitStatus::DeviceLost, wait.backendReason};
}

}  // namespace uzp::render
