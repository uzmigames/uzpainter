#include "evaluator/gpu_store.h"

#include <algorithm>
#include <bit>
#include <cstring>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/error.h"
#include "evaluator/hwmath.h"
#include "evaluator/projection_uv.h"
#include "render/image_pass.h"
#include "render/texture_readback.h"

namespace uzp::evaluator {

namespace {

using State = uz::RHIResourceState;
using render::image_pass_detail::Transition;

uz::RHITextureUsage TileUsage() {
    return uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::UnorderedAccess |
           uz::RHITextureUsage::CopySrc | uz::RHITextureUsage::CopyDst;
}

bool Valid(uz::RHITextureHandle handle) { return handle.IsValid(); }

/// The stored bits of a plane value (plane 3 is the coverage, linear).
uint32_t StoreValueBits(float value, const TileFormat& format, uint32_t plane) {
    if (format.halfCoverage && format.alpha && plane == 3) {
        value = arith::HalfToFloat(arith::HalfNearestEven(value));
    }
    switch (format.encoding) {
        case render::TexelEncoding::Unorm8:
            if (format.srgb && plane < 3) return arith::Srgb8Store(value);
            return arith::WriteUnorm(value, 8);
        case render::TexelEncoding::Unorm16: return arith::WriteUnorm(value, 16);
        case render::TexelEncoding::Float16: return arith::HalfTowardZero(value);
        case render::TexelEncoding::Float32: return std::bit_cast<uint32_t>(value);
    }
    return 0;
}

}  // namespace

GpuTileStore::GpuTileStore(render::IDevice& device) : m_device(device) {}

GpuTileStore::~GpuTileStore() {
    for (auto& [handle, tile] : m_tiles) m_device.DestroyTexture(tile.texture);
    for (PendingUpload& upload : m_uploads) m_device.DestroyBuffer(upload.staging);
    DestroyRetired();
    ReleaseBitmaps();
    if (m_table16Upload.IsValid()) m_device.DestroyBuffer(m_table16Upload);
    if (m_table16.IsValid()) m_device.DestroyBuffer(m_table16);
    if (m_powUpload.IsValid()) m_device.DestroyBuffer(m_powUpload);
    if (m_pow.IsValid()) m_device.DestroyBuffer(m_pow);
}

const GpuTileStore::Tile* GpuTileStore::Find(TileHandle tile) const {
    const auto it = m_tiles.find(tile);
    return it == m_tiles.end() ? nullptr : &it->second;
}

render::Result<void> GpuTileStore::RequireContext() const {
    if (m_context == nullptr) {
        return EvalFail(EvalErrorKind::Internal, "GPU tile store used outside an engine request");
    }
    return {};
}

render::Result<uz::RHIBufferHandle> GpuTileStore::CreateBuffer(uint64_t bytes,
                                                               uz::RHIBufferUsage usage,
                                                               uz::RHIMemoryType memory,
                                                               uint32_t stride, const char* name) {
    uz::RHIBufferDesc desc;
    desc.sizeBytes = std::max<uint64_t>(bytes, 16);
    desc.stride = stride;
    desc.usage = usage;
    desc.memory = memory;
    desc.debugName = name;
    return m_device.CreateBuffer(desc);
}

void GpuTileStore::DestroyRetired() {
    for (const uz::RHIBufferHandle buffer : m_retired) m_device.DestroyBuffer(buffer);
    m_retired.clear();
}

render::Result<void> GpuTileStore::EnsureTable16() {
    if (m_table16.IsValid()) return {};
    const std::vector<uint32_t>& table = OperandTableWords();
    const uint64_t bytes = table.size() * sizeof(uint32_t);
    render::Result<uz::RHIBufferHandle> upload =
        CreateBuffer(bytes, uz::RHIBufferUsage::CopySrc, uz::RHIMemoryType::Upload, 0,
                     "evaluator_operand_tables_upload");
    if (!upload) return render::Unexpected(upload.error());
    auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(*upload));
    if (mapped == nullptr) {
        m_device.DestroyBuffer(*upload);
        return render::Fail(render::ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                            "evaluator: operand table upload buffer not mapped");
    }
    std::memcpy(mapped, table.data(), bytes);
    m_device.Rhi().UnmapBuffer(*upload);
    render::Result<uz::RHIBufferHandle> gpu =
        CreateBuffer(bytes, uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst,
                     uz::RHIMemoryType::Default, sizeof(uint32_t), "evaluator_operand_tables");
    if (!gpu) {
        m_device.DestroyBuffer(*upload);
        return render::Unexpected(gpu.error());
    }
    m_table16Upload = *upload;
    m_table16 = *gpu;
    m_table16Copied = false;
    return {};
}

render::Result<void> GpuTileStore::EnsurePowTables() {
    if (m_pow.IsValid()) return {};
    const uint64_t bytes = uint64_t{kPowWords} * sizeof(uint32_t);
    render::Result<uz::RHIBufferHandle> upload =
        CreateBuffer(bytes, uz::RHIBufferUsage::CopySrc, uz::RHIMemoryType::Upload, 0,
                     "evaluator_pow_tables_upload");
    if (!upload) return render::Unexpected(upload.error());
    auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(*upload));
    if (mapped == nullptr) {
        m_device.DestroyBuffer(*upload);
        return render::Fail(render::ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                            "evaluator: pow table upload buffer not mapped");
    }
    const std::pair<hw::Table, uint32_t> tables[6] = {{hw::Table::Log2Hi, kPowLog2Hi},
                                                      {hw::Table::Log2Lo, kPowLog2Lo},
                                                      {hw::Table::Exp2Pos, kPowExp2Pos},
                                                      {hw::Table::Exp2Neg, kPowExp2Neg},
                                                      {hw::Table::Sin, kPowSin},
                                                      {hw::Table::Cos, kPowCos}};
    for (const auto& [table, offset] : tables) {
        const std::vector<uint32_t>& values = hw::Values(table);
        std::memcpy(mapped + uint64_t{offset} * sizeof(uint32_t), values.data(), values.size() * sizeof(uint32_t));
    }
    m_device.Rhi().UnmapBuffer(*upload);
    render::Result<uz::RHIBufferHandle> gpu =
        CreateBuffer(bytes, uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst,
                     uz::RHIMemoryType::Default, sizeof(uint32_t), "evaluator_pow_tables");
    if (!gpu) {
        m_device.DestroyBuffer(*upload);
        return render::Unexpected(gpu.error());
    }
    m_powUpload = *upload;
    m_pow = *gpu;
    m_powCopied = false;
    return {};
}

void GpuTileStore::ReleaseBitmaps() {
    for (auto& [key, bitmap] : m_bitmaps) {
        if (bitmap.upload.IsValid()) m_device.DestroyBuffer(bitmap.upload);
        m_device.DestroyBuffer(bitmap.buffer);
    }
    m_bitmaps.clear();
    m_bitmapBytes = 0;
}

render::Result<uz::RHIBufferHandle> GpuTileStore::BitmapBuffer(const std::string& key,
                                                                const DecodedImage& image) {
    const auto it = m_bitmaps.find(key);
    if (it != m_bitmaps.end()) return it->second.buffer;
    const std::vector<uint32_t> words = PackBitmapCodes(image);
    const uint64_t bytes = std::max<uint64_t>(words.size(), 1) * sizeof(uint32_t);
    if (m_bitmapBytes + bytes > kBitmapCacheBytes && !m_bitmaps.empty()) {
        // Empty the cache once nothing queued reads it.
        render::Result<void> flushed = Flush();
        if (!flushed) return render::Unexpected(flushed.error());
        ReleaseBitmaps();
    }
    render::Result<uz::RHIBufferHandle> upload =
        CreateBuffer(bytes, uz::RHIBufferUsage::CopySrc, uz::RHIMemoryType::Upload, 0,
                     "evaluator_bitmap_upload");
    if (!upload) return render::Unexpected(upload.error());
    auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(*upload));
    if (mapped == nullptr) {
        m_device.DestroyBuffer(*upload);
        return render::Fail(render::ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                            "evaluator: bitmap upload buffer not mapped");
    }
    if (!words.empty()) std::memcpy(mapped, words.data(), words.size() * sizeof(uint32_t));
    m_device.Rhi().UnmapBuffer(*upload);
    render::Result<uz::RHIBufferHandle> gpu =
        CreateBuffer(bytes, uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst,
                     uz::RHIMemoryType::Default, sizeof(uint32_t), "evaluator_bitmap");
    if (!gpu) {
        m_device.DestroyBuffer(*upload);
        return render::Unexpected(gpu.error());
    }
    m_bitmaps.emplace(key, Bitmap{*upload, *gpu, bytes});
    m_bitmapBytes += bytes;
    return *gpu;
}

render::Result<TileHandle> GpuTileStore::Allocate(const TileFormat& format, uint32_t width,
                                                  uint32_t height) {
    if (width == 0 || height == 0 || width > kTileSize || height > kTileSize) {
        return EvalFail(EvalErrorKind::Internal,
                        "a tile is 1 to " + std::to_string(kTileSize) + " texels on each axis");
    }
    uz::RHITextureDesc desc;
    desc.width = width;
    desc.height = height;
    desc.format = RhiFormatOf(format);
    desc.usage = TileUsage();
    desc.debugName = "evaluator_tile";
    render::Result<uz::RHITextureHandle> texture = m_device.CreateTexture(desc);
    if (!texture) return render::Unexpected(texture.error());
    Tile tile;
    tile.texture = *texture;
    tile.format = format;
    tile.width = width;
    tile.height = height;
    const TileHandle handle = m_next++;
    m_tiles.emplace(handle, tile);
    m_bytes += TileBytes(format, width, height);
    return handle;
}

void GpuTileStore::Release(TileHandle handle) {
    const auto it = m_tiles.find(handle);
    if (it == m_tiles.end()) return;
    m_bytes -= TileBytes(it->second.format, it->second.width, it->second.height);
    m_device.DestroyTexture(it->second.texture);
    m_tiles.erase(it);
}

render::Result<void> GpuTileStore::Upload(TileHandle handle, const DecodedImage& image,
                                          uint32_t x0, uint32_t y0) {
    render::Result<void> context = RequireContext();
    if (!context) return context;
    const Tile* tile = Find(handle);
    if (tile == nullptr) return EvalFail(EvalErrorKind::Internal, "upload into an unknown tile");
    if (x0 + tile->width > image.width || y0 + tile->height > image.height) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the bitmap (" + std::to_string(image.width) + "x" +
                            std::to_string(image.height) + ") does not cover the tile window");
    }
    if (image.channels < tile->format.channels) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "a bitmap with " + std::to_string(image.channels) +
                            " channels cannot fill a " + std::to_string(tile->format.channels) +
                            "-channel tile");
    }
    const bool sameDepth = image.encoding == tile->format.encoding;
    const bool codesToFloat32 = image.encoding == render::TexelEncoding::Unorm16 &&
                                tile->format.encoding == render::TexelEncoding::Float32;
    if (!sameDepth && !codesToFloat32) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "bitmap conversion into this channel format is not part of this profile "
                        "(phase1.8_compositor-sources-projection)");
    }
    // Rows laid out at the 256-byte pitch D3D12's copy footprint uses (texture_readback.h).
    const uint32_t bytesPerChannel = tile->format.BytesPerChannel();
    const uint32_t stored = tile->format.StoredChannels();
    const uint64_t rowBytes = uint64_t{tile->width} * stored * bytesPerChannel;
    const uint32_t rowPitch = static_cast<uint32_t>(render::ReadbackRowPitch(rowBytes));
    render::Result<uz::RHIBufferHandle> staging =
        CreateBuffer(uint64_t{rowPitch} * tile->height, uz::RHIBufferUsage::CopySrc,
                     uz::RHIMemoryType::Upload, 0, "evaluator_upload");
    if (!staging) return render::Unexpected(staging.error());
    auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(*staging));
    if (mapped == nullptr) {
        m_device.DestroyBuffer(*staging);
        return render::Fail(render::ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                            "evaluator: upload buffer not mapped");
    }
    const uint32_t coverage = StoreValueBits(1.0f, tile->format, 3);
    for (uint32_t y = 0; y < tile->height; ++y) {
        std::byte* row = mapped + uint64_t{rowPitch} * y;
        for (uint32_t x = 0; x < tile->width; ++x) {
            for (uint32_t c = 0; c < stored; ++c) {
                uint32_t bits = 0;
                if (c < tile->format.channels) {
                    const uint32_t sample = image.At(x0 + x, y0 + y, c);
                    if (codesToFloat32) {
                        bits = std::bit_cast<uint32_t>(arith::UnormOperand(sample & 0xFFFF, 16));
                    } else if (tile->format.encoding == render::TexelEncoding::Float16) {
                        // The image holds the float32 value of each half; the texture its bits.
                        bits = arith::HalfTowardZero(std::bit_cast<float>(sample));
                    } else {
                        bits = sample;
                    }
                } else if (c == 3) {
                    bits = coverage;
                }
                std::memcpy(row + (uint64_t{x} * stored + c) * bytesPerChannel, &bits,
                            bytesPerChannel);
            }
        }
    }
    m_device.Rhi().UnmapBuffer(*staging);
    m_uploads.push_back(PendingUpload{*staging, rowPitch, tile->texture});
    return {};
}

render::Result<void> GpuTileStore::Blend(const BlendOp& op) {
    render::Result<void> context = RequireContext();
    if (!context) return context;
    const Tile* dst = Find(op.dst);
    if (dst == nullptr) return EvalFail(EvalErrorKind::Internal, "blend into an unknown tile");
    const Tile* acc = op.acc.kind == Operand::Kind::Tile ? Find(op.acc.tile) : nullptr;
    const Tile* src = op.source.kind == Operand::Kind::Tile ? Find(op.source.tile) : nullptr;
    const Tile* mask = op.mask.kind == Operand::Kind::Tile ? Find(op.mask.tile) : nullptr;
    if ((op.acc.kind == Operand::Kind::Tile && acc == nullptr) ||
        (op.source.kind == Operand::Kind::Tile && src == nullptr) ||
        (op.mask.kind == Operand::Kind::Tile && mask == nullptr)) {
        return EvalFail(EvalErrorKind::Internal, "blend operand tile unknown");
    }
    for (const Tile* input : {acc, src, mask}) {
        if (input != nullptr && (input->width != dst->width || input->height != dst->height)) {
            return EvalFail(EvalErrorKind::Internal, "blend operands differ in size");
        }
    }
    for (const Tile* input : {acc, src}) {
        if (input != nullptr && (input->format.encoding != dst->format.encoding ||
                                 input->format.srgb != dst->format.srgb ||
                                 input->format.channels != dst->format.channels)) {
            return EvalFail(EvalErrorKind::Internal, "blend operands differ in format");
        }
    }
    if (!arith::HasKernel(op.mode)) {
        return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                        std::string(core::ToString(op.mode)) +
                            " has no blend kernel (a group placement)");
    }
    render::Result<void> table = EnsureTable16();
    if (!table) return table;
    using M = core::BlendingMode;
    const bool rotates = op.mode == M::NormalMapCombine || op.mode == M::NormalMapDetail ||
                         op.mode == M::NormalMapInverseDetail;
    if (rotates) {
        render::Result<void> pow = EnsurePowTables();
        if (!pow) return pow;
    }
    render::Result<render::ComputeKernel> kernel =
        m_context->Kernel(BlendKernelSource(BlendKernelVariant{op.mode, dst->format}));
    if (!kernel) return render::Unexpected(kernel.error());

    BlendBindings bindings;
    bindings.width = dst->width;
    bindings.height = dst->height;
    if (acc != nullptr) {
        bindings.accSrv = m_device.Rhi().GetTextureSRVIndex(acc->texture);
        bindings.accAlpha = acc->format.alpha;
    }
    if (src != nullptr) {
        bindings.srcSrv = m_device.Rhi().GetTextureSRVIndex(src->texture);
        bindings.srcAlpha = src->format.alpha;
    }
    if (mask != nullptr) {
        bindings.maskSrv = m_device.Rhi().GetTextureSRVIndex(mask->texture);
        bindings.maskEncoding = mask->format.encoding;
    }
    bindings.dstUav = m_device.Rhi().GetTextureUAVIndex(dst->texture);
    bindings.table16Srv = m_device.Rhi().GetBufferSRVIndex(m_table16);
    if (rotates) bindings.powSrv = m_device.Rhi().GetBufferSRVIndex(m_pow);

    PendingDispatch pending;
    pending.kernel = *kernel;
    pending.params = EncodeBlendParams(op, bindings);
    pending.groupsX = render::image_pass_detail::Groups(dst->width, 8);
    pending.groupsY = render::image_pass_detail::Groups(dst->height, 8);
    pending.dst = dst->texture;
    if (acc != nullptr) pending.inputs[0] = acc->texture;
    if (src != nullptr) pending.inputs[1] = src->texture;
    if (mask != nullptr) pending.inputs[2] = mask->texture;
    m_dispatches.push_back(pending);
    return {};
}

render::Result<void> GpuTileStore::Levels(const LevelsOp& op) {
    render::Result<void> context = RequireContext();
    if (!context) return context;
    const Tile* dst = Find(op.dst);
    const Tile* src = Find(op.src);
    if (dst == nullptr || src == nullptr) {
        return EvalFail(EvalErrorKind::Internal, "levels into or from an unknown tile");
    }
    if (src->width != dst->width || src->height != dst->height || !(src->format == dst->format)) {
        return EvalFail(EvalErrorKind::Internal, "levels operands differ in size or format");
    }
    render::Result<void> table = EnsureTable16();
    if (!table) return table;
    render::Result<void> pow = EnsurePowTables();
    if (!pow) return pow;
    render::Result<render::ComputeKernel> kernel = m_context->Kernel(LevelsKernelSource(dst->format));
    if (!kernel) return render::Unexpected(kernel.error());
    LevelsBindings bindings;
    bindings.width = dst->width;
    bindings.height = dst->height;
    bindings.srcSrv = m_device.Rhi().GetTextureSRVIndex(src->texture);
    bindings.dstUav = m_device.Rhi().GetTextureUAVIndex(dst->texture);
    bindings.table16Srv = m_device.Rhi().GetBufferSRVIndex(m_table16);
    bindings.powSrv = m_device.Rhi().GetBufferSRVIndex(m_pow);
    bindings.srcAlpha = src->format.alpha;
    PendingDispatch pending;
    pending.kernel = *kernel;
    pending.params = EncodeLevelsParams(op, bindings);
    pending.groupsX = render::image_pass_detail::Groups(dst->width, 8);
    pending.groupsY = render::image_pass_detail::Groups(dst->height, 8);
    pending.dst = dst->texture;
    pending.inputs[0] = src->texture;
    m_dispatches.push_back(pending);
    return {};
}

render::Result<void> GpuTileStore::Project(const ProjectOp& op) {
    render::Result<void> context = RequireContext();
    if (!context) return context;
    const Tile* dst = Find(op.dst);
    if (dst == nullptr || !op.image) {
        return EvalFail(EvalErrorKind::Internal, "projection into an unknown tile or of no bitmap");
    }
    if (op.projection.MayUncover() && !dst->format.alpha) {
        return EvalFail(EvalErrorKind::Internal,
                        "a projection that may uncover texels needs a coverage plane");
    }
    const DecodedImage& image = *op.image;
    const std::string key =
        op.imageKey + (image.encoding == render::TexelEncoding::Unorm16 ? "/16" : "/8");
    render::Result<uz::RHIBufferHandle> buffer = BitmapBuffer(key, image);
    if (!buffer) return render::Unexpected(buffer.error());
    render::Result<render::ComputeKernel> kernel = m_context->Kernel(ProjectKernelSource(dst->format));
    if (!kernel) return render::Unexpected(kernel.error());
    ProjectBindings bindings;
    bindings.width = dst->width;
    bindings.height = dst->height;
    bindings.dstUav = m_device.Rhi().GetTextureUAVIndex(dst->texture);
    bindings.imageSrv = m_device.Rhi().GetBufferSRVIndex(*buffer);
    PendingDispatch pending;
    pending.kernel = *kernel;
    pending.params = EncodeProjectParams(op, bindings);
    pending.groupsX = render::image_pass_detail::Groups(dst->width, 8);
    pending.groupsY = render::image_pass_detail::Groups(dst->height, 8);
    pending.dst = dst->texture;
    m_dispatches.push_back(pending);
    return {};
}

render::Result<void> GpuTileStore::Flush() {
    bool bitmapsPending = false;
    for (const auto& [key, bitmap] : m_bitmaps) bitmapsPending = bitmapsPending || bitmap.upload.IsValid();
    if (m_uploads.empty() && m_dispatches.empty() && !bitmapsPending &&
        (m_table16Copied || !m_table16.IsValid()) && (m_powCopied || !m_pow.IsValid())) {
        return {};
    }
    render::Result<void> context = RequireContext();
    if (!context) return context;

    // The parameter arena of this flush: one block per blend.
    uz::RHIBufferHandle arenaUpload = uz::RHIBufferHandle::Invalid();
    uz::RHIBufferHandle arena = uz::RHIBufferHandle::Invalid();
    const uint64_t arenaBytes = uint64_t{kBlendParamsStride} * sizeof(uint32_t) *
                                std::max<size_t>(m_dispatches.size(), 1);
    if (!m_dispatches.empty()) {
        render::Result<uz::RHIBufferHandle> upload =
            CreateBuffer(arenaBytes, uz::RHIBufferUsage::CopySrc, uz::RHIMemoryType::Upload, 0,
                         "evaluator_params_upload");
        if (!upload) return render::Unexpected(upload.error());
        arenaUpload = *upload;
        auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(arenaUpload));
        if (mapped == nullptr) {
            m_device.DestroyBuffer(arenaUpload);
            return render::Fail(render::ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                                "evaluator: parameter arena not mapped");
        }
        for (size_t i = 0; i < m_dispatches.size(); ++i) {
            std::memcpy(mapped + i * kBlendParamsStride * sizeof(uint32_t), m_dispatches[i].params.data(),
                        kBlendParamsStride * sizeof(uint32_t));
        }
        m_device.Rhi().UnmapBuffer(arenaUpload);
        render::Result<uz::RHIBufferHandle> gpu = CreateBuffer(
            arenaBytes, uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst,
            uz::RHIMemoryType::Default, sizeof(uint32_t), "evaluator_params");
        if (!gpu) {
            m_device.DestroyBuffer(arenaUpload);
            return render::Unexpected(gpu.error());
        }
        arena = *gpu;
    }
    const uint32_t arenaSrv = arena.IsValid() ? m_device.Rhi().GetBufferSRVIndex(arena) : 0;
    const bool copyTable = m_table16.IsValid() && !m_table16Copied;
    const bool copyPow = m_pow.IsValid() && !m_powCopied;

    render::Result<void> done = m_context->SubmitAndWait([&](uz::IRHICommandList& cmd) {
        if (copyTable) {
            const uz::RHIBarrierDesc toCopy = Transition(m_table16, State::Common, State::CopyDst);
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(m_table16Upload, 0, m_table16, 0, OperandTableWords().size() * sizeof(uint32_t));
            const uz::RHIBarrierDesc toRead =
                Transition(m_table16, State::CopyDst, State::ShaderResource);
            cmd.ResourceBarrier(&toRead, 1);
        }
        if (copyPow) {
            const uz::RHIBarrierDesc toCopy = Transition(m_pow, State::Common, State::CopyDst);
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(m_powUpload, 0, m_pow, 0, uint64_t{kPowWords} * sizeof(uint32_t));
            const uz::RHIBarrierDesc toRead = Transition(m_pow, State::CopyDst, State::ShaderResource);
            cmd.ResourceBarrier(&toRead, 1);
        }
        if (arena.IsValid()) {
            const uz::RHIBarrierDesc toCopy = Transition(arena, State::Common, State::CopyDst);
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(arenaUpload, 0, arena, 0, arenaBytes);
            const uz::RHIBarrierDesc toRead = Transition(arena, State::CopyDst, State::ShaderResource);
            cmd.ResourceBarrier(&toRead, 1);
        }
        for (const auto& [key, bitmap] : m_bitmaps) {
            if (!bitmap.upload.IsValid()) continue;
            const uz::RHIBarrierDesc toCopy = Transition(bitmap.buffer, State::Common, State::CopyDst);
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(bitmap.upload, 0, bitmap.buffer, 0, bitmap.bytes);
            const uz::RHIBarrierDesc toRead = Transition(bitmap.buffer, State::CopyDst, State::ShaderResource);
            cmd.ResourceBarrier(&toRead, 1);
        }
        for (const PendingUpload& upload : m_uploads) {
            const uz::RHIBarrierDesc toCopy = Transition(upload.texture, State::Common, State::CopyDst);
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBufferToTexture(upload.staging, 0, upload.rowPitch, upload.texture, 0, 0);
            const uz::RHIBarrierDesc back = Transition(upload.texture, State::CopyDst, State::Common);
            cmd.ResourceBarrier(&back, 1);
        }
        for (size_t i = 0; i < m_dispatches.size(); ++i) {
            const PendingDispatch& dispatch = m_dispatches[i];
            uz::RHIBarrierDesc before[4];
            uint32_t count = 0;
            before[count++] = Transition(dispatch.dst, State::Common, State::UnorderedAccess);
            for (const uz::RHITextureHandle input : dispatch.inputs) {
                if (Valid(input)) before[count++] = Transition(input, State::Common, State::ShaderResource);
            }
            cmd.ResourceBarrier(before, count);
            cmd.SetPipeline(dispatch.kernel.pipeline);
            const uint32_t root[2] = {arenaSrv, static_cast<uint32_t>(i)};
            cmd.SetRootConstants(render::kRootConstantsParam, root, 2);
            cmd.Dispatch(dispatch.groupsX, dispatch.groupsY, 1);
            uz::RHIBarrierDesc after[4];
            count = 0;
            after[count++] = Transition(dispatch.dst, State::UnorderedAccess, State::Common);
            for (const uz::RHITextureHandle input : dispatch.inputs) {
                if (Valid(input)) after[count++] = Transition(input, State::ShaderResource, State::Common);
            }
            cmd.ResourceBarrier(after, count);
        }
    });
    // The GPU has finished (or the wait failed): with a successful wait the staging buffers are
    // free; after a timeout they may still be read, so they are kept (as the engine keeps its
    // device in that case).
    if (done) {
        for (const PendingUpload& upload : m_uploads) m_device.DestroyBuffer(upload.staging);
        if (arenaUpload.IsValid()) m_device.DestroyBuffer(arenaUpload);
        if (arena.IsValid()) m_device.DestroyBuffer(arena);
        DestroyRetired();
        if (copyTable) m_table16Copied = true;
        if (copyPow) {
            // The 128 MiB staging copy is not needed once the GPU holds the tables.
            m_device.DestroyBuffer(m_powUpload);
            m_powUpload = uz::RHIBufferHandle::Invalid();
            m_powCopied = true;
        }
        for (auto& [key, bitmap] : m_bitmaps) {
            if (bitmap.upload.IsValid()) m_device.DestroyBuffer(bitmap.upload);
            bitmap.upload = uz::RHIBufferHandle::Invalid();
        }
    } else {
        for (const PendingUpload& upload : m_uploads) m_retired.push_back(upload.staging);
        if (arenaUpload.IsValid()) m_retired.push_back(arenaUpload);
        if (arena.IsValid()) m_retired.push_back(arena);
    }
        m_uploads.clear();
    m_dispatches.clear();
    return done;
}

render::Result<TileImage> GpuTileStore::Read(TileHandle handle) {
    render::Result<void> flushed = Flush();
    if (!flushed) return render::Unexpected(flushed.error());
    const Tile* tile = Find(handle);
    if (tile == nullptr) return EvalFail(EvalErrorKind::Internal, "read of an unknown tile");
    render::TextureReadback readback(*m_context);
    render::ReadbackDesc desc;
    desc.texture = tile->texture;
    desc.channels = tile->format.channels;
    render::Result<render::ReadbackId> id = readback.Request(desc);
    if (!id) return render::Unexpected(id.error());
    render::Result<render::ReadbackImage> image = readback.Complete(*id);
    if (!image) return render::Unexpected(image.error());
    TileImage result;
    result.format = tile->format;
    result.width = image->width;
    result.height = image->height;
    result.texels = std::move(image->texels);
    return result;
}

}  // namespace uzp::evaluator
