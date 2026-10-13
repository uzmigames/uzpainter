#pragma once

// Running a channel DAG (dag.h) on a tile store (tile_store.h) under the tile cache
// (admission.h): per tile, bottom-up through the layer lists, serving every node output whose
// (node, subtree hash, tile) is cached and computing the rest; results are read back at native
// precision. A layer's content runs through its content effects and its mask through its mask
// effects and geometry mask, each chain served from its highest cached output; effects on
// constants (uniform sources, backgrounds) are folded on the CPU with the same arithmetic. Backend-neutral: the GPU store runs it on the engine thread (evaluator.h), the CPU
// store anywhere.

#include "evaluator/admission.h"
#include "evaluator/dag.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/resources.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace uzp::evaluator {

struct EvaluationStats {
    uint64_t tiles = 0;          ///< Tiles of the channel.
    uint64_t constantTiles = 0;  ///< Tiles whose result is the base constant (no layer).
    uint64_t cacheHits = 0;      ///< Node outputs served from the cache.
    uint64_t cacheMisses = 0;    ///< Node outputs computed.
    uint64_t blends = 0;         ///< Blend operations run (layers, read-outs and fill effects).
    uint64_t levels = 0;         ///< Levels operations run on tiles.
    uint64_t uploads = 0;        ///< Bitmap tiles projected (bitmap content computed).
    uint64_t evictions = 0;      ///< Tiles evicted during the evaluation.
    uint64_t flushes = 0;        ///< Store flushes forced by the budget.
    uint64_t persistentHits = 0; ///< Tiles served from the persistent results (result_cache.h).
};

/// One tile of a channel result: the base constant (an empty stack) or the texels of the tile
/// as the store holds them (`TileImage` layout: `channels` channels per texel).
struct TileResult {
    uint32_t x0 = 0;
    uint32_t y0 = 0;
    uint32_t width = 0;
    uint32_t height = 0;
    std::optional<std::array<float, 3>> constant;
    std::vector<std::byte> texels;
};

struct ChannelResult {
    core::ChannelType channel = core::ChannelType::BaseColor;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    TileFormat tileFormat;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<TileResult> tiles;
    EvaluationStats stats;
};

struct EvalEnvironment {
    ITileStore& store;
    TileCache& cache;
    /// May be null when the DAG has no bitmap source.
    const IResourceProvider* resources = nullptr;
    /// May be null when the DAG has no geometry mask (geometry_mask.h).
    const IGeometryMaskProvider* geometry = nullptr;
    /// Normal-channel bitmaps as the 16-bit textures the channel samples (its import rule,
    /// evaluate.cpp `NormalTexture`), by resource hash, made once per evaluation.
    std::unordered_map<std::string, std::shared_ptr<const DecodedImage>> normalTextures{};
    /// sRGB bitmaps as the float32 linear images Painter samples (sources.h), by resource hash
    /// (suffixed `/l8` for the decode of an L8 BaseColor, Specular or Emissive), made once per
    /// evaluation.
    std::unordered_map<std::string, std::shared_ptr<const DecodedImage>> srgbDecoded{};
    /// 8-bit Raw bitmaps under OCIO as the float32 images Painter samples (sources.h), by resource
    /// hash, made once per evaluation.
    std::unordered_map<std::string, std::shared_ptr<const DecodedImage>> ocioRawDecoded{};
    /// Colour bitmaps read by a one-channel tile as the R16F grey textures Painter samples
    /// (decision 218), by image key, made once per evaluation.
    std::unordered_map<std::string, std::shared_ptr<const DecodedImage>> greyTextures{};
};

/// Evaluates every tile of `dag`, reading each back. The root meets the base as the profile says
/// (profile.h): an isolated root is composited over the base by one read-out blend per tile;
/// under `RootComposite::OverBase` 32-bit float channels are re-composited over their base once
/// at read-out (arith::Float32Readout). Nothing stays pinned afterwards; the computed tiles stay
/// cached.
[[nodiscard]] render::Result<ChannelResult> EvaluateChannel(const ChannelDag& dag,
                                                            EvalEnvironment& env);

/// The mask of `layer` (BuildLayerMask) over the set of `frame`, tile by tile: its constant or its
/// 16-bit raster as the layer blends with it, computed and cached by the same mask chain as a
/// channel evaluation (the tiles one serves the other). The result's format is `kMaskFormat`
/// (one channel); its `channel` is `frame`'s, which the mask does not depend on.
[[nodiscard]] render::Result<ChannelResult> EvaluateLayerMask(const ChannelDag& frame, const DagLayer& layer,
                                                              EvalEnvironment& env);

/// The read-out of tile (`tx`, `ty`) before the channel's write rule (the virtual normal maps'
/// input, height_to_normal.h): the isolated root composited over `base` in float32, a constant
/// for an empty stack, else a raw 32-bit float tile of the channel's channel count, cached and
/// left pinned in `env.cache` for the caller to unpin. Fails with `unsupported_source` under a
/// profile whose root is not isolated.
[[nodiscard]] render::Result<Operand> EvaluateFloat32Readout(const ChannelDag& dag,
                                                             EvalEnvironment& env, uint32_t tx,
                                                             uint32_t ty,
                                                             const std::array<float, 3>& base,
                                                             EvaluationStats& stats);

/// The isolated root list of tile (`tx`, `ty`) composited from a transparent start, before its
/// read-out (the Normal channel's input of the virtual normal maps, height_to_normal.h): a tile
/// of the channel's tile format with its coverage plane, cached and left pinned in `env.cache`
/// for the caller to unpin, or the transparent constant for an empty stack. Fails with
/// `unsupported_source` under a profile whose root is not isolated.
[[nodiscard]] render::Result<Operand> EvaluateIsolatedRoot(const ChannelDag& dag, EvalEnvironment& env,
                                                           uint32_t tx, uint32_t ty, EvaluationStats& stats);

}  // namespace uzp::evaluator
