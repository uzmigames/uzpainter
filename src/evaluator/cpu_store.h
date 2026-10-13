#pragma once

// The CPU tile store: the compositor's operations in plain C++ through arith.h. It is the
// reference the GPU store must equal bit for bit (tests/evaluator/), and the evaluation path on
// a machine without a GPU (hosted CI, `UZP_NO_GPU=1`). Each operation computes its texels on every
// hardware thread, in contiguous ranges under the caller's floating-point control state; every
// texel is the single-threaded result bit for bit (decision 246).

#include "evaluator/texture_unit.h"
#include "evaluator/tile_store.h"

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace uzp::evaluator {

class CpuTileStore final : public ITileStore {
public:
    render::Result<TileHandle> Allocate(const TileFormat& format, uint32_t width,
                                        uint32_t height) override;
    void Release(TileHandle tile) override;
    render::Result<void> Upload(TileHandle tile, const DecodedImage& image, uint32_t x0,
                                uint32_t y0) override;
    render::Result<void> Project(const ProjectOp& op) override;
    render::Result<void> Blend(const BlendOp& op) override;
    render::Result<void> Levels(const LevelsOp& op) override;
    render::Result<void> VirtualNormal(const VirtualNormalOp& op) override;
    render::Result<void> Flush() override { return {}; }
    render::Result<TileImage> Read(TileHandle tile) override;
    [[nodiscard]] uint64_t AllocatedBytes() const override { return m_bytes; }

    [[nodiscard]] size_t TileCount() const { return m_tiles.size(); }

private:
    /// A tile: `StoredChannels()` values per texel, each a UNORM code, or the bits of the
    /// float32 value of a float texel (16-bit floats hold the value of the stored half).
    struct Tile {
        TileFormat format;
        uint32_t width = 0;
        uint32_t height = 0;
        std::vector<uint32_t> values;
    };

    const Tile* Find(TileHandle tile) const;

    std::unordered_map<TileHandle, Tile> m_tiles;
    /// The mip chains of minified bitmaps (projection_uv.h `BitmapChain`), by image key.
    std::unordered_map<std::string, std::shared_ptr<const tu::Chain>> m_chains;
    TileHandle m_next = 1;
    uint64_t m_bytes = 0;
};

/// The operand of a stored plane value of `format` (plane 3 is the coverage, linear).
[[nodiscard]] float OperandOf(uint32_t stored, const TileFormat& format, uint32_t plane);
/// The stored plane value of a composite result (plane 3 is the coverage, linear; through
/// binary16 first when `format.halfCoverage`).
[[nodiscard]] uint32_t StoreValue(float value, const TileFormat& format, uint32_t plane);

}  // namespace uzp::evaluator
