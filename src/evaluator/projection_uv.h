#pragma once

// The `Fill` and `UV` projections of a bitmap source (docs/architecture/04-layer-stack-and-
// compositing.md §4, §5; parity/semantics/uv-sampling.json, fitted on the Tier 0 golden
// `resample-uv`): the documented `UVProjectionParams` transform, the `Nearest`, `BilinearHQ`
// and `BilinearSharp` filters in fixed point, and the four `UVWrapMode`s, evaluated per texel
// on the CPU (this file, the reference) and in the GPU kernel `shaders/evaluator_project.hlsl`
// (gpu_store.h), which mirrors it operation for operation.
//
// Output texel (i, j) of a W x H texture set (row 0 on top, i and j counted over the whole set)
// samples at u = (i + 1/2) / W, v = 1 - (j + 1/2) / H. The offset moves the point before the
// scale and the rotation about the UV centre: (a, b) = ((u - 1/2 - o_u) s_u, (v - 1/2 - o_v) s_v),
// u' = (cos r a + sin r b) + 1/2 and v' = (-sin r a + cos r b) + 1/2 (r the rotation in degrees),
// all in double precision in this order (decision 056: `resample-uv-minify` user 7 and
// `resample-uv-impulse` users 6-7 combine an offset with a scale). Bitmap texel coordinates
// (row 0 on top, centres at integers): x = u' w - 1/2, y = (1 - v') h - 1/2 for a w x h bitmap.
//
// - Nearest: the texel (floor(x + 1/2), floor(y + 1/2)); its code is the sample (exact at every
//   scale, resampling.json `resample-nearest`).
// - BilinearHQ and BilinearSharp: X = floor(256 x + 1/2), x0 = X >> 8, fx = X & 255 (same for y);
//   integer weights w11 = (fx fy + 127) >> 8, w10 = fx - w11, w01 = fy - w11,
//   w00 = 256 - fx - fy + w11 over the taps (x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1).
//   The sampled value is `BilinearFilter` of the weights and the texels' float32 values
//   float32(c / M) (M = 255 or 65535): the GPU's linear filter of a float32 texture (measured,
//   `uzp-evaluator-tests bilinear-hardware`), with the bitmap stored bottom-up, which turns the
//   GPU's w11 rounding (ties up) into ties down here (uv-sampling.json `uv-bilinear-repeat`).
//   Both filters are single-level bilinear: magnification and 1:1 only (minification is a
//   release gap, `CheckSampling`).
// - Nearest samples float32(c / M) of the texel.
//
// The channel stores the sampled value with its own write rule (cpu_store.h `StoreValue`): at
// 1:1 a bitmap is copied exactly. Wrap modes: `Repeat` takes tap
// indices modulo the bitmap size; `RepeatNone` clamps them to the bitmap and leaves the texels
// whose u' or v' lies outside [0, 1) uncovered (the fill keeps the value below there: the
// projected tile carries a coverage plane); `RepeatHorizontally` and `RepeatVertically` repeat
// along u or v only and treat the other axis as `RepeatNone`.
//
// `Fill` projection: the identity transform with `Repeat` (the bitmap matched to the UV tile),
// with the fill's filter.

#include "evaluator/formats.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <array>
#include <cstdint>
#include <memory>
#include <string>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"

namespace uzp::evaluator {

/// The resolved parameters of one UV projection.
struct UvProjection {
    core::FilteringMode filter = core::FilteringMode::BilinearHQ;
    core::UVWrapMode wrap = core::UVWrapMode::Repeat;
    double cosR = 1.0;
    double sinR = 0.0;
    std::array<double, 2> scale{1.0, 1.0};
    std::array<double, 2> offset{0.0, 0.0};

    /// Wrap modes that leave texels uncovered (the projected tile needs a coverage plane).
    [[nodiscard]] bool MayUncover() const { return wrap != core::UVWrapMode::Repeat; }

    friend bool operator==(const UvProjection&, const UvProjection&) = default;
};

/// The projection of a fill's `projection` (modes `Fill` and `UV`). Fails with
/// `evaluator:unsupported_source` for the physical-size scale modes (their unit rule needs the
/// mesh, 12 §3) and for other projection modes.
[[nodiscard]] render::Result<UvProjection> UvProjectionOf(const core::Projection& projection,
                                                          core::Id node);

/// Bitmap texels per output texel: the larger singular value of the Jacobian of (x, y) over
/// (i, j) for a `bitmapWidth` x `bitmapHeight` bitmap on a `setWidth` x `setHeight` set.
[[nodiscard]] double Footprint(const UvProjection& projection, uint32_t setWidth,
                               uint32_t setHeight, uint32_t bitmapWidth, uint32_t bitmapHeight);

/// Fails with `evaluator:unsupported_source` when the set resolution is not a power of two on
/// each axis (the texel centres are computed by exact power-of-two scaling) or when a bilinear
/// filter minifies (a footprint above one texel: Painter samples it with the GPU's anisotropic
/// texture unit, not modelled bit for bit, decision 056).
[[nodiscard]] render::Result<void> CheckSampling(const UvProjection& projection,
                                                 uint32_t setWidth, uint32_t setHeight,
                                                 const DecodedImage& image, core::Id node);

/// One projected texel: whether it is covered and, per channel, the sampled value.
struct ProjectedTexel {
    bool covered = true;
    std::array<float, 3> value{0.0f, 0.0f, 0.0f};
};

/// Bits the bilinear filter keeps of each texel below the largest weighed texel's exponent.
inline constexpr int kFilterOperandBits = 28;

/// The GPU's linear filter of float32 texels in [0, 1] with 8-bit weights (summing to 256): with
/// E the binary exponent of the largest texel of non-zero weight (t_max in [2^(E-1), 2^E)), each
/// texel t enters as the integer floor(t 2^(28 - E)); the weighted sum of these integers, times
/// 2^(E - 36), is rounded to the nearest float32, ties up. A texel weighed 256 comes back
/// unchanged.
[[nodiscard]] float BilinearFilter(const std::array<uint32_t, 4>& weights,
                                   const std::array<float, 4>& texels);

/// The texel (i, j) of the set (whole-set indices) projected from `image`; a grey bitmap feeds
/// all three channels, a colour bitmap its first three.
[[nodiscard]] ProjectedTexel ProjectTexel(const UvProjection& projection, const DecodedImage& image,
                                          uint32_t i, uint32_t j, uint32_t setWidth,
                                          uint32_t setHeight);

/// The full description of a projection operation on a tile store.
struct ProjectOp {
    TileHandle dst = kNoTile;
    /// The bitmap and the key of its decoded samples (the resource hash).
    std::shared_ptr<const DecodedImage> image;
    std::string imageKey;
    UvProjection projection;
    /// The set resolution and the tile's origin in it.
    uint32_t setWidth = 0;
    uint32_t setHeight = 0;
    uint32_t x0 = 0;
    uint32_t y0 = 0;
    /// The Height channel: the sampled value v is stored as float32(float32(2 v) - 1) (sources.h).
    bool signedRange = false;
};

/// The value a projection stores before the channel's write rule: `v`, or 2 v - 1 in float32
/// on the Height channel.
[[nodiscard]] float RangeValue(float v, bool signedRange);

}  // namespace uzp::evaluator
