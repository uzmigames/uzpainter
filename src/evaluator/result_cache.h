#pragma once

// Persistent evaluation results (decision 253): what export and capture read from a CPU
// evaluation, kept across processes in the `eval` area of the disk caches (render/disk_cache.h).
//
// - The read-out of a channel whose root list is isolated and not empty (`EvaluateOn`): every
//   tile of `EvaluateChannel`, its texels as the store reads them back, tiles in its order.
// - The combined virtual normal (`EvaluateVirtualNormalOn`): float32 x 3 per texel.
//
// A key is the SHA-256 of the evaluator's own digest of the result (the read-out hash, or the
// virtual normal's, which chain the profile, channel, format, resolution, base and every
// evaluation-relevant field of the stack, bitmaps by content hash, geometry masks by mesh and
// query), the tile format and grid, the build fingerprint (`render::BuildFingerprint`) and the
// caller's MXCSR control bits (`render::FloatControlBits`). Only the CPU evaluator's tile cache
// carries the area (`CpuEvaluator`); the GPU evaluator never reads or writes it. A stored result
// is served only when every bitmap it was computed from is still available
// (`IResourceProvider::Available`) and, when it has a geometry mask, a geometry provider is given;
// otherwise the evaluation runs as without the cache, and fails as it would. An evaluator whose
// tile cache already holds the result reads it there and neither loads nor stores it.

#include "evaluator/dag.h"
#include "evaluator/evaluate.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/hash.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/resources.h"
#include "render/disk_cache.h"

#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace uzp::evaluator {

/// The cap of the `eval` area.
inline constexpr uint64_t kResultCacheBytes = 4ull << 30;

/// The `eval` area of the enabled caches, or null when they are off.
[[nodiscard]] render::DiskCache* PersistentResults();

/// The stored read-out of `dag` as `EvaluateChannel` returns it (its statistics count every tile
/// as a persistent hit), or nullopt: none stored, `dag` has no isolated root with layers, a bitmap
/// of `dag` is unavailable from `resources`, or `dag` has a geometry mask and `geometry` is null.
[[nodiscard]] std::optional<ChannelResult> LoadReadout(render::DiskCache& disk, const ChannelDag& dag,
                                                       const IResourceProvider* resources,
                                                       const IGeometryMaskProvider* geometry, const IProceduralSourceProvider* procedurals = nullptr);
/// Stores `result`, the evaluation of `dag`, when `dag` has an isolated root with layers.
void StoreReadout(render::DiskCache& disk, const ChannelDag& dag, const ChannelResult& result);

/// The stored texels of the combined virtual normal whose evaluator digest is `key` on a
/// `width` x `height` set, or nullopt: none stored, or the inputs of one of `dags` (its Height and
/// Normal channels) are not there (`LoadReadout`).
[[nodiscard]] std::optional<std::vector<float>> LoadVirtualNormal(render::DiskCache& disk, const Digest& key,
                                                                  uint32_t width, uint32_t height,
                                                                  std::span<const ChannelDag* const> dags,
                                                                  const IResourceProvider* resources,
                                                                  const IGeometryMaskProvider* geometry, const IProceduralSourceProvider* procedurals = nullptr);
/// Stores the texels of `result`, the combined virtual normal of digest `key`.
void StoreVirtualNormal(render::DiskCache& disk, const Digest& key, const VirtualNormalResult& result);

}  // namespace uzp::evaluator
