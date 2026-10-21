#pragma once

// Owen-scrambled Sobol sampling of the `painter_iray` path tracer, indexed by (pixel, sample,
// dimension) under the render's fixed seed (rulebook task phase3.4_path-tracer-transport item
// 2.4; docs/architecture/07-preview-and-render-parity.md §3.2). CPU reference: the transport
// kernel's HLSL mirror is written and checked against it with item 2.7.
//
// Sources (docs/approved-sources.md): P-BURLEY2020, Burley 2020, *Practical Hash-based Owen
// Scrambling*, JCGT 9(4): the improved Laine-Karras permutation, nested uniform (Owen)
// scrambling of a 32-bit fixed-point value by bit reversal around that permutation, the
// hash_combine seed mixing and the shuffled, scrambled 4D Sobol sequence padded to further
// dimensions by independently seeded copies; P-PBRT, *Physically Based Rendering*
// 4th ed. §8.7 (Sobol samplers): Sobol generator matrices from primitive polynomials and initial
// direction numbers m_i (dimension 0 the van der Corput sequence; dimensions 1-3 the polynomials
// x + 1, x^2 + x + 1 and x^3 + x + 1 with m = (1), (1, 3) and (1, 3, 1)).
//
// The algorithm is the one of the Phase 0 render prototype (tools/parity/render_fits/sampler.py,
// parity/semantics/iray.json entry `transport`); tests/render/test_pathtracer_sampler.py checks
// that both give the same bits on a grid of seeds, pixels, sample indices and dimensions.
//
// - Pixel seed: s_p = LK(LK(pixel, seed), seed * 0x2545F491), uint32 wrap-around.
// - Dimension d belongs to the 4D set k = d / 4 as its component c = d % 4. The set seed is
//   s_k = hash_combine(s_p, k); the sample index is shuffled per set, i' = Owen(i, s_k), and the
//   value is Owen(Sobol_c(i'), hash_combine(s_k, c)).
//
// Every component is a (0,1)-sequence and components 0 and 1 of one set a (0,2)-sequence: any
// aligned block of 2^m sample indices puts exactly one value in each interval [j/2^m, (j+1)/2^m)
// of a component and one point in each elementary box of area 2^-m of components (0, 1).
// Distinct sets are decorrelated by their seeds, not stratified against each other.

#include <cstdint>

namespace uzp::render::pathtracer {

/// Dimensions of one Sobol set; dimension d is component d % 4 of set d / 4.
inline constexpr uint32_t kSobolSetDimensions = 4;

/// The bits of `x` in reverse order (bit 0 becomes bit 31).
uint32_t ReverseBits(uint32_t x);

/// Burley 2020: the improved Laine-Karras hash. Bit k of the result depends only on
/// bits 0..k of `x`, so applied to bit-reversed values it is a nested (Owen) permutation.
uint32_t LaineKarrasPermutation(uint32_t x, uint32_t seed);

/// Burley 2020: Owen scrambling of the 32-bit fixed-point value `x` (x / 2^32).
uint32_t NestedUniformScramble(uint32_t x, uint32_t seed);

/// Burley 2020's seed mixing: seed ^ (value + 0x9E3779B9 + (seed << 6) + (seed >> 2)).
uint32_t HashCombine(uint32_t seed, uint32_t value);

/// Unscrambled Sobol value of component `component` (0-3) for `index`, as 32-bit fixed point:
/// the XOR of the generator's direction numbers selected by the set bits of `index`.
uint32_t Sobol(uint32_t index, uint32_t component);

/// Direction number `bit` (0-31) of component `component` (0-3): column `bit` of its generator
/// matrix as a 32-bit fixed-point value.
uint32_t SobolDirection(uint32_t component, uint32_t bit);

/// The scramble seed of pixel `pixel` (row-major index y * width + x) under `render_seed`.
uint32_t PixelSeed(uint32_t pixel, uint32_t render_seed);

/// Sample `index` of dimension `dimension` for a pixel seed, as 32-bit fixed point.
uint32_t SampleBits(uint32_t pixel_seed, uint32_t index, uint32_t dimension);

/// `SampleBits` as a float in [0, 1): its top 24 bits times 2^-24, exact in binary32 and
/// never 1 (the transport is fp32).
float SampleFloat(uint32_t pixel_seed, uint32_t index, uint32_t dimension);

/// The float in [0, 1) of a 32-bit fixed-point value (top 24 bits times 2^-24).
float FixedToFloat(uint32_t bits);

}  // namespace uzp::render::pathtracer
