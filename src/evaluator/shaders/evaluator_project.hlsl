// UV projection kernel of the compositor (src/evaluator/projection_uv.h, kernelgen.h), one
// specialisation per destination tile format: UZP_ENC (ENC_* of image_common.hlsli),
// UZP_CHANNELS (1 or 3), UZP_SRGB (codes are sRGB8), UZP_ALPHA (the tile carries a coverage
// plane). Mirrors ProjectTexel, SampleValue and the store of cpu_store.cpp operation for
// operation: the UV transform in double precision (each operation one IEEE double operation,
// compiled IEEE-strict and `precise`), the fixed-point coordinates and weights in integers, the
// texels as float32(c / M) correctly rounded or a float32 image's values (2 t - 1 on the Height
// channel, before the filter), the bilinear filter in integers (BilinearFilter: operands aligned
// to the largest weighed texel magnitude, rounded once to float32, ties away from zero), and the
// channel's write rule.
//
// Parameters: a block of 32 uints in the arena behind root constant 0, block index in root
// constant 1 (kernelgen.h, ProjectParam). The bitmap is a structured buffer of uints holding its
// codes packed in sample order (rows top first, channels interleaved): two 16-bit codes or four
// 8-bit codes per uint, low bits first, or one float32 value per uint (a decoded sRGB bitmap). A
// minifying bilinear projection (P_CHAIN non-zero) samples the bitmap's float32 mip chain through
// the texture unit (texture_unit.h, mirrored below) with Painter's float32 arithmetic around it
// (projection_uv.cpp `Minified`); with P_TU_SRGB8 non-zero the chain holds an 8-bit sRGB bitmap's
// level-0 codes, one per uint, summed with the sRGB8 texture's arithmetic (decision 219).

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
#define P_CHAIN 29
#define P_TU_TABLES 30
#define P_TU_SRGB8 31

// core::FilteringMode and core::UVWrapMode.
#define FILTER_SHARP 1u
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

// P_IMAGE_SIXTEEN: the bitmap's encoding.
#define IMAGE_UNORM8 0u
#define IMAGE_UNORM16 1u
#define IMAGE_FLOAT32 2u
// An R16F texture (decision 218): float32 bits of binary16 values; its filter returns a binary16.
#define IMAGE_FLOAT16 3u

uint Code(uint srv, uint sixteen, uint width, uint channels, int64_t x, int64_t y, uint c) {
    StructuredBuffer<uint> image = ResourceDescriptorHeap[srv];
    const uint channel = channels == 1u ? 0u : c;
    const uint k = ((uint)y * width + (uint)x) * channels + channel;
    if (sixteen == IMAGE_FLOAT32 || sixteen == IMAGE_FLOAT16) return image[k];
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

// The texel's value (projection_uv.cpp `TexelValue`): float32(c / M) of a code, or the stored
// value of a float32 image (a decoded sRGB bitmap).
float TexelValue(uint srv, uint sixteen, uint width, uint channels, int64_t x, int64_t y, uint c, uint range) {
    const uint code = Code(srv, sixteen, width, channels, x, y, c);
    return sixteen == IMAGE_FLOAT32 || sixteen == IMAGE_FLOAT16 ? asfloat(code) : DivNearest(code, range);
}

// projection_uv.h BilinearFilter on float32 texels: E the frexp exponent of the largest texel
// magnitude of non-zero weight (positive floats order as their bits), each operand |t| 2^(28 - E)
// truncated from the texel's bits with the texel's sign, the exact integer sum (magnitude below
// 2^37) rounded to 24 significant bits, ties away from zero, scaled by 2^(E - 36) with an exact
// power of two.
uint Operand(float t, int exponent) {
    const uint bits = asuint(t) & 0x7FFFFFFFu;
    if (bits == 0u) return 0u;
    const uint significand = (bits & 0x7FFFFFu) | 0x800000u;  // t = significand 2^(field - 150)
    const int shift = (int)(bits >> 23) - 150 + 28 - exponent;
    if (shift >= 0) return significand << (uint)shift;
    return shift > -32 ? significand >> (uint)(-shift) : 0u;
}

float BilinearFilter(uint4 w, float4 t) {
    uint largest = 0u;
    [unroll] for (uint k = 0; k < 4u; ++k) {
        if (w[k] != 0u) largest = max(largest, asuint(t[k]) & 0x7FFFFFFFu);
    }
    if (largest == 0u) return 0.0f;
    const int exponent = (int)(largest >> 23) - 126;
    int64_t signedSum = 0;
    [unroll] for (uint q = 0; q < 4u; ++q) {
        const int64_t term = (int64_t)w[q] * (int64_t)Operand(t[q], exponent);
        signedSum += (asuint(t[q]) & 0x80000000u) != 0u ? -term : term;
    }
    const bool negative = signedSum < 0;
    const uint64_t sum = (uint64_t)(negative ? -signedSum : signedSum);
    const uint high = (uint)(sum >> 32);
    const int length = high != 0u ? 33 + (int)firstbithigh(high) : 1 + (int)firstbithigh((uint)sum);
    const int shift = max(length - 24, 0);
    uint significand = (uint)(sum >> (uint)shift);
    if (shift > 0 && ((sum >> (uint)(shift - 1)) & 1u) != 0u) significand += 1u;
    const float scale = asfloat((uint)(shift + exponent - 36 + 127) << 23);  // 2^(shift + E - 36)
    const float magnitude = (float)significand * scale;
    return negative ? -magnitude : magnitude;
}

// The float32 value of the binary16 nearest to v, ties away from zero (arith.cpp HalfNearestAway):
// the result of the bilinear filter of an R16F texture (decision 218).
float HalfNearestAway(float v) {
    const uint bits = asuint(v);
    const uint sign = bits & 0x80000000u;
    const uint magnitude = bits & 0x7FFFFFFFu;
    if (magnitude >= 0x7F800000u) return v;
    if (magnitude >= 0x477FF000u) return asfloat(sign | 0x7F800000u);
    if (magnitude < 0x38800000u) {
        if (magnitude < 0x33000000u) return asfloat(sign);
        const uint significand = (magnitude & 0x7FFFFFu) | 0x800000u;
        const uint shift = 126u - (magnitude >> 23);
        uint q = significand >> shift;
        if ((significand & ((1u << shift) - 1u)) >= (1u << (shift - 1u))) q += 1u;
        return asfloat(sign | asuint(float(q) * 5.9604644775390625e-08f));
    }
    uint h = magnitude & 0xFFFFE000u;
    if ((magnitude & 0x1FFFu) >= 0x1000u) h += 0x2000u;
    return asfloat(sign | h);
}

// projection_uv.h RangeValue: on the Height channel a bitmap texel enters the filter as 2 t - 1,
// two float32 operations.
float SignedValue(float t, bool signedRange) {
    if (!signedRange) return t;
    precise const float twice = 2.0f * t;
    return twice - 1.0f;
}

// ── The texture unit (texture_unit.h), operation for operation ───────────────
// The tables buffer holds the LOD table (two uint16 per uint, the lower index in the low half)
// followed by the geometry words; the chain buffer holds the bitmap's float32 RGB mip chain,
// rows bottom up, level after level.

#define TU_LOD_ENTRIES (3u * 512u * 512u + 512u)
#define TU_LOD_WORDS (TU_LOD_ENTRIES / 2u)
#define TU_RHO 513u
#define TU_FRACTIONS 147u
#define TU_UNMEASURED 0xFFu

static uint g_tuTables;
static uint g_tuChain;
static uint g_tuSrgb8;

uint TuLod(uint index) {
    StructuredBuffer<uint> tables = ResourceDescriptorHeap[g_tuTables];
    const uint word = tables[index >> 1];
    return (index & 1u) != 0u ? word >> 16 : word & 0xFFFFu;
}

uint TuGeometry(uint word) {
    StructuredBuffer<uint> tables = ResourceDescriptorHeap[g_tuTables];
    return tables[TU_LOD_WORDS + word];
}

float3 TuTexel(uint index) {
    StructuredBuffer<float> chain = ResourceDescriptorHeap[g_tuChain];
    return float3(chain[index * 3u], chain[index * 3u + 1u], chain[index * 3u + 2u]);
}

int TuCoarse(int e) { return e - ((((e + 126) % 4) + 4) % 4); }

// The larger component of a gradient: its magnitude, sign and axis.
void TuAxisOf(float2 g, out float length, out int sign, out int axis) {
    const float x = abs(g.x);
    const float y = abs(g.y);
    if (x >= y) {
        length = x;
        sign = g.x < 0.0f ? -1 : 1;
        axis = 0;
    } else {
        length = y;
        sign = g.y < 0.0f ? -1 : 1;
        axis = 1;
    }
}

struct TuFootprint {
    int lambdaMajor;
    int lambda;
    int rho;
    int biased;
    int sign;
    int axis;
    bool magnify;
    uint lower;
    uint f;
};

TuFootprint TuResolve(float2 ddx, float2 ddy, uint size, uint levels, int bias) {
    float lx, ly;
    int sx, sy, ax, ay;
    TuAxisOf(ddx, lx, sx, ax);
    TuAxisOf(ddy, ly, sy, ay);
    // The longer gradient by its exponent and 9-bit mantissa; ddx on a tie.
    const bool xMajor = (asuint(lx) >> 14) >= (asuint(ly) >> 14);
    const uint majorBits = asuint(xMajor ? lx : ly);
    const uint minorBits = asuint(xMajor ? ly : lx);
    const int sizeLog = (int)firstbitlow(size);
    const uint ma = (majorBits >> 14) & 511u;
    const uint mb = (minorBits >> 14) & 511u;
    const int ea = (int)(majorBits >> 23) - 127 + sizeLog;
    const int eb = (int)(minorBits >> 23) - 127 + sizeLog;
    TuFootprint fp;
    fp.sign = xMajor ? sx : sy;
    fp.axis = xMajor ? ax : ay;
    fp.lambdaMajor = (int)TuLod(3u * 512u * 512u + ma) + 256 * (ea - 3);
    const int d = ea - eb;
    fp.lambda = d >= 3 ? fp.lambdaMajor - 512 : (int)TuLod(((uint)d * 512u + ma) * 512u + mb) + 256 * (ea - 3);
    // The minor-axis LOD is clamped at 0 before the anisotropy is taken from it.
    fp.lambda = max(fp.lambda, 0);
    fp.rho = fp.lambdaMajor - fp.lambda;
    fp.biased = fp.lambda + bias;
    fp.magnify = false;
    fp.lower = 0u;
    fp.f = 0u;
    const uint last = levels - 1u;
    if (fp.lambdaMajor <= 0 && fp.biased <= 0) {
        fp.magnify = true;
    } else if (fp.biased >= 0) {
        fp.lower = (uint)(fp.biased >> 8);
        fp.f = (uint)(fp.biased & 255);
        if (fp.lower >= last) {
            fp.lower = last;
            fp.f = 0u;
        }
    }
    return fp;
}

// One probe: up to eight taps (chain index, weight in 1/1024) and its offset. `half` is the tap
// count of the first of a p = 0 pair's two probes when the sRGB8 unit sums them apart (0: one).
struct TuProbe {
    int offset;
    uint count;
    uint half;
    uint texel[8];
    uint weight[8];
};

void TuSplit(inout TuProbe probe, uint w, uint n, int64_t px, int64_t py, uint level, uint levelOffset,
             uint side, bool repeatU, bool repeatV) {
    const int64_t top = (int64_t)256 * (int64_t)(side - 1u);
    if (!repeatU) px = px < 0 ? 0 : (px > top ? top : px);
    if (!repeatV) py = py < 0 ? 0 : (py > top ? top : py);
    const uint fx = (uint)(px & 255);
    const uint fy = (uint)(py & 255);
    const uint x1 = (w * fx + 128u) >> 8;
    const uint x0 = w - x1;
    const uint w11 = (x1 * fy + 128u) >> 8;
    const uint w01 = (x0 * fy + 127u) >> 8;
    const uint weights[4] = {x0 - w01, x1 - w11, w01, w11};
    const int64_t n64 = (int64_t)side;
    [unroll] for (uint k = 0; k < 4u; ++k) {
        if (weights[k] == 0u) continue;
        int64_t tx = (px >> 8) + (int64_t)(k & 1u);
        int64_t ty = (py >> 8) + (int64_t)(k >> 1);
        tx = repeatU ? ((tx % n64) + n64) % n64 : (tx < 0 ? 0 : (tx >= n64 ? n64 - 1 : tx));
        ty = repeatV ? ((ty % n64) + n64) % n64 : (ty < 0 ? 0 : (ty >= n64 ? n64 - 1 : ty));
        probe.texel[probe.count] = levelOffset + (uint)(ty * n64 + tx);
        probe.weight[probe.count] = n * weights[k];
        probe.count += 1u;
    }
}

// n 2^e rounded to the nearest float32, ties up (n < 2^63).
float TuTiesUp(uint64_t n, int e) {
    if (n == 0) return 0.0f;
    const uint high = (uint)(n >> 32);
    const int length = high != 0u ? 33 + (int)firstbithigh(high) : 1 + (int)firstbithigh((uint)n);
    const int shift = max(length - 24, 0);
    uint q = (uint)(n >> (uint)shift);
    if (shift > 0 && ((n >> (uint)(shift - 1)) & 1u) != 0u) q += 1u;
    // q <= 2^24 is exact in float32; the power of two lies in the normal range for the domain.
    return (float)q * asfloat((uint)(e + shift + 127) << 23);
}

// The sRGB8 code of channel c of chain texel `index`, its decode and its segment exponent (the
// binary exponent of the decode of c | 7; texture_unit.h, step 5').
uint TuSrgb8Code(uint index, uint c) {
    StructuredBuffer<uint> chain = ResourceDescriptorHeap[g_tuChain];
    return chain[index * 3u + c];
}
int TuSegmentExponent(uint code) { return (int)((kSrgb8Operand[code | 7u] >> 23) & 255u) - 126; }

// x (in units of 2^-26) truncated to a multiple of 2^lsb.
int64_t TuTruncate26(int64_t x, int lsb) {
    const int shift = lsb + 26;
    if (shift <= 0) return x;
    return (x >> (uint)shift) << (uint)shift;
}

// x (>= 0, in units of 2^-26) rounded to the nearest binary16, ties away from zero.
float TuHalfNearestAway(int64_t x) {
    if (x == 0) return 0.0f;
    const uint64_t ux = (uint64_t)x;
    const uint high = (uint)(ux >> 32);
    const int length = high != 0u ? 33 + (int)firstbithigh(high) : 1 + (int)firstbithigh((uint)ux);
    const int lsb = max(length - 11, 2);
    const uint q = (uint)((ux + ((uint64_t)1 << (uint)(lsb - 1))) >> (uint)lsb);
    return (float)q * asfloat((uint)(lsb - 26 + 127) << 23);
}

// The sRGB8 texture's sums of one channel (texture_unit.h, steps 5' and 6'; texture_unit.cpp
// `Srgb8Filter`, operation for operation).
float TuSrgb8Channel(TuProbe probes[8], uint group[8], uint count, uint c) {
    uint live = 0u;
    uint lastTexel = 0u;
    for (uint k = 0u; k < count; ++k) {
        for (uint q = 0u; q < probes[k].count; ++q) {
            if (probes[k].weight[q] != 0u) {
                live += 1u;
                lastTexel = probes[k].texel[q];
            }
        }
    }
    if (live == 1u) return asfloat(kSrgb8Operand[TuSrgb8Code(lastTexel, c)]);
    uint partProbe[16];
    uint partBegin[16];
    uint partEnd[16];
    uint partGroup[16];
    uint n = 0u;
    for (uint k1 = 0u; k1 < count; ++k1) {
        if (probes[k1].half != 0u) {
            partProbe[n] = k1; partBegin[n] = 0u; partEnd[n] = probes[k1].half; partGroup[n] = group[k1]; n += 1u;
            partProbe[n] = k1; partBegin[n] = probes[k1].half; partEnd[n] = probes[k1].count; partGroup[n] = group[k1];
            n += 1u;
        } else {
            partProbe[n] = k1; partBegin[n] = 0u; partEnd[n] = probes[k1].count; partGroup[n] = group[k1]; n += 1u;
        }
    }
    int exponent[16];
    int64_t value[16];
    int levelExponent[2] = {-1000, -1000};
    for (uint k2 = 0u; k2 < n; ++k2) {
        int e = -1000;
        for (uint q2 = partBegin[k2]; q2 < partEnd[k2]; ++q2) {
            e = max(e, TuSegmentExponent(TuSrgb8Code(probes[partProbe[k2]].texel[q2], c)));
        }
        exponent[k2] = e;
        levelExponent[partGroup[k2] / 2u] = max(levelExponent[partGroup[k2] / 2u], e);
    }
    for (uint k3 = 0u; k3 < n; ++k3) {
        value[k3] = 0;
        if (partBegin[k3] == partEnd[k3]) continue;  // a probe of weight 0 adds nothing
        const int e3 = exponent[k3];
        int64_t sum = 0;
        for (uint q3 = partBegin[k3]; q3 < partEnd[k3]; ++q3) {
            const uint code = TuSrgb8Code(probes[partProbe[k3]].texel[q3], c);
            sum += (int64_t)probes[partProbe[k3]].weight[q3] * (int64_t)Operand(asfloat(kSrgb8Operand[code]), e3 + 20);
        }
        // S 2^(E - 18) in units of 2^-26 (every segment exponent is at least -8).
        const int grid = max(TuCoarse(levelExponent[partGroup[k3] / 2u]), -6) - 16;
        value[k3] = TuTruncate26(sum << (uint)(e3 + 8), grid);
    }
    int64_t acc = 0;
    for (uint k4 = 0u; k4 < n; ++k4) {
        if (k4 >= 1u) {
            int g = -1000;
            for (uint q4 = 0u; q4 < n; ++q4) {
                if (partGroup[q4] <= partGroup[k4] && value[q4] != 0) g = max(g, exponent[q4]);
            }
            if (g > -1000) acc = TuTruncate26(acc, TuCoarse(g) - 16);
        }
        acc += value[k4];
    }
    int gAll = -1000;
    for (uint q5 = 0u; q5 < n; ++q5) {
        if (value[q5] != 0) gAll = max(gAll, exponent[q5]);
    }
    if (gAll > -1000) acc = TuTruncate26(acc, TuCoarse(gAll) - 16);
    return TuHalfNearestAway(acc);
}

float3 TuSampleAt(TuFootprint fp, uint size, uint levels, float u, float v, bool repeatU, bool repeatV) {
    TuProbe probes[8];
    uint group[8];
    uint count = 0u;
    const uint t = fp.magnify ? 0u : min(256u, (7u * fp.f) >> 2);
    uint levelOffset = 0u;
    for (uint skip = 0u; skip < fp.lower; ++skip) levelOffset += (size >> skip) * (size >> skip);
    [loop] for (uint role = 0u; role < 2u; ++role) {
        const uint level = fp.lower + role;
        if (level >= levels) break;
        const uint side = size >> level;
        uint4 entry = uint4(0u, 0u, 0u, 0u);
        bool active = true;
        if (fp.magnify) {
            if (role != 0u) break;
            entry = uint4(1u | (4u << 8), 0u, 256u, 0u);
        } else if ((role == 0u && t == 256u) || (role == 1u && t == 0u)) {
            active = false;
        } else {
            const uint s = fp.sign > 0 ? 0u : 1u;
            const uint r = (uint)fp.rho;
            const uint index = fp.f >= TU_FRACTIONS ? (TU_RHO * TU_FRACTIONS * 4u + r * 2u + s) * 4u
                                                    : (((r * TU_FRACTIONS + fp.f) * 2u + s) * 2u + role) * 4u;
            entry = uint4(TuGeometry(index), TuGeometry(index + 1u), TuGeometry(index + 2u), TuGeometry(index + 3u));
        }
        // The cell of the opposite sign, whose pair at p != 0 splits an sRGB8 pair at p = 0
        // (texture_unit.h, step 5').
        uint4 opposite = uint4(0u, 0u, 0u, 0u);
        if (active && g_tuSrgb8 != 0u && !fp.magnify) {
            const uint so = fp.sign > 0 ? 1u : 0u;
            const uint ro = (uint)fp.rho;
            const uint io = fp.f >= TU_FRACTIONS ? (TU_RHO * TU_FRACTIONS * 4u + ro * 2u + so) * 4u
                                                 : (((ro * TU_FRACTIONS + fp.f) * 2u + so) * 2u + role) * 4u;
            opposite = uint4(TuGeometry(io), TuGeometry(io + 1u), TuGeometry(io + 2u), TuGeometry(io + 3u));
        }
        if (active) {
            precise const double xs = ((double)u * (double)side - 0.5) * 256.0 + 0.5;
            precise const double ys = ((double)v * (double)side - 0.5) * 256.0 + 0.5;
            const int64_t x = FloorToInt(xs);
            const int64_t y = FloorToInt(ys);
            TuProbe found[4];
            uint n = 0u;
            const uint pairs = entry.x & 0xFFu;
            for (uint k = 0u; k < pairs; ++k) {
                const uint mult = (entry.x >> (8u + 8u * k)) & 0xFFu;
                const int p = (int)((entry.y >> (16u * k)) & 0xFFFFu);
                const uint lr = k == 0u ? entry.z : entry.w;
                const uint wl = lr & 0xFFFFu;
                const uint wr = lr >> 16;
                if (p == 0) {
                    found[n].offset = 0;
                    found[n].count = 0u;
                    found[n].half = 0u;
                    if (wl != 0u) TuSplit(found[n], wl, mult, x, y, level, levelOffset, side, repeatU, repeatV);
                    const uint first = found[n].count;
                    if (wr != 0u) TuSplit(found[n], wr, mult, x, y, level, levelOffset, side, repeatU, repeatV);
                    const uint pairsOpposite = opposite.x & 0xFFu;
                    const bool apart = pairsOpposite != TU_UNMEASURED && k < pairsOpposite &&
                                       ((opposite.y >> (16u * k)) & 0xFFFFu) != 0u;
                    if (apart && first != 0u && first != found[n].count) found[n].half = first;
                    n += 1u;
                } else {
                    found[n].offset = -p;
                    found[n].count = 0u;
                    found[n].half = 0u;
                    TuSplit(found[n], wl, mult, fp.axis == 0 ? x - p : x, fp.axis == 0 ? y : y - p, level,
                            levelOffset, side, repeatU, repeatV);
                    found[n + 1u].offset = p;
                    found[n + 1u].count = 0u;
                    found[n + 1u].half = 0u;
                    TuSplit(found[n + 1u], wr, mult, fp.axis == 0 ? x + p : x, fp.axis == 0 ? y : y + p, level,
                            levelOffset, side, repeatU, repeatV);
                    n += 2u;
                }
            }
            // Insertion sort by offset along the major gradient (stable).
            for (uint a = 1u; a < n; ++a) {
                TuProbe moving = found[a];
                uint b = a;
                while (b > 0u && fp.sign * found[b - 1u].offset > fp.sign * moving.offset) {
                    found[b] = found[b - 1u];
                    b -= 1u;
                }
                found[b] = moving;
            }
            for (uint k2 = 0u; k2 < n; ++k2) {
                probes[count] = found[k2];
                group[count] = role * 2u + k2 / 2u;
                count += 1u;
            }
        }
        levelOffset += side * side;
    }

    float3 result = float3(0.0f, 0.0f, 0.0f);
    if (g_tuSrgb8 != 0u) {
        [loop] for (uint cs = 0u; cs < 3u; ++cs) result[cs] = TuSrgb8Channel(probes, group, count, cs);
        return result;
    }
    [loop] for (uint c = 0u; c < 3u; ++c) {
        int exponent[8];
        uint64_t sum[8];
        for (uint k = 0u; k < count; ++k) {
            uint largest = 0u;
            for (uint q = 0u; q < probes[k].count; ++q) largest = max(largest, asuint(TuTexel(probes[k].texel[q])[c]));
            sum[k] = 0;
            exponent[k] = 0;
            if (largest == 0u) continue;
            const int e = (int)(largest >> 23) - 126;
            exponent[k] = e;
            for (uint q2 = 0u; q2 < probes[k].count; ++q2) {
                sum[k] += (uint64_t)probes[k].weight[q2] * (uint64_t)Operand(TuTexel(probes[k].texel[q2])[c], e);
            }
        }
        uint64_t acc = 0;
        int accExp = 0;
        for (uint k3 = 0u; k3 < count; ++k3) {
            if (k3 >= 2u) {
                int g = 0;
                bool any = false;
                for (uint q3 = 0u; q3 < count; ++q3) {
                    if (group[q3] <= group[k3] && sum[q3] != 0) {
                        g = any ? max(g, exponent[q3]) : exponent[q3];
                        any = true;
                    }
                }
                const int lsb = TuCoarse(g) - 36;
                if (any && acc != 0 && lsb > accExp) {
                    const int shift = lsb - accExp;
                    acc = shift >= 64 ? 0 : acc >> (uint)shift;
                    accExp = lsb;
                }
            }
            if (sum[k3] == 0) continue;
            uint64_t part = sum[k3];
            int partExp = exponent[k3] - 38;
            const int grid = TuCoarse(exponent[k3]) - 36;
            if (grid > partExp) {
                part >>= (uint)(grid - partExp);
                partExp = grid;
            }
            if (part == 0) continue;
            if (acc == 0) {
                acc = part;
                accExp = partExp;
            } else {
                const int low = min(accExp, partExp);
                acc = (acc << (uint)(accExp - low)) + (part << (uint)(partExp - low));
                accExp = low;
            }
        }
        result[c] = TuTiesUp(acc, accExp);
    }
    return result;
}

float3 TuSample(uint size, uint levels, float u, float v, float2 ddx, float2 ddy, int bias, bool repeatU,
                bool repeatV) {
    return TuSampleAt(TuResolve(ddx, ddy, size, levels, bias), size, levels, u, v, repeatU, repeatV);
}

// ── Painter's minification around the texture unit (projection_uv.cpp) ────────

// fma(a, b, c) rounded once to float32: the exact product and sum in double with the TwoSum error
// deciding a sum that lands on a float32 midpoint.
float Fma32(float a, float b, float c) {
    precise const double p = (double)a * (double)b;
    precise const double s = p + (double)c;
    precise const double back = s - p;
    precise const double e = (p - (s - back)) + ((double)c - back);
    float r = (float)s;
    if ((double)r != s) {
        const bool above = s > (double)r;
        const float n = asfloat(asuint(r) + ((above == (r >= 0.0f)) ? 1u : 0xFFFFFFFFu));
        precise const double mid = ((double)r + (double)n) * 0.5;
        if (mid == s && e != 0.0) r = ((e > 0.0) == ((double)n > (double)r)) ? n : r;
    }
    return r;
}

// sqrt correctly rounded (x > 0 normal): the hardware square root moved to the float whose
// rounding interval holds sqrt(x), decided with exact double squares of the midpoints.
float SqrtCorrect(float x) {
    if (x <= 0.0f) return 0.0f;
    float r = sqrt(x);
    [loop] for (int k = 0; k < 4; ++k) {
        const float up = asfloat(asuint(r) + 1u);
        precise const double mu = ((double)r + (double)up) * 0.5;
        if ((double)x > mu * mu) {
            r = up;
            continue;
        }
        const float down = asfloat(asuint(r) - 1u);
        precise const double md = ((double)down + (double)r) * 0.5;
        if ((double)x < md * md) {
            r = down;
            continue;
        }
        break;
    }
    return r;
}

struct PainterMatrix {
    float m00, m01, m02, m10, m11, m12;
};

// Painter's float32 matrix, written over the double transform's slots for a minifying
// projection (kernelgen.cpp EncodeProjectParams, projection_uv.cpp PainterMatrix).
PainterMatrix PainterMatrixParams() {
    PainterMatrix m;
    m.m00 = asfloat(Param(16));
    m.m01 = asfloat(Param(17));
    m.m02 = asfloat(Param(18));
    m.m10 = asfloat(Param(19));
    m.m11 = asfloat(Param(20));
    m.m12 = asfloat(Param(21));
    return m;
}

float2 PainterPoint(PainterMatrix m, uint i, uint j, double invWidth, double invHeight) {
    const float u = (float)(((double)i + 0.5) * invWidth);
    const float v = (float)(1.0 - ((double)j + 0.5) * invHeight);
    precise const float pu = m.m01 * v;
    precise const float pv = m.m11 * v;
    precise const float x = Fma32(m.m00, u, pu) + m.m02;
    precise const float y = Fma32(m.m10, u, pv) + m.m12;
    return float2(x, y);
}

float3 Minified(PainterMatrix m, uint i, uint j, double invWidth, double invHeight, float2 ddx, float2 ddy,
                bool sharp, uint size, bool repeat) {
    const uint levels = firstbithigh(size) + 1u;
    const float2 uv = PainterPoint(m, i, j, invWidth, invHeight);
    if (sharp) return TuSample(size, levels, uv.x, uv.y, ddx, ddy, -384, repeat, repeat);
    const float2 x0 = PainterPoint(m, i & ~1u, j, invWidth, invHeight);
    const float2 x1 = PainterPoint(m, i | 1u, j, invWidth, invHeight);
    const float2 y0 = PainterPoint(m, i, j & ~1u, invWidth, invHeight);
    const float2 y1 = PainterPoint(m, i, j | 1u, invWidth, invHeight);
    precise const float dux = x1.x - x0.x;
    precise const float dvx = x1.y - x0.y;
    precise const float duy = y1.x - y0.x;
    precise const float dvy = y1.y - y0.y;
    const float third = asfloat(0x3EAAAAABu);  // float32(1 / 3)
    precise const float2 hqDdx = float2(third * ddx.x, third * ddx.y);
    precise const float2 hqDdy = float2(third * ddy.x, third * ddy.y);
    const int2 steps[9] = {int2(0, 0), int2(1, 0), int2(-1, 0), int2(0, -1), int2(0, 1), int2(1, -1), int2(-1, -1),
                           int2(-1, 1), int2(0, 0)};
    const float weights[9] = {0.25f, 0.125f, 0.125f, 0.125f, 0.125f, 0.0625f, 0.0625f, 0.0625f, 0.0625f};
    float3 acc = float3(0.0f, 0.0f, 0.0f);
    [loop] for (uint k = 0u; k < 9u; ++k) {
        precise const float sx = (float)steps[k].x * third;
        precise const float sy = (float)steps[k].y * third;
        precise const float pu = (uv.x + sx * dux) + sy * duy;
        precise const float pv = (uv.y + sx * dvx) + sy * dvy;
        const float3 sample = TuSample(size, levels, pu, pv, hqDdx, hqDdy, 0, repeat, repeat);
        [unroll] for (uint c = 0u; c < 3u; ++c) {
            precise const float weighed = weights[k] * sample[c];
            precise const float sum = acc[c] + weighed;
            acc[c] = sum;
        }
    }
    TuFootprint level0;
    level0.lambdaMajor = 0;
    level0.lambda = 0;
    level0.rho = 0;
    level0.biased = 0;
    level0.sign = 1;
    level0.axis = 0;
    level0.magnify = true;
    level0.lower = 0u;
    level0.f = 0u;
    const float3 base = TuSampleAt(level0, size, levels, uv.x, uv.y, repeat, repeat);
    precise const float lengthX = SqrtCorrect(dux * dux + dvx * dvx);
    precise const float lengthY = SqrtCorrect(duy * duy + dvy * dvy);
    precise const float spread = min(lengthX, lengthY) * (float)size - 1.0f;
    const float alpha = min(max(spread, 0.0f), 1.0f);
    precise const float keep = 1.0f - alpha;
    float3 value;
    [unroll] for (uint c = 0u; c < 3u; ++c) {
        precise const float part = acc[c] * alpha;
        value[c] = Fma32(base[c], keep, part);
    }
    return value;
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
    const bool signedRange = Param(P_SIGNED) != 0u;
    const double cosR = ParamDouble(P_COS);
    const double sinR = ParamDouble(P_SIN);
    const uint range = sixteen != 0u ? 65535u : 255u;

    const uint chainSrv = Param(P_CHAIN);
    if (filter != FILTER_NEAREST && chainSrv != 0u) {
        // Minification through the texture unit (projection_uv.cpp `Minified`).
        g_tuChain = chainSrv;
        g_tuSrgb8 = Param(P_TU_SRGB8);
        g_tuTables = Param(P_TU_TABLES);
        const double invWidth = ParamDouble(P_INV_WIDTH);
        const double invHeight = ParamDouble(P_INV_HEIGHT);
        const PainterMatrix m = PainterMatrixParams();
        const float2 uv = PainterPoint(m, i, j, invWidth, invHeight);
        const bool repeat = wrap == WRAP_REPEAT;
        const bool inside = uv.x >= 0.0f && uv.x < 1.0f && uv.y >= 0.0f && uv.y < 1.0f;
        const bool minCovered = repeat || inside;
        const float texel = (float)invWidth;
        precise const float2 ddx = float2(m.m00 * texel, m.m10 * texel);
        precise const float2 ddy = float2(m.m01 * texel, m.m11 * texel);
        float3 minValue = float3(0.0f, 0.0f, 0.0f);
        if (minCovered) {
            minValue = Minified(m, i, j, invWidth, invHeight, ddx, ddy, filter == FILTER_SHARP, imageWidth, repeat);
        }
        float4 minResult = float4(0.0f, 0.0f, 0.0f, 1.0f);
        minResult.x = StoreChannel(minValue.x);
#if UZP_CHANNELS == 3
        minResult.y = StoreChannel(minValue.y);
        minResult.z = StoreChannel(minValue.z);
#endif
#if UZP_ALPHA
        minResult.w = StoreCoverage(minCovered ? 1.0f : 0.0f);
#else
        minResult.w = StoreCoverage(1.0f);
#endif
        StoreTexel(Param(P_DST_UAV), int2(id.xy), minResult);
        return;
    }

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

    float3 value = float3(0.0f, 0.0f, 0.0f);
    if (covered) {
        if (filter == FILTER_NEAREST) {
            precise const double xr = x + 0.5;
            precise const double yr = y + 0.5;
            // A tie between two rows takes the upper one: ceil(y + 1/2) - 1 (projection_uv.h).
            const int64_t xi = Address(FloorToInt(xr), imageWidth, repeatX);
            const int64_t yi = Address(-FloorToInt(-yr) - 1, imageHeight, repeatY);
            [unroll] for (uint c = 0; c < 3u; ++c) {
                value[c] = SignedValue(TexelValue(srv, sixteen, imageWidth, channels, xi, yi, c, range), signedRange);
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
                const float t00 = SignedValue(TexelValue(srv, sixteen, imageWidth, channels, xa, ya, c, range), signedRange);
                const float t10 = SignedValue(TexelValue(srv, sixteen, imageWidth, channels, xb, ya, c, range), signedRange);
                const float t01 = SignedValue(TexelValue(srv, sixteen, imageWidth, channels, xa, yb, c, range), signedRange);
                const float t11 = SignedValue(TexelValue(srv, sixteen, imageWidth, channels, xb, yb, c, range), signedRange);
                value[c] = BilinearFilter(uint4(w00, w10, w01, w11), float4(t00, t10, t01, t11));
                if (sixteen == IMAGE_FLOAT16) value[c] = HalfNearestAway(value[c]);
            }
        }
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
