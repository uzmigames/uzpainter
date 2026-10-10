#pragma once

// The GPU tile store: tiles are textures of the render layer's device, blends are the generated
// kernels (kernelgen.h) dispatched in batches, uploads are buffer-to-texture copies and reads go
// through `TextureReadback`. Operations are queued and run by `Flush` as one submission: the
// parameter blocks of the queued blends are written to one arena buffer, copied to the GPU and
// read by the kernels through the descriptor heap.
//
// Owned and used by the engine thread (evaluator.h); each request hands its `EngineContext` to
// `BeginRequest`, and the context must stay set while operations are queued or flushed.

#include "evaluator/kernelgen.h"
#include "evaluator/tile_store.h"
#include "render/engine_thread.h"

#include <cstdint>
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
    render::Result<void> Blend(const BlendOp& op) override;
    render::Result<void> Flush() override;
    render::Result<TileImage> Read(TileHandle tile) override;
    [[nodiscard]] uint64_t AllocatedBytes() const override { return m_bytes; }

    [[nodiscard]] size_t TileCount() const { return m_tiles.size(); }
    [[nodiscard]] size_t QueuedOperations() const { return m_uploads.size() + m_blends.size(); }

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
    struct PendingBlend {
        render::ComputeKernel kernel;
        std::array<uint32_t, kBlendParamsStride> params{};
        uint32_t groupsX = 0;
        uint32_t groupsY = 0;
        uz::RHITextureHandle dst = uz::RHITextureHandle::Invalid();
        uz::RHITextureHandle acc = uz::RHITextureHandle::Invalid();
        uz::RHITextureHandle src = uz::RHITextureHandle::Invalid();
        uz::RHITextureHandle mask = uz::RHITextureHandle::Invalid();
    };

    const Tile* Find(TileHandle tile) const;
    render::Result<void> RequireContext() const;
    /// Creates the 16-bit UNORM operand table (upload and GPU buffers); copied by the next flush.
    render::Result<void> EnsureTable16();
    render::Result<uz::RHIBufferHandle> CreateBuffer(uint64_t bytes, uz::RHIBufferUsage usage,
                                                     uz::RHIMemoryType memory, uint32_t stride,
                                                     const char* name);
    void DestroyRetired();

    render::IDevice& m_device;
    render::EngineContext* m_context = nullptr;
    std::unordered_map<TileHandle, Tile> m_tiles;
    TileHandle m_next = 1;
    uint64_t m_bytes = 0;
    std::vector<PendingUpload> m_uploads;
    std::vector<PendingBlend> m_blends;
    uz::RHIBufferHandle m_table16Upload = uz::RHIBufferHandle::Invalid();
    uz::RHIBufferHandle m_table16 = uz::RHIBufferHandle::Invalid();
    bool m_table16Copied = false;
    std::vector<uz::RHIBufferHandle> m_retired;
};

}  // namespace uzp::evaluator
