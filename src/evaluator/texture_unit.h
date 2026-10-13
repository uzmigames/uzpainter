#pragma once

// The recording GPU's anisotropic texture unit for axis-aligned gradients (decisions 061, 071,
// 083, 084): NVIDIA GeForce RTX 4090, driver 617.14, through Vulkan, sampling a float32 texture
// with its full mip chain through linear min, mag and mip filters with maxAnisotropy 4. Painter's
// BilinearSharp and BilinearHQ minify through this unit (decisions 056, 060). It is all integer
// arithmetic on two measured tables, so this CPU reference and the projection kernel
// (`shaders/evaluator_project.hlsl`) agree bit for bit. Measured with
// `tools/parity/vk_sampler_probe` on synthetic textures (`tables.py` writes the tables and
// validates the whole unit sample for sample against the hardware).
//
// SampleGrad(u, v, ddx, ddy) on a square power-of-two texture of side W with levels 0..M
// (level k of side W >> k, rows bottom up as the GPU stores them):
//
// 1. Footprint. Each gradient is axis-aligned: its larger component carries it, the other is
//    ignored (components below 1e-5 of the larger one change nothing, which covers the float
//    residue of rotations by multiples of 90 degrees). Its length in texels is |g| W, read as a
//    9-bit truncated mantissa m and an exponent e (length in [2^e (1 + m/512), 2^e (1 + (m+1)/512))).
//    The longer gradient is the major axis (the u gradient on a tie), giving the sign s of its
//    component and the axis (x or y) the probes run along.
// 2. LOD in 1/256. lambda_major = Lmaj[m_major] + 256 (e_major - 3). With d = e_major - e_minor,
//    lambda = Lod[d][m_major][m_minor] + 256 (e_major - 3) for d <= 2 and lambda_major - 512
//    otherwise. rho = lambda_major - lambda (0..512, the anisotropy in the LOD domain) and
//    lambda' = lambda + bias (bias in 1/256: 0 or -384 for Painter).
// 3. Levels. With lambda_major <= 0 and lambda' <= 0 the sample is plain magnification: one
//    bilinear probe of weight 256 on level 0. Otherwise the lower level is k = lambda' >> 8 and
//    f = lambda' & 255 (k = 0, f = 0 when lambda' < 0; k = M, f = 0 at or above the last level);
//    the upper level k + 1 weighs t = min(256, floor(7 f / 4)) / 256 and the lower 1 - t.
// 4. Probes. The measured geometry of the cell (rho, f, s) gives each level's probe pairs
//    (p, wl, wr, n): n copies of a probe of weight wl at -p and of one of weight wr at +p, the
//    offsets p in 1/256 texel of that level along the major axis, the weights in 1/(1024 / n)
//    (the level's weights sum to 1024 (1 - t) or 1024 t). A pair at p = 0 is one probe holding
//    both. For f >= 147 (t = 1) the upper level takes the cell's full-weight geometry.
//    A probe at fixed-point position (X, Y) = (floor(256 (u W_k - 1/2) + 1/2), same for v) plus
//    its offset splits its weight w over the 2 x 2 texels at (X >> 8, Y >> 8) by rule F:
//    x1 = rhu(w fx / 256), x0 = w - x1, w11 = rhu(x1 fy / 256), w01 = rhd(x0 fy / 256), with
//    fx = X & 255, fy = Y & 255 and rhu / rhd rounding half up / down; each tap weight is
//    multiplied by n. Repeat addressing wraps the texel indices; clamp-to-edge clamps the
//    probe's fixed-point position to [0, 256 (W_k - 1)].
// 5. Probe sums (decision 071). E is the exponent of the probe's largest texel of non-zero
//    weight (t in [2^(E-1), 2^E)); S = sum over its taps of w floor(t 2^(28 - E)); the value is
//    S 2^(E - 38). A probe whose texels are all 0 adds nothing.
// 6. Accumulation (decision 083). coarse(E) = E - ((E + 126) mod 4). The probes go lower level
//    first, each level's by offset along s (ascending for s > 0), in consecutive pairs per level.
//    Each probe enters truncated to a multiple of 2^(coarse(E) - 36); before each addition after
//    the first, the running sum is truncated to a multiple of 2^(coarse(G) - 36), G the largest
//    E of every pair up to and including the incoming probe's. The sum is rounded to the nearest
//    float32, ties up.
//
// Domain: texels 0 or at least 2^-18 and at most 1 (8- and 16-bit codes and their mip means), so
// every sum fits 64 bits; W a power of two; finite non-zero gradients.
//
// An R8G8B8A8_SRGB texture (decisions 209, 213, 219) takes steps 1-4 unchanged and its own sums:
// 5'. A code's segment exponent is the binary exponent (frexp) of the decode of c | 7. A probe's E
//    is the largest segment exponent of its taps; S = sum over its taps of w floor(d 2^(8 - E)),
//    d = Srgb8Operand(c), worth S 2^(E - 18). A pair at p = 0 is two probes (one per weight, in
//    the table's order) when the cell of the opposite sign holds that pair at p != 0, the pair's
//    true offset being non-zero; otherwise it is one probe.
// 6'. Each probe enters truncated to a multiple of 2^(max(coarse(L), -6) - 16), L the largest E
//    of its level's probes. Before each addition after the first, the running sum is truncated
//    to a multiple of 2^(coarse(G) - 16), G the largest E of the probes of non-zero value whose
//    pair is at or before the incoming probe's; after the last, to 2^(coarse(G) - 16) over every
//    probe. The sum is rounded to the nearest binary16, ties away from zero. One tap of non-zero
//    weight in the whole sample returns its decode.

#include <array>
#include <cstdint>
#include <span>
#include <vector>

namespace uzp::evaluator::tu {

/// The LOD table: 3 x 512 x 512 entries Lod[d][m_major][m_minor] followed by the 512 entries of
/// Lmaj, all for a major exponent of 3 (lambda in 1/256).
inline constexpr uint32_t kLodEntries = 3u * 512u * 512u + 512u;
/// The geometry table: per cell (rho 0..512, f 0..146, sign + then -, role lower then upper)
/// four uint32 words, then per (rho, sign) the full-weight upper geometry (four words).
inline constexpr uint32_t kRhoCells = 513u;
inline constexpr uint32_t kFractions = 147u;
inline constexpr uint32_t kGeometryWords = (kRhoCells * kFractions * 2u * 2u + kRhoCells * 2u) * 4u;
/// A level geometry entry: word 0 = pair count | n0 << 8 | n1 << 16 (0xFF count: not measured),
/// word 1 = p0 | p1 << 16, word 2 = wl0 | wr0 << 16, word 3 = wl1 | wr1 << 16.
inline constexpr uint32_t kUnmeasured = 0xFFu;

/// The inflated tables (built once).
[[nodiscard]] const std::vector<uint16_t>& LodTable();
[[nodiscard]] const std::vector<uint32_t>& GeometryTable();
/// The stored forms (zlib), for the measurement check and the GPU upload.
[[nodiscard]] std::span<const unsigned char> CompressedLod();
[[nodiscard]] std::span<const unsigned char> CompressedGeometry();

/// One RGB float32 mip chain, rows bottom up: level k (side W >> k) starts at `offsets[k]`
/// texels into `texels` (three floats per texel).
struct Chain {
    uint32_t size = 0;
    std::vector<uint32_t> offsets;
    std::vector<float> texels;
    /// An sRGB8 texture (decisions 209, 213, 219): the sRGB8 code of each stored texel channel,
    /// whose decode `Srgb8Operand` `texels` holds. A sample that reads a level past the stored
    /// ones throws. Empty for a float32 texture.
    std::vector<uint8_t> codes;
};

/// Painter's mip chain of level-0 texels (rows bottom up, three per texel; decisions 060, 084):
/// each texel of a level is the GPU's linear filter of the 2 x 2 block above it at the block's
/// centre, the four weights 64/256 (operands floor(t 2^(28 - E)) below the largest texel's
/// exponent E, the sum rounded to float32 ties up).
[[nodiscard]] Chain BuildChain(uint32_t size, std::vector<float> level0);

/// An sRGB8 bitmap's chain (`Chain::codes`): level 0's codes (rows bottom up, three per texel)
/// and the level offsets of its full mip chain. Painter's sRGB8 mip levels are not measured
/// (decision 219), so none is stored.
[[nodiscard]] Chain BuildSrgb8Chain(uint32_t size, std::vector<uint8_t> level0);

/// What a sample resolves to before the texels are read (for tests and the kernel's mirror).
struct Footprint {
    int lambdaMajor = 0;
    int lambda = 0;     ///< before the bias
    int rho = 0;
    int biased = 0;     ///< lambda + bias
    int sign = 1;       ///< the major gradient's sign
    int axis = 0;       ///< 0: the probes run along x, 1: along y
    bool magnify = false;
    uint32_t lower = 0; ///< the lower level
    uint32_t f = 0;     ///< the lower level's fraction (0 when clamped)
};

/// Steps 1-3 for gradients (ddx, ddy) in UV units on a texture of side `size` with `levels`
/// levels and a bias in 1/256.
[[nodiscard]] Footprint Resolve(std::array<float, 2> ddx, std::array<float, 2> ddy, uint32_t size,
                                uint32_t levels, int bias);

/// SampleGrad of the three channels of `chain` at (u, v) (GPU coordinates: v up), repeat or
/// clamp-to-edge per axis. An sRGB8 chain is filtered with the sRGB8 texture's arithmetic
/// (decision 219); it throws when the sample reads a level other than 0.
[[nodiscard]] std::array<float, 3> Sample(const Chain& chain, float u, float v,
                                          std::array<float, 2> ddx, std::array<float, 2> ddy,
                                          int bias, bool repeatU, bool repeatV);

/// One bilinear probe of an sRGB8 texture, summed as steps 5' and 6' sum a single probe: four
/// codes with weights in 1/256 that sum to 256 (projection_uv.cpp's magnification and 1:1 weights,
/// decision 224). It equals decision 209's single-probe rule on every two-tap probe (all code
/// pairs and weights) and on 8 000 000 random four-tap probes (decision 224).
[[nodiscard]] float Srgb8Probe(const std::array<uint32_t, 4>& weights, const std::array<uint32_t, 4>& codes);

/// SampleLevel(u, v, 0): one bilinear probe of weight 256 on level 0 (step 3's magnification).
[[nodiscard]] std::array<float, 3> SampleLevel0(const Chain& chain, float u, float v, bool repeatU,
                                                bool repeatV);

}  // namespace uzp::evaluator::tu
