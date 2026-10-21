// Jump-flood dilation (src/render/dilation.h). Seeds are linear texel indices + 1 (0: none) in
// two structured buffers used alternately. Integer arithmetic only.
//
// SeedMain     seed = index + 1 where the coverage mask's channel 0 is non-zero, else 0
// StepMain     one jump-flood step of length g_step: each texel keeps, among its own seed and
//              the seeds of the eight texels at offsets (dx, dy) * step (dx, dy in -1..1,
//              inside the image), the one at the smallest squared distance, ties to the smaller
//              linear index
// ResolveMain  every uncovered texel whose seed lies within the distance limit takes the seed
//              texel's colour; the output already holds a copy of the colour
//
// Resources are named as image_common.hlsli says: heap indices on DX12, slots in the fixed-slot
// SPIR-V of Vulkan (UZP_RW_BUFFERS; ResolveMain with the output's UZP_DST_FORMAT, the others
// with UZP_NO_STORAGE_IMAGE).

#include "image_common.hlsli"

#ifdef UZP_FIXED_SLOTS
// Push constants on Vulkan (image_common.hlsli): each dispatch records its own.
struct Params {
    uint width;
    uint height;
    uint step;
    uint srcSeeds;
    uint dstSeeds;
    uint coverageSrv;
    uint colourSrv;
    uint outputUav;
    uint maxDistanceSq;
};
[[vk::push_constant]] Params g_root;
#define g_width g_root.width
#define g_height g_root.height
#define g_step g_root.step
#define g_srcSeeds g_root.srcSeeds
#define g_dstSeeds g_root.dstSeeds
#define g_coverageSrv g_root.coverageSrv
#define g_colourSrv g_root.colourSrv
#define g_outputUav g_root.outputUav
#define g_maxDistanceSq g_root.maxDistanceSq
#else
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
    uint g_step;
    uint g_srcSeeds;      // UAV index of the seed buffer read
    uint g_dstSeeds;      // UAV index of the seed buffer written
    uint g_coverageSrv;
    uint g_colourSrv;
    uint g_outputUav;
    uint g_maxDistanceSq; // squared distance limit (0xFFFFFFFF: unlimited)
};
#endif

uint DistanceSq(int2 p, uint seed) {
    const int2 s = int2(int(seed % g_width), int(seed / g_width));
    const int2 d = p - s;
    return uint(d.x * d.x) + uint(d.y * d.y);
}

[numthreads(8, 8, 1)]
void SeedMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    const uint index = id.y * g_width + id.x;
    const float4 mask = LoadTexel(g_coverageSrv, int2(id.xy));
    RwStore(g_dstSeeds, index, mask.x != 0.0f ? index + 1u : 0u);
}

[numthreads(8, 8, 1)]
void StepMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    const int2 p = int2(id.xy);
    const uint index = id.y * g_width + id.x;
    uint best = RwWord(g_srcSeeds, index);
    uint bestDistance = best != 0u ? DistanceSq(p, best - 1u) : 0xFFFFFFFFu;
    const int step = int(g_step);
    for (int dy = -1; dy <= 1; ++dy) {
        for (int dx = -1; dx <= 1; ++dx) {
            if (dx == 0 && dy == 0) continue;
            const int2 q = p + int2(dx, dy) * step;
            if (q.x < 0 || q.y < 0 || q.x >= int(g_width) || q.y >= int(g_height)) continue;
            const uint seed = RwWord(g_srcSeeds, uint(q.y) * g_width + uint(q.x));
            if (seed == 0u) continue;
            const uint distance = DistanceSq(p, seed - 1u);
            if (distance < bestDistance || (distance == bestDistance && seed < best)) {
                best = seed;
                bestDistance = distance;
            }
        }
    }
    RwStore(g_dstSeeds, index, best);
}

#ifndef UZP_NO_STORAGE_IMAGE
[numthreads(8, 8, 1)]
void ResolveMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    const int2 p = int2(id.xy);
    const uint index = id.y * g_width + id.x;
    const uint seed = RwWord(g_srcSeeds, index);
    if (seed == 0u || seed == index + 1u) return;
    if (DistanceSq(p, seed - 1u) > g_maxDistanceSq) return;
    const uint s = seed - 1u;
    const int2 source = int2(int(s % g_width), int(s / g_width));
    StoreTexel(g_outputUav, p, LoadTexel(g_colourSrv, source));
}
#endif
