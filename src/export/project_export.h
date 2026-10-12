#pragma once

// The end-to-end export of a saved project (docs/architecture/08-export.md §1-§5; task
// phase1.18_export-engine, decision 104): a `.uzp` project file and a Painter-compatible
// `json_config`, published as a new generation under the configuration's exportPath.
//
// 1. The project file is opened through the project store (its lock taken, its current revision
//    read); a file whose integrity report finds corrupt content or a missing dependency is refused
//    before anything is planned.
// 2. The configuration is compiled against that revision (`CompilePlan`, with the file's path as
//    `$project`).
// 3. The evaluator runs on the CPU store with the templates installed beside the executable,
//    reading the project's resources from the file and the texturing mesh re-derived from its
//    stored bytes (`mesh::RederiveMesh`).
// 4. `PublishExport` encodes every file in memory, then publishes the files, the plan and the
//    receipt as a new generation by an atomic pointer update.
//
// A refusal (`core::ValueError`, `core::NotYetSupported`) is thrown before anything is written;
// an evaluation, encoding or publication failure is returned with the previous generation still
// selected. The same build, project file and configuration give the same files, plan and receipt
// except for the receipt's `moment` and the generation id (EXP-05, item 3.2).

#include <filesystem>
#include <string>

#include "export/publish.h"
#include "export/receipt.h"

namespace uzp::exporter {

struct ProjectExportRequest {
    std::filesystem::path project;
    /// The `json_config` text.
    std::string config;
    BuildIdentity identity;
    /// The evaluator's templates; empty: `TemplateLibrary::DefaultDirectory()`.
    std::filesystem::path templates;
};

/// Exports the current revision of `request.project` (see above). Throws `core::ValueError` and
/// `core::NotYetSupported` before anything is written, and `store::StoreError` when the project
/// file cannot be opened.
[[nodiscard]] render::Result<Publication> ExportProject(const ProjectExportRequest& request);

}  // namespace uzp::exporter
