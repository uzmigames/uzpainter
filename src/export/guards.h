#pragma once

// The export's static refusals as pure checks, and the dry run's preflight over them (decision
// 091, amended for SUP-035).
//
// Each guard returns the `core::NotYetSupported` message the export throws for a planned file, or
// nothing when it admits the file; it reads only the project, the plan and the texture set's UV
// coverage, never an image. The export's throwing checks are these guards: `CheckProcessing`
// (encode.h), `CheckIslandNormal` and `CheckPadding` (padding.h) throw their message, so the
// export and the preflight cannot give different reasons.
//
// The preflight (`PreflightExport`) runs them over a compiled plan in the order of
// `EncodeExport`'s step 1 (write.h): the processing, then, for a file that needs the coverage, a
// combined virtual normal on UV islands (decision 245; a file written under EXC-014, decision 417,
// still refused when its Height has no layer) and the padding (padding.h; `infinite` is admitted
// under EXC-013, decision 414). Per file:
// - `blocked`: a guard refuses it, with the export's exact reason;
// - `needs_evaluation`: the file needs its texture set's UV coverage and none is available, so the
//   island and padding checks did not run;
// - `no_known_blocker`: every static check admits it. That is no export guarantee: what the
//   evaluation decides (a bitmap the texture unit refuses, an unidentified base) is not checked.
// The whole preflight is `blocked` when any file is: the export is all or nothing, so one refusal
// refuses every file of the plan.

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "export/padding.h"
#include "export/plan.h"
#include "uzp_core/manifest/json.h"

namespace uzp::exporter {

/// The owner of the exact padding and Normal on UV-islanded sets (decisions 103, 245, 259, 396
/// and 414).
inline constexpr std::string_view kIslandsOwner = "owner phase4.1_export-island-padding-exact";

/// The refusal of the processing `file` (planned on `project`) asks for outside the recorded
/// domain (encode.h); none for a statistics file. Throws std::invalid_argument when the file's
/// texture set is not in `project`.
[[nodiscard]] std::optional<std::string> ProcessingRefusal(const core::Project& project, const PlannedFile& file);

/// The refusal of a combined virtual normal in `file` over `coverage` with uncovered texels,
/// whatever the padding, a statistics file included (padding.h, decision 245); none for a file
/// production writes under EXC-014 (padding.h `IslandNormalLifted`, decision 417).
[[nodiscard]] std::optional<std::string> IslandNormalFileRefusal(const PlannedFile& file, const Coverage& coverage);

/// Decision 245 §2, kept by decision 417: the refusal of a file written under EXC-014
/// (`IslandNormalLifted`) whose stack has no Height channel or no layer contributing to it (its
/// Height DAG of `templateId` in `templates` has no root layer), with its owner. None when the
/// Height has a layer, and none when its DAG does not build (the evaluation fails then).
[[nodiscard]] std::optional<std::string> IslandNormalHeightRefusal(const core::Project& project,
                                                                   const PlannedFile& file,
                                                                   const evaluator::TemplateLibrary& templates,
                                                                   std::string_view templateId);

/// The refusal of `file`'s padding over `coverage` when it is not fitted (padding.h); none for a
/// statistics file, nor for `infinite`, written under EXC-013 (decision 414). Throws
/// std::invalid_argument when the coverage does not have the file's size.
[[nodiscard]] std::optional<std::string> PaddingRefusal(const PlannedFile& file, const Coverage& coverage);

enum class PreflightStatus : uint8_t { blocked, needs_evaluation, no_known_blocker };
[[nodiscard]] std::string_view PreflightStatusName(PreflightStatus status);

/// One planned file's preflight (above).
struct FilePreflight {
    std::string rootPath;
    std::string fileName;
    std::string relativePath;
    PreflightStatus status = PreflightStatus::no_known_blocker;
    /// `blocked`: the export's NotYetSupported message; `needs_evaluation`: why the coverage is not
    /// available; empty otherwise.
    std::string reason;
};

struct ExportPreflight {
    PreflightStatus status = PreflightStatus::no_known_blocker;
    /// In plan order.
    std::vector<FilePreflight> files;
};

/// Why the preflight has no UV coverage (`SourceInputs::geometry` null).
struct CoverageGap {
    /// True: the project has no texturing mesh, so it has no UV islands, as the export reads a null
    /// geometry (a statistics file then needs no coverage). False: a texturing mesh exists and its
    /// coverage could not be obtained, so the island checks are unknown, a statistics file of a
    /// combined virtual normal included.
    bool meshAbsent = false;
    /// Why there is no coverage: the reason of a `needs_evaluation`.
    std::string reason;
};

/// The preflight's coverage source for a project.
struct PreflightCoverage {
    /// Only `geometry` and `templateId` (the project's) are set: the masks of the revision's
/// texturing mesh, or null.
    SourceInputs inputs;
    /// Why `inputs.geometry` is null, when it is.
    CoverageGap gap;
};

/// The texturing mesh of `project` re-derived from its stored bytes (`read` returns the bytes of a
/// stored resource; mesh/reload.h `RederiveMesh`) into objects of this call alone: no image read,
/// no evaluation. Without a mesh, `gap.meshAbsent`; a mesh that does not re-derive is a gap with
/// its error, never taken for an absent mesh.
[[nodiscard]] PreflightCoverage CoverageForPreflight(const core::Project& project,
                                                     const std::function<std::string(const std::string&)>& read);

/// The preflight of `plan`, compiled from `project` (above). The coverage is `inputs.geometry`'s
/// (`CoverageOf`); without it a file that needs it is `needs_evaluation`, `gap.reason` saying why.
/// A statistics file needs the coverage only when it reads a combined virtual normal, and then not
/// when `gap.meshAbsent`. Reads nothing else of `inputs` but `templateId`, whose base values
/// `templates` holds for the Height DAG of `IslandNormalHeightRefusal`: no image is decoded and no
/// tile is evaluated.
[[nodiscard]] ExportPreflight PreflightExport(const core::Project& project, const ExportPlan& plan,
                                              const SourceInputs& inputs, const CoverageGap& gap,
                                              const evaluator::TemplateLibrary& templates);

/// `{status, note, files: [{root_path, map, relative_path, status, type?, reason?, references?}]}`:
/// a blocked file's `type` is `NotYetSupported` and its `references` the tasks, recordings and
/// decisions its reason names, in order.
[[nodiscard]] core::json::Object PreflightJson(const ExportPreflight& preflight);

}  // namespace uzp::exporter
