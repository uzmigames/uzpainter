// UzPainter's backend-neutral inline-ray-query layer (ray_query.h).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/ray_query.h"

#include "render/device.h"
#include "mesh/texturing_mesh.h"
#include "render/vulkan_backend.h"

#include "dx12_device.h"
#include "shader_compiler.h"
#include "vulkan_command_list.h"
#include "vulkan_device.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <utility>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kRayCastHlsl[] = {
#embed "shaders/ray_cast.hlsl"
};
#pragma clang diagnostic pop

static_assert(sizeof(CastRay) == 32, "CastRay is the 32-byte Ray of ray_cast.hlsl");
static_assert(sizeof(RayHit) == 32, "RayHit is the 32-byte Hit of ray_cast.hlsl");

constexpr uint32_t kRayRecordBytes = 32;
constexpr uint32_t kInstanceRecordBytes = 64;
constexpr uint32_t kRaysPerGroup = 64;
/// The most rays one dispatch traces: 65535 groups, the X group-count limit every DX12 device and
/// the Vulkan minimum guarantee.
constexpr uint64_t kMaxRays = uint64_t{65535} * kRaysPerGroup;

std::string Join(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) out += (out.empty() ? "" : ", ") + item;
    return out;
}

Unexpected Invalid(Backend backend, const std::string& why) {
    return Fail(ErrorCode::RequestFailed, backend, why);
}

uz::VulkanDevice& NativeVulkan(IDevice& device) { return static_cast<uz::VulkanDevice&>(device.Rhi()); }

/// A buffer of `bytes` (at least 4) in upload memory holding `data`, flushed for the GPU.
Result<uz::RHIBufferHandle> UploadBuffer(IDevice& device, std::span<const uint8_t> data, uz::RHIBufferUsage usage,
                                         uint32_t stride, const char* name) {
    uz::RHIBufferDesc desc;
    desc.sizeBytes = std::max<uint64_t>(data.size(), 4);
    desc.stride = stride;
    desc.usage = usage;
    desc.memory = uz::RHIMemoryType::Upload;
    desc.debugName = name;
    Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(desc);
    if (!buffer) return buffer;
    void* mapped = device.Rhi().MapBuffer(*buffer);
    if (!mapped) {
        device.DestroyBuffer(*buffer);
        return Fail(ErrorCode::ResourceCreationFailed, device.GetBackend(), std::string(name) + " is not mappable");
    }
    if (!data.empty()) std::memcpy(mapped, data.data(), data.size());
    device.Rhi().UnmapBuffer(*buffer);  // flushes non-coherent memory (UZP-MOD-013)
    return buffer;
}

void DestroyBuffers(IDevice& device, std::vector<uz::RHIBufferHandle>& buffers) {
    for (const uz::RHIBufferHandle buffer : buffers) device.DestroyBuffer(buffer);
    buffers.clear();
}

// ── CPU reference ──

struct Vec3 {
    double x, y, z;
};
Vec3 Sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 Cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
double Dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

Vec3 Position(const RayGeometry& geometry, uint32_t vertex) {
    float xyz[3];
    std::memcpy(xyz, geometry.vertices.data() + static_cast<size_t>(vertex) * geometry.vertexStride, sizeof(xyz));
    return {xyz[0], xyz[1], xyz[2]};
}

/// The inverse of the affine 3x4 `m` (row-major), as a 3x4; false when singular.
bool InvertAffine(const std::array<float, 12>& m, std::array<double, 12>& out) {
    const double a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], k = m[10];
    const double det = a * (e * k - f * h) - b * (d * k - f * g) + c * (d * h - e * g);
    if (det == 0.0) return false;
    const double inv[9] = {(e * k - f * h) / det, (c * h - b * k) / det, (b * f - c * e) / det,
                           (f * g - d * k) / det, (a * k - c * g) / det, (c * d - a * f) / det,
                           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det};
    const double t[3] = {m[3], m[7], m[11]};
    for (int r = 0; r < 3; ++r) {
        out[r * 4 + 0] = inv[r * 3 + 0];
        out[r * 4 + 1] = inv[r * 3 + 1];
        out[r * 4 + 2] = inv[r * 3 + 2];
        out[r * 4 + 3] = -(inv[r * 3 + 0] * t[0] + inv[r * 3 + 1] * t[1] + inv[r * 3 + 2] * t[2]);
    }
    return true;
}

std::optional<std::string> ValidateScene(const RaySceneDesc& desc) {
    if (desc.meshes.empty()) return "the scene has no mesh";
    if (desc.instances.empty()) return "the scene has no instance";
    for (size_t m = 0; m < desc.meshes.size(); ++m) {
        const RayMesh& mesh = desc.meshes[m];
        if (mesh.geometries.empty()) return "mesh " + std::to_string(m) + " has no geometry";
        for (size_t g = 0; g < mesh.geometries.size(); ++g) {
            const RayGeometry& geometry = mesh.geometries[g];
            const std::string where = "mesh " + std::to_string(m) + " geometry " + std::to_string(g) + ": ";
            if (geometry.vertexStride < 12 || geometry.vertexStride % 4 != 0) {
                return where + "vertex stride " + std::to_string(geometry.vertexStride) +
                       " is below 12 bytes or not a multiple of 4";
            }
            if (geometry.vertexCount == 0) return where + "no vertices";
            if (geometry.vertices.size() < uint64_t{geometry.vertexCount - 1} * geometry.vertexStride + 12) {
                return where + "fewer vertex bytes than vertexCount x stride";
            }
            if (geometry.indices.empty()) {
                if (geometry.vertexCount % 3 != 0) return where + "the vertex count is not a multiple of 3";
            } else {
                if (geometry.indices.size() % 3 != 0) return where + "the index count is not a multiple of 3";
                for (const uint32_t index : geometry.indices) {
                    if (index >= geometry.vertexCount) return where + "index " + std::to_string(index) + " is past the vertices";
                }
            }
        }
    }
    for (size_t i = 0; i < desc.instances.size(); ++i) {
        const RayInstance& instance = desc.instances[i];
        if (instance.mesh >= desc.meshes.size()) return "instance " + std::to_string(i) + " names an unknown mesh";
        if (instance.instanceId > 0xFFFFFFu) return "instance " + std::to_string(i) + ": the id exceeds 24 bits";
        for (const float value : instance.transform) {
            if (!std::isfinite(value)) return "instance " + std::to_string(i) + ": the transform is not finite";
        }
        std::array<double, 12> inverse{};
        if (!InvertAffine(instance.transform, inverse)) {
            return "instance " + std::to_string(i) + ": the transform is not invertible";
        }
        if ((instance.flags & ~kRayInstanceFlagMask) != 0 ||
            ((instance.flags & kRayInstanceForceOpaque) && (instance.flags & kRayInstanceForceNonOpaque))) {
            return "instance " + std::to_string(i) + ": flags outside the shared four, or opaque and non-opaque forced";
        }
    }
    return std::nullopt;
}

std::string Float(double value) {
    char buf[40];
    std::snprintf(buf, sizeof(buf), "%.9g", value);
    return buf;
}

}  // namespace

// ── Capability ───────────────────────────────────────────────────────────────

RayQuerySupport QueryRayQuerySupport(IDevice& device) {
    RayQuerySupport support;
    support.backend = device.GetBackend();
    if (support.backend == Backend::Vulkan) {
        uz::VulkanDevice& native = NativeVulkan(device);
        support.accelerationStructures = native.SupportsRayTracing();
        support.inlineRayQuery = native.SupportsInlineRayQuery();
        support.missing = native.RayQueryMissing();
        return support;
    }
    auto& dx12 = static_cast<Dx12Device&>(device);
    support.accelerationStructures = dx12.Native().SupportsRayTracing();
    support.inlineRayQuery = dx12.Native().SupportsInlineRayQuery();
    D3D12_FEATURE_DATA_D3D12_OPTIONS5 options5{};
    const bool haveOptions5 =
        SUCCEEDED(dx12.D3D12()->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS5, &options5, sizeof(options5)));
    if (!haveOptions5 || options5.RaytracingTier < D3D12_RAYTRACING_TIER_1_1) {
        support.missing.push_back("DXR Tier 1.1");
    }
    D3D12_FEATURE_DATA_SHADER_MODEL shaderModel{D3D_SHADER_MODEL_6_6};
    if (FAILED(dx12.D3D12()->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &shaderModel, sizeof(shaderModel))) ||
        shaderModel.HighestShaderModel < D3D_SHADER_MODEL_6_6) {
        support.missing.push_back("Shader Model 6.6");
    }
    if (!support.inlineRayQuery && support.missing.empty()) support.missing.push_back("inline ray queries (device)");
    return support;
}

Result<void> RequireInlineRayQuery(IDevice& device) {
    const RayQuerySupport support = QueryRayQuerySupport(device);
    if (support.inlineRayQuery) return {};
    return Fail(ErrorCode::GpuBackendUnavailable, support.backend,
                "inline ray queries are unavailable on " + device.AdapterName() + ": missing " +
                    Join(support.missing) + "; nothing was dispatched and nothing falls back");
}

// ── Scene ────────────────────────────────────────────────────────────────────

std::vector<uint8_t> PackPositions(std::span<const float> xyz, uint32_t stride) {
    if (stride < 12) return {};  // no room for a position; the scene check then refuses the geometry
    const size_t count = xyz.size() / 3;
    std::vector<uint8_t> bytes(count * stride, 0xA5);
    for (size_t i = 0; i < count; ++i) std::memcpy(bytes.data() + i * stride, xyz.data() + i * 3, 12);
    return bytes;
}

std::array<uint8_t, 64> PackRayInstance(const RayInstance& instance, uint32_t hitGroupOffset, uint64_t blasAddress) {
    std::array<uint8_t, 64> record{};
    std::memcpy(record.data(), instance.transform.data(), 48);
    const uint32_t idMask = (instance.instanceId & 0xFFFFFFu) | (uint32_t{instance.mask} << 24);
    const uint32_t offsetFlags = (hitGroupOffset & 0xFFFFFFu) | (uint32_t{instance.flags} << 24);
    std::memcpy(record.data() + 48, &idMask, 4);
    std::memcpy(record.data() + 52, &offsetFlags, 4);
    std::memcpy(record.data() + 56, &blasAddress, 8);
    return record;
}

Result<RayScene> BuildRayScene(IDevice& device, const RaySceneDesc& desc, Deadline deadline) {
    const Backend backend = device.GetBackend();
    if (std::optional<std::string> problem = ValidateScene(desc)) return Invalid(backend, *problem);
    if (Result<void> required = RequireInlineRayQuery(device); !required) return Unexpected(required.error());

    RayScene scene;
    const auto fail = [&](const Error& error) -> Unexpected {
        ReleaseRayScene(device, scene);
        return Unexpected(error);
    };
    const uz::RHIBufferUsage input = uz::RHIBufferUsage::AccelerationStructureBuildInput;
    for (size_t m = 0; m < desc.meshes.size(); ++m) {
        const RayMesh& mesh = desc.meshes[m];
        std::vector<uz::RHIRTGeometryDesc> geometries;
        for (const RayGeometry& geometry : mesh.geometries) {
            Result<uz::RHIBufferHandle> vertices = UploadBuffer(device, geometry.vertices, input, 0, "ray_vertices");
            if (!vertices) return fail(vertices.error());
            scene.buffers.push_back(*vertices);
            uz::RHIRTGeometryDesc g;
            g.vertexBuffer = *vertices;
            g.vertexCount = geometry.vertexCount;
            g.vertexStride = geometry.vertexStride;
            g.vertexFormat = uz::RHIFormat::RGB32Float;
            g.isOpaque = geometry.opaque;
            if (!geometry.indices.empty()) {
                const auto* bytes = reinterpret_cast<const uint8_t*>(geometry.indices.data());
                Result<uz::RHIBufferHandle> indices =
                    UploadBuffer(device, {bytes, geometry.indices.size() * 4}, input, 0, "ray_indices");
                if (!indices) return fail(indices.error());
                scene.buffers.push_back(*indices);
                g.indexBuffer = *indices;
                g.indexCount = static_cast<uint32_t>(geometry.indices.size());
                g.indexFormat = uz::RHIIndexFormat::Uint32;
            }
            geometries.push_back(g);
        }
        uz::RHIBLASDesc blasDesc;
        blasDesc.geometries = geometries.data();
        blasDesc.geometryCount = static_cast<uint32_t>(geometries.size());
        blasDesc.buildFlags = uz::RHIASBuildFlags::PreferFastTrace;
        blasDesc.debugName = "ray_blas";
        const uz::RHIBLASHandle blas = device.Rhi().CreateBLAS(blasDesc);
        if (!blas.IsValid()) {
            return fail(Fail(ErrorCode::ResourceCreationFailed, backend,
                             "CreateBLAS refused mesh " + std::to_string(m) + " (the render core log has the cause)")
                            .error());
        }
        scene.blases.push_back(blas);
    }

    std::vector<uint8_t> records;
    records.reserve(desc.instances.size() * kInstanceRecordBytes);
    for (const RayInstance& instance : desc.instances) {
        const uint64_t address = device.Rhi().GetBLASGPUAddress(scene.blases[instance.mesh]);
        if (address == 0) {
            return fail(Fail(ErrorCode::ResourceCreationFailed, backend, "a BLAS has no device address").error());
        }
        const std::array<uint8_t, 64> record = PackRayInstance(instance, 0, address);
        records.insert(records.end(), record.begin(), record.end());
    }
    Result<uz::RHIBufferHandle> instances = UploadBuffer(device, records, input, 0, "ray_instances");
    if (!instances) return fail(instances.error());
    scene.buffers.push_back(*instances);
    scene.instanceCount = static_cast<uint32_t>(desc.instances.size());

    uz::RHITLASDesc tlasDesc;
    tlasDesc.maxInstanceCount = scene.instanceCount;
    tlasDesc.buildFlags = uz::RHIASBuildFlags::PreferFastTrace;
    tlasDesc.debugName = "ray_tlas";
    scene.tlas = device.Rhi().CreateTLAS(tlasDesc);
    if (!scene.tlas.IsValid()) {
        return fail(Fail(ErrorCode::ResourceCreationFailed, backend,
                         "CreateTLAS refused the scene (the render core log has the cause)")
                        .error());
    }

    const uz::RHIBufferHandle instanceBuffer = *instances;
    // A refused build makes the Vulkan queue refuse the whole list (vulkan_backend.cpp).
    Result<uint64_t> fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        for (const uz::RHIBLASHandle blas : scene.blases) cmd.BuildBLAS(blas, uz::RHIBufferHandle::Invalid());
        cmd.UAVBarrierAS();
        cmd.BuildTLAS(scene.tlas, instanceBuffer, scene.instanceCount, uz::RHIBufferHandle::Invalid());
        cmd.UAVBarrierAS();
    });
    if (!fence) return fail(fence.error());
    scene.buildFence = *fence;
    const WaitResult wait = device.Queue().Wait(*fence, deadline);
    if (wait.status != WaitStatus::Signaled) return Unexpected(device.WaitFailure(wait));  // the failed device keeps them
    return scene;
}

void ReleaseRayScene(IDevice& device, RayScene& scene) {
    if (device.CheckRemoved()) return;  // a failed device keeps what its work may still use
    if (scene.tlas.IsValid()) device.Rhi().DestroyTLAS(scene.tlas);
    for (const uz::RHIBLASHandle blas : scene.blases) device.Rhi().DestroyBLAS(blas);
    DestroyBuffers(device, scene.buffers);
    scene.tlas = uz::RHITLASHandle::Invalid();
    scene.blases.clear();
}

// ── Ray cast ─────────────────────────────────────────────────────────────────

std::string_view RayCastHlsl() { return {kRayCastHlsl, sizeof(kRayCastHlsl)}; }

Result<std::vector<uint8_t>> CompileRayCastKernel(KernelTarget target, const std::filesystem::path& dxcompiler) {
    uz::ShaderCompiler compiler;
    if (!compiler.Init(dxcompiler.string())) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt, "DXC failed to load from " + dxcompiler.string());
    }
    const std::string source(RayCastHlsl());
    uz::ShaderCompileDesc desc;
    desc.source = source;
    desc.sourceName = "ray_cast.hlsl";
    desc.stage = uz::ShaderStageCompile::Compute;
    desc.model = uz::ShaderModelCompile::SM6_6;
    desc.output = target == KernelTarget::Spirv ? uz::ShaderOutputFormat::SPIRV : uz::ShaderOutputFormat::DXIL;
    desc.enableRayQuery = true;  // SPIR-V: -fspv-extension=SPV_KHR_ray_query (UZP-MOD-006)
    uz::ShaderCompileResult result = compiler.Compile(desc);
    if (!result.success || result.bytecode.empty()) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    "ray_cast.hlsl to " + std::string(KernelTargetName(target)) + ": " +
                        (result.errors.empty() ? "no bytecode" : result.errors));
    }
    return std::move(result.bytecode);
}

std::vector<std::string> SpirvExtensions(std::span<const uint8_t> spirv) {
    std::vector<std::string> out;
    std::vector<uint32_t> words(spirv.size() / 4);
    if (!words.empty()) std::memcpy(words.data(), spirv.data(), words.size() * 4);
    constexpr uint32_t kOpExtension = 10;
    for (size_t i = 5; i < words.size();) {
        const uint32_t length = words[i] >> 16;
        if (length == 0 || i + length > words.size()) break;
        if ((words[i] & 0xFFFF) == kOpExtension && length >= 2) {
            const char* text = reinterpret_cast<const char*>(&words[i + 1]);
            out.emplace_back(text, strnlen(text, (length - 1) * 4));
        }
        i += length;
    }
    return out;
}

Result<std::vector<RayHit>> CastRays(IDevice& device, const RayScene& scene, const ComputeKernel& kernel,
                                     std::span<const CastRay> rays, Deadline deadline) {
    const Backend backend = device.GetBackend();
    if (Result<void> required = RequireInlineRayQuery(device); !required) return Unexpected(required.error());
    if (!scene.tlas.IsValid()) return Invalid(backend, "the scene has no TLAS");
    if (rays.empty()) return std::vector<RayHit>{};
    if (rays.size() > kMaxRays) {
        return Invalid(backend, std::to_string(rays.size()) + " rays exceed the " + std::to_string(kMaxRays) +
                                    " one dispatch traces");
    }
    const uint64_t bytes = uint64_t{rays.size()} * kRayRecordBytes;

    std::vector<uz::RHIBufferHandle> buffers;
    const auto release = [&] { DestroyBuffers(device, buffers); };
    Result<uz::RHIBufferHandle> rayBuffer =
        UploadBuffer(device, {reinterpret_cast<const uint8_t*>(rays.data()), bytes}, uz::RHIBufferUsage::StructuredBuffer,
                     kRayRecordBytes, "ray_cast_rays");
    if (!rayBuffer) return Unexpected(rayBuffer.error());
    buffers.push_back(*rayBuffer);
    uz::RHIBufferDesc hitsDesc;
    hitsDesc.sizeBytes = bytes;
    hitsDesc.stride = kRayRecordBytes;
    hitsDesc.usage = uz::RHIBufferUsage::UnorderedAccess | uz::RHIBufferUsage::StructuredBuffer |
                     uz::RHIBufferUsage::CopySrc;
    hitsDesc.memory = uz::RHIMemoryType::Default;
    hitsDesc.debugName = "ray_cast_hits";
    Result<uz::RHIBufferHandle> hits = device.CreateBuffer(hitsDesc);
    if (!hits) {
        release();
        return Unexpected(hits.error());
    }
    buffers.push_back(*hits);
    uz::RHIBufferDesc readbackDesc;
    readbackDesc.sizeBytes = bytes;
    readbackDesc.usage = uz::RHIBufferUsage::CopyDst;
    readbackDesc.memory = uz::RHIMemoryType::Readback;
    readbackDesc.debugName = "ray_cast_readback";
    Result<uz::RHIBufferHandle> readback = device.CreateBuffer(readbackDesc);
    if (!readback) {
        release();
        return Unexpected(readback.error());
    }
    buffers.push_back(*readback);

    const auto count = static_cast<uint32_t>(rays.size());
    Result<uint64_t> fence = device.Queue().Submit([&](uz::IRHICommandList& cmd) {
        using State = uz::RHIResourceState;
        const uz::RHIBarrierDesc toUav{uz::RHITextureHandle::Invalid(), *hits, State::Common, State::UnorderedAccess};
        cmd.ResourceBarrier(&toUav, 1);
        cmd.SetPipeline(kernel.pipeline);
        if (backend == Backend::Vulkan) {
            auto& vk = static_cast<uz::VulkanCommandList&>(cmd);
            vk.SetComputeStorageBuffer(0, *rayBuffer);
            vk.SetComputeStorageBuffer(1, *hits);
            vk.SetComputeAccelerationStructure(scene.tlas);
            const uint32_t constants[4] = {count, 0, 1, 0};
            for (uint32_t i = 0; i < 4; ++i) vk.SetDescriptorIndex(i, constants[i]);  // push constants
        } else {
            const uint32_t constants[4] = {count, device.Rhi().GetBufferSRVIndex(*rayBuffer),
                                           device.Rhi().GetBufferUAVIndex(*hits),
                                           device.Rhi().GetTLASSRVIndex(scene.tlas)};
            cmd.SetRootConstants(kRootConstantsParam, constants, 4);
        }
        cmd.Dispatch((count + kRaysPerGroup - 1) / kRaysPerGroup, 1, 1);
        const uz::RHIBarrierDesc toCopy{uz::RHITextureHandle::Invalid(), *hits, State::UnorderedAccess, State::CopySrc};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyBuffer(*hits, 0, *readback, 0, bytes);
    });
    if (!fence) {
        release();
        return Unexpected(fence.error());
    }
    const WaitResult wait = device.Queue().Wait(*fence, deadline);
    if (wait.status != WaitStatus::Signaled) return Unexpected(device.WaitFailure(wait));  // the failed device keeps them
    const void* mapped = device.MapReadback(*readback);
    if (!mapped) {
        release();
        return Fail(ErrorCode::RequestFailed, backend, "the hit readback buffer is not host-visible");
    }
    std::vector<RayHit> out(rays.size());
    std::memcpy(out.data(), mapped, bytes);
    release();
    return out;
}

std::vector<RayHit> RayCastReference(const RaySceneDesc& desc, std::span<const CastRay> rays) {
    std::vector<RayHit> out(rays.size());
    for (size_t r = 0; r < rays.size(); ++r) {
        const CastRay& ray = rays[r];
        double best = std::numeric_limits<double>::infinity();
        RayHit hit;
        for (size_t i = 0; i < desc.instances.size(); ++i) {
            const RayInstance& instance = desc.instances[i];
            if (instance.mask == 0 || instance.mesh >= desc.meshes.size()) continue;
            std::array<double, 12> inv{};
            if (!InvertAffine(instance.transform, inv)) continue;
            const Vec3 o{inv[0] * ray.origin[0] + inv[1] * ray.origin[1] + inv[2] * ray.origin[2] + inv[3],
                         inv[4] * ray.origin[0] + inv[5] * ray.origin[1] + inv[6] * ray.origin[2] + inv[7],
                         inv[8] * ray.origin[0] + inv[9] * ray.origin[1] + inv[10] * ray.origin[2] + inv[11]};
            const Vec3 d{inv[0] * ray.direction[0] + inv[1] * ray.direction[1] + inv[2] * ray.direction[2],
                         inv[4] * ray.direction[0] + inv[5] * ray.direction[1] + inv[6] * ray.direction[2],
                         inv[8] * ray.direction[0] + inv[9] * ray.direction[1] + inv[10] * ray.direction[2]};
            const RayMesh& mesh = desc.meshes[instance.mesh];
            for (size_t g = 0; g < mesh.geometries.size(); ++g) {
                const RayGeometry& geometry = mesh.geometries[g];
                bool opaque = geometry.opaque;
                if (instance.flags & kRayInstanceForceOpaque) opaque = true;
                if (instance.flags & kRayInstanceForceNonOpaque) opaque = false;
                const size_t triangles =
                    geometry.indices.empty() ? geometry.vertexCount / 3 : geometry.indices.size() / 3;
                for (size_t p = 0; p < triangles; ++p) {
                    if (!opaque && (p & 1) != 0) continue;  // the kernel's non-opaque rule
                    const auto vertex = [&](size_t k) {
                        return geometry.indices.empty() ? static_cast<uint32_t>(p * 3 + k) : geometry.indices[p * 3 + k];
                    };
                    const Vec3 v0 = Position(geometry, vertex(0));
                    const Vec3 e1 = Sub(Position(geometry, vertex(1)), v0);
                    const Vec3 e2 = Sub(Position(geometry, vertex(2)), v0);
                    const Vec3 pv = Cross(d, e2);
                    const double det = Dot(e1, pv);
                    if (det == 0.0) continue;
                    const Vec3 tv = Sub(o, v0);
                    const double u = Dot(tv, pv) / det;
                    const Vec3 qv = Cross(tv, e1);
                    const double v = Dot(d, qv) / det;
                    const double t = Dot(e2, qv) / det;
                    if (u < 0.0 || v < 0.0 || u + v > 1.0) continue;
                    if (t < ray.tMin || t > ray.tMax || t >= best) continue;
                    best = t;
                    hit.hit = 1;
                    hit.instanceId = instance.instanceId & 0xFFFFFFu;
                    hit.primitiveId = static_cast<uint32_t>(p);
                    hit.geometryIndex = static_cast<uint32_t>(g);
                    hit.u = static_cast<float>(u);
                    hit.v = static_cast<float>(v);
                    hit.t = static_cast<float>(t);
                    hit.instanceIndex = static_cast<uint32_t>(i);
                }
            }
        }
        out[r] = hit;
    }
    return out;
}

RayHitDiff DiffRayHits(std::span<const RayHit> a, std::span<const RayHit> b, double tolerance) {
    RayHitDiff diff;
    diff.rays = std::max(a.size(), b.size());
    if (a.size() != b.size()) {
        diff.differing.push_back("record counts differ: " + std::to_string(a.size()) + " vs " + std::to_string(b.size()));
    }
    const size_t n = std::min(a.size(), b.size());
    for (size_t i = 0; i < n; ++i) {
        const RayHit& x = a[i];
        const RayHit& y = b[i];
        std::string line;
        const auto field = [&](bool differs, size_t& counter, const std::string& what) {
            if (!differs) return;
            ++counter;
            line += (line.empty() ? "" : "; ") + what;
        };
        std::vector<std::string> fields;
        const auto named = [&](bool differs, const char* name) {
            if (differs) fields.emplace_back(name);
            return differs;
        };
        field(named(x.hit != y.hit, "hit"), diff.hit, "hit " + std::to_string(x.hit) + " vs " + std::to_string(y.hit));
        field(named(x.instanceId != y.instanceId, "instance_id"), diff.instanceId,
              "instance id " + std::to_string(x.instanceId) + " vs " + std::to_string(y.instanceId));
        field(named(x.primitiveId != y.primitiveId, "primitive_id"), diff.primitiveId,
              "primitive " + std::to_string(x.primitiveId) + " vs " + std::to_string(y.primitiveId));
        field(named(x.geometryIndex != y.geometryIndex, "geometry_index"), diff.geometryIndex,
              "geometry " + std::to_string(x.geometryIndex) + " vs " + std::to_string(y.geometryIndex));
        field(named(x.instanceIndex != y.instanceIndex, "instance_index"), diff.instanceIndex,
              "instance index " + std::to_string(x.instanceIndex) + " vs " + std::to_string(y.instanceIndex));
        if (x.hit == 1 && y.hit == 1) {
            const double du = std::fabs(double{x.u} - double{y.u});
            const double dv = std::fabs(double{x.v} - double{y.v});
            const double dt = std::fabs(double{x.t} - double{y.t});
            diff.maxDeltaBarycentric = std::max({diff.maxDeltaBarycentric, du, dv});
            diff.maxDeltaT = std::max(diff.maxDeltaT, dt);
            // A non-finite value never equals another.
            const bool finite = std::isfinite(x.u) && std::isfinite(x.v) && std::isfinite(x.t) &&
                                std::isfinite(y.u) && std::isfinite(y.v) && std::isfinite(y.t);
            field(named(!finite || !(du <= tolerance) || !(dv <= tolerance), "barycentrics"), diff.barycentrics,
                  "barycentrics (" + Float(x.u) + ", " + Float(x.v) + ") vs (" + Float(y.u) + ", " + Float(y.v) + ")");
            field(named(!finite || !(dt <= tolerance * std::max(1.0, std::fabs(double{y.t}))), "t"), diff.t,
                  "t " + Float(x.t) + " vs " + Float(y.t));
        }
        if (!line.empty()) {
            diff.differing.push_back("ray " + std::to_string(i) + ": " + line);
            diff.differences.push_back({i, std::move(fields)});
        }
    }
    return diff;
}

// ── Ray-cast fixtures (item 2.10) ────────────────────────────────────────────

namespace {

struct FixtureBuilder {
    RayCastFixture fixture;

    void Ray(RayKind kind, std::array<float, 3> origin, std::array<float, 3> direction, float tMin = 0,
             float tMax = 1000) {
        fixture.rays.push_back(CastRay{origin, tMin, direction, tMax});
        fixture.kinds.push_back(kind);
    }
    /// A ray from `origin` towards `target`, with the direction `target - origin` (t = 1 there).
    void Towards(RayKind kind, std::array<float, 3> origin, std::array<float, 3> target) {
        Ray(kind, origin, {target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]});
    }
};

RayGeometry Geometry(const std::vector<float>& xyz, uint32_t stride, std::vector<uint32_t> indices, bool opaque) {
    RayGeometry geometry;
    geometry.vertexStride = stride;
    geometry.vertexCount = static_cast<uint32_t>(xyz.size() / 3);
    geometry.vertices = PackPositions(xyz, stride);
    geometry.indices = std::move(indices);
    geometry.opaque = opaque;
    return geometry;
}

RayInstance Translated(float x, float y, float z, uint32_t id, uint8_t flags = 0, uint8_t mask = 0xFF) {
    RayInstance instance;
    instance.transform = {1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z};
    instance.instanceId = id;
    instance.flags = flags;
    instance.mask = mask;
    return instance;
}

/// A 4 x 4 grid of unit cells on z = 0 over [0, 4]^2, 16-byte stride, each cell split along its
/// diagonal from (i, j) to (i + 1, j + 1).
RayCastFixture PlaneFixture() {
    FixtureBuilder b;
    b.fixture.id = "plane";
    std::vector<float> xyz;
    for (int j = 0; j <= 4; ++j) {
        for (int i = 0; i <= 4; ++i) xyz.insert(xyz.end(), {float(i), float(j), 0});
    }
    std::vector<uint32_t> indices;
    for (uint32_t j = 0; j < 4; ++j) {
        for (uint32_t i = 0; i < 4; ++i) {
            const uint32_t a = j * 5 + i, c = a + 6;
            indices.insert(indices.end(), {a, a + 1, c, a, c, a + 5});
        }
    }
    b.fixture.scene.meshes.push_back({{Geometry(xyz, 16, indices, true)}});
    b.fixture.scene.instances = {Translated(0, 0, 0, 1)};
    for (int j = 0; j < 4; ++j) {
        for (int i = 0; i < 4; ++i) {
            b.Ray(RayKind::Interior, {i + 0.7f, j + 0.2f, 1}, {0, 0, -1});   // below the diagonal
            b.Ray(RayKind::Interior, {i + 0.15f, j + 0.65f, 1}, {0, 0, -1});  // above it
        }
    }
    b.Ray(RayKind::Interior, {0.3f, 0.1f, 2}, {0.25f, 0.125f, -1});
    b.Ray(RayKind::Interior, {3.6f, 2.2f, -2}, {-0.0625f, 0.25f, 1});  // from below
    b.Ray(RayKind::Miss, {5, 5, 1}, {0, 0, -1});
    b.Ray(RayKind::Miss, {-1, 2, 1}, {0, 0, -1});
    b.Ray(RayKind::Miss, {2.3f, 4.5f, 1}, {0, 0, -1});
    b.Ray(RayKind::Miss, {2.3f, 1.7f, 1}, {0, 0, 1});         // pointing away
    b.Ray(RayKind::Miss, {2.3f, 1.7f, 1}, {0, 0, -1}, 0, 0.5f);  // tMax before the plane
    b.Ray(RayKind::Edge, {1, 0.5f, 1}, {0, 0, -1});            // shared vertical edge
    b.Ray(RayKind::Edge, {2.5f, 2, 1}, {0, 0, -1});            // shared horizontal edge
    b.Ray(RayKind::Edge, {0.5f, 0.5f, 1}, {0, 0, -1});         // cell diagonal
    b.Ray(RayKind::Boundary, {0, 1.5f, 1}, {0, 0, -1});        // border edge
    b.Ray(RayKind::Vertex, {1, 1, 1}, {0, 0, -1});
    b.Ray(RayKind::Vertex, {2, 3, 1}, {0, 0, -1});
    b.Ray(RayKind::Boundary, {0, 0, 1}, {0, 0, -1});  // border corners
    b.Ray(RayKind::Boundary, {4, 4, 1}, {0, 0, -1});
    b.Ray(RayKind::Grazing, {-1, 1.7f, 0.001f}, {1, 0, -0.0004f});  // meets z = 0 at x = 1.5
    b.Ray(RayKind::Grazing, {-1, 2.6f, 0.0001f}, {1, 0.001f, -0.00002f});
    b.Ray(RayKind::Grazing, {-1, 2.5f, 0}, {1, 0, 0});  // in the plane
    return b.fixture;
}

/// A UV sphere of radius 1 at the origin (12 rings, 16 segments, single pole vertices), 32-byte
/// stride, and one instance translated to (10, 0, 0).
RayCastFixture SphereFixture() {
    constexpr int kRings = 12, kSegments = 16;
    constexpr double kPi = 3.14159265358979323846;
    FixtureBuilder b;
    b.fixture.id = "sphere";
    std::vector<float> xyz = {0, 0, 1};
    for (int r = 1; r < kRings; ++r) {
        const double theta = kPi * r / kRings;
        for (int s = 0; s < kSegments; ++s) {
            const double phi = 2 * kPi * s / kSegments;
            xyz.insert(xyz.end(), {float(std::sin(theta) * std::cos(phi)), float(std::sin(theta) * std::sin(phi)),
                                   float(std::cos(theta))});
        }
    }
    xyz.insert(xyz.end(), {0, 0, -1});
    const auto ring = [](int r, int s) { return uint32_t(1 + (r - 1) * kSegments + (s % kSegments)); };
    const uint32_t south = uint32_t(1 + (kRings - 1) * kSegments);
    std::vector<uint32_t> indices;
    for (int s = 0; s < kSegments; ++s) indices.insert(indices.end(), {0, ring(1, s), ring(1, s + 1)});
    for (int r = 1; r < kRings - 1; ++r) {
        for (int s = 0; s < kSegments; ++s) {
            indices.insert(indices.end(), {ring(r, s), ring(r + 1, s), ring(r + 1, s + 1)});
            indices.insert(indices.end(), {ring(r, s), ring(r + 1, s + 1), ring(r, s + 1)});
        }
    }
    for (int s = 0; s < kSegments; ++s) indices.insert(indices.end(), {ring(kRings - 1, s), south, ring(kRings - 1, s + 1)});
    b.fixture.scene.meshes.push_back({{Geometry(xyz, 32, indices, true)}});
    b.fixture.scene.instances = {Translated(0, 0, 0, 11), Translated(10, 0, 0, 12)};
    // Towards the centre from directions off every vertex, edge and pole.
    const std::array<std::array<float, 3>, 8> dirs = {{{0.6123f, 0.2171f, 0.7604f},
                                                       {-0.4417f, 0.8113f, 0.3829f},
                                                       {0.1373f, -0.9214f, -0.3637f},
                                                       {-0.7731f, -0.3049f, 0.5561f},
                                                       {0.9037f, 0.1291f, -0.4083f},
                                                       {-0.2389f, 0.4471f, -0.8622f},
                                                       {0.3313f, 0.6619f, 0.6724f},
                                                       {-0.5512f, -0.7343f, -0.3961f}}};
    for (const auto& d : dirs) {
        b.Towards(RayKind::Interior, {3 * d[0], 3 * d[1], 3 * d[2]}, {0, 0, 0});
        b.Towards(RayKind::Interior, {10 + 3 * d[0], 3 * d[1], 3 * d[2]}, {10, 0, 0});
        b.Ray(RayKind::Interior, {0, 0, 0}, d);  // from inside: the inner faces
    }
    b.Ray(RayKind::Miss, {-3, 1.5f, 0.1f}, {1, 0, 0});
    b.Ray(RayKind::Miss, {5, 0, 0}, {0, 0, 1});
    b.Ray(RayKind::Vertex, {0, 0, 3}, {0, 0, -1});  // the north pole
    b.Ray(RayKind::Vertex, {0, 0, -3}, {0, 0, 1});  // the south pole
    b.Ray(RayKind::Grazing, {-3, 0.97f, 0.05f}, {1, 0, 0});
    b.Ray(RayKind::Grazing, {-3, 0.0f, 0.995f}, {1, 0, 0});
    b.Ray(RayKind::Grazing, {7, 0.999f, 0.01f}, {1, 0, 0});
    return b.fixture;
}

/// A cube of half-size 1 at the origin with 0.25 bevels (6 inset faces, 12 edge quads, 8 corner
/// triangles, 44 triangles over 24 shared vertices), 12-byte stride.
RayCastFixture BevelledCubeFixture() {
    constexpr float kIn = 0.75f;
    FixtureBuilder b;
    b.fixture.id = "bevelled-cube";
    std::vector<float> xyz;
    // Face corner (axis a, sign s, corner signs u, v of the other two axes in order).
    const auto corner = [&](int a, int s, int u, int v) {
        std::array<float, 3> p{};
        const int o1 = (a + 1) % 3, o2 = (a + 2) % 3;
        p[a] = float(s);
        p[o1] = kIn * u;
        p[o2] = kIn * v;
        for (size_t i = 0; i < xyz.size(); i += 3) {
            if (xyz[i] == p[0] && xyz[i + 1] == p[1] && xyz[i + 2] == p[2]) return uint32_t(i / 3);
        }
        xyz.insert(xyz.end(), p.begin(), p.end());
        return uint32_t(xyz.size() / 3 - 1);
    };
    const auto at = [&](int a, int s, std::array<int, 3> signs) {
        // The corner of face (a, s) in the octant of `signs` (the face axis's sign is s).
        return corner(a, s, signs[(a + 1) % 3], signs[(a + 2) % 3]);
    };
    std::vector<uint32_t> indices;
    const auto quad = [&](uint32_t p, uint32_t q, uint32_t r, uint32_t t) {
        indices.insert(indices.end(), {p, q, r, p, r, t});
    };
    for (int a = 0; a < 3; ++a) {
        for (int s : {-1, 1}) quad(corner(a, s, -1, -1), corner(a, s, 1, -1), corner(a, s, 1, 1), corner(a, s, -1, 1));
    }
    for (int a = 0; a < 3; ++a) {
        const int c = (a + 1) % 3, w = (a + 2) % 3;  // edge between faces a and c, along axis w
        for (int sa : {-1, 1}) {
            for (int sc : {-1, 1}) {
                std::array<int, 3> lo{}, hi{};
                lo[a] = hi[a] = sa;
                lo[c] = hi[c] = sc;
                lo[w] = -1;
                hi[w] = 1;
                quad(at(a, sa, lo), at(a, sa, hi), at(c, sc, hi), at(c, sc, lo));
            }
        }
    }
    for (int sx : {-1, 1}) {
        for (int sy : {-1, 1}) {
            for (int sz : {-1, 1}) {
                const std::array<int, 3> o = {sx, sy, sz};
                indices.insert(indices.end(), {at(0, sx, o), at(1, sy, o), at(2, sz, o)});
            }
        }
    }
    b.fixture.scene.meshes.push_back({{Geometry(xyz, 12, indices, true)}});
    b.fixture.scene.instances = {Translated(0, 0, 0, 21)};
    b.Ray(RayKind::Interior, {3, 0.1f, 0.2f}, {-1, 0, 0});
    b.Ray(RayKind::Interior, {0.15f, -3, -0.35f}, {0, 1, 0});
    b.Ray(RayKind::Interior, {-0.4f, 0.3f, 3}, {0, 0, -1});
    b.Ray(RayKind::Interior, {3, 3, 0.1f}, {-1, -1, 0});        // the +x+y bevel
    b.Ray(RayKind::Interior, {-3, 0.3f, -3}, {1, 0, 1});        // the -x-z bevel
    b.Ray(RayKind::Interior, {3, 3.05f, 2.95f}, {-1, -1, -1});  // the +x+y+z corner triangle
    b.Ray(RayKind::Interior, {0.05f, 0.02f, 0.01f}, {0.3f, 0.9f, 0.1f});  // from inside
    b.Ray(RayKind::Miss, {3, 1.5f, 1.5f}, {-1, 0, 0});
    b.Ray(RayKind::Miss, {3, 3, 3}, {1, 1, 1});
    b.Ray(RayKind::Edge, {3, 0, kIn}, {-1, 0, 0});   // face +x / bevel edge
    b.Ray(RayKind::Edge, {3, kIn, 0.3f}, {-1, 0, 0}); // face +x / bevel +x+y border
    b.Ray(RayKind::Vertex, {3, kIn, kIn}, {-1, 0, 0});
    b.Ray(RayKind::Vertex, {-kIn, -3, kIn}, {0, 1, 0});
    b.Ray(RayKind::Grazing, {3, 1.0f, 0.3f}, {-1, 0.00001f, 0});
    return b.fixture;
}

/// An opaque/non-opaque pair: a non-opaque quad at z = 0 (geometry 0) over an opaque quad at
/// z = -1 (geometry 1), instanced plain, forced opaque, forced non-opaque and with mask 0.
RayCastFixture OpacityFixture() {
    FixtureBuilder b;
    b.fixture.id = "opacity-pair";
    const std::vector<float> front = {0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0};
    const std::vector<float> back = {0, 0, -1, 1, 0, -1, 1, 1, -1, 0, 1, -1};
    const std::vector<uint32_t> quad = {0, 1, 2, 0, 2, 3};
    b.fixture.scene.meshes.push_back({{Geometry(front, 12, quad, false), Geometry(back, 12, quad, true)}});
    b.fixture.scene.meshes.push_back({{Geometry(back, 20, quad, true)}});
    b.fixture.scene.instances = {Translated(0, 0, 0, 31), Translated(2, 0, 0, 32, kRayInstanceForceOpaque),
                                 Translated(4, 0, 0, 33, kRayInstanceForceNonOpaque), Translated(6, 0, 0, 34, 0, 0)};
    b.fixture.scene.instances[2].mesh = 1;
    for (const float x : {0.f, 2.f, 4.f, 6.f}) {
        // Instance 2 forces its opaque quad non-opaque: the odd triangle is passed, nothing is behind.
        b.Ray(x == 6 ? RayKind::Miss : RayKind::Interior, {x + 0.75f, 0.25f, 1}, {0, 0, -1});  // even triangle
        b.Ray(x >= 4 ? RayKind::Miss : RayKind::Interior, {x + 0.25f, 0.75f, 1}, {0, 0, -1});  // odd triangle
    }
    b.Ray(RayKind::Interior, {0.6f, 0.3f, -3}, {0, 0, 1});  // from below: the opaque back first
    return b.fixture;
}

}  // namespace

std::string_view RayKindName(RayKind kind) {
    switch (kind) {
        case RayKind::Interior: return "interior";
        case RayKind::Miss: return "miss";
        case RayKind::Edge: return "edge";
        case RayKind::Vertex: return "vertex";
        case RayKind::Boundary: return "boundary";
        case RayKind::Grazing: return "grazing";
    }
    return "unknown";
}

std::vector<RayCastFixture> RayCastFixtures() {
    return {PlaneFixture(), SphereFixture(), BevelledCubeFixture(), OpacityFixture()};
}

RaySceneDesc RaySceneFromMesh(const mesh::TexturingMesh& source, std::span<const uint32_t> nonOpaqueMaterials) {
    RaySceneDesc desc;
    for (size_t o = 0; o < source.objects.size(); ++o) {
        const mesh::Object& object = source.objects[o];
        // One geometry per material the object's triangles use, in material order.
        std::vector<uint32_t> materials;
        for (const mesh::Triangle& triangle : object.triangles) {
            const uint32_t material = source.corners[triangle.corners[0]].material;
            if (std::find(materials.begin(), materials.end(), material) == materials.end()) {
                materials.push_back(material);
            }
        }
        std::sort(materials.begin(), materials.end());
        RayMesh rayMesh;
        for (const uint32_t material : materials) {
            std::vector<float> xyz;
            std::vector<uint32_t> indices;
            std::vector<uint32_t> remap(source.positions.size(), UINT32_MAX);
            for (const mesh::Triangle& triangle : object.triangles) {
                if (source.corners[triangle.corners[0]].material != material) continue;
                for (const uint32_t corner : triangle.corners) {
                    const uint32_t position = source.corners[corner].position;
                    if (remap[position] == UINT32_MAX) {
                        remap[position] = static_cast<uint32_t>(xyz.size() / 3);
                        const mesh::Float3& p = source.positions[position];
                        xyz.insert(xyz.end(), {p.x, p.y, p.z});
                    }
                    indices.push_back(remap[position]);
                }
            }
            const bool opaque = std::find(nonOpaqueMaterials.begin(), nonOpaqueMaterials.end(), material) ==
                                nonOpaqueMaterials.end();
            rayMesh.geometries.push_back(
                Geometry(xyz, static_cast<uint32_t>(sizeof(mesh::Float3)), std::move(indices), opaque));
        }
        if (rayMesh.geometries.empty()) continue;  // an object without triangles has nothing to hit
        RayInstance instance;
        instance.mesh = static_cast<uint32_t>(desc.meshes.size());
        // Column-major 4x4 (element [c * 4 + r]) to row-major 3x4.
        for (int r = 0; r < 3; ++r) {
            for (int c = 0; c < 4; ++c) instance.transform[r * 4 + c] = static_cast<float>(object.transform[c * 4 + r]);
        }
        instance.instanceId = static_cast<uint32_t>(o) & 0xFFFFFFu;
        desc.meshes.push_back(std::move(rayMesh));
        desc.instances.push_back(instance);
    }
    return desc;
}

// ── Qualification slice ──────────────────────────────────────────────────────

RaySceneDesc RayQueryQualificationScene() {
    RayGeometry quad;
    const float quadXyz[] = {0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0};
    quad.vertexStride = 20;
    quad.vertexCount = 4;
    quad.vertices = PackPositions(quadXyz, quad.vertexStride);
    quad.indices = {0, 1, 2, 0, 2, 3};
    quad.opaque = true;
    RayGeometry cover;
    const float coverXyz[] = {0, 0, 0.5f, 1, 0, 0.5f, 1, 1, 0.5f, 0, 0, 0.5f, 1, 1, 0.5f, 0, 1, 0.5f};
    cover.vertexStride = 12;
    cover.vertexCount = 6;
    cover.vertices = PackPositions(coverXyz, cover.vertexStride);
    cover.opaque = false;
    RaySceneDesc desc;
    desc.meshes.push_back({{quad, cover}});
    RayInstance first;
    first.instanceId = 7;
    RayInstance second;
    second.transform = {1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0};
    second.instanceId = 0x123456;
    RayInstance third;
    third.transform = {1, 0, 0, 20, 0, 1, 0, 0, 0, 0, 1, 0};
    third.instanceId = 3;
    third.flags = kRayInstanceForceOpaque;
    desc.instances = {first, second, third};
    return desc;
}

std::vector<CastRay> RayQueryQualificationRays() {
    const auto down = [](float x, float y, float tMin = 0, float tMax = 100) {
        return CastRay{{x, y, 2}, tMin, {0, 0, -1}, tMax};
    };
    return {
        down(0.75f, 0.25f),                       // 0: even non-opaque triangle committed
        down(0.25f, 0.75f),                       // 1: odd non-opaque triangle passed, the quad below
        down(10.25f, 0.75f),                      // 2: the same on the second instance
        down(20.25f, 0.75f),                      // 3: forced opaque: the odd triangle is hit
        down(5, 5),                               // 4: miss
        down(0.25f, 0.75f, 0, 1),                 // 5: tMax before any surface
        down(0.75f, 0.25f, 1.75f),                // 6: tMin past the non-opaque cover
        CastRay{{0.2f, 0.1f, 1}, 0, {0.125f, 0.25f, -1}, 100},  // 7: oblique, meets the cover at (0.2625, 0.225)
        CastRay{{0.625f, 0.375f, -1}, 0, {0, 0, 1}, 100},      // 8: from below, the quad first
    };
}

std::vector<RayHit> RayQueryQualificationAnswers() {
    // hit, instance id, primitive, geometry, u (vertex 1), v (vertex 2), t, instance index.
    // Triangle (v0, v1, v2) = ((0,0), (1,0), (1,1)): (x, y) = (u + v, v); triangle
    // ((0,0), (1,1), (0,1)): (x, y) = (u, u + v).
    return {
        {1, 7, 0, 1, 0.5f, 0.25f, 1.5f, 0},
        {1, 7, 1, 0, 0.25f, 0.5f, 2.0f, 0},
        {1, 0x123456, 1, 0, 0.25f, 0.5f, 2.0f, 1},
        {1, 3, 1, 1, 0.25f, 0.5f, 1.5f, 2},
        {},
        {},
        {1, 7, 0, 0, 0.5f, 0.25f, 2.0f, 0},
        {1, 7, 0, 1, 0.0375f, 0.225f, 0.5f, 0},
        {1, 7, 0, 0, 0.25f, 0.375f, 1.0f, 0},
    };
}

}  // namespace uzp::render
