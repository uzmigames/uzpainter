#pragma once

// The virtual normal maps `Normal_OpenGL` and `Normal_DirectX` and the geometry-only normal
// pass-through (docs/architecture/04-layer-stack-and-compositing.md §6, EXP-09; task
// phase1.12_compositor-height-normal, parity/semantics/height-to-normal.json, decisions 064, 065,
// 079 and 080). Fitted on the Tier 0 height-normal goldens of Painter 12.1.5, exact on every r1
// map:
//
// - Inputs: the Height channel's read-out before its write rule (the isolated root composited
//   over the base in float32, not the stored half: opacity 0.75 and 0.1 show it); the Normal
//   channel's root list composited from a transparent start, colour X and coverage a (before its
//   read-out); the bound Normal mesh map's codes as UNORM operands M.
// - Height-derived vector v per texel (rows top first, wrap-around at the set border), h(dx, dy)
//   the height at column x + dx, row y + dy, W the set width:
//     Sharp:          v = (h(-1, 0) - h(0, 0), h(0, 0) - h(0, -1), 100 / W);
//     Smooth (Sobel): v = (L - R, B - T, 800 / W), L = (h(-1,-1) + 2 h(-1,0)) + h(-1,1), R likewise
//                     at dx = +1, T = (h(-1,-1) + 2 h(0,-1)) + h(1,-1), B likewise at dy = +1
//                     (this summation order is the implemented convention; the goldens do not
//                     separate it from others).
//   z is a UV-space gradient: 0.390625 = 100 / 256 and 3.125 = 800 / 256, recorded at 256, 512,
//   1024 and 2048 texels (square sets; other sizes and shapes are refused).
// - Combination (arith.h normal-map steps): H = normalise(v); F = decode(M), its y negated when
//   the mesh map is in the DirectX convention, else the flat normal (0, 0, 1); A = normalise(
//   reoriented(F, H)) (a mesh map in the project's convention; another one is refused); the
//   channel normal C = the flat normal where a = 0, else u = decode(X
//   hw::Rcp(a)) turned toward the flat normal by a: (u.x k, u.y k, cos(t)), t = a acos(z), z =
//   u.z clamped to [0, 1], k = sin(t) rsqrt(fma(-z, z, 1)) (acos, sin, cos and rsqrt the GPU's,
//   hwmath.h; u kept at a = 1 or z = 1); n = normalise(reoriented(A, C)). Normal_OpenGL stores fma(n, 1/2, 1/2);
//   Normal_DirectX negates n.y first. At full coverage C = decode(X). The Normal channel's own
//   read-out (its export) is X over the flat colour (0.5, 0.5, 1), while an empty channel exports
//   its template base 127/255 (dag.h ChannelDag::readoutBase).
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
#include <string_view>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// The z component of the height-derived vector at 256 texels: Sharp, Sobel.
inline constexpr float kSharpZ = 0.390625f;
inline constexpr float kSobelZ = 3.125f;

/// The z of `method` on a set `width` texels wide: kSharpZ or kSobelZ times 256 / width (exact
/// for the power-of-two widths it is used with).
[[nodiscard]] float HeightZ(core::HeightToNormalMethod method, uint32_t width);

/// The heights the stencils read around one texel: index (dy + 1) 3 + dx + 1, dx, dy in [-1, 1].
using HeightNeighbourhood = std::array<float, 9>;

/// The height-derived vector v (before normalisation) of `method` with z `z` (see above).
[[nodiscard]] std::array<float, 3> HeightVector(core::HeightToNormalMethod method,
                                                const HeightNeighbourhood& h, float z);

/// The flat normal colour: the Normal channel's read-out base and an empty channel's input.
inline constexpr std::array<float, 3> kFlatNormalColour{0.5f, 0.5f, 1.0f};

/// The inputs of one texel of a virtual map besides the height vector.
struct NormalInputs {
    /// A Normal mesh map is bound: its operands and its convention (else F is the flat normal).
    bool hasMesh = false;
    std::array<float, 3> mesh = kFlatNormalColour;
    bool meshDirectX = false;
    /// The Normal channel's colour X and coverage a from a transparent start.
    std::array<float, 3> channel = kFlatNormalColour;
    float coverage = 1.0f;
};

/// The encoded normal of one texel: the combination of the height vector `v` with the mesh map
/// and the Normal channel of `inputs`, as n / 2 + 1/2 in `convention`.
[[nodiscard]] std::array<float, 3> VirtualNormalTexel(const std::array<float, 3>& v, const NormalInputs& inputs,
                                                      core::NormalMapFormat convention);

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
/// combined virtual map (the Height read-out, the Normal channel's root list and the Normal
/// mesh map, one VirtualNormalOp per tile) or the geometry-only pass-through. Fails with the
/// evaluation failures of the two channels and with `evaluator:unsupported_source` for what is
/// not recorded: a set that is not square of 256, 512, 1024 or 2048 texels, a Normal mesh map in
/// the combined map that is not a 16-bit RGB image at the set resolution in the project's
/// convention, a profile whose root is not isolated; `missing_resource` for a Normal mesh map
/// without a resource provider or bytes.
[[nodiscard]] render::Result<VirtualNormalResult> EvaluateVirtualNormalOn(
    const core::Project& project, std::int64_t revision, const VirtualNormalRequest& request,
    const TemplateLibrary& templates, ITileStore& store, TileCache& cache);

/// Whether the Height read-out the stencils of `stack` read is 0 on every texel, decided from the
/// stack without evaluating it: the stack has no Height channel, or no layer contributes to its
/// Height (an empty root list reads out as the base) and its base is 0. On a texture set whose
/// UV islands do not cover the tile, a combined virtual map is exact at its island-edge texels
/// only then (export/padding.h `CheckIslandNormal`, decision 245). Fails with `not_found` for an
/// unknown set or stack and with the failures of the Height DAG.
[[nodiscard]] render::Result<bool> FlatZeroHeight(const core::Project& project, core::Id textureSet, core::Id stack,
                                                  const TemplateLibrary& templates, std::string_view templateId);

}  // namespace uzp::evaluator
