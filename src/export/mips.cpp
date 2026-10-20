#include "export/mips.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <string>

namespace uzp::exporter {

namespace {

constexpr double kCodeMax = 65535.0;

/// x^2.4 for x in [0, 1]: x^2 times the fifth root of x^2, the root by 40 Newton steps from 1
/// (monotone from above; the steps settle within an ulp long before the last one). Only +, *, /
/// and comparisons: the same bits on every IEEE-754 machine.
double Pow24(double x) {
    const double z = x * x;
    if (z == 0.0) return 0.0;
    double y = 1.0;
    for (int i = 0; i < 40; ++i) {
        const double y2 = y * y;
        y = (4.0 * y + z / (y2 * y2)) / 5.0;
    }
    return z * y;
}

/// IEC 61966-2-1 decode of an encoded value in [0, 1].
double SrgbToLinear(double v) {
    if (v <= 0.04045) return v / 12.92;
    return Pow24((v + 0.055) / 1.055);
}

struct SrgbTables {
    /// decode(c / 65535) for every code.
    std::vector<double> decode;
    /// decode((c + 0.5) / 65535), the upper edge of code c's interval, for c < 65535.
    std::vector<double> edges;
    SrgbTables() : decode(65536), edges(65535) {
        for (uint32_t c = 0; c < 65536; ++c) decode[c] = SrgbToLinear(c / kCodeMax);
        for (uint32_t c = 0; c < 65535; ++c) edges[c] = SrgbToLinear((c + 0.5) / kCodeMax);
    }
};

const SrgbTables& Tables() {
    static const SrgbTables tables;
    return tables;
}

bool IsPowerOfTwo(uint32_t v) { return v != 0 && (v & (v - 1)) == 0; }

/// The four source texel indices (top left, top right, bottom left, bottom right) of texel
/// (x, y) of the level below `src`.
std::array<uint64_t, 4> Footprint(const Rgba16Image& src, uint32_t x, uint32_t y) {
    const uint32_t x0 = std::min(2 * x, src.width - 1);
    const uint32_t x1 = std::min(2 * x + 1, src.width - 1);
    const uint32_t y0 = std::min(2 * y, src.height - 1);
    const uint32_t y1 = std::min(2 * y + 1, src.height - 1);
    const uint64_t w = src.width;
    return {y0 * w + x0, y0 * w + x1, y1 * w + x0, y1 * w + x1};
}

uint16_t MeanCode(const Rgba16Image& src, const std::array<uint64_t, 4>& at, uint32_t channel) {
    uint32_t sum = 0;
    for (uint64_t i : at) sum += src.rgba[i * 4 + channel];
    return static_cast<uint16_t>((sum + 2) / 4);
}

uint16_t SrgbMeanCode(const Rgba16Image& src, const std::array<uint64_t, 4>& at,
                      uint32_t channel) {
    const std::vector<double>& decode = Tables().decode;
    double sum = 0.0;
    for (uint64_t i : at) sum += decode[src.rgba[i * 4 + channel]];
    return SrgbEncode16(sum * 0.25);
}

uint16_t UnitToCode(double v) {
    const double t = std::floor((v * 0.5 + 0.5) * kCodeMax + 0.5);
    return static_cast<uint16_t>(std::clamp(t, 0.0, kCodeMax));
}

/// Writes the unit vector of (x, y, z) (or (0, 0, 1) for the zero vector) as codes.
void StoreNormal(double x, double y, double z, uint16_t* out) {
    const double length = std::sqrt(x * x + y * y + z * z);
    if (length == 0.0) {
        x = 0.0;
        y = 0.0;
        z = 1.0;
    } else {
        x /= length;
        y /= length;
        z /= length;
    }
    out[0] = UnitToCode(x);
    out[1] = UnitToCode(y);
    out[2] = UnitToCode(z);
}

double CodeToUnit(uint16_t code) { return code / kCodeMax * 2.0 - 1.0; }

/// The smallest 16-bit alpha code whose 8-bit code c satisfies c / 255 > threshold.
uint32_t MinCoveredCode16(double threshold) {
    uint32_t k8 = 0;
    while (k8 < 255 && !(k8 / 255.0 > threshold)) ++k8;
    // round(v / 257) >= k8  <=>  v >= 257 k8 - 128.
    return k8 == 0 ? 0 : 257 * k8 - 128;
}

/// The 16-bit code of alpha m * s, clamped to 1.
uint32_t ScaledAlpha(double m, double s) {
    const double v = m * s;
    if (v >= 1.0) return 65535;
    return static_cast<uint32_t>(std::floor(v * kCodeMax + 0.5));
}

/// Alpha-coverage preservation of one level: `means` are the box-filtered alphas in [0, 1];
/// returns the scale whose covered count is closest to `target` (decision 315).
double CoverageScale(const std::vector<double>& means, uint64_t target, uint32_t minCode) {
    std::vector<double> sorted = means;
    std::sort(sorted.begin(), sorted.end());
    const uint64_t n = sorted.size();
    auto count = [&](double s) -> uint64_t {
        // Covered is monotone in m: binary search the first covered mean.
        uint64_t lo = 0;
        uint64_t hi = n;
        while (lo < hi) {
            const uint64_t mid = lo + (hi - lo) / 2;
            if (ScaledAlpha(sorted[mid], s) >= minCode) hi = mid;
            else lo = mid + 1;
        }
        return n - lo;
    };
    // Every positive mean is at least 1 / 262140, so this scale takes it to 1.
    constexpr double kMaxScale = 262140.0;
    const uint64_t goal = std::min(target, count(kMaxScale));
    const uint64_t atOne = count(1.0);
    if (atOne == goal) return 1.0;
    // Bisect the edge between count < k and count >= k; k = 1 when the goal is 0, whose answer
    // is the largest scale that still covers nothing.
    const uint64_t k = goal == 0 ? 1 : goal;
    double lo = atOne < k ? 1.0 : 0.0;
    double hi = atOne < k ? kMaxScale : 1.0;
    for (int i = 0; i < 2000; ++i) {
        const double mid = lo + (hi - lo) / 2.0;
        if (mid <= lo || mid >= hi) break;
        if (count(mid) < k) lo = mid;
        else hi = mid;
    }
    if (goal == 0) return lo;
    const uint64_t above = count(hi) - goal;
    const uint64_t below = goal - count(lo);
    return above <= below ? hi : lo;
}

Rgba16Image NextLevel(const Rgba16Image& src, const MipOptions& options, uint64_t baseCovered,
                      uint64_t baseTexels, uint32_t minCode) {
    Rgba16Image dst;
    dst.width = std::max(1u, src.width / 2);
    dst.height = std::max(1u, src.height / 2);
    dst.rgba.resize(uint64_t{dst.width} * dst.height * 4);
    std::vector<double> alphaMeans;
    if (options.mapClass == MipClass::MaskedColour) alphaMeans.resize(uint64_t{dst.width} * dst.height);
    for (uint32_t y = 0; y < dst.height; ++y) {
        for (uint32_t x = 0; x < dst.width; ++x) {
            const std::array<uint64_t, 4> at = Footprint(src, x, y);
            const uint64_t texel = uint64_t{y} * dst.width + x;
            uint16_t* out = dst.rgba.data() + texel * 4;
            switch (options.mapClass) {
                case MipClass::Linear:
                    for (uint32_t c = 0; c < 4; ++c) out[c] = MeanCode(src, at, c);
                    break;
                case MipClass::Colour:
                    for (uint32_t c = 0; c < 3; ++c) out[c] = SrgbMeanCode(src, at, c);
                    out[3] = MeanCode(src, at, 3);
                    break;
                case MipClass::Normal: {
                    double v[3] = {0.0, 0.0, 0.0};
                    for (uint64_t i : at)
                        for (uint32_t c = 0; c < 3; ++c) v[c] += CodeToUnit(src.rgba[i * 4 + c]);
                    StoreNormal(v[0], v[1], v[2], out);
                    out[3] = MeanCode(src, at, 3);
                    break;
                }
                case MipClass::MaskedColour: {
                    for (uint32_t c = 0; c < 3; ++c) out[c] = SrgbMeanCode(src, at, c);
                    uint32_t sum = 0;
                    for (uint64_t i : at) sum += src.rgba[i * 4 + 3];
                    alphaMeans[texel] = sum / (4.0 * kCodeMax);
                    break;
                }
            }
        }
    }
    if (options.mapClass == MipClass::MaskedColour) {
        const uint64_t texels = alphaMeans.size();
        const uint64_t target = (2 * baseCovered * texels + baseTexels) / (2 * baseTexels);
        const double scale = CoverageScale(alphaMeans, target, minCode);
        for (uint64_t i = 0; i < texels; ++i)
            dst.rgba[i * 4 + 3] = static_cast<uint16_t>(ScaledAlpha(alphaMeans[i], scale));
    }
    return dst;
}

}  // namespace

double SrgbDecode16(uint16_t code) { return Tables().decode[code]; }

uint16_t SrgbEncode16(double linear) {
    const std::vector<double>& edges = Tables().edges;
    return static_cast<uint16_t>(std::upper_bound(edges.begin(), edges.end(), linear) -
                                 edges.begin());
}

uint32_t FullMipCount(uint32_t width, uint32_t height) {
    uint32_t side = std::max(width, height);
    uint32_t count = 1;
    while (side > 1) {
        side /= 2;
        ++count;
    }
    return count;
}

uint64_t CoveredTexels(const Rgba16Image& image, double threshold) {
    uint64_t covered = 0;
    for (uint64_t i = 3; i < image.rgba.size(); i += 4) {
        const uint32_t code8 = (image.rgba[i] + 128u) / 257u;
        if (code8 / 255.0 > threshold) ++covered;
    }
    return covered;
}

std::vector<Rgba16Image> GenerateMipChain(const Rgba16Image& base, const MipOptions& options) {
    if (base.width == 0 || base.height == 0)
        throw std::invalid_argument("GenerateMipChain: empty image");
    if (base.rgba.size() != uint64_t{base.width} * base.height * 4)
        throw std::invalid_argument("GenerateMipChain: texel count does not match the image size");
    if (!IsPowerOfTwo(base.width) || !IsPowerOfTwo(base.height))
        throw std::invalid_argument("GenerateMipChain: " + std::to_string(base.width) + "x" +
                                    std::to_string(base.height) +
                                    " is not a power of two on both sides");
    if (!(options.alphaThreshold >= 0.0 && options.alphaThreshold < 1.0))
        throw std::invalid_argument("GenerateMipChain: alphaThreshold must lie in [0, 1)");

    std::vector<Rgba16Image> chain;
    chain.reserve(FullMipCount(base.width, base.height));
    chain.push_back(base);
    if (options.mapClass == MipClass::Normal) {
        Rgba16Image& level0 = chain.front();
        for (uint64_t i = 0; i < level0.rgba.size(); i += 4) {
            uint16_t* t = level0.rgba.data() + i;
            StoreNormal(CodeToUnit(t[0]), CodeToUnit(t[1]), CodeToUnit(t[2]), t);
        }
    }
    const uint64_t baseTexels = uint64_t{base.width} * base.height;
    const uint64_t baseCovered = CoveredTexels(base, options.alphaThreshold);
    const uint32_t minCode = MinCoveredCode16(options.alphaThreshold);
    while (chain.back().width > 1 || chain.back().height > 1)
        chain.push_back(NextLevel(chain.back(), options, baseCovered, baseTexels, minCode));
    return chain;
}

Rgba8Image QuantizeTo8(const Rgba16Image& image) {
    Rgba8Image out;
    out.width = image.width;
    out.height = image.height;
    out.rgba.resize(image.rgba.size());
    for (uint64_t i = 0; i < image.rgba.size(); ++i)
        out.rgba[i] = static_cast<uint8_t>((image.rgba[i] + 128u) / 257u);
    return out;
}

}  // namespace uzp::exporter
