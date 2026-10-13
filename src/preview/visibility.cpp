#include "preview/visibility.h"

#include <algorithm>
#include <atomic>
#include <bit>
#include <deque>
#include <limits>
#include <mutex>
#include <numeric>
#include <utility>

namespace uzp::preview {

namespace {

struct Box {
    std::array<float, 3> lo{std::numeric_limits<float>::max(), std::numeric_limits<float>::max(),
                            std::numeric_limits<float>::max()};
    std::array<float, 3> hi{-std::numeric_limits<float>::max(), -std::numeric_limits<float>::max(),
                            -std::numeric_limits<float>::max()};

    void Grow(const Box& other) {
        for (int a = 0; a < 3; ++a) {
            lo[a] = std::min(lo[a], other.lo[a]);
            hi[a] = std::max(hi[a], other.hi[a]);
        }
    }
    [[nodiscard]] bool Empty() const { return lo[0] > hi[0]; }
    /// Half the surface area (the heuristic only compares areas).
    [[nodiscard]] double HalfArea() const {
        if (Empty()) return 0.0;
        const double x = static_cast<double>(hi[0]) - lo[0];
        const double y = static_cast<double>(hi[1]) - lo[1];
        const double z = static_cast<double>(hi[2]) - lo[2];
        return x * y + y * z + z * x;
    }
};

struct Primitive {
    Box box;
    std::array<double, 3> centroid{};
};

struct Node {
    Box box;
    uint32_t first = 0;
    uint32_t count = 0;
};

class Builder {
public:
    Builder(std::span<const float> corners, uint32_t maxDepth, VisibilityBvh& out)
        : m_corners(corners), m_maxDepth(maxDepth), m_out(out) {
        const size_t triangles = corners.size() / 9;
        m_primitives.resize(triangles);
        for (size_t t = 0; t < triangles; ++t) {
            Primitive& p = m_primitives[t];
            for (int k = 0; k < 3; ++k) {
                for (int a = 0; a < 3; ++a) {
                    const float v = corners[t * 9 + static_cast<size_t>(k * 3 + a)];
                    p.box.lo[a] = std::min(p.box.lo[a], v);
                    p.box.hi[a] = std::max(p.box.hi[a], v);
                }
            }
            for (int a = 0; a < 3; ++a) {
                p.centroid[a] = (static_cast<double>(p.box.lo[a]) + p.box.hi[a]) / 2.0;
            }
        }
        m_order.resize(triangles);
        std::iota(m_order.begin(), m_order.end(), 0u);
    }

    void Run() {
        if (m_primitives.empty()) return;
        m_nodes.emplace_back();
        Build(0, 0, static_cast<uint32_t>(m_primitives.size()), 0);
        m_out.nodes.reserve(m_nodes.size() * kBvhNodeWords);
        for (const Node& node : m_nodes) {
            for (int a = 0; a < 3; ++a) m_out.nodes.push_back(std::bit_cast<uint32_t>(node.box.lo[a]));
            m_out.nodes.push_back(node.first);
            for (int a = 0; a < 3; ++a) m_out.nodes.push_back(std::bit_cast<uint32_t>(node.box.hi[a]));
            m_out.nodes.push_back(node.count);
        }
    }

private:
    void Leaf(uint32_t index, uint32_t begin, uint32_t end) {
        m_nodes[index].first = static_cast<uint32_t>(m_out.occluders.size() / kOccluderWords);
        m_nodes[index].count = end - begin;
        for (uint32_t i = begin; i < end; ++i) {
            const uint32_t t = m_order[i];
            for (int k = 0; k < 3; ++k) {
                for (int a = 0; a < 3; ++a) {
                    m_out.occluders.push_back(std::bit_cast<uint32_t>(m_corners[size_t{t} * 9 + static_cast<size_t>(k * 3 + a)]));
                }
                m_out.occluders.push_back(k == 0 ? t : 0u);
            }
        }
    }

    void Build(uint32_t index, uint32_t begin, uint32_t end, uint32_t depth) {
        Box box;
        for (uint32_t i = begin; i < end; ++i) box.Grow(m_primitives[m_order[i]].box);
        m_nodes[index].box = box;
        m_out.depth = std::max(m_out.depth, depth);
        const uint32_t count = end - begin;
        if (count <= kBvhLeafSize || depth >= m_maxDepth) {
            Leaf(index, begin, end);
            return;
        }

        std::array<double, 3> cLo{std::numeric_limits<double>::max(), std::numeric_limits<double>::max(),
                                  std::numeric_limits<double>::max()};
        std::array<double, 3> cHi{-cLo[0], -cLo[1], -cLo[2]};
        for (uint32_t i = begin; i < end; ++i) {
            const Primitive& p = m_primitives[m_order[i]];
            for (int a = 0; a < 3; ++a) {
                cLo[a] = std::min(cLo[a], p.centroid[a]);
                cHi[a] = std::max(cHi[a], p.centroid[a]);
            }
        }
        const auto binOf = [&](const Primitive& p, int axis) {
            const double extent = cHi[axis] - cLo[axis];
            const auto bin = static_cast<uint32_t>(kBvhBins * ((p.centroid[axis] - cLo[axis]) / extent));
            return std::min(bin, kBvhBins - 1);
        };

        // The binned surface-area heuristic: the plane after bin `plane` of `axis` with the lowest
        // cost (left count x left area + right count x right area).
        int bestAxis = -1;
        uint32_t bestPlane = 0;
        double bestCost = std::numeric_limits<double>::infinity();
        for (int axis = 0; axis < 3; ++axis) {
            if (!(cHi[axis] > cLo[axis])) continue;
            std::array<Box, kBvhBins> bins{};
            std::array<uint32_t, kBvhBins> counts{};
            for (uint32_t i = begin; i < end; ++i) {
                const Primitive& p = m_primitives[m_order[i]];
                const uint32_t bin = binOf(p, axis);
                bins[bin].Grow(p.box);
                ++counts[bin];
            }
            std::array<double, kBvhBins> rightCost{};
            Box right;
            uint32_t rightCount = 0;
            for (uint32_t b = kBvhBins - 1; b > 0; --b) {
                right.Grow(bins[b]);
                rightCount += counts[b];
                rightCost[b] = rightCount * right.HalfArea();
            }
            Box left;
            uint32_t leftCount = 0;
            for (uint32_t plane = 0; plane + 1 < kBvhBins; ++plane) {
                left.Grow(bins[plane]);
                leftCount += counts[plane];
                if (leftCount == 0 || leftCount == count) continue;
                const double cost = leftCount * left.HalfArea() + rightCost[plane + 1];
                if (cost < bestCost) {
                    bestCost = cost;
                    bestAxis = axis;
                    bestPlane = plane;
                }
            }
        }

        uint32_t middle = begin + count / 2;  // centroids that all coincide: halved in order
        if (bestAxis >= 0) {
            const auto split = std::stable_partition(m_order.begin() + begin, m_order.begin() + end, [&](uint32_t t) {
                return binOf(m_primitives[t], bestAxis) <= bestPlane;
            });
            middle = static_cast<uint32_t>(split - m_order.begin());
        }
        const auto left = static_cast<uint32_t>(m_nodes.size());
        m_nodes.emplace_back();
        m_nodes.emplace_back();
        m_nodes[index].first = left;
        m_nodes[index].count = 0;
        Build(left, begin, middle, depth + 1);
        Build(left + 1, middle, end, depth + 1);
    }

    std::span<const float> m_corners;
    uint32_t m_maxDepth;
    VisibilityBvh& m_out;
    std::vector<Primitive> m_primitives;
    std::vector<uint32_t> m_order;
    std::vector<Node> m_nodes;
};

struct CacheEntry {
    std::vector<float> corners;
    std::shared_ptr<const VisibilityBvh> bvh;
};

/// The structures kept: the preview window and a capture may show two meshes at once.
constexpr size_t kCacheEntries = 2;

std::mutex g_cacheMutex;
std::deque<CacheEntry> g_cache;  // most recently used first
std::atomic<uint64_t> g_builds{0};

}  // namespace

VisibilityBvh BuildVisibilityBvh(std::span<const float> corners, uint32_t maxDepth) {
    VisibilityBvh bvh;
    Builder(corners, std::min(maxDepth, kBvhMaxDepth), bvh).Run();
    return bvh;
}

std::shared_ptr<const VisibilityBvh> VisibilityBvhOf(std::vector<float> corners) {
    {
        std::lock_guard lock(g_cacheMutex);
        for (auto it = g_cache.begin(); it != g_cache.end(); ++it) {
            // Compared bit for bit: the structure depends on the exact float corners.
            if (it->corners.size() == corners.size() &&
                std::equal(it->corners.begin(), it->corners.end(), corners.begin(),
                           [](float a, float b) { return std::bit_cast<uint32_t>(a) == std::bit_cast<uint32_t>(b); })) {
                CacheEntry entry = std::move(*it);
                g_cache.erase(it);
                g_cache.push_front(std::move(entry));
                return g_cache.front().bvh;
            }
        }
    }
    auto bvh = std::make_shared<const VisibilityBvh>(BuildVisibilityBvh(corners));
    ++g_builds;
    std::lock_guard lock(g_cacheMutex);
    g_cache.push_front(CacheEntry{std::move(corners), bvh});
    while (g_cache.size() > kCacheEntries) g_cache.pop_back();
    return bvh;
}

uint64_t VisibilityBvhBuilds() { return g_builds; }

}  // namespace uzp::preview
