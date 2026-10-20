#pragma once

// UzPainter's grunge and noise family (docs/architecture/05-procedural-content.md §3, the
// "Grunges and noises" row; rulebook task phase3.2_proc-grunge-families; decision 331). The
// inventory of the assets and of the parameter sets the recipes record is
// docs/analysis/proc-grunge-families/01-asset-inventory.md.
//
// Every asset is `uzasset://grunge/<id>@1`: one single-channel, float32, linear texture of one UV
// tile, computed per texel from the request's seed and parameters. It reads no image input. Each
// asset is a fixed configuration of six pattern kinds over the shared primitive library
// (`primitives.h`: flushed single operations, `Pcg3d` hashing, `Fade2002`, `SqrtRn`):
//
// - fBm: fractional Brownian motion (Mandelbrot and Van Ness 1968; Musgrave in Ebert et al.,
//   "Texturing and Modeling") of Perlin 2002 gradient noise on the z = 0 plane, lacunarity 2;
// - ridged: the same sum of (1 - |noise|)^2 per octave (Musgrave's ridged multifractal);
// - spots: one disc per Worley cell (Worley 1996), with a radius class, a presence probability, a
//   soft (1 - d^2/r^2)^2 or hard profile and an intensity from the cell hash, the brightest kept;
// - scratches: one tapered line segment per Worley cell, its direction from a table spanning the
//   rotation variation, the brightest kept;
// - cracks: Worley's F2 - F1 cell borders under a width and a hardness;
// - weave: a plain weave of warp and weft threads (Peachey, "Building Procedural Textures", in
//   Ebert et al.: periodic patterns from the integer and fractional parts of a coordinate).
//
// Tiling: every lattice is periodic. A cell index is taken modulo the period, and every distance
// is computed from the fractional part of the coordinate, so the texture continued past its
// border is the texture itself, bit for bit (Lagae et al., "A Survey of Procedural Noise
// Functions", 2010, periodic noise). The `tiling` parameter repeats the pattern a whole number of
// times across the texture. A texel's coordinate (x + 1/2) P / R is exact in float32 for every
// period P and resolution R of the domain, so the periodicity holds for the float computation.
//
// Parameters (UzPainter's own names; Painter's are not discovered yet, item 2.2):
// - every asset: `balance` (adds balance - 1/2), `contrast` (scales about 1/2 by
//   1 / (1 - 0.9 contrast)), the result clamped to [0, 1], `invert` (1 - value) and `tiling`;
// - spots: `disorder` (the spot centre's jitter inside its cell, 1/2 + disorder / 2);
// - scratches: `rotation_variation` (degrees: the span of the sixteen directions);
// - humidity: `flip_horizontal`, `flip_vertical` (the coordinate mirrored inside the tile);
// - cracks: `hardness` (soft to hard profile) and `shape` (the border width, 0.02 to 0.12 cell);
// - linen: `tension_variation` (the thickness variation of each thread).
//
// One kernel pass per request. Its parameter block (`GrungeWords`) carries every float the
// kernel needs, computed once on the host (divisions and the direction table's sines and cosines
// in IEEE double, then rounded to float32), so the kernel has no division and no transcendental.
// The CPU reference (`GrungeTexel`) reads the same block and equals the kernel bit for bit.
//
// None of these assets is certified: the records say `unavailable`, the seam refuses them, and no
// alias of the library names them (decision 324). The domains are those of the records.

#include "procedural/asset_library.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include <cstdint>
#include <expected>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural {

/// The family of every grunge asset (`uzasset://grunge/<id>@1`).
inline constexpr std::string_view kGrungeFamily = "grunge";

/// The ids of the family's assets, in the inventory's order.
[[nodiscard]] std::span<const std::string_view> GrungeAssetIds();

/// Registers every grunge asset with `hlsl`, each with the record `library` holds for it (its
/// domain, its status, its provenance). Refused when the library lacks a record or the host
/// refuses the registration.
std::expected<void, std::string> RegisterGrungeFamilies(HlslBackend& hlsl, const AssetLibrary& library);

/// The parameter block of the kernel of `request` (its words are what `ProcParam` reads): the
/// asset's configuration, the request's parameters and the derived float32 constants for the
/// output resolution. Refused for an asset outside the family or a parameter it lacks.
[[nodiscard]] std::expected<std::vector<uint32_t>, std::string> GrungeWords(const ProceduralRequest& request);

/// The CPU reference of the texel at (x, y) of the texture that `words` describes, for the
/// request seed `seed`. Any integer position is valid: a position outside [0, R) gives the
/// texture continued periodically, so (x + R, y) and (x, y + R) give the texel of (x, y).
[[nodiscard]] float GrungeTexel(std::span<const uint32_t> words, int32_t x, int32_t y, uint32_t seed);

}  // namespace uzp::procedural
