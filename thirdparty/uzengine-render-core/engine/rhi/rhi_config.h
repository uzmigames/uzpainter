// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-002. Original: UzEngine runtime/engine/rhi/rhi_config.h at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

#pragma once

/// UzEngine RHI Configuration
///
/// The RHI configuration value type and its conversion to a device
/// descriptor. The caller supplies the backend (UzPainter: `--gpu-backend`).

#include "rhi_backend.h"

#include <cstdint>
#include <string>

namespace uz {

/// Shader model levels supported by the engine.
///
/// Ordered from lowest to highest capability. The engine negotiates the highest
/// shader model the GPU supports at device creation time.
/// SM6.6 is the preferred baseline — it enables bindless resource access.
enum class ShaderModel : uint8_t {
    SM5_0,   ///< DirectX 11 baseline (absolute minimum).
    SM5_1,   ///< DirectX 11.3+ (dynamic indexing, space-qualified registers).
    SM6_0,   ///< DirectX 12 baseline (wave intrinsics, 64-bit integers).
    SM6_1,   ///< Barycentric intrinsics, `SV_ViewID` for VR.
    SM6_2,   ///< Native float16 (`half`), denorm mode control.
    SM6_3,   ///< DirectX Raytracing 1.0 (DXR), `TraceRay` intrinsic.
    SM6_4,   ///< Variable rate shading (VRS), low-precision packed dot product.
    SM6_5,   ///< DXR 1.1, mesh shaders, sampler feedback.
    SM6_6,   ///< DirectX 12 Ultimate — bindless (`ResourceDescriptorHeap[]`), dynamic resources.
    SM6_7,   ///< Advanced texture ops, relaxed precision, quad-wide shuffle.
    SM6_8,   ///< Work graphs, wave size range, expanded comparison samplers.
    SM6_9,   ///< Cooperative vectors, inline ray tracing in compute, extended atomics.
};

/// Resolved RHI configuration from all sources.
///
/// Filled by the caller, consumed by `ToDeviceDesc()` for device creation.
/// All fields have safe defaults matching the highest-capability path (DX12 + SM6.6).
///
/// # Lifetime
/// Transient value type — created once during startup and passed to device creation.
/// Not stored long-term; the device remembers its own backend and shader model.
struct RHIConfig {
    RHIBackend backend = RHIBackend::DX12;           ///< GPU API backend to initialize.
    std::optional<ShaderModel> shaderModel;          ///< Force shader model (nullopt = auto-negotiate highest).
    bool enableValidation = false;                   ///< Enable API validation layer (DX12 debug, Vulkan VK_LAYER_KHRONOS_validation).
    bool enableGpuValidation = false;                ///< Enable GPU-based validation (DX12 only; expensive, catches shader errors).
    bool enableBreadcrumbs = false;                  ///< Enable DRED auto-breadcrumbs for device-removed diagnosis (DX12 only).
    uint32_t adapterIndex = 0;                       ///< GPU adapter index (0 = system default / high-performance preference).
};

/// Converts RHIBackend enum to display string.
[[nodiscard]] const char* RHIBackendToString(RHIBackend backend);

/// Converts ShaderModel enum to display string.
[[nodiscard]] const char* ShaderModelToString(ShaderModel sm);

/// Converts a RHIConfig into a RHIDeviceDesc for device creation.
[[nodiscard]] RHIDeviceDesc ToDeviceDesc(const RHIConfig& config);

} // namespace uz
