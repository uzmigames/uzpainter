#pragma once

// UzPainter's filter families (docs/architecture/05-procedural-content.md §3, the Filters row;
// rulebook task phase3.2_proc-filter-families; decision 328). A filter computes from the layer
// content at its position in the effect list (04-layer-stack-and-compositing.md §2 step 4): one
// image input, `content` (kContentInput), with the output's resolution, channels and colour space.
//
// - Sharpen (`uzasset://filter/sharpen@1`): Laplacian sharpening (Gonzalez and Woods, Digital
//   Image Processing, 4th ed., §3.6), g = f - amount x L(f) with the four-neighbour Laplacian
//   L(f) = (((f(x-1, y) + f(x+1, y)) + f(x, y-1)) + f(x, y+1)) - 4 f, the content wrapping at
//   the texture border. Every channel alike.
// - Grayscale conversion (`uzasset://filter/grayscale@1`): Y = (red R + green G) + blue B,
//   written to the three channels; the defaults are ITU-R BT.709's luma coefficients rounded to
//   float32.
// - Levels (`uzasset://filter/levels@1`): mapped onto the native levels effect
//   (`LevelsFilterEffect`), whose semantics Tier 0 settled (parity/semantics/masks-levels.json
//   `levels`, `levels-clamp`: the recording GPU's reciprocal, log2 and exp2 from measured
//   tables). It is not an HLSL family (decision 328 §1): the evaluator's levels effect is its
//   implementation on every lane.
//
// Sharpen and grayscale conversion are `IHlslFamily` families of the HLSL host: one kernel pass
// and a CPU reference built from the primitive library (`primitives.h`: flushed single
// operations, no contraction), equal bit for bit. A parameter is rounded once to float32. Each
// family's record, domain and status are those of its provenance record in the asset library
// (`RegisterFilterFamilies`), so the seam and the certification harness read one declaration.
//
// None of the three is certified: the records say `unavailable`, the seam refuses them, and no
// alias of the library names them (decision 324). `FilterEffectReference` is the CPU candidate
// lane of a filter effect, for certification and tests; the evaluator refuses filter effects
// until a family is certified (phase3.3_procedural-families).

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include "uzp_core/types/enums.h"
#include "uzp_core/types/layers.h"

#include <expected>
#include <optional>
#include <string>
#include <string_view>

namespace uzp::procedural {

inline constexpr std::string_view kSharpenAsset = "uzasset://filter/sharpen@1";
inline constexpr std::string_view kGrayscaleAsset = "uzasset://filter/grayscale@1";
inline constexpr std::string_view kLevelsAsset = "uzasset://filter/levels@1";

/// The joint rule of every filter, which the domain's JSON cannot state: the content input has
/// the output's resolution, channels and colour space. The refusal (`outside certified domain`)
/// names the content's field, its value and the output's value; nothing is resampled or
/// converted. Empty when the rule holds, or when the request has no content input (the domain
/// check refuses that first).
[[nodiscard]] std::optional<UnsupportedProcedural> FilterJointRefusal(const ProceduralRequest& request);

/// Registers Sharpen and grayscale conversion with `hlsl`, each with the record `library` holds
/// for it (its domain, its status, its provenance). Refused when the library lacks a record or
/// the host refuses the registration.
std::expected<void, std::string> RegisterFilterFamilies(HlslBackend& hlsl, const AssetLibrary& library);

/// The native levels effect a Levels filter request maps onto: one component whose input and
/// output ranges, gamma and clamp are the request's parameters (its affected channel is the
/// filter's, which the caller sets). Refused before anything is evaluated: another asset than the
/// Levels filter, a pin the library does not hold, a request outside the record's domain or
/// outside the joint rule. Nothing is clamped.
[[nodiscard]] std::expected<core::LevelsParams, UnsupportedProcedural> LevelsFilterEffect(
    const ProceduralRequest& request, const AssetLibrary& library);

/// The CPU lane of the Levels filter: `evaluator::arith::Levels` of every content value with the
/// mapped component's float32 parameters (converted as the evaluator converts a levels effect's),
/// over the request's tile; `request_failed` with the refusal or the invalid input otherwise.
render::Result<Raster> LevelsFilterReference(const ProceduralRequest& request, const AssetLibrary& library,
                                             const InputImages& inputs);

/// The content input of a filter request: `spec`, and the SHA-256 of the raster's float32
/// samples (little-endian, rows top first).
[[nodiscard]] ImageInput ContentInput(const Raster& content, const RasterSpec& spec);

/// A filter effect on the CPU candidate lane (04 §2 step 4): the filter of `request` evaluated on
/// `content` (the Levels filter through `LevelsFilterReference`, the others through
/// `hlsl.EvaluateReference`), then blended over the same content with the effect's own `mode` and
/// `opacity` through the evaluator's effect mix (`arith::Composite` with `effectMix`, mask 1),
/// over the request's tile. `content` must have the SHA-256 that the request's content input
/// names, one or three channels, and a mode with a blend kernel; otherwise `request_failed`.
render::Result<Raster> FilterEffectReference(const HlslBackend& hlsl, const AssetLibrary& library,
                                             const ProceduralRequest& request, const Raster& content,
                                             core::BlendingMode mode, float opacity);

}  // namespace uzp::procedural
