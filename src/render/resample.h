#pragma once

// Resampling of one image into another of any size (docs/architecture/13-engine-integration.md
// §4.1; 04-layer-stack-and-compositing.md §7; 08-export.md §3), the filter kernel a parameter:
// the compositor and the exporter choose it (the Painter-fitted filters of
// parity/semantics/resampling.json are among them). Kernel: src/render/shaders/resample.hlsl.
//
// Output texel (i, j) of a W' x H' image samples the W x H source at x = (i + 0.5) W / W' - 0.5,
// y = (j + 0.5) H / H' - 0.5 (texel centres at integers, row 0 on top). Filters:
//
// - Nearest: the texel (floor((i + 0.5) W / W'), floor((j + 0.5) H / H')), copied unchanged
//   (Painter's `Nearest`, resampling.json `resample-nearest`).
// - Bilinear: Painter's fixed-point bilinear (resampling.json `resample-bilinearhq-*`):
//   X = floor(256 x + 0.5), x0 = X >> 8, fx = X & 255 (same for y), integer weights
//   w11 = (fx fy + 127) >> 8, w10 = fx - w11, w01 = fy - w11, w00 = 256 - fx - fy + w11 over the
//   taps (x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1); unorm channels write
//   S / (256 M) (S the weighted code sum) with the write rule of image_pass.h, which for 16-bit
//   codes is the fitted formula. Taps outside the image are clamped or wrapped (`ResampleWrap`).
// - Box: exact area weights. With g = gcd(W, W'), a source texel spans `W' / g` units and an
//   output texel `W / g`; each tap weighs the length of the overlap (per axis, the 2D weight is
//   the product). Unorm channels write S / (T M), T the weight total.
//
// Float channels (float formats, and the decoded channels of `ColourMode::Srgb` and `Normal`)
// accumulate weight x value in float32, tap by tap (rows top to bottom, texels left to right;
// bilinear in the order above), and are scaled by 1/256 (bilinear) or by float32(1 / T) (box).
// An identical source and destination size is an exact copy for every filter.

#include "render/backend.h"
#include "render/engine_thread.h"
#include "render/image_pass.h"

#include <array>
#include <cstdint>

namespace uzp::render {

enum class ResampleFilter : uint8_t { Nearest, Bilinear, Box };

/// How bilinear taps outside the image are resolved (Box and Nearest taps are always inside).
enum class ResampleWrap : uint8_t { Clamp, Repeat };

struct ResampleOptions {
    ResampleFilter filter = ResampleFilter::Box;
    ResampleWrap wrap = ResampleWrap::Clamp;
    ColourMode colour = ColourMode::Linear;
};

/// Resamples mip 0 of `source` into mip 0 of `destination` (same format, any size). The source
/// needs `ShaderResource` usage, the destination `UnorderedAccess`; for equal sizes, a copy, the
/// source needs `CopySrc` and the destination `CopyDst` instead. `ColourMode::Srgb` needs an
/// 8-bit unorm format, `ColourMode::Normal` a four-channel one.
Result<void> Resample(EngineContext& context, uz::RHITextureHandle source,
                      uz::RHITextureHandle destination, const ResampleOptions& options);

namespace resample_detail {

/// One recorded dispatch of the resample kernel (mip generation chains them).
struct ResampleDispatch {
    ComputeKernel kernel;
    std::array<uint32_t, 12> constants{};
    uint32_t groupsX = 0;
    uint32_t groupsY = 0;
};

/// `request_failed` when `colour` does not apply to `format`.
Result<void> CheckColourMode(const IDevice& device, ImagePassFormat format, ColourMode colour);

/// The dispatch filtering the image behind SRV `srcSrv` (srcWidth x srcHeight) into the image
/// behind UAV `dstUav` (dstWidth x dstHeight), both of `format`.
Result<ResampleDispatch> Prepare(EngineContext& context, ImagePassFormat format,
                                 uint32_t srcWidth, uint32_t srcHeight, uint32_t srcSrv,
                                 uint32_t dstWidth, uint32_t dstHeight, uint32_t dstUav,
                                 const ResampleOptions& options);

/// Records `dispatch`; the source must be in `ShaderResource`, the destination in
/// `UnorderedAccess` state.
void Record(uz::IRHICommandList& cmd, const ResampleDispatch& dispatch);

}  // namespace resample_detail

}  // namespace uzp::render
