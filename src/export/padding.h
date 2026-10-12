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
//   (R-090).
// - `infinite` with incomplete coverage: refused with `core::NotYetSupported` naming R-090. The
//   fit of tier0 height-normal-bevelled-cube and -sphere found an 8-neighbour copy dilation
//   (each uncovered texel copies its first covered neighbour: right, left, up, down, then the
//   diagonals; x wraps, y does not). It is exact on the bevelled cube's virtual normals, but not
//   on the spheres' poles. For a document channel it also needs a one-texel ring around each
//   island whose values blend across the UV seam with weights not identified yet.

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

/// Applies `file`'s padding to `raster` (the file's evaluated values) over `coverage`, after
/// CheckPadding (which it repeats). Every admitted case keeps the evaluated values (see above).
void ApplyPadding(const PlannedFile& file, FileRaster& raster, const Coverage& coverage);

}  // namespace uzp::exporter
