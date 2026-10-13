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
// - Nearest: the texel (floor(x + 1/2), ceil(y + 1/2) - 1), the GPU's point sample of the bitmap
//   stored bottom-up: a tie between two rows takes the upper one (`srgb-bitmap-variants-v2` s3,
//   every texel of a scale-2 Nearest projection lies on a tie; decision 174); its code is the
//   sample (exact at every scale, resampling.json `resample-nearest`).
// - BilinearHQ and BilinearSharp: X = floor(256 x + 1/2), x0 = X >> 8, fx = X & 255 (same for y);
//   integer weights w11 = (fx fy + 127) >> 8, w10 = fx - w11, w01 = fy - w11,
//   w00 = 256 - fx - fy + w11 over the taps (x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1).
//   The sampled value is `BilinearFilter` of the weights and the texels' float32 values
//   float32(c / M) (M = 255 or 65535): the GPU's linear filter of a float32 texture (measured,
//   `uzp-evaluator-tests bilinear-hardware`), with the bitmap stored bottom-up, which turns the
//   GPU's w11 rounding (ties up) into ties down here (uv-sampling.json `uv-bilinear-repeat`).
//   That is magnification and 1:1 (a footprint of at most one texel).
// - Bilinear minification (a footprint above one texel) goes through the recording GPU's
//   anisotropic texture unit (texture_unit.h, decisions 060, 083, 084) on the bitmap's float32
//   mip chain stored bottom-up (`BitmapChain`), with Painter's arithmetic around it (decision
//   060), all for a square power-of-two bitmap on a square set and a rotation that is a multiple
//   of 90 degrees (other cases fail in `CheckSampling`):
//   - the UV in float32 (decisions 060, 084): the angle t = float32(r) float32(pi / 180), c =
//     float32(cos t), s = float32(sin t), the linear part S R in float32 products m00 = s_u c,
//     m01 = s_u s, m10 = -s_v s, m11 = s_v c, the translation in float32 operations m02 = (m00
//     t_u + m01 t_v) + 1/2 and m12 = (m10 t_u + m11 t_v) + 1/2 with t = (-1/2 - o_u, -1/2 - o_v);
//     u = float32((i + 1/2) / W), v = float32(1 - (j + 1/2) / H), u' = fma(m00, u, m01 v) + m02
//     and v' = fma(m10, u, m11 v) + m12 (fma one rounding);
//   - the gradients ddx = (m00, m10) / W and ddy = (m01, m11) / W (v counted upwards);
//   - BilinearSharp: one sample at LOD bias -1.5;
//   - BilinearHQ: dux, dvx, duy, dvy the fine derivatives of u' and v' in the 2 x 2 quad of
//     (i, j); nine samples at ((u' + DX dux) + DY duy, (v' + DX dvx) + DY dvy) with DX, DY in
//     {-1/3, 0, 1/3} (float32(1/3) times -1, 0, 1), gradients float32(1/3) ddx and float32(1/3)
//     ddy, LOD bias 0, summed in float32 as acc = acc + float32(w / 16) sample in the order centre
//     (4), (+, 0), (-, 0), (0, -), (0, +) (2 each), (+, -), (-, -), (-, +) (1 each) and the centre
//     again (1); C1 the level-0 bilinear sample at (u', v'); alpha = clamp(min(|(dux, dvx)|,
//     |(duy, dvy)|) w - 1, 0, 1) in float32 (w the bitmap width); the value fma(C1, 1 - alpha,
//     acc alpha).
//   The magnifying path keeps the double UV above: both give the same fixed-point coordinates on
//   every magnifying golden (decision 060).
// - Nearest samples float32(c / M) of the texel.
// - A float32 image (a decoded sRGB bitmap, sources.h) gives its stored values in place of
//   float32(c / M), through the same addressing and filters; it is never minified (`CheckSampling`).
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
#include "evaluator/texture_unit.h"
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
    /// The rotation in degrees (minification needs a multiple of 90).
    double rotation = 0.0;
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

/// Whether a bilinear projection of `image` minifies (a footprint above one texel): it then
/// samples through the texture unit.
[[nodiscard]] bool Minifies(const UvProjection& projection, uint32_t setWidth, uint32_t setHeight,
                            const DecodedImage& image);

/// Fails with `evaluator:unsupported_source` when the set resolution is not a power of two on
/// each axis (the texel centres are computed by exact power-of-two scaling) or when a bilinear
/// filter minifies outside the texture unit's measured domain: a rotation that is not a multiple
/// of 90 degrees, a bitmap that is not square with a power-of-two side, a non-square set, or
/// `signedRange` (the Height channel: Painter filters the signed heights, `ProjectTexel`, and its
/// minification of them is not measured), and for a float32 image (a decoded sRGB bitmap) that
/// a bilinear filter would minify.
[[nodiscard]] render::Result<void> CheckSampling(const UvProjection& projection,
                                                 uint32_t setWidth, uint32_t setHeight,
                                                 const DecodedImage& image, bool signedRange,
                                                 core::Id node);

/// One projected texel: whether it is covered and, per channel, the sampled value.
struct ProjectedTexel {
    bool covered = true;
    std::array<float, 3> value{0.0f, 0.0f, 0.0f};
};

/// Bits the bilinear filter keeps of each texel below the largest weighed texel's exponent.
inline constexpr int kFilterOperandBits = 28;

/// The GPU's linear filter of float32 texels with 8-bit weights (summing to 256): with E the binary
/// exponent of the largest texel magnitude of non-zero weight (|t|_max in [2^(E-1), 2^E)), each
/// texel t enters as the integer t 2^(28 - E) truncated toward zero (floor for t >= 0, the
/// measured range); the weighted sum of these integers, times 2^(E - 36), is rounded to the
/// nearest float32, ties away from zero (up for t >= 0). A texel weighed 256 comes back unchanged.
/// Signed texels are the Height channel's (height-to-normal.json `height-normal-resolution`:
/// exact on its magnified sets).
[[nodiscard]] float BilinearFilter(const std::array<uint32_t, 4>& weights,
                                   const std::array<float, 4>& texels);

/// The bitmap's float32 RGB mip chain for the texture unit: level 0 holds float32(c / M), rows
/// bottom up (the GPU's orientation); a grey bitmap feeds all three channels.
[[nodiscard]] tu::Chain BitmapChain(const DecodedImage& image);

/// Painter's float32 UV matrix (m00, m01, m02, m10, m11, m12) of a projection (decision 060).
[[nodiscard]] std::array<float, 6> PainterMatrix(const UvProjection& projection);

/// The texel (i, j) of the set (whole-set indices) projected from `image`; a grey bitmap feeds
/// all three channels, a colour bitmap its first three. With `signedRange` (the Height channel)
/// every bitmap texel is its signed value RangeValue(t, true) before the filter: Painter filters
/// the signed heights (height-to-normal.json `height-normal-resolution`; filtering t and then
/// taking 2 v - 1 leaves 16 values of the 512 set one half step off). `chain` is the bitmap's
/// `BitmapChain` when the projection minifies (`Minifies`), else null; `CheckSampling` refuses a
/// minifying projection with `signedRange`.
[[nodiscard]] ProjectedTexel ProjectTexel(const UvProjection& projection, const DecodedImage& image,
                                          uint32_t i, uint32_t j, uint32_t setWidth,
                                          uint32_t setHeight, bool signedRange = false,
                                          const tu::Chain* chain = nullptr);

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
    /// The Height channel: each bitmap texel t is sampled as float32(float32(2 t) - 1) (sources.h,
    /// ProjectTexel).
    bool signedRange = false;
};

/// The signed value of a bitmap texel `v` on the Height channel: 2 v - 1 in float32 (else `v`).
[[nodiscard]] float RangeValue(float v, bool signedRange);

}  // namespace uzp::evaluator
