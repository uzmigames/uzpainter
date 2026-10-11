#include "mesh/certificate.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "mesh/tangents.h"

namespace uzp::mesh {

namespace json = core::json;

std::string_view StatusName(CertificateStatus status) {
    switch (status) {
        case CertificateStatus::pass: return "pass";
        case CertificateStatus::warn: return "warn";
        case CertificateStatus::fail: return "fail";
    }
    return "fail";
}

namespace {

using D3 = std::array<double, 3>;
using D2 = std::array<double, 2>;

D3 Sub(const D3& a, const D3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
double Dot(const D3& a, const D3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
D3 Cross(const D3& a, const D3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
double Length(const D3& a) { return std::sqrt(Dot(a, a)); }
D3 Scale(const D3& a, double s) { return {a[0] * s, a[1] * s, a[2] * s}; }
D3 ToD3(const Float3& v) { return {v.x, v.y, v.z}; }
double Cross2(const D2& a, const D2& b) { return a[0] * b[1] - a[1] * b[0]; }
D2 Sub2(const D2& a, const D2& b) { return {a[0] - b[0], a[1] - b[1]}; }

bool Finite(const Float3& v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }

/// A triangle of the mesh with what every measure needs, in scene space and UV space.
struct Tri {
    const Triangle* triangle = nullptr;
    std::array<D3, 3> p{};  ///< scene-space positions (file units)
    std::array<D2, 3> uv{};
    std::uint32_t material = 0;
    double uv_area = 0.0;  ///< signed, UV units squared
};

D3 Transform(const Matrix4& m, const Float3& p) {
    const double x = p.x, y = p.y, z = p.z;
    return {m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14]};
}

std::vector<Tri> Triangles(const TexturingMesh& mesh) {
    std::vector<Tri> tris;
    tris.reserve(mesh.TriangleCount());
    for (const Object& object : mesh.objects) {
        for (const Triangle& t : object.triangles) {
            Tri tri;
            tri.triangle = &t;
            for (std::size_t i = 0; i < 3; ++i) {
                const Corner& c = mesh.corners[t.corners[i]];
                tri.p[i] = Transform(object.transform, mesh.positions[c.position]);
                tri.uv[i] = {c.uv0.u, c.uv0.v};
            }
            tri.material = mesh.corners[t.corners[0]].material;
            tri.uv_area = 0.5 * Cross2(Sub2(tri.uv[1], tri.uv[0]), Sub2(tri.uv[2], tri.uv[0]));
            tris.push_back(tri);
        }
    }
    return tris;
}

void CountCorners(const TexturingMesh& mesh, CornerCounts& counts) {
    for (const Corner& c : mesh.corners) {
        const Float3 t = CornerTangent(c);
        const Float3 b = CornerBitangent(c);
        const bool finite = Finite(c.normal) && Finite(t) && Finite(b);
        if (!Finite(c.normal)) ++counts.non_finite_normals;
        const double ln = Length(ToD3(c.normal)), lt = Length(ToD3(t)), lb = Length(ToD3(b));
        const bool zero_n = Finite(c.normal) && ln < kZeroLength;
        const bool zero_t = Finite(t) && lt < kZeroLength;
        const bool zero_b = Finite(b) && lb < kZeroLength;
        counts.zero_normals += zero_n;
        counts.zero_tangents += zero_t;
        counts.zero_bitangents += zero_b;
        bool degenerate = !finite || zero_n || zero_t || zero_b;
        if (!degenerate) {
            const D3 tn = Scale(ToD3(t), 1.0 / lt), bn = Scale(ToD3(b), 1.0 / lb), nn = Scale(ToD3(c.normal), 1.0 / ln);
            degenerate = std::abs(Dot(tn, Cross(bn, nn))) < kMinTbnVolume;
        }
        counts.degenerate_tbn += degenerate;
        counts.flipped_handedness += c.tangent[3] < 0.0f;
    }
}

bool Inside01(const D2& uv) { return uv[0] >= 0.0 && uv[0] <= 1.0 && uv[1] >= 0.0 && uv[1] <= 1.0; }

// ── Coincident opposite faces ────────────────────────────────────────────────────────────────

/// Area of the intersection of two counter-clockwise 2D triangles (Sutherland-Hodgman).
double OverlapArea(const std::array<D2, 3>& a, const std::array<D2, 3>& b) {
    std::vector<D2> poly(a.begin(), a.end());
    for (std::size_t e = 0; e < 3 && !poly.empty(); ++e) {
        const D2& p = b[e];
        const D2& q = b[(e + 1) % 3];
        const auto side = [&](const D2& x) { return Cross2(Sub2(q, p), Sub2(x, p)); };
        std::vector<D2> out;
        for (std::size_t i = 0; i < poly.size(); ++i) {
            const D2& cur = poly[i];
            const D2& next = poly[(i + 1) % poly.size()];
            const double sc = side(cur), sn = side(next);
            if (sc >= 0.0) out.push_back(cur);
            if ((sc >= 0.0) != (sn >= 0.0)) {
                const double k = sc / (sc - sn);
                out.push_back({cur[0] + k * (next[0] - cur[0]), cur[1] + k * (next[1] - cur[1])});
            }
        }
        poly = std::move(out);
    }
    double area = 0.0;
    for (std::size_t i = 0; i < poly.size(); ++i) area += Cross2(poly[i], poly[(i + 1) % poly.size()]);
    return 0.5 * area;
}

struct CellKey {
    std::int64_t x, y, z;
    bool operator==(const CellKey&) const = default;
};
struct CellHash {
    std::size_t operator()(const CellKey& k) const {
        std::uint64_t h = static_cast<std::uint64_t>(k.x) * 0x9E3779B97F4A7C15ull;
        h ^= static_cast<std::uint64_t>(k.y) * 0xC2B2AE3D27D4EB4Full + (h << 6) + (h >> 2);
        h ^= static_cast<std::uint64_t>(k.z) * 0x165667B19E3779F9ull + (h << 6) + (h >> 2);
        return static_cast<std::size_t>(h);
    }
};

std::uint64_t CountCoincidentOpposite(const std::vector<Tri>& tris) {
    struct Geo {
        D3 n{};
        double area = 0.0;
        D3 lo{}, hi{};
    };
    std::vector<Geo> geo(tris.size());
    D3 lo{std::numeric_limits<double>::infinity(), std::numeric_limits<double>::infinity(),
          std::numeric_limits<double>::infinity()};
    D3 hi = Scale(lo, -1.0);
    double extent_sum = 0.0;
    double extent_max = 0.0;
    std::size_t valid = 0;
    for (std::size_t i = 0; i < tris.size(); ++i) {
        const auto& p = tris[i].p;
        Geo& g = geo[i];
        const D3 n = Cross(Sub(p[1], p[0]), Sub(p[2], p[0]));
        const double len = Length(n);
        for (std::size_t k = 0; k < 3; ++k) {
            g.lo[k] = std::min({p[0][k], p[1][k], p[2][k]});
            g.hi[k] = std::max({p[0][k], p[1][k], p[2][k]});
            lo[k] = std::min(lo[k], g.lo[k]);
            hi[k] = std::max(hi[k], g.hi[k]);
        }
        if (!(len > 0.0) || !std::isfinite(len)) continue;
        g.n = Scale(n, 1.0 / len);
        g.area = 0.5 * len;
        const double extent = std::max({g.hi[0] - g.lo[0], g.hi[1] - g.lo[1], g.hi[2] - g.lo[2]});
        extent_sum += extent;
        extent_max = std::max(extent_max, extent);
        ++valid;
    }
    if (valid < 2) return 0;
    const double diagonal = Length(Sub(hi, lo));
    if (!(diagonal > 0.0) || !std::isfinite(diagonal)) return 0;
    const double tol = 1e-6 * diagonal;
    // About one triangle per cell, and no triangle over more than 33 cells along an axis.
    const double cell = std::max({extent_sum / static_cast<double>(valid), extent_max / 32.0, 1e-9 * diagonal});
    const auto cell_of = [&](double value, std::size_t axis) {
        return static_cast<std::int64_t>(std::floor((value - lo[axis]) / cell));
    };
    std::unordered_map<CellKey, std::vector<std::uint32_t>, CellHash> grid;
    for (std::size_t i = 0; i < tris.size(); ++i) {
        if (geo[i].area <= 0.0) continue;
        std::array<std::int64_t, 3> c0{}, c1{};
        for (std::size_t k = 0; k < 3; ++k) {
            c0[k] = cell_of(geo[i].lo[k] - tol, k);
            c1[k] = cell_of(geo[i].hi[k] + tol, k);
        }
        for (std::int64_t x = c0[0]; x <= c1[0]; ++x) {
            for (std::int64_t y = c0[1]; y <= c1[1]; ++y) {
                for (std::int64_t z = c0[2]; z <= c1[2]; ++z) grid[{x, y, z}].push_back(static_cast<std::uint32_t>(i));
            }
        }
    }
    std::vector<bool> marked(tris.size(), false);
    const auto coincident_opposite = [&](std::size_t i, std::size_t j) {
        const Geo& a = geo[i];
        const Geo& b = geo[j];
        if (Dot(a.n, b.n) > -0.9999) return false;
        for (const D3& q : tris[j].p) {
            if (std::abs(Dot(a.n, Sub(q, tris[i].p[0]))) > tol) return false;
        }
        const D3 e1 = Scale(Sub(tris[i].p[1], tris[i].p[0]), 1.0 / Length(Sub(tris[i].p[1], tris[i].p[0])));
        const D3 e2 = Cross(a.n, e1);
        const auto project = [&](const D3& q) {
            const D3 d = Sub(q, tris[i].p[0]);
            return D2{Dot(d, e1), Dot(d, e2)};
        };
        const std::array<D2, 3> ta{project(tris[i].p[0]), project(tris[i].p[1]), project(tris[i].p[2])};
        // `b` faces the other way: reversed, it is counter-clockwise in `a`'s plane too.
        const std::array<D2, 3> tb{project(tris[j].p[0]), project(tris[j].p[2]), project(tris[j].p[1])};
        return OverlapArea(ta, tb) > 1e-6 * std::min(a.area, b.area);
    };
    for (const auto& [key, ids] : grid) {
        for (std::size_t m = 0; m < ids.size(); ++m) {
            for (std::size_t n = m + 1; n < ids.size(); ++n) {
                const std::size_t i = ids[m], j = ids[n];
                // Test each pair once: in the cell of the low corner of the boxes' intersection.
                bool first = true;
                const std::array<std::int64_t, 3> here{key.x, key.y, key.z};
                for (std::size_t k = 0; k < 3; ++k) {
                    const double low = std::max(geo[i].lo[k], geo[j].lo[k]) - tol;
                    const double high = std::min(geo[i].hi[k], geo[j].hi[k]) + tol;
                    if (low > high) {
                        first = false;
                        break;
                    }
                    if (cell_of(low, k) != here[k]) first = false;
                }
                if (!first || !coincident_opposite(i, j)) continue;
                marked[i] = true;
                marked[j] = true;
            }
        }
    }
    return static_cast<std::uint64_t>(std::count(marked.begin(), marked.end(), true));
}

// ── Per-set UV metrics ───────────────────────────────────────────────────────────────────────

std::uint64_t Bits(double value) {
    if (value == 0.0) value = 0.0;  // -0 and +0 are the same point
    return std::bit_cast<std::uint64_t>(value);
}

/// One end of a UV edge: its UV and its scene-space position, bit for bit.
using EdgeEnd = std::array<std::uint64_t, 5>;

EdgeEnd EndOf(const Tri& tri, std::size_t i) {
    return {Bits(tri.uv[i][0]), Bits(tri.uv[i][1]), Bits(tri.p[i][0]), Bits(tri.p[i][1]), Bits(tri.p[i][2])};
}

struct EdgeKey {
    EdgeEnd lo, hi;  ///< the two ends, lower first
    bool operator==(const EdgeKey&) const = default;
};
struct EdgeHash {
    std::size_t operator()(const EdgeKey& k) const {
        std::uint64_t h = 1469598103934665603ull;
        for (const EdgeEnd* end : {&k.lo, &k.hi}) {
            for (std::uint64_t v : *end) h = (h ^ v) * 1099511628211ull;
        }
        return static_cast<std::size_t>(h);
    }
};

EdgeKey KeyOf(const Tri& tri, std::size_t e) {
    EdgeEnd a = EndOf(tri, e);
    EdgeEnd b = EndOf(tri, (e + 1) % 3);
    if (b < a) std::swap(a, b);
    return {a, b};
}

struct UnionFind {
    std::vector<std::uint32_t> parent;
    explicit UnionFind(std::size_t n) : parent(n) { std::iota(parent.begin(), parent.end(), 0u); }
    std::uint32_t Find(std::uint32_t x) {
        while (parent[x] != x) x = parent[x] = parent[parent[x]];
        return x;
    }
    void Join(std::uint32_t a, std::uint32_t b) {
        a = Find(a);
        b = Find(b);
        if (a != b) parent[std::max(a, b)] = std::min(a, b);
    }
};

struct Segment {
    D2 a, b;  ///< px
    std::uint32_t island;
    double min_x, max_x, min_y, max_y;
};

double PointSegment(const D2& p, const D2& a, const D2& b) {
    const D2 ab = Sub2(b, a);
    const double len2 = ab[0] * ab[0] + ab[1] * ab[1];
    double k = len2 > 0.0 ? ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / len2 : 0.0;
    k = std::clamp(k, 0.0, 1.0);
    const double dx = p[0] - (a[0] + k * ab[0]), dy = p[1] - (a[1] + k * ab[1]);
    return std::sqrt(dx * dx + dy * dy);
}

int Orientation(const D2& a, const D2& b, const D2& c) {
    const double v = Cross2(Sub2(b, a), Sub2(c, a));
    return (v > 0.0) - (v < 0.0);
}

bool OnSegment(const D2& a, const D2& b, const D2& p) {
    return std::min(a[0], b[0]) <= p[0] && p[0] <= std::max(a[0], b[0]) && std::min(a[1], b[1]) <= p[1] &&
           p[1] <= std::max(a[1], b[1]);
}

double SegmentDistance(const Segment& s, const Segment& t) {
    const int o1 = Orientation(s.a, s.b, t.a), o2 = Orientation(s.a, s.b, t.b);
    const int o3 = Orientation(t.a, t.b, s.a), o4 = Orientation(t.a, t.b, s.b);
    if (o1 != o2 && o3 != o4 && o1 != 0 && o2 != 0 && o3 != 0 && o4 != 0) return 0.0;
    if ((o1 == 0 && OnSegment(s.a, s.b, t.a)) || (o2 == 0 && OnSegment(s.a, s.b, t.b)) ||
        (o3 == 0 && OnSegment(t.a, t.b, s.a)) || (o4 == 0 && OnSegment(t.a, t.b, s.b))) {
        return 0.0;
    }
    return std::min({PointSegment(s.a, t.a, t.b), PointSegment(s.b, t.a, t.b), PointSegment(t.a, s.a, s.b),
                     PointSegment(t.b, s.a, s.b)});
}

/// Edge function of the directed edge a -> b at c, evaluated with the edge in one canonical
/// direction so that two triangles sharing the edge get exactly opposite values.
double EdgeFunction(const D2& a, const D2& b, const D2& c) {
    const bool forward = a < b;
    const D2& p = forward ? a : b;
    const D2& q = forward ? b : a;
    const double e = (q[0] - p[0]) * (c[1] - p[1]) - (q[1] - p[1]) * (c[0] - p[0]);
    return forward ? e : -e;
}

/// Adds the texel centres `tri` covers (top-left rule) to `coverage` (saturating at 2); returns
/// how many centres it raised to 2.
std::uint64_t Rasterize(const Tri& tri, int width, int height, std::vector<std::uint8_t>& coverage) {
    std::array<D2, 3> v{};
    for (std::size_t i = 0; i < 3; ++i) v[i] = {tri.uv[i][0] * width, tri.uv[i][1] * height};
    if (tri.uv_area < 0.0) std::swap(v[1], v[2]);  // counter-clockwise
    const double min_x = std::min({v[0][0], v[1][0], v[2][0]}), max_x = std::max({v[0][0], v[1][0], v[2][0]});
    const double min_y = std::min({v[0][1], v[1][1], v[2][1]}), max_y = std::max({v[0][1], v[1][1], v[2][1]});
    const auto first = [](double lo) { return static_cast<long long>(std::floor(lo - 0.5)); };
    const auto last = [](double hi) { return static_cast<long long>(std::ceil(hi - 0.5)); };
    const long long c0 = std::max(0LL, first(min_x)), c1 = std::min<long long>(width - 1, last(max_x));
    const long long r0 = std::max(0LL, first(min_y)), r1 = std::min<long long>(height - 1, last(max_y));
    std::array<bool, 3> top_left{};
    for (std::size_t e = 0; e < 3; ++e) {
        const D2& a = v[e];
        const D2& b = v[(e + 1) % 3];
        top_left[e] = b[1] < a[1] || (b[1] == a[1] && b[0] < a[0]);
    }
    std::uint64_t raised = 0;
    for (long long row = r0; row <= r1; ++row) {
        for (long long col = c0; col <= c1; ++col) {
            const D2 c{static_cast<double>(col) + 0.5, static_cast<double>(row) + 0.5};
            bool inside = true;
            for (std::size_t e = 0; e < 3 && inside; ++e) {
                const double f = EdgeFunction(v[e], v[(e + 1) % 3], c);
                inside = f > 0.0 || (f == 0.0 && top_left[e]);
            }
            if (!inside) continue;
            std::uint8_t& count = coverage[static_cast<std::size_t>(row) * static_cast<std::size_t>(width) +
                                           static_cast<std::size_t>(col)];
            if (count < 2 && ++count == 2) ++raised;
        }
    }
    return raised;
}

/// The singular-value ratio of the map from the triangle's surface (cm) to UV (px), or nothing
/// for a degenerate triangle.
std::optional<double> Anisotropy(const Tri& tri, double scale, int width, int height) {
    const D3 a = Scale(Sub(tri.p[1], tri.p[0]), scale);
    const D3 b = Scale(Sub(tri.p[2], tri.p[0]), scale);
    const double la = Length(a);
    if (!(la > 0.0)) return std::nullopt;
    const D3 e1 = Scale(a, 1.0 / la);
    const D3 normal = Cross(a, b);
    const double ln = Length(normal);
    if (!(ln > 0.0)) return std::nullopt;
    const D3 e2 = Cross(Scale(normal, 1.0 / ln), e1);
    // Surface edge vectors q1 = (la, 0), q2 = (b.e1, b.e2); UV edges d1, d2 in px.
    const double q2x = Dot(b, e1), q2y = Dot(b, e2);
    const D2 d1{(tri.uv[1][0] - tri.uv[0][0]) * width, (tri.uv[1][1] - tri.uv[0][1]) * height};
    const D2 d2{(tri.uv[2][0] - tri.uv[0][0]) * width, (tri.uv[2][1] - tri.uv[0][1]) * height};
    // J = [d1 d2] [q1 q2]^-1, with [q1 q2]^-1 = 1/(la q2y) [[q2y, -q2x], [0, la]].
    const double det = la * q2y;
    if (!(std::abs(det) > 0.0)) return std::nullopt;
    const double j00 = (d1[0] * q2y) / det, j01 = (-d1[0] * q2x + d2[0] * la) / det;
    const double j10 = (d1[1] * q2y) / det, j11 = (-d1[1] * q2x + d2[1] * la) / det;
    const double e = (j00 + j11) / 2, f = (j00 - j11) / 2, g = (j10 + j01) / 2, h = (j10 - j01) / 2;
    const double q = std::sqrt(e * e + h * h), r = std::sqrt(f * f + g * g);
    const double s1 = q + r, s2 = std::abs(q - r);
    const double ratio = s1 / s2;
    if (!(s2 > 0.0) || !std::isfinite(ratio)) return std::nullopt;
    return ratio;
}

UvSetMetrics MeasureSet(const std::vector<const Tri*>& tris, double scale, int width, int height) {
    UvSetMetrics m;
    // Islands and boundary edges.
    UnionFind islands(tris.size());
    struct EdgeUse {
        std::uint32_t uses = 0;
        std::uint32_t triangle = 0;
        D2 a{}, b{};
    };
    std::unordered_map<EdgeKey, EdgeUse, EdgeHash> edges;
    std::vector<EdgeKey> order;  // first-use order, for a deterministic walk
    for (std::uint32_t i = 0; i < tris.size(); ++i) {
        for (std::size_t e = 0; e < 3; ++e) {
            const D2& a = tris[i]->uv[e];
            const D2& b = tris[i]->uv[(e + 1) % 3];
            const EdgeKey key = KeyOf(*tris[i], e);
            auto [it, inserted] = edges.try_emplace(key, EdgeUse{0, i, a, b});
            if (inserted) order.push_back(key);
            else islands.Join(it->second.triangle, i);
            ++it->second.uses;
        }
    }
    std::vector<std::uint32_t> roots;
    for (std::uint32_t i = 0; i < tris.size(); ++i) {
        if (islands.Find(i) == i) roots.push_back(i);
    }
    m.islands = roots.size();
    // Overlap.
    std::vector<std::uint8_t> coverage(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), 0);
    for (const Tri* tri : tris) {
        if (std::abs(tri->uv_area) > kZeroUvArea) m.overlap_px += Rasterize(*tri, width, height, coverage);
    }
    // Density and anisotropy.
    std::vector<std::pair<double, double>> density;  // (px/cm, surface cm^2)
    for (const Tri* tri : tris) {
        const double surface = 0.5 * Length(Cross(Sub(tri->p[1], tri->p[0]), Sub(tri->p[2], tri->p[0]))) * scale * scale;
        const double px = std::abs(tri->uv_area) * width * height;
        if (!(surface > 0.0) || std::abs(tri->uv_area) <= kZeroUvArea || !std::isfinite(surface)) continue;
        density.emplace_back(std::sqrt(px / surface), surface);
        if (const std::optional<double> ratio = Anisotropy(*tri, scale, width, height)) {
            m.anisotropy_max = std::max(m.anisotropy_max.value_or(0.0), *ratio);
        }
    }
    if (!density.empty()) {
        std::sort(density.begin(), density.end());
        double total = 0.0;
        for (const auto& [d, w] : density) total += w;
        DensityStats stats{density.front().first, density.back().first, density.back().first};
        double seen = 0.0;
        for (const auto& [d, w] : density) {
            seen += w;
            if (seen >= total / 2) {
                stats.p50 = d;
                break;
            }
        }
        m.density_px_per_cm = stats;
    }
    // Gap and border over the boundary edges.
    std::vector<Segment> segments;
    for (const EdgeKey& key : order) {
        const EdgeUse& use = edges.at(key);
        if (use.uses != 1) continue;
        const D2 a{use.a[0] * width, use.a[1] * height};
        const D2 b{use.b[0] * width, use.b[1] * height};
        segments.push_back(Segment{a, b, islands.Find(use.triangle), std::min(a[0], b[0]), std::max(a[0], b[0]),
                                   std::min(a[1], b[1]), std::max(a[1], b[1])});
        for (const D2& p : {a, b}) {
            const double border = std::min({p[0], width - p[0], p[1], height - p[1]});
            m.border_px = std::min(m.border_px.value_or(border), border);
        }
    }
    if (m.islands > 1) {
        std::sort(segments.begin(), segments.end(), [](const Segment& s, const Segment& t) { return s.min_x < t.min_x; });
        double best = std::numeric_limits<double>::infinity();
        for (std::size_t i = 0; i < segments.size(); ++i) {
            for (std::size_t j = i + 1; j < segments.size() && segments[j].min_x - segments[i].max_x <= best; ++j) {
                const Segment& s = segments[i];
                const Segment& t = segments[j];
                if (s.island == t.island) continue;
                if (t.min_y - s.max_y > best || s.min_y - t.max_y > best) continue;
                best = std::min(best, SegmentDistance(s, t));
            }
        }
        if (std::isfinite(best)) m.gap_px = best;
    }
    return m;
}

json::Value Optional(const std::optional<double>& v) { return v ? json::Value(*v) : json::Value(nullptr); }

}  // namespace

Certificate Certify(const TexturingMesh& mesh, const CertificateOptions& options) {
    if (options.width <= 0 || options.height <= 0) throw std::invalid_argument("certificate grid must be positive");
    Certificate cert;
    cert.grid = options;
    CountCorners(mesh, cert.corners);
    const std::vector<Tri> tris = Triangles(mesh);
    for (const Tri& tri : tris) {
        if (std::abs(tri.uv_area) <= kZeroUvArea) {
            ++cert.faces.zero_area_uv;
        } else if (tri.uv_area < 0.0) {
            ++cert.faces.flipped_uv;
        }
        if (!Inside01(tri.uv[0]) || !Inside01(tri.uv[1]) || !Inside01(tri.uv[2])) ++cert.outside_0_1;
    }
    cert.faces.coincident_opposite = CountCoincidentOpposite(tris);
    cert.faces.ngons_triangulated = mesh.flags.ngons_triangulated;
    std::vector<std::vector<const Tri*>> sets(mesh.materials.size());
    for (const Tri& tri : tris) {
        if (tri.material < sets.size()) sets[tri.material].push_back(&tri);
    }
    for (std::size_t s = 0; s < sets.size(); ++s) {
        cert.per_set[mesh.materials[s].name] =
            MeasureSet(sets[s], mesh.units.scale_to_internal, options.width, options.height);
    }
    const CornerCounts& c = cert.corners;
    const FaceCounts& f = cert.faces;
    if (c.non_finite_normals || c.zero_normals || c.zero_tangents || c.zero_bitangents || c.degenerate_tbn ||
        f.coincident_opposite || cert.outside_0_1) {
        cert.status = CertificateStatus::fail;
    } else {
        bool overlap = false;
        for (const auto& [name, metrics] : cert.per_set) overlap = overlap || metrics.overlap_px > 0;
        if (c.flipped_handedness || f.zero_area_uv || f.flipped_uv || f.ngons_triangulated || overlap) {
            cert.status = CertificateStatus::warn;
        }
    }
    return cert;
}

json::Object CertificateToJson(const Certificate& cert, const TexturingMesh& mesh) {
    const CornerCounts& c = cert.corners;
    const FaceCounts& f = cert.faces;
    json::Object per_set;
    for (const auto& [name, m] : cert.per_set) {
        json::Value density = nullptr;
        if (m.density_px_per_cm) {
            density = json::Object{{"max", m.density_px_per_cm->max},
                                   {"min", m.density_px_per_cm->min},
                                   {"p50", m.density_px_per_cm->p50}};
        }
        per_set[name] = json::Object{{"anisotropy_max", Optional(m.anisotropy_max)},
                                     {"border_px", Optional(m.border_px)},
                                     {"density_px_per_cm", std::move(density)},
                                     {"gap_px", Optional(m.gap_px)},
                                     {"islands", json::Value(m.islands)},
                                     {"overlap_px", json::Value(m.overlap_px)}};
    }
    json::Array materials;
    for (const Material& material : mesh.materials) materials.push_back(material.name);
    json::Value meters = nullptr;
    if (mesh.units.source_meters_per_unit > 0.0) meters = json::Value(mesh.units.source_meters_per_unit);
    return {
        {"corners", json::Object{{"degenerate_tbn", json::Value(c.degenerate_tbn)},
                                 {"flipped_handedness", json::Value(c.flipped_handedness)},
                                 {"non_finite_normals", json::Value(c.non_finite_normals)},
                                 {"zero_bitangents", json::Value(c.zero_bitangents)},
                                 {"zero_normals", json::Value(c.zero_normals)},
                                 {"zero_tangents", json::Value(c.zero_tangents)}}},
        {"faces", json::Object{{"coincident_opposite", json::Value(f.coincident_opposite)},
                               {"flipped_uv", json::Value(f.flipped_uv)},
                               {"ngons_triangulated", json::Value(f.ngons_triangulated)},
                               {"zero_area_uv", json::Value(f.zero_area_uv)}}},
        {"uv", json::Object{{"grid", json::Object{{"height", cert.grid.height}, {"width", cert.grid.width}}},
                            {"outside_0_1", json::Value(cert.outside_0_1)},
                            {"per_set", std::move(per_set)}}},
        {"mesh", json::Object{{"materials", std::move(materials)},
                              {"objects", json::Value(static_cast<std::uint64_t>(mesh.objects.size()))},
                              {"triangles", json::Value(static_cast<std::uint64_t>(mesh.TriangleCount()))},
                              {"units", json::Object{{"from", mesh.units.from},
                                                     {"scale_to_internal", json::Value(mesh.units.scale_to_internal)},
                                                     {"source", mesh.units.source},
                                                     {"source_meters_per_unit", std::move(meters)}}}}},
        {"hashes", HashesToJson(mesh.hashes)},
        {"status", std::string(StatusName(cert.status))},
    };
}

}  // namespace uzp::mesh
