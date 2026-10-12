#pragma once

// Writing a plan's files (docs/architecture/08-export.md §3, §5; task
// phase1.16_export-processing-encoders, decisions 089 and 090): every planned file evaluated,
// padded, encoded and written under the plan's exportPath at its relativePath. Generations, the
// delivery pointer and receipts are phase1.17_export-publication-receipts, which builds on this.
//
// Order, so that a refusal or a failure leaves nothing written:
// 1. every file's processing is checked (CheckProcessing: NotYetSupported for an unrecorded one);
// 2. every file is evaluated (EvaluateFileOn), padded over its texture set's coverage
//    (ApplyPadding) and encoded (EncodeFile) in memory;
// 3. only then are the files written, in plan order, sub-folders created as needed.
//
// The coverage comes from `inputs.geometry` (the texture set's material, every object); a
// configuration with an image file and no texturing mesh fails before anything is written. Same
// build, project and configuration give the same bytes (EXP-05).

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "export/plan.h"

namespace uzp::exporter {

/// A planned file's bytes, encoded in memory.
struct EncodedFile {
    std::string bytes;
    /// The EXP-09 tag of the file's normal source, when it has one.
    std::optional<evaluator::NormalTag> normalTag;
    /// The layout written: the plan's, or L / RGB when an all-opaque alpha was dropped (encode.h).
    FileLayout layout = FileLayout::L;
};

/// Steps 1 and 2 above: every file of `plan` (compiled from revision `revision` of `project`)
/// checked, then evaluated, padded and encoded in memory, in plan order. Throws
/// `core::NotYetSupported` (or `core::ValueError`) before anything is evaluated for an unrecorded
/// processing or padding; returns the evaluator's failure, or an `export:` failure (no texturing
/// mesh, a padding or encoder that fails). Writes nothing.
[[nodiscard]] render::Result<std::vector<EncodedFile>> EncodeExport(const core::Project& project, std::int64_t revision,
                                                                    const ExportPlan& plan, const SourceInputs& inputs,
                                                                    const evaluator::TemplateLibrary& templates,
                                                                    evaluator::ITileStore& store,
                                                                    evaluator::TileCache& cache);

struct WrittenFile {
    std::string rootPath;
    /// `/`-separated, relative to exportPath.
    std::string relativePath;
    std::string path;
    uint64_t size = 0;
    /// Lower-case hex SHA-256 of the bytes written.
    std::string sha256;
};

/// Writes every file of `plan` (compiled from revision `revision` of `project`). Throws
/// `core::NotYetSupported` before anything is evaluated for an unrecorded processing or padding;
/// returns the evaluator's failure, or an `export:` failure (no texturing mesh, a write that
/// fails), with nothing written except, for a write failure, the files before it.
[[nodiscard]] render::Result<std::vector<WrittenFile>> WriteExport(const core::Project& project, std::int64_t revision,
                                                                   const ExportPlan& plan, const SourceInputs& inputs,
                                                                   const evaluator::TemplateLibrary& templates,
                                                                   evaluator::ITileStore& store,
                                                                   evaluator::TileCache& cache);

}  // namespace uzp::exporter
