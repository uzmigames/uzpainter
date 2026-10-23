#include "evaluator/result_cache.h"

#include <cstring>
#include <set>
#include <string>

namespace uzp::evaluator {

namespace {

/// The layout of the payloads and the composition of the keys below.
constexpr uint32_t kResultsVersion = 1;

/// Every bitmap a list's layers read (their sources, their content effects' and their mask
/// effects' sources, and those of their groups) into `bitmaps`; true when one of them has a
/// geometry mask.
bool CollectInputs(const DagList& list, std::set<std::string>& bitmaps) {
    bool geometry = false;
    auto source = [&](const std::optional<DagSource>& s) {
        if (s && s->kind == DagSource::Kind::Bitmap) bitmaps.insert(s->sha256);
    };
    for (const DagLayer& layer : list.layers) {
        source(layer.source);
        for (const DagEffect& effect : layer.effects) source(effect.source);
        if (layer.maskStack) {
            for (const DagEffect& effect : layer.maskStack->effects) source(effect.source);
            geometry = geometry || layer.maskStack->geometry.has_value();
        }
        if (layer.group) geometry = CollectInputs(*layer.group, bitmaps) || geometry;
    }
    return geometry;
}

/// What the evaluation of `dags` reads from outside them is there: every bitmap is available from
/// `resources` and, when a layer has a geometry mask, `geometry` is given. Otherwise the stored
/// result is not served and the evaluation fails as it would without it.
bool InputsAvailable(std::span<const ChannelDag* const> dags, const IResourceProvider* resources,
                     const IGeometryMaskProvider* geometry, const IProceduralSourceProvider* procedurals) {
    std::set<std::string> bitmaps;
    bool masks = false;
    for (const ChannelDag* dag : dags) {
        if (dag != nullptr) {
            if (!ProceduralInputsAvailable(*dag, procedurals)) return false;
            masks = CollectInputs(dag->root, bitmaps) || masks;
        }
    }
    if (masks && geometry == nullptr) return false;
    if (bitmaps.empty()) return true;
    if (resources == nullptr) return false;
    for (const std::string& sha256 : bitmaps) {
        if (!resources->Available(sha256)) return false;
    }
    return true;
}

bool Persists(const ChannelDag& dag) { return dag.root.isolated && !dag.root.layers.empty(); }

void Seed(HashWriter& writer, std::string_view kind) {
    writer.Str(kind).U32(kResultsVersion).Str(render::BuildFingerprint()).U32(render::FloatControlBits());
}

render::CacheKey ReadoutKey(const ChannelDag& dag) {
    HashWriter writer;
    Seed(writer, "uzp-eval-readout");
    writer.Sub(dag.readoutHash).Str(dag.profile.id);
    writer.U32(static_cast<uint32_t>(dag.channel)).U32(static_cast<uint32_t>(dag.format));
    const TileFormat& format = dag.tileFormat;
    writer.U32(static_cast<uint32_t>(format.encoding)).U32(format.channels);
    writer.Bool(format.srgb).Bool(format.alpha).Bool(format.halfCoverage).Bool(format.halfCoverageFromHalf);
    writer.U32(dag.grid.width).U32(dag.grid.height).U32(kTileSize);
    return writer.Finish();
}

render::CacheKey VirtualNormalKey(const Digest& key, uint32_t width, uint32_t height) {
    HashWriter writer;
    Seed(writer, "uzp-eval-virtual-normal");
    writer.Sub(key).U32(width).U32(height);
    return writer.Finish();
}

/// Bytes of the texels of one tile as `TileImage` holds them.
uint64_t TileBytes(const ChannelDag& dag, uint32_t tx, uint32_t ty) {
    return uint64_t{dag.grid.TileWidth(tx)} * dag.grid.TileHeight(ty) * dag.tileFormat.channels *
           dag.tileFormat.BytesPerChannel();
}

}  // namespace

render::DiskCache* PersistentResults() { return render::CacheArea("eval", kResultCacheBytes); }

std::optional<ChannelResult> LoadReadout(render::DiskCache& disk, const ChannelDag& dag,
                                         const IResourceProvider* resources, const IGeometryMaskProvider* geometry, const IProceduralSourceProvider* procedurals) {
    if (!Persists(dag)) return std::nullopt;
    uint64_t size = 0;
    for (uint32_t ty = 0; ty < dag.grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < dag.grid.TilesX(); ++tx) size += TileBytes(dag, tx, ty);
    }
    std::optional<std::vector<std::byte>> payload = disk.Get(ReadoutKey(dag), size);
    if (!payload) return std::nullopt;
    const ChannelDag* dags[] = {&dag};
    if (!InputsAvailable(dags, resources, geometry, procedurals)) return std::nullopt;
    ChannelResult result;
    result.channel = dag.channel;
    result.format = dag.format;
    result.tileFormat = dag.tileFormat;
    result.width = dag.grid.width;
    result.height = dag.grid.height;
    size_t offset = 0;
    for (uint32_t ty = 0; ty < dag.grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < dag.grid.TilesX(); ++tx) {
            TileResult tile;
            tile.x0 = tx * kTileSize;
            tile.y0 = ty * kTileSize;
            tile.width = dag.grid.TileWidth(tx);
            tile.height = dag.grid.TileHeight(ty);
            const size_t bytes = static_cast<size_t>(TileBytes(dag, tx, ty));
            tile.texels.assign(payload->begin() + static_cast<std::ptrdiff_t>(offset),
                               payload->begin() + static_cast<std::ptrdiff_t>(offset + bytes));
            offset += bytes;
            result.tiles.push_back(std::move(tile));
            ++result.stats.tiles;
            ++result.stats.cacheHits;
            ++result.stats.persistentHits;
        }
    }
    return result;
}

void StoreReadout(render::DiskCache& disk, const ChannelDag& dag, const ChannelResult& result) {
    if (!Persists(dag) || result.tiles.size() != dag.grid.Count()) return;
    std::vector<std::byte> payload;
    for (size_t i = 0; i < result.tiles.size(); ++i) {
        const TileResult& tile = result.tiles[i];
        const uint32_t tx = static_cast<uint32_t>(i % dag.grid.TilesX());
        const uint32_t ty = static_cast<uint32_t>(i / dag.grid.TilesX());
        // An isolated root with layers reads back every tile; anything else is not this layout.
        if (tile.constant || tile.texels.size() != TileBytes(dag, tx, ty)) return;
        payload.insert(payload.end(), tile.texels.begin(), tile.texels.end());
    }
    disk.Put(ReadoutKey(dag), payload);
}

std::optional<std::vector<float>> LoadVirtualNormal(render::DiskCache& disk, const Digest& key, uint32_t width,
                                                    uint32_t height, std::span<const ChannelDag* const> dags,
                                                    const IResourceProvider* resources,
                                                    const IGeometryMaskProvider* geometry, const IProceduralSourceProvider* procedurals) {
    const uint64_t texels = uint64_t{width} * height * 3;
    std::optional<std::vector<std::byte>> payload =
        disk.Get(VirtualNormalKey(key, width, height), texels * sizeof(float));
    if (!payload || !InputsAvailable(dags, resources, geometry, procedurals)) return std::nullopt;
    std::vector<float> values(static_cast<size_t>(texels));
    std::memcpy(values.data(), payload->data(), payload->size());
    return values;
}

void StoreVirtualNormal(render::DiskCache& disk, const Digest& key, const VirtualNormalResult& result) {
    if (result.texels.size() != size_t{result.width} * result.height * 3) return;
    disk.Put(VirtualNormalKey(key, result.width, result.height),
             std::as_bytes(std::span<const float>(result.texels)));
}

}  // namespace uzp::evaluator
