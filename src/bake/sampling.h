#pragma once

// Fixed sample addressing of the CPU baker (`06-baking.md` §1, decision 302): sample `s` of a
// texel is a pure function of the texel index, the sample id and the sample count, so which
// thread computes it never matters. The point set is Hammersley's, (s / N, Φ2(s)), rotated per
// texel (Cranley-Patterson) by an offset hashed from the texel index; directions use a fixed
// orthonormal frame (Duff et al., "Building an Orthonormal Basis, Revisited", JCGT 2017).
// The same functions are meant for the later GpuBaker (P4-DXR).

#include <cstdint>

#include "bake/bake_request.h"

namespace uzp::bake {

struct Sample2 {
    double u1 = 0.0;
    double u2 = 0.0;
};

struct Vec3d {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

/// SplitMix64's finaliser (Steele, Lea and Flood, "Fast Splittable Pseudorandom Number
/// Generators", OOPSLA 2014).
std::uint64_t SplitMix64(std::uint64_t value);

/// Van der Corput radical inverse in base 2 of `index`, in [0, 1).
double RadicalInverse2(std::uint32_t index);

/// Sample `sample_id` of `sample_count` for the texel `texel_index` (row-major), in [0, 1)².
Sample2 TexelSample(std::uint64_t texel_index, std::uint32_t sample_id, std::uint32_t sample_count);

/// Unit direction around the unit normal `n` for `sample` under `distribution`; its component
/// along `n` is >= 0.
Vec3d HemisphereDirection(Distribution distribution, Sample2 sample, Vec3d n);

}  // namespace uzp::bake
