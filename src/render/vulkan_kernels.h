#pragma once

// The compute kernels that qualify a Vulkan device's dispatch and readback path bit for bit
// (phase3.1_vulkan-compute-parity items 2.8 and 3.8; decision 310), shared by the `selftest`
// Vulkan slice and the native tests. Each kernel has a CPU reference computing the same 32-bit
// value for texel (x, y):
//
//   pattern16  R16_SFLOAT: the 16-bit pattern of the DX12 hardware slice (selftest
//              hardware_slice.h), stored through `f16tof32`; every value is a finite half, so
//              the store is exact
//   hash32     R32_UINT: a 32-bit integer hash (multiplies, xors, shifts, a rotate, an add)
//   ieee32     R32_SFLOAT: x * 0.1f + y * 0.7f - (x ^ y) * 0.3f, compiled IEEE-strict (no
//              contraction, UZP-MOD-008); every operation is one correctly rounded IEEE
//              operation in Vulkan and on the CPU, and no operand or result is subnormal
//
// Each storage image declares its format (`[[vk::image_format]]`), so no `...WithoutFormat`
// feature is needed. These kernels qualify the device path only; they are not Painter outputs and
// are no parity evidence for any.

#include "render/backend.h"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace uzp::render {

class VulkanDevice;

struct VulkanQualificationKernel {
    const char* name;
    const char* source;            ///< HLSL, entry point `main`, 8x8x1 groups, b0 = {width, height}.
    uz::RHIFormat format;
    uint32_t bytesPerTexel;
    uint32_t spirvImageFormat;     ///< The `ImageFormat` its SPIR-V image type must declare.
    bool extendedFormat;           ///< Its format needs `StorageImageExtendedFormats`.
    bool ieeeStrict;
    uint32_t (*expected)(uint32_t x, uint32_t y);  ///< The CPU reference, as stored bits.
};

[[nodiscard]] const std::vector<VulkanQualificationKernel>& VulkanQualificationKernels();

/// SPIR-V of `kernel` compiled by DXC (`dxcompiler`, through the vendored `uz::ShaderCompiler`,
/// Vulkan 1.2 target), or `kernel_compile_failed`.
[[nodiscard]] Result<std::vector<uint8_t>> CompileVulkanKernel(const VulkanQualificationKernel& kernel,
                                                               const std::filesystem::path& dxcompiler);

/// SPIR-V `Capability` values the qualification checks: an R16f storage image needs
/// `StorageImageExtendedFormats` (feature `shaderStorageImageExtendedFormats`, required and
/// enabled); the `...WithoutFormat` ones (features the backend does not enable) must not appear.
inline constexpr uint32_t kSpirvCapabilityStorageImageExtendedFormats = 49;
inline constexpr uint32_t kSpirvCapabilityStorageImageReadWithoutFormat = 55;
inline constexpr uint32_t kSpirvCapabilityStorageImageWriteWithoutFormat = 56;
/// `SPV_KHR_float_controls`, which IEEE-strict SPIR-V declares (`-Gis`, UZP-MOD-008); the
/// qualification requires `shaderSignedZeroInfNanPreserveFloat32`.
inline constexpr uint32_t kSpirvCapabilitySignedZeroInfNanPreserve = 4466;
inline constexpr uint32_t kSpirvCapabilityShader = 1;

/// What a SPIR-V module declares: its capabilities, storage-image formats and `NoContraction`
/// decorations.
struct SpirvFacts {
    std::vector<uint32_t> capabilities;  ///< `OpCapability` operands, in module order.
    std::vector<uint32_t> imageFormats;  ///< `OpTypeImage` formats, in module order.
    uint32_t noContraction = 0;

    [[nodiscard]] bool HasCapability(uint32_t capability) const;
    /// The capabilities outside `Shader`, `StorageImageExtendedFormats` and
    /// `SignedZeroInfNanPreserve`, the ones a qualified device supports and enables.
    [[nodiscard]] std::vector<uint32_t> UnqualifiedCapabilities() const;
};
[[nodiscard]] SpirvFacts InspectSpirv(const std::vector<uint8_t>& spirv);

struct KernelReadback {
    uint32_t width = 0;
    uint32_t height = 0;
    uint64_t rowPitch = 0;
    uint64_t fenceValue = 0;
    std::vector<uint32_t> values;   ///< Read-back texels widened to 32 bits, row-major.
    size_t mismatches = 0;
    std::string firstMismatch;      ///< "(x, y): got 0x..., expected 0x..."; empty without one.
};

/// Dispatches `compiled` (made from `kernel`) over a `width` x `height` storage image, copies it to
/// a readback buffer at `ReadbackRowPitch(row, texel)`, waits for the fence with `deadline` and
/// compares every texel with the CPU reference. A failed wait returns the device's
/// `WaitFailure` and leaves the image and buffer to the failed device (never freed while the GPU
/// may use them).
[[nodiscard]] Result<KernelReadback> DispatchQualificationKernel(VulkanDevice& device,
                                                                 const VulkanQualificationKernel& kernel,
                                                                 const ComputeKernel& compiled, uint32_t width,
                                                                 uint32_t height, std::chrono::milliseconds deadline);

}  // namespace uzp::render
