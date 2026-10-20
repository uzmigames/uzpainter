#pragma once

// The `Thickness` baker of the CPU baker (phase3.4_baker-thickness, `docs/architecture/06-baking.md`
// §2 and §3.3, decision 341), on the shared ray-cast core of `embree_baker.cpp`: at each hit texel,
// `NbSecondary` secondary rays cast inward from the high surface point, over the hemisphere opposite
// the interpolated high normal by `Distribution`, each searching `MinDistance` to `MaxDistance`
// (centimetres, or fractions of the bounding-box size with `MaxDistanceRelativeScale`). The
// samples are decision 302's (Hammersley by texel index and ray id). Each ray's first hit is
// classed like an AO ray (escaped, front face, back face, its own triangle) and its distance kept.
//
// - What the baker produces is the per-ray evidence: every ray's class and hit distance in
//   centimetres. No per-texel thickness value is computed: how a texel's ray distances combine
//   (their mean, with or without the escaped rays, what an escaped ray counts, which hit classes
//   count) is not recorded.
// - So every `MaximizeRange` ("Normalization") value is refused before any work (`NotYetSupported`),
//   Painter's default "Relative to min/max (per UV tile)" included; only a request without a
//   normalisation (an evidence request no parameter makes) bakes.
// - `Spread` other than 180 and `FilterMethodSecondary` other than Always are refused by
//   `RequestFromParameters` (as for AO). `SubSampling` above 1 and `DilationWidth` above 0 are
//   refused here. The evidence is bounded at 2^26 rays (texels x `NbSecondary`).
//
// Non-hit texels cast no ray: their slots hold `NotCast` and 0. Parity with Painter is not claimed
// (`pending-evidence`).

#include <cstddef>
#include <functional>

#include "bake/bake_request.h"
#include "bake/sampling.h"
#include "uzp_core/manifest/json.h"

namespace uzp::bake {

/// The first hit of a secondary ray, classed (decision 302 §4), and its distance in mesh units.
struct SecondaryHit {
    ThicknessRayClass cls = ThicknessRayClass::Escaped;
    float t = 0.0f;
};

/// Casts one secondary ray from `origin` along the unit `direction`, searching [tnear, tfar].
using SecondaryCaster = std::function<SecondaryHit(const Vec3d& origin, const Vec3d& direction, float tnear, float tfar)>;

/// Raises `uzp::core::NotYetSupported` for what the baker does not establish (above), naming
/// phase3.4_baker-thickness, and `uzp::core::ValueError` for an invalid setting. Before any work.
void ValidateThickness(const BakeRequest& request);

/// Allocates the per-ray maps and records the settings and effective distances of `request`.
void PrepareThickness(const BakeRequest& request, BakeResult& result);

/// Casts the inward rays of the hit at `texel` (high point `point`, unit high normal `normal`) and
/// writes their classes and distances.
void CastThickness(BakeResult& result, std::size_t texel, const Vec3d& point, const Vec3d& normal,
                   const SecondaryCaster& cast);

/// Totals the rays by class into `result.thickness.rays`, serially, after every texel is cast.
void CountThickness(BakeResult& result);

/// `record` as the binding's `effective_normalization`: the settings by Painter's labels
/// (`MaximizeRange` null where none is set), the effective distances, the unit and the range (null:
/// no thickness value, so none applied).
core::json::Object ThicknessRecordJson(const ThicknessRecord& record);

}  // namespace uzp::bake
