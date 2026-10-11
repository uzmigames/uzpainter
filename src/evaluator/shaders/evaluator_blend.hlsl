// Blend kernel of the compositor (src/evaluator/kernelgen.h), one specialisation per blend mode
// and tile format: UZP_MODE_<Mode>, UZP_ENC (ENC_* of image_common.hlsli), UZP_CHANNELS (1 or
// 3), UZP_SRGB (codes are sRGB8), UZP_ALPHA (the destination carries a coverage plane),
// UZP_HALF_COVERAGE (that plane is written through binary16, TileFormat::halfCoverage).
// Mirrors src/evaluator/arith.cpp operation for operation: every float operation is one IEEE
// operation (compiled IEEE-strict), Fma is the float32 rounding of the exact x y + z (exact
// product and one addition in double), Rcp, Sqrt and RsqrtCorrect are correctly rounded (the
// hardware result corrected with exact double residuals), HwRcp, HwSqrt and HwRsqrt are the
// recording GPU's results rebuilt from the measured tables of hwmath.h (never this GPU's own
// instructions), min/max follow IEEE minNum/maxNum where numpy's fmin/fmax do and propagate NaN
// where numpy's minimum/maximum do.
//
// Parameters come from a block of 32 uints in the arena behind root constant 0, block index in
// root constant 1 (kernelgen.h, BlendParam): width, height, flags, backdrop (SRV index or
// constant rgba), source (SRV index or constant rgba), mask (SRV index of plane 0 or constant),
// opacity, the destination UAV, the operand tables SRV (the 16-bit UNORM operands and the
// hardware arithmetic tables at the offsets of evaluator_tables.hlsli), the mask tile's
// encoding and, for the normal-map modes, the function tables SRV (the GPU's sine and cosine,
// hwmath.h, at the offsets UZP_POW_SIN and UZP_POW_COS). 32-bit float results are stored raw (the channel base re-composition is a read-out
// step of evaluate.cpp). The flag FLAG_EFFECT_MIX selects the mix of an effect (a mask or content
// effect: a + (r - a) alpha for every mode).
//
// With UZP_LEVELS the kernel is the Levels effect instead (arith.cpp Levels, LevelsOp of
// tile_store.h): parameter block width, height, source SRV, destination UAV, operand tables SRV,
// log2/exp2 tables SRV (hwmath.h, at the offsets UZP_POW_*), the source's coverage flag and three
// components of six words (input min, input max, gamma, output min, output max, clamp).
//
// UZP_RAW_OUTPUT (a raw blend, tile_store.h BlendOp::rawOutput): the destination is a 32-bit float
// tile and every result is stored as it is (the float32 read-out of the virtual normal maps); the
// operands keep the encoding UZP_ENC.
//
// With UZP_VNORMAL the kernel is one tile of a virtual normal map instead (height_to_normal.cpp,
// VirtualNormalOp of tile_store.h): parameter block width, height, flags (bit 0 the height is
// tiles, bit 1 the Normal channel is a tile, bit 2 the Sobel method, bit 3 the DirectX
// convention), destination UAV, operand tables SRV, the constant height, the Normal channel's
// SRV or constant rgb, and the SRVs of the nine height tiles around the tile (index (dy + 1) 3 +
// dx + 1).

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
#define P_POW_SRV 19

#define FLAG_ACC_TILE 1u
#define FLAG_SRC_TILE 2u
#define FLAG_MASK_TILE 4u
#define FLAG_ACC_ALPHA 8u
#define FLAG_SRC_ALPHA 16u
#define FLAG_EFFECT_MIX 32u

static const float kNaN = asfloat(0x7FC00000u);
/// The SRV of the operand tables (kernelgen.h OperandTableWords), set from the parameter block.
static uint g_tables;
/// The blend is an effect's (FLAG_EFFECT_MIX).
static bool g_effectMix;

uint TableWord(uint index) {
    StructuredBuffer<uint> tables = ResourceDescriptorHeap[g_tables];
    return tables[index];
}

/// The SRV of the function tables (hwmath.h Values: log2, exp2, sin, cos at the offsets
/// UZP_POW_*), set from the parameter block of the Levels and the normal-map kernels.
static uint g_pow;

uint PowWord(uint index) {
    StructuredBuffer<uint> tables = ResourceDescriptorHeap[g_pow];
    return tables[index];
}

// v (exact in double) rounded toward zero to float32.
float TowardZero(double v) {
    float r = (float)v;
    if (abs((double)r) > abs(v)) r = asfloat(asuint(r) - 1u);
    return r;
}

#if defined(UZP_MODE_Tint) || defined(UZP_MODE_Saturation) || defined(UZP_MODE_Color) || defined(UZP_MODE_Value)
#define UZP_COMPONENT 1
#endif
#if defined(UZP_MODE_NormalMapCombine) || defined(UZP_MODE_NormalMapDetail) || defined(UZP_MODE_NormalMapInverseDetail)
#define UZP_NORMALMAP 1
#endif

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

// ── Hardware arithmetic of the recording GPU (hwmath.cpp) ────────────────────

static const uint kQuietNaN = 0x7FC00000u;

int HwDelta(uint offset, uint index) {
    const uint word = TableWord(offset + (index >> 4));
    return int((word >> ((index & 15u) * 2u)) & 3u) - 2;
}

// The index in [1, 4) of the normal y = z 4^k.
uint RootIndex(uint bits) {
    const int e = int((bits >> 23) & 0xFFu) - 127;
    const int k = e >= 0 ? e / 2 : -((1 - e) / 2);
    const uint z = uint(int(bits) - (k << 24));
    return z - 0x3F800000u;
}

// 1 / sqrt(y) correctly rounded for a positive normal y (m^2 is exact in double; fma rounds
// m^2 y - 1 once, so its sign is exact).
float RsqrtCorrect(float y) {
    float c = rsqrt(y);
    const double Y = (double)y;
    [loop] for (int i = 0; i < 4; ++i) {
        const float up = asfloat(asuint(c) + 1u);
        const float down = asfloat(asuint(c) - 1u);
        const double mUp = ((double)c + (double)up) * 0.5;
        const double mDown = ((double)down + (double)c) * 0.5;
        if (fma(mUp * mUp, Y, -1.0) < 0.0) c = up;
        else if (fma(mDown * mDown, Y, -1.0) > 0.0) c = down;
        else break;
    }
    return c;
}

float HwRcp(float x) {
    const uint bits = asuint(x);
    const uint sign = bits & 0x80000000u;
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return asfloat(kQuietNaN);
    if (magnitude == 0x7F800000u) return asfloat(sign);
    if (magnitude < 0x00800000u) return asfloat(sign | 0x7F800000u);
    const float c = Rcp(asfloat(magnitude));
    if (asuint(c) < 0x00800000u) return asfloat(sign);
    const uint r = asuint(c) + uint(HwDelta(UZP_TABLE_RCP, magnitude & 0x7FFFFFu));
    return asfloat(sign | r);
}

float HwSqrt(float y) {
    const uint bits = asuint(y);
    if ((bits & 0x7FFFFFFFu) > 0x7F800000u) return asfloat(kQuietNaN);
    if ((bits & 0x7FFFFFFFu) < 0x00800000u) return asfloat(bits & 0x80000000u);
    if ((bits & 0x80000000u) != 0u) return asfloat(kQuietNaN);
    if (bits == 0x7F800000u) return y;
    return asfloat(asuint(Sqrt(y)) + uint(HwDelta(UZP_TABLE_SQRT, RootIndex(bits))));
}

float HwRsqrt(float y) {
    const uint bits = asuint(y);
    if ((bits & 0x7FFFFFFFu) > 0x7F800000u) return asfloat(kQuietNaN);
    if ((bits & 0x7FFFFFFFu) < 0x00800000u) return asfloat((bits & 0x80000000u) | 0x7F800000u);
    if ((bits & 0x80000000u) != 0u) return asfloat(kQuietNaN);
    if (bits == 0x7F800000u) return 0.0f;
    return asfloat(asuint(RsqrtCorrect(y)) + uint(HwDelta(UZP_TABLE_RSQRT, RootIndex(bits))));
}

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
    return Clamp01(Fma(x, HwRcp(b), 1.0f));
}

float ColorDodge(float a, float b) {
    const float t = 1.0f - b;
    const float m = a * HwRcp(t);
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
    const float high = Fma(HwSqrt(a), twoBMinusOne, twoA * oneMinusB);
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
    const float m = a * HwRcp(b);
    return Fmax(Fmin(m, 1.0f), 0.0f);
}

#if !defined(UZP_COMPONENT) && !defined(UZP_NORMALMAP)
float BlendKernel(float a, float b) {
#if defined(UZP_MODE_Normal) || defined(UZP_MODE_Replace) || defined(UZP_MODE_PassThrough)
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
#endif

// ── Colour kernels (arith.cpp BlendColour) ───────────────────────────────────

#if defined(UZP_COMPONENT)
float Max3(float3 c) { return Fmax(Fmax(c.x, c.y), c.z); }
float Min3(float3 c) { return Fmin(Fmin(c.x, c.y), c.z); }

// The fitted hue in turns (arith.cpp Hue).
float Hue(float3 c) {
    const float eps = asfloat(kColourConstants[0]);
    const float d = Max3(c) - Min3(c);
    const bool minR = c.x <= c.y && c.x <= c.z;
    const bool minB = !minR && c.z < c.y;
    const float centre = minB ? 1.0f : (minR ? 3.0f : 5.0f);
    const float x = minB ? c.y - c.x : (minR ? c.z - c.y : c.x - c.z);
    const float h6 = Fma(x - 3.0f * eps, HwRcp(d + eps), centre);
    const float h = h6 * (1.0f / 6.0f);
    return h < 0.0f ? h + 1.0f : h;
}

// The hexcone weights of a hue (arith.cpp HueWeights).
float3 HueWeights(float h) {
    const float f = h - floor(h);
    return float3(Clamp01(abs(Fma(f, 6.0f, -3.0f)) - 1.0f), Clamp01(2.0f - abs(Fma(f, 6.0f, -2.0f))),
                  Clamp01(2.0f - abs(Fma(f, 6.0f, -4.0f))));
}

float3 BlendColour(float3 a, float3 b, float alpha) {
#if UZP_CHANNELS == 1
#if defined(UZP_MODE_Value)
    return b;
#else
    return a;
#endif
#else
#if defined(UZP_MODE_Tint) || defined(UZP_MODE_Color)
    const float3 hueSource = b;
#else
    const float3 hueSource = a;
#endif
#if defined(UZP_MODE_Saturation) || defined(UZP_MODE_Color)
    const float3 satSource = b;
#else
    const float3 satSource = a;
#endif
#if defined(UZP_MODE_Value)
    const float3 valueSource = b;
#else
    const float3 valueSource = a;
#endif
    const float3 w = HueWeights(Hue(hueSource));
    const float v = 2.0f * Max3(valueSource);
    const float smax = Max3(satSource);
    const float d = smax - Min3(satSource);
    const float inv = HwRcp(smax + asfloat(kColourConstants[0]));
#if defined(UZP_MODE_Saturation)
    const float keep = 1.0f - d * inv;
#else
    const float keep = Fma(-d, inv, 1.0f);
#endif
    const float lo = v * keep;
    const float span = v - lo;
    return float3(Fma(span, w.x, lo), Fma(span, w.y, lo), Fma(span, w.z, lo));
#endif
}
#endif

#if defined(UZP_NORMALMAP) || defined(UZP_VNORMAL)
float DotYxz(float3 u, float3 v) { return Fma(u.z, v.z, Fma(u.x, v.x, u.y * v.y)); }
float DotXyz(float3 u, float3 v) { return Fma(u.z, v.z, Fma(u.y, v.y, u.x * v.x)); }

float3 Normalise(float3 v) {
    const float inv = HwRsqrt(DotYxz(v, v));
    return float3(v.x * inv, v.y * inv, v.z * inv);
}

float3 DecodeNormal(float3 c) {
    float3 n = float3(c.x * 2.0f - 1.0f, c.y * 2.0f - 1.0f, c.z * 2.0f - 1.0f);
    n.z = Fmax(n.z, 0.0f);
    return Normalise(n);
}
#endif

#if defined(UZP_NORMALMAP)
// The recording GPU's GLSL asin (hwmath.cpp Asin).
float HwAsin(float x) {
    const uint bits = asuint(x);
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x3F800000u) return asfloat(kQuietNaN);
    if (magnitude < 0x00800000u) return 0.0f;
    const float t = asfloat(magnitude);
    const bool upper = t > 0.57f;
    const float a = upper ? HwSqrt(Fma(-0.5f, t, 0.5f)) : t;
    const float s = a * a;
    float r = 5.175137819e-2f;
    r = Fma(r, s, 1.816697683e-2f);
    r = Fma(r, s, 4.675685871e-2f);
    r = Fma(r, s, 7.484657646e-2f);
    r = Fma(r, s, 1.666701424e-1f);
    r = r * s;
    const float p = Fma(r, a, a);
    const float result = upper ? Fma(-2.0f, p, asfloat(kColourConstants[1])) : p;
    return (bits & 0x80000000u) != 0u ? -result : result;
}

// The table index of the GPU's sine and cosine for x in [0, float32(pi / 2)] (hwmath.cpp
// TrigIndex): the turn x float32(1 / (2 pi)) toward zero, times 2^25 (exact), truncated.
uint TrigIndex(float x) {
    const float u = TowardZero((double)x * (double)asfloat(0x3E22F983u));
    return (uint)(u * 33554432.0f);
}

// The unit normal rotated toward (0, 0, 1) by alpha (arith.cpp TowardFlat).
float3 TowardFlat(float3 n, float alpha) {
    if (!(alpha < 1.0f)) return n;
    const float z = Clamp01(n.z);
    const float w = Fma(-z, z, 1.0f);
    if (!(w > 0.0f)) return n;
    const float turned = alpha * (asfloat(kColourConstants[1]) - HwAsin(z));
    const uint k = TrigIndex(turned);
    const float sine = asfloat(PowWord(UZP_POW_SIN + k));
    const float cosine = asfloat(PowWord(UZP_POW_COS + k));
    const float scale = sine * HwRsqrt(w);
    return float3(n.x * scale, n.y * scale, cosine);
}
#endif

#if defined(UZP_NORMALMAP) || defined(UZP_VNORMAL)
float3 Reoriented(float3 base, float3 detail) {
    const float3 t = float3(base.x, base.y, base.z + 1.0f);
    const float3 u = float3(-detail.x, -detail.y, detail.z);
    const float d = DotXyz(t, u);
    return float3(Fma(t.x, d, -(u.x * t.z)), Fma(t.y, d, -(u.y * t.z)), t.z * (d - u.z));
}
#endif

#if defined(UZP_NORMALMAP)
float3 BlendColour(float3 a, float3 b, float alpha) {
#if UZP_CHANNELS == 1
    return b;
#else
    const float3 lower = DecodeNormal(a);
    const float3 upper = TowardFlat(DecodeNormal(b), alpha);
#if defined(UZP_MODE_NormalMapCombine)
    const float3 r = float3(lower.x + upper.x, lower.y + upper.y, lower.z * upper.z);
#elif defined(UZP_MODE_NormalMapDetail)
    const float3 r = Reoriented(lower, upper);
#else
    const float3 r = Reoriented(upper, lower);
#endif
    const float3 n = Normalise(r);
    return float3(Fma(n.x, 0.5f, 0.5f), Fma(n.y, 0.5f, 0.5f), Fma(n.z, 0.5f, 0.5f));
#endif
}
#endif

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
    return asfloat(TableWord(UZP_TABLE_UNORM16 + (code & 0xFFFFu)));
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
    if (enc == ENC_UNORM16) return asfloat(TableWord(UZP_TABLE_UNORM16 + (Codes(raw, ENC_UNORM16).x & 0xFFFFu)));
    return raw.x;
}

// ── Compositing of one texel (arith.cpp Composite) ───────────────────────────

float Mix(float a, float r, float alphaS) {
    if (g_effectMix) {
        const float e = r - a;
        return a + e * alphaS;
    }
#if defined(UZP_MODE_Replace)
    const float d = r - a;
    return a + d * alphaS;
#elif defined(UZP_MODE_ColorBurn)
    // Painter's ColorBurn mixes with one rounding of a (1 - alpha) + r alpha.
    return Fma(a, 1.0f - alphaS, r * alphaS);
#else
    const float oneMinusAlpha = 1.0f - alphaS;
    const float ta = a * oneMinusAlpha;
    const float tr = r * alphaS;
    return ta + tr;
#endif
}

float CompositeChannel(float a, float s, float r, float alphaB, float alphaS) {
#if UZP_ENC == 0 || UZP_ENC == 1
    r = Clamp01(r);
#endif
    if (alphaB == 1.0f) {
#if defined(UZP_NORMALMAP) && UZP_CHANNELS == 3
        return r;
#else
        return Mix(a, r, alphaS);
#endif
    }
    if (alphaB == 0.0f) return s;
    const float oneMinusAlphaS = 1.0f - alphaS;
    const float oneMinusAlphaB = 1.0f - alphaB;
    const float backdrop = (oneMinusAlphaS * alphaB) * a;
    const float blended = oneMinusAlphaB * s + alphaB * r;
    const float alphaO = alphaS + alphaB * oneMinusAlphaS;
    return (backdrop + alphaS * blended) * Rcp(alphaO);
}

// A pass-through group's composite (arith.cpp Composite, PassThrough): the backdrop a moved
// toward the group's result s by t = opacity x mask.
float PassThroughChannel(float a, float s, float alphaB, float alphaG, float t) {
    if (alphaB == 1.0f) return Fma(s - a, t, a);
    if (alphaB == 0.0f) return s;
    const float pa = a * alphaB;
    const float ps = s * alphaG;
    const float alphaO = Fma(alphaG - alphaB, t, alphaB);
    return Fma(ps - pa, t, pa) * Rcp(alphaO);
}

float StoreChannel(float v) {
#if UZP_RAW_OUTPUT
    if (isnan(v)) return asfloat(0x7FC00000u);
    return v;
#elif UZP_ENC == 0 || UZP_ENC == 1
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

// The float32 value of the binary16 nearest to v, ties to even (arith.cpp HalfNearestEven).
float HalfNearestEven(float v) {
    const uint bits = asuint(v);
    const uint sign = bits & 0x80000000u;
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return asfloat(sign | 0x7FC00000u);  // quiet NaN
    if (magnitude == 0x7F800000u) return v;
    if (magnitude >= 0x477FF000u) return asfloat(sign | 0x7F800000u);  // >= 65520: infinity
    if (magnitude < 0x38800000u) {  // a subnormal half (or zero), step 2^-24
        if (magnitude < 0x33000000u) return asfloat(sign);
        const uint significand = (magnitude & 0x7FFFFFu) | 0x800000u;
        const uint shift = 126u - (magnitude >> 23);
        uint q = significand >> shift;
        const uint rest = significand & ((1u << shift) - 1u);
        const uint half = 1u << (shift - 1u);
        if (rest > half || (rest == half && (q & 1u) != 0u)) q += 1u;
        return asfloat(sign | asuint(float(q) * 5.9604644775390625e-08f));
    }
    uint h = (magnitude >> 13) - (112u << 10);
    const uint rest = magnitude & 0x1FFFu;
    if (rest > 0x1000u || (rest == 0x1000u && (h & 1u) != 0u)) h += 1u;
    return asfloat(sign | (((h >> 10) + 112u) << 23) | ((h & 0x3FFu) << 13));
}

float StoreCoverage(float alpha) {
#if UZP_RAW_OUTPUT
    return alpha;
#endif
#if UZP_HALF_COVERAGE
    alpha = HalfNearestEven(alpha);
#endif
#if UZP_ENC == 0 || UZP_ENC == 1
    return CodeValue(WriteValue(alpha, UZP_ENC), UZP_ENC);
#elif UZP_ENC == 2
    return HalfTowardZero(alpha);
#else
    return alpha;
#endif
}

#if !defined(UZP_LEVELS) && !defined(UZP_VNORMAL)
[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    const uint base = g_block * 32u;
    const uint width = params[base + P_WIDTH];
    const uint height = params[base + P_HEIGHT];
    if (id.x >= width || id.y >= height) return;
    const uint flags = params[base + P_FLAGS];
    g_tables = params[base + P_TABLE16_SRV];
    g_pow = params[base + P_POW_SRV];
    g_effectMix = (flags & FLAG_EFFECT_MIX) != 0u;
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

    float3 r = float3(0.0f, 0.0f, 0.0f);
#if defined(UZP_COMPONENT) || defined(UZP_NORMALMAP)
    r = BlendColour(acc.xyz, src.xyz, alphaB == 1.0f ? alphaS : 1.0f);
#else
    r.x = BlendKernel(acc.x, src.x);
#if UZP_CHANNELS == 3
    r.y = BlendKernel(acc.y, src.y);
    r.z = BlendKernel(acc.z, src.z);
#endif
#endif
    float4 result = float4(0.0f, 0.0f, 0.0f, 1.0f);
#if defined(UZP_MODE_PassThrough)
    result.x = StoreChannel(PassThroughChannel(acc.x, src.x, alphaB, src.w, opacityMask));
#if UZP_CHANNELS == 3
    result.y = StoreChannel(PassThroughChannel(acc.y, src.y, alphaB, src.w, opacityMask));
    result.z = StoreChannel(PassThroughChannel(acc.z, src.z, alphaB, src.w, opacityMask));
#endif
    float alphaO = 1.0f;
    if (alphaB == 0.0f) alphaO = alphaS;
    else if (alphaB != 1.0f) alphaO = Fma(src.w - alphaB, opacityMask, alphaB);
#else
    result.x = StoreChannel(CompositeChannel(acc.x, src.x, r.x, alphaB, alphaS));
#if UZP_CHANNELS == 3
    result.y = StoreChannel(CompositeChannel(acc.y, src.y, r.y, alphaB, alphaS));
    result.z = StoreChannel(CompositeChannel(acc.z, src.z, r.z, alphaB, alphaS));
#endif
    float alphaO = 1.0f;
    if (alphaB == 0.0f) alphaO = alphaS;
    else if (alphaB != 1.0f) alphaO = alphaS + alphaB * (1.0f - alphaS);
#endif
#if UZP_ALPHA
    result.w = StoreCoverage(alphaO);
#else
    result.w = StoreCoverage(1.0f);
#endif
    StoreTexel(params[base + P_DST_UAV], p, result);
}
#endif

#if defined(UZP_LEVELS)
// ── Levels (arith.cpp Levels, hwmath.cpp Log2 / Exp2) ────────────────────────

#define L_WIDTH 0
#define L_HEIGHT 1
#define L_SRC 2
#define L_DST_UAV 3
#define L_TABLE16_SRV 4
#define L_POW_SRV 5
#define L_SRC_ALPHA 6
#define L_COMPONENTS 8

float HwLog2(float x) {
    const uint bits = asuint(x);
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return asfloat(kQuietNaN);
    if (magnitude < 0x00800000u) return asfloat(0xFF800000u);
    if ((bits & 0x80000000u) != 0u) return asfloat(kQuietNaN);
    if (bits == 0x7F800000u) return x;
    const int e = int(bits >> 23) - 127;
    const uint m = bits & 0x7FFFFFu;
    if (e >= 0) {
        const float hi = asfloat(PowWord(UZP_POW_LOG2HI + m));
        return e == 0 ? hi : TowardZero((double)e + (double)hi);
    }
    const float lo = asfloat(PowWord(UZP_POW_LOG2LO + m));
    return e == -1 ? lo : TowardZero((double)(e + 1) + (double)lo);
}

float HwExp2(float y) {
    if (isnan(y)) return asfloat(kQuietNaN);
    const float a = abs(y);
    const bool negative = y < 0.0f;
    if (a >= 256.0f) return negative ? 0.0f : asfloat(0x7F800000u);
    const float k = floor(a);
    const float f = a - k;
    const uint j = uint(f * 8388608.0f);
    const uint v = PowWord((negative ? UZP_POW_EXP2NEG : UZP_POW_EXP2POS) + j);
    // 2^k moves the exponent field; the float32 range decides the result.
    const int exponent = int((v >> 23) & 0xFFu) + (negative ? -int(k) : int(k));
    if (exponent <= 0) return 0.0f;
    if (exponent >= 255) return asfloat(0x7F800000u);
    return asfloat((v & 0x807FFFFFu) | (uint(exponent) << 23));
}

float Levels(float v, uint at) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    const float inMin = asfloat(params[at]);
    const float inMax = asfloat(params[at + 1u]);
    const float gamma = asfloat(params[at + 2u]);
    const float outMin = asfloat(params[at + 3u]);
    const float outMax = asfloat(params[at + 4u]);
    const float range = inMax - inMin;
    const float d = v - inMin;
    float t = d * HwRcp(range);
    if (params[at + 5u] != 0u) t = Clamp01(t);
    if (gamma != 1.0f) {
        const float l = HwLog2(abs(t));
        const float product = gamma * l;
        const float pw = HwExp2(product);
        t = t > 0.0f ? pw : (t < 0.0f ? -pw : t * pw);
    }
    const float outRange = outMax - outMin;
    return Fma(t, outRange, outMin);
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    const uint base = g_block * 32u;
    const uint width = params[base + L_WIDTH];
    const uint height = params[base + L_HEIGHT];
    if (id.x >= width || id.y >= height) return;
    g_tables = params[base + L_TABLE16_SRV];
    g_pow = params[base + L_POW_SRV];
    const int2 p = int2(id.xy);
    const bool hasAlpha = params[base + L_SRC_ALPHA] != 0u;
    const float4 v = LoadOperand(params[base + L_SRC], p, hasAlpha);
    float4 result = float4(0.0f, 0.0f, 0.0f, 1.0f);
    result.x = StoreChannel(Levels(v.x, base + L_COMPONENTS));
#if UZP_CHANNELS == 3
    result.y = StoreChannel(Levels(v.y, base + L_COMPONENTS + 6u));
    result.z = StoreChannel(Levels(v.z, base + L_COMPONENTS + 12u));
#endif
#if UZP_ALPHA
    result.w = StoreCoverage(v.w);
#else
    result.w = StoreCoverage(1.0f);
#endif
    StoreTexel(params[base + L_DST_UAV], p, result);
}
#endif

#if defined(UZP_VNORMAL)
// ── Virtual normal maps (height_to_normal.cpp) ──────────────────────────────

#define V_WIDTH 0
#define V_HEIGHT 1
#define V_FLAGS 2
#define V_DST_UAV 3
#define V_TABLE16_SRV 4
#define V_HEIGHT_CONST 5
#define V_NORMAL_SRV 6
#define V_NORMAL_CONST 7
#define V_HEIGHT_SRV 10

#define V_FLAG_HEIGHT_TILES 1u
#define V_FLAG_NORMAL_TILE 2u
#define V_FLAG_SOBEL 4u
#define V_FLAG_DIRECTX 8u

// The height at (x, y) of the tile's frame, read from the neighbouring tile across an edge.
float HeightAt(uint base, uint flags, int x, int y, int width, int height) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    if ((flags & V_FLAG_HEIGHT_TILES) == 0u) return asfloat(params[base + V_HEIGHT_CONST]);
    const int ox = x < 0 ? -1 : (x >= width ? 1 : 0);
    const int oy = y < 0 ? -1 : (y >= height ? 1 : 0);
    const uint srv = params[base + V_HEIGHT_SRV + uint((oy + 1) * 3 + ox + 1)];
    return LoadTexel(srv, int2(x - ox * width, y - oy * height)).x;
}

// (a + 2 b) + c: one (1, 2, 1) row or column of the Sobel stencil.
float Smooth(float a, float b, float c) { return (a + 2.0f * b) + c; }

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    const uint base = g_block * 32u;
    const int width = int(params[base + V_WIDTH]);
    const int height = int(params[base + V_HEIGHT]);
    if (int(id.x) >= width || int(id.y) >= height) return;
    const uint flags = params[base + V_FLAGS];
    g_tables = params[base + V_TABLE16_SRV];
    const int x = int(id.x);
    const int y = int(id.y);
    float h[9];
    [unroll] for (int dy = -1; dy <= 1; ++dy) {
        [unroll] for (int dx = -1; dx <= 1; ++dx) {
            h[(dy + 1) * 3 + dx + 1] = HeightAt(base, flags, x + dx, y + dy, width, height);
        }
    }
    float3 v;
    if ((flags & V_FLAG_SOBEL) != 0u) {
        const float left = Smooth(h[0], h[3], h[6]);
        const float right = Smooth(h[2], h[5], h[8]);
        const float top = Smooth(h[0], h[1], h[2]);
        const float bottom = Smooth(h[6], h[7], h[8]);
        v = float3(left - right, bottom - top, 3.125f);
    } else {
        v = float3(h[3] - h[4], h[4] - h[1], 0.390625f);
    }
    float3 channel;
    if ((flags & V_FLAG_NORMAL_TILE) != 0u) {
        channel = LoadTexel(params[base + V_NORMAL_SRV], int2(x, y)).xyz;
    } else {
        channel = float3(asfloat(params[base + V_NORMAL_CONST]), asfloat(params[base + V_NORMAL_CONST + 1]),
                         asfloat(params[base + V_NORMAL_CONST + 2]));
    }
    const float3 heightNormal = Normalise(v);
    const float3 combined = Normalise(Reoriented(float3(0.0f, 0.0f, 1.0f), heightNormal));
    const float3 n = Normalise(Reoriented(combined, DecodeNormal(channel)));
    const float ny = (flags & V_FLAG_DIRECTX) != 0u ? -n.y : n.y;
    float4 result = float4(Fma(n.x, 0.5f, 0.5f), Fma(ny, 0.5f, 0.5f), Fma(n.z, 0.5f, 0.5f), 1.0f);
    result.x = StoreChannel(result.x);
    result.y = StoreChannel(result.y);
    result.z = StoreChannel(result.z);
    StoreTexel(params[base + V_DST_UAV], int2(x, y), result);
}
#endif
