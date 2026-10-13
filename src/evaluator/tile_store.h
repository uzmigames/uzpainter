#pragma once

// Where tiles live and how the compositor's operations run on them: the interface the evaluator
// drives (evaluate.h), implemented on the GPU (gpu_store.h, kernels through the render layer's
// kernel cache) and on the CPU (cpu_store.h, the same arithmetic through arith.h). Both produce
// the same bytes; the CPU store is the reference and runs where no GPU is available.
//
// Errors are the render layer's `Result`/`Error`: evaluator failures use `RequestFailed` with a
// reason that starts with `evaluator:<kind>` (evaluator.h, `EvalFail`).

#include "evaluator/arith.h"
#include "evaluator/formats.h"
#include "render/backend.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "uzp_core/types/enums.h"

namespace uzp::evaluator {

struct ProjectOp;  // projection_uv.h

/// A tile of a store; 0 is no tile.
using TileHandle = uint64_t;
inline constexpr TileHandle kNoTile = 0;

/// A decoded bitmap (a source resource): `values` holds width x height x channels samples, rows
/// top to bottom, UNORM codes or the bits of the float32 value of each sample. A `Float16`
/// image is an R16F texture (a colour bitmap read by a one-channel tile, decision 218): each
/// sample holds the float32 bits of a binary16 value, and its bilinear filter returns a binary16.
struct DecodedImage {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    render::TexelEncoding encoding = render::TexelEncoding::Unorm16;
    std::vector<uint32_t> values;
    /// The float32 values are the decodes `Srgb8Operand` of an 8-bit sRGB bitmap's codes (evaluate.cpp
    /// `SrgbDecoded`): Painter samples it as an sRGB8 texture (decision 219).
    bool srgb8 = false;
    /// The projection writes the filter's result as a 16-bit UNORM code before the tile stores it:
    /// a bitmap on the Normal channel, a `Unorm16` image (evaluate.cpp `NormalTexture`, decision 226).
    bool unorm16Target = false;

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
    /// An effect's mix (a mask or content effect, arith.h `CompositeInput::effectMix`).
    bool effectMix = false;
    /// The coverage-weighted source-over (arith.h `CompositeInput::coverageWeights`).
    bool coverageWeights = false;
    /// The backdrop is the empty start of an isolated list (arith.h
    /// `CompositeInput::emptyBackdrop`).
    bool emptyBackdrop = false;
    /// The fused read-out over the base (arith.h `CompositeInput::fusedReadout`).
    bool fusedReadout = false;
    /// The composite before any write rule: `dst` is a 32-bit float tile of the source's channel
    /// count without a coverage plane, the operands keep their own formats and the clamp of UNORM
    /// formats follows the source's format (the float32 read-out the virtual normal maps read,
    /// height_to_normal.h).
    bool rawOutput = false;
};

/// A Levels effect (arith::Levels) of `src` into `dst` (same size and format): component c of
/// every texel through `components[c]` (a grey tile or a mask uses the first), each result
/// stored with the tile's write rule; the coverage plane is copied.
struct LevelsOp {
    TileHandle dst = kNoTile;
    TileHandle src = kNoTile;
    std::array<arith::LevelsComponent, 3> components{};
};

/// One tile of a virtual normal map (height_to_normal.h): the height-derived normal of every
/// texel from the float32 height read-out of the tile and its eight neighbours (wrap-around at the
/// set border), combined with the Normal channel, stored in `dst` as n / 2 + 1/2 (32-bit float,
/// three channels, raw).
struct VirtualNormalOp {
    TileHandle dst = kNoTile;
    /// The grey 32-bit float height read-out tiles at tile offsets (dx, dy) in [-1, 1]^2, index
    /// (dy + 1) 3 + dx + 1, all of the dst's size; every entry kNoTile when the Height is the
    /// constant `heightConstant` (an empty or absent Height channel).
    std::array<TileHandle, 9> height{kNoTile, kNoTile, kNoTile, kNoTile, kNoTile,
                                     kNoTile, kNoTile, kNoTile, kNoTile};
    float heightConstant = 0.0f;
    /// The z of the height vector (height_to_normal.h HeightZ).
    float z = 0.390625f;
    /// The Normal channel's root list composited from a transparent start, before the read-out:
    /// a tile of the channel's tile format with its coverage plane, or a constant colour and
    /// coverage (an empty or absent channel: the flat colour at coverage 1).
    Operand normal = Operand::Constant({0.5f, 0.5f, 1.0f}, 1.0f);
    /// The bound Normal mesh map as UNORM operands (a three-channel 32-bit float tile), or the
    /// flat colour when none is bound.
    Operand mesh = Operand::Constant({0.5f, 0.5f, 1.0f}, 1.0f);
    /// The mesh map is in the DirectX convention (its decoded y is negated).
    bool meshDirectX = false;
    core::HeightToNormalMethod method = core::HeightToNormalMethod::Sharp;
    core::NormalMapFormat convention = core::NormalMapFormat::OpenGL;
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
    /// texel, as raw storage: samples of the tile's own encoding are copied (codes onto UNORM and
    /// sRGB8 tiles, half values onto 16-bit float tiles, floats onto 32-bit float tiles); 16-bit
    /// codes into a 32-bit float tile become float32(code / 65535). Any other combination fails
    /// with `evaluator:unsupported_source`. Bitmap sources are evaluated by `Project`, which
    /// applies the colour transfer of every channel format.
    virtual render::Result<void> Upload(TileHandle tile, const DecodedImage& image, uint32_t x0,
                                        uint32_t y0) = 0;

    /// Queues the UV projection of a bitmap into `op.dst` (projection_uv.h): every texel of the
    /// tile sampled with the projection's filter and wrap mode and stored with the channel's write
    /// rule; uncovered texels get coverage 0 when `op.dst` has a coverage plane. `Flush` runs it.
    virtual render::Result<void> Project(const ProjectOp& op) = 0;

    /// Queues one blend; `Flush` runs the queue.
    virtual render::Result<void> Blend(const BlendOp& op) = 0;

    /// Queues one Levels effect; `Flush` runs the queue.
    virtual render::Result<void> Levels(const LevelsOp& op) = 0;

    /// Queues one tile of a virtual normal map; `Flush` runs the queue.
    virtual render::Result<void> VirtualNormal(const VirtualNormalOp& op) = 0;

    /// Runs every queued operation and waits for it.
    virtual render::Result<void> Flush() = 0;

    /// Flushes, then returns the tile's texels.
    virtual render::Result<TileImage> Read(TileHandle tile) = 0;

    /// Bytes of every allocated tile.
    [[nodiscard]] virtual uint64_t AllocatedBytes() const = 0;
};

}  // namespace uzp::evaluator
