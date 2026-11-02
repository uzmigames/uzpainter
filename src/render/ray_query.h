#pragma once

// UzPainter's backend-neutral inline-ray-query layer (phase3.2_vulkan-ray-tracing items 2.5, 2.7,
// 2.9 and 2.11; docs/architecture/13-engine-integration.md §2.4, §4.1; decision 372).
//
// - Capability: `QueryRayQuerySupport` reports whether the device runs inline ray queries and
//   names every missing item (DX12: DXR Tier 1.1 and Shader Model 6.6; Vulkan:
//   VK_KHR_acceleration_structure, VK_KHR_deferred_host_operations, VK_KHR_ray_query, features
//   accelerationStructure and rayQuery, and the entry points the vendored backend checks).
//   `RequireInlineRayQuery` turns a missing item into `gpu_backend_unavailable` before any work;
//   nothing falls back to another path.
// - Acceleration structures: `BuildRayScene` builds one BLAS per mesh through the raw RHI
//   `CreateBLAS` (never the vendored scene-level managers) with each geometry's real vertex
//   stride and opacity flag, and one TLAS over the instances, whose 64-byte records
//   (`PackRayInstance`) have the same bytes on DXR and Vulkan.
// - Ray cast: `CastRays` dispatches the ray-cast kernel (shaders/ray_cast.hlsl, the same HLSL for
//   DXIL and SPIR-V) and reads back one `RayHit` per ray. `RayCastReference` computes the same
//   records on the CPU in double precision; `DiffRayHits` compares two record sets field by field.
//
// Lifetime: a scene's GPU objects are destroyed by `ReleaseRayScene` only once nothing submitted
// uses them; a device that failed (removed, lost, abandoned) keeps them. Threading: as for every
// `IDevice`, one thread.

#include "render/backend.h"

#include <array>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>

namespace uzp::render {

// ── Capability ───────────────────────────────────────────────────────────────

struct RayQuerySupport {
    Backend backend = Backend::Dx12;
    bool accelerationStructures = false;  ///< BLAS/TLAS create and build work.
    bool inlineRayQuery = false;          ///< Compute kernels may use `RayQuery`.
    std::vector<std::string> missing;     ///< What keeps inline ray queries off, by name.
};

[[nodiscard]] RayQuerySupport QueryRayQuerySupport(IDevice& device);

/// Empty when the device runs inline ray queries; otherwise `gpu_backend_unavailable {backend,
/// reason}` naming every missing item. Called before any ray-query work is created.
[[nodiscard]] Result<void> RequireInlineRayQuery(IDevice& device);

// ── Scene ────────────────────────────────────────────────────────────────────

/// One triangle geometry: `vertexCount` vertices of `vertexStride` bytes, each starting with its
/// position as three floats; indexed when `indices` is not empty.
struct RayGeometry {
    std::vector<uint8_t> vertices;
    uint32_t vertexStride = 12;
    uint32_t vertexCount = 0;
    std::vector<uint32_t> indices;
    bool opaque = true;
};

/// One BLAS: its geometries in order (`RayHit::geometryIndex`).
struct RayMesh {
    std::vector<RayGeometry> geometries;
};

/// D3D12_RAYTRACING_INSTANCE_FLAGS == VkGeometryInstanceFlagBitsKHR (same values).
inline constexpr uint8_t kRayInstanceForceOpaque = 0x4;
inline constexpr uint8_t kRayInstanceForceNonOpaque = 0x8;
/// The four instance flags both APIs share (cull disable, flip facing, force opaque, force
/// non-opaque); `BuildRayScene` refuses any other bit.
inline constexpr uint8_t kRayInstanceFlagMask = 0xF;

struct RayInstance {
    uint32_t mesh = 0;
    /// Object to world, 3x4 row-major (the last column is the translation).
    std::array<float, 12> transform = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    uint32_t instanceId = 0;  ///< 24 bits.
    uint8_t mask = 0xFF;
    uint8_t flags = 0;
};

struct RaySceneDesc {
    std::vector<RayMesh> meshes;
    std::vector<RayInstance> instances;
};

/// Positions packed at `stride` bytes per vertex (the bytes after each position are a fixed
/// filler), for building a `RayGeometry`; empty for a stride below 12.
[[nodiscard]] std::vector<uint8_t> PackPositions(std::span<const float> xyz, uint32_t stride);

/// The 64-byte TLAS instance record, the layout of D3D12_RAYTRACING_INSTANCE_DESC and of
/// VkAccelerationStructureInstanceKHR: the transform, then `instanceId | mask << 24`, then
/// `hitGroupOffset | flags << 24`, then the BLAS address, little-endian.
[[nodiscard]] std::array<uint8_t, 64> PackRayInstance(const RayInstance& instance, uint32_t hitGroupOffset,
                                                      uint64_t blasAddress);

/// The GPU objects of a built scene.
struct RayScene {
    std::vector<uz::RHIBufferHandle> buffers;  ///< Vertex, index and instance buffers.
    std::vector<uz::RHIBLASHandle> blases;
    uz::RHITLASHandle tlas = uz::RHITLASHandle::Invalid();
    uint32_t instanceCount = 0;
    uint64_t buildFence = 0;
};

/// Validates `desc` (`request_failed` naming the first problem: no mesh or instance, an empty
/// geometry, a stride below 12 or not a multiple of 4, too few vertex bytes, an index count that
/// is not a multiple of 3 or an index past the vertices, an instance of an unknown mesh, an id
/// above 24 bits, a non-finite or singular transform, flags outside `kRayInstanceFlagMask` or
/// both opacities forced), requires inline ray queries, uploads the geometry, creates the BLASes and the
/// TLAS through the raw RHI and records every build in one submission (BLAS builds, a barrier,
/// the TLAS build, a barrier), then waits for it until `deadline`. A failed wait returns the
/// device's `WaitFailure` and leaves the objects to the failed device.
[[nodiscard]] Result<RayScene> BuildRayScene(IDevice& device, const RaySceneDesc& desc, Deadline deadline);

/// Destroys the scene's objects (the TLAS, the BLASes, the buffers) unless the device failed.
/// Only after every submission that used them has completed.
void ReleaseRayScene(IDevice& device, RayScene& scene);

// ── Ray cast ─────────────────────────────────────────────────────────────────

/// One ray of the ray-cast kernel (32 bytes, `Ray` in ray_cast.hlsl).
struct CastRay {
    std::array<float, 3> origin = {};
    float tMin = 0;
    std::array<float, 3> direction = {};
    float tMax = 0;
};

/// One hit record (32 bytes, `Hit` in ray_cast.hlsl). A miss is all zero.
struct RayHit {
    uint32_t hit = 0;
    uint32_t instanceId = 0;
    uint32_t primitiveId = 0;
    uint32_t geometryIndex = 0;
    float u = 0;  ///< Barycentric weight of the triangle's vertex 1.
    float v = 0;  ///< Barycentric weight of the triangle's vertex 2.
    float t = 0;
    uint32_t instanceIndex = 0;
};

/// The ray-cast kernel's HLSL (shaders/ray_cast.hlsl).
[[nodiscard]] std::string_view RayCastHlsl();

/// The ray-cast kernel compiled by DXC for `target` (cs_6_6; SPIR-V with `SPV_KHR_ray_query`,
/// UZP-MOD-006), or `kernel_compile_failed`.
[[nodiscard]] Result<std::vector<uint8_t>> CompileRayCastKernel(KernelTarget target,
                                                                const std::filesystem::path& dxcompiler);

/// SPIR-V capability `RayQueryKHR` and the extension the ray-cast module must declare.
inline constexpr uint32_t kSpirvCapabilityRayQueryKHR = 4472;
inline constexpr uint32_t kSpirvCapabilityRayTracingKHR = 4479;
/// The `OpExtension` names a SPIR-V module declares, in module order.
[[nodiscard]] std::vector<std::string> SpirvExtensions(std::span<const uint8_t> spirv);

/// Traces `rays` through the scene's TLAS with `kernel` (made from `CompileRayCastKernel` for the
/// device) and returns one record per ray, after requiring inline ray queries; at most
/// 65535 x 64 rays (one dispatch), `request_failed` beyond. A failed wait
/// returns the device's `WaitFailure` and leaves the buffers to the failed device.
[[nodiscard]] Result<std::vector<RayHit>> CastRays(IDevice& device, const RayScene& scene,
                                                   const ComputeKernel& kernel, std::span<const CastRay> rays,
                                                   Deadline deadline);

/// The records the kernel must produce, computed on the CPU in double precision: each instance's
/// ray in object space (inverse of its affine transform), Möller–Trumbore per triangle, hits with
/// tMin <= t <= tMax, the nearest kept; a triangle is non-opaque when its geometry is and the
/// instance does not force it opaque (or the instance forces it non-opaque), and a non-opaque
/// triangle counts only when its primitive index is even (the kernel's rule); instances with mask
/// 0 are skipped. Exact ties between triangles are not resolved the way hardware does, so known
/// answers use rays without ties.
[[nodiscard]] std::vector<RayHit> RayCastReference(const RaySceneDesc& desc, std::span<const CastRay> rays);

/// How two record sets differ: per field, the rays whose field differs (floats beyond
/// `tolerance`), the largest |delta| of t and of the barycentrics over rays both hit, and one line
/// per differing ray.
struct RayHitDiff {
    size_t rays = 0;
    size_t hit = 0;
    size_t instanceId = 0;
    size_t primitiveId = 0;
    size_t geometryIndex = 0;
    size_t instanceIndex = 0;
    size_t barycentrics = 0;
    size_t t = 0;
    double maxDeltaT = 0;
    double maxDeltaBarycentric = 0;
    std::vector<std::string> differing;  ///< "ray <i>: <field> <a> vs <b>; ...".

    [[nodiscard]] bool Equal() const { return differing.empty(); }
};

[[nodiscard]] RayHitDiff DiffRayHits(std::span<const RayHit> a, std::span<const RayHit> b, double tolerance);

// ── Qualification slice ──────────────────────────────────────────────────────

/// The scene of the selftest ray-query slice and the native tests (decision 372): one mesh of two
/// geometries over the unit square, an opaque indexed quad at z = 0 with a 20-byte vertex stride
/// (geometry 0, triangles (0,1,2) below and (0,2,3) above the diagonal y = x) and a non-opaque
/// non-indexed quad at z = 0.5 with a 12-byte stride (geometry 1, triangle 0 below the diagonal,
/// triangle 1 above it); three instances: identity with id 7, translated by x + 10 with id
/// 0x123456, translated by x + 20 with id 3 and forced opaque.
[[nodiscard]] RaySceneDesc RayQueryQualificationScene();
/// Nine rays with known answers on that scene: the even non-opaque triangle committed, the odd one
/// passed through, the second instance, the forced-opaque instance, a miss, tMax before any
/// surface, tMin past the first surface, an oblique ray and a ray from below. No ray meets an edge.
[[nodiscard]] std::vector<CastRay> RayQueryQualificationRays();
/// The hand-computed answers to those rays (the check of `RayCastReference` itself).
[[nodiscard]] std::vector<RayHit> RayQueryQualificationAnswers();

}  // namespace uzp::render
