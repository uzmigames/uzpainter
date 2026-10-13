#pragma once

// The acceleration structure of the viewport's visibility rays (decision 251;
// docs/architecture/07-preview-and-render-parity.md §6): a bounding volume hierarchy over the
// world-space triangles of every texture set, built on the CPU and traversed by the
// `painter_viewport` kernel (shaders/viewport.hlsl) for its self-occlusion rays.
//
// - Build: binned surface-area heuristic (Wald 2007; Pharr, Jakob and Humphreys, PBRT 4th ed.
//   §7.3) on the triangles' centroids, `kBvhBins` bins per axis, in a deterministic order (the
//   lowest cost wins; on a tie the lower axis, then the lower plane; partitions are stable). A
//   node of at most `kBvhLeafSize` triangles, or at depth `kBvhMaxDepth`, is a leaf; so is a node
//   whose centroids all coincide and that fits a leaf, while a larger one is halved in order.
//   Boxes are the exact float bounds of their triangles' corners.
// - Layout (raw buffers, little-endian words): node i is `kBvhNodeWords` words: the box's
//   minimum xyz (float bits), then `first`, the box's maximum xyz, then `count`. An interior node
//   has count 0 and its children at `first` and `first + 1`; a leaf holds `count` triangles from
//   `first` of the occluder list. Node 0 is the root. Occluder j is `kOccluderWords` words:
//   corner 0 xyz, the triangle's index in the viewport's triangle order, corner 1 xyz, 0,
//   corner 2 xyz, 0.
// - Traversal stack: a node at depth d has at most d pending siblings, so a stack of
//   `kBvhMaxDepth` entries cannot overflow (the kernel's `BVH_STACK`).
// - Cache: `VisibilityBvhOf` keeps the last structures built, keyed by the world-space triangle
//   corners themselves (the mesh after its transforms and unit scale). The worker derives a new
//   mesh object for every evaluation; one of the same geometry reuses its structure, so the BVH
//   is rebuilt only when the geometry changes.

#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <vector>

namespace uzp::preview {

inline constexpr uint32_t kBvhMaxDepth = 32;
inline constexpr uint32_t kBvhLeafSize = 4;
inline constexpr uint32_t kBvhBins = 16;
inline constexpr uint32_t kBvhNodeWords = 8;
inline constexpr uint32_t kOccluderWords = 12;

struct VisibilityBvh {
    std::vector<uint32_t> nodes;
    std::vector<uint32_t> occluders;
    /// The deepest leaf's depth (the root is at depth 0).
    uint32_t depth = 0;
};

/// The BVH of the triangles of `corners`: nine floats per triangle (corner 0, 1 and 2 xyz) in the
/// viewport's triangle order. Empty for no triangles. `maxDepth` is the depth cap (tests lower it).
[[nodiscard]] VisibilityBvh BuildVisibilityBvh(std::span<const float> corners, uint32_t maxDepth = kBvhMaxDepth);

/// `BuildVisibilityBvh(corners)`, built once per distinct `corners` and shared (thread-safe).
[[nodiscard]] std::shared_ptr<const VisibilityBvh> VisibilityBvhOf(std::vector<float> corners);

/// How many structures `VisibilityBvhOf` has built in this process (tests: a cache hit builds none).
[[nodiscard]] uint64_t VisibilityBvhBuilds();

}  // namespace uzp::preview
