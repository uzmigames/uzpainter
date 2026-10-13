#pragma once

// Processing and encoding of the planned files (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decisions 089 and 090).
//
// Painter's export behaviour is reproduced where the Tier 0 recordings decide it and it is fitted
// exactly; everything else is refused before anything is written (decisions 090 and 103). In the
// domain written today:
//
// - Formats: PNG at 8 or 16 bits and OpenEXR at 16f or 32f; layouts L, L+A, RGB and RGB+A; at the
//   texture set's own size, with `infinite` or `passthrough` padding (padding.h).
// - Values: the file's channels as EvaluateFileOn reads them out, every stored sample as its
//   operand (evaluator/diagnostics.h `MapOf`). The plan admits Legacy colour management and OCIO
//   with Painter's substance config (decision 190), which writes the same files but for the PNG 16
//   of an sRGB-encoded channel (`OcioSrgbPng16Code`) and `$colorSpace` (plan.cpp). An sRGB8 User
//   channel is exported linear, as its decoded operand, in every format.
// - PNG 8 and 16: each value is written with the UNORM write rule at the file's depth
//   (arith::WriteUnorm): clamped to [0, 1], truncated to depth + 4 fractional bits, the nearest
//   code with ties down. A Height channel is written as v * 0.5 + 0.5. An sRGB8 BaseColor,
//   Specular or Emissive (`FileRaster::srgbEncoded`) is written as the sRGB encode of its linear
//   value: x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), -0.055), with the
//   recording GPU's log2 and exp2 (evaluator/hwmath.h; decisions 091 and 126). Its OpenEXR files
//   hold the linear value. Encoded by png_writer.h.
// - OpenEXR 32f: each value unchanged (float32, no clamp; a signed channel keeps its sign).
//   OpenEXR 16f: each value rounded toward zero to a half. Encoded by exr_writer.h.
// - Alpha: an L+A or RGB+A file whose alpha is 1 everywhere is written without it (L or RGB).
// - Dithering: no change at PNG 16.
//
// Measured on recording R-090 (export-bit-depth, export-dither, export-alpha-layouts), every rule
// exact against Painter's own files (decisions 103 and 126).
//
// Refused with `core::NotYetSupported`, recorded but not fitted (decision 103): dithering at PNG
// 8 bits (deterministic, not a threshold matrix), dithering in OpenEXR (not compared with off), a size
// other than the texture set's (resize), and the `color`, `transparent` and `diffusion` paddings.
// An sRGB8 channel other than a User channel, BaseColor, Specular and Emissive (EmissionColor,
// Diffuse, CoatColor, ...) is refused as not recorded: no recording shows whether Painter writes it
// linear or sRGB-encoded. A PNG of an L8 BaseColor, Specular or Emissive is refused as recorded but
// not fitted: Dota 2's empty L8 Specular, float32(10/255) in OpenEXR, writes (14330, 2570, 14330)
// at PNG 16 (decision 169). Its OpenEXR files hold the linear value.

#include <cstdint>
#include <optional>
#include <string>

#include "export/plan.h"
#include "uzp_core/types/project.h"

namespace uzp::exporter {

/// The 16-bit PNG code Painter 12.1.5 writes under OCIO with its substance config (decision 190)
/// for the linear value `v` of an sRGB-encoded channel (`FileRaster::srgbEncoded`), or nothing when
/// `v` is not recorded. Recorded (`export-ocio-encode` s3, the authored ramp holding each of the
/// 256 codes on BaseColor, and s7, the empty BaseColor; r1 and r2): the operand of each sRGB8 code
/// (arith::Srgb8Operand) and float32(0.8). It is a measured table: no closed form reproduces it.
/// The IEC encode rounded misses 14 of the 257 values (the legacy encode 74), and the codes of the
/// ten operands 5k 2^-14 (k = 1..10, all on the linear segment) step by 259 twice in a row, which
/// no rounding of a linear function of k does. Its PNG 8 and OpenEXR files are the legacy ones.
[[nodiscard]] std::optional<uint16_t> OcioSrgbPng16Code(float v);

/// The recording that decides the export processing no Tier 0 recording covers yet.
inline constexpr std::string_view kProcessingRecording = "export-processing recording R-090 (decision 090)";

/// Throws `core::NotYetSupported` when `file` (planned on `project`) asks for processing outside
/// the domain above. A statistics file has no processing and always passes.
void CheckProcessing(const core::Project& project, const PlannedFile& file);

/// A planned file's bytes and the layout they hold (the plan's, or L / RGB when an all-opaque
/// alpha was dropped).
struct EncodedImage {
    std::string bytes;
    FileLayout layout = FileLayout::L;
};

/// The bytes of `file` from its padded raster (CheckProcessing must have passed): the PNG or
/// OpenEXR file, or the statistics JSON of a statistics file. Throws std::invalid_argument when
/// the raster does not match the file's size and layout.
[[nodiscard]] EncodedImage EncodeFile(const PlannedFile& file, const FileRaster& raster);

}  // namespace uzp::exporter
