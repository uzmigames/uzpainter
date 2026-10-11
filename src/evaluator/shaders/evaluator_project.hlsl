// UV projection kernel of the compositor (src/evaluator/projection_uv.h, kernelgen.h), one
// specialisation per destination tile format: UZP_ENC (ENC_* of image_common.hlsli),
// UZP_CHANNELS (1 or 3), UZP_SRGB (codes are sRGB8), UZP_ALPHA (the tile carries a coverage
// plane). Mirrors ProjectTexel, SampleValue and the store of cpu_store.cpp operation for
// operation: the UV transform in double precision (each operation one IEEE double operation,
// compiled IEEE-strict and `precise`), the fixed-point coordinates and weights in integers, the
// texels as float32(c / M) correctly rounded, the bilinear filter in integers (BilinearFilter:
// operands aligned to the largest weighed texel, rounded once to float32, ties up), and the
// channel's write rule.
//
// Parameters: a block of 32 uints in the arena behind root constant 0, block index in root
// constant 1 (kernelgen.h, ProjectParam). The bitmap is a structured buffer of uints holding its
// codes packed in sample order (rows top first, channels interleaved): two 16-bit codes or four
// 8-bit codes per uint, low bits first.

#include "image_common.hlsli"
#include "evaluator_tables.hlsli"

cbuffer Root : register(b0) {
    uint g_paramsSrv;
    uint g_block;
};

#define P_WIDTH 0
#define P_HEIGHT 1
#define P_X0 2
#define P_Y0 3
#define P_DST_UAV 4
#define P_IMAGE_SRV 5
#define P_IMAGE_WIDTH 6
#define P_IMAGE_HEIGHT 7
#define P_IMAGE_CHANNELS 8
#define P_IMAGE_SIXTEEN 9
#define P_FILTER 10
#define P_WRAP 11
#define P_INV_WIDTH 12
#define P_INV_HEIGHT 14
#define P_COS 16
#define P_SIN 18
#define P_SCALE_U 20
#define P_SCALE_V 22
#define P_OFFSET_U 24
#define P_OFFSET_V 26
#define P_SIGNED 28

// core::FilteringMode and core::UVWrapMode.
#define FILTER_NEAREST 2u
#define WRAP_REPEAT_NONE 0u
#define WRAP_REPEAT_HORIZONTALLY 1u
#define WRAP_REPEAT_VERTICALLY 2u
#define WRAP_REPEAT 3u

static uint g_base;

uint Param(uint offset) {
    StructuredBuffer<uint> params = ResourceDescriptorHeap[g_paramsSrv];
    return params[g_base + offset];
}
double ParamDouble(uint offset) { return asdouble(Param(offset), Param(offset + 1u)); }

int64_t FloorToInt(double d) {
    const int64_t t = (int64_t)d;  // toward zero
    return (double)t > d ? t - 1 : t;
}

int64_t Address(int64_t index, uint extent, bool repeat) {
    const int64_t n = (int64_t)extent;
    if (repeat) return ((index % n) + n) % n;
    return index < 0 ? 0 : (index >= n ? n - 1 : index);
}

uint Code(uint srv, uint sixteen, uint width, uint channels, int64_t x, int64_t y, uint c) {
    StructuredBuffer<uint> image = ResourceDescriptorHeap[srv];
    const uint channel = channels == 1u ? 0u : c;
    const uint k = ((uint)y * width + (uint)x) * channels + channel;
    if (sixteen != 0u) {
        const uint word = image[k >> 1];
        return (k & 1u) != 0u ? word >> 16 : word & 0xFFFFu;
    }
    const uint word = image[k >> 2];
    return (word >> ((k & 3u) * 8u)) & 0xFFu;
}

// The float32 nearest to s / d for 0 <= s < 2^24 and d = 255 or 65535: the hardware quotient
// moved to the float whose interval holds the exact quotient, decided with exact double residuals
// (q d - s is exact for 25-bit q and 16-bit d). s / d is never a tie between two floats (d is odd,
// so a quotient with a finite binary expansion is an integer).
float DivNearest(uint s, uint d) {
    float q = (float)s / (float)d;
    const double S = (double)s;
    const double D = (double)d;
    [loop] for (int i = 0; i < 8; ++i) {
        const float up = asfloat(asuint(q) + 1u);
        const float down = q > 0.0f ? asfloat(asuint(q) - 1u) : 0.0f;
        precise const double mUp = ((double)q + (double)up) * 0.5;
        precise const double mDown = ((double)down + (double)q) * 0.5;
        precise const double rUp = mUp * D - S;
        precise const double rDown = mDown * D - S;
        if (rUp < 0.0) q = up;
        else if (q > 0.0f && rDown > 0.0) q = down;
        else break;
    }
    return q;
}

// projection_uv.h BilinearFilter on float32 texels in [0, 1]: E the frexp exponent of the largest
// texel of non-zero weight (positive floats order as their bits), each operand floor(t 2^(28 - E))
// from the texel's bits, the exact integer sum (below 2^37) rounded to 24 significant bits, ties
// up, scaled by 2^(E - 36) with an exact power of two.
uint Operand(float t, int exponent) {
    const uint bits = asuint(t);
    if (bits == 0u) return 0u;
    const uint significand = (bits & 0x7FFFFFu) | 0x800000u;  // t = significand 2^(field - 150)
    const int shift = (int)(bits >> 23) - 150 + 28 - exponent;
    if (shift >= 0) return significand << (uint)shift;
    return shift > -32 ? significand >> (uint)(-shift) : 0u;
}

float BilinearFilter(uint4 w, float4 t) {
    uint largest = 0u;
    [unroll] for (uint k = 0; k < 4u; ++k) {
        if (w[k] != 0u) largest = max(largest, asuint(t[k]));
    }
    if (largest == 0u) return 0.0f;
    const int exponent = (int)(largest >> 23) - 126;
    uint64_t sum = 0;
    [unroll] for (uint q = 0; q < 4u; ++q) sum += (uint64_t)w[q] * (uint64_t)Operand(t[q], exponent);
    const uint high = (uint)(sum >> 32);
    const int length = high != 0u ? 33 + (int)firstbithigh(high) : 1 + (int)firstbithigh((uint)sum);
    const int shift = max(length - 24, 0);
    uint significand = (uint)(sum >> (uint)shift);
    if (shift > 0 && ((sum >> (uint)(shift - 1)) & 1u) != 0u) significand += 1u;
    const float scale = asfloat((uint)(shift + exponent - 36 + 127) << 23);  // 2^(shift + E - 36)
    return (float)significand * scale;
}

// ── Storage (cpu_store.cpp StoreValue; evaluator_blend.hlsl) ─────────────────

float HalfTowardZero(float v) {
    const uint bits = asuint(v);
    const uint sign = bits & 0x80000000u;
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return asfloat(sign | 0x7FC00000u);
    if (magnitude == 0x7F800000u) return v;
    if (magnitude >= 0x477FE000u) return asfloat(sign | 0x477FE000u);
    if (magnitude < 0x38800000u) {
        const float scaled = asfloat(magnitude) * 16777216.0f;
        const uint mantissa = uint(scaled);
        return asfloat(sign | asuint(float(mantissa) * 5.9604644775390625e-08f));
    }
    return asfloat(sign | (magnitude & 0xFFFFE000u));
}

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
    return v;
#endif
}

float StoreCoverage(float alpha) {
#if UZP_ENC == 0 || UZP_ENC == 1
    return CodeValue(WriteValue(alpha, UZP_ENC), UZP_ENC);
#else
    return alpha;
#endif
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    g_base = g_block * 32u;
    const uint width = Param(P_WIDTH);
    const uint height = Param(P_HEIGHT);
    if (id.x >= width || id.y >= height) return;
    const uint i = Param(P_X0) + id.x;
    const uint j = Param(P_Y0) + id.y;
    const uint srv = Param(P_IMAGE_SRV);
    const uint imageWidth = Param(P_IMAGE_WIDTH);
    const uint imageHeight = Param(P_IMAGE_HEIGHT);
    const uint channels = Param(P_IMAGE_CHANNELS);
    const uint sixteen = Param(P_IMAGE_SIXTEEN);
    const uint filter = Param(P_FILTER);
    const uint wrap = Param(P_WRAP);
    const double cosR = ParamDouble(P_COS);
    const double sinR = ParamDouble(P_SIN);

    precise const double u = ((double)i + 0.5) * ParamDouble(P_INV_WIDTH);
    precise const double v = 1.0 - ((double)j + 0.5) * ParamDouble(P_INV_HEIGHT);
    precise const double a = ((u - 0.5) - ParamDouble(P_OFFSET_U)) * ParamDouble(P_SCALE_U);
    precise const double b = ((v - 0.5) - ParamDouble(P_OFFSET_V)) * ParamDouble(P_SCALE_V);
    precise const double ca = cosR * a;
    precise const double sb = sinR * b;
    precise const double u2 = (ca + sb) + 0.5;
    precise const double sa = (-sinR) * a;
    precise const double cb = cosR * b;
    precise const double v2 = (sa + cb) + 0.5;
    precise const double x = u2 * (double)imageWidth - 0.5;
    precise const double y = (1.0 - v2) * (double)imageHeight - 0.5;

    const bool repeatX = wrap == WRAP_REPEAT || wrap == WRAP_REPEAT_HORIZONTALLY;
    const bool repeatY = wrap == WRAP_REPEAT || wrap == WRAP_REPEAT_VERTICALLY;
    const bool covered = (repeatX || (u2 >= 0.0 && u2 < 1.0)) && (repeatY || (v2 >= 0.0 && v2 < 1.0));

    const uint range = sixteen != 0u ? 65535u : 255u;
    float3 value = float3(0.0f, 0.0f, 0.0f);
    if (covered) {
        if (filter == FILTER_NEAREST) {
            precise const double xr = x + 0.5;
            precise const double yr = y + 0.5;
            const int64_t xi = Address(FloorToInt(xr), imageWidth, repeatX);
            const int64_t yi = Address(FloorToInt(yr), imageHeight, repeatY);
            [unroll] for (uint c = 0; c < 3u; ++c) {
                value[c] = DivNearest(Code(srv, sixteen, imageWidth, channels, xi, yi, c), range);
            }
        } else {
            precise const double xs = x * 256.0 + 0.5;
            precise const double ys = y * 256.0 + 0.5;
            const int64_t fixedX = FloorToInt(xs);
            const int64_t fixedY = FloorToInt(ys);
            const int64_t x0 = fixedX >> 8;
            const int64_t y0 = fixedY >> 8;
            const uint fx = (uint)(fixedX & 255);
            const uint fy = (uint)(fixedY & 255);
            const uint w11 = (fx * fy + 127u) >> 8;
            const uint w10 = fx - w11;
            const uint w01 = fy - w11;
            const uint w00 = 256u - fx - fy + w11;
            const int64_t xa = Address(x0, imageWidth, repeatX);
            const int64_t xb = Address(x0 + 1, imageWidth, repeatX);
            const int64_t ya = Address(y0, imageHeight, repeatY);
            const int64_t yb = Address(y0 + 1, imageHeight, repeatY);
            [unroll] for (uint c = 0; c < 3u; ++c) {
                const float t00 = DivNearest(Code(srv, sixteen, imageWidth, channels, xa, ya, c), range);
                const float t10 = DivNearest(Code(srv, sixteen, imageWidth, channels, xb, ya, c), range);
                const float t01 = DivNearest(Code(srv, sixteen, imageWidth, channels, xa, yb, c), range);
                const float t11 = DivNearest(Code(srv, sixteen, imageWidth, channels, xb, yb, c), range);
                value[c] = BilinearFilter(uint4(w00, w10, w01, w11), float4(t00, t10, t01, t11));
            }
        }
    }
    if (covered && Param(P_SIGNED) != 0u) {
        // The Height channel: 2 v - 1, two float32 operations.
        precise const float3 twice = 2.0f * value;
        value = twice - 1.0f;
    }
    float4 result = float4(0.0f, 0.0f, 0.0f, 1.0f);
    result.x = StoreChannel(value.x);
#if UZP_CHANNELS == 3
    result.y = StoreChannel(value.y);
    result.z = StoreChannel(value.z);
#endif
#if UZP_ALPHA
    result.w = StoreCoverage(covered ? 1.0f : 0.0f);
#else
    result.w = StoreCoverage(1.0f);
#endif
    StoreTexel(Param(P_DST_UAV), int2(id.xy), result);
}
