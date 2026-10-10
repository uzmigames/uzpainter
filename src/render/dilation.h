#pragma once

// Jump-flood dilation over a coverage mask (docs/architecture/13-engine-integration.md §4.1,
// 04-layer-stack-and-compositing.md §7, 08-export.md §3): uncovered texels take the colour of
// the nearest covered texel within a distance limit. Export padding (`infinite` and the
// distance-limited modes fitted by phase1.16_export-processing-encoders) is built on it.
// Kernels: src/render/shaders/dilation_jfa.hlsl. Integer arithmetic only.
//
// - Covered: the coverage mask's channel 0 is non-zero (the conservative R8Unorm mask of
//   uv_raster.h qualifies).
// - Seeds: every covered texel is its own seed. Jump flooding ("1+JFA") runs a step of length 1,
//   then steps of N/2, N/4, ..., 1 (`JumpFloodSteps`). In a step each texel keeps, among its
//   current seed and the seeds of the eight texels at offsets (dx, dy) x step (dx, dy in
//   {-1, 0, 1}, inside the image), the seed at the smallest squared Euclidean distance.
// - Tie-break: equal squared distances go to the seed with the smaller linear index y W + x.
// - Distance limit: an uncovered texel takes its seed's colour when the squared distance is at
//   most maxDistance²; uncovered texels farther away, and covered texels, keep their colour
//   (copied bit for bit). `kUnlimitedDistance` fills every texel when any texel is covered.
//
// Jump flooding finds the exact nearest covered texel in all but rare configurations; the CPU
// reference (tests/render/reference/) runs the same steps, and the tests also compare the
// result with a brute-force nearest-texel search on their island masks.

#include "render/backend.h"
#include "render/engine_thread.h"

#include <cstdint>
#include <vector>

namespace uzp::render {

/// A `maxDistance` without limit.
inline constexpr uint32_t kUnlimitedDistance = 0xFFFFFFFFu;

struct DilationDesc {
    /// The colour to dilate (`ShaderResource` and `CopySrc` usage).
    uz::RHITextureHandle colour = uz::RHITextureHandle::Invalid();
    /// The coverage mask, the colour's size (`ShaderResource` usage, any image-pass format).
    uz::RHITextureHandle coverage = uz::RHITextureHandle::Invalid();
    /// Receives the result: the colour's size and format (`UnorderedAccess` and `CopyDst`).
    uz::RHITextureHandle output = uz::RHITextureHandle::Invalid();
    /// Euclidean distance limit in texels; 0 copies the colour unchanged.
    uint32_t maxDistance = kUnlimitedDistance;
};

/// Dilates `desc.colour` into `desc.output` (mip 0 of each).
Result<void> Dilate(EngineContext& context, const DilationDesc& desc);

/// The jump lengths for a width x height image and a distance limit: none when the reach
/// L = min(maxDistance, max(width, height) - 1) is 0; otherwise 1, then N/2, N/4, ..., 1 with N
/// the smallest power of two greater than L.
[[nodiscard]] std::vector<uint32_t> JumpFloodSteps(uint32_t width, uint32_t height,
                                                   uint32_t maxDistance);

}  // namespace uzp::render
