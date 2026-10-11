#pragma once

// The float32 reciprocal, square root and reciprocal square root of the GPU the Tier 0 goldens
// were recorded on (NVIDIA GeForce RTX 4090, D3D12), which Painter's blend kernels use
// (parity/semantics/blend-kernels.json): `Divide`, `ColorBurn`, `ColorDodge` and the HSV modes
// divide through the hardware reciprocal, `SoftLight` takes the hardware square root, the
// normal-map modes normalise through the hardware reciprocal square root. These results are
// faithful (within one unit in the last place) but not correctly rounded, so they are
// reproduced from measured tables on every backend, never from the host's or the GPU's own
// instructions:
//
//   Hw(x) = the correctly rounded result moved by d(x) units in the last place,
//
// with d in {-2, -1, 0, 1} read from `src/evaluator/tables/hw-<op>.zlib`. Each table is a zlib
// stream of little-endian uint32 words holding sixteen 2-bit codes each (code = d + 2, entry i
// at bits 2 (i mod 16) of word i / 16), measured over every float32 of the reduced domain by
// `uzp-evaluator-tests fp-hardware`:
//
//   rcp:   entry m for x = 1 + m 2^-23 in [1, 2) (2^23 entries); 1/x of any normal x scales by
//          its exponent;
//   sqrt, rsqrt: entry i for the i-th float32 in [1, 4) (2^24 entries); y = z 4^k scales the
//          result by 2^k (2^-k).
//
// Inputs outside the normal range follow the measured hardware (the `fp-hardware` case checks
// them): subnormal inputs count as zero of their sign; 1/(+-0) = +-inf, 1/(+-inf) = +-0, and a
// reciprocal below the smallest normal is +-0; sqrt(+-0) = +-0, sqrt(+inf) = +inf, rsqrt(+-0) =
// +-inf, rsqrt(+inf) = +0; sqrt and rsqrt of a negative number and every NaN give the quiet NaN.
//
// The base-2 logarithm and exponential (phase1.11_compositor-mask-effects: Painter's Levels gamma
// is pow(t, gamma), and the GPU's pow is exactly exp2(gamma log2 t)) are not faithful near log2's
// zero, so their tables hold the measured results themselves: four tables of 2^23 float32 bit
// patterns, each a zlib stream of little-endian uint32 second differences (entry i = b[i] -
// 2 b[i-1] + b[i-2] modulo 2^32, b[-1] = b[-2] = 0), measured by `uzp-evaluator-tests
// pow-hardware`:
//
//   lg2-hi:  log2(1 + m 2^-23), in [1, 2);       lg2-lo:  log2((1 + m 2^-23) / 2), in [0.5, 1);
//   ex2-pos: exp2(m 2^-23);                       ex2-neg: exp2(-m 2^-23).
//
// The rest of the domain follows from them (checked on 2^20 hashed inputs over every exponent,
// subnormals, zeros, infinities and NaN): log2(2^e (1 + m 2^-23)) is e + lg2-hi[m] (e >= 1),
// lg2-hi[m] (e = 0), lg2-lo[m] (e = -1) or (e + 1) + lg2-lo[m] (e <= -2), the sum exact in double
// and rounded toward zero to float32; zeros and subnormals give -inf, negative numbers and NaN the
// quiet NaN, +inf gives +inf. exp2(y) splits the magnitude |y| = k + f (integer k, f in [0, 1)),
// truncates f to j = floor(f 2^23) and gives ex2-pos[j] 2^k for y >= 0, ex2-neg[j] 2^-k for
// y < 0; results below 2^-126 flush to +0, results at or above 2^128 are +inf, NaN gives the
// quiet NaN.
//
// The sine and cosine (phase1.11_compositor-blend-gaps: the normal-map modes rotate the upper
// normal by the layer opacity) are the GPU's approximate instruction, which reads its argument
// in turns as a fixed-point number: u = x c rounded toward zero to float32, c = float32(1 /
// (2 pi)) = 0x3E22F983, then k = floor(u 2^25), and the result depends on k alone. Two tables of
// 2^23 float32 bit patterns in the stored form of lg2/ex2 hold sin and cos for k in [0, 2^23),
// which covers every float32 x in [0, float32(pi / 2)] (`uzp-evaluator-tests trig-hardware`
// measures them; the rule was checked on every float32 of that range):
//
//   sin: entry k = sin of any x with k(x) = k;   cos: likewise.
//
// The arcsine is the recording GPU's GLSL `asin` (GLSL.std.450 Asin: equal through Vulkan, which
// Painter 12.1.5 renders with, and OpenGL; the D3D12 `asin` differs), a polynomial in float32 with fused multiply-adds identified on and checked against
// every float32 in [0, 1]: for t = |x| <= 0.57, s = t t, r = ((((c4 s + c3) s + c2) s + c1) s +
// c0) s, asin = fma(r, t, t); above, t' = sqrt(fma(-1/2, t, 1/2)) with the hardware square root
// and asin = fma(-2, P(t'), float32(pi / 2)), P the same polynomial; c0..c4 = 1.666701424e-1,
// 7.484657646e-2, 4.675685871e-2, 1.816697683e-2, 5.175137819e-2 (float32). Subnormal inputs
// give +0, |x| > 1 and NaN the quiet NaN, and the sign of x carries to the result.

#include <cstdint>
#include <span>
#include <vector>

namespace uzp::evaluator::hw {

enum class Op : uint8_t { Rcp, Sqrt, Rsqrt };

/// The tables of the base-2 logarithm and exponential, sine and cosine (above), 2^23 entries each.
enum class Table : uint8_t { Log2Hi, Log2Lo, Exp2Pos, Exp2Neg, Sin, Cos };
inline constexpr uint32_t kTableEntries = 1u << 23;

inline constexpr uint32_t kRcpEntries = 1u << 23;
inline constexpr uint32_t kRootEntries = 1u << 24;

/// The packed delta words of `op` (16 entries per word), inflated once from the embedded table.
[[nodiscard]] const std::vector<uint32_t>& Words(Op op);

/// The measured offset d of entry `index` of `op`, in units in the last place.
[[nodiscard]] int Delta(Op op, uint32_t index);

/// 1 / sqrt(y) correctly rounded to float32 (the reference the rsqrt table is relative to).
[[nodiscard]] float RsqrtCorrect(float y);

/// The hardware results (see above).
[[nodiscard]] float Rcp(float x);
[[nodiscard]] float Sqrt(float y);
[[nodiscard]] float Rsqrt(float y);

/// The table of `op` as stored: the zlib stream of `Words(op)` (the `fp-hardware` case writes a
/// measured table in this form for comparison).
[[nodiscard]] std::span<const unsigned char> Compressed(Op op);

/// The 2^23 result bit patterns of `table`, inflated once on first use (32 MiB each).
[[nodiscard]] const std::vector<uint32_t>& Values(Table table);
/// The stored form of `table` (zlib of the second differences).
[[nodiscard]] std::span<const unsigned char> Compressed(Table table);
/// The stored form of 2^23 measured bit patterns (the `pow-hardware` case writes it).
[[nodiscard]] std::vector<unsigned char> CompressValues(const std::vector<uint32_t>& values);

/// The recording GPU's log2, exp2 and pow(x, g) = exp2(g log2(x)) (the product one float32
/// multiplication), from the tables (above).
[[nodiscard]] float Log2(float x);
[[nodiscard]] float Exp2(float y);
[[nodiscard]] float Pow(float x, float g);

/// The table index k of the GPU's sine and cosine for x in [0, float32(pi / 2)] (above).
[[nodiscard]] uint32_t TrigIndex(float x);
/// The recording GPU's sin and cos for x in [0, float32(pi / 2)], from the tables (above).
[[nodiscard]] float Sin(float x);
[[nodiscard]] float Cos(float x);
/// The recording GPU's GLSL asin (above).
[[nodiscard]] float Asin(float x);

}  // namespace uzp::evaluator::hw
