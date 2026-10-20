#pragma once

// The `Position` baker of the CPU baker (phase3.4_baker-position, `docs/architecture/06-baking.md`
// §2 and §3.3, decision 337), on the shared ray-cast core of `embree_baker.cpp`: at each hit texel,
// the high surface point at the primary hit (Embree's barycentrics on the hit triangle, in double),
// in the meshes' scene frame. `LowAsHigh` bakes the low parts onto themselves.
//
// - `Mode` All axis writes x, y and z; One axis writes the coordinate on `Axis` only.
// - `Normalization` None writes the coordinate in centimetres (the mesh-unit value times the
//   request's `scale_to_internal`, `12-mesh-import.md` §3): no bounds apply, so
//   `NormalizationScale` has no effect.
// - `Normalization` BBox and BSphere are refused before any work (`NotYetSupported`): which box or
//   sphere (the texture set's or the scene's, the low or the high meshes) and how a point maps to
//   a value are not recorded.
// - `SubSampling` above 1 and `DilationWidth` above 0 are refused: their resolve and padding rules
//   are not recorded.
//
// The map is float32 and unclamped. Non-hit texels hold zero and are told apart by the class map.
// The applied normalisation is recorded in the result (`PositionNormalizationRecord`) and, as JSON,
// for the binding's `baked.effective_normalization`. Parity with Painter is not claimed
// (`pending-evidence`).

#include <cstddef>

#include "bake/bake_request.h"
#include "bake/sampling.h"
#include "uzp_core/manifest/json.h"

namespace uzp::bake {

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (above), naming
/// phase3.4_baker-position, and `uzp::core::ValueError` for an invalid setting. Before any work.
void ValidatePosition(const BakeRequest& request);

/// Allocates `result.position` and records the normalisation `request` applies.
void PreparePosition(const BakeRequest& request, BakeResult& result);

/// Writes the high surface point `point` (mesh units) of the hit at `texel`.
void WritePosition(BakeResult& result, std::size_t texel, const Vec3d& point);

/// `record` as the binding's `effective_normalization`: Painter's labels for the four settings,
/// the channel count, the unit, the unit scale and the bounds (null: none applied).
core::json::Object PositionNormalizationJson(const PositionNormalizationRecord& record);

}  // namespace uzp::bake
