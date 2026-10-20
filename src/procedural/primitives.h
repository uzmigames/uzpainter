#pragma once

// The shared primitive library of the HLSL procedural families (docs/architecture/
// 05-procedural-content.md §3), written from public literature only (provenance per primitive:
// src/procedural/primitives.provenance.json): Perlin's 1985 and 2002 gradient noise, simplex
// noise, Worley's cellular noise, fBm, and the standard morphological and blur operators.
//
// This file is the CPU reference. `shaders/proc_primitives.hlsli` is its HLSL mirror,
// operation for operation, and the two agree bit for bit:
//
// - Every float operation is one IEEE single operation in a fixed order (the kernels compile
//   IEEE-strict with `precise`, the CPU without contraction).
// - Every float result is flushed to a signed zero when it is subnormal (`Ftz`): a GPU may or
//   may not flush subnormals, so both sides flush them explicitly.
// - There is no division, no hardware square root and no transcendental function. The square
//   root is computed on integers and is correctly rounded (`SqrtRn`, equal to IEEE `sqrt`).
// - Lattice hashing is integer arithmetic (`Pcg3d`), exact on both sides.
//
// Coordinates must be finite with magnitude below 2^23, so that every lattice index converts
// exactly; the families' certified domains keep them inside that range.

#include "procedural/seam.h"

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural::prim {

// ── Arithmetic ───────────────────────────────────────────────────────────────

/// `x`, or a zero of its sign when `x` is subnormal.
[[nodiscard]] float Ftz(float x);
[[nodiscard]] float Add(float a, float b);
[[nodiscard]] float Sub(float a, float b);
[[nodiscard]] float Mul(float a, float b);
/// `Add(a, Mul(t, Sub(b, a)))`.
[[nodiscard]] float Lerp(float a, float b, float t);
/// The correctly rounded square root (IEEE 754 `squareRoot`, round to nearest even) computed
/// with integer arithmetic: a bit-by-bit integer square root of the scaled significand and its
/// exact remainder. Negative inputs give the quiet NaN 0x7FC00000; NaN, zeros and +inf give
/// themselves.
[[nodiscard]] float SqrtRn(float x);

/// Floating-point constants of the library, with the bit patterns the HLSL mirror receives
/// (`ConstantsHlsl`).
struct Constants {
    float simplexF3;     ///< float32(1/3), Gustavson's skew factor (sqrt(4) - 1) / 3.
    float simplexG3;     ///< float32(1/6), Gustavson's unskew factor (1 - 1/sqrt(4)) / 3.
    float simplexG3x2;   ///< 2 G3, rounded once.
    float simplexG3x3;   ///< 3 G3, rounded once.
    float simplexR2;     ///< float32(0.6), the kernel radius squared of Gustavson's 3D code.
    float simplexScale;  ///< 32, Gustavson's 3D output scale.
};
[[nodiscard]] const Constants& Library();

/// `static const float` definitions of `Library()` as bit patterns, for the HLSL mirror.
[[nodiscard]] std::string ConstantsHlsl();

// ── Hashing ──────────────────────────────────────────────────────────────────

using U3 = std::array<uint32_t, 3>;

/// Jarzynski and Olano's `pcg3d` (JCGT 9(3), 2020): a linear congruential step, then two rounds
/// of cross-multiplication with a 16-bit xorshift between them.
[[nodiscard]] U3 Pcg3d(U3 v);
/// The per-seed offset added to every lattice key: `Pcg3d((seed, seed ^ 0x5BD1E995, seed ^
/// 0x27D4EB2F))`.
[[nodiscard]] U3 SeedOffset(uint32_t seed);
/// The hash of lattice cell (i, j, k) under a seed offset: `Pcg3d((i, j, k) + offset)`.
[[nodiscard]] U3 CellHash(int32_t i, int32_t j, int32_t k, const U3& offset);

// ── Noise (scalar fields over 3D points) ─────────────────────────────────────

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

/// Perlin 1985's interpolant 3t^2 - 2t^3, as `t t (3 - 2 t)`.
[[nodiscard]] float Fade1985(float t);
/// Perlin 2002's interpolant 6t^5 - 15t^4 + 10t^3, as `t t t (t (6 t - 15) + 10)`.
[[nodiscard]] float Fade2002(float t);

/// Perlin 1985 gradient noise: a pseudo-random gradient per lattice point (components uniform
/// in [-1, 1), from the cell hash), dot products with the offsets to the eight corners,
/// trilinear interpolation weighted by `Fade1985`. Zero at every lattice point.
[[nodiscard]] float Perlin1985(Vec3 p, uint32_t seed);
/// Perlin 2002 "improved noise": `Fade2002` and the paper's twelve cube-edge gradients chosen
/// by the low four hash bits (`h & 15`, four of the twelve repeated). Zero at every lattice
/// point.
[[nodiscard]] float Perlin2002(Vec3 p, uint32_t seed);
/// 3D simplex noise (Perlin 2001; Gustavson 2005): skew to the simplex lattice, the four
/// corners of the containing simplex by ranking the offsets, radial kernel (0.6 - d^2)^4 and
/// gradient `h % 12` of the cube-edge set, sum scaled by 32.
[[nodiscard]] float Simplex3(Vec3 p, uint32_t seed);

enum class WorleyMetric : uint8_t { Euclidean, Manhattan, Chebyshev };

struct WorleyResult {
    float f1 = 0.0f;     ///< Distance to the nearest feature point.
    float f2 = 0.0f;     ///< Distance to the second nearest.
    uint32_t cell = 0;   ///< The nearest point's cell hash (`CellHash(...)[0]`).
};

/// Worley 1996 cellular noise with one feature point per cell (its offset in [0, 1)^3 from the
/// cell hash), searched over the 27 cells around the point's cell, nearest first by strict
/// comparison in z, y, x order. Euclidean distances are compared squared and rooted with
/// `SqrtRn` at the end.
[[nodiscard]] WorleyResult Worley3(Vec3 p, uint32_t seed, WorleyMetric metric);

enum class FbmBasis : uint8_t { Perlin1985, Perlin2002, Simplex3, WorleyF1 };

/// Fractional Brownian motion (Mandelbrot and Van Ness 1968; Musgrave, in Ebert et al.,
/// "Texturing and Modeling"): the sum over `octaves` of amplitude x basis(p x frequency), the
/// first amplitude and frequency 1, each next one multiplied by `gain` and `lacunarity`; octave
/// i uses seed + i. Not normalised.
[[nodiscard]] float Fbm(FbmBasis basis, Vec3 p, uint32_t seed, uint32_t octaves,
                        float lacunarity, float gain);

// ── Image operators ──────────────────────────────────────────────────────────

enum class Border : uint8_t { Wrap, Clamp };
enum class Footprint : uint8_t { Square, Disk };

/// The texel of `image` at (x, y) after the border rule, every channel flushed by `Ftz`.
[[nodiscard]] float Texel(const Raster& image, int64_t x, int64_t y, uint32_t channel,
                          Border border);

/// Grey-scale dilation (maximum) and erosion (minimum) by a flat structuring element of radius
/// `radius`: the (2r + 1)^2 square, or the disk dx^2 + dy^2 <= r^2. The window is scanned rows
/// top to bottom, texels left to right; a texel replaces the running value only when strictly
/// greater (dilation) or smaller (erosion), so NaN never wins.
[[nodiscard]] Raster Dilate(const Raster& image, uint32_t radius, Footprint footprint,
                            Border border);
[[nodiscard]] Raster Erode(const Raster& image, uint32_t radius, Footprint footprint,
                           Border border);

/// A separable convolution by `weights` (2r + 1 taps, centred): the horizontal pass, then the
/// vertical pass over its result. Each output starts at 0 and adds `Mul(weight k, texel at
/// offset k - r)` for k = 0 ... 2r.
[[nodiscard]] Raster SeparableBlur(const Raster& image, std::span<const float> weights,
                                   Border border);
/// Box filter weights: 2r + 1 copies of float32(1 / (2r + 1)).
[[nodiscard]] std::vector<float> BoxWeights(uint32_t radius);
/// Gaussian weights exp(-k^2 / (2 sigma^2)) for k = -r ... r, computed and normalised to sum
/// 1 in double precision, then rounded to float32 (the host computes them once; the kernels
/// receive the float32 values).
[[nodiscard]] std::vector<float> GaussianWeights(double sigma, uint32_t radius);

/// The names of the primitives above, as the provenance record lists them.
[[nodiscard]] std::span<const std::string_view> PrimitiveNames();

}  // namespace uzp::procedural::prim
