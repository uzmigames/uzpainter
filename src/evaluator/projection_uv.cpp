#include "evaluator/projection_uv.h"

#include <bit>
#include <cmath>
#include <numbers>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

constexpr int64_t kSubtexel = 256;  // 8-bit sub-texel fixed point

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
                                   uint32_t setHeight, const DecodedImage& image, core::Id node) {
    if (!IsPowerOfTwo(setWidth) || !IsPowerOfTwo(setHeight)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "UV projection needs a power-of-two texture set resolution (" +
                            std::to_string(setWidth) + "x" + std::to_string(setHeight) + ")",
                        node);
    }
    if (image.width == 0 || image.height == 0 || image.channels == 0) {
        return EvalFail(EvalErrorKind::UnsupportedSource, "an empty bitmap", node);
    }
    if (image.encoding != render::TexelEncoding::Unorm8 &&
        image.encoding != render::TexelEncoding::Unorm16) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "bitmap sources are 8- or 16-bit images", node);
    }
    if (projection.filter != core::FilteringMode::Nearest) {
        const double footprint =
            Footprint(projection, setWidth, setHeight, image.width, image.height);
        if (footprint > 1.0 + 1e-9) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            std::string(core::ToString(projection.filter)) +
                                " minification (" + std::to_string(footprint) +
                                " bitmap texels per texel) is a release gap: Painter samples it "
                                "with the GPU's anisotropic texture unit, not modelled bit for "
                                "bit (decision 056)",
                            node);
        }
    }
    return {};
}

float BilinearFilter(const std::array<uint32_t, 4>& weights, const std::array<float, 4>& texels) {
    float largest = 0.0f;
    for (size_t k = 0; k < 4; ++k) {
        if (weights[k] != 0) largest = std::fmax(largest, texels[k]);
    }
    if (largest == 0.0f) return 0.0f;
    int exponent = 0;
    (void)std::frexp(largest, &exponent);
    // Each operand is below 2^28 + 1 and exact in double before the truncating conversion; the
    // sum is below 2^37.
    uint64_t sum = 0;
    for (size_t k = 0; k < 4; ++k) {
        const double scaled = std::ldexp(static_cast<double>(texels[k]), kFilterOperandBits - exponent);
        sum += weights[k] * static_cast<uint64_t>(scaled);
    }
    // Round the sum to 24 significant bits, ties up, and scale it by 2^(E - 36).
    int shift = 0;
    while ((sum >> shift) >= (uint64_t{1} << 24)) ++shift;
    uint64_t significand = sum >> shift;
    if (shift > 0 && ((sum >> (shift - 1)) & 1) != 0) ++significand;
    return static_cast<float>(
        std::ldexp(static_cast<double>(significand), shift + exponent - kFilterOperandBits - 8));
}

ProjectedTexel ProjectTexel(const UvProjection& p, const DecodedImage& image, uint32_t i,
                            uint32_t j, uint32_t setWidth, uint32_t setHeight) {
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
    const uint32_t bits = image.encoding == render::TexelEncoding::Unorm8 ? 8u : 16u;

    if (p.filter == core::FilteringMode::Nearest) {
        const int64_t xi = Address(static_cast<int64_t>(std::floor(x + 0.5)), image.width, repeatX);
        const int64_t yi = Address(static_cast<int64_t>(std::floor(y + 0.5)), image.height, repeatY);
        for (uint32_t c = 0; c < 3; ++c) result.value[c] = arith::UnormOperand(Code(image, xi, yi, c), bits);
        return result;
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
            texels[k] = arith::UnormOperand(Code(image, taps[k][0], taps[k][1], c), bits);
        }
        result.value[c] = BilinearFilter(weights, texels);
    }
    return result;
}

float RangeValue(float v, bool signedRange) {
    if (!signedRange) return v;
    const float twice = 2.0f * v;
    return twice - 1.0f;
}

}  // namespace uzp::evaluator
