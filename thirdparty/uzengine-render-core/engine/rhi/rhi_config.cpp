// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-002. Original: UzEngine runtime/engine/rhi/rhi_config.cpp at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

/// UzEngine RHI Configuration — Implementation
///
/// String conversion helpers and `ToDeviceDesc`. The backend is supplied by
/// the caller (UzPainter: `--gpu-backend`); there is no engine config,
/// `.uzproject` or CVar resolution in this copy.

#include "rhi_config.h"
#include "rhi.h"

#include <string>

namespace uz {

// ─────────────────────────────────────────────────────────────────────────────
// IRHIDevice::IsBindless — out-of-line to break circular include
// ─────────────────────────────────────────────────────────────────────────────

bool IRHIDevice::IsBindless() const {
    // Vulkan: descriptor indexing features are ENABLED at device creation,
    // but the command list does not yet implement ResourceDescriptorHeap-style
    // bindless (shaders use register-bound descriptors via -fvk-*-shift).
    // Return false until the SPIR-V shader path supports UZ_BINDLESS.
    if (GetBackend() == RHIBackend::Vulkan) {
        return false;
    }
    // Metal: argument buffers exist, but the engine's Metal shader path
    // (Slang → MSL) compiles the register-bound SM5 variants — never bindless.
    if (GetBackend() == RHIBackend::Metal) {
        return false;
    }
    // DX12: SM6.6+ enables ResourceDescriptorHeap bindless.
    // DX11: always false (no SM6.6 support).
    return GetShaderModel() >= ShaderModel::SM6_6;
}

// ─────────────────────────────────────────────────────────────────────────────
// String Conversion Helpers
// ─────────────────────────────────────────────────────────────────────────────

const char* RHIBackendToString(RHIBackend backend) {
    switch (backend) {
        case RHIBackend::DX12:   return "DX12";
        case RHIBackend::DX11:   return "DX11";
        case RHIBackend::Vulkan: return "Vulkan";
        case RHIBackend::Metal:  return "Metal";
        case RHIBackend::Null:   return "Null";
    }
    return "Unknown";
}

const char* ShaderModelToString(ShaderModel sm) {
    switch (sm) {
        case ShaderModel::SM5_0: return "SM5.0";
        case ShaderModel::SM5_1: return "SM5.1";
        case ShaderModel::SM6_0: return "SM6.0";
        case ShaderModel::SM6_1: return "SM6.1";
        case ShaderModel::SM6_2: return "SM6.2";
        case ShaderModel::SM6_3: return "SM6.3";
        case ShaderModel::SM6_4: return "SM6.4";
        case ShaderModel::SM6_5: return "SM6.5";
        case ShaderModel::SM6_6: return "SM6.6";
        case ShaderModel::SM6_7: return "SM6.7";
        case ShaderModel::SM6_8: return "SM6.8";
        case ShaderModel::SM6_9: return "SM6.9";
    }
    return "Unknown";
}

// ─────────────────────────────────────────────────────────────────────────────
// ToDeviceDesc
// ─────────────────────────────────────────────────────────────────────────────

RHIDeviceDesc ToDeviceDesc(const RHIConfig& config) {
    RHIDeviceDesc desc{};
    desc.backend = config.backend;
    desc.enableValidation = config.enableValidation;
    desc.enableGpuValidation = config.enableGpuValidation;
    desc.enableBreadcrumbs   = config.enableBreadcrumbs;
    desc.adapterIndex = config.adapterIndex;
    // Pass CLI shader model override to force device negotiation down.
    // Without this, --sm 6.0 is parsed but never forwarded to the device.
    desc.forceShaderModel = config.shaderModel;
    return desc;
}

} // namespace uz
