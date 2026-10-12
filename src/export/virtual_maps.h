#pragma once

// The export's virtual maps (docs/architecture/08-export.md §2; task
// phase1.15_export-plan-compiler, decisions 086 and 092; parity/semantics/virtual-maps.json). The names
// are the documented `virtualMap` `srcMapName`s (Painter's public Python API documentation,
// export.html); their meaning is Adobe's public output-template documentation ("Output
// templates": converted maps), their operators are fitted on Tier 0 goldens.
//
// - `Normal_OpenGL`, `Normal_DirectX`: the combined normal of phase1.12 (mesh normal, Normal
//   channel and the height-derived normal, `evaluator/height_to_normal.h`), tagged `combined`.
// - The geometry-only pass-through is the meshMap `normal_base` (the bound Normal mesh map,
//   green inverted across conventions), tagged `geometry_only` (EXP-09).
// - `AO_Mixed`: the best model of the opacity sweep (the AO mesh map times the AO channel before
//   its L16 write, written at 8 bits) misses r1 at 31 values, each a few ulps from a 2^-12
//   boundary: Painter's operand conversions or arithmetic there are not identified (decision
//   092, recording R-092).
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

/// What a virtual-map or mesh-map evaluation reads.
struct VirtualMapRequest {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    std::string templateId{evaluator::kDefaultTemplateId};
    /// The bytes of bitmap sources and mesh maps.
    std::shared_ptr<const evaluator::IResourceProvider> resources;
    std::shared_ptr<const evaluator::IGeometryMaskProvider> geometry;
};

struct VirtualMapResult {
    evaluator::DiagnosticMap values;
    /// Normal_OpenGL, Normal_DirectX and the normal_base pass-through: the EXP-09 tag.
    std::optional<evaluator::NormalTag> tag;
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

/// The meshMap pass-through of revision `revision`: `normal_base` (MeshMapUsage::Normal) is the
/// geometry-only normal in the project's convention (height_to_normal.h), tagged
/// `geometry_only`. Every other mesh map fails with `evaluator:unsupported_source` (its native
/// precision export belongs to phase1.16_export-processing-encoders).
[[nodiscard]] render::Result<VirtualMapResult> EvaluateMeshMapOn(const core::Project& project, std::int64_t revision,
                                                                 core::MeshMapUsage usage,
                                                                 const VirtualMapRequest& request,
                                                                 const evaluator::TemplateLibrary& templates,
                                                                 evaluator::ITileStore& store,
                                                                 evaluator::TileCache& cache);

}  // namespace uzp::exporter
