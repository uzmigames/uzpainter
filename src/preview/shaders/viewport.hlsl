// The `painter_viewport` pass (src/preview/viewport.h): one thread per pixel casts its centre ray
// against the triangles binned to its 16 x 16 tile, shades the nearest hit with the split-sum GGX
// specular and Burley diffuse on the SH irradiance (src/preview/environment.h), each multiplied by
// its ray-traced visibility ratio (decision 251) weighted by the AO map's visibility (decision 257),
// and writes the linear colour rounded to binary16 and its display codes from the display table
// (src/preview/display_transform.h).
//
// Every input is a raw buffer reached through the SM 6.6 descriptor heap; the indices arrive in
// the root constants. Buffer layouts are those written by src/preview/viewport.cpp and
// src/preview/visibility.h. `BVH_STACK` (the traversal stack) is defined by viewport.cpp as the
// build's depth cap.
//
// Entry points: `main`, the pass; `probe` (tests), the visibility of given rays.

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
    uint g_bvhNodesSrv;
    uint g_occludersSrv;
};

#define TILE 16u
#define TRIANGLE_WORDS 40u
// Five map references of three words (base colour, metalness, roughness, normal, occlusion), then
// the base colour, the metalness and the roughness.
#define MATERIAL_WORDS 20u
#define NO_MAP 0xFFFFFFFFu
#define PI 3.14159265358979f
#define NODE_BYTES 32u
#define OCCLUDER_BYTES 48u
#define OUTPUT_DIFFUSE_VISIBILITY 1u
#define OUTPUT_SPECULAR_VISIBILITY 2u

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

// ── Shading normal ───────────────────────────────────────────────────────────────────────────

// The shading normal s, faded toward the interpolated normal n as the view's mirror reflection
// about s sinks toward the geometric tangent plane (decision 256). The shading and geometric
// normals define different hemispheres, a mismatch to handle with care (Physically Based Rendering,
// 4th ed., 9.1.5): the mirror reflection about s can fall below the geometric surface, where the
// pass reflected the dark lower environment, and the former hard switch to n wherever s faced away
// drew a thin dark contour. With e = dot(reflect(-view, s), ng), ng facing the viewer: e >= FADE_BAND
// keeps s, e <= 0 or s facing away gives n, and in between n and s blend by smoothstep(0, FADE_BAND, e).
#define FADE_BAND 0.2f
float3 FadeShadingNormal(float3 s, float3 n, float3 ng, float3 view) {
    const float sv = dot(s, view);
    const float e = dot(s * (2.0f * sv) - view, ng);
    if (sv > 0.0f && e >= FADE_BAND) return s;
    const float3 interpolated = normalize(n);
    if (sv <= 0.0f || e <= 0.0f) return interpolated;
    const float3 blend = lerp(interpolated, s, smoothstep(0.0f, FADE_BAND, e));
    return dot(blend, blend) > 0.0f ? normalize(blend) : interpolated;
}

// ── Visibility (decision 251) ────────────────────────────────────────────────────────────────

// A visibility ray: its origin, the watertight shear of its direction (Woop, Benthin and Wald
// 2013, as for camera rays), the reciprocal direction of the box tests and which direction
// components are 0.
struct ShadowRay {
    float3 origin;
    uint kx;
    uint ky;
    uint kz;
    float shearX;
    float shearY;
    float shearZ;
    float3 invDir;
    uint3 parallel;
};

ShadowRay MakeShadowRay(float3 origin, float3 dir) {
    ShadowRay r;
    r.origin = origin;
    const float3 a = abs(dir);
    r.kz = a.x > a.y ? (a.x > a.z ? 0u : 2u) : (a.y > a.z ? 1u : 2u);
    r.kx = r.kz == 2u ? 0u : r.kz + 1u;
    r.ky = r.kx == 2u ? 0u : r.kx + 1u;
    r.shearX = dir[r.kx] / dir[r.kz];
    r.shearY = dir[r.ky] / dir[r.kz];
    r.shearZ = 1.0f / dir[r.kz];
    // A zero component has no slab distances (its reciprocal is unused): the box test checks
    // the origin against that slab instead.
    r.parallel = uint3(dir.x == 0.0f ? 1u : 0u, dir.y == 0.0f ? 1u : 0u, dir.z == 0.0f ? 1u : 0u);
    r.invDir = float3(r.parallel.x != 0u ? 0.0f : 1.0f / dir.x, r.parallel.y != 0u ? 0.0f : 1.0f / dir.y,
                      r.parallel.z != 0u ? 0.0f : 1.0f / dir.z);
    return r;
}

// The slab test of a node's box. The box is the exact float bound of its triangles; the far
// distance is grown by 1 + 2 gamma(3) (Ize 2013) to cover the rounding of the slab distances. A
// ray parallel to a slab lies in it for every distance when its origin does, boundary included
// (a ray along a box face meets the triangles on that face's edges), and never otherwise.
bool HitsBox(ShadowRay r, float3 lo, float3 hi) {
    float tNear = 0.0f;
    float tFar = 3.402823e38f;
    [unroll] for (uint a = 0u; a < 3u; ++a) {
        if (r.parallel[a] != 0u) {
            if (r.origin[a] < lo[a] || r.origin[a] > hi[a]) return false;
            continue;
        }
        const float t0 = (lo[a] - r.origin[a]) * r.invDir[a];
        const float t1 = (hi[a] - r.origin[a]) * r.invDir[a];
        tNear = max(tNear, min(t0, t1));
        tFar = min(tFar, max(t0, t1));
    }
    return tNear <= tFar * 1.0000004f;
}

// Whether the triangle (p0, p1, p2) blocks the ray: decision 178's watertight edge functions on
// the sheared corners (both faces count, a triangle seen edge-on covers nothing), and a hit
// distance T / det in front of the origin (Woop et al.'s scaled distance, its sign only).
bool Blocks(ShadowRay r, float3 p0, float3 p1, float3 p2) {
    const float3 r0 = p0 - r.origin;
    const float3 r1 = p1 - r.origin;
    const float3 r2 = p2 - r.origin;
    precise const float x0 = r0[r.kx] - r.shearX * r0[r.kz];
    precise const float y0 = r0[r.ky] - r.shearY * r0[r.kz];
    precise const float x1 = r1[r.kx] - r.shearX * r1[r.kz];
    precise const float y1 = r1[r.ky] - r.shearY * r1[r.kz];
    precise const float x2 = r2[r.kx] - r.shearX * r2[r.kz];
    precise const float y2 = r2[r.ky] - r.shearY * r2[r.kz];
    precise const float f0 = x1 * y2 - y1 * x2;
    precise const float f1 = x2 * y0 - y2 * x0;
    precise const float f2 = x0 * y1 - y0 * x1;
    if ((f0 < 0.0f || f1 < 0.0f || f2 < 0.0f) && (f0 > 0.0f || f1 > 0.0f || f2 > 0.0f)) return false;
    if (f0 == 0.0f && f1 == 0.0f && f2 == 0.0f) return false;
    precise const float z0 = r.shearZ * r0[r.kz];
    precise const float z1 = r.shearZ * r1[r.kz];
    precise const float z2 = r.shearZ * r2[r.kz];
    precise const float det = f0 + f1 + f2;
    precise const float t = f0 * z0 + f1 * z1 + f2 * z2;
    return det > 0.0f ? t > 0.0f : t < 0.0f;
}

// Any hit along the ray, through the BVH (src/preview/visibility.h): the nearer-first order does
// not matter for an any-hit query, so the left child is visited first and the right one pushed.
// A node at depth d has at most d pending siblings, and the build makes every node at depth
// BVH_STACK a leaf, so the stack cannot overflow. The triangle `self` (the ray's own) is skipped.
bool OccludedBvh(ByteAddressBuffer nodes, ByteAddressBuffer occluders, uint nodeCount, ShadowRay r, uint self) {
    if (nodeCount == 0u) return false;
    uint stack[BVH_STACK];
    uint depth = 0u;
    uint node = 0u;
    for (;;) {
        const uint4 a = nodes.Load4(node * NODE_BYTES);
        const uint4 b = nodes.Load4(node * NODE_BYTES + 16u);
        if (b.w != 0u) {
            for (uint k = 0u; k < b.w; ++k) {
                const uint base = (a.w + k) * OCCLUDER_BYTES;
                const uint4 q0 = occluders.Load4(base);
                if (q0.w == self) continue;
                if (Blocks(r, asfloat(q0.xyz), asfloat(occluders.Load3(base + 16u)), asfloat(occluders.Load3(base + 32u)))) {
                    return true;
                }
            }
        } else {
            const uint left = a.w;
            const bool hitLeft = HitsBox(r, asfloat(nodes.Load3(left * NODE_BYTES)), asfloat(nodes.Load3(left * NODE_BYTES + 16u)));
            const uint right = left + 1u;
            const bool hitRight = HitsBox(r, asfloat(nodes.Load3(right * NODE_BYTES)), asfloat(nodes.Load3(right * NODE_BYTES + 16u)));
            if (hitLeft) {
                if (hitRight) stack[depth++] = right;
                node = left;
                continue;
            }
            if (hitRight) {
                node = right;
                continue;
            }
        }
        if (depth == 0u) return false;
        node = stack[--depth];
    }
    return false;
}

// Any hit by testing every triangle in order (the reference of the traversal; tests only).
bool OccludedLinear(ByteAddressBuffer occluders, uint count, ShadowRay r, uint self) {
    for (uint j = 0u; j < count; ++j) {
        const uint base = j * OCCLUDER_BYTES;
        const uint4 q0 = occluders.Load4(base);
        if (q0.w == self) continue;
        if (Blocks(r, asfloat(q0.xyz), asfloat(occluders.Load3(base + 16u)), asfloat(occluders.Load3(base + 32u)))) {
            return true;
        }
    }
    return false;
}

// The ray origin moved off the surface at p along its geometric normal n (Wachter and Binder,
// "A Fast and Robust Method for Avoiding Self-Intersection", Ray Tracing Gems 2019, ch. 6): by
// 256 n units in the last place of each coordinate's integer representation, or by n / 65536
// for a coordinate within 1/32 of zero.
float3 OffsetRayOrigin(float3 p, float3 n) {
    const int3 offset = int3(256.0f * n);
    const float3 moved = float3(asfloat(asint(p.x) + (p.x < 0.0f ? -offset.x : offset.x)),
                                asfloat(asint(p.y) + (p.y < 0.0f ? -offset.y : offset.y)),
                                asfloat(asint(p.z) + (p.z < 0.0f ? -offset.z : offset.z)));
    return float3(abs(p.x) < 1.0f / 32.0f ? p.x + (1.0f / 65536.0f) * n.x : moved.x,
                  abs(p.y) < 1.0f / 32.0f ? p.y + (1.0f / 65536.0f) * n.y : moved.y,
                  abs(p.z) < 1.0f / 32.0f ? p.z + (1.0f / 65536.0f) * n.z : moved.z);
}

// ── Sampling ─────────────────────────────────────────────────────────────────────────────────

// A 32-bit integer hash (Wellons' lowbias32).
uint Hash(uint x) {
    x ^= x >> 16u;
    x *= 0x7feb352du;
    x ^= x >> 15u;
    x *= 0x846ca68bu;
    x ^= x >> 16u;
    return x;
}

// The scramble of `stream` at pixel p: a hash of the pixel coordinates only.
uint PixelHash(uint2 p, uint stream) { return Hash(p.x ^ Hash(p.y ^ Hash(stream))); }

// Point i of the n-point Hammersley set, its first coordinate shifted by `shift` modulo 1
// (Cranley and Patterson 1976) and its radical inverse scrambled by XOR with `scramble` (random
// digit scrambling); both coordinates lie in [0, 1).
float2 Sequence(uint i, uint n, uint shift, uint scramble) {
    const float a = (float(i) + 0.5f) / float(n) + float(shift >> 8u) * (1.0f / 16777216.0f);
    return float2(a - floor(a), float((reversebits(i) ^ scramble) >> 8u) * (1.0f / 16777216.0f));
}

// An orthonormal basis (t, b, n) of the unit vector n (Duff et al. 2017).
void Basis(float3 n, out float3 t, out float3 b) {
    const float s = n.z >= 0.0f ? 1.0f : -1.0f;
    const float a = -1.0f / (s + n.z);
    const float c = n.x * n.y * a;
    t = float3(1.0f + s * n.x * n.x * a, s * c, -s * n.x);
    b = float3(c, s + n.y * n.y * a, -n.y);
}

// The largest i in [0, size - 2] with cdf[i] <= x, for cdf[0] = 0 <= x < cdf[size - 1] = 1: the
// interval it opens has cdf[i] <= x < cdf[i + 1], so it has a positive width.
uint FindInterval(ByteAddressBuffer lighting, uint offset, uint size, float x) {
    uint lo = 0u;
    uint hi = size - 1u;
    while (hi - lo > 1u) {
        const uint mid = (lo + hi) / 2u;
        if (LoadF(lighting, offset + mid) <= x) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return lo;
}

// The environment-importance distribution (src/preview/environment.h `ImportanceDistribution`):
// header words 46-48 hold its offset, width and height; the marginal CDF (height + 1 values),
// then the conditional CDFs (height rows of width + 1).

// A direction drawn from the distribution (PBRT 4th ed. PiecewiseConstant2D, continuous within
// a texel) and its density per unit solid angle (0 at a pole).
float3 SampleEnvironment(ByteAddressBuffer lighting, float2 xi, float rotationTurns, out float pdf) {
    const uint offset = lighting.Load(46u * 4u);
    const uint w = lighting.Load(47u * 4u);
    const uint h = lighting.Load(48u * 4u);
    const uint row = FindInterval(lighting, offset, h + 1u, xi.y);
    const float m0 = LoadF(lighting, offset + row);
    const float m1 = LoadF(lighting, offset + row + 1u);
    const uint conditional = offset + h + 1u + row * (w + 1u);
    const uint column = FindInterval(lighting, conditional, w + 1u, xi.x);
    const float c0 = LoadF(lighting, conditional + column);
    const float c1 = LoadF(lighting, conditional + column + 1u);
    const float u = (float(column) + (xi.x - c0) / (c1 - c0)) / float(w);
    const float v = (float(row) + (xi.y - m0) / (m1 - m0)) / float(h);
    const float theta = PI * v;
    const float sinTheta = sin(theta);
    pdf = sinTheta > 0.0f ? (m1 - m0) * float(h) * (c1 - c0) * float(w) / (2.0f * PI * PI * sinTheta) : 0.0f;
    // The inverse of the environment mapping (SampleLevel) at this rotation.
    const float phi = 2.0f * PI * (u - rotationTurns - 0.25f);
    return float3(-sin(phi) * sinTheta, cos(theta), cos(phi) * sinTheta);
}

// The distribution's density per unit solid angle in direction d (unit).
float EnvironmentPdf(ByteAddressBuffer lighting, float3 d, float rotationTurns) {
    const uint offset = lighting.Load(46u * 4u);
    const uint w = lighting.Load(47u * 4u);
    const uint h = lighting.Load(48u * 4u);
    float u = atan2(-d.x, d.z) / (2.0f * PI) + 0.25f + rotationTurns;
    u -= floor(u);
    const float v = acos(clamp(d.y, -1.0f, 1.0f)) / PI;
    const uint column = min(uint(u * float(w)), w - 1u);
    const uint row = min(uint(v * float(h)), h - 1u);
    const float sinTheta = sqrt(max(0.0f, 1.0f - d.y * d.y));
    if (!(sinTheta > 0.0f)) return 0.0f;
    const uint conditional = offset + h + 1u + row * (w + 1u);
    const float marginal = LoadF(lighting, offset + row + 1u) - LoadF(lighting, offset + row);
    const float within = LoadF(lighting, conditional + column + 1u) - LoadF(lighting, conditional + column);
    return marginal * float(h) * within * float(w) / (2.0f * PI * PI * sinTheta);
}

// Smith's Lambda of the GGX distribution at cos(theta) = c (as the albedo table's).
float SmithLambda(float c, float alpha) {
    const float c2 = c * c;
    const float tan2 = (1.0f - c2) / c2;
    return (-1.0f + sqrt(1.0f + alpha * alpha * tan2)) / 2.0f;
}

// A GGX visible normal for the view ve (z up) and alpha (Heitz 2018, "Sampling the GGX
// Distribution of Visible Normals").
float3 SampleVisibleNormal(float3 ve, float alpha, float2 xi) {
    const float3 vh = normalize(float3(alpha * ve.x, alpha * ve.y, ve.z));
    const float lensq = vh.x * vh.x + vh.y * vh.y;
    const float3 t1 = lensq > 0.0f ? float3(-vh.y, vh.x, 0.0f) / sqrt(lensq) : float3(1.0f, 0.0f, 0.0f);
    const float3 t2 = cross(vh, t1);
    const float r = sqrt(xi.x);
    const float phi = 2.0f * PI * xi.y;
    const float a = r * cos(phi);
    const float s = 0.5f * (1.0f + vh.z);
    const float b = (1.0f - s) * sqrt(max(0.0f, 1.0f - a * a)) + s * r * sin(phi);
    const float3 nh = a * t1 + b * t2 + sqrt(max(0.0f, 1.0f - a * a - b * b)) * vh;
    return normalize(float3(alpha * nh.x, alpha * nh.y, max(1e-6f, nh.z)));
}

// seen / total per channel: 1 where no ray was blocked (the numerator is then the denominator),
// and where the denominator is zero or not finite; otherwise clamped to [0, 1].
float3 Ratio(float3 seen, float3 total, bool blocked) {
    if (!blocked) return float3(1.0f, 1.0f, 1.0f);
    float3 ratio;
    [unroll] for (uint c = 0u; c < 3u; ++c) {
        const bool valid = total[c] > 0.0f && total[c] < 3.402823e38f;
        ratio[c] = valid ? saturate(seen[c] / total[c]) : 1.0f;
    }
    return ratio;
}

struct VisibilityInputs {
    float3 origin;        // the hit point moved off its triangle (OffsetRayOrigin)
    float3 ng;            // the geometric normal, facing the viewer
    float3 shading;       // the shading normal, after FadeShadingNormal: AoVisibility's axis
    uint self;            // the hit triangle
    uint2 pixel;
    float rotationTurns;
    uint nodeCount;
    float aperture;       // a, the AO map's visible fraction in [0, 1] (decision 257)
    float exponent;       // k = 2 (1 - a) / a of AoVisibility, for 0 < a < 1
};

// The AO map's visibility of a direction (decision 257, amended at implementation), an assumed
// directional AO: V_ao(d) = mu^k with mu = dot(s, d) about the shading normal s and
// k = 2 (1 - a) / a. Under the cosine-weighted measure t = mu^2 is uniform on [0, 1], so the mean
// of V_ao is the integral of t^(k / 2) over [0, 1], 1 / (1 + k / 2) = a: under uniform light the
// cosine-weighted visible fraction of the hemisphere is exactly a, the calibration of a visibility
// cone with sin^2(alpha) = a (Oat and Sander 2007, Ambient Aperture Lighting); the power law
// itself is UzPainter's construction. It is continuous in s and d, so a narrow specular lobe and
// the facet clip see no step; it is 1 along s and falls towards the horizon, more for a lower a.
// a = 1 keeps every direction without the test (the pixel of the pass before the AO map, bit for
// bit); a = 0 keeps none. `exponent` is k, computed once per hit.
float AoVisibility(VisibilityInputs v, float3 d) {
    if (v.aperture >= 1.0f) return 1.0f;
    if (!(v.aperture > 0.0f)) return 0.0f;
    return pow(max(dot(v.shading, d), 0.0f), v.exponent);
}

// R_d: the diffuse term's visibility per channel, sum V w L / sum w L over directions from the
// balance-heuristic mixture (Veach 1997) of cosine-weighted directions about the shading normal
// and environment-importance directions, w = cos / p_mix. Directions below the geometric facet
// are left out of both sums. V is V_ao (AoVisibility) for a direction no triangle blocks, else 0.
float3 DiffuseVisibility(ByteAddressBuffer lighting, ByteAddressBuffer nodes, ByteAddressBuffer occluders,
                         VisibilityInputs v, uint count) {
    if (count == 0u) return float3(1.0f, 1.0f, 1.0f);
    const uint cosineCount = (count + 1u) / 2u;
    const uint environmentCount = count / 2u;
    const float cosineShare = float(cosineCount) / float(count);
    const float environmentShare = float(environmentCount) / float(count);
    float3 t;
    float3 b;
    Basis(v.shading, t, b);
    const uint h0 = PixelHash(v.pixel, 0u);
    const uint h1 = PixelHash(v.pixel, 1u);
    const uint h2 = PixelHash(v.pixel, 2u);
    const uint h3 = PixelHash(v.pixel, 3u);
    float3 seen = float3(0.0f, 0.0f, 0.0f);
    float3 total = float3(0.0f, 0.0f, 0.0f);
    bool blocked = false;
    for (uint i = 0u; i < count; ++i) {
        float3 d;
        float environmentPdf;
        if (i < cosineCount) {
            const float2 xi = Sequence(i, cosineCount, h0, h1);
            const float r = sqrt(xi.x);
            const float phi = 2.0f * PI * xi.y;
            d = normalize(r * cos(phi) * t + r * sin(phi) * b + sqrt(max(0.0f, 1.0f - xi.x)) * v.shading);
            environmentPdf = EnvironmentPdf(lighting, d, v.rotationTurns);
        } else {
            const float2 xi = Sequence(i - cosineCount, environmentCount, h2, h3);
            d = SampleEnvironment(lighting, xi, v.rotationTurns, environmentPdf);
        }
        const float cosine = dot(v.shading, d);
        if (!(cosine > 0.0f) || !(dot(v.ng, d) > 0.0f)) continue;
        const float pdf = cosineShare * cosine / PI + environmentShare * environmentPdf;
        if (!(pdf > 0.0f)) continue;
        const float3 c = (cosine / pdf) * SampleLevel(lighting, 0u, d, v.rotationTurns);
        total += c;
        const float visible = AoVisibility(v, d);
        if (!(visible > 0.0f) || OccludedBvh(nodes, occluders, v.nodeCount, MakeShadowRay(v.origin, d), v.self)) {
            blocked = true;
        } else if (visible < 1.0f) {
            blocked = true;
            seen += visible * c;
        } else {
            seen += c;
        }
    }
    return Ratio(seen, total, blocked);
}

// R_s: the specular term's visibility per channel, sum V w L / sum w L over directions from the
// balance-heuristic mixture (Veach 1997) of the view reflected about GGX visible normals (Heitz
// 2018) of the shading normal and environment-importance directions, w = f cos / p_mix with
// f cos = F D G2 / (4 n.v) (Schlick's Fresnel with F0, the height-correlated Smith masking of the
// albedo table) and the visible-normal density G1 D / (4 n.v). Sampling the environment as well
// keeps a bright light that the lobe only grazes from resting on one heavy ray. Directions below
// the shading or the geometric facet are left out of both sums. V is V_ao (AoVisibility) for a
// direction no triangle blocks, else 0: V_ao weighted over the sampled lobe is the specular
// occlusion, so it depends on the view and the roughness.
float3 SpecularVisibility(ByteAddressBuffer lighting, ByteAddressBuffer nodes, ByteAddressBuffer occluders,
                          VisibilityInputs v, float3 view, float3 f0, float roughness, uint count) {
    if (count == 0u) return float3(1.0f, 1.0f, 1.0f);
    float3 t;
    float3 b;
    Basis(v.shading, t, b);
    const float3 ve = float3(dot(view, t), dot(view, b), dot(view, v.shading));
    if (!(ve.z > 0.0f)) return float3(1.0f, 1.0f, 1.0f);
    const float alpha = max(roughness * roughness, 1e-4f);
    const float alpha2 = alpha * alpha;
    const float lambdaView = SmithLambda(ve.z, alpha);
    const uint lobeCount = (count + 1u) / 2u;
    const uint environmentCount = count / 2u;
    const float lobeShare = float(lobeCount) / float(count);
    const float environmentShare = float(environmentCount) / float(count);
    const uint h4 = PixelHash(v.pixel, 4u);
    const uint h5 = PixelHash(v.pixel, 5u);
    const uint h6 = PixelHash(v.pixel, 6u);
    const uint h7 = PixelHash(v.pixel, 7u);
    float3 seen = float3(0.0f, 0.0f, 0.0f);
    float3 total = float3(0.0f, 0.0f, 0.0f);
    bool blocked = false;
    for (uint i = 0u; i < count; ++i) {
        float3 d;
        float3 le;
        float environmentPdf;
        if (i < lobeCount) {
            const float3 ne = SampleVisibleNormal(ve, alpha, Sequence(i, lobeCount, h4, h5));
            const float vn = dot(ve, ne);
            if (!(vn > 0.0f)) continue;
            le = ne * (2.0f * vn) - ve;
            if (!(le.z > 0.0f)) continue;
            d = normalize(le.x * t + le.y * b + le.z * v.shading);
            environmentPdf = EnvironmentPdf(lighting, d, v.rotationTurns);
        } else {
            d = SampleEnvironment(lighting, Sequence(i - lobeCount, environmentCount, h6, h7), v.rotationTurns,
                                  environmentPdf);
            le = float3(dot(d, t), dot(d, b), dot(d, v.shading));
            if (!(le.z > 0.0f)) continue;
        }
        if (!(dot(v.ng, d) > 0.0f)) continue;
        // The half vector; D's denominator h.z^2 (alpha^2 - 1) + 1 is written as
        // h.x^2 + h.y^2 + alpha^2 h.z^2 (|h| = 1), which keeps its precision at small alpha.
        const float3 hv = normalize(ve + le);
        const float vh = dot(ve, hv);
        if (!(vh > 0.0f)) continue;
        const float spread = hv.x * hv.x + hv.y * hv.y + alpha2 * hv.z * hv.z;
        const float distribution = alpha2 / (PI * spread * spread);
        const float lobePdf = distribution / ((1.0f + lambdaView) * 4.0f * ve.z);
        const float pdf = lobeShare * lobePdf + environmentShare * environmentPdf;
        if (!(pdf > 0.0f)) continue;
        const float m = saturate(1.0f - vh);
        const float fc = m * m * m * m * m;
        const float3 fresnel = f0 + (float3(1.0f, 1.0f, 1.0f) - f0) * fc;
        const float g2 = 1.0f / (1.0f + lambdaView + SmithLambda(le.z, alpha));
        const float3 c = fresnel * (distribution * g2 / (4.0f * ve.z * pdf)) * SampleLevel(lighting, 0u, d, v.rotationTurns);
        total += c;
        const float visible = AoVisibility(v, d);
        if (!(visible > 0.0f) || OccludedBvh(nodes, occluders, v.nodeCount, MakeShadowRay(v.origin, d), v.self)) {
            blocked = true;
        } else if (visible < 1.0f) {
            blocked = true;
            seen += visible * c;
        } else {
            seen += c;
        }
    }
    return Ratio(seen, total, blocked);
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
    const bool orthographic = frame.Load(24u * 4u) != 0u;
    const uint diffuseRays = frame.Load(25u * 4u);
    const uint specularRays = frame.Load(26u * 4u);
    const uint nodeCount = frame.Load(27u * 4u);
    const uint outputMode = frame.Load(28u * 4u);
    const float occlusionStrength = LoadF(frame, 29u);

    // The ray through the pixel centre: from the eye (perspective; tanHalf is the tangent of half
    // the field of view), or along `forward` from the pixel's point on the plane through the eye
    // (orthographic; tanHalf is half the orthographic height).
    const float sx = ((float(id.x) + 0.5f) / float(g_width) * 2.0f - 1.0f) * tanHalf * aspect;
    const float sy = (1.0f - (float(id.y) + 0.5f) / float(g_height) * 2.0f) * tanHalf;
    const float3 dir = orthographic ? forward : normalize(forward + right * sx + up * sy);
    const float3 origin = orthographic ? eye + right * sx + up * sy : eye;

    // Coverage is decided watertight (Woop, Benthin and Wald 2013): each corner relative to the
    // origin is sheared so the ray runs along the axis kz, and each edge function is the 2D cross
    // product of two sheared corners. A shared corner is sheared to the same values in every
    // triangle, and fl(a b - c d) has the sign of the exact a b - c d of those values or is zero,
    // so a ray inside the projected mesh is inside, or on an edge of, some triangle: no ray
    // through a shared edge or corner misses both sides. Both faces are visible: the triangle
    // covers the ray when no edge function is negative or none is positive.
    const float3 absDir = abs(dir);
    const uint kz = absDir.x > absDir.y ? (absDir.x > absDir.z ? 0u : 2u) : (absDir.y > absDir.z ? 1u : 2u);
    const uint kx = kz == 2u ? 0u : kz + 1u;
    const uint ky = kx == 2u ? 0u : kx + 1u;
    const float shearX = dir[kx] / dir[kz];
    const float shearY = dir[ky] / dir[kz];

    // Nearest hit among the tile's covering triangles, ascending index, strict nearer. The depth
    // and barycentrics of a covering triangle are Moller-Trumbore's.
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
        const float3 r0 = p0 - origin;
        const float3 r1 = p1 - origin;
        const float3 r2 = p2 - origin;
        precise const float x0 = r0[kx] - shearX * r0[kz];
        precise const float y0 = r0[ky] - shearY * r0[kz];
        precise const float x1 = r1[kx] - shearX * r1[kz];
        precise const float y1 = r1[ky] - shearY * r1[kz];
        precise const float x2 = r2[kx] - shearX * r2[kz];
        precise const float y2 = r2[ky] - shearY * r2[kz];
        precise const float f0 = x1 * y2 - y1 * x2;
        precise const float f1 = x2 * y0 - y2 * x0;
        precise const float f2 = x0 * y1 - y0 * x1;
        if ((f0 < 0.0f || f1 < 0.0f || f2 < 0.0f) && (f0 > 0.0f || f1 > 0.0f || f2 > 0.0f)) continue;
        if (f0 == 0.0f && f1 == 0.0f && f2 == 0.0f) continue;  // seen edge-on: covers nothing
        const float3 e1 = p1 - p0;
        const float3 e2 = p2 - p0;
        const float3 pv = cross(dir, e2);
        const float det = dot(e1, pv);
        if (det == 0.0f) continue;
        const float inv = 1.0f / det;
        const float3 tv = origin - p0;
        const float u = dot(tv, pv) * inv;
        const float3 qv = cross(tv, e1);
        const float v = dot(dir, qv) * inv;
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
        float ao = 1.0f;
        if (material < materialCount) {
            const uint mw = material * MATERIAL_WORDS;
            baseColour = LoadF3(materials, mw + 15u);
            metalness = LoadF(materials, mw + 18u);
            roughness = LoadF(materials, mw + 19u);
            const MapRef baseMap = LoadMap(materials, material, 0u);
            const MapRef metalMap = LoadMap(materials, material, 1u);
            const MapRef roughMap = LoadMap(materials, material, 2u);
            const MapRef normalMap = LoadMap(materials, material, 3u);
            const MapRef occlusionMap = LoadMap(materials, material, 4u);
            if (baseMap.offset != NO_MAP) baseColour = SampleMap(baseMap, 3u, uv);
            if (metalMap.offset != NO_MAP) metalness = SampleMap(metalMap, 1u, uv).x;
            if (roughMap.offset != NO_MAP) roughness = SampleMap(roughMap, 1u, uv).x;
            if (normalMap.offset != NO_MAP) tn = SampleMap(normalMap, 3u, uv) * 2.0f - 1.0f;
            if (occlusionMap.offset != NO_MAP) ao = SampleMap(occlusionMap, 1u, uv).x;
        }
        metalness = saturate(metalness);
        roughness = saturate(roughness);
        // The AO map's visible fraction a = 1 + s (ao - 1) (glTF 2.0 occlusionTexture.strength,
        // decision 257); ao = 1 (no map) gives exactly 1.
        const float aperture = ao == 1.0f ? 1.0f : saturate(1.0f + occlusionStrength * (ao - 1.0f));

        // MikkTSpace: the perturbed normal in the interpolated, unnormalised corner frame.
        const float3 bitangent = handedness * cross(n, tangent);
        float3 shading = tn.x * tangent + tn.y * bitangent + tn.z * n;
        shading = dot(shading, shading) > 0.0f ? normalize(shading) : normalize(n);
        shading = FadeShadingNormal(shading, n, ng, view);

        const float nv = max(dot(shading, view), 1e-4f);
        const float3 reflected = shading * (2.0f * nv) - view;
        const float3 f0 = float3(0.04f, 0.04f, 0.04f) + (baseColour - float3(0.04f, 0.04f, 0.04f)) * metalness;
        const float3 albedo = BrdfTable(lighting, brdfSize, nv, roughness);
        const float3 specular =
            Prefiltered(lighting, levels, normalize(reflected), roughness, rotationTurns) * (f0 * albedo.x + albedo.y);
        const float dielectricAlbedo = 0.04f * albedo.x + albedo.y;
        const float3 diffuse = baseColour * (1.0f - metalness) * Irradiance(lighting, Unrotate(shading, rotationTurns)) *
                               (albedo.z * (1.0f - dielectricAlbedo) / PI);

        // Visibility (decision 251): rays leave the hit point, interpolated from the corners
        // and moved off the triangle along its geometric normal, towards the viewer's side.
        ByteAddressBuffer nodes = ResourceDescriptorHeap[g_bvhNodesSrv];
        ByteAddressBuffer occluders = ResourceDescriptorHeap[g_occludersSrv];
        VisibilityInputs vis;
        vis.origin = OffsetRayOrigin(p0 * w0 + p1 * bestU + p2 * bestV, ng);
        vis.ng = ng;
        vis.shading = shading;
        vis.self = best;
        vis.pixel = id.xy;
        vis.rotationTurns = rotationTurns;
        vis.nodeCount = nodeCount;
        vis.aperture = aperture;
        vis.exponent = aperture > 0.0f && aperture < 1.0f ? 2.0f * (1.0f - aperture) / aperture : 0.0f;
        const float3 diffuseVisibility = DiffuseVisibility(lighting, nodes, occluders, vis, diffuseRays);
        const float3 specularVisibility =
            SpecularVisibility(lighting, nodes, occluders, vis, view, f0, roughness, specularRays);
        colour = (specular * specularVisibility + diffuse * diffuseVisibility) * intensity;
        if (outputMode == OUTPUT_DIFFUSE_VISIBILITY) colour = diffuseVisibility;
        if (outputMode == OUTPUT_SPECULAR_VISIBILITY) colour = specularVisibility;
    }

    const float4 linearColour = float4(RoundToHalf(colour.x), RoundToHalf(colour.y), RoundToHalf(colour.z), 1.0f);
    RWTexture2D<float4> linearOut = ResourceDescriptorHeap[g_linearUav];
    linearOut[id.xy] = linearColour;
    const uint4 codes = uint4(DisplayCodeOf(table, linearColour.x), DisplayCodeOf(table, linearColour.y),
                              DisplayCodeOf(table, linearColour.z), 65535u);
    RWTexture2D<float4> displayOut = ResourceDescriptorHeap[g_displayUav];
    displayOut[id.xy] = float4(codes) / 65535.0f;
}

// `probe` (tests, viewport.h `TraceVisibility`): one thread per ray of the buffer at g_frameSrv
// (words 0-2 the ray, occluder and node counts, word 3 zero, then 12 words per ray: point xyz,
// normal xyz, direction xyz, the triangle to skip, 0, 0). The ray leaves `point` moved along
// `normal` by OffsetRayOrigin (a zero normal moves nothing). Texel (i % g_width, i / g_width) of
// g_linearUav receives (blocked through the BVH, blocked by the linear test of every triangle,
// 0, 1).
[numthreads(64, 1, 1)]
void probe(uint3 id : SV_DispatchThreadID) {
    ByteAddressBuffer rays = ResourceDescriptorHeap[g_frameSrv];
    ByteAddressBuffer nodes = ResourceDescriptorHeap[g_bvhNodesSrv];
    ByteAddressBuffer occluders = ResourceDescriptorHeap[g_occludersSrv];
    const uint count = rays.Load(0u);
    const uint i = id.x;
    if (i >= count) return;
    const uint base = (4u + i * 12u) * 4u;
    const float3 start = asfloat(rays.Load3(base));
    const float3 normal = asfloat(rays.Load3(base + 12u));
    const float3 dir = asfloat(rays.Load3(base + 24u));
    const uint self = rays.Load(base + 36u);
    const ShadowRay r = MakeShadowRay(OffsetRayOrigin(start, normal), dir);
    const bool viaBvh = OccludedBvh(nodes, occluders, rays.Load(8u), r, self);
    const bool viaLinear = OccludedLinear(occluders, rays.Load(4u), r, self);
    RWTexture2D<float4> result = ResourceDescriptorHeap[g_linearUav];
    result[uint2(i % g_width, i / g_width)] = float4(viaBvh ? 1.0f : 0.0f, viaLinear ? 1.0f : 0.0f, 0.0f, 1.0f);
}
