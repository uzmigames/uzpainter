#pragma once

// The export's virtual maps (docs/architecture/08-export.md §2; task
// phase1.15_export-plan-compiler, decisions 086 and 092; parity/semantics/virtual-maps.json). The names
// are the documented `virtualMap` `srcMapName`s (Painter's public Python API documentation,
// export.html); their meaning is Adobe's public output-template documentation ("Output
// templates": converted maps), their operators are fitted on Tier 0 goldens.
//
// - `Normal_OpenGL`, `Normal_DirectX`: the combined normal of phase1.12 (mesh normal, Normal
//   channel and the height-derived normal, `evaluator/height_to_normal.h`), tagged `combined`.
//   The fits hold on every texel of a fully covered set and on the interior of UV islands; the
//   island-edge texels read the Height outside the islands, so an export refuses them there
//   (padding.h `CheckIslandNormal`, decision 245).
// - The diagnostic measure export (write.h; `VirtualMapRequest::islandNormal`, decision 308)
//   computes them on UV islands by Painter's recorded rule instead, not proven exact:
//   1. the stencil reads the Height read-out on the covered texels and, outside them, the
//      measured ring over the Height's stored operands without its 1 - (1 - m) step, then the
//      flood (padding.h `PadIslandHeight`; decisions 263, 288 (a));
//   2. the covered texels are the combined normal of that Height;
//   3. the mesh-free normal (the same without the mesh map, decision 276), padded by decision
//      287's ring copy and the clamped flood (padding.h `PadIslandNormal`); a ring texel whose
//      covered neighbours all lie across the x border keeps the flat height normal combined
//      with the Normal channel there (decision 287 §4);
//   4. without a Normal mesh map, the uncovered texels are that padded normal (decision 287
//      §5); with one, each is `MeshOnPaddedNormal` of the mesh map at the texel and the padded
//      unit Hn and C separately, in covered order (decision 293). The diagnostic undecided
//      marker remains pending the wider Height-ring and border evidence.
//   A measurement reads the float32 Height before and after step 1 when the environment variable
//   `UZP_DIAGNOSTIC_NORMAL_DUMP` names a directory (`<set>-height-readout.f32`,
//   `<set>-height-padded.f32`, raw rows top first); nothing else reads it.
// - The geometry-only pass-through is the meshMap `normal_base` (the bound Normal mesh map,
//   green inverted across conventions), tagged `geometry_only` (EXP-09).
// - `AO_Mixed` (decision 411; tools/parity/fit/ao_mixed_scan.py): the AO mesh map operand a enters
//   as a' = (1 + a) - 1; the AO channel operand is its fill mixed over the white base,
//   c = fma(S, al, 1) - al (S the source written as an L16 code first on an L16 channel; al the
//   layer opacity, its L16 code with ties down on L16, its float32 value on L32F), or 1 without
//   a layer; v = a' c, re-composited as (v - 1) + 1, written at 8 bits (WriteUnorm), every step
//   one float32 rounding. Exact on every r1 texel of the admitted AO goldens at PNG 8, PNG 16
//   and OpenEXR 32f. It is computed only in that scope (`AoMixedRefusal`): legacy colour
//   management, the default template, an L16 or L32F AO channel, a bound 8- or 16-bit grey AO
//   mesh map at the set's resolution, full UV coverage, and either no AO layer or one root fill
//   in Normal with a grey uniform colour or an 8- or 16-bit grey bitmap at the set's resolution
//   under the identity UV projection. Not the stored channel: an L16 channel stores the mix
//   quantized, an L32F one fma(S - 1, al, 1). After save and reopen Painter's AO_Mixed differs
//   on blended sets (decision 411).
// - `Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`,
//   `reflection`, `1/ior`, `f0`: fitted exactly on their goldens (virtual-maps.json), but they
//   read each channel's per-texel coverage, which the evaluator does not give, and constants
//   where a channel has no layer, seen on one template only (decision 092, recording R-092).
// - `View_2D`: a shaded render of the 2D view, not an operator on the channels (decision 092).
//
// A release-gap map is refused before anything is written (`Support`, CompilePlan).
//
// A virtual map's values are float32 (the export writes them with its file's write rule).

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "evaluator/admission.h"
#include "evaluator/diagnostics.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/resources.h"
#include "evaluator/templates.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::exporter {

struct Coverage;

/// The documented virtual maps, in documentation order.
enum class VirtualMap : uint8_t {
    Normal_OpenGL, Normal_DirectX, AO_Mixed, Diffuse, Specular, Glossiness, Unity4Diff, Unity4Gloss,
    reflection, OneOverIor, Glossiness2, f0, View_2D,
};
inline constexpr size_t kVirtualMapCount = 13;

/// The documented name (`1/ior` for OneOverIor).
[[nodiscard]] std::string_view VirtualMapName(VirtualMap map);
/// The map a documented name names (exact, case-sensitive); nullopt otherwise.
[[nodiscard]] std::optional<VirtualMap> ParseVirtualMap(std::string_view name);
/// Every documented name, in documentation order.
[[nodiscard]] std::vector<std::string> VirtualMapNames();

/// Whether this build computes a virtual map, with its evidence or its owner.
struct VirtualMapSupport {
    bool supported = false;
    /// Components of the map's values: 3 (normals, colours) or 1.
    uint32_t components = 1;
    /// supported: the Tier 0 goldens it equals; release gap: the task that owns it.
    std::string evidenceOrOwner;
};
[[nodiscard]] VirtualMapSupport Support(VirtualMap map);

/// Why `AO_Mixed` of `stack` in `set` is outside the scope it is computed in (above), or nullopt
/// when inside it, before any image is read (the images and the coverage are checked at
/// evaluation).
[[nodiscard]] std::optional<std::string> AoMixedRefusal(const core::Project& project, const core::TextureSet& set,
                                                        const core::Stack& stack);

/// What a virtual-map or mesh-map evaluation reads.
struct VirtualMapRequest {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    std::string templateId{evaluator::kDefaultTemplateId};
    /// The bytes of bitmap sources and mesh maps.
    std::shared_ptr<const evaluator::IResourceProvider> resources;
    std::shared_ptr<const evaluator::IGeometryMaskProvider> geometry;
    /// The diagnostic measure export only (write.h, decision 308), never production: the UV
    /// coverage (with its triangles) over which `Normal_OpenGL` and `Normal_DirectX` are computed
    /// and padded as Painter computes them (below). Null: the whole-tile evaluation.
    const Coverage* islandNormal = nullptr;
    std::shared_ptr<const evaluator::IProceduralSourceProvider> procedurals{};
};

struct VirtualMapResult {
    evaluator::DiagnosticMap values;
    /// Normal_OpenGL, Normal_DirectX and the normal_base pass-through: the EXP-09 tag.
    std::optional<evaluator::NormalTag> tag;
    /// `islandNormal` on incomplete coverage: the uncovered texels hold the map's own padding,
    /// which the export's padding must not replace.
    bool padded = false;
    /// The texels of it whose form is not recorded (decision 276 items 4 (b) and (c)): every
    /// uncovered texel when a Normal mesh map is bound, else none.
    uint64_t undecided = 0;
};

/// Evaluates a supported virtual map of revision `revision` of `project` on `store` with `cache`.
/// Fails with `evaluator:unsupported_source` for a release-gap map and with the failures of the
/// evaluations it runs.
[[nodiscard]] render::Result<VirtualMapResult> EvaluateVirtualMapOn(const core::Project& project,
                                                                    std::int64_t revision, VirtualMap map,
                                                                    const VirtualMapRequest& request,
                                                                    const evaluator::TemplateLibrary& templates,
                                                                    evaluator::ITileStore& store,
                                                                    evaluator::TileCache& cache);

/// The components a pass-through mesh map other than `normal_base` exports: AO and Curvature 1,
/// Position 3; nullopt for the mesh maps no recording shows (decision 103).
[[nodiscard]] std::optional<uint32_t> PassThroughComponents(core::MeshMapUsage usage);

/// The AO, Curvature or Position mesh map bound to the request's texture set, passed through:
/// every code of its 8- or 16-bit image (grey for AO and Curvature, RGB for Position, at the set's
/// resolution) as its UNORM operand (recording R-090 P7, decision 103). Any other mesh map, image
/// layout or size fails with `evaluator:unsupported_source`.
[[nodiscard]] render::Result<VirtualMapResult> PassThroughMeshMap(const core::Project& project,
                                                                  core::MeshMapUsage usage,
                                                                  const VirtualMapRequest& request);

/// The meshMap pass-through of revision `revision`: `normal_base` (MeshMapUsage::Normal) is the
/// geometry-only normal in the project's convention (height_to_normal.h), tagged
/// `geometry_only`; AO, Curvature and Position are PassThroughMeshMap. Every other mesh map fails
/// with `evaluator:unsupported_source`.
[[nodiscard]] render::Result<VirtualMapResult> EvaluateMeshMapOn(const core::Project& project, std::int64_t revision,
                                                                 core::MeshMapUsage usage,
                                                                 const VirtualMapRequest& request,
                                                                 const evaluator::TemplateLibrary& templates,
                                                                 evaluator::ITileStore& store,
                                                                 evaluator::TileCache& cache);

}  // namespace uzp::exporter
