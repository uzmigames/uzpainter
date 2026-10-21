// Shared arithmetic of UzPainter's image passes (src/render/image_pass.h): texel encodings,
// the float-to-UNORM write rule, rounding to half precision and a deterministic reciprocal
// square root. Every operation is exact integer arithmetic or a single IEEE float operation
// (kernels are compiled IEEE-strict, `-Gis`), so the CPU references in tests/render/reference/
// reproduce the results bit for bit.
//
// Resources are reached through the SM 6.6 descriptor heap (`ResourceDescriptorHeap[index]`);
// the indices arrive in the root constants (b0).
//
// Fixed slots (UZP_FIXED_SLOTS: SPIR-V of a kernel that defines UZP_DST_FORMAT or
// UZP_NO_STORAGE_IMAGE, decision 313): the vendored Vulkan backend has no descriptor heap, only
// one descriptor set of fixed bindings (src/render/kernel_bindings.h). A resource "index" is then
// its slot: sampled images t0..t15 (bindings 0..15), structured buffers at bindings 64..79, and
// one storage image u0 (binding 48) of the format UZP_DST_FORMAT names (DST_* below; declared, so
// no `...WithoutFormat` capability is needed; UZP_NO_STORAGE_IMAGE: the kernel writes none).
// With UZP_RW_BUFFERS the structured buffers are read-write (the image passes' seed and state
// buffers: `RwWord`, `RwStore`, `RwAdd`). Such a kernel takes its root constants as push
// constants (recorded per dispatch; the vendored backend's b0 emulation is one buffer per command
// list). Every other kernel keeps the descriptor heap on both targets.

#define ENC_UNORM8 0u
#define ENC_UNORM16 1u
#define ENC_FLOAT16 2u
#define ENC_FLOAT32 3u

// UZP_DST_FORMAT values (uz::RHIFormat of the destination tile, evaluator/formats.h RhiFormatOf).
#define DST_R8 0
#define DST_R16 1
#define DST_R16F 2
#define DST_R32F 3
#define DST_RGBA8 4
#define DST_RGBA16 5
#define DST_RGBA16F 6
#define DST_RGBA32F 7
// The two-channel image-pass formats (src/render/image_pass.h ImagePassFormatOf).
#define DST_RG8 8
#define DST_RG16 9
#define DST_RG16F 10
#define DST_RG32F 11

bool IsUnorm(uint enc) { return enc <= ENC_UNORM16; }
uint UnormBits(uint enc) { return enc == ENC_UNORM8 ? 8u : 16u; }
uint UnormMax(uint enc) { return enc == ENC_UNORM8 ? 255u : 65535u; }

#if defined(__spirv__) && (defined(UZP_DST_FORMAT) || defined(UZP_NO_STORAGE_IMAGE))
#define UZP_FIXED_SLOTS 1

Texture2D<float4> g_slotTexture0 : register(t0);
Texture2D<float4> g_slotTexture1 : register(t1);
Texture2D<float4> g_slotTexture2 : register(t2);
Texture2D<float4> g_slotTexture3 : register(t3);
Texture2D<float4> g_slotTexture4 : register(t4);
Texture2D<float4> g_slotTexture5 : register(t5);
Texture2D<float4> g_slotTexture6 : register(t6);
Texture2D<float4> g_slotTexture7 : register(t7);
Texture2D<float4> g_slotTexture8 : register(t8);
Texture2D<float4> g_slotTexture9 : register(t9);
Texture2D<float4> g_slotTexture10 : register(t10);
Texture2D<float4> g_slotTexture11 : register(t11);
Texture2D<float4> g_slotTexture12 : register(t12);
Texture2D<float4> g_slotTexture13 : register(t13);
Texture2D<float4> g_slotTexture14 : register(t14);
Texture2D<float4> g_slotTexture15 : register(t15);

#ifdef UZP_RW_BUFFERS
#define UZP_SLOT_BUFFER RWStructuredBuffer<uint>
#else
#define UZP_SLOT_BUFFER StructuredBuffer<uint>
#endif
[[vk::binding(64, 0)]] UZP_SLOT_BUFFER g_slotBuffer0;
[[vk::binding(65, 0)]] UZP_SLOT_BUFFER g_slotBuffer1;
[[vk::binding(66, 0)]] UZP_SLOT_BUFFER g_slotBuffer2;
[[vk::binding(67, 0)]] UZP_SLOT_BUFFER g_slotBuffer3;
[[vk::binding(68, 0)]] UZP_SLOT_BUFFER g_slotBuffer4;
[[vk::binding(69, 0)]] UZP_SLOT_BUFFER g_slotBuffer5;
[[vk::binding(70, 0)]] UZP_SLOT_BUFFER g_slotBuffer6;
[[vk::binding(71, 0)]] UZP_SLOT_BUFFER g_slotBuffer7;
[[vk::binding(72, 0)]] UZP_SLOT_BUFFER g_slotBuffer8;
[[vk::binding(73, 0)]] UZP_SLOT_BUFFER g_slotBuffer9;
[[vk::binding(74, 0)]] UZP_SLOT_BUFFER g_slotBuffer10;
[[vk::binding(75, 0)]] UZP_SLOT_BUFFER g_slotBuffer11;
[[vk::binding(76, 0)]] UZP_SLOT_BUFFER g_slotBuffer12;
[[vk::binding(77, 0)]] UZP_SLOT_BUFFER g_slotBuffer13;
[[vk::binding(78, 0)]] UZP_SLOT_BUFFER g_slotBuffer14;
[[vk::binding(79, 0)]] UZP_SLOT_BUFFER g_slotBuffer15;

#ifdef UZP_DST_FORMAT
#if UZP_DST_FORMAT == DST_R8
[[vk::image_format("r8")]]
#elif UZP_DST_FORMAT == DST_R16
[[vk::image_format("r16")]]
#elif UZP_DST_FORMAT == DST_R16F
[[vk::image_format("r16f")]]
#elif UZP_DST_FORMAT == DST_R32F
[[vk::image_format("r32f")]]
#elif UZP_DST_FORMAT == DST_RGBA8
[[vk::image_format("rgba8")]]
#elif UZP_DST_FORMAT == DST_RGBA16
[[vk::image_format("rgba16")]]
#elif UZP_DST_FORMAT == DST_RGBA16F
[[vk::image_format("rgba16f")]]
#elif UZP_DST_FORMAT == DST_RGBA32F
[[vk::image_format("rgba32f")]]
#elif UZP_DST_FORMAT == DST_RG8
[[vk::image_format("rg8")]]
#elif UZP_DST_FORMAT == DST_RG16
[[vk::image_format("rg16")]]
#elif UZP_DST_FORMAT == DST_RG16F
[[vk::image_format("rg16f")]]
#elif UZP_DST_FORMAT == DST_RG32F
[[vk::image_format("rg32f")]]
#else
#error "UZP_DST_FORMAT names no destination format"
#endif
RWTexture2D<float4> g_slotOutput : register(u0);
#endif

float4 LoadTexel(uint slot, int2 p) {
    const int3 q = int3(p, 0);
    switch (slot) {
        case 0u: return g_slotTexture0.Load(q);
        case 1u: return g_slotTexture1.Load(q);
        case 2u: return g_slotTexture2.Load(q);
        case 3u: return g_slotTexture3.Load(q);
        case 4u: return g_slotTexture4.Load(q);
        case 5u: return g_slotTexture5.Load(q);
        case 6u: return g_slotTexture6.Load(q);
        case 7u: return g_slotTexture7.Load(q);
        case 8u: return g_slotTexture8.Load(q);
        case 9u: return g_slotTexture9.Load(q);
        case 10u: return g_slotTexture10.Load(q);
        case 11u: return g_slotTexture11.Load(q);
        case 12u: return g_slotTexture12.Load(q);
        case 13u: return g_slotTexture13.Load(q);
        case 14u: return g_slotTexture14.Load(q);
        default: return g_slotTexture15.Load(q);
    }
}

#ifdef UZP_DST_FORMAT
// The slot is u0 (the only storage image a kernel writes).
void StoreTexel(uint slot, int2 p, float4 value) { g_slotOutput[p] = value; }
#endif

uint BufferWord(uint slot, uint index) {
    switch (slot) {
        case 0u: return g_slotBuffer0[index];
        case 1u: return g_slotBuffer1[index];
        case 2u: return g_slotBuffer2[index];
        case 3u: return g_slotBuffer3[index];
        case 4u: return g_slotBuffer4[index];
        case 5u: return g_slotBuffer5[index];
        case 6u: return g_slotBuffer6[index];
        case 7u: return g_slotBuffer7[index];
        case 8u: return g_slotBuffer8[index];
        case 9u: return g_slotBuffer9[index];
        case 10u: return g_slotBuffer10[index];
        case 11u: return g_slotBuffer11[index];
        case 12u: return g_slotBuffer12[index];
        case 13u: return g_slotBuffer13[index];
        case 14u: return g_slotBuffer14[index];
        default: return g_slotBuffer15[index];
    }
}

float BufferFloat(uint slot, uint index) { return asfloat(BufferWord(slot, index)); }

#ifdef UZP_RW_BUFFERS
uint RwWord(uint slot, uint index) { return BufferWord(slot, index); }

#define UZP_RW_CASES(OP) OP(0) OP(1) OP(2) OP(3) OP(4) OP(5) OP(6) OP(7) OP(8) OP(9) OP(10) \
    OP(11) OP(12) OP(13) OP(14)
#define UZP_STORE_CASE(n) case n##u: g_slotBuffer##n[index] = value; return;
#define UZP_ADD_CASE(n) case n##u: InterlockedAdd(g_slotBuffer##n[index], value); return;

void RwStore(uint slot, uint index, uint value) {
    switch (slot) {
        UZP_RW_CASES(UZP_STORE_CASE)
        default: g_slotBuffer15[index] = value; return;
    }
}

void RwAdd(uint slot, uint index, uint value) {
    switch (slot) {
        UZP_RW_CASES(UZP_ADD_CASE)
        default: InterlockedAdd(g_slotBuffer15[index], value); return;
    }
}
#endif
#else
float4 LoadTexel(uint srv, int2 p) {
    Texture2D<float4> image = ResourceDescriptorHeap[srv];
    return image.Load(int3(p, 0));
}

void StoreTexel(uint uav, int2 p, float4 value) {
    RWTexture2D<float4> image = ResourceDescriptorHeap[uav];
    image[p] = value;
}

uint BufferWord(uint srv, uint index) {
    StructuredBuffer<uint> buffer = ResourceDescriptorHeap[srv];
    return buffer[index];
}

float BufferFloat(uint srv, uint index) {
    StructuredBuffer<float> buffer = ResourceDescriptorHeap[srv];
    return buffer[index];
}

// Read-write structured buffers of uints, by UAV index.
uint RwWord(uint uav, uint index) {
    RWStructuredBuffer<uint> buffer = ResourceDescriptorHeap[uav];
    return buffer[index];
}

void RwStore(uint uav, uint index, uint value) {
    RWStructuredBuffer<uint> buffer = ResourceDescriptorHeap[uav];
    buffer[index] = value;
}

void RwAdd(uint uav, uint index, uint value) {
    RWStructuredBuffer<uint> buffer = ResourceDescriptorHeap[uav];
    InterlockedAdd(buffer[index], value);
}
#endif

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
