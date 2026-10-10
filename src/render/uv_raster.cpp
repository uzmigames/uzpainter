#include "render/uv_raster.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <deque>
#include <limits>
#include <string>
#include <unordered_set>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kUvRasterHlsl[] = {
#embed "shaders/uv_raster.hlsl"
};
#pragma clang diagnostic pop

/// Texels per side of a CoverMain work item (its thread group is 8 x 8).
constexpr uint32_t kBlock = 8;
constexpr uint32_t kMaxSize = 16384;
constexpr uint32_t kMaxGroupsPerDimension = 65535;
constexpr uint64_t kMaxRawBytes = 0xFFFFFFFCull;

/// Word offsets of the params buffer (`P_*` in uv_raster.hlsl).
enum ParamWord : uint32_t {
    kTileColumn = 0,
    kTileRow = 1,
    kTriangles = 2,
    kPosition = 3,
    kNormal = 6,
    kUv = 9,
    kTangent = 12,
    kMaterial = 15,
    kIsland = 18,
    kParamWords = 21,
};

KernelSource Source(const char* entryPoint, const char* name) {
    KernelSource source;
    source.name = name;
    source.hlsl.assign(kUvRasterHlsl, sizeof(kUvRasterHlsl));
    source.entryPoint = entryPoint;
    return source;
}

struct NamedAttribute {
    const char* name;
    const CornerAttribute* attribute;
    uint32_t bytes;
    uint32_t word;  ///< Its offset in the params buffer.
};

std::array<NamedAttribute, 6> Attributes(const CornerBuffers& corners) {
    return {{{"position", &corners.position, 12, kPosition},
             {"normal", &corners.normal, 12, kNormal},
             {"uv0", &corners.uv0, 8, kUv},
             {"tangent", &corners.tangent, 16, kTangent},
             {"material id", &corners.materialId, 4, kMaterial},
             {"island id", &corners.islandId, 4, kIsland}}};
}

template <class T>
T LoadAt(std::span<const std::byte> bytes, uint64_t offset) {
    T value;
    std::memcpy(&value, bytes.data() + offset, sizeof(T));
    return value;
}

/// One CoverMain work item: a triangle and a block of at most 8 x 8 texels of its bounding box
/// (texel space, y up).
struct WorkItem {
    uint32_t triangle;
    uint32_t x0;
    uint32_t y0;
    uint32_t size;  ///< width | height << 8
};

/// The texel range [first, last) whose unit intervals overlap (lo, hi) with a positive length,
/// clipped to [0, size).
std::pair<uint32_t, uint32_t> TexelRange(float lo, float hi, uint32_t size) {
    const float first = std::max(std::floor(lo), 0.0f);
    const float last = std::min(std::ceil(hi), static_cast<float>(size));
    if (!(first < last)) return {0, 0};
    return {static_cast<uint32_t>(first), static_cast<uint32_t>(last)};
}

/// A raw (byte-address) GPU buffer filled from the CPU: an upload buffer and the default-heap
/// buffer the pass reads.
struct RawBuffer {
    uz::RHIBufferHandle upload = uz::RHIBufferHandle::Invalid();
    uz::RHIBufferHandle gpu = uz::RHIBufferHandle::Invalid();
    uint64_t size = 0;
};

class Resources {
public:
    explicit Resources(IDevice& device) : m_device(device) {}
    ~Resources() {
        for (const RawBuffer& buffer : m_buffers) {
            m_device.DestroyBuffer(buffer.upload);
            m_device.DestroyBuffer(buffer.gpu);
        }
    }
    Resources(const Resources&) = delete;
    Resources& operator=(const Resources&) = delete;

    /// A raw buffer holding `bytes` (padded with zeros to a multiple of 16 bytes, at least 16).
    Result<const RawBuffer*> Raw(std::span<const std::byte> bytes, const char* name) {
        RawBuffer buffer;
        buffer.size = std::max<uint64_t>(16, (bytes.size() + 15) / 16 * 16);
        uz::RHIBufferDesc desc;
        desc.sizeBytes = buffer.size;
        desc.usage = uz::RHIBufferUsage::CopySrc;
        desc.memory = uz::RHIMemoryType::Upload;
        desc.debugName = name;
        Result<uz::RHIBufferHandle> upload = m_device.CreateBuffer(desc);
        if (!upload) return Unexpected(upload.error());
        buffer.upload = *upload;
        desc.stride = 0;  // raw SRV (ByteAddressBuffer)
        desc.usage = uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst;
        desc.memory = uz::RHIMemoryType::Default;
        Result<uz::RHIBufferHandle> gpu = m_device.CreateBuffer(desc);
        if (!gpu) {
            m_device.DestroyBuffer(buffer.upload);
            return Unexpected(gpu.error());
        }
        buffer.gpu = *gpu;
        m_buffers.push_back(buffer);
        auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(buffer.upload));
        if (!mapped) {
            return Fail(ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                        std::string("uv raster: upload buffer '") + name + "' not mapped");
        }
        std::memset(mapped, 0, buffer.size);
        if (!bytes.empty()) std::memcpy(mapped, bytes.data(), bytes.size());
        m_device.Rhi().UnmapBuffer(buffer.upload);
        return &m_buffers.back();
    }

    [[nodiscard]] uint32_t Srv(const RawBuffer& buffer) const {
        return m_device.Rhi().GetBufferSRVIndex(buffer.gpu);
    }

    /// Records the copies into the default-heap buffers, leaving them readable by shaders.
    void RecordUploads(uz::IRHICommandList& cmd) const {
        for (const RawBuffer& buffer : m_buffers) {
            const uz::RHIBarrierDesc toCopy{uz::RHITextureHandle::Invalid(), buffer.gpu,
                                            uz::RHIResourceState::Common,
                                            uz::RHIResourceState::CopyDst};
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(buffer.upload, 0, buffer.gpu, 0, buffer.size);
            const uz::RHIBarrierDesc toRead{uz::RHITextureHandle::Invalid(), buffer.gpu,
                                            uz::RHIResourceState::CopyDst,
                                            uz::RHIResourceState::ShaderResource};
            cmd.ResourceBarrier(&toRead, 1);
        }
    }

    /// Keeps the buffers alive (they may still be in use by a GPU that missed its deadline).
    void Abandon() { m_buffers.clear(); }

private:
    IDevice& m_device;
    std::deque<RawBuffer> m_buffers;  // stable addresses: `Raw` returns pointers into it
};

}  // namespace

std::vector<uz::RHITextureHandle> UvRasterBuffers::Textures() const {
    return {position, normal, tangent, bitangent, islandId, materialId, triangle, conservative};
}

void UvRasterBuffers::Destroy(IDevice& device) {
    for (uz::RHITextureHandle* texture : {&position, &normal, &tangent, &bitangent, &islandId,
                                          &materialId, &triangle, &conservative}) {
        device.DestroyTexture(*texture);
        *texture = uz::RHITextureHandle::Invalid();
    }
}

Result<void> ValidateUvRaster(const CornerBuffers& corners, const UvRasterRequest& request,
                              Backend backend) {
    const auto fail = [&](std::string reason) {
        return Fail(ErrorCode::RequestFailed, backend, "uv raster: " + std::move(reason));
    };
    if (request.width == 0 || request.height == 0 || request.width > kMaxSize ||
        request.height > kMaxSize) {
        return fail("size " + std::to_string(request.width) + "x" +
                    std::to_string(request.height) + " is outside 1 to " +
                    std::to_string(kMaxSize) + " texels per side");
    }
    if (request.uvTile != kUvTile1001) {
        return fail("UV tile " + std::to_string(request.uvTile) +
                    ": only tile 1001 is rasterised in v1 (docs/architecture/12-mesh-import.md "
                    "§6)");
    }
    if (corners.buffers.size() > kMaxCornerBuffers) {
        return fail(std::to_string(corners.buffers.size()) + " corner buffers, at most " +
                    std::to_string(kMaxCornerBuffers));
    }
    for (size_t i = 0; i < corners.buffers.size(); ++i) {
        if (corners.buffers[i].size() > kMaxRawBytes) {
            return fail("corner buffer " + std::to_string(i) + " is 4 GiB or larger");
        }
    }
    for (const NamedAttribute& named : Attributes(corners)) {
        const CornerAttribute& a = *named.attribute;
        const std::string what = std::string("attribute ") + named.name;
        if (a.buffer >= corners.buffers.size()) {
            return fail(what + " names buffer " + std::to_string(a.buffer) + " of " +
                        std::to_string(corners.buffers.size()));
        }
        if (a.offset % 4 != 0 || a.stride % 4 != 0) {
            return fail(what + ": offset " + std::to_string(a.offset) + " and stride " +
                        std::to_string(a.stride) + " must be multiples of 4");
        }
        if (a.stride < named.bytes) {
            return fail(what + ": stride " + std::to_string(a.stride) +
                        " is smaller than the attribute's " + std::to_string(named.bytes) +
                        " bytes");
        }
        if (corners.cornerCount == 0) continue;
        const uint64_t end = uint64_t{a.offset} +
                             uint64_t{corners.cornerCount - 1} * a.stride + named.bytes;
        if (end > corners.buffers[a.buffer].size()) {
            return fail(what + ": " + std::to_string(corners.cornerCount) + " corners end at byte " +
                        std::to_string(end) + " of a " +
                        std::to_string(corners.buffers[a.buffer].size()) + "-byte buffer");
        }
    }
    if (corners.triangles.size() % 3 != 0) {
        return fail(std::to_string(corners.triangles.size()) +
                    " corner ids, not a multiple of 3");
    }
    if (corners.triangles.size_bytes() > kMaxRawBytes) {
        return fail("the corner ids take 4 GiB or more");
    }
    for (size_t i = 0; i < corners.triangles.size(); ++i) {
        if (corners.triangles[i] >= corners.cornerCount) {
            return fail("triangle " + std::to_string(i / 3) + " names corner " +
                        std::to_string(corners.triangles[i]) + " of " +
                        std::to_string(corners.cornerCount));
        }
    }
    return {};
}

Result<UvRasterBuffers> RasterizeUv(EngineContext& context, const CornerBuffers& corners,
                                    const UvRasterRequest& request) {
    IDevice& device = context.Device();
    const Backend backend = device.GetBackend();
    if (std::optional<Error> removed = device.CheckRemoved()) return Unexpected(*removed);
    if (Result<void> valid = ValidateUvRaster(corners, request, backend); !valid) {
        return Unexpected(valid.error());
    }

    // Work items: every selected triangle's bounding box in texel space, clipped to the tile and
    // cut into 8 x 8 blocks. The texel coordinates are computed with the same single-precision
    // operations as the kernel's.
    const uint32_t tileColumn = (request.uvTile - 1001) % 10;
    const uint32_t tileRow = (request.uvTile - 1001) / 10;
    const std::unordered_set<uint32_t> materials(request.materials.begin(),
                                                 request.materials.end());
    const std::span<const std::byte> uvBytes = corners.buffers[corners.uv0.buffer];
    const std::span<const std::byte> materialBytes = corners.buffers[corners.materialId.buffer];
    std::vector<WorkItem> items;
    const size_t triangleCount = corners.triangles.size() / 3;
    for (size_t t = 0; t < triangleCount; ++t) {
        const uint32_t first = corners.triangles[t * 3];
        if (!materials.empty()) {
            const uint32_t material = LoadAt<uint32_t>(
                materialBytes,
                corners.materialId.offset + uint64_t{first} * corners.materialId.stride);
            if (!materials.contains(material)) continue;
        }
        constexpr float kInf = std::numeric_limits<float>::infinity();
        float minX = kInf, maxX = -kInf, minY = kInf, maxY = -kInf;
        bool finite = true;
        for (size_t k = 0; k < 3; ++k) {
            const uint64_t at =
                corners.uv0.offset + uint64_t{corners.triangles[t * 3 + k]} * corners.uv0.stride;
            const float u = LoadAt<float>(uvBytes, at) - static_cast<float>(tileColumn);
            const float v = LoadAt<float>(uvBytes, at + 4) - static_cast<float>(tileRow);
            const float x = u * static_cast<float>(request.width);
            const float y = v * static_cast<float>(request.height);
            finite = finite && std::isfinite(x) && std::isfinite(y);
            minX = std::min(minX, x);
            maxX = std::max(maxX, x);
            minY = std::min(minY, y);
            maxY = std::max(maxY, y);
        }
        if (!finite) continue;  // covers nothing
        const auto [x0, x1] = TexelRange(minX, maxX, request.width);
        const auto [y0, y1] = TexelRange(minY, maxY, request.height);
        for (uint32_t by = y0; by < y1; by += kBlock) {
            for (uint32_t bx = x0; bx < x1; bx += kBlock) {
                const uint32_t w = std::min(kBlock, x1 - bx);
                const uint32_t h = std::min(kBlock, y1 - by);
                items.push_back({static_cast<uint32_t>(t), bx, by, w | (h << 8)});
            }
        }
    }
    if (items.size() > uint64_t{kMaxGroupsPerDimension} * kMaxGroupsPerDimension ||
        items.size() * sizeof(WorkItem) > kMaxRawBytes) {
        return Fail(ErrorCode::RequestFailed, backend,
                    "uv raster: " + std::to_string(items.size()) +
                        " work items exceed one dispatch");
    }

    // Inputs: the corner buffers, the corner ids, the params and the work items.
    Resources resources(device);
    std::vector<uint32_t> cornerSrv;
    for (const std::span<const std::byte> buffer : corners.buffers) {
        Result<const RawBuffer*> raw = resources.Raw(buffer, "uv_raster_corners");
        if (!raw) return Unexpected(raw.error());
        cornerSrv.push_back(resources.Srv(**raw));
    }
    Result<const RawBuffer*> triangles =
        resources.Raw(std::as_bytes(corners.triangles), "uv_raster_triangles");
    if (!triangles) return Unexpected(triangles.error());
    std::array<uint32_t, kParamWords> params{};
    params[kTileColumn] = tileColumn;
    params[kTileRow] = tileRow;
    params[kTriangles] = resources.Srv(**triangles);
    for (const NamedAttribute& named : Attributes(corners)) {
        params[named.word] = cornerSrv[named.attribute->buffer];
        params[named.word + 1] = named.attribute->offset;
        params[named.word + 2] = named.attribute->stride;
    }
    Result<const RawBuffer*> paramBuffer =
        resources.Raw(std::as_bytes(std::span(params)), "uv_raster_params");
    if (!paramBuffer) return Unexpected(paramBuffer.error());
    Result<const RawBuffer*> itemBuffer =
        resources.Raw(std::as_bytes(std::span(items)), "uv_raster_items");
    if (!itemBuffer) return Unexpected(itemBuffer.error());

    Result<ComputeKernel> clear = context.Kernel(Source("ClearMain", "uv_raster_clear"));
    if (!clear) return Unexpected(clear.error());
    Result<ComputeKernel> cover = context.Kernel(Source("CoverMain", "uv_raster_cover"));
    if (!cover) return Unexpected(cover.error());
    Result<ComputeKernel> resolve = context.Kernel(Source("ResolveMain", "uv_raster_resolve"));
    if (!resolve) return Unexpected(resolve.error());

    // Outputs.
    UvRasterBuffers out;
    out.uvTile = request.uvTile;
    out.width = request.width;
    out.height = request.height;
    const auto make = [&](uz::RHITextureHandle& handle, uz::RHIFormat format,
                          const char* name) -> Result<void> {
        uz::RHITextureDesc desc;
        desc.width = request.width;
        desc.height = request.height;
        desc.format = format;
        desc.usage = uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::UnorderedAccess |
                     uz::RHITextureUsage::CopySrc;
        desc.debugName = name;
        Result<uz::RHITextureHandle> texture = device.CreateTexture(desc);
        if (!texture) return Unexpected(texture.error());
        handle = *texture;
        return {};
    };
    using F = uz::RHIFormat;
    for (Result<void> made : {make(out.position, F::RGBA32Float, "uv_raster_position"),
                              make(out.normal, F::RGBA32Float, "uv_raster_normal"),
                              make(out.tangent, F::RGBA32Float, "uv_raster_tangent"),
                              make(out.bitangent, F::RGBA32Float, "uv_raster_bitangent"),
                              make(out.islandId, F::R32Uint, "uv_raster_island_id"),
                              make(out.materialId, F::R32Uint, "uv_raster_material_id"),
                              make(out.triangle, F::R32Uint, "uv_raster_triangle"),
                              make(out.conservative, F::R8Unorm, "uv_raster_conservative")}) {
        if (!made) {
            out.Destroy(device);
            return Unexpected(made.error());
        }
    }

    const uz::IRHIDevice& rhi = device.Rhi();
    const uint32_t itemCount = static_cast<uint32_t>(items.size());
    const uint32_t groupsX = std::clamp<uint32_t>(itemCount, 1, kMaxGroupsPerDimension);
    const uint32_t groupsY = (itemCount + groupsX - 1) / groupsX;
    const std::array<uint32_t, 14> root = {
        resources.Srv(**paramBuffer),
        resources.Srv(**itemBuffer),
        itemCount,
        groupsX,
        rhi.GetTextureUAVIndex(out.triangle),
        rhi.GetTextureUAVIndex(out.conservative),
        rhi.GetTextureUAVIndex(out.position),
        rhi.GetTextureUAVIndex(out.normal),
        rhi.GetTextureUAVIndex(out.tangent),
        rhi.GetTextureUAVIndex(out.bitangent),
        rhi.GetTextureUAVIndex(out.materialId),
        rhi.GetTextureUAVIndex(out.islandId),
        request.width,
        request.height,
    };
    const std::vector<uz::RHITextureHandle> textures = out.Textures();
    const auto transition = [&](uz::IRHICommandList& cmd, uz::RHIResourceState before,
                                uz::RHIResourceState after) {
        std::vector<uz::RHIBarrierDesc> barriers;
        for (uz::RHITextureHandle texture : textures) {
            barriers.push_back({texture, uz::RHIBufferHandle::Invalid(), before, after});
        }
        cmd.ResourceBarrier(barriers.data(), static_cast<uint32_t>(barriers.size()));
    };
    const auto uavBarrier = [](uz::IRHICommandList& cmd,
                               std::initializer_list<uz::RHITextureHandle> list) {
        std::vector<uz::RHIBarrierDesc> barriers;
        for (uz::RHITextureHandle texture : list) {
            barriers.push_back({texture, uz::RHIBufferHandle::Invalid(),
                                uz::RHIResourceState::UnorderedAccess,
                                uz::RHIResourceState::UnorderedAccess});
        }
        cmd.ResourceBarrier(barriers.data(), static_cast<uint32_t>(barriers.size()));
    };
    const uint32_t texelGroupsX = (request.width + 7) / 8;
    const uint32_t texelGroupsY = (request.height + 7) / 8;
    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        resources.RecordUploads(cmd);
        transition(cmd, uz::RHIResourceState::Common, uz::RHIResourceState::UnorderedAccess);
        cmd.SetPipeline(clear->pipeline);
        cmd.SetRootConstants(kRootConstantsParam, root.data(), static_cast<uint32_t>(root.size()));
        cmd.Dispatch(texelGroupsX, texelGroupsY, 1);
        uavBarrier(cmd, {out.triangle, out.conservative});
        if (itemCount > 0) {
            cmd.SetPipeline(cover->pipeline);
            cmd.SetRootConstants(kRootConstantsParam, root.data(),
                                 static_cast<uint32_t>(root.size()));
            cmd.Dispatch(groupsX, groupsY, 1);
            uavBarrier(cmd, {out.triangle, out.conservative});
        }
        cmd.SetPipeline(resolve->pipeline);
        cmd.SetRootConstants(kRootConstantsParam, root.data(), static_cast<uint32_t>(root.size()));
        cmd.Dispatch(texelGroupsX, texelGroupsY, 1);
        transition(cmd, uz::RHIResourceState::UnorderedAccess, uz::RHIResourceState::Common);
    });
    if (!done) {
        if (done.error().code == ErrorCode::Timeout) {
            // The GPU may still use every resource of the pass; the engine keeps its device and
            // fails every later request, so they are left to the process exit.
            resources.Abandon();
            return Unexpected(done.error());
        }
        out.Destroy(device);
        return Unexpected(done.error());
    }
    return out;
}

}  // namespace uzp::render
