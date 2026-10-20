#pragma once

// The `Height` baker of the CPU baker (phase3.4_baker-height, `docs/architecture/06-baking.md` §2
// and §3.3, decision 341), on the shared ray-cast core of `embree_baker.cpp`: at each hit texel,
// the signed distance from the low surface to the high surface along the primary ray. It is
// positive where the high surface lies in front of the low one, towards the ray's origin (above it
// for the distance-based cage, between it and the cage for a custom cage), and negative behind it.
// The value is in centimetres: the mesh-unit distance times the request's `scale_to_internal`
// (`12-mesh-import.md` §3). `LowAsHigh` bakes the low parts onto themselves, so it is zero.
//
// - Every `MaximizeRange` ("Normalization") value is refused before any work (`NotYetSupported`):
//   how a signed distance maps to a value under each (which bound each sign takes, where zero
//   falls, which texels a per-UV-tile range spans, what the low mesh's range is, what Manual
//   reads) and how `Divisor` composes with it are not recorded. Painter's default is "Relative to
//   low mesh (per UV tile)", so a Height bake with Painter's defaults is refused.
// - A request without a normalisation (an evidence request no parameter makes) bakes the signed
//   distance, unnormalised; `Divisor` is recorded and not applied.
// - `SubSampling` above 1 and `DilationWidth` above 0 are refused: their resolve and padding rules
//   are not recorded.
//
// The map is float32 and unclamped. Non-hit texels hold zero and are told apart by the class map.
// What was applied is recorded in the result (`HeightNormalizationRecord`) and, as JSON, for the
// binding's `baked.effective_normalization`. Parity with Painter is not claimed (`pending-evidence`).

#include <cstddef>

#include "bake/bake_request.h"
#include "uzp_core/manifest/json.h"

namespace uzp::bake {

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (above), naming
/// phase3.4_baker-height, and `uzp::core::ValueError` for an invalid setting. Before any work.
void ValidateHeight(const BakeRequest& request);

/// Allocates `result.height_map` and records what `request` applies.
void PrepareHeight(const BakeRequest& request, BakeResult& result);

/// Writes the signed low-to-high distance `distance` (mesh units) of the hit at `texel`.
void WriteHeight(BakeResult& result, std::size_t texel, double distance);

/// `record` as the binding's `effective_normalization`: Painter's labels for the settings (null
/// where no normalisation is set), whether each was applied, the unit, the unit scale and the range
/// (null: none applied).
core::json::Object HeightNormalizationJson(const HeightNormalizationRecord& record);

}  // namespace uzp::bake
