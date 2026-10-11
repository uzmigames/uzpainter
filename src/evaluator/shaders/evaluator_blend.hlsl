// Blend kernel of the compositor (src/evaluator/kernelgen.h), one specialisation per blend mode
// and tile format: UZP_MODE_<Mode>, UZP_ENC (ENC_* of image_common.hlsli), UZP_CHANNELS (1 or
// 3), UZP_SRGB (codes are sRGB8), UZP_ALPHA (the destination carries a coverage plane).
// Mirrors src/evaluator/arith.cpp operation for operation: every float operation is one IEEE
// operation (compiled IEEE-strict), Fma is the float32 rounding of the exact x y + z (exact
// product and one addition in double), Rcp and Sqrt are correctly rounded (the hardware result
// corrected with exact double residuals), min/max follow IEEE minNum/maxNum where numpy's fmin/
// fmax do and propagate NaN where numpy's minimum/maximum do.
//
// Parameters come from a block of 32 uints in the arena behind root constant 0, block index in
// root constant 1 (kernelgen.h, BlendParam): width, height, flags, backdrop (SRV index or
// constant rgba), source (SRV index or constant rgba), mask (SRV index of plane 0 or constant),
// opacity, the destination UAV, the 16-bit UNORM operand table SRV and the mask tile's
// encoding. 32-bit float results are stored raw (the channel base re-composition is a read-out
// step of evaluate.cpp).

#include "image_common.hlsli"
#include "evaluator_tables.hlsli"

cbuffer Root : register(b0) {
    uint g_paramsSrv;
    uint g_block;
};

#define P_WIDTH 0
#define P_HEIGHT 1
#define P_FLAGS 2
#define P_ACC_INDEX 3
#define P_ACC_CONST 4
#define P_SRC_INDEX 8
#define P_SRC_CONST 9
#define P_MASK_INDEX 13
#define P_MASK_CONST 14
#define P_OPACITY 15
#define P_DST_UAV 16
#define P_TABLE16_SRV 17
#define P_MASK_ENC 18

#define FLAG_ACC_TILE 1u
#define FLAG_SRC_TILE 2u
#define FLAG_MASK_TILE 4u
#define FLAG_ACC_ALPHA 8u
#define FLAG_SRC_ALPHA 16u

static const float kNaN = asfloat(0x7FC00000u);
/// The SRV of the 16-bit UNORM operand table, set from the parameter block.
static uint g_table16;

// ── Arithmetic (arith.cpp) ───────────────────────────────────────────────────

float Fma(float x, float y, float z) {
    const double p = (double)x * (double)y;
    const double s = p + (double)z;
    return (float)s;
}

// 1 / x correctly rounded: the hardware quotient moved to the float whose interval holds the
// exact reciprocal, decided with exact double residuals (m x - 1 is exact for a 25-bit m).
float Rcp(float x) {
    if (isnan(x)) return x;
    if (x == 0.0f) return asfloat(asuint(x) | 0x7F800000u);
    if (isinf(x)) return asfloat(asuint(x) & 0x80000000u);
    const float ax = abs(x);
    float c = 1.0f / ax;
    if (!isinf(c)) {
        const double X = (double)ax;
        [loop] for (int i = 0; i < 4; ++i) {
            const float up = asfloat(asuint(c) + 1u);
            const float down = asfloat(asuint(c) - 1u);
            const double mUp = ((double)c + (double)up) * 0.5;
            const double mDown = ((double)down + (double)c) * 0.5;
            if (mUp * X - 1.0 < 0.0) c = up;
            else if (mDown * X - 1.0 > 0.0) c = down;
            else break;
        }
    }
    return x < 0.0f ? -c : c;
}

// sqrt(a) correctly rounded by the same correction (m m - a is exact for a 25-bit m).
float Sqrt(float a) {
    if (!(a > 0.0f) || isinf(a)) return sqrt(a);
    float c = sqrt(a);
    const double A = (double)a;
    [loop] for (int i = 0; i < 4; ++i) {
        const float up = asfloat(asuint(c) + 1u);
        const float down = asfloat(asuint(c) - 1u);
        const double mUp = ((double)c + (double)up) * 0.5;
        const double mDown = ((double)down + (double)c) * 0.5;
        if (mUp * mUp - A < 0.0) c = up;
        else if (mDown * mDown - A > 0.0) c = down;
        else break;
    }
    return c;
}

// IEEE minNum / maxNum spelled out: HLSL min / max are not guaranteed to return the other
// operand on NaN (the DX12 driver propagated it), the CPU's fmin / fmax are.
float Fmin(float x, float y) { return isnan(x) ? y : (isnan(y) ? x : (x < y ? x : y)); }
float Fmax(float x, float y) { return isnan(x) ? y : (isnan(y) ? x : (x > y ? x : y)); }
float MinNan(float x, float y) { return (isnan(x) || isnan(y)) ? kNaN : (x < y ? x : y); }
float MaxNan(float x, float y) { return (isnan(x) || isnan(y)) ? kNaN : (x > y ? x : y); }
float Clamp01(float x) { return Fmin(Fmax(x, 0.0f), 1.0f); }

float HardLight(float a, float b) {
    const float twoA = 2.0f * a;
    const float low = twoA * b;
    const float oneMinusA = 1.0f - a;
    const float x = -2.0f * oneMinusA;
    const float y = 1.0f - b;
    const float high = Fma(x, y, 1.0f);
    return b <= 0.5f ? low : high;
}

float ColorBurn(float a, float b) {
    const float x = a - 1.0f;
    return Clamp01(Fma(x, Rcp(b), 1.0f));
}

float ColorDodge(float a, float b) {
    const float t = 1.0f - b;
    const float m = a * Rcp(t);
    return Fmax(Fmin(1.0f, m), 0.0f);
}

float SoftLight(float a, float b) {
    const float twoA = 2.0f * a;
    const float twoB = 2.0f * b;
    const float aa = a * a;
    const float oneMinusTwoB = 1.0f - twoB;
    const float low = Fma(twoA, b, aa * oneMinusTwoB);
    const float twoBMinusOne = twoB - 1.0f;
    const float oneMinusB = 1.0f - b;
    const float high = Fma(Sqrt(a), twoBMinusOne, twoA * oneMinusB);
    return b <= 0.5f ? low : high;
}

float LinearLight(float a, float b) {
    const float twoB = 2.0f * b;
    const float low = (a + twoB) - 1.0f;
    const float bMinusHalf = b - 0.5f;
    const float high = a + 2.0f * bMinusHalf;
    return Clamp01(b <= 0.5f ? low : high);
}

float VividLight(float a, float b) {
    const float twoB = 2.0f * b;
    const float bMinusHalf = b - 0.5f;
    const float twoBMinusHalf = 2.0f * bMinusHalf;
    return b <= 0.5f ? ColorBurn(a, twoB) : ColorDodge(a, twoBMinusHalf);
}

float PinLight(float a, float b) {
    const float twoB = 2.0f * b;
    const float low = MinNan(a, twoB);
    const float high = MaxNan(a, twoB - 1.0f);
    return b <= 0.5f ? low : high;
}

float Divide(float a, float b) {
    const float m = a * Rcp(b);
    return Fmax(Fmin(m, 1.0f), 0.0f);
}

float BlendKernel(float a, float b) {
#if defined(UZP_MODE_Normal) || defined(UZP_MODE_Replace)
    return b;
#elif defined(UZP_MODE_Disable)
    return a;
#elif defined(UZP_MODE_Multiply)
    return a * b;
#elif defined(UZP_MODE_Divide)
    return Divide(a, b);
#elif defined(UZP_MODE_InverseDivide)
    return Divide(b, a);
#elif defined(UZP_MODE_Darken)
    return MinNan(a, b);
#elif defined(UZP_MODE_Lighten)
    return MaxNan(a, b);
#elif defined(UZP_MODE_LinearDodge)
    return a + b;
#elif defined(UZP_MODE_Subtract)
    return a - b;
#elif defined(UZP_MODE_InverseSubtract)
    return b - a;
#elif defined(UZP_MODE_Difference)
    return abs(a - b);
#elif defined(UZP_MODE_Exclusion)
    const float aMinusHalf = a - 0.5f;
    const float x = -2.0f * aMinusHalf;
    const float y = b - 0.5f;
    return Fma(x, y, 0.5f);
#elif defined(UZP_MODE_SignedAddition)
    const float twoB = 2.0f * b;
    return (a + twoB) - 1.0f;
#elif defined(UZP_MODE_Screen)
    const float x = -(1.0f - a);
    const float y = 1.0f - b;
    return Fma(x, y, 1.0f);
#elif defined(UZP_MODE_LinearBurn)
    return (a + b) - 1.0f;
#elif defined(UZP_MODE_Overlay)
    return HardLight(b, a);
#elif defined(UZP_MODE_ColorBurn)
    return ColorBurn(a, b);
#elif defined(UZP_MODE_ColorDodge)
    return ColorDodge(a, b);
#elif defined(UZP_MODE_SoftLight)
    return SoftLight(a, b);
#elif defined(UZP_MODE_HardLight)
    return HardLight(a, b);
#elif defined(UZP_MODE_VividLight)
    return VividLight(a, b);
#elif defined(UZP_MODE_LinearLight)
    return LinearLight(a, b);
#elif defined(UZP_MODE_PinLight)
    return PinLight(a, b);
#else
#error "UZP_MODE_<Mode> selects the blend kernel"
#endif
}

// ── Storage (arith.cpp, cpu_store.cpp) ───────────────────────────────────────

// The float32 value of the binary16 nearest toward zero.
float HalfTowardZero(float v) {
    const uint bits = asuint(v);
    const uint sign = bits & 0x80000000u;
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return asfloat(sign | 0x7FC00000u);  // quiet NaN
    if (magnitude == 0x7F800000u) return v;
    if (magnitude >= 0x477FE000u) return asfloat(sign | 0x477FE000u);  // 65504
    if (magnitude < 0x38800000u) {
        const float scaled = asfloat(magnitude) * 16777216.0f;
        const uint mantissa = uint(scaled);
        return asfloat(sign | asuint(float(mantissa) * 5.9604644775390625e-08f));
    }
    return asfloat(sign | (magnitude & 0xFFFFE000u));
}

// The largest k with v >= threshold k (arith.h Srgb8Thresholds: the recording GPU's float-to-sRGB8
// conversion), compared in double.
uint Srgb8Store(float v) {
    float c = v >= 0.0f ? v : 0.0f;
    c = c <= 1.0f ? c : 1.0f;
    const double value = (double)c;
    uint lo = 0u;
    uint hi = 255u;
    [loop] while (lo < hi) {
        const uint mid = (lo + hi + 1u) >> 1;
        const double threshold = asdouble(kSrgb8ThresholdLo[mid], kSrgb8ThresholdHi[mid]);
        if (value >= threshold) lo = mid;
        else hi = mid - 1u;
    }
    return lo;
}

float UnormOperand(uint code) {
#if UZP_ENC == 0
    return asfloat(kUnorm8Operand[code & 0xFFu]);
#else
    StructuredBuffer<float> table = ResourceDescriptorHeap[g_table16];
    return table[code & 0xFFFFu];
#endif
}

// ── Operands ─────────────────────────────────────────────────────────────────

float4 LoadOperand(uint srv, int2 p, bool hasAlpha) {
    const float4 raw = LoadTexel(srv, p);
    float4 op = float4(0.0f, 0.0f, 0.0f, 1.0f);
#if UZP_ENC == 0 || UZP_ENC == 1
    const uint4 codes = Codes(raw, UZP_ENC);
#if UZP_SRGB
    op.x = asfloat(kSrgb8Operand[codes.x & 0xFFu]);
#if UZP_CHANNELS == 3
    op.y = asfloat(kSrgb8Operand[codes.y & 0xFFu]);
    op.z = asfloat(kSrgb8Operand[codes.z & 0xFFu]);
#endif
#else
    op.x = UnormOperand(codes.x);
#if UZP_CHANNELS == 3
    op.y = UnormOperand(codes.y);
    op.z = UnormOperand(codes.z);
#endif
#endif
    if (hasAlpha) op.w = UnormOperand(codes.w);
#else
    op.x = raw.x;
#if UZP_CHANNELS == 3
    op.y = raw.y;
    op.z = raw.z;
#endif
    if (hasAlpha) op.w = raw.w;
#endif
    return op;
}

float LoadMask(uint srv, int2 p, uint enc) {
    const float4 raw = LoadTexel(srv, p);
    if (enc == ENC_UNORM8) return asfloat(kUnorm8Operand[Codes(raw, ENC_UNORM8).x & 0xFFu]);
    if (enc == ENC_UNORM16) {
        StructuredBuffer<float> table = ResourceDescriptorHeap[g_table16];
        return table[Codes(raw, ENC_UNORM16).x & 0xFFFFu];
    }
    return raw.x;
}

// ── Compositing of one texel (arith.cpp Composite) ───────────────────────────

float Mix(float a, float r, float alphaS) {
#if defined(UZP_MODE_Replace)
    const float d = r - a;
    return a + d * alphaS;
#else
    const float oneMinusAlpha = 1.0f - alphaS;
    const float ta = a * oneMinusAlpha;
    const float tr = r * alphaS;
    return ta + tr;
#endif
}

float CompositeChannel(float a, float s, float alphaB, float alphaS) {
    float r = BlendKernel(a, s);
#if UZP_ENC == 0 || UZP_ENC == 1
    r = Clamp01(r);
#endif
    if (alphaB == 1.0f) return Mix(a, r, alphaS);
    if (alphaB == 0.0f) return s;
    const float oneMinusAlphaS = 1.0f - alphaS;
    const float oneMinusAlphaB = 1.0f - alphaB;
    const float backdrop = (oneMinusAlphaS * alphaB) * a;
    const float blended = oneMinusAlphaB * s + alphaB * r;
    const float alphaO = alphaS + alphaB * oneMinusAlphaS;
    return (backdrop + alphaS * blended) * Rcp(alphaO);
}

float StoreChannel(float v) {
#if UZP_ENC == 0 || UZP_ENC == 1
#if UZP_SRGB
    return CodeValue(Srgb8Store(v), UZP_ENC);
#else
    return CodeValue(WriteValue(v, UZP_ENC), UZP_ENC);
#endif
#elif UZP_ENC == 2
    return HalfTowardZero(v);
#else
    if (isnan(v)) return asfloat(0x7FC00000u);
    return v;
#endif
}

float StoreCoverage(float alpha) {
#if UZP_ENC == 0 || UZP_ENC == 1
    return CodeValue(WriteValue(alpha, UZP_ENC), UZP_ENC);
#elif UZP_ENC == 2
    return HalfTowardZero(alpha);
#else
    return alpha;
#endif
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    const uint base = g_block * 32u;
    const uint width = params[base + P_WIDTH];
    const uint height = params[base + P_HEIGHT];
    if (id.x >= width || id.y >= height) return;
    const uint flags = params[base + P_FLAGS];
    g_table16 = params[base + P_TABLE16_SRV];
    const int2 p = int2(id.xy);

    float4 acc;
    if (flags & FLAG_ACC_TILE) {
        acc = LoadOperand(params[base + P_ACC_INDEX], p, (flags & FLAG_ACC_ALPHA) != 0u);
    } else {
        acc = float4(asfloat(params[base + P_ACC_CONST]), asfloat(params[base + P_ACC_CONST + 1]),
                     asfloat(params[base + P_ACC_CONST + 2]), asfloat(params[base + P_ACC_CONST + 3]));
    }
    float4 src;
    if (flags & FLAG_SRC_TILE) {
        src = LoadOperand(params[base + P_SRC_INDEX], p, (flags & FLAG_SRC_ALPHA) != 0u);
    } else {
        src = float4(asfloat(params[base + P_SRC_CONST]), asfloat(params[base + P_SRC_CONST + 1]),
                     asfloat(params[base + P_SRC_CONST + 2]), asfloat(params[base + P_SRC_CONST + 3]));
    }
    float mask;
    if (flags & FLAG_MASK_TILE) {
        mask = LoadMask(params[base + P_MASK_INDEX], p, params[base + P_MASK_ENC]);
    } else {
        mask = asfloat(params[base + P_MASK_CONST]);
    }
    const float opacity = asfloat(params[base + P_OPACITY]);
    const float opacityMask = opacity * mask;
    const float alphaS = opacityMask * src.w;
    const float alphaB = acc.w;

    float4 result = float4(0.0f, 0.0f, 0.0f, 1.0f);
    result.x = StoreChannel(CompositeChannel(acc.x, src.x, alphaB, alphaS));
#if UZP_CHANNELS == 3
    result.y = StoreChannel(CompositeChannel(acc.y, src.y, alphaB, alphaS));
    result.z = StoreChannel(CompositeChannel(acc.z, src.z, alphaB, alphaS));
#endif
    float alphaO = 1.0f;
    if (alphaB == 0.0f) alphaO = alphaS;
    else if (alphaB != 1.0f) alphaO = alphaS + alphaB * (1.0f - alphaS);
#if UZP_ALPHA
    result.w = StoreCoverage(alphaO);
#else
    result.w = StoreCoverage(1.0f);
#endif
    StoreTexel(params[base + P_DST_UAV], p, result);
}
