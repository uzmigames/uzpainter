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
// combined virtual normal on UV islands (decision 245) and the padding (decision 259). Per file:
// - `blocked`: a guard refuses it, with the export's exact reason;
// - `needs_evaluation`: the file needs its texture set's UV coverage and none is available, so the
//   island and padding checks did not run;
// - `no_known_blocker`: every static check admits it. That is no export guarantee: what the
//   evaluation decides (a bitmap the texture unit refuses, an unidentified base) is not checked.
// The whole preflight is `blocked` when any file is: the export is all or nothing, so one refusal
// refuses every file of the plan.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "export/padding.h"
#include "export/plan.h"
#include "uzp_core/manifest/json.h"

namespace uzp::exporter {

/// The owner of padding on UV-islanded sets (decisions 103, 245 and 259).
inline constexpr std::string_view kIslandsOwner = "owner phase1.25_pilot-wand item 2.7";

/// The refusal of the processing `file` (planned on `project`) asks for outside the recorded
/// domain (encode.h); none for a statistics file. Throws std::invalid_argument when the file's
/// texture set is not in `project`.
[[nodiscard]] std::optional<std::string> ProcessingRefusal(const core::Project& project, const PlannedFile& file);

/// The refusal of a combined virtual normal in `file` over `coverage` with uncovered texels,
/// whatever the padding, a statistics file included (padding.h, decision 245).
[[nodiscard]] std::optional<std::string> IslandNormalFileRefusal(const PlannedFile& file, const Coverage& coverage);

/// The refusal of `file`'s padding over `coverage` when it is not fitted (padding.h, decision
/// 259); none for a statistics file. Throws std::invalid_argument when the coverage does not have
/// the file's size.
[[nodiscard]] std::optional<std::string> PaddingRefusal(const PlannedFile& file, const Coverage& coverage,
                                                        InexactPadding inexact = InexactPadding::refuse);

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

/// The preflight of `plan`, compiled from `project` (above). The coverage is `inputs.geometry`'s
/// (`CoverageOf`); without it a file that needs it is `needs_evaluation`, `unavailable` saying why.
/// Reads nothing else of `inputs`: no image is decoded and no tile is evaluated.
[[nodiscard]] ExportPreflight PreflightExport(const core::Project& project, const ExportPlan& plan,
                                              const SourceInputs& inputs, std::string_view unavailable);

/// `{status, note, files: [{root_path, map, relative_path, status, type?, reason?, references?}]}`:
/// a blocked file's `type` is `NotYetSupported` and its `references` the tasks, recordings and
/// decisions its reason names, in order.
[[nodiscard]] core::json::Object PreflightJson(const ExportPreflight& preflight);

}  // namespace uzp::exporter
