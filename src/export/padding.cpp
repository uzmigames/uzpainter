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
// The far window: the far texels within this many columns and rows of its centre (decision 275).
constexpr int kFarReach = 1;
// Two triangles are coplanar (one planar face) within this relative tolerance.
constexpr double kCoplanar = 1e-6;
// The seam gate (decision 278): a seam edge whose faces' float32 unit normals meet at a dot product
// of at most kFoldGate is folded enough. Painter's constant lies in (kFoldLow, kFoldHigh], and
// whether its comparison is <= or < is not identified (decision 278 open item (a)).
constexpr float kFoldGate = 0.985f;
constexpr float kFoldLow = 0.98498905f;
constexpr float kFoldHigh = 0.98501915f;
// The seam reach (decision 279): a seam edge feeds the far window when its UV segment lies within
// kReachCap texels of the ring texel's centre; Painter's cap lies in (kReachLow, kReachCap] (decision
// 279 open item (c)).
constexpr double kReachCap = 1.8;
constexpr double kReachLow = 1.7;

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
    std::array<std::array<float, 2>, 3> uv{};       // the comparator's float32 UV (v up)
    std::array<std::array<float, 3>, 3> normalised{};  // the comparator's mesh-box-normalised position
    std::array<float, 3> normal{};                  // the seam gate's float32 unit face normal
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

/// A UV seam edge: edge `edge` (opposite corner `edge`) of triangle `own`, shared in 3D with
/// triangle `far`, whose UVs there differ.
struct SeamEdge {
    uint32_t own = 0;
    size_t edge = 0;
    uint32_t far = 0;
};

/// The coverage's triangles, their islands and planar faces, the UV seam edges of each island, and
/// the triangle covering each covered texel (the first in mesh order, as the coverage rasterises
/// them).
class RingGeometry {
public:
    explicit RingGeometry(const Coverage& coverage);

    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<KernelTriangle> triangles;
    std::vector<int32_t> owner;  // per texel: the covering triangle, -1 when uncovered
    std::map<std::pair<uint32_t, uint32_t>, std::vector<uint32_t>> edges;  // sorted vertex pair -> triangles
    std::map<uint32_t, std::vector<SeamEdge>> seams;  // island -> its triangles' seam edges, in mesh order

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
    // The mesh box (decision 273): ext = hi - lo, c = lo + ext / 2, r = 1 / (max(ext) / 2), each a
    // correctly rounded float32 operation; a position P normalises to P r - c r.
    std::array<float, 3> centre{};
    float extent = 0.0f;
    for (size_t c = 0; c < 3; ++c) {
        const float ext = coverage.boxMax[c] - coverage.boxMin[c];
        const float halfExt = ext * 0.5f;
        centre[c] = coverage.boxMin[c] + halfExt;
        extent = std::max(extent, ext);
    }
    const float halfExtent = extent * 0.5f;
    const float scale = 1.0f / halfExtent;
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
        // The face normal (decision 278): cross(P1 - P0, P2 - P0) over the stored positions, divided
        // by its length, each a correctly rounded float32 operation.
        {
            const auto& P = source.position;
            const std::array<float, 3> e1{P[1][0] - P[0][0], P[1][1] - P[0][1], P[1][2] - P[0][2]};
            const std::array<float, 3> e2{P[2][0] - P[0][0], P[2][1] - P[0][1], P[2][2] - P[0][2]};
            const std::array<float, 3> n{e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2],
                                         e1[0] * e2[1] - e1[1] * e2[0]};
            const float length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
            for (size_t c = 0; c < 3; ++c) k.normal[c] = n[c] / length;
        }
        for (size_t c = 0; c < 3; ++c) {
            const auto& p = source.position[c];
            k.p[c] = {p[0], p[1], p[2]};
            k.t[c] = {uv[c][0] * w, (1.0 - static_cast<double>(uv[c][1])) * h};
            k.uv[c] = uv[c];
            for (size_t d = 0; d < 3; ++d) {
                const float scaled = p[d] * scale;
                const float shift = centre[d] * scale;
                k.normalised[c][d] = scaled - shift;
            }
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
    // Each island's seam edges: an edge whose other triangles there have other UVs.
    for (uint32_t i = 0; i < count; ++i) {
        const KernelTriangle& own = triangles[i];
        for (size_t e = 0; e < 3; ++e) {
            const uint32_t a = own.vertex[(e + 1) % 3];
            const uint32_t b = own.vertex[(e + 2) % 3];
            for (const uint32_t j : edges.at({std::min(a, b), std::max(a, b)})) {
                const KernelTriangle& other = triangles[j];
                if (j == i || (cornerAt(other, a) == own.corner[(e + 1) % 3] &&
                               cornerAt(other, b) == own.corner[(e + 2) % 3])) {
                    continue;  // the same island across the edge
                }
                seams[own.chart].push_back({i, e, j});
            }
        }
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

/// The recording GPU's float32 distance of decision 273's comparator from the ring texel (rx, ry)
/// to the tap (tx, ty) of triangle `k`, on a `width` x `height` tile. Both texel centres (u, v) =
/// ((x + 1/2) / W, 1 - (y + 1/2) / H) take barycentrics from `k`'s UV inverse matrix based at its
/// third corner, through the GPU's reciprocal of the determinant, and interpolate the
/// mesh-box-normalised positions as fma(l2, P2, fma(l0, P0, l1 P1)); then the squared distance by
/// FMA and the GPU's square root. Every other operation is one correctly rounded float32 operation.
float CompareDistance(const KernelTriangle& k, uint32_t width, uint32_t height, uint32_t rx, uint32_t ry, uint32_t tx,
                      uint32_t ty) {
    const auto& U = k.uv;
    const float e0u = U[0][0] - U[2][0];
    const float e0v = U[0][1] - U[2][1];
    const float e1u = U[1][0] - U[2][0];
    const float e1v = U[1][1] - U[2][1];
    const float a = e0u * e1v;
    const float b = e0v * e1u;
    const float r = evaluator::hw::Rcp(a - b);
    const float m00 = e1v * r;
    const float m01 = -e1u * r;
    const float m10 = -e0v * r;
    const float m11 = e0u * r;
    const auto fw = static_cast<float>(width);
    const auto fh = static_cast<float>(height);
    const auto position = [&](uint32_t x, uint32_t y) {
        const float pu = (static_cast<float>(x) + 0.5f) / fw;
        const float pv = 1.0f - (static_cast<float>(y) + 0.5f) / fh;
        const float dx = pu - U[2][0];
        const float dy = pv - U[2][1];
        const float l0 = std::fma(m00, dx, m01 * dy);
        const float l1 = std::fma(m10, dx, m11 * dy);
        const float sum = l0 + l1;
        const float l2 = 1.0f - sum;
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

/// Decision 278's seam gate of one seam edge (tau's ring point q, the edge's own triangle E and far
/// triangle J): `gated` when the faces' float32 unit normals meet at a dot product of at most
/// kFoldGate and q lies behind J's plane (n_J . (q - p) < 0, p the edge's first vertex).
/// `bracket` when the dot product lies in (kFoldLow, kFoldHigh] and q lies behind J, `onPlane` when
/// q lies on J's plane and the dot product is at most kFoldHigh: there the gate is not identified.
struct SeamGate {
    bool gated = false;
    bool bracket = false;
    bool onPlane = false;
};

SeamGate GateOf(const KernelTriangle& E, const KernelTriangle& J, const Vec3& q, const Vec3& p) {
    const float dot = E.normal[0] * J.normal[0] + E.normal[1] * J.normal[1] + E.normal[2] * J.normal[2];
    const double side = Dot({J.normal[0], J.normal[1], J.normal[2]}, Sub(q, p));
    return {dot <= kFoldGate && side < 0.0, dot > kFoldLow && dot <= kFoldHigh && side < 0.0,
            side == 0.0 && dot <= kFoldHigh};
}

/// The texel-space distance from (px, py) to the UV segment of edge `edge` of `k`.
double SegmentDistance(const KernelTriangle& k, size_t edge, double px, double py) {
    const auto& a = k.t[(edge + 1) % 3];
    const auto& b = k.t[(edge + 2) % 3];
    const double ex = b[0] - a[0];
    const double ey = b[1] - a[1];
    const double length = ex * ex + ey * ey;
    const double u = length == 0.0 ? 0.0 : std::clamp(((px - a[0]) * ex + (py - a[1]) * ey) / length, 0.0, 1.0);
    return std::hypot(px - a[0] - u * ex, py - a[1] - u * ey);
}

/// `out` in tap order: nearest first, equal distances by the comparator (own taps), then toward
/// +u, +v; the first kKeptCandidates.
std::vector<Candidate> Ordered(const RingGeometry& g, uint32_t x, uint32_t y, std::vector<Candidate> out) {
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
                const KernelTriangle& k = g.triangles[c.triangle];
                group.emplace_back(c.tap.far ? 0.0f : CompareDistance(k, g.width, g.height, x, y, c.tap.x, c.tap.y), c);
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

/// The chain's number of taps over `candidates` (tap order): the 4 nearest, or 1 when the nearest
/// lies at distance 0.
uint32_t TapCount(const std::vector<Candidate>& candidates) {
    double nearest = std::numeric_limits<double>::infinity();
    for (const Candidate& c : candidates) {
        if (!c.tap.far) nearest = std::min(nearest, c.tap.distance);
    }
    return candidates[0].tap.distance > kZeroDistance * nearest
               ? static_cast<uint32_t>(std::min(kMaxTaps, candidates.size()))
               : 1u;
}

/// Whether the chains over `a` and `b` (tap order) take the same taps at the same distances.
bool SameTaps(const std::vector<Candidate>& a, const std::vector<Candidate>& b) {
    const uint32_t n = TapCount(a);
    if (TapCount(b) != n) return false;
    for (uint32_t i = 0; i < n; ++i) {
        if (a[i].texel != b[i].texel || a[i].tap.far != b[i].tap.far || a[i].tap.distance != b[i].tap.distance) {
            return false;
        }
    }
    return true;
}

/// A ring texel's candidates in tap order, and where decisions 278's gate and 279's reach do not
/// decide them.
struct CandidateSet {
    std::vector<Candidate> candidates;
    bool foldBracket = false;
    bool onFarPlane = false;
    bool mixedGates = false;
    bool reachBracket = false;
};

/// The candidates of ring texel (x, y) with q extrapolated through `tau` (decisions 275, 278, 279).
CandidateSet Candidates(const RingGeometry& g, uint32_t x, uint32_t y, const std::vector<size_t>& own, uint32_t tau) {
    const KernelTriangle& T = g.triangles[tau];
    const std::array<double, 3> l = TexelBary(T, x + 0.5, y + 0.5);
    const Vec3 q = Point(T, l);
    // Each texel the ring may read: an own neighbour, or a far texel in the window of some seam edges.
    struct Entry {
        size_t texel = 0;
        uint32_t triangle = 0;
        double frame = 0.0;    // |q - P|, P in tau's frame: the distance of an own tap of tau's island or a far tap
        double outside = -1;   // an own neighbour outside tau's island: min(|q_k - P|, |q - P|) (decision 279)
        bool own = false;
        std::vector<uint32_t> via;  // the seam edges (indices into `edges`) whose window holds it
    };
    std::vector<Entry> pool;
    const auto entry = [&](size_t texel) -> Entry& {
        for (Entry& e : pool) {
            if (e.texel == texel) return e;
        }
        Entry e;
        e.texel = texel;
        e.triangle = static_cast<uint32_t>(g.owner[texel]);
        const KernelTriangle& k = g.triangles[e.triangle];
        const double tx = static_cast<double>(texel % g.width) + 0.5;
        const double ty = static_cast<double>(texel / g.width) + 0.5;
        const Vec3 p = Point(k, TexelBary(k, tx, ty));
        e.frame = Norm(Sub(q, g.Frame(p, e.triangle, tau)));
        if (k.chart != T.chart) {
            e.outside = std::min(Norm(Sub(Point(k, TexelBary(k, x + 0.5, y + 0.5)), p)), Norm(Sub(q, p)));
        }
        pool.push_back(std::move(e));
        return pool.back();
    };
    for (const size_t texel : own) entry(texel).own = true;
    // The seam edges of every island that owns an own neighbour whose UV segment lies within
    // kReachCap texels of the ring texel's centre (decision 279), each through decision 278's gate:
    // q folded about the edge into the far triangle J, f its point in J's texel space, and J's
    // island's covered texels in the 3 x 3 block of columns floor(f_u - 1/2) +- 1 and rows
    // ceil(f_v - 1/2) +- 1 (decision 275).
    std::vector<uint32_t> charts;
    for (const size_t texel : own) charts.push_back(g.triangles[static_cast<size_t>(g.owner[texel])].chart);
    std::sort(charts.begin(), charts.end());
    charts.erase(std::unique(charts.begin(), charts.end()), charts.end());
    struct Edge {
        SeamGate gate;
        double reach = 0.0;
    };
    std::vector<Edge> edges;
    for (const uint32_t chart : charts) {
        const auto seams = g.seams.find(chart);
        if (seams == g.seams.end()) continue;
        for (const SeamEdge& seam : seams->second) {
            const KernelTriangle& E = g.triangles[seam.own];
            const double reach = SegmentDistance(E, seam.edge, x + 0.5, y + 0.5);
            if (reach > kReachCap) continue;
            const KernelTriangle& J = g.triangles[seam.far];
            const uint32_t va = E.vertex[(seam.edge + 1) % 3];
            const uint32_t vb = E.vertex[(seam.edge + 2) % 3];
            const auto index = static_cast<uint32_t>(edges.size());
            edges.push_back({GateOf(E, J, q, E.p[(seam.edge + 1) % 3]), reach});
            const std::array<double, 2> far = TexelOf(J, Fold(MakeHinge(E, J, va, vb), q));
            const auto col0 = static_cast<int64_t>(std::floor(far[0] - 0.5));
            const auto row0 = static_cast<int64_t>(std::ceil(far[1] - 0.5));
            for (int64_t row = row0 - kFarReach; row <= row0 + kFarReach; ++row) {
                for (int64_t col = col0 - kFarReach; col <= col0 + kFarReach; ++col) {
                    if (row < 0 || col < 0 || row >= g.height || col >= g.width) continue;
                    const size_t texel = static_cast<size_t>(row) * g.width + static_cast<size_t>(col);
                    const int32_t k = g.owner[texel];
                    if (k < 0 || g.triangles[static_cast<size_t>(k)].chart != J.chart) continue;
                    Entry& e = entry(texel);
                    if (e.via.empty() || e.via.back() != index) e.via.push_back(index);
                }
            }
        }
    }
    // The candidates when the edges `open` feed the far windows: an own neighbour of tau's island
    // is an own tap; any other texel is a far tap when an open edge's window holds it, else an own
    // neighbour outside tau's island is an own tap at its `outside` distance (decision 279).
    const auto build = [&](const auto& open) {
        std::vector<Candidate> out;
        for (const Entry& e : pool) {
            const auto tx = static_cast<uint32_t>(e.texel % g.width);
            const auto ty = static_cast<uint32_t>(e.texel / g.width);
            const bool inside = e.own && e.outside < 0.0;
            if (!inside && std::any_of(e.via.begin(), e.via.end(), [&](uint32_t i) { return open(edges[i]); })) {
                out.push_back({{tx, ty, e.frame, true}, e.texel, e.triangle});
            } else if (e.own) {
                out.push_back({{tx, ty, inside ? e.frame : e.outside, false}, e.texel, e.triangle});
            }
        }
        return Ordered(g, x, y, std::move(out));
    };
    CandidateSet out{build([](const Edge& e) { return !e.gate.gated; })};
    if (edges.empty()) return out;
    // Where the rule is not identified: the reach cap between kReachLow and kReachCap changes the
    // taps (decision 279 open item (c)); an edge whose window gives the chain a tap, with the gate
    // or without it, has its fold in the bracket or q on its far plane, or two such edges are gated
    // differently (decision 278 open items (a) and (b)).
    out.reachBracket =
        !SameTaps(out.candidates, build([](const Edge& e) { return !e.gate.gated && e.reach <= kReachLow; }));
    const std::vector<Candidate> ungated = build([](const Edge&) { return true; });
    std::vector<uint8_t> reaches(edges.size(), 0);
    for (const std::vector<Candidate>* list : {&std::as_const(out.candidates), &ungated}) {
        const uint32_t n = TapCount(*list);
        for (uint32_t i = 0; i < n; ++i) {
            if (!(*list)[i].tap.far) continue;
            for (const Entry& e : pool) {
                if (e.texel != (*list)[i].texel) continue;
                for (const uint32_t v : e.via) reaches[v] = 1;
            }
        }
    }
    bool gated = false;
    bool open = false;
    for (size_t i = 0; i < edges.size(); ++i) {
        if (reaches[i] == 0) continue;
        out.foldBracket = out.foldBracket || edges[i].gate.bracket;
        out.onFarPlane = out.onFarPlane || edges[i].gate.onPlane;
        (edges[i].gate.gated ? gated : open) = true;
    }
    out.mixedGates = gated && open;
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
            const auto rx = static_cast<uint32_t>(x);
            const auto ry = static_cast<uint32_t>(y);
            std::vector<uint32_t> triangles;
            for (const size_t texel : own) triangles.push_back(static_cast<uint32_t>(g.owner[texel]));
            std::sort(triangles.begin(), triangles.end(), std::greater<>());
            triangles.erase(std::unique(triangles.begin(), triangles.end()), triangles.end());
            // tau (decision 279): the triangle of the own neighbour nearest under decision 273's
            // comparator, through that neighbour's own triangle; a tie goes toward +u, then +v.
            if (triangles.size() > 1) {
                size_t best = own[0];
                float nearest = std::numeric_limits<float>::infinity();
                for (const size_t texel : own) {
                    const auto tx = static_cast<uint32_t>(texel % coverage.width);
                    const auto ty = static_cast<uint32_t>(texel / coverage.width);
                    const auto k = static_cast<size_t>(g.owner[texel]);
                    const float d = CompareDistance(g.triangles[k], g.width, g.height, rx, ry, tx, ty);
                    const auto bx = static_cast<uint32_t>(best % coverage.width);
                    const auto by = static_cast<uint32_t>(best / coverage.width);
                    if (d < nearest || (d == nearest && (tx > bx || (tx == bx && ty < by)))) {
                        nearest = d;
                        best = texel;
                    }
                }
                const auto tau = static_cast<uint32_t>(g.owner[best]);
                std::rotate(triangles.begin(), std::find(triangles.begin(), triangles.end(), tau),
                            std::find(triangles.begin(), triangles.end(), tau) + 1);
            }
            RingTexel r;
            r.x = rx;
            r.y = ry;
            r.triangles = static_cast<uint32_t>(triangles.size());
            const CandidateSet set = Candidates(g, rx, ry, own, triangles[0]);
            r.candidates = Taps(set.candidates);
            r.taps = TapCount(set.candidates);
            r.fractions = Fractions(r.candidates, r.taps);
            r.foldBracket = set.foldBracket;
            r.onFarPlane = set.onFarPlane;
            r.mixedGates = set.mixedGates;
            r.reachBracket = set.reachBracket;
            for (size_t i = 1; i < triangles.size(); ++i) {
                r.alternatives.push_back(Taps(Candidates(g, rx, ry, own, triangles[i]).candidates));
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
