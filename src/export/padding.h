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
//   refused: what Painter writes outside the islands of an imported mesh map, or of a virtual
//   map that reads one or a Height without layers, is not recorded (R-090 exports a virtual
//   normal with `passthrough` only from layers and no mesh map, where Painter's r1 and r2 differ
//   on 37095 of 37214 uncovered texels; owner phase1.25_pilot-wand item 2.7, decision 245).
// - `infinite` with incomplete coverage (decision 223, under exception EXC-007): covered texels
//   keep their evaluated values; the others are filled in two steps.
//   1. The ring, every uncovered texel with a covered 8-neighbour (x wraps, y does not), takes the
//      mean of those neighbours: weight 1 for a side neighbour and f/(1 - f) for a diagonal,
//      f = 0.4142245 (decisions 176, 206). On a straight edge (three covered neighbours in one
//      row or column) one diagonal is weakened so that the mean moves 24.875 * 2^-15 texel: +x
//      on horizontal edges, -row on vertical edges. The mean is rounded to float32 and through
//      1 - (1 - v); a mean of equal values is that value.
//   2. Every other texel copies its seed found by a jump flood over the covered and ring texels
//      (decision 197): steps k = max(width, height)/2 down to 1, eight offsets in a fixed order,
//      the strictly nearest seed kept.
//   The padding acts on the values the file stores, after the encode: OpenEXR floats, and PNG
//   codes as UNORM operands (a padded code is written back with the UNORM write rule). A PNG 16
//   sRGB channel under OCIO stores Painter's recorded codes (encode.h `OcioSrgbPng16Code`), which
//   a mean of linear values would leave; decision 223 measured the Wand on its PNG 16 codes.
//   This is Painter's rule on straight edges away from seams only. Painter's ring across UV seams,
//   at seam corners and at poles is not identified (decision 220), so outside the islands the
//   values differ from Painter's; EXC-007 excepts exactly those texels, and the exact rule stays
//   open (phase1.25_pilot-wand item 2.7).
// - A combined virtual normal (`Normal_OpenGL`, `Normal_DirectX`) with incomplete coverage, under
//   every padding (decision 245): its island-edge texels, the covered texels with an uncovered
//   8-neighbour, read the Height outside the islands through the height-to-normal stencil.
//   Painter's covered texels there are the same under every padding (all 46 PNG 16 steps of
//   tier0 export-padding) and stable across recordings, but they are not the stencil of the
//   evaluated Height: 445 of 1452 edge texels differ on export-padding, 592 to 2296 on the
//   height-normal sphere and bevelled cube, 1071 on the Wand v1, while every interior texel is
//   exact. Such a file is refused (`CheckIslandNormal`) unless no layer writes the Height
//   (evaluator `FlatZeroHeight`): the stencil then reads 0 everywhere, and Painter's Height
//   outside the islands, made from the covered texels or the empty channel's base, is 0 too.
//   That case is deduced from the fits, not recorded.

#include <cstdint>
#include <vector>

#include "export/plan.h"

namespace uzp::exporter {

/// A texture set's texel-centre UV coverage, rows top first: non-zero where a triangle covers the
/// texel's centre.
struct Coverage {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> covered;

    [[nodiscard]] bool Complete() const;
};

/// Throws `core::NotYetSupported` (see above) when `file`'s padding over `coverage` is not fitted,
/// and std::invalid_argument when the coverage does not have the file's size. A statistics file
/// has no padding and always passes.
void CheckPadding(const PlannedFile& file, const Coverage& coverage);

/// Whether a channel of `file` reads a combined virtual normal (Normal_OpenGL, Normal_DirectX).
[[nodiscard]] bool ReadsCombinedNormal(const PlannedFile& file);

/// Throws `core::NotYetSupported` (see above) when `file` reads a combined virtual normal over
/// `coverage` with uncovered texels and the Height of its stack is not 0 everywhere
/// (`flatZeroHeight`, evaluator `FlatZeroHeight`), whatever the padding.
void CheckIslandNormal(const PlannedFile& file, const Coverage& coverage, bool flatZeroHeight);

/// Applies `file`'s padding over `coverage` to `stored`, the values the file stores (above),
/// `channels` per texel, rows top first, after CheckPadding (which it repeats): `infinite` on
/// incomplete coverage fills the uncovered texels; every other admitted case keeps the values.
/// Returns whether any texel was filled.
bool ApplyPadding(const PlannedFile& file, const Coverage& coverage, uint32_t channels, std::vector<float>& stored);

}  // namespace uzp::exporter
