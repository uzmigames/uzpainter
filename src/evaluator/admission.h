#pragma once

// Memory admission of the compositor (docs/architecture/04-layer-stack-and-compositing.md §7,
// 13-engine-integration.md §6): live tiles x bytes per tile stay within the admission budget the
// render layer derives from the VRAM budget and the descriptor capacity. `TileCache` keeps every
// computed tile under that bound, keyed by (node, subtree hash, tile), evicting the least recently
// used unpinned tile when a new one needs room; `CheckTextureSet` refuses, at creation, a texture
// set whose own live tiles cannot fit.

#include "evaluator/formats.h"
#include "evaluator/hash.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"
#include "render/capabilities.h"

#include <cstdint>
#include <list>
#include <optional>
#include <span>
#include <unordered_map>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::render {
class DiskCache;
}

namespace uzp::evaluator {

/// The bound: live bytes and live tiles.
struct AdmissionLimits {
    uint64_t bytes = 0;
    uint64_t maxTiles = 0;

    friend bool operator==(const AdmissionLimits&, const AdmissionLimits&) = default;
};

/// The limits of the render layer's budget (13 §6).
[[nodiscard]] AdmissionLimits LimitsOf(const render::AdmissionBudget& budget);

/// Tiles the evaluation of one tile needs besides the cached results: the backdrop, the source
/// and the destination of one blend.
inline constexpr uint64_t kWorkingSetTiles = 3;

/// Bytes of the final tiles of every channel of a stack at `width` x `height` (its live tiles).
[[nodiscard]] uint64_t StackLiveBytes(uint32_t width, uint32_t height,
                                      std::span<const core::ChannelFormat> formats);
/// Tiles of the final results of every channel of a stack.
[[nodiscard]] uint64_t StackLiveTiles(uint32_t width, uint32_t height, size_t channels);
/// Bytes of the working set at `width` x `height`: `kWorkingSetTiles` tiles of the widest
/// format among `formats`, with the coverage plane.
[[nodiscard]] uint64_t WorkingSetBytes(uint32_t width, uint32_t height,
                                       std::span<const core::ChannelFormat> formats);

/// Admits a texture set whose stack has `formats` at `width` x `height`: its live tiles plus the
/// working set fit `limits`; `evaluator:texture_set_over_budget` (naming the bytes) otherwise.
[[nodiscard]] render::Result<void> CheckTextureSet(const AdmissionLimits& limits, uint32_t width,
                                                   uint32_t height,
                                                   std::span<const core::ChannelFormat> formats);
/// `CheckTextureSet` over every stack of `set`.
[[nodiscard]] render::Result<void> CheckTextureSet(const AdmissionLimits& limits,
                                                   const core::TextureSet& set);

/// What a cached tile is the output of.
enum class CacheKind : uint8_t {
    Content,  ///< A layer's content for one channel (a bitmap source tile).
    Prefix,   ///< The accumulator of a layer list after one of its layers (bottom-up).
    Readout,  ///< An isolated root list composited over the channel base (profile.h).
    Effect,   ///< A layer's content after one of its content effects (chained hash).
    Mask,     ///< A layer's mask after one of its effects or its geometry mask (chained hash).
};

struct CacheKey {
    core::Id node = core::kNoId;  ///< The layer or effect (Content, Effect, Mask) or the list owner (Prefix).
    CacheKind kind = CacheKind::Prefix;
    Digest hash{};  ///< The subtree hash (channel, format, profile included).
    uint32_t tileX = 0;
    uint32_t tileY = 0;

    friend bool operator==(const CacheKey&, const CacheKey&) = default;
};

struct CacheKeyHash {
    size_t operator()(const CacheKey& key) const noexcept {
        size_t value = DigestHash{}(key.hash);
        value ^= static_cast<size_t>(key.node) * 0x9E3779B97F4A7C15ull;
        value ^= (static_cast<size_t>(key.tileX) << 20) ^ static_cast<size_t>(key.tileY) ^
                 (static_cast<size_t>(key.kind) << 40);
        return value;
    }
};

struct CacheStats {
    uint64_t hits = 0;
    uint64_t misses = 0;
    uint64_t evictions = 0;
    uint64_t liveBytes = 0;
    uint64_t liveTiles = 0;
    uint64_t peakBytes = 0;
};

/// The tile cache: computed tiles by key, LRU eviction under the limits, pins for the tiles an
/// evaluation in progress holds (never evicted). Not synchronised: used by the thread that owns
/// the store (the engine thread for the GPU store).
class TileCache {
public:
    explicit TileCache(AdmissionLimits limits);

    /// The cached tile of `key`, pinned, or nullopt (a miss).
    [[nodiscard]] std::optional<TileHandle> Lookup(const CacheKey& key);

    /// A new tile for `key`, pinned, evicting unpinned tiles from the least recently used until
    /// it fits; `evaluator:tile_budget_exceeded` when the pinned tiles alone leave no room.
    [[nodiscard]] render::Result<TileHandle> Allocate(const CacheKey& key, const TileFormat& format,
                                                      uint32_t width, uint32_t height,
                                                      ITileStore& store);

    void Unpin(TileHandle tile);
    void UnpinAll();
    /// Releases every tile (nothing may be pinned).
    void Clear(ITileStore& store);

    [[nodiscard]] const CacheStats& stats() const { return stats_; }
    [[nodiscard]] const AdmissionLimits& limits() const { return limits_; }
    [[nodiscard]] bool Contains(const CacheKey& key) const { return entries_.contains(key); }

    /// The persistent results this cache's evaluations read and store (result_cache.h; the CPU
    /// evaluator's), or null.
    void SetPersistent(render::DiskCache* persistent) { persistent_ = persistent; }
    [[nodiscard]] render::DiskCache* persistent() const { return persistent_; }

private:
    struct Entry {
        CacheKey key;
        TileHandle tile = kNoTile;
        uint64_t bytes = 0;
        uint32_t pins = 0;
        std::list<TileHandle>::iterator recency;
    };

    bool EvictOne(ITileStore& store);

    AdmissionLimits limits_;
    CacheStats stats_;
    std::unordered_map<CacheKey, Entry, CacheKeyHash> entries_;
    std::unordered_map<TileHandle, CacheKey> keys_;
    std::list<TileHandle> recency_;  ///< Most recently used first.
    render::DiskCache* persistent_ = nullptr;
};

}  // namespace uzp::evaluator
