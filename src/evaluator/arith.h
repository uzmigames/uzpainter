#pragma once

// Scalar arithmetic of the compositor (docs/architecture/04-layer-stack-and-compositing.md §3-§4),
// written once here for the CPU and mirrored operation for operation by the generated kernels
// (kernelgen.h, shaders/evaluator_blend.hlsl), so both backends produce the same bits:
//
// - operands from storage (parity/semantics/blend-modes.json, "Operands"): UNORM codes as
//   float32(code / M) through lookup tables; sRGB8 codes as the IEC 61966-2-1 decode on 8
//   significant bits; floats as stored;
// - the separable blend kernels of blend-modes.json in float32 with the fused multiply-add,
//   reciprocal and square root of the fit (one rounding each), and the opacity mix
//   v = a (1 - alpha) + r alpha (Replace: a + (r - a) alpha);
// - the write rules ("Write"): UNORM n bits truncated to n + 4 fractional bits then the nearest
//   code, ties down; sRGB8 round(255 encode(v)); 16-bit float toward zero; 32-bit float as it
//   is, re-composited over the channel base (1 + (v - 1)) once at read-out;
// - the isolated-group composite (W3C Compositing and Blending Level 1 §5.1, §6; approved source
//   S-W3C-BLEND) that the Tier 0 `group-masks` golden confirms for groups without masks.
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

/// The modes whose kernel this file defines: the separable modes of blend-modes.json (Normal,
/// Replace, Disable, Multiply ... PinLight). The non-separable modes (Tint, Saturation, Color,
/// Value) and the normal-map modes are the kernels of phase1.10_compositor-blend-kernels;
/// PassThrough is a group placement, not a kernel.
[[nodiscard]] bool HasSeparableKernel(core::BlendingMode mode);
/// r of blend-modes.json for the lower value `a` and the upper value `b` (float32).
[[nodiscard]] float BlendKernel(core::BlendingMode mode, float a, float b);

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
/// The linear operand of an sRGB8 code: float32(SignificandRound(decode(code / 255), 8)).
[[nodiscard]] float Srgb8Operand(uint32_t code);
/// The sRGB8 code of a linear value: round(255 encode(v)), v clamped to [0, 1] (NaN to 0),
/// decided by comparing v with the 255 decode thresholds in double precision.
[[nodiscard]] uint32_t Srgb8Store(float v);

/// The bits of the binary16 value of `v` rounded toward zero (finite values beyond the
/// largest half give the largest half; infinities and NaN keep their class).
[[nodiscard]] uint16_t HalfTowardZero(float v);
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
[[nodiscard]] const std::array<float, 256>& Srgb8OperandTable();
/// Entry k >= 1: decode((k - 0.5) / 255) in double; entry 0 is unused (0).
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
    int channels = 3;
};

/// The composite before the write rule: straight colour (components past `channels` are 0) and
/// the resulting alpha. alpha_s = opacity x mask x src alpha; with an opaque backdrop the fitted
/// opacity mix; with a transparent backdrop the source as it is (W3C §5.1: no blending against
/// nothing); otherwise the general formula of W3C §5.1 with straight colours.
[[nodiscard]] std::array<float, 4> Composite(const CompositeInput& in);

}  // namespace uzp::evaluator::arith
