// Bindless sampled-texture gather (phase3.2_vulkan-ray-tracing item 2.4; src/render/bindless.h):
// each thread reads one texel of the texture its lookup names by bindless index, with the
// texture's mip-level size and level count, from the same HLSL on DX12 (DXIL, the SM 6.6
// descriptor heap) and on Vulkan (SPIR-V, the bindless sampled-image array of descriptor set 1,
// UZP-MOD-007). The index varies per thread, so the access is `NonUniformResourceIndex`; this is
// how the path tracer's material textures are named.
//
// Bindings: DX12 reads the lookups (structured SRV) and writes the results (structured UAV) from
// `ResourceDescriptorHeap` at the indices in the root constants, and a texture at its SRV heap
// index. Vulkan (`__spirv__`) reads the lookups at storage-buffer binding 64, writes the results
// at 65 (UZP-MOD-013), with the lookup count in the push constants, and a texture at its slot of
// set 1, binding 0.

struct Lookup {
    uint texture;  // the bindless index (DX12: the SRV heap index; Vulkan: the set-1 slot)
    uint x;
    uint y;
    uint mip;
};

struct Gathered {
    float4 value;  // the texel, read with Load (no filtering, no conversion beyond the format's)
    uint width;    // the mip level's size
    uint height;
    uint levels;   // the texture's mip-level count
    uint pad;
};

#if defined(__spirv__)
struct Params {
    uint count;
    uint lookupsIndex;
    uint resultsIndex;
    uint pad;
};
[[vk::push_constant]] Params g_root;
[[vk::binding(64, 0)]] StructuredBuffer<Lookup> g_lookups;
[[vk::binding(65, 0)]] RWStructuredBuffer<Gathered> g_results;
[[vk::binding(0, 1)]] Texture2D<float4> g_bindlessTextures[];
#define LOOKUP_COUNT g_root.count
#else
cbuffer Params : register(b0) {
    uint g_count;
    uint g_lookupsIndex;
    uint g_resultsIndex;
    uint g_pad;
};
#define LOOKUP_COUNT g_count
#endif

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= LOOKUP_COUNT) return;
#if defined(__spirv__)
    const Lookup lookup = g_lookups[id.x];
    Texture2D<float4> texture = g_bindlessTextures[NonUniformResourceIndex(lookup.texture)];
#else
    StructuredBuffer<Lookup> lookups = ResourceDescriptorHeap[g_lookupsIndex];
    RWStructuredBuffer<Gathered> results = ResourceDescriptorHeap[g_resultsIndex];
    const Lookup lookup = lookups[id.x];
    Texture2D<float4> texture = ResourceDescriptorHeap[NonUniformResourceIndex(lookup.texture)];
#endif
    Gathered gathered;
    texture.GetDimensions(lookup.mip, gathered.width, gathered.height, gathered.levels);
    gathered.value = texture.Load(int3(lookup.x, lookup.y, lookup.mip));
    gathered.pad = 0;
#if defined(__spirv__)
    g_results[id.x] = gathered;
#else
    results[id.x] = gathered;
#endif
}
