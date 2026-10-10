// Shared arithmetic of UzPainter's image passes (src/render/image_pass.h): texel encodings,
// the float-to-UNORM write rule, rounding to half precision and a deterministic reciprocal
// square root. Every operation is exact integer arithmetic or a single IEEE float operation
// (kernels are compiled IEEE-strict, `-Gis`), so the CPU references in tests/render/reference/
// reproduce the results bit for bit.
//
// Resources are reached through the SM 6.6 descriptor heap (`ResourceDescriptorHeap[index]`);
// the indices arrive in the root constants (b0).

#define ENC_UNORM8 0u
#define ENC_UNORM16 1u
#define ENC_FLOAT16 2u
#define ENC_FLOAT32 3u

bool IsUnorm(uint enc) { return enc <= ENC_UNORM16; }
uint UnormBits(uint enc) { return enc == ENC_UNORM8 ? 8u : 16u; }
uint UnormMax(uint enc) { return enc == ENC_UNORM8 ? 255u : 65535u; }

float4 LoadTexel(uint srv, int2 p) {
    Texture2D<float4> image = ResourceDescriptorHeap[srv];
    return image.Load(int3(p, 0));
}

void StoreTexel(uint uav, int2 p, float4 value) {
    RWTexture2D<float4> image = ResourceDescriptorHeap[uav];
    image[p] = value;
}

// The codes of a stored unorm texel: exact for any load conversion within half a code.
uint4 Codes(float4 value, uint enc) {
    const float m = float(UnormMax(enc));
    const float4 scaled = value * m;
    const float4 biased = scaled + 0.5f;
    return uint4(biased);
}

// The value whose store conversion yields `code` (float-to-UNORM conversion rounds to the
// nearest code, and code / M is far closer to `code` than half a code).
float CodeValue(uint code, uint enc) { return float(code) / float(UnormMax(enc)); }

// Write rule of an exact rational value v = s / (t * M), M = 2^n - 1: v is truncated to n + 4
// fractional bits, V = floor(v * 2^(n+4)), and stored as the nearest code, ties down:
// floor((V * M + 2^(n+3) - 1) / 2^(n+4)). V is computed as floor(floor(s * 2^(n+4) / t) / M)
// with s = q t + r so that no product exceeds 64 bits.
uint WriteRatio(uint64_t s, uint64_t t, uint enc) {
    const uint n = UnormBits(enc);
    const uint64_t m = UnormMax(enc);
    const uint64_t q = s / t;
    const uint64_t r = s % t;
    const uint64_t f = (q << (n + 4)) + ((r << (n + 4)) / t);
    const uint64_t v = f / m;
    const uint64_t bias = (uint64_t(1) << (n + 3)) - 1;
    return uint((v * m + bias) >> (n + 4));
}

// Write rule of a float value: clamped to [0, 1] (NaN to 0), truncated to n + 4 fractional bits
// (an exact power-of-two scaling and a truncation) and stored as the nearest code, ties down.
uint WriteValue(float value, uint enc) {
    const uint n = UnormBits(enc);
    const uint64_t m = UnormMax(enc);
    float v = value >= 0.0f ? value : 0.0f;
    v = v <= 1.0f ? v : 1.0f;
    const float scaled = v * float(1u << (n + 4));
    const uint64_t truncated = uint64_t(uint(scaled));
    const uint64_t bias = (uint64_t(1) << (n + 3)) - 1;
    return uint((truncated * m + bias) >> (n + 4));
}

// `x` rounded to the nearest binary16 value, ties to even, returned as the float32 holding it
// exactly (so the store conversion to a 16-bit float format is exact). Overflow gives infinity.
float RoundToHalf(float x) {
    const uint bits = asuint(x);
    const uint sign = bits & 0x80000000u;
    const uint a = bits & 0x7FFFFFFFu;
    if (a >= 0x7F800000u) return x;                              // infinity or NaN
    if (a >= 0x477FF000u) return asfloat(sign | 0x7F800000u);    // >= 65520: infinity
    if (a <= 0x33000000u) return asfloat(sign);                  // <= 2^-25: zero
    const int e = int(a >> 23) - 127;
    if (e == -25) return asfloat(sign | 0x33800000u);            // (2^-25, 2^-24): 2^-24
    // Normal halves keep 10 mantissa bits; subnormal halves (e < -14) keep bits down to 2^-24.
    const uint drop = e >= -14 ? 13u : uint(13 + (-14 - e));
    const uint unit = 1u << drop;
    const uint low = a & (unit - 1u);
    uint kept = a & ~(unit - 1u);
    const uint halfUnit = unit >> 1;
    if (low > halfUnit || (low == halfUnit && (kept & unit) != 0u)) kept += unit;
    return asfloat(sign | kept);
}

// The value a float format stores for `x`: half rounding for 16-bit floats, unchanged for 32-bit.
float FloatStore(float x, uint enc) { return enc == ENC_FLOAT16 ? RoundToHalf(x) : x; }

// 1 / sqrt(d) for d > 0 by three Newton steps from the bit-level estimate, in single IEEE
// operations (no hardware approximation, so the CPU reproduces it exactly).
float DeterministicRsqrt(float d) {
    float y = asfloat(0x5F375A86u - (asuint(d) >> 1));
    const float h = d * 0.5f;
    [unroll] for (uint i = 0; i < 3; ++i) {
        const float yy = y * y;
        const float t = h * yy;
        const float u = 1.5f - t;
        y = y * u;
    }
    return y;
}
