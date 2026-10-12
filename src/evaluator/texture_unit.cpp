#include "evaluator/texture_unit.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <mutex>
#include <stdexcept>

#include "zlib.h"

namespace uzp::evaluator::tu {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr unsigned char kLodZ[] = {
#embed "tables/tu-lod.zlib"
};
constexpr unsigned char kGeometryZ[] = {
#embed "tables/tu-geometry.zlib"
};
#pragma clang diagnostic pop

template <typename T>
std::vector<T> Inflate(std::span<const unsigned char> packed, size_t count) {
    std::vector<T> values(count);
    z_stream stream{};
    stream.next_in = const_cast<Bytef*>(packed.data());
    stream.avail_in = static_cast<uInt>(packed.size());
    stream.next_out = reinterpret_cast<Bytef*>(values.data());
    stream.avail_out = static_cast<uInt>(values.size() * sizeof(T));
    int status = inflateInit(&stream);
    if (status == Z_OK) status = inflate(&stream, Z_FINISH);
    const bool complete = status == Z_STREAM_END && stream.avail_out == 0;
    inflateEnd(&stream);
    if (!complete) {
        // The tables are part of the build; a damaged one is a build defect, not an input error.
        throw std::runtime_error("evaluator: embedded texture-unit table is damaged");
    }
    return values;
}

/// Round half up / down of x / 256.
constexpr uint32_t Rhu(uint32_t x) { return (x + 128u) >> 8; }
constexpr uint32_t Rhd(uint32_t x) { return (x + 127u) >> 8; }

/// E lowered until the biased float32 exponent E + 126 is a multiple of 4.
constexpr int Coarse(int e) { return e - (((e + 126) % 4) + 4) % 4; }

/// The 9-bit truncated mantissa and the exponent of |g| size (size a power of two, g finite
/// and non-zero).
struct Key {
    int mantissa;
    int exponent;
};
Key KeyOf(float g, uint32_t size) {
    const uint32_t bits = std::bit_cast<uint32_t>(g) & 0x7FFFFFFFu;
    return {static_cast<int>((bits >> 14) & 511u),
            static_cast<int>(bits >> 23) - 127 + std::countr_zero(size)};
}

/// One gradient: its larger component's magnitude, sign and axis.
struct Axis {
    float length;
    int sign;
    int axis;
};
Axis AxisOf(std::array<float, 2> g) {
    const float x = std::fabs(g[0]);
    const float y = std::fabs(g[1]);
    if (x >= y) return {x, g[0] < 0.0f ? -1 : 1, 0};
    return {y, g[1] < 0.0f ? -1 : 1, 1};
}

/// A value n 2^e under construction (n = 0: nothing yet).
struct Sum {
    uint64_t n = 0;
    int e = 0;
};

void TruncateTo(Sum& s, int lsb) {
    if (s.n != 0 && lsb > s.e) {
        const int shift = lsb - s.e;
        s.n = shift >= 64 ? 0 : s.n >> shift;
        s.e = lsb;
    }
}

void Add(Sum& s, uint64_t n, int e) {
    if (n == 0) return;
    if (s.n == 0) {
        s = {n, e};
        return;
    }
    const int low = std::min(s.e, e);
    s.n = (s.n << (s.e - low)) + (n << (e - low));
    s.e = low;
}

/// n 2^e rounded to the nearest float32, ties up.
float TiesUp(const Sum& s) {
    if (s.n == 0) return 0.0f;
    const int length = 64 - std::countl_zero(s.n);
    const int shift = std::max(length - 24, 0);
    uint64_t q = s.n >> shift;
    if (shift > 0 && ((s.n >> (shift - 1)) & 1u) != 0) ++q;
    return static_cast<float>(std::ldexp(static_cast<double>(q), s.e + shift));
}

/// One probe's taps: texel indices into its level and weights (1/1024).
struct Probe {
    int offset = 0;
    uint32_t count = 0;
    std::array<uint32_t, 8> texel{};
    std::array<uint32_t, 8> weight{};
};

void SplitInto(Probe& probe, uint32_t w, uint32_t n, int64_t px, int64_t py, const Chain& chain,
               uint32_t level, bool repeatU, bool repeatV) {
    const uint32_t side = chain.size >> level;
    if (!repeatU) px = std::clamp<int64_t>(px, 0, int64_t{256} * (side - 1));
    if (!repeatV) py = std::clamp<int64_t>(py, 0, int64_t{256} * (side - 1));
    const uint32_t fx = static_cast<uint32_t>(px & 255);
    const uint32_t fy = static_cast<uint32_t>(py & 255);
    const uint32_t x1 = Rhu(w * fx);
    const uint32_t x0 = w - x1;
    const uint32_t w11 = Rhu(x1 * fy);
    const uint32_t w01 = Rhd(x0 * fy);
    const std::array<uint32_t, 4> weights{x0 - w01, x1 - w11, w01, w11};
    const int64_t n64 = side;
    for (uint32_t k = 0; k < 4; ++k) {
        if (weights[k] == 0) continue;
        int64_t tx = (px >> 8) + (k & 1u);
        int64_t ty = (py >> 8) + (k >> 1);
        tx = repeatU ? ((tx % n64) + n64) % n64 : std::clamp<int64_t>(tx, 0, n64 - 1);
        ty = repeatV ? ((ty % n64) + n64) % n64 : std::clamp<int64_t>(ty, 0, n64 - 1);
        probe.texel[probe.count] = chain.offsets[level] + static_cast<uint32_t>(ty * n64 + tx);
        probe.weight[probe.count] = n * weights[k];
        ++probe.count;
    }
}

}  // namespace

std::span<const unsigned char> CompressedLod() { return {kLodZ, sizeof(kLodZ)}; }
std::span<const unsigned char> CompressedGeometry() { return {kGeometryZ, sizeof(kGeometryZ)}; }

const std::vector<uint16_t>& LodTable() {
    static const std::vector<uint16_t> table = Inflate<uint16_t>(CompressedLod(), kLodEntries);
    return table;
}

const std::vector<uint32_t>& GeometryTable() {
    static const std::vector<uint32_t> table = Inflate<uint32_t>(CompressedGeometry(), kGeometryWords);
    return table;
}

Chain BuildChain(uint32_t size, std::vector<float> level0) {
    Chain chain;
    chain.size = size;
    chain.texels = std::move(level0);
    chain.offsets.push_back(0);
    uint32_t side = size;
    while (side > 1) {
        const uint32_t above = chain.offsets.back();
        const uint32_t half = side / 2;
        chain.offsets.push_back(static_cast<uint32_t>(chain.texels.size() / 3));
        for (uint32_t y = 0; y < half; ++y) {
            for (uint32_t x = 0; x < half; ++x) {
                for (uint32_t c = 0; c < 3; ++c) {
                    std::array<float, 4> quad{};
                    for (uint32_t k = 0; k < 4; ++k) {
                        quad[k] = chain.texels[(above + (2 * y + (k >> 1)) * side + 2 * x + (k & 1u)) * 3 + c];
                    }
                    // The GPU's linear filter at the block's centre: weights 64/256 each, operands
                    // floor(t 2^(28 - E)) below the largest texel's exponent, ties up.
                    const float largest = std::fmax(std::fmax(quad[0], quad[1]), std::fmax(quad[2], quad[3]));
                    float value = 0.0f;
                    if (largest > 0.0f) {
                        int e = 0;
                        (void)std::frexp(largest, &e);
                        uint64_t operands = 0;
                        for (const float t : quad) {
                            operands += static_cast<uint64_t>(std::ldexp(static_cast<double>(t), 28 - e));
                        }
                        value = TiesUp({operands * 64u, e - 36});
                    }
                    chain.texels.push_back(value);
                }
            }
        }
        side = half;
    }
    return chain;
}

Footprint Resolve(std::array<float, 2> ddx, std::array<float, 2> ddy, uint32_t size,
                  uint32_t levels, int bias) {
    const Axis gx = AxisOf(ddx);
    const Axis gy = AxisOf(ddy);
    // The longer gradient by its exponent and 9-bit mantissa; ddx on a tie.
    const bool xMajor = (std::bit_cast<uint32_t>(gx.length) >> 14) >= (std::bit_cast<uint32_t>(gy.length) >> 14);
    const Axis& major = xMajor ? gx : gy;
    const Axis& minor = xMajor ? gy : gx;
    const Key a = KeyOf(major.length, size);
    const Key b = KeyOf(minor.length, size);
    const std::vector<uint16_t>& lod = LodTable();
    Footprint fp;
    fp.sign = major.sign;
    fp.axis = major.axis;
    fp.lambdaMajor = static_cast<int>(lod[3u * 512u * 512u + static_cast<uint32_t>(a.mantissa)]) +
                     256 * (a.exponent - 3);
    const int d = a.exponent - b.exponent;
    fp.lambda = d >= 3 ? fp.lambdaMajor - 512
                       : static_cast<int>(lod[(static_cast<uint32_t>(d) * 512u +
                                               static_cast<uint32_t>(a.mantissa)) *
                                                  512u +
                                              static_cast<uint32_t>(b.mantissa)]) +
                             256 * (a.exponent - 3);
    // The minor-axis LOD is clamped at 0 before the anisotropy is taken from it.
    fp.lambda = std::max(fp.lambda, 0);
    fp.rho = fp.lambdaMajor - fp.lambda;
    fp.biased = fp.lambda + bias;
    const uint32_t last = levels - 1;
    if (fp.lambdaMajor <= 0 && fp.biased <= 0) {
        fp.magnify = true;
    } else if (fp.biased < 0) {
        fp.lower = 0;
        fp.f = 0;
    } else {
        fp.lower = static_cast<uint32_t>(fp.biased >> 8);
        fp.f = static_cast<uint32_t>(fp.biased & 255);
        if (fp.lower >= last) {
            fp.lower = last;
            fp.f = 0;
        }
    }
    return fp;
}

namespace {

std::array<float, 3> SampleAt(const Chain& chain, const Footprint& fp, float u, float v, bool repeatU,
                              bool repeatV) {
    const uint32_t levels = static_cast<uint32_t>(chain.offsets.size());
    const std::vector<uint32_t>& geometry = GeometryTable();

    // The probes of each level, in the unit's order.
    std::array<Probe, 8> probes{};
    std::array<uint32_t, 8> group{};
    uint32_t count = 0;
    const uint32_t t = fp.magnify ? 0u : std::min<uint32_t>(256u, (7u * fp.f) >> 2);
    for (uint32_t role = 0; role < 2; ++role) {
        const uint32_t level = fp.lower + role;
        if (level >= levels) break;
        std::array<uint32_t, 4> entry{};
        if (fp.magnify) {
            if (role != 0) break;
            entry = {1u | (4u << 8), 0u, 256u, 0u};
        } else {
            if ((role == 0 && t == 256u) || (role == 1 && t == 0u)) continue;
            const uint32_t s = fp.sign > 0 ? 0u : 1u;
            const uint32_t r = static_cast<uint32_t>(fp.rho);
            const uint32_t index =
                fp.f >= kFractions
                    ? (kRhoCells * kFractions * 4u + r * 2u + s) * 4u
                    : (((r * kFractions + fp.f) * 2u + s) * 2u + role) * 4u;
            for (uint32_t k = 0; k < 4; ++k) entry[k] = geometry[index + k];
            if ((entry[0] & 0xFFu) == kUnmeasured) {
                throw std::runtime_error("evaluator: texture-unit geometry cell not measured");
            }
        }
        const uint32_t side = chain.size >> level;
        const int64_t x = static_cast<int64_t>(std::floor(256.0 * (static_cast<double>(u) * side - 0.5) + 0.5));
        const int64_t y = static_cast<int64_t>(std::floor(256.0 * (static_cast<double>(v) * side - 0.5) + 0.5));
        std::array<Probe, 4> found{};
        uint32_t n = 0;
        const uint32_t pairs = entry[0] & 0xFFu;
        for (uint32_t k = 0; k < pairs; ++k) {
            const uint32_t mult = (entry[0] >> (8 + 8 * k)) & 0xFFu;
            const int p = static_cast<int>((entry[1] >> (16 * k)) & 0xFFFFu);
            const uint32_t wl = entry[2 + k] & 0xFFFFu;
            const uint32_t wr = entry[2 + k] >> 16;
            auto place = [&](Probe& probe, uint32_t w, int offset) {
                const int64_t px = fp.axis == 0 ? x + offset : x;
                const int64_t py = fp.axis == 0 ? y : y + offset;
                if (w != 0) SplitInto(probe, w, mult, px, py, chain, level, repeatU, repeatV);
            };
            if (p == 0) {
                found[n].offset = 0;
                place(found[n], wl, 0);
                place(found[n], wr, 0);
                ++n;
            } else {
                found[n].offset = -p;
                place(found[n], wl, -p);
                found[n + 1].offset = p;
                place(found[n + 1], wr, p);
                n += 2;
            }
        }
        std::stable_sort(found.begin(), found.begin() + n, [&](const Probe& a, const Probe& b) {
            return fp.sign * a.offset < fp.sign * b.offset;
        });
        for (uint32_t k = 0; k < n; ++k) {
            probes[count] = found[k];
            group[count] = role * 2u + k / 2u;
            ++count;
        }
    }

    std::array<float, 3> result{};
    for (uint32_t c = 0; c < 3; ++c) {
        std::array<int, 8> exponent{};
        std::array<uint64_t, 8> sum{};
        for (uint32_t k = 0; k < count; ++k) {
            float largest = 0.0f;
            for (uint32_t q = 0; q < probes[k].count; ++q) {
                largest = std::fmax(largest, chain.texels[probes[k].texel[q] * 3 + c]);
            }
            if (largest == 0.0f) continue;
            int e = 0;
            (void)std::frexp(largest, &e);
            exponent[k] = e;
            for (uint32_t q = 0; q < probes[k].count; ++q) {
                const double scaled =
                    std::ldexp(static_cast<double>(chain.texels[probes[k].texel[q] * 3 + c]), 28 - e);
                sum[k] += uint64_t{probes[k].weight[q]} * static_cast<uint64_t>(scaled);
            }
        }
        Sum acc;
        for (uint32_t k = 0; k < count; ++k) {
            if (k >= 2) {
                int g = 0;
                bool any = false;
                for (uint32_t q = 0; q < count; ++q) {
                    if (group[q] <= group[k] && sum[q] != 0) {
                        g = any ? std::max(g, exponent[q]) : exponent[q];
                        any = true;
                    }
                }
                if (any) TruncateTo(acc, Coarse(g) - 36);
            }
            if (sum[k] == 0) continue;
            Sum part{sum[k], exponent[k] - 38};
            TruncateTo(part, Coarse(exponent[k]) - 36);
            Add(acc, part.n, part.e);
        }
        result[c] = TiesUp(acc);
    }
    return result;
}

}  // namespace

std::array<float, 3> Sample(const Chain& chain, float u, float v, std::array<float, 2> ddx,
                            std::array<float, 2> ddy, int bias, bool repeatU, bool repeatV) {
    const uint32_t levels = static_cast<uint32_t>(chain.offsets.size());
    return SampleAt(chain, Resolve(ddx, ddy, chain.size, levels, bias), u, v, repeatU, repeatV);
}

std::array<float, 3> SampleLevel0(const Chain& chain, float u, float v, bool repeatU, bool repeatV) {
    Footprint fp;
    fp.magnify = true;
    return SampleAt(chain, fp, u, v, repeatU, repeatV);
}

}  // namespace uzp::evaluator::tu
