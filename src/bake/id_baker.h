#pragma once

// The `ID` baker of the CPU baker (phase3.4_baker-id, `docs/architecture/06-baking.md` §2 and §3.3,
// decision 337), on the shared ray-cast core of `embree_baker.cpp`.
//
// - `ColorSource` Mesh ID / Polygroup: a hit texel's label is the index of the high mesh the
//   primary hit is on, plus one, in request order (`LowAsHigh`: the low part). The bake mesh holds
//   no polygroups, so a mesh is one group. Non-hit texels hold 0 and keep their class.
// - The other sources are refused before any work (`NotYetSupported`): Vertex color, Material color
//   and File ID need inputs the bake mesh does not carry, and nothing recorded describes Submesh.
// - Every `ColorGenerator` is refused: the colour Painter gives each label is not recorded. A request
//   without a generator bakes the label map only.
// - `SubSampling` above 1 and `DilationWidth` above 0 are refused: their resolve and padding rules
//   are not recorded.
//
// Parity with Painter is not claimed (`pending-evidence`).

#include <cstddef>
#include <vector>

#include "bake/bake_request.h"

namespace uzp::bake {

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (above), naming
/// phase3.4_baker-id, and `uzp::core::ValueError` for more high meshes than uint16 labels. Before
/// any work.
void ValidateId(const BakeRequest& request);

/// Allocates `result.id_labels` and records the names of `high`, the meshes primary rays may hit,
/// in label order.
void PrepareId(const std::vector<const BakeMesh*>& high, BakeResult& result);

/// Writes the label of high mesh `mesh` (its index in the scene) at `texel`.
void WriteId(BakeResult& result, std::size_t texel, unsigned mesh);

}  // namespace uzp::bake
