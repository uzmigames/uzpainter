#pragma once

// The virtual normal maps `Normal_OpenGL` and `Normal_DirectX` and the geometry-only normal
// pass-through (docs/architecture/04-layer-stack-and-compositing.md §6, EXP-09; task
// phase1.12_compositor-height-normal, parity/semantics/height-to-normal.json, decisions 064 and
// 065). Fitted on the Tier 0 height-normal goldens of Painter 12.1.5, exact on every recorded map:
//
// - Input: the Height channel's read-out before its write rule (the isolated root composited
//   over the base in float32, not the stored half: opacity 0.75 and 0.1 show it) and the Normal
//   channel's read-out composited over the flat colour (0.5, 0.5, 1) (an empty Normal channel
//   acts as the flat normal although it exports its base 127/255).
// - Height-derived vector v per texel (rows top first, wrap-around at the set border), h(dx, dy)
//   the height at column x + dx, row y + dy:
//     Sharp:          v = (h(-1, 0) - h(0, 0), h(0, 0) - h(0, -1), 0.390625);
//     Smooth (Sobel): v = (L - R, B - T, 3.125), L = (h(-1,-1) + 2 h(-1,0)) + h(-1,1), R likewise
//                     at dx = +1, T = (h(-1,-1) + 2 h(0,-1)) + h(1,-1), B likewise at dy = +1
//                     (this summation order is the implemented convention; the goldens do not
//                     separate it from others).
//   0.390625 = 1 / 2.56 (and 3.125 = 8 x 0.390625) at 256 texels; other resolutions are not
//   recorded and are refused.
// - Combination (arith.h normal-map steps): H = normalise(v); A = normalise(reoriented(F, H))
//   with F the flat normal (0, 0, 1); C = decode(Normal-channel read-out); n = normalise(
//   reoriented(A, C)). Normal_OpenGL stores fma(n, 1/2, 1/2); Normal_DirectX negates n.y first.
//   A bound Normal mesh map (whose place in the chain is not recorded) is refused.
// - Results are the float32 encoded normals; an export writes them with its write rule (16-bit
//   PNG: arith::WriteUnorm).
//
// The geometry-only pass-through is the bound Normal mesh map itself: every code as the operand
// float32(code / max), the green codes inverted (max - g) when the requested convention differs
// from the map's (phase0.9 normal-convention fixture: Painter's DirectX bake is the inverted
// OpenGL bake).
//
// Every result carries its EXP-09 tag: `combined` with the relief round it contains (the
// snapshot's revision, the Height read-out's subtree hash and the method) or `geometry_only`.

#include "evaluator/admission.h"
#include "evaluator/evaluate.h"
#include "evaluator/resources.h"
#include "evaluator/templates.h"
#include "evaluator/tile_store.h"

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// The z component of the height-derived vector at 256 texels: Sharp, Sobel.
inline constexpr float kSharpZ = 0.390625f;
inline constexpr float kSobelZ = 3.125f;
/// The only set resolution whose height-to-normal scaling is recorded.
inline constexpr uint32_t kRecordedNormalResolution = 256;

/// The heights the stencils read around one texel: index (dy + 1) 3 + dx + 1, dx, dy in [-1, 1].
using HeightNeighbourhood = std::array<float, 9>;

/// The height-derived vector v (before normalisation) of `method` (see above).
[[nodiscard]] std::array<float, 3> HeightVector(core::HeightToNormalMethod method,
                                                const HeightNeighbourhood& h);

/// The encoded normal of one texel: the combination of the height vector `v` with the Normal
/// channel's read-out colour `channel`, as n / 2 + 1/2 in `convention`.
[[nodiscard]] std::array<float, 3> VirtualNormalTexel(const std::array<float, 3>& v,
                                                      const std::array<float, 3>& channel,
                                                      core::NormalMapFormat convention);

/// The flat colour the virtual maps composite the Normal channel over.
inline constexpr std::array<float, 3> kFlatNormalColour{0.5f, 0.5f, 1.0f};

/// What a virtual normal source is.
enum class NormalSourceKind : uint8_t {
    Combined,      ///< Normal_OpenGL / Normal_DirectX: mesh normal, channel normal and height.
    GeometryOnly,  ///< The bound Normal mesh map, passed through.
};

/// The relief a combined normal contains (EXP-09): an adapter must not add it again.
struct ReliefRound {
    /// The snapshot's revision the normal was evaluated from.
    std::int64_t revision = 0;
    /// Hex SHA-256 of the Height read-out's subtree (profile, channel, format, base, resolution,
    /// every contributing layer, source and mask); empty when the stack has no Height channel.
    std::string heightHash;
    core::HeightToNormalMethod method = core::HeightToNormalMethod::Sharp;

    friend bool operator==(const ReliefRound&, const ReliefRound&) = default;
};

/// The EXP-09 tag of an exported or previewed normal.
struct NormalTag {
    core::MeshMapRole role = core::MeshMapRole::combined;
    /// Set exactly when `role` is `combined`.
    std::optional<ReliefRound> relief;

    friend bool operator==(const NormalTag&, const NormalTag&) = default;
};

struct VirtualNormalRequest {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    NormalSourceKind kind = NormalSourceKind::Combined;
    core::NormalMapFormat convention = core::NormalMapFormat::OpenGL;
    /// The template the project was created from (its base values).
    std::string templateId{kDefaultTemplateId};
    /// The bytes of bitmap sources and of the Normal mesh map; may be null when there are none.
    std::shared_ptr<const IResourceProvider> resources;
    /// The rasters of `Mesh` geometry masks; may be null when the stacks have none.
    std::shared_ptr<const IGeometryMaskProvider> geometry;
};

struct VirtualNormalResult {
    NormalSourceKind kind = NormalSourceKind::Combined;
    core::NormalMapFormat convention = core::NormalMapFormat::OpenGL;
    uint32_t width = 0;
    uint32_t height = 0;
    /// Rows top first, three float32 per texel: the encoded normal in [0, 1].
    std::vector<float> texels;
    NormalTag tag;
    EvaluationStats stats;
};

/// Evaluates `request` against `project` (revision `revision`) on `store` with `cache`: the
/// combined virtual map (the Height and Normal read-outs, one VirtualNormalOp per tile) or the
/// geometry-only pass-through. Fails with the evaluation failures of the two channels and with
/// `evaluator:unsupported_source` for what is not recorded: a set resolution other than 256, a
/// bound Normal mesh map in the combined map, a non-empty Normal channel in a DirectX project,
/// a profile whose root is not isolated; `missing_resource` for a pass-through without a Normal
/// mesh map or bytes.
[[nodiscard]] render::Result<VirtualNormalResult> EvaluateVirtualNormalOn(
    const core::Project& project, std::int64_t revision, const VirtualNormalRequest& request,
    const TemplateLibrary& templates, ITileStore& store, TileCache& cache);

}  // namespace uzp::evaluator
