#include "export/padding.h"

#include "evaluator/hwmath.h"
#include "export/encode.h"
#include "mesh/texturing_mesh.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <functional>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace uzp::exporter {

namespace {

/// The owner of padding on UV-islanded sets (decisions 103, 245 and 259).
constexpr std::string_view kIslandsOwner = "owner phase1.25_pilot-wand item 2.7";

[[noreturn]] void Unfitted(const PlannedFile& file, const std::string& what,
                           std::string_view owner = kProcessingRecording) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(owner) + ")");
}

/// A channel reading a combined virtual normal.
bool ChannelReadsCombinedNormal(const PlannedChannel& channel) { return ReadsCombinedNormal(channel.source); }

// The 8-neighbours as (dy, dx), in scan order.
constexpr std::array<std::array<int, 2>, 8> kNeighbours{
    {{-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}}};
// The jump flood's offsets per step as (dy, dx), in the order they are tried (decision 197).
constexpr std::array<std::array<int, 2>, 8> kFloodOffsets{
    {{0, 1}, {0, -1}, {-1, 0}, {1, 0}, {-1, 1}, {1, -1}, {-1, -1}, {1, 1}}};

// The ring's code levels (decision 268): level l codes a share of at least 1 / k on `levels` steps.
struct CodeLevel {
    int k = 0;
    int levels = 0;
};
constexpr std::array<CodeLevel, 3> kCodeLevels{{{4, 1023}, {3, 255}, {2, 63}}};
// At most 4 taps (decision 270); a measurement sees the 8 nearest candidates.
constexpr size_t kMaxTaps = 4;
constexpr size_t kKeptCandidates = 8;
// Distances this close (relative) are equal shares, ordered by the comparator (decision 267).
constexpr double kEqualShare = 1e-9;
// A nearest candidate this close (relative to the nearest covered neighbour) is at distance 0.
constexpr double kZeroDistance = 1e-6;
// The far window: the texels within this many far texels of the unfolded ring point (decision 268).
constexpr int kFarReach = 3;
// Two triangles are coplanar (one planar face) within this relative tolerance.
constexpr double kCoplanar = 1e-6;

using Vec3 = std::array<double, 3>;

Vec3 Sub(const Vec3& a, const Vec3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
Vec3 Add(const Vec3& a, const Vec3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
Vec3 Scale(const Vec3& a, double s) { return {a[0] * s, a[1] * s, a[2] * s}; }
double Dot(const Vec3& a, const Vec3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Vec3 Cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
double Norm(const Vec3& a) { return std::sqrt(Dot(a, a)); }
Vec3 Unit(const Vec3& a) { return Scale(a, 1.0 / Norm(a)); }

/// A triangle of the set, as the ring kernel reads it.
struct KernelTriangle {
    std::array<Vec3, 3> p{};                        // 3D position
    std::array<std::array<double, 2>, 3> t{};       // texel space (u W, (1 - v) H): centres at + 1/2
    std::array<uint32_t, 3> vertex{};               // the position's identity (its value)
    std::array<uint32_t, 3> corner{};               // the (position, UV) pair's identity
    std::array<std::array<float, 2>, 3> raster{};   // the comparator's float32 (u W, (1 - v) H)
    std::array<std::array<float, 3>, 3> normalised{};  // the comparator's mesh-box-normalised position
    uint32_t chart = 0;                             // UV island: triangles joined by shared UV edges
    uint32_t face = 0;                              // planar face: coplanar triangles joined by 3D edges
};

/// Barycentrics of the texel-space point (x, y) in `k` (double).
std::array<double, 3> TexelBary(const KernelTriangle& k, double x, double y) {
    const auto& a = k.t[0];
    const auto& b = k.t[1];
    const auto& c = k.t[2];
    const double area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const double l1 = ((x - a[0]) * (c[1] - a[1]) - (y - a[1]) * (c[0] - a[0])) / area;
    const double l2 = ((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) / area;
    return {1.0 - l1 - l2, l1, l2};
}

Vec3 Point(const KernelTriangle& k, const std::array<double, 3>& l) {
    return Add(Add(Scale(k.p[0], l[0]), Scale(k.p[1], l[1])), Scale(k.p[2], l[2]));
}

/// The texel-space point of the 3D point `q` of `k`'s plane.
std::array<double, 2> TexelOf(const KernelTriangle& k, const Vec3& q) {
    const Vec3 e1 = Sub(k.p[1], k.p[0]);
    const Vec3 e2 = Sub(k.p[2], k.p[0]);
    const Vec3 v = Sub(q, k.p[0]);
    const double a = Dot(e1, e1);
    const double b = Dot(e1, e2);
    const double c = Dot(e2, e2);
    const double det = a * c - b * b;
    const double l1 = (c * Dot(e1, v) - b * Dot(e2, v)) / det;
    const double l2 = (a * Dot(e2, v) - b * Dot(e1, v)) / det;
    const double l0 = 1.0 - l1 - l2;
    return {l0 * k.t[0][0] + l1 * k.t[1][0] + l2 * k.t[2][0], l0 * k.t[0][1] + l1 * k.t[1][1] + l2 * k.t[2][1]};
}

/// The rotation about a 3D edge shared by two triangles that takes the other triangle's side of
/// the edge onto the own plane, on the far side of the edge (decision 270).
struct Hinge {
    Vec3 a{};
    Vec3 e{};        // unit, along the edge
    Vec3 inOwn{};    // unit, from the edge toward the own triangle, in its plane
    Vec3 inOther{};  // unit, from the edge toward the other triangle, in its plane
};

Vec3 Across(const Vec3& from, const Vec3& to, const Vec3& e) {
    const Vec3 v = Sub(to, from);
    return Unit(Sub(v, Scale(e, Dot(v, e))));
}

/// The hinge of `own` and `other` about their shared edge (va, vb), by position identity.
Hinge MakeHinge(const KernelTriangle& own, const KernelTriangle& other, uint32_t va, uint32_t vb) {
    const auto local = [](const KernelTriangle& k, uint32_t v) {
        return static_cast<size_t>(std::find(k.vertex.begin(), k.vertex.end(), v) - k.vertex.begin());
    };
    const size_t ia = local(own, va);
    const size_t ib = local(own, vb);
    const size_t ja = local(other, va);
    const size_t jb = local(other, vb);
    Hinge h;
    h.a = own.p[ia];
    h.e = Unit(Sub(own.p[ib], h.a));
    h.inOwn = Across(h.a, own.p[3 - ia - ib], h.e);
    h.inOther = Across(h.a, other.p[3 - ja - jb], h.e);
    return h;
}

/// `p`, a point on the other triangle's side, rotated onto the own plane's far side.
Vec3 Unfold(const Hinge& h, const Vec3& p) {
    const Vec3 v = Sub(p, h.a);
    const double s = Dot(v, h.e);
    const Vec3 r = Sub(v, Scale(h.e, s));
    const Vec3 to = Scale(h.inOwn, -1.0);
    const double along = Dot(r, h.inOther);
    const double out = Dot(r, Cross(h.e, h.inOther));
    return Add(Add(h.a, Scale(h.e, s)), Add(Scale(to, along), Scale(Cross(h.e, to), out)));
}

/// The inverse of Unfold: a point on the own plane's far side, onto the other triangle's plane.
Vec3 Fold(const Hinge& h, const Vec3& p) {
    const Vec3 v = Sub(p, h.a);
    const double s = Dot(v, h.e);
    const Vec3 r = Sub(v, Scale(h.e, s));
    const Vec3 to = Scale(h.inOwn, -1.0);
    const double along = Dot(r, to);
    const double out = Dot(r, Cross(h.e, to));
    return Add(Add(h.a, Scale(h.e, s)), Add(Scale(h.inOther, along), Scale(Cross(h.e, h.inOther), out)));
}

uint32_t Find(std::vector<uint32_t>& parent, uint32_t i) {
    while (parent[i] != i) i = parent[i] = parent[parent[i]];
    return i;
}

/// The coverage's triangles, their islands and planar faces, and the triangle covering each
/// covered texel (the first in mesh order, as the coverage rasterises them).
class RingGeometry {
public:
    explicit RingGeometry(const Coverage& coverage);

    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<KernelTriangle> triangles;
    std::vector<int32_t> owner;  // per texel: the covering triangle, -1 when uncovered
    std::map<std::pair<uint32_t, uint32_t>, std::vector<uint32_t>> edges;  // sorted vertex pair -> triangles

    /// `p`, a point of triangle `k`, in tau's frame: as it is in tau's planar face, rotated about
    /// an edge shared by the two faces, else as it is.
    Vec3 Frame(const Vec3& p, uint32_t k, uint32_t tau) const;

private:
    std::vector<std::vector<uint32_t>> m_faces;
    mutable std::map<std::pair<uint32_t, uint32_t>, std::optional<Hinge>> m_hinges;
};

RingGeometry::RingGeometry(const Coverage& coverage) : width(coverage.width), height(coverage.height) {
    if (coverage.triangles.empty()) {
        throw std::invalid_argument("export: the measured infinite padding needs the texture set's triangles");
    }
    const double w = width;
    const double h = height;
    const float fw = static_cast<float>(width);
    const float fh = static_cast<float>(height);
    // The mesh box (decision 261): c = float32 centre, half = float32 half of the largest extent.
    std::array<float, 3> centre{};
    double extent = 0.0;
    for (size_t c = 0; c < 3; ++c) {
        centre[c] = static_cast<float>((static_cast<double>(coverage.boxMin[c]) + coverage.boxMax[c]) / 2.0);
        extent = std::max(extent, static_cast<double>(coverage.boxMax[c]) - coverage.boxMin[c]);
    }
    const float half = static_cast<float>(extent / 2.0);
    std::map<std::array<uint32_t, 3>, uint32_t> vertices;
    std::map<std::array<uint32_t, 3>, uint32_t> corners;
    std::vector<int32_t> index(coverage.triangles.size(), -1);
    for (size_t i = 0; i < coverage.triangles.size(); ++i) {
        const IslandTriangle& source = coverage.triangles[i];
        const auto& uv = source.uv;
        const double area = (static_cast<double>(uv[1][0]) - uv[0][0]) * (static_cast<double>(uv[2][1]) - uv[0][1]) -
                            (static_cast<double>(uv[1][1]) - uv[0][1]) * (static_cast<double>(uv[2][0]) - uv[0][0]);
        if (area == 0.0) continue;  // covers nothing, as in the coverage
        KernelTriangle k;
        for (size_t c = 0; c < 3; ++c) {
            const auto& p = source.position[c];
            k.p[c] = {p[0], p[1], p[2]};
            k.t[c] = {uv[c][0] * w, (1.0 - static_cast<double>(uv[c][1])) * h};
            k.raster[c] = {uv[c][0] * fw, (1.0f - uv[c][1]) * fh};
            for (size_t d = 0; d < 3; ++d) k.normalised[c][d] = p[d] / half - centre[d] / half;
            const std::array<uint32_t, 3> bits{std::bit_cast<uint32_t>(p[0]), std::bit_cast<uint32_t>(p[1]),
                                               std::bit_cast<uint32_t>(p[2])};
            k.vertex[c] = vertices.try_emplace(bits, static_cast<uint32_t>(vertices.size())).first->second;
            const std::array<uint32_t, 3> corner{k.vertex[c], std::bit_cast<uint32_t>(uv[c][0]),
                                                 std::bit_cast<uint32_t>(uv[c][1])};
            k.corner[c] = corners.try_emplace(corner, static_cast<uint32_t>(corners.size())).first->second;
        }
        index[i] = static_cast<int32_t>(triangles.size());
        triangles.push_back(k);
    }
    const auto count = static_cast<uint32_t>(triangles.size());
    for (uint32_t i = 0; i < count; ++i) {
        for (size_t e = 0; e < 3; ++e) {
            const uint32_t a = triangles[i].vertex[(e + 1) % 3];
            const uint32_t b = triangles[i].vertex[(e + 2) % 3];
            edges[{std::min(a, b), std::max(a, b)}].push_back(i);
        }
    }
    // Islands (shared UV edges) and planar faces (coplanar triangles sharing a 3D edge).
    std::vector<uint32_t> chart(count);
    std::vector<uint32_t> face(count);
    std::iota(chart.begin(), chart.end(), 0u);
    std::iota(face.begin(), face.end(), 0u);
    const auto cornerAt = [&](const KernelTriangle& k, uint32_t v) {
        return k.corner[static_cast<size_t>(std::find(k.vertex.begin(), k.vertex.end(), v) - k.vertex.begin())];
    };
    const auto coplanar = [&](const KernelTriangle& a, const KernelTriangle& b) {
        const Vec3 na = Cross(Sub(a.p[1], a.p[0]), Sub(a.p[2], a.p[0]));
        const Vec3 nb = Cross(Sub(b.p[1], b.p[0]), Sub(b.p[2], b.p[0]));
        const double la = Norm(na);
        const double lb = Norm(nb);
        if (la == 0.0 || lb == 0.0) return false;
        if (Norm(Cross(na, nb)) > kCoplanar * la * lb) return false;
        return std::abs(Dot(na, Sub(b.p[0], a.p[0]))) / la <= kCoplanar * std::sqrt(la);
    };
    for (const auto& [key, list] : edges) {
        for (size_t i = 0; i < list.size(); ++i) {
            for (size_t j = i + 1; j < list.size(); ++j) {
                const KernelTriangle& a = triangles[list[i]];
                const KernelTriangle& b = triangles[list[j]];
                if (cornerAt(a, key.first) == cornerAt(b, key.first) && cornerAt(a, key.second) == cornerAt(b, key.second)) {
                    chart[Find(chart, list[i])] = Find(chart, list[j]);
                }
                if (coplanar(a, b)) face[Find(face, list[i])] = Find(face, list[j]);
            }
        }
    }
    std::map<uint32_t, uint32_t> faceIndex;
    for (uint32_t i = 0; i < count; ++i) {
        triangles[i].chart = Find(chart, i);
        const auto [it, added] = faceIndex.try_emplace(Find(face, i), static_cast<uint32_t>(m_faces.size()));
        if (added) m_faces.emplace_back();
        triangles[i].face = it->second;
        m_faces[it->second].push_back(i);
    }
    // The covering triangle of each texel, by the coverage's own test (evaluator/geometry_mask.cpp).
    owner.assign(size_t{width} * height, -1);
    for (size_t i = 0; i < coverage.triangles.size(); ++i) {
        if (index[i] < 0) continue;
        const auto& uv = coverage.triangles[i].uv;
        std::array<std::array<double, 2>, 3> p{};
        for (size_t c = 0; c < 3; ++c) p[c] = {static_cast<double>(uv[c][0]), static_cast<double>(uv[c][1])};
        const auto cross = [](const std::array<double, 2>& a, const std::array<double, 2>& b, double u, double v) {
            return (b[0] - a[0]) * (v - a[1]) - (b[1] - a[1]) * (u - a[0]);
        };
        const double area = cross(p[0], p[1], p[2][0], p[2][1]);
        const double colLo = std::max(0.0, std::floor(std::min({p[0][0], p[1][0], p[2][0]}) * w - 0.5));
        const double colHi = std::min(w - 1.0, std::ceil(std::max({p[0][0], p[1][0], p[2][0]}) * w - 0.5));
        const double rowLo = std::max(0.0, std::floor((1.0 - std::max({p[0][1], p[1][1], p[2][1]})) * h - 0.5));
        const double rowHi = std::min(h - 1.0, std::ceil((1.0 - std::min({p[0][1], p[1][1], p[2][1]})) * h - 0.5));
        for (double row = rowLo; row <= rowHi; row += 1.0) {
            for (double col = colLo; col <= colHi; col += 1.0) {
                const double u = (col + 0.5) / w;
                const double v = 1.0 - (row + 0.5) / h;
                const double w0 = cross(p[0], p[1], u, v);
                const double w1 = cross(p[1], p[2], u, v);
                const double w2 = cross(p[2], p[0], u, v);
                const bool inside = area > 0.0 ? (w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0) : (w0 <= 0.0 && w1 <= 0.0 && w2 <= 0.0);
                const size_t t = static_cast<size_t>(row) * width + static_cast<size_t>(col);
                if (inside && owner[t] < 0) owner[t] = index[i];
            }
        }
    }
    for (size_t t = 0; t < owner.size(); ++t) {
        if ((owner[t] >= 0) != (coverage.covered[t] != 0)) {
            throw std::invalid_argument("export: the coverage is not its triangles' texel-centre coverage");
        }
    }
}

Vec3 RingGeometry::Frame(const Vec3& p, uint32_t k, uint32_t tau) const {
    const uint32_t from = triangles[k].face;
    const uint32_t to = triangles[tau].face;
    if (from == to) return p;
    const auto [it, added] = m_hinges.try_emplace({to, from});
    if (added) {
        for (const uint32_t i : m_faces[to]) {
            for (size_t e = 0; e < 3 && !it->second; ++e) {
                const uint32_t a = triangles[i].vertex[(e + 1) % 3];
                const uint32_t b = triangles[i].vertex[(e + 2) % 3];
                for (const uint32_t j : edges.at({std::min(a, b), std::max(a, b)})) {
                    if (triangles[j].face != from) continue;
                    it->second = MakeHinge(triangles[i], triangles[j], a, b);
                    break;
                }
            }
            if (it->second) break;
        }
    }
    return it->second ? Unfold(*it->second, p) : p;
}

/// The recording GPU's float32 distance of decision 267's comparator from the ring texel (rx, ry)
/// to the tap (tx, ty) of triangle `k`: both points interpolated in `k` (edge-function
/// barycentrics in raster space, fma(l2, P2, fma(l0, P0, l1 P1))) over the mesh-box-normalised
/// positions, the squared distance by FMA, then the GPU's square root.
float CompareDistance(const KernelTriangle& k, uint32_t rx, uint32_t ry, uint32_t tx, uint32_t ty) {
    const auto position = [&](uint32_t x, uint32_t y) {
        const float pu = static_cast<float>(x) + 0.5f;
        const float pv = static_cast<float>(y) + 0.5f;
        const auto& r = k.raster;
        const auto edge = [&](const std::array<float, 2>& p, const std::array<float, 2>& q) {
            const float a = (q[0] - p[0]) * (pv - p[1]);
            const float b = (q[1] - p[1]) * (pu - p[0]);
            return a - b;
        };
        const float a0 = (r[1][0] - r[0][0]) * (r[2][1] - r[0][1]);
        const float a1 = (r[1][1] - r[0][1]) * (r[2][0] - r[0][0]);
        const float area = a0 - a1;
        const float l0 = edge(r[1], r[2]) / area;
        const float l1 = edge(r[2], r[0]) / area;
        const float l2 = edge(r[0], r[1]) / area;
        std::array<float, 3> out{};
        for (size_t c = 0; c < 3; ++c) {
            const auto& n = k.normalised;
            out[c] = std::fma(l2, n[2][c], std::fma(l0, n[0][c], l1 * n[1][c]));
        }
        return out;
    };
    const std::array<float, 3> q = position(rx, ry);
    const std::array<float, 3> p = position(tx, ty);
    const float dx = q[0] - p[0];
    const float dy = q[1] - p[1];
    const float dz = q[2] - p[2];
    return evaluator::hw::Sqrt(std::fma(dz, dz, std::fma(dy, dy, dx * dx)));
}

struct Candidate {
    RingTap tap;
    size_t texel = 0;
    uint32_t triangle = 0;
};

/// The candidates of ring texel (x, y) with q extrapolated through `tau`, in tap order: nearest
/// first, equal distances by the comparator (own taps), then toward +u, +v.
std::vector<Candidate> Candidates(const RingGeometry& g, uint32_t x, uint32_t y, const std::vector<size_t>& own,
                                  uint32_t tau) {
    const KernelTriangle& T = g.triangles[tau];
    const std::array<double, 3> l = TexelBary(T, x + 0.5, y + 0.5);
    const Vec3 q = Point(T, l);
    std::vector<Candidate> out;
    const auto add = [&](size_t texel, bool far) {
        const auto k = static_cast<uint32_t>(g.owner[texel]);
        const auto tx = static_cast<uint32_t>(texel % g.width);
        const auto ty = static_cast<uint32_t>(texel / g.width);
        const Vec3 p = g.Frame(Point(g.triangles[k], TexelBary(g.triangles[k], tx + 0.5, ty + 0.5)), k, tau);
        out.push_back({{tx, ty, Norm(Sub(q, p)), far}, texel, k});
    };
    for (const size_t texel : own) add(texel, false);
    // Across each UV seam edge q lies beyond: the far island's covered texels around q unfolded.
    for (size_t i = 0; i < 3; ++i) {
        if (!(l[i] < 0.0)) continue;
        const uint32_t va = T.vertex[(i + 1) % 3];
        const uint32_t vb = T.vertex[(i + 2) % 3];
        const auto ca = T.corner[(i + 1) % 3];
        const auto cb = T.corner[(i + 2) % 3];
        for (const uint32_t j : g.edges.at({std::min(va, vb), std::max(va, vb)})) {
            const KernelTriangle& J = g.triangles[j];
            const auto at = [&](uint32_t v) {
                return J.corner[static_cast<size_t>(std::find(J.vertex.begin(), J.vertex.end(), v) - J.vertex.begin())];
            };
            if (j == tau || (at(va) == ca && at(vb) == cb)) continue;  // the same island across the edge
            const std::array<double, 2> far = TexelOf(J, Fold(MakeHinge(T, J, va, vb), q));
            const auto col0 = static_cast<int64_t>(std::floor(far[0] - 0.5));
            const auto row0 = static_cast<int64_t>(std::floor(far[1] - 0.5));
            for (int64_t row = row0 - kFarReach + 1; row <= row0 + kFarReach; ++row) {
                for (int64_t col = col0 - kFarReach + 1; col <= col0 + kFarReach; ++col) {
                    if (row < 0 || col < 0 || row >= g.height || col >= g.width) continue;
                    const size_t texel = static_cast<size_t>(row) * g.width + static_cast<size_t>(col);
                    const int32_t k = g.owner[texel];
                    if (k < 0 || g.triangles[static_cast<size_t>(k)].chart != J.chart) continue;
                    if (std::any_of(out.begin(), out.end(), [&](const Candidate& c) { return c.texel == texel; })) continue;
                    add(texel, true);
                }
            }
        }
    }
    std::sort(out.begin(), out.end(), [](const Candidate& a, const Candidate& b) {
        return a.tap.distance != b.tap.distance ? a.tap.distance < b.tap.distance : a.texel < b.texel;
    });
    for (size_t first = 0; first < out.size();) {
        size_t last = first + 1;
        while (last < out.size() && out[last].tap.distance <= out[first].tap.distance * (1.0 + kEqualShare)) ++last;
        if (last - first > 1) {
            std::vector<std::pair<float, Candidate>> group;
            for (size_t i = first; i < last; ++i) {
                const Candidate& c = out[i];
                group.emplace_back(c.tap.far ? 0.0f : CompareDistance(g.triangles[c.triangle], x, y, c.tap.x, c.tap.y), c);
            }
            std::stable_sort(group.begin(), group.end(), [](const auto& a, const auto& b) {
                if (a.second.tap.far != b.second.tap.far) return !a.second.tap.far;
                if (a.first != b.first) return a.first < b.first;
                if (a.second.tap.x != b.second.tap.x) return a.second.tap.x > b.second.tap.x;
                return a.second.tap.y < b.second.tap.y;
            });
            for (size_t i = first; i < last; ++i) out[i] = group[i - first].second;
        }
        first = last;
    }
    if (out.size() > kKeptCandidates) out.resize(kKeptCandidates);
    return out;
}

/// The chain's fractions over the first `n` candidates (decision 268).
std::vector<float> Fractions(const std::vector<RingTap>& taps, uint32_t n) {
    std::vector<float> t;
    for (uint32_t level = 0; level + 1 < n; ++level) {
        double sum = 0.0;
        for (uint32_t j = level; j < n; ++j) sum += 1.0 / taps[j].distance;
        const double share = (1.0 / taps[level].distance) / sum;
        const auto [k, levels] = kCodeLevels[level];
        const double u = std::clamp(std::nearbyint((share - 1.0 / k) * k / (k - 1) * levels), 0.0, static_cast<double>(levels));
        t.push_back(static_cast<float>((levels + (k - 1) * u) / (static_cast<double>(k) * levels)));
    }
    return t;
}

std::vector<RingTap> Taps(const std::vector<Candidate>& candidates) {
    std::vector<RingTap> out;
    for (const Candidate& c : candidates) out.push_back(c.tap);
    return out;
}

/// The value of the chain over `v` (the taps' values in tap order) with fractions `t`, rounded
/// through 1 - (1 - m) (decision 206).
float Chain(const std::array<float, kMaxTaps>& v, uint32_t n, const std::vector<float>& t) {
    float m = v[0];
    if (n > 1) {
        const float last = 1.0f - t[n - 2];
        m = std::fma(last, v[n - 1] - v[n - 2], v[n - 2]);
        for (uint32_t level = n - 2; level-- > 0;) m = std::fma(t[level], v[level] - m, m);
    }
    const float complement = 1.0f - m;
    return 1.0f - complement;
}

/// The ring of the measured `infinite` padding over `coverage` (padding.h).
std::vector<RingTexel> RingOf(const Coverage& coverage) {
    const RingGeometry g(coverage);
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    std::vector<RingTexel> ring;
    std::vector<size_t> own;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (coverage.covered[static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x)] != 0) continue;
            own.clear();
            for (const auto& [dy, dx] : kNeighbours) {
                const int yy = y + dy;
                const int xx = ((x + dx) % width + width) % width;
                if (yy < 0 || yy >= height) continue;
                const size_t texel = static_cast<size_t>(yy) * coverage.width + static_cast<size_t>(xx);
                if (coverage.covered[texel] != 0) own.push_back(texel);
            }
            if (own.empty()) continue;
            std::vector<uint32_t> triangles;
            for (const size_t texel : own) triangles.push_back(static_cast<uint32_t>(g.owner[texel]));
            std::sort(triangles.begin(), triangles.end(), std::greater<>());
            triangles.erase(std::unique(triangles.begin(), triangles.end()), triangles.end());
            const auto rx = static_cast<uint32_t>(x);
            const auto ry = static_cast<uint32_t>(y);
            RingTexel r;
            r.x = rx;
            r.y = ry;
            r.triangles = static_cast<uint32_t>(triangles.size());
            r.candidates = Taps(Candidates(g, rx, ry, own, triangles[0]));
            double nearest = std::numeric_limits<double>::infinity();
            for (const RingTap& tap : r.candidates) {
                if (!tap.far) nearest = std::min(nearest, tap.distance);
            }
            r.taps = r.candidates[0].distance > kZeroDistance * nearest
                         ? static_cast<uint32_t>(std::min(kMaxTaps, r.candidates.size()))
                         : 1u;
            r.fractions = Fractions(r.candidates, r.taps);
            for (size_t i = 1; i < triangles.size(); ++i) {
                r.alternatives.push_back(Taps(Candidates(g, rx, ry, own, triangles[i])));
            }
            ring.push_back(std::move(r));
        }
    }
    return ring;
}


// `infinite` padding over incomplete coverage (padding.h): the ring, then the jump flood.
void InfinitePadding(const Coverage& coverage, uint32_t channels, std::vector<float>& values) {
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    if (channels == 0 || channels > 4 || values.size() != size_t{coverage.width} * coverage.height * channels) {
        throw std::invalid_argument("export: infinite padding takes 1 to 4 values per texel");
    }
    const std::vector<uint8_t>& covered = coverage.covered;
    const auto index = [&](auto y, auto x) { return static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x); };
    const auto copy = [&](size_t from, size_t to) {
        std::copy_n(values.begin() + static_cast<std::ptrdiff_t>(from * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(to * channels));
    };
    // 1. The ring, from the covered texels only.
    std::vector<uint8_t> seed(covered);
    const std::vector<RingTexel> ringTexels = RingOf(coverage);
    std::vector<float> ring;
    ring.reserve(ringTexels.size() * channels);
    for (const RingTexel& r : ringTexels) {
        for (uint32_t c = 0; c < channels; ++c) {
            std::array<float, kMaxTaps> v{};
            for (uint32_t i = 0; i < r.taps; ++i) {
                v[i] = values[index(r.candidates[i].y, r.candidates[i].x) * channels + c];
            }
            ring.push_back(Chain(v, r.taps, r.fractions));
        }
    }
    for (size_t i = 0; i < ringTexels.size(); ++i) {
        const size_t texel = index(ringTexels[i].y, ringTexels[i].x);
        std::copy_n(ring.begin() + static_cast<std::ptrdiff_t>(i * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(texel * channels));
        seed[texel] = 1;
    }
    // 2. The jump flood over the covered and ring texels; each step reads the previous step's seeds.
    const size_t texels = size_t{coverage.width} * coverage.height;
    std::vector<int32_t> seedY(texels, -1);
    std::vector<int32_t> seedX(texels, -1);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (seed[index(y, x)] != 0) {
                seedY[index(y, x)] = y;
                seedX[index(y, x)] = x;
            }
        }
    }
    const auto distance = [](int32_t sy, int32_t sx, int y, int x) {
        if (sy < 0) return std::numeric_limits<int64_t>::max();
        const int64_t dy = sy - y;
        const int64_t dx = sx - x;
        return dy * dy + dx * dx;
    };
    std::vector<int32_t> nextY(texels);
    std::vector<int32_t> nextX(texels);
    for (int k = std::max(width, height) / 2; k >= 1; k /= 2) {
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const size_t t = index(y, x);
                int32_t bestY = seedY[t];
                int32_t bestX = seedX[t];
                int64_t best = distance(bestY, bestX, y, x);
                for (const auto& [dy, dx] : kFloodOffsets) {
                    const int yy = y + dy * k;
                    const int xx = x + dx * k;
                    if (yy < 0 || yy >= height || xx < 0 || xx >= width) continue;
                    const size_t from = index(yy, xx);
                    const int64_t d = distance(seedY[from], seedX[from], y, x);
                    if (d < best) {
                        best = d;
                        bestY = seedY[from];
                        bestX = seedX[from];
                    }
                }
                nextY[t] = bestY;
                nextX[t] = bestX;
            }
        }
        seedY.swap(nextY);
        seedX.swap(nextX);
    }
    for (size_t t = 0; t < texels; ++t) {
        if (seed[t] == 0 && seedY[t] >= 0) copy(index(seedY[t], seedX[t]), t);
    }
}

}  // namespace

bool Coverage::Complete() const {
    return std::all_of(covered.begin(), covered.end(), [](uint8_t c) { return c != 0; });
}

void IslandTriangles(Coverage& coverage, const mesh::TexturingMesh& mesh, const std::string& material) {
    uint32_t id = UINT32_MAX;
    for (const mesh::Material& candidate : mesh.materials) {
        if (candidate.name == material) id = candidate.index;
    }
    coverage.triangles.clear();
    coverage.boxMin.fill(std::numeric_limits<float>::infinity());
    coverage.boxMax.fill(-std::numeric_limits<float>::infinity());
    for (const mesh::Object& object : mesh.objects) {
        const auto place = [&](const mesh::Float3& p) -> std::array<float, 3> {
            if (object.transform == mesh::kIdentity) return {p.x, p.y, p.z};
            const mesh::Matrix4& m = object.transform;
            std::array<float, 3> out{};
            for (size_t r = 0; r < 3; ++r) {
                out[r] = static_cast<float>(m[r] * p.x + m[4 + r] * p.y + m[8 + r] * p.z + m[12 + r]);
            }
            return out;
        };
        for (const mesh::Triangle& triangle : object.triangles) {
            IslandTriangle t;
            for (size_t c = 0; c < 3; ++c) {
                const mesh::Corner& corner = mesh.corners[triangle.corners[c]];
                t.uv[c] = {corner.uv0.u, corner.uv0.v};
                t.position[c] = place(mesh.positions[corner.position]);
                for (size_t d = 0; d < 3; ++d) {
                    coverage.boxMin[d] = std::min(coverage.boxMin[d], t.position[c][d]);
                    coverage.boxMax[d] = std::max(coverage.boxMax[d], t.position[c][d]);
                }
            }
            if (mesh.corners[triangle.corners[0]].material == id) coverage.triangles.push_back(t);
        }
    }
}

std::vector<RingTexel> MeasuredRing(const Coverage& coverage) { return RingOf(coverage); }

void CheckPadding(const PlannedFile& file, const Coverage& coverage, InexactPadding inexact) {
    if (file.layout == FileLayout::Statistics) return;
    if (coverage.width != file.width || coverage.height != file.height ||
        coverage.covered.size() != size_t{coverage.width} * coverage.height) {
        throw std::invalid_argument("export: the coverage of " + file.relativePath + " does not have its size");
    }
    if (coverage.Complete()) return;
    const Padding padding = file.parameters->paddingAlgorithm;
    if (padding == Padding::infinite) {
        if (inexact == InexactPadding::measure) return;
        Unfitted(file,
                 "the padding \"infinite\" on a texture set whose UV islands do not cover the whole tile is not "
                 "exact: Painter's ring across UV seams, at seam corners and at poles is not identified, and the "
                 "best-known rule misses Painter's padding texels by up to 59150 PNG 16 codes (decision 220)",
                 std::string(kIslandsOwner) + ", " + std::string(kProcessingRecording) + ", decision 259");
    }
    if (padding != Padding::passthrough) {
        Unfitted(file, "the padding \"" + std::string(PaddingName(padding)) +
                           "\" on a texture set whose UV islands do not cover the whole tile is not fitted");
    }
    if (file.layout == FileLayout::LA || file.layout == FileLayout::RGBA) {
        Unfitted(file, "an alpha layout (L+A, RGB+A) on a texture set whose UV islands do not cover the whole tile "
                       "is recorded under infinite and transparent padding only, and not fitted");
    }
    for (const PlannedChannel& channel : file.channels) {
        const SourceType type = channel.source.type;
        if (type == SourceType::meshMap || type == SourceType::virtualMap) {
            Unfitted(file,
                     "the padding \"passthrough\" of a " + std::string(SourceTypeName(type)) +
                         " source outside the UV islands is not recorded (R-090 records it for a virtual normal "
                         "from layers without a mesh map only, where Painter's values there differ between "
                         "recordings)",
                     std::string(kIslandsOwner) + ", " + std::string(kProcessingRecording) + ", decision 245");
        }
    }
}

bool ReadsCombinedNormal(const PlannedSource& source) {
    if (source.type == SourceType::virtualMap) return source.normalRole == core::MeshMapRole::combined;
    if (source.type != SourceType::diagnosticMap || !source.diagnostic) return false;
    using Kind = evaluator::DiagnosticSource::Kind;
    const evaluator::DiagnosticSource& d = *source.diagnostic;
    return (d.kind == Kind::Isolated || d.kind == Kind::Contribution || d.kind == Kind::RegionStats) &&
           d.map.kind == evaluator::DiagnosticMapId::Kind::VirtualNormal;
}

bool ReadsCombinedNormal(const PlannedFile& file) {
    return std::any_of(file.channels.begin(), file.channels.end(), ChannelReadsCombinedNormal);
}

std::string IslandNormalRefusal(const PlannedSource& source) {
    return "the " + std::string(SourceTypeName(source.type)) + " \"" + source.name +
           "\" reads the combined virtual normal on a texture set whose UV islands do not cover the whole tile: its "
           "island-edge texels read the Height outside the islands, where Painter's Height (the same under every "
           "padding of recording R-090) is not reproduced, and no recording shows it for a Height without layers (" +
           std::string(kIslandsOwner) + ": the Height outside the UV islands; decision 245)";
}

void CheckIslandNormal(const PlannedFile& file, const Coverage& coverage) {
    if (coverage.Complete()) return;
    const auto normal = std::find_if(file.channels.begin(), file.channels.end(), ChannelReadsCombinedNormal);
    if (normal == file.channels.end()) return;
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + IslandNormalRefusal(normal->source));
}

bool ApplyPadding(const PlannedFile& file, const Coverage& coverage, uint32_t channels, std::vector<float>& stored,
                  InexactPadding inexact) {
    CheckPadding(file, coverage, inexact);
    // Every other case keeps the values: complete coverage, or `passthrough`.
    if (file.layout == FileLayout::Statistics || file.parameters->paddingAlgorithm != Padding::infinite ||
        coverage.Complete() || std::none_of(coverage.covered.begin(), coverage.covered.end(), [](uint8_t c) {
            return c != 0;
        })) {
        return false;
    }
    InfinitePadding(coverage, channels, stored);
    return true;
}

}  // namespace uzp::exporter
