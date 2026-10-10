#pragma once

// Generated compositor kernels (docs/architecture/04-layer-stack-and-compositing.md §7): one
// blend kernel per (blend mode, channel tile format), HLSL specialised through defines and
// compiled through the render layer's kernel cache (IEEE-strict, DXIL and SPIR-V). The kernel
// body is shaders/evaluator_blend.hlsl; it mirrors arith.cpp operation for operation and reads
// its per-dispatch parameters from a block of `kBlendParamsStride` uints in a structured buffer
// (the parameter arena of gpu_store.h), indexed by two root constants.

#include "evaluator/formats.h"
#include "evaluator/tile_store.h"
#include "render/kernel_cache.h"

#include <array>
#include <cstdint>
#include <string>

#include "uzp_core/types/enums.h"

namespace uzp::evaluator {

struct BlendKernelVariant {
    core::BlendingMode mode = core::BlendingMode::Normal;
    /// The destination (and backdrop) tile format; `alpha` selects the coverage plane.
    TileFormat format;
};

/// The HLSL of the variant: `evaluator_blend.hlsl` with the defines `UZP_MODE_<Mode>`,
/// `UZP_ENC`, `UZP_CHANNELS`, `UZP_SRGB` and `UZP_ALPHA`, including the render layer's
/// `image_common.hlsli` and the generated `evaluator_tables.hlsli`.
[[nodiscard]] render::KernelSource BlendKernelSource(const BlendKernelVariant& variant);

/// `evaluator_tables.hlsli`: the sRGB8 operand table, the sRGB8 decode thresholds (doubles as
/// uint pairs) and the 8-bit UNORM operand table, generated from arith.h.
[[nodiscard]] render::KernelInclude TablesInclude();

/// Uints per parameter block.
inline constexpr uint32_t kBlendParamsStride = 32;

/// Bits of the parameter block's flags word.
enum BlendFlags : uint32_t {
    kFlagAccIsTile = 1,
    kFlagSrcIsTile = 2,
    kFlagMaskIsTile = 4,
    kFlagAccAlpha = 8,
    kFlagSrcAlpha = 16,
};

/// Offsets inside a parameter block.
enum BlendParam : uint32_t {
    kParamWidth = 0,
    kParamHeight = 1,
    kParamFlags = 2,
    kParamAccIndex = 3,
    kParamAccConst = 4,   ///< 4 floats (rgb, alpha).
    kParamSrcIndex = 8,
    kParamSrcConst = 9,   ///< 4 floats.
    kParamMaskIndex = 13,
    kParamMaskConst = 14,
    kParamOpacity = 15,
    kParamStoreBase = 16,  ///< 3 floats.
    kParamDstUav = 19,
    kParamTable16Srv = 20,
    kParamMaskEncoding = 21,
};

struct BlendBindings {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t accSrv = 0;
    bool accAlpha = false;
    uint32_t srcSrv = 0;
    bool srcAlpha = false;
    uint32_t maskSrv = 0;
    render::TexelEncoding maskEncoding = render::TexelEncoding::Unorm16;
    uint32_t dstUav = 0;
    uint32_t table16Srv = 0;
};

/// The parameter block of `op` with the descriptor indices of `bindings`.
[[nodiscard]] std::array<uint32_t, kBlendParamsStride> EncodeBlendParams(
    const BlendOp& op, const BlendBindings& bindings);

}  // namespace uzp::evaluator
