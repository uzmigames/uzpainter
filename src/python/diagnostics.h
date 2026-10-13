#pragma once

// The diagnostic views of the open project (task phase2.1_recipe-diagnostic-views, decision 136),
// shared by `uzpainter.diagnostics` (bind_diagnostics.cpp) and the worker's Diagnostics tools
// (src/supervisor/worker.cpp).
//
// - A `DiagnosticRun` reads the committed revision of the open project once (inside an open native
//   `Transaction` it refuses, as the export does) and evaluates every diagnostic of the call on the
//   revision's CPU evaluation (evaluation.h) with the inputs the export reads: the project's
//   template, its resources and the texturing mesh re-derived from its stored bytes; the tiles an
//   earlier export, capture or diagnostic of the revision computed serve it. Each view is computed
//   by the entry point the export's `diagnosticMap` sources use (`src/evaluator/diagnostics.h`,
//   decisions 075, 076, 111), so a view equals the export of its source. The export of a run that
//   computed a material's views writes that mask and those views without computing them again
//   (one computation per view, B19).
// - The node of a call names its stack: uids are unique in a project.
// - Decision 126 applies per source (`exporter::RequireIdentifiedBase`): `isolate`, `contribution`
//   and `region_stats` on a channel whose template base is inferred raise `NotYetSupported`;
//   `material_views` moves each such channel view to `refused` and returns the others.
// - Decision 245 applies per source too (`exporter::IslandNormalRefusal`): `isolate`,
//   `contribution` and `region_stats` of Normal_OpenGL or Normal_DirectX on a texture set whose
//   UV islands do not cover the tile raise `NotYetSupported` before evaluating, as the export of
//   their source is refused: the island-edge texels read Painter's Height outside the islands.
// - `Export` publishes diagnostic sources as an ordinary export generation (OpenEXR 32f, padding
//   `passthrough`, so every value is the source's float32 value), with its plan and receipt.
//
// Failures raise `ApiError` with the classes of the Python API: `ValueError` for a node that is in
// no stack or an invalid configuration, `NotYetSupported` for a refusal, the evaluator's classes
// (decision 082) for an evaluation failure.

#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "evaluator/diagnostics.h"
#include "evaluator/evaluator.h"
#include "export/plan.h"
#include "export/publish.h"
#include "python/evaluation.h"
#include "python/session.h"
#include "uzp_core/document/document.h"

namespace uzp::python {

/// The material views of a material with the views decision 126 refuses taken out, shared with the
/// run that computed them.
struct DiagnosticMaterialViews {
    std::shared_ptr<const evaluator::MaterialViews> views;
    /// View name -> the refusal's reason.
    std::map<std::string, std::string> refused;
};

class DiagnosticRun {
public:
    /// The committed revision of the open project. `ProjectError` without one, `RuntimeError`
    /// inside an open native Transaction.
    DiagnosticRun();

    [[nodiscard]] const core::Snapshot& snapshot() const { return m_snapshot; }

    [[nodiscard]] evaluator::IsolationResult Isolate(core::Id node, const evaluator::DiagnosticMapId& map);
    [[nodiscard]] evaluator::ContributionResult Contribution(core::Id node, const evaluator::DiagnosticMapId& map);
    [[nodiscard]] DiagnosticMaterialViews MaterialViews(core::Id material);
    /// The statistics of `map` inside the region of `material` (the source `regionStats/<map>/<material>`).
    [[nodiscard]] evaluator::RegionStats RegionStats(const evaluator::DiagnosticMapId& map, core::Id material);

    /// Publishes `sources` (every one naming `node`) as one export generation under `exportPath`,
    /// one file `$textureSet_<kind>_<map or view>_<uid>.exr` per source, in order. The mask and the
    /// views `MaterialViews` computed are written as computed, not computed again.
    [[nodiscard]] exporter::Publication Export(core::Id node, const std::vector<evaluator::DiagnosticSource>& sources,
                                               const std::filesystem::path& exportPath);

private:
    /// The request of the stack holding `node`; `ValueError` when no stack holds it.
    [[nodiscard]] evaluator::DiagnosticRequest RequestFor(core::Id node) const;
    /// Raises the refusal of decision 126 or 245 for `source` of the stack of `request`, if any.
    void RequireExact(const evaluator::DiagnosticRequest& request, const evaluator::DiagnosticSource& source) const;

    std::shared_ptr<OpenProject> m_open;
    core::Snapshot m_snapshot;
    EvaluationLease m_evaluation;
    /// The views the last `MaterialViews` computed (null before), which `Export` reads.
    std::shared_ptr<const evaluator::MaterialViews> m_views;
};

}  // namespace uzp::python
