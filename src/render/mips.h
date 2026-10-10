#pragma once

// Mip generation (docs/architecture/13-engine-integration.md §4.1, 08-export.md §5: the
// `.uztexture` chains and the export presets): every level from the previous one with the box
// filter of resample.h (exact area weights; level k is max(1, extent >> k) per axis, so odd
// extents weigh three source texels per axis), in three modes that combine:
//
// - sRGB-aware (`ColourMode::Srgb`): decode, filter in linear float, encode (image_pass.h);
// - normal (`ColourMode::Normal`): the filtered vector renormalised, then stored;
// - alpha-coverage preserving (`preserveAlphaCoverage`, four-channel unorm formats): with the
//   cutoff code K = ceil(alphaCutoff M) (at least 1), level 0 covers count0 texels (alpha
//   >= K). Each filtered level k (N_k texels) covers exactly target = round(count0 N_k / N_0)
//   texels (nearest, ties down): the `target` texels of largest alpha, equal alphas taken in
//   linear order (rows top to bottom, texels left to right). With t the alpha of the last
//   covered texel: when every texel of alpha t is covered, alpha becomes min(M, floor(alpha K /
//   u)) with u the divisor closest to K that separates the covered texels (u = K leaves alpha
//   unchanged); when t is split, u = max(t, 1) and the texels of alpha t become K (covered) or
//   K - 1 (not covered; 0 stays 0). Kernels: src/render/shaders/mips.hlsl.
//
// Levels are filtered from the stored previous level, so the chain equals the CPU reference's
// level-by-level arithmetic bit for bit.

#include "render/backend.h"
#include "render/engine_thread.h"
#include "render/image_pass.h"

#include <cstdint>

namespace uzp::render {

struct MipOptions {
    ColourMode colour = ColourMode::Linear;
    bool preserveAlphaCoverage = false;
    /// Alpha at or above this fraction counts as covered (alpha test); in (0, 1].
    float alphaCutoff = 0.5f;
};

/// Fills mip levels 1 .. mipLevels - 1 of `texture` from level 0. The texture needs `CopySrc`
/// and `CopyDst` usage and an image-pass format; `ColourMode::Srgb` needs 8-bit unorm,
/// `ColourMode::Normal` four channels, alpha coverage four unorm channels.
Result<void> GenerateMips(EngineContext& context, uz::RHITextureHandle texture,
                          const MipOptions& options);

/// The extent of mip `level` of an `extent`-texel axis: max(1, extent >> level).
[[nodiscard]] constexpr uint32_t MipExtent(uint32_t extent, uint32_t level) {
    const uint32_t shifted = level >= 32 ? 0u : extent >> level;
    return shifted == 0 ? 1u : shifted;
}

/// K, the smallest covered alpha code for `cutoff` in `encoding` (an unorm encoding):
/// ceil(cutoff M) clamped to 1..M.
[[nodiscard]] uint32_t AlphaCutoffCode(float cutoff, TexelEncoding encoding);

}  // namespace uzp::render
