#pragma once

// Processing and encoding of the planned files (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decisions 089 and 090).
//
// Painter's export behaviour is reproduced where the Tier 0 recordings decide it and this task has
// fitted it; everything else is refused before anything is written (decision 090). In the domain
// written today:
//
// - Formats: PNG at 16 bits and OpenEXR at 32-bit float, grey (L) or RGB, without dithering, at the
//   texture set's own size, with `infinite` or `passthrough` padding (padding.h).
// - Values: the file's channels as EvaluateFileOn reads them out, every stored sample as its
//   operand (evaluator/diagnostics.h `MapOf`). Legacy colour management is the only mode the plan
//   admits. An sRGB8 User channel is exported linear, as its decoded operand (measured on every
//   sRGB8 User-channel PNG of the current envelope).
// - PNG 16: each value is written with the UNORM write rule (arith::WriteUnorm, 16 bits): clamped
//   to [0, 1], truncated to 20 fractional bits, the nearest code with ties down. Encoded by
//   png_writer.h.
// - OpenEXR 32f: each value unchanged (float32, no clamp; a signed channel keeps its sign).
//   Encoded by exr_writer.h.
//
// Refused with `core::NotYetSupported` (decision 090):
// - naming recording R-090, because no recording shows what Painter does: PNG at 8 bits, OpenEXR
//   at 16f, the L+A layout, an sRGB8 channel in OpenEXR, dithering, a size other than the texture
//   set's (resize), and the `color`, `transparent` and `diffusion` paddings;
// - as recorded but not fitted here: an sRGB8 channel other than a User channel (BaseColor and the
//   other material colours are exported sRGB-encoded, and the evaluator's template constants of
//   such channels are already export values), and the RGB+A layout (recording R-085 P6/P7: an
//   alpha of 1 everywhere is dropped), whose alpha sources the plan does not resolve yet.

#include <string>

#include "export/plan.h"
#include "uzp_core/types/project.h"

namespace uzp::exporter {

/// The recording that decides the export processing no Tier 0 recording covers yet.
inline constexpr std::string_view kProcessingRecording = "export-processing recording R-090 (decision 090)";

/// Throws `core::NotYetSupported` when `file` (planned on `project`) asks for processing outside
/// the domain above. A statistics file has no processing and always passes.
void CheckProcessing(const core::Project& project, const PlannedFile& file);

/// The bytes of `file` from its padded raster (CheckProcessing must have passed): the PNG or
/// OpenEXR file, or the statistics JSON of a statistics file. Throws std::invalid_argument when
/// the raster does not match the file's size and layout.
[[nodiscard]] std::string EncodeFile(const PlannedFile& file, const FileRaster& raster);

}  // namespace uzp::exporter
