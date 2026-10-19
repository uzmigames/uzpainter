#pragma once

// Export padding (docs/architecture/08-export.md §3; task phase1.16_export-processing-encoders,
// decision 090): what a file holds outside the UV islands of its texture set.
//
// The coverage is the texture set's texel-centre UV coverage (evaluator/geometry_mask.h: a texel
// is covered when its centre lies inside or on a triangle of the set's material). The evaluator
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
//      lerp chain over at most 4 taps (decisions 267, 268, 270):
//      - the ring point q is the texel centre extrapolated through its own triangle tau, the
//        triangle of its covered 8-neighbours (the highest-index one when they lie in several:
//        decision 270's V-gap majority);
//      - the candidates are the covered 8-neighbours and, across each UV seam edge of tau that q
//        lies beyond, the covered texels of the far island around q unfolded into it; a candidate
//        in tau's planar face is used at its 3D position, one in a face sharing a 3D edge with that
//        face is rotated about the edge into its plane, onto the far side, any other one is used at
//        its 3D position; d is the distance from q;
//      - the taps are the 4 nearest; a nearest at distance 0 is copied;
//      - the tap order is the exact 1/d share, largest first; equal shares are ordered by decision
//        267's comparator (each own tap's GPU-sqrt distance in mesh-box-normalised float32 object
//        space to q extrapolated through that tap's own triangle), then toward +u, +v (far taps
//        after own ones): the best known order, not exact on non-dyadic UVs (decision 271);
//      - level l of the n - 1 levels codes tap l's share s among taps l..n with (k, L) = (4, 1023),
//        (3, 255), (2, 63): u = round((s - 1/k) k / (k - 1) L) in [0, L], t = float32(1/k +
//        (k - 1)/k u / L); the value is m = fma(1 - t, v_n - v_n-1, v_n-1) for the last level, then
//        m = fma(t, v_l - m, m) outward, rounded through 1 - (1 - m) (decision 206).
//      Painter's ring is not this at V-gap positions, at pole tap sets, on multi-facet bevels, on
//      anisotropic islands and in the order of equal shares (decisions 267, 270, 271).
//   2. Every other texel copies its seed found by a jump flood over the covered and ring texels
//      (decision 197): steps k = max(width, height)/2 down to 1, eight offsets in a fixed order,
//      the strictly nearest seed kept.
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
//   bound, whatever the ring.

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
/// by its object's transform) and the box of every triangle corner of the mesh, into `coverage`.
void IslandTriangles(Coverage& coverage, const mesh::TexturingMesh& mesh, const std::string& material);

/// One candidate tap of a ring texel of the measured `infinite` padding: its texel, its distance d
/// from the ring point (above), and whether it lies across a UV seam.
struct RingTap {
    uint32_t x = 0;
    uint32_t y = 0;
    double distance = 0.0;
    bool far = false;
};

/// A ring texel of the measured `infinite` padding (above): its candidates in tap order, of which
/// the first `taps` are the chain's (1 for a copy), the chain's fractions t per level, and the
/// number of distinct triangles among its covered 8-neighbours. `alternatives` holds, for each of
/// those triangles other than tau (in decreasing index), the candidates in tap order with q
/// extrapolated through it instead: what a measurement of the V-gap position compares.
struct RingTexel {
    uint32_t x = 0;
    uint32_t y = 0;
    std::vector<RingTap> candidates;
    uint32_t taps = 0;
    std::vector<float> fractions;
    uint32_t triangles = 0;
    std::vector<std::vector<RingTap>> alternatives;
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

}  // namespace uzp::exporter
