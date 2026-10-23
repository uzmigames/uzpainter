#pragma once

// The export resize: a planned file whose size (`sizeLog2`) is not its texture set's (task
// phase3.2_unreal-ue56-packed-preset item 2.9; decisions 103 and 349), fitted on recording R-090
// P4 (`export-resize`: 256 x 256 and 256 x 128 sets, Nearest and BilinearHQ fills, an impulse
// texel; sizeLog2 6, 7, 9 and 10 and the [w, h] probes; r1 and r2 identical).
//
// - Upscale (each side the set's times a power of two, one side larger): Painter's file is the
//   texture set evaluated at the file's size, every texel of every recorded map (BaseColor sRGB8,
//   User0 RGB16, Height L16F, Normal_OpenGL and Normal_DirectX) where the evaluator evaluates that
//   size. `AtFileSize` is that project.
// - Downscale (each side the set's or half of it, one side halved): each texel is the mean of the
//   2 or 4 texels of the set's evaluation it covers, in a single step, stored in the channel's
//   format (`Downscale`): RGB16 the nearest 16-bit code (a 2-texel tie rounds up), L16F the
//   nearest half (ties away from zero). A 4-texel RGB16 mean halfway between two codes is not
//   recorded and is refused. Not reproduced: sRGB8 channels and virtual normals.
//
// The recorded domain the guard (guards.cpp `ProcessingRefusal`) admits is narrower than this:
// see there. A side below 128 is not written at its planned size by Painter (sizeLog2 6 on a 256
// set is written at 128, sizeLog2 7 on 256 x 128 at 256 x 128), so it is refused.

#include <cstdint>
#include <optional>
#include <string>

#include "export/padding.h"
#include "export/plan.h"
#include "uzp_core/types/project.h"

namespace uzp::exporter {

/// How a file is resized from its texture set's size.
enum class Resize : uint8_t {
    none,       ///< The set's size.
    downscale,  ///< Each side the set's or half of it, one side halved.
    upscale,    ///< Each side the set's times a power of two, one side larger.
    other,      ///< Any other pair of sizes (a mixed or a non-power-of-two resize): not recorded.
};

/// The resize of `file` from a `setWidth` x `setHeight` texture set.
[[nodiscard]] Resize ResizeOf(uint32_t setWidth, uint32_t setHeight, const PlannedFile& file);

/// `project` with the texture set of `file` at `file`'s size: an upscaled file is evaluated on it.
[[nodiscard]] core::Project AtFileSize(const core::Project& project, const PlannedFile& file);

/// The UV coverage of `set` at `width` x `height` (write.h `CoverageOf` at another size), or
/// nothing when `inputs` has no geometry or it gives no coverage.
[[nodiscard]] std::optional<Coverage> CoverageAt(const core::TextureSet& set, const SourceInputs& inputs,
                                                 uint32_t width, uint32_t height);

/// The refusal of a resized `file` whose texture set has uncovered texels at the set's size
/// (`native`) or at the file's (`target`): Painter's padding around a resize is recorded on sets
/// whose UV islands cover the whole tile only.
[[nodiscard]] std::optional<std::string> ResizeCoverageRefusal(const PlannedFile& file, const Coverage& native,
                                                               const Coverage& target);

/// The downscale (above) of `native`, the evaluation of a `Resize::downscale` file at its texture
/// set's size, to `file`'s size. Every channel must hold an RGB16 or L16F documentMap component
/// (`FileRaster::documentFormat`). Fails (`evaluator:unsupported_source`) on a 4-texel RGB16 tie;
/// throws std::invalid_argument when the raster is not the downscale's source.
[[nodiscard]] render::Result<FileRaster> Downscale(const PlannedFile& file, const FileRaster& native);

}  // namespace uzp::exporter
