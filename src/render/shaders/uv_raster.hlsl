// UV-space raster pass (src/render/uv_raster.h, docs/architecture/12-mesh-import.md §5).
// Three entry points, dispatched in this order:
//   ClearMain    per texel: triangle = none, conservative mask = 0
//   CoverMain    per work item (one triangle, a block of at most 8 x 8 texels of its bounding
//                box): texel-centre coverage (atomic minimum of the triangle index) and the
//                conservative mask (separating-axis test of triangle and texel square)
//   ResolveMain  per texel: the winning triangle's attributes interpolated at the texel centre
// Resources are bound bindlessly (SM 6.6 `ResourceDescriptorHeap`) by the indices in the root
// constants. Compiled IEEE-strict (`-Gis`): no contraction, no reassociation.
//
// Fixed slots (SPIR-V with UZP_UV_OUTPUT, Vulkan; src/render/kernel_bindings.h, decision 313):
// the vendored backend binds one storage image per dispatch, so each entry point is compiled once
// per output buffer it writes (UV_* below) and dispatched once per output, in the same order:
// ClearMain for the triangle ids and the mask, CoverMain for each, ResolveMain for the six
// attribute buffers. A buffer "index" is then its slot (bindings 64..72), the resolve reads the
// triangle ids as the sampled image t0, and the root constants are push constants. Every value
// is computed by the same code as on DX12, so the buffers are the same bytes.
//
// Texel space: x = (u - tile column) * width, y = (v - tile row) * height; texel (col, row) is the
// square [col, col + 1] x [height - 1 - row, height - row]; its centre is (col + 1/2,
// height - row - 1/2), i.e. row 0 is v = 1.

#define UV_TRIANGLE 0
#define UV_MASK 1
#define UV_POSITION 2
#define UV_NORMAL 3
#define UV_TANGENT 4
#define UV_BITANGENT 5
#define UV_MATERIAL 6
#define UV_ISLAND 7

#if defined(__spirv__) && defined(UZP_UV_OUTPUT)
#define UZP_FIXED_SLOTS 1
struct Root {
    uint params;
    uint items;
    uint itemCount;
    uint groupsX;
    uint triangleUav;
    uint maskUav;
    uint positionUav;
    uint normalUav;
    uint tangentUav;
    uint bitangentUav;
    uint materialUav;
    uint islandUav;
    uint width;
    uint height;
};
[[vk::push_constant]] Root g_root;
#define g_params g_root.params
#define g_items g_root.items
#define g_itemCount g_root.itemCount
#define g_groupsX g_root.groupsX
#define g_width g_root.width
#define g_height g_root.height

// Raw buffers: params, items, corner ids and at most six corner buffers (uv_raster.h).
[[vk::binding(64, 0)]] ByteAddressBuffer g_slotBuffer0;
[[vk::binding(65, 0)]] ByteAddressBuffer g_slotBuffer1;
[[vk::binding(66, 0)]] ByteAddressBuffer g_slotBuffer2;
[[vk::binding(67, 0)]] ByteAddressBuffer g_slotBuffer3;
[[vk::binding(68, 0)]] ByteAddressBuffer g_slotBuffer4;
[[vk::binding(69, 0)]] ByteAddressBuffer g_slotBuffer5;
[[vk::binding(70, 0)]] ByteAddressBuffer g_slotBuffer6;
[[vk::binding(71, 0)]] ByteAddressBuffer g_slotBuffer7;
[[vk::binding(72, 0)]] ByteAddressBuffer g_slotBuffer8;

Texture2D<uint> g_triangleIds : register(t0);

#if UZP_UV_OUTPUT == UV_MASK
[[vk::image_format("r8")]] RWTexture2D<unorm float> g_output : register(u0);
#elif UZP_UV_OUTPUT >= UV_POSITION && UZP_UV_OUTPUT <= UV_BITANGENT
[[vk::image_format("rgba32f")]] RWTexture2D<float4> g_output : register(u0);
#else
[[vk::image_format("r32ui")]] RWTexture2D<uint> g_output : register(u0);
#endif

uint RawWord(uint slot, uint address) {
    switch (slot) {
        case 0u: return g_slotBuffer0.Load(address);
        case 1u: return g_slotBuffer1.Load(address);
        case 2u: return g_slotBuffer2.Load(address);
        case 3u: return g_slotBuffer3.Load(address);
        case 4u: return g_slotBuffer4.Load(address);
        case 5u: return g_slotBuffer5.Load(address);
        case 6u: return g_slotBuffer6.Load(address);
        case 7u: return g_slotBuffer7.Load(address);
        default: return g_slotBuffer8.Load(address);
    }
}

uint4 RawWords4(uint slot, uint address) {
    return uint4(RawWord(slot, address), RawWord(slot, address + 4), RawWord(slot, address + 8),
                 RawWord(slot, address + 12));
}
#else
cbuffer Root : register(b0) {
    uint g_params;        // raw buffer: layout words (see the P_* offsets)
    uint g_items;         // raw buffer: 4 words per work item
    uint g_itemCount;
    uint g_groupsX;       // groups per row of the CoverMain dispatch
    uint g_triangleUav;   // R32Uint
    uint g_maskUav;       // R8Unorm
    uint g_positionUav;   // RGBA32Float
    uint g_normalUav;
    uint g_tangentUav;
    uint g_bitangentUav;
    uint g_materialUav;   // R32Uint
    uint g_islandUav;     // R32Uint
    uint g_width;
    uint g_height;
};

uint RawWord(uint srv, uint address) {
    ByteAddressBuffer data = ResourceDescriptorHeap[srv];
    return data.Load(address);
}

uint4 RawWords4(uint srv, uint address) {
    ByteAddressBuffer data = ResourceDescriptorHeap[srv];
    return data.Load4(address);
}
#endif

static const uint kNone = 0xFFFFFFFFu;

// Word offsets in the params buffer; an attribute is {buffer SRV index, byte offset, stride}.
static const uint P_TILE_COLUMN = 0;
static const uint P_TILE_ROW = 1;
static const uint P_TRIANGLES = 2;   // raw buffer SRV index of the corner ids
static const uint P_POSITION = 3;
static const uint P_NORMAL = 6;
static const uint P_UV = 9;
static const uint P_TANGENT = 12;
static const uint P_MATERIAL = 15;
static const uint P_ISLAND = 18;

uint Param(uint word) { return RawWord(g_params, word * 4); }

uint LoadWord(uint attribute, uint corner, uint component) {
    const uint address = Param(attribute + 1) + corner * Param(attribute + 2) + component * 4;
    return RawWord(Param(attribute), address);
}

float LoadFloat(uint attribute, uint corner, uint component) {
    return asfloat(LoadWord(attribute, corner, component));
}

float3 LoadFloat3(uint attribute, uint corner) {
    return float3(LoadFloat(attribute, corner, 0), LoadFloat(attribute, corner, 1),
                  LoadFloat(attribute, corner, 2));
}

uint CornerOf(uint triIndex, uint k) { return RawWord(Param(P_TRIANGLES), (triIndex * 3 + k) * 4); }

// The corner's UV in texel space.
float2 TexelUv(uint corner) {
    const float u = LoadFloat(P_UV, corner, 0) - float(Param(P_TILE_COLUMN));
    const float v = LoadFloat(P_UV, corner, 1) - float(Param(P_TILE_ROW));
    return float2(u * float(g_width), v * float(g_height));
}

// Edge function of the directed edge a -> b at p: positive left of the edge. Each product and the
// difference are rounded on their own (IEEE-strict).
float EdgeRaw(float2 a, float2 b, float2 p) {
    const float left = (b.x - a.x) * (p.y - a.y);
    const float right = (b.y - a.y) * (p.x - a.x);
    return left - right;
}

// The edge function evaluated in one canonical vertex order (lexicographic on x, then y), negated
// when a -> b is the other order: two triangles sharing an edge get exactly opposite values.
float Edge(float2 a, float2 b, float2 p) {
    const bool ordered = a.x < b.x || (a.x == b.x && a.y < b.y);
    return ordered ? EdgeRaw(a, b, p) : -EdgeRaw(b, a, p);
}

// cross(a, b) as separate IEEE products and differences (no contraction under `-Gis`). The
// intrinsic is GLSL.std.450 Cross in SPIR-V, an extended instruction NoContraction does not
// reach, whose products the Vulkan driver may fuse; DXIL expands it into these operations
// (decision 352).
float3 Cross(float3 a, float3 b) {
    const float3 left = a.yzx * b.zxy;
    const float3 right = a.zxy * b.yzx;
    return left - right;
}

struct Triangle {
    float2 t[3];
    float orientation;  // +1 counter-clockwise in texel space, -1 clockwise, 0 degenerate
};

Triangle LoadTriangle(uint triIndex, out uint corners[3]) {
    Triangle tri;
    [unroll] for (uint k = 0; k < 3; ++k) {
        corners[k] = CornerOf(triIndex, k);
        tri.t[k] = TexelUv(corners[k]);
    }
    const float area = Edge(tri.t[0], tri.t[1], tri.t[2]);
    tri.orientation = area > 0.0f ? 1.0f : (area < 0.0f ? -1.0f : 0.0f);
    return tri;
}

// Oriented edge functions at p; e[i] belongs to the edge opposite vertex i and is positive inside.
float3 Edges(Triangle tri, float2 p) {
    return float3(Edge(tri.t[1], tri.t[2], p), Edge(tri.t[2], tri.t[0], p),
                  Edge(tri.t[0], tri.t[1], p)) * tri.orientation;
}

// Texel-centre coverage: inside or on the boundary, with a positive sum (non-degenerate).
bool CentreInside(float3 e) {
    return e.x >= 0.0f && e.y >= 0.0f && e.z >= 0.0f && (e.x + e.y) + e.z > 0.0f;
}

// Output writes: on DX12 every buffer through its UAV index; with fixed slots only the buffer
// UZP_UV_OUTPUT names, the others are not written by that dispatch.
void StoreId(uint output, uint uav, uint2 p, uint value) {
#ifdef UZP_FIXED_SLOTS
#if UZP_UV_OUTPUT == UV_TRIANGLE || UZP_UV_OUTPUT == UV_MATERIAL || UZP_UV_OUTPUT == UV_ISLAND
    if (output == UZP_UV_OUTPUT) g_output[p] = value;
#endif
#else
    RWTexture2D<uint> image = ResourceDescriptorHeap[uav];
    image[p] = value;
#endif
}

void StoreMask(uint2 p, float value) {
#ifdef UZP_FIXED_SLOTS
#if UZP_UV_OUTPUT == UV_MASK
    g_output[p] = value;
#endif
#else
    RWTexture2D<unorm float> mask = ResourceDescriptorHeap[g_maskUav];
    mask[p] = value;
#endif
}

void MinTriangle(uint2 p, uint triIndex) {
#ifdef UZP_FIXED_SLOTS
#if UZP_UV_OUTPUT == UV_TRIANGLE
    InterlockedMin(g_output[p], triIndex);
#endif
#else
    RWTexture2D<uint> triangles = ResourceDescriptorHeap[g_triangleUav];
    InterlockedMin(triangles[p], triIndex);
#endif
}

void StoreFloat4(uint output, uint uav, uint2 p, float4 value) {
#ifdef UZP_FIXED_SLOTS
#if UZP_UV_OUTPUT >= UV_POSITION && UZP_UV_OUTPUT <= UV_BITANGENT
    if (output == UZP_UV_OUTPUT) g_output[p] = value;
#endif
#else
    RWTexture2D<float4> image = ResourceDescriptorHeap[uav];
    image[p] = value;
#endif
}

uint TriangleAt(uint2 p) {
#ifdef UZP_FIXED_SLOTS
    return g_triangleIds.Load(int3(p, 0));
#else
    RWTexture2D<uint> triangles = ResourceDescriptorHeap[g_triangleUav];
    return triangles[p];
#endif
}

#ifdef UZP_FIXED_SLOTS
#define TRIANGLE_UAV 0u
#define POSITION_UAV 0u
#define NORMAL_UAV 0u
#define TANGENT_UAV 0u
#define BITANGENT_UAV 0u
#define MATERIAL_UAV 0u
#define ISLAND_UAV 0u
#else
#define TRIANGLE_UAV g_triangleUav
#define POSITION_UAV g_positionUav
#define NORMAL_UAV g_normalUav
#define TANGENT_UAV g_tangentUav
#define BITANGENT_UAV g_bitangentUav
#define MATERIAL_UAV g_materialUav
#define ISLAND_UAV g_islandUav
#endif

[numthreads(8, 8, 1)]
void ClearMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    StoreId(UV_TRIANGLE, TRIANGLE_UAV, id.xy, kNone);
    StoreMask(id.xy, 0.0f);
}

[numthreads(8, 8, 1)]
void CoverMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID) {
    const uint item = group.y * g_groupsX + group.x;
    if (item >= g_itemCount) return;
    const uint4 work = RawWords4(g_items, item * 16);  // triangle, x0, y0, (w | h << 8)
    const uint w = work.w & 0xFFu;
    const uint h = (work.w >> 8) & 0xFFu;
    if (local.x >= w || local.y >= h) return;
    const uint x = work.y + local.x;
    const uint y = work.z + local.y;
    const uint2 texel = uint2(x, g_height - 1 - y);

    uint corners[3];
    const Triangle tri = LoadTriangle(work.x, corners);
    if (tri.orientation == 0.0f) return;

    const float3 centre = Edges(tri, float2(float(x) + 0.5f, float(y) + 0.5f));
    const bool inside = CentreInside(centre);

    // Separating axes: the texel square's axes are settled by the work item (the block lies in the
    // triangle's bounding box with a positive overlap on both axes); along each triangle edge's
    // normal the square must reach strictly inside the edge (max > 0) and strictly before the
    // opposite vertex (min < height of that vertex).
    const float3 c00 = Edges(tri, float2(float(x), float(y)));
    const float3 c10 = Edges(tri, float2(float(x + 1), float(y)));
    const float3 c01 = Edges(tri, float2(float(x), float(y + 1)));
    const float3 c11 = Edges(tri, float2(float(x + 1), float(y + 1)));
    const float3 hi = max(max(c00, c10), max(c01, c11));
    const float3 lo = min(min(c00, c10), min(c01, c11));
    const float3 apex = float3(Edges(tri, tri.t[0]).x, Edges(tri, tri.t[1]).y,
                               Edges(tri, tri.t[2]).z);
    const bool overlaps = all(hi > 0.0f) && all(lo < apex);

    if (inside || overlaps) StoreMask(texel, 1.0f);
    if (inside) MinTriangle(texel, work.x);
}

[numthreads(8, 8, 1)]
void ResolveMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;

    const uint triIndex = TriangleAt(id.xy);
    if (triIndex == kNone) {
        StoreFloat4(UV_POSITION, POSITION_UAV, id.xy, float4(0.0f, 0.0f, 0.0f, 0.0f));
        StoreFloat4(UV_NORMAL, NORMAL_UAV, id.xy, float4(0.0f, 0.0f, 0.0f, 0.0f));
        StoreFloat4(UV_TANGENT, TANGENT_UAV, id.xy, float4(0.0f, 0.0f, 0.0f, 0.0f));
        StoreFloat4(UV_BITANGENT, BITANGENT_UAV, id.xy, float4(0.0f, 0.0f, 0.0f, 0.0f));
        StoreId(UV_MATERIAL, MATERIAL_UAV, id.xy, kNone);
        StoreId(UV_ISLAND, ISLAND_UAV, id.xy, kNone);
        return;
    }

    uint corners[3];
    const Triangle tri = LoadTriangle(triIndex, corners);
    const float y = float(g_height - 1 - id.y);
    const float3 e = Edges(tri, float2(float(id.x) + 0.5f, y + 0.5f));
    const float sum = (e.x + e.y) + e.z;
    const float3 w = e / sum;

    float3 position = float3(0.0f, 0.0f, 0.0f);
    float3 normal = float3(0.0f, 0.0f, 0.0f);
    float3 tangent = float3(0.0f, 0.0f, 0.0f);
    float3 bitangent = float3(0.0f, 0.0f, 0.0f);
    float handedness = 0.0f;
    [unroll] for (uint k = 0; k < 3; ++k) {
        const uint c = corners[k];
        const float3 n = LoadFloat3(P_NORMAL, c);
        const float3 t = LoadFloat3(P_TANGENT, c);
        const float s = LoadFloat(P_TANGENT, c, 3);
        position += LoadFloat3(P_POSITION, c) * w[k];
        normal += n * w[k];
        tangent += t * w[k];
        handedness += s * w[k];
        bitangent += Cross(n, t) * s * w[k];
    }
    StoreFloat4(UV_POSITION, POSITION_UAV, id.xy, float4(position, 1.0f));
    StoreFloat4(UV_NORMAL, NORMAL_UAV, id.xy, float4(normal, 0.0f));
    StoreFloat4(UV_TANGENT, TANGENT_UAV, id.xy, float4(tangent, handedness));
    StoreFloat4(UV_BITANGENT, BITANGENT_UAV, id.xy, float4(bitangent, 0.0f));
    StoreId(UV_MATERIAL, MATERIAL_UAV, id.xy, LoadWord(P_MATERIAL, corners[0], 0));
    StoreId(UV_ISLAND, ISLAND_UAV, id.xy, LoadWord(P_ISLAND, corners[0], 0));
}
