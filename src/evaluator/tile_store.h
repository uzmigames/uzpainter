#pragma once

// Where tiles live and how the compositor's operations run on them: the interface the evaluator
// drives (evaluate.h), implemented on the GPU (gpu_store.h, kernels through the render layer's
// kernel cache) and on the CPU (cpu_store.h, the same arithmetic through arith.h). Both produce
// the same bytes; the CPU store is the reference and runs where no GPU is available.
//
// Errors are the render layer's `Result`/`Error`: evaluator failures use `RequestFailed` with a
// reason that starts with `evaluator:<kind>` (evaluator.h, `EvalFail`).

#include "evaluator/formats.h"
#include "render/backend.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "uzp_core/types/enums.h"

namespace uzp::evaluator {

/// A tile of a store; 0 is no tile.
using TileHandle = uint64_t;
inline constexpr TileHandle kNoTile = 0;

/// A decoded bitmap (a source resource): `values` holds width x height x channels samples, rows
/// top to bottom, UNORM codes or the bits of the float32 value of each sample.
struct DecodedImage {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    render::TexelEncoding encoding = render::TexelEncoding::Unorm16;
    std::vector<uint32_t> values;

    [[nodiscard]] uint32_t At(uint32_t x, uint32_t y, uint32_t c) const {
        return values[(size_t{y} * width + x) * channels + c];
    }
};

/// An input of a blend: a tile or a constant (straight colour and alpha).
struct Operand {
    enum class Kind : uint8_t { Constant, Tile };
    Kind kind = Kind::Constant;
    TileHandle tile = kNoTile;
    std::array<float, 4> value{0.0f, 0.0f, 0.0f, 1.0f};

    static Operand Constant(std::array<float, 3> rgb, float alpha) {
        return {Kind::Constant, kNoTile, {rgb[0], rgb[1], rgb[2], alpha}};
    }
    static Operand Of(TileHandle tile) { return {Kind::Tile, tile, {0.0f, 0.0f, 0.0f, 1.0f}}; }
};

/// One blend of a source over a backdrop into `dst` (all tiles of the same size; `dst` of the
/// channel's tile format, with the coverage plane when it is an isolated intermediate). The mask
/// is a constant or the first plane of a tile.
struct BlendOp {
    TileHandle dst = kNoTile;
    Operand acc;
    Operand source;
    Operand mask = Operand::Constant({1.0f, 1.0f, 1.0f}, 1.0f);
    core::BlendingMode mode = core::BlendingMode::Normal;
    float opacity = 1.0f;
};

/// The texels of a tile as the store holds them: `format.channels` channels per texel (the
/// coverage plane is not returned), tightly packed, each channel `format.BytesPerChannel()`
/// bytes (codes, half bits or float32 bits, little-endian).
struct TileImage {
    TileFormat format;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<std::byte> texels;
};

class ITileStore {
public:
    virtual ~ITileStore() = default;

    virtual render::Result<TileHandle> Allocate(const TileFormat& format, uint32_t width,
                                                uint32_t height) = 0;
    virtual void Release(TileHandle tile) = 0;

    /// Copies the window of `image` at (`x0`, `y0`) the size of `tile` into `tile`, texel for
    /// texel: samples of the tile's own encoding are copied (codes onto UNORM and sRGB8 tiles,
    /// half values onto 16-bit float tiles, floats onto 32-bit float tiles); 16-bit codes into a
    /// 32-bit float tile become float32(code / 65535) (parity/semantics/blend-modes.json, RGB32F
    /// operands). Other combinations are the colour-transfer rules of
    /// phase1.8_compositor-sources-projection and fail with `evaluator:unsupported_source`.
    virtual render::Result<void> Upload(TileHandle tile, const DecodedImage& image, uint32_t x0,
                                        uint32_t y0) = 0;

    /// Queues one blend; `Flush` runs the queue.
    virtual render::Result<void> Blend(const BlendOp& op) = 0;

    /// Runs every queued operation and waits for it.
    virtual render::Result<void> Flush() = 0;

    /// Flushes, then returns the tile's texels.
    virtual render::Result<TileImage> Read(TileHandle tile) = 0;

    /// Bytes of every allocated tile.
    [[nodiscard]] virtual uint64_t AllocatedBytes() const = 0;
};

}  // namespace uzp::evaluator
