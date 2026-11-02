// Inline ray-query ray cast (phase3.2_vulkan-ray-tracing items 2.9 and 2.11, decision 372): one
// hit record per ray, from the same HLSL on DX12 (DXIL, SM 6.6 descriptor heap) and on Vulkan
// (SPIR-V with SPV_KHR_ray_query, the vendored fixed bindings). No ray-tracing pipeline: a compute
// kernel traces with `RayQuery` (src/render/ray_query.h).
//
// Non-opaque geometry is resolved here, in place of an any-hit shader: a non-opaque triangle
// candidate is committed when its primitive index is even and ignored when odd, so a ray passes
// through the odd triangles of a non-opaque geometry. The CPU reference (`RayCastReference`)
// applies the same rule.
//
// Bindings: DX12 reads the rays (structured SRV), the hits (structured UAV) and the TLAS (its SRV)
// from `ResourceDescriptorHeap` at the indices in the root constants. Vulkan (`__spirv__`) reads
// the rays at storage-buffer binding 64, the hits at 65 and the TLAS at binding 80
// (UZP-MOD-007), with the ray count in the push constants.

struct Ray {
    float3 origin;
    float tMin;
    float3 direction;
    float tMax;
};

struct Hit {
    uint hit;            // 1: a triangle was committed; 0: a miss (every other field 0)
    uint instanceId;     // the instance's 24-bit user id (CommittedInstanceID)
    uint primitiveId;    // the triangle within its geometry (CommittedPrimitiveIndex)
    uint geometryIndex;  // the geometry within its BLAS (CommittedGeometryIndex)
    float u;             // barycentric weight of the triangle's vertex 1
    float v;             // barycentric weight of the triangle's vertex 2
    float t;             // the hit distance along the ray, in units of its direction
    uint instanceIndex;  // the instance's position in the TLAS (CommittedInstanceIndex)
};

#if defined(__spirv__)
struct Params {
    uint rayCount;
    uint raysIndex;
    uint hitsIndex;
    uint tlasIndex;
};
[[vk::push_constant]] Params g_root;
[[vk::binding(64, 0)]] StructuredBuffer<Ray> g_rays;
[[vk::binding(65, 0)]] RWStructuredBuffer<Hit> g_hits;
[[vk::binding(80, 0)]] RaytracingAccelerationStructure g_tlas;
#define RAY_COUNT g_root.rayCount
#else
cbuffer Params : register(b0) {
    uint g_rayCount;
    uint g_raysIndex;
    uint g_hitsIndex;
    uint g_tlasIndex;
};
#define RAY_COUNT g_rayCount
#endif

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= RAY_COUNT) return;
#if defined(__spirv__)
    const Ray ray = g_rays[id.x];
#else
    StructuredBuffer<Ray> rays = ResourceDescriptorHeap[g_raysIndex];
    RWStructuredBuffer<Hit> hits = ResourceDescriptorHeap[g_hitsIndex];
    RaytracingAccelerationStructure tlas = ResourceDescriptorHeap[g_tlasIndex];
    const Ray ray = rays[id.x];
#endif
    RayDesc desc;
    desc.Origin = ray.origin;
    desc.TMin = ray.tMin;
    desc.Direction = ray.direction;
    desc.TMax = ray.tMax;

    RayQuery<RAY_FLAG_NONE> query;
#if defined(__spirv__)
    query.TraceRayInline(g_tlas, RAY_FLAG_NONE, 0xFF, desc);
#else
    query.TraceRayInline(tlas, RAY_FLAG_NONE, 0xFF, desc);
#endif
    while (query.Proceed()) {
        if (query.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE &&
            (query.CandidatePrimitiveIndex() & 1u) == 0u) {
            query.CommitNonOpaqueTriangleHit();
        }
    }

    Hit hit = (Hit)0;
    if (query.CommittedStatus() == COMMITTED_TRIANGLE_HIT) {
        const float2 barycentrics = query.CommittedTriangleBarycentrics();
        hit.hit = 1u;
        hit.instanceId = query.CommittedInstanceID();
        hit.primitiveId = query.CommittedPrimitiveIndex();
        hit.geometryIndex = query.CommittedGeometryIndex();
        hit.u = barycentrics.x;
        hit.v = barycentrics.y;
        hit.t = query.CommittedRayT();
        hit.instanceIndex = query.CommittedInstanceIndex();
    }
#if defined(__spirv__)
    g_hits[id.x] = hit;
#else
    hits[id.x] = hit;
#endif
}
