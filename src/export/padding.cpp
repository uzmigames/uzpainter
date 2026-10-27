#include "export/padding.h"

#include "evaluator/geometry_mask.h"
#include "evaluator/hwmath.h"
#include "export/encode.h"
#include "export/guards.h"
#include "mesh/texturing_mesh.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <deque>
#include <functional>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>

namespace uzp::exporter {

namespace {

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
// Distances this close (relative) are equal shares, ordered by the comparators (decisions 267 and
// 282; the band holds decision 288's ties at float32 precision).
constexpr double kEqualShare = 1e-5;
// A nearest candidate this close (relative to the nearest covered neighbour) is at distance 0.
constexpr double kZeroDistance = 1e-6;
// The far window: the far texels within this many columns and rows of its centre (decision 275).
constexpr int kFarReach = 1;
// Two triangles are coplanar (one planar face) within this relative tolerance.
constexpr double kCoplanar = 1e-6;
// Decision 364: unit normals whose cross product is shorter than this are parallel.
constexpr double kParallel = 1e-10;
// The seam gate (decision 278): a seam edge whose faces' float32 unit normals meet at a dot product
// of at most kFoldGate is folded enough. Painter's constant lies in (kFoldLow, kFoldHigh], and
// whether its comparison is <= or < is not identified (decision 278 open item (a)).
constexpr float kFoldGate = 0.985f;
constexpr float kFoldLow = 0.98498905f;
constexpr float kFoldHigh = 0.98501915f;
// The seam reach (decisions 279 and 285): a seam edge feeds the far window when its UV segment lies
// within kReachCap texels of the ring texel's centre; Painter's cap lies in [kReachLow, kReachHigh)
// (decision 285 finding 3: bevelled-cube-256 (4, 234) needs its edge at 1.77200433 included, the
// Wand's (740, 1459) needs its edge at 1.78724202 excluded; the bounds round those inward).
constexpr double kReachCap = 1.78;
constexpr double kReachLow = 1.7720044;
constexpr double kReachHigh = 1.787242;
// Legacy corner sensitivity diagnostic (decision 294): a seam edge outside tau's planar face whose nearest
// point to the ring texel's centre is an end V, and which is not collinear (UV |sin| at most
// kCollinear) with another seam edge of the island ending at V, reaches kCornerGated texels when
// another seam edge of the ring texel ending at V is gated, else kCornerOpen. Painter's caps lie in
// [kCornerGatedLow, kCornerGatedHigh) and [kCornerOpenLow, kCornerOpenHigh), its collinear
// threshold below kCollinearHigh (flagged from kCollinearLow: an exact continuation is exempt).
// The bounds round the Wand's edges inward: kept at 0.97461490 (274, 1989) and 1.07592644
// (634, 1418), dropped at 1.02000402 (175, 1101) and 1.20807410 (566, 1439); decision 294 writes
// the open low end 1.075926, which would drop (634, 1418)'s edge. Nominal eligibility now uses
// last-drawn seam-strip ownership; both nominal corner caps retain the global reach cap.
constexpr double kCornerGated = kReachCap;
constexpr double kCornerGatedLow = 0.974615;
constexpr double kCornerGatedHigh = 1.020004;
constexpr double kCornerOpen = kReachCap;
constexpr double kCornerOpenLow = 1.0759265;
constexpr double kCornerOpenHigh = 1.208074;
constexpr double kCollinear = 1e-3;
constexpr double kCollinearLow = 1e-6;
constexpr double kCollinearHigh = 0.0305;
// Adjacent own taps whose distances lie within this relative band are ordered by decision 273's
// comparator (decision 294).
constexpr double kOwnBand = 1e-4;
// A tap in a planar face with no 3D edge to tau's face is developed along face paths of at most
// this many hinges (decision 281).
constexpr size_t kMaxHinges = 4;
// Decision 365: the most edges a far point is carried across after its fold into J.
constexpr size_t kMaxHops = 4;
// The window side (decision 291): a far point f with f - 1/2 within kWindowSide texel of an integer
// on some axis lies on a window boundary, where Painter's side is not identified. At most
// kWindowSides such axes of a ring texel are tried on both sides; with more, it is flagged untried.
constexpr double kWindowSide = 1e-4;
constexpr size_t kWindowSides = 10;
// Decision 280's fixed orders of exactly tied taps, as v-up offsets (du, dv): an own tap's from
// the ring texel, a far tap's from its window's base (floor(f_u - 1/2), ceil(f_v - 1/2)).
constexpr std::array<std::array<int, 2>, 8> kOwnOrder{
    {{1, 0}, {-1, 0}, {0, -1}, {0, 1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}};
constexpr std::array<std::array<int, 2>, 9> kWindowOrder{
    {{0, 0}, {1, 0}, {0, 1}, {1, 1}, {0, -1}, {1, -1}, {-1, 0}, {-1, 1}, {-1, -1}}};
// Where those orders are not identified (decision 280 open item (c)): the rank pairs of kOwnOrder
// that never tie visibly, and the rank pairs of kWindowOrder that the recorded ties order neither
// directly nor through other ranks.
bool OwnOrderOpen(size_t a, size_t b) {
    const auto [lo, hi] = std::minmax(a, b);
    return (lo == 0 && hi == 1) || (lo == 2 && hi == 3) || (lo == 5 && hi == 6);
}
bool WindowOrderOpen(size_t a, size_t b) {
    const auto [lo, hi] = std::minmax(a, b);
    if (hi <= 5) return false;             // the first six ranks: one chain of recorded ties
    if (lo == 6 && hi == 7) return false;  // (-1, 0) before (-1, +1)
    return !(hi == 8 && lo <= 2);          // (0, 0), (+1, 0) and (0, +1) before (-1, -1)
}
// Decision 280's tie classes that the data leave open, of a group of equal distances (`RingTexel`).
constexpr uint8_t kTieOwnFar = 1;    // an own tap and a far tap (open item (d))
constexpr uint8_t kTieOwnOrder = 2;  // own taps tied on the comparator, an open kOwnOrder pair
constexpr uint8_t kTieFarFold = 4;   // far taps in different planar faces (open item (a))
constexpr uint8_t kTieFarOrder = 8;  // far taps tied in float32, an open kWindowOrder pair or windows

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

/// Decision 282's hinge gate: whether the float32 unit face normals of `a` and `b` meet at a dot
/// product of at most kFoldGate (decision 278's test). A shallower hinge is not unfolded.
bool FoldedPast(const KernelTriangle& a, const KernelTriangle& b) {
    return a.normal[0] * b.normal[0] + a.normal[1] * b.normal[1] + a.normal[2] * b.normal[2] <= kFoldGate;
}

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

/// The 3D distance from `q` to the segment a b.
double SegmentGap(const Vec3& a, const Vec3& b, const Vec3& q) {
    const Vec3 e = Sub(b, a);
    const double t = std::min(std::max(Dot(Sub(q, a), e) / Dot(e, e), 0.0), 1.0);
    return Norm(Sub(q, Add(a, Scale(e, t))));
}

/// Decision 364: `p` turned rigidly about the line where the plane of `source` meets the plane of
/// `target`, by the angle between their unit face normals m and n (Rodrigues), so that the source
/// plane lands on the target plane; as it is when the planes are parallel or their normals meet at
/// a dot product above kFoldGate (decision 282's gate). The line's point solves n.x = n.P_target,
/// m.x = m.P_source, a.x = 0 (a the unit axis m x n) by Cramer's rule.
Vec3 PlaneRotation(const Vec3& p, const KernelTriangle& source, const KernelTriangle& target) {
    const Vec3 n = Unit({target.normal[0], target.normal[1], target.normal[2]});
    const Vec3 m = Unit({source.normal[0], source.normal[1], source.normal[2]});
    Vec3 axis = Cross(m, n);
    const double sine = Norm(axis);
    const double cosine = Dot(m, n);
    if (sine < kParallel || cosine > static_cast<double>(kFoldGate)) return p;
    axis = Scale(axis, 1.0 / sine);
    const double dn = Dot(n, target.p[0]);
    const double dm = Dot(m, source.p[0]);
    const Vec3 across = Cross(m, axis);
    const double det = Dot(n, across);
    const Vec3 origin = Scale(Add(Scale(across, dn), Scale(Cross(axis, n), dm)), 1.0 / det);
    const Vec3 v = Sub(p, origin);
    const Vec3 turned = Add(Add(origin, Scale(v, cosine)), Scale(Cross(axis, v), sine));
    return Add(turned, Scale(axis, Dot(axis, v) * (1.0 - cosine)));
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

/// The key of texel cell (col, row) of the strip map (RingGeometry::strips); either may be negative.
uint64_t StripCell(int64_t col, int64_t row) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(col)) << 32) | static_cast<uint32_t>(row);
}

/// A UV seam edge: edge `edge` (opposite corner `edge`) of triangle `own`, shared in 3D with
/// triangle `far`, whose UVs there differ; `run`, its run (RingGeometry's constructor).
struct SeamEdge {
    uint32_t own = 0;
    size_t edge = 0;
    uint32_t farTriangle = 0;
    uint32_t run = 0;
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
    /// A seam edge as drawn into the one strip map shared by every island: `seams[chart][index]`.
    struct DrawnSeam {
        uint32_t chart = 0;
        uint32_t index = 0;
    };
    std::vector<DrawnSeam> drawOrder;  // every seam edge in mesh order (own, edge, far)
    /// Per texel cell (StripCell), the `drawOrder` indices, ascending, of the seams whose strip may
    /// cover the cell's centre: the floor-texel box of the UV ends widened by one texel.
    std::unordered_map<uint64_t, std::vector<uint32_t>> strips;
    std::set<uint32_t> coveredCharts;  // the islands that cover some texel centre (decision 365)

    /// A stage of Hop: the far point in its triangle's texel space, and the triangle.
    struct HopStage {
        std::array<double, 2> f{};
        uint32_t triangle = 0;
    };
    /// Decision 365's walk: `q` folded about seam edge (va, vb) of triangle `e` into its far
    /// triangle `j`, then, while the point lies outside its triangle (a negative 3D barycentric,
    /// the least, the first on a tie), folded about that edge into the edge's next triangle (the
    /// first other one in `edges`), at most kMaxHops times; never back across the edge it came
    /// through.
    std::vector<HopStage> Hop(uint32_t e, uint32_t j, uint32_t va, uint32_t vb, const Vec3& q) const;

    /// `p`, a point of triangle `k`, in tau's frame for the ring point `q`. A far tap (k in another
    /// chart than tau) is rotated rigidly from the plane of a far triangle J into tau's (decision
    /// 364, PlaneRotation): J is the far triangle of the seam edge of tau's island, into k's island,
    /// whose 3D segment is nearest `q` (the first on a tie), else `window`, the far triangle of the
    /// window that puts the tap. Otherwise: as it is in tau's planar face, rotated about an edge
    /// shared by the two faces, else rotated hinge by hinge along the fewest-hinge face paths (at
    /// most kMaxHinges) into tau's plane, the development nearest `q` (decision 281), else as it is.
    /// A hinge is rotated about only when it is folded past the gate (decision 282, `FoldedPast`: of
    /// k and tau across a shared edge, of the path's two triangles at each hinge of a development).
    /// A far tap with no J keeps its own chart rigid: a hinge whose two triangles are both in k's
    /// chart is not rotated about (decision 342).
    Vec3 Frame(const Vec3& p, uint32_t k, uint32_t tau, const Vec3& q,
               std::optional<uint32_t> window = std::nullopt) const;
    /// Whether triangle `k`'s planar face is tau's or shares a 3D edge with it.
    bool Hinged(uint32_t k, uint32_t tau) const;

private:
    /// An edge (va, vb) shared by two planar faces: `own` a triangle of the first, `other` of the
    /// second.
    struct FaceEdge {
        uint32_t own = 0;
        uint32_t other = 0;
        uint32_t va = 0;
        uint32_t vb = 0;
    };
    struct FaceHinge {
        FaceEdge edge;
        Hinge hinge;
    };
    /// The first edge of face `to`'s triangles (in face order, then edge order) shared with face
    /// `from`, and its hinge.
    const std::optional<FaceHinge>& HingeOf(uint32_t to, uint32_t from) const;
    /// The fewest-hinge simple face paths from face `from` to face `to`, breadth first.
    const std::vector<std::vector<uint32_t>>& Paths(uint32_t from, uint32_t to) const;

    std::vector<std::vector<uint32_t>> m_faces;
    /// Per face, its neighbour faces in the order of `edges`, each with its first shared edge.
    std::vector<std::vector<std::pair<uint32_t, FaceEdge>>> m_links;
    mutable std::map<std::pair<uint32_t, uint32_t>, std::optional<FaceHinge>> m_hinges;
    mutable std::map<std::pair<uint32_t, uint32_t>, std::vector<std::vector<uint32_t>>> m_paths;
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
            // Welded by value: -0 and +0 are one coordinate (decision 288).
            const auto key = [](float v) { return v == 0.0f ? 0u : std::bit_cast<uint32_t>(v); };
            const std::array<uint32_t, 3> bits{key(p[0]), key(p[1]), key(p[2])};
            k.vertex[c] = vertices.try_emplace(bits, static_cast<uint32_t>(vertices.size())).first->second;
            const std::array<uint32_t, 3> corner{k.vertex[c], key(uv[c][0]), key(uv[c][1])};
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
    // The face graph (decision 281): faces sharing an edge of the position-welded mesh.
    m_links.resize(m_faces.size());
    for (const auto& [key, list] : edges) {
        for (const uint32_t i : list) {
            for (const uint32_t j : list) {
                const uint32_t fi = triangles[i].face;
                const uint32_t fj = triangles[j].face;
                auto& links = m_links[fi];
                if (fi == fj ||
                    std::any_of(links.begin(), links.end(), [&](const auto& l) { return l.first == fj; })) {
                    continue;
                }
                links.push_back({fj, {i, j, key.first, key.second}});
            }
        }
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
                drawOrder.push_back({own.chart, static_cast<uint32_t>(seams[own.chart].size() - 1)});
            }
        }
    }
    // The strip map's cells (decision 356): each seam edge in the floor-texel box of its UV ends,
    // widened by one texel, so that every texel centre its strip may cover is in a listed cell.
    for (uint32_t d = 0; d < drawOrder.size(); ++d) {
        const SeamEdge& seam = seams.at(drawOrder[d].chart)[drawOrder[d].index];
        const auto& a = triangles[seam.own].t[(seam.edge + 1) % 3];
        const auto& b = triangles[seam.own].t[(seam.edge + 2) % 3];
        const auto lo = [](double p, double q) { return static_cast<int64_t>(std::floor(std::min(p, q) - 1.0)); };
        const auto hi = [](double p, double q) { return static_cast<int64_t>(std::floor(std::max(p, q) + 1.0)); };
        for (int64_t row = lo(a[1], b[1]); row <= hi(a[1], b[1]); ++row) {
            for (int64_t col = lo(a[0], b[0]); col <= hi(a[0], b[0]); ++col) strips[StripCell(col, row)].push_back(d);
        }
    }
    // Each island's seam runs: seams joined end to end through a shared UV end, collinear (UV |sin|
    // at most kCollinear) and with far triangles of one island, transitively. A run is named by one
    // of its seams' indices; only the equality of runs is read.
    for (auto& islandSeams : seams) {
        std::vector<SeamEdge>& list = islandSeams.second;
        std::vector<uint32_t> parent(list.size());
        std::iota(parent.begin(), parent.end(), 0u);
        std::map<std::array<double, 2>, std::vector<uint32_t>> at;  // UV end -> the seams ending there
        for (uint32_t i = 0; i < list.size(); ++i) {
            const KernelTriangle& k = triangles[list[i].own];
            at[k.t[(list[i].edge + 1) % 3]].push_back(i);
            at[k.t[(list[i].edge + 2) % 3]].push_back(i);
        }
        for (const auto& atEnd : at) {
            const std::vector<uint32_t>& ids = atEnd.second;
            for (size_t m = 0; m < ids.size(); ++m) {
                for (size_t n = m + 1; n < ids.size(); ++n) {
                    const SeamEdge& s = list[ids[m]];
                    const SeamEdge& r = list[ids[n]];
                    if (triangles[s.farTriangle].chart != triangles[r.farTriangle].chart) continue;
                    const auto& sa = triangles[s.own].t[(s.edge + 1) % 3];
                    const auto& sb = triangles[s.own].t[(s.edge + 2) % 3];
                    const auto& ra = triangles[r.own].t[(r.edge + 1) % 3];
                    const auto& rb = triangles[r.own].t[(r.edge + 2) % 3];
                    const double ex = sb[0] - sa[0];
                    const double ey = sb[1] - sa[1];
                    const double fx = rb[0] - ra[0];
                    const double fy = rb[1] - ra[1];
                    const double lengths = std::sqrt(ex * ex + ey * ey) * std::sqrt(fx * fx + fy * fy);
                    if (std::abs(ex * fy - ey * fx) <= kCollinear * lengths) {
                        parent[Find(parent, ids[m])] = Find(parent, ids[n]);
                    }
                }
            }
        }
        for (uint32_t i = 0; i < list.size(); ++i) list[i].run = Find(parent, i);
    }
    // The covering triangle of each texel, by the coverage's own test (evaluator/geometry_mask.h).
    owner.assign(size_t{width} * height, -1);
    for (size_t i = 0; i < coverage.triangles.size(); ++i) {
        if (index[i] < 0) continue;
        evaluator::CoveredTexels(coverage.triangles[i].uv, width, height, [&](uint32_t col, uint32_t row) {
            int32_t& t = owner[size_t{row} * width + col];
            if (t < 0) t = index[i];
        });
    }
    for (size_t t = 0; t < owner.size(); ++t) {
        if ((owner[t] >= 0) != (coverage.covered[t] != 0)) {
            throw std::invalid_argument("export: the coverage is not its triangles' texel-centre coverage");
        }
        if (owner[t] >= 0) coveredCharts.insert(triangles[static_cast<size_t>(owner[t])].chart);
    }
}

std::vector<RingGeometry::HopStage> RingGeometry::Hop(uint32_t e, uint32_t j, uint32_t va, uint32_t vb,
                                                      const Vec3& q) const {
    Vec3 point = Fold(MakeHinge(triangles[e], triangles[j], va, vb), q);
    uint32_t cur = j;
    std::array<uint32_t, 2> came{std::min(va, vb), std::max(va, vb)};
    std::vector<HopStage> stages{{TexelOf(triangles[cur], point), cur}};
    for (size_t hop = 0; hop < kMaxHops; ++hop) {
        const KernelTriangle& C = triangles[cur];
        const Vec3 e1 = Sub(C.p[1], C.p[0]);
        const Vec3 e2 = Sub(C.p[2], C.p[0]);
        const Vec3 v = Sub(point, C.p[0]);
        const double a = Dot(e1, e1);
        const double b = Dot(e1, e2);
        const double c = Dot(e2, e2);
        const double det = a * c - b * b;
        const double l1 = (c * Dot(e1, v) - b * Dot(e2, v)) / det;
        const double l2 = (a * Dot(e2, v) - b * Dot(e1, v)) / det;
        const std::array<double, 3> lam{1.0 - l1 - l2, l1, l2};
        size_t i = 0;
        for (size_t m = 1; m < 3; ++m) {
            if (lam[m] < lam[i]) i = m;
        }
        if (lam[i] >= 0.0) break;
        const uint32_t av = C.vertex[(i + 1) % 3];
        const uint32_t bv = C.vertex[(i + 2) % 3];
        const std::array<uint32_t, 2> edge{std::min(av, bv), std::max(av, bv)};
        if (edge == came) break;
        std::optional<uint32_t> next;
        for (const uint32_t n : edges.at({edge[0], edge[1]})) {
            if (n != cur) {
                next = n;
                break;
            }
        }
        if (!next) break;
        point = Fold(MakeHinge(C, triangles[*next], av, bv), point);
        cur = *next;
        came = edge;
        stages.push_back({TexelOf(triangles[cur], point), cur});
    }
    return stages;
}

const std::optional<RingGeometry::FaceHinge>& RingGeometry::HingeOf(uint32_t to, uint32_t from) const {
    const auto [it, added] = m_hinges.try_emplace({to, from});
    if (added) {
        for (const uint32_t i : m_faces[to]) {
            for (size_t e = 0; e < 3 && !it->second; ++e) {
                const uint32_t a = triangles[i].vertex[(e + 1) % 3];
                const uint32_t b = triangles[i].vertex[(e + 2) % 3];
                for (const uint32_t j : edges.at({std::min(a, b), std::max(a, b)})) {
                    if (triangles[j].face != from) continue;
                    it->second = FaceHinge{{i, j, a, b}, MakeHinge(triangles[i], triangles[j], a, b)};
                    break;
                }
            }
            if (it->second) break;
        }
    }
    return it->second;
}

const std::vector<std::vector<uint32_t>>& RingGeometry::Paths(uint32_t from, uint32_t to) const {
    const auto [it, added] = m_paths.try_emplace({from, to});
    if (!added) return it->second;
    std::deque<std::vector<uint32_t>> queue{{from}};
    size_t best = 0;
    while (!queue.empty()) {
        std::vector<uint32_t> path = std::move(queue.front());
        queue.pop_front();
        if (best != 0 && path.size() > best) break;
        if (path.back() == to) {
            best = path.size();
            it->second.push_back(std::move(path));
            continue;
        }
        if (path.size() > kMaxHinges) continue;
        for (const auto& link : m_links[path.back()]) {
            if (std::find(path.begin(), path.end(), link.first) != path.end()) continue;
            std::vector<uint32_t> longer = path;
            longer.push_back(link.first);
            queue.push_back(std::move(longer));
        }
    }
    return it->second;
}

bool RingGeometry::Hinged(uint32_t k, uint32_t tau) const {
    return triangles[k].face == triangles[tau].face || HingeOf(triangles[tau].face, triangles[k].face).has_value();
}

Vec3 RingGeometry::Frame(const Vec3& p, uint32_t k, uint32_t tau, const Vec3& q,
                         std::optional<uint32_t> window) const {
    const KernelTriangle& target = triangles[tau];
    if (triangles[k].chart != target.chart) {
        std::optional<uint32_t> source = window;
        double nearest = std::numeric_limits<double>::infinity();
        if (const auto island = seams.find(target.chart); island != seams.end()) {
            for (const SeamEdge& seam : island->second) {
                if (triangles[seam.farTriangle].chart != triangles[k].chart) continue;
                const KernelTriangle& E = triangles[seam.own];
                const double gap = SegmentGap(E.p[(seam.edge + 1) % 3], E.p[(seam.edge + 2) % 3], q);
                if (gap < nearest) {
                    source = seam.farTriangle;
                    nearest = gap;
                }
            }
        }
        if (source) return PlaneRotation(p, triangles[*source], target);
    }
    const uint32_t from = triangles[k].face;
    const uint32_t to = triangles[tau].face;
    if (from == to) return p;
    if (const auto& h = HingeOf(to, from)) return FoldedPast(triangles[k], triangles[tau]) ? Unfold(h->hinge, p) : p;
    // A far tap (k in another chart than tau) keeps its own chart rigid: a hinge whose two
    // triangles are both in k's chart is not rotated about (decision 342).
    const uint32_t chart = triangles[k].chart;
    const bool farTap = chart != triangles[tau].chart;
    std::optional<Vec3> nearest;
    for (const std::vector<uint32_t>& path : Paths(from, to)) {
        Vec3 r = p;
        for (size_t i = 0; i + 1 < path.size(); ++i) {
            // Into face path[i + 1]'s plane, about its first edge shared with face path[i].
            const auto& links = m_links[path[i + 1]];
            const FaceEdge& edge =
                std::find_if(links.begin(), links.end(), [&](const auto& l) { return l.first == path[i]; })->second;
            if (farTap && triangles[edge.own].chart == chart && triangles[edge.other].chart == chart) continue;
            if (!FoldedPast(triangles[edge.own], triangles[edge.other])) continue;
            r = Unfold(MakeHinge(triangles[edge.own], triangles[edge.other], edge.va, edge.vb), r);
        }
        if (!nearest || Norm(Sub(q, r)) < Norm(Sub(q, *nearest))) nearest = r;
    }
    return nearest.value_or(p);
}

using Float3 = std::array<float, 3>;

/// Decision 273's float32 position of texel (x, y)'s centre through triangle `k`, on a `width` x
/// `height` tile: the centre (u, v) = ((x + 1/2) / W, 1 - (y + 1/2) / H) takes barycentrics from
/// `k`'s UV inverse matrix based at its third corner, through the GPU's reciprocal of the
/// determinant, and interpolates the mesh-box-normalised positions as fma(l2, P2, fma(l0, P0,
/// l1 P1)). Every other operation is one correctly rounded float32 operation.
Float3 Position32(const KernelTriangle& k, uint32_t width, uint32_t height, uint32_t x, uint32_t y,
                  bool fusedDeterminant = false) {
    const auto& U = k.uv;
    const float e0u = U[0][0] - U[2][0];
    const float e0v = U[0][1] - U[2][1];
    const float e1u = U[1][0] - U[2][0];
    const float e1v = U[1][1] - U[2][1];
    const float a = e0u * e1v;
    const float b = e0v * e1u;
    const float determinant = fusedDeterminant ? std::fma(e0u, e1v, -b) : a - b;
    const float r = evaluator::hw::Rcp(determinant);
    const float m00 = e1v * r;
    const float m01 = -e1u * r;
    const float m10 = -e0v * r;
    const float m11 = e0u * r;
    const auto fw = static_cast<float>(width);
    const auto fh = static_cast<float>(height);
    const float pu = (static_cast<float>(x) + 0.5f) / fw;
    const float pv = 1.0f - (static_cast<float>(y) + 0.5f) / fh;
    const float dx = pu - U[2][0];
    const float dy = pv - U[2][1];
    const float l0 = std::fma(m00, dx, m01 * dy);
    const float l1 = std::fma(m10, dx, m11 * dy);
    const float sum = l0 + l1;
    const float l2 = 1.0f - sum;
    Float3 out{};
    for (size_t c = 0; c < 3; ++c) {
        const auto& n = k.normalised;
        out[c] = std::fma(l2, n[2][c], std::fma(l0, n[0][c], l1 * n[1][c]));
    }
    return out;
}

/// The recording GPU's float32 distance: the squared distance by FMA, then its square root.
float Distance32(const Float3& q, const Float3& p) {
    const float dx = q[0] - p[0];
    const float dy = q[1] - p[1];
    const float dz = q[2] - p[2];
    return evaluator::hw::Sqrt(std::fma(dz, dz, std::fma(dy, dy, dx * dx)));
}

/// Decision 273's comparator distance from the ring texel (rx, ry) to the tap (tx, ty), both
/// through triangle `k`.
float CompareDistance(const KernelTriangle& k, uint32_t width, uint32_t height, uint32_t rx, uint32_t ry, uint32_t tx,
                      uint32_t ty, bool fusedDeterminant = true) {
    const Float3 q = Position32(k, width, height, rx, ry, fusedDeterminant);
    const Float3 p = Position32(k, width, height, tx, ty, fusedDeterminant);
    const float dx = q[0] - p[0];
    const float dy = q[1] - p[1];
    const float dz = q[2] - p[2];
    // The own comparator and single-triangle weights evaluate y first; the far comparator stays separate.
    return evaluator::hw::Sqrt(std::fma(dz, dz, std::fma(dx, dx, dy * dy)));
}

// Float32 vector operations without contraction, each one correctly rounded operation.
Float3 Sub32(const Float3& a, const Float3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
Float3 Add32(const Float3& a, const Float3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
Float3 Scale32(const Float3& a, float s) { return {a[0] * s, a[1] * s, a[2] * s}; }
float Dot32(const Float3& a, const Float3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Float3 Cross32(const Float3& a, const Float3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
/// `a` divided by its length, the GPU's square root of its float32 squared length.
Float3 Unit32(const Float3& a) {
    const float length = evaluator::hw::Sqrt(Dot32(a, a));
    return {a[0] / length, a[1] / length, a[2] / length};
}

/// `p`, decision 273's float32 position of a point of triangle `E`, rotated in float32 about E's
/// edge `edge` into the plane of its far triangle `J` (decision 282 finding 3): Fold over the
/// box-normalised positions, each operation a correctly rounded float32 one.
Float3 Fold32(const Float3& p, const KernelTriangle& E, size_t edge, const KernelTriangle& J) {
    const auto local = [](const KernelTriangle& t, uint32_t v) {
        return static_cast<size_t>(std::find(t.vertex.begin(), t.vertex.end(), v) - t.vertex.begin());
    };
    const uint32_t va = E.vertex[(edge + 1) % 3];
    const uint32_t vb = E.vertex[(edge + 2) % 3];
    const size_t ia = local(E, va);
    const size_t ib = local(E, vb);
    const size_t ja = local(J, va);
    const size_t jb = local(J, vb);
    const Float3& a = E.normalised[ia];
    const Float3 axis = Unit32(Sub32(E.normalised[ib], a));
    const auto across = [&](const Float3& to3) {
        const Float3 v = Sub32(to3, a);
        return Unit32(Sub32(v, Scale32(axis, Dot32(v, axis))));
    };
    const Float3 inOwn = across(E.normalised[3 - ia - ib]);
    const Float3 inOther = across(J.normalised[3 - ja - jb]);
    const Float3 v = Sub32(p, a);
    const float s = Dot32(v, axis);
    const Float3 r = Sub32(v, Scale32(axis, s));
    const Float3 toward = Scale32(inOwn, -1.0f);
    const float along = Dot32(r, toward);
    const float out = Dot32(r, Cross32(axis, toward));
    return Add32(Add32(a, Scale32(axis, s)), Add32(Scale32(inOther, along), Scale32(Cross32(axis, inOther), out)));
}

struct Candidate {
    RingTap tap;
    size_t texel = 0;
    uint32_t triangle = 0;
    uint32_t seam = 0;                 // a far tap: E, the own triangle of the first seam edge whose
    std::array<int64_t, 2> window{};   // window holds it, that window's base (col0, row0), the edge
    size_t edge = 0;                   // of E and its far triangle J
    uint32_t farTriangle = 0;
    bool multiFacet = false;           // its distance develops it along a face path (decision 281)
    uint8_t tie = 0;                   // the open tie classes of its group of equal distances (Ordered)
};

/// Decision 278's seam gate of one seam edge for the ring texel's triangle tau, its ring point q and
/// the edge's far triangle J: `gated` when tau's and J's float32 unit normals meet at a dot product
/// of at most kFoldGate (tau's normal, not that of the edge's own triangle E: decision 292) and q
/// lies behind J's plane (n_J . (q - p) < 0, p the edge's first vertex).
/// `bracket` when the dot product lies in (kFoldLow, kFoldHigh] and q lies behind J, `onPlane` when
/// q lies on J's plane and the dot product is at most kFoldHigh: there the gate is not identified.
struct SeamGate {
    bool gated = false;
    bool bracket = false;
    bool onPlane = false;
};

SeamGate GateOf(const KernelTriangle& T, const KernelTriangle& J, const Vec3& q, const Vec3& p) {
    const float dot = T.normal[0] * J.normal[0] + T.normal[1] * J.normal[1] + T.normal[2] * J.normal[2];
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

/// Whether the one-texel seam strip of edge `edge` of `k` (straight ends) covers the sample point
/// (px, py): inside, or on an edge of the strip whose outward normal points to -u, or to -v (up the
/// tile) for an edge with no u component (the top-left fill rule).
bool StripCovers(const KernelTriangle& k, size_t edge, double px, double py) {
    const auto& a = k.t[(edge + 1) % 3];
    const auto& b = k.t[(edge + 2) % 3];
    const double ex = b[0] - a[0];
    const double ey = b[1] - a[1];
    const double length2 = ex * ex + ey * ey;
    const double along = (px - a[0]) * ex + (py - a[1]) * ey;
    const double cross = (px - a[0]) * ey - (py - a[1]) * ex;
    const double half = 0.5 * std::sqrt(length2);
    if (along < 0.0 || along > length2 || std::abs(cross) > half) return false;
    const auto kept = [](double nx, double ny) { return nx < 0.0 || (nx == 0.0 && ny < 0.0); };
    return (along != 0.0 || kept(-ex, -ey)) && (along != length2 || kept(ex, ey)) &&
           (cross != half || kept(ey, -ex)) && (cross != -half || kept(-ey, ex));
}

/// The rank in `order` of the offset (du, dv).
template <size_t N>
size_t Rank(const std::array<std::array<int, 2>, N>& order, int64_t du, int64_t dv) {
    for (size_t i = 0; i < N; ++i) {
        if (order[i][0] == du && order[i][1] == dv) return i;
    }
    return N;
}

/// `out` in tap order: nearest first; within a group of distances equal to kEqualShare relative
/// (decisions 280, 282 and 294) by the float32 distance (an own tap's decision 273 comparator; a far
/// tap's |fold(q_E) - P|, q_E the ring texel's decision-273 position through E, rotated into J's
/// plane about the seam edge when it is folded past the gate, Fold32, and P the tap's through its
/// own triangle, not rotated), then own taps before far ones, then kOwnOrder or kWindowOrder; then
/// adjacent own taps within kOwnBand relative by the comparator, then kOwnOrder (decision 294).
/// Each candidate's `tie` holds its group's open tie classes. The first kKeptCandidates.
std::vector<Candidate> Ordered(const RingGeometry& g, uint32_t x, uint32_t y, std::vector<Candidate> out) {
    std::sort(out.begin(), out.end(), [](const Candidate& a, const Candidate& b) {
        return a.tap.distance != b.tap.distance ? a.tap.distance < b.tap.distance : a.texel < b.texel;
    });
    // An own tap's decision 273 comparator distance and its kOwnOrder rank.
    const auto ownKey = [&](const Candidate& c) {
        int64_t du = static_cast<int64_t>(c.tap.x) - x;  // x wraps
        if (du > 1) du -= g.width;
        if (du < -1) du += g.width;
        const int64_t dv = static_cast<int64_t>(y) - c.tap.y;
        return std::pair<float, size_t>{
            CompareDistance(g.triangles[c.triangle], g.width, g.height, x, y, c.tap.x, c.tap.y),
            Rank(kOwnOrder, du, dv)};
    };
    struct Keyed {
        float distance = 0.0f;
        size_t rank = 0;
        Candidate c;
    };
    for (size_t first = 0; first < out.size();) {
        size_t last = first + 1;
        while (last < out.size() && out[last].tap.distance <= out[first].tap.distance * (1.0 + kEqualShare)) ++last;
        if (last - first > 1) {
            std::vector<Keyed> group;
            for (size_t i = first; i < last; ++i) {
                const Candidate& c = out[i];
                const KernelTriangle& k = g.triangles[c.triangle];
                if (!c.tap.across_seam) {
                    const auto [distance, rank] = ownKey(c);
                    group.push_back({distance, rank, c});
                } else {
                    const KernelTriangle& E = g.triangles[c.seam];
                    const KernelTriangle& J = g.triangles[c.farTriangle];
                    Float3 qE = Position32(E, g.width, g.height, x, y);
                    if (FoldedPast(E, J)) qE = Fold32(qE, E, c.edge, J);
                    const Float3 p = Position32(k, g.width, g.height, c.tap.x, c.tap.y);
                    group.push_back({Distance32(qE, p),
                                     Rank(kWindowOrder, c.tap.x - c.window[0], c.window[1] - c.tap.y), c});
                }
            }
            // The float32 distance first; own before far only at equal ones (decision 294 (b)).
            std::stable_sort(group.begin(), group.end(), [](const Keyed& a, const Keyed& b) {
                if (a.distance != b.distance) return a.distance < b.distance;
                if (a.c.tap.across_seam != b.c.tap.across_seam) return !a.c.tap.across_seam;
                return a.rank < b.rank;
            });
            // The tie classes the data leave open (decision 280 decision 2).
            uint8_t tie = 0;
            for (size_t i = 0; i < group.size(); ++i) {
                for (size_t j = i + 1; j < group.size(); ++j) {
                    const Keyed& a = group[i];
                    const Keyed& b = group[j];
                    if (a.c.tap.across_seam != b.c.tap.across_seam) {
                        if (a.distance == b.distance) tie |= kTieOwnFar;
                    } else if (!a.c.tap.across_seam) {
                        if (a.distance == b.distance && OwnOrderOpen(a.rank, b.rank)) tie |= kTieOwnOrder;
                    } else {
                        if (g.triangles[a.c.triangle].face != g.triangles[b.c.triangle].face) tie |= kTieFarFold;
                        if (a.distance == b.distance && (a.c.seam != b.c.seam || a.c.window != b.c.window ||
                                                         WindowOrderOpen(a.rank, b.rank))) {
                            tie |= kTieFarOrder;
                        }
                    }
                }
            }
            for (size_t i = first; i < last; ++i) {
                out[i] = group[i - first].c;
                out[i].tie = tie;
            }
        }
        first = last;
    }
    // Decision 294 (c): adjacent own taps within kOwnBand relative, by the comparator, then kOwnOrder
    // (an open pair tied on the comparator flagged), swapped pass by pass until none moves.
    std::map<size_t, std::pair<float, size_t>> compared;
    const auto key = [&](const Candidate& c) {
        const auto it = compared.find(c.texel);
        return it != compared.end() ? it->second : compared.emplace(c.texel, ownKey(c)).first->second;
    };
    for (bool changed = true; changed;) {
        changed = false;
        for (size_t i = 0; i + 1 < out.size(); ++i) {
            Candidate& a = out[i];
            Candidate& b = out[i + 1];
            if (a.tap.across_seam || b.tap.across_seam || b.tap.distance > a.tap.distance * (1.0 + kOwnBand)) continue;
            const auto ka = key(a);
            const auto kb = key(b);
            if (ka.first == kb.first && OwnOrderOpen(ka.second, kb.second)) {
                a.tie |= kTieOwnOrder;
                b.tie |= kTieOwnOrder;
            }
            if (kb < ka) {
                std::swap(a, b);
                changed = true;
            }
        }
    }
    if (out.size() > kKeptCandidates) out.resize(kKeptCandidates);
    return out;
}

/// The chain's number of taps over `candidates` (tap order): the 4 nearest, or 1 when the nearest
/// lies at distance 0 relative to the nearest own candidate. A list without own candidates is never
/// a copy (decision 280 finding 4): its scale is its farthest candidate.
uint32_t TapCount(const std::vector<Candidate>& candidates) {
    double nearest = std::numeric_limits<double>::infinity();
    for (const Candidate& c : candidates) {
        if (!c.tap.across_seam) nearest = std::min(nearest, c.tap.distance);
    }
    if (std::isinf(nearest)) nearest = candidates.back().tap.distance;
    return candidates[0].tap.distance > kZeroDistance * nearest
               ? static_cast<uint32_t>(std::min(kMaxTaps, candidates.size()))
               : 1u;
}

/// Whether the chains over `a` and `b` (tap order) take the same taps at the same distances.
bool SameTaps(const std::vector<Candidate>& a, const std::vector<Candidate>& b) {
    const uint32_t n = TapCount(a);
    if (TapCount(b) != n) return false;
    for (uint32_t i = 0; i < n; ++i) {
        if (a[i].texel != b[i].texel || a[i].tap.across_seam != b[i].tap.across_seam || a[i].tap.distance != b[i].tap.distance) {
            return false;
        }
    }
    return true;
}

/// A ring texel's candidates in tap order, and where decisions 278's gate, 285's reach and 291's
/// window side do not decide them.
struct CandidateSet {
    std::vector<Candidate> candidates;
    bool foldBracket = false;
    bool onFarPlane = false;
    bool mixedGates = false;
    bool reachBracket = false;
    bool cornerReachBracket = false;
    bool windowSide = false;
};

/// An axis (0 u, 1 v) of the far point of a seam edge (an index into Candidates' edges).
using WindowAxis = std::array<size_t, 2>;

/// The candidates of ring texel (x, y) with q extrapolated through `tau` (decisions 275, 278, 279,
/// 285, 288, 290, 291, 292). The far windows of the axes in `flipped` are taken on the other side
/// of their boundary (decision 291); with any, only the candidates are computed.
CandidateSet Candidates(const RingGeometry& g, uint32_t x, uint32_t y, const std::vector<size_t>& own, uint32_t tau,
                        const std::vector<WindowAxis>& flipped = {}) {
    const KernelTriangle& T = g.triangles[tau];
    const std::array<double, 3> l = TexelBary(T, x + 0.5, y + 0.5);
    const Vec3 q = Point(T, l);
    // Each texel the ring may read: an own neighbour, or a far texel in the window of some seam edges.
    struct Entry {
        size_t texel = 0;
        uint32_t triangle = 0;
        double frame = 0.0;    // |q - P|, P in tau's frame (or |q_K - P|): the distance of an own tap of tau's island or a far tap
        double outside = -1;   // an own neighbour outside tau's island: min(|q_k - P|, |q - P|) (decision 279)
        bool own = false;
        bool multiFacet = false;    // in a face with no 3D edge to tau's face (decision 281)
        std::vector<uint32_t> via;  // the seam edges (indices into `edges`) whose window holds it
    };
    std::vector<Entry> pool;
    const auto entry = [&](size_t texel, std::optional<uint32_t> window = std::nullopt) -> Entry& {
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
        e.frame = Norm(Sub(q, g.Frame(p, e.triangle, tau, q, window)));
        e.multiFacet = !g.Hinged(e.triangle, tau);
        if (k.chart != T.chart) {
            e.outside = std::min(Norm(Sub(Point(k, TexelBary(k, x + 0.5, y + 0.5)), p)), Norm(Sub(q, p)));
        }
        pool.push_back(std::move(e));
        return pool.back();
    };
    for (const size_t texel : own) {
        Entry& e = entry(texel);
        e.own = true;
        // An own neighbour of tau's island in another triangle K that shares a UV edge (two corners)
        // with tau is measured through K: |q_K - P|, q_K the ring texel's centre extrapolated through
        // K (decision 285 finding 2). One sharing a corner only keeps tau's frame (decision 279).
        const KernelTriangle& k = g.triangles[e.triangle];
        if (e.triangle == tau || k.chart != T.chart) continue;
        size_t shared = 0;
        for (const uint32_t c : k.corner) shared += std::count(T.corner.begin(), T.corner.end(), c);
        if (shared < 2) continue;
        const Vec3 p = Point(k, TexelBary(k, static_cast<double>(texel % g.width) + 0.5,
                                          static_cast<double>(texel / g.width) + 0.5));
        e.frame = Norm(Sub(Point(k, TexelBary(k, x + 0.5, y + 0.5)), p));
        e.multiFacet = false;
    }
    // The seam edges of every island that owns an own neighbour whose UV segment lies within
    // kReachCap texels of the ring texel's centre (decisions 279 and 285; those within kReachHigh
    // are kept for the reach flag), each through decision 278's gate:
    // q folded about the edge into the far triangle J, f its point in J's texel space, and the
    // covered texels, of any island (decision 364), in the 3 x 3 block of columns
    // floor(f_u - 1/2) +- 1 and rows ceil(f_v - 1/2) +- 1 (decision 275). No edge whose far
    // triangle is tau (decision 288) or whose UV ends both lie on the tile's left or right border
    // (decision 290) opens a window. The axes whose f - 1/2 lies within kWindowSide of an integer
    // are kept (decision 291).
    std::vector<uint32_t> charts;
    for (const size_t texel : own) charts.push_back(g.triangles[static_cast<size_t>(g.owner[texel])].chart);
    std::sort(charts.begin(), charts.end());
    charts.erase(std::unique(charts.begin(), charts.end()), charts.end());
    struct Edge {
        SeamGate gate;
        double reach = 0.0;
        uint32_t own = 0;                // E
        std::array<int64_t, 2> window{};  // the far window's base (col0, row0)
        size_t edge = 0;                  // the edge of E
        uint32_t farTriangle = 0;         // J
        // Decision 294 (a): E lies outside tau's planar face and the edge's nearest point to the
        // texel centre is an end V; another edge of `edges` ending at V is gated; the least UV |sin|
        // with another seam edge of E's island ending at V (infinite when none).
        bool corner = false;
        bool gatedAtEnd = false;
        double sine = std::numeric_limits<double>::infinity();
    };
    std::vector<Edge> edges;
    std::vector<WindowAxis> sides;
    // One strip map shared by every island (decision 356): each one-texel seam strip (top-left fill)
    // is drawn in mesh order (own triangle, edge, far triangle), including uncovered samples, and
    // the last seam drawn owns each sample. Ownership is resolved before the gate, tau and
    // tile-border exclusions; an island's query discovers every seam of a run whose seam owns a
    // sample of the 3x3 neighbourhood.
    std::array<std::optional<RingGeometry::DrawnSeam>, 9> winners{};
    size_t sample = 0;
    for (int dx = -1; dx <= 1; ++dx) {
        for (int dy = -1; dy <= 1; ++dy, ++sample) {
            const auto cell = g.strips.find(StripCell(static_cast<int64_t>(x) + dx, static_cast<int64_t>(y) + dy));
            if (cell == g.strips.end()) continue;
            const double px = static_cast<double>(x) + dx + 0.5;
            const double py = static_cast<double>(y) + dy + 0.5;
            for (const uint32_t d : cell->second) {
                const RingGeometry::DrawnSeam& drawn = g.drawOrder[d];
                const SeamEdge& seam = g.seams.at(drawn.chart)[drawn.index];
                if (StripCovers(g.triangles[seam.own], seam.edge, px, py)) winners[sample] = drawn;
            }
        }
    }
    for (const uint32_t chart : charts) {
        const auto seams = g.seams.find(chart);
        if (seams == g.seams.end()) continue;
        const auto owned = [&](uint32_t run) {
            return std::any_of(winners.begin(), winners.end(), [&](const auto& w) {
                return w && w->chart == chart && seams->second[w->index].run == run;
            });
        };
        for (const SeamEdge& seam : seams->second) {
            const KernelTriangle& E = g.triangles[seam.own];
            const double ua = E.t[(seam.edge + 1) % 3][0];
            if (seam.farTriangle == tau || (ua == E.t[(seam.edge + 2) % 3][0] && (ua == 0.0 || ua == g.width))) {
                continue;
            }
            const double reach = SegmentDistance(E, seam.edge, x + 0.5, y + 0.5);
            if (reach >= kReachHigh || !owned(seam.run)) continue;
            const KernelTriangle& J = g.triangles[seam.farTriangle];
            const uint32_t va = E.vertex[(seam.edge + 1) % 3];
            const uint32_t vb = E.vertex[(seam.edge + 2) % 3];
            const auto index = static_cast<uint32_t>(edges.size());
            // Decision 365: an island that covers no texel centre is transparent; the far point is
            // carried on across it to the first stage in a covered island, whose triangle is the
            // window's J for the frame.
            const std::vector<RingGeometry::HopStage> stages = g.Hop(seam.own, seam.farTriangle, va, vb, q);
            std::array<double, 2> farPoint = stages.front().f;
            uint32_t windowTriangle = seam.farTriangle;
            if (!g.coveredCharts.contains(J.chart)) {
                for (size_t s = 1; s < stages.size(); ++s) {
                    if (g.coveredCharts.contains(g.triangles[stages[s].triangle].chart)) {
                        farPoint = stages[s].f;
                        windowTriangle = stages[s].triangle;
                        break;
                    }
                }
            }
            std::array<int64_t, 2> base{static_cast<int64_t>(std::floor(farPoint[0] - 0.5)),
                                        static_cast<int64_t>(std::ceil(farPoint[1] - 0.5))};
            for (size_t axis = 0; axis < 2; ++axis) {
                const double m = farPoint[axis] - 0.5;
                const double boundary = std::round(m);
                if (!(std::abs(m - boundary) < kWindowSide)) continue;
                sides.push_back({index, axis});
                if (std::find(flipped.begin(), flipped.end(), WindowAxis{index, axis}) == flipped.end()) continue;
                // The other side: columns boundary - 1 | boundary, rows boundary | boundary + 1.
                const auto n = static_cast<int64_t>(boundary);
                base[axis] = (axis == 0 ? 2 * n - 1 : 2 * n + 1) - base[axis];
            }
            const auto [col0, row0] = base;
            edges.push_back({GateOf(T, J, q, E.p[(seam.edge + 1) % 3]), reach, seam.own, base, seam.edge,
                             seam.farTriangle});
            for (int64_t row = row0 - kFarReach; row <= row0 + kFarReach; ++row) {
                for (int64_t col = col0 - kFarReach; col <= col0 + kFarReach; ++col) {
                    if (row < 0 || col < 0 || row >= g.height || col >= g.width) continue;
                    const size_t texel = static_cast<size_t>(row) * g.width + static_cast<size_t>(col);
                    // Every covered texel, of any island (decision 364): a texel of tau's island
                    // that is not an own neighbour becomes a far tap at its frame distance.
                    if (g.owner[texel] < 0) continue;
                    Entry& e = entry(texel, windowTriangle);
                    if (e.via.empty() || e.via.back() != index) e.via.push_back(index);
                }
            }
        }
    }
    // Decision 294 (a): which edges end at a UV corner beyond the texel's projection onto them.
    const double px = x + 0.5;
    const double py = y + 0.5;
    const auto endsOf = [&](uint32_t triangle, size_t edge) {
        const KernelTriangle& k = g.triangles[triangle];
        return std::array<std::array<double, 2>, 2>{k.t[(edge + 1) % 3], k.t[(edge + 2) % 3]};
    };
    for (size_t i = 0; i < edges.size(); ++i) {
        Edge& edge = edges[i];
        const KernelTriangle& E = g.triangles[edge.own];
        const auto [a, b] = endsOf(edge.own, edge.edge);
        const double ex = b[0] - a[0];
        const double ey = b[1] - a[1];
        const double along = ((px - a[0]) * ex + (py - a[1]) * ey) / (ex * ex + ey * ey);
        if (E.face == T.face || (along >= 0.0 && along <= 1.0)) continue;
        const std::array<double, 2> v = along < 0.0 ? a : b;
        edge.corner = true;
        for (const SeamEdge& seam : g.seams.at(E.chart)) {
            const auto [c, d] = endsOf(seam.own, seam.edge);
            if ((seam.own == edge.own && seam.edge == edge.edge) || (c != v && d != v)) continue;
            const double fx = d[0] - c[0];
            const double fy = d[1] - c[1];
            const double length = std::sqrt(ex * ex + ey * ey) * std::sqrt(fx * fx + fy * fy);
            edge.sine = std::min(edge.sine, std::abs(ex * fy - ey * fx) / length);
        }
        for (size_t k = 0; k < edges.size(); ++k) {
            const auto [c, d] = endsOf(edges[k].own, edges[k].edge);
            if (k != i && edges[k].gate.gated && (c == v || d == v)) edge.gatedAtEnd = true;
        }
    }
    // The reaches (decision 285's cap, decision 294's corner caps and collinear threshold).
    struct Reaches {
        double cap = kReachCap;
        double gated = kCornerGated;
        double open = kCornerOpen;
        double collinear = kCollinear;
    };
    const auto within = [&](const Edge& e, const Reaches& r) {
        if (e.corner && e.sine > r.collinear) return e.reach <= (e.gatedAtEnd ? r.gated : r.open);
        return e.reach <= r.cap;
    };
    // The candidates when the edges that reach the texel under `reaches` and are `open` feed the
    // far windows: an own neighbour of tau's island is an own tap; any other texel is a far tap
    // when an open edge's window holds it, else an own neighbour outside tau's island is an own
    // tap at its `outside` distance (decision 279). A far tap's E and window are those of the
    // first reaching edge that holds it.
    const auto build = [&](const auto& open, const Reaches& reaches) {
        std::vector<Candidate> out;
        for (const Entry& e : pool) {
            const auto tx = static_cast<uint32_t>(e.texel % g.width);
            const auto ty = static_cast<uint32_t>(e.texel / g.width);
            const bool inside = e.own && e.outside < 0.0;
            if (!inside && std::any_of(e.via.begin(), e.via.end(), [&](uint32_t i) {
                    return within(edges[i], reaches) && open(edges[i]);
                })) {
                const Edge& first = edges[*std::find_if(e.via.begin(), e.via.end(),
                                                        [&](uint32_t i) { return within(edges[i], reaches); })];
                out.push_back({{tx, ty, e.frame, true},
                               e.texel,
                               e.triangle,
                               first.own,
                               first.window,
                               first.edge,
                               first.farTriangle,
                               e.multiFacet});
            } else if (e.own) {
                out.push_back({{tx, ty, inside ? e.frame : e.outside, false},
                               e.texel,
                               e.triangle,
                               0,
                               {},
                               0,
                               0,
                               inside && e.multiFacet});
            }
        }
        return Ordered(g, x, y, std::move(out));
    };
    const auto kept = [](const Edge& e) { return !e.gate.gated; };
    const Reaches nominal{};
    CandidateSet out{build(kept, nominal)};
    if (edges.empty() || !flipped.empty()) return out;
    // Decision 291: a far window taken on the other side of its boundary, on any subset of the near
    // axes, that changes the taps; with more than kWindowSides near axes, untried.
    if (sides.size() > kWindowSides) {
        out.windowSide = true;
    } else {
        for (uint32_t chosen = 1; chosen < (1u << sides.size()) && !out.windowSide; ++chosen) {
            std::vector<WindowAxis> subset;
            for (size_t i = 0; i < sides.size(); ++i) {
                if (((chosen >> i) & 1u) != 0) subset.push_back(sides[i]);
            }
            out.windowSide = !SameTaps(out.candidates, Candidates(g, x, y, own, tau, subset).candidates);
        }
    }
    // Where the rule is not identified: a reach cap anywhere in [kReachLow, kReachHigh) changes the
    // taps (decision 285 finding 3); a corner cap anywhere in its bracket, or a collinear threshold
    // anywhere in [kCollinearLow, kCollinearHigh), changes them (decision 294). Each is tried at its
    // bracket's low end and at each edge's value inside it (the settings that differ). An edge
    // whose window gives the chain a tap, with the gate or without it, has its fold in the bracket
    // or q on its far plane, or two such edges are gated differently (decision 278 open items (a)
    // and (b)).
    const auto bracket = [&](double Reaches::* slot, double low, double high, double Edge::* value) {
        std::vector<double> settings{low};
        for (const Edge& e : edges) {
            if (e.*value > low && e.*value < high) settings.push_back(e.*value);
        }
        return std::any_of(settings.begin(), settings.end(), [&](double setting) {
            Reaches tried;
            tried.*slot = setting;
            const bool same = std::none_of(edges.begin(), edges.end(), [&](const Edge& e) {
                return within(e, tried) != within(e, nominal);
            });
            return !same && !SameTaps(out.candidates, build(kept, tried));
        });
    };
    out.reachBracket = bracket(&Reaches::cap, kReachLow, kReachHigh, &Edge::reach);
    out.cornerReachBracket = bracket(&Reaches::gated, kCornerGatedLow, kCornerGatedHigh, &Edge::reach) ||
                             bracket(&Reaches::open, kCornerOpenLow, kCornerOpenHigh, &Edge::reach) ||
                             bracket(&Reaches::collinear, kCollinearLow, kCollinearHigh, &Edge::sine);
    const std::vector<Candidate> ungated = build([](const Edge&) { return true; }, nominal);
    std::vector<uint8_t> reaches(edges.size(), 0);
    for (const std::vector<Candidate>* list : {&std::as_const(out.candidates), &ungated}) {
        const uint32_t n = TapCount(*list);
        for (uint32_t i = 0; i < n; ++i) {
            if (!(*list)[i].tap.across_seam) continue;
            for (const Entry& e : pool) {
                if (e.texel != (*list)[i].texel) continue;
                for (const uint32_t v : e.via) {
                    if (within(edges[v], nominal)) reaches[v] = 1;
                }
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
std::vector<float> Fractions(const RingGeometry& g, uint32_t x, uint32_t y, uint32_t tau,
                             const std::vector<Candidate>& candidates, uint32_t n) {
    std::array<double, kMaxTaps> distances{};
    bool singleOwnTriangle = n > 1;
    for (uint32_t i = 0; i < n; ++i) {
        const Candidate& c = candidates[i];
        distances[i] = c.tap.distance;
        singleOwnTriangle = singleOwnTriangle && !c.tap.across_seam && c.triangle == tau;
    }
    if (singleOwnTriangle) {
        // Only the chain's shares use float32 positions; tap selection and flags keep their geometry.
        std::array<double, kMaxTaps> measured{};
        bool usable = true;
        for (uint32_t i = 0; i < n; ++i) {
            const RingTap& tap = candidates[i].tap;
            measured[i] = CompareDistance(g.triangles[tau], g.width, g.height, x, y, tap.x, tap.y);
            usable = usable && std::isfinite(measured[i]) && measured[i] > 0.0;
        }
        // A collapsed normalised position cannot define a reciprocal weight.
        if (usable) distances = measured;
    }
    std::vector<float> t;
    for (uint32_t level = 0; level + 1 < n; ++level) {
        double sum = 0.0;
        for (uint32_t j = level; j < n; ++j) sum += 1.0 / distances[j];
        const double share = (1.0 / distances[level]) / sum;
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
/// through 1 - (1 - m) (decision 206) when `rounded`; the Height the virtual normal's stencil reads
/// is the chain's raw value (decision 288 (a)).
float Chain(const std::array<float, kMaxTaps>& v, uint32_t n, const std::vector<float>& t, bool rounded = true) {
    float m = v[0];
    if (n > 1) {
        const float last = 1.0f - t[n - 2];
        m = std::fma(last, v[n - 1] - v[n - 2], v[n - 2]);
        for (uint32_t level = n - 2; level-- > 0;) m = std::fma(t[level], v[level] - m, m);
    }
    if (!rounded) return m;
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
                    // Tau keeps the split determinant; only final own ordering fuses it.
                    const float d = CompareDistance(g.triangles[k], g.width, g.height, rx, ry, tx, ty, false);
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
            r.fractions = Fractions(g, rx, ry, triangles[0], set.candidates, r.taps);
            r.foldBracket = set.foldBracket;
            r.onFarPlane = set.onFarPlane;
            r.mixedGates = set.mixedGates;
            r.reachBracket = set.reachBracket;
            r.cornerReachBracket = set.cornerReachBracket;
            r.windowSide = set.windowSide;
            for (uint32_t i = 0; i < r.taps; ++i) {
                const Candidate& c = set.candidates[i];
                r.ownFarTie = r.ownFarTie || (c.tie & kTieOwnFar) != 0;
                r.ownOrder = r.ownOrder || (c.tie & kTieOwnOrder) != 0;
                r.farFold = r.farFold || (c.tie & kTieFarFold) != 0;
                r.farOrder = r.farOrder || (c.tie & kTieFarOrder) != 0;
                r.multiFacet = r.multiFacet || c.multiFacet;
            }
            for (size_t i = 1; i < triangles.size(); ++i) {
                r.alternatives.push_back(Taps(Candidates(g, rx, ry, own, triangles[i]).candidates));
            }
            ring.push_back(std::move(r));
        }
    }
    return ring;
}


/// The jump flood (padding.h step 2): every texel that is not a `seed` copies the `channels` values
/// of its seed among them; each step reads the previous step's seeds, clamped to the image.
void JumpFlood(const Coverage& coverage, const std::vector<uint8_t>& seed, uint32_t channels,
               std::vector<float>& values) {
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    const auto index = [&](auto y, auto x) { return static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x); };
    const auto copy = [&](size_t from, size_t to) {
        std::copy_n(values.begin() + static_cast<std::ptrdiff_t>(from * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(to * channels));
    };
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
                    // A read outside the image is clamped to its nearest edge texel (decision 285).
                    const int yy = std::clamp(y + dy * k, 0, height - 1);
                    const int xx = std::clamp(x + dx * k, 0, width - 1);
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

void CheckValues(const Coverage& coverage, uint32_t channels, const std::vector<float>& values) {
    if (channels == 0 || channels > 4 || values.size() != size_t{coverage.width} * coverage.height * channels) {
        throw std::invalid_argument("export: infinite padding takes 1 to 4 values per texel");
    }
}

// `infinite` padding over incomplete coverage (padding.h): the ring, then the jump flood; the
// ring's chain rounded through 1 - (1 - m) when `rounded`.
void InfinitePadding(const Coverage& coverage, uint32_t channels, std::vector<float>& values, bool rounded = true) {
    CheckValues(coverage, channels, values);
    const auto index = [&](auto y, auto x) { return static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x); };
    // 1. The ring, from the covered texels only.
    std::vector<uint8_t> seed(coverage.covered);
    const std::vector<RingTexel> ringTexels = RingOf(coverage);
    std::vector<float> ring;
    ring.reserve(ringTexels.size() * channels);
    for (const RingTexel& r : ringTexels) {
        for (uint32_t c = 0; c < channels; ++c) {
            std::array<float, kMaxTaps> v{};
            for (uint32_t i = 0; i < r.taps; ++i) {
                v[i] = values[index(r.candidates[i].y, r.candidates[i].x) * channels + c];
            }
            ring.push_back(Chain(v, r.taps, r.fractions, rounded));
        }
    }
    for (size_t i = 0; i < ringTexels.size(); ++i) {
        const size_t texel = index(ringTexels[i].y, ringTexels[i].x);
        std::copy_n(ring.begin() + static_cast<std::ptrdiff_t>(i * channels), channels,
                    values.begin() + static_cast<std::ptrdiff_t>(texel * channels));
        seed[texel] = 1;
    }
    // 2. The jump flood over the covered and ring texels.
    JumpFlood(coverage, seed, channels, values);
}

/// The Normal's ring classes (decision 287), per texel: 0 covered; 1 a ring texel with a covered
/// 8-neighbour without wrap-around; 2 a ring texel whose covered 8-neighbours all lie across the
/// x border (x wraps for the ring, as for the Height's); 3 any other texel.
std::vector<uint8_t> NormalRingClasses(const Coverage& coverage) {
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    std::vector<uint8_t> classes(coverage.covered.size(), 3);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const size_t t = static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x);
            if (coverage.covered[t] != 0) {
                classes[t] = 0;
                continue;
            }
            bool direct = false;
            bool wrapped = false;
            for (const auto& [dy, dx] : kNeighbours) {
                const int yy = y + dy;
                if (yy < 0 || yy >= height) continue;
                const int xx = ((x + dx) % width + width) % width;
                if (coverage.covered[static_cast<size_t>(yy) * coverage.width + static_cast<size_t>(xx)] == 0) continue;
                if (x + dx < 0 || x + dx >= width) {
                    wrapped = true;
                } else {
                    direct = true;
                }
            }
            classes[t] = direct ? 1 : wrapped ? 2 : 3;
        }
    }
    return classes;
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
    if (std::optional<std::string> refusal = PaddingRefusal(file, coverage, inexact)) {
        throw core::NotYetSupported(*refusal);
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
    if (std::optional<std::string> refusal = IslandNormalFileRefusal(file, coverage)) {
        throw core::NotYetSupported(*refusal);
    }
}

void PadIslandHeight(const Coverage& coverage, std::vector<float>& operands) {
    InfinitePadding(coverage, 1, operands, false);
}

bool NormalRingAcrossBorder(const Coverage& coverage) {
    const std::vector<uint8_t> classes = NormalRingClasses(coverage);
    return std::find(classes.begin(), classes.end(), uint8_t{2}) != classes.end();
}

void PadIslandNormal(const Coverage& coverage, std::vector<float>& normals) {
    constexpr uint32_t kChannels = 3;
    CheckValues(coverage, kChannels, normals);
    const int width = static_cast<int>(coverage.width);
    const int height = static_cast<int>(coverage.height);
    const std::vector<uint8_t> classes = NormalRingClasses(coverage);
    std::vector<uint8_t> seed(classes.size(), 0);
    // 1. The ring (decision 287): a copy of the nearest covered 8-neighbour without wrap-around,
    // in the flood's offset order (its side neighbours come before its diagonal ones, so the
    // first covered one is the nearest, ties in that order); a ring texel whose covered
    // neighbours all lie across the x border keeps its value. Both seed the gutter.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const size_t t = static_cast<size_t>(y) * coverage.width + static_cast<size_t>(x);
            if (classes[t] == 3) continue;
            seed[t] = 1;
            if (classes[t] != 1) continue;
            for (const auto& [dy, dx] : kFloodOffsets) {
                const int yy = y + dy;
                const int xx = x + dx;
                if (yy < 0 || yy >= height || xx < 0 || xx >= width) continue;
                const size_t from = static_cast<size_t>(yy) * coverage.width + static_cast<size_t>(xx);
                if (coverage.covered[from] == 0) continue;
                std::copy_n(normals.begin() + static_cast<std::ptrdiff_t>(from * kChannels), kChannels,
                            normals.begin() + static_cast<std::ptrdiff_t>(t * kChannels));
                break;
            }
        }
    }
    // 2. The gutter: decision 197's flood over the covered and ring texels, its reads clamped
    // (decision 285).
    JumpFlood(coverage, seed, kChannels, normals);
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
