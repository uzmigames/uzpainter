#pragma once

// The `Opacity` baker of the CPU baker (phase3.4_baker-opacity, `docs/architecture/06-baking.md`
// §2 and §3.3, decision 341), on the shared ray-cast core of `embree_baker.cpp`: at each hit texel,
// the opacity of the high surface the primary ray hit. A bake mesh carries no transparency input
// (no alpha, texture or material), so a hit surface is opaque: 1. Misses, back-face hits, hidden and
// uncovered texels hold 0 and are told apart by the class map, as in every map of the core.
//
// The map is float32 in [0, 1], unencoded: the channel format of Painter's map is established by
// the Tier 2b goldens (item 2.2). `SubSampling` above 1 and `DilationWidth` above 0 are refused
// before any work: a fractional coverage and the padding are not recorded. Opacity has no
// parameters of its own (`assets/defaults/baking.json`). Parity with Painter is not claimed
// (`pending-evidence`).

#include <cstddef>

#include "bake/bake_request.h"

namespace uzp::bake {

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (`SubSampling` > 1,
/// `DilationWidth` > 0), naming phase3.4_baker-opacity. Called before any work.
void ValidateOpacity(const BakeRequest& request);

/// Allocates `result.opacity` (one zero float per texel).
void PrepareOpacity(BakeResult& result);

/// Writes the opacity of the hit at `texel`.
void WriteOpacity(BakeResult& result, std::size_t texel);

}  // namespace uzp::bake
