// Native tests of the inline-ray-query layer (phase3.2_vulkan-ray-tracing items 2.1-2.3, 2.5-2.7,
// 2.9, 2.11 and tests 3.1-3.3; decision 372): src/render/ray_query.h over the vendored Vulkan
// acceleration structures (UZP-MOD-007) and DXR. Driven by tests/render/test_ray_query.py.
//
//   ray-query-reference  no GPU: the CPU reference against hand-computed answers, the 64-byte
//                        instance record, the record differ, and the capability decision on
//                        fabricated Vulkan records (a device without VK_KHR_ray_query reports it
//                        missing)
//   vulkan-ray-query     this machine's Vulkan device: what it enabled, the ray-cast kernel's
//                        SPIR-V, invalid BLAS/TLAS input refused, the qualification scene traced
//                        and compared with the known answers and the CPU reference, twice
//                        byte-identical, a rebuild after a vertex change, a refused build that
//                        submits nothing
//   dx12-ray-query       the same scene and rays on this machine's DX12 device (DXR 1.1), compared
//                        with the CPU reference
//   ray-query-mesh       no GPU: the ray scene of a UzPainter mesh (`RaySceneFromMesh`)
//   ray-cast-fixtures    every ray-cast fixture on DX12 and Vulkan, twice each: repeatability, the
//                        CPU reference by ray kind, the DX12/Vulkan comparison; writes
//                        <dir>/ray-cast-raw.json for tools/parity/raycast.py
//
// Exit code 77 when the machine has no device of the backend.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/capabilities.h"
#include "render/device.h"
#include "render/ray_query.h"
#include "render/vulkan_backend.h"
#include "render/vulkan_kernels.h"
#include "render/vulkan_qualification.h"

#include "mesh/texturing_mesh.h"

#include "paths.h"
#include "vulkan_command_list.h"
#include "vulkan_device.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <initializer_list>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace uzp::render;
namespace fs = std::filesystem;
using Ms = std::chrono::milliseconds;

constexpr int kExitSkip = 77;
constexpr double kTolerance = 1e-5;
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

template <class T>
std::string Describe(const Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

std::string Joined(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) out += (out.empty() ? "" : " | ") + item;
    return out;
}

fs::path DxcPath() { return fs::path(uz::GetExeDir()) / "dxcompiler.dll"; }

Deadline Soon() { return Clock::now() + Ms(10000); }

// ── ray-query-reference ──────────────────────────────────────────────────────

VulkanDeviceRecord RecordWith(bool accelerationStructure, bool deferred, bool rayQuery, bool features) {
    VulkanDeviceRecord r;
    r.name = "Fabricated dGPU";
    if (accelerationStructure) r.extensions.emplace_back("VK_KHR_acceleration_structure");
    if (deferred) r.extensions.emplace_back("VK_KHR_deferred_host_operations");
    if (rayQuery) r.extensions.emplace_back("VK_KHR_ray_query");
    if (accelerationStructure) r.features.emplace_back("accelerationStructure", features);
    if (rayQuery) r.features.emplace_back("rayQuery", features);
    return r;
}

int RunReference() {
    const RaySceneDesc scene = RayQueryQualificationScene();
    const std::vector<CastRay> rays = RayQueryQualificationRays();
    const std::vector<RayHit> answers = RayQueryQualificationAnswers();
    const std::vector<RayHit> reference = RayCastReference(scene, rays);
    const RayHitDiff known = DiffRayHits(reference, answers, 1e-6);
    Check(known.Equal() && rays.size() == answers.size(),
          "the CPU reference gives the hand-computed answers of the qualification rays", Joined(known.differing));
    Check(scene.meshes.size() == 1 && scene.meshes[0].geometries[0].vertexStride == 20 &&
              scene.meshes[0].geometries[1].vertexStride == 12 && !scene.meshes[0].geometries[1].opaque,
          "the qualification BLAS has a 20-byte and a 12-byte stride and a non-opaque geometry");

    RayInstance instance;
    instance.transform = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
    instance.instanceId = 0x123456;
    instance.mask = 0xAB;
    instance.flags = kRayInstanceForceOpaque;
    const std::array<uint8_t, 64> record = PackRayInstance(instance, 0x0A0B0C, 0x1122334455667788ull);
    float transform[12];
    std::memcpy(transform, record.data(), 48);
    uint32_t idMask = 0, offsetFlags = 0;
    uint64_t address = 0;
    std::memcpy(&idMask, record.data() + 48, 4);
    std::memcpy(&offsetFlags, record.data() + 52, 4);
    std::memcpy(&address, record.data() + 56, 8);
    Check(transform[3] == 4 && transform[11] == 12 && idMask == 0xAB123456u && offsetFlags == 0x040A0B0Cu &&
              address == 0x1122334455667788ull,
          "the instance record has the 64-byte layout of D3D12_RAYTRACING_INSTANCE_DESC and "
          "VkAccelerationStructureInstanceKHR");

    std::vector<RayHit> changed = answers;
    changed[3].primitiveId = 0;
    changed[7].t += 0.01f;
    const RayHitDiff diff = DiffRayHits(changed, answers, kTolerance);
    Check(diff.primitiveId == 1 && diff.t == 1 && diff.differing.size() == 2 &&
              diff.differing[0].starts_with("ray 3: primitive 0 vs 1") && diff.differing[1].starts_with("ray 7: t"),
          "the record differ counts each field and lists every differing ray", Joined(diff.differing));
    std::vector<RayHit> nonFinite = answers;
    nonFinite[0].t = std::numeric_limits<float>::infinity();
    nonFinite[1].u = std::numeric_limits<float>::quiet_NaN();
    std::vector<RayHit> bothInfinite = answers;
    bothInfinite[0].t = std::numeric_limits<float>::infinity();
    const RayHitDiff nan = DiffRayHits(nonFinite, answers, kTolerance);
    Check(nan.differing.size() == 2 && !DiffRayHits(bothInfinite, nonFinite, kTolerance).differing.empty(),
          "a non-finite distance or barycentric never compares equal", Joined(nan.differing));

    Check(VulkanRayQueryMissing(RecordWith(true, true, true, true)).empty(),
          "a device with the three extensions and both features misses nothing");
    Check(VulkanRayQueryMissing(RecordWith(true, true, false, true)) == std::vector<std::string>{"VK_KHR_ray_query"},
          "a device without VK_KHR_ray_query reports it missing");
    Check(VulkanRayQueryMissing(RecordWith(true, true, true, false)) ==
              std::vector<std::string>{"accelerationStructure", "rayQuery"},
          "features reported false are named");
    Check(VulkanRayQueryMissing(RecordWith(false, false, false, false)) ==
              std::vector<std::string>{"VK_KHR_acceleration_structure", "VK_KHR_deferred_host_operations",
                                       "VK_KHR_ray_query"},
          "a device without any of them names the three extensions");
    const CapabilityReport without = VulkanCapabilityReport(RecordWith(true, true, false, true), AdmissionPolicy{});
    const CapabilityReport with = VulkanCapabilityReport(RecordWith(true, true, true, true), AdmissionPolicy{});
    Check(!without.rayQuery && without.rayTracing && without.rayQueryMissing == std::vector<std::string>{"VK_KHR_ray_query"} &&
              without.ToJson().find("\"ray_query_missing\":[\"VK_KHR_ray_query\"]") != std::string::npos,
          "the Vulkan capability report states ray queries unavailable with the missing list");
    Check(with.rayQuery && with.rayTracing && with.rayQueryMissing.empty() &&
              with.ToJson().find("\"ray_query\":true,\"ray_query_missing\":[]") != std::string::npos,
          "the Vulkan capability report states ray queries available with nothing missing");
    return Finish();
}

// ── Meshes (item 2.7) ────────────────────────────────────────────────────────

/// Two objects of a UzPainter mesh: a unit quad of material 0 and a unit quad of material 1 at
/// z = -1 in object 0, and object 1 (the same quad, material 0) translated by x + 5 through its
/// column-major transform.
uzp::mesh::TexturingMesh TwoObjectMesh() {
    using namespace uzp::mesh;
    TexturingMesh mesh;
    mesh.positions = {{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}, {0, 0, -1}, {1, 0, -1}, {1, 1, -1}, {0, 1, -1}};
    const auto corner = [&](uint32_t position, uint32_t material) {
        Corner c;
        c.position = position;
        c.material = material;
        mesh.corners.push_back(c);
        return static_cast<uint32_t>(mesh.corners.size() - 1);
    };
    const auto quad = [&](Object& object, uint32_t base, uint32_t material) {
        object.triangles.push_back({{corner(base, material), corner(base + 1, material), corner(base + 2, material)}});
        object.triangles.push_back({{corner(base, material), corner(base + 2, material), corner(base + 3, material)}});
    };
    Object first;
    quad(first, 4, 1);  // material 1 first in file order; geometries follow material order
    quad(first, 0, 0);
    Object second;
    second.transform = kIdentity;
    second.transform[12] = 5;  // column 3, row 0: the x translation
    quad(second, 0, 0);
    Object empty;  // no triangles: no BLAS
    mesh.objects = {first, empty, second};
    mesh.materials = {{"opaque", 0}, {"cutout", 1}};
    return mesh;
}

std::vector<CastRay> TwoObjectRays() {
    return {
        CastRay{{0.75f, 0.25f, 1}, 0, {0, 0, -1}, 100},  // object 0, material 0 quad
        CastRay{{0.25f, 0.75f, 1}, 0, {0, 0, -1}, 100},  // the same, other triangle
        CastRay{{0.6f, 0.3f, -3}, 0, {0, 0, 1}, 100},    // from below: material 1 (non-opaque, even)
        CastRay{{0.3f, 0.6f, -3}, 0, {0, 0, 1}, 100},    // from below: material 1 odd passed, quad 0 behind
        CastRay{{5.75f, 0.25f, 1}, 0, {0, 0, -1}, 100},  // object 2, translated
        CastRay{{2.5f, 0.5f, 1}, 0, {0, 0, -1}, 100},    // between the objects: a miss
    };
}

int RunMesh() {
    const uzp::mesh::TexturingMesh mesh = TwoObjectMesh();
    const uint32_t cutout[] = {1};
    const RaySceneDesc scene = RaySceneFromMesh(mesh, cutout);
    Check(scene.meshes.size() == 2 && scene.instances.size() == 2 && scene.meshes[0].geometries.size() == 2 &&
              scene.meshes[1].geometries.size() == 1,
          "a mesh gives one BLAS per object with triangles and one geometry per material");
    const RayGeometry& opaque = scene.meshes[0].geometries[0];
    const RayGeometry& cut = scene.meshes[0].geometries[1];
    Check(opaque.vertexStride == 12 && opaque.vertexCount == 4 && opaque.indices.size() == 6 && opaque.opaque &&
              cut.vertexCount == 4 && !cut.opaque,
          "each geometry holds its own positions at the 12-byte Float3 stride and its material's opacity");
    Check(scene.instances[1].transform[3] == 5 && scene.instances[1].transform[0] == 1 &&
              scene.instances[0].instanceId == 0 && scene.instances[1].instanceId == 2 &&
              scene.instances[1].mesh == 1,
          "an object's column-major transform becomes the row-major instance transform, its index the id");
    const std::vector<RayHit> hits = RayCastReference(scene, TwoObjectRays());
    Check(hits[0].hit && hits[0].geometryIndex == 0 && hits[0].primitiveId == 0 && hits[2].geometryIndex == 1 &&
              hits[3].geometryIndex == 0 && hits[3].t == 3.0f && hits[4].instanceId == 2 && !hits[5].hit,
          "the reference traces the mesh scene: materials, opacity, the translated object, a miss");
    return Finish();
}

// ── GPU cases ────────────────────────────────────────────────────────────────

struct Traced {
    std::vector<RayHit> hits;
    bool ok = false;
};

/// Traces the qualification rays through `desc` on `device` with `kernel`.
Traced Trace(IDevice& device, const ComputeKernel& kernel, const RaySceneDesc& desc,
             const std::vector<CastRay>& rays, const std::string& what) {
    Result<RayScene> scene = BuildRayScene(device, desc, Soon());
    Check(scene.has_value(), what + ": the BLAS and TLAS build", Describe(scene));
    if (!scene) return {};
    Result<std::vector<RayHit>> hits = CastRays(device, *scene, kernel, rays, Soon());
    Check(hits.has_value(), what + ": the inline queries are traced and read back", Describe(hits));
    if (!hits) return {};
    ReleaseRayScene(device, *scene);
    return {*hits, true};
}

/// The checks both backends share; the traced records, empty when they did not run.
std::vector<RayHit> RunShared(IDevice& device, const std::string& backend) {
    Result<std::vector<uint8_t>> bytecode = CompileRayCastKernel(device.NativeKernelTarget(), DxcPath());
    Check(bytecode.has_value(), backend + ": the ray-cast kernel compiles", Describe(bytecode));
    if (!bytecode) return {};
    if (device.NativeKernelTarget() == KernelTarget::Spirv) {
        const SpirvFacts facts = InspectSpirv(*bytecode);
        const std::vector<std::string> extensions = SpirvExtensions(*bytecode);
        Check(std::find(extensions.begin(), extensions.end(), "SPV_KHR_ray_query") != extensions.end() &&
                  facts.HasCapability(kSpirvCapabilityRayQueryKHR) &&
                  !facts.HasCapability(kSpirvCapabilityRayTracingKHR),
              "vulkan: the SPIR-V declares SPV_KHR_ray_query and RayQueryKHR, no ray-tracing pipeline",
              Joined(extensions));
        Check(std::find(facts.bindings.begin(), facts.bindings.end(), 80u) != facts.bindings.end(),
              "vulkan: the TLAS is at binding 80");
    }
    Result<ComputeKernel> kernel = device.CreateComputeKernel(*bytecode, "ray_cast");
    Check(kernel.has_value(), backend + ": the ray-cast compute pipeline is created", Describe(kernel));
    if (!kernel) return {};

    const RaySceneDesc desc = RayQueryQualificationScene();
    const std::vector<CastRay> rays = RayQueryQualificationRays();
    const Traced first = Trace(device, *kernel, desc, rays, backend);
    if (!first.ok) return {};
    const RayHitDiff known = DiffRayHits(first.hits, RayQueryQualificationAnswers(), kTolerance);
    Check(known.Equal(), backend + ": every record equals its hand-computed answer", Joined(known.differing));
    const RayHitDiff reference = DiffRayHits(first.hits, RayCastReference(desc, rays), kTolerance);
    Check(reference.Equal(), backend + ": every record equals the CPU reference", Joined(reference.differing));
    char deltas[96];
    std::snprintf(deltas, sizeof(deltas), "max |dt| %.3g, max |d barycentric| %.3g", reference.maxDeltaT,
                  reference.maxDeltaBarycentric);
    Info(backend + ": " + deltas);

    const Traced second = Trace(device, *kernel, desc, rays, backend + " again");
    Check(second.ok && std::memcmp(first.hits.data(), second.hits.data(), first.hits.size() * sizeof(RayHit)) == 0,
          backend + ": a second build and trace gives byte-identical records");

    // Rebuild after a vertex change: the opaque quad moved to z = -0.5.
    RaySceneDesc moved = desc;
    RayGeometry& quad = moved.meshes[0].geometries[0];
    for (uint32_t v = 0; v < quad.vertexCount; ++v) {
        const float z = -0.5f;
        std::memcpy(quad.vertices.data() + static_cast<size_t>(v) * quad.vertexStride + 8, &z, 4);
    }
    const Traced rebuilt = Trace(device, *kernel, moved, rays, backend + " moved");
    const RayHitDiff movedDiff = rebuilt.ok ? DiffRayHits(rebuilt.hits, RayCastReference(moved, rays), kTolerance)
                                            : RayHitDiff{};
    Check(rebuilt.ok && movedDiff.Equal() && rebuilt.hits[1].t == 2.5f,
          backend + ": a rebuild after a vertex change hits the moved triangles", Joined(movedDiff.differing));

    // Invalid input: refused by the layer before anything is created.
    RaySceneDesc bad = desc;
    bad.meshes[0].geometries[1].vertexStride = 10;
    Result<RayScene> refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().code == ErrorCode::RequestFailed &&
              refused.error().reason.find("stride 10") != std::string::npos,
          backend + ": a 10-byte vertex stride is refused", Describe(refused));
    bad = desc;
    bad.meshes[0].geometries[0].indices.pop_back();
    refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().reason.find("multiple of 3") != std::string::npos,
          backend + ": an index count that is not a multiple of 3 is refused", Describe(refused));
    bad = desc;
    bad.meshes[0].geometries[0].indices[2] = 9;
    refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().reason.find("past the vertices") != std::string::npos,
          backend + ": an index past the vertices is refused", Describe(refused));
    bad = desc;
    bad.instances[0].transform = {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0};
    refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().reason.find("not invertible") != std::string::npos,
          backend + ": a singular instance transform is refused", Describe(refused));
    bad = desc;
    bad.instances[2].flags = kRayInstanceForceOpaque | kRayInstanceForceNonOpaque;
    refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().reason.find("forced") != std::string::npos,
          backend + ": an instance forced both opaque and non-opaque is refused", Describe(refused));
    bad = desc;
    bad.instances[1].mesh = 4;
    refused = BuildRayScene(device, bad, Soon());
    Check(!refused && refused.error().reason.find("unknown mesh") != std::string::npos,
          backend + ": an instance of an unknown mesh is refused", Describe(refused));

    // A UzPainter mesh's scene through the same calls (item 2.7).
    const uint32_t cutout[] = {1};
    const RaySceneDesc meshScene = RaySceneFromMesh(TwoObjectMesh(), cutout);
    const Traced meshTrace = Trace(device, *kernel, meshScene, TwoObjectRays(), backend + " mesh");
    const RayHitDiff meshDiff =
        meshTrace.ok ? DiffRayHits(meshTrace.hits, RayCastReference(meshScene, TwoObjectRays()), kTolerance)
                     : RayHitDiff{};
    Check(meshTrace.ok && meshDiff.Equal(), backend + ": a UzPainter mesh's scene traces as the CPU reference",
          Joined(meshDiff.differing));

    device.DestroyComputeKernel(*kernel);
    return first.hits;
}

/// The vendored RHI refuses invalid BLAS/TLAS descriptions itself (UZP-MOD-007 on Vulkan).
void RunRhiRefusals(IDevice& device) {
    uz::RHIBufferDesc plain;
    plain.sizeBytes = 256;
    plain.usage = uz::RHIBufferUsage::StructuredBuffer;
    plain.stride = 4;
    plain.memory = uz::RHIMemoryType::Upload;
    Result<uz::RHIBufferHandle> noInput = device.CreateBuffer(plain);
    plain.usage = uz::RHIBufferUsage::AccelerationStructureBuildInput;
    plain.stride = 0;
    Result<uz::RHIBufferHandle> input = device.CreateBuffer(plain);
    Check(noInput && input, "vulkan: buffers with and without AccelerationStructureBuildInput are created");
    if (!noInput || !input) return;
    uz::IRHIDevice& rhi = device.Rhi();
    uz::RHIRTGeometryDesc g;
    g.vertexBuffer = *input;
    g.vertexCount = 3;
    g.vertexStride = 12;
    uz::RHIBLASDesc blas;
    blas.geometries = &g;
    blas.geometryCount = 1;
    blas.buildFlags = uz::RHIASBuildFlags::PreferFastTrace;
    const uz::RHIBLASHandle good = rhi.CreateBLAS(blas);
    Check(good.IsValid() && rhi.GetBLASGPUAddress(good) != 0, "vulkan: a valid BLAS is created with a device address");
    const auto refusedWith = [&](auto mutate) {
        uz::RHIRTGeometryDesc changed = g;
        uz::RHIBLASDesc desc = blas;
        desc.geometries = &changed;
        mutate(changed, desc);
        const uz::RHIBLASHandle handle = rhi.CreateBLAS(desc);
        if (handle.IsValid()) rhi.DestroyBLAS(handle);
        return !handle.IsValid();
    };
    Check(refusedWith([](uz::RHIRTGeometryDesc& c, uz::RHIBLASDesc&) { c.vertexStride = 10; }),
          "vulkan: CreateBLAS refuses a stride below 12 bytes");
    Check(refusedWith([](uz::RHIRTGeometryDesc& c, uz::RHIBLASDesc&) { c.vertexFormat = uz::RHIFormat::RGBA16Float; }),
          "vulkan: CreateBLAS refuses a vertex format other than RGB32Float");
    Check(refusedWith([&](uz::RHIRTGeometryDesc& c, uz::RHIBLASDesc&) { c.vertexBuffer = *noInput; }),
          "vulkan: CreateBLAS refuses a vertex buffer without AccelerationStructureBuildInput");
    Check(refusedWith([](uz::RHIRTGeometryDesc& c, uz::RHIBLASDesc&) { c.vertexCount = 4; }),
          "vulkan: CreateBLAS refuses a non-indexed vertex count that is not a multiple of 3");
    Check(refusedWith([](uz::RHIRTGeometryDesc& c, uz::RHIBLASDesc&) { c.vertexCount = 30; }),
          "vulkan: CreateBLAS refuses vertices past the end of the buffer");
    Check(refusedWith([](uz::RHIRTGeometryDesc&, uz::RHIBLASDesc& d) {
              d.buildFlags = uz::RHIASBuildFlags::PreferFastTrace | uz::RHIASBuildFlags::PreferFastBuild;
          }),
          "vulkan: CreateBLAS refuses PreferFastTrace with PreferFastBuild");
    Check(refusedWith([](uz::RHIRTGeometryDesc&, uz::RHIBLASDesc& d) { d.geometryCount = 0; }),
          "vulkan: CreateBLAS refuses a description without geometry");
    uz::RHITLASDesc tlasDesc;
    tlasDesc.maxInstanceCount = 0;
    Check(!rhi.CreateTLAS(tlasDesc).IsValid(), "vulkan: CreateTLAS refuses zero instances");

    // A refused build records nothing, and the queue then submits nothing.
    tlasDesc.maxInstanceCount = 1;
    const uz::RHITLASHandle tlas = rhi.CreateTLAS(tlasDesc);
    Check(tlas.IsValid(), "vulkan: a TLAS for one instance is created");
    const uint64_t before = device.Queue().LastSubmitted();
    Result<uint64_t> fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildTLAS(tlas, *input, 2, uz::RHIBufferHandle::Invalid());  // more than the TLAS holds
    });
    Check(!fence && fence.error().code == ErrorCode::RequestFailed &&
              fence.error().reason.find("acceleration-structure") != std::string::npos &&
              device.Queue().LastSubmitted() == before,
          "vulkan: a TLAS build past its instance count is refused and the list is not submitted", Describe(fence));
    fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildBLAS(good, uz::RHIBufferHandle::Invalid(), true);  // an update without AllowUpdate
    });
    Check(!fence && device.Queue().LastSubmitted() == before,
          "vulkan: a BLAS update without AllowUpdate is refused and the list is not submitted", Describe(fence));
    // A build in a refused list never ran, so a later update of it is refused too.
    blas.buildFlags = uz::RHIASBuildFlags::PreferFastTrace | uz::RHIASBuildFlags::AllowUpdate;
    const uz::RHIBLASHandle updatable = rhi.CreateBLAS(blas);
    fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildBLAS(updatable, uz::RHIBufferHandle::Invalid());
        cmd.BuildBLAS(updatable, uz::RHIBufferHandle::Invalid(), true);  // after a build in this list: allowed
        cmd.BuildTLAS(tlas, *input, 2, uz::RHIBufferHandle::Invalid());  // refused: the list is not submitted
    });
    Result<uint64_t> later = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildBLAS(updatable, uz::RHIBufferHandle::Invalid(), true);
    });
    Check(updatable.IsValid() && !fence && !later && device.Queue().LastSubmitted() == before,
          "vulkan: a build in a refused list does not count as built for a later update", Describe(later));
    Result<uint64_t> built = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildBLAS(updatable, uz::RHIBufferHandle::Invalid());
    });
    Result<uint64_t> updated = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        cmd.BuildBLAS(updatable, uz::RHIBufferHandle::Invalid(), true);
        cmd.UAVBarrierAS();
    });
    Check(built && updated && device.Queue().Wait(*updated, Soon()).status == WaitStatus::Signaled,
          "vulkan: after a submitted build, an update in a later list runs", Describe(updated));
    rhi.DestroyBLAS(updatable);
    rhi.DestroyTLAS(tlas);
    rhi.DestroyBLAS(good);
    rhi.DestroyBLAS(good);  // a second destroy of the same handle does nothing
    device.DestroyBuffer(*noInput);
    device.DestroyBuffer(*input);
}

int RunVulkan() {
    const VulkanSurvey survey = SurveyVulkan();
    if (survey.devices.empty()) {
        Info("no Vulkan physical device");
        return kExitSkip;
    }
    const VulkanQualification q = QualifyVulkan(survey, 0);
    Check(q.qualified, "this machine's Vulkan device qualifies", q.Summary(survey));
    if (!q.qualified) return Finish();
    const VulkanDeviceRecord& record = survey.devices[*q.device];
    const std::vector<std::string> recordMissing = VulkanRayQueryMissing(record);
    Info("record: ray-query missing = " + (recordMissing.empty() ? std::string("none") : Joined(recordMissing)));
    Result<std::unique_ptr<VulkanDevice>> created = CreateQualifiedVulkanDevice(survey, q);
    Check(created.has_value(), "the qualified Vulkan device is created", Describe(created));
    if (!created) return Finish();
    VulkanDevice& device = **created;
    const RayQuerySupport support = QueryRayQuerySupport(device);
    Info("device: acceleration structures " + std::string(support.accelerationStructures ? "on" : "off") +
         ", ray queries " + (support.inlineRayQuery ? "on" : "off") + ", missing " + Joined(support.missing) +
         ", scratch alignment " + std::to_string(static_cast<uz::VulkanDevice&>(device.Rhi()).ScratchAlignment()));
    Check(support.missing == recordMissing && support.inlineRayQuery == recordMissing.empty(),
          "the device enabled exactly what its record exposes for inline ray queries");
    if (!support.inlineRayQuery) {
        Result<void> required = RequireInlineRayQuery(device);
        Check(!required && required.error().code == ErrorCode::GpuBackendUnavailable,
              "without inline ray queries the request fails before any work", Describe(required));
        return Finish();
    }
    Result<CapabilityReport> report = QueryCapabilities(device, AdmissionPolicy{});
    Check(report && report->rayQuery && report->rayTracing && report->rayQueryMissing.empty(),
          "the Vulkan capability query reports inline ray queries", Describe(report));

    RunRhiRefusals(device);
    (void)RunShared(device, "vulkan");
    const VulkanTeardown teardown = device.Shutdown(Clock::now() + Ms(10000));
    Check(teardown == VulkanTeardown::Destroyed, "after its work completed the Vulkan device is destroyed",
          std::string(VulkanTeardownName(teardown)));
    return Finish();
}

int RunDx12() {
    DeviceOptions options;
    options.backend = Backend::Dx12;
    Result<std::unique_ptr<IDevice>> created = CreateDevice(options);
    if (!created) {
        Info("no DX12 device: " + created.error().Describe());
        return kExitSkip;
    }
    IDevice& device = **created;
    const RayQuerySupport support = QueryRayQuerySupport(device);
    Info("dx12: ray queries " + std::string(support.inlineRayQuery ? "on" : "off") + ", missing " +
         Joined(support.missing));
    if (!support.inlineRayQuery) {
        Result<void> required = RequireInlineRayQuery(device);
        Check(!required && required.error().code == ErrorCode::GpuBackendUnavailable &&
                  !support.missing.empty(),
              "without DXR 1.1 the request fails before any work, naming what is missing", Describe(required));
        return Finish();
    }
    Result<CapabilityReport> report = QueryCapabilities(device, AdmissionPolicy{});
    Check(report && report->rayQuery && report->rayQueryMissing.empty(),
          "the DX12 capability query reports inline ray queries", Describe(report));
    (void)RunShared(device, "dx12");
    return Finish();
}

// ── Ray-cast fixtures (items 2.10, 2.12, 3.1, 3.3, 3.4) ──────────────────────

struct BackendRun {
    std::string backend;
    std::string adapter;
    std::string driver;
    std::unique_ptr<IDevice> device;
    ComputeKernel kernel;
    bool ready = false;
};

std::string JsonEscape(const std::string& text) {
    std::string out;
    for (const char c : text) {
        if (c == '"' || c == '\\') out += '\\';
        if (static_cast<unsigned char>(c) >= 0x20) out += c;
    }
    return out;
}

std::string DiffJson(const RayHitDiff& diff) {
    char deltas[96];
    std::snprintf(deltas, sizeof(deltas), "\"max_delta_t\":%.9g,\"max_delta_barycentric\":%.9g", diff.maxDeltaT,
                  diff.maxDeltaBarycentric);
    std::string json = "{\"differing_rays\":" + std::to_string(diff.differences.size()) +
                       ",\"hit\":" + std::to_string(diff.hit) + ",\"instance_id\":" + std::to_string(diff.instanceId) +
                       ",\"primitive_id\":" + std::to_string(diff.primitiveId) +
                       ",\"geometry_index\":" + std::to_string(diff.geometryIndex) +
                       ",\"instance_index\":" + std::to_string(diff.instanceIndex) +
                       ",\"barycentrics\":" + std::to_string(diff.barycentrics) + ",\"t\":" + std::to_string(diff.t) +
                       "," + deltas + ",\"differences\":[";
    for (size_t i = 0; i < diff.differences.size(); ++i) {
        json += (i ? "," : "") + std::string("{\"ray\":") + std::to_string(diff.differences[i].ray) + ",\"fields\":[";
        for (size_t f = 0; f < diff.differences[i].fields.size(); ++f) {
            json += (f ? ",\"" : "\"") + diff.differences[i].fields[f] + "\"";
        }
        json += "]}";
    }
    return json + "]}";
}

/// The records of the rays of `kinds`, in order.
std::vector<RayHit> OfKinds(const std::vector<RayHit>& hits, const RayCastFixture& fixture,
                            std::initializer_list<RayKind> kinds) {
    std::vector<RayHit> out;
    for (size_t i = 0; i < hits.size(); ++i) {
        if (std::find(kinds.begin(), kinds.end(), fixture.kinds[i]) != kinds.end()) out.push_back(hits[i]);
    }
    return out;
}

int RunFixtures(const fs::path& dir) {
    std::vector<BackendRun> runs;
    for (const Backend backend : {Backend::Dx12, Backend::Vulkan}) {
        BackendRun run;
        run.backend = std::string(BackendName(backend));
        DeviceOptions options;
        options.backend = backend;
        Result<std::unique_ptr<IDevice>> created = CreateDevice(options);
        if (!created) {
            Info(run.backend + ": no device: " + created.error().Describe());
            return kExitSkip;
        }
        run.device = std::move(*created);
        Result<CapabilityReport> report = QueryCapabilities(*run.device, AdmissionPolicy{});
        if (report) {
            run.adapter = report->adapter;
            run.driver = report->driver;
        }
        Result<void> required = RequireInlineRayQuery(*run.device);
        Check(required.has_value(), run.backend + ": inline ray queries are available", Describe(required));
        Result<std::vector<uint8_t>> bytecode = CompileRayCastKernel(run.device->NativeKernelTarget(), DxcPath());
        Result<ComputeKernel> kernel =
            bytecode ? run.device->CreateComputeKernel(*bytecode, "ray_cast") : Result<ComputeKernel>(Unexpected(bytecode.error()));
        Check(kernel.has_value(), run.backend + ": the ray-cast kernel is created", Describe(kernel));
        if (!required || !kernel) return Finish();
        run.kernel = *kernel;
        run.ready = true;
        runs.push_back(std::move(run));
    }

    std::string json = "{\"schema\":\"uzpainter/parity/ray-cast-raw/1\",\"backends\":[";
    for (size_t i = 0; i < runs.size(); ++i) {
        json += (i ? "," : "") + std::string("{\"backend\":\"") + runs[i].backend + "\",\"adapter\":\"" +
                JsonEscape(runs[i].adapter) + "\",\"driver\":\"" + JsonEscape(runs[i].driver) + "\"}";
    }
    json += "],\"tolerance\":1e-05,\"fixtures\":[";
    bool firstFixture = true;
    for (const RayCastFixture& fixture : RayCastFixtures()) {
        size_t triangles = 0;
        for (const RayMesh& mesh : fixture.scene.meshes) {
            for (const RayGeometry& g : mesh.geometries) {
                triangles += g.indices.empty() ? g.vertexCount / 3 : g.indices.size() / 3;
            }
        }
        const std::vector<RayHit> reference = RayCastReference(fixture.scene, fixture.rays);
        std::vector<std::vector<RayHit>> records;
        std::string perBackend;
        for (BackendRun& run : runs) {
            const Traced first = Trace(*run.device, run.kernel, fixture.scene, fixture.rays, run.backend + " " + fixture.id);
            const Traced second = Trace(*run.device, run.kernel, fixture.scene, fixture.rays,
                                        run.backend + " " + fixture.id + " again");
            if (!first.ok || !second.ok) return Finish();
            const bool repeatable =
                std::memcmp(first.hits.data(), second.hits.data(), first.hits.size() * sizeof(RayHit)) == 0;
            Check(repeatable, run.backend + " " + fixture.id + ": two builds and traces give byte-identical records");
            const RayHitDiff strict = DiffRayHits(OfKinds(first.hits, fixture, {RayKind::Interior, RayKind::Miss}),
                                                  OfKinds(reference, fixture, {RayKind::Interior, RayKind::Miss}),
                                                  kTolerance);
            Check(strict.Equal(), run.backend + " " + fixture.id + ": interior and miss rays equal the CPU reference",
                  Joined(strict.differing));
            // Edge and vertex rays: a hit at the reference distance, on any of the triangles there.
            size_t sharedRays = 0, sharedWrong = 0;
            for (size_t i = 0; i < fixture.rays.size(); ++i) {
                if (fixture.kinds[i] != RayKind::Edge && fixture.kinds[i] != RayKind::Vertex) continue;
                ++sharedRays;
                const RayHit& got = first.hits[i];
                const RayHit& want = reference[i];
                if (!got.hit || !want.hit || std::fabs(double{got.t} - double{want.t}) > kTolerance * std::max(1.0, double{want.t})) {
                    ++sharedWrong;
                    Info(run.backend + " " + fixture.id + ": shared ray " + std::to_string(i) + " got hit " +
                         std::to_string(got.hit) + " t " + std::to_string(got.t) + ", reference hit " +
                         std::to_string(want.hit) + " t " + std::to_string(want.t));
                }
            }
            Check(sharedWrong == 0, run.backend + " " + fixture.id + ": edge and vertex rays hit at the reference distance");
            const RayHitDiff all = DiffRayHits(first.hits, reference, kTolerance);
            perBackend += (perBackend.empty() ? "" : ",") + std::string("{\"backend\":\"") + run.backend +
                          "\",\"repeatable\":" + (repeatable ? "true" : "false") +
                          ",\"strict_differing\":" + std::to_string(strict.differences.size()) +
                          ",\"shared_rays\":" + std::to_string(sharedRays) +
                          ",\"shared_wrong\":" + std::to_string(sharedWrong) + ",\"versus_cpu\":" + DiffJson(all) + "}";
            records.push_back(first.hits);
        }
        const RayHitDiff cross = DiffRayHits(records[0], records[1], 0.0);
        Check(cross.Equal(), fixture.id + ": DX12 and Vulkan give the same records", Joined(cross.differing));
        std::string kinds;
        for (const RayKind kind : {RayKind::Interior, RayKind::Miss, RayKind::Edge, RayKind::Vertex, RayKind::Boundary,
                                   RayKind::Grazing}) {
            const size_t n = static_cast<size_t>(std::count(fixture.kinds.begin(), fixture.kinds.end(), kind));
            kinds += (kinds.empty() ? "" : ",") + std::string("\"") + std::string(RayKindName(kind)) + "\":" + std::to_string(n);
        }
        json += (firstFixture ? "" : ",") + std::string("{\"id\":\"") + fixture.id +
                "\",\"rays\":" + std::to_string(fixture.rays.size()) + ",\"triangles\":" + std::to_string(triangles) +
                ",\"instances\":" + std::to_string(fixture.scene.instances.size()) + ",\"kinds\":{" + kinds +
                "},\"runs\":[" + perBackend + "],\"cross_backend\":" + DiffJson(cross) + "}";
        firstFixture = false;
    }
    json += "]}";
    for (BackendRun& run : runs) run.device->DestroyComputeKernel(run.kernel);
    const fs::path out = dir / "ray-cast-raw.json";
    FILE* file = _wfopen(out.c_str(), L"wb");
    const bool written = file != nullptr && std::fwrite(json.data(), 1, json.size(), file) == json.size();
    const bool closed = file != nullptr && std::fclose(file) == 0;
    Check(written && closed, "the raw report is written", out.string());
    Info("raw report: " + out.string());
    return Finish();
}

}  // namespace

/// The ray-query cases (this file); -1 for any other mode.
int RunRayQueryCase(std::string_view mode, const fs::path& dir) {
    if (mode == "ray-query-reference") return RunReference();
    if (mode == "ray-query-mesh") return RunMesh();
    if (mode == "ray-cast-fixtures") return RunFixtures(dir);
    if (mode == "vulkan-ray-query") return RunVulkan();
    if (mode == "dx12-ray-query") return RunDx12();
    return -1;
}
