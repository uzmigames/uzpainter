#pragma once

// The GPU tile store: tiles are textures of the render layer's device, blends and projections
// are the generated kernels (kernelgen.h) dispatched in batches, uploads are buffer-to-texture
// copies and reads go through `TextureReadback`. Operations are queued and run by `Flush` as one
// submission, in queue order: the parameter blocks of the queued dispatches are written to one
// arena buffer, copied to the GPU and read by the kernels through the descriptor heap. Bitmaps
// sampled by projections are kept in VRAM as packed code buffers keyed by (resource hash,
// encoding), uploaded once and reused across tiles and requests up to `kBitmapCacheBytes`.
//
// Owned and used by the engine thread (evaluator.h); each request hands its `EngineContext` to
// `BeginRequest`, and the context must stay set while operations are queued or flushed.

#include "evaluator/kernelgen.h"
#include "evaluator/tile_store.h"
#include "render/engine_thread.h"

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace uzp::evaluator {

class GpuTileStore final : public ITileStore {
public:
    explicit GpuTileStore(render::IDevice& device);
    /// Destroys every tile and buffer (nothing may be in flight: `Flush` waits).
    ~GpuTileStore() override;
    GpuTileStore(const GpuTileStore&) = delete;
    GpuTileStore& operator=(const GpuTileStore&) = delete;

    void BeginRequest(render::EngineContext& context) { m_context = &context; }
    void EndRequest() { m_context = nullptr; }

    render::Result<TileHandle> Allocate(const TileFormat& format, uint32_t width,
                                        uint32_t height) override;
    void Release(TileHandle tile) override;
    render::Result<void> Upload(TileHandle tile, const DecodedImage& image, uint32_t x0,
                                uint32_t y0) override;
    render::Result<void> Project(const ProjectOp& op) override;
    render::Result<void> Blend(const BlendOp& op) override;
    render::Result<void> Levels(const LevelsOp& op) override;
    render::Result<void> VirtualNormal(const VirtualNormalOp& op) override;
    render::Result<void> Flush() override;
    render::Result<TileImage> Read(TileHandle tile) override;
    [[nodiscard]] uint64_t AllocatedBytes() const override { return m_bytes; }

    [[nodiscard]] size_t TileCount() const { return m_tiles.size(); }
    [[nodiscard]] size_t QueuedOperations() const { return m_uploads.size() + m_dispatches.size(); }
    /// Bitmaps resident in VRAM and their bytes.
    [[nodiscard]] size_t CachedBitmaps() const { return m_bitmaps.size(); }

    /// The VRAM the bitmap cache may hold before it is emptied (after a flush).
    static constexpr uint64_t kBitmapCacheBytes = uint64_t{1} << 30;

private:
    struct Tile {
        uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
        TileFormat format;
        uint32_t width = 0;
        uint32_t height = 0;
    };
    struct PendingUpload {
        uz::RHIBufferHandle staging = uz::RHIBufferHandle::Invalid();
        uint32_t rowPitch = 0;
        uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    };
    /// A queued kernel dispatch (a blend or a projection): its parameter block, the tile it
    /// writes and the tiles it reads.
    struct PendingDispatch {
        render::ComputeKernel kernel;
        std::array<uint32_t, kBlendParamsStride> params{};
        uint32_t groupsX = 0;
        uint32_t groupsY = 0;
        uz::RHITextureHandle dst = uz::RHITextureHandle::Invalid();
        std::array<uz::RHITextureHandle, 3> inputs{uz::RHITextureHandle::Invalid(),
                                                   uz::RHITextureHandle::Invalid(),
                                                   uz::RHITextureHandle::Invalid()};
        /// Further distinct inputs (a virtual normal tile's height neighbours and channel).
        std::vector<uz::RHITextureHandle> extraInputs;
    };
    /// A bitmap's packed codes in VRAM; `upload` is valid until the first flush copies it.
    struct Bitmap {
        uz::RHIBufferHandle upload = uz::RHIBufferHandle::Invalid();
        uz::RHIBufferHandle buffer = uz::RHIBufferHandle::Invalid();
        uint64_t bytes = 0;
    };

    const Tile* Find(TileHandle tile) const;
    render::Result<void> RequireContext() const;
    /// Creates the operand tables buffer (kernelgen.h `OperandTableWords`: the 16-bit UNORM
    /// operands and the hardware arithmetic tables; upload and GPU buffers), copied by the next
    /// flush.
    render::Result<void> EnsureTable16();
    /// Creates the function tables buffer (log2, exp2, sin, cos) of the Levels kernel and the
    /// normal-map blend kernels (kernelgen.h `kPowWords`), copied by the next flush.
    render::Result<void> EnsurePowTables();
    render::Result<uz::RHIBufferHandle> CreateBuffer(uint64_t bytes, uz::RHIBufferUsage usage,
                                                     uz::RHIMemoryType memory, uint32_t stride,
                                                     const char* name);
    /// The VRAM buffer of `image` under `key`, created (and queued for copying) when absent.
    render::Result<uz::RHIBufferHandle> BitmapBuffer(const std::string& key, const DecodedImage& image);
    void ReleaseBitmaps();
    void DestroyRetired();

    render::IDevice& m_device;
    render::EngineContext* m_context = nullptr;
    std::unordered_map<TileHandle, Tile> m_tiles;
    TileHandle m_next = 1;
    uint64_t m_bytes = 0;
    std::vector<PendingUpload> m_uploads;
    std::vector<PendingDispatch> m_dispatches;
    std::unordered_map<std::string, Bitmap> m_bitmaps;
    uint64_t m_bitmapBytes = 0;
    uz::RHIBufferHandle m_table16Upload = uz::RHIBufferHandle::Invalid();
    uz::RHIBufferHandle m_table16 = uz::RHIBufferHandle::Invalid();
    bool m_table16Copied = false;
    uz::RHIBufferHandle m_powUpload = uz::RHIBufferHandle::Invalid();
    uz::RHIBufferHandle m_pow = uz::RHIBufferHandle::Invalid();
    bool m_powCopied = false;
    std::vector<uz::RHIBufferHandle> m_retired;
};

}  // namespace uzp::evaluator
