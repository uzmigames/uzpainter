#include "evaluator/arith.h"

#include <bit>
#include <cfenv>
#include <cmath>
#include <limits>

namespace uzp::evaluator::arith {

namespace {

constexpr float kHalf = 0.5f;
constexpr float kOne = 1.0f;
constexpr float kTwo = 2.0f;

float Mul(float x, float y) { return x * y; }
float Add(float x, float y) { return x + y; }
float Sub(float x, float y) { return x - y; }

float HardLight(float a, float b) {
    const float twoA = Mul(kTwo, a);
    const float low = Mul(twoA, b);
    const float oneMinusA = Sub(kOne, a);
    const float x = Mul(-kTwo, oneMinusA);
    const float y = Sub(kOne, b);
    const float high = Fma(x, y, kOne);
    return b <= kHalf ? low : high;
}

float ColorBurn(float a, float b) {
    const float x = Sub(a, kOne);
    return Clamp01(Fma(x, Rcp(b), kOne));
}

float ColorDodge(float a, float b) {
    const float t = Sub(kOne, b);
    const float m = Mul(a, Rcp(t));
    return Fmax(Fmin(kOne, m), 0.0f);
}

float SoftLight(float a, float b) {
    // low = fma(2a, b, a a (1 - 2b)); high = fma(sqrt(a), 2b - 1, 2a (1 - b)).
    const float twoA = Mul(kTwo, a);
    const float twoB = Mul(kTwo, b);
    const float aa = Mul(a, a);
    const float oneMinusTwoB = Sub(kOne, twoB);
    const float low = Fma(twoA, b, Mul(aa, oneMinusTwoB));
    const float twoBMinusOne = Sub(twoB, kOne);
    const float oneMinusB = Sub(kOne, b);
    const float high = Fma(Sqrt(a), twoBMinusOne, Mul(twoA, oneMinusB));
    return b <= kHalf ? low : high;
}

float LinearLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float low = Sub(Add(a, twoB), kOne);
    const float bMinusHalf = Sub(b, kHalf);
    const float high = Add(a, Mul(kTwo, bMinusHalf));
    return Clamp01(b <= kHalf ? low : high);
}

float VividLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float bMinusHalf = Sub(b, kHalf);
    const float twoBMinusHalf = Mul(kTwo, bMinusHalf);
    return b <= kHalf ? ColorBurn(a, twoB) : ColorDodge(a, twoBMinusHalf);
}

float PinLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float low = MinNan(a, twoB);
    const float high = MaxNan(a, Sub(twoB, kOne));
    return b <= kHalf ? low : high;
}

float Divide(float a, float b) {
    const float m = Mul(a, Rcp(b));
    return Fmax(Fmin(m, kOne), 0.0f);
}

}  // namespace

float Fma(float x, float y, float z) {
    return static_cast<float>(
        std::fma(static_cast<double>(x), static_cast<double>(y), static_cast<double>(z)));
}

float Rcp(float x) { return 1.0f / x; }

float Sqrt(float x) { return std::sqrt(x); }

float Fmin(float x, float y) { return std::fmin(x, y); }

float Fmax(float x, float y) { return std::fmax(x, y); }

float MinNan(float x, float y) {
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<float>::quiet_NaN();
    return x < y ? x : y;
}

float MaxNan(float x, float y) {
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<float>::quiet_NaN();
    return x > y ? x : y;
}

float Clamp01(float x) { return Fmin(Fmax(x, 0.0f), kOne); }

bool HasSeparableKernel(core::BlendingMode mode) {
    using M = core::BlendingMode;
    switch (mode) {
        case M::Normal: case M::Replace: case M::Disable: case M::Multiply: case M::Divide:
        case M::InverseDivide: case M::Darken: case M::Lighten: case M::LinearDodge:
        case M::Subtract: case M::InverseSubtract: case M::Difference: case M::Exclusion:
        case M::SignedAddition: case M::Overlay: case M::Screen: case M::LinearBurn:
        case M::ColorBurn: case M::ColorDodge: case M::SoftLight: case M::HardLight:
        case M::VividLight: case M::LinearLight: case M::PinLight:
            return true;
        case M::PassThrough: case M::Tint: case M::Saturation: case M::Color: case M::Value:
        case M::NormalMapCombine: case M::NormalMapDetail: case M::NormalMapInverseDetail:
            return false;
    }
    return false;
}

float BlendKernel(core::BlendingMode mode, float a, float b) {
    using M = core::BlendingMode;
    switch (mode) {
        case M::Normal: case M::Replace: return b;
        case M::Disable: return a;
        case M::Multiply: return Mul(a, b);
        case M::Divide: return Divide(a, b);
        case M::InverseDivide: return Divide(b, a);
        case M::Darken: return MinNan(a, b);
        case M::Lighten: return MaxNan(a, b);
        case M::LinearDodge: return Add(a, b);
        case M::Subtract: return Sub(a, b);
        case M::InverseSubtract: return Sub(b, a);
        case M::Difference: return std::fabs(Sub(a, b));
        case M::Exclusion: {
            const float aMinusHalf = Sub(a, kHalf);
            const float x = Mul(-kTwo, aMinusHalf);
            const float y = Sub(b, kHalf);
            return Fma(x, y, kHalf);
        }
        case M::SignedAddition: {
            const float twoB = Mul(kTwo, b);
            return Sub(Add(a, twoB), kOne);
        }
        case M::Screen: {
            const float x = -Sub(kOne, a);
            const float y = Sub(kOne, b);
            return Fma(x, y, kOne);
        }
        case M::LinearBurn: return Sub(Add(a, b), kOne);
        case M::Overlay: return HardLight(b, a);
        case M::ColorBurn: return ColorBurn(a, b);
        case M::ColorDodge: return ColorDodge(a, b);
        case M::SoftLight: return SoftLight(a, b);
        case M::HardLight: return HardLight(a, b);
        case M::VividLight: return VividLight(a, b);
        case M::LinearLight: return LinearLight(a, b);
        case M::PinLight: return PinLight(a, b);
        case M::PassThrough: case M::Tint: case M::Saturation: case M::Color: case M::Value:
        case M::NormalMapCombine: case M::NormalMapDetail: case M::NormalMapInverseDetail:
            break;
    }
    return std::numeric_limits<float>::quiet_NaN();
}

// ── Storage ──────────────────────────────────────────────────────────────────

uint32_t WriteUnorm(float v, uint32_t bits) {
    float c = v >= 0.0f ? v : 0.0f;  // NaN compares false: 0
    c = c <= 1.0f ? c : 1.0f;
    const float scale = static_cast<float>(uint64_t{1} << (bits + 4));  // exact power of two
    const uint64_t j = static_cast<uint64_t>(c * scale);
    const uint64_t m = (uint64_t{1} << bits) - 1;
    const uint64_t bias = (uint64_t{1} << (bits + 3)) - 1;
    return static_cast<uint32_t>((j * m + bias) >> (bits + 4));
}

float UnormOperand(uint32_t code, uint32_t bits) {
    const double m = static_cast<double>((uint64_t{1} << bits) - 1);
    return static_cast<float>(static_cast<double>(code) / m);
}

double SrgbDecode(double encoded) {
    const double x = encoded > 0.0 ? encoded : 0.0;
    if (encoded <= 0.04045) return encoded / 12.92;
    return std::pow((x + 0.055) / 1.055, 2.4);
}

double SrgbEncode(double linear) {
    const double x = linear > 0.0 ? linear : 0.0;
    if (linear <= 0.0031308) return 12.92 * linear;
    return 1.055 * std::pow(x, 1.0 / 2.4) - 0.055;
}

double SignificandRound(double x, int bits) {
    int exponent = 0;
    const double mantissa = std::frexp(x, &exponent);
    const double scale = static_cast<double>(int64_t{1} << bits);
    return std::ldexp(std::nearbyint(mantissa * scale) / scale, exponent);
}

const std::array<float, 256>& Srgb8OperandTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> t{};
        for (uint32_t c = 0; c < 256; ++c) {
            t[c] = static_cast<float>(SignificandRound(SrgbDecode(c / 255.0), 8));
        }
        return t;
    }();
    return table;
}

const std::array<double, 256>& Srgb8Thresholds() {
    static const std::array<double, 256> table = [] {
        std::array<double, 256> t{};
        t[0] = 0.0;
        for (uint32_t k = 1; k < 256; ++k) t[k] = SrgbDecode((k - 0.5) / 255.0);
        return t;
    }();
    return table;
}

const std::array<float, 256>& Unorm8OperandTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> t{};
        for (uint32_t c = 0; c < 256; ++c) t[c] = UnormOperand(c, 8);
        return t;
    }();
    return table;
}

const std::vector<float>& Unorm16OperandTable() {
    static const std::vector<float> table = [] {
        std::vector<float> t(65536);
        for (uint32_t c = 0; c < 65536; ++c) t[c] = UnormOperand(c, 16);
        return t;
    }();
    return table;
}

float Srgb8Operand(uint32_t code) { return Srgb8OperandTable()[code & 0xFF]; }

uint32_t Srgb8Store(float v) {
    float c = v >= 0.0f ? v : 0.0f;
    c = c <= 1.0f ? c : 1.0f;
    const double value = static_cast<double>(c);
    const std::array<double, 256>& thresholds = Srgb8Thresholds();
    uint32_t code = 0;
    for (uint32_t k = 1; k < 256; ++k) {
        if (value >= thresholds[k]) code = k;
    }
    return code;
}

uint16_t HalfTowardZero(float v) {
    const uint32_t bits = std::bit_cast<uint32_t>(v);
    const uint16_t sign = static_cast<uint16_t>((bits >> 16) & 0x8000u);
    const uint32_t magnitude = bits & 0x7FFFFFFFu;
    if (magnitude >= 0x7F800000u) {
        // Infinity keeps its class; NaN keeps a quiet NaN payload.
        if (magnitude == 0x7F800000u) return static_cast<uint16_t>(sign | 0x7C00u);
        return static_cast<uint16_t>(sign | 0x7E00u);
    }
    if (magnitude >= 0x477FE000u) {  // >= 65504: the largest finite half (toward zero)
        return static_cast<uint16_t>(sign | 0x7BFFu);
    }
    if (magnitude < 0x38800000u) {  // below 2^-14: a subnormal half, step 2^-24
        const float scaled = std::bit_cast<float>(magnitude) * 16777216.0f;  // exact
        const uint32_t mantissa = static_cast<uint32_t>(scaled);
        return static_cast<uint16_t>(sign | mantissa);
    }
    const uint32_t exponent = (magnitude >> 23) - 127 + 15;
    const uint32_t mantissa = (magnitude >> 13) & 0x3FFu;
    return static_cast<uint16_t>(sign | (exponent << 10) | mantissa);
}

float HalfToFloat(uint16_t bits) {
    const uint32_t sign = (static_cast<uint32_t>(bits) & 0x8000u) << 16;
    const uint32_t exponent = (bits >> 10) & 0x1Fu;
    const uint32_t mantissa = bits & 0x3FFu;
    if (exponent == 0) {
        if (mantissa == 0) return std::bit_cast<float>(sign);
        const float value = static_cast<float>(mantissa) * 5.9604644775390625e-08f;  // 2^-24
        return std::bit_cast<float>(sign | std::bit_cast<uint32_t>(value));
    }
    if (exponent == 31) {
        return std::bit_cast<float>(sign | 0x7F800000u | (mantissa << 13));
    }
    return std::bit_cast<float>(sign | ((exponent + 112) << 23) | (mantissa << 13));
}

float Float32Store(float v, float base) {
    if (std::isnan(v)) return std::bit_cast<float>(0x7FC00000u);
    const float t = v - base;
    return t + base;
}

// ── Compositing of one texel ─────────────────────────────────────────────────

std::array<float, 4> Composite(const CompositeInput& in) {
    std::array<float, 4> out{0.0f, 0.0f, 0.0f, 1.0f};
    const float opacityMask = Mul(in.opacity, in.mask);
    const float alphaS = Mul(opacityMask, in.src[3]);
    const float alphaB = in.acc[3];
    const bool replace = in.mode == core::BlendingMode::Replace;
    for (int i = 0; i < in.channels; ++i) {
        const float a = in.acc[static_cast<size_t>(i)];
        const float s = in.src[static_cast<size_t>(i)];
        float r = BlendKernel(in.mode, a, s);
        if (in.clampUnorm) r = Clamp01(r);
        float v = 0.0f;
        if (alphaB == 1.0f) {
            if (replace) {
                const float d = Sub(r, a);
                v = Add(a, Mul(d, alphaS));
            } else {
                const float oneMinusAlpha = Sub(kOne, alphaS);
                const float ta = Mul(a, oneMinusAlpha);
                const float tr = Mul(r, alphaS);
                v = Add(ta, tr);
            }
        } else if (alphaB == 0.0f) {
            v = s;
        } else {
            // W3C §5.1 with straight colours: Co = [(1 - as) ab Cb + as ((1 - ab) Cs + ab B)] / ao.
            const float oneMinusAlphaS = Sub(kOne, alphaS);
            const float oneMinusAlphaB = Sub(kOne, alphaB);
            const float backdrop = Mul(Mul(oneMinusAlphaS, alphaB), a);
            const float blended = Add(Mul(oneMinusAlphaB, s), Mul(alphaB, r));
            const float alphaO = Add(alphaS, Mul(alphaB, oneMinusAlphaS));
            v = Mul(Add(backdrop, Mul(alphaS, blended)), Rcp(alphaO));
        }
        out[static_cast<size_t>(i)] = v;
    }
    if (alphaB == 1.0f) {
        out[3] = 1.0f;
    } else if (alphaB == 0.0f) {
        out[3] = alphaS;
    } else {
        out[3] = Add(alphaS, Mul(alphaB, Sub(kOne, alphaS)));
    }
    return out;
}

}  // namespace uzp::evaluator::arith
