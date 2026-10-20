#pragma once

// The `WorldSpaceNormal` baker of the CPU baker (phase3.4_baker-world-space-normal,
// `docs/architecture/06-baking.md` §2 and §3.3, decision 337), on the shared ray-cast core of
// `embree_baker.cpp`: at each hit texel, the high mesh's interpolated corner normals at the primary
// hit, normalised in double, in the meshes' scene frame (`mesh_inputs.h`: the object transforms
// applied, normals through the inverse transpose). `LowAsHigh` bakes the low parts onto themselves,
// so the hit is on the low mesh and the normal is its own.
//
// The map is float32 xyz, signed and unencoded: the channel format and value mapping of Painter's
// map are established by the Tier 2b goldens (item 2.2), so no encoding is applied here. Misses,
// back-face hits, hidden and uncovered texels hold zero and are told apart by the class map.
// `SubSampling` above 1 and `DilationWidth` above 0 are refused before any work: their resolve and
// padding rules are not recorded. Parity with Painter is not claimed (`pending-evidence`).

#include <cstddef>

#include "bake/bake_request.h"
#include "bake/sampling.h"

namespace uzp::bake {

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (`SubSampling` > 1,
/// `DilationWidth` > 0), naming phase3.4_baker-world-space-normal. Called before any work.
void ValidateWorldSpaceNormal(const BakeRequest& request);

/// Allocates `result.world_normal` (three zero floats per texel).
void PrepareWorldSpaceNormal(BakeResult& result);

/// Writes the unit high normal `normal` of the hit at `texel`.
void WriteWorldSpaceNormal(BakeResult& result, std::size_t texel, const Vec3d& normal);

}  // namespace uzp::bake
