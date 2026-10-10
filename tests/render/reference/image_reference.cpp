#include "image_reference.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <numeric>

// Float sums and products are rounded one operation at a time, as in the IEEE-strict kernels.
#pragma clang fp contract(off)

namespace uzp::render::reference {

namespace {

float AsFloat(uint32_t bits) { return std::bit_cast<float>(bits); }
uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }

double DecodeSrgb(double encoded) {
    return encoded <= 0.04045 ? encoded / 12.92 : std::pow((encoded + 0.055) / 1.055, 2.4);
}

const std::array<float, 256>& DecodeTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> values{};
        for (int c = 0; c < 256; ++c) values[c] = static_cast<float>(DecodeSrgb(c / 255.0));
        return values;
    }();
    return table;
}

const std::array<float, 256>& ThresholdTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> values{};
        for (int k = 1; k < 256; ++k) {
            values[k] = static_cast<float>(DecodeSrgb((k - 0.5) / 255.0));
        }
        return values;
    }();
    return table;
}

float Rsqrt(float d) {
    float y = AsFloat(0x5F375A86u - (Bits(d) >> 1));
    const float h = d * 0.5f;
    for (int i = 0; i < 3; ++i) {
        const float yy = y * y;
        const float t = h * yy;
        const float u = 1.5f - t;
        y = y * u;
    }
    return y;
}

/// The stored value of a float channel.
uint32_t FloatStore(float value, Encoding encoding) {
    return encoding == Encoding::Float16 ? RoundToHalfBits(value) : Bits(value);
}

int64_t FloorDiv(int64_t a, int64_t b) {
    const int64_t q = a / b;
    return (a % b != 0 && a < 0) ? q - 1 : q;
}

uint32_t Wrapped(int64_t i, uint32_t size, Wrap wrap) {
    const int64_t n = size;
    if (wrap == Wrap::Repeat) return static_cast<uint32_t>(((i % n) + n) % n);
    return static_cast<uint32_t>(std::clamp<int64_t>(i, 0, n - 1));
}

/// One output texel of a filtered resample: taps with integer and float weights.
struct Tap {
    uint32_t x;
    uint32_t y;
    uint32_t weight;
    float weightF;
};

void FilterTexel(const Image& source, Image& out, uint32_t ox, uint32_t oy,
                 const std::vector<Tap>& taps, uint64_t total, float scale, Colour colour) {
    const Encoding enc = source.encoding;
    const bool unorm = IsUnorm(enc);
    const uint32_t m = unorm ? UnormMax(enc) : 0;
    std::array<uint64_t, 4> sum{};
    std::array<float, 4> acc{};
    auto floatPath = [&](uint32_t c) { return !unorm || (c < 3 && colour != Colour::Linear); };
    for (const Tap& tap : taps) {
        for (uint32_t c = 0; c < source.channels; ++c) {
            const uint32_t stored = source.At(tap.x, tap.y, c);
            if (!floatPath(c)) {
                sum[c] += uint64_t{tap.weight} * stored;
                continue;
            }
            float value;
            if (!unorm) {
                value = AsFloat(stored);
            } else if (colour == Colour::Srgb) {
                value = SrgbDecode(stored);
            } else {
                value = static_cast<float>(static_cast<int32_t>(2 * stored) -
                                           static_cast<int32_t>(m));
            }
            const float term = tap.weightF * value;
            acc[c] = acc[c] + term;
        }
    }
    for (uint32_t c = 0; c < source.channels; ++c) {
        if (!floatPath(c)) {
            out.At(ox, oy, c) = WriteRatio(sum[c], total, UnormBits(enc));
        } else if (colour == Colour::Srgb && c < 3) {
            const float linear = acc[c] * scale;
            out.At(ox, oy, c) = SrgbEncode(linear);
        } else if (!(colour == Colour::Normal && c < 3)) {
            const float value = acc[c] * scale;
            out.At(ox, oy, c) = FloatStore(value, enc);
        }
    }
    if (colour == Colour::Normal) {
        const float xx = acc[0] * acc[0];
        const float yy = acc[1] * acc[1];
        const float zz = acc[2] * acc[2];
        const float xy = xx + yy;
        const float d = xy + zz;
        std::array<float, 3> n = {0.0f, 0.0f, 1.0f};
        if (d > 0.0f) {
            const float r = Rsqrt(d);
            n = {acc[0] * r, acc[1] * r, acc[2] * r};
        }
        for (uint32_t c = 0; c < 3; ++c) {
            if (unorm) {
                const float half = n[c] * 0.5f;
                const float unit = half + 0.5f;
                out.At(ox, oy, c) = WriteValue(unit, UnormBits(enc));
            } else {
                out.At(ox, oy, c) = FloatStore(n[c], enc);
            }
        }
    }
}

uint32_t BoxWeight(uint32_t s, uint32_t i, uint32_t a, uint32_t b) {
    const uint32_t lo = std::max(s * a, i * b);
    const uint32_t hi = std::min((s + 1) * a, (i + 1) * b);
    return hi - lo;
}

uint32_t Distance2(uint32_t width, uint32_t x, uint32_t y, uint32_t seed) {
    const int64_t dx = int64_t{x} - seed % width;
    const int64_t dy = int64_t{y} - seed / width;
    return static_cast<uint32_t>(dx * dx + dy * dy);
}

/// Copies `colour`, then gives every uncovered texel whose seed (index + 1, 0: none) is within
/// the limit the seed texel's colour.
Image Resolve(const Image& colour, const std::vector<uint8_t>& covered,
              const std::vector<uint32_t>& seeds, uint32_t maxDistance) {
    Image out = colour;
    const uint64_t limit = uint64_t{maxDistance} * maxDistance;
    const uint64_t limitSq = std::min<uint64_t>(limit, 0xFFFFFFFFull);
    for (uint32_t y = 0; y < colour.height; ++y) {
        for (uint32_t x = 0; x < colour.width; ++x) {
            const uint32_t index = y * colour.width + x;
            const uint32_t seed = seeds[index];
            if (covered[index] || seed == 0) continue;
            if (Distance2(colour.width, x, y, seed - 1) > limitSq) continue;
            const uint32_t sx = (seed - 1) % colour.width;
            const uint32_t sy = (seed - 1) / colour.width;
            for (uint32_t c = 0; c < colour.channels; ++c) out.At(x, y, c) = colour.At(sx, sy, c);
        }
    }
    return out;
}

}  // namespace

bool IsUnorm(Encoding encoding) {
    return encoding == Encoding::Unorm8 || encoding == Encoding::Unorm16;
}
uint32_t UnormBits(Encoding encoding) { return encoding == Encoding::Unorm8 ? 8 : 16; }
uint32_t UnormMax(Encoding encoding) { return (1u << UnormBits(encoding)) - 1; }
uint32_t BytesPerChannel(Encoding encoding) {
    switch (encoding) {
        case Encoding::Unorm8: return 1;
        case Encoding::Unorm16:
        case Encoding::Float16: return 2;
        case Encoding::Float32: return 4;
    }
    return 0;
}

Image MakeImage(uint32_t width, uint32_t height, uint32_t channels, Encoding encoding) {
    Image image;
    image.width = width;
    image.height = height;
    image.channels = channels;
    image.encoding = encoding;
    image.values.assign(size_t{width} * height * channels, 0);
    return image;
}

std::vector<std::byte> ToBytes(const Image& image) {
    const uint32_t size = BytesPerChannel(image.encoding);
    std::vector<std::byte> bytes(image.values.size() * size);
    for (size_t i = 0; i < image.values.size(); ++i) {
        uint32_t stored = image.values[i];
        if (image.encoding == Encoding::Float16) {
            stored = std::bit_cast<uint16_t>(static_cast<_Float16>(AsFloat(stored)));
        }
        std::memcpy(&bytes[i * size], &stored, size);
    }
    return bytes;
}

Image FromBytes(uint32_t width, uint32_t height, uint32_t channels, Encoding encoding,
                const std::vector<std::byte>& bytes) {
    Image image = MakeImage(width, height, channels, encoding);
    const uint32_t size = BytesPerChannel(encoding);
    for (size_t i = 0; i < image.values.size() && (i + 1) * size <= bytes.size(); ++i) {
        uint32_t stored = 0;
        std::memcpy(&stored, &bytes[i * size], size);
        if (encoding == Encoding::Float16) {
            const auto half = std::bit_cast<_Float16>(static_cast<uint16_t>(stored));
            stored = Bits(static_cast<float>(half));
        }
        image.values[i] = stored;
    }
    return image;
}

uint32_t RoundToHalfBits(float value) {
    return Bits(static_cast<float>(static_cast<_Float16>(value)));
}

uint32_t WriteRatio(uint64_t s, uint64_t t, uint32_t bits) {
    const unsigned __int128 m = (1u << bits) - 1;
    const unsigned __int128 v = (static_cast<unsigned __int128>(s) << (bits + 4)) / (t * m);
    const unsigned __int128 code = (v * m + (1u << (bits + 3)) - 1) >> (bits + 4);
    return static_cast<uint32_t>(code);
}

uint32_t WriteValue(float value, uint32_t bits) {
    double v = value >= 0.0f ? value : 0.0;
    v = std::min(v, 1.0);
    const uint64_t m = (1u << bits) - 1;
    const auto truncated = static_cast<uint64_t>(std::floor(std::ldexp(v, bits + 4)));
    return static_cast<uint32_t>((truncated * m + (1u << (bits + 3)) - 1) >> (bits + 4));
}

uint32_t PainterBilinearStore16(uint64_t weightedSum) {
    const uint64_t v = (weightedSum << 20) / (256ull * 65535ull);
    return static_cast<uint32_t>((v * 65535ull + (1ull << 19) - 1) >> 20);
}

float SrgbDecode(uint32_t code) { return DecodeTable()[code]; }

uint32_t SrgbEncode(float linear) {
    const std::array<float, 256>& thresholds = ThresholdTable();
    uint32_t code = 0;
    for (uint32_t k = 1; k < 256; ++k) {
        if (linear >= thresholds[k]) code = k;
    }
    return code;
}

Image DilateJumpFlood(const Image& colour, const std::vector<uint8_t>& covered,
                      uint32_t maxDistance) {
    const uint32_t w = colour.width;
    const uint32_t h = colour.height;
    const uint32_t extent = std::max(w, h);
    const uint32_t reach = std::min(maxDistance, extent - 1);
    if (reach == 0) return colour;
    std::vector<uint32_t> steps = {1};
    uint32_t n = 1;
    while (n <= reach) n *= 2;
    for (uint32_t step = n / 2; step >= 1; step /= 2) steps.push_back(step);

    std::vector<uint32_t> seeds(size_t{w} * h);
    for (uint32_t i = 0; i < seeds.size(); ++i) seeds[i] = covered[i] ? i + 1 : 0;
    std::vector<uint32_t> next(seeds.size());
    for (const uint32_t step : steps) {
        for (uint32_t y = 0; y < h; ++y) {
            for (uint32_t x = 0; x < w; ++x) {
                const uint32_t index = y * w + x;
                uint32_t best = seeds[index];
                uint32_t bestD = best ? Distance2(w, x, y, best - 1) : 0xFFFFFFFFu;
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        if (dx == 0 && dy == 0) continue;
                        const int64_t qx = int64_t{x} + int64_t{dx} * step;
                        const int64_t qy = int64_t{y} + int64_t{dy} * step;
                        if (qx < 0 || qy < 0 || qx >= w || qy >= h) continue;
                        const uint32_t seed = seeds[static_cast<size_t>(qy * w + qx)];
                        if (seed == 0) continue;
                        const uint32_t d = Distance2(w, x, y, seed - 1);
                        if (d < bestD || (d == bestD && seed < best)) {
                            best = seed;
                            bestD = d;
                        }
                    }
                }
                next[index] = best;
            }
        }
        seeds.swap(next);
    }
    return Resolve(colour, covered, seeds, maxDistance);
}

Image DilateBruteForce(const Image& colour, const std::vector<uint8_t>& covered,
                       uint32_t maxDistance) {
    const uint32_t w = colour.width;
    std::vector<uint32_t> coveredIndices;
    for (uint32_t i = 0; i < covered.size(); ++i) {
        if (covered[i]) coveredIndices.push_back(i);
    }
    std::vector<uint32_t> seeds(covered.size(), 0);
    if (maxDistance == 0) return colour;
    for (uint32_t index = 0; index < covered.size(); ++index) {
        uint32_t best = 0;
        uint32_t bestD = 0xFFFFFFFFu;
        for (const uint32_t candidate : coveredIndices) {  // ascending: ties keep the smaller
            const uint32_t d = Distance2(w, index % w, index / w, candidate);
            if (d < bestD) {
                best = candidate + 1;
                bestD = d;
            }
        }
        seeds[index] = best;
    }
    return Resolve(colour, covered, seeds, maxDistance);
}

Image Resample(const Image& source, uint32_t width, uint32_t height, Filter filter, Wrap wrap,
               Colour colour) {
    if (width == source.width && height == source.height) return source;
    Image out = MakeImage(width, height, source.channels, source.encoding);
    const uint32_t sw = source.width;
    const uint32_t sh = source.height;
    const uint32_t gx = std::gcd(sw, width);
    const uint32_t gy = std::gcd(sh, height);
    const uint32_t ax = width / gx;
    const uint32_t bx = sw / gx;
    const uint32_t ay = height / gy;
    const uint32_t by = sh / gy;
    const float invTotal =
        static_cast<float>(1.0 / (static_cast<double>(bx) * static_cast<double>(by)));
    std::vector<Tap> taps;
    for (uint32_t j = 0; j < height; ++j) {
        for (uint32_t i = 0; i < width; ++i) {
            if (filter == Filter::Nearest) {
                const uint32_t sx = static_cast<uint32_t>((2ull * i + 1) * sw / (2ull * width));
                const uint32_t sy = static_cast<uint32_t>((2ull * j + 1) * sh / (2ull * height));
                for (uint32_t c = 0; c < source.channels; ++c) out.At(i, j, c) = source.At(sx, sy, c);
                continue;
            }
            taps.clear();
            if (filter == Filter::Bilinear) {
                // X = floor(256 x + 0.5), x = (i + 0.5) W / W' - 0.5, exactly.
                const int64_t x = FloorDiv(256 * (2 * int64_t{i} + 1) * sw - 255 * int64_t{width},
                                           2 * int64_t{width});
                const int64_t y = FloorDiv(256 * (2 * int64_t{j} + 1) * sh - 255 * int64_t{height},
                                           2 * int64_t{height});
                const int64_t x0 = FloorDiv(x, 256);
                const int64_t y0 = FloorDiv(y, 256);
                const auto fx = static_cast<uint32_t>(x - x0 * 256);
                const auto fy = static_cast<uint32_t>(y - y0 * 256);
                const uint32_t w11 = (fx * fy + 127) >> 8;
                const uint32_t w10 = fx - w11;
                const uint32_t w01 = fy - w11;
                const uint32_t w00 = 256 - fx - fy + w11;
                const uint32_t xa = Wrapped(x0, sw, wrap);
                const uint32_t xb = Wrapped(x0 + 1, sw, wrap);
                const uint32_t ya = Wrapped(y0, sh, wrap);
                const uint32_t yb = Wrapped(y0 + 1, sh, wrap);
                taps = {{xa, ya, w00, static_cast<float>(w00)},
                        {xb, ya, w10, static_cast<float>(w10)},
                        {xa, yb, w01, static_cast<float>(w01)},
                        {xb, yb, w11, static_cast<float>(w11)}};
                FilterTexel(source, out, i, j, taps, 256, 1.0f / 256.0f, colour);
                continue;
            }
            for (uint32_t sy = j * by / ay; sy <= ((j + 1) * by - 1) / ay; ++sy) {
                const uint32_t wy = BoxWeight(sy, j, ay, by);
                for (uint32_t sx = i * bx / ax; sx <= ((i + 1) * bx - 1) / ax; ++sx) {
                    const uint32_t wx = BoxWeight(sx, i, ax, bx);
                    const float weightF = static_cast<float>(wx) * static_cast<float>(wy);
                    taps.push_back({sx, sy, wx * wy, weightF});
                }
            }
            FilterTexel(source, out, i, j, taps, uint64_t{bx} * by, invTotal, colour);
        }
    }
    return out;
}

uint64_t CoveredTexels(const Image& image, uint32_t cutoff) {
    uint64_t count = 0;
    for (uint32_t y = 0; y < image.height; ++y) {
        for (uint32_t x = 0; x < image.width; ++x) count += image.At(x, y, 3) >= cutoff ? 1 : 0;
    }
    return count;
}

std::vector<Image> MipChain(const Image& base, uint32_t levels, Colour colour,
                            uint32_t coverageCutoff) {
    std::vector<Image> chain = {base};
    const uint64_t n0 = uint64_t{base.width} * base.height;
    const uint64_t count0 = coverageCutoff ? CoveredTexels(base, coverageCutoff) : 0;
    const uint32_t m = IsUnorm(base.encoding) ? UnormMax(base.encoding) : 0;
    for (uint32_t k = 1; k < levels; ++k) {
        const Image& previous = chain.back();
        const uint32_t w = std::max(1u, base.width >> k);
        const uint32_t h = std::max(1u, base.height >> k);
        Image level = Resample(previous, w, h, Filter::Box, Wrap::Clamp, colour);
        if (coverageCutoff) {
            const uint32_t cutoff = coverageCutoff;
            std::vector<uint64_t> histogram(m + 2, 0);
            for (uint32_t y = 0; y < h; ++y) {
                for (uint32_t x = 0; x < w; ++x) ++histogram[level.At(x, y, 3)];
            }
            const uint64_t nk = uint64_t{w} * h;
            // Nearest of count0 nk / n0, ties down.
            const uint64_t target = (2 * count0 * nk + n0 - 1) / (2 * n0);
            // The covered texels: the `target` largest alphas, equal alphas in linear order.
            uint32_t divisor = m + 1;
            uint32_t tie = 0xFFFFFFFFu;
            uint64_t tieCovered = 0;
            if (target > 0) {
                uint64_t above = 0;
                uint32_t t = m;
                while (t > 0 && above + histogram[t] < target) above += histogram[t--];
                tieCovered = target - above;
                if (t == 0 || tieCovered < histogram[t]) {
                    tie = t;
                    divisor = std::max(t, 1u);
                } else {
                    uint32_t lower = 1;
                    for (uint32_t s = t; s > 0; --s) {
                        if (histogram[s - 1] != 0) {
                            lower = s;
                            break;
                        }
                    }
                    divisor = std::clamp(cutoff, lower, t);
                }
            }
            uint64_t rank = 0;
            for (uint32_t y = 0; y < h; ++y) {
                for (uint32_t x = 0; x < w; ++x) {
                    uint32_t& alpha = level.At(x, y, 3);
                    if (alpha == tie) {
                        alpha = rank++ < tieCovered ? cutoff : (tie == 0 ? 0 : cutoff - 1);
                    } else {
                        alpha = std::min<uint32_t>(
                            m, static_cast<uint32_t>(uint64_t{alpha} * cutoff / divisor));
                    }
                }
            }
        }
        chain.push_back(std::move(level));
    }
    return chain;
}

}  // namespace uzp::render::reference
