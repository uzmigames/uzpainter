#pragma once

// Scalar arithmetic of the compositor (docs/architecture/04-layer-stack-and-compositing.md §3-§4),
// written once here for the CPU and mirrored operation for operation by the generated kernels
// (kernelgen.h, shaders/evaluator_blend.hlsl), so both backends produce the same bits:
//
// - operands from storage (parity/semantics/blend-modes.json, "Operands"): UNORM codes as
//   float32(code / M) through lookup tables; sRGB8 codes as the IEC 61966-2-1 decode on 8
//   significant bits; floats as stored;
// - the blend kernels of parity/semantics/blend-kernels.json in float32 with the fused
//   multiply-adds the goldens show (one rounding each), the recording GPU's reciprocal and
//   square roots where Painter divides or takes roots (hwmath.h), and the opacity mix
//   v = a (1 - alpha) + r alpha (Replace: a + (r - a) alpha; ColorBurn: fma(a, 1 - alpha, r alpha));
// - the write rules ("Write"): UNORM n bits truncated to n + 4 fractional bits then the nearest
//   code, ties down; sRGB8 round(255 encode(v)); 16-bit float toward zero; 32-bit float as it
//   is, re-composited over the channel base (1 + (v - 1)) once at read-out;
// - the isolated-group composite (W3C Compositing and Blending Level 1 §5.1, §6; approved source
//   S-W3C-BLEND) that the Tier 0 `group-masks` golden confirms for groups without masks, and the
//   coverage-weighted float32 order of the source-over onto a backdrop that is not opaque
//   (CompositeInput::coverageWeights; Tier 0 `group-coverage-order`).
//
// Every float32 operation is a single IEEE operation (the sources are compiled with contraction
// off); "Fma" is the float32 rounding of the exact x y + z (the product of two floats is exact
// in double, so one double addition and one conversion give it).

#include <array>
#include <cstdint>
#include <vector>

#include "uzp_core/types/enums.h"

namespace uzp::evaluator::arith {

[[nodiscard]] float Fma(float x, float y, float z);
/// 1 / x correctly rounded to float32 (+-inf for +-0).
[[nodiscard]] float Rcp(float x);
/// sqrt(x) correctly rounded to float32 (NaN below zero).
[[nodiscard]] float Sqrt(float x);
/// IEEE minNum / maxNum: the other operand when one is NaN (HLSL min / max, numpy fmin / fmax).
[[nodiscard]] float Fmin(float x, float y);
[[nodiscard]] float Fmax(float x, float y);
/// NaN-propagating minimum / maximum (numpy minimum / maximum).
[[nodiscard]] float MinNan(float x, float y);
[[nodiscard]] float MaxNan(float x, float y);
[[nodiscard]] float Clamp01(float x);

/// The separable modes (Normal, Replace, Disable, Multiply ... PinLight): one kernel per
/// channel (`BlendKernel`).
[[nodiscard]] bool HasSeparableKernel(core::BlendingMode mode);
/// The component modes (Tint, Saturation, Color, Value) and the normal-map modes
/// (NormalMapCombine, NormalMapDetail, NormalMapInverseDetail): one kernel per texel over the
/// three components (`BlendColour`).
[[nodiscard]] bool HasColourKernel(core::BlendingMode mode);
/// Every mode with a kernel: all 31 modes but PassThrough, which is a group placement.
[[nodiscard]] bool HasKernel(core::BlendingMode mode);
/// r of blend-kernels.json for the lower value `a` and the upper value `b` (float32) of a
/// separable mode; Divide, ColorBurn, ColorDodge and VividLight divide through the hardware
/// reciprocal and SoftLight takes the hardware square root (hwmath.h).
[[nodiscard]] float BlendKernel(core::BlendingMode mode, float a, float b);
/// r of a colour mode for the lower colour `a` and the upper colour `b` (`channels` 1 or 3).
/// Three components: the component modes through HSV (hue, saturation or value of the upper
/// colour, the value doubled), the normal-map modes on the decoded unit normals with the upper
/// one first rotated toward (0, 0, 1) by `alpha` (whiteout for Combine, reoriented normal mapping
/// for Detail and InverseDetail), encoded back as n / 2 + 1/2. One component (grey): Value and
/// the normal-map modes give `b`, Tint, Saturation and Color give `a`.
[[nodiscard]] std::array<float, 3> BlendColour(core::BlendingMode mode, const std::array<float, 3>& a,
                                               const std::array<float, 3>& b, int channels, float alpha);

/// float32 constants of the colour kernels, shared bit for bit with the generated kernels
/// (kernelgen.cpp writes them into `evaluator_tables.hlsli`).
/// The saturation and hue epsilon of the HSV conversion (fitted: 2^-12).
inline constexpr float kHsvEpsilon = 0.000244140625f;
inline constexpr float kThird = 1.0f / 3.0f;
inline constexpr float kTwoThirds = 2.0f / 3.0f;
inline constexpr float kHalfPi = 1.57079632679489661923f;
/// asin(t) / t as a series in t^2: (2k)! / (4^k (k!)^2 (2k + 1)), k = 0..11.
inline constexpr std::array<float, 12> kAsinSeries = {
    1.0f, 1.0f / 6.0f, 3.0f / 40.0f, 15.0f / 336.0f, 105.0f / 3456.0f, 945.0f / 42240.0f,
    10395.0f / 599040.0f, 135135.0f / 9676800.0f, 2027025.0f / 175472640.0f,
    34459425.0f / 3530096640.0f, 654729075.0f / 78033715200.0f,
    13749310575.0f / 1880240947200.0f};
/// sin(x) / x as a series in x^2: (-1)^k / (2k + 1)!, k = 0..8.
inline constexpr std::array<float, 9> kSinSeries = {
    1.0f, -1.0f / 6.0f, 1.0f / 120.0f, -1.0f / 5040.0f, 1.0f / 362880.0f, -1.0f / 39916800.0f,
    1.0f / 6227020800.0f, -1.0f / 1307674368000.0f, 1.0f / 355687428096000.0f};

// ── Storage ──────────────────────────────────────────────────────────────────

/// UNORM write rule: v clamped to [0, 1] (NaN to 0), j = floor(v 2^(n+4)),
/// code = (j (2^n - 1) + 2^(n+3) - 1) >> (n+4).
[[nodiscard]] uint32_t WriteUnorm(float v, uint32_t bits);
/// float32(code / (2^bits - 1)), the operand of a stored UNORM code.
[[nodiscard]] float UnormOperand(uint32_t code, uint32_t bits);

/// IEC 61966-2-1 transfer functions in double precision.
[[nodiscard]] double SrgbDecode(double encoded);
[[nodiscard]] double SrgbEncode(double linear);
/// `x` rounded to `bits` significant binary digits (nearest), keeping its exponent.
[[nodiscard]] double SignificandRound(double x, int bits);
/// The linear operand of an sRGB8 code (`Srgb8OperandTable`): the recording GPU's sRGB8 decode,
/// which lies within 2^-8 relative of the IEC decode on 8 significant bits but differs from it on
/// 29 codes (parity/semantics/colour-transfer.json).
[[nodiscard]] float Srgb8Operand(uint32_t code);
/// The sRGB8 code of a linear value: the number of thresholds of `Srgb8Thresholds` at or below v
/// (v clamped to [0, 1], NaN to 0). This is the GPU's float-to-sRGB8 conversion Painter stores
/// through, not round(255 encode(v)): the IEC rounding differs on 2 936 of the 65 536 16-bit
/// operands and on 12 of the Tier 0 uniform ramp values, the thresholds on none
/// (parity/semantics/colour-transfer.json).
[[nodiscard]] uint32_t Srgb8Store(float v);

/// The bits of the binary16 value of `v` rounded toward zero (finite values beyond the
/// largest half give the largest half; infinities and NaN keep their class).
[[nodiscard]] uint16_t HalfTowardZero(float v);
/// The bits of the binary16 value of `v` rounded to nearest, ties to even (IEEE 754
/// convertFormat; magnitudes from 65520 up give infinity; infinities and NaN keep their class).
/// The coverage plane of an sRGB8 intermediate passes through it before its 8-bit write
/// (profile.h `EvaluatorProfile::srgb8HalfCoverage`).
[[nodiscard]] uint16_t HalfNearestEven(float v);
/// The float32 value of a binary16 bit pattern (exact).
[[nodiscard]] float HalfToFloat(uint16_t bits);
/// The 32-bit float store: the value itself, with NaN as the quiet NaN 0x7FC00000 (payloads
/// carry no value; CONTRACT §3.1 compares NaN with NaN).
[[nodiscard]] float Float32Store(float v);
/// The read-out of a 32-bit float channel: float32(float32(v - base) + base), the channel value
/// re-composited over its base once (blend-modes.json: 1 + (v - 1) over the white base). The
/// blend fits use the raw backdrop and apply this to the result, so it is not a per-layer store.
[[nodiscard]] float Float32Readout(float v, float base);

/// Lookup tables the kernels embed or upload (their CPU twins compute the same values).
/// Entry c: the linear value the GPU the Tier 0 goldens were recorded on (NVIDIA GeForce RTX 4090,
/// D3D12) loads from an sRGB8 texel of code c, measured by `uzp-evaluator-tests srgb8-hardware`.
/// Painter exports an sRGB8 channel at 16 bits as this value through the UNORM write rule, and
/// blends sRGB8 channels on it.
[[nodiscard]] const std::array<float, 256>& Srgb8OperandTable();
/// Entry k >= 1: the smallest float32 the conversion stores as code k or above (in double);
/// entry 0 is unused (0). The values are the float-to-sRGB8 conversion of the GPU the Tier 0
/// goldens were recorded on (NVIDIA GeForce RTX 4090, D3D12), measured by bisection over float32
/// bit patterns (`uzp-evaluator-tests srgb8-hardware`); each lies within 0.15 code of the IEC
/// 61966-2-1 threshold decode((k - 0.5) / 255) and has at most 11 significant mantissa bits.
[[nodiscard]] const std::array<double, 256>& Srgb8Thresholds();
[[nodiscard]] const std::array<float, 256>& Unorm8OperandTable();
[[nodiscard]] const std::vector<float>& Unorm16OperandTable();

// ── Compositing of one texel ─────────────────────────────────────────────────

/// One texel of a blend: straight colour and alpha of the backdrop (`acc`, alpha 1 on the stack
/// accumulator, the coverage inside an isolated group) and of the source (`src`, alpha 1 for a
/// layer's content, the group coverage for a group result), the mask value, the layer opacity and
/// the mode. `channels` is 1 (grey) or 3.
struct CompositeInput {
    std::array<float, 4> acc{0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 4> src{0.0f, 0.0f, 0.0f, 1.0f};
    float mask = 1.0f;
    float opacity = 1.0f;
    core::BlendingMode mode = core::BlendingMode::Normal;
    /// UNORM formats clamp r to [0, 1] before the opacity mix (blend-modes.json).
    bool clampUnorm = false;
    /// The mix of an effect (a mask or content effect, parity/semantics/masks-levels.json): over
    /// an opaque backdrop v = a + (r - a) alpha for every mode, instead of the layer mix.
    bool effectMix = false;
    /// The source-over onto a backdrop that is not opaque weights its terms with the coverage it
    /// computes (profile.h `EvaluatorProfile::coverageWeights`): wb = (1 - as) ab, ao = as + wb,
    /// ws = ao - ab and v = fma(ws, Cs, fma(ab, as B, wb Cb)) x Rcp(ao) with the recording GPU's
    /// reciprocal, also over a backdrop of zero coverage.
    bool coverageWeights = false;
    /// The backdrop is the empty start of an isolated list (its first layer): the source is
    /// copied, with coverage as.
    bool emptyBackdrop = false;
    /// The read-out of an isolated root over the opaque base (profile.h
    /// `EvaluatorProfile::fusedReadout`): v = fma(C - base, alpha, base), one rounding of the
    /// product and the sum, in place of the Replace mix.
    bool fusedReadout = false;
    int channels = 3;
};

/// One component of a Levels effect as Painter stores it (float32 parameters).
struct LevelsComponent {
    float inMin = 0.0f;
    float inMax = 1.0f;
    float gamma = 1.0f;
    float outMin = 0.0f;
    float outMax = 1.0f;
    bool clamp = false;
};

/// Levels of one value (parity/semantics/masks-levels.json): t = (v - inMin) Rcp(inMax - inMin)
/// with the recording GPU's reciprocal; clamped to [0, 1] when `clamp`; when gamma is not 1,
/// t = sign(t) pow(|t|, gamma) with the recording GPU's pow (hwmath.h); the output is
/// fma(t, outMax - outMin, outMin).
[[nodiscard]] float Levels(float v, const LevelsComponent& levels);

/// The composite before the write rule: straight colour (components past `channels` are 0) and
/// the resulting alpha. alpha_s = opacity x mask x src alpha; with an opaque backdrop the fitted
/// opacity mix; with `coverageWeights`, over any other backdrop but the empty start, the
/// coverage-weighted order (CompositeInput); otherwise, with a transparent backdrop, the source
/// as it is (W3C §5.1: no blending against nothing), and the general formula of W3C §5.1 with
/// straight colours.
[[nodiscard]] std::array<float, 4> Composite(const CompositeInput& in);

}  // namespace uzp::evaluator::arith
