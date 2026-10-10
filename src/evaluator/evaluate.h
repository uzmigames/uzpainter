#pragma once

// Running a channel DAG (dag.h) on a tile store (tile_store.h) under the tile cache
// (admission.h): per tile, bottom-up through the layer lists, serving every node output whose
// (node, subtree hash, tile) is cached and computing the rest; results are read back at native
// precision. Backend-neutral: the GPU store runs it on the engine thread (evaluator.h), the CPU
// store anywhere.

#include "evaluator/admission.h"
#include "evaluator/dag.h"
#include "evaluator/resources.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace uzp::evaluator {

struct EvaluationStats {
    uint64_t tiles = 0;          ///< Tiles of the channel.
    uint64_t constantTiles = 0;  ///< Tiles whose result is the base constant (no layer).
    uint64_t cacheHits = 0;      ///< Node outputs served from the cache.
    uint64_t cacheMisses = 0;    ///< Node outputs computed.
    uint64_t blends = 0;         ///< Blend operations run.
    uint64_t uploads = 0;        ///< Bitmap windows uploaded.
    uint64_t evictions = 0;      ///< Tiles evicted during the evaluation.
    uint64_t flushes = 0;        ///< Store flushes forced by the budget.
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
};

/// Evaluates every tile of `dag`, reading each back. Nothing stays pinned afterwards; the
/// computed tiles stay cached.
[[nodiscard]] render::Result<ChannelResult> EvaluateChannel(const ChannelDag& dag,
                                                            EvalEnvironment& env);

}  // namespace uzp::evaluator
