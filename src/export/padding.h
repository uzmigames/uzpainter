#pragma once

// Export padding (docs/architecture/08-export.md §3; task phase1.16_export-processing-encoders,
// decision 090): what a file holds outside the UV islands of its texture set.
//
// The coverage is the texture set's texel-centre UV coverage (evaluator/geometry_mask.h: a texel
// is covered when its centre lies inside or on a triangle of the set's material, its vertices
// snapped to 1/256 texel, decision 281). The evaluator
// fills the whole UV tile, so every texel of a raster holds the stack's value there.
//
// - Complete coverage (every texel covered, as on the grid meshes of the Tier 0 corpus): padding
//   changes nothing, for `infinite` and `passthrough` alike. The written files equal Painter's
//   byte for byte (parity/semantics/export-processing.json).
// - `passthrough` with incomplete coverage: no padding operation; every texel keeps its evaluated
//   value. Inside the islands Painter's r1 and r2 agree. Outside them Painter's own exports of
//   layer content differ between r1 and r2 at up to every uncovered texel (session state), so
//   they have no exact target (decision 032). A file reading a meshMap or virtualMap source is
//   refused: what Painter writes outside the islands of an imported mesh map is not recorded
//   (R-090 exports a virtual normal with `passthrough` only from layers and no mesh map, where
//   Painter's r1 and r2 differ on 37095 of 37214 uncovered texels; owner phase1.25_pilot-wand
//   item 2.7, decision 245). A combined virtual normal is refused before that (below).
// - `infinite` with incomplete coverage: refused with `core::NotYetSupported` naming R-090 and
//   decision 259, before anything is written. The rule below is not proven to be Painter's outside
//   the islands, and the owner withdrew exception EXC-007, which had excepted those texels
//   (decision 259: every texel identical). It is applied only when a caller asks to measure it
//   against Painter (`InexactPadding::measure`, the exact hunt of phase1.25_pilot-wand item 2.7),
//   over the coverage's triangles (`IslandTriangles`); the export never does. Covered texels keep
//   their evaluated values; the others are filled in two steps.
//   1. The ring, every uncovered texel with a covered 8-neighbour (x wraps, y does not), is an FMA
//      lerp chain over at most 4 taps (decisions 267, 268, 270, 273, 275, 278 to 282, 285, 288,
//      290 to 292, 294):
//      - the ring point q is the texel centre extrapolated through its own triangle tau, the
//        triangle of its covered 8-neighbours; when they lie in several, the triangle of the one
//        nearest under decision 273's comparator (below, through that neighbour's own triangle),
//        an exact tie toward +u, then +v (decision 279);
//      - the candidates are the covered 8-neighbours and the far windows of the UV seam edges of
//        every island that owns one of them, whose UV segment lies within 1.78 texels of the texel
//        centre (decision 294's corner edges: 1.0 or 1.15, below), whichever side of it q lies on
//        (decisions 275, 279, 285): q folded about the edge into
//        the far triangle, f its point in that triangle's texel space (v down, centres at + 1/2),
//        and the covered texels, of any island (decision 364), in the 3 x 3 block of columns
//        floor(f_u - 1/2) +- 1 and rows ceil(f_v - 1/2) +- 1. When J's island covers no texel
//        centre, the point is carried on across J's edges (folded about each, at most 4) to the
//        first triangle of a covered island, whose texel space gives f (decision 365). A seam edge
//        (E, J), E its triangle on
//        the near side and J
//        the far one, gives no far candidates when the float32 dot product of tau's and J's unit
//        face normals (cross(P1 - P0, P2 - P0) over the stored positions, divided by its length) is
//        at most 0.985 and q lies behind J's plane, n_J . (q - p) < 0 with p a vertex of the edge
//        (decision 278's gate, with tau's normal: decision 292). A seam edge whose far triangle is
//        tau (decision 288), or whose two UV ends both lie on u = 0 or both on u = 1 (decision
//        290), gives none. Triangles share an edge or a corner when their positions and UVs are
//        equal by value, -0 = +0 (decision 288). A corner edge (decision 294), a seam edge of a
//        triangle outside tau's planar face whose nearest point to the texel centre is an end V
//        (the centre's projection onto its UV segment outside it) and whose UV |sin| with every
//        other seam edge of its island ending at V exceeds 1e-3, reaches only within 1.0 texel
//        when another seam edge reaching the texel (within 1.787242 texels) ending at V is gated,
//        else within 1.15;
//      - a far candidate (in another island than tau) is turned rigidly from the plane of a far
//        triangle J into tau's plane, about the planes' intersection line (Rodrigues; parallel
//        planes, or normals meeting at a dot product above 0.985, leave it as it is): J is the far
//        triangle of the seam edge of tau's island, into the candidate's island, whose 3D segment
//        is nearest q, else the far triangle of the window that first holds it (decision 364);
//      - any other candidate in tau's planar face is used at its 3D position, one in a face
//        sharing a 3D edge with that face is rotated about the edge into its plane, onto the far
//        side, any other
//        one is rotated hinge by hinge along the fewest-hinge paths of faces sharing 3D edges (at
//        most 4 hinges, breadth first), the development nearest q (decision 281; not exact, and
//        flagged), else used at its 3D position; d is the distance from q. A hinge is rotated about
//        only when the float32 dot product of its two triangles' unit normals (tau's and the
//        candidate's across a shared edge, the path's two at each hinge of a development) is at
//        most 0.985, the seam gate's test; a shallower hinge leaves the candidate as it is
//        (decision 282). An own neighbour of tau's
//        island in another triangle K that shares a UV edge with tau is an own tap at |q_K - P|, q_K
//        the texel centre extrapolated through K and P its raw 3D position (decision 285; one in a
//        triangle sharing only a corner with tau stays in tau's frame). An own neighbour outside
//        tau's island that no window holds is an own tap at min(|q_k - P|, |q - P|), q_k the texel
//        centre extrapolated through the neighbour's own triangle; one a window holds is a far tap
//        (decision 279);
//      - not identified, and flagged by the measured ring (`RingTexel`): Painter's reach cap, in
//        [1.772004, 1.787242) texels; its corner caps, in [0.974615, 1.020004) and [1.0759265,
//        1.208074), and its collinear threshold, in [1e-6, 0.0305); the gate's constant, in
//        (0.98498905, 0.98501915], and whether it
//        compares with <= or <; a ring point on J's plane; a texel reached across two seam edges
//        with different gates; a chain tap developed along a face path; the tie classes below
//        that the data leave open; a far point f within 1e-4 texel of a window boundary (f - 1/2
//        integral on an axis) where the window on the other side changes the chain (decision 291:
//        Painter's side there is a float32 rounding that is not reproduced);
//      - the taps are the 4 nearest; a nearest at distance 0 relative to the nearest own
//        candidate is copied, and a list of 8 kept candidates without own ones is never a copy
//        (decision 280);
//      - the tap order is the 1/d share, largest first, distances within 1e-5 relative tied
//        (decision 282, which holds decision 288's float32-precision ties; decision 280 within
//        them), each tie by its taps' float32 distances, an own tap before a far one at an equal
//        one (decision 294 (b)): an own tap's is decision 273's comparator (each own tap's GPU-sqrt
//        distance, squared by FMA, to q, both interpolated through that tap's own triangle: float32
//        texel-centre UVs, barycentrics from the UV inverse matrix based at the third corner with
//        the GPU's reciprocal, and fma(l2, P2, fma(l0, P0, l1 P1)) over positions normalised by
//        the mesh box as P r - c r, c = lo + ext / 2, r = 1 / (max(ext) / 2)), equal ones ordered
//        by the offset (du, dv) from the ring texel, v up: (+1, 0), (-1, 0), (0, -1), (0, +1),
//        (+1, +1), (+1, -1), (-1, +1), (-1, -1); a far tap's is |fold(q_E) - P| (q_E the ring
//        texel through E, the own triangle of the first seam edge whose window holds the tap,
//        rotated in float32 about that edge into its far triangle's plane when the edge is folded
//        past 0.985; P the tap through its own triangle, not rotated; decision 282), equal ones
//        ordered by the offset from the window's base (floor(f_u - 1/2), ceil(f_v - 1/2)),
//        v up: (0, 0), (+1, 0), (0, +1), (+1, +1), (0, -1), (+1, -1), (-1, 0), (-1, +1),
//        (-1, -1). Then adjacent own taps whose distances lie within 1e-4 relative are ordered
//        by the comparator, then the offset (decision 294 (c)). Not identified, and flagged: an
//        own and a far tap at equal float32 distance; own taps
//        tied on the comparator at (+1, 0) / (-1, 0), (0, +1) / (0, -1) or (+1, -1) / (-1, +1);
//        far taps at equal distance in different planar faces; far taps tied in float32 from
//        different windows or at offsets the recorded ties do not order;
//      - level l of the n - 1 levels codes tap l's share s among taps l..n with (k, L) = (4, 1023),
//        (3, 255), (2, 63): u = round((s - 1/k) k / (k - 1) L) in [0, L], t = float32(1/k +
//        (k - 1)/k u / L); the value is m = fma(1 - t, v_n - v_n-1, v_n-1) for the last level, then
//        m = fma(t, v_l - m, m) outward, rounded through 1 - (1 - m) (decision 206).
//      Painter's ring is not this at pole tap sets, on multi-facet bevels, on anisotropic
//      islands, at far points on an exact texel centre, at V-gap boundaries, across concave
//      hinges, on curved shared islands and at the Wand's convex seam texels whose Height no chain
//      over these taps gives (decisions 267, 270, 273, 275, 277, 279, 280, 281).
//   2. Every other texel copies its seed found by a jump flood over the covered and ring texels
//      (decision 197): steps k = max(width, height)/2 down to 1, eight offsets in a fixed order,
//      each read outside the image clamped to its nearest edge texel (decision 285), the strictly
//      nearest seed kept.
//   Each channel is padded in its document format (decision 274, which corrects decision 223's
//   padding of the PNG 16 codes). A channel that reads a documentMap is padded on the operands of
//   its stack channel's format (`FileRaster::documentFormat`): an sRGB8 channel's linear operands,
//   an 8- or 16-bit UNORM channel's operands, a float channel's floats. Each filled texel is stored
//   as that format stores it (evaluator/cpu_store.h `StoreValue`: the GPU's float-to-sRGB8
//   conversion, the UNORM write, the half toward zero) and written as the file writes the
//   channel's other texels (encode.h). Any other channel (a mesh map, a virtual map, a luma, a
//   constant) is padded on the values the file stores, as decision 223 did: OpenEXR floats, and
//   PNG codes as UNORM operands written back with the UNORM write rule. No recording shows
//   Painter's domain for those.
//   The refusal is lifted only when the rule is exact (phase1.25_pilot-wand item 2.7).
// - A combined virtual normal (`Normal_OpenGL`, `Normal_DirectX`, or a diagnosticMap that
//   isolates, compares or summarises one) with incomplete coverage, under every padding and in
//   statistics files (decision 245): its island-edge texels, the covered texels with an
//   uncovered 8-neighbour, read the Height outside the islands through the height-to-normal
//   stencil. Painter's covered texels there are the same under every padding (all 46 PNG 16
//   steps of tier0 export-padding) and stable across recordings, but they are not the stencil of
//   the evaluated Height: 445 of 1452 edge texels differ on export-padding, 592 to 2296 on the
//   height-normal sphere and bevelled cube, 1071 on the Wand v1, while every interior texel is
//   exact. Such a file is refused (`CheckIslandNormal`), a Height without layers included: no
//   recording shows what Painter's empty Height reads outside the islands, and its other virtual
//   maps read an empty channel as a constant that is not the channel's base (R-092).
//   Outside the islands Painter's combined normal is neither the padding above of its stored
//   values nor the stencil of the padded Height (decision 276): each gutter texel is the bound
//   Normal mesh map at that texel combined with the mesh-free normal of its flood seed in the
//   ring. Measuring a Normal file with this padding is therefore wrong wherever a mesh map is
//   bound, whatever the ring. The diagnostic measure export pads it by that rule instead
//   (`PadIslandNormal`, below; virtual_maps.h, decision 308).

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "export/plan.h"

namespace uzp::mesh {
struct TexturingMesh;
}

namespace uzp::exporter {

/// A triangle of a texture set's material, as the mesh stores it: its corners' first UV set (v
/// up) and 3D positions.
struct IslandTriangle {
    std::array<std::array<float, 2>, 3> uv{};
    std::array<std::array<float, 3>, 3> position{};
};

/// A texture set's texel-centre UV coverage, rows top first: non-zero where a triangle covers the
/// texel's centre.
struct Coverage {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> covered;
    /// The measured `infinite` padding's geometry (`IslandTriangles`): the set's triangles in mesh
    /// order and the bounding box of the whole mesh's positions. Empty when not known; the
    /// measured padding then refuses to run (std::invalid_argument).
    std::vector<IslandTriangle> triangles{};
    std::array<float, 3> boxMin{};
    std::array<float, 3> boxMax{};

    [[nodiscard]] bool Complete() const;
};

/// The triangles of `material` in `mesh` (every object, in mesh order, each corner's position moved
/// by its object's transform) and the box of every triangle corner of the mesh (decision 273's
/// box), into `coverage`.
void IslandTriangles(Coverage& coverage, const mesh::TexturingMesh& mesh, const std::string& material);

/// One candidate tap of a ring texel of the measured `infinite` padding: its texel, its distance d
/// from the ring point (above), and whether it lies across a UV seam.
struct RingTap {
    uint32_t x = 0;
    uint32_t y = 0;
    double distance = 0.0;
    bool across_seam = false;
};

/// A ring texel of the measured `infinite` padding (above): its candidates in tap order, of which
/// the first `taps` are the chain's (1 for a copy), the chain's fractions t per level, and the
/// number of distinct triangles among its covered 8-neighbours. `alternatives` holds, for each of
/// those triangles other than tau (in decreasing index), the candidates in tap order with q
/// extrapolated through it instead: what a measurement of the V-gap position compares.
/// The flags mark where the rule above does not decide the chain: a seam edge whose window
/// gives the chain a tap, with decision 278's gate or without it, has its faces' normal dot product
/// inside the open bracket (0.98498905, 0.98501915] with q behind the far plane (`foldBracket`), or
/// q exactly on the far plane with a dot product of at most 0.98501915 (`onFarPlane`); two such
/// edges are gated differently (`mixedGates`); a reach cap anywhere in [1.772004, 1.787242) texels
/// instead of 1.78 changes the taps (`reachBracket`, decision 285); a corner cap anywhere in
/// [0.974615, 1.020004) instead of 1.0 or in [1.0759265, 1.208074) instead of 1.15, or a collinear
/// threshold anywhere in [1e-6, 0.0305) instead of 1e-3, changes them (`cornerReachBracket`,
/// decision 294); some seam edge's far point lies
/// within 1e-4 texel of a window boundary and the window on its other side changes the taps
/// (`windowSide`, decision 291). A group of equal distances holding a chain tap holds an own
/// and a far tap at equal float32 distances (`ownFarTie`), an open own pair tied on the comparator
/// (`ownOrder`, also between adjacent own taps within 1e-4), far taps in different planar faces
/// (`farFold`) or an open far pair (`farOrder`, decision 280). A chain tap's distance is developed
/// along a face path (`multiFacet`, decision 281). The chain is still that of the rule above
/// (constant 0.985, gated per edge, caps 1.78, 1.0 and 1.15, threshold 1e-3, the fixed orders, the
/// nearer development).
struct RingTexel {
    uint32_t x = 0;
    uint32_t y = 0;
    std::vector<RingTap> candidates;
    uint32_t taps = 0;
    std::vector<float> fractions;
    uint32_t triangles = 0;
    std::vector<std::vector<RingTap>> alternatives;
    bool foldBracket = false;
    bool onFarPlane = false;
    bool mixedGates = false;
    bool reachBracket = false;
    bool cornerReachBracket = false;
    bool windowSide = false;
    bool ownFarTie = false;
    bool ownOrder = false;
    bool farFold = false;
    bool farOrder = false;
    bool multiFacet = false;
};

/// The ring of the measured `infinite` padding over `coverage` (which needs its triangles), rows
/// top first. Throws std::invalid_argument when the coverage has no triangles or is not theirs.
[[nodiscard]] std::vector<RingTexel> MeasuredRing(const Coverage& coverage);

/// Whether an `infinite` padding on incomplete coverage, which is not exact (above), is refused, as
/// the export always does, or written to be measured against Painter (decision 259).
enum class InexactPadding : uint8_t { refuse, measure };

/// Throws `core::NotYetSupported` (see above) when `file`'s padding over `coverage` is not fitted,
/// and std::invalid_argument when the coverage does not have the file's size. A statistics file
/// has no padding and always passes.
void CheckPadding(const PlannedFile& file, const Coverage& coverage,
                  InexactPadding inexact = InexactPadding::refuse);

/// Whether `source` reads a combined virtual normal: the virtualMap Normal_OpenGL or
/// Normal_DirectX, or a diagnosticMap that isolates, compares or summarises one.
[[nodiscard]] bool ReadsCombinedNormal(const PlannedSource& source);
/// Whether a channel of `file` reads one.
[[nodiscard]] bool ReadsCombinedNormal(const PlannedFile& file);

/// Why `source`, which reads a combined virtual normal, is refused on a texture set whose UV
/// islands do not cover the tile (see above), with its owner.
[[nodiscard]] std::string IslandNormalRefusal(const PlannedSource& source);

/// Throws `core::NotYetSupported` (IslandNormalRefusal) when `file` reads a combined virtual
/// normal over `coverage` with uncovered texels, whatever the padding, a statistics file included.
void CheckIslandNormal(const PlannedFile& file, const Coverage& coverage);

/// Applies `file`'s padding over `coverage` to `stored`, the values the file stores (above),
/// `channels` per texel, rows top first, after CheckPadding (which it repeats with `inexact`):
/// `infinite` on incomplete coverage, measured only, fills the uncovered texels; every other
/// admitted case keeps the values. Returns whether any texel was filled.
bool ApplyPadding(const PlannedFile& file, const Coverage& coverage, uint32_t channels, std::vector<float>& stored,
                  InexactPadding inexact = InexactPadding::refuse);

// The diagnostic measure export's combined virtual normal on UV islands (write.h, decision 308),
// never production: Painter's rule as recorded, not proven exact.

/// The Height the virtual normal's stencil reads (decisions 263, 288 (a)): `operands`, one per
/// texel of `coverage` (which needs its triangles), with every uncovered texel filled by the
/// measured ring above without its 1 - (1 - m) step, then the flood. Throws as ApplyPadding does.
void PadIslandHeight(const Coverage& coverage, std::vector<float>& operands);

/// Whether `coverage` has a ring texel whose covered 8-neighbours all lie across the x border:
/// one that keeps its unpadded mesh-free normal (decision 287 §4).
[[nodiscard]] bool NormalRingAcrossBorder(const Coverage& coverage);

/// The padding of the mesh-free normal (decision 287): `normals`, three per texel, holds the
/// evaluated normal on the covered texels and the unpadded one elsewhere. Each ring texel (an
/// uncovered texel with a covered 8-neighbour, x wrapping) copies its nearest covered 8-neighbour
/// without wrap-around (texel distance, ties in decision 197's offset order (dy, dx): (0, 1),
/// (0, -1), (-1, 0), (1, 0), (-1, 1), (1, -1), (-1, -1), (1, 1)), or keeps its value when its
/// covered neighbours all lie across the x border; every other uncovered texel copies its seed in
/// decision 197's flood over the covered and ring texels, reads clamped (decision 285).
void PadIslandNormal(const Coverage& coverage, std::vector<float>& normals);

}  // namespace uzp::exporter
