#include "evaluator/evaluate.h"

#include <cstring>
#include <memory>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/error.h"
#include "evaluator/projection_uv.h"

namespace uzp::evaluator {

namespace {

/// A normal-map bitmap as the Normal channel imports it: every green code c becomes max - c
/// (blend-modes.json `blend-normal-channel-import`). 8- and 16-bit codes only.
render::Result<std::shared_ptr<const DecodedImage>> GreenInverted(const DecodedImage& image, core::Id node) {
    if (image.channels < 3 || (image.encoding != render::TexelEncoding::Unorm16 &&
                               image.encoding != render::TexelEncoding::Unorm8)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "a Normal-channel bitmap must be an 8- or 16-bit RGB image", node);
    }
    const uint32_t max = image.encoding == render::TexelEncoding::Unorm16 ? 65535u : 255u;
    auto inverted = std::make_shared<DecodedImage>(image);
    for (size_t i = 1; i < inverted->values.size(); i += inverted->channels) {
        inverted->values[i] = max - inverted->values[i];
    }
    return std::shared_ptr<const DecodedImage>(std::move(inverted));
}

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
        if (!m_dag.root.isolated) {
            return EvaluateList(m_dag.root, Operand::Constant(m_dag.base, 1.0f), true);
        }
        if (m_dag.root.layers.empty()) return Operand::Constant(m_dag.base, 1.0f);
        // Isolated root (profile.h): the layers composite from a transparent start, then the
        // result is composited over the base once, v = base + (C - base) a, stored with the
        // channel's write rule (the Replace mix at opacity 1, whose alpha is the coverage).
        const CacheKey key{m_dag.root.owner, CacheKind::Readout, m_dag.readoutHash, m_tx, m_ty};
        render::Result<std::optional<TileHandle>> cached = Lookup(key);
        if (!cached) return render::Unexpected(cached.error());
        if (*cached) return Operand::Of(**cached);
        render::Result<Operand> stack =
            EvaluateList(m_dag.root, Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f), true);
        if (!stack) return stack;
        render::Result<TileHandle> dst = Allocate(key, m_dag.tileFormat);
        if (!dst) return render::Unexpected(dst.error());
        BlendOp op;
        op.dst = *dst;
        op.acc = Operand::Constant(m_dag.readoutBase, 1.0f);
        op.source = *stack;
        op.mode = core::BlendingMode::Replace;
        op.opacity = 1.0f;
        op.fusedReadout = m_dag.profile.fusedReadout;
        render::Result<void> queued = m_env.store.Blend(op);
        if (!queued) return render::Unexpected(queued.error());
        ++m_stats.blends;
        Defer(*stack);
        return Operand::Of(*dst);
    }

    /// The isolated root composited over `base` before the channel's write rule: a constant for
    /// an empty stack, else a 32-bit float tile (raw), which stays pinned after this evaluation.
    render::Result<Operand> RunFloat32Readout(const std::array<float, 3>& base) {
        if (!m_dag.root.isolated) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            "the float32 read-out needs a profile whose root list is isolated");
        }
        if (m_dag.root.layers.empty()) return Operand::Constant(base, 1.0f);
        HashWriter hash;
        hash.Sub(m_dag.readoutHash).Str("float32-readout").F32(base[0]).F32(base[1]).F32(base[2]);
        const CacheKey key{m_dag.root.owner, CacheKind::Readout, hash.Finish(), m_tx, m_ty};
        render::Result<std::optional<TileHandle>> cached = Lookup(key);
        if (!cached) return render::Unexpected(cached.error());
        if (*cached) return Keep(Operand::Of(**cached));
        render::Result<Operand> stack =
            EvaluateList(m_dag.root, Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f), true);
        if (!stack) return stack;
        TileFormat format;
        format.encoding = render::TexelEncoding::Float32;
        format.channels = m_dag.tileFormat.channels;
        render::Result<TileHandle> dst = Allocate(key, format);
        if (!dst) return render::Unexpected(dst.error());
        BlendOp op;
        op.dst = *dst;
        op.acc = Operand::Constant(base, 1.0f);
        op.source = *stack;
        op.mode = core::BlendingMode::Replace;
        op.opacity = 1.0f;
        op.fusedReadout = m_dag.profile.fusedReadout;
        op.rawOutput = true;
        render::Result<void> queued = m_env.store.Blend(op);
        if (!queued) return render::Unexpected(queued.error());
        ++m_stats.blends;
        Defer(*stack);
        return Keep(Operand::Of(*dst));
    }

    /// The isolated root list from a transparent start (EvaluateIsolatedRoot).
    render::Result<Operand> RunIsolatedRoot() {
        if (!m_dag.root.isolated) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            "the root list before its read-out needs a profile whose root list is isolated");
        }
        if (m_dag.root.layers.empty()) return Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f);
        render::Result<Operand> stack =
            EvaluateList(m_dag.root, Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f), true);
        if (!stack) return stack;
        return Keep(*stack);
    }

    /// The mask `layer` blends with on this tile (pinned until the end of the tile).
    render::Result<Operand> RunMask(const DagLayer& layer) { return MaskOf(layer); }

private:
    /// Takes `operand`'s pin out of this evaluation's hands: the caller unpins it.
    Operand Keep(const Operand& operand) {
        for (auto it = m_pinned.begin(); it != m_pinned.end(); ++it) {
            if (*it == operand.tile) {
                m_pinned.erase(it);
                break;
            }
        }
        return operand;
    }

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

    /// The source of a layer or fill effect: a constant, or its projected tile of `format`.
    render::Result<Operand> SourceOperand(core::Id node, const DagSource& source, TileFormat format) {
        if (source.kind == DagSource::Kind::Uniform) {
            return Operand::Constant(source.uniform, 1.0f);
        }
        const CacheKey key{node, CacheKind::Content, source.hash, m_tx, m_ty};
        render::Result<std::optional<TileHandle>> cached = Lookup(key);
        if (!cached) return render::Unexpected(cached.error());
        if (*cached) return Operand::Of(**cached);
        if (m_env.resources == nullptr) {
            return EvalFail(EvalErrorKind::MissingResource,
                            "no resource provider for bitmap " + source.sha256, node);
        }
        std::shared_ptr<const DecodedImage> image = m_env.resources->Fetch(source.sha256);
        if (!image) {
            return EvalFail(EvalErrorKind::MissingResource,
                            "bitmap " + source.sha256 + " is not available", node);
        }
        std::string imageKey = source.sha256;
        if (source.invertGreen) {
            imageKey += "/green-inverted";
            std::shared_ptr<const DecodedImage>& inverted = m_env.greenInverted[source.sha256];
            if (!inverted) {
                render::Result<std::shared_ptr<const DecodedImage>> made = GreenInverted(*image, node);
                if (!made) return render::Unexpected(made.error());
                inverted = *made;
            }
            image = inverted;
        }
        render::Result<void> sampling = CheckSampling(source.projection, m_dag.grid.width,
                                                      m_dag.grid.height, *image, node);
        if (!sampling) return render::Unexpected(sampling.error());
        // A wrap mode that can leave texels uncovered gives the content a coverage plane: the
        // fill keeps the value below there (resampling.json, RepeatNone).
        format.alpha = source.projection.MayUncover();
        return Projected(key, format, image, imageKey, source.projection, source.signedRange);
    }

    render::Result<Operand> Projected(const CacheKey& key, const TileFormat& format,
                                      std::shared_ptr<const DecodedImage> image, const std::string& imageKey,
                                      const UvProjection& projection, bool signedRange) {
        render::Result<TileHandle> tile = Allocate(key, format);
        if (!tile) return render::Unexpected(tile.error());
        ProjectOp op;
        op.dst = *tile;
        op.image = std::move(image);
        op.imageKey = imageKey;
        op.projection = projection;
        op.setWidth = m_dag.grid.width;
        op.setHeight = m_dag.grid.height;
        op.x0 = m_tx * kTileSize;
        op.y0 = m_ty * kTileSize;
        op.signedRange = signedRange;
        render::Result<void> projected = m_env.store.Project(op);
        if (!projected) return render::Unexpected(projected.error());
        ++m_stats.uploads;
        return Operand::Of(*tile);
    }

    /// A constant stored in `format` and read back (the operand a tile of it would hold).
    static std::array<float, 4> StoredConstant(const std::array<float, 4>& value, const TileFormat& format) {
        std::array<float, 4> out{0.0f, 0.0f, 0.0f, value[3]};
        for (uint32_t c = 0; c < format.channels; ++c) {
            out[c] = OperandOf(StoreValue(value[c], format, c), format, c);
        }
        return out;
    }

    /// Runs `effects` over `start` (a layer's content or a mask) in `format`, from the highest
    /// cached output up; each output is stored in `format` (whose coverage plane is the start's:
    /// levels keep it, a fill effect over a covered backdrop keeps full coverage) and cached
    /// under (`owner`, `kind`, the effect's chained hash).
    render::Result<Operand> RunEffects(core::Id owner, CacheKind kind, Operand start,
                                       const std::vector<DagEffect>& effects, TileFormat format) {
        Operand acc = start;
        size_t first = 0;
        for (size_t i = effects.size(); i > 0; --i) {
            const CacheKey key{owner, kind, effects[i - 1].hash, m_tx, m_ty};
            render::Result<std::optional<TileHandle>> cached = Lookup(key);
            if (!cached) return render::Unexpected(cached.error());
            if (*cached) {
                acc = Operand::Of(**cached);
                first = i;
                break;
            }
        }
        for (size_t i = first; i < effects.size(); ++i) {
            const DagEffect& effect = effects[i];
            const CacheKey key{owner, kind, effect.hash, m_tx, m_ty};
            if (effect.kind == DagEffect::Kind::Levels) {
                if (acc.kind == Operand::Kind::Constant) {
                    std::array<float, 4> value = acc.value;
                    for (uint32_t c = 0; c < format.channels; ++c) value[c] = arith::Levels(value[c], effect.levels[c]);
                    const std::array<float, 4> stored = StoredConstant(value, format);
                    acc = Operand::Constant({stored[0], stored[1], stored[2]}, stored[3]);
                    continue;
                }
                render::Result<TileHandle> dst = Allocate(key, format);
                if (!dst) return render::Unexpected(dst.error());
                LevelsOp op;
                op.dst = *dst;
                op.src = acc.tile;
                op.components = effect.levels;
                render::Result<void> queued = m_env.store.Levels(op);
                if (!queued) return render::Unexpected(queued.error());
                ++m_stats.levels;
                Defer(acc);
                acc = Operand::Of(*dst);
                continue;
            }
            render::Result<Operand> source = SourceOperand(effect.uid, *effect.source, format);
            if (!source) return source;
            if (acc.kind == Operand::Kind::Constant && source->kind == Operand::Kind::Constant) {
                arith::CompositeInput in;
                in.acc = acc.value;
                in.src = source->value;
                in.opacity = effect.opacity;
                in.mode = effect.mode;
                in.clampUnorm = format.IsUnorm();
                in.effectMix = true;
                in.channels = format.channels;
                const std::array<float, 4> stored = StoredConstant(arith::Composite(in), format);
                acc = Operand::Constant({stored[0], stored[1], stored[2]}, stored[3]);
                continue;
            }
            render::Result<TileHandle> dst = Allocate(key, format);
            if (!dst) return render::Unexpected(dst.error());
            BlendOp op;
            op.dst = *dst;
            op.acc = acc;
            op.source = *source;
            op.mode = effect.mode;
            op.opacity = effect.opacity;
            op.effectMix = true;
            render::Result<void> queued = m_env.store.Blend(op);
            if (!queued) return render::Unexpected(queued.error());
            ++m_stats.blends;
            Defer(acc);
            Defer(*source);
            acc = Operand::Of(*dst);
        }
        return acc;
    }

    render::Result<Operand> ContentOf(const DagLayer& layer) {
        render::Result<Operand> source = SourceOperand(layer.uid, *layer.source, m_dag.tileFormat);
        if (!source) return source;
        if (layer.effects.empty()) return source;
        TileFormat format = m_dag.tileFormat;
        format.alpha = layer.source->kind == DagSource::Kind::Bitmap && layer.source->projection.MayUncover();
        return RunEffects(layer.uid, CacheKind::Effect, *source, layer.effects, format);
    }

    /// The mask a layer blends with: its constant, or its mask raster (16 bits) after its effects
    /// and geometry mask.
    render::Result<Operand> MaskOf(const DagLayer& layer) {
        if (!layer.maskStack) return Operand::Constant({layer.mask, layer.mask, layer.mask}, 1.0f);
        const DagMask& mask = *layer.maskStack;
        const TileFormat format = TileFormatOf(kMaskFormat);
        if (mask.geometry) {
            const CacheKey key{layer.uid, CacheKind::Mask, mask.hash, m_tx, m_ty};
            render::Result<std::optional<TileHandle>> cached = Lookup(key);
            if (!cached) return render::Unexpected(cached.error());
            if (*cached) return Operand::Of(**cached);
        }
        const Operand background = Operand::Constant({mask.background, mask.background, mask.background}, 1.0f);
        render::Result<Operand> value = RunEffects(layer.uid, CacheKind::Mask, background, mask.effects, format);
        if (!value || !mask.geometry) return value;
        if (m_env.geometry == nullptr) {
            return EvalFail(EvalErrorKind::MissingResource, "no geometry mask provider", layer.uid);
        }
        std::shared_ptr<const DecodedImage> raster = m_env.geometry->Coverage(mask.geometry->query);
        if (!raster || raster->width != m_dag.grid.width || raster->height != m_dag.grid.height) {
            return EvalFail(EvalErrorKind::MissingResource, "the geometry mask raster is not available", layer.uid);
        }
        UvProjection identity;
        identity.filter = core::FilteringMode::Nearest;
        const CacheKey geometryKey{layer.uid, CacheKind::Content, mask.geometry->hash, m_tx, m_ty};
        render::Result<std::optional<TileHandle>> cachedGeometry = Lookup(geometryKey);
        if (!cachedGeometry) return render::Unexpected(cachedGeometry.error());
        Operand geometry;
        if (*cachedGeometry) {
            geometry = Operand::Of(**cachedGeometry);
        } else {
            const std::string imageKey = "geometry/" + Hex(mask.geometry->hash);
            render::Result<Operand> projected = Projected(geometryKey, format, raster, imageKey, identity, false);
            if (!projected) return projected;
            geometry = *projected;
        }
        // The geometry mask multiplies the mask (0 or 1: the effect mix keeps the product exact).
        const CacheKey key{layer.uid, CacheKind::Mask, mask.hash, m_tx, m_ty};
        render::Result<TileHandle> dst = Allocate(key, format);
        if (!dst) return render::Unexpected(dst.error());
        BlendOp op;
        op.dst = *dst;
        op.acc = *value;
        op.source = geometry;
        op.mode = core::BlendingMode::Multiply;
        op.effectMix = true;
        render::Result<void> queued = m_env.store.Blend(op);
        if (!queued) return render::Unexpected(queued.error());
        ++m_stats.blends;
        Defer(*value);
        Defer(geometry);
        return Operand::Of(*dst);
    }

    static bool SameTile(const Operand& a, const Operand& b) {
        return a.kind == Operand::Kind::Tile && b.kind == Operand::Kind::Tile && a.tile == b.tile;
    }

    /// `emptyStart`: `start` is the empty start of an isolated list (CompositeInput::emptyBackdrop);
    /// a PassThrough group's children start from the accumulator below the group, which is the
    /// empty start only where the group is the first layer of a list that starts empty.
    render::Result<Operand> EvaluateList(const DagList& list, const Operand& start, bool emptyStart) {
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
            // A PassThrough group's children start from this accumulator (kept pinned: the
            // group composite reads it again); any other group from a transparent start.
            render::Result<Operand> source =
                !layer.group ? ContentOf(layer)
                : layer.group->fromBackdrop
                    ? EvaluateList(*layer.group, acc, emptyStart && i == 0)
                    : EvaluateList(*layer.group, Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f), true);
            if (!source) return source;
            render::Result<Operand> mask = MaskOf(layer);
            if (!mask) return mask;
            render::Result<TileHandle> dst = Allocate(key, format);
            if (!dst) return render::Unexpected(dst.error());
            BlendOp op;
            op.dst = *dst;
            op.acc = acc;
            op.source = *source;
            op.mask = *mask;
            op.mode = layer.mode;
            op.opacity = layer.opacity;
            op.coverageWeights = m_dag.profile.coverageWeights;
            op.emptyBackdrop = emptyStart && i == 0;
            render::Result<void> queued = m_env.store.Blend(op);
            if (!queued) return render::Unexpected(queued.error());
            ++m_stats.blends;
            if (!list.fromBackdrop || !SameTile(acc, start)) Defer(acc);
            Defer(*source);
            Defer(*mask);
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

/// The read-out of a 32-bit float channel under a profile that blends the root layers over the
/// base (`RootComposite::OverBase`): every sample re-composited over the channel base once
/// (arith::Float32Readout; blend-modes.json "1 + (v - 1)"). The accumulator tiles stay raw, as
/// the blend fits read their backdrop. An isolated root is composited over the base by its
/// read-out blend instead (`TileEvaluation::Run`), which is this rule at full coverage.
void ReadOut(const ChannelDag& dag, TileResult& tile) {
    if (dag.tileFormat.encoding != render::TexelEncoding::Float32 || dag.root.isolated) return;
    const uint32_t channels = dag.tileFormat.channels;
    const size_t samples = tile.texels.size() / sizeof(float);
    for (size_t i = 0; i < samples; ++i) {
        float value = 0.0f;
        std::memcpy(&value, tile.texels.data() + i * sizeof(float), sizeof(float));
        value = arith::Float32Readout(value, dag.base[i % channels]);
        std::memcpy(tile.texels.data() + i * sizeof(float), &value, sizeof(float));
    }
}

}  // namespace

render::Result<Operand> EvaluateFloat32Readout(const ChannelDag& dag, EvalEnvironment& env, uint32_t tx,
                                               uint32_t ty, const std::array<float, 3>& base,
                                               EvaluationStats& stats) {
    TileEvaluation evaluation(dag, tx, ty, env, stats);
    return evaluation.RunFloat32Readout(base);
}

render::Result<Operand> EvaluateIsolatedRoot(const ChannelDag& dag, EvalEnvironment& env, uint32_t tx,
                                             uint32_t ty, EvaluationStats& stats) {
    TileEvaluation evaluation(dag, tx, ty, env, stats);
    return evaluation.RunIsolatedRoot();
}

render::Result<ChannelResult> EvaluateLayerMask(const ChannelDag& frame, const DagLayer& layer,
                                                EvalEnvironment& env) {
    ChannelResult result;
    result.channel = frame.channel;
    result.format = kMaskFormat;
    result.tileFormat = TileFormatOf(kMaskFormat);
    result.width = frame.grid.width;
    result.height = frame.grid.height;
    for (uint32_t ty = 0; ty < frame.grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < frame.grid.TilesX(); ++tx) {
            TileResult tile;
            tile.x0 = tx * kTileSize;
            tile.y0 = ty * kTileSize;
            tile.width = frame.grid.TileWidth(tx);
            tile.height = frame.grid.TileHeight(ty);
            ++result.stats.tiles;
            {
                TileEvaluation evaluation(frame, tx, ty, env, result.stats);
                render::Result<Operand> mask = evaluation.RunMask(layer);
                if (!mask) return render::Unexpected(mask.error());
                if (mask->kind == Operand::Kind::Constant) {
                    tile.constant = std::array<float, 3>{mask->value[0], mask->value[1], mask->value[2]};
                    ++result.stats.constantTiles;
                } else {
                    render::Result<TileImage> image = env.store.Read(mask->tile);
                    if (!image) return render::Unexpected(image.error());
                    tile.texels = std::move(image->texels);
                }
            }
            result.tiles.push_back(std::move(tile));
        }
    }
    return result;
}

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
                    ReadOut(dag, tile);
                }
            }
            result.tiles.push_back(std::move(tile));
        }
    }
    return result;
}

}  // namespace uzp::evaluator
