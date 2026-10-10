#include "evaluator/evaluate.h"

#include <string>

#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

/// One tile evaluation: pins, deferred unpins and the retry that flushes the store when the
/// budget is full of tiles whose operations are only queued.
class TileEvaluation {
public:
    TileEvaluation(const ChannelDag& dag, uint32_t tx, uint32_t ty, EvalEnvironment& env,
                   EvaluationStats& stats)
        : m_dag(dag), m_tx(tx), m_ty(ty), m_env(env), m_stats(stats),
          m_width(dag.grid.TileWidth(tx)), m_height(dag.grid.TileHeight(ty)) {}

    ~TileEvaluation() {
        for (const TileHandle tile : m_pinned) m_env.cache.Unpin(tile);
        for (const TileHandle tile : m_deferred) m_env.cache.Unpin(tile);
    }

    render::Result<Operand> Run() {
        return EvaluateList(m_dag.root, Operand::Constant(m_dag.base, 1.0f));
    }

private:
    render::Result<std::optional<TileHandle>> Lookup(const CacheKey& key) {
        const uint64_t evictionsBefore = m_env.cache.stats().evictions;
        std::optional<TileHandle> tile = m_env.cache.Lookup(key);
        m_stats.evictions += m_env.cache.stats().evictions - evictionsBefore;
        if (tile) {
            ++m_stats.cacheHits;
            m_pinned.push_back(*tile);
        } else {
            ++m_stats.cacheMisses;
        }
        return tile;
    }

    /// A new cached tile; when the budget holds only pinned tiles, the queued operations are run
    /// so the tiles they read can be released, then the allocation is retried once.
    render::Result<TileHandle> Allocate(const CacheKey& key, const TileFormat& format) {
        const uint64_t evictionsBefore = m_env.cache.stats().evictions;
        render::Result<TileHandle> tile =
            m_env.cache.Allocate(key, format, m_width, m_height, m_env.store);
        if (!tile && EvalErrorKindOf(tile.error()) == EvalErrorKind::TileBudgetExceeded &&
            !m_deferred.empty()) {
            render::Result<void> flushed = m_env.store.Flush();
            if (!flushed) return render::Unexpected(flushed.error());
            ++m_stats.flushes;
            for (const TileHandle deferred : m_deferred) m_env.cache.Unpin(deferred);
            m_deferred.clear();
            tile = m_env.cache.Allocate(key, format, m_width, m_height, m_env.store);
        }
        m_stats.evictions += m_env.cache.stats().evictions - evictionsBefore;
        if (!tile) return tile;
        m_pinned.push_back(*tile);
        return tile;
    }

    /// Marks a pinned input as done once the operation reading it is queued; it is unpinned at
    /// the end of the tile, or earlier when a flush makes room.
    void Defer(const Operand& operand) {
        if (operand.kind != Operand::Kind::Tile) return;
        for (auto it = m_pinned.begin(); it != m_pinned.end(); ++it) {
            if (*it == operand.tile) {
                m_pinned.erase(it);
                m_deferred.push_back(operand.tile);
                return;
            }
        }
    }

    render::Result<Operand> ContentOf(const DagLayer& layer) {
        const DagSource& source = *layer.source;
        if (source.kind == DagSource::Kind::Uniform) {
            return Operand::Constant(source.uniform, 1.0f);
        }
        const CacheKey key{layer.uid, CacheKind::Content, source.hash, m_tx, m_ty};
        render::Result<std::optional<TileHandle>> cached = Lookup(key);
        if (!cached) return render::Unexpected(cached.error());
        if (*cached) return Operand::Of(**cached);
        if (m_env.resources == nullptr) {
            return EvalFail(EvalErrorKind::MissingResource,
                            "no resource provider for bitmap " + source.sha256, layer.uid);
        }
        std::shared_ptr<const DecodedImage> image = m_env.resources->Fetch(source.sha256);
        if (!image) {
            return EvalFail(EvalErrorKind::MissingResource,
                            "bitmap " + source.sha256 + " is not available", layer.uid);
        }
        render::Result<TileHandle> tile = Allocate(key, m_dag.tileFormat);
        if (!tile) return render::Unexpected(tile.error());
        render::Result<void> uploaded =
            m_env.store.Upload(*tile, *image, m_tx * kTileSize, m_ty * kTileSize);
        if (!uploaded) return render::Unexpected(uploaded.error());
        ++m_stats.uploads;
        return Operand::Of(*tile);
    }

    render::Result<Operand> EvaluateList(const DagList& list, Operand start) {
        Operand acc = start;
        TileFormat format = m_dag.tileFormat;
        format.alpha = list.isolated;
        // The highest cached prefix, searched from the top: everything below it is served by
        // that one tile, everything above it is computed.
        size_t first = 0;
        for (size_t i = list.layers.size(); i > 0; --i) {
            const DagLayer& layer = list.layers[i - 1];
            const CacheKey key{list.owner, CacheKind::Prefix, layer.prefixHash, m_tx, m_ty};
            render::Result<std::optional<TileHandle>> cached = Lookup(key);
            if (!cached) return render::Unexpected(cached.error());
            if (*cached) {
                acc = Operand::Of(**cached);
                first = i;
                break;
            }
        }
        for (size_t i = first; i < list.layers.size(); ++i) {
            const DagLayer& layer = list.layers[i];
            const CacheKey key{list.owner, CacheKind::Prefix, layer.prefixHash, m_tx, m_ty};
            render::Result<Operand> source =
                layer.group ? EvaluateList(*layer.group, Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f))
                            : ContentOf(layer);
            if (!source) return source;
            render::Result<TileHandle> dst = Allocate(key, format);
            if (!dst) return render::Unexpected(dst.error());
            BlendOp op;
            op.dst = *dst;
            op.acc = acc;
            op.source = *source;
            op.mask = Operand::Constant({layer.mask, layer.mask, layer.mask}, 1.0f);
            op.mode = layer.mode;
            op.opacity = layer.opacity;
            op.storeBase = list.isolated ? std::array<float, 3>{0.0f, 0.0f, 0.0f} : m_dag.base;
            render::Result<void> queued = m_env.store.Blend(op);
            if (!queued) return render::Unexpected(queued.error());
            ++m_stats.blends;
            Defer(acc);
            Defer(*source);
            acc = Operand::Of(*dst);
        }
        return acc;
    }

    const ChannelDag& m_dag;
    uint32_t m_tx;
    uint32_t m_ty;
    EvalEnvironment& m_env;
    EvaluationStats& m_stats;
    uint32_t m_width;
    uint32_t m_height;
    std::vector<TileHandle> m_pinned;
    std::vector<TileHandle> m_deferred;
};

}  // namespace

render::Result<ChannelResult> EvaluateChannel(const ChannelDag& dag, EvalEnvironment& env) {
    ChannelResult result;
    result.channel = dag.channel;
    result.format = dag.format;
    result.tileFormat = dag.tileFormat;
    result.width = dag.grid.width;
    result.height = dag.grid.height;
    for (uint32_t ty = 0; ty < dag.grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < dag.grid.TilesX(); ++tx) {
            TileResult tile;
            tile.x0 = tx * kTileSize;
            tile.y0 = ty * kTileSize;
            tile.width = dag.grid.TileWidth(tx);
            tile.height = dag.grid.TileHeight(ty);
            ++result.stats.tiles;
            {
                TileEvaluation evaluation(dag, tx, ty, env, result.stats);
                render::Result<Operand> output = evaluation.Run();
                if (!output) return render::Unexpected(output.error());
                if (output->kind == Operand::Kind::Constant) {
                    tile.constant = std::array<float, 3>{output->value[0], output->value[1],
                                                         output->value[2]};
                    ++result.stats.constantTiles;
                } else {
                    render::Result<TileImage> image = env.store.Read(output->tile);
                    if (!image) return render::Unexpected(image.error());
                    tile.texels = std::move(image->texels);
                }
            }
            result.tiles.push_back(std::move(tile));
        }
    }
    return result;
}

}  // namespace uzp::evaluator
