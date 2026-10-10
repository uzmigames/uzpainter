// Resampling of one image into another of any size (src/render/resample.h), also the filter step
// of mip generation (src/render/mips.h). One thread per output texel.
//
// Filters: Nearest (the source texel under the output texel centre, copied unchanged), Bilinear
// (Painter's fixed-point bilinear of parity/semantics/resampling.json: 8-bit sub-texel position,
// integer weights) and Box (exact area weights). Colour modes: Linear (every channel filtered as
// stored), Srgb (8-bit unorm channels 0-2 decoded through the IEC 61966-2-1 table, filtered in
// linear float and encoded through the threshold table; channel 3 linear) and Normal (channels
// 0-2 a vector, filtered then renormalised; channel 3 linear).

#include "image_common.hlsli"
#include "srgb_tables.hlsli"

#define FILTER_NEAREST 0u
#define FILTER_BILINEAR 1u
#define FILTER_BOX 2u
#define WRAP_CLAMP 0u
#define WRAP_REPEAT 1u
#define COLOUR_LINEAR 0u
#define COLOUR_SRGB 1u
#define COLOUR_NORMAL 2u

cbuffer Params : register(b0) {
    uint g_srcWidth;
    uint g_srcHeight;
    uint g_dstWidth;
    uint g_dstHeight;
    uint g_mode;       // filter | wrap << 4 | colour << 8 | encoding << 12 | channels << 16
    uint g_srcSrv;
    uint g_dstUav;
    uint g_boxAx;      // Box: a source texel is `a` units wide, an output texel `b` units (x)
    uint g_boxBx;
    uint g_boxAy;      // (y)
    uint g_boxBy;
    uint g_invTotal;   // Box: float32 bits of 1 / (bx * by), rounded on the CPU
};

static uint s_filter;
static uint s_wrap;
static uint s_colour;
static uint s_enc;
static uint s_channels;

// Per-channel accumulators: integer sums of weight x code for linear unorm channels, float sums
// of weight x value for every other channel, in tap order.
static uint64_t s_sum[4];
static float s_acc[4];

bool FloatPath(uint c) {
    if (!IsUnorm(s_enc)) return true;
    return c < 3u && s_colour != COLOUR_LINEAR;
}

float SrgbDecode(uint code) { return asfloat(kSrgbDecode[code]); }

// The largest k in 0..255 with lin >= threshold k (threshold 0 is never tested).
uint SrgbEncode(float lin) {
    uint lo = 0u;
    uint hi = 255u;
    while (lo < hi) {
        const uint mid = (lo + hi + 1u) >> 1;
        if (lin >= asfloat(kSrgbEncodeThreshold[mid])) {
            lo = mid;
        } else {
            hi = mid - 1u;
        }
    }
    return lo;
}

void AddTap(int2 p, uint weight, float weightF) {
    const float4 texel = LoadTexel(g_srcSrv, p);
    const uint4 codes = Codes(texel, s_enc);
    [unroll] for (uint c = 0; c < 4u; ++c) {
        if (c >= s_channels) break;
        if (!FloatPath(c)) {
            s_sum[c] += uint64_t(weight) * uint64_t(codes[c]);
            continue;
        }
        float value;
        if (!IsUnorm(s_enc)) {
            value = texel[c];
        } else if (s_colour == COLOUR_SRGB) {
            value = SrgbDecode(codes[c]);
        } else {
            value = float(int(2u * codes[c]) - int(UnormMax(s_enc)));
        }
        const float term = weightF * value;
        s_acc[c] = s_acc[c] + term;
    }
}

int Wrap(int i, uint size) {
    if (s_wrap == WRAP_REPEAT) {
        const int n = int(size);
        return ((i % n) + n) % n;
    }
    return clamp(i, 0, int(size) - 1);
}

int64_t FloorDiv(int64_t a, int64_t b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

// Painter's 8-bit sub-texel position of output texel i: X = floor(256 x + 0.5) with
// x = (i + 0.5) src / dst - 0.5, computed exactly.
int64_t SubTexel(uint i, uint src, uint dst) {
    const int64_t numerator =
        256 * int64_t(2u * i + 1u) * int64_t(src) - 255 * int64_t(dst);
    return FloorDiv(numerator, 2 * int64_t(dst));
}

void GatherBilinear(uint2 i) {
    const int64_t x = SubTexel(i.x, g_srcWidth, g_dstWidth);
    const int64_t y = SubTexel(i.y, g_srcHeight, g_dstHeight);
    const int x0 = int(x >> 8);
    const int y0 = int(y >> 8);
    const uint fx = uint(x & 255);
    const uint fy = uint(y & 255);
    const uint w11 = (fx * fy + 127u) >> 8;
    const uint w10 = fx - w11;
    const uint w01 = fy - w11;
    const uint w00 = 256u - fx - fy + w11;
    const int xa = Wrap(x0, g_srcWidth);
    const int xb = Wrap(x0 + 1, g_srcWidth);
    const int ya = Wrap(y0, g_srcHeight);
    const int yb = Wrap(y0 + 1, g_srcHeight);
    AddTap(int2(xa, ya), w00, float(w00));
    AddTap(int2(xb, ya), w10, float(w10));
    AddTap(int2(xa, yb), w01, float(w01));
    AddTap(int2(xb, yb), w11, float(w11));
}

// Source texel s spans [s a, (s + 1) a), output texel i spans [i b, (i + 1) b).
uint BoxWeight(uint s, uint i, uint a, uint b) {
    const uint lo = max(s * a, i * b);
    const uint hi = min((s + 1u) * a, (i + 1u) * b);
    return hi - lo;
}

void GatherBox(uint2 i) {
    const uint sx0 = (i.x * g_boxBx) / g_boxAx;
    const uint sx1 = ((i.x + 1u) * g_boxBx - 1u) / g_boxAx;
    const uint sy0 = (i.y * g_boxBy) / g_boxAy;
    const uint sy1 = ((i.y + 1u) * g_boxBy - 1u) / g_boxAy;
    for (uint sy = sy0; sy <= sy1; ++sy) {
        const uint wy = BoxWeight(sy, i.y, g_boxAy, g_boxBy);
        for (uint sx = sx0; sx <= sx1; ++sx) {
            const uint wx = BoxWeight(sx, i.x, g_boxAx, g_boxBx);
            const float weightF = float(wx) * float(wy);
            AddTap(int2(sx, sy), wx * wy, weightF);
        }
    }
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_dstWidth || id.y >= g_dstHeight) return;
    s_filter = g_mode & 15u;
    s_wrap = (g_mode >> 4) & 15u;
    s_colour = (g_mode >> 8) & 15u;
    s_enc = (g_mode >> 12) & 15u;
    s_channels = (g_mode >> 16) & 15u;
    const int2 pos = int2(id.xy);

    if (s_filter == FILTER_NEAREST) {
        const uint sx = (2u * id.x + 1u) * g_srcWidth / (2u * g_dstWidth);
        const uint sy = (2u * id.y + 1u) * g_srcHeight / (2u * g_dstHeight);
        StoreTexel(g_dstUav, pos, LoadTexel(g_srcSrv, int2(sx, sy)));
        return;
    }

    [unroll] for (uint c = 0; c < 4u; ++c) {
        s_sum[c] = 0;
        s_acc[c] = 0.0f;
    }
    uint64_t total;
    float scale;
    if (s_filter == FILTER_BILINEAR) {
        GatherBilinear(id.xy);
        total = 256;
        scale = 0.00390625f;
    } else {
        GatherBox(id.xy);
        total = uint64_t(g_boxBx) * uint64_t(g_boxBy);
        scale = asfloat(g_invTotal);
    }

    float4 result = float4(0.0f, 0.0f, 0.0f, 1.0f);
    [unroll] for (uint c = 0; c < 4u; ++c) {
        if (c >= s_channels) break;
        if (!FloatPath(c)) {
            result[c] = CodeValue(WriteRatio(s_sum[c], total, s_enc), s_enc);
        } else if (s_colour == COLOUR_SRGB && c < 3u) {
            const float lin = s_acc[c] * scale;
            result[c] = CodeValue(SrgbEncode(lin), s_enc);
        } else if (!(s_colour == COLOUR_NORMAL && c < 3u)) {
            const float value = s_acc[c] * scale;
            result[c] = FloatStore(value, s_enc);
        }
    }
    if (s_colour == COLOUR_NORMAL) {
        const float xx = s_acc[0] * s_acc[0];
        const float yy = s_acc[1] * s_acc[1];
        const float zz = s_acc[2] * s_acc[2];
        const float xy = xx + yy;
        const float d = xy + zz;
        float3 n = float3(0.0f, 0.0f, 1.0f);
        if (d > 0.0f) {
            const float r = DeterministicRsqrt(d);
            n = float3(s_acc[0] * r, s_acc[1] * r, s_acc[2] * r);
        }
        [unroll] for (uint c = 0; c < 3u; ++c) {
            if (IsUnorm(s_enc)) {
                const float halfN = n[c] * 0.5f;
                const float unit = halfN + 0.5f;
                result[c] = CodeValue(WriteValue(unit, s_enc), s_enc);
            } else {
                result[c] = FloatStore(n[c], s_enc);
            }
        }
    }
    StoreTexel(g_dstUav, pos, result);
}
