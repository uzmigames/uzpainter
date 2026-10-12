// The `painter_viewport` pass (src/preview/viewport.h): one thread per pixel casts its centre ray
// against the triangles binned to its 16 x 16 tile, shades the nearest hit with the split-sum GGX
// specular and Burley diffuse on the SH irradiance (src/preview/environment.h) and writes the
// linear colour rounded to binary16 and its display codes from the display table
// (src/preview/display_transform.h).
//
// Every input is a raw buffer reached through the SM 6.6 descriptor heap; the indices arrive in
// the root constants. Buffer layouts are those written by src/preview/viewport.cpp.

#include "image_common.hlsli"

cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
    uint g_frameSrv;
    uint g_trianglesSrv;
    uint g_tileOffsetsSrv;
    uint g_tileTrianglesSrv;
    uint g_materialsSrv;
    uint g_mapsSrv;
    uint g_lightingSrv;
    uint g_tableSrv;
    uint g_linearUav;
    uint g_displayUav;
};

#define TILE 16u
#define TRIANGLE_WORDS 40u
#define MATERIAL_WORDS 20u
#define NO_MAP 0xFFFFFFFFu
#define PI 3.14159265358979f

float LoadF(ByteAddressBuffer b, uint word) { return asfloat(b.Load(word * 4u)); }
float3 LoadF3(ByteAddressBuffer b, uint word) { return asfloat(b.Load3(word * 4u)); }

// ── Material maps ────────────────────────────────────────────────────────────────────────────

struct MapRef {
    uint offset;
    uint width;
    uint height;
};

MapRef LoadMap(ByteAddressBuffer materials, uint material, uint slot) {
    const uint3 w = materials.Load3((material * MATERIAL_WORDS + slot * 3u) * 4u);
    MapRef m;
    m.offset = w.x;
    m.width = w.y;
    m.height = w.z;
    return m;
}

uint Wrap(int i, uint n) { return uint(((i % int(n)) + int(n)) % int(n)); }

// Bilinear sample with wrapping of `components` values per texel at uv (texel (c, r) centred at
// u = (c + 1/2) / W, v = 1 - (r + 1/2) / H).
float3 SampleMap(MapRef m, uint components, float2 uv) {
    ByteAddressBuffer maps = ResourceDescriptorHeap[g_mapsSrv];
    const float x = uv.x * float(m.width) - 0.5f;
    const float y = (1.0f - uv.y) * float(m.height) - 0.5f;
    const float fx = floor(x);
    const float fy = floor(y);
    const float tx = x - fx;
    const float ty = y - fy;
    const uint x0 = Wrap(int(fx), m.width);
    const uint x1 = Wrap(int(fx) + 1, m.width);
    const uint y0 = Wrap(int(fy), m.height);
    const uint y1 = Wrap(int(fy) + 1, m.height);
    float3 v[4];
    const uint idx[4] = {y0 * m.width + x0, y0 * m.width + x1, y1 * m.width + x0, y1 * m.width + x1};
    [unroll] for (uint k = 0; k < 4u; ++k) {
        const uint base = m.offset + idx[k] * components;
        v[k] = float3(LoadF(maps, base), components > 1u ? LoadF(maps, base + 1u) : 0.0f,
                      components > 2u ? LoadF(maps, base + 2u) : 0.0f);
    }
    const float3 top = v[0] + (v[1] - v[0]) * tx;
    const float3 bottom = v[2] + (v[3] - v[2]) * tx;
    return top + (bottom - top) * ty;
}

// ── Environment ──────────────────────────────────────────────────────────────────────────────

// Bilinear sample of radiance level `level` in direction d (iray.json `environment-mapping`).
float3 SampleLevel(ByteAddressBuffer lighting, uint level, float3 d, float rotationTurns) {
    const uint3 desc = lighting.Load3((27u + level * 3u) * 4u);
    const uint w = desc.y;
    const uint h = desc.z;
    float u = atan2(-d.x, d.z) / (2.0f * PI) + 0.25f + rotationTurns;
    u -= floor(u);
    const float v = acos(clamp(d.y, -1.0f, 1.0f)) / PI;
    const float x = u * float(w) - 0.5f;
    const float y = clamp(v * float(h) - 0.5f, 0.0f, float(h - 1u));
    const float fx = floor(x);
    const float fy = floor(y);
    const float tx = x - fx;
    const float ty = y - fy;
    const uint x0 = Wrap(int(fx), w);
    const uint x1 = Wrap(int(fx) + 1, w);
    const uint y0 = uint(fy);
    const uint y1 = min(y0 + 1u, h - 1u);
    const float3 a = LoadF3(lighting, desc.x + (y0 * w + x0) * 3u);
    const float3 b = LoadF3(lighting, desc.x + (y0 * w + x1) * 3u);
    const float3 c = LoadF3(lighting, desc.x + (y1 * w + x0) * 3u);
    const float3 e = LoadF3(lighting, desc.x + (y1 * w + x1) * 3u);
    const float3 top = a + (b - a) * tx;
    const float3 bottom = c + (e - c) * tx;
    return top + (bottom - top) * ty;
}

float3 Prefiltered(ByteAddressBuffer lighting, uint levels, float3 d, float roughness, float rotationTurns) {
    const float l = roughness * float(levels - 1u);
    const uint l0 = uint(floor(l));
    const uint l1 = min(l0 + 1u, levels - 1u);
    const float t = l - float(l0);
    const float3 a = SampleLevel(lighting, l0, d, rotationTurns);
    const float3 b = SampleLevel(lighting, l1, d, rotationTurns);
    return a + (b - a) * t;
}

// The SH irradiance at the unit normal n, in the frame of the environment (rotated like it).
float3 Irradiance(ByteAddressBuffer lighting, float3 n) {
    const float basis[9] = {0.282095f,         0.488603f * n.y,         0.488603f * n.z,
                            0.488603f * n.x,   1.092548f * n.x * n.y,   1.092548f * n.y * n.z,
                            0.315392f * (3.0f * n.z * n.z - 1.0f), 1.092548f * n.x * n.z,
                            0.546274f * (n.x * n.x - n.y * n.y)};
    float3 sum = float3(0.0f, 0.0f, 0.0f);
    [unroll] for (uint i = 0; i < 9u; ++i) sum += LoadF3(lighting, i * 3u) * basis[i];
    return sum;
}

// The direction d rotated by -rotation about +Y, so that a lookup at rotation 0 of the result
// equals a lookup of d at `rotationTurns` (the SH coefficients are projected at rotation 0).
float3 Unrotate(float3 d, float rotationTurns) {
    const float a = 2.0f * PI * rotationTurns;
    const float c = cos(a);
    const float s = sin(a);
    // u grows with atan2(-x, z): adding `rotationTurns` to u is a rotation of d by +a in that angle.
    return float3(d.x * c - d.z * s, d.y, d.x * s + d.z * c);
}

float3 BrdfTable(ByteAddressBuffer lighting, uint size, float nv, float roughness) {
    const uint offset = lighting.Load(45u * 4u);
    const float x = clamp(nv * float(size) - 0.5f, 0.0f, float(size - 1u));
    const float y = clamp(roughness, 0.0f, 1.0f) * float(size - 1u);
    const uint x0 = uint(floor(x));
    const uint y0 = uint(floor(y));
    const uint x1 = min(x0 + 1u, size - 1u);
    const uint y1 = min(y0 + 1u, size - 1u);
    const float tx = x - float(x0);
    const float ty = y - float(y0);
    const float3 a = LoadF3(lighting, offset + (y0 * size + x0) * 3u);
    const float3 b = LoadF3(lighting, offset + (y0 * size + x1) * 3u);
    const float3 c = LoadF3(lighting, offset + (y1 * size + x0) * 3u);
    const float3 d = LoadF3(lighting, offset + (y1 * size + x1) * 3u);
    const float3 top = a + (b - a) * tx;
    const float3 bottom = c + (d - c) * tx;
    return top + (bottom - top) * ty;
}

// ── Pass ─────────────────────────────────────────────────────────────────────────────────────

uint DisplayCodeOf(ByteAddressBuffer table, float value) {
    const uint bits = f32tof16(RoundToHalf(value));
    const uint word = table.Load((bits >> 1u) * 4u);
    return (bits & 1u) != 0u ? (word >> 16u) : (word & 0xFFFFu);
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    ByteAddressBuffer frame = ResourceDescriptorHeap[g_frameSrv];
    ByteAddressBuffer triangles = ResourceDescriptorHeap[g_trianglesSrv];
    ByteAddressBuffer tileOffsets = ResourceDescriptorHeap[g_tileOffsetsSrv];
    ByteAddressBuffer tileTriangles = ResourceDescriptorHeap[g_tileTrianglesSrv];
    ByteAddressBuffer materials = ResourceDescriptorHeap[g_materialsSrv];
    ByteAddressBuffer lighting = ResourceDescriptorHeap[g_lightingSrv];
    ByteAddressBuffer table = ResourceDescriptorHeap[g_tableSrv];

    const float3 eye = LoadF3(frame, 0u);
    const float3 right = LoadF3(frame, 3u);
    const float3 up = LoadF3(frame, 6u);
    const float3 forward = LoadF3(frame, 9u);
    const float tanHalf = LoadF(frame, 12u);
    const float aspect = LoadF(frame, 13u);
    const float3 background = LoadF3(frame, 14u);
    const float rotationTurns = LoadF(frame, 17u);
    const float intensity = LoadF(frame, 18u);
    const uint materialCount = frame.Load(20u * 4u);
    const uint levels = frame.Load(21u * 4u);
    const uint brdfSize = frame.Load(22u * 4u);
    const uint tilesX = frame.Load(23u * 4u);

    // The ray through the pixel centre.
    const float sx = ((float(id.x) + 0.5f) / float(g_width) * 2.0f - 1.0f) * tanHalf * aspect;
    const float sy = (1.0f - (float(id.y) + 0.5f) / float(g_height) * 2.0f) * tanHalf;
    const float3 dir = normalize(forward + right * sx + up * sy);

    // Nearest hit among the tile's triangles (Moller-Trumbore), ascending index, strict nearer.
    const uint tile = (id.y / TILE) * tilesX + id.x / TILE;
    const uint first = tileOffsets.Load(tile * 4u);
    const uint last = tileOffsets.Load((tile + 1u) * 4u);
    float bestT = 3.402823e38f;
    uint best = NO_MAP;
    float bestU = 0.0f;
    float bestV = 0.0f;
    for (uint k = first; k < last; ++k) {
        const uint t = tileTriangles.Load(k * 4u);
        const uint base = t * TRIANGLE_WORDS;
        const float3 p0 = LoadF3(triangles, base);
        const float3 p1 = LoadF3(triangles, base + 12u);
        const float3 p2 = LoadF3(triangles, base + 24u);
        const float3 e1 = p1 - p0;
        const float3 e2 = p2 - p0;
        const float3 pv = cross(dir, e2);
        const float det = dot(e1, pv);
        if (det == 0.0f) continue;
        const float inv = 1.0f / det;
        const float3 tv = eye - p0;
        const float u = dot(tv, pv) * inv;
        if (u < 0.0f || u > 1.0f) continue;
        const float3 qv = cross(tv, e1);
        const float v = dot(dir, qv) * inv;
        if (v < 0.0f || u + v > 1.0f) continue;
        const float hit = dot(e2, qv) * inv;
        if (hit <= 0.0f || hit >= bestT) continue;
        bestT = hit;
        best = t;
        bestU = u;
        bestV = v;
    }

    float3 colour = background;
    if (best != NO_MAP) {
        const uint base = best * TRIANGLE_WORDS;
        const float w0 = 1.0f - bestU - bestV;
        const float3 p0 = LoadF3(triangles, base);
        const float3 p1 = LoadF3(triangles, base + 12u);
        const float3 p2 = LoadF3(triangles, base + 24u);
        float3 ng = normalize(cross(p1 - p0, p2 - p0));
        float3 n = LoadF3(triangles, base + 3u) * w0 + LoadF3(triangles, base + 15u) * bestU +
                   LoadF3(triangles, base + 27u) * bestV;
        const float2 uv = asfloat(triangles.Load2((base + 6u) * 4u)) * w0 +
                          asfloat(triangles.Load2((base + 18u) * 4u)) * bestU +
                          asfloat(triangles.Load2((base + 30u) * 4u)) * bestV;
        const float4 t0 = asfloat(triangles.Load4((base + 8u) * 4u));
        const float4 t1 = asfloat(triangles.Load4((base + 20u) * 4u));
        const float4 t2 = asfloat(triangles.Load4((base + 32u) * 4u));
        const float3 tangent = t0.xyz * w0 + t1.xyz * bestU + t2.xyz * bestV;
        const float handedness = (t0.w * w0 + t1.w * bestU + t2.w * bestV) < 0.0f ? -1.0f : 1.0f;
        const float3 view = -dir;
        if (dot(ng, view) < 0.0f) {
            ng = -ng;
            n = -n;
        }
        if (dot(n, n) == 0.0f) n = ng;
        const uint material = triangles.Load((base + 36u) * 4u);

        float3 baseColour = float3(0.8f, 0.8f, 0.8f);
        float metalness = 0.0f;
        float roughness = 0.3f;
        float3 tn = float3(0.0f, 0.0f, 1.0f);
        if (material < materialCount) {
            const uint mw = material * MATERIAL_WORDS;
            baseColour = LoadF3(materials, mw + 12u);
            metalness = LoadF(materials, mw + 15u);
            roughness = LoadF(materials, mw + 16u);
            const MapRef baseMap = LoadMap(materials, material, 0u);
            const MapRef metalMap = LoadMap(materials, material, 1u);
            const MapRef roughMap = LoadMap(materials, material, 2u);
            const MapRef normalMap = LoadMap(materials, material, 3u);
            if (baseMap.offset != NO_MAP) baseColour = SampleMap(baseMap, 3u, uv);
            if (metalMap.offset != NO_MAP) metalness = SampleMap(metalMap, 1u, uv).x;
            if (roughMap.offset != NO_MAP) roughness = SampleMap(roughMap, 1u, uv).x;
            if (normalMap.offset != NO_MAP) tn = SampleMap(normalMap, 3u, uv) * 2.0f - 1.0f;
        }
        metalness = saturate(metalness);
        roughness = saturate(roughness);

        // MikkTSpace: the perturbed normal in the interpolated, unnormalised corner frame.
        const float3 bitangent = handedness * cross(n, tangent);
        float3 shading = tn.x * tangent + tn.y * bitangent + tn.z * n;
        shading = dot(shading, shading) > 0.0f ? normalize(shading) : normalize(n);
        if (dot(shading, view) <= 0.0f) shading = normalize(n);

        const float nv = max(dot(shading, view), 1e-4f);
        const float3 reflected = shading * (2.0f * nv) - view;
        const float3 f0 = float3(0.04f, 0.04f, 0.04f) + (baseColour - float3(0.04f, 0.04f, 0.04f)) * metalness;
        const float3 albedo = BrdfTable(lighting, brdfSize, nv, roughness);
        const float3 specular =
            Prefiltered(lighting, levels, normalize(reflected), roughness, rotationTurns) * (f0 * albedo.x + albedo.y);
        const float dielectricAlbedo = 0.04f * albedo.x + albedo.y;
        const float3 diffuse = baseColour * (1.0f - metalness) * Irradiance(lighting, Unrotate(shading, rotationTurns)) *
                               (albedo.z * (1.0f - dielectricAlbedo) / PI);
        colour = (specular + diffuse) * intensity;
    }

    const float4 linearColour = float4(RoundToHalf(colour.x), RoundToHalf(colour.y), RoundToHalf(colour.z), 1.0f);
    RWTexture2D<float4> linearOut = ResourceDescriptorHeap[g_linearUav];
    linearOut[id.xy] = linearColour;
    const uint4 codes = uint4(DisplayCodeOf(table, linearColour.x), DisplayCodeOf(table, linearColour.y),
                              DisplayCodeOf(table, linearColour.z), 65535u);
    RWTexture2D<float4> displayOut = ResourceDescriptorHeap[g_displayUav];
    displayOut[id.xy] = float4(codes) / 65535.0f;
}
