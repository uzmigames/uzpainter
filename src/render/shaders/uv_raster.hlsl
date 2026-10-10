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
// Texel space: x = (u - tile column) * width, y = (v - tile row) * height; texel (col, row) is the
// square [col, col + 1] x [height - 1 - row, height - row]; its centre is (col + 1/2,
// height - row - 1/2), i.e. row 0 is v = 1.

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

uint Param(uint word) {
    ByteAddressBuffer params = ResourceDescriptorHeap[g_params];
    return params.Load(word * 4);
}

uint LoadWord(uint attribute, uint corner, uint component) {
    ByteAddressBuffer data = ResourceDescriptorHeap[Param(attribute)];
    const uint address = Param(attribute + 1) + corner * Param(attribute + 2) + component * 4;
    return data.Load(address);
}

float LoadFloat(uint attribute, uint corner, uint component) {
    return asfloat(LoadWord(attribute, corner, component));
}

float3 LoadFloat3(uint attribute, uint corner) {
    return float3(LoadFloat(attribute, corner, 0), LoadFloat(attribute, corner, 1),
                  LoadFloat(attribute, corner, 2));
}

uint CornerOf(uint triIndex, uint k) {
    ByteAddressBuffer ids = ResourceDescriptorHeap[Param(P_TRIANGLES)];
    return ids.Load((triIndex * 3 + k) * 4);
}

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

[numthreads(8, 8, 1)]
void ClearMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    RWTexture2D<uint> triangles = ResourceDescriptorHeap[g_triangleUav];
    RWTexture2D<unorm float> mask = ResourceDescriptorHeap[g_maskUav];
    triangles[id.xy] = kNone;
    mask[id.xy] = 0.0f;
}

[numthreads(8, 8, 1)]
void CoverMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID) {
    const uint item = group.y * g_groupsX + group.x;
    if (item >= g_itemCount) return;
    ByteAddressBuffer items = ResourceDescriptorHeap[g_items];
    const uint4 work = items.Load4(item * 16);  // triangle, x0, y0, (w | h << 8)
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

    if (inside || overlaps) {
        RWTexture2D<unorm float> mask = ResourceDescriptorHeap[g_maskUav];
        mask[texel] = 1.0f;
    }
    if (inside) {
        RWTexture2D<uint> triangles = ResourceDescriptorHeap[g_triangleUav];
        InterlockedMin(triangles[texel], work.x);
    }
}

[numthreads(8, 8, 1)]
void ResolveMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    RWTexture2D<uint> triangles = ResourceDescriptorHeap[g_triangleUav];
    RWTexture2D<float4> positions = ResourceDescriptorHeap[g_positionUav];
    RWTexture2D<float4> normals = ResourceDescriptorHeap[g_normalUav];
    RWTexture2D<float4> tangents = ResourceDescriptorHeap[g_tangentUav];
    RWTexture2D<float4> bitangents = ResourceDescriptorHeap[g_bitangentUav];
    RWTexture2D<uint> materials = ResourceDescriptorHeap[g_materialUav];
    RWTexture2D<uint> islands = ResourceDescriptorHeap[g_islandUav];

    const uint triIndex = triangles[id.xy];
    if (triIndex == kNone) {
        positions[id.xy] = float4(0.0f, 0.0f, 0.0f, 0.0f);
        normals[id.xy] = float4(0.0f, 0.0f, 0.0f, 0.0f);
        tangents[id.xy] = float4(0.0f, 0.0f, 0.0f, 0.0f);
        bitangents[id.xy] = float4(0.0f, 0.0f, 0.0f, 0.0f);
        materials[id.xy] = kNone;
        islands[id.xy] = kNone;
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
        bitangent += cross(n, t) * s * w[k];
    }
    positions[id.xy] = float4(position, 1.0f);
    normals[id.xy] = float4(normal, 0.0f);
    tangents[id.xy] = float4(tangent, handedness);
    bitangents[id.xy] = float4(bitangent, 0.0f);
    materials[id.xy] = LoadWord(P_MATERIAL, corners[0], 0);
    islands[id.xy] = LoadWord(P_ISLAND, corners[0], 0);
}
