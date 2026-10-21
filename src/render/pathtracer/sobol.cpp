#include "render/pathtracer/sobol.h"

#include <array>

namespace uzp::render::pathtracer {
namespace {

constexpr uint32_t kBits = 32;
constexpr uint32_t kGolden = 0x9E3779B9u;  // Burley 2020's hash_combine constant

struct Polynomial {
    uint32_t degree;       // s
    uint32_t coefficients; // a: the inner coefficients, most significant first
    std::array<uint32_t, 3> initial;  // m_1 .. m_s
};

// P-PBRT 4th ed. §8.7: Sobol dimensions 1-3 (dimension 0 is the van der Corput sequence).
constexpr std::array<Polynomial, 3> kPolynomials = {{
    {1, 0, {1, 0, 0}},
    {2, 1, {1, 3, 0}},
    {3, 1, {1, 3, 1}},
}};

// Direction numbers v_1 .. v_32 of each component as 32-bit fixed point: v_i = m_i 2^(32 - i)
// for i <= s, then v_i = v_(i-s) ^ (v_(i-s) >> s) ^ XOR over k in 1..s-1 with a_k set of v_(i-k).
constexpr std::array<std::array<uint32_t, kBits>, kSobolSetDimensions> MakeDirections() {
    std::array<std::array<uint32_t, kBits>, kSobolSetDimensions> table{};
    for (uint32_t k = 0; k < kBits; ++k) table[0][k] = 1u << (kBits - 1 - k);
    for (uint32_t c = 1; c < kSobolSetDimensions; ++c) {
        const Polynomial& p = kPolynomials[c - 1];
        std::array<uint32_t, kBits + 1> v{};
        for (uint32_t i = 1; i <= p.degree; ++i) v[i] = p.initial[i - 1] << (kBits - i);
        for (uint32_t i = p.degree + 1; i <= kBits; ++i) {
            uint32_t value = v[i - p.degree] ^ (v[i - p.degree] >> p.degree);
            for (uint32_t k = 1; k < p.degree; ++k) {
                if ((p.coefficients >> (p.degree - 1 - k)) & 1u) value ^= v[i - k];
            }
            v[i] = value;
        }
        for (uint32_t i = 0; i < kBits; ++i) table[c][i] = v[i + 1];
    }
    return table;
}

constexpr auto kDirections = MakeDirections();

}  // namespace

uint32_t ReverseBits(uint32_t x) {
    x = ((x >> 1) & 0x55555555u) | ((x & 0x55555555u) << 1);
    x = ((x >> 2) & 0x33333333u) | ((x & 0x33333333u) << 2);
    x = ((x >> 4) & 0x0F0F0F0Fu) | ((x & 0x0F0F0F0Fu) << 4);
    x = ((x >> 8) & 0x00FF00FFu) | ((x & 0x00FF00FFu) << 8);
    return (x >> 16) | (x << 16);
}

uint32_t LaineKarrasPermutation(uint32_t x, uint32_t seed) {
    // P-BURLEY2020: the improved Laine-Karras permutation.
    x += seed;
    x ^= x * 0x6C50B47Cu;
    x ^= x * 0xB82F1E52u;
    x ^= x * 0xC7AFE638u;
    x ^= x * 0x8D22F6E6u;
    return x;
}

uint32_t NestedUniformScramble(uint32_t x, uint32_t seed) {
    // P-BURLEY2020: nested uniform scrambling by bit reversal.
    return ReverseBits(LaineKarrasPermutation(ReverseBits(x), seed));
}

uint32_t HashCombine(uint32_t seed, uint32_t value) {
    return seed ^ (value + kGolden + (seed << 6) + (seed >> 2));
}

uint32_t SobolDirection(uint32_t component, uint32_t bit) {
    return kDirections[component % kSobolSetDimensions][bit % kBits];
}

uint32_t Sobol(uint32_t index, uint32_t component) {
    const auto& v = kDirections[component % kSobolSetDimensions];
    uint32_t result = 0;
    for (uint32_t bit = 0; index != 0; ++bit, index >>= 1) {
        if (index & 1u) result ^= v[bit];
    }
    return result;
}

uint32_t PixelSeed(uint32_t pixel, uint32_t render_seed) {
    return LaineKarrasPermutation(LaineKarrasPermutation(pixel, render_seed),
                                  render_seed * 0x2545F491u);
}

uint32_t SampleBits(uint32_t pixel_seed, uint32_t index, uint32_t dimension) {
    // P-BURLEY2020 shuffled_scrambled_sobol4d, padded by one seed per 4D set.
    const uint32_t set_seed = HashCombine(pixel_seed, dimension / kSobolSetDimensions);
    const uint32_t component = dimension % kSobolSetDimensions;
    const uint32_t shuffled = NestedUniformScramble(index, set_seed);
    return NestedUniformScramble(Sobol(shuffled, component), HashCombine(set_seed, component));
}

float FixedToFloat(uint32_t bits) {
    return static_cast<float>(bits >> 8) * 0x1p-24f;
}

float SampleFloat(uint32_t pixel_seed, uint32_t index, uint32_t dimension) {
    return FixedToFloat(SampleBits(pixel_seed, index, dimension));
}

}  // namespace uzp::render::pathtracer
