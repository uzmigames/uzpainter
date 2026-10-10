// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-001. Original: UzEngine runtime/engine/rhi/rhi_factory.cpp at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

/// Unified RHI Device Factory
///
/// Dispatches `CreateRHIDevice()` to the correct backend implementation
/// based on `RHIDeviceDesc::backend`. Returns `std::unique_ptr<IRHIDevice>`
/// for RAII-safe ownership transfer.
///
/// UzPainter builds DX12 and Vulkan only; any other backend is rejected
/// with an explicit error.

#include "rhi_backend.h"
#include "rhi_config.h"
#include "log.h"

#include <memory>

// Include backend device headers (Windows-only backends)
#ifdef _WIN32
#include "dx12/dx12_device.h"
#endif

// Vulkan backend (cross-platform — Windows and Linux)
#include "vulkan/vulkan_device.h"

namespace uz {

namespace {
    RHIBackend g_activeBackend = RHIBackend::DX12;
    ShaderModel g_activeShaderModel = ShaderModel::SM5_0;
} // namespace

RHIBackend GetActiveRHIBackend() { return g_activeBackend; }
ShaderModel GetActiveShaderModel() { return g_activeShaderModel; }

std::unique_ptr<IRHIDevice> CreateRHIDevice(const RHIDeviceDesc& desc) {
    switch (desc.backend) {
#ifdef _WIN32
        case RHIBackend::DX12: {
            auto device = std::make_unique<DX12Device>();
            if (!device->Init(desc)) {
                UZ_LOG(RHI, Error, "CreateRHIDevice: DX12Device::Init failed");
                return nullptr;
            }
            g_activeBackend = desc.backend;
            g_activeShaderModel = device->GetShaderModel();
            return device;
        }
#endif

        case RHIBackend::Vulkan: {
            auto device = std::make_unique<VulkanDevice>();
            if (!device->Init(desc)) {
                UZ_LOG(RHI, Error, "CreateRHIDevice: VulkanDevice::Init failed");
                return nullptr;
            }
            g_activeBackend = desc.backend;
            g_activeShaderModel = device->GetShaderModel();
            return device;
        }

        default:
            UZ_LOG(RHI, Error, "CreateRHIDevice: backend {} is not supported (DX12 and Vulkan only)",
                   RHIBackendToString(desc.backend));
            return nullptr;
    }
}

} // namespace uz
