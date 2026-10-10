#include "evaluator/admission.h"

#include <algorithm>
#include <string>
#include <vector>

#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

TileGrid GridOf(uint32_t width, uint32_t height) { return TileGrid{width, height}; }

uint64_t TilesBytes(const TileFormat& format, const TileGrid& grid) {
    uint64_t bytes = 0;
    for (uint32_t ty = 0; ty < grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < grid.TilesX(); ++tx) {
            bytes += TileBytes(format, grid.TileWidth(tx), grid.TileHeight(ty));
        }
    }
    return bytes;
}

std::string Mebibytes(uint64_t bytes) {
    char buffer[48];
    std::snprintf(buffer, sizeof(buffer), "%.1f MiB", static_cast<double>(bytes) / (1024.0 * 1024.0));
    return buffer;
}

}  // namespace

AdmissionLimits LimitsOf(const render::AdmissionBudget& budget) {
    return {budget.bytes, budget.maxTilesByDescriptors};
}

uint64_t StackLiveBytes(uint32_t width, uint32_t height,
                        std::span<const core::ChannelFormat> formats) {
    const TileGrid grid = GridOf(width, height);
    uint64_t bytes = 0;
    for (const core::ChannelFormat format : formats) bytes += TilesBytes(TileFormatOf(format), grid);
    return bytes;
}

uint64_t StackLiveTiles(uint32_t width, uint32_t height, size_t channels) {
    return uint64_t{GridOf(width, height).Count()} * channels;
}

uint64_t WorkingSetBytes(uint32_t width, uint32_t height,
                         std::span<const core::ChannelFormat> formats) {
    const uint32_t tileWidth = std::min(width, kTileSize);
    const uint32_t tileHeight = std::min(height, kTileSize);
    uint64_t widest = 0;
    for (const core::ChannelFormat format : formats) {
        widest = std::max(widest, TileBytes(TileFormatOf(format, true), tileWidth, tileHeight));
    }
    return kWorkingSetTiles * widest;
}

render::Result<void> CheckTextureSet(const AdmissionLimits& limits, uint32_t width,
                                     uint32_t height,
                                     std::span<const core::ChannelFormat> formats) {
    const uint64_t live = StackLiveBytes(width, height, formats);
    const uint64_t working = WorkingSetBytes(width, height, formats);
    const uint64_t tiles = StackLiveTiles(width, height, formats.size()) + kWorkingSetTiles;
    if (live + working > limits.bytes) {
        return EvalFail(EvalErrorKind::TextureSetOverBudget,
                        "a " + std::to_string(width) + "x" + std::to_string(height) + " set with " +
                            std::to_string(formats.size()) + " channels needs " +
                            Mebibytes(live + working) + " of live tiles (" + Mebibytes(live) +
                            " results, " + Mebibytes(working) + " working set); the budget is " +
                            Mebibytes(limits.bytes));
    }
    if (tiles > limits.maxTiles) {
        return EvalFail(EvalErrorKind::TextureSetOverBudget,
                        "a " + std::to_string(width) + "x" + std::to_string(height) + " set with " +
                            std::to_string(formats.size()) + " channels needs " +
                            std::to_string(tiles) + " live tiles; the descriptor budget allows " +
                            std::to_string(limits.maxTiles));
    }
    return {};
}

render::Result<void> CheckTextureSet(const AdmissionLimits& limits, const core::TextureSet& set) {
    for (const core::Stack& stack : set.stacks) {
        std::vector<core::ChannelFormat> formats;
        for (const auto& [type, channel] : stack.channels) formats.push_back(channel.format);
        render::Result<void> ok = CheckTextureSet(
            limits, static_cast<uint32_t>(set.resolution.width),
            static_cast<uint32_t>(set.resolution.height), formats);
        if (!ok) return ok;
    }
    return {};
}

// ── TileCache ────────────────────────────────────────────────────────────────

TileCache::TileCache(AdmissionLimits limits) : limits_(limits) {}

std::optional<TileHandle> TileCache::Lookup(const CacheKey& key) {
    const auto it = entries_.find(key);
    if (it == entries_.end()) {
        ++stats_.misses;
        return std::nullopt;
    }
    Entry& entry = it->second;
    ++stats_.hits;
    ++entry.pins;
    recency_.splice(recency_.begin(), recency_, entry.recency);
    return entry.tile;
}

bool TileCache::EvictOne(ITileStore& store) {
    for (auto it = recency_.rbegin(); it != recency_.rend(); ++it) {
        const auto keyIt = keys_.find(*it);
        if (keyIt == keys_.end()) continue;
        const auto entryIt = entries_.find(keyIt->second);
        if (entryIt == entries_.end() || entryIt->second.pins != 0) continue;
        Entry entry = entryIt->second;
        store.Release(entry.tile);
        stats_.liveBytes -= entry.bytes;
        --stats_.liveTiles;
        ++stats_.evictions;
        recency_.erase(entry.recency);
        keys_.erase(entry.tile);
        entries_.erase(entryIt);
        return true;
    }
    return false;
}

render::Result<TileHandle> TileCache::Allocate(const CacheKey& key, const TileFormat& format,
                                               uint32_t width, uint32_t height,
                                               ITileStore& store) {
    if (const auto existing = entries_.find(key); existing != entries_.end()) {
        return EvalFail(EvalErrorKind::Internal, "a tile of this key is already cached", key.node);
    }
    const uint64_t bytes = TileBytes(format, width, height);
    while (stats_.liveBytes + bytes > limits_.bytes || stats_.liveTiles + 1 > limits_.maxTiles) {
        if (!EvictOne(store)) {
            return EvalFail(EvalErrorKind::TileBudgetExceeded,
                            "a " + std::to_string(width) + "x" + std::to_string(height) +
                                " tile of " + Mebibytes(bytes) + " does not fit: " +
                                std::to_string(stats_.liveTiles) + " pinned tiles hold " +
                                Mebibytes(stats_.liveBytes) + " of the " + Mebibytes(limits_.bytes) +
                                " budget (" + std::to_string(limits_.maxTiles) + " tiles)",
                            key.node);
        }
    }
    render::Result<TileHandle> tile = store.Allocate(format, width, height);
    if (!tile) return tile;
    Entry entry;
    entry.key = key;
    entry.tile = *tile;
    entry.bytes = bytes;
    entry.pins = 1;
    recency_.push_front(*tile);
    entry.recency = recency_.begin();
    entries_.emplace(key, entry);
    keys_.emplace(*tile, key);
    stats_.liveBytes += bytes;
    ++stats_.liveTiles;
    stats_.peakBytes = std::max(stats_.peakBytes, stats_.liveBytes);
    return *tile;
}

void TileCache::Unpin(TileHandle tile) {
    const auto keyIt = keys_.find(tile);
    if (keyIt == keys_.end()) return;
    const auto entryIt = entries_.find(keyIt->second);
    if (entryIt != entries_.end() && entryIt->second.pins > 0) --entryIt->second.pins;
}

void TileCache::UnpinAll() {
    for (auto& [key, entry] : entries_) entry.pins = 0;
}

void TileCache::Clear(ITileStore& store) {
    for (auto& [key, entry] : entries_) store.Release(entry.tile);
    entries_.clear();
    keys_.clear();
    recency_.clear();
    stats_.liveBytes = 0;
    stats_.liveTiles = 0;
}

}  // namespace uzp::evaluator
