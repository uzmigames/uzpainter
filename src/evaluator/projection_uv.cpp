#include "evaluator/projection_uv.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

constexpr int64_t kSubtexel = 256;  // 8-bit sub-texel fixed point
constexpr int kSharpBias = -384;     // BilinearSharp's LOD bias, -1.5 in 1/256

/// BilinearHQ's nine samples in summation order: offsets in thirds of the fine derivatives and
/// weights in sixteenths; the last step reads the centre again (decision 060).
struct HqStep {
    int dx;
    int dy;
    int weight;
};
constexpr std::array<HqStep, 9> kHqOrder{{{0, 0, 4}, {1, 0, 2}, {-1, 0, 2}, {0, -1, 2}, {0, 1, 2},
                                          {1, -1, 1}, {-1, -1, 1}, {-1, 1, 1}, {0, 0, 1}}};

int64_t Address(int64_t index, uint32_t extent, bool repeat) {
    const int64_t n = extent;
    if (repeat) return ((index % n) + n) % n;
    return index < 0 ? 0 : (index >= n ? n - 1 : index);
}

bool IsPowerOfTwo(uint32_t value) { return value != 0 && (value & (value - 1)) == 0; }

/// The channel `c` code of bitmap texel (x, y): a grey bitmap feeds every channel.
uint32_t Code(const DecodedImage& image, int64_t x, int64_t y, uint32_t c) {
    const uint32_t channel = image.channels == 1 ? 0 : c;
    return image.At(static_cast<uint32_t>(x), static_cast<uint32_t>(y), channel);
}

/// The channel `c` value of bitmap texel (x, y): float32(c / M) of a code, or the stored value
/// of a float32 image (a decoded sRGB bitmap, sources.h) or of an R16F image (decision 218).
float TexelValue(const DecodedImage& image, int64_t x, int64_t y, uint32_t c) {
    const uint32_t code = Code(image, x, y, c);
    switch (image.encoding) {
        case render::TexelEncoding::Float32:
        case render::TexelEncoding::Float16: return std::bit_cast<float>(code);
        case render::TexelEncoding::Unorm16: return arith::UnormOperand(code, 16);
        default: return arith::UnormOperand(code, 8);
    }
}

}  // namespace

render::Result<UvProjection> UvProjectionOf(const core::Projection& projection, core::Id node) {
    UvProjection result;
    result.filter = projection.uv.filtering_mode;
    if (projection.mode == core::ProjectionMode::Fill) {
        result.wrap = core::UVWrapMode::Repeat;
        return result;
    }
    if (projection.mode != core::ProjectionMode::UV) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        std::string(core::ToString(projection.mode)) +
                            " projection is outside this profile (P3-SMART / P4-NODES)",
                        node);
    }
    const core::UVTransformation& transform = projection.uv.uv_transformation;
    if (transform.scale_mode != core::ScaleMode::Factors) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        std::string(core::ToString(transform.scale_mode)) +
                            " UV scale mode is a release gap (its unit rule needs the mesh, "
                            "12-mesh-import.md section 3)",
                        node);
    }
    result.wrap = projection.uv.uv_wrapping_mode;
    const double radians = transform.rotation * (std::numbers::pi / 180.0);
    result.cosR = std::cos(radians);
    result.sinR = std::sin(radians);
    result.rotation = transform.rotation;
    result.scale = transform.scale;
    result.offset = transform.offset;
    return result;
}

double Footprint(const UvProjection& projection, uint32_t setWidth, uint32_t setHeight,
                 uint32_t bitmapWidth, uint32_t bitmapHeight) {
    const double su = projection.scale[0] / setWidth;
    const double sv = projection.scale[1] / setHeight;
    const double a = bitmapWidth * projection.cosR * su;
    const double b = -(bitmapWidth * projection.sinR * sv);
    const double c = bitmapHeight * projection.sinR * su;
    const double d = bitmapHeight * projection.cosR * sv;
    const double trace = a * a + b * b + c * c + d * d;
    const double det = a * d - b * c;
    const double disc = std::sqrt(std::fmax(trace * trace - 4.0 * det * det, 0.0));
    return std::sqrt((trace + disc) / 2.0);
}

render::Result<void> CheckSampling(const UvProjection& projection, uint32_t setWidth,
                                   uint32_t setHeight, const DecodedImage& image, bool signedRange,
                                   core::Id node) {
    if (!IsPowerOfTwo(setWidth) || !IsPowerOfTwo(setHeight)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "UV projection needs a power-of-two texture set resolution (" +
                            std::to_string(setWidth) + "x" + std::to_string(setHeight) + ")",
                        node);
    }
    if (image.width == 0 || image.height == 0 || image.channels == 0) {
        return EvalFail(EvalErrorKind::UnsupportedSource, "an empty bitmap", node);
    }
    if (image.encoding == render::TexelEncoding::Float16 ||
        (image.encoding == render::TexelEncoding::Float32 && Minifies(projection, setWidth, setHeight, image))) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "bitmap sources are 8- or 16-bit images (a float32 bitmap is not minified)", node);
    }
    if (Minifies(projection, setWidth, setHeight, image)) {
        const std::string what = std::string(core::ToString(projection.filter)) + " minification (" +
                                 std::to_string(Footprint(projection, setWidth, setHeight, image.width,
                                                          image.height)) +
                                 " bitmap texels per texel)";
        if (std::fmod(projection.rotation, 90.0) != 0.0) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            what + " at a rotation of " + std::to_string(projection.rotation) +
                                " degrees is a release gap: the texture unit's rotated footprints are "
                                "not modelled (decisions 061, 084)",
                            node);
        }
        if (image.width != image.height || !IsPowerOfTwo(image.width) || setWidth != setHeight ||
            (projection.wrap != core::UVWrapMode::Repeat && projection.wrap != core::UVWrapMode::RepeatNone)) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            what + " needs a square power-of-two bitmap, a square set and Repeat or "
                                   "RepeatNone: the mip chain, the gradients and the addressing are "
                                   "measured there only (decision 084)",
                            node);
        }
        if (signedRange) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            what + " on the Height channel is a release gap: Painter filters the "
                                   "signed heights and their minification is not measured",
                            node);
        }
    }
    return {};
}

bool Minifies(const UvProjection& projection, uint32_t setWidth, uint32_t setHeight,
              const DecodedImage& image) {
    return projection.filter != core::FilteringMode::Nearest &&
           Footprint(projection, setWidth, setHeight, image.width, image.height) > 1.0 + 1e-9;
}

tu::Chain BitmapChain(const DecodedImage& image) {
    if (image.srgb8) {
        // The codes behind the decodes.
        std::vector<uint8_t> codes(size_t{image.width} * image.height * 3);
        for (uint32_t row = 0; row < image.height; ++row) {
            const uint32_t y = image.height - 1 - row;  // the GPU's rows go bottom up
            for (uint32_t x = 0; x < image.width; ++x) {
                for (uint32_t c = 0; c < 3; ++c) {
                    codes[(size_t{row} * image.width + x) * 3 + c] =
                        static_cast<uint8_t>(Srgb8Code(TexelValue(image, x, y, c)));
                }
            }
        }
        return tu::BuildSrgb8Chain(image.width, std::move(codes));
    }
    std::vector<float> level0(size_t{image.width} * image.height * 3);
    for (uint32_t row = 0; row < image.height; ++row) {
        const uint32_t y = image.height - 1 - row;  // the GPU's rows go bottom up
        for (uint32_t x = 0; x < image.width; ++x) {
            for (uint32_t c = 0; c < 3; ++c) {
                level0[(size_t{row} * image.width + x) * 3 + c] = TexelValue(image, x, y, c);
            }
        }
    }
    return tu::BuildChain(image.width, std::move(level0));
}

bool ReadsMipLevels(const UvProjection& projection, uint32_t setWidth, uint32_t setHeight,
                    const DecodedImage& image) {
    if (!Minifies(projection, setWidth, setHeight, image)) return false;
    const std::array<float, 6> m = PainterMatrix(projection);
    const float texel = static_cast<float>(1.0 / setWidth);
    std::array<float, 2> ddx{m[0] * texel, m[3] * texel};
    std::array<float, 2> ddy{m[1] * texel, m[4] * texel};
    int bias = kSharpBias;
    if (projection.filter != core::FilteringMode::BilinearSharp) {
        const float third = static_cast<float>(1.0 / 3.0);
        ddx = {third * ddx[0], third * ddx[1]};
        ddy = {third * ddy[0], third * ddy[1]};
        bias = 0;
    }
    const uint32_t levels = static_cast<uint32_t>(std::countr_zero(image.width)) + 1u;
    const tu::Footprint fp = tu::Resolve(ddx, ddy, image.width, levels, bias);
    return !fp.magnify && fp.biased > 0;
}

std::array<float, 6> PainterMatrix(const UvProjection& p) {
    // The rotation in float32: the angle float32(degrees) float32(pi / 180), its cosine and sine
    // rounded to float32; the linear part S R in float32 products (decision 084).
    const float theta = static_cast<float>(p.rotation) * static_cast<float>(std::numbers::pi / 180.0);
    const float c = static_cast<float>(std::cos(static_cast<double>(theta)));
    const float s = static_cast<float>(std::sin(static_cast<double>(theta)));
    const float su = static_cast<float>(p.scale[0]);
    const float sv = static_cast<float>(p.scale[1]);
    const float m00 = su * c;
    const float m01 = su * s;
    const float m10 = -sv * s;
    const float m11 = sv * c;
    // The translation S R (-1/2 - o) + 1/2 in float32 operations.
    const float tx = -0.5f - static_cast<float>(p.offset[0]);
    const float ty = -0.5f - static_cast<float>(p.offset[1]);
    const float m02 = (m00 * tx + m01 * ty) + 0.5f;
    const float m12 = (m10 * tx + m11 * ty) + 0.5f;
    return {m00, m01, m02, m10, m11, m12};
}

float BilinearFilter(const std::array<uint32_t, 4>& weights, const std::array<float, 4>& texels) {
    float largest = 0.0f;
    for (size_t k = 0; k < 4; ++k) {
        if (weights[k] != 0) largest = std::fmax(largest, std::fabs(texels[k]));
    }
    if (largest == 0.0f) return 0.0f;
    int exponent = 0;
    (void)std::frexp(largest, &exponent);
    // Each operand's magnitude is below 2^28 + 1 and exact in double before the conversion, which
    // truncates toward zero; the sum's magnitude is below 2^37.
    int64_t sum = 0;
    for (size_t k = 0; k < 4; ++k) {
        const double scaled = std::ldexp(static_cast<double>(texels[k]), kFilterOperandBits - exponent);
        sum += static_cast<int64_t>(weights[k]) * static_cast<int64_t>(scaled);
    }
    // Round the magnitude to 24 significant bits, ties away from zero, and scale it by 2^(E - 36).
    const bool negative = sum < 0;
    const uint64_t magnitude = static_cast<uint64_t>(negative ? -sum : sum);
    int shift = 0;
    while ((magnitude >> shift) >= (uint64_t{1} << 24)) ++shift;
    uint64_t significand = magnitude >> shift;
    if (shift > 0 && ((magnitude >> (shift - 1)) & 1) != 0) ++significand;
    const float result = static_cast<float>(
        std::ldexp(static_cast<double>(significand), shift + exponent - kFilterOperandBits - 8));
    return negative ? -result : result;
}

uint32_t Srgb8Code(float decode) {
    const std::array<float, 256>& table = arith::Srgb8OperandTable();
    const auto at = std::lower_bound(table.begin(), table.end(), decode);
    if (at == table.end() || *at != decode) {
        throw std::logic_error("evaluator: a texel of an sRGB8 image is not an sRGB8 decode");
    }
    return static_cast<uint32_t>(at - table.begin());
}

namespace {

/// Painter's float32 (u', v') of set texel (i, j) (decision 060).
std::array<float, 2> PainterPoint(const std::array<float, 6>& m, uint32_t i, uint32_t j, uint32_t setWidth,
                                  uint32_t setHeight) {
    const float u = static_cast<float>((i + 0.5) / setWidth);
    const float v = static_cast<float>(1.0 - (j + 0.5) / setHeight);
    const float pu = m[1] * v;
    const float pv = m[4] * v;
    return {std::fma(m[0], u, pu) + m[2], std::fma(m[3], u, pv) + m[5]};
}

/// BilinearSharp and BilinearHQ through the texture unit (projection_uv.h).
std::array<float, 3> Minified(const UvProjection& p, const tu::Chain& chain, uint32_t i, uint32_t j,
                              uint32_t setWidth, uint32_t setHeight, bool repeat) {
    const std::array<float, 6> m = PainterMatrix(p);
    const std::array<float, 2> uv = PainterPoint(m, i, j, setWidth, setHeight);
    // The gradients: the matrix columns per texel of the (square) set, v counted upwards.
    const float texel = static_cast<float>(1.0 / setWidth);
    const std::array<float, 2> ddx{m[0] * texel, m[3] * texel};
    const std::array<float, 2> ddy{m[1] * texel, m[4] * texel};
    if (p.filter == core::FilteringMode::BilinearSharp) {
        return tu::Sample(chain, uv[0], uv[1], ddx, ddy, kSharpBias, repeat, repeat);
    }
    // BilinearHQ: the fine derivatives in the 2 x 2 quad of (i, j).
    const std::array<float, 2> x0 = PainterPoint(m, i & ~1u, j, setWidth, setHeight);
    const std::array<float, 2> x1 = PainterPoint(m, i | 1u, j, setWidth, setHeight);
    const std::array<float, 2> y0 = PainterPoint(m, i, j & ~1u, setWidth, setHeight);
    const std::array<float, 2> y1 = PainterPoint(m, i, j | 1u, setWidth, setHeight);
    const float dux = x1[0] - x0[0];
    const float dvx = x1[1] - x0[1];
    const float duy = y1[0] - y0[0];
    const float dvy = y1[1] - y0[1];
    const float third = static_cast<float>(1.0 / 3.0);
    const std::array<float, 2> hqDdx{third * ddx[0], third * ddx[1]};
    const std::array<float, 2> hqDdy{third * ddy[0], third * ddy[1]};
    std::array<float, 3> acc{0.0f, 0.0f, 0.0f};
    for (const HqStep& step : kHqOrder) {
        const float sx = static_cast<float>(step.dx) * third;
        const float sy = static_cast<float>(step.dy) * third;
        const float pu = (uv[0] + sx * dux) + sy * duy;
        const float pv = (uv[1] + sx * dvx) + sy * dvy;
        const std::array<float, 3> sample = tu::Sample(chain, pu, pv, hqDdx, hqDdy, 0, repeat, repeat);
        const float weight = static_cast<float>(step.weight) / 16.0f;
        for (uint32_t c = 0; c < 3; ++c) acc[c] = acc[c] + weight * sample[c];
    }
    const std::array<float, 3> base = tu::SampleLevel0(chain, uv[0], uv[1], repeat, repeat);
    const float lengthX = std::sqrt(dux * dux + dvx * dvx);
    const float lengthY = std::sqrt(duy * duy + dvy * dvy);
    const float width = static_cast<float>(chain.size);
    const float alpha = std::fmin(std::fmax(std::fmin(lengthX, lengthY) * width - 1.0f, 0.0f), 1.0f);
    std::array<float, 3> value{};
    for (uint32_t c = 0; c < 3; ++c) value[c] = std::fma(base[c], 1.0f - alpha, acc[c] * alpha);
    return value;
}

/// `texel` as the projection writes it: through a 16-bit UNORM code for a Normal-channel bitmap
/// (`DecodedImage::unorm16Target`, decision 226), else unchanged.
ProjectedTexel Written(const DecodedImage& image, ProjectedTexel texel) {
    if (image.unorm16Target) {
        for (float& v : texel.value) v = arith::UnormOperand(arith::WriteUnorm(v, 16), 16);
    }
    return texel;
}

}  // namespace

ProjectedTexel ProjectTexel(const UvProjection& p, const DecodedImage& image, uint32_t i,
                            uint32_t j, uint32_t setWidth, uint32_t setHeight, bool signedRange,
                            const tu::Chain* chain) {
    if (chain != nullptr && p.filter != core::FilteringMode::Nearest) {
        const bool repeat = p.wrap == core::UVWrapMode::Repeat;
        const std::array<float, 2> uv = PainterPoint(PainterMatrix(p), i, j, setWidth, setHeight);
        ProjectedTexel result;
        result.covered = repeat || (uv[0] >= 0.0f && uv[0] < 1.0f && uv[1] >= 0.0f && uv[1] < 1.0f);
        if (result.covered) result.value = Minified(p, *chain, i, j, setWidth, setHeight, repeat);
        return Written(image, result);
    }
    // Power-of-two resolutions: multiplying by the inverse is the exact division.
    const double invWidth = 1.0 / setWidth;
    const double invHeight = 1.0 / setHeight;
    const double u = (i + 0.5) * invWidth;
    const double v = 1.0 - (j + 0.5) * invHeight;
    const double a = ((u - 0.5) - p.offset[0]) * p.scale[0];
    const double b = ((v - 0.5) - p.offset[1]) * p.scale[1];
    const double ca = p.cosR * a;
    const double sb = p.sinR * b;
    const double u2 = (ca + sb) + 0.5;
    const double sa = (-p.sinR) * a;
    const double cb = p.cosR * b;
    const double v2 = (sa + cb) + 0.5;
    const double x = u2 * image.width - 0.5;
    const double y = (1.0 - v2) * image.height - 0.5;

    const bool repeatX = p.wrap == core::UVWrapMode::Repeat ||
                         p.wrap == core::UVWrapMode::RepeatHorizontally;
    const bool repeatY = p.wrap == core::UVWrapMode::Repeat ||
                         p.wrap == core::UVWrapMode::RepeatVertically;
    ProjectedTexel result;
    result.covered = (repeatX || (u2 >= 0.0 && u2 < 1.0)) && (repeatY || (v2 >= 0.0 && v2 < 1.0));
    if (!result.covered) return result;

    if (p.filter == core::FilteringMode::Nearest) {
        // The GPU's point sample of the bottom-up bitmap: texel floor(x + 1/2) across and, down
        // the rows, ceil(y + 1/2) - 1 (a tie takes the upper row: `srgb-bitmap-variants-v2` s3).
        const int64_t xi = Address(static_cast<int64_t>(std::floor(x + 0.5)), image.width, repeatX);
        const int64_t yi = Address(static_cast<int64_t>(std::ceil(y + 0.5)) - 1, image.height, repeatY);
        for (uint32_t c = 0; c < 3; ++c) {
            result.value[c] = RangeValue(TexelValue(image, xi, yi, c), signedRange);
        }
        return Written(image, result);
    }
    const int64_t fixedX = static_cast<int64_t>(std::floor(x * kSubtexel + 0.5));
    const int64_t fixedY = static_cast<int64_t>(std::floor(y * kSubtexel + 0.5));
    const int64_t x0 = fixedX >> 8;
    const int64_t y0 = fixedY >> 8;
    const uint32_t fx = static_cast<uint32_t>(fixedX & 255);
    const uint32_t fy = static_cast<uint32_t>(fixedY & 255);
    const uint32_t w11 = (fx * fy + 127) >> 8;
    const std::array<uint32_t, 4> weights{256 - fx - fy + w11, fx - w11, fy - w11, w11};
    const int64_t xa = Address(x0, image.width, repeatX);
    const int64_t xb = Address(x0 + 1, image.width, repeatX);
    const int64_t ya = Address(y0, image.height, repeatY);
    const int64_t yb = Address(y0 + 1, image.height, repeatY);
    const std::array<std::array<int64_t, 2>, 4> taps{{{xa, ya}, {xb, ya}, {xa, yb}, {xb, yb}}};
    for (uint32_t c = 0; c < 3; ++c) {
        std::array<float, 4> texels{};
        for (size_t k = 0; k < 4; ++k) {
            texels[k] = RangeValue(TexelValue(image, taps[k][0], taps[k][1], c), signedRange);
        }
        if (image.srgb8) {
            // An sRGB8 texture: one probe of the texture unit's sRGB8 sums on its codes, with these
            // weights (decisions 209, 219, 224).
            std::array<uint32_t, 4> codes{};
            for (size_t k = 0; k < 4; ++k) codes[k] = Srgb8Code(texels[k]);
            result.value[c] = tu::Srgb8Probe(weights, codes);
            continue;
        }
        result.value[c] = BilinearFilter(weights, texels);
        // An R16F texture's filter returns a binary16, to nearest, ties away from zero (decision 218).
        if (image.encoding == render::TexelEncoding::Float16) {
            result.value[c] = arith::HalfToFloat(arith::HalfNearestAway(result.value[c]));
        }
    }
    return Written(image, result);
}

float RangeValue(float v, bool signedRange) {
    if (!signedRange) return v;
    const float twice = 2.0f * v;
    return twice - 1.0f;
}

}  // namespace uzp::evaluator
