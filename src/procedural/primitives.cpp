#include "procedural/primitives.h"

#include <bit>
#include <cmath>
#include <cstdio>
#include <string>

namespace uzp::procedural::prim {

namespace {

constexpr float kHash24 = 0x1.0p-23f;  // a 24-bit hash value times 2^-23 is in [0, 2)
constexpr float kUnit24 = 0x1.0p-24f;  // a 24-bit hash value times 2^-24 is in [0, 1)

/// The twelve cube-edge gradients of Gustavson's 3D simplex code (`grad3`).
constexpr int8_t kEdges[12][3] = {{1, 1, 0},  {-1, 1, 0}, {1, -1, 0}, {-1, -1, 0},
                                  {1, 0, 1},  {-1, 0, 1}, {1, 0, -1}, {-1, 0, -1},
                                  {0, 1, 1},  {0, -1, 1}, {0, 1, -1}, {0, -1, -1}};

float Bits(uint32_t bits) { return std::bit_cast<float>(bits); }

/// A 24-bit hash value's float.
float Hash24(uint32_t h) { return static_cast<float>(h >> 8); }

float Dot3(float gx, float gy, float gz, float x, float y, float z) {
    return Add(Add(Mul(gx, x), Mul(gy, y)), Mul(gz, z));
}

/// Perlin 1985's gradient at a lattice point: each component (h >> 8) 2^-23 - 1.
float Grad1985(const U3& h, float x, float y, float z) {
    const float gx = Sub(Mul(Hash24(h[0]), kHash24), 1.0f);
    const float gy = Sub(Mul(Hash24(h[1]), kHash24), 1.0f);
    const float gz = Sub(Mul(Hash24(h[2]), kHash24), 1.0f);
    return Dot3(gx, gy, gz, x, y, z);
}

/// Perlin 2002's `grad(hash, x, y, z)`: u is x for h < 8, else y; v is y for h < 4, x for h
/// 12 or 14, else z; their signs from bits 0 and 1.
float Grad2002(uint32_t hash, float x, float y, float z) {
    const uint32_t h = hash & 15u;
    const float u = h < 8u ? x : y;
    const float v = h < 4u ? y : (h == 12u || h == 14u ? x : z);
    return Add((h & 1u) == 0u ? u : -u, (h & 2u) == 0u ? v : -v);
}

template <class Corner>
float Lattice(Vec3 p, uint32_t seed, float (*fade)(float), Corner corner) {
    const float fx = std::floor(p.x);
    const float fy = std::floor(p.y);
    const float fz = std::floor(p.z);
    const int32_t i = static_cast<int32_t>(fx);
    const int32_t j = static_cast<int32_t>(fy);
    const int32_t k = static_cast<int32_t>(fz);
    const float x = Sub(p.x, fx);
    const float y = Sub(p.y, fy);
    const float z = Sub(p.z, fz);
    const float x1 = Sub(x, 1.0f);
    const float y1 = Sub(y, 1.0f);
    const float z1 = Sub(z, 1.0f);
    const U3 offset = SeedOffset(seed);
    const float n000 = corner(CellHash(i, j, k, offset), x, y, z);
    const float n100 = corner(CellHash(i + 1, j, k, offset), x1, y, z);
    const float n010 = corner(CellHash(i, j + 1, k, offset), x, y1, z);
    const float n110 = corner(CellHash(i + 1, j + 1, k, offset), x1, y1, z);
    const float n001 = corner(CellHash(i, j, k + 1, offset), x, y, z1);
    const float n101 = corner(CellHash(i + 1, j, k + 1, offset), x1, y, z1);
    const float n011 = corner(CellHash(i, j + 1, k + 1, offset), x, y1, z1);
    const float n111 = corner(CellHash(i + 1, j + 1, k + 1, offset), x1, y1, z1);
    const float u = fade(x);
    const float v = fade(y);
    const float w = fade(z);
    const float a = Lerp(Lerp(n000, n100, u), Lerp(n010, n110, u), v);
    const float b = Lerp(Lerp(n001, n101, u), Lerp(n011, n111, u), v);
    return Lerp(a, b, w);
}

/// One corner of a simplex: (0.6 - d^2)^4 times the gradient's dot product, 0 outside.
float SimplexCorner(const U3& hash, float x, float y, float z) {
    const Constants& c = Library();
    const float t = Sub(Sub(Sub(c.simplexR2, Mul(x, x)), Mul(y, y)), Mul(z, z));
    if (t < 0.0f) return 0.0f;
    const int8_t* g = kEdges[hash[0] % 12u];
    const float t2 = Mul(t, t);
    return Mul(Mul(t2, t2), Dot3(g[0], g[1], g[2], x, y, z));
}

/// e^y for y <= 0 with IEEE double additions, multiplications and divisions only (so every
/// machine computes the same value): y halved until |y| <= 1/2, a 24-term Taylor series,
/// then squared back.
double DeterministicExp(double y) {
    int halvings = 0;
    while (y < -0.5) {
        y *= 0.5;
        ++halvings;
    }
    double term = 1.0;
    double sum = 1.0;
    for (int n = 1; n <= 24; ++n) {
        term = term * y / n;
        sum += term;
    }
    for (int i = 0; i < halvings; ++i) sum *= sum;
    return sum;
}

Raster Morph(const Raster& image, uint32_t radius, Footprint footprint, Border border,
             bool dilate) {
    Raster out{image.width, image.height, image.channels, {}};
    out.texels.resize(image.texels.size());
    const int64_t r = radius;
    for (uint32_t y = 0; y < image.height; ++y) {
        for (uint32_t x = 0; x < image.width; ++x) {
            for (uint32_t c = 0; c < image.channels; ++c) {
                float best = Texel(image, x, y, c, border);
                for (int64_t dy = -r; dy <= r; ++dy) {
                    for (int64_t dx = -r; dx <= r; ++dx) {
                        if (footprint == Footprint::Disk && dx * dx + dy * dy > r * r) continue;
                        const float v = Texel(image, int64_t{x} + dx, int64_t{y} + dy, c, border);
                        if (dilate ? v > best : v < best) best = v;
                    }
                }
                out.texels[(size_t{y} * image.width + x) * image.channels + c] = best;
            }
        }
    }
    return out;
}

}  // namespace

float Ftz(float x) {
    const uint32_t b = std::bit_cast<uint32_t>(x);
    return (b & 0x7F800000u) == 0u ? Bits(b & 0x80000000u) : x;
}

float Add(float a, float b) { return Ftz(a + b); }
float Sub(float a, float b) { return Ftz(a - b); }
float Mul(float a, float b) { return Ftz(a * b); }
float Lerp(float a, float b, float t) { return Add(a, Mul(t, Sub(b, a))); }

float SqrtRn(float x) {
    const uint32_t b = std::bit_cast<uint32_t>(x);
    const uint32_t e = (b >> 23) & 0xFFu;
    if (e == 0xFFu) return (b & 0x007FFFFFu) != 0u || (b >> 31) == 0u ? x : Bits(0x7FC00000u);
    if (e == 0u) return Bits(b & 0x80000000u);  // a zero (subnormals are flushed)
    if ((b >> 31) != 0u) return Bits(0x7FC00000u);
    // x = m 2^q with m the 24-bit significand; scaled so that q is even and m in [2^24, 2^26).
    uint64_t m = (b & 0x007FFFFFu) | 0x00800000u;
    int32_t q = static_cast<int32_t>(e) - 150;
    if ((q & 1) != 0) {
        m <<= 1;
        q -= 1;
    } else {
        m <<= 2;
        q -= 2;
    }
    // sqrt(m 2^24) is in [2^24, 2^25): 25 bits, the last one the rounding bit.
    uint64_t n = m << 24;
    uint64_t root = 0;
    uint64_t bit = uint64_t{1} << 50;
    while (bit > n) bit >>= 2;
    while (bit != 0) {
        if (n >= root + bit) {
            n -= root + bit;
            root = (root >> 1) + bit;
        } else {
            root >>= 1;
        }
        bit >>= 2;
    }
    uint32_t significand = static_cast<uint32_t>(root >> 1);
    if ((root & 1u) != 0u && (n != 0u || (significand & 1u) != 0u)) ++significand;
    int32_t exponent = q / 2 + 12 + 127;  // sqrt(x) = (root / 2) 2^(q/2 - 11), root / 2 < 2^24
    if (significand == 0x01000000u) {
        significand >>= 1;
        ++exponent;
    }
    return Bits(static_cast<uint32_t>(exponent) << 23 | (significand & 0x007FFFFFu));
}

const Constants& Library() {
    static const Constants constants = [] {
        Constants c;
        c.simplexF3 = static_cast<float>(1.0 / 3.0);
        c.simplexG3 = static_cast<float>(1.0 / 6.0);
        c.simplexG3x2 = 2.0f * c.simplexG3;
        c.simplexG3x3 = 3.0f * c.simplexG3;
        c.simplexR2 = 0.6f;
        c.simplexScale = 32.0f;
        return c;
    }();
    return constants;
}

std::string ConstantsHlsl() {
    const Constants& c = Library();
    const std::pair<const char*, float> named[] = {
        {"kSimplexF3", c.simplexF3},   {"kSimplexG3", c.simplexG3},
        {"kSimplexG3x2", c.simplexG3x2}, {"kSimplexG3x3", c.simplexG3x3},
        {"kSimplexR2", c.simplexR2},   {"kSimplexScale", c.simplexScale},
    };
    std::string text = "// Generated by src/procedural/primitives.cpp (ConstantsHlsl).\n";
    char line[96];
    for (const auto& [name, value] : named) {
        std::snprintf(line, sizeof(line), "static const float %s = asfloat(0x%08Xu);\n", name,
                      std::bit_cast<uint32_t>(value));
        text += line;
    }
    return text;
}

U3 Pcg3d(U3 v) {
    for (uint32_t& c : v) c = c * 1664525u + 1013904223u;
    v[0] += v[1] * v[2];
    v[1] += v[2] * v[0];
    v[2] += v[0] * v[1];
    for (uint32_t& c : v) c ^= c >> 16u;
    v[0] += v[1] * v[2];
    v[1] += v[2] * v[0];
    v[2] += v[0] * v[1];
    return v;
}

U3 SeedOffset(uint32_t seed) { return Pcg3d({seed, seed ^ 0x5BD1E995u, seed ^ 0x27D4EB2Fu}); }

U3 CellHash(int32_t i, int32_t j, int32_t k, const U3& offset) {
    return Pcg3d({static_cast<uint32_t>(i) + offset[0], static_cast<uint32_t>(j) + offset[1],
                  static_cast<uint32_t>(k) + offset[2]});
}

float Fade1985(float t) { return Mul(Mul(t, t), Sub(3.0f, Mul(2.0f, t))); }

float Fade2002(float t) {
    return Mul(Mul(Mul(t, t), t), Add(Mul(t, Sub(Mul(t, 6.0f), 15.0f)), 10.0f));
}

float Perlin1985(Vec3 p, uint32_t seed) { return Lattice(p, seed, Fade1985, Grad1985); }

float Perlin2002(Vec3 p, uint32_t seed) {
    return Lattice(p, seed, Fade2002, [](const U3& h, float x, float y, float z) {
        return Grad2002(h[0], x, y, z);
    });
}

float Simplex3(Vec3 p, uint32_t seed) {
    const Constants& c = Library();
    const float s = Mul(Add(Add(p.x, p.y), p.z), c.simplexF3);
    const float fi = std::floor(Add(p.x, s));
    const float fj = std::floor(Add(p.y, s));
    const float fk = std::floor(Add(p.z, s));
    const float t = Mul(Add(Add(fi, fj), fk), c.simplexG3);
    const float x0 = Sub(p.x, Sub(fi, t));
    const float y0 = Sub(p.y, Sub(fj, t));
    const float z0 = Sub(p.z, Sub(fk, t));
    // The second and third corners: offsets of the simplex the point is in, by rank.
    int32_t i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
        if (y0 >= z0) {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        } else if (x0 >= z0) {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1;
        } else {
            i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1;
        }
    } else {
        if (y0 < z0) {
            i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1;
        } else if (x0 < z0) {
            i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1;
        } else {
            i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        }
    }
    const float x1 = Add(Sub(x0, static_cast<float>(i1)), c.simplexG3);
    const float y1 = Add(Sub(y0, static_cast<float>(j1)), c.simplexG3);
    const float z1 = Add(Sub(z0, static_cast<float>(k1)), c.simplexG3);
    const float x2 = Add(Sub(x0, static_cast<float>(i2)), c.simplexG3x2);
    const float y2 = Add(Sub(y0, static_cast<float>(j2)), c.simplexG3x2);
    const float z2 = Add(Sub(z0, static_cast<float>(k2)), c.simplexG3x2);
    const float x3 = Add(Sub(x0, 1.0f), c.simplexG3x3);
    const float y3 = Add(Sub(y0, 1.0f), c.simplexG3x3);
    const float z3 = Add(Sub(z0, 1.0f), c.simplexG3x3);
    const int32_t i = static_cast<int32_t>(fi);
    const int32_t j = static_cast<int32_t>(fj);
    const int32_t k = static_cast<int32_t>(fk);
    const U3 offset = SeedOffset(seed);
    const float n0 = SimplexCorner(CellHash(i, j, k, offset), x0, y0, z0);
    const float n1 = SimplexCorner(CellHash(i + i1, j + j1, k + k1, offset), x1, y1, z1);
    const float n2 = SimplexCorner(CellHash(i + i2, j + j2, k + k2, offset), x2, y2, z2);
    const float n3 = SimplexCorner(CellHash(i + 1, j + 1, k + 1, offset), x3, y3, z3);
    return Mul(c.simplexScale, Add(Add(Add(n0, n1), n2), n3));
}

WorleyResult Worley3(Vec3 p, uint32_t seed, WorleyMetric metric) {
    const float fx = std::floor(p.x);
    const float fy = std::floor(p.y);
    const float fz = std::floor(p.z);
    const int32_t i = static_cast<int32_t>(fx);
    const int32_t j = static_cast<int32_t>(fy);
    const int32_t k = static_cast<int32_t>(fz);
    const U3 offset = SeedOffset(seed);
    float f1 = Bits(0x7F800000u);  // +inf
    float f2 = Bits(0x7F800000u);
    uint32_t cell = 0;
    for (int32_t dz = -1; dz <= 1; ++dz) {
        for (int32_t dy = -1; dy <= 1; ++dy) {
            for (int32_t dx = -1; dx <= 1; ++dx) {
                const U3 h = CellHash(i + dx, j + dy, k + dz, offset);
                const float px = Add(static_cast<float>(i + dx), Mul(Hash24(h[0]), kUnit24));
                const float py = Add(static_cast<float>(j + dy), Mul(Hash24(h[1]), kUnit24));
                const float pz = Add(static_cast<float>(k + dz), Mul(Hash24(h[2]), kUnit24));
                const float ox = Sub(px, p.x);
                const float oy = Sub(py, p.y);
                const float oz = Sub(pz, p.z);
                float d;
                if (metric == WorleyMetric::Euclidean) {
                    d = Add(Add(Mul(ox, ox), Mul(oy, oy)), Mul(oz, oz));
                } else {
                    const float ax = std::fabs(ox);
                    const float ay = std::fabs(oy);
                    const float az = std::fabs(oz);
                    if (metric == WorleyMetric::Manhattan) {
                        d = Add(Add(ax, ay), az);
                    } else {
                        const float axy = ay > ax ? ay : ax;
                        d = az > axy ? az : axy;
                    }
                }
                if (d < f1) {
                    f2 = f1;
                    f1 = d;
                    cell = h[0];
                } else if (d < f2) {
                    f2 = d;
                }
            }
        }
    }
    if (metric == WorleyMetric::Euclidean) {
        f1 = SqrtRn(f1);
        f2 = SqrtRn(f2);
    }
    return WorleyResult{f1, f2, cell};
}

float Fbm(FbmBasis basis, Vec3 p, uint32_t seed, uint32_t octaves, float lacunarity,
          float gain) {
    float sum = 0.0f;
    float amplitude = 1.0f;
    Vec3 q = p;
    for (uint32_t octave = 0; octave < octaves; ++octave) {
        const uint32_t s = seed + octave;
        float n = 0.0f;
        switch (basis) {
            case FbmBasis::Perlin1985: n = Perlin1985(q, s); break;
            case FbmBasis::Perlin2002: n = Perlin2002(q, s); break;
            case FbmBasis::Simplex3: n = Simplex3(q, s); break;
            case FbmBasis::WorleyF1: n = Worley3(q, s, WorleyMetric::Euclidean).f1; break;
        }
        sum = Add(sum, Mul(amplitude, n));
        q = Vec3{Mul(q.x, lacunarity), Mul(q.y, lacunarity), Mul(q.z, lacunarity)};
        amplitude = Mul(amplitude, gain);
    }
    return sum;
}

float Texel(const Raster& image, int64_t x, int64_t y, uint32_t channel, Border border) {
    const int64_t w = image.width;
    const int64_t h = image.height;
    if (border == Border::Wrap) {
        x = ((x % w) + w) % w;
        y = ((y % h) + h) % h;
    } else {
        x = x < 0 ? 0 : (x >= w ? w - 1 : x);
        y = y < 0 ? 0 : (y >= h ? h - 1 : y);
    }
    return Ftz(image.texels[(static_cast<size_t>(y) * image.width + static_cast<size_t>(x)) *
                                image.channels +
                            channel]);
}

Raster Dilate(const Raster& image, uint32_t radius, Footprint footprint, Border border) {
    return Morph(image, radius, footprint, border, true);
}

Raster Erode(const Raster& image, uint32_t radius, Footprint footprint, Border border) {
    return Morph(image, radius, footprint, border, false);
}

Raster SeparableBlur(const Raster& image, std::span<const float> weights, Border border) {
    const int64_t r = static_cast<int64_t>(weights.size() / 2);
    const auto pass = [&](const Raster& in, bool horizontal) {
        Raster out{in.width, in.height, in.channels, {}};
        out.texels.resize(in.texels.size());
        for (uint32_t y = 0; y < in.height; ++y) {
            for (uint32_t x = 0; x < in.width; ++x) {
                for (uint32_t c = 0; c < in.channels; ++c) {
                    float sum = 0.0f;
                    for (int64_t k = 0; k <= 2 * r; ++k) {
                        const int64_t tx = horizontal ? int64_t{x} + k - r : int64_t{x};
                        const int64_t ty = horizontal ? int64_t{y} : int64_t{y} + k - r;
                        sum = Add(sum, Mul(weights[static_cast<size_t>(k)],
                                           Texel(in, tx, ty, c, border)));
                    }
                    out.texels[(size_t{y} * in.width + x) * in.channels + c] = sum;
                }
            }
        }
        return out;
    };
    return pass(pass(image, true), false);
}

std::vector<float> BoxWeights(uint32_t radius) {
    const float w = static_cast<float>(1.0 / (2.0 * radius + 1.0));
    return std::vector<float>(size_t{2} * radius + 1, w);
}

std::vector<float> GaussianWeights(double sigma, uint32_t radius) {
    std::vector<double> exact;
    double total = 0.0;
    for (int64_t k = -int64_t{radius}; k <= int64_t{radius}; ++k) {
        const double value = DeterministicExp(-double(k * k) / (2.0 * sigma * sigma));
        exact.push_back(value);
        total += value;
    }
    std::vector<float> weights;
    for (const double value : exact) weights.push_back(static_cast<float>(value / total));
    return weights;
}

std::span<const std::string_view> PrimitiveNames() {
    static constexpr std::string_view kNames[] = {
        "SqrtRn",   "Pcg3d",  "Perlin1985", "Perlin2002",    "Simplex3",
        "Worley3",  "Fbm",    "Dilate",     "Erode",         "SeparableBlur",
        "BoxWeights", "GaussianWeights",
    };
    return kNames;
}

}  // namespace uzp::procedural::prim
