#pragma once

// Generated compositor kernels (docs/architecture/04-layer-stack-and-compositing.md §7): one
// blend kernel per (blend mode, channel tile format), HLSL specialised through defines and
// compiled through the render layer's kernel cache (IEEE-strict, DXIL and SPIR-V). The kernel
// body is shaders/evaluator_blend.hlsl; it mirrors arith.cpp operation for operation and reads
// its per-dispatch parameters from a block of `kBlendParamsStride` uints in a structured buffer
// (the parameter arena of gpu_store.h), indexed by two root constants. 32-bit float results
// are stored as they are: the channel's re-composition over its base is a read-out step
// (evaluate.h), not a store.

#include "evaluator/formats.h"
#include "evaluator/tile_store.h"
#include "render/kernel_cache.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "uzp_core/types/enums.h"

namespace uzp::evaluator {

struct BlendKernelVariant {
    core::BlendingMode mode = core::BlendingMode::Normal;
    /// The destination (and backdrop) tile format; `alpha` selects the coverage plane.
    TileFormat format;
    /// A raw blend (BlendOp::rawOutput): `format` is the operands' format (without `alpha`) and
    /// the destination a 32-bit float tile written as it is (`UZP_RAW_OUTPUT`).
    bool rawOutput = false;
};

/// The HLSL of the variant: `evaluator_blend.hlsl` with the defines `UZP_MODE_<Mode>`,
/// `UZP_ENC`, `UZP_CHANNELS`, `UZP_SRGB`, `UZP_ALPHA`, `UZP_HALF_COVERAGE` (the coverage plane
/// written through binary16, `TileFormat::halfCoverage`) and `UZP_RAW_OUTPUT`, including the render layer's
/// `image_common.hlsli` and the generated `evaluator_tables.hlsli`.
[[nodiscard]] render::KernelSource BlendKernelSource(const BlendKernelVariant& variant);

/// `evaluator_tables.hlsli`: the sRGB8 operand table, the sRGB8 store thresholds (doubles as
/// uint pairs), the 8-bit UNORM operand table and the float32 constants of the colour kernels,
/// generated from arith.h, and the offsets of the operand tables buffer (`UZP_TABLE_*`).
[[nodiscard]] render::KernelInclude TablesInclude();

/// Offsets (in uints) of the operand tables buffer the blend kernels read: the 16-bit UNORM
/// operands (`arith::Unorm16OperandTable`, float bits) and the packed delta words of the hardware
/// reciprocal, square root and reciprocal square root (`hw::Words`).
inline constexpr uint32_t kTableUnorm16 = 0;
inline constexpr uint32_t kTableRcp = kTableUnorm16 + 65536;
inline constexpr uint32_t kTableSqrt = kTableRcp + (1u << 23) / 16;
inline constexpr uint32_t kTableRsqrt = kTableSqrt + (1u << 24) / 16;
inline constexpr uint32_t kTableWords = kTableRsqrt + (1u << 24) / 16;

/// The operand tables buffer: `kTableWords` uints at the offsets above (built once).
[[nodiscard]] const std::vector<uint32_t>& OperandTableWords();

/// Offsets (in uints) of the function tables buffer the Levels kernel and the normal-map blend
/// kernels read (`hw::Values` of `Log2Hi`, `Log2Lo`, `Exp2Pos`, `Exp2Neg`, `Sin`, `Cos`, 2^23
/// words each; 192 MiB, created on first use).
inline constexpr uint32_t kPowLog2Hi = 0;
inline constexpr uint32_t kPowLog2Lo = kPowLog2Hi + (1u << 23);
inline constexpr uint32_t kPowExp2Pos = kPowLog2Lo + (1u << 23);
inline constexpr uint32_t kPowExp2Neg = kPowExp2Pos + (1u << 23);
inline constexpr uint32_t kPowSin = kPowExp2Neg + (1u << 23);
inline constexpr uint32_t kPowCos = kPowSin + (1u << 23);
inline constexpr uint32_t kPowWords = kPowCos + (1u << 23);

/// Uints per parameter block.
inline constexpr uint32_t kBlendParamsStride = 32;

/// Bits of the parameter block's flags word.
enum BlendFlags : uint32_t {
    kFlagAccIsTile = 1,
    kFlagSrcIsTile = 2,
    kFlagMaskIsTile = 4,
    kFlagAccAlpha = 8,
    kFlagSrcAlpha = 16,
    kFlagEffectMix = 32,  ///< The effect mix (BlendOp::effectMix).
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
    kParamDstUav = 16,
    kParamTable16Srv = 17,  ///< The operand tables buffer (`OperandTableWords`).
    kParamMaskEncoding = 18,
    kParamPowSrv = 19,  ///< The function tables buffer (normal-map modes; `kPowWords`).
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
    uint32_t powSrv = 0;
};

/// The parameter block of `op` with the descriptor indices of `bindings`.
[[nodiscard]] std::array<uint32_t, kBlendParamsStride> EncodeBlendParams(
    const BlendOp& op, const BlendBindings& bindings);

// ── Levels (tile_store.h LevelsOp) ───────────────────────────────────────────

/// The HLSL of the Levels kernel over tiles of `format` (`evaluator_blend.hlsl` with
/// `UZP_LEVELS`). Its parameter blocks share the arena and stride of the blend kernels.
[[nodiscard]] render::KernelSource LevelsKernelSource(const TileFormat& format);

struct LevelsBindings {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t srcSrv = 0;
    uint32_t dstUav = 0;
    uint32_t table16Srv = 0;
    uint32_t powSrv = 0;
    bool srcAlpha = false;
};

/// The parameter block of `op` with the descriptor indices of `bindings`.
[[nodiscard]] std::array<uint32_t, kBlendParamsStride> EncodeLevelsParams(
    const LevelsOp& op, const LevelsBindings& bindings);

// ── UV projection (projection_uv.h) ──────────────────────────────────────────

/// The HLSL of the projection kernel into tiles of `format` (`shaders/evaluator_project.hlsl`
/// with `UZP_ENC`, `UZP_CHANNELS`, `UZP_SRGB` and `UZP_ALPHA`). Its parameter blocks share the
/// arena and stride of the blend kernels.
[[nodiscard]] render::KernelSource ProjectKernelSource(const TileFormat& format);

struct ProjectBindings {
    uint32_t width = 0;   ///< The tile.
    uint32_t height = 0;
    uint32_t dstUav = 0;
    uint32_t imageSrv = 0;  ///< The packed bitmap codes (`PackBitmapCodes`).
};

/// The parameter block of `op` with the descriptor indices of `bindings`.
[[nodiscard]] std::array<uint32_t, kBlendParamsStride> EncodeProjectParams(
    const ProjectOp& op, const ProjectBindings& bindings);

// ── Virtual normal maps (height_to_normal.h, tile_store.h VirtualNormalOp) ────

/// The HLSL of the virtual normal kernel (`evaluator_blend.hlsl` with `UZP_VNORMAL`): 32-bit float
/// height and Normal-channel read-outs in, the encoded normal out (raw 32-bit float). Its
/// parameter blocks share the arena and stride of the blend kernels.
[[nodiscard]] render::KernelSource VirtualNormalKernelSource();

struct VirtualNormalBindings {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t dstUav = 0;
    uint32_t table16Srv = 0;
    /// The SRVs of the nine height tiles (all 0 when the height is constant).
    std::array<uint32_t, 9> heightSrv{};
    /// The SRV of the Normal channel's read-out tile (0 when it is a constant).
    uint32_t normalSrv = 0;
};

/// The parameter block of `op` with the descriptor indices of `bindings`.
[[nodiscard]] std::array<uint32_t, kBlendParamsStride> EncodeVirtualNormalParams(
    const VirtualNormalOp& op, const VirtualNormalBindings& bindings);

/// The codes of `image` in sample order, packed for the projection kernel: two 16-bit codes or
/// four 8-bit codes per uint, low bits first.
[[nodiscard]] std::vector<uint32_t> PackBitmapCodes(const DecodedImage& image);

}  // namespace uzp::evaluator
