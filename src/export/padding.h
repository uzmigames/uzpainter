#pragma once

// Export padding (docs/architecture/08-export.md §3; task phase1.16_export-processing-encoders,
// decision 090): what a file holds outside the UV islands of its texture set.
//
// The coverage is the texture set's texel-centre UV coverage (evaluator/geometry_mask.h: a texel
// is covered when its centre lies inside or on a triangle of the set's material). Inside it the
// file holds the evaluated values; the evaluator fills the whole UV tile, so a texel outside it
// holds the stack's value there until padding replaces it.
//
// - Complete coverage (every texel covered, as on the grid meshes of the Tier 0 corpus): the
//   padding changes nothing, for `infinite` and `passthrough` alike; this is what the recordings
//   show (the exported files equal the evaluated values on every texel).
// - Incomplete coverage: Painter's `infinite` padding is not the nearest covered texel (on the
//   bevelled cube of tier0/semantics/height-normal-bevelled-cube it differs at 12040 of the 12200
//   uncovered texels); it follows the mesh across UV seams. Until that operator is fitted, and
//   `passthrough` characterised, both are refused with `core::NotYetSupported` naming recording
//   R-090 (decision 090).

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
/// CheckPadding (which it repeats).
void ApplyPadding(const PlannedFile& file, FileRaster& raster, const Coverage& coverage);

}  // namespace uzp::exporter
