#pragma once

// Processing and encoding of the planned files (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decisions 089 and 090).
//
// Painter's export behaviour is reproduced where the Tier 0 recordings decide it, and refused
// before anything is written everywhere else (decision 090). The recordings of the current
// envelope export PNG at 16 bits and OpenEXR at 32-bit float, grey or RGB, without dithering, at
// the texture set's own size, with `infinite` or `passthrough` padding. In that domain:
//
// - Values: the file's channels as EvaluateFileOn reads them out, every stored sample as its
//   operand (an sRGB8 sample as its decoded value, evaluator/diagnostics.h `MapOf`). Legacy colour
//   management is the only mode the plan admits, and its exports apply no further transform; a
//   signed channel (Height) keeps its sign in OpenEXR.
// - PNG 16: each value is written with the UNORM write rule (arith::WriteUnorm, 16 bits): clamped
//   to [0, 1], truncated to 20 fractional bits, the nearest code with ties down. Encoded by
//   png_writer.h.
// - OpenEXR 32f: each value unchanged (float32). Encoded by exr_writer.h.
//
// Refused with `core::NotYetSupported` naming recording R-090 (decision 090), because no recording
// shows what Painter does: PNG at 8 bits, OpenEXR at 16f, the L+A and RGB+A layouts, dithering,
// a size other than the texture set's (resize), and the `color`, `transparent` and `diffusion`
// paddings with their dilationDistance.

#include <string>

#include "export/plan.h"

namespace uzp::exporter {

/// The recording that decides the export processing no Tier 0 recording covers yet.
inline constexpr std::string_view kProcessingRecording = "export-processing recording R-090 (decision 090)";

/// Throws `core::NotYetSupported` (kProcessingRecording) when `file` asks for processing outside
/// the recorded domain above. A statistics file has no processing and always passes. `setWidth`
/// and `setHeight` are the texture set's resolution.
void CheckProcessing(const PlannedFile& file, uint32_t setWidth, uint32_t setHeight);

/// The bytes of `file` from its padded raster (CheckProcessing must have passed): the PNG or
/// OpenEXR file, or the statistics JSON of a statistics file. Throws std::invalid_argument when
/// the raster does not match the file's size and layout.
[[nodiscard]] std::string EncodeFile(const PlannedFile& file, const FileRaster& raster);

}  // namespace uzp::exporter
